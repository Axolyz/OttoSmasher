"""三大搜索的准备任务（规格 09 §9.6.5、10 §10.2.5）。只写任务目录；登记由 Core 做（键仍然相同才采纳）。

- ``search.index``（轻量通道）：语音检索索引。只读打开数据库，复用节奏分析（解码音频算停顿、读 F0 算逐块属性），
  一批多时用进程池并行（每个进程自己的只读连接；取消时整棵进程树一起结束）。
- ``f0.measure``（模型通道）：音高检索覆盖 = 缺的 F0 段（FCPE，60 秒一段 + 两侧 1 秒上下文），与语音分析里测 F0 是同一段代码。
"""

from __future__ import annotations

import multiprocessing as mp
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
        ranges = {r[0]: (r[1], float(r[2]), float(r[3])) for r in conn.execute(
            f'SELECT id, asset_id, start, "end" FROM sample WHERE id IN ({",".join("?" * len(items))})', [i[0] for i in items])} if items else {}
        # 同一资产上相邻的采样一起解码一次（跨度不超过 PRELOAD_SPAN 秒），再逐条切片
        for group in _groups(items, ranges):
            g = [ranges[sid] for sid, _ in group if sid in ranges]
            if len(group) > 1 and g:
                try:
                    rhythm.preload(g[0][0], min(x[1] for x in g), max(x[2] for x in g))
                except CoreError:
                    rhythm.unload()
            for sid, key in group:
                try:
                    status, reason, data = build_row(rhythm, conn, sid)
                except CoreError as e:
                    status, reason, data = "none", e.code, None
                out.append([sid, key, status, reason, data])
            rhythm.unload()
    finally:
        conn.close()
    return out


PRELOAD_SPAN = 300.0


def _groups(items: list[tuple[str, str]], ranges: dict[str, tuple[str, float, float]]) -> list[list[tuple[str, str]]]:
    out: list[list[tuple[str, str]]] = []
    cur: list[tuple[str, str]] = []
    lo = hi = 0.0
    asset = None
    for it in items:
        r = ranges.get(it[0])
        if r is None:
            out.append([it])
            continue
        if cur and r[0] == asset and max(hi, r[2]) - min(lo, r[1]) <= PRELOAD_SPAN:
            cur.append(it)
            lo, hi = min(lo, r[1]), max(hi, r[2])
            continue
        if cur:
            out.append(cur)
        cur, asset, lo, hi = [it], r[0], r[1], r[2]
    if cur:
        out.append(cur)
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
    # 按资产、起点排序：同一批里的采样尽量是同一条音轨上相邻的，一次解码
    conn = connect(Path(db), readonly=True)
    try:
        pos = {}
        ids = [t[0] for t in todo]
        for i in range(0, len(ids), 900):
            part = ids[i : i + 900]
            pos.update({r[0]: (r[1], r[2]) for r in conn.execute(f"SELECT id, asset_id, start FROM sample WHERE id IN ({','.join('?' * len(part))})", part)})
    finally:
        conn.close()
    todo.sort(key=lambda t: pos.get(t[0], ("", 0.0)))
    rows: list[list[Any]] = []
    total = len(todo)
    ctx.progress("index", 0, total, "search-indexing")
    workers = max(1, min(int(params.get("workers") or 0) or (os.cpu_count() or 2) - 2, 8))
    if total >= PARALLEL_MIN and workers > 1:
        batches = [todo[i : i + BATCH] for i in range(0, total, BATCH)]
        with ProcessPoolExecutor(max_workers=workers, mp_context=mp.get_context("spawn")) as pool:
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


def acoustic(params: dict[str, Any], ctx: Any) -> dict[str, Any]:
    """单音声学指标（10 §10.3）：先补测范围里缺的 F0（与语音分析同一段代码），再逐条解码采样音频、读 F0、算指标。"""
    import json

    import numpy as np

    from ..algo import acoustic as ac
    from ..core.errors import CoreError
    from ..media import decode as dec
    from ..models import f0store
    from ..models.onnx import Device
    from .worker import _measure_f0

    sessions: list[Any] = []
    done, errors = _measure_f0(params["plan"], ctx, Path(params["models_dir"]), Path(params["support_dir"]), Device.of(ctx.device), sessions)
    root = Path(params["f0root"])
    rows: list[dict[str, Any]] = []
    items = params["items"]
    for n, it in enumerate(items):
        ctx.progress("metrics", n, len(items), "acoustic-measuring")
        try:
            f = it["file"]
            ref = dec.StreamRef(f["path"], int(f["ordinal"]), int(f["sample_rate"]), int(f["channels"]), f.get("codec"), f.get("format"))
            local_start, _local_end, file_start = it["storage"]
            sr = ref.sample_rate
            a = round((file_start + it["start"] - local_start) * sr)
            b = round((file_start + it["end"] - local_start) * sr)
            pcm = dec.decode_frames(ref, a, b, cache=ctx.job_dir / "cache")
            if it["identity"] is None:
                i0, frames = int(it["start"] // 0.01), np.full((0, 3), np.nan)
            else:
                i0, frames, have = f0store.read(root, it["asset"], it["identity"], it["start"], it["end"], it["duration"])
                for k in f0store.chunks_for(it["start"], it["end"], it["duration"]):  # 这个任务刚测的段
                    p = ctx.job_dir / "f0" / it["asset"] / f"{k}.npy"
                    if p.exists():
                        arr = np.load(p)
                        c0 = k * f0store.CHUNK_FRAMES
                        lo, hi = max(i0, c0), min(i0 + len(frames), c0 + len(arr))
                        if hi > lo:
                            frames[lo - i0 : hi - i0] = arr[lo - c0 : hi - c0]
            measured = np.isfinite(frames).all(axis=1) if len(frames) else np.zeros(0, dtype=bool)
            m = ac.metrics(pcm, sr, frames[:, 0] if len(frames) else np.zeros(0), frames[:, 1] if len(frames) else np.zeros(0),
                           frames[:, 2] if len(frames) else np.zeros(0), measured, f0_start=i0 * 0.01 - it["start"])
            rows.append({"sample": it["sample"], "asset": it["asset"], "start": it["start"], "end": it["end"], "sig": it["sig"], "algo": params["algo"], "metrics": m})
        except CoreError as exc:
            errors.append({"sample": it["sample"], "error": exc.to_wire()})
    ctx.progress("metrics", len(items), len(items), "acoustic-measuring")
    (ctx.job_dir / "rows.json").write_text(json.dumps(rows), encoding="utf-8")
    return {"f0": done, "rows": "rows.json", "errors": errors[:50], "probes": [s.probe for s in sessions if s.probe]}

