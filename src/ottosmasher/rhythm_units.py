"""Audible rhythm groups derived from, never substituted for, aligned phones."""

from __future__ import annotations

import json
from functools import lru_cache

import numpy as np

VERSION = "rhythm-groups-v2"
VOWELS = {"a", "i", "u", "e", "o"}
SILENCE = {"SP", "sil", "pau", "", "sp"}


def normalize_phone(label):
    base = label.replace("ː", "").replace("̥", "")
    return {"ɯ": "u", "ɨ": "u", "ɴ": "N", "ŋ": "N", "ɰ̃": "N", "I": "i", "U": "u"}.get(base, base)


def group_phones(phones, anchors=(), split_before=()):
    """Contiguous vowel chains and a following nasal form one heuristic onset.

    N attaches backwards, not forwards. Any consonant, silence or explicit split
    breaks a group; a long vowel is not a silence and retains all source members.
    """
    result = []
    strengths = {round(a["time"], 5): a.get("strength") for a in anchors}
    previous = None
    for i, p in enumerate(phones):
        label = normalize_phone(p["label"])
        if label not in VOWELS | {"N"}:
            previous = None
            continue
        merge = (
            previous is not None
            and previous in VOWELS
            and result
            and i not in split_before
            and -0.001 <= p["start"] - result[-1]["end"] <= 0.035
        )
        member = {**p, "phone": label, "phone_index": i}
        if merge:
            unit = result[-1]
            unit["members"].append(member)
            unit["end"] = p["end"]
        else:
            unit = {
                "time": p["start"],
                "end": p["end"],
                "phone": label,
                "members": [member],
                "kind": "perceptual_group_heuristic",
            }
            result.append(unit)
        previous = label
    for unit in result:
        unit["duration"] = unit["end"] - unit["time"]
        unit["label"] = " ".join(p["label"] for p in unit["members"])
        values = [strengths.get(round(p["start"], 5)) for p in unit["members"]]
        unit["strength"] = max((v for v in values if v is not None), default=None)
        runs = []
        for p in unit["members"]:
            if runs and runs[-1]["phone"] == p["phone"]:
                runs[-1]["end"] = p["end"]
            else:
                runs.append({"phone": p["phone"], "start": p["start"], "end": p["end"]})
        unit["phone_runs"] = runs
    return result


def measured_pauses(analysis, sensitivity=1.0):
    """Acoustic elastic cores, not permission to delete unknown/breath audio."""
    from .boundaries import energy_frames, quiet_runs

    lineage = analysis.get("audio_lineage")
    if not lineage:
        return []
    times, rms, hop = energy_frames(lineage["audio_path"], analysis["window_start"])
    threshold = max(float(np.quantile(rms, 0.85)) * 0.25 * sensitivity, 1e-5)
    phones = analysis.get("phones", [])
    if not phones:
        return []
    result = []
    for a, b in quiet_runs(times, rms, hop, threshold, minimum=0.12 / sensitivity):
        # Geminate closure is already counted as mora occupancy, not an extra rest.
        if any(p["label"] in {"cl", "q", "Q", "っ"} and p["start"] < b and p["end"] > a for p in phones):
            continue
        a, b = max(a, phones[0]["start"]), min(b, phones[-1]["end"])
        if b - a < 0.12 / sensitivity - 1e-8:
            continue
        result.append(
            {
                "start": a + 0.02,
                "end": b - 0.02,
                "kind": "acoustic_elastic_gap",
                "verified": False,
                "preserve_audio": True,
                "threshold": threshold,
            }
        )
    return result


@lru_cache(maxsize=256)
def _view(payload, splits, sensitivity):
    analysis = json.loads(payload)
    units = group_phones(analysis.get("phones", []), analysis.get("anchors", []), splits)
    pauses = measured_pauses(analysis, sensitivity) if units else []
    for u in units:
        u["phrase"] = sum(p["end"] <= u["time"] for p in pauses)
    return {
        "version": VERSION,
        "pause_sensitivity": sensitivity,
        "units": units,
        "pauses": pauses,
        "raw_anchor_count": len(analysis.get("anchors", [])),
        "split_before": list(splits),
        "verified": False,
        "timing_note": "Grouped vowel starts are an editable listening heuristic, not mora boundaries.",
    }


def rhythm_view(analysis, split_before=(), pause_sensitivity=1.0):
    if not analysis or not analysis.get("phones"):
        return None
    return _view(json.dumps(analysis, sort_keys=True), tuple(sorted(split_before)), pause_sensitivity)


def get_rhythm_view(db, cue_id, kind, analysis):
    if not analysis:
        return None
    row = db.execute(
        "SELECT split_before FROM rhythm_edits WHERE cue_id=? AND kind=? AND analysis_version=?",
        (cue_id, kind, analysis["version"]),
    ).fetchone()
    if row is None and analysis.get("raw_id"):
        # Only transfer edits when the exact upstream output and phone ordering
        # survived the adapter upgrade. Never guess old indices across models.
        for prior in db.execute(
            "SELECT e.split_before,a.payload FROM rhythm_edits e JOIN analyses a ON a.cue_id=e.cue_id AND a.kind=e.kind AND a.version=e.analysis_version WHERE e.cue_id=? AND e.kind=? ORDER BY e.updated DESC",
            (cue_id, kind),
        ):
            old = json.loads(prior[1])
            if old.get("raw_id") == analysis["raw_id"] and [p["label"] for p in old.get("phones", [])] == [
                p["label"] for p in analysis.get("phones", [])
            ]:
                row = prior
                break
    settings = db.execute(
        "SELECT payload FROM cue_settings WHERE cue_id=? AND kind=? AND analysis_id=?",
        (cue_id, kind, analysis["version"]),
    ).fetchone()
    options = json.loads(settings[0]) if settings else {}
    return rhythm_view(analysis, json.loads(row[0]) if row else (), options.get("pause_sensitivity", 1.0))
