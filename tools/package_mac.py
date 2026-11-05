"""本地构建 macOS 发布包（阶段 10，所有者 2026-10-30【基线变更】：只发 macOS、本地构建、Release 由所有者说了才发、除 PyMSS 外模型随包）。

用法（仓库根目录）：``.venv/bin/python tools/package_mac.py``（``--skip-build`` 跳过前端构建，``--no-zip`` 不打包 ZIP）。
产物：``out/release/OttoSmasher.app``、``out/release/OttoSmasher-<版本>-macos-arm64.zip`` 与同名 ``.sha256``、``RELEASE_NOTES.md``。
默认先把小版本号加一（提交“版本 x.y.z”、本地标签 vx.y.z），``--no-bump`` 按当前版本重新构建。

.app 的 Contents/Resources 布局（``app/main/paths.ts``、``core/ottosmasher/resources.py`` 按这个找）：
- ``app/``：应用代码（``out/`` 的主进程、preload、界面；``app/renderer/i18n/locales``；mpv 渲染桥与 libmpv）
- ``python/``：python-build-standalone（与开发环境同一个）+ Core 及依赖（按 uv.lock，不含开发依赖）
- ``third_party/``：模型支持文件、pydomino 扩展
- ``models/``：随包的模型权重（按 registry 的 SHA-256 核对后复制）
- ``bin/``、``lib/``：ffmpeg、ffprobe、rubberband（third_party 里固定版本的那一份，由 tools/build_media_tools_macos.py 在云端生成）与 ``otto`` 启动器
- ``licenses/``：本项目与第三方的许可
全部 Mach-O 文件逐个 ad-hoc 签名，最后签整个 .app（没有 Apple 开发者证书，不公证）。
"""

from __future__ import annotations

import argparse
import re
import hashlib
import json
import os
import plistlib
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "out" / "release"
NAME = "OttoSmasher"
BUNDLE_ID = "io.github.axolyz.ottosmasher"
MIN_MACOS = "14.0"
HELPERS = ("", " (GPU)", " (Renderer)", " (Plugin)")
TOOLS = ("ffmpeg", "ffprobe", "rubberband")
SYSTEM_PREFIXES = ("/usr/lib/", "/System/")


def run(*cmd: str | Path, **kw) -> subprocess.CompletedProcess:
    return subprocess.run([str(c) for c in cmd], check=True, **kw)


def step(msg: str) -> None:
    print(f"==> {msg}", flush=True)


# ---------------------------------------------------------------- 检查


def preflight() -> dict[str, Path]:
    if sys.platform != "darwin" or os.uname().machine != "arm64":
        sys.exit("只支持在 Apple 芯片的 macOS 上构建")
    base = Path(sys.base_prefix)
    need = {
        "electron": ROOT / "node_modules" / "electron" / "dist" / "Electron.app",
        "python": base,
        "bridge": ROOT / "app" / "native" / "mpv-bridge" / "build" / "Release" / "mpv_bridge.node",
        "libmpv": ROOT / "third_party" / "libmpv" / "macos-arm64",
        "support": ROOT / "third_party" / "model-support",
        "native": ROOT / "third_party" / "native" / "darwin-arm64",
        "media": ROOT / "third_party" / "media-tools" / "macos-arm64",
        "models": ROOT / "dev-workspace" / "Models",
    }
    missing = [f"{k}: {v}" for k, v in need.items() if not v.exists()]
    if missing:
        sys.exit("缺少：\n  " + "\n  ".join(missing))
    return need


# ---------------------------------------------------------------- Electron 外壳与改名


