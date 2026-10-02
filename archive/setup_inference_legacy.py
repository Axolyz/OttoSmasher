"""Build the single project inference environment. No global packages or shell edits."""

import os
import subprocess
import sys
from pathlib import Path

CODE_ROOT = Path(__file__).resolve().parents[1]
ROOT = Path(os.environ.get("OTTO_ROOT", CODE_ROOT)).resolve()
ENV = ROOT / ".runtime/envs/inference"


def run(args, **kw):
    subprocess.run(list(map(str, args)), cwd=ROOT, check=True, **kw)


def main():
    run([sys.executable, CODE_ROOT / "scripts/fetch_sources.py"])
    run([sys.executable, CODE_ROOT / "scripts/patch_inference_sources.py"])
    py = ENV / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
    if not py.is_file():
        run([sys.executable, "-m", "venv", ENV])
    run([py, "-m", "pip", "install", "--retries", "1", "cmake==4.4.3", "ninja==1.13.2", "wheel"])
    env = dict(os.environ)
    cmake = ENV / (
        "Lib/site-packages/cmake/data/bin"
        if os.name == "nt"
        else "lib/python3.11/site-packages/cmake/data/bin"
    )
    env["PATH"] = str(cmake) + os.pathsep + env["PATH"]
    if sys.platform == "darwin":
        cc = Path("/Library/Developer/CommandLineTools/usr/bin")
        env.update(CC=str(cc / "clang"), CXX=str(cc / "clang++"))
    platform = "windows-x64" if os.name == "nt" else "macos-arm64"
    lock = CODE_ROOT / "dependencies" / ("inference." + platform + ".lock.txt")
    req = lock if lock.is_file() else CODE_ROOT / "dependencies/inference.in"
    if os.name == "nt":
        # CUDA wheel selection is explicit; CPU-only systems use --CpuOnly.
        index = os.environ.get("OTTO_TORCH_INDEX", "https://download.pytorch.org/whl/cu130")
        run(
            [
                py,
                "-m",
                "pip",
                "install",
                "--retries",
                "1",
                "torch==2.14.0",
                "torchaudio==2.11.0",
                "--index-url",
                index,
            ],
            env=env,
        )
    run([py, "-m", "pip", "install", "--retries", "1", "-r", req], env=env)
    run([py, "-m", "pip", "install", "--retries", "1", CODE_ROOT])
    run([py, "-m", "pip", "check"])
    run([py, "-m", "ottosmasher.inference_runtime"])
    resolved = subprocess.check_output([str(py), "-m", "pip", "freeze"], cwd=ROOT, text=True)
    (ROOT / ".runtime" / ("inference." + platform + ".resolved.txt")).write_text(resolved, encoding="utf-8")


if __name__ == "__main__":
    main()
