"""检索进程池在真实 Core 的条件下启动：另一个线程正阻塞在读 stdin（Core 的请求通道）。

Windows 上同步管道有未完成的读取时，别的线程碰同一个句柄可能卡住；Core 的单元测试多用内联模式，覆盖不到这里。
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

SCRIPT = """
import faulthandler, os, sys, threading, time
from pathlib import Path

from ottosmasher.core import search_worker as sw

if __name__ == "__main__":
    faulthandler.dump_traceback_later(60, exit=True)
    threading.Thread(target=lambda: sys.stdin.buffer.read(), daemon=True).start()
    time.sleep(0.5)
    pool = sw.SearchPool(Path(sys.argv[1]), Path(sys.argv[2]), workers=2)
    slot = pool.acquire()
    res = pool.run(sw.selftest_wait, [(0.1,), (0.1,)], slot)
    print("ok" if res and not any(r["cancelled"] for r in res) else f"bad {res}", flush=True)
    pool.shutdown()
    os._exit(0)  # 另一个线程还卡在读 stdin，正常退出解释器会报错
"""


def test_pool_starts_while_another_thread_reads_stdin(tmp_path: Path):
    from ottosmasher.store.db import connect

    db = tmp_path / "空格 工作区" / "otto.db"
    db.parent.mkdir()
    connect(db).close()
    script = tmp_path / "pool_probe.py"
    script.write_text(SCRIPT, encoding="utf-8")
    p = subprocess.Popen(
        [sys.executable, str(script), str(db), str(tmp_path)],
        stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, encoding="utf-8", errors="replace",
    )
    try:
        # stdin 一直开着（真实 Core 也是）：先等探针跑完，不能用 communicate（它一上来就关 stdin）
        assert p.wait(timeout=120) is not None
        out, err = p.stdout.read(), p.stderr.read()
    finally:
        p.kill()
    assert p.returncode == 0 and out.strip() == "ok", f"rc={p.returncode}\nstdout={out}\nstderr={err}"