def make_shell(src: Path, app: Path, version: str) -> None:
    if app.exists():
        shutil.rmtree(app)
    run("ditto", src, app)  # 保留框架里的符号链接
    c = app / "Contents"
    (c / "MacOS" / "Electron").rename(c / "MacOS" / NAME)
    for h in HELPERS:
        old = c / "Frameworks" / f"Electron Helper{h}.app"
        new = c / "Frameworks" / f"{NAME} Helper{h}.app"
        (old / "Contents" / "MacOS" / f"Electron Helper{h}").rename(old / "Contents" / "MacOS" / f"{NAME} Helper{h}")
        edit_plist(old / "Contents" / "Info.plist", {
            "CFBundleExecutable": f"{NAME} Helper{h}", "CFBundleName": f"{NAME} Helper{h}", "CFBundleDisplayName": f"{NAME} Helper{h}",
            "CFBundleIdentifier": f"{BUNDLE_ID}.helper{h.strip(' ()').lower() and '.' + h.strip(' ()').lower()}",
        })
        old.rename(new)
    edit_plist(c / "Info.plist", {
        "CFBundleExecutable": NAME, "CFBundleName": NAME, "CFBundleDisplayName": NAME, "CFBundleIdentifier": BUNDLE_ID,
        "CFBundleShortVersionString": version, "CFBundleVersion": version, "CFBundleIconFile": f"{NAME}.icns",
        "LSMinimumSystemVersion": MIN_MACOS, "LSApplicationCategoryType": "public.app-category.music", "NSHumanReadableCopyright": "GPL-3.0-or-later",
    })
    res = c / "Resources"
    for f in ("default_app.asar", "electron.icns"):
        (res / f).unlink(missing_ok=True)
    make_icon(res / f"{NAME}.icns")


def edit_plist(path: Path, values: dict[str, str]) -> None:
    with open(path, "rb") as fh:
        pl = plistlib.load(fh)
    pl.update(values)
    with open(path, "wb") as fh:
        plistlib.dump(pl, fh)


def make_icon(dst: Path) -> None:
    src = ROOT / "assets" / "brand" / "logo.png"
    with tempfile.TemporaryDirectory() as tmp:
        iconset = Path(tmp) / "icon.iconset"
        iconset.mkdir()
        for size in (16, 32, 128, 256, 512):
            for scale in (1, 2):
                px = size * scale
                name = f"icon_{size}x{size}{'@2x' if scale == 2 else ''}.png"
                run("sips", "-z", px, px, src, "--out", iconset / name, stdout=subprocess.DEVNULL)
        run("iconutil", "-c", "icns", iconset, "-o", dst)


# ---------------------------------------------------------------- 应用代码


def copy_app_code(res: Path, need: dict[str, Path], version: str) -> None:
    code = res / "app"
    for d in ("main", "preload", "renderer"):
        shutil.copytree(ROOT / "out" / d, code / "out" / d)
    shutil.copytree(ROOT / "app" / "renderer" / "i18n" / "locales", code / "app" / "renderer" / "i18n" / "locales")
    rel = code / "app" / "native" / "mpv-bridge" / "build"
    (rel / "Release").mkdir(parents=True)
    shutil.copy2(need["bridge"], rel / "Release" / "mpv_bridge.node")
    shutil.copytree(need["libmpv"], rel / "libmpv", symlinks=True)  # 渲染桥的 rpath：@loader_path/../libmpv
    pkg = json.loads((ROOT / "package.json").read_text(encoding="utf-8"))
    (code / "package.json").write_text(json.dumps({"name": pkg["name"], "productName": NAME, "version": version, "main": pkg["main"]}, indent=2), encoding="utf-8")


# ---------------------------------------------------------------- Python


def copy_python(res: Path, need: dict[str, Path]) -> None:
    py = res / "python"
    run("ditto", need["python"], py)
    (py / "lib" / "python3.12" / "EXTERNALLY-MANAGED").unlink(missing_ok=True)
    for d in ("test", "idlelib", "tkinter", "turtledemo", "ensurepip", "lib2to3"):
        shutil.rmtree(py / "lib" / "python3.12" / d, ignore_errors=True)
    exe = py / "bin" / "python3"
    uv = ROOT / "tools" / "uv"
    with tempfile.TemporaryDirectory() as tmp:
        req = Path(tmp) / "requirements.txt"
        run(uv, "export", "--frozen", "--no-dev", "--no-hashes", "--no-emit-project", "--format", "requirements-txt", "-o", req, stdout=subprocess.DEVNULL)
        run(uv, "pip", "install", "--python", exe, "-r", req)
    run(uv, "pip", "install", "--python", exe, "--no-deps", "--reinstall-package", "ottosmasher-core", ROOT)
    run(exe, "-c", "import ottosmasher.core.server, onnxruntime, pyopenjtalk, numpy, scipy, regex, msgspec; print('python ok')")
    # 预先编译字节码，运行时也不再写（PYTHONDONTWRITEBYTECODE）：否则用户第一次运行就往 .app 里写 __pycache__，改动签过名的内容
    # （个别第三方包里带的旧语法测试文件编译不了，不影响运行，所以不检查返回码）
    subprocess.run([str(exe), "-m", "compileall", "-q", "-j", "0", str(py / "lib" / "python3.12")], check=False, stdout=subprocess.DEVNULL)


