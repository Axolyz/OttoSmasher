"""正式音轨的 MP3 存储（规格 13 §13.3.2）：LAME VBR V0，带 LAME/Xing 头（编码延迟与尾部填充信息，无缝解码）。

- 采样率是 32 / 44.1 / 48 kHz 时保持，否则重采样到 48 kHz；超过 2 声道拒绝；
- 编码后解码一遍核对长度：解码帧数 − 期望帧数 必须在 [0, 1152]（只允许 MP3 尾部填充），否则编码失败、保留原文件；
- 记录编码清单（原内容 SHA-256、帧数、采样率、修剪量）。不宣称与原 PCM 逐样本相等。
"""

from __future__ import annotations

import hashlib
import subprocess
from pathlib import Path
from typing import Any

from ottosmasher.core.errors import CoreError

from .tools import find

KEEP_RATES = (32000, 44100, 48000)
MAX_TAIL = 1152


def _sha(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def decoded_frames(path: Path, channels: int) -> int:
    """用 ffmpeg 解码 MP3（按 LAME 头去掉编码延迟）数帧。"""
    proc = subprocess.run(
        [find("ffmpeg"), "-v", "error", "-nostdin", "-i", str(path), "-map", "0:a:0", "-f", "f32le", "-acodec", "pcm_f32le", "-"],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    if proc.returncode != 0:
        raise CoreError("mp3-encode-failed", reason="decode", detail=proc.stderr.decode("utf-8", "replace")[-300:])
    return len(proc.stdout) // (4 * channels)


def encode_v0(src: Path, dst: Path, *, frames: int, rate: int, channels: int) -> dict[str, Any]:
    """WAV → MP3 V0；返回编码清单。``frames`` / ``rate`` 是源 PCM 的帧数与采样率。"""
    if channels > 2:
        raise CoreError("mp3-encode-failed", reason="too-many-channels", channels=channels)
    out_rate = rate if rate in KEEP_RATES else 48000
    expected = frames if out_rate == rate else round(frames * out_rate / rate)
    args = [find("ffmpeg"), "-v", "error", "-nostdin", "-y", "-i", str(src), "-map", "0:a:0", "-c:a", "libmp3lame", "-q:a", "0"]
    if out_rate != rate:
        args += ["-ar", str(out_rate)]
    tmp = dst.with_suffix(".tmp.mp3")
    proc = subprocess.run([*args, "-write_xing", "1", str(tmp)], stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, check=False)
    if proc.returncode != 0:
        tmp.unlink(missing_ok=True)
        raise CoreError("mp3-encode-failed", reason="encode", detail=proc.stderr.decode("utf-8", "replace")[-300:])
    got = decoded_frames(tmp, channels)
    tail = got - expected
    if not 0 <= tail <= MAX_TAIL:
        tmp.unlink(missing_ok=True)
        raise CoreError("mp3-encode-failed", reason="length", expected=expected, got=got)
    tmp.replace(dst)
    return {
        "codec": "mp3-lame-v0",
        "sourceSha256": _sha(src),
        "sourceFrames": frames,
        "sourceRate": rate,
        "rate": out_rate,
        "frames": expected,
        "decodedFrames": got,
        "tailPadding": tail,
        "channels": channels,
    }


def wav_info(path: Path) -> tuple[int, int, int]:
    """(帧数, 采样率, 声道)：ffprobe 读 WAV（含浮点 WAV）。"""
    proc = subprocess.run(
        [find("ffprobe"), "-v", "error", "-select_streams", "a:0", "-count_packets", "-show_entries",
         "stream=sample_rate,channels,duration_ts,nb_frames", "-of", "default=nw=1", str(path)],
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=False,
    )  # fmt: skip
    if proc.returncode != 0:
        raise CoreError("decode-failed", path=str(path), detail=proc.stderr.decode("utf-8", "replace")[-300:])
    info = dict(line.split("=", 1) for line in proc.stdout.decode().splitlines() if "=" in line)
    rate, ch = int(info["sample_rate"]), int(info["channels"])
    frames = int(info["duration_ts"]) if info.get("duration_ts", "N/A") not in ("N/A", "") else -1
    if frames < 0:
        frames = decoded_frames(path, ch)
    return frames, rate, ch
