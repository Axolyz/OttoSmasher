#!/usr/bin/env python3
"""Install isolated libmpv and build the macOS N-API view. No global changes."""

import argparse
import os
import platform
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--prefix", type=Path, default=ROOT / ".runtime/envs/player")
    parser.add_argument("--build-only", action="store_true", help="Reuse the installed player environment")
    args = parser.parse_args()
    if platform.system() == "Windows":
        from setup_player_windows import main as build_windows
        return build_windows(args.build_only)
    if platform.system() != "Darwin":
        raise SystemExit("The native view adapter currently supports macOS only.")
    runtime = args.prefix.resolve()
    mamba = ROOT / ".runtime/bin/micromamba"
    if not args.build_only:
        if not mamba.is_file():
            raise SystemExit("Run the project bootstrap first: .runtime/bin/micromamba is missing")
        subprocess.run(
            [
                str(mamba),
                "install" if (runtime / "conda-meta").exists() else "create",
                "-y",
                "-p",
                str(runtime),
                "-c",
                "conda-forge",
                "--strict-channel-priority",
                "mpv=0.41.0",
                "nodejs=22",
            ],
            check=True,
        )
    compiler = Path(subprocess.check_output(["xcrun", "--find", "clang++"], text=True).strip())
    dev = Path(subprocess.check_output(["xcode-select", "-p"], text=True).strip())
    sdk = Path(os.environ["SDKROOT"]) if os.environ.get("SDKROOT") else dev / "SDKs/MacOSX.sdk"
    if not sdk.is_dir():
        sdk = Path(subprocess.check_output(["xcrun", "--sdk", "macosx", "--show-sdk-path"], text=True).strip())
    if not compiler.is_file() or not sdk.is_dir():
        raise SystemExit("Apple Command Line Tools are required; set DEVELOPER_DIR if installed elsewhere")
    subprocess.run(
        [
            str(compiler),
            "-std=c++17",
            "-mmacosx-version-min=14.0",
            "-shared",
            "-undefined",
            "dynamic_lookup",
            "-fblocks",
            "-Wno-deprecated-declarations",
            "-isysroot",
            str(sdk),
            "-I" + str(runtime / "include/node"),
            "-I" + str(runtime / "include"),
            str(ROOT / "desktop/native/player.mm"),
            "-L" + str(runtime / "lib"),
            "-lmpv",
            "-framework",
            "Cocoa",
            "-framework",
            "OpenGL",
            "-Wl,-rpath," + str(runtime / "lib"),
            "-Wl,-rpath,@loader_path/player/lib",
            "-o",
            str(ROOT / ".runtime/player.building.node"),
        ],
        check=True,
    )
    (ROOT / ".runtime/player.building.node").replace(ROOT / ".runtime/player.node")
    print("libmpv ready:", ROOT / ".runtime/player.node")


if __name__ == "__main__":
    main()
