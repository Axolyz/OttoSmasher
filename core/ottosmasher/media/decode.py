"""区间解码（规格 16 R20.2、R21.1、R21.5；ARCHITECTURE §10.3）：只读需要的区间，逐样本等于整段解码的对应样本。

时间口径：一条音频流的“文件秒” t 对应第 round(t × 采样率) 个样本，样本 0 = 从头解码得到的第一个样本
（MP3 的编码延迟已由解码器按 LAME/Xing 头去掉）。

实测（2026-10-07，FFmpeg 9.0.2，30 秒锯齿斜坡，见 STATUS）：
- WAV、FLAC：``-ss`` 精确定位逐样本正确 → **直接定位**；
- MP3：从目标前 2 秒起解码再丢弃（预滚）后逐样本正确 → **预滚定位**；
- MKV（时间戳只到毫秒）里的 FLAC 偏 ±19 个样本、M4A/AAC 偏上百个样本 → **帧索引定位**：
  整条流解码一次，记下每一帧的时间戳与它在整段里的确切样本序号（缓存在 ``Data/Cache/FrameIndex``，可重建；
  文件大小或修改时间变了就失效）；读区间时从目标前 2 秒的那一帧起解码（不让 ffmpeg 修剪），
  从 ashowinfo 读出实际输出的第一帧时间戳，查索引得到它的确切样本序号，再精确裁切。
"""

from __future__ import annotations

import hashlib
import os
import re
import subprocess
import threading
from dataclasses import dataclass
from pathlib import Path

import numpy as np

from ottosmasher.core.errors import CoreError

from . import tools

PREROLL = 2.0
DIRECT_FORMATS = {"wav", "flac", "aiff", "w64", "caf"}


@dataclass(frozen=True)
class StreamRef:
    """要解码的一条音频流。"""

    path: str
    ordinal: int
    sample_rate: int
    channels: int
    codec: str | None
    format_name: str | None

    @property
    def method(self) -> str:
        fmts = set((self.format_name or "").split(","))
        codec = self.codec or ""
        if fmts & DIRECT_FORMATS and (codec.startswith("pcm_") or codec in ("flac", "alac")):
            return "direct"
        if "mp3" in fmts and codec == "mp3":
            return "preroll"
        return "indexed"


# ---------------------------------------------------------------- 帧索引


@dataclass(frozen=True)
class FrameIndex:
    pts_time: np.ndarray  # float64，每帧的时间戳（秒）
    start: np.ndarray  # int64，每帧第一个样本在整段里的序号
    total: int  # 整条流的样本数

    def frame_at_or_before(self, sample: int) -> int:
        return max(0, int(np.searchsorted(self.start, sample, side="right")) - 1)

    def sample_of_pts(self, pts: float, sample_rate: int) -> int:
        """实际输出的第一帧时间戳 → 它的确切样本序号；与最近一帧的偏差超过半帧就报错（不猜）。"""
        k = int(np.argmin(np.abs(self.pts_time - pts)))
        n = int(self.start[k + 1] - self.start[k]) if k + 1 < len(self.start) else int(self.total - self.start[k])
        if abs(self.pts_time[k] - pts) > 0.5 * max(n, 1) / sample_rate:
            raise CoreError("decode-misaligned", pts=pts)
        return int(self.start[k])


def _index_path(cache: Path, ref: StreamRef) -> Path:
    st = os.stat(ref.path)
    key = hashlib.sha256(f"{os.path.abspath(ref.path)}|{st.st_size}|{st.st_mtime_ns}|{ref.ordinal}".encode()).hexdigest()[:24]
    return cache / "FrameIndex" / f"{key}.npz"


def build_index(ref: StreamRef) -> FrameIndex:
    cmd = [
        tools.find("ffprobe"), "-v", "error", "-select_streams", f"a:{ref.ordinal}",
        "-show_entries", "frame=pts_time,best_effort_timestamp_time,nb_samples", "-of", "csv=p=0", "-i", ref.path,
    ]  # fmt: skip
    out = subprocess.run(cmd, capture_output=True, stdin=subprocess.DEVNULL)
    if out.returncode != 0:
        raise CoreError("decode-failed", path=ref.path, detail=out.stderr.decode("utf-8", "replace").strip()[-300:])
    pts: list[float] = []
    counts: list[int] = []
    for line in out.stdout.decode("ascii", "replace").splitlines():
        f = line.strip().split(",")
        if len(f) < 3:
            continue
        t = f[0] if f[0] not in ("", "N/A") else f[1]
        try:
            pts.append(float(t))
            counts.append(int(f[2]))
        except ValueError:
            raise CoreError("decode-failed", path=ref.path, detail=f"frame without timestamp: {line[:80]}") from None
    if not pts:
        raise CoreError("decode-failed", path=ref.path, detail="no-frames")
    c = np.asarray(counts, dtype=np.int64)
    start = np.concatenate([[0], np.cumsum(c)[:-1]]).astype(np.int64)
    return FrameIndex(np.asarray(pts, dtype=np.float64), start, int(c.sum()))


def frame_index(ref: StreamRef, cache: Path) -> FrameIndex:
    p = _index_path(cache, ref)
    if p.is_file():
        with np.load(p) as z:
            return FrameIndex(z["pts_time"], z["start"], int(z["total"]))
    idx = build_index(ref)
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_name(p.name + f".{os.getpid()}.tmp.npz")
    np.savez(tmp, pts_time=idx.pts_time, start=idx.start, total=np.int64(idx.total))
    os.replace(tmp, p)  # 并发构建时后写的覆盖先写的，读者只会看到完整文件
    return idx


# ---------------------------------------------------------------- 解码


_SHOWINFO = re.compile(r"Parsed_ashowinfo_\d+ @ [^\]]*\] n:\s*0 .*?pts_time:\s*(-?[\d.]+)")


