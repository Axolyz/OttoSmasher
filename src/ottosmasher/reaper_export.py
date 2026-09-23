"""macOS REAPERMedia clipboard export; source media remains unwarped and persistent."""

from __future__ import annotations

import hashlib
import itertools
import json
import os
import re
import shutil
import subprocess
import sys
import uuid
from pathlib import Path

import soundfile as sf

from .media import render
from .time_mapping import schedule
from .workspace import ROOT, write_json

VERSION = "reaper-media-macos-v1"


def quoted(value):
    # REAPER supports double, single and backtick quoted tokens; choose a delimiter
    # absent from the path. Do not alter a real filename by escaping it incorrectly.
    value = str(value)
    if any(c in value for c in "\x00\r\n"):
        raise ValueError("REAPER paths cannot contain line breaks or NUL")
    for delimiter in ('"', "'", "`"):
        if delimiter not in value:
            return delimiter + value + delimiter
    raise ValueError("Path contains all REAPER quoting delimiters; choose another export directory")


def media_payload(audio_path, duration, markers, snap_offset, beat_seconds, title):
    if not Path(audio_path).is_file():
        raise ValueError("Source audio must exist before clipboard publication")
    if not markers or duration <= 0 or not 0 <= snap_offset <= duration:
        raise ValueError("Invalid item mapping")
    if any(b[0] <= a[0] or b[1] <= a[1] for a, b in itertools.pairwise(markers)):
        raise ValueError("Stretch markers must increase in both destination and source time")
    f = lambda x: format(float(x), ".12f")
    guid = lambda: "{" + str(uuid.uuid4()).upper() + "}"
    lines = [
        "<ITEM",
        "POSITION 0 0",
        f"SNAPOFFS {f(snap_offset)} {f(snap_offset / beat_seconds)}",
        f"LENGTH {f(duration)} {f(duration / beat_seconds)}",
        "LOOP 0",
        "ALLTAKES 0",
        "FADEIN 1 0 0 1 0 0 0",
        "FADEOUT 1 0 0 1 0 0 0",
        "MUTE 0 0",
        "SEL 1",
        "IGUID " + guid(),
        "NAME " + quoted(title),
        "VOLPAN 1 0 1 -1",
        "SOFFS 0",
        "PLAYRATE 1 1 0 -1 0 0.0025",
        "CHANMODE 0",
        "GUID " + guid(),
        "SM " + " + ".join(f"{f(dest)} {f(src)} 0 0 {f(dest / beat_seconds)}" for dest, src in markers),
        "<SOURCE WAVE",
        "FILE " + quoted(audio_path),
        ">",
        ">",
    ]
    # Captured from REAPER 7.79/macOS: UTF-8 records, NUL separators, double tail NUL.
    return ("\0".join(lines) + "\0\0").encode("utf-8")


def publish_clipboard(payload):
    if sys.platform != "darwin":
        raise ValueError("Native clipboard export currently supports macOS only")
    try:
        proc = subprocess.run(
            [sys.executable, "-m", "ottosmasher.reaper_export", "--clipboard"],
            input=payload,
            capture_output=True,
            timeout=30,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise ValueError(f"REAPER clipboard copy failed: {exc}") from exc
    if proc.returncode:
        raise ValueError("REAPER clipboard copy failed: " + proc.stderr.decode(errors="replace")[-1000:])
    return json.loads(proc.stdout)


def export_reaper(cue, analysis, plan, variant="vocals", directory=None, origin="first_onset", copy=True):
    if origin not in {"first_onset", "item_start"}:
        raise ValueError("Unknown paste origin")
    folder = Path(directory).expanduser() if directory else ROOT / "outputs/reaper-media"
    if not folder.is_absolute():
        folder = ROOT / folder
    folder = folder.resolve()
    folder.mkdir(parents=True, exist_ok=True)
    raw, base = render(
        cue, variant=variant, lineage=analysis.get("audio_lineage"), selection=analysis.get("audio_selection")
    )
    # Export needs the shared timing schedule, without running Rubber Band.
    info = sf.info(raw)
    meta = schedule(plan, base["source_start"], info.frames, info.samplerate)
    sha = hashlib.sha256(raw.read_bytes()).hexdigest()
    title = re.sub(r'[\\/:*?"<>|\x00-\x1f]', "_", cue["spoken"]).strip(" .")[:55] or "sample"
    audio = folder / f"{title}__{variant}__{sha[:16]}.wav"
    if not audio.exists():
        temp = audio.with_suffix(f".{os.getpid()}.tmp.wav")
        shutil.copyfile(raw, temp)
        os.replace(temp, audio)
    elif hashlib.sha256(audio.read_bytes()).hexdigest() != sha:
        raise ValueError("Existing persistent media was modified; choose another work directory")
    start = meta["timeline_start_seconds"]
    # Linear segments and protected source cores are identical to the web time map.
    markers = sorted(
        {(round(t - start, 12), round(s - base["source_start"], 12)) for s, t in meta["time_map"]["knots"]}
    )
    sr = meta["sample_rate"]
    markers = sorted(
        set(
            markers
            + [
                (round(c["target_anchor"] / sr, 12), round(c["source_anchor"] / sr, 12))
                for c in meta["cores"]
            ]
        )
    )
    snap = (
        plan["unit_targets"][0]["target_beat"] * plan["beat_seconds"] - start
        if origin == "first_onset"
        else 0.0
    )
    payload = media_payload(audio, meta["actual_duration"], markers, snap, plan["beat_seconds"], title)
    result = {
        "version": VERSION,
        "plan_id": plan["plan_id"],
        "audio": str(audio),
        "audio_sha256": sha,
        "variant": variant,
        "snap_offset": snap,
        "duration": meta["actual_duration"],
        "markers": markers,
        "origin": origin,
        "plan": plan,
        "time_map": meta["time_map"],
        "audio_lineage": analysis.get("audio_lineage"),
        "audio_selection": analysis.get("audio_selection"),
        "source_scope": analysis.get("scope") or plan.get("scope"),
        "source_start": base["source_start"],
        "source_end": base["source_end"],
        "clipboard_type": "REAPERMedia",
        "clipboard_sha256": hashlib.sha256(payload).hexdigest(),
        "copied": False,
    }
    manifest = folder / f"{plan['plan_id']}__{variant}__{origin}.json"
    write_json(manifest, result)
    if copy:
        publish_clipboard(payload)
        result["copied"] = True
        write_json(manifest, result)
    result["manifest"] = str(manifest)
    return result


def main():
    # NSPasteboard access happens on this subprocess's main thread, never a worker.
    from AppKit import NSPasteboard
    from Foundation import NSData

    payload = sys.stdin.buffer.read()
    if not payload.startswith(b"<ITEM\0") or len(payload) > 2_000_000:
        raise ValueError("Invalid REAPERMedia payload")
    board = NSPasteboard.generalPasteboard()
    data = NSData.dataWithBytes_length_(payload, len(payload))
    board.declareTypes_owner_(["REAPERMedia"], None)
    if not board.setData_forType_(data, "REAPERMedia"):
        raise RuntimeError("NSPasteboard rejected REAPERMedia")
    if bytes(board.dataForType_("REAPERMedia")) != payload:
        raise RuntimeError("Clipboard verification failed")
    print(json.dumps({"copied": True, "bytes": len(payload)}))


if __name__ == "__main__":
    main()
