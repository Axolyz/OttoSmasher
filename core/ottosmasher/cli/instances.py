"""正在运行的应用登记在哪、otto 用哪个、怎么打开应用（所有者 2026-11-04）。

应用主进程启动时写 ``<登记目录>/<pid>.json``（应用路径、otto 路径、工作区、版本，不含连接密钥），退出时删掉（app/main/main.ts）。
otto 优先连和自己同一种的应用：发布版的 otto 连发布版，仓库里的 tools/otto 连开发版，免得开发版的改动写进日常工作区。
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any

from .. import resources
from ..core import agent_link


def registry_dir() -> Path:
    env = os.environ.get("OTTO_REGISTRY_DIR")
    if env:
        return Path(env)
    if sys.platform == "win32":
        base = Path(os.environ.get("APPDATA") or Path.home() / "AppData" / "Roaming")
        return base / "OttoSmasher" / "instances"
    return Path.home() / "Library" / "Application Support" / "OttoSmasher" / "instances"


def build() -> str:
    return "packaged" if resources.packaged() else "source"


def running() -> list[dict[str, Any]]:
    """活着的应用，最新启动的在前；进程已经不在的（崩溃留下的）顺手删掉。"""
    out = []
    try:
        files = list(registry_dir().glob("*.json"))
    except OSError:
        return []
    for f in files:
        try:
            info = json.loads(f.read_text(encoding="utf-8"))
            alive = agent_link._alive(int(info["pid"]))
        except (OSError, ValueError, KeyError, TypeError):
            continue
        if alive:
            out.append(info)
        else:
            f.unlink(missing_ok=True)
    return sorted(out, key=lambda i: str(i.get("startedAt", "")), reverse=True)


def workspace_of_running() -> Path | None:
    """没指定工作区时用哪个：同一种应用里默认工作区优先，其次最新启动的；没有同一种的就不猜。"""
    mine = [Path(i["workspace"]) for i in running() if i.get("build") == build() and i.get("workspace")]
    if not mine:
        return None
    default = resources.default_workspace()
    return default if default in mine else mine[0]


def app_location() -> Path:
    """这个 otto 属于哪个应用：发布版 = .app（Windows 是 exe），源码运行 = 仓库。"""
    if not resources.packaged():
        return resources.REPO
    root = resources.root()
    return root.parent / "OttoSmasher.exe" if sys.platform == "win32" else root.parent.parent


def launch(workspace: Path | None) -> None:
    """打开应用，不等它就绪。``workspace``：明确指定时才传，否则应用用自己的默认工作区。"""
    app = app_location()
    env = {k: v for k, v in os.environ.items() if not k.startswith(("OTTO_", "PYTHON")) and k != "VIRTUAL_ENV"}
    if workspace is not None:
        env["OTTO_WORKSPACE"] = str(workspace)
    if not resources.packaged():
        env["OTTO_DEV"] = "1"
        for k in ("OTTO_REGISTRY_DIR", "OTTO_LOCALE", "OTTO_MPV_AO"):
            if k in os.environ:
                env[k] = os.environ[k]
        if sys.platform == "win32":
            raise OSError("from a source checkout on Windows, start the app with: npm start")  # 仓库的 tools/npm 只有 macOS 版
        _detached([str(app / "tools" / "npm"), "start"], env, cwd=app)
    elif sys.platform == "win32":
        _detached([str(app)], env, cwd=app.parent)
    else:
        args = ["open", "-a", str(app)]
        if workspace is not None:
            args += ["--env", f"OTTO_WORKSPACE={workspace}"]
        subprocess.run(args, env=env, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)


def _detached(cmd: list[str], env: dict[str, str], cwd: Path) -> None:
    kw: dict[str, Any] = {"creationflags": 0x00000008 | 0x00000200} if sys.platform == "win32" else {"start_new_session": True}  # DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP
    subprocess.Popen(cmd, env=env, cwd=cwd, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, **kw)
