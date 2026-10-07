"""进程树的启动与结束（ARCHITECTURE §2.2，规格 13 §13.1.2、16 R19.2）。

- POSIX：子进程放进独立的进程组（``start_new_session=True``），结束 = 向整个进程组发信号。
- Windows：子进程加入一个设了 ``KILL_ON_JOB_CLOSE`` 的作业对象，结束 = ``TerminateJobObject``。
  （Windows 未实测，标“未验收”。）

只结束本任务的进程树，不误伤其他任务；不用 ``kill(pid, 0)`` 在 Windows 上探活。
"""

from __future__ import annotations

import os
import signal
import subprocess
import sys
import time
from collections.abc import Sequence
from pathlib import Path
from typing import IO, Any


class ProcessTree:
    def __init__(self, popen: subprocess.Popen[bytes], job_handle: Any = None) -> None:
        self.popen = popen
        self._job = job_handle

    @property
    def pid(self) -> int:
        return self.popen.pid

    def kill(self, grace: float = 2.0) -> None:
        """结束整棵进程树：先礼后兵（POSIX：SIGTERM → 等 grace 秒 → SIGKILL）。"""
        if sys.platform == "win32":
            _win_terminate(self._job, self.popen)
            return
        try:
            pgid = os.getpgid(self.popen.pid)
        except ProcessLookupError:
            pgid = self.popen.pid
        _signal_group(pgid, signal.SIGTERM)
        deadline = time.monotonic() + grace
        while time.monotonic() < deadline:
            if self.popen.poll() is not None and not _group_alive(pgid):
                return
            time.sleep(0.05)
        _signal_group(pgid, signal.SIGKILL)
        try:
            self.popen.wait(timeout=5)
        except subprocess.TimeoutExpired:
            pass

    def close(self) -> None:
        if sys.platform == "win32" and self._job is not None:
            import ctypes

            ctypes.windll.kernel32.CloseHandle(self._job)  # type: ignore[attr-defined]
            self._job = None


def spawn_tree(
    args: Sequence[str],
    *,
    cwd: Path | None = None,
    env: dict[str, str] | None = None,
    stdout: int | IO[Any] | None = subprocess.PIPE,
    stderr: int | IO[Any] | None = None,
) -> ProcessTree:
    if sys.platform == "win32":
        flags = subprocess.CREATE_NEW_PROCESS_GROUP | 0x01000000  # CREATE_BREAKAWAY_FROM_JOB
        p = subprocess.Popen(
            list(args), cwd=cwd, env=env, stdin=subprocess.DEVNULL, stdout=stdout, stderr=stderr, creationflags=flags
        )
        return ProcessTree(p, _win_job_for(p))
    p = subprocess.Popen(
        list(args), cwd=cwd, env=env, stdin=subprocess.DEVNULL, stdout=stdout, stderr=stderr, start_new_session=True
    )
    return ProcessTree(p)


def _signal_group(pgid: int, sig: int) -> None:
    try:
        os.killpg(pgid, sig)
    except (ProcessLookupError, PermissionError):
        pass


def _group_alive(pgid: int) -> bool:
    try:
        os.killpg(pgid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


# ---------------------------------------------------------------- Windows（未验收）


def _win_job_for(p: subprocess.Popen[bytes]) -> Any:
    import ctypes
    from ctypes import wintypes

    k32 = ctypes.windll.kernel32  # type: ignore[attr-defined]
    job = k32.CreateJobObjectW(None, None)

    class IO_COUNTERS(ctypes.Structure):
        _fields_ = [(n, ctypes.c_ulonglong) for n in (
            "ReadOperationCount", "WriteOperationCount", "OtherOperationCount",
            "ReadTransferCount", "WriteTransferCount", "OtherTransferCount")]

    class BASIC(ctypes.Structure):
        _fields_ = [
            ("PerProcessUserTimeLimit", ctypes.c_int64), ("PerJobUserTimeLimit", ctypes.c_int64),
            ("LimitFlags", wintypes.DWORD), ("MinimumWorkingSetSize", ctypes.c_size_t),
            ("MaximumWorkingSetSize", ctypes.c_size_t), ("ActiveProcessLimit", wintypes.DWORD),
            ("Affinity", ctypes.c_size_t), ("PriorityClass", wintypes.DWORD), ("SchedulingClass", wintypes.DWORD),
        ]

    class EXTENDED(ctypes.Structure):
        _fields_ = [
            ("BasicLimitInformation", BASIC), ("IoInfo", IO_COUNTERS),
            ("ProcessMemoryLimit", ctypes.c_size_t), ("JobMemoryLimit", ctypes.c_size_t),
            ("PeakProcessMemoryUsed", ctypes.c_size_t), ("PeakJobMemoryUsed", ctypes.c_size_t),
        ]

    info = EXTENDED()
    info.BasicLimitInformation.LimitFlags = 0x2000  # JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
    k32.SetInformationJobObject(job, 9, ctypes.byref(info), ctypes.sizeof(info))  # JobObjectExtendedLimitInformation
    handle = k32.OpenProcess(0x1F0FFF, False, p.pid)
    k32.AssignProcessToJobObject(job, handle)
    k32.CloseHandle(handle)
    return job


def _win_terminate(job: Any, p: subprocess.Popen[bytes]) -> None:
    import ctypes

    if job is not None:
        ctypes.windll.kernel32.TerminateJobObject(job, 1)  # type: ignore[attr-defined]
    try:
        p.wait(timeout=5)
    except subprocess.TimeoutExpired:
        p.kill()
