"""构建 Windows x64 发布包（DECISIONS §14：免安装 ZIP、不签名）。在 Windows 上跑，平时由云端构建（.github/workflows/windows.yml）。

用法（仓库根目录）：``.venv\\Scripts\\python.exe tools\\package_win.py``（``--skip-build`` 跳过前端构建，``--no-zip`` 不打包 ZIP）。
产物：``out/release/OttoSmasher/``、``out/release/OttoSmasher-<版本>-windows-x64.zip`` 与同名 ``.sha256``。
版本号不在这里加：macOS 的构建（tools/package_mac.py）加一并打标签，这里按当前版本打包，两端同一个提交同一个版本。

文件夹布局（``app/main/paths.ts``、``core/ottosmasher/resources.py`` 按这个找）：
- ``OttoSmasher.exe`` + Electron 的其余文件；
- ``resources/app/``：应用代码（``out/`` 的主进程、preload、界面；文案；mpv 渲染桥与旁边的 ``libmpv-2.dll``）
- ``resources/python/``：python-build-standalone（与开发环境同一个）+ Core 及依赖（按 uv.lock，不含开发依赖）
- ``resources/third_party/``：模型支持文件、pydomino 扩展
- ``resources/models/``：随包的模型权重（按 registry 的 SHA-256 核对后复制）
- ``resources/bin/``：ffmpeg、ffprobe、rubberband（third_party/media-tools）与 ``otto.cmd``
- ``resources/licenses/``：本项目与第三方的许可
"""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import subprocess
import sys
import tempfile
import zipfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from package_mac import VOCODER_NOTICE, copy_models, run, step  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "out" / "release"
NAME = "OttoSmasher"
TP = ROOT / "third_party"


def preflight() -> dict[str, Path]:
    if sys.platform != "win32":
        sys.exit("只支持在 Windows 上构建（平时用云端，见 .github/workflows/windows.yml）")
    need = {
        "electron": ROOT / "node_modules" / "electron" / "dist",
        "python": Path(sys.base_prefix),
        "bridge": ROOT / "app" / "native" / "mpv-bridge" / "build" / "Release" / "mpv_bridge.node",
        "libmpv": ROOT / "app" / "native" / "mpv-bridge" / "build" / "Release" / "libmpv-2.dll",
        "support": TP / "model-support",
        "native": TP / "native" / "win32-x64",
        "models": ROOT / "dev-workspace" / "Models",
        "ffmpeg": TP / "media-tools" / "ffmpeg",
        "rubberband": TP / "media-tools" / "rubberband",
        "rcedit": TP / "tools-win" / "rcedit-x64.exe",
        "uv": Path(shutil.which("uv") or "uv-not-found"),
    }
    missing = [f"{k}: {v}" for k, v in need.items() if not v.exists()]
    if missing:
        sys.exit("缺少：\n  " + "\n  ".join(missing))
    return need


def make_shell(need: dict[str, Path], folder: Path, version: str) -> Path:
    """Electron 外壳：改名、换图标和文件信息。"""
    if folder.exists():
        shutil.rmtree(folder)
    shutil.copytree(need["electron"], folder)
    exe = folder / f"{NAME}.exe"
    (folder / "electron.exe").rename(exe)
    (folder / "resources" / "default_app.asar").unlink(missing_ok=True)
    with tempfile.TemporaryDirectory() as tmp:
        ico = Path(tmp) / "icon.ico"
        run(need["ffmpeg"] / "bin" / "ffmpeg.exe", "-v", "error", "-y", "-i", ROOT / "assets" / "brand" / "logo-1024.png", "-vf", "scale=256:256", ico)
        run(need["rcedit"], exe, "--set-icon", ico, "--set-file-version", version, "--set-product-version", version,
            "--set-version-string", "ProductName", NAME, "--set-version-string", "FileDescription", NAME,
            "--set-version-string", "CompanyName", NAME, "--set-version-string", "LegalCopyright", "GPL-3.0-or-later",
            "--set-version-string", "OriginalFilename", f"{NAME}.exe", "--set-version-string", "InternalName", NAME)
    return exe


