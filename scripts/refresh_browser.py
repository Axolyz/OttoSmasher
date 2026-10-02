"""Rebuild the Helper and restart only its HTTP process, leaving jobs alive."""

import argparse
import http.client
import json
import os
import shutil
import signal
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

CODE_ROOT = Path(__file__).resolve().parents[1]
ROOT = Path(os.environ.get("OTTO_ROOT", CODE_ROOT)).expanduser().resolve()
parser = argparse.ArgumentParser()
parser.add_argument("--port", type=int, default=18765)
parser.add_argument("--no-build", action="store_true")
a = parser.parse_args()
origin = f"http://127.0.0.1:{a.port}"


def status():
    try:
        with urllib.request.urlopen(origin + "/api/helper/info", timeout=2) as r:
            result = json.load(r)
        if result.get("root") != str(ROOT):
            raise RuntimeError("该端口属于其他工作区；未停止其服务")
        return True
    except (urllib.error.URLError, TimeoutError, ConnectionError, http.client.RemoteDisconnected):
        return False


from ottosmasher.editions import assert_idle, identity, transition_lock
from ottosmasher.workspace import DATA, write_json

# Serialize the entire restart against task admission. The new service does not acquire this lock.
lock = transition_lock()
lock.acquire()
import atexit

atexit.register(lock.release)
assert_idle()
write_json(DATA / "edition-context.json", identity())
if not a.no_build:
    subprocess.run([str(CODE_ROOT / "scripts/setup_desktop.sh")], cwd=CODE_ROOT, check=True)
if status():
    lsof = shutil.which("lsof") or "/usr/sbin/lsof"
    pids = subprocess.check_output([lsof, "-ti", f"tcp:{a.port}", "-sTCP:LISTEN"], text=True).split()
    for pid in set(pids):
        cmd = subprocess.check_output(["ps", "-p", pid, "-o", "command="], text=True)
        if "ottosmasher.cli serve" not in cmd or str(CODE_ROOT) not in cmd:
            raise RuntimeError("未识别 HTTP 服务进程；请手动关闭后重试")
        os.kill(int(pid), signal.SIGTERM)
    for _ in range(50):
        if not status():
            break
        time.sleep(0.1)
    else:
        raise RuntimeError("HTTP 服务未停止")
logpath = ROOT / "data/logs/desktop-service.log"
logpath.parent.mkdir(parents=True, exist_ok=True)
with logpath.open("ab") as log:
    subprocess.Popen(
        [sys.executable, "-m", "ottosmasher.cli", "serve", "--port", str(a.port)],
        cwd=ROOT,
        env={**os.environ, "OTTO_ROOT": str(ROOT), "PYTHONPATH": str(CODE_ROOT / "src")},
        stdin=subprocess.DEVNULL,
        stdout=log,
        stderr=log,
        start_new_session=True,
    )
for _ in range(100):
    if status():
        print(f"已更新：{origin}/helper/ — 版本 {identity()['edition']}；请刷新页面。")
        break
    time.sleep(0.2)
else:
    raise RuntimeError(f"服务未启动，请查看 {logpath}")
