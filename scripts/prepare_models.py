"""Explicit setup-time downloads for retained models; never called by ordinary queries."""

import hashlib
import json
import shutil
import subprocess
import sys
import urllib.request
import zipfile
import os
from pathlib import Path

CODE_ROOT = Path(__file__).resolve().parents[1]
ROOT = Path(os.environ.get("OTTO_ROOT", CODE_ROOT)).resolve()


def get(url, path, sha=None):
    if path.is_file():
        if not sha or hashlib.file_digest(path.open("rb"), "sha256").hexdigest() == sha:
            return
        raise ValueError(f"Existing model has a different checksum: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    for attempt in range(2):
        try:
            with (
                urllib.request.urlopen(url, timeout=60) as inp,
                path.with_suffix(".download").open("wb") as out,
            ):
                shutil.copyfileobj(inp, out)
            tmp = path.with_suffix(".download")
            if sha and hashlib.file_digest(tmp.open("rb"), "sha256").hexdigest() != sha:
                raise ValueError("Checksum mismatch: " + str(path))
            tmp.replace(path)
            return
        except OSError as e:
            if attempt:
                raise RuntimeError(f"Download failed. Download {url} as {path}: {e}") from e


def main():
    # Call the unified runtime for model-specific conversion and HF snapshots.
    if "--worker" not in sys.argv:
        from ottosmasher.inference_runtime import python_path

        subprocess.run([python_path(), __file__, "--worker"], cwd=ROOT, check=True)
        return
    from huggingface_hub import snapshot_download
    from pymss.model_download import download_model
    from pymss.model_registry import resolve_model

    for model in ["becruily_deux", "bs_roformer_voc_hyperacev2"]:
        try:
            resolve_model(model, model_dir=ROOT / "models/separation")
        except (ValueError, FileNotFoundError):
            download_model(model, model_dir=ROOT / "models/separation", source="huggingface", timeout=60)
    lock = json.loads((CODE_ROOT / "dependencies/models.lock.json").read_text())
    model = ROOT / "models/narabas/narabas-v0.onnx"
    get(
        "https://github.com/darashi/narabas-models/releases/download/v0/narabas-v0.onnx",
        model,
        lock[str(model.relative_to(ROOT))]["sha256"],
    )
    if not (ROOT / "models/hubert/1218_hfa_model_new_dict/model.onnx").is_file():
        archive = ROOT / ".runtime/downloads/hubert-model.zip"
        get(
            "https://github.com/wolfgitpr/HubertFA/releases/download/v0.0.7/1218_hfa_model_new_dict.zip",
            archive,
        )
        with zipfile.ZipFile(archive) as z:
            for n in z.namelist():
                if not (ROOT / "models/hubert" / n).resolve().is_relative_to(ROOT / "models/hubert"):
                    raise ValueError("Unsafe archive member")
            z.extractall(ROOT / "models/hubert")
    fcpe = json.loads((CODE_ROOT / "dependencies/features-models.json").read_text())["fcpe"]
    get(fcpe["download_url"], ROOT / fcpe["path"], fcpe["sha256"])
    flat = json.loads((CODE_ROOT / "dependencies/flatten-model.json").read_text())
    base = "https://raw.githubusercontent.com/ARounder-183/HiFiShifter/6432687173ae343ef0f2f824695650e877739ee0/backend/src-tauri/resources/models/nsf_hifigan/"
    get(base + "pc_nsf_hifigan.onnx", ROOT / flat["path"], flat["sha256"])
    get(base + "config.json", ROOT / flat["config"], flat["config_sha256"])
    folder = ROOT / "models/sound-lab/bandit-v2"
    if not (folder / "model.ckpt").is_file():
        import torch

        get(
            "https://zenodo.org/records/12701995/files/checkpoint-multi.ckpt",
            folder / "checkpoint-multi.ckpt",
        )
        state = torch.load(folder / "checkpoint-multi.ckpt", map_location="cpu", weights_only=True)[
            "state_dict"
        ]
        torch.save(
            {k.removeprefix("model."): v for k, v in state.items() if k.startswith("model.")},
            folder / "model.ckpt",
        )
    if not (folder / "config.yaml").exists():
        shutil.copyfile(CODE_ROOT / "dependencies/bandit-v2.yaml", folder / "config.yaml")
    for name, repo in [
        ("yohane", "NextFire/mms-300m-ForcedAligner-karaoke-ja-Latn"),
        ("qwen3-aligner", "Qwen/Qwen3-ForcedAligner-0.6B-hf"),
    ]:
        folder = ROOT / "models" / name
        if (folder / "model.safetensors").exists() and (
            name != "qwen3-aligner" or (folder / "chat_template.jinja").exists()
        ):
            continue
        try:
            snapshot_download(
                repo,
                local_dir=folder,
                allow_patterns=["*.json", "*.safetensors", "*.txt", "*.jinja", "README.md", "LICENSE"],
                max_workers=2,
            )
        except Exception as e:
            raise RuntimeError(
                f"Download incomplete. Obtain files from https://huggingface.co/{repo}/tree/main and place them in {folder}: {e}"
            ) from e


if __name__ == "__main__":
    main()
