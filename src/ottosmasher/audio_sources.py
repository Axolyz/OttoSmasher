"""Resolve model target crops back to their unchanged separated audio asset."""

import json
from functools import lru_cache
from pathlib import Path


@lru_cache(maxsize=1024)
def _manifest(path, stamp):
    return json.loads(Path(path).read_text())


def separated_source(lineage):
    if lineage.get("folder"):
        path = Path(lineage["folder"]) / "manifest.json"
        if path.exists():
            parent = _manifest(str(path), path.stat().st_mtime_ns)
            if parent.get("input_variant") != "vocals" or parent.get("source_fingerprint") != lineage.get(
                "source_fingerprint"
            ):
                raise ValueError("Separated parent asset does not match source lineage")
            return parent
    if lineage.get("crop_backend"):
        raise ValueError(
            "Full separated parent asset is missing; do not use aligner crop for source features"
        )
    return lineage
