"""Stage an allowlisted core application. Never copy a working .runtime or models wholesale."""

import argparse
import hashlib
import json
import platform
import shutil
import subprocess
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def digest(path):
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def audit_runtime(prefix):
    if prefix.name in {"inference", "experiment"}:
        raise ValueError("不能打包 experiment 环境")
    for path in prefix.rglob("*"):
        name = path.name.lower()
        # sklearn/scipy ship a tiny optional array-api shim, not the PyTorch runtime.
        if name == "torch" and path.parent.name == "array_api_compat":
            continue
        if name in {"torch", "torchaudio", "torchvision"} or name.startswith(
            ("torch-", "torchaudio-", "torchvision-", "libtorch")
        ):
            raise ValueError("standard 运行库不得包含 PyTorch: " + str(path))


def audit_software(directory):
    for path in directory.rglob("*"):
        if path.is_file() and (path.suffix == ".onnx" or path.name.endswith((".onnx.data", ".onnx_data"))):
            raise ValueError("应用资源混入模型权重：" + str(path))
        if path.name in {"archive", "inference", "experiment"} and path.is_dir():
            raise ValueError("应用资源混入实验环境：" + str(path))


def stage(core, player, target, onnx=None):
    import conda_pack

    target.mkdir(parents=True, exist_ok=True)
    software = target / "software"
    if software.exists():
        shutil.rmtree(software)
    software.mkdir()
    for folder in ("src", "scripts", "dependencies"):
        shutil.copytree(
            ROOT / folder, software / folder, ignore=shutil.ignore_patterns("__pycache__", "*.pyc")
        )
    shutil.copytree(ROOT / "desktop/dist", software / "desktop/dist")
    for name in ("ottosmasher.png", "pyproject.toml", "README.md", "LICENSE", "THIRD_PARTY_NOTICES.md"):
        shutil.copy2(ROOT / name, software / name)
    if onnx is None:
        raise ValueError("standard 分发必须提供独立 ONNX 环境")
    for prefix in (core, player, onnx):
        if prefix is not None:
            audit_runtime(prefix)
    if not any(onnx.rglob("otto_domino_decoder*")):
        raise ValueError("缺少 pydomino 原生解码扩展")
    # Only runtime adapters are copied; weights and development checkouts are excluded.
    adapters = ["narabas/narabas/symbols.py", "HubertFA/onnx_infer.py"] + [
        "HubertFA/tools/" + name + ".py"
        for name in ("config_utils", "infer_base", "align_word", "decoder", "plot", "export_tool", "g2p")
    ]
    for relative in adapters:
        source = ROOT / "vendor" / relative
        dest = software / "vendor" / relative
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, dest)
    for name in ("pydomino", "HubertFA", "narabas"):
        source = ROOT / "vendor" / name / "LICENSE"
        dest = software / "third-party" / name / "LICENSE"
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, dest)
    support = json.loads((ROOT / "dependencies/model-support.json").read_text())
    for item in support["files"]:
        source = ROOT / item["path"]
        if not source.is_file() or digest(source) != item["sha256"]:
            raise ValueError("缺少或损坏的模型支持文件：" + item["path"])
        dest = software / "model-support" / item["path"]
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, dest)
    preparation = software / "model-support/models/tsqyomi/preparation.json"
    preparation.write_text(json.dumps(support["tsqyomi"], indent=2), encoding="utf-8")
    audit_software(software)
    runtime = target / "runtime"
    if runtime.exists():
        shutil.rmtree(runtime)
    runtime.mkdir()
    files = []
    for name, prefix in [("core", core), ("player", player), ("onnx", onnx)]:
        if prefix is None:
            continue
        archive = runtime / f"{name}.tar.gz"
        conda_pack.pack(
            prefix=str(prefix.resolve()),
            output=str(archive),
            force=True,
            ignore_editable_packages=False,
            n_threads=2,
            filters=[("exclude", "**/*.onnx"), ("exclude", "**/*.onnx.data"), ("exclude", "**/*.onnx_data")],
        )
        files.append({"name": archive.name, "target": name, "sha256": digest(archive)})
    native = []
    for name in ["player.node"] + (["mpv-2.dll"] if platform.system() == "Windows" else []):
        shutil.copy2(ROOT / ".runtime" / name, runtime / name)
        if name == "player.node" and platform.system() == "Darwin":
            load_commands = subprocess.check_output(["otool", "-l", str(runtime / name)], text=True)
            for rpath in re.findall(r"cmd LC_RPATH\s+cmdsize \d+\s+path (.+?) \(offset", load_commands):
                if rpath.startswith("/"):
                    subprocess.run(
                        ["install_name_tool", "-delete_rpath", rpath, str(runtime / name)], check=True
                    )
            subprocess.run(["codesign", "--force", "--sign", "-", str(runtime / name)], check=True)
        native.append({"name": name, "sha256": digest(runtime / name)})
    # Include code in the runtime ID so the service cannot reuse a stale backend.
    code_hash = hashlib.sha256()
    for p in sorted(software.rglob("*")):
        if p.is_file():
            code_hash.update(p.relative_to(software).as_posix().encode())
            code_hash.update(p.read_bytes())
    manifest = {
        "platform": "win32" if platform.system() == "Windows" else "darwin",
        "arch": "x64" if platform.system() == "Windows" else "arm64",
        "files": files,
        "native": native,
        "code_sha256": code_hash.hexdigest(),
    }
    manifest["id"] = hashlib.sha256(json.dumps(manifest, sort_keys=True).encode()).hexdigest()[:20]
    (runtime / "manifest.json").write_text(json.dumps(manifest, indent=2))
    print(json.dumps({"stage": str(target), "id": manifest["id"]}))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--core", type=Path, default=ROOT / ".runtime/envs/core")
    parser.add_argument("--player", type=Path)
    parser.add_argument("--onnx", type=Path, required=True)
    parser.add_argument("--output", type=Path, default=ROOT / "build/app")
    args = parser.parse_args()
    stage(args.core, args.player, args.output, args.onnx)
