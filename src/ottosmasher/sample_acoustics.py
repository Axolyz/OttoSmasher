"""Audio capabilities and cached acoustic frames, independent of transcription."""

import json
from pathlib import Path

from . import sample_audio
from .workspace import identity


def capabilities(db, mid):
    roles, errors = [], {}
    for role in ("selected", "raw", "vocals", "residual"):
        try:
            asset = sample_audio.resolve(db, mid, role)
            roles.append({"value": role, "audio_role": asset["role"]})
        except (ValueError, OSError) as exc:
            errors[role] = str(exc)
    return {
        "roles": roles,
        "errors": errors,
        "default_role": "selected" if any(r["value"] == "selected" for r in roles) else "raw",
    }


def cached(db, mid, role="selected"):
    asset = sample_audio.resolve(db, mid, role)
    # Exactly the PCM cache key, without creating/decoding audio in a GET request.
    path = sample_audio.DATA / "sample-cache" / (identity("sample-pcm-v1", asset) + ".features.json")
    offset = 0
    if not path.is_file() and asset.get("path"):
        path = Path(asset["path"]).with_suffix(".features.json")
        offset = asset["start"]
    if not path.is_file():
        return {"status": "missing", "frames": None, "role": asset["role"]}
    raw = json.loads(path.read_text())
    keep = [i for i, t in enumerate(raw["times"]) if offset <= t < asset["end"] - asset["start"] + offset]
    frames = {k: [raw[k][i] for i in keep] for k in ("times", "f0_hz", "voiced", "energy", "confidence")}
    frames["times"] = [t - offset for t in frames["times"]]
    return {"status": "ready", "frames": frames, "role": asset["role"], "model": raw.get("model")}
