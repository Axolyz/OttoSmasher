"""列表缩略图取帧（ARCHITECTURE §10.2、规格 16 R22.11）。

ffmpeg 在指定时间取一帧视频，缩放裁切成固定尺寸（铺满、居中裁），存 JPEG。
输入定位用 ``-ss``（放在 ``-i`` 前，按关键帧跳再精确解到目标时间）；视频流按“第几条视频流”选（``-map 0:v:N``，与 probe 的 ordinal 一致）。
先写临时文件再改名，半成品不会被当成缓存。
"""

from __future__ import annotations

import os
import subprocess
from collections.abc import Callable
from pathlib import Path
from typing import Any

from ottosmasher.core.errors import CoreError

from . import tools

SIZES = {"list": (176, 100), "poster": (640, 360)}  # 列表 88×50 的两倍（Retina；原片行 56×32 缩着显示）；短音频查看器的画面 320×180 的两倍
WIDTH, HEIGHT = SIZES["list"]


def grab(path: str, ordinal: int, t: float, out: Path, *, size: str = "list", on_proc: Callable[[Any], None] | None = None) -> None:
    w, h = SIZES[size]
    out.parent.mkdir(parents=True, exist_ok=True)
    tmp = out.with_name(out.name + f".{os.getpid()}.tmp")
    vf = f"scale={w}:{h}:force_original_aspect_ratio=increase,crop={w}:{h}"
    args = [
        tools.find("ffmpeg"), "-nostdin", "-v", "error", "-ss", f"{max(0.0, t):.3f}", "-i", path,
        "-map", f"0:v:{ordinal}", "-frames:v", "1", "-vf", vf, "-q:v", "4", "-f", "image2", "-c:v", "mjpeg", "-y", str(tmp),
    ]  # fmt: skip
    proc = subprocess.Popen(args, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
    if on_proc:
        on_proc(proc)
    _, err = proc.communicate()
    if proc.returncode != 0 or not tmp.is_file() or tmp.stat().st_size == 0:
        tmp.unlink(missing_ok=True)
        raise CoreError("decode-failed", path=path, detail=err.decode("utf-8", "replace").strip()[-400:] or f"exit {proc.returncode}")
    os.replace(tmp, out)
