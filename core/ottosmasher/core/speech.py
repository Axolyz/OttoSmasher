"""语音分析（规格 08 §8.1–§8.4、§8.8）：Core 侧——选范围、冻结输入、复用判断、提交任务、采纳结果、读取测量。

- **分析只挂在“声音资产 + 文本单元”上**（所有者 2026-10-08【基线变更，细化 D41】，见 ``core/units.py``）：字幕的一行，或用户给一段选区手输的台词。
  当前版本、历史版本、人工修正都属于这句，不属于任何采样；删采样、改扩展量重建，分析和修正都还在。采样只按两条规则读取覆盖它的句。
- 一个操作、统一复用规则：输入（对齐文本版本、辞典版本、前端版本、模型版本、目标区间、容差、输入音频身份）与这句的当前头完全相同 → 跳过；
  任何不同 → 重跑。确认框写清“将分析 M 句；N 句已是最新，跳过；K 条无法处理（原因）”。
- 入口：原片页 = 所选原片在默认人声轨（没有就是原混音）上的台词行（不需要先建采样），加上原片上语音采样自己的那一句；
  采样库 = 各采样所绑音轨上它读的句（有自己文本的读自己那一句，没有的读范围内的句）；详情 = 当前选区 + 手输文字（手输单元）。
- 音频 = 单元所在的资产（不触发分离、不换音源、不改绑）；窗口 = 目标两侧各扩展容差，只在同一物理声音（存放目标的那段存储）内扩展，记录请求与实际扩展量、是否被截短。
- 采纳（按顺序）：任务取消 → 不写（采纳函数不会被调用）；输入在任务期间变了 → 只进历史；当前头是人工版本或已被更新 → 只进历史；否则成为新的当前头。
  失败结果只进历史，旧的成功结果不会“消失”。
- 读取测量没有副作用。
时钟：测量里的音素时间都是资产局部秒；采样的 start/end 也是资产局部秒；标注（字幕行）的 start/end 是原片秒。
"""

from __future__ import annotations

import hashlib
import json
import shutil
import sqlite3
from collections.abc import Callable, Iterable
from pathlib import Path
from typing import Any

import math

from ..algo import speech as derive
from ..domain.mapping import Mapping
from ..domain.overlap import overlaps
from ..lang.ja import dictionary as dict_mod
from ..lang.ja import frontend as fe_mod
from ..lang.ja import openjtalk as oj_mod
from ..models import domino, f0store, fcpe, registry
from ..store.db import transaction
from ..store.workspace import Workspace
from . import assets as assets_mod
from . import settings as settings_mod
from . import units
from .clock import new_id, now_iso
from .edits import ChangeSet, dumps, loads
from .probes import record_probes
from .errors import CoreError

KIND = "alignment"
JOB_KIND = "speech.analyze"
BLOCKED_LIST_MAX = 50
OWNER = units.OWNER


