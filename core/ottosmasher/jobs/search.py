"""三大搜索的准备任务（规格 09 §9.6.5、10 §10.2.5）。只写任务目录；登记由 Core 做（键仍然相同才采纳）。

- ``search.index``（轻量通道）：语音检索索引。只读打开数据库，复用节奏分析（解码音频算停顿、读 F0 算逐块属性），
  一批多时用进程池并行（每个进程自己的只读连接；取消时整棵进程树一起结束）。
- ``f0.measure``（模型通道）：音高检索覆盖 = 缺的 F0 段（FCPE，60 秒一段 + 两侧 1 秒上下文），与语音分析里测 F0 是同一段代码。
"""

from __future__ import annotations

import os
from concurrent.futures import ProcessPoolExecutor, as_completed
from pathlib import Path
from typing import Any

import msgspec

PARALLEL_MIN = 64
BATCH = 32


class _NoJobs:
    """只读服务不登记任务结果。"""

    adopters: dict[str, Any] = {}
    jobs_dir = Path(".")


def _services(db: str, workspace: str, support_dir: str) -> tuple[Any, Any]:
    from ..core.rhythm import RhythmService
    from ..core.speech import SpeechService
    from ..store.db import connect
    from ..store.workspace import Workspace

    conn = connect(Path(db), readonly=True)
    ws = Workspace(Path(workspace))
    speech = SpeechService(conn, ws, _NoJobs(), Path(support_dir))
    return conn, RhythmService(conn, ws, speech, edits=None)


def build_batch(db: str, workspace: str, support_dir: str, items: list[tuple[str, str]]) -> list[list[Any]]:
    """[(采样, 键)] → [[采样, 键, status, reason, data]]。进程池里跑（顶层函数，可 pickle）。"""
    from ..core.errors import CoreError
    from ..core.search_index import build_row

    conn, rhythm = _services(db, workspace, support_dir)
    out: list[list[Any]] = []
    try:
        for sid, key in items:
            try:
                status, reason, data = build_row(rhythm, conn, sid)
            except CoreError as e:
                status, reason, data = "none", e.code, None
            out.append([sid, key, status, reason, data])
    finally:
        conn.close()
    return out


def index(params: dict[str, Any], ctx: Any) -> dict[str, Any]:
    from ..core.search_index import speech_keys
    from ..store.db import connect

    db, workspace, support = params["db"], params["workspace"], params["support_dir"]
    conn = connect(Path(db), readonly=True)
    try:
        keys = speech_keys(conn, list(params["ids"]))  # 先算键再构建：构建期间资料变了，采纳时键对不上就丢掉（不会把新状态记成旧键）
    finally:
        conn.close()
    todo = [(sid, k) for sid, (k, has) in keys.items() if has]
    rows: list[list[Any]] = []
    total = len(todo)
    ctx.progress("index", 0, total, "search-indexing")
    workers = max(1, min(int(params.get("workers") or 0) or (os.cpu_count() or 2) - 2, 8))
    if total >= PARALLEL_MIN and workers > 1:
        batches = [todo[i : i + BATCH] for i in range(0, total, BATCH)]
        with ProcessPoolExecutor(max_workers=workers) as pool:
            futs = [pool.submit(build_batch, db, workspace, support, b) for b in batches]
            for f in as_completed(futs):
                rows += f.result()
                ctx.progress("index", len(rows), total, "search-indexing")
    else:
        for i in range(0, total, BATCH):
            rows += build_batch(db, workspace, support, todo[i : i + BATCH])
            ctx.progress("index", len(rows), total, "search-indexing")
    (ctx.job_dir / "rows.msgpack").write_bytes(msgspec.msgpack.encode(rows))
    return {"rows": "rows.msgpack", "built": sum(1 for r in rows if r[2] == "ok"), "none": sum(1 for r in rows if r[2] != "ok")}


def f0(params: dict[str, Any], ctx: Any) -> dict[str, Any]:
    from ..models.onnx import Device
    from .worker import _measure_f0

    sessions: list[Any] = []
    done, errors = _measure_f0(params["plan"], ctx, Path(params["models_dir"]), Path(params["support_dir"]), Device.of(ctx.device), sessions)
    return {"f0": done, "f0Errors": errors, "probes": [s.probe for s in sessions if s.probe]}
