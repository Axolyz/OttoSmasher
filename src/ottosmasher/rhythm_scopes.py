"""Virtual speech selections; neither subtitle ownership nor audio is rewritten.

Elastic low-energy cores are timing resources. Only conservative, longer cores
between complete rhythm units become independently searchable speech scopes.
"""

from __future__ import annotations

import math
from copy import deepcopy
from itertools import pairwise

from .rhythm_units import SILENCE, normalize_phone
from .workspace import identity

VERSION = "pause-scopes-v1"
SELECTION_VERSION = "source-selection-v1"
DEFAULT_PAUSE_SECONDS = 0.28


def _bounds(cue, analysis):
    lineage = analysis.get("audio_lineage") or {}
    return (
        float(lineage.get("window_start", analysis.get("window_start", cue.get("start", 0)))),
        float(lineage.get("window_end", analysis.get("window_end", cue.get("end", 0)))),
    )


def _options(settings, count):
    settings = settings or {}
    threshold = settings.get("pause_threshold_seconds", DEFAULT_PAUSE_SECONDS)
    if isinstance(threshold, bool) or not isinstance(threshold, (int, float)) or not 0.16 <= threshold <= 2:
        raise ValueError("Segment pause threshold must be between 0.16 and 2 seconds")

    def indices(name):
        values = settings.get(name, [])
        if not isinstance(values, (list, tuple)) or any(
            isinstance(i, bool) or not isinstance(i, int) or not 0 < i < count for i in values
        ):
            raise ValueError("Segment split must precede an existing non-first rhythm unit")
        return sorted(set(values))

    return {
        "pause_threshold_seconds": float(threshold),
        "split_before": indices("split_before"),
        "suppressed_split_before": indices("suppressed_split_before"),
    }


def _phone_indices(unit):
    return [m["phone_index"] for m in unit.get("members", []) if isinstance(m.get("phone_index"), int)]


def _automatic_boundary(analysis, units, pause, threshold):
    # A CTC blank, subtitle space or model silence tag is not acoustic evidence.
    if pause.get("kind") != "acoustic_elastic_gap":
        return None
    a, b = float(pause["start"]), float(pause["end"])
    if b - a < threshold - 1e-8:
        return None
    next_index = next((i for i, unit in enumerate(units) if unit["time"] >= b - 1e-7), None)
    if next_index is None or next_index == 0:
        return None
    previous, following = units[next_index - 1], units[next_index]
    if previous["end"] > a + 1e-7 or following["time"] < b - 1e-7:
        return None
    seam = (a + b) / 2
    phones = analysis.get("phones", [])
    if any(
        normalize_phone(p["label"]) not in SILENCE | {"AP", "[BOS]", "[EOS]"} and p["start"] < seam < p["end"]
        for p in phones
    ):
        return None
    # Even when its center is elsewhere, a geminate closure is not a rest.
    if any(p["label"] in {"cl", "q", "Q", "っ"} and p["start"] < b and p["end"] > a for p in phones):
        return None
    return {
        "split_before_unit_index": next_index,
        "source_seconds": seam,
        "gap_start": a,
        "gap_end": b,
        "gap_seconds": b - a,
        "basis": "long_acoustic_gap_between_complete_units",
        "manual": False,
        "verified": False,
        "preserve_audio": True,
    }


def _manual_boundary(analysis, units, index):
    previous, following = units[index - 1], units[index]
    left, right = float(previous["end"]), float(following["time"])
    # Include consonants leading into the next vowel. Phones between the prior
    # vowel and this unit belong on the right of the cut when there is no rest.
    first = min(_phone_indices(following), default=None)
    last = max(_phone_indices(previous), default=-1)
    if first is not None:
        for p in analysis.get("phones", [])[last + 1 : first]:
            if normalize_phone(p["label"]) not in SILENCE | {"AP", "[BOS]", "[EOS]"}:
                right = min(right, float(p["start"]))
    if left > right + 1e-7:
        raise ValueError(
            f"Cannot split before unit {index + 1}: the preceding sound crosses its leading consonant"
        )
    return {
        "split_before_unit_index": index,
        "source_seconds": (left + right) / 2,
        "gap_start": left,
        "gap_end": right,
        "gap_seconds": max(0.0, right - left),
        "basis": "manual_unit_boundary",
        "manual": True,
        "verified": False,
        "preserve_audio": True,
    }