def _sha(obj: Any) -> str:
    return hashlib.sha256(json.dumps(obj, sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode("utf-8")).hexdigest()


def _txt(text: str, source: str, equals: bool = False) -> dict[str, Any]:
    return {"text": text, "source": source, "version": hashlib.sha256(text.encode("utf-8")).hexdigest()[:16], "equalsSubtitle": equals}


class SpeechService:
    def __init__(self, conn: sqlite3.Connection, ws: Workspace, jobs: Any, support_dir: Path, on_change: Callable[[ChangeSet], None] | None = None) -> None:
        self.conn = conn
        self.ws = ws
        self.jobs = jobs
        self.support_dir = support_dir
        self.on_change = on_change
        jobs.adopters[JOB_KIND] = self._adopt

    # ------------------------------------------------------------ 文本单元（所有者 2026-10-08；对齐文本的选择 08 §8.2.1）

    def _pads(self) -> tuple[float, float]:
        v = settings_mod.values(self.conn)
        return float(v["subtitle.pad_before"]), float(v["subtitle.pad_after"])

    def _asset(self, asset_id: str, memo: dict[str, Any] | None) -> dict[str, Any]:
        key = ("asset", asset_id)
        if memo is not None and key in memo:
            return memo[key]
        a = assets_mod.get(self.conn, asset_id)
        if memo is not None:
            memo[key] = a
        return a

    def line_unit(self, ann_id: str, asset_id: str, pads: tuple[float, float] | None = None, memo: dict[str, Any] | None = None) -> dict[str, Any]:
        """字幕行在资产上的单元：目标 = 字幕区间 ± 字幕采样扩展量（裁到资产覆盖范围）；文本 = 行的对齐文本（人工 > 自动）。
        处理不了抛 speech-blocked（no-text / out-of-track）。"""
        ann = self.conn.execute('SELECT id, start, "end", clean_text, align_text_auto, align_text_manual FROM annotation WHERE id=?', (ann_id,)).fetchone()
        lt = units.line_text(ann) if ann is not None else None
        if lt is None:
            raise CoreError("speech-blocked", reason="no-text")
        asset = self._asset(asset_id, memo)
        tgt = units.line_target(float(ann["start"]), float(ann["end"]), asset["mapping"], float(asset["duration"]), pads or self._pads())
        if tgt is None:
            raise CoreError("speech-blocked", reason="out-of-track")
        auto = (ann["align_text_auto"] or "").strip()
        return {
            "unitId": units.line_id(ann_id, asset_id), "kind": units.LINE, "annotation": ann_id, "asset": asset_id, "target": tgt,
            "name": (ann["clean_text"] or "").strip() or lt[0], "txt": _txt(lt[0], lt[1], bool(auto) and lt[0] == auto),
        }

    def typed_unit(self, asset_id: str, start: float, end: float, text: str, name: str | None = None, source: str = "selection") -> dict[str, Any]:
        """手输单元：目标 = 输入时的那段选区；同一资产同一选区是同一句。"""
        text = text.strip()
        if not text:
            raise CoreError("speech-blocked", reason="no-text")
        return {
            "unitId": units.typed_owner(self.conn, asset_id, start, end), "kind": units.TYPED, "annotation": None, "asset": asset_id,
            "target": (start, end), "name": name or text, "txt": _txt(text, source),
        }

    def unit_by_id(self, unit_id: str, pads: tuple[float, float] | None = None, memo: dict[str, Any] | None = None) -> dict[str, Any]:
        """按编号还原单元（结果表里再发起）：字幕行按当前的行与设置；手输单元按最近一次分析的选区与文本。"""
        if units.kind_of(unit_id) == units.LINE:
            ann, asset = units.parse_line(unit_id)
            if self.conn.execute("SELECT 1 FROM sound_asset WHERE id=?", (asset,)).fetchone() is None:
                raise CoreError("speech-blocked", reason="no-text")
            return self.line_unit(ann, asset, pads, memo)
        r = self.conn.execute(
            "SELECT asset_id, range_start, range_end, inputs FROM measure_run WHERE owner_type=? AND owner_id=? AND kind=? ORDER BY created_at DESC, rowid DESC LIMIT 1",
            (OWNER, unit_id, KIND),
        ).fetchone()
        if r is None or self.conn.execute("SELECT 1 FROM sound_asset WHERE id=?", (r["asset_id"],)).fetchone() is None:
            raise CoreError("speech-blocked", reason="no-text")
        inp = loads(r["inputs"])
        u = self.typed_unit(r["asset_id"], float(r["range_start"]), float(r["range_end"]), inp.get("text") or "", inp.get("name"), inp.get("textSource") or "selection")
        return u | {"unitId": unit_id}

    def own_unit(self, s: sqlite3.Row, memo: dict[str, Any] | None = None) -> dict[str, Any] | None:
        """采样自己的那一句（有自己文本的采样只读它）：手输过台词 → 手输单元（采样选区）；字幕采样 → 这一行在所绑资产上的单元。
        字幕行处理不了（没有对齐文本、不在资产范围里）时单元仍是这一行，``txt`` 为 None、带 ``reason``。没有自己的文本 → None。"""
        manual = (s["align_text_manual"] or "").strip()
        if manual:
            return self.typed_unit(s["asset_id"], float(s["start"]), float(s["end"]), manual, s["name"], "sample-manual")
        origin = loads(s["origin"]) if s["origin"] else None
        if origin and origin.get("kind") == "subtitle" and origin.get("annotation"):
            try:
                return self.line_unit(origin["annotation"], s["asset_id"], None, memo)
            except CoreError as e:
                return {
                    "unitId": units.line_id(origin["annotation"], s["asset_id"]), "kind": units.LINE, "annotation": origin["annotation"],
                    "asset": s["asset_id"], "target": None, "name": s["name"], "txt": None, "reason": e.args_.get("reason") or e.code,
                }
        return None

    def text_of(self, s: sqlite3.Row) -> dict[str, Any]:
        """采样自己那一句的对齐文本：手输台词 > 字幕行的对齐文本（人工 > 自动）。没有自己的文本 → reason。"""
        own = self.own_unit(s)
        if own is None or own["txt"] is None:
            return {"text": None, "reason": (own or {}).get("reason") or "no-text"}
        t = own["txt"]
        return {"text": t["text"], "source": t["source"], "version": t["version"], "equalsSubtitle": t["equalsSubtitle"]}

    def candidates(self, s: sqlite3.Row, memo: dict[str, Any] | None = None) -> list[dict[str, Any]]:
        """没有自己文本的采样读到（也是从采样入口分析它时要分析）的句：与采样范围（换算成原片秒）正长度交叠的台词行
        （当前字幕版本或用户加的、未删、有对齐文本）在所绑资产上的单元，加上这个资产上与范围交叠的手输单元（文本取最近一次分析用的）。"""
        asset = self._asset(s["asset_id"], memo)
        start, end = float(s["start"]), float(s["end"])
        out: dict[str, dict[str, Any]] = {}
        try:
            m = Mapping.of(asset["mapping"])
            a, b = m.to_source(start), m.to_source(end)
        except CoreError:
            a = b = None
        if a is not None and b is not None:
            sub = self.conn.execute("SELECT current_subtitle_version_id FROM source WHERE id=?", (asset["source_id"],)).fetchone()
            pads = self._pads()
            for r in self.conn.execute(
                "SELECT id FROM annotation WHERE source_id=? AND kind='line' AND deleted=0 AND (subtitle_version_id IS NULL OR subtitle_version_id IS ?)"
                ' AND "end" > ? AND start < ? ORDER BY start, rowid',
                (asset["source_id"], sub[0] if sub else None, min(a, b), max(a, b)),
            ):
                try:
                    u = self.line_unit(r["id"], s["asset_id"], pads, memo)
                except CoreError:
                    continue
                out[u["unitId"]] = u
        for r in self.conn.execute(
            "SELECT owner_id, range_start, range_end, inputs FROM measure_run WHERE owner_type=? AND kind=? AND owner_id LIKE 'typed:%' AND asset_id=?"
            " AND range_end > ? AND range_start < ? ORDER BY created_at DESC, rowid DESC",
            (OWNER, KIND, s["asset_id"], start, end),
        ):
            if r["owner_id"] in out:
                continue
            inp = loads(r["inputs"])
            if (inp.get("text") or "").strip():
                out[r["owner_id"]] = self.typed_unit(s["asset_id"], float(r["range_start"]), float(r["range_end"]), inp["text"], inp.get("name"),
                                                     inp.get("textSource") or "selection") | {"unitId": r["owner_id"]}
        return sorted(out.values(), key=lambda u: (u["target"][0], u["target"][1]))

    # ------------------------------------------------------------ 冻结输入

    def _versions(self) -> dict[str, Any]:
        values = settings_mod.values(self.conn)
        d = values["frontend.user_dictionary"]
        _, sha = registry.locate(domino.MODEL_ID, domino.MODEL_FILE, self.ws.models, self.support_dir)
        return {
            "language": "ja",
            "dictionary": dict_mod.version_of(d["compiled"]),
            "dictionaryPath": str(self.ws.dictionary / d["compiled"]) if d["compiled"] else None,
            "frontend": f"{fe_mod.FRONTEND_VERSION}+{oj_mod.TSQYOMI_VERSION}+pyopenjtalk-plus {oj_mod.PYOPENJTALK_VERSION}",
            "model": {"id": domino.MODEL_ID, "sha256": sha, "decoder": domino.DECODER_VERSION},
            "tolerance": [float(values["analysis.tolerance_before"]), float(values["analysis.tolerance_after"])],
        }

    def _locate(self, asset_id: str, start: float, end: float, memo: dict[str, Any] | None) -> tuple[dict[str, Any], Any, Any, dict[str, Any]]:
        """资产与存放 [start, end) 的文件窗口；同一次计划里按资产记住（分离资产的定位要探测文件，几百条采样不能每条都探测）。"""
        hit = memo.get(asset_id) if memo is not None else None
        if hit is not None and hit[2].covers(start, end):
            return hit
        asset = assets_mod.get(self.conn, asset_id)
        ref, win, media = assets_mod.locate(self.conn, self.ws.root, asset, start, end)
        assets_mod.check_media(media)  # 文件缺失或被改动 → 明确报错（进 K），不回退别的轨
        out = (asset, ref, win, media)
        if memo is not None:
            memo[asset_id] = out
        return out


    def _build(
        self, owner_type: str, owner: str, name: str, asset_id: str, start: float, end: float, txt: dict[str, Any], ver: dict[str, Any], memo: dict[str, Any] | None
    ) -> dict[str, Any]:
        asset, ref, win, media = self._locate(asset_id, start, end, memo)
        snap = media["snapshot"] or {}
        before, after = ver["tolerance"]
        lo = max(0.0, win.local_start)
        hi = min(float(asset["duration"]), win.local_end)
        ws_, we_ = max(lo, start - before), min(hi, end + after)
        sr = ref.sample_rate
        a, b = round(win.to_file(ws_) * sr), round(win.to_file(we_) * sr)
        w0, w1 = win.to_local(a / sr), win.to_local(b / sr)
        audio = {
            "asset": asset["id"],
            "mapping": asset["mapping"],
            "media": media["media_file_id"],
            "snapshot": {k: snap.get(k) for k in ("size", "mtime_ns")},
            "ordinal": ref.ordinal,
            "storage": [win.local_start, win.local_end, win.file_start],
        }
        fp_inputs = {
            "language": ver["language"], "text": txt["version"], "dictionary": ver["dictionary"], "frontend": ver["frontend"],
            "model": ver["model"], "target": [round(start, 6), round(end, 6)], "tolerance": ver["tolerance"], "audio": audio,
        }
        return {
            "ownerType": owner_type, "owner": owner, "sample": owner if owner_type == "sample" else None, "asset": asset["id"], "name": name,
            "text": txt["text"], "textSource": txt["source"], "textVersion": txt["version"], "equalsSubtitle": txt["equalsSubtitle"],
            "target": [start, end], "window": [w0, w1], "requested": ver["tolerance"], "actual": [round(start - w0, 6), round(w1 - end, 6)],
            "truncated": [start - before < lo - 1e-9, end + after > hi + 1e-9],
            "file": {"path": ref.path, "ordinal": ref.ordinal, "sample_rate": ref.sample_rate, "channels": ref.channels, "codec": ref.codec, "format": ref.format_name},
            "frames": [a, b], "audio": audio, "fingerprint": _sha(fp_inputs),
        }


    # ------------------------------------------------------------ 范围与计划（08 §8.4）

    _SAMPLE_COLS = 'id, asset_id, start, "end", name, nature, align_text_manual, origin, text_snapshot, parent_sample_id'

    def _samples(self, ids: Iterable[str]) -> list[sqlite3.Row]:
        ids = list(dict.fromkeys(ids))
        out = []
        for i in range(0, len(ids), 500):
            chunk = ids[i : i + 500]
            rows = {r["id"]: r for r in self.conn.execute(f"SELECT {self._SAMPLE_COLS} FROM sample WHERE id IN ({','.join('?' * len(chunk))})", chunk)}
            out += [rows[x] for x in chunk if x in rows]
        return out

    def _source_units(self, source_ids: Iterable[str], pads: tuple[float, float], memo: dict[str, Any]) -> dict[str, dict[str, Any]]:
        """原片入口的默认范围：所选原片中、字幕区间不与已确认 OP/ED 正长度交叠、有对齐文本的台词行在默认人声轨（没有就是原混音）上的单元；
        再加上原片上性质为语音的采样自己的那一句（绑在别的音轨上的字幕采样、手输过台词的采样），同样不在 OP/ED 里。"""
        out: dict[str, dict[str, Any]] = {}
        for sid in dict.fromkeys(source_ids):
            opeds = [(r[0], r[1]) for r in self.conn.execute('SELECT start, "end" FROM oped WHERE source_id=? AND deleted=0', (sid,))]
            track = units.analysis_track(self.conn, sid)
            if track is not None:
                sub = self.conn.execute("SELECT current_subtitle_version_id FROM source WHERE id=?", (sid,)).fetchone()
                for r in self.conn.execute(
                    'SELECT id, start, "end" FROM annotation WHERE source_id=? AND kind=\'line\' AND deleted=0'
                    " AND (subtitle_version_id IS NULL OR subtitle_version_id IS ?) ORDER BY start, rowid",
                    (sid, sub[0] if sub else None),
                ):
                    if any(overlaps(r["start"], r["end"], a, b) for a, b in opeds):
                        continue
                    try:
                        u = self.line_unit(r["id"], track, pads, memo)
                    except CoreError:
                        continue  # 没有对齐文本、不在音轨范围里：不在原片入口的范围里
                    out.setdefault(u["unitId"], u)
            rows = self.conn.execute(
                f"SELECT {', '.join('s.' + c.strip() for c in self._SAMPLE_COLS.split(','))}, a.mapping FROM sample s JOIN sound_asset a ON a.id=s.asset_id"
                " WHERE a.source_id=? AND s.nature='speech' ORDER BY s.start, s.rowid",
                (sid,),
            )
            for r in rows:
                own = self.own_unit(r, memo)
                if own is None or own["txt"] is None or own["unitId"] in out:
                    continue
                if own["kind"] == units.LINE:
                    a = self.conn.execute('SELECT start, "end" FROM annotation WHERE id=?', (own["annotation"],)).fetchone()
                    span = (a[0], a[1])
                else:
                    try:
                        m = Mapping.of(loads(r["mapping"]))
                        span = (m.to_source(float(r["start"])), m.to_source(float(r["end"])))
                    except CoreError:
                        continue
                if any(overlaps(span[0], span[1], a, b) for a, b in opeds):
                    continue
                out[own["unitId"]] = own
        return out

    def plan(self, entry: str, ids: list[str], rerun_fresh: bool) -> dict[str, Any]:
        if entry not in ("source", "samples", "units"):
            raise CoreError("speech-invalid", reason="not-an-option", field="entry")
        ver = self._versions()
        memo: dict[str, Any] = {}
        pads = self._pads()
        specs: dict[str, dict[str, Any]] = {}
        blocked: list[dict[str, Any]] = []
        if entry == "source":
            specs = self._source_units(ids, pads, memo)
        elif entry == "samples":
            for s in self._samples(ids):
                own = self.own_unit(s, memo)
                if own is not None:
                    if own["txt"] is None:
                        blocked.append({"id": s["id"], "name": s["name"], "reason": own.get("reason") or "no-text"})
                    else:
                        specs.setdefault(own["unitId"], own)
                    continue
                found = self.candidates(s, memo)
                if not found:
                    blocked.append({"id": s["id"], "name": s["name"], "reason": "no-text"})
                for u in found:
                    specs.setdefault(u["unitId"], u)
        else:
            for uid in dict.fromkeys(ids):
                try:
                    specs[uid] = self.unit_by_id(uid, pads, memo)
                except CoreError as e:
                    blocked.append({"id": uid, "name": uid, "reason": e.args_.get("reason") or e.code})
        run: list[dict[str, Any]] = []
        fresh: list[dict[str, Any]] = []
        mix = 0
        for u in specs.values():
            try:
                it = self._build(OWNER, u["unitId"], u["name"], u["asset"], u["target"][0], u["target"][1], u["txt"], ver, memo)
            except CoreError as e:
                blocked.append({"id": u["unitId"], "name": u["name"], "reason": e.args_.get("reason") if e.code == "speech-blocked" else e.code})
                continue
            it |= {"unitKind": u["kind"], "annotation": u.get("annotation")}
            asset = self._asset(u["asset"], memo)
            if asset["origin"] == "stream" or not asset["roles"]:
                mix += 1
            head = self._head_row(u["unitId"])
            it["baseHead"] = head["run_id"] if head else None
            is_fresh = head is not None and head["status"] == "ok" and loads(head["inputs"]).get("fingerprint") == it["fingerprint"]
            if is_fresh and not rerun_fresh:
                fresh.append(it)
            else:
                run.append(it | {"wasFresh": True} if is_fresh else it)
        return {"run": run, "fresh": fresh, "blocked": blocked, "mix": mix, "versions": ver}

    def preview(self, entry: str, ids: list[str], rerun_fresh: bool) -> dict[str, Any]:
        p = self.plan(entry, ids, rerun_fresh)
        fresh_all = sum(1 for it in p["run"] if it.get("wasFresh")) + len(p["fresh"])
        return {
            "run": len(p["run"]), "fresh": len(p["fresh"]), "blocked": len(p["blocked"]),
            "blockedList": p["blocked"][:BLOCKED_LIST_MAX], "mixBound": p["mix"], "freshAll": fresh_all,
        }

    def submit(self, entry: str, ids: list[str], rerun_fresh: bool) -> dict[str, Any]:
        p = self.plan(entry, ids, rerun_fresh)
        if not p["run"]:
            raise CoreError("speech-nothing-to-do", fresh=len(p["fresh"]), blocked=len(p["blocked"]))
        return self._submit_items(p["run"], p["fresh"], p["versions"])

    def submit_range(self, asset_id: str, start: float, end: float, text: str) -> dict[str, Any]:
        """对“选区 + 手输文字”做语音分析（详情里的局部分析；不需要先保存采样）：手输单元。复用规则相同；人工版本保护相同。"""
        asset = assets_mod.get(self.conn, asset_id)
        from ..domain.mapping import check_range

        start, end = check_range(float(start), float(end), float(asset["duration"]), frame=1.0 / assets_mod.rate_of(self.conn, asset))
        ver = self._versions()
        u = self.typed_unit(asset_id, start, end, text)
        it = self._build(OWNER, u["unitId"], u["name"], asset_id, start, end, u["txt"], ver, None) | {"unitKind": u["kind"], "annotation": None}
        head = self._head_row(u["unitId"])
        it["baseHead"] = head["run_id"] if head else None
        if head is not None and head["status"] == "ok" and loads(head["inputs"]).get("fingerprint") == it["fingerprint"]:
            raise CoreError("speech-nothing-to-do", fresh=1, blocked=0)
        return self._submit_items([it], [], ver)

    def _submit_items(self, run: list[dict[str, Any]], fresh: list[dict[str, Any]], ver: dict[str, Any]) -> dict[str, Any]:
        items = []
        for i, it in enumerate(run):
            items.append({**it, "idx": i})
        params = {
            "items": items,
            "dictionary": {"path": ver["dictionaryPath"], "version": ver["dictionary"]},
            "versions": {k: v for k, v in ver.items() if k != "dictionaryPath"},
            "models_dir": str(self.ws.models),
            "support_dir": str(self.support_dir),
        }
        params["f0"] = self._f0_plan(items)
        params["skipped"] = [{"owner": it["owner"], "ownerType": it["ownerType"], "name": it["name"]} for it in fresh]
        affects = {"asset": sorted({it["asset"] for it in items})}
        job = self.jobs.submit(JOB_KIND, params, affects)
        self.jobs.add_items(job["id"], [(it["owner"], "queued") for it in items] + [(it["owner"], "skipped") for it in fresh])
        return self.jobs.summary(job["id"])

    # ------------------------------------------------------------ 人工修正（08 §8.7）：改的是“这句”，所有读这句的采样和原片页音素层同时生效

    def _head_full(self, owner: str) -> tuple[sqlite3.Row, sqlite3.Row]:
        head = self.conn.execute("SELECT * FROM measure_head WHERE owner_type=? AND owner_id=? AND kind=?", (OWNER, owner, KIND)).fetchone()
        if head is None:
            raise CoreError("speech-edit-invalid", reason="no-analysis")
        run = self.conn.execute("SELECT * FROM measure_run WHERE id=?", (head["run_id"],)).fetchone()
        if run["status"] != "ok":
            raise CoreError("speech-edit-invalid", reason="no-analysis")
        return head, run

    @staticmethod
    def parse_times(text: str) -> list[dict[str, Any]]:
        """精确时间文本：每行「开始秒 Tab 结束秒 Tab 音素」（空行忽略）。"""
        out = []
        for i, raw in enumerate(text.replace("\r\n", "\n").split("\n"), start=1):
            if not raw.strip():
                continue
            parts = raw.strip().split("\t") if "\t" in raw else raw.split()
            if len(parts) != 3:
                raise CoreError("speech-edit-invalid", reason="format", line=i)
            try:
                a, b = float(parts[0]), float(parts[1])
            except ValueError:
                raise CoreError("speech-edit-invalid", reason="number", line=i) from None
            out.append({"start": a, "end": b, "label": parts[2].strip()})
        return out


    def save_manual(self, owner: str, version: int, phones: list[dict[str, Any]] | None, text: str | None) -> dict[str, Any]:
        """编辑这句的音素时间 → 新的人工版本并成为当前头（之后的自动重跑不覆盖它）。只能改时间：行数、标签、顺序不变；
        前一个结束 ≤ 本个开始 < 本个结束 ≤ 范围终点（不重叠，允许空隙；句中停顿可以零长度）。版本变了要求重新载入。"""
        head, run = self._head_full(owner)
        if int(head["version"]) != int(version):
            raise CoreError("speech-edit-conflict", expected=int(version), actual=int(head["version"]))
        if text is not None:
            phones = self.parse_times(text)
        res = loads(run["result"])
        inputs = loads(run["inputs"])
        old = res["phones"]
        new = list(phones or [])
        if len(new) != len(old):
            raise CoreError("speech-edit-invalid", reason="count", expected=len(old), got=len(new))
        w0, w1 = (inputs.get("window") or [run["range_start"], run["range_end"]])
        prev = float(w0)
        out = []
        for i, (o, n) in enumerate(zip(old, new, strict=True), start=1):
            if str(n.get("label", "")) != o["label"]:
                raise CoreError("speech-edit-invalid", reason="label", line=i)
            a, b = n.get("start"), n.get("end")
            if not all(isinstance(x, (int, float)) and math.isfinite(x) for x in (a, b)):
                raise CoreError("speech-edit-invalid", reason="number", line=i)
            a, b = round(float(a), 6), round(float(b), 6)
            if a < prev - 1e-9 or b > float(w1) + 1e-9 or not (a < b or (a == b and o["label"] == "pau")):
                raise CoreError("speech-edit-invalid", reason="order", line=i)
            prev = b
            ph = {k: v for k, v in o.items() if k not in ("start", "end", "eff", "strength")} | {"start": a, "end": b}
            if o["label"] in derive.EFFECTIVE_LABELS or o.get("orig") in derive.EFFECTIVE_LABELS:
                ph["eff"] = [a, b]  # 人工版本不收缩
            out.append(ph)
        # 起音强度按新时间重算（18 A15）
        strengths = self._strengths(run["asset_id"], float(w0), float(w1), [(p.get("orig", p["label"]), p["start"], p["end"]) for p in out])
        for p, st in zip(out, strengths, strict=True):
            if st is not None:
                p["strength"] = round(float(st), 6)
        rid = new_id()
        span = units.span_of({"phones": out})
        before = units.span_of(res)
        with transaction(self.conn):
            self.conn.execute(
                "INSERT INTO measure_run(id, kind, owner_type, owner_id, asset_id, range_start, range_end, inputs, status, manual, result, created_at, span_start, span_end)"
                " VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'ok', 1, ?, ?, ?, ?)",
                (rid, KIND, OWNER, owner, run["asset_id"], run["range_start"], run["range_end"], dumps(inputs | {"manualOf": run["id"]}),
                 dumps(res | {"phones": out}), now_iso(), span[0] if span else None, span[1] if span else None),
            )
            self.conn.execute("UPDATE measure_head SET run_id=?, version=version+1 WHERE owner_type=? AND owner_id=? AND kind=?", (rid, OWNER, owner, KIND))
        self._changed({owner: [run["asset_id"], *self._extent(run, before, span)]})
        return {"runId": rid, "version": int(head["version"]) + 1}

    def switch_head(self, owner: str, run_id: str, version: int) -> dict[str, Any]:
        """切换版本：在这句的历史成功版本（人工/模型）之间换当前头。"""
        head, cur = self._head_full(owner)
        if int(head["version"]) != int(version):
            raise CoreError("speech-edit-conflict", expected=int(version), actual=int(head["version"]))
        r = self.conn.execute("SELECT * FROM measure_run WHERE id=? AND owner_type=? AND owner_id=? AND kind=?", (run_id, OWNER, owner, KIND)).fetchone()
        if r is None or r["status"] != "ok":
            raise CoreError("speech-edit-invalid", reason="not-a-version")
        with transaction(self.conn):
            self.conn.execute("UPDATE measure_head SET run_id=?, version=version+1 WHERE owner_type=? AND owner_id=? AND kind=?", (run_id, OWNER, owner, KIND))
        self._changed({owner: [r["asset_id"], *self._extent(r, units.span_of(loads(cur["result"])), units.span_of(loads(r["result"])))]})
        return {"runId": run_id, "version": int(head["version"]) + 1}

    @staticmethod
    def _extent(run: Any, *spans: tuple[float, float] | None) -> tuple[float, float]:
        """这句影响的资产区间：目标 ∪ 前后版本的音素跨度（找读这句的采样用）。"""
        xs = [(float(run["range_start"]), float(run["range_end"]))] + [s for s in spans if s is not None]
        return min(a for a, _ in xs), max(b for _, b in xs)

    def affected_samples(self, extents: Iterable[tuple[str, float, float]]) -> set[str]:
        """读到这些句的采样（同一资产上与区间正长度交叠的；有自己文本的采样多算进来只是多刷新一次）。"""
        out: set[str] = set()
        for asset, a, b in extents:
            out |= {r[0] for r in self.conn.execute('SELECT id FROM sample WHERE asset_id=? AND "end" > ? AND start < ?', (asset, a, b))}
        return out

    def _changed(self, owners: dict[str, list[Any]]) -> None:
        """``owners``：句 → [资产, 起, 止]。变更事件里 ``measure`` = 句与读到它们的采样，界面据此刷新。"""
        if self.on_change:
            cs = ChangeSet()
            for o in owners:
                cs.add("measure", o)
            for sid in self.affected_samples(tuple(v) for v in owners.values()):
                cs.add("measure", sid)
            self.on_change(cs)

    def _strengths(self, asset_id: str, w0: float, w1: float, phones: list[tuple[str, float, float]]) -> list[float | None]:
        from ..media import decode as dec

        asset, ref, win, media = self._locate(asset_id, w0, w1, None)
        sr = ref.sample_rate
        a, b = round(win.to_file(w0) * sr), round(win.to_file(w1) * sr)
        pcm = dec.decode_frames(ref, a, b, cache=self.ws.data / "Cache")
        t0 = win.to_local(a / sr)
        return derive.onset_strengths(pcm, sr, [(lab, s - t0, e - t0) for lab, s, e in phones])

    # ------------------------------------------------------------ F0（08 §8.1 第 4 项、10 §10.1：该声音没测过才测）

    @staticmethod
    def f0_sha() -> str:
        return next(f.sha256 for f in registry.spec(fcpe.MODEL_ID).files if f.rel_path == fcpe.MODEL_FILE)

    def _f0_plan(self, items: list[dict[str, Any]]) -> list[dict[str, Any]]:
        by_asset: dict[str, dict[str, Any]] = {}
        for it in items:
            a = by_asset.get(it["asset"])
            if a is None:
                dur = float(self.conn.execute("SELECT duration FROM sound_asset WHERE id=?", (it["asset"],)).fetchone()[0])
                ident = f0store.identity(it["audio"], self.f0_sha())
                a = by_asset[it["asset"]] = {
                    "asset": it["asset"], "identity": ident, "duration": dur, "file": it["file"], "storage": it["audio"]["storage"],
                    "have": f0store.present(self.ws.f0, it["asset"], ident), "chunks": set(),
                }
            a["chunks"] |= set(f0store.chunks_for(it["target"][0], it["target"][1], a["duration"])) - a["have"]
        return [
            {k: v for k, v in a.items() if k != "have"} | {"chunks": sorted(a["chunks"])} for a in by_asset.values() if a["chunks"]
        ]

    def _adopt_f0(self, job_id: str, entries: list[dict[str, Any]], ts: str) -> None:
        self._adopt_f0_dirs(job_id, entries, ts, {})

    def _adopt_f0_dirs(self, job_id: str, entries: list[dict[str, Any]], ts: str, files: dict[str, dict[int, Path]]) -> None:
        """``files``：资产 → {段号: 文件}；没给的按语音分析任务的布局（任务目录/f0/<资产>/<段号>.npy）。"""
        for e in entries:
            src = self.jobs.jobs_dir / job_id / "f0" / e["asset"]
            if self.conn.execute("SELECT 1 FROM sound_asset WHERE id=?", (e["asset"],)).fetchone() is None:
                continue
            given = files.get(e["asset"], {})
            for k in e["chunks"]:
                f0store.adopt_chunk(
                    self.ws.f0, e["asset"], e["identity"], int(k), given.get(int(k), src / f"{k}.npy"), {"model": self.f0_sha(), "frontend": fcpe.FRONTEND_VERSION}
                )
            have = sorted(f0store.present(self.ws.f0, e["asset"], e["identity"]))
            rid = new_id()
            self.conn.execute(
                "INSERT INTO measure_run(id, kind, owner_type, owner_id, asset_id, inputs, status, manual, result, created_at)"
                " VALUES (?, 'f0', 'asset', ?, ?, ?, 'ok', 0, ?, ?)",
                (rid, e["asset"], e["asset"], dumps({"identity": e["identity"], "model": self.f0_sha(), "frontend": fcpe.FRONTEND_VERSION, "job": job_id}),
                 dumps({"identity": e["identity"], "chunks": have}), ts),
            )
            head = self.conn.execute("SELECT 1 FROM measure_head WHERE owner_type='asset' AND owner_id=? AND kind='f0'", (e["asset"],)).fetchone()
            if head is None:
                self.conn.execute("INSERT INTO measure_head(owner_type, owner_id, kind, run_id, version) VALUES ('asset', ?, 'f0', ?, 1)", (e["asset"], rid))
            else:
                self.conn.execute("UPDATE measure_head SET run_id=?, version=version+1 WHERE owner_type='asset' AND owner_id=? AND kind='f0'", (rid, e["asset"]))

    def f0_identity(self, asset_id: str, start: float, end: float) -> tuple[dict[str, Any], str]:
        """存放 [start, end) 的那段声音的 F0 测量身份（f0store.identity）；读取与登记（拉平成品）共用。"""
        asset = assets_mod.get(self.conn, asset_id)
        ref, win, media = assets_mod.locate(self.conn, self.ws.root, asset, start, end)
        audio = {
            "asset": asset["id"], "mapping": asset["mapping"], "media": media["media_file_id"],
            "snapshot": {k: (media["snapshot"] or {}).get(k) for k in ("size", "mtime_ns")}, "ordinal": ref.ordinal,
            "storage": [win.local_start, win.local_end, win.file_start],
        }
        return asset, f0store.identity(audio, self.f0_sha())

    def f0_frames(self, asset_id: str, start: float, end: float) -> tuple[int, Any, Any]:
        """资产区间的 F0 帧（第一帧序号、[n, 3]、是否已测）；读取没有副作用。"""
        asset = assets_mod.get(self.conn, asset_id)
        dur = float(asset["duration"])
        if not (0 <= start < end <= dur + 1e-6):
            raise CoreError("range-invalid", reason="out-of-bounds", start=start, end=end, duration=dur)
        _, ident = self.f0_identity(asset_id, start, min(end, dur))
        return f0store.read(self.ws.f0, asset_id, ident, start, min(end, dur), dur)

    def record_f0(self, asset_id: str, identity: str, chunks: dict[int, Path], job_id: str, ts: str) -> None:
        """把任务测好的 F0 段放进测量目录，并写测量记录（kind=f0、归属资产）。在调用方事务里执行。"""
        self._adopt_f0_dirs(job_id, [{"asset": asset_id, "identity": identity, "chunks": sorted(chunks)}], ts, {asset_id: chunks})

    def f0(self, asset_id: str, start: float, end: float) -> dict[str, Any]:
        """资产区间的 F0 帧（读取没有副作用）；没测的帧标 missing。时间：资产局部秒，第一帧的中心为 ``t0``。"""
        i0, frames, have = self.f0_frames(asset_id, start, end)
        return {
            "t0": (i0 * fcpe.HOP + fcpe.HOP / 2) / fcpe.SR, "step": fcpe.HOP / fcpe.SR, "count": len(frames),
            "f0": frames[:, 0].astype("<f4").tobytes(), "confidence": frames[:, 1].astype("<f4").tobytes(), "energy": frames[:, 2].astype("<f4").tobytes(),
            "measured": int(have.sum()),
        }


    # ------------------------------------------------------------ 采纳

    def _head_row(self, owner: str) -> sqlite3.Row | None:
        return self.conn.execute(
            "SELECT h.run_id, h.version, r.status, r.manual, r.inputs FROM measure_head h JOIN measure_run r ON r.id=h.run_id"
            " WHERE h.owner_type=? AND h.owner_id=? AND h.kind=?",
            (OWNER, owner, KIND),
        ).fetchone()

    def _current_item(self, it: dict[str, Any], ver: dict[str, Any], memo: dict[str, Any]) -> dict[str, Any]:
        """采纳时按现在的资料重建这一句的输入（判断任务期间输入变没变）。"""
        if it.get("unitKind") == units.LINE:
            u = self.line_unit(it["annotation"], it["asset"], None, memo)
        else:
            u = self.typed_unit(it["asset"], it["target"][0], it["target"][1], it["text"], it["name"], it["textSource"]) | {"unitId": it["owner"]}
        if u["unitId"] != it["owner"]:
            raise CoreError("speech-blocked", reason="changed")
        return self._build(OWNER, u["unitId"], u["name"], u["asset"], u["target"][0], u["target"][1], u["txt"], ver, memo)

    def _adopt(self, job: dict[str, Any], result: dict[str, Any]) -> None:
        params = loads(job["params"])
        items = {it["idx"]: it for it in params["items"]}
        rows = self.conn.execute("SELECT idx, status, error, result_ref FROM job_item WHERE job_id=? AND status IN ('ok', 'failed')", (job["id"],)).fetchall()
        item_dir = self.jobs.jobs_dir / job["id"] / "items"
        ver_now = self._versions()
        memo: dict[str, Any] = {}
        touched: dict[str, list[Any]] = {}
        ts = now_iso()
        with transaction(self.conn):
            for r in rows:
                it = items.get(r["idx"])
                if it is None or it.get("ownerType") != OWNER:
                    continue  # 旧格式（归属采样）的任务：不再登记
                owner = it["owner"]
                if self.conn.execute("SELECT 1 FROM sound_asset WHERE id=?", (it["asset"],)).fetchone() is None:
                    continue  # 资产在任务期间被删了：不登记
                inputs = {k: it.get(k) for k in ("name", "unitKind", "annotation", "text", "textSource", "textVersion", "equalsSubtitle", "target", "window",
                                                  "requested", "actual", "truncated", "audio", "fingerprint")}
                inputs |= {"versions": params["versions"], "device": loads(job["device"]), "job": job["id"]}
                span = None
                if r["status"] == "ok":
                    res = json.loads((item_dir / r["result_ref"]).read_text(encoding="utf-8"))
                    status = "ok"
                    span = units.span_of(res)
                else:
                    res = {"error": loads(r["error"]) if r["error"] else None}
                    status = "failed"
                rid = new_id()
                self.conn.execute(
                    "INSERT INTO measure_run(id, kind, owner_type, owner_id, asset_id, range_start, range_end, inputs, status, manual, result, created_at, span_start, span_end)"
                    " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 0, ?, ?, ?, ?)",
                    (rid, KIND, OWNER, owner, it["asset"], it["target"][0], it["target"][1], dumps(inputs), status, dumps(res), ts,
                     span[0] if span else None, span[1] if span else None),
                )
                if status != "ok":
                    touched.setdefault(owner, [it["asset"], *it["target"]])
                    continue
                head = self._head_row(owner)
                if head is not None and (head["manual"] or head["run_id"] != it.get("baseHead")):
                    touched.setdefault(owner, [it["asset"], *it["target"]])
                    continue  # 人工版本或已被更新：只进历史
                try:
                    changed = self._current_item(it, ver_now, memo)["fingerprint"] != it["fingerprint"]
                except CoreError:
                    changed = True
                if changed:
                    touched.setdefault(owner, [it["asset"], *it["target"]])
                    continue  # 输入在任务期间变了：只进历史
                old = None
                if head is not None:
                    o = self.conn.execute("SELECT result FROM measure_run WHERE id=?", (head["run_id"],)).fetchone()
                    old = units.span_of(loads(o["result"])) if o and o["result"] else None
                xs = [x for x in (tuple(it["target"]), span, old) if x is not None]
                touched[owner] = [it["asset"], min(a for a, _ in xs), max(b for _, b in xs)]
                self._set_head(owner, rid, head)
        with transaction(self.conn):
            self._adopt_f0(job["id"], result.get("f0") or [], ts)
        record_probes(self.conn, result.get("probes") or [])
        # 成功后清理私有中间文件（逐条结果已进库）；失败的任务不会走到这里，证据保留
        shutil.rmtree(self.jobs.jobs_dir / job["id"] / "cache", ignore_errors=True)
        if touched:
            self._changed(touched)

    def _set_head(self, owner: str, run_id: str, head: sqlite3.Row | None) -> None:
        if head is None:
            self.conn.execute("INSERT INTO measure_head(owner_type, owner_id, kind, run_id, version) VALUES (?, ?, ?, ?, 1)", (OWNER, owner, KIND, run_id))
        else:
            self.conn.execute("UPDATE measure_head SET run_id=?, version=version+1 WHERE owner_type=? AND owner_id=? AND kind=?", (run_id, OWNER, owner, KIND))

    # ------------------------------------------------------------ 读取（无副作用）

    @staticmethod
    def _head_wire(r: sqlite3.Row, version: int) -> dict[str, Any]:
        inp = loads(r["inputs"])
        return {
            "runId": r["id"], "version": int(version), "status": r["status"], "manual": bool(r["manual"]), "createdAt": r["created_at"],
            "text": inp.get("text"), "textSource": inp.get("textSource"), "window": inp.get("window"),
            "result": loads(r["result"]) if r["status"] == "ok" else None,
        }

    def _snapshot(self, asset_id: str, start: float, end: float) -> dict[str, Any] | None:
        try:
            _, _, _, media = self._locate(asset_id, start, end, None)
        except CoreError:
            return None
        return {k: (media["snapshot"] or {}).get(k) for k in ("size", "mtime_ns")}

    def _overlapping(self, asset_id: str, start: float, end: float) -> list[sqlite3.Row]:
        """资产上音素跨度与 [start, end) 正长度交叠的句的当前头（成功的）。"""
        return self.conn.execute(
            "SELECT h.owner_id, h.version, r.* FROM measure_head h JOIN measure_run r ON r.id=h.run_id"
            " WHERE h.owner_type=? AND h.kind=? AND r.asset_id=? AND r.status='ok' AND r.span_end > ? AND r.span_start < ? ORDER BY r.span_start, h.owner_id",
            (OWNER, KIND, asset_id, start, end),
        ).fetchall()

    def _unit_view(self, u: dict[str, Any], start: float, end: float, own: bool, head_row: sqlite3.Row | None = None, read_head: bool = True) -> dict[str, Any]:
        """``read_head=False``：这句的当前头不读（别的声音上测的，文件快照对不上）。"""
        uid = u["unitId"]
        if head_row is None and read_head:
            head_row = self.conn.execute(
                "SELECT h.owner_id, h.version, r.* FROM measure_head h JOIN measure_run r ON r.id=h.run_id WHERE h.owner_type=? AND h.owner_id=? AND h.kind=?",
                (OWNER, uid, KIND),
            ).fetchone()
        runs = self.conn.execute(
            "SELECT id, status, manual, created_at, inputs, result FROM measure_run WHERE owner_type=? AND owner_id=? AND kind=? ORDER BY created_at DESC, rowid DESC",
            (OWNER, uid, KIND),
        ).fetchall()
        head = self._head_wire(head_row, head_row["version"]) if head_row is not None else None
        span = units.span_of(head["result"]) if head and head["result"] else None
        txt = u.get("txt")
        return {
            "unitId": uid, "kind": units.kind_of(uid), "name": u.get("name") or (txt or {}).get("text") or (head or {}).get("text"),
            "text": (txt or {}).get("text") or (head or {}).get("text"), "target": list(u["target"]) if u.get("target") else None,
            "partial": (not own) and units.partial(span if span else (tuple(u["target"]) if u.get("target") else None), start, end),
            "head": head,
            "runs": [
                {
                    "id": r["id"], "status": r["status"], "manual": bool(r["manual"]), "createdAt": r["created_at"],
                    "error": (loads(r["result"]) or {}).get("error") if r["status"] != "ok" and r["result"] else None, "text": loads(r["inputs"]).get("text"),
                }
                for r in runs
            ],
        }

    def reading(self, s: sqlite3.Row) -> dict[str, Any]:
        """采样读到的句（所有者 2026-10-08）：有自己的文本 → 只有自己那一句；没有 → 范围内已分析的句（同一物理声音）与可分析的句。
        ``head`` = 读到的句合成的当前头（没有自己文本时音素裁到采样范围）；两句的音素在时间上冲突 → ``conflict``、``head`` 为 None。"""
        start, end = float(s["start"]), float(s["end"])
        memo: dict[str, Any] = {}
        own = self.own_unit(s, memo)
        views: list[dict[str, Any]] = []
        if own is not None:
            views.append(self._unit_view(own, start, end, True))
        else:
            seen: dict[str, dict[str, Any]] = {}
            other: set[str] = set()
            snap = self._snapshot(s["asset_id"], start, end)
            for r in self._overlapping(s["asset_id"], start, end):
                if snap is None or (loads(r["inputs"]).get("audio") or {}).get("snapshot") != snap:
                    other.add(r["owner_id"])
                    continue  # 文件内容不同：不读（R11.10）
                inp = loads(r["inputs"])
                u = {"unitId": r["owner_id"], "name": inp.get("name") or inp.get("text"), "target": (float(r["range_start"]), float(r["range_end"]))}
                seen[r["owner_id"]] = self._unit_view(u, start, end, False, r)
            for u in self.candidates(s, memo):
                if u["unitId"] not in seen:
                    seen[u["unitId"]] = self._unit_view(u, start, end, False, read_head=u["unitId"] not in other)
                else:
                    seen[u["unitId"]]["name"], seen[u["unitId"]]["text"] = u["name"], u["txt"]["text"]
            views = sorted(seen.values(), key=lambda v: (units.span_of(v["head"]["result"]) if v["head"] and v["head"]["result"] else tuple(v["target"] or (0, 0)))[0])
        ok = [v for v in views if v["head"] is not None and v["head"]["status"] == "ok" and v["head"]["result"]]
        head: dict[str, Any] | None = None
        conflict = None
        if own is not None:
            if ok:
                head = ok[0]["head"] | {"units": [ok[0]["unitId"]], "partial": False}
        elif ok:
            merged = units.merge([{"unitId": v["unitId"], "name": v["name"], "result": v["head"]["result"]} for v in ok], start, end)
            if "conflict" in merged:
                conflict = merged["conflict"]
            else:
                hs = [v["head"] for v in ok]
                head = {
                    "runId": "+".join(h["runId"] for h in hs), "version": sum(int(h["version"]) for h in hs), "status": "ok",
                    "manual": any(h["manual"] for h in hs), "createdAt": max(h["createdAt"] for h in hs),
                    "text": " ".join(h["text"] or "" for h in hs).strip() or None, "textSource": "units", "window": [start, end],
                    "result": merged, "units": [v["unitId"] for v in ok], "partial": any(v["partial"] for v in ok),
                }
        if own is not None:
            text, source, reason = ((own["txt"] or {}).get("text"), (own["txt"] or {}).get("source"), None if own["txt"] else own.get("reason") or "no-text")
        else:
            joined = " ".join(v["text"] or "" for v in views).strip()
            text, source, reason = (joined or None, "units" if joined else None, None if joined else "no-text")
        return {"own": own is not None, "text": text, "textSource": source, "reason": reason, "head": head, "conflict": conflict, "units": views}

    def sample_view(self, sample_id: str) -> dict[str, Any]:
        """舞台语音面板：采样读到的句（各自的当前头与全部版本，新的在前）、合成的当前头、对齐文本现状。"""
        s = self.conn.execute(f"SELECT {self._SAMPLE_COLS} FROM sample WHERE id=?", (sample_id,)).fetchone()
        if s is None:
            raise CoreError("sample-not-found", id=sample_id)
        return {"sampleId": sample_id, **self.reading(s)}

    def for_asset(self, asset_id: str, start: float, end: float) -> list[dict[str, Any]]:
        """原片视口的音素层（08 §8.8）：这个资产上各句当前头的成功测量，只取同一物理声音（文件快照一致）的；读取没有副作用。时间：资产局部秒。"""
        asset = assets_mod.get(self.conn, asset_id)
        try:
            _, _, media = assets_mod.locate(self.conn, self.ws.root, asset, max(0.0, start), min(float(asset["duration"]), end))
            snap = {k: (media["snapshot"] or {}).get(k) for k in ("size", "mtime_ns")}
        except CoreError:
            return []
        rows = self.conn.execute(
            "SELECT h.owner_id, r.id, r.manual, r.inputs, r.result FROM measure_head h JOIN measure_run r ON r.id=h.run_id"
            " WHERE h.owner_type=? AND h.kind=? AND r.asset_id=? AND r.status='ok' AND r.range_end > ? AND r.range_start < ? ORDER BY r.range_start",
            (OWNER, KIND, asset_id, start, end),
        )
        out = []
        for r in rows:
            inp = loads(r["inputs"])
            if (inp.get("audio") or {}).get("snapshot") != snap:
                continue  # 文件指纹不同 → 不显示（R11.10）
            res = loads(r["result"])
            out.append({
                "unitId": r["owner_id"], "kind": units.kind_of(r["owner_id"]), "name": inp.get("name") or inp.get("text"), "runId": r["id"], "manual": bool(r["manual"]),
                "phones": [{"label": p["label"], "start": p["start"], "end": p["end"]} for p in res["phones"]],
            })
        return out

    def results(self, job_id: str) -> list[dict[str, Any]]:
        job = self.conn.execute("SELECT params FROM job WHERE id=?", (job_id,)).fetchone()
        if job is None:
            raise CoreError("job-not-found", id=job_id)
        params = loads(job["params"])
        names = {it["owner"]: (it.get("ownerType"), it["name"]) for it in params.get("items", []) + params.get("skipped", []) if it.get("owner")}
        rows = self.conn.execute(
            "SELECT j.idx, j.target, j.status, j.error, s.name FROM job_item j LEFT JOIN sample s ON s.id=j.target WHERE j.job_id=? ORDER BY j.status='skipped', j.idx",
            (job_id,),
        )
        out = []
        for r in rows:
            otype, pname = names.get(r["target"], ("sample", None))
            if otype == "sample":  # 旧格式（归属采样）的任务
                out.append({"idx": r["idx"], "unitId": None, "sampleId": r["target"], "name": r["name"], "status": r["status"],
                            "error": loads(r["error"]) if r["error"] else None, "deleted": r["name"] is None})
                continue
            out.append({"idx": r["idx"], "unitId": r["target"], "sampleId": None, "name": pname, "status": r["status"],
                        "error": loads(r["error"]) if r["error"] else None, "deleted": False})
        return out

    def source_counts(self, source_id: str) -> dict[str, int]:
        """原片页「准备」里的语音分析一行：原片入口范围内的句数与已分析（当前头为成功测量）的句数。"""
        found = self._source_units([source_id], self._pads(), {})
        if not found:
            return {"speech": 0, "analyzed": 0}
        ids = list(found)
        done = 0
        for i in range(0, len(ids), 900):
            part = ids[i : i + 900]
            done += self.conn.execute(
                f"SELECT COUNT(*) FROM measure_head WHERE owner_type=? AND kind=? AND owner_id IN ({','.join('?' * len(part))})", (OWNER, KIND, *part)
            ).fetchone()[0]
        return {"speech": len(ids), "analyzed": int(done)}

    def analyzed_counts(self, source_id: str | None = None) -> dict[str, dict[str, int]]:
        """每个原片：语音性质采样数与“已分析”（读到的句有成功测量，含只读到一部分的 ◐）数。"""
        q = (
            f"SELECT a.source_id, COUNT(*), SUM(CASE WHEN {units.state_sql('s')} IN ('ok', 'manual', 'partial') THEN 1 ELSE 0 END)"
            " FROM sample s JOIN sound_asset a ON a.id=s.asset_id WHERE s.nature='speech'"
        )
        args: list[Any] = []
        if source_id:
            q += " AND a.source_id=?"
            args.append(source_id)
        q += " GROUP BY a.source_id"
        return {r[0]: {"speech": int(r[1]), "analyzed": int(r[2] or 0)} for r in self.conn.execute(q, args)}
