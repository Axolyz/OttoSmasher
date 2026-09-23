"""Standalone subtitle experiment; never imports results into the analysis database."""

import argparse
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
import numpy as np
import pysubs2
import soundfile as sf
from scipy.signal import resample_poly

from ottosmasher.vocals import PersistentVocals, prepare_vocals
from ottosmasher.workspace import ROOT, connect, identity, write_json

OUT = ROOT / "outputs/subtitle-preprocessing"


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def prepare_text(src, folder, info):
    profile_path = ROOT / "configs/subtitle-cleaning/kemono-friends.json"
    profile = json.loads(profile_path.read_text())
    if profile["title_contains"] not in src["title"]:
        raise ValueError("Select a cleaning profile for this subtitle format first")
    original = pysubs2.load(src["subtitle_path"], encoding="utf-8-sig")
    spoken = pysubs2.SSAFile()
    audit, mapping = [], []
    for i, event in enumerate(original):
        text = event.plaintext
        removed = []
        for pattern in profile["remove_patterns"]:
            removed.extend(re.findall(pattern, text))
            text = re.sub(pattern, "", text)
        text = text.strip()
        audit.append(
            {
                "original_index": i,
                "original_text": event.plaintext,
                "alignment_text": text,
                "removed": removed,
                "unresolved_brackets": any(c in text for c in "（）()"),
                "status": "align" if text else "unspoken_preserve_original_time",
            }
        )
        if text:
            spoken.append(pysubs2.SSAEvent(start=event.start, end=event.end, text=text.replace("\n", "\\N")))
            mapping.append(i)
    subtitle = folder / "spoken.srt"
    spoken.save(subtitle)
    write_json(
        folder / "cleaning.json",
        {"profile": str(profile_path), "profile_sha256": digest(profile_path), "rows": audit},
    )
    info.update(
        spoken_subtitle=str(subtitle), original_indices=mapping, cleaning_profile_sha256=digest(profile_path)
    )
    write_json(folder / "input.json", info)