def list_scopes(cue, analysis, view, settings=None):
    """Return parent whole cue followed by virtual, independently usable parts.

    Suppressed automatic boundaries are retained in the whole scope's evidence,
    making merge/disable actions reversible. Explicit manual splits win over a
    suppression at the same index.
    """
    units = view.get("units", [])
    options = _options(settings, len(units))
    start, end = _bounds(cue, analysis)
    if not math.isfinite(start + end) or not 0 <= start < end:
        raise ValueError("Invalid parent source bounds")
    candidates = {}
    for pause in view.get("pauses", []):
        boundary = _automatic_boundary(analysis, units, pause, options["pause_threshold_seconds"])
        if boundary and start < boundary["source_seconds"] < end:
            i = boundary["split_before_unit_index"]
            if i not in candidates or boundary["gap_seconds"] > candidates[i]["gap_seconds"]:
                candidates[i] = boundary
    detected = [
        dict(candidates[i], suppressed=i in options["suppressed_split_before"]) for i in sorted(candidates)
    ]
    for i in options["suppressed_split_before"]:
        candidates.pop(i, None)
    for i in options["split_before"]:
        candidates[i] = (
            dict(candidates[i], manual=True, basis="manual_confirmed_acoustic_boundary")
            if i in candidates
            else _manual_boundary(analysis, units, i)
        )
    boundaries = [candidates[i] for i in sorted(candidates)]
    analysis_id, rhythm_id = identity(analysis), identity(view)
    common = {
        "version": VERSION,
        "parent_cue_id": cue["id"],
        "parent_analysis_id": analysis_id,
        "parent_rhythm_id": rhythm_id,
        "settings": options,
        "parent_source_start": start,
        "parent_source_end": end,
        "parent_text": cue.get("spoken", cue.get("original", "")),
        "verified": False,
    }

    def descriptor(kind, ordinal, first, stop, left, right, incoming, outgoing):
        phone_indices = [
            i for i, p in enumerate(analysis.get("phones", [])) if p["end"] > left and p["start"] < right
        ]
        data = {
            **common,
            "kind": kind,
            "ordinal": ordinal,
            "label": "整句" if kind == "whole" else f"语段 {ordinal}",
            "source_start": left,
            "source_end": right,
            "parent_unit_indices": list(range(first, stop)),
            "parent_phone_indices": phone_indices,
            "boundaries": boundaries if kind == "whole" else [b for b in (incoming, outgoing) if b],
            "incoming_boundary": incoming,
            "outgoing_boundary": outgoing,
            "detected_boundaries": detected if kind == "whole" else [],
            "boundary_note": "Virtual selection; subtitle context and original audio are preserved.",
        }
        data["scope_id"] = identity(VERSION, data)
        return data

    whole = descriptor("whole", 0, 0, len(units), start, end, None, None)
    if not boundaries:
        return [whole]
    result = [whole]
    cuts = [0, *[b["split_before_unit_index"] for b in boundaries], len(units)]
    seams = [start, *[b["source_seconds"] for b in boundaries], end]
    for j, (first, stop) in enumerate(pairwise(cuts)):
        result.append(
            descriptor(
                "segment",
                j + 1,
                first,
                stop,
                seams[j],
                seams[j + 1],
                boundaries[j - 1] if j else None,
                boundaries[j] if j < len(boundaries) else None,
            )
        )
    for j, scope in enumerate(result[1:]):
        scope["previous_scope_id"] = result[j]["scope_id"] if j else None
        scope["next_scope_id"] = result[j + 2]["scope_id"] if j + 2 < len(result) else None
    return result


def _mora_range(analysis, view, indices):
    starts = [
        min(
            (m["mora_index"] for m in u.get("members", []) if isinstance(m.get("mora_index"), int)),
            default=None,
        )
        for u in view["units"]
    ]
    first, stop = indices[0], indices[-1] + 1
    begin = starts[first]
    end = starts[stop] if stop < len(starts) else (analysis.get("mora") or {}).get("count")
    if isinstance(begin, int) and isinstance(end, int) and 0 <= begin < end:
        return begin, end
    return None


