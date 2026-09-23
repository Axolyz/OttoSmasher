from __future__ import annotations

import hashlib
import os
import threading

import soundfile as sf

from .workspace import DATA, ROOT, command, executable, identity, write_json

LOCK = threading.Lock()


def window(cue, padding=0.65):
    return max(0.0, cue["start"] - padding), min(cue["source_duration"], cue["end"] + padding)


def source_audio(source):
    """A reusable mono analysis copy; never substitutes for original-quality export."""
    key = identity(source["fingerprint"], source["audio_stream"], "mono16k-v1")
    target = DATA / "audio" / f"{key}.wav"
    target.parent.mkdir(parents=True, exist_ok=True)
    with LOCK:
        if not target.exists():
            temp = target.with_suffix(f".{os.getpid()}.tmp.wav")
            command(
                [
                    executable("ffmpeg"),
                    "-v",
                    "error",
                    "-nostdin",
                    "-y",
                    "-i",
                    source["path"],
                    "-map",
                    f"0:{source['audio_stream']}",
                    "-vn",
                    "-ac",
                    "1",
                    "-ar",
                    "16000",
                    "-c:a",
                    "pcm_s16le",
                    temp,
                ]
            )
            os.replace(temp, target)
    return target


def read_window(cue, padding=0.65):
    start, end = window(cue, padding)
    path = source_audio(cue)
    with sf.SoundFile(path) as f:
        f.seek(round(start * f.samplerate))
        y = f.read(round((end - start) * f.samplerate), dtype="float32")
        return y, f.samplerate, start, end


def render(
    cue, factor=1.0, padding=0.65, metronome_bpm=None, offset=0.0, variant="raw", lineage=None, selection=None
):
    """Uniform time stretch, no local warping. Offset places clip on an external timeline."""
    if not 0.5 <= factor <= 2.0:
        raise ValueError("Duration multiplier must be between 0.5 and 2")
    if not 0 <= padding <= 2:
        raise ValueError("Padding must be between 0 and 2 seconds")
    start, end = window(cue, padding)
    if lineage and lineage.get("target_cue_id"):
        if lineage["target_cue_id"] != cue["id"] or lineage["source_fingerprint"] != cue["fingerprint"]:
            raise ValueError("Target crop belongs to another source or cue")
        start, end = lineage["window_start"], lineage["window_end"]
        if not 0 <= start < end <= cue["source_duration"]:
            raise ValueError("Invalid target audio crop")
    parent_start, parent_end = start, end
    if selection:
        from .rhythm_scopes import SELECTION_VERSION

        signed = {k: v for k, v in selection.items() if k != "selection_id"}
        if (
            selection.get("version") != SELECTION_VERSION
            or selection.get("selection_id") != identity(SELECTION_VERSION, signed)
            or selection.get("parent_cue_id") != cue["id"]
            or selection.get("source_fingerprint") != cue["fingerprint"]
        ):
            raise ValueError("Audio selection belongs to another source/cue or has changed")
        if not lineage or (
            selection.get("audio_sha256") != lineage.get("audio_sha256")
            or abs(selection.get("parent_window_start", -1) - parent_start) > 1e-7
            or abs(selection.get("parent_window_end", -1) - parent_end) > 1e-7
        ):
            raise ValueError("Audio selection does not match the parent vocals lineage")
        start, end = selection["source_start"], selection["source_end"]
        if not parent_start <= start < end <= parent_end:
            raise ValueError("Audio selection is outside the parent crop")
    input_path, seek, input_map = cue["path"], start, f"0:{cue['audio_stream']}"
    if variant == "vocals" or selection:
        if not lineage:
            raise ValueError("No separated vocals available for this cue; select raw explicitly")
        from pathlib import Path

        if (
            lineage["source_fingerprint"] != cue["fingerprint"]
            or abs(parent_start - lineage["window_start"]) > 0.001
            or abs(parent_end - lineage["window_end"]) > 0.001
        ):
            raise ValueError("Vocals lineage does not match this source/window")
        if not Path(lineage["audio_path"]).is_file():
            raise ValueError("Separated vocals file is missing; rerun preprocessing")
        if hashlib.sha256(Path(lineage["audio_path"]).read_bytes()).hexdigest() != lineage["audio_sha256"]:
            raise ValueError("Vocals asset checksum mismatch")
        if variant == "vocals":
            input_path, seek, input_map = lineage["audio_path"], start - parent_start, "0:a:0"
    if variant not in {"raw", "vocals"}:
        raise ValueError("Unknown audio variant")
    key = identity(
        cue["id"],
        cue["fingerprint"],
        cue["audio_stream"],
        start,
        end,
        factor,
        variant,
        lineage["audio_sha256"] if variant == "vocals" else None,
        selection,
        "atempo-v4-lossless-unity",
    )
    target = DATA / "previews" / f"{key}.wav"
    target.parent.mkdir(parents=True, exist_ok=True)
    with LOCK:
        if not target.exists():
            temp = target.with_suffix(f".{os.getpid()}.tmp.wav")
            command(
                [
                    executable("ffmpeg"),
                    "-v",
                    "error",
                    "-nostdin",
                    "-y",
                    "-ss",
                    str(seek),
                    "-t",
                    str(end - start),
                    "-i",
                    input_path,
                    "-map",
                    input_map,
                    "-vn",
                    "-af",
                    "anull" if factor == 1 else f"atempo={1 / factor:.10f}",
                    "-ar",
                    "48000",
                    "-c:a",
                    "pcm_s24le",
                    temp,
                ]
            )
            os.replace(temp, target)
    info = sf.info(target)
    return target, {
        "source_id": cue["source_id"],
        "cue_id": cue["id"],
        "source_path": cue["path"],
        "fingerprint": cue["fingerprint"],
        "audio_stream": cue["audio_stream"],
        "source_start": start,
        "source_end": end,
        "duration_multiplier": factor,
        "timeline_offset_seconds": offset,
        "backend": "ffmpeg-atempo",
        "sample_rate": info.samplerate,
        "actual_duration": info.duration,
        "expected_duration": (end - start) * factor,
        "boundary_origin": "virtual_speech_scope"
        if selection
        else "model_crop"
        if lineage and lineage.get("target_cue_id")
        else "subtitle_with_padding",
        "local_warp": False,
        "audio_variant": variant,
        "input_audio_path": input_path,
        "audio_lineage": lineage if variant == "vocals" else None,
        "audio_selection": selection,
    }