def copy_app_code(res: Path, need: dict[str, Path], version: str) -> None:
    code = res / "app"
    for d in ("main", "preload", "renderer"):
        shutil.copytree(ROOT / "out" / d, code / "out" / d)
    shutil.copytree(ROOT / "app" / "renderer" / "i18n" / "locales", code / "app" / "renderer" / "i18n" / "locales")
    rel = code / "app" / "native" / "mpv-bridge" / "build" / "Release"
    rel.mkdir(parents=True)
    shutil.copy2(need["bridge"], rel / "mpv_bridge.node")
    shutil.copy2(need["libmpv"], rel / "libmpv-2.dll")  # 系统按 .node 所在目录找依赖
    pkg = json.loads((ROOT / "package.json").read_text(encoding="utf-8"))
    (code / "package.json").write_text(json.dumps({"name": pkg["name"], "productName": NAME, "version": version, "main": pkg["main"]}), encoding="utf-8")


def copy_python(res: Path, need: dict[str, Path]) -> None:
    py = res / "python"
    shutil.copytree(need["python"], py)
    for d in ("test", "idlelib", "tkinter", "turtledemo", "ensurepip", "lib2to3"):
        shutil.rmtree(py / "Lib" / d, ignore_errors=True)
    (py / "Lib" / "EXTERNALLY-MANAGED").unlink(missing_ok=True)
    exe = py / "python.exe"
    uv = need["uv"]
    with tempfile.TemporaryDirectory() as tmp:
        req = Path(tmp) / "requirements.txt"
        run(uv, "export", "--frozen", "--no-dev", "--no-hashes", "--no-emit-project", "--format", "requirements-txt", "-o", req, stdout=subprocess.DEVNULL, cwd=ROOT)
        run(uv, "pip", "install", "--python", exe, "-r", req)
    run(uv, "pip", "install", "--python", exe, "--no-deps", "--reinstall-package", "ottosmasher-core", ROOT)
    run(exe, "-c", "import ottosmasher.core.server, onnxruntime, pyopenjtalk, numpy, scipy, regex, msgspec; print('python ok', onnxruntime.get_available_providers())")
    # 预先编译字节码（个别第三方包里带的旧语法测试文件编译不了，不影响运行，所以不检查返回码）
    subprocess.run([str(exe), "-m", "compileall", "-q", "-j", "0", str(py / "Lib")], check=False, stdout=subprocess.DEVNULL)


def copy_support(res: Path, need: dict[str, Path]) -> None:
    tp = res / "third_party"
    shutil.copytree(need["support"], tp / "model-support")
    shutil.copytree(need["native"], tp / "native" / "win32-x64")


LAUNCHER = """@echo off
rem otto: OttoSmasher command line (packaged)
setlocal
set "R=%~dp0.."
set PYTHONHOME=
set PYTHONPATH=
set PYTHONSTARTUP=
set VIRTUAL_ENV=
set PYTHONNOUSERSITE=1
set PYTHONDONTWRITEBYTECODE=1
set PYTHONUTF8=1
set "OTTO_RESOURCES=%R%"
set "OTTO_FFMPEG=%R%\\bin\\ffmpeg.exe"
set "OTTO_FFPROBE=%R%\\bin\\ffprobe.exe"
set "OTTO_RUBBERBAND=%R%\\bin\\rubberband.exe"
"%R%\\python\\python.exe" -m ottosmasher.cli %*
"""


def bundle_tools(res: Path, need: dict[str, Path]) -> None:
    bin_dir = res / "bin"
    bin_dir.mkdir()
    for t in ("ffmpeg.exe", "ffprobe.exe"):  # ffplay 用不上
        shutil.copy2(need["ffmpeg"] / "bin" / t, bin_dir / t)
    for t in ("rubberband.exe", "sndfile.dll"):
        shutil.copy2(need["rubberband"] / t, bin_dir / t)
    (bin_dir / "otto.cmd").write_text(LAUNCHER.replace("\n", "\r\n"), encoding="ascii", newline="")


