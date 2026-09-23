"""One rendered buffer for speech, rhythm clicks and the actual search witness."""

from __future__ import annotations

import os
import re
import shutil

import numpy as np
import soundfile as sf
from praatio import textgrid

from .media import LOCK, render
from .timeline import map_time
from .workspace import DATA, ROOT, identity, write_json


def click_track(times, length, sr=48000, frequency=1200):
    y = np.zeros(length, dtype=np.float32)
    size = round(0.025 * sr)
    t = np.arange(size) / sr
    pulse = (0.24 * np.sin(2 * np.pi * frequency * t) * np.exp(-t * 180)).astype(np.float32)
    pulse[0] = 0.24
    for time in times:
        start = round(time * sr)
        if start < 0 or start >= length:
            continue
        count = min(size, length - start)
        y[start : start + count] += pulse[:count]
    return y


def render_witness(cue, analysis, witness, variant="vocals"):
    """Audition the exact quantized plan selected by retrieval."""
    if not witness.get("strict_plan"):
        raise ValueError("Legacy deformation playback retired; search again for a plan_id")
    from .strict_audio import render_strict

    return render_strict(cue, analysis, witness["strict_plan"], variant)


def preview(cue, analysis, view, mode, variant="vocals", witness=None):
    if mode == "aligned":
        path, meta = render_witness(cue, analysis, witness, variant)
        source_times = [
            b * witness["beat_seconds"] - meta["timeline_start_seconds"] for b in witness["anchor_beats"]
        ]
        target_times = [
            b * witness["beat_seconds"] - meta["timeline_start_seconds"] for b in witness["target_beats"]
        ]
    else:
        path, meta = render(
            cue,
            variant=variant,
            lineage=analysis.get("audio_lineage"),
            selection=analysis.get("audio_selection"),
        )
        source_times = [u["time"] - meta["source_start"] for u in view["units"]]
        target_times = []
    key = identity("rhythm-audition-v1", str(path), mode, source_times, target_times)
    target = DATA / "previews" / f"{key}.wav"
    with LOCK:
        if not target.exists():
            audio, sr = sf.read(path, dtype="float32", always_2d=True)
            if mode == "rhythm":
                audio = np.zeros_like(audio)
            audio *= 0.8
            audio += click_track(source_times, len(audio), sr, 950)[:, None]
            if target_times:
                audio += click_track(target_times, len(audio), sr, 1600)[:, None]
            peak = float(abs(audio).max())
            if peak > 0.98:
                audio *= 0.98 / peak
            temp = target.with_suffix(f".{os.getpid()}.tmp.wav")
            sf.write(temp, audio, sr, subtype="PCM_24")
            os.replace(temp, target)
    return {
        "id": key,
        "url": f"/api/previews/{key}.wav",
        "mode": mode,
        "duration": sf.info(target).duration,
        "source_click_seconds": source_times,
        "target_click_seconds": target_times,
        "manifest": meta,
    }