# ---------------------------------------------------------------- 支持文件与模型


def copy_support(res: Path, need: dict[str, Path]) -> None:
    tp = res / "third_party"
    shutil.copytree(need["support"], tp / "model-support")
    shutil.copytree(need["native"], tp / "native" / "darwin-arm64")


def copy_models(res: Path, need: dict[str, Path]) -> None:
    sys.path.insert(0, str(ROOT / "core"))
    from ottosmasher.models import registry

    dst = res / "models"
    for m in registry.MODELS:
        for f in m.files:
            if f.role != "weight":
                continue
            src = need["models"] / f.rel_path
            if not src.is_file() or registry.sha256_file(src) != f.sha256:
                sys.exit(f"模型文件缺失或不对：{src}（先在开发版里下载 / 导入模型）")
            (dst / f.rel_path).parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, dst / f.rel_path)


# ---------------------------------------------------------------- 媒体工具（bundle_tools 由 build_media_tools_macos.py 调用）


def macho_deps(path: Path) -> list[str]:
    out = subprocess.run(["otool", "-L", str(path)], capture_output=True, text=True, check=True).stdout.splitlines()[1:]
    return [ln.strip().split(" (")[0] for ln in out if ln.strip()]


def rpaths(path: Path) -> list[str]:
    out = subprocess.run(["otool", "-l", str(path)], capture_output=True, text=True, check=True).stdout.splitlines()
    return [out[i + 2].split()[1] for i, ln in enumerate(out) if "LC_RPATH" in ln]


def resolve_dep(dep: str, owner: Path) -> Path | None:
    if dep.startswith(SYSTEM_PREFIXES):
        return None
    if dep.startswith("@rpath/"):
        for rp in rpaths(owner):
            p = Path(rp.replace("@loader_path", str(owner.parent)).replace("@executable_path", str(owner.parent))) / dep[len("@rpath/") :]
            if p.exists():
                return p.resolve()
        raise SystemExit(f"找不到 {dep}（{owner}）")
    if dep.startswith("@loader_path/"):
        return (owner.parent / dep[len("@loader_path/") :]).resolve()
    return Path(dep).resolve()


def bundle_tools(res: Path, need: dict[str, Path]) -> None:
    bin_dir, lib_dir = res / "bin", res / "lib"
    bin_dir.mkdir()
    lib_dir.mkdir()
    queue: list[tuple[Path, Path]] = []  # (原文件, 包内文件)
    for t in TOOLS:
        dst = bin_dir / t
        shutil.copy2(need[t], dst)
        queue.append((need[t], dst))
    done: dict[Path, str] = {}
    while queue:
        src, dst = queue.pop()
        os.chmod(dst, 0o755)
        for dep in macho_deps(dst):
            real = resolve_dep(dep, src)
            if real is None or real == src:
                continue
            name = real.name
            if real not in done:
                target = lib_dir / name
                if not target.exists():
                    shutil.copy2(real, target)
                    queue.append((real, target))
                done[real] = name
            new = f"@loader_path/{'../lib/' if dst.parent == bin_dir else ''}{name}"
            run("install_name_tool", "-change", dep, new, dst, stderr=subprocess.DEVNULL)
        if dst.parent == lib_dir:
            run("install_name_tool", "-id", f"@loader_path/{dst.name}", dst, stderr=subprocess.DEVNULL)
        for rp in rpaths(dst):
            subprocess.run(["install_name_tool", "-delete_rpath", rp, str(dst)], stderr=subprocess.DEVNULL)
    for t in TOOLS:
        bad = [d for d in macho_deps(bin_dir / t) if not d.startswith(SYSTEM_PREFIXES + ("@loader_path/",))]
        if bad:
            sys.exit(f"{t} 还引用包外的库：{bad}")


