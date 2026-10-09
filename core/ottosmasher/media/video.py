"""视频片段（规格 12 §12.5、16 R21.9、S7；ARCHITECTURE §10.3）：按“输出帧 → 源时间”的函数逐帧取**最近的源帧**，不插帧、不做光流。

- 源帧：ffmpeg 按区间解码（``-ss`` 精确定位 + ``-copyts``，``showinfo`` 报每帧的真实时间），按时间顺序流式读取；
  输出帧需要的源时间单调不减时（原声、同映射变速）一边读一边选，内存只放两帧；循环动画先整段读进内存（很短）。
- 超出视频流范围的输出帧补黑帧（调用方在完成提示里说明，不移动音频）。
- 编码：默认 H.264（yuv420p，CRF 18）+ AAC 256k，MP4；可选高质量中间编码 ProRes 422 HQ + PCM 24-bit（MOV）。宽高补成偶数。
- 帧数 = ⌈时长 × 帧率⌉，输出按音频时长截断：时长与音频一致（不加 -shortest，避免截掉音频）。帧率写成分数（24000/1001）。
"""

from __future__ import annotations

import math
import queue
import re
import subprocess
import threading
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from fractions import Fraction
from pathlib import Path
from typing import Any

import numpy as np

from ottosmasher.core.errors import CoreError

from . import tools

_PTS = re.compile(r"pts_time:\s*(-?[\d.]+)")


@dataclass(frozen=True)
class VideoInfo:
    width: int
    height: int
    fps: float
    start: float  # 第一帧的时间（流时间，秒）
    end: float  # 最后一帧之后（start + 时长）


def info(path: str, ordinal: int = 0) -> VideoInfo:
    """视频流（或图片）的尺寸、帧率、起止。"""
    cmd = [tools.find("ffprobe"), "-v", "error", "-select_streams", f"v:{ordinal}", "-show_entries",
           "stream=width,height,avg_frame_rate,r_frame_rate,start_time,duration,nb_frames:format=duration", "-of", "json", path]
    try:
        out = subprocess.run(cmd, capture_output=True, check=True, timeout=60).stdout
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired) as e:
        raise CoreError("video-probe-failed", path=path, detail=str(e)[:300]) from None
    import json

    d = json.loads(out)
    streams = d.get("streams") or []
    if not streams:
        raise CoreError("video-probe-failed", path=path, detail="no video stream")
    s = streams[0]

    def rate(v: Any) -> float:
        try:
            f = float(Fraction(str(v)))
            return f if 0 < f < 1000 else 0.0
        except (ValueError, ZeroDivisionError):
            return 0.0

    fps = rate(s.get("avg_frame_rate")) or rate(s.get("r_frame_rate")) or 30.0
    start = float(s.get("start_time") or 0.0)
    dur = s.get("duration") or (d.get("format") or {}).get("duration")
    dur_f = float(dur) if dur not in (None, "N/A") else 1.0 / fps
    return VideoInfo(int(s["width"]), int(s["height"]), fps, start, start + dur_f)


def _reader(path: str, ordinal: int, a: float, b: float, w: int, h: int, on_proc: Callable[[Any], None] | None) -> Iterator[tuple[float, bytes]]:
    """解码 [a, b]（流时间）里的帧：逐帧给出（时间, rgb24 字节）。"""
    cmd = [
        tools.find("ffmpeg"), "-hide_banner", "-nostdin", "-loglevel", "info", "-copyts", "-ss", f"{max(0.0, a):.6f}", "-i", path,
        # -copyts 下要用 -to（输出时间戳是原片时间；-t 会按绝对时间戳截断，长片子后段一帧都不出）
        "-map", f"0:v:{ordinal}", "-to", f"{max(0.0, b):.6f}", "-vf", f"showinfo,scale={w}:{h}:flags=bicubic,format=rgb24",
        "-fps_mode", "passthrough", "-f", "rawvideo", "-",
    ]
    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    if on_proc:
        on_proc(proc)
    times: queue.Queue[float | None] = queue.Queue()
    tail: list[str] = []

    def errs() -> None:
        assert proc.stderr is not None
        for raw in proc.stderr:
            line = raw.decode("utf-8", "replace")
            if "Parsed_showinfo" in line:
                m = _PTS.search(line)
                if m:
                    times.put(float(m.group(1)))
            else:
                tail.append(line)
                del tail[:-20]
        times.put(None)

    th = threading.Thread(target=errs, daemon=True)
    th.start()
    size = w * h * 3
    assert proc.stdout is not None
    try:
        while True:
            buf = proc.stdout.read(size)
            if len(buf) < size:
                break
            t = times.get(timeout=60)
            if t is None:
                break
            yield t, buf
    finally:
        proc.stdout.close()
        rc = proc.wait()
        th.join(5)
        if rc != 0:
            raise CoreError("video-export-failed", detail="".join(tail)[-500:])


