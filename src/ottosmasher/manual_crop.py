"""Non-destructive manual media bounds; model labels stay unchanged."""

import hashlib

import numpy as np
import soundfile as sf

from .workspace import DATA, identity


def apply_crop(analysis, start, end):
    parent = analysis.get("alignment_input_lineage")
    if not parent or not parent["window_start"] <= start < end <= parent["window_end"]:
        raise ValueError("Crop must stay inside the original contextual vocal window")
    phones = analysis.get("phones", [])
    if phones and (start > phones[0]["start"] or end < phones[-1]["end"]):
        raise ValueError("Crop must retain all model phonemes; use grouping for rhythm corrections")
    y, sr = sf.read(parent["audio_path"], always_2d=True)
    a, b = round((start - parent["window_start"]) * sr), round((end - parent["window_start"]) * sr)
    y = y[a:b]
    key = identity(parent, a, b)
    folder = DATA / "manual-crops"
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / f"{key}.wav"
    sf.write(path, y, sr, subtype="PCM_24")
    start, end = parent["window_start"] + a / sr, parent["window_start"] + b / sr
    lineage = {
        **parent,
        "audio_path": str(path),
        "audio_sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
        "window_start": start,
        "window_end": end,
        "parent_audio_sha256": parent["audio_sha256"],
        "crop_version": "manual-crop-v1",
    }
    return {
        **analysis,
        "audio_lineage": lineage,
        "window_start": start,
        "window_end": end,
        "manual_crop": [start, end],
        "waveform": [float(np.max(np.abs(x))) for x in np.array_split(y, min(180, len(y)))],
    }
