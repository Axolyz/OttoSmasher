"""Build only the pinned pydomino decoder; no second ONNX Runtime or weights."""

import os
import subprocess
import sys
import sysconfig
from pathlib import Path

root = Path(__file__).resolve().parents[1]
build = root / ".runtime/build/domino-decoder"
extra = []
if sys.platform == "darwin":
    dev = Path("/Library/Developer/CommandLineTools")
    try:
        compiler = subprocess.check_output(
            ["/usr/bin/xcrun", "--find", "clang++"], text=True, stderr=subprocess.DEVNULL
        ).strip()
    except subprocess.CalledProcessError:
        compiler = str(dev / "usr/bin/clang++")
    extra = ["-DCMAKE_CXX_COMPILER=" + compiler]
    if os.environ.get("SDKROOT"):
        extra.append("-DCMAKE_OSX_SYSROOT=" + os.environ["SDKROOT"])
subprocess.run(
    [
        "cmake",
        "-S",
        str(root / "scripts/domino-decoder"),
        "-B",
        str(build),
        "-DCMAKE_BUILD_TYPE=Release",
        "-DDOMINO_SOURCE=" + str(root / "vendor/pydomino"),
        "-DPYTHON_EXECUTABLE=" + sys.executable,
        "-DCMAKE_INSTALL_PREFIX=" + sysconfig.get_path("platlib"),
        *extra,
    ],
    check=True,
)
subprocess.run(["cmake", "--build", str(build), "--config", "Release", "--parallel", "2"], check=True)
subprocess.run(["cmake", "--install", str(build), "--config", "Release"], check=True)