def copy_media(res: Path, need: dict[str, Path]) -> None:
    """固定版本的媒体工具放进包里：本地和云端打包用的是同一份。"""
    for sub in ("bin", "lib"):
        shutil.copytree(need["media"] / sub, res / sub, symlinks=True)


def check_min_macos(root: Path) -> None:
    """包里任何一个可执行文件或动态库要求的系统版本都不能高于声明的最低版本（ROADMAP L70）。"""
    want = tuple(int(x) for x in MIN_MACOS.split("."))
    bad = []
    for f in root.rglob("*"):
        if f.is_symlink() or not f.is_file():
            continue
        with open(f, "rb") as h:
            if h.read(4) not in (b"\xcf\xfa\xed\xfe", b"\xca\xfe\xba\xbe"):
                continue
        out = subprocess.run(["vtool", "-show-build", str(f)], capture_output=True, text=True).stdout
        for m in re.finditer(r"^\s*(?:minos|version)\s+(\d+(?:\.\d+)*)\s*$", out, re.M):
            have = tuple(int(x) for x in m.group(1).split("."))
            if have > want:
                bad.append(f"{f.relative_to(root)}: {m.group(1)}")
                break
    if bad:
        sys.exit(f"这些文件要求的系统版本高于 macOS {MIN_MACOS}：\n  " + "\n  ".join(sorted(bad)[:40]))


LAUNCHER = """#!/bin/sh
# OttoSmasher 命令行 otto（发布版）：用包里的 Python 运行；可以经 ~/.local/bin/otto 的链接调用
self="$0"
while [ -L "$self" ]; do
  link="$(readlink "$self")"
  case "$link" in /*) self="$link" ;; *) self="$(dirname "$self")/$link" ;; esac
done
R="$(cd "$(dirname "$self")/.." && pwd -P)"
unset PYTHONHOME PYTHONPATH PYTHONSTARTUP VIRTUAL_ENV
export PYTHONNOUSERSITE=1 PYTHONDONTWRITEBYTECODE=1 OTTO_RESOURCES="$R" OTTO_FFMPEG="$R/bin/ffmpeg" OTTO_FFPROBE="$R/bin/ffprobe" OTTO_RUBBERBAND="$R/bin/rubberband"
exec "$R/python/bin/python3" -m ottosmasher.cli "$@"
"""


def write_launcher(res: Path) -> None:
    p = res / "bin" / "otto"
    p.write_text(LAUNCHER, encoding="utf-8")
    os.chmod(p, 0o755)


# ---------------------------------------------------------------- 许可


VOCODER_NOTICE = """PC-NSF-HiFiGAN (models/flatten/pc_nsf_hifigan.onnx)

Original work: OpenVPI. Converted model from ARounder-183/HiFiShifter @6432687.
License: Creative Commons Attribution-NonCommercial-ShareAlike 4.0 International (CC BY-NC-SA 4.0)
https://creativecommons.org/licenses/by-nc-sa/4.0/

This model is a separate component distributed with OttoSmasher under its own license; it is NOT covered by
OttoSmasher's GPL-3.0-or-later license. OttoSmasher is distributed free of charge (non-commercial).
Commercial use or commercial redistribution of this model is not permitted. To redistribute OttoSmasher
commercially, remove Contents/Resources/models/flatten/ first. Check OpenVPI's terms before using audio
produced with this model commercially.
"""


