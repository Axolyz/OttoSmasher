"""Exact source cores at target frames, with pitch-preserving bridges between."""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path

import numpy as np
import soundfile as sf

from .media import LOCK, render
from .workspace import DATA, ROOT, command, identity, write_json

VERSION = "protected-cores-rubberband-v4-shared"


def rubberband():
    paths = sorted((ROOT / ".runtime/rubberband").glob("rubberband/*/bin/rubberband"))
    if not paths:
        from .workspace import executable
        return Path(executable('rubberband')), dict(os.environ)
    env = {
        **os.environ,
        "DYLD_LIBRARY_PATH": ":".join(str(p) for p in (ROOT / ".runtime/rubberband").glob("*/*/lib")),
    }
    return paths[-1], env


def stretch(piece, frames, sr, scratch, index):
    if frames < 1 or not len(piece):
        raise ValueError("A speech bridge cannot have zero frames")
    if len(piece) == frames:
        return piece.copy()
    binary, env = rubberband()
    src = scratch / f"{index}-in.wav"
    out = scratch / f"{index}-out.wav"
    sf.write(src, piece, sr, subtype="FLOAT")
    command([binary, "-q", "-3", "-D", f"{frames / sr:.12f}", src, out], env=env, timeout=120)
    data, rate = sf.read(out, dtype="float32", always_2d=True)
    if rate != sr:
        raise ValueError("Stretcher changed sample rate")
    if len(data) < frames:
        data = np.pad(data, ((0, frames - len(data)), (0, 0)))
    data = data[:frames]
    # Original shoulders blend only inside bridges, never into protected cores.
    shoulder = min(round(0.003 * sr), len(piece) // 4, frames // 4)
    if shoulder:
        fade = np.linspace(0, 1, shoulder, dtype=np.float32)[:, None]
        data[:shoulder] = piece[:shoulder] * (1 - fade) + data[:shoulder] * fade
        data[-shoulder:] = data[-shoulder:] * (1 - fade) + piece[-shoulder:] * fade
    return data


def render_strict(cue, analysis, plan, variant="vocals"):
    path, base = render(
        cue, variant=variant, lineage=analysis.get("audio_lineage"), selection=analysis.get("audio_selection")
    )
    y, sr = sf.read(path, dtype="float32", always_2d=True)
    from .time_mapping import schedule

    timing = schedule(plan, base["source_start"], len(y), sr)
    cores, total = timing["cores"], timing["total_frames"]
    key = identity(VERSION, base, plan["plan_id"], sr)
    folder = DATA / "previews"
    folder.mkdir(parents=True, exist_ok=True)
    target = folder / (key + ".wav")
    meta_path = folder / (key + ".json")
    with LOCK:
        if target.exists() and meta_path.exists():
            return target, json.loads(meta_path.read_text())
        out = np.zeros((total, y.shape[1]), dtype=np.float32)
        rendered_segments = timing["segments"]
        with tempfile.TemporaryDirectory(prefix=key, dir=folder) as tmp:
            scratch = Path(tmp)
            for i, segment in enumerate(rendered_segments):
                l, r = segment["source_frames"]
                x, z = segment["target_frames"]
                out[x:z] = y[l:r] if segment["kind"] == "core" else stretch(y[l:r], z - x, sr, scratch, i)
        for c in cores:
            if not np.array_equal(
                out[c["target_start"] : c["target_end"]], y[c["source_start"] : c["source_end"]]
            ):
                raise ValueError("Protected source core was altered")
        temporary = target.with_suffix(".tmp.wav")
        sf.write(temporary, out, sr, subtype="PCM_24")
        os.replace(temporary, target)
        meta = {
            **base,
            "backend": VERSION,
            "plan_id": plan["plan_id"],
            "plan": plan,
            **timing,
            "cores": cores,
            "segments": rendered_segments,
            "speech_bridge_ratios": [
                (s["target_frames"][1] - s["target_frames"][0])
                / (s["source_frames"][1] - s["source_frames"][0])
                for s in rendered_segments
                if s["kind"] == "bridge"
            ],
            "sample_rate": sr,
            "actual_duration": total / sr,
            "timeline_start_seconds": timing["timeline_start_seconds"],
            "timeline_end_seconds": timing["timeline_end_seconds"],
            "local_warp": True,
            "speech_warp": "protected_onset_cores",
            "boundary_note": "Core samples are fixed. Other phone boundaries are edit-map estimates, not re-detected measurements.",
        }
        write_json(meta_path, meta)
    return target, meta