def _run_ffmpeg(ref: StreamRef, seek: float, duration: float) -> np.ndarray:
    """精确定位（ffmpeg 修剪到 seek）后解码 ``duration`` 秒。只用于直接定位与预滚定位。"""
    cmd = [tools.find("ffmpeg"), "-hide_banner", "-nostdin", "-nostats", "-loglevel", "error"]
    if seek > 0:
        cmd += ["-ss", f"{float(seek):.9f}"]
    cmd += ["-t", f"{float(duration):.9f}", "-i", ref.path, "-map", f"0:a:{ref.ordinal}", "-f", "f32le", "-c:a", "pcm_f32le", "-"]
    out = subprocess.run(cmd, capture_output=True, stdin=subprocess.DEVNULL)
    err = out.stderr.decode("utf-8", "replace")
    if out.returncode != 0:
        raise CoreError("decode-failed", path=ref.path, detail=err.strip()[-300:])
    pcm = np.frombuffer(out.stdout, dtype="<f4")
    if pcm.size % ref.channels:
        raise CoreError("decode-failed", path=ref.path, detail="partial-frame")
    return pcm.reshape(-1, ref.channels)


def _stream_indexed(ref: StreamRef, seek: float, b: int, idx: FrameIndex) -> tuple[np.ndarray, int]:
    """不让 ffmpeg 修剪、不设终点：边读边从 ashowinfo 得到第一帧时间戳，够 b 个样本就停。

    （容器可能定位到比 seek 早几秒的索引点，输出端/输入端的 -t、-to 都按时长算，会读不够——实测。）
    """
    cmd = [tools.find("ffmpeg"), "-hide_banner", "-nostdin", "-nostats", "-loglevel", "info", "-copyts", "-noaccurate_seek"]
    if seek > 0:
        cmd += ["-ss", f"{seek:.9f}"]
    cmd += ["-i", ref.path, "-map", f"0:a:{ref.ordinal}", "-af", "ashowinfo", "-f", "f32le", "-c:a", "pcm_f32le", "-"]
    p = subprocess.Popen(cmd, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    found: list[float] = []
    log: list[str] = []
    seen = threading.Event()

    def read_err() -> None:
        assert p.stderr is not None
        for raw in p.stderr:
            line = raw.decode("utf-8", "replace")
            log.append(line)
            if not found:
                m = _SHOWINFO.search(line)
                if m:
                    found.append(float(m.group(1)))
                    seen.set()
        seen.set()

    t = threading.Thread(target=read_err, daemon=True)
    t.start()
    frame_bytes = 4 * ref.channels
    buf = bytearray()
    first: int | None = None
    killed = False
    assert p.stdout is not None
    while True:
        chunk = p.stdout.read(1 << 16)
        if not chunk:
            break
        buf += chunk
        if first is None and found:
            first = idx.sample_of_pts(found[0], ref.sample_rate)
        if first is not None and len(buf) // frame_bytes >= b - first:
            killed = True
            p.kill()
            break
    p.stdout.close()
    p.wait()
    t.join(timeout=5)
    if first is None:
        seen.wait(timeout=5)
        if not found:
            raise CoreError("decode-failed", path=ref.path, detail="".join(log).strip()[-300:] or "no-first-frame-info")
        first = idx.sample_of_pts(found[0], ref.sample_rate)
    if not killed and p.returncode != 0:
        raise CoreError("decode-failed", path=ref.path, detail="".join(log).strip()[-300:])
    usable = len(buf) - len(buf) % frame_bytes
    return np.frombuffer(bytes(buf[:usable]), dtype="<f4").reshape(-1, ref.channels), first


def decode_frames(ref: StreamRef, a: int, b: int, *, cache: Path) -> np.ndarray:
    """样本区间 [a, b) → float32 数组 (帧数, 声道)。越出流尾报错，不补零。"""
    if not (0 <= a < b):
        raise CoreError("range-invalid", reason="empty", start=a, end=b, duration=None)
    sr = ref.sample_rate
    need = b - a
    method = ref.method
    if method in ("direct", "preroll"):
        pre = 0 if method == "direct" else int(round(PREROLL * sr))
        s0 = max(0, a - pre)
        seek = s0 / sr
        pcm = _run_ffmpeg(ref, seek, (b - s0) / sr + 0.05)
        first = int(round(seek * sr))
    else:
        idx = frame_index(ref, cache)
        if b > idx.total:
            raise CoreError("range-invalid", reason="out-of-bounds", start=a / sr, end=b / sr, duration=idx.total / sr)
        k = idx.frame_at_or_before(max(0, a - int(round(PREROLL * sr))))
        pcm, first = _stream_indexed(ref, float(idx.pts_time[k]), b, idx)
        if first > a:
            # 容器把定位放到了目标之后（极少见）：从头解码，不猜
            pcm, first = _stream_indexed(ref, 0.0, b, idx)
    off = a - first
    seg = pcm[off : off + need]
    if off < 0 or len(seg) != need:
        raise CoreError("range-invalid", reason="out-of-bounds", start=a / sr, end=b / sr, duration=None)
    return np.ascontiguousarray(seg)


def decode_range(ref: StreamRef, start: float, end: float, *, cache: Path) -> np.ndarray:
    """文件秒区间 [start, end) → 样本 [round(start·sr), round(end·sr))。"""
    sr = ref.sample_rate
    return decode_frames(ref, int(round(start * sr)), int(round(end * sr)), cache=cache)


def decode_all(ref: StreamRef) -> np.ndarray:
    """从头解码整条流（测试的对照、峰值生成）。"""
    return _run_ffmpeg(ref, 0.0, 1e9)  # 1e9 秒 = 不设终点
