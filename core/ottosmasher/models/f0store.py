"""F0 测量的存储（规格 10 §10.1、ARCHITECTURE §4.5）：按资产共享，逐帧无损，**不是缓存**。

- 网格：资产局部秒，第 i 帧中心 = (i × 160 + 80) / 16000；每帧 F0、置信度、能量（float32，[N, 3]）。
- 分段：每段 60 秒（6000 帧），推理时两侧各带 1 秒上下文；只测用到的段（“该声音没测过才测”）。
- 位置：``Data/Measurements/f0/<资产>/<身份>/<段号>.npy`` + ``manifest.json``；身份 = 文件快照 + 音频流 + 存储窗口 + 映射 + 模型与算法版本的指纹，
  同一资产的文件变了就是另一份测量，不混用。
"""

from __future__ import annotations

import hashlib
import json
import math
import os
from pathlib import Path
from typing import Any

import numpy as np

from . import fcpe

CHUNK_FRAMES = fcpe.SEGMENT_FRAMES
CHUNK_SECONDS = CHUNK_FRAMES * fcpe.HOP / fcpe.SR  # 60 秒
CONTEXT_SECONDS = 1.0
ALGO_VERSION = "f0-store-1"


def identity(audio: dict[str, Any], model_sha: str) -> str:
    key = {"audio": audio, "model": model_sha, "frontend": fcpe.FRONTEND_VERSION, "store": ALGO_VERSION}
    return hashlib.sha256(json.dumps(key, sort_keys=True, separators=(",", ":")).encode()).hexdigest()[:16]


def total_frames(duration: float) -> int:
    return fcpe.frame_count(round(duration * fcpe.SR))


def chunks_for(start: float, end: float, duration: float) -> list[int]:
    n = total_frames(duration)
    last = max(0, (n - 1) // CHUNK_FRAMES)
    a = max(0, int(math.floor(start / CHUNK_SECONDS)))
    b = min(last, int(math.floor(max(start, end - 1e-9) / CHUNK_SECONDS)))
    return list(range(a, b + 1))


def chunk_plan(k: int, duration: float) -> dict[str, Any]:
    """第 k 段：要解码的资产局部区间（含上下文）、跳过的上下文帧数、本段帧数。"""
    n = total_frames(duration)
    f0, f1 = k * CHUNK_FRAMES, min((k + 1) * CHUNK_FRAMES, n)
    t0 = f0 * fcpe.HOP / fcpe.SR
    t1 = f1 * fcpe.HOP / fcpe.SR
    d0 = max(0.0, t0 - CONTEXT_SECONDS)
    d1 = min(duration, t1 + CONTEXT_SECONDS)
    return {"decode": [d0, d1], "skip": round((t0 - d0) * fcpe.SR / fcpe.HOP), "frames": f1 - f0}


def asset_dir(root: Path, asset_id: str, ident: str) -> Path:
    return root / asset_id / ident


def present(root: Path, asset_id: str, ident: str) -> set[int]:
    d = asset_dir(root, asset_id, ident)
    try:
        man = json.loads((d / "manifest.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return set()
    return {int(k) for k in man.get("chunks", {}) if (d / f"{k}.npy").exists()}


def adopt_chunk(root: Path, asset_id: str, ident: str, k: int, src: Path, meta: dict[str, Any]) -> None:
    """把任务算好的一段放进测量目录（已有就不覆盖）并更新清单（原子写）。"""
    d = asset_dir(root, asset_id, ident)
    d.mkdir(parents=True, exist_ok=True)
    dst = d / f"{k}.npy"
    if not dst.exists():
        tmp = d / f".{k}.npy.tmp"
        tmp.write_bytes(src.read_bytes())
        os.replace(tmp, dst)
    mp = d / "manifest.json"
    try:
        man = json.loads(mp.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        man = {"identity": ident, "meta": meta, "chunks": {}}
    man["chunks"][str(k)] = {"frames": int(np.load(dst, mmap_mode="r").shape[0])}
    tmp = d / ".manifest.json.tmp"
    tmp.write_text(json.dumps(man, ensure_ascii=False, sort_keys=True), encoding="utf-8")
    os.replace(tmp, mp)


def read(root: Path, asset_id: str, ident: str, start: float, end: float, duration: float) -> tuple[int, np.ndarray, np.ndarray]:
    """[start, end) 的帧：返回（第一帧序号，[n, 3] 帧，[n] 是否已测）。没测的帧为 NaN。读取没有副作用。"""
    n = total_frames(duration)
    i0 = max(0, int(math.floor(start / (fcpe.HOP / fcpe.SR))))
    i1 = min(n, int(math.ceil(end / (fcpe.HOP / fcpe.SR))))
    out = np.full((max(0, i1 - i0), 3), np.nan, dtype=np.float32)
    have = np.zeros(len(out), dtype=bool)
    d = asset_dir(root, asset_id, ident)
    for k in chunks_for(start, end, duration):
        p = d / f"{k}.npy"
        if not p.exists():
            continue
        arr = np.load(p, mmap_mode="r")
        c0 = k * CHUNK_FRAMES
        a, b = max(i0, c0), min(i1, c0 + len(arr))
        if b > a:
            out[a - i0 : b - i0] = arr[a - c0 : b - c0]
            have[a - i0 : b - i0] = True
    return i0, out, have
