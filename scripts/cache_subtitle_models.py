"""Import manually downloaded official weights into the isolated HF cache."""

import argparse
import hashlib
import json
import shutil
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("directory", type=Path)
    args = parser.parse_args()
    specs = json.loads((ROOT / "dependencies/subtitle-preprocessing.models.json").read_text())
    for spec in specs:
        source = args.directory / spec["rfilename"]
        with source.open("rb") as f:
            sha = hashlib.file_digest(f, "sha256").hexdigest()
        if sha != spec["lfs"]["sha256"]:
            raise ValueError(f"Model hash mismatch: {source}")
        cache = ROOT / "models/subtitle-preprocessing/hub" / ("models--" + spec["repo"].replace("/", "--"))
        blob = cache / "blobs" / sha
        blob.parent.mkdir(parents=True, exist_ok=True)
        if not blob.exists():
            shutil.copy2(source, blob)
        target = cache / "snapshots" / spec["revision"] / spec["rfilename"]
        target.parent.mkdir(parents=True, exist_ok=True)
        if not target.exists():
            target.symlink_to("../../blobs/" + sha)
        print(spec["rfilename"], "verified")


if __name__ == "__main__":
    main()
