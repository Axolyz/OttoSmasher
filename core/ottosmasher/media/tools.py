"""外部媒体工具的位置（ARCHITECTURE §1.2、AGENTS §4）。

查找顺序：环境变量 ``OTTO_FFPROBE`` / ``OTTO_FFMPEG`` → ``PATH``（开发期用本机 Homebrew 版本，只调用不改动）。
发布包里的位置在阶段 10 定（由主进程通过环境变量传入）。
找不到就报 ``tool-missing``，不换别的工具（P6）。
"""

from __future__ import annotations

import os
import shutil
from functools import cache
from pathlib import Path

from ottosmasher.core.errors import CoreError

_ENV = {"ffprobe": "OTTO_FFPROBE", "ffmpeg": "OTTO_FFMPEG"}


@cache
def find(tool: str) -> str:
    env = os.environ.get(_ENV.get(tool, ""), "")
    if env:
        if Path(env).is_file():
            return env
        raise CoreError("tool-missing", tool=tool, path=env)
    found = shutil.which(tool)
    if found:
        return found
    raise CoreError("tool-missing", tool=tool, path=None)
