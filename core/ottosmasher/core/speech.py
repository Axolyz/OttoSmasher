"""语音分析（规格 08 §8.1–§8.4、§8.8）：Core 侧——选范围、冻结输入、复用判断、提交任务、采纳结果、读取测量。

- **分析属于“文本层的段 + 具体那条声音资产”**（所有者 2026-10-09【基线变更】，``core/units.py``）：
  版本、当前头、人工修音素时间都挂在这里；同一段在不同的轨上各有一份。采样不拥有分析，只按判定区间读取。
- 一个操作、统一复用规则（D45 按“段 + 资产”判断）：输入（段文本、辞典、前端、模型、目标区间、容差、输入音频身份）与这段可用的分析完全相同 → 跳过；
  任何不同 → 重跑。确认框写清“将分析 M 段；N 段已是最新，跳过；K 条无法处理（原因）”。
- 入口：原片页 = 所选原片的段（不在 OP/ED 里），在默认人声轨（没有就是原混音）或用户选的当前查看的轨上，不需要先建采样；
  段右键 = 这几段；采样库 = 各采样判定区间读到的段，在采样所在的资产上；结果表 = 指定的“段 + 资产”。
- 目标 = 段区间映射到资产（裁到覆盖范围），窗口 = 目标两侧各扩展对齐容差，只在同一物理声音内扩展；只送这段的文本，不带邻句。
- 采纳（按顺序）：任务取消 → 不写；段已删或内容（文本、区间）在任务期间变了、其他输入变了 → 只进历史；
  当前头是人工版本且内容仍与段一致、或当前头已被更新 → 只进历史；否则成为新的当前头。失败结果只进历史。
- 段的文本或区间改了之后，旧分析立即停用（读到的采样显示“第 X 段改过，待重新分析”），直到重新分析；人工版本保护也只对内容一致的头生效。
- 读取测量没有副作用。
时钟：测量里的音素时间都是资产局部秒；采样的 start/end 也是资产局部秒；段、判定区间是原片秒。
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
from .edits import SEGMENT_MAX, ChangeSet, dumps, loads
from .probes import record_probes
from .errors import CoreError

KIND = "alignment"
JOB_KIND = "speech.analyze"
BLOCKED_LIST_MAX = 50
OWNER = units.OWNER


def _sha(obj: Any) -> str:
    return hashlib.sha256(json.dumps(obj, sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode("utf-8")).hexdigest()


def _txt(text: str) -> dict[str, Any]:
    return {"text": text, "source": "segment", "version": hashlib.sha256(text.encode("utf-8")).hexdigest()[:16], "equalsSubtitle": False}


class SpeechService:
    def __init__(self, conn: sqlite3.Connection, ws: Workspace, jobs: Any, support_dir: Path, on_change: Callable[[ChangeSet], None] | None = None) -> None:
        self.conn = conn
        self.ws = ws
        self.jobs = jobs
        self.support_dir = support_dir
        self.on_change = on_change
        jobs.adopters[JOB_KIND] = self._adopt

    # ------------------------------------------------------------ 段与“段 + 资产”

    _SEG_COLS = 'id, source_id, start, "end", text, speakers, deleted'

    def _asset(self, asset_id: str, memo: dict[str, Any] | None) -> dict[str, Any]:
        key = ("asset", asset_id)
        if memo is not None and key in memo:
            return memo[key]
        a = assets_mod.get(self.conn, asset_id)
        if memo is not None:
            memo[key] = a
        return a

    def _segment(self, segment_id: str) -> sqlite3.Row | None:
        return self.conn.execute(f"SELECT {self._SEG_COLS} FROM text_segment WHERE id=?", (segment_id,)).fetchone()

    def segment_unit(self, seg: Any, asset_id: str, memo: dict[str, Any] | None = None) -> dict[str, Any]:
        """一段在一条资产上的分析单元；处理不了抛 speech-blocked（no-text / out-of-track / other-source）。"""
        text = (seg["text"] or "").strip()
        if not text:
            raise CoreError("speech-blocked", reason="no-text")
        asset = self._asset(asset_id, memo)
        if asset["source_id"] != seg["source_id"]:
            raise CoreError("speech-blocked", reason="other-source")
        tgt = units.seg_target(float(seg["start"]), float(seg["end"]), asset["mapping"], float(asset["duration"]))
        if tgt is None:
            raise CoreError("speech-blocked", reason="out-of-track")
        return {
            "unitId": units.unit_id(seg["id"], asset_id), "segment": seg["id"], "asset": asset_id, "target": tgt,
            "name": text.replace("\n", " "), "txt": _txt(text), "seg": {"start": float(seg["start"]), "end": float(seg["end"]), "text": seg["text"]},
        }

    def unit_by_id(self, unit_id: str, memo: dict[str, Any] | None = None) -> dict[str, Any]:
        seg_id, asset_id = units.parse(unit_id)
        seg = self._segment(seg_id)
        if seg is None or seg["deleted"]:
            raise CoreError("speech-blocked", reason="segment-deleted")
        if self.conn.execute("SELECT 1 FROM sound_asset WHERE id=?", (asset_id,)).fetchone() is None:
            raise CoreError("speech-blocked", reason="out-of-track")
        return self.segment_unit(seg, asset_id, memo)

    def judge_of(self, s: Any, memo: dict[str, Any] | None = None) -> tuple[float, float] | None:
        """采样的判定区间（原片秒）；没有记录的 = 选区经映射换算。"""
        if s["tag_judge_start"] is not None and s["tag_judge_end"] is not None:
            return float(s["tag_judge_start"]), float(s["tag_judge_end"])
        try:
            m = Mapping.of(self._asset(s["asset_id"], memo)["mapping"])
            return m.to_source(float(s["start"])), m.to_source(float(s["end"]))
        except CoreError:
            return None

    def read_segments(self, source_id: str, a: float, b: float) -> list[sqlite3.Row]:
        """与 [a, b)（原片秒）正长度交叠的存活段，按 (start, end, id)。"""
        return self.conn.execute(
            f'SELECT {self._SEG_COLS} FROM text_segment WHERE source_id=? AND deleted=0 AND start < ? AND "end" > ? AND start > ? ORDER BY start, "end", id',
            (source_id, b, a, a - SEGMENT_MAX - 1e-6),
        ).fetchall()

    def ordinals(self, source_id: str, ids: Iterable[str]) -> dict[str, int]:
        """段在文本层里的序号（读取时按存活段的 (start, end, id) 排出来，不存）。"""
        want = set(ids)
        out: dict[str, int] = {}
        if not want:
            return out
        for i, (sid,) in enumerate(self.conn.execute('SELECT id FROM text_segment WHERE source_id=? AND deleted=0 ORDER BY start, "end", id', (source_id,)), start=1):
            if sid in want:
                out[sid] = i
        return out

    def _runs(self, unit: str) -> list[sqlite3.Row]:
        return self.conn.execute(
            "SELECT * FROM measure_run WHERE owner_type=? AND owner_id=? AND kind=? ORDER BY created_at DESC, rowid DESC", (OWNER, unit, KIND)
        ).fetchall()

    def _head_run(self, unit: str) -> str | None:
        r = self.conn.execute("SELECT run_id FROM measure_head WHERE owner_type=? AND owner_id=? AND kind=?", (OWNER, unit, KIND)).fetchone()
        return r[0] if r else None

    def usable_run(self, unit: str, seg: Any) -> sqlite3.Row | None:
        """可用的分析：内容与段现在一致的成功版本里，当前头 > 人工 > 最新（文件快照另在读取时核对）。"""
        return units.pick_usable(self._runs(unit), seg, self._head_run(unit))

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



    # ------------------------------------------------------------ 范围与计划（08 §8.4，按“段 + 资产”）

    _SAMPLE_COLS = 'id, asset_id, start, "end", name, nature, origin, text_snapshot, parent_sample_id, tag_judge_start, tag_judge_end'

    def _samples(self, ids: Iterable[str]) -> list[sqlite3.Row]:
        ids = list(dict.fromkeys(ids))
        out = []
        for i in range(0, len(ids), 500):
            chunk = ids[i : i + 500]
            rows = {r["id"]: r for r in self.conn.execute(f"SELECT {self._SAMPLE_COLS} FROM sample WHERE id IN ({','.join('?' * len(chunk))})", chunk)}
            out += [rows[x] for x in chunk if x in rows]
        return out

    def _track_for(self, source_id: str, asset_id: str | None) -> str | None:
        """原片页入口用的音轨：用户选的当前查看的轨（必须属于这个原片），否则默认人声轨（没有就是原混音）。"""
        if asset_id is not None:
            r = self.conn.execute("SELECT source_id FROM sound_asset WHERE id=?", (asset_id,)).fetchone()
            if r is not None and r[0] == source_id:
                return asset_id
        return units.analysis_track(self.conn, source_id)

    def _source_units(self, source_ids: Iterable[str], asset_id: str | None, memo: dict[str, Any], blocked: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
        """原片入口：所选原片中、区间不与已确认 OP/ED 正长度交叠的段，在所选音轨上（不需要先建采样）。"""
        out: dict[str, dict[str, Any]] = {}
        for sid in dict.fromkeys(source_ids):
            track = self._track_for(sid, asset_id)
            if track is None:
                blocked.append({"id": sid, "name": sid, "reason": "no-track"})
                continue
            opeds = [(r[0], r[1]) for r in self.conn.execute('SELECT start, "end" FROM oped WHERE source_id=? AND deleted=0', (sid,))]
            for seg in self.conn.execute(f'SELECT {self._SEG_COLS} FROM text_segment WHERE source_id=? AND deleted=0 ORDER BY start, "end", id', (sid,)):
                if any(overlaps(seg["start"], seg["end"], a, b) for a, b in opeds):
                    continue
                try:
                    u = self.segment_unit(seg, track, memo)
                except CoreError:
                    continue  # 不在这条音轨的范围里：不在原片入口的范围里
                out.setdefault(u["unitId"], u)
        return out

    def plan(self, entry: str, ids: list[str], rerun_fresh: bool, asset_id: str | None = None) -> dict[str, Any]:
        if entry not in ("source", "segments", "samples", "units"):
            raise CoreError("speech-invalid", reason="not-an-option", field="entry")
        ver = self._versions()
        memo: dict[str, Any] = {}
        specs: dict[str, dict[str, Any]] = {}
        blocked: list[dict[str, Any]] = []
        if entry == "source":
            specs = self._source_units(ids, asset_id, memo, blocked)
        elif entry == "segments":
            for sid in dict.fromkeys(ids):
                seg = self._segment(sid)
                if seg is None or seg["deleted"]:
                    blocked.append({"id": sid, "name": sid, "reason": "segment-deleted"})
                    continue
                track = self._track_for(seg["source_id"], asset_id)
                try:
                    if track is None:
                        raise CoreError("speech-blocked", reason="no-track")
                    u = self.segment_unit(seg, track, memo)
                except CoreError as e:
                    blocked.append({"id": sid, "name": (seg["text"] or "").replace("\n", " "), "reason": e.args_.get("reason") or e.code})
                    continue
                specs.setdefault(u["unitId"], u)
        elif entry == "samples":
            for s in self._samples(ids):
                judge = self.judge_of(s, memo)
                src = self._asset(s["asset_id"], memo)["source_id"]
                segs = self.read_segments(src, *judge) if judge else []
                if not segs:
                    blocked.append({"id": s["id"], "name": s["name"], "reason": "no-text"})
                    continue
                for seg in segs:
                    try:
                        u = self.segment_unit(seg, s["asset_id"], memo)
                    except CoreError as e:
                        blocked.append({"id": s["id"], "name": s["name"], "reason": e.args_.get("reason") or e.code})
                        continue
                    specs.setdefault(u["unitId"], u)
        else:
            for uid in dict.fromkeys(ids):
                try:
                    specs[uid] = self.unit_by_id(uid, memo)
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
            it |= {"segment": u["segment"], "seg": u["seg"]}
            asset = self._asset(u["asset"], memo)
            if asset["origin"] == "stream" or not asset["roles"]:
                mix += 1
            head = self._head_run(u["unitId"])
            it["baseHead"] = head
            use = units.pick_usable(self._runs(u["unitId"]), u["seg"], head)
            is_fresh = use is not None and loads(use["inputs"]).get("fingerprint") == it["fingerprint"]
            if is_fresh and not rerun_fresh:
                fresh.append(it)
            else:
                run.append(it | {"wasFresh": True} if is_fresh else it)
        return {"run": run, "fresh": fresh, "blocked": blocked, "mix": mix, "versions": ver}

    def preview(self, entry: str, ids: list[str], rerun_fresh: bool, asset_id: str | None = None) -> dict[str, Any]:
        p = self.plan(entry, ids, rerun_fresh, asset_id)
        fresh_all = sum(1 for it in p["run"] if it.get("wasFresh")) + len(p["fresh"])
        return {
            "run": len(p["run"]), "fresh": len(p["fresh"]), "blocked": len(p["blocked"]),
            "blockedList": p["blocked"][:BLOCKED_LIST_MAX], "mixBound": p["mix"], "freshAll": fresh_all,
        }

    def submit(self, entry: str, ids: list[str], rerun_fresh: bool, asset_id: str | None = None, background: bool = False) -> dict[str, Any]:
        p = self.plan(entry, ids, rerun_fresh, asset_id)
        if not p["run"]:
            raise CoreError("speech-nothing-to-do", fresh=len(p["fresh"]), blocked=len(p["blocked"]))
        return self._submit_items(p["run"], p["fresh"], p["versions"], background)

    def _submit_items(self, run: list[dict[str, Any]], fresh: list[dict[str, Any]], ver: dict[str, Any], background: bool = False) -> dict[str, Any]:
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
        job = self.jobs.submit(JOB_KIND, params, affects, background=background)
        self.jobs.add_items(job["id"], [(it["owner"], "queued") for it in items] + [(it["owner"], "skipped") for it in fresh])
        return self.jobs.summary(job["id"])

    # ------------------------------------------------------------ 人工修正（08 §8.7）：改的是“这段在这条轨上的分析”，所有读它的采样和原片页音素层同时生效

    def _head_full(self, owner: str) -> tuple[sqlite3.Row, sqlite3.Row, sqlite3.Row]:
        head = self.conn.execute("SELECT * FROM measure_head WHERE owner_type=? AND owner_id=? AND kind=?", (OWNER, owner, KIND)).fetchone()
        if head is None:
            raise CoreError("speech-edit-invalid", reason="no-analysis")
        run = self.conn.execute("SELECT * FROM measure_run WHERE id=?", (head["run_id"],)).fetchone()
        if run["status"] != "ok":
            raise CoreError("speech-edit-invalid", reason="no-analysis")
        seg = self._segment(units.parse(owner)[0])
        if seg is None or seg["deleted"]:
            raise CoreError("speech-edit-invalid", reason="segment-deleted")
        return head, run, seg

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
        """编辑这段在这条轨上的音素时间 → 新的人工版本并成为当前头（之后的自动重跑不覆盖它，除非段改过）。只能改时间：行数、标签、顺序不变；
        前一个结束 ≤ 本个开始 < 本个结束 ≤ 范围终点（不重叠，允许空隙；句中停顿可以零长度）。版本变了要求重新载入；段改过之后不能在旧头上改。"""
        head, run, seg = self._head_full(owner)
        if int(head["version"]) != int(version):
            raise CoreError("speech-edit-conflict", expected=int(version), actual=int(head["version"]))
        if not units.content_matches(run, seg):
            raise CoreError("speech-edit-invalid", reason="segment-changed")
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
        with transaction(self.conn):
            self.conn.execute(
                "INSERT INTO measure_run(id, kind, owner_type, owner_id, asset_id, range_start, range_end, inputs, status, manual, result, created_at,"
                " span_start, span_end, seg_start, seg_end, seg_text) VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'ok', 1, ?, ?, ?, ?, ?, ?, ?)",
                (rid, KIND, OWNER, owner, run["asset_id"], run["range_start"], run["range_end"], dumps(inputs | {"manualOf": run["id"]}),
                 dumps(res | {"phones": out}), now_iso(), span[0] if span else None, span[1] if span else None,
                 run["seg_start"], run["seg_end"], run["seg_text"]),
            )
            self.conn.execute("UPDATE measure_head SET run_id=?, version=version+1 WHERE owner_type=? AND owner_id=? AND kind=?", (rid, OWNER, owner, KIND))
        self._changed([owner])
        return {"runId": rid, "version": int(head["version"]) + 1}

    def switch_head(self, owner: str, run_id: str, version: int) -> dict[str, Any]:
        """切换版本：在这段这条轨上、内容与段现在一致的成功版本（人工/模型）之间换当前头。"""
        head, _cur, seg = self._head_full(owner)
        if int(head["version"]) != int(version):
            raise CoreError("speech-edit-conflict", expected=int(version), actual=int(head["version"]))
        r = self.conn.execute("SELECT * FROM measure_run WHERE id=? AND owner_type=? AND owner_id=? AND kind=?", (run_id, OWNER, owner, KIND)).fetchone()
        if r is None or r["status"] != "ok":
            raise CoreError("speech-edit-invalid", reason="not-a-version")
        if not units.content_matches(r, seg):
            raise CoreError("speech-edit-invalid", reason="segment-changed")
        with transaction(self.conn):
            self.conn.execute("UPDATE measure_head SET run_id=?, version=version+1 WHERE owner_type=? AND owner_id=? AND kind=?", (run_id, OWNER, owner, KIND))
        self._changed([owner])
        return {"runId": run_id, "version": int(head["version"]) + 1}

    def samples_reading(self, owners: Iterable[str]) -> set[str]:
        """读到这些“段 + 资产”的采样：同一资产上判定区间与段正长度交叠的。"""
        out: set[str] = set()
        for o in owners:
            try:
                seg_id, asset_id = units.parse(o)
            except CoreError:
                continue
            seg = self._segment(seg_id)
            if seg is None:
                continue
            out |= {r[0] for r in self.conn.execute(
                "SELECT id FROM sample WHERE asset_id=? AND tag_judge_start < ? AND tag_judge_end > ?", (asset_id, seg["end"], seg["start"]))}
        return out

    def _changed(self, owners: Iterable[str]) -> None:
        """变更事件里 ``measure`` = “段 + 资产”与读到它们的采样，界面据此刷新。"""
        owners = list(owners)
        if self.on_change and owners:
            cs = ChangeSet()
            for o in owners:
                cs.add("measure", o)
            for sid in self.samples_reading(owners):
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
            "SELECT h.run_id, h.version, r.status, r.manual, r.inputs, r.seg_start, r.seg_end, r.seg_text FROM measure_head h JOIN measure_run r ON r.id=h.run_id"
            " WHERE h.owner_type=? AND h.owner_id=? AND h.kind=?",
            (OWNER, owner, KIND),
        ).fetchone()

    def _adopt(self, job: dict[str, Any], result: dict[str, Any]) -> None:
        params = loads(job["params"])
        items = {it["idx"]: it for it in params["items"]}
        rows = self.conn.execute("SELECT idx, status, error, result_ref FROM job_item WHERE job_id=? AND status IN ('ok', 'failed')", (job["id"],)).fetchall()
        item_dir = self.jobs.jobs_dir / job["id"] / "items"
        ver_now = self._versions()
        memo: dict[str, Any] = {}
        touched: list[str] = []
        ts = now_iso()
        with transaction(self.conn):
            for r in rows:
                it = items.get(r["idx"])
                if it is None or it.get("ownerType") != OWNER or not str(it.get("owner", "")).startswith("seg:"):
                    continue  # 旧格式（归属采样 / 字幕行 / 手输单元）的任务：不再登记
                owner = it["owner"]
                if self.conn.execute("SELECT 1 FROM sound_asset WHERE id=?", (it["asset"],)).fetchone() is None:
                    continue  # 资产在任务期间被删了：不登记
                inputs = {k: it.get(k) for k in ("name", "segment", "seg", "text", "textSource", "textVersion", "target", "window",
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
                seg = it.get("seg") or {}
                rid = new_id()
                self.conn.execute(
                    "INSERT INTO measure_run(id, kind, owner_type, owner_id, asset_id, range_start, range_end, inputs, status, manual, result, created_at,"
                    " span_start, span_end, seg_start, seg_end, seg_text) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 0, ?, ?, ?, ?, ?, ?, ?)",
                    (rid, KIND, OWNER, owner, it["asset"], it["target"][0], it["target"][1], dumps(inputs), status, dumps(res), ts,
                     span[0] if span else None, span[1] if span else None, seg.get("start"), seg.get("end"), seg.get("text")),
                )
                touched.append(owner)
                if status != "ok":
                    continue
                cur = self._segment(it["segment"])
                if cur is None or cur["deleted"] or not units.content_matches({"seg_start": seg.get("start"), "seg_end": seg.get("end"), "seg_text": seg.get("text")}, cur):
                    continue  # 段已删或内容在任务期间变了：只进历史
                head = self._head_row(owner)
                if head is not None:
                    if head["run_id"] != it.get("baseHead"):
                        continue  # 已被更新：只进历史
                    if head["manual"] and units.content_matches(head, cur):
                        continue  # 人工版本（且仍与段一致）：只进历史
                try:
                    now = self.unit_by_id(owner, memo)
                    changed = self._build(OWNER, owner, now["name"], now["asset"], now["target"][0], now["target"][1], now["txt"], ver_now, memo)["fingerprint"] != it["fingerprint"]
                except CoreError:
                    changed = True
                if changed:
                    continue  # 其他输入（辞典、音频……）在任务期间变了：只进历史
                self._set_head(owner, rid, head)
        with transaction(self.conn):
            self._adopt_f0(job["id"], result.get("f0") or [], ts)
        record_probes(self.conn, result.get("probes") or [])
        # 成功后清理私有中间文件（逐条结果已进库）；失败的任务不会走到这里，证据保留
        shutil.rmtree(self.jobs.jobs_dir / job["id"] / "cache", ignore_errors=True)
        if touched:
            self._changed(dict.fromkeys(touched))

    def _set_head(self, owner: str, run_id: str, head: sqlite3.Row | None) -> None:
        if head is None:
            self.conn.execute("INSERT INTO measure_head(owner_type, owner_id, kind, run_id, version) VALUES (?, ?, ?, ?, 1)", (OWNER, owner, KIND, run_id))
        else:
            self.conn.execute("UPDATE measure_head SET run_id=?, version=version+1 WHERE owner_type=? AND owner_id=? AND kind=?", (run_id, OWNER, owner, KIND))

    # ------------------------------------------------------------ 读取（无副作用）

    @staticmethod
    def _run_wire(r: sqlite3.Row, version: int) -> dict[str, Any]:
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

    def _segment_view(self, seg: sqlite3.Row, asset_id: str, ordinal: int, start: float, end: float, snap: dict[str, Any] | None,
                      memo: dict[str, Any]) -> dict[str, Any]:
        """一段在采样所在资产上的分析：可用版本、实际的当前头、全部版本、状态（ok / stale 段改过 / failed / none / other-sound 文件变了）。"""
        uid = units.unit_id(seg["id"], asset_id)
        runs = self._runs(uid)
        head = self.conn.execute("SELECT run_id, version FROM measure_head WHERE owner_type=? AND owner_id=? AND kind=?", (OWNER, uid, KIND)).fetchone()
        use = units.pick_usable(runs, seg, head["run_id"] if head else None)
        state = "ok"
        if use is not None and (snap is None or (loads(use["inputs"]).get("audio") or {}).get("snapshot") != snap):
            use, state = None, "other-sound"  # 文件内容不同：不读（R11.10）
        elif use is None:
            oks = [r for r in runs if r["status"] == "ok"]
            state = "stale" if oks else ("failed" if runs else "none")
        try:
            target = list(units.seg_target(float(seg["start"]), float(seg["end"]), self._asset(asset_id, memo)["mapping"],
                                           float(self._asset(asset_id, memo)["duration"])) or []) or None
        except CoreError:
            target = None
        cur = next((r for r in runs if head is not None and r["id"] == head["run_id"]), None)
        span = (float(use["span_start"]), float(use["span_end"])) if use is not None and use["span_start"] is not None else None
        return {
            "unitId": uid, "segmentId": seg["id"], "ordinal": ordinal, "name": (seg["text"] or "").replace("\n", " "), "text": seg["text"],
            "speakers": loads(seg["speakers"]), "target": target, "state": state, "partial": units.partial(span, start, end),
            "head": self._run_wire(use, head["version"] if head and use["id"] == head["run_id"] else 0) if use is not None else None,
            "current": self._run_wire(cur, head["version"]) if cur is not None and head is not None else None,
            "headVersion": int(head["version"]) if head else 0,
            "runs": [
                {
                    "id": r["id"], "status": r["status"], "manual": bool(r["manual"]), "createdAt": r["created_at"],
                    "error": (loads(r["result"]) or {}).get("error") if r["status"] != "ok" and r["result"] else None, "text": loads(r["inputs"]).get("text"),
                    "matches": units.content_matches(r, seg),
                }
                for r in runs
            ],
        }

    def reading(self, s: sqlite3.Row) -> dict[str, Any]:
        """采样读到的段（所有者 2026-10-09）：判定区间正长度交叠的所有段在采样所在资产上的分析。
        任何一段没有可用分析 → ``blocked``（缺哪段 / 哪段改过），``head`` 为 None；两段的非停顿音素在采样范围内交叠 → ``conflict``；
        否则 ``head`` = 合成的结果（音素裁到采样范围，被裁掉一部分的非停顿音素标 clipped / ◐）。"""
        memo: dict[str, Any] = {}
        start, end = float(s["start"]), float(s["end"])
        asset = self._asset(s["asset_id"], memo)
        judge = self.judge_of(s, memo)
        segs = self.read_segments(asset["source_id"], *judge) if judge else []
        base = {"judge": list(judge) if judge else None, "head": None, "conflict": None, "blocked": None}
        if not segs:
            return base | {"text": None, "textSource": None, "reason": "no-text", "units": []}
        ords = self.ordinals(asset["source_id"], [t["id"] for t in segs])
        snap = self._snapshot(s["asset_id"], start, end)
        views = [self._segment_view(t, s["asset_id"], ords.get(t["id"], 0), start, end, snap, memo) for t in segs]
        text = " ".join(v["name"] for v in views)
        out = base | {"text": text, "textSource": "segments", "reason": None, "units": views}
        bad = [v for v in views if v["head"] is None]
        if bad:
            stale = [v for v in bad if v["state"] == "stale"]
            pick = stale or bad
            out["blocked"] = {"code": "rhythm-segment-stale" if stale else "rhythm-segments-missing",
                              "args": {"segments": ", ".join(str(v["ordinal"]) for v in pick), "n": len(pick)}}
            return out
        merged = units.merge([{"unitId": v["unitId"], "ordinal": v["ordinal"], "result": v["head"]["result"]} for v in views], start, end)
        if "conflict" in merged:
            c = merged["conflict"]
            try:
                m = Mapping.of(asset["mapping"])
                a, b = m.to_source(c["start"]), m.to_source(c["end"])
            except CoreError:
                a, b = c["start"], c["end"]
            out["conflict"] = {"a": c["a"], "b": c["b"], "start": round(a, 3), "end": round(b, 3), "units": c["units"]}
            out["blocked"] = {"code": "rhythm-units-conflict", "args": {"a": c["a"], "b": c["b"], "start": round(a, 3), "end": round(b, 3)}}
            return out
        hs = [v["head"] for v in views]
        out["head"] = {
            "runId": "+".join(h["runId"] for h in hs), "version": sum(int(v["headVersion"]) for v in views), "status": "ok",
            "manual": any(h["manual"] for h in hs), "createdAt": max(h["createdAt"] for h in hs),
            "text": text, "textSource": "segments", "window": [start, end], "result": merged,
            "units": [v["unitId"] for v in views], "partial": any(p.get("clipped") for p in merged["phones"]),
        }
        return out

    def sample_view(self, sample_id: str) -> dict[str, Any]:
        """舞台语音面板：采样读到的段（各自在这条轨上的可用分析、当前头与全部版本）、合成的结果、判定区间。"""
        s = self.conn.execute(f"SELECT {self._SAMPLE_COLS} FROM sample WHERE id=?", (sample_id,)).fetchone()
        if s is None:
            raise CoreError("sample-not-found", id=sample_id)
        return {"sampleId": sample_id, **self.reading(s)}

    def for_asset(self, asset_id: str, start: float, end: float) -> list[dict[str, Any]]:
        """原片视口的音素层（08 §8.8）：这条资产上各段的可用分析（同一物理声音）；读取没有副作用。时间：资产局部秒。"""
        asset = assets_mod.get(self.conn, asset_id)
        try:
            _, _, media = assets_mod.locate(self.conn, self.ws.root, asset, max(0.0, start), min(float(asset["duration"]), end))
            snap = {k: (media["snapshot"] or {}).get(k) for k in ("size", "mtime_ns")}
            m = Mapping.of(asset["mapping"])
            a, b = m.to_source(max(0.0, start)), m.to_source(min(float(asset["duration"]), end))
        except CoreError:
            return []
        segs = self.read_segments(asset["source_id"], a, b)
        ords = self.ordinals(asset["source_id"], [t["id"] for t in segs])
        out = []
        for t in segs:
            uid = units.unit_id(t["id"], asset_id)
            r = self.usable_run(uid, t)
            if r is None or (loads(r["inputs"]).get("audio") or {}).get("snapshot") != snap:
                continue  # 没有可用分析或文件指纹不同 → 不显示（R11.10）
            res = loads(r["result"])
            out.append({
                "unitId": uid, "segmentId": t["id"], "ordinal": ords.get(t["id"], 0), "name": (t["text"] or "").replace("\n", " "),
                "runId": r["id"], "manual": bool(r["manual"]),
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
            "SELECT j.idx, j.target, j.status, j.error FROM job_item j WHERE j.job_id=? ORDER BY j.status='skipped', j.idx", (job_id,)
        )
        out = []
        for r in rows:
            otype, pname = names.get(r["target"], (None, None))
            is_seg = str(r["target"]).startswith("seg:")
            out.append({"idx": r["idx"], "unitId": r["target"] if is_seg else None, "sampleId": None, "name": pname, "status": r["status"],
                        "error": loads(r["error"]) if r["error"] else None, "deleted": False})
        return out

    def source_counts(self, source_id: str) -> dict[str, int]:
        """原片页「准备」里的语音分析一行：原片入口范围内（默认人声轨或原混音上、不在 OP/ED 里）的段数与有可用分析的段数。"""
        blocked: list[dict[str, Any]] = []
        found = self._source_units([source_id], None, {}, blocked)
        done = 0
        for u in found.values():
            seg = self._segment(u["segment"])
            if seg is not None and self.usable_run(u["unitId"], seg) is not None:
                done += 1
        return {"speech": len(found), "analyzed": done}

    def analyzed_counts(self, source_id: str | None = None) -> dict[str, dict[str, int]]:
        """每个原片：语音性质采样数与“已分析”（读到的段都有可用分析，含 ◐）数。"""
        q = (
            f"SELECT a.source_id, COUNT(*), SUM(CASE WHEN {units.state_sql('s', 'a.source_id')} IN ('ok', 'manual', 'partial') THEN 1 ELSE 0 END)"
            " FROM sample s JOIN sound_asset a ON a.id=s.asset_id WHERE s.nature='speech'"
        )
        args: list[Any] = []
        if source_id:
            q += " AND a.source_id=?"
            args.append(source_id)
        q += " GROUP BY a.source_id"
        return {r[0]: {"speech": int(r[1]), "analyzed": int(r[2] or 0)} for r in self.conn.execute(q, args)}