def copy_licenses(res: Path, need: dict[str, Path]) -> None:
    d = res / "licenses"
    d.mkdir()
    shutil.copy2(ROOT / "LICENSE", d / "OttoSmasher-LICENSE.txt")
    shutil.copy2(ROOT / "docs" / "THIRD_PARTY.md", d / "THIRD_PARTY.md")
    el = need["electron"].parent
    shutil.copy2(el / "LICENSE", d / "Electron-LICENSE.txt")
    shutil.copy2(el / "LICENSES.chromium.html", d / "Chromium-LICENSES.html")
    shutil.copy2(need["python"] / "lib" / "python3.12" / "LICENSE.txt", d / "Python-LICENSE.txt")
    # 模型：各按自己的许可作为单独组件随包（THIRD_PARTY.md 的那一节原样放进来）；声码器的非商业条款单独写一份
    tp = (ROOT / "docs" / "THIRD_PARTY.md").read_text(encoding="utf-8")
    start = tp.index("### 模型权重")
    (d / "MODELS.md").write_text(tp[start : tp.index("### ", start + 4)], encoding="utf-8")
    (d / "PC-NSF-HiFiGAN-NOTICE.txt").write_text(VOCODER_NOTICE, encoding="utf-8")
    for lic in (need["media"] / "licenses").iterdir():  # build_media_tools_macos.py 随压缩包带的 ffmpeg、rubberband 许可
        shutil.copy2(lic, d / lic.name)
    for lic in (need["libmpv"] / "licenses").iterdir():  # build_libmpv_macos.sh 随压缩包带的 mpv、FFmpeg、dav1d 许可
        shutil.copy2(lic, d / f"libmpv-{lic.name}")


# ---------------------------------------------------------------- 签名与打包


def is_macho(p: Path) -> bool:
    try:
        with open(p, "rb") as fh:
            magic = fh.read(4)
    except OSError:
        return False
    return magic in (b"\xcf\xfa\xed\xfe", b"\xca\xfe\xba\xbe", b"\xfe\xed\xfa\xcf", b"\xbe\xba\xfe\xca")


