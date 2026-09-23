"""Build the Windows x64 addon against pinned Electron and libmpv headers."""

import hashlib
import json
import shutil
import subprocess
import tarfile
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SDK = ROOT / ".runtime/player-sdk"
MPV = "https://github.com/shinchiro/mpv-winbuild-cmake/releases/download/20260923/mpv-dev-x86_64-20260923-git-6fd80b2003.7z"
SHA = "372f29c292d0c8b4ce916225739e5872e35b8e11f3f4590c285baed8ba551100"


def fetch(url, target, sha=None):
    target.parent.mkdir(parents=True, exist_ok=True)
    if not target.exists():
        error = None
        for _ in range(2):
            try:
                with (
                    urllib.request.urlopen(url, timeout=60) as inp,
                    target.with_suffix(".part").open("wb") as out,
                ):
                    shutil.copyfileobj(inp, out)
                target.with_suffix(".part").replace(target)
                error = None
                break
            except OSError as exc:
                error = exc
        if error:
            raise RuntimeError(f"Download failed. Save {url} to {target}: {error}")
    if sha and hashlib.file_digest(target.open("rb"), "sha256").hexdigest() != sha:
        raise ValueError(f"Checksum mismatch: {target}")
    return target


def main(build_only=False):
    SDK.mkdir(parents=True, exist_ok=True)
    if not shutil.which("cl"):
        raise RuntimeError(
            "Install Visual Studio C++ Build Tools and run this script from an x64 Native Tools terminal (cl.exe missing)."
        )
    if not build_only:
        archive = fetch(MPV, SDK / "mpv.7z", SHA)
        seven = shutil.which("7z") or shutil.which("7zr")
        if not seven:
            raise RuntimeError("Missing 7zip; install the core runtime first")
        subprocess.run([seven, "x", "-y", str(archive), "-o" + str(SDK / "mpv")], check=True)
        version = json.loads((ROOT / "desktop/package.json").read_text())["devDependencies"][
            "electron"
        ].lstrip("^~")
        headers = fetch(
            f"https://electronjs.org/headers/v{version}/node-v{version}-headers.tar.gz",
            SDK / "headers.tar.gz",
        )
        with tarfile.open(headers) as tar:
            tar.extractall(SDK / "electron", filter="data")
        fetch(f"https://electronjs.org/headers/v{version}/win-x64/node.lib", SDK / "node.lib")
    node_header = next((SDK / "electron").rglob("node_api.h"))
    client_header = next((SDK / "mpv").rglob("client.h"))
    dll = next((SDK / "mpv").rglob("libmpv-2.dll"), None) or next((SDK / "mpv").rglob("mpv-2.dll"))
    shutil.copyfile(dll, ROOT / ".runtime/mpv-2.dll")
    subprocess.run(
        [
            "cl",
            "/nologo",
            "/std:c++17",
            "/EHsc",
            "/LD",
            "/utf-8",
            "/DNAPI_VERSION=8",
            "/I" + str(node_header.parent),
            "/I" + str(client_header.parent.parent),
            str(ROOT / "desktop/native/player_win.cpp"),
            "/link",
            str(SDK / "node.lib"),
            "user32.lib",
            "/OUT:" + str(ROOT / ".runtime/player.node"),
        ],
        cwd=SDK,
        check=True,
    )
    print("Windows libmpv addon built; native playback still requires hardware validation.")
