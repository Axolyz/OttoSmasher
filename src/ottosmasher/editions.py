"""Edition capabilities are enforced by the service, CLI and workers alike."""

import importlib.util
import os

from filelock import FileLock

from .workspace import CODE_ROOT, DATA

ARCHIVED = {
    "builtin-separation": {"lifecycle": "archived", "runtime": "torch", "module": "builtin_separation"},
    "native-alignment": {"lifecycle": "archived", "runtime": "torch", "module": "native_alignment"},
}


def edition():
    value = os.environ.get("OTTO_EDITION", "standard")
    if value not in ("standard", "experiment"):
        raise ValueError("未知版本：" + value)
    return value


def enabled():
    names = sorted(set(filter(None, os.environ.get("OTTO_ARCHIVED", "").split(","))))
    for name in names:
        if name not in ARCHIVED:
            raise ValueError("未知搁置模块：" + name)
        if ARCHIVED[name]["runtime"] == "torch" and edition() != "experiment":
            raise ValueError("此搁置模块需要 experiment：" + name)
    return names


def identity():
    names = enabled()
    provider = os.environ.get("OTTO_SEPARATION_PROVIDER", "studio")
    if provider not in {"studio", "builtin"}:
        raise ValueError("未知分离提供者")
    if provider == "builtin" and "builtin-separation" not in names:
        raise ValueError("内置分离必须显式启用 builtin-separation")
    return {"edition": edition(), "archived": names, "separation_provider": provider}


def require(name):
    if name not in enabled():
        raise ValueError(f"功能已长期搁置：{name}；请使用 experiment --enable-archived {name}")


def archived_module(name):
    require(name)
    path = CODE_ROOT / "archive" / ARCHIVED[name]["module"] / "adapter.py"
    spec = importlib.util.spec_from_file_location("ottosmasher._archived_" + name.replace("-", "_"), path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def require_operation(operation, payload):
    if operation == "native-alignment":
        require("native-alignment")
    if operation == "subtitles":
        raise ValueError("字幕试验已迁往 ~/Documents/AudioLab；请使用 AudioLab 启动脚本")


def capabilities():
    return {
        **identity(),
        "onnx": True,
        "torch": edition() == "experiment",
        "archived_features": ARCHIVED,
    }


def transition_lock():
    DATA.mkdir(parents=True, exist_ok=True)
    return FileLock(str(DATA / "edition.lock"), timeout=30)


def assert_idle():
    from .operation_jobs import listing

    active = [r for r in listing() if r["status"] in ("running", "queued")]
    if active:
        raise RuntimeError("请等待任务完成或取消后再切换版本：" + ", ".join(r["id"] for r in active))