def scope_context(cue, analysis, view, scope):
    """Derive local indices/rhythm inference input, retaining absolute source time."""
    signed = {k: v for k, v in scope.items() if k not in {"scope_id", "previous_scope_id", "next_scope_id"}}
    if (
        scope["parent_cue_id"] != cue["id"]
        or scope["parent_analysis_id"] != identity(analysis)
        or scope["parent_rhythm_id"] != identity(view)
        or scope["scope_id"] != identity(VERSION, signed)
    ):
        raise ValueError("Scope is stale or belongs to another cue/analysis")
    if scope["kind"] == "whole":
        return analysis, view
    if scope["kind"] != "segment":
        raise ValueError("Unknown rhythm scope kind")
    indices = scope["parent_unit_indices"]
    if (
        not indices
        or indices != list(range(indices[0], indices[-1] + 1))
        or indices[-1] >= len(view["units"])
    ):
        raise ValueError("Scope must contain an ordered contiguous unit selection")
    start, end = scope["source_start"], scope["source_end"]
    parent_start, parent_end = _bounds(cue, analysis)
    if not parent_start <= start < end <= parent_end:
        raise ValueError("Scope lies outside its parent audio crop")
    local_analysis, local_view = deepcopy(analysis), deepcopy(view)
    local_analysis["window_start"], local_analysis["window_end"] = start, end
    phones, index_map = [], {}
    mora_range = _mora_range(analysis, view, indices)

    def local_phone(phone, parent_index=None):
        p = deepcopy(phone)
        if parent_index is not None:
            p["parent_phone_index"] = parent_index
        if isinstance(p.get("mora_index"), int):
            p["parent_mora_index"] = p["mora_index"]
            if mora_range and mora_range[0] <= p["mora_index"] < mora_range[1]:
                p["mora_index"] -= mora_range[0]
            else:
                p.pop("mora_index", None)
        # Only silence should straddle an automatic seam. Keep the original
        # annotation explicitly when clipping it to a virtual selection.
        if p.get("start", start) < start or p.get("end", end) > end:
            p["parent_interval"] = [p["start"], p["end"]]
            p["start"], p["end"] = max(start, p["start"]), min(end, p["end"])
        return p

    for i, p in enumerate(analysis.get("phones", [])):
        if p["end"] > start and p["start"] < end:
            index_map[i] = len(phones)
            phones.append(local_phone(p, i))
    local_analysis["phones"] = phones
    local_analysis["anchors"] = [deepcopy(a) for a in analysis.get("anchors", []) if start <= a["time"] < end]
    local_analysis["mora"] = deepcopy(analysis.get("mora") or {})
    if mora_range:
        a, b = mora_range
        seq = local_analysis["mora"].get("sequence", [])
        local_analysis["mora"].update(count=b - a, sequence=seq[a:b], parent_range=[a, b])
        if len(seq) >= b:
            local_analysis["mora"]["reading"] = "".join(seq[a:b])
    else:
        local_analysis["mora"].update(
            count=None,
            sequence=[],
            phone_mapping="unavailable",
            reading="",
            scope_note="No reliable mora bounds for this selection",
        )
    local_view["units"] = []
    for i in indices:
        unit = deepcopy(view["units"][i])
        unit["parent_unit_index"] = i
        members = []
        for m in unit.get("members", []):
            parent_index = m.get("phone_index")
            p = local_phone(m, parent_index)
            if parent_index in index_map:
                p["phone_index"] = index_map[parent_index]
            else:
                p.pop("phone_index", None)
            members.append(p)
        unit["members"] = members
        local_view["units"].append(unit)
    local_view["pauses"] = [
        dict(p, start=max(start, p["start"]), end=min(end, p["end"]))
        for p in view.get("pauses", [])
        if p["end"] > start and p["start"] < end
    ]
    for unit in local_view["units"]:
        unit["phrase"] = sum(p["end"] <= unit["time"] for p in local_view["pauses"])
    local_view["raw_anchor_count"] = len(local_analysis["anchors"])
    local_view["split_before"] = [index_map[i] for i in view.get("split_before", []) if i in index_map]
    local_view["scope_id"] = scope["scope_id"]
    local_analysis["scope"] = deepcopy(scope)
    lineage = analysis.get("audio_lineage") or {}
    selection = {
        "version": SELECTION_VERSION,
        "scope_id": scope["scope_id"],
        "parent_cue_id": cue["id"],
        "source_fingerprint": cue.get("fingerprint"),
        "parent_analysis_id": scope["parent_analysis_id"],
        "parent_rhythm_id": scope["parent_rhythm_id"],
        "parent_window_start": parent_start,
        "parent_window_end": parent_end,
        "audio_sha256": lineage.get("audio_sha256"),
        "source_start": start,
        "source_end": end,
    }
    selection["selection_id"] = identity(SELECTION_VERSION, selection)
    local_analysis["audio_selection"] = selection
    return local_analysis, local_view
