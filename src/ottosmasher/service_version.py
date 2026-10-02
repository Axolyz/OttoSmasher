"""Detect a source service left running across edits; never hot-reload modules."""

import hashlib
import json
import subprocess
import sys
import urllib.error
import urllib.request

from .workspace import CODE_ROOT, ROOT


def signature(code_root=CODE_ROOT):
    digest = hashlib.sha256()
    for folder in ("src/ottosmasher", "scripts", "dependencies", "archive"):
        for path in sorted((code_root / folder).rglob("*")):
            if path.is_file() and path.suffix in (".py", ".json", ".txt", ".yaml", ".yml"):
                digest.update(path.relative_to(code_root).as_posix().encode())
                digest.update(path.read_bytes())
    return digest.hexdigest()


# Snapshot once, not on each request: loaded Python modules do not change with disk.
LOADED_SIGNATURE = signature()


def ensure_current_service(port=18765):
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/api/helper/info", timeout=3) as response:
            info = json.load(response)
    except urllib.error.HTTPError as exc:
        raise RuntimeError(f"本地服务检查失败：HTTP {exc.code}") from exc
    except urllib.error.URLError:
        from .editions import assert_idle, identity, transition_lock
        from .workspace import DATA, write_json

        with transition_lock():
            context_file = DATA / "edition-context.json"
            previous = json.loads(context_file.read_text()) if context_file.exists() else None
            if previous != identity():
                assert_idle()
            write_json(context_file, identity())
        return  # Electron will start the service.
    if info.get("root") != str(ROOT):
        raise RuntimeError("该端口属于其他工作区；未停止其服务")
    from .editions import identity

    context = identity()
    if (
        info.get("code_signature") != LOADED_SIGNATURE
        or info.get("edition", "standard") != context["edition"]
        or info.get("archived", []) != context["archived"]
        or info.get("separation_provider", "studio") != context["separation_provider"]
    ):
        try:
            subprocess.run(
                [
                    sys.executable,
                    str(CODE_ROOT / "scripts/refresh_browser.py"),
                    "--no-build",
                    "--port",
                    str(port),
                ],
                check=True,
            )
        except subprocess.CalledProcessError as exc:
            raise RuntimeError("版本切换失败；请查看上方任务或服务错误，原任务未自动取消") from exc


def ensure_desktop_modules():
    """Archive frontend code is linked only by an explicit developer build."""
    import os

    from .editions import enabled

    expected = sorted(enabled())
    marker = CODE_ROOT / "desktop/dist/edition-modules.json"
    if marker.exists() and json.loads(marker.read_text()) == expected:
        return
    subprocess.run([str(CODE_ROOT / "scripts/setup_desktop.sh")], cwd=ROOT, check=True, env=os.environ.copy())
