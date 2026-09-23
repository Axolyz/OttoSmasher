"""Native playback descriptors: original video plus the exact selected audio asset."""

import json
import re
from pathlib import Path

from .workspace import DATA, identity, write_json


def register(video, start, end, asset, streams):
    from .sample_audio import pcm

    if not asset.get("path"):
        asset = {**asset, "path": str(pcm(asset)), "start": 0, "end": end - start, "audio_stream": 0}
    raw = Path(asset["path"]).resolve() == Path(video).resolve()
    audio_tracks = [s["index"] for s in streams if s["codec_type"] == "audio"]
    spec = {
        "path": str(Path(video).resolve()),
        "start": start,
        "end": end,
        "audio_path": None if raw else asset["path"],
        "aid": audio_tracks.index(asset["audio_stream"]) + 1 if raw else None,
        "audio_delay": start - asset["start"],
        "asset": asset,
        "version": 1,
    }
    paths = [spec["path"]] + ([spec["audio_path"]] if spec["audio_path"] else [])
    spec["files"] = {p: [Path(p).stat().st_size, Path(p).stat().st_mtime_ns] for p in paths}
    key = identity("native-player-v1", spec)
    write_json(DATA / "cache/native-player" / (key + ".json"), spec)
    return {
        "url": "/api/helper/native-player/" + key,
        "origin": start,
        "duration": end - start,
        "audio_source": asset["role"],
        "native": True,
        "waveform_url": f"/api/helper/native-player/{key}/waveform",
    }


def load(key):
    if not re.fullmatch("[a-f0-9]{24}", key):
        raise ValueError("无效原生播放标识")
    spec = json.loads((DATA / "cache/native-player" / (key + ".json")).read_text())
    for p, fingerprint in spec["files"].items():
        stat = Path(p).stat()
        if [stat.st_size, stat.st_mtime_ns] != fingerprint:
            raise ValueError("播放音源已改变，请重新打开")
    return spec


def waveform(key):
    from .media_operations import waveform as peaks

    a = load(key)["asset"]
    return peaks(a["path"], a["start"], a["end"], a.get("audio_stream", 0), bins=32000)