def export_witness(cue, analysis, witness, variant="vocals"):
    wav, meta = render_witness(cue, analysis, witness, variant)
    key = identity("timeline-export-v1", meta, analysis)
    folder = ROOT / "outputs/clips" / key
    folder.mkdir(parents=True, exist_ok=True)
    title = re.sub(r'[\\/:*?"<>|\x00-\x1f]', "_", cue["spoken"] or cue["title"]).strip(" .")[:55] or "sample"
    output = folder / f"{title}__{variant}_aligned__{key[:8]}.wav"
    shutil.copy2(wav, output)
    meta.update(
        {
            "analysis": analysis,
            "audio_file": output.name,
            "subtitle": cue["original"],
            "spoken_text": cue["spoken"],
        }
    )
    if analysis.get("audio_selection"):
        from .rhythm_units import SILENCE, normalize_phone

        reading = (analysis.get("mora") or {}).get("reading", "")
        meta["parent_spoken_text"] = cue["spoken"]
        meta["spoken_text"] = reading or " ".join(
            p["label"] for p in analysis.get("phones", []) if normalize_phone(p["label"]) not in SILENCE
        )
        meta["transcript_kind"] = "scope_reading_unverified" if reading else "scope_phone_labels_unverified"
        meta["source_scope"] = analysis.get("scope")
    click_audio = None
    if witness.get("strict_plan"):
        clicks = preview_strict(cue, analysis, witness["strict_plan"], "strict_rhythm", variant)
        click_audio = folder / "diagnostic-clicks.wav"
        shutil.copy2(DATA / "previews" / (clicks["id"] + ".wav"), click_audio)
        meta["click_audio_file"] = click_audio.name
    write_json(folder / "manifest.json", meta)
    output.with_suffix(".lab").write_text(meta["spoken_text"] + "\n", encoding="utf-8")
    tg = textgrid.Textgrid()
    duration = meta["actual_duration"]

    def position(t):
        return min(duration, max(0, map_time(t, meta["time_map"]) - meta["timeline_start_seconds"]))

    entries = [(position(p["start"]), position(p["end"]), p["label"]) for p in analysis.get("phones", [])]
    entries = [p for p in entries if p[1] > p[0]]
    if entries:
        tg.addTier(textgrid.IntervalTier("phones_model_unverified", entries, minT=0, maxT=duration))
    emissions = [
        (position(p["start"]), position(p["end"]), p["label"]) for p in analysis.get("emission_phones", [])
    ]
    emissions = [p for p in emissions if p[1] > p[0]]
    if emissions:
        tg.addTier(textgrid.IntervalTier("ctc_emission_support", emissions, minT=0, maxT=duration))
    tg.addTier(
        textgrid.PointTier(
            "rhythm_groups",
            [
                (position(u["time"]), u.get("label", u.get("phone", "onset")))
                for u in (
                    witness.get("anchors")
                    or [
                        {"time": p["source_seconds"], "label": p["label"]}
                        for p in witness["strict_plan"]["unit_targets"]
                    ]
                )
            ],
            minT=0,
            maxT=duration,
        )
    )
    tg.save(str(output.with_suffix(".TextGrid")), format="long_textgrid", includeBlankSpaces=True)
    return {
        "path": str(folder),
        "audio": str(output),
        "click_audio": str(click_audio) if click_audio else None,
        "manifest": meta,
    }


def preview_strict(cue, analysis, plan, mode, variant="vocals"):
    from .strict_audio import render_strict

    path, meta = render_strict(cue, analysis, plan, variant)
    source_times = [
        p["target_beat"] * plan["beat_seconds"] - meta["timeline_start_seconds"] for p in plan["unit_targets"]
    ]
    targets = [
        p["target_beat"] * plan["beat_seconds"] - meta["timeline_start_seconds"]
        for p in plan["unit_targets"]
        if p["role"] == "matched"
    ]
    if mode == "strict":
        return {
            "id": path.stem,
            "url": f"/api/previews/{path.stem}.wav",
            "duration": meta["actual_duration"],
            "source_click_seconds": source_times,
            "target_click_seconds": targets,
            "manifest": meta,
        }
    if mode == "strict_overlay":
        first_beat = int(np.ceil(meta["timeline_start_seconds"] / plan["beat_seconds"]))
        last_beat = int(np.ceil(meta["timeline_end_seconds"] / plan["beat_seconds"]))
        targets = [
            b * plan["beat_seconds"] - meta["timeline_start_seconds"] for b in range(first_beat, last_beat)
        ]
    key = identity("strict-clicks-v2", str(path), mode)
    output = DATA / "previews" / (key + ".wav")
    with LOCK:
        if not output.exists():
            y, sr = sf.read(path, dtype="float32", always_2d=True)
            if mode == "strict_rhythm":
                y[:] = 0
            y = (
                y * 0.8
                + click_track(source_times, len(y), sr, 950)[:, None]
                + click_track(targets, len(y), sr, 1600)[:, None]
            )
            peak = float(abs(y).max())
            if peak > 0.98:
                y *= 0.98 / peak
            temp = output.with_suffix(".tmp.wav")
            sf.write(temp, y, sr, subtype="PCM_24")
            os.replace(temp, output)
    return {
        "id": key,
        "url": f"/api/previews/{key}.wav",
        "duration": meta["actual_duration"],
        "source_click_seconds": source_times,
        "target_click_seconds": targets,
        "manifest": meta,
    }
