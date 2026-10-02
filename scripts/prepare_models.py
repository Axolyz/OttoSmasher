"""Explicit setup-time downloads for retained models; never called by ordinary queries."""

import hashlib
import json
import os
import shutil
import urllib.request
import zipfile
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


if __name__ == "__main__":
    main()