def rate_text(fps: float) -> str:
    """帧率写成分数（23.976 → 24000/1001），容器里的帧率才干净。"""
    return str(Fraction(fps).limit_denominator(1001))


def frame_count(duration: float, fps: float) -> int:
    """要生成的画面帧数：向上取整，最后按音频时长截断。"""
    return max(1, int(math.ceil(duration * fps - 1e-6)))


def even(v: int) -> int:
    return v + (v % 2)


def render(
    out: Path,
    *,
    frames: int,
    fps: float,
    size: tuple[int, int],
    picture: dict[str, Any],
    times: list[float],
    audio: str | None,
    codec: str = "h264",
    duration: float | None = None,
    on_proc: Callable[[Any], None] | None = None,
    progress: Callable[[int, int], None] | None = None,
) -> dict[str, Any]:
    """写视频文件。``times[k]`` = 第 k 个输出帧要取的画面时间（画面文件的流时间；NaN = 黑帧）。
    ``picture``：{"kind": "video"|"image"|"loop", "path", "ordinal", "start", "end"}；loop 的 times 已经取过模。返回黑帧数。"""
    w, h = size
    w2, h2 = even(w), even(h)
    blank = bytes(w * h * 3)
    if codec == "prores":
        vcodec = ["-c:v", "prores_ks", "-profile:v", "3", "-pix_fmt", "yuv422p10le"]
        acodec = ["-c:a", "pcm_s24le"]
    else:
        vcodec = ["-c:v", "libx264", "-preset", "medium", "-crf", "18", "-pix_fmt", "yuv420p", "-movflags", "+faststart"]
        acodec = ["-c:a", "aac", "-b:a", "256k"]
    cmd = [tools.find("ffmpeg"), "-hide_banner", "-nostdin", "-loglevel", "error", "-y",
           "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{w}x{h}", "-r", rate_text(fps), "-i", "-"]
    if audio:
        cmd += ["-i", audio]
    cmd += ["-map", "0:v"] + (["-map", "1:a"] + acodec if audio else ["-an"])
    # 时长与音频一致：画面帧数向上取整，再按音频时长截（不加 -shortest，不截掉音频）
    cut = ["-t", f"{duration:.6f}"] if duration else ["-frames:v", str(frames)]
    cmd += ["-vf", f"pad={w2}:{h2}"] + vcodec + ["-r", rate_text(fps), *cut, str(out)]
    enc = subprocess.Popen(cmd, stdin=subprocess.PIPE, stderr=subprocess.PIPE)
    if on_proc:
        on_proc(enc)
    black = 0
    assert enc.stdin is not None
    try:
        kind = picture["kind"]
        if kind in ("image", "loop"):
            # 图片：重复同一帧；循环动画：整段读进内存，按取过模的时间取最近帧
            seq = list(_reader(picture["path"], int(picture.get("ordinal", 0)), picture["start"], picture["end"] + 1.0, w, h, on_proc))
            if not seq:
                raise CoreError("video-export-failed", detail="no frames in picture")
            ts = np.array([t for t, _ in seq])
            for k, t in enumerate(times):
                if kind == "image" or not math.isfinite(t):
                    buf = seq[0][1] if kind == "image" else blank
                    black += 0 if kind == "image" else 1
                else:
                    buf = seq[int(np.argmin(np.abs(ts - t)))][1]
                enc.stdin.write(buf)
                if progress and k % 10 == 0:
                    progress(k, frames)
        else:
            finite = [t for t in times if math.isfinite(t)]
            # 每个输出帧取最近的源帧：源时间单调不减时流式读取（原声、同映射变速）
            if finite and any(b < a - 1e-9 for a, b in zip(finite, finite[1:], strict=False)):
                raise CoreError("video-export-failed", detail="non-monotonic picture times")
            src = _reader(picture["path"], int(picture.get("ordinal", 0)), (min(finite) - 1.0) if finite else 0.0,
                          (max(finite) + 1.0) if finite else 0.0, w, h, on_proc) if finite else iter(())
            cur: tuple[float, bytes] | None = next(src, None)
            nxt: tuple[float, bytes] | None = next(src, None)
            for k, t in enumerate(times):
                if not math.isfinite(t) or t < picture["start"] - 0.5 / fps or t >= picture["end"] or cur is None:
                    enc.stdin.write(blank)
                    black += 1
                    continue
                while nxt is not None and abs(nxt[0] - t) <= abs(cur[0] - t):
                    cur, nxt = nxt, next(src, None)
                enc.stdin.write(cur[1])
                if progress and k % 10 == 0:
                    progress(k, frames)
            for _ in src:  # 读完，让解码进程正常退出
                pass
    except BrokenPipeError:
        pass
    finally:
        enc.stdin.close()
        rc = enc.wait()
    if rc != 0:
        err = (enc.stderr.read() if enc.stderr else b"").decode("utf-8", "replace")
        raise CoreError("video-export-failed", detail=err[-500:])
    return {"black": black}
