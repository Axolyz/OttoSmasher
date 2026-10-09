"""检索进程池（ARCHITECTURE §2.1、§2.2、§9）：常驻、只读打开数据库；每次检索按分片并行；取消令牌是共享内存里的一个标志。

- 进程用 spawn 启动（与平台无关），初始化时只读打开数据库；方案按（采样 + 索引失效键, 范围, BPM）缓存在进程内存里；
- 取消：置标志 → 各分片在循环里检查（每个采样 / 每个变体一次）→ 2 秒内不退出就强制结束并重建进程池（被取消的检索不写固定结果）；
- **检索不解码、不推理、不读波形**：分片函数只读 ``speech_index`` 与 F0 测量文件（测试用“一调用就失败”的替身证明）。
"""

from __future__ import annotations

import math
import multiprocessing as mp
import os
import threading
import time
from collections.abc import Callable
from concurrent.futures import Future, ProcessPoolExecutor
from pathlib import Path
from typing import Any

import numpy as np

SLOTS = 64
CANCEL_GRACE = 2.0

_STATE: dict[str, Any] = {}


def _init(db: str, f0_root: str, flags: Any) -> None:
    from ..store.db import connect

    _STATE["db"] = db
    _STATE["f0"] = Path(f0_root)
    _STATE["flags"] = flags
    _STATE["conn"] = connect(Path(db), readonly=True)
    _STATE["schemes"] = {}


def _cancelled(slot: int) -> Callable[[], bool]:
    flags = _STATE.get("flags")
    if flags is None:
        return lambda: False
    return lambda: bool(flags[slot])


def _conn() -> Any:
    return _STATE["conn"]


# ---------------------------------------------------------------- 语音检索分片


def speech_shard(sample_ids: list[str], query: dict[str, Any], bpm: float | None, slot: int) -> dict[str, Any]:
    from ..algo import speech_search as ss
    from .search_index import read_wires

    q = ss.parse_query(query)
    wires = read_wires(_conn(), sample_ids)
    batch = ss.Batch.of_wires(wires)
    cache = _STATE.setdefault("schemes", {})
    if len(cache) > 200_000:
        cache.clear()
    out = ss.search(batch, q, bpm, cache=cache, cancel=_cancelled(slot))
    hits = []
    for h in out.hits:
        ev = h.evidence
        hits.append({
            "sample": batch.sample_ids[h.sample], "first": h.first, "count": h.count, "start": h.start, "end": h.end,
            "score": h.score, "blockScore": h.block_score,
            "evidence": None if ev is None else {
                "strict": ev.strict, "cost": ev.cost, "error": ev.error, "conflicts": ev.conflicts, "deficit": ev.deficit, "speed": ev.speed,
                "density": ev.density, "bpm": ev.bpm, "plan": ev.plan, "scope": ev.scope, "shift": ev.shift, "deform": ev.deform,
                "rests": list(ev.rests), "changed": ev.changed,
            },
        })
    return {"hits": hits, "windows": out.windows, "noEvidence": out.no_evidence, "cancelled": out.cancelled, "searched": len(wires)}


# ---------------------------------------------------------------- 音高检索分片


def _regions(spans: list[tuple[int, int]]) -> list[tuple[int, int]]:
    out: list[list[int]] = []
    for a, b in sorted(spans):
        if out and a <= out[-1][1]:
            out[-1][1] = max(out[-1][1], b)
        else:
            out.append([a, b])
    return [(a, b) for a, b in out]


def pitch_shard(assets: list[dict[str, Any]], blocks: list[dict[str, Any]], params: dict[str, Any], mode: str, slot: int) -> dict[str, Any]:
    """``assets``：[{asset, identity, duration, spans: [[帧起, 帧止, 采样ID 或 None]], lines: [[起, 止]] | None}]。"""
    from ..algo import pitch_search as ps
    from ..models import f0store

    q = ps.parse_query(blocks)
    prm = ps.check_params(params, mode=mode)
    sounds: list[ps.Sound] = []
    owner: list[dict[str, Any]] = []
    for a in assets:
        spans = [(int(s[0]), int(s[1])) for s in a["spans"]]
        for r0, r1 in _regions(spans):
            i0, frames, _have = f0store.read(_STATE["f0"], a["asset"], a["identity"], r0 * ps.FRAME, r1 * ps.FRAME, a["duration"])
            inside = [sp for sp in spans if r0 <= sp[0] and sp[1] <= r1]
            sounds.append(ps.Sound(
                a["asset"], i0, frames[:, 0], frames[:, 1], frames[:, 2], inside,
                None if a.get("lines") is None else [(float(x), float(y)) for x, y in a["lines"]],
            ))
            owner.append(a)
    out = ps.search_exact(sounds, q, prm, cancel=_cancelled(slot))
    hits = []
    for h in out.hits:
        a = owner[h.sound]
        samples = [s[2] for s in a["spans"] if s[2] is not None and s[0] <= h.start and h.end <= s[1]]
        hits.append({
            "asset": a["asset"], "start": h.start, "frames": h.frames, "octave": h.octave, "score": h.score,
            "ratio": h.frames / q.frames, "blocks": [list(b) for b in h.blocks], "samples": samples,
        })
    return {"hits": hits, "windows": out.windows, "unknownBounds": out.unknown_bounds, "cancelled": out.cancelled}


