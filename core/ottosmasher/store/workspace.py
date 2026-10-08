"""工作区布局与独占锁（ARCHITECTURE §6，规格 13 §13.3）。

长期固定的目录名一律英文；按原片、按日期生成的子目录另行处理。
"""

from __future__ import annotations

import os
import sys
from dataclasses import dataclass
from pathlib import Path

from ..core.errors import CoreError

# 工作区里的固定目录（相对工作区根）。顺序即创建顺序。
FIXED_DIRS: tuple[str, ...] = (
    "Library",
    "Library/Tracks",
    "Library/Independent",
    "Library/Exports",
    "Library/REAPER",
    "Models",
    "Data",
    "Data/Measurements",
    "Data/Cache",
    "Data/Jobs",
    "Data/Manifests",
    "Data/Dictionary",
    "Data/Logs",
    "Data/Backups",
    "Data/Staging",
)


@dataclass(frozen=True)
class Workspace:
    root: Path

    @property
    def library(self) -> Path:
        return self.root / "Library"

    @property
    def models(self) -> Path:
        return self.root / "Models"

    @property
    def data(self) -> Path:
        return self.root / "Data"

    @property
    def db_path(self) -> Path:
        return self.data / "library.sqlite3"

    @property
    def jobs(self) -> Path:
        return self.data / "Jobs"

    @property
    def logs(self) -> Path:
        return self.data / "Logs"

    @property
    def backups(self) -> Path:
        return self.data / "Backups"

    @property
    def dictionary(self) -> Path:
        return self.data / "Dictionary"

    @property
    def staging(self) -> Path:
        return self.data / "Staging"

    def ensure(self) -> None:
        """创建固定目录；可并发调用（规格 13 §13.3.5：支持并发首次初始化）。"""
        for rel in FIXED_DIRS:
            (self.root / rel).mkdir(parents=True, exist_ok=True)


class WorkspaceLock:
    """工作区独占锁：同一工作区同时只能有一个 Core。进程退出时操作系统自动释放。"""

    def __init__(self, ws: Workspace) -> None:
        self._path = ws.data / "core.lock"
        self._fh: int | None = None

    def acquire(self) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        fd = os.open(self._path, os.O_RDWR | os.O_CREAT, 0o644)
        try:
            if sys.platform == "win32":
                import msvcrt

                msvcrt.locking(fd, msvcrt.LK_NBLCK, 1)
            else:
                import fcntl

                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            os.close(fd)
            raise CoreError("workspace-locked", path=str(self._path.parent.parent)) from None
        os.ftruncate(fd, 0)
        os.write(fd, str(os.getpid()).encode())
        self._fh = fd

    def release(self) -> None:
        if self._fh is None:
            return
        try:
            if sys.platform == "win32":
                import msvcrt

                os.lseek(self._fh, 0, os.SEEK_SET)
                msvcrt.locking(self._fh, msvcrt.LK_UNLCK, 1)
            else:
                import fcntl

                fcntl.flock(self._fh, fcntl.LOCK_UN)
        finally:
            os.close(self._fh)
            self._fh = None
