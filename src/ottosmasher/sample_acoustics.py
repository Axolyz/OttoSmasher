"""Audio capabilities and cached acoustic frames, independent of transcription."""

import json
import bisect
import threading
from collections import OrderedDict

_FRAME_CACHE = OrderedDict()
_FRAME_LOCK = threading.RLock()
_FRAME_BYTES = 0
_FRAME_BUDGET = 64 * 1024 * 1024


def _frames(path):
    """Bounded immutable-file cache; return shared data, slice before exposing."""
    global _FRAME_BYTES
    stat = path.stat()
    key = (str(path), stat.st_size, stat.st_mtime_ns)
    with _FRAME_LOCK:
        if key in _FRAME_CACHE:
            _FRAME_CACHE.move_to_end(key)
            return _FRAME_CACHE[key][0]
        raw = json.loads(path.read_text())
        # Python lists/numbers cost substantially more than their JSON text.
        cost = max(stat.st_size * 5, sum(len(v) * 40 for v in raw.values() if isinstance(v, list)))
        if cost <= _FRAME_BUDGET:
            while _FRAME_CACHE and _FRAME_BYTES + cost > _FRAME_BUDGET:
                _, (_, previous) = _FRAME_CACHE.popitem(last=False)
                _FRAME_BYTES -= previous
            _FRAME_CACHE[key] = (raw, cost)
            _FRAME_BYTES += cost
        return raw
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
    return cached_asset(asset)


def cached_asset(asset):
    # Exactly the PCM cache key, without creating/decoding audio in a GET request.
    path = sample_audio.DATA / "sample-cache" / (identity("sample-pcm-v1", asset) + ".features.json")
    offset = 0
    if not path.is_file() and asset.get("path"):
        path = Path(asset["path"]).with_suffix(".features.json")
        offset = asset["start"]
    if not path.is_file():
        return {"status": "missing", "frames": None, "role": asset["role"]}
    raw = _frames(path)
    first = bisect.bisect_left(raw["times"], offset)
    last = bisect.bisect_left(raw["times"], asset["end"] - asset["start"] + offset)
    frames = {k: raw[k][first:last] for k in ("times", "f0_hz", "voiced", "energy", "confidence")}
    frames["times"] = [t - offset for t in frames["times"]]
    return {"status": "ready", "frames": frames, "role": asset["role"], "model": raw.get("model")}