def copy_licenses(res: Path, folder: Path, need: dict[str, Path]) -> None:
    d = res / "licenses"
    d.mkdir()
    shutil.copy2(ROOT / "LICENSE", d / "OttoSmasher-LICENSE.txt")
    shutil.copy2(ROOT / "docs" / "THIRD_PARTY.md", d / "THIRD_PARTY.md")
    shutil.copy2(folder / "LICENSE", d / "Electron-LICENSE.txt")
    shutil.move(str(folder / "LICENSES.chromium.html"), d / "Chromium-LICENSES.html")
    (folder / "LICENSE").unlink()
    (folder / "version").unlink(missing_ok=True)
    shutil.copy2(res / "python" / "LICENSE.txt", d / "Python-LICENSE.txt")
    tp = (ROOT / "docs" / "THIRD_PARTY.md").read_text(encoding="utf-8")
    start = tp.index("### 模型权重")
    (d / "MODELS.md").write_text(tp[start : tp.index("### ", start + 4)], encoding="utf-8")
    (d / "PC-NSF-HiFiGAN-NOTICE.txt").write_text(VOCODER_NOTICE.replace("Contents/Resources/models/flatten/", "resources/models/flatten/"), encoding="utf-8")
    shutil.copy2(need["ffmpeg"] / "LICENSE.txt", d / "ffmpeg-LICENSE.txt")
    shutil.copy2(need["rubberband"] / "COPYING.txt", d / "rubberband-COPYING.txt")


def make_zip(folder: Path, version: str) -> Path:
    z = OUT / f"{NAME}-{version}-windows-x64.zip"
    z.unlink(missing_ok=True)
    with zipfile.ZipFile(z, "w", zipfile.ZIP_DEFLATED, compresslevel=6) as zf:
        for p in sorted(folder.rglob("*")):
            if p.is_file():
                zf.write(p, p.relative_to(folder.parent))
    size = z.stat().st_size
    if size >= 2_000_000_000:
        sys.exit(f"ZIP 超过 2 GB：{size}")
    h = hashlib.sha256(z.read_bytes()).hexdigest()
    (OUT / f"{z.name}.sha256").write_text(f"{h}  {z.name}\n", encoding="utf-8")
    print(f"{z}  {size / 1e6:.0f} MB  sha256 {h}")
    return z


def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    ap = argparse.ArgumentParser()
    ap.add_argument("--skip-build", action="store_true")
    ap.add_argument("--no-zip", action="store_true")
    a = ap.parse_args()
    need = preflight()
    version = json.loads((ROOT / "package.json").read_text(encoding="utf-8"))["version"]
    if not a.skip_build:
        step("构建主进程、preload 与界面")
        run(shutil.which("npm") or "npm", "run", "build", cwd=ROOT)
    OUT.mkdir(parents=True, exist_ok=True)
    folder = OUT / NAME
    res = folder / "resources"
    step("Electron 外壳（改名、图标、文件信息）")
    make_shell(need, folder, version)
    step("应用代码、mpv 渲染桥与 libmpv")
    copy_app_code(res, need, version)
    step("Python 运行时与 Core（按 uv.lock）")
    copy_python(res, need)
    step("模型支持文件、pydomino 扩展、模型权重")
    copy_support(res, need)
    copy_models(res, need)
    step("ffmpeg / ffprobe / rubberband、otto 启动器")
    bundle_tools(res, need)
    step("许可")
    copy_licenses(res, folder, need)
    total = sum(p.stat().st_size for p in folder.rglob("*") if p.is_file())
    print(f"{folder}  {total / 1e6:.0f} MB")
    if not a.no_zip:
        step("ZIP")
        make_zip(folder, version)


if __name__ == "__main__":
    main()