def export_bundle(cue, analysis=None, factor=1.0, context=None, offset=0.0, variant="raw", lineage=None):
    import shutil

    from praatio import textgrid

    if analysis and (variant == "vocals" or analysis.get("audio_selection")):
        if analysis.get("input_variant") != "vocals" or not analysis.get("audio_lineage"):
            raise ValueError("Export analysis must reference separated vocals")
        lineage = analysis["audio_lineage"]
    wav, manifest = render(
        cue,
        factor,
        offset=offset,
        variant=variant,
        lineage=lineage,
        selection=(analysis or {}).get("audio_selection"),
    )
    manifest["selection_context"] = context
    key = identity(manifest, analysis)
    folder = ROOT / "outputs" / "clips" / key
    folder.mkdir(parents=True, exist_ok=True)
    import re

    title = re.sub(r'[\\/:*?"<>|\x00-\x1f]', "_", cue["spoken"] or cue["title"]).strip(" .")[:55] or "sample"
    output = folder / f"{title}__{variant}__{key[:8]}.wav"
    shutil.copy2(wav, output)
    manifest["subtitle"] = cue["original"]
    manifest["spoken_text"] = cue["spoken"]
    if (analysis or {}).get("audio_selection"):
        from .rhythm_units import SILENCE, normalize_phone

        scoped_reading = (analysis.get("mora") or {}).get("reading", "")
        manifest["parent_spoken_text"] = cue["spoken"]
        manifest["spoken_text"] = scoped_reading or " ".join(
            p["label"] for p in analysis.get("phones", []) if normalize_phone(p["label"]) not in SILENCE
        )
        manifest["transcript_kind"] = (
            "scope_reading_unverified" if scoped_reading else "scope_phone_labels_unverified"
        )
    manifest["analysis"] = analysis
    manifest["audio_file"] = output.name
    write_json(folder / "manifest.json", manifest)
    output.with_suffix(".lab").write_text(manifest["spoken_text"] + "\n", encoding="utf-8")
    tg = textgrid.Textgrid()
    duration = manifest["actual_duration"]
    start = manifest["source_start"]
    scoped = bool((analysis or {}).get("audio_selection"))
    a, b = (
        (0, duration)
        if scoped
        else (max(0, (cue["start"] - start) * factor), min(duration, (cue["end"] - start) * factor))
    )
    tg.addTier(
        textgrid.IntervalTier(
            "parent_subtitle_context_unverified" if scoped else "subtitle_unverified",
            [(a, min(b, duration), cue["spoken"] or cue["original"])],
            minT=0,
            maxT=duration,
        )
    )
    if analysis and analysis.get("phones"):
        entries = [
            (max(0, (p["start"] - start) * factor), min(duration, (p["end"] - start) * factor), p["label"])
            for p in analysis["phones"]
            if p["end"] > start and p["start"] < start + duration / factor
        ]
        entries = [x for x in entries if x[1] > x[0]]
        tg.addTier(textgrid.IntervalTier("phones_model_unverified", entries, minT=0, maxT=duration))
    tg.save(str(output.with_suffix(".TextGrid")), format="long_textgrid", includeBlankSpaces=True)
    return {"path": str(folder), "audio": str(output), "manifest": manifest}
