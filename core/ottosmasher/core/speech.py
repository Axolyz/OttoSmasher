"""语音分析（规格 08 §8.1–§8.4、§8.8）：Core 侧——选范围、冻结输入、复用判断、提交任务、采纳结果、读取测量。

- 一个操作、统一复用规则：输入（对齐文本版本、辞典版本、前端版本、模型版本、目标区间、容差、输入音频身份）与当前头完全相同 → 跳过；
  任何不同 → 重跑。确认框写清“将分析 M 条；N 条已是最新，跳过；K 条无法处理（原因）”。
- 音频 = 采样实际绑定的资产（不触发分离、不换音源、不改绑）；目标 = 采样选区，窗口 = 目标两侧各扩展容差，只在同一物理声音（存放目标的那段存储）内扩展，记录请求与实际扩展量、是否被截短。
- 采纳（按顺序）：任务取消 → 不写（采纳函数不会被调用）；输入在任务期间变了 → 只进历史；当前头是人工版本或已被更新 → 只进历史；否则成为新的当前头。
  失败结果只进历史，旧的成功结果不会“消失”。
- 读取测量没有副作用。
时钟：测量里的音素时间都是资产局部秒；采样的 start/end 也是资产局部秒；文本快照里的 start/end 是原片秒。
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
from ..domain.overlap import overlaps
from ..lang.ja import dictionary as dict_mod
from ..lang.ja import frontend as fe_mod
from ..lang.ja import openjtalk as oj_mod
from ..models import domino, f0store, fcpe, registry
from ..store.db import transaction
from ..store.workspace import Workspace
from . import assets as assets_mod
from . import settings as settings_mod
from .clock import new_id, now_iso
from .edits import ChangeSet, dumps, loads
from .probes import record_probes
from .errors import CoreError

KIND = "alignment"
JOB_KIND = "speech.analyze"
BLOCKED_LIST_MAX = 50


def _sha(obj: Any) -> str:
    return hashlib.sha256(json.dumps(obj, sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode("utf-8")).hexdigest()


class SpeechService:
    def __init__(self, conn: sqlite3.Connection, ws: Workspace, jobs: Any, support_dir: Path, on_change: Callable[[ChangeSet], None] | None = None) -> None:
        self.conn = conn
        self.ws = ws
        self.jobs = jobs
        self.support_dir = support_dir
        self.on_change = on_change
        jobs.adopters[JOB_KIND] = self._adopt

    # ------------------------------------------------------------ 对齐文本（08 §8.2.1）

    def text_of(self, s: sqlite3.Row) -> dict[str, Any]:
        """人工对齐文本 > 字幕行的对齐文本（人工 > 自动）> 采样文本快照。没有 → reason。"""
        manual = (s["align_text_manual"] or "").strip()
        origin = loads(s["origin"]) if s["origin"] else None
        ann = None
        if origin and origin.get("kind") == "subtitle" and origin.get("annotation"):
            ann = self.conn.execute("SELECT align_text_auto, align_text_manual, deleted FROM annotation WHERE id=?", (origin["annotation"],)).fetchone()
        auto = (ann["align_text_auto"] or "").strip() if ann is not None else ""
        if manual:
            text, source = manual, "sample-manual"
        elif ann is not None and (ann["align_text_manual"] or "").strip():
            text, source = ann["align_text_manual"].strip(), "line-manual"
        elif auto:
            text, source = auto, "line-auto"
        else:
            snap = loads(s["text_snapshot"]) if s["text_snapshot"] else {}
            text, source = (snap.get("alignText") or "").strip(), "snapshot"
        if not text:
            parent_has_text = False
            if s["parent_sample_id"]:
                p = self.conn.execute("SELECT origin, text_snapshot, align_text_manual FROM sample WHERE id=?", (s["parent_sample_id"],)).fetchone()
                parent_has_text = p is not None and bool((p["align_text_manual"] or "").strip() or p["origin"] or p["text_snapshot"])
            return {"text": None, "reason": "range-differs" if parent_has_text else "no-text"}
        return {"text": text, "source": source, "version": hashlib.sha256(text.encode("utf-8")).hexdigest()[:16], "equalsSubtitle": bool(auto) and text == auto}

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

    def item_for(self, s: sqlite3.Row, ver: dict[str, Any], memo: dict[str, Any] | None = None) -> dict[str, Any]:
        """一个采样的冻结输入；处理不了抛 CoreError（原因进 K）。"""
        txt = self.text_of(s)
        if txt["text"] is None:
            raise CoreError("speech-blocked", reason=txt["reason"])
        return self._build("sample", s["id"], s["name"], s["asset_id"], float(s["start"]), float(s["end"]), txt, ver, memo)

    @staticmethod
    def range_owner(asset_id: str, start: float, end: float) -> str:
        """“资产选区 + 文字区段”的测量归属（不需要采样，08 §8.4 第三个入口）：同一资产同一区间是同一个归属。"""
        return hashlib.sha256(f"{asset_id}|{round(start, 6)}|{round(end, 6)}".encode()).hexdigest()[:32]

    def item_for_range(self, asset_id: str, start: float, end: float, text: str, ver: dict[str, Any], memo: dict[str, Any] | None = None) -> dict[str, Any]:
        text = text.strip()
        if not text:
            raise CoreError("speech-blocked", reason="no-text")
        txt = {"text": text, "source": "selection", "version": hashlib.sha256(text.encode("utf-8")).hexdigest()[:16], "equalsSubtitle": False}
        return self._build("asset_text", self.range_owner(asset_id, start, end), text, asset_id, start, end, txt, ver, memo)

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

    # ------------------------------------------------------------ 范围与计划

    _SAMPLE_COLS = 'id, asset_id, start, "end", name, nature, align_text_manual, origin, text_snapshot, parent_sample_id'

    def _samples(self, ids: Iterable[str]) -> list[sqlite3.Row]:
        ids = list(dict.fromkeys(ids))
        out = []
        for i in range(0, len(ids), 500):
            chunk = ids[i : i + 500]
            rows = {r["id"]: r for r in self.conn.execute(f"SELECT {self._SAMPLE_COLS} FROM sample WHERE id IN ({','.join('?' * len(chunk))})", chunk)}
            out += [rows[x] for x in chunk if x in rows]
        return out

    def _source_scope(self, source_ids: Iterable[str]) -> list[sqlite3.Row]:
        """原片入口的默认范围：性质为语音、有对齐文本、原字幕区间不与已确认 OP/ED 正长度交叠的采样（08 §8.4）。"""
        out = []
        for sid in dict.fromkeys(source_ids):
            opeds = [(r[0], r[1]) for r in self.conn.execute('SELECT start, "end" FROM oped WHERE source_id=? AND deleted=0', (sid,))]
            rows = self.conn.execute(
                f"SELECT {', '.join('s.' + c.strip() for c in self._SAMPLE_COLS.split(','))} FROM sample s JOIN sound_asset a ON a.id=s.asset_id"
                " WHERE a.source_id=? AND s.nature='speech' ORDER BY s.start, s.rowid",
                (sid,),
            )
            for r in rows:
                if self.text_of(r)["text"] is None:
                    continue
                snap = loads(r["text_snapshot"]) if r["text_snapshot"] else {}
                if "start" in snap and any(overlaps(snap["start"], snap["end"], a, b) for a, b in opeds):
                    continue
                out.append(r)
        return out

    def plan(self, entry: str, ids: list[str], rerun_fresh: bool) -> dict[str, Any]:
        if entry not in ("source", "samples"):
            raise CoreError("speech-invalid", reason="not-an-option", field="entry")
        rows = self._source_scope(ids) if entry == "source" else self._samples(ids)
        ver = self._versions()
        run: list[dict[str, Any]] = []
        fresh: list[dict[str, Any]] = []
        blocked: list[dict[str, Any]] = []
        mix = 0
        memo: dict[str, Any] = {}
        for r in rows:
            try:
                it = self.item_for(r, ver, memo)
            except CoreError as e:
                blocked.append({"id": r["id"], "name": r["name"], "reason": e.args_.get("reason") if e.code == "speech-blocked" else e.code})
                continue
            roles = self.conn.execute("SELECT COUNT(*) FROM asset_role WHERE asset_id=? AND state='on'", (it["asset"],)).fetchone()[0]
            origin = self.conn.execute("SELECT origin FROM sound_asset WHERE id=?", (it["asset"],)).fetchone()[0]
            if origin == "stream" or roles == 0:
                mix += 1
            head = self._head_row(r["id"])
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
        """对“资产选区 + 文字区段”做语音分析（详情里的局部分析；不需要先保存采样）。复用规则相同；人工版本保护相同。"""
        asset = assets_mod.get(self.conn, asset_id)
        from ..domain.mapping import check_range

        start, end = check_range(float(start), float(end), float(asset["duration"]), frame=1.0 / assets_mod.rate_of(self.conn, asset))
        ver = self._versions()
        it = self.item_for_range(asset_id, start, end, text, ver)
        head = self._head_row(it["owner"], "asset_text")
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
        affects = {"sample": [it["sample"] for it in items if it["sample"]], "asset": sorted({it["asset"] for it in items})}
        job = self.jobs.submit(JOB_KIND, params, affects)
        self.jobs.add_items(job["id"], [(it["owner"], "queued") for it in items] + [(it["owner"], "skipped") for it in fresh])
        return self.jobs.summary(job["id"])

    # ------------------------------------------------------------ 人工修正（08 §8.7）

    def _head_full(self, owner: str, owner_type: str) -> tuple[sqlite3.Row, sqlite3.Row]:
        head = self.conn.execute("SELECT * FROM measure_head WHERE owner_type=? AND owner_id=? AND kind=?", (owner_type, owner, KIND)).fetchone()
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

    def save_manual(self, owner: str, version: int, phones: list[dict[str, Any]] | None, text: str | None, owner_type: str = "sample") -> dict[str, Any]:
        """编辑音素时间 → 新的人工版本并成为当前头（之后的自动重跑不覆盖它）。只能改时间：行数、标签、顺序不变；
        前一个结束 ≤ 本个开始 < 本个结束 ≤ 范围终点（不重叠，允许空隙；句中停顿可以零长度）。版本变了要求重新载入。"""
        head, run = self._head_full(owner, owner_type)
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
        with transaction(self.conn):
            self.conn.execute(
                "INSERT INTO measure_run(id, kind, owner_type, owner_id, asset_id, range_start, range_end, inputs, status, manual, result, created_at)"
                " VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'ok', 1, ?, ?)",
                (rid, KIND, owner_type, owner, run["asset_id"], run["range_start"], run["range_end"], dumps(inputs | {"manualOf": run["id"]}),
                 dumps(res | {"phones": out}), now_iso()),
            )
            self.conn.execute("UPDATE measure_head SET run_id=?, version=version+1 WHERE owner_type=? AND owner_id=? AND kind=?", (rid, owner_type, owner, KIND))
        self._changed(owner)
        return {"runId": rid, "version": int(head["version"]) + 1}

    def switch_head(self, owner: str, run_id: str, version: int, owner_type: str = "sample") -> dict[str, Any]:
        """切换版本：在同一归属的历史成功版本（人工/模型）之间换当前头。"""
        head, _ = self._head_full(owner, owner_type)
        if int(head["version"]) != int(version):
            raise CoreError("speech-edit-conflict", expected=int(version), actual=int(head["version"]))
        r = self.conn.execute("SELECT status FROM measure_run WHERE id=? AND owner_type=? AND owner_id=? AND kind=?", (run_id, owner_type, owner, KIND)).fetchone()
        if r is None or r["status"] != "ok":
            raise CoreError("speech-edit-invalid", reason="not-a-version")
        with transaction(self.conn):
            self.conn.execute("UPDATE measure_head SET run_id=?, version=version+1 WHERE owner_type=? AND owner_id=? AND kind=?", (run_id, owner_type, owner, KIND))
        self._changed(owner)
        return {"runId": run_id, "version": int(head["version"]) + 1}

    def _changed(self, owner: str) -> None:
        if self.on_change:
            cs = ChangeSet()
            cs.add("measure", owner)
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
        for e in entries:
            src = self.jobs.jobs_dir / job_id / "f0" / e["asset"]
            if self.conn.execute("SELECT 1 FROM sound_asset WHERE id=?", (e["asset"],)).fetchone() is None:
                continue
            for k in e["chunks"]:
                f0store.adopt_chunk(self.ws.f0, e["asset"], e["identity"], int(k), src / f"{k}.npy", {"model": self.f0_sha(), "frontend": fcpe.FRONTEND_VERSION})
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

    def f0(self, asset_id: str, start: float, end: float) -> dict[str, Any]:
        """资产区间的 F0 帧（读取没有副作用）；没测的帧标 missing。时间：资产局部秒，第一帧的中心为 ``t0``。"""
        asset = assets_mod.get(self.conn, asset_id)
        dur = float(asset["duration"])
        if not (0 <= start < end <= dur + 1e-6):
            raise CoreError("range-invalid", reason="out-of-bounds", start=start, end=end, duration=dur)
        ref, win, media = assets_mod.locate(self.conn, self.ws.root, asset, start, min(end, dur))
        audio = {
            "asset": asset["id"], "mapping": asset["mapping"], "media": media["media_file_id"],
            "snapshot": {k: (media["snapshot"] or {}).get(k) for k in ("size", "mtime_ns")}, "ordinal": ref.ordinal,
            "storage": [win.local_start, win.local_end, win.file_start],
        }
        ident = f0store.identity(audio, self.f0_sha())
        i0, frames, have = f0store.read(self.ws.f0, asset_id, ident, start, min(end, dur), dur)
        return {
            "t0": (i0 * fcpe.HOP + fcpe.HOP / 2) / fcpe.SR, "step": fcpe.HOP / fcpe.SR, "count": len(frames),
            "f0": frames[:, 0].astype("<f4").tobytes(), "confidence": frames[:, 1].astype("<f4").tobytes(), "energy": frames[:, 2].astype("<f4").tobytes(),
            "measured": int(have.sum()),
        }

    # ------------------------------------------------------------ 采纳

    def _head_row(self, owner: str, owner_type: str = "sample") -> sqlite3.Row | None:
        return self.conn.execute(
            "SELECT h.run_id, h.version, r.status, r.manual, r.inputs FROM measure_head h JOIN measure_run r ON r.id=h.run_id"
            " WHERE h.owner_type=? AND h.owner_id=? AND h.kind=?",
            (owner_type, owner, KIND),
        ).fetchone()

    def _adopt(self, job: dict[str, Any], result: dict[str, Any]) -> None:
        params = loads(job["params"])
        items = {it["idx"]: it for it in params["items"]}
        rows = self.conn.execute("SELECT idx, status, error, result_ref FROM job_item WHERE job_id=? AND status IN ('ok', 'failed')", (job["id"],)).fetchall()
        item_dir = self.jobs.jobs_dir / job["id"] / "items"
        ver_now = self._versions()
        memo: dict[str, Any] = {}
        cs = ChangeSet()
        ts = now_iso()
        with transaction(self.conn):
            for r in rows:
                it = items.get(r["idx"])
                if it is None:
                    continue
                otype, owner = it.get("ownerType", "sample"), it.get("owner") or it["sample"]
                if otype == "sample":
                    s = self.conn.execute(f"SELECT {self._SAMPLE_COLS} FROM sample WHERE id=?", (owner,)).fetchone()
                    if s is None or s["asset_id"] != it["asset"]:
                        continue  # 采样在任务期间被删了或换了绑定：不登记
                elif self.conn.execute("SELECT 1 FROM sound_asset WHERE id=?", (it["asset"],)).fetchone() is None:
                    continue
                inputs = {k: it[k] for k in ("text", "textSource", "textVersion", "equalsSubtitle", "target", "window", "requested", "actual", "truncated", "audio", "fingerprint")}
                inputs |= {"versions": params["versions"], "device": loads(job["device"]), "job": job["id"]}
                if r["status"] == "ok":
                    res = json.loads((item_dir / r["result_ref"]).read_text(encoding="utf-8"))
                    status = "ok"
                else:
                    res = {"error": loads(r["error"]) if r["error"] else None}
                    status = "failed"
                rid = new_id()
                self.conn.execute(
                    "INSERT INTO measure_run(id, kind, owner_type, owner_id, asset_id, range_start, range_end, inputs, status, manual, result, created_at)"
                    " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 0, ?, ?)",
                    (rid, KIND, otype, owner, it["asset"], it["target"][0], it["target"][1], dumps(inputs), status, dumps(res), ts),
                )
                cs.add("measure", owner)
                if status != "ok":
                    continue
                head = self._head_row(owner, otype)
                if head is not None and (head["manual"] or head["run_id"] != it.get("baseHead")):
                    continue  # 人工版本或已被更新：只进历史
                try:
                    now = (
                        self.item_for(s, ver_now, memo)
                        if otype == "sample"
                        else self.item_for_range(it["asset"], it["target"][0], it["target"][1], it["text"], ver_now, memo)
                    )
                    changed = now["fingerprint"] != it["fingerprint"]
                except CoreError:
                    changed = True
                if changed:
                    continue  # 输入在任务期间变了：只进历史
                self._set_head(owner, rid, head, otype)
        with transaction(self.conn):
            self._adopt_f0(job["id"], result.get("f0") or [], ts)
        record_probes(self.conn, result.get("probes") or [])
        # 成功后清理私有中间文件（逐条结果已进库）；失败的任务不会走到这里，证据保留
        shutil.rmtree(self.jobs.jobs_dir / job["id"] / "cache", ignore_errors=True)
        if cs.entities and self.on_change:
            self.on_change(cs)

    def _set_head(self, owner: str, run_id: str, head: sqlite3.Row | None, owner_type: str = "sample") -> None:
        if head is None:
            self.conn.execute("INSERT INTO measure_head(owner_type, owner_id, kind, run_id, version) VALUES (?, ?, ?, ?, 1)", (owner_type, owner, KIND, run_id))
        else:
            self.conn.execute(
                "UPDATE measure_head SET run_id=?, version=version+1 WHERE owner_type=? AND owner_id=? AND kind=?", (run_id, owner_type, owner, KIND)
            )

    # ------------------------------------------------------------ 读取（无副作用）

    def sample_view(self, sample_id: str) -> dict[str, Any]:
        """舞台语音面板：对齐文本现状、当前头（含音素）、同一采样的全部版本（新的在前）。"""
        s = self.conn.execute(f"SELECT {self._SAMPLE_COLS} FROM sample WHERE id=?", (sample_id,)).fetchone()
        if s is None:
            raise CoreError("sample-not-found", id=sample_id)
        txt = self.text_of(s)
        runs = self.conn.execute(
            "SELECT id, status, manual, created_at, inputs, result FROM measure_run WHERE owner_type='sample' AND owner_id=? AND kind=? ORDER BY created_at DESC, rowid DESC",
            (sample_id, KIND),
        ).fetchall()
        head = self._head_row(sample_id)
        head_obj = None
        if head is not None:
            r = next(x for x in runs if x["id"] == head["run_id"])
            inp = loads(r["inputs"])
            head_obj = {
                "runId": r["id"], "version": head["version"], "status": r["status"], "manual": bool(r["manual"]), "createdAt": r["created_at"],
                "text": inp.get("text"), "textSource": inp.get("textSource"), "window": inp.get("window"), "result": loads(r["result"]) if r["status"] == "ok" else None,
                "projectedFrom": None,
            }
        else:
            head_obj = self._projection(s)
        out_runs = []
        for r in runs:
            res = loads(r["result"]) if r["result"] else {}
            out_runs.append({
                "id": r["id"], "status": r["status"], "manual": bool(r["manual"]), "createdAt": r["created_at"],
                "error": res.get("error") if r["status"] != "ok" else None, "text": loads(r["inputs"]).get("text"),
            })
        return {
            "sampleId": sample_id, "text": txt["text"], "textSource": txt.get("source"), "reason": txt.get("reason"),
            "head": head_obj, "runs": out_runs,
        }

    def _projection(self, s: sqlite3.Row) -> dict[str, Any] | None:
        """子采样（截取）自己没有测量时，用覆盖它、属于同一物理声音的成功测量的投影（08 §8.8）；处理过的声音不借用（它们是别的资产）。"""
        start, end = float(s["start"]), float(s["end"])
        rows = self.conn.execute(
            "SELECT h.owner_type, h.owner_id, h.version, r.id, r.manual, r.created_at, r.inputs, r.result FROM measure_head h JOIN measure_run r ON r.id=h.run_id"
            " WHERE h.kind='alignment' AND r.status='ok' AND r.asset_id=? AND r.range_start <= ? AND r.range_end >= ? ORDER BY (r.range_end - r.range_start), r.created_at DESC",
            (s["asset_id"], start + 1e-6, end - 1e-6),
        ).fetchall()
        for r in rows:
            inp = loads(r["inputs"])
            try:
                _, _, _, media = self._locate(s["asset_id"], start, end, None)
            except CoreError:
                return None
            if (inp.get("audio") or {}).get("snapshot") != {k: (media["snapshot"] or {}).get(k) for k in ("size", "mtime_ns")}:
                continue
            res = loads(r["result"])
            phones = [p | {"start": max(p["start"], start), "end": min(p["end"], end)} for p in res["phones"] if p["end"] > start and p["start"] < end]
            return {
                "runId": r["id"], "version": r["version"], "status": "ok", "manual": bool(r["manual"]), "createdAt": r["created_at"],
                "text": inp.get("text"), "textSource": inp.get("textSource"), "window": inp.get("window"), "result": res | {"phones": phones},
                "projectedFrom": r["owner_id"],
            }
        return None

    def for_asset(self, asset_id: str, start: float, end: float) -> list[dict[str, Any]]:
        """原片视口的音素层（08 §8.8）：这个资产上各采样当前头的成功测量，只取同一物理声音（文件快照一致）的；读取没有副作用。时间：资产局部秒。"""
        asset = assets_mod.get(self.conn, asset_id)
        try:
            _, _, media = assets_mod.locate(self.conn, self.ws.root, asset, max(0.0, start), min(float(asset["duration"]), end))
            snap = {k: (media["snapshot"] or {}).get(k) for k in ("size", "mtime_ns")}
        except CoreError:
            return []
        rows = self.conn.execute(
            "SELECT h.owner_type, h.owner_id, r.id, r.manual, r.inputs, r.result, r.range_start, r.range_end FROM measure_head h JOIN measure_run r ON r.id=h.run_id"
            " WHERE h.kind='alignment' AND r.asset_id=? AND r.status='ok' AND r.range_end > ? AND r.range_start < ? ORDER BY r.range_start",
            (asset_id, start, end),
        )
        out = []
        for r in rows:
            inp = loads(r["inputs"])
            if (inp.get("audio") or {}).get("snapshot") != snap:
                continue  # 文件指纹不同 → 不显示（R11.10）
            res = loads(r["result"])
            out.append({"sampleId": r["owner_id"] if r["owner_type"] == "sample" else None, "runId": r["id"], "manual": bool(r["manual"]), "phones": [{"label": p["label"], "start": p["start"], "end": p["end"]} for p in res["phones"]]})
        return out

    def results(self, job_id: str) -> list[dict[str, Any]]:
        job = self.conn.execute("SELECT params FROM job WHERE id=?", (job_id,)).fetchone()
        if job is None:
            raise CoreError("job-not-found", id=job_id)
        names = {it["owner"]: (it.get("ownerType", "sample"), it["name"]) for it in loads(job["params"]).get("items", []) if it.get("owner")}
        rows = self.conn.execute(
            "SELECT j.idx, j.target, j.status, j.error, s.name FROM job_item j LEFT JOIN sample s ON s.id=j.target WHERE j.job_id=? ORDER BY j.status='skipped', j.idx",
            (job_id,),
        )
        out = []
        for r in rows:
            otype, pname = names.get(r["target"], ("sample", None))
            is_sample = otype == "sample"
            out.append({
                "idx": r["idx"], "sampleId": r["target"] if is_sample else None, "name": r["name"] if is_sample else pname,
                "status": r["status"], "error": loads(r["error"]) if r["error"] else None, "deleted": is_sample and r["name"] is None,
            })
        return out

    def analyzed_counts(self, source_id: str | None = None) -> dict[str, dict[str, int]]:
        """每个原片：语音性质采样数与“已分析”（当前头为成功测量）数。"""
        q = (
            "SELECT a.source_id, COUNT(*), SUM(CASE WHEN r.status='ok' THEN 1 ELSE 0 END) FROM sample s JOIN sound_asset a ON a.id=s.asset_id"
            " LEFT JOIN measure_head h ON h.owner_type='sample' AND h.owner_id=s.id AND h.kind='alignment'"
            " LEFT JOIN measure_run r ON r.id=h.run_id WHERE s.nature='speech'"
        )
        args: list[Any] = []
        if source_id:
            q += " AND a.source_id=?"
            args.append(source_id)
        q += " GROUP BY a.source_id"
        return {r[0]: {"speech": int(r[1]), "analyzed": int(r[2] or 0)} for r in self.conn.execute(q, args)}
