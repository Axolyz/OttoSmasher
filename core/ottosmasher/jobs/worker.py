"""任务进程入口：``python -m ottosmasher.jobs.worker <任务目录>``。

读 ``input.json``（种类、冻结的参数与设备设置），执行，向 stdout 逐行写 JSON 事件：
``{"type": "progress", ...}``、``{"type": "result", "result": ...}``、``{"type": "error", "code", "args"}``。
stderr 是日志。只写本任务目录；登记与否由 Core 决定（取消永远不会留下半成品登记）。
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import time
import traceback
from collections.abc import Callable
from pathlib import Path
from typing import Any

from ..core.errors import CoreError


class Ctx:
    def __init__(self, job_dir: Path, device: dict[str, Any]) -> None:
        self.job_dir = job_dir
        self.device = device

    def emit(self, msg: dict[str, Any]) -> None:
        sys.stdout.write(json.dumps(msg, ensure_ascii=False) + "\n")
        sys.stdout.flush()

    def progress(self, stage: str, done: int, total: int, code: str = "", **args: Any) -> None:
        self.emit({"type": "progress", "stage": stage, "done": done, "total": total, "code": code, "args": args})

    def log(self, text: str) -> None:
        sys.stderr.write(text + "\n")
        sys.stderr.flush()


def _models_verify(params: dict[str, Any], ctx: Ctx) -> dict[str, Any]:
    from ..models.registry import sha256_file

    paths: list[str] = params["paths"]
    out: dict[str, Any] = {}
    for i, p in enumerate(paths):
        ctx.progress("hashing", i, len(paths), "models-hashing", file=Path(p).name)
        path = Path(p)
        try:
            st = path.stat()
        except FileNotFoundError:
            continue
        out[p] = {"size": st.st_size, "mtime_ns": st.st_mtime_ns, "sha256": sha256_file(path)}
        ctx.log(f"sha256 {p} {out[p]['sha256']}")
    ctx.progress("hashing", len(paths), len(paths), "models-hashing")
    return {"hashes": out}


def _selftest_sleep(params: dict[str, Any], ctx: Ctx) -> dict[str, Any]:
    """睡一会儿；可以起若干子进程（同一进程组），用来验证取消会结束整棵树。"""
    children = []
    for _ in range(int(params.get("children", 0))):
        children.append(subprocess.Popen([sys.executable, "-c", "import time; time.sleep(600)"]))
    # 原子写入：别人（测试、诊断）随时可能来读，不能读到写了一半的文件
    tmp = ctx.job_dir / f"children.json.{os.getpid()}.tmp"
    tmp.write_text(json.dumps([c.pid for c in children]))
    os.replace(tmp, ctx.job_dir / "children.json")
    seconds = float(params.get("seconds", 1.0))
    steps = max(1, int(seconds / 0.05))
    for i in range(steps):
        ctx.progress("sleeping", i, steps, "selftest-sleeping")
        time.sleep(seconds / steps)
    for c in children:
        c.terminate()
        c.wait()
    return {"slept": seconds, "device": ctx.device}


def _selftest_fail(params: dict[str, Any], ctx: Ctx) -> dict[str, Any]:
    ctx.log("selftest: failing on purpose")
    raise CoreError("selftest-failed", reason=params.get("reason", "requested"))


HANDLERS: dict[str, Callable[[dict[str, Any], Ctx], dict[str, Any]]] = {
    "models.verify": _models_verify,
    "selftest.sleep": _selftest_sleep,
    "selftest.sleep_model": _selftest_sleep,
    "selftest.fail": _selftest_fail,
}


def main(argv: list[str]) -> int:
    job_dir = Path(argv[1])
    spec = json.loads((job_dir / "input.json").read_text(encoding="utf-8"))
    ctx = Ctx(job_dir, spec.get("device", {}))
    handler = HANDLERS.get(spec["kind"])
    if handler is None:
        ctx.emit({"type": "error", "code": "job-kind-unknown", "args": {"kind": spec["kind"]}})
        return 1
    try:
        result = handler(spec.get("params", {}), ctx)
    except CoreError as exc:
        ctx.emit({"type": "error", "code": exc.code, "args": exc.args_})
        return 1
    except Exception as exc:  # noqa: BLE001 — 任何异常都变成失败，并把栈写进日志
        traceback.print_exc()
        ctx.emit({"type": "error", "code": "job-exception", "args": {"type": type(exc).__name__, "message": str(exc)}})
        return 1
    ctx.emit({"type": "result", "result": result})
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
