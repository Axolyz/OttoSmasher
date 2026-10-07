"""发现 PyMSS Studio 的安装与环境（规格 14 §14.6.1）。只读：不改 Studio 的任何文件、不替它装依赖。

- 安装目录：设置 ``studio.app_path``，留空自动检测（macOS ``/Applications/Pymss Studio.app``、``~/Applications/…``；Windows 候选未实机验证）；
  资源目录依次试 ``<app>/Contents/Resources``、``<app>/resources``、``<app>``（给的是 .exe 时先取父目录），以存在 ``python/worker.py`` 为准。
- 数据目录：设置 ``studio.data_dir``，默认 ``~/.pymss-studio``。
- 活动推理环境：``<数据目录>/runtime-envs/active-runtime.json``，再试 ``<资源目录>/python-runtime/runtime-envs/active-runtime.json``；
  取 ``pythonPath``（相对路径以该 JSON 所在目录为基准）。
- 模型目录：``<数据目录>/settings/app.json`` 的 ``modelDir``，否则 ``<数据目录>/models``。
- 版本：macOS 读 ``Info.plist`` 的 CFBundleShortVersionString；其他平台未知（None）。

格式来自对 0.0.18 的只读观察，不是官方承诺：未知字段忽略、缺字段明确报错。
"""

from __future__ import annotations

import json
import os
import plistlib
import sys
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from ottosmasher.core.errors import CoreError


@dataclass(frozen=True)
class StudioEnv:
    app: str
    resources: str
    worker: str
    data_dir: str
    runtime_file: str
    python: str
    model_dir: str
    version: str | None

    def wire(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def of(cls, d: dict[str, Any]) -> StudioEnv:
        return cls(**{k: d[k] for k in cls.__dataclass_fields__})


def app_candidates() -> list[Path]:
    home = Path.home()
    if sys.platform == "darwin":
        return [Path("/Applications/Pymss Studio.app"), home / "Applications" / "Pymss Studio.app"]
    if sys.platform == "win32":
        out = []
        for var, sub in (("LOCALAPPDATA", "Programs/Pymss Studio"), ("LOCALAPPDATA", "Programs/pymss-studio"), ("ProgramFiles", "Pymss Studio")):
            base = os.environ.get(var)
            if base:
                out.append(Path(base) / sub)
        return out
    return []


def _resources(app: Path) -> Path | None:
    if app.is_file():  # 给的是 .exe
        app = app.parent
    for cand in (app / "Contents" / "Resources", app / "resources", app):
        if (cand / "python" / "worker.py").is_file():
            return cand
    return None


def _version(app: Path) -> str | None:
    plist = app / "Contents" / "Info.plist"
    try:
        with plist.open("rb") as f:
            v = plistlib.load(f).get("CFBundleShortVersionString")
        return str(v) if v else None
    except (OSError, plistlib.InvalidFileException):
        return None


def discover(app_path: str = "", data_dir: str = "") -> StudioEnv:
    apps = [Path(app_path).expanduser()] if app_path else app_candidates()
    app = res = None
    for cand in apps:
        r = _resources(cand) if cand.exists() else None
        if r is not None:
            app, res = cand, r
            break
    if app is None or res is None:
        raise CoreError("studio-not-found", path=app_path or None)
    data = Path(data_dir).expanduser() if data_dir else Path.home() / ".pymss-studio"
    runtime = None
    for cand in (data / "runtime-envs" / "active-runtime.json", res / "python-runtime" / "runtime-envs" / "active-runtime.json"):
        if cand.is_file():
            runtime = cand
            break
    if runtime is None:
        raise CoreError("studio-no-runtime")
    try:
        info = json.loads(runtime.read_text(encoding="utf-8"))
        py = info["pythonPath"]
    except (OSError, ValueError, KeyError, TypeError):
        raise CoreError("studio-no-runtime", detail="bad-active-runtime") from None
    python = Path(py) if Path(py).is_absolute() else (runtime.parent / py)
    python = Path(os.path.normpath(python))
    if not python.exists():
        raise CoreError("studio-no-runtime", detail="python-missing", path=str(python))
    model_dir = data / "models"
    try:
        md = json.loads((data / "settings" / "app.json").read_text(encoding="utf-8")).get("modelDir")
        if isinstance(md, str) and md:
            model_dir = Path(md).expanduser()
    except (OSError, ValueError):
        pass
    return StudioEnv(
        app=str(app),
        resources=str(res),
        worker=str(res / "python" / "worker.py"),
        data_dir=str(data),
        runtime_file=str(runtime),
        python=str(python),
        model_dir=str(model_dir),
        version=_version(app),
    )


def worker_env(env: StudioEnv) -> dict[str, str]:
    """子进程环境（14 §14.6.2）：数据目录、模型目录、活动环境；不继承 PYTHONPATH / PYTHONHOME；UTF-8。"""
    out = {k: v for k, v in os.environ.items() if k not in ("PYTHONPATH", "PYTHONHOME")}
    out.update(
        {
            "PYMSS_STUDIO_DATA_ROOT": env.data_dir,
            "PYMSS_MODEL_DIR": env.model_dir,
            "PYMSS_STUDIO_RUNTIME_ENVS_DIR": str(Path(env.runtime_file).parent),
            "PYMSS_STUDIO_ACTIVE_RUNTIME_FILE": env.runtime_file,
            "PYTHONNOUSERSITE": "1",
            "PYTHONUTF8": "1",
        }
    )
    return out
