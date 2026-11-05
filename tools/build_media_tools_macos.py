"""在云端的 macOS 14 上生成随包的 ffmpeg、ffprobe、rubberband（.github/workflows/build-media-tools.yml）。

只构建一次，产物放进 third-party 预发布版本并在 tools/third_party.json 里固定 SHA-256；本地和云端打包都用这同一份，
结果不随构建机器的 Homebrew 变化。在 macOS 14 上取 Homebrew 的成品，最低系统版本才是 14（所有者 2026-11-04，ROADMAP L70）。

用法：python tools/build_media_tools_macos.py <输出目录>   （要先 brew install ffmpeg rubberband）
产物：<输出目录>/media-tools-macos-arm64-<ffmpeg 版本>.tar.gz，解压后是 bin/、lib/、licenses/、versions.txt。
"""

from __future__ import annotations

import shutil
import subprocess
import sys
import tarfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from package_mac import MIN_MACOS, TOOLS, bundle_tools, check_min_macos  # noqa: E402


def main() -> None:
    out = Path(sys.argv[1]).resolve()
    name = "media-tools-macos-arm64"
    d = out / name
    shutil.rmtree(d, ignore_errors=True)
    d.mkdir(parents=True)
    need = {}
    for t in TOOLS:
        p = shutil.which(t)
        if not p:
            sys.exit(f"{t} 不在 PATH 上：先 brew install ffmpeg rubberband")
        need[t] = Path(p).resolve()
    bundle_tools(d, need)
    for f in sorted((d / "bin").iterdir()) + sorted((d / "lib").iterdir()):
        subprocess.run(["codesign", "--force", "--sign", "-", str(f)], check=True, capture_output=True)
    check_min_macos(d)
    lic = d / "licenses"
    lic.mkdir()
    for t in ("ffmpeg", "rubberband"):
        prefix = need[t].parents[1]
        for f in list(prefix.glob("LICENSE*")) + list(prefix.glob("COPYING*")):
            shutil.copy2(f, lic / f"{t}-{f.name}")
    # 能真的运行，并记下版本
    ff = subprocess.run([str(d / "bin" / "ffmpeg"), "-version"], capture_output=True, text=True, check=True).stdout.splitlines()[0]
    fp = subprocess.run([str(d / "bin" / "ffprobe"), "-version"], capture_output=True, text=True, check=True).stdout.splitlines()[0]
    rb = subprocess.run([str(d / "bin" / "rubberband"), "--version"], capture_output=True, text=True)
    rb_ver = (rb.stdout + rb.stderr).strip().splitlines()[0]
    (d / "versions.txt").write_text(f"built for macOS {MIN_MACOS}\n{ff}\n{fp}\nrubberband {rb_ver}\n", encoding="utf-8")
    version = ff.split()[2]
    tar = out / f"{name}-{version}.tar.gz"
    with tarfile.open(tar, "w:gz") as tf:
        tf.add(d, arcname=name)
    print(tar)
    print((d / "versions.txt").read_text(encoding="utf-8"))


if __name__ == "__main__":
    main()
