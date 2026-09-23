"""Create a source-only portable installation directory, excluding local/private assets."""

import argparse
import shutil
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=ROOT / "dist/windows")
    args = parser.parse_args()
    target = args.output.resolve() / "OttoSmasher"
    if target.exists():
        if not (target / "WINDOWS-STATUS.txt").is_file():
            raise ValueError("Output directory already exists and is not a generated source bundle")
        shutil.rmtree(target)
    target.mkdir(parents=True, exist_ok=True)
    # Fixed allowlist: never copy .runtime, models, media, database, credentials or vendor caches.
    for name in ("src", "scripts", "dependencies", "docs", "desktop"):
        shutil.copytree(
            ROOT / name,
            target / name,
            dirs_exist_ok=True,
            ignore=shutil.ignore_patterns("__pycache__", "*.pyc", "node_modules", ".vite", "dist"),
        )
    for name in ("README.md", "pyproject.toml", "launch-windows.cmd", "ottosmasher.png"):
        shutil.copy2(ROOT / name, target / name)
    (target / "WINDOWS-STATUS.txt").write_text(
        "Source installation bundle; not a preinstalled binary distribution.\n"
        "Windows x64 native playback, CUDA, Unicode paths and high DPI await real-machine acceptance.\n"
        "Use an x64 Native Tools terminal (Visual Studio C++ Build Tools).\n"
        "powershell -ExecutionPolicy Bypass -File scripts/setup_windows.ps1\n"
        "Append -CpuOnly on CPU systems. Dependencies and models download locally.\n"
        "After installation: launch-windows.cmd. Keep the installed directory in place.\n",
        encoding="utf-8",
    )
    archive = args.output.resolve() / "OttoSmasher-windows-source.zip"
    with zipfile.ZipFile(archive, "w", zipfile.ZIP_DEFLATED) as bundle:
        for p in sorted(target.rglob("*")):
            if p.is_file():
                bundle.write(p, p.relative_to(target.parent))
    print(archive)


if __name__ == "__main__":
    main()