def sign(app: Path) -> None:
    files = [p for p in app.rglob("*") if p.is_file() and not p.is_symlink() and is_macho(p)]
    for p in sorted(files, key=lambda x: -len(x.parts)):  # 先里后外
        run("codesign", "--force", "--sign", "-", "--timestamp=none", p, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    for b in sorted([*app.rglob("*.framework"), *app.rglob("*.app")], key=lambda x: -len(x.parts)):
        if b != app:
            run("codesign", "--force", "--sign", "-", "--timestamp=none", b, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    run("codesign", "--force", "--sign", "-", "--timestamp=none", app)
    run("codesign", "--verify", "--deep", "--strict", app)


def make_zip(app: Path, version: str) -> Path:
    z = OUT / f"{NAME}-{version}-macos-arm64.zip"
    z.unlink(missing_ok=True)
    run("ditto", "-c", "-k", "--sequesterRsrc", "--keepParent", app, z)
    size = z.stat().st_size
    if size >= 2_000_000_000:
        sys.exit(f"ZIP 超过 2 GB：{size}")
    h = hashlib.sha256(z.read_bytes()).hexdigest()
    (OUT / f"{z.name}.sha256").write_text(f"{h}  {z.name}\n", encoding="utf-8")
    print(f"{z}  {size / 1e6:.0f} MB  sha256 {h}")
    return z


# ---------------------------------------------------------------- 版本与发布说明（所有者 2026-10-31：每次构建自动加一）

VERSION_FILES = {
    "package.json": r'("version": ")(\d+\.\d+\.\d+)(")',
    "package-lock.json": r'("name": "ottosmasher",\s*"version": ")(\d+\.\d+\.\d+)(")',
    "pyproject.toml": r'(^version = ")(\d+\.\d+\.\d+)(")',
    "core/ottosmasher/__init__.py": r'(__version__ = ")(\d+\.\d+\.\d+)(")',
    "uv.lock": r'(name = "ottosmasher-core"\nversion = ")(\d+\.\d+\.\d+)(")',
}


def git(*args: str) -> str:
    return subprocess.run(["git", *args], cwd=ROOT, check=True, capture_output=True, text=True).stdout.strip()


def bump_version() -> str:
    """小版本号加一，写进全部版本位置，提交“版本 x.y.z”并打本地标签 vx.y.z。要求工作区干净：构建出来的包对应一个提交。"""
    if git("status", "--porcelain", "--untracked-files=no"):
        sys.exit("有未提交的修改：先提交（构建要对应一个提交），或用 --no-bump 按当前版本重新构建")
    old = json.loads((ROOT / "package.json").read_text(encoding="utf-8"))["version"]
    major, minor, patch = (int(x) for x in old.split("."))
    new = f"{major}.{minor}.{patch + 1}"
    for rel, pat in VERSION_FILES.items():
        f = ROOT / rel
        text = f.read_text(encoding="utf-8")
        out, n = re.subn(pat, lambda m: f"{m.group(1)}{new}{m.group(3)}", text, flags=re.M)
        if n < 1:
            sys.exit(f"{rel} 里找不到版本号 {old}")
        f.write_text(out, encoding="utf-8")
    git("add", *VERSION_FILES)
    git("commit", "-q", "-m", f"版本 {new}（构建）")
    git("tag", f"v{new}")
    print(f"版本 {old} → {new}（已提交、本地标签 v{new}）", flush=True)
    return new


def changes_since(version: str) -> str:
    """这一版相对上一个版本的提交（第一行）。上一个版本：标签 v<上一版>；没有标签（例如别人拿到的源码不带标签）就找上一个“版本 …”提交。"""
    prev = None
    tags = [t for t in git("tag", "--list", "v*", "--sort=-v:refname").splitlines() if t != f"v{version}"]
    if tags:
        prev = tags[0]
    else:
        bumps = git("log", "--format=%H", "--grep=^版本 ", "-n", "2").splitlines()
        prev = bumps[1] if len(bumps) > 1 else None
    rng = f"{prev}..HEAD" if prev else "HEAD"
    lines = [x for x in git("log", "--format=%s", "--no-merges", rng).splitlines() if not x.startswith("版本 ")]
    if not prev:
        return "- 第一个版本"
    if not lines:
        return "- 没有功能改动（重新构建）"
    return "\n".join(f"- {x if len(x) <= 160 else x[:159] + '…'}" for x in lines)


def write_notes(version: str, z: Path | None) -> None:
    sha = (OUT / f"{z.name}.sha256").read_text(encoding="utf-8").split()[0] if z else "（没有打 ZIP）"
    text = (ROOT / "tools" / "release_notes.md").read_text(encoding="utf-8").split("-->\n", 1)[1]
    for k, v in {"{version}": version, "{zip}": z.name if z else "", "{windows_zip}": f"OttoSmasher-{version}-windows-x64.zip", "{sha256}": sha, "{changes}": changes_since(version)}.items():
        text = text.replace(k, v)
    (OUT / "RELEASE_NOTES.md").write_text(text, encoding="utf-8")
    print(OUT / "RELEASE_NOTES.md")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--skip-build", action="store_true")
    ap.add_argument("--no-zip", action="store_true")
    ap.add_argument("--no-bump", action="store_true", help="不加版本号，按当前版本重新构建")
    ap.add_argument("--bump-only", action="store_true", help="只加版本号、提交并打标签，不构建（发版由标签触发云端构建）")
    a = ap.parse_args()
    if a.bump_only:
        bump_version()
        return
    need = preflight()
    if not a.no_bump:
        bump_version()
    version = json.loads((ROOT / "package.json").read_text(encoding="utf-8"))["version"]
    if not a.skip_build:
        step("构建主进程、preload 与界面")
        run(ROOT / "tools" / "npm", "run", "build", cwd=ROOT)
    OUT.mkdir(parents=True, exist_ok=True)
    app = OUT / f"{NAME}.app"
    res = app / "Contents" / "Resources"
    step("Electron 外壳（改名、图标、Info.plist）")
    make_shell(need["electron"], app, version)
    step("应用代码、mpv 渲染桥与 libmpv")
    copy_app_code(res, need, version)
    step("Python 运行时与 Core（按 uv.lock）")
    copy_python(res, need)
    step("模型支持文件、pydomino 扩展、模型权重")
    copy_support(res, need)
    copy_models(res, need)
    step("ffmpeg / ffprobe / rubberband 与它们的动态库、otto 启动器")
    copy_media(res, need)
    write_launcher(res)
    step("许可")
    copy_licenses(res, need)
    step("ad-hoc 签名")
    sign(app)
    step("核对最低系统版本")
    check_min_macos(app)
    total = sum(p.stat().st_size for p in app.rglob("*") if p.is_file() and not p.is_symlink())
    print(f"{app}  {total / 1e6:.0f} MB")
    z = None
    if not a.no_zip:
        step("ZIP")
        z = make_zip(app, version)
    step("发布说明")
    write_notes(version, z)


if __name__ == "__main__":
    main()
