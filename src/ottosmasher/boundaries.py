"""Acoustic crop evidence, independent of sparse CTC emission support."""

import numpy as np
import soundfile as sf

VERSION = "acoustic-coverage-v3"


def energy_frames(path, origin, hop_seconds=0.01):
    y, sr = sf.read(path, dtype="float32", always_2d=True)
    mono = y.mean(axis=1)
    hop = max(1, round(sr * hop_seconds))
    rms = np.array([np.sqrt(np.mean(mono[i : i + hop] ** 2)) for i in range(0, len(mono), hop)])
    return origin + np.arange(len(rms)) * hop / sr, rms, hop / sr


def quiet_runs(times, rms, hop, threshold, minimum=0.06):
    quiet = np.r_[False, rms <= threshold, False]
    edges = np.flatnonzero(np.diff(quiet.astype(int)))
    return [
        (float(times[a]), float(times[min(b - 1, len(times) - 1)] + hop))
        for a, b in zip(edges[::2], edges[1::2])
        if (b - a) * hop >= minimum - 1e-8
    ]


def acoustic_crop(item, phones, raw):
    origin, limit = item["window_start"], item["window_end"]
    times, rms, hop = energy_frames(item["audio_lineage"]["audio_path"], origin)
    threshold = max(float(np.quantile(rms, 0.85)) * 0.12, 1e-5)
    quiet = quiet_runs(times, rms, hop, threshold)
    first, last = phones[0]["start"], phones[-1]["end"]
    before, after = origin, limit
    for p in raw["phones"]:
        if p["label"] in {"SP", "AP", "pau", "sil", "", "[BOS]", "[EOS]"}:
            continue
        a, b = p["start"] + origin, p["end"] + origin
        if b <= first + 1e-6:
            before = max(before, b)
        if a >= last - 1e-6:
            after = min(after, a)
    target = next(c for c in item["context"] if c["id"] == item["id"])
    lo = max(before, min(first - 0.35, target["start"] - 0.5))
    hi = min(after, max(last + 0.8, target["end"] + 0.5))
    # Only a measured quiet seam can shorten the conservative search window.
    leading = [min(b, first) for a, b in quiet if a < first and b > lo]
    trailing = [max(a, last) for a, b in quiet if b > last and a < hi]
    start = max(lo, max(leading) - 0.03) if leading else lo
    speech_end = min(trailing) if trailing else hi
    end = min(hi, speech_end + 0.05)
    return (
        start,
        end,
        {
            "version": VERSION,
            "speech_end": speech_end,
            "uncertain_start": not bool(leading),
            "uncertain_end": not bool(trailing),
            "ownership_limits": [before, after],
            "threshold": threshold,
            "quiet_runs": quiet,
            "method": "waveform_quiet_seams_with_neighbor_ownership",
        },
    )


def estimate_ctc_coverage(phones, evidence):
    """Keep starts fixed; blank duration is unknown, never automatically silence."""
    output = []
    for i, p in enumerate(phones):
        next_start = phones[i + 1]["start"] if i + 1 < len(phones) else evidence["speech_end"]
        stop = max(p["end"], next_start)
        for a, b in evidence["quiet_runs"]:
            if b > p["end"] and a < stop:
                stop = max(p["end"], a)
                break
        output.append(
            {
                **p,
                "emission_start": p["start"],
                "emission_end": p["end"],
                "end": stop,
                "coverage_kind": "acoustic_estimate_not_model_boundary",
            }
        )
    return output