def prepare(sources):
    manifests = [json.loads(p.read_text()) for p in (ROOT / "data/vocals").glob("*/manifest.json")]
    session = None
    try:
        for src in sources:
            folder = OUT / src["id"]
            folder.mkdir(parents=True, exist_ok=True)
            marker = folder / "input.json"
            if marker.exists():
                old = json.loads(marker.read_text())
                if old["source_fingerprint"] == src["fingerprint"] and old["subtitle_sha256"] == digest(
                    src["subtitle_path"]
                ):
                    prepare_text(src, folder, old)
                    continue
                raise ValueError("Input changed; use a new output directory")
            entries = [
                m
                for m in manifests
                if m.get("source_fingerprint") == src["fingerprint"]
                and Path(m.get("separated_context", "missing")).is_file()
            ]
            stop, gaps = 0.0, []
            for m in sorted(entries, key=lambda e: e["context_start"]):
                if m["context_start"] > stop:
                    gaps.append((stop, m["context_start"]))
                stop = max(stop, m["context_end"])
            if stop < src["duration"]:
                gaps.append((stop, src["duration"]))
            if gaps and session is None:
                session = PersistentVocals()
            for a, b in gaps:
                cue = {
                    **src,
                    "id": identity("subtitle-gap", src["id"], a, b),
                    "start": a,
                    "end": b,
                    "source_duration": src["duration"],
                }
                entries.extend(prepare_vocals([cue], session=session).values())
            # Original source clock throughout; short crossfades only where cached stems overlap.
            sr = 16000
            n = round(src["duration"] * sr)
            samples, weights = np.zeros(n, np.float32), np.zeros(n, np.float32)
            lineage = []
            for m in entries:
                path = m["separated_context"]
                y, rate = sf.read(path, dtype="float32", always_2d=True)
                from math import gcd

                g = gcd(rate, sr)
                y = resample_poly(y.mean(axis=1), sr // g, rate // g)
                start = round(m["context_start"] * sr)
                y = y[: max(0, n - start)]
                w = np.ones(len(y), np.float32)
                fade = min(round(0.05 * sr), len(y) // 2)
                if fade:
                    w[:fade] = np.linspace(0.001, 1, fade)
                    w[-fade:] = np.linspace(1, 0.001, fade)
                samples[start : start + len(y)] += y * w
                weights[start : start + len(y)] += w
                lineage.append(
                    {
                        "path": path,
                        "sha256": digest(path),
                        "start": m["context_start"],
                        "end": m["context_end"],
                    }
                )
            # Container duration may exceed decoded audio by a millisecond.
            # Trim only this tiny trailing discrepancy; never fill an interior gap.
            last = np.flatnonzero(weights > 0)[-1] + 1
            trailing_trim = (n - last) / sr
            if 0 < trailing_trim <= 0.01:
                samples, weights = samples[:last], weights[:last]
            if np.any(weights == 0):
                raise ValueError(f"Uncovered input samples: {np.sum(weights == 0)}")
            audio = folder / "vocals.wav"
            sf.write(audio, samples / weights, sr, subtype="PCM_24")
            write_json(
                marker,
                {
                    "source_fingerprint": src["fingerprint"],
                    "source": src["path"],
                    "subtitle": src["subtitle_path"],
                    "subtitle_sha256": digest(src["subtitle_path"]),
                    "audio": str(audio),
                    "audio_sha256": digest(audio),
                    "stems": lineage,
                    "input_variant": "pymss_vocals",
                    "sample_rate": sr,
                    "trailing_container_discrepancy_seconds": trailing_trim,
                },
            )
            prepare_text(src, folder, json.loads(marker.read_text()))
            print("prepared", src["title"], flush=True)
    finally:
        if session:
            session.close()


def run_tool(src, tool):
    folder = OUT / src["id"]
    info = json.loads((folder / "input.json").read_text())
    dest = folder / tool
    dest.mkdir(exist_ok=True)
    if (dest / "result.json").exists():
        (dest / "failure.json").unlink(missing_ok=True)
        return
    audio = info["audio"]
    sub = info["subtitle"] if tool == "subplz" else info["spoken_subtitle"]
    if tool == "sub-align":
        output = dest / "aligned.srt"
        cmd = [
            str(ROOT / ".runtime/envs/sub-align/bin/sub-align"),
            audio,
            sub,
            "--language",
            "ja",
            "--device",
            "cpu",
            "--no-auto-offset",
            "--margin",
            "1.5",
            "-o",
            str(output),
        ]
    else:
        output = dest / "vocals.srt"
        cmd = [
            str(ROOT / ".runtime/envs/subplz/bin/subplz"),
            "sync",
            "--audio",
            audio,
            "--text",
            sub,
            "--output-dir",
            str(dest),
            "--language",
            "ja",
            "--model",
            "turbo",
            "--device",
            "cpu",
            "--threads",
            "4",
            "--quantize",
            "--respect-grouping",
            "--cache-dir",
            str(dest / "cache"),
        ]
    env = {
        **os.environ,
        "PATH": str(ROOT / ".runtime/envs/core/bin") + os.pathsep + os.environ["PATH"],
        "HF_HOME": str(ROOT / "models/subtitle-preprocessing"),
        "OMP_NUM_THREADS": "4",
        "NLTK_DATA": str(ROOT / "models/subtitle-preprocessing/nltk_data"),
        "HF_HUB_DISABLE_XET": "1",
        "HF_HUB_DOWNLOAD_TIMEOUT": "120",
        "HF_HUB_ETAG_TIMEOUT": "30",
        "TOKENIZERS_PARALLELISM": "false",
    }
    write_json(
        dest / "command.json",
        {
            "argv": cmd,
            "input_audio_sha256": info["audio_sha256"],
            "input_subtitle_sha256": digest(sub),
            "upstream": json.loads((ROOT / "dependencies/subtitle-preprocessing.sources.json").read_text())[
                tool
            ],
        },
    )
    started = time.time()
    with (dest / "run.log").open("w") as log:
        subprocess.run(cmd, env=env, stdout=log, stderr=subprocess.STDOUT, check=True, cwd=ROOT)
    if not output.exists():
        raise ValueError(f"No expected subtitle output: {output}")
    aligned = pysubs2.load(output)
    original = pysubs2.load(info["subtitle"], encoding="utf-8-sig")
    expected = pysubs2.load(sub)
    # Only restore metadata when exact line ownership is retained; never guess a remapping.
    same = len(aligned) == len(expected) and all(
        a.plaintext.strip() == b.plaintext.strip() for a, b in zip(aligned, expected)
    )
    invalid = sum(e.end <= e.start or e.start < 0 for e in aligned)
    if invalid:
        raise ValueError(f"{invalid} invalid output ranges")
    if same:
        indices = range(len(original)) if tool == "subplz" else info["original_indices"]
        for idx, event in zip(indices, aligned):
            original[idx].start, original[idx].end = event.start, event.end
        original.save(dest / "preserved-text.srt")
    write_json(
        dest / "result.json",
        {
            "tool": tool,
            "output": str(output),
            "input_cues": len(expected),
            "output_cues": len(aligned),
            "exact_line_mapping": same,
            "preserved_text_output": str(dest / "preserved-text.srt") if same else None,
            "unspoken_events": "original times retained only in preserved-text output",
            "verified": False,
            "elapsed_seconds": time.time() - started,
        },
    )
    export = OUT / tool
    export.mkdir(exist_ok=True)
    shutil.copy2(dest / "preserved-text.srt" if same else output, export / (src["title"] + ".srt"))
    (dest / "failure.json").unlink(missing_ok=True)
    print("finished", tool, src["title"], flush=True)


def main():
    p = argparse.ArgumentParser()
    p.add_argument("operation", choices=["prepare", "sub-align", "subplz", "all"])
    p.add_argument("--source-id")
    args = p.parse_args()
    sources = [
        dict(r)
        for r in connect().execute("SELECT * FROM sources ORDER BY title")
        if not args.source_id or r["id"] == args.source_id
    ]
    if not sources:
        p.error("No matching sources")
    if args.operation in ("prepare", "all"):
        prepare(sources)
    if args.operation != "prepare":
        failures = []
        task = OUT / ("task-" + args.operation + ".json")
        completed = []
        write_json(task, {"status": "running", "pid": os.getpid(), "completed": completed})
        for src in sources:
            for tool in ["sub-align", "subplz"] if args.operation == "all" else [args.operation]:
                try:
                    run_tool(src, tool)
                    completed.append({"source_id": src["id"], "tool": tool})
                    write_json(
                        task,
                        {
                            "status": "running",
                            "pid": os.getpid(),
                            "completed": completed,
                            "failures": failures,
                        },
                    )
                except Exception as exc:  # noqa: BLE001 - record per-file failures and continue
                    failures.append({"source_id": src["id"], "tool": tool, "error": str(exc)})
                    write_json(OUT / src["id"] / tool / "failure.json", failures[-1])
                    print("failed", tool, src["title"], str(exc), flush=True)
        write_json(
            task,
            {
                "status": "complete_with_failures" if failures else "complete",
                "completed": completed,
                "failures": failures,
            },
        )
        if failures:
            raise SystemExit(f"{len(failures)} failed runs; raw logs retained")


if __name__ == "__main__":
    main()
