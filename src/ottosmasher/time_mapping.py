"""Pure sample-frame timing. No audio decoding, storage or DSP dependencies."""

import math
from itertools import pairwise

import numpy as np

VERSION = "shared-frame-map-v1"


def core_schedule(source_frames, target_frames, length, sr):
    if any(b <= a for a, b in pairwise(source_frames)) or any(b <= a for a, b in pairwise(target_frames)):
        raise ValueError("Colliding source or target frames")
    cores = []
    for i, (s, d) in enumerate(zip(source_frames, target_frames, strict=True)):
        before = min(s if i == 0 else s - source_frames[i - 1], d if i == 0 else d - target_frames[i - 1])
        after = min(
            length - 1 - s if i == len(source_frames) - 1 else source_frames[i + 1] - s,
            length if i == len(source_frames) - 1 else target_frames[i + 1] - d,
        )
        radius = min(round(0.008 * sr), max(0, before // 4), max(0, after // 4))
        if not 0 <= s < length or d < 0:
            raise ValueError("Anchor outside source/target audio")
        cores.append(
            {
                "source_start": s - radius,
                "source_end": s + radius + 1,
                "target_start": d - radius,
                "target_end": d + radius + 1,
                "source_anchor": s,
                "target_anchor": d,
            }
        )
    return cores


def schedule(plan, source_start, length, sr=48000):
    points = sorted(
        list(plan["unit_targets"])
        + list(plan.get("control_targets", []))
        + ([plan["end_target"]] if plan.get("end_target") else []),
        key=lambda p: p["source_seconds"],
    )
    factor = plan.get("duration_multiplier") or plan["witness"]["duration_multiplier"]
    beat = plan["beat_seconds"]
    source = [round((p["source_seconds"] - source_start) * sr) for p in points]
    first = points[0]["target_beat"] * beat - source[0] / sr * factor
    keep_canvas = plan.get("retain_query_canvas", False)
    origin = math.floor((min(0.0, first) if keep_canvas else first) * sr) / sr
    dest = [round((p["target_beat"] * beat - origin) * sr) for p in points]
    cores = core_schedule(source, dest, length, sr)
    begin = max(0, cores[0]["target_start"] - round(cores[0]["source_start"] * factor))
    end = cores[-1]["target_end"] + round((length - cores[-1]["source_end"]) * factor)
    total = (
        max(end, round(((plan.get("witness") or {}).get("query_span_beats", 0) * beat - origin) * sr))
        if keep_canvas
        else end
    )
    if total / sr > 600:
        raise ValueError("Strict preview exceeds ten minutes")
    segments, previous = [], (0, begin)
    for c in cores:
        segments.append((*previous, c["source_start"], c["target_start"], "bridge"))
        segments.append((c["source_start"], c["target_start"], c["source_end"], c["target_end"], "core"))
        previous = (c["source_end"], c["target_end"])
    segments.append((*previous, length, end, "bridge"))
    rendered, knots = [], []
    for a, x, b, z, kind in segments:
        if b == a:
            if z > x:
                raise ValueError("Cannot stretch an empty source bridge")
            continue
        if z <= x:
            raise ValueError("No positive output duration for speech bridge")
        ps = (
            [
                (
                    max(a, round((p["start"] - source_start) * sr)),
                    min(b, round((p["end"] - source_start) * sr)),
                )
                for p in plan.get("pauses", [])
            ]
            if kind == "bridge"
            else []
        )
        ps = [(l, r) for l, r in ps if r > l]
        cuts = sorted({a, b, *[t for p in ps for t in p]})
        pieces = [(l, r, any(l >= p and r <= q for p, q in ps)) for l, r in pairwise(cuts)]
        silence = sum(r - l for l, r, quiet in pieces if quiet)
        speech = b - a - silence
        reserve = max(sum(q for _, _, q in pieces), round(min(silence, (z - x) * 0.02)))
        voice_ratio = min(factor, max(1, z - x - reserve) / max(1, speech)) if silence else (z - x) / (b - a)
        pause_ratio = max(0, ((z - x) - speech * voice_ratio) / silence) if silence else 0
        cursor, cumulative = x, 0.0
        for j, (l, r, quiet) in enumerate(pieces):
            cumulative += (r - l) * (pause_ratio if quiet else voice_ratio)
            stop = (
                z
                if j == len(pieces) - 1
                else min(z - (len(pieces) - j - 1), max(cursor + 1, x + round(cumulative)))
            )
            if stop <= cursor:
                raise ValueError("Speech bridge rounded to zero frames")
            knots.extend(
                [(source_start + l / sr, origin + cursor / sr), (source_start + r / sr, origin + stop / sr)]
            )
            rendered.append(
                {
                    "source_frames": [l, r],
                    "target_frames": [cursor, stop],
                    "kind": "elastic_gap" if quiet else kind,
                }
            )
            cursor = stop
    lo, hi = plan.get("speech_bounds", [points[0]["source_seconds"], points[-1]["source_seconds"]])
    speech_source = speech_target = 0.0
    for segment in rendered:
        if segment["kind"] == "elastic_gap":
            continue
        a, b = segment["source_frames"]
        x, z = segment["target_frames"]
        overlap = max(0, min(b, (hi - source_start) * sr) - max(a, (lo - source_start) * sr))
        speech_source += overlap / sr
        speech_target += overlap * (z - x) / (b - a) / sr
    return {
        "time_map": {
            "version": VERSION,
            "knots": [list(k) for k in sorted(set(knots))],
            "factor": factor,
            "origin_seconds": source_start,
            "offset_seconds": first,
            "pauses": [],
            "local_phone_warp": True,
        },
        "cores": cores,
        "segments": rendered,
        "sample_rate": sr,
        "total_frames": total,
        "actual_duration": total / sr,
        "timeline_start_seconds": origin,
        "timeline_end_seconds": origin + total / sr,
        "source_speech_seconds": speech_source,
        "target_speech_seconds": speech_target,
        "speech_playback_speed": speech_source / speech_target if speech_target else None,
    }


def map_seconds(value, mapping):
    knots = mapping["knots"]
    return float(np.interp(value, [k[0] for k in knots], [k[1] for k in knots]))
