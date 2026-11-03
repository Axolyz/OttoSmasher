"""``python -m ottosmasher --workspace <目录>``：启动 Core，stdio 上收发 msgpack 帧。"""

from __future__ import annotations

import argparse
import faulthandler
import logging
import logging.handlers
import os
import sys
from pathlib import Path

from .core.errors import CoreError
from .core.rpc import FrameWriter
from .core.server import Core


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="ottosmasher")
    ap.add_argument("--workspace", required=True, type=Path)
    ap.add_argument("--support-dir", type=Path, default=None)
    ap.add_argument("--dev", action="store_true", help="dev mode: allow self-test jobs")
    ap.add_argument("--no-agent-link", action="store_true", help="do not open the local endpoint for the command line (otto)")
    args = ap.parse_args(argv)

    # stdout 只用来传帧；任何意外的 print 都改到 stderr
    out = sys.stdout.buffer
    sys.stdout = sys.stderr

    core = Core(args.workspace, support_dir=args.support_dir, dev=args.dev, agent_link=not args.no_agent_link)
    logs = args.workspace / "Data" / "Logs"
    logs.mkdir(parents=True, exist_ok=True)
    # 诊断卡死：设了就每隔这么多秒把所有线程的调用栈写进 Data/Logs/hang-dump.log（平时不设）
    dump_every = os.environ.get("OTTO_HANG_DUMP_SECONDS")
    if dump_every:
        faulthandler.dump_traceback_later(float(dump_every), repeat=True, file=open(logs / "hang-dump.log", "wb", buffering=0))  # noqa: SIM115 — 进程结束才关
    handler = logging.handlers.RotatingFileHandler(logs / "core.log", maxBytes=5 * 1024 * 1024, backupCount=5, encoding="utf-8")
    logging.basicConfig(level=logging.INFO, handlers=[handler, logging.StreamHandler(sys.stderr)],
                        format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    try:
        core.open()
    except CoreError as exc:
        # 打不开工作区：发一个错误事件再退出（主进程据此提示）
        FrameWriter(out).event("core.fatal", exc.to_wire())
        logging.error("core failed to open: %r", exc)
        return 2
    try:
        # 读端用无缓冲的原始文件：读线程阻塞在 read 时退出解释器，不会因为缓冲区锁而中止
        stdin_raw = open(sys.stdin.fileno(), "rb", buffering=0, closefd=False)  # noqa: SIM115
        core.serve(stdin_raw, out)
    finally:
        core.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
