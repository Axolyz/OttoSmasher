"""波形峰值（规格 05 §5.3.2、16 R22.10；ARCHITECTURE §10.2）。

- 生成：整条流从头解码一次（流式读取，不在内存里放整段 PCM），每 ``BUCKET`` 个样本记一对 (最小, 最大)（各声道合并）；
  结果缓存在 ``Data/Cache/Peaks``（可清理、可重建），键 = 文件路径 + 大小 + 修改时间 + 第几条音频流，同一文件的资产共用。
- 查询：任意区间、按请求的点数（上限 ``MAX_POINTS``）把桶合并成不多于该点数的 (最小, 最大) 序列。
  峰值只做显示，不参与任何计算。
"""

from __future__ import annotations

import hashlib
import os
import re
import subprocess
import sys
import threading
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

import numpy as np

from ottosmasher.core.errors import CoreError

from . import tools
from .decode import FrameIndex, StreamRef, save_index

BUCKET = 256
MAX_POINTS = 32000


@dataclass(frozen=True)
class Peaks:
    sample_rate: int
    bucket: int
    frames: int  # 整条流的样本数（帧数）
    mins: np.ndarray  # float32，每桶最小值
    maxs: np.ndarray  # float32，每桶最大值

    def query(self, start: float, end: float, points: int) -> dict[str, object]:
        """[start, end) 秒 → 不多于 points 个 (最小, 最大)；越界报错。"""
        dur = self.frames / self.sample_rate
        if not (0 <= start < end) or end > dur + 1.0 / self.sample_rate:
            raise CoreError("range-invalid", reason="out-of-bounds", start=start, end=end, duration=dur)
        points = max(1, min(int(points), MAX_POINTS))
        b0 = int(start * self.sample_rate) // self.bucket
        b1 = min(len(self.mins), -(-int(round(end * self.sample_rate)) // self.bucket))
        n = max(1, b1 - b0)
        group = -(-n // points)  # 每个输出点合并几个桶
        edges = np.arange(b0, b1, group)
        mins = np.minimum.reduceat(self.mins[b0:b1], edges - b0) if n else np.zeros(0, np.float32)
        maxs = np.maximum.reduceat(self.maxs[b0:b1], edges - b0) if n else np.zeros(0, np.float32)
        return {
            "start": b0 * self.bucket / self.sample_rate,
            "step": group * self.bucket / self.sample_rate,
            "min": mins.astype("<f4").tobytes(),
            "max": maxs.astype("<f4").tobytes(),
            "count": int(len(mins)),
        }


def cache_path(cache: Path, ref: StreamRef) -> Path:
    st = os.stat(ref.path)
    key = hashlib.sha256(
        f"peaks1|{os.path.abspath(ref.path)}|{st.st_size}|{st.st_mtime_ns}|{ref.ordinal}|{BUCKET}".encode()
    ).hexdigest()[:24]
    return cache / "Peaks" / f"{key}.npz"


def load(cache: Path, ref: StreamRef) -> Peaks | None:
    p = cache_path(cache, ref)
    if not p.is_file():
        return None
    with np.load(p) as z:
        return Peaks(int(z["sample_rate"]), int(z["bucket"]), int(z["frames"]), z["mins"], z["maxs"])


def _low_priority() -> dict[str, object]:
    if sys.platform == "win32":
        return {"creationflags": subprocess.BELOW_NORMAL_PRIORITY_CLASS}  # type: ignore[attr-defined]
    return {"preexec_fn": lambda: os.nice(10)}


_FRAME = re.compile(r"\] n:\s*\d+\s+pts:\s*\S+\s+pts_time:\s*(\S+).*?nb_samples:\s*(\d+)")


def build(ref: StreamRef, cache: Path, *, on_proc: Callable[[subprocess.Popen[bytes]], None] | None = None) -> Peaks:
    """整条流解码一次生成峰值并原子写入缓存。ffmpeg 以较低优先级运行；``on_proc`` 拿到进程以便退出时结束它。

    需要帧索引的流（MKV 等，见 decode）在同一次解码里用 ashowinfo 顺带记下每帧时间戳与样本数，写入帧索引缓存，
    之后的区间解码不必再整条解码一遍。
    """
    indexed = ref.method == "indexed"
    cmd = [tools.find("ffmpeg"), "-hide_banner", "-nostdin", "-nostats", "-loglevel", "info" if indexed else "error"]
    cmd += ["-i", ref.path, "-map", f"0:a:{ref.ordinal}"]
    if indexed:
        cmd += ["-af", "ashowinfo"]
    cmd += ["-f", "f32le", "-c:a", "pcm_f32le", "-"]
    p = subprocess.Popen(cmd, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE, **_low_priority())  # type: ignore[call-overload]
    if on_proc is not None:
        on_proc(p)
    assert p.stdout is not None and p.stderr is not None
    pts: list[float] = []
    counts: list[int] = []
    tail: list[str] = []

    def read_err() -> None:
        for raw_line in p.stderr:  # type: ignore[union-attr]
            line = raw_line.decode("utf-8", "replace")
            m = _FRAME.search(line) if indexed else None
            if m:
                try:
                    pts.append(float(m.group(1)))
                    counts.append(int(m.group(2)))
                except ValueError:
                    pts.append(float("nan"))
                    counts.append(int(m.group(2)))
            else:
                tail.append(line)
                del tail[:-20]

    t = threading.Thread(target=read_err, daemon=True)
    t.start()
    frame_bytes = 4 * ref.channels
    chunk_frames = BUCKET * 4096
    mins: list[np.ndarray] = []
    maxs: list[np.ndarray] = []
    carry = np.zeros((0, ref.channels), dtype=np.float32)
    rest = b""  # 管道读到半个样本时留到下一次
    frames = 0
    while True:
        raw = p.stdout.read(chunk_frames * frame_bytes)
        if not raw:
            break
        raw = rest + raw
        usable = len(raw) - len(raw) % frame_bytes
        rest = raw[usable:]
        x = np.frombuffer(raw[:usable], dtype="<f4").reshape(-1, ref.channels)
        frames += len(x)
        x = np.concatenate([carry, x]) if len(carry) else x
        whole = len(x) - len(x) % BUCKET
        if whole:
            blocks = x[:whole].reshape(-1, BUCKET * ref.channels)
            mins.append(blocks.min(axis=1))
            maxs.append(blocks.max(axis=1))
        carry = x[whole:]
    p.wait()
    t.join(timeout=10)
    if p.returncode != 0:
        raise CoreError("decode-failed", path=ref.path, detail="".join(tail).strip()[-300:])
    if indexed and counts and sum(counts) == frames and all(x == x for x in pts):
        c = np.asarray(counts, dtype=np.int64)
        save_index(ref, cache, FrameIndex(np.asarray(pts), np.concatenate([[0], np.cumsum(c)[:-1]]).astype(np.int64), frames))
    if len(carry):
        mins.append(carry.min(keepdims=True).reshape(1))
        maxs.append(carry.max(keepdims=True).reshape(1))
    pk = Peaks(
        ref.sample_rate,
        BUCKET,
        frames,
        np.concatenate(mins).astype(np.float32) if mins else np.zeros(0, np.float32),
        np.concatenate(maxs).astype(np.float32) if maxs else np.zeros(0, np.float32),
    )
    out = cache_path(cache, ref)
    out.parent.mkdir(parents=True, exist_ok=True)
    tmp = out.with_name(out.name + f".{os.getpid()}.tmp.npz")
    np.savez(tmp, sample_rate=pk.sample_rate, bucket=pk.bucket, frames=pk.frames, mins=pk.mins, maxs=pk.maxs)
    os.replace(tmp, out)
    return pk