# ---------------------------------------------------------------- 进程池


class SearchPool:
    """常驻进程池 + 取消标志。``inline=True`` 时在调用线程里直接跑分片（测试用）。"""

    def __init__(self, db: Path, f0_root: Path, workers: int | None = None, inline: bool = False) -> None:
        self.db = str(db)
        self.f0_root = str(f0_root)
        self.workers = workers or max(1, min(6, (os.cpu_count() or 4) - 2))
        self.inline = inline
        self._ctx = mp.get_context("spawn")
        self.flags = self._ctx.Array("b", SLOTS, lock=False)
        self._free = list(range(SLOTS))
        self._lock = threading.Lock()
        self._pool: ProcessPoolExecutor | None = None
        if inline:
            _init(self.db, self.f0_root, self.flags)

    def _executor(self) -> ProcessPoolExecutor:
        with self._lock:
            if self._pool is None:
                self._pool = ProcessPoolExecutor(
                    max_workers=self.workers, mp_context=self._ctx, initializer=_init, initargs=(self.db, self.f0_root, self.flags)
                )
            return self._pool

    def acquire(self) -> int:
        with self._lock:
            if not self._free:
                raise RuntimeError("too many concurrent searches")
            slot = self._free.pop(0)
            self.flags[slot] = 0
            return slot

    def release(self, slot: int) -> None:
        with self._lock:
            self.flags[slot] = 0
            self._free.append(slot)

    def run(self, fn: Callable[..., dict[str, Any]], shards: list[tuple[Any, ...]], slot: int) -> list[dict[str, Any]] | None:
        """跑完全部分片；被取消返回 None（2 秒内没退出的分片 → 强制结束并重建进程池）。"""
        if self.inline:
            out = []
            for args in shards:
                if self.flags[slot]:
                    return None
                r = fn(*args, slot)
                if r.get("cancelled"):
                    return None
                out.append(r)
            return None if self.flags[slot] else out
        ex = self._executor()
        futs: list[Future[dict[str, Any]]] = [ex.submit(fn, *args, slot) for args in shards]
        while True:
            if all(f.done() for f in futs):
                break
            if self.flags[slot]:
                deadline = time.monotonic() + CANCEL_GRACE
                while time.monotonic() < deadline and not all(f.done() for f in futs):
                    time.sleep(0.02)
                if not all(f.done() for f in futs):
                    self._kill()
                return None
            time.sleep(0.01)
        res = [f.result() for f in futs]
        if self.flags[slot] or any(r.get("cancelled") for r in res):
            return None
        return res

    def cancel(self, slot: int) -> None:
        self.flags[slot] = 1

    def _kill(self) -> None:
        with self._lock:
            pool, self._pool = self._pool, None
        if pool is None:
            return
        for p in list(getattr(pool, "_processes", {}).values()):
            try:
                p.kill()
            except Exception:  # noqa: BLE001
                pass
        pool.shutdown(wait=False, cancel_futures=True)

    def shutdown(self) -> None:
        self._kill()


def shards_of(items: list[Any], n: int, weight: Callable[[Any], float] | None = None) -> list[list[Any]]:
    """均分（按权重贪心装箱，保持各分片内的原顺序）。"""
    n = max(1, min(n, len(items)))
    if weight is None:
        size = math.ceil(len(items) / n) if items else 1
        return [items[i : i + size] for i in range(0, len(items), size)] or [[]]
    bins: list[list[tuple[int, Any]]] = [[] for _ in range(n)]
    load = np.zeros(n)
    for i, it in sorted(enumerate(items), key=lambda x: -weight(x[1])):
        k = int(np.argmin(load))
        bins[k].append((i, it))
        load[k] += weight(it)
    return [[it for _, it in sorted(b, key=lambda x: x[0])] for b in bins if b]


# ---------------------------------------------------------------- 自检（测试用：可取消的等待、不理会取消的卡死）


def selftest_wait(seconds: float, slot: int) -> dict[str, Any]:
    t = time.monotonic() + seconds
    stop = _cancelled(slot)
    while time.monotonic() < t:
        if stop():
            return {"cancelled": True}
        time.sleep(0.01)
    return {"cancelled": False, "pid": os.getpid()}


def selftest_hang(seconds: float, slot: int) -> dict[str, Any]:
    time.sleep(seconds)
    return {"cancelled": False, "pid": os.getpid()}
