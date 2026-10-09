"""三大搜索（规格 09 §9.6、10 §10.2、04 §4.2.10；ARCHITECTURE §2.2、§9）：Core 侧——范围、覆盖预检、准备任务的提交与采纳。

覆盖预检：语音检索“n/m 已就绪”（有分析但索引没建或过期 → 「准备当前范围索引」）；音高检索“a/b 已索引”（F0 没测 → 「准备当前范围索引」）。
准备任务完成后只刷新覆盖数（事件 ``search.coverage``），**不重新搜索**（10 §10.2.5）。
"""

from __future__ import annotations

import sqlite3
from collections.abc import Callable
from pathlib import Path
from typing import Any

import msgspec

from ..store.db import transaction
from ..store.workspace import Workspace
from . import assets as assets_mod
from .clock import now_iso
from .errors import CoreError
from .probes import record_probes
from .search_index import SpeechIndex, pitch_coverage

MODES = ("speech", "pitch")


class SearchService:
    def __init__(
        self, conn: sqlite3.Connection, ws: Workspace, jobs: Any, samples: Any, speech: Any, support_dir: Path,
        emit: Callable[[str, Any], None] | None = None,
    ) -> None:
        self.conn = conn
        self.ws = ws
        self.jobs = jobs
        self.samples = samples
        self.speech = speech
        self.support_dir = support_dir
        self.emit = emit
        self.index = SpeechIndex(conn)
        jobs.adopters["search.index"] = self._adopt_index
        jobs.adopters["f0.measure"] = self._adopt_f0

    # ------------------------------------------------------------ 范围

    def scope_ids(self, scope: dict[str, Any] | None) -> list[str]:
        """当前浏览范围（查找栏与范围行的条件）→ 采样 ID（与列表同一套条件）。"""
        sc = scope or {}
        return self.samples.ids(natures=sc.get("natures"), starred=bool(sc.get("starred")), text=str(sc.get("text") or ""), source_id=sc.get("sourceId"))

    def _sample_ranges(self, ids: list[str]) -> list[tuple[str, str, float, float]]:
        out = []
        for i in range(0, len(ids), 900):
            part = ids[i : i + 900]
            out += [
                (r[0], r[1], float(r[2]), float(r[3]))
                for r in self.conn.execute(f'SELECT id, asset_id, start, "end" FROM sample WHERE id IN ({",".join("?" * len(part))})', part)
            ]
        order = {s: k for k, s in enumerate(ids)}
        out.sort(key=lambda r: order[r[0]])
        return out

    # ------------------------------------------------------------ 覆盖预检

    def coverage(self, mode: str, scope: dict[str, Any] | None) -> dict[str, Any]:
        if mode not in MODES:
            raise CoreError("search-invalid", field="mode")
        ids = self.scope_ids(scope)
        if mode == "speech":
            s = self.index.status(ids)
            return {"mode": mode, "total": len(ids), "ready": len(s["ready"]), "stale": len(s["stale"]), "noAnalysis": len(s["missing"]) + len(s["none"])}
        cov = pitch_coverage(self.conn, self.ws.f0, self._sample_ranges(ids))
        return {"mode": mode, "total": len(ids), "ready": len(cov["ready"]), "stale": len(cov["pending"]), "noAnalysis": 0}

    # ------------------------------------------------------------ 准备当前范围索引

    def prepare(self, mode: str, scope: dict[str, Any] | None) -> dict[str, Any]:
        if mode not in MODES:
            raise CoreError("search-invalid", field="mode")
        ids = self.scope_ids(scope)
        if mode == "speech":
            stale = self.index.status(ids)["stale"]
            if not stale:
                raise CoreError("search-nothing-to-prepare")
            params = {"ids": stale, "db": str(self.ws.db_path), "workspace": str(self.ws.root), "support_dir": str(self.support_dir)}
            return self.jobs.submit("search.index", params, {"sample": stale})
        cov = pitch_coverage(self.conn, self.ws.f0, self._sample_ranges(ids))
        plan = self._f0_plan(cov)
        if not plan:
            raise CoreError("search-nothing-to-prepare")
        params = {"plan": plan, "models_dir": str(self.ws.models), "support_dir": str(self.support_dir)}
        return self.jobs.submit("f0.measure", params, {"asset": sorted({p["asset"] for p in plan})})

    def _f0_plan(self, cov: dict[str, Any]) -> list[dict[str, Any]]:
        """覆盖缺口 → F0 测量计划（与语音分析里测 F0 同一格式：资产、身份、时长、文件、存储窗口、段号）。"""
        out = []
        for p in cov["plan"].values():
            asset = assets_mod.get(self.conn, p["asset"])
            chunks = sorted(p["chunks"])
            # 用第一段所在的存储定位文件（身份已按同一存储算出）
            from ..models import f0store

            cp = f0store.chunk_plan(chunks[0], p["duration"])
            t0 = min(max(0.0, cp["decode"][0]), float(asset["duration"]))
            t1 = min(float(asset["duration"]), max(t0 + 1e-3, cp["decode"][1]))
            try:
                ref, win, media = assets_mod.locate(self.conn, self.ws.root, asset, t0, t1)
                assets_mod.check_media(media)
            except CoreError:
                continue  # 文件缺失或被改动：不测（覆盖里仍是“未就绪”）
            out.append({
                "asset": p["asset"], "identity": p["identity"], "duration": p["duration"], "chunks": chunks,
                "file": {"path": ref.path, "ordinal": ref.ordinal, "sample_rate": ref.sample_rate, "channels": ref.channels, "codec": ref.codec, "format": ref.format_name},
                "storage": [win.local_start, win.local_end, win.file_start],
            })
        return out

    # ------------------------------------------------------------ 采纳

    def _adopt_index(self, job: dict[str, Any], result: dict[str, Any]) -> None:
        rows = msgspec.msgpack.decode((self.jobs.jobs_dir / job["id"] / result["rows"]).read_bytes())
        with transaction(self.conn):
            n = self.index.adopt([tuple(r) for r in rows])
        if self.emit:
            self.emit("search.coverage", {"mode": "speech", "adopted": n})

    def _adopt_f0(self, job: dict[str, Any], result: dict[str, Any]) -> None:
        with transaction(self.conn):
            self.speech._adopt_f0(job["id"], result.get("f0") or [], now_iso())
        record_probes(self.conn, result.get("probes") or [])
        if self.emit:
            self.emit("search.coverage", {"mode": "pitch", "adopted": len(result.get("f0") or [])})
