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

from ..domain.overlap import overlaps
from ..lang.ja import dictionary as dict_mod
from ..lang.ja import frontend as fe_mod
from ..lang.ja import openjtalk as oj_mod
from ..models import domino, registry
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

    def item_for(self, s: sqlite3.Row, ver: dict[str, Any]) -> dict[str, Any]:
        """一个采样的冻结输入；处理不了抛 CoreError（原因进 K）。"""
        txt = self.text_of(s)
        if txt["text"] is None:
            raise CoreError("speech-blocked", reason=txt["reason"])
        asset = assets_mod.get(self.conn, s["asset_id"])
        start, end = float(s["start"]), float(s["end"])
        ref, win, media = assets_mod.locate(self.conn, self.ws.root, asset, start, end)
        assets_mod.check_media(media)  # 文件缺失或被改动 → 明确报错（进 K），不回退别的轨
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
            "sample": s["id"], "asset": asset["id"], "name": s["name"],
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
        for r in rows:
            try:
                it = self.item_for(r, ver)
            except CoreError as e:
                blocked.append({"id": r["id"], "name": r["name"], "reason": e.args_.get("reason") if e.code == "speech-blocked" else e.code})
                continue
            roles = self.conn.execute("SELECT COUNT(*) FROM asset_role WHERE asset_id=? AND state='on'", (it["asset"],)).fetchone()[0]
            origin = self.conn.execute("SELECT origin FROM sound_asset WHERE id=?", (it["asset"],)).fetchone()[0]
            if origin == "stream" or roles == 0:
                mix += 1
            head = self._head_row(r["id"])
            it["baseHead"] = head["run_id"] if head else None
            if head is not None and head["status"] == "ok" and loads(head["inputs"]).get("fingerprint") == it["fingerprint"] and not rerun_fresh:
                fresh.append(it)
            else:
                run.append(it)
        return {"run": run, "fresh": fresh, "blocked": blocked, "mix": mix, "versions": ver}

    def preview(self, entry: str, ids: list[str], rerun_fresh: bool) -> dict[str, Any]:
        p = self.plan(entry, ids, rerun_fresh)
        return {
            "run": len(p["run"]), "fresh": len(p["fresh"]), "blocked": len(p["blocked"]),
            "blockedList": p["blocked"][:BLOCKED_LIST_MAX], "mixBound": p["mix"], "freshAll": len(self.plan(entry, ids, False)["fresh"]) if rerun_fresh else len(p["fresh"]),
        }

    def submit(self, entry: str, ids: list[str], rerun_fresh: bool) -> dict[str, Any]:
        p = self.plan(entry, ids, rerun_fresh)
        if not p["run"]:
            raise CoreError("speech-nothing-to-do", fresh=len(p["fresh"]), blocked=len(p["blocked"]))
        ver = p["versions"]
        items = []
        for i, it in enumerate(p["run"]):
            items.append({**it, "idx": i})
        params = {
            "items": items,
            "dictionary": {"path": ver["dictionaryPath"], "version": ver["dictionary"]},
            "versions": {k: v for k, v in ver.items() if k != "dictionaryPath"},
            "models_dir": str(self.ws.models),
            "support_dir": str(self.support_dir),
        }
        affects = {"sample": [it["sample"] for it in items]}
        job = self.jobs.submit(JOB_KIND, params, affects)
        self.jobs.add_items(job["id"], [(it["sample"], "queued") for it in items] + [(it["sample"], "skipped") for it in p["fresh"]])
        return self.jobs.summary(job["id"])

    # ------------------------------------------------------------ 采纳

    def _head_row(self, sample_id: str) -> sqlite3.Row | None:
        return self.conn.execute(
            "SELECT h.run_id, h.version, r.status, r.manual, r.inputs FROM measure_head h JOIN measure_run r ON r.id=h.run_id"
            " WHERE h.owner_type='sample' AND h.owner_id=? AND h.kind=?",
            (sample_id, KIND),
        ).fetchone()

    def _adopt(self, job: dict[str, Any], result: dict[str, Any]) -> None:
        params = loads(job["params"])
        items = {it["idx"]: it for it in params["items"]}
        rows = self.conn.execute("SELECT idx, status, error, result_ref FROM job_item WHERE job_id=? AND status IN ('ok', 'failed')", (job["id"],)).fetchall()
        item_dir = self.jobs.jobs_dir / job["id"] / "items"
        ver_now = self._versions()
        cs = ChangeSet()
        ts = now_iso()
        with transaction(self.conn):
            for r in rows:
                it = items.get(r["idx"])
                if it is None:
                    continue
                s = self.conn.execute(f"SELECT {self._SAMPLE_COLS} FROM sample WHERE id=?", (it["sample"],)).fetchone()
                if s is None or s["asset_id"] != it["asset"]:
                    continue  # 采样在任务期间被删了或换了绑定：不登记
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
                    " VALUES (?, ?, 'sample', ?, ?, ?, ?, ?, ?, 0, ?, ?)",
                    (rid, KIND, it["sample"], it["asset"], it["target"][0], it["target"][1], dumps(inputs), status, dumps(res), ts),
                )
                cs.add("measure", it["sample"])
                if status != "ok":
                    continue
                head = self._head_row(it["sample"])
                if head is not None and (head["manual"] or head["run_id"] != it.get("baseHead")):
                    continue  # 人工版本或已被更新：只进历史
                try:
                    changed = self.item_for(s, ver_now)["fingerprint"] != it["fingerprint"]
                except CoreError:
                    changed = True
                if changed:
                    continue  # 输入在任务期间变了：只进历史
                self._set_head(it["sample"], rid, head)
        record_probes(self.conn, result.get("probes") or [])
        # 成功后清理私有中间文件（逐条结果已进库）；失败的任务不会走到这里，证据保留
        shutil.rmtree(self.jobs.jobs_dir / job["id"] / "cache", ignore_errors=True)
        if cs.entities and self.on_change:
            self.on_change(cs)

    def _set_head(self, sample_id: str, run_id: str, head: sqlite3.Row | None) -> None:
        if head is None:
            self.conn.execute("INSERT INTO measure_head(owner_type, owner_id, kind, run_id, version) VALUES ('sample', ?, ?, ?, 1)", (sample_id, KIND, run_id))
        else:
            self.conn.execute(
                "UPDATE measure_head SET run_id=?, version=version+1 WHERE owner_type='sample' AND owner_id=? AND kind=?", (run_id, sample_id, KIND)
            )

    # ------------------------------------------------------------ 读取（无副作用）

    def results(self, job_id: str) -> list[dict[str, Any]]:
        rows = self.conn.execute(
            "SELECT j.idx, j.target, j.status, j.error, s.name FROM job_item j LEFT JOIN sample s ON s.id=j.target WHERE j.job_id=? ORDER BY j.status='skipped', j.idx",
            (job_id,),
        )
        return [
            {"idx": r["idx"], "sampleId": r["target"], "name": r["name"], "status": r["status"], "error": loads(r["error"]) if r["error"] else None, "deleted": r["name"] is None}
            for r in rows
        ]

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
