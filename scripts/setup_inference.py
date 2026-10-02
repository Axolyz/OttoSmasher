"""Prepare only the requested runtime; never install experimental tools globally."""

import argparse
import os
import subprocess
import sys
from pathlib import Path

CODE_ROOT = Path(__file__).resolve().parents[1]
ROOT = Path(os.environ.get("OTTO_ROOT", CODE_ROOT)).resolve()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--edition", choices=["standard", "experiment"], default="standard")
    parser.add_argument("--enable-archived", default="")
    parser.add_argument(
        "--with-models", action="store_true", help="显式下载 tsqyomi 权重；默认只准备运行环境"
    )
    args = parser.parse_args()
    os.environ.update(OTTO_EDITION=args.edition, OTTO_ARCHIVED=args.enable_archived)
    from ottosmasher.editions import enabled

    names = enabled()
    subprocess.run([sys.executable, CODE_ROOT / "scripts/fetch_sources.py"], check=True)
    targets = [("onnx", "onnx.in")]
    if args.edition == "experiment":
        targets.append(("inference", "experiment.in"))
    for name, requirements in targets:
        env = ROOT / ".runtime/envs" / name
        py = env / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
        if not py.exists():
            subprocess.run([sys.executable, "-m", "venv", env], check=True)
        locked = CODE_ROOT / "dependencies" / "onnx.macos-arm64.lock.txt"
        if name == "onnx" and sys.platform == "darwin" and locked.is_file():
            requirements = locked.name
        build_env = dict(os.environ)
        if name == "onnx":
            subprocess.run([py, "-c", "import pyopenjtalk; assert pyopenjtalk.g2p('あ')"], check=True)
            subprocess.run([py, "-m", "pip", "install", "cmake==4.4.3", "ninja==1.13.2", "wheel"], check=True)
            build_env["PATH"] = str(py.parent) + os.pathsep + build_env.get("PATH", "")
            if sys.platform == "darwin":
                compiler = Path("/Library/Developer/CommandLineTools/usr/bin")
                build_env.update(CC=str(compiler / "clang"), CXX=str(compiler / "clang++"))
        subprocess.run(
            [
                py,
                "-m",
                "pip",
                "install",
                "cmake",
                "ninja",
                "wheel",
                "-r",
                CODE_ROOT / "dependencies" / requirements,
                CODE_ROOT,
            ],
            cwd=ROOT,
            env=build_env,
            check=True,
        )
        if name == "onnx":
            subprocess.run([py, "-c", "import pyopenjtalk; assert pyopenjtalk.g2p('あ')"], check=True)
            subprocess.run(
                [py, CODE_ROOT / "scripts/setup_domino_decoder.py"], cwd=CODE_ROOT, env=build_env, check=True
            )
            if args.with_models:
                subprocess.run(
                    [py, CODE_ROOT / "scripts/prepare_tsqyomi.py"],
                    cwd=ROOT,
                    env={**build_env, "PYTHONPATH": str(CODE_ROOT / "src")},
                    check=True,
                )
        if name == "inference":
            for module in names:
                req = (
                    CODE_ROOT
                    / "archive"
                    / ("builtin_separation" if module == "builtin-separation" else "native_alignment")
                    / "requirements.txt"
                )
                subprocess.run([py, "-m", "pip", "install", "-r", req], cwd=ROOT, check=True)
        subprocess.run([py, "-m", "pip", "check"], check=True)
        freeze = subprocess.check_output([py, "-m", "pip", "freeze"], text=True)
        (ROOT / ".runtime" / f"{name}.resolved.txt").write_text(freeze)


if __name__ == "__main__":
    main()
