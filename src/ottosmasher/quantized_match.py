"""Fast retrieval against compiled rhythm patterns, without refitting the audio.

Only a translation is searched here. The indexed rhythm's internal intervals,
including its final sound, remain unchanged. Required-query tolerance is a
retrieval tolerance; it never silently creates a different quantization plan.
"""

from __future__ import annotations

import math
from itertools import product

import numpy as np

VERSION = "quantized-pattern-match-v2"
from .sound_features import first_vowel, satisfies
from .time_mapping import schedule

EPS = 1e-9


def _get(value, key, default=None):
    return value.get(key, default) if isinstance(value, dict) else getattr(value, key, default)


def _map(value, source, target, factor):
    """Piecewise timing with the same overall speed for unmarked outer audio."""
    if value < source[0]:
        return float(target[0] + (value - source[0]) * factor)
    if value > source[-1]:
        return float(target[-1] + (value - source[-1]) * factor)
    return float(np.interp(value, source, target))


def _duration(unit, requested_phone, source, target, factor):
    if requested_phone and first_vowel(unit) != requested_phone:
        return None
    if unit.get("end") is None:
        return None
    return _map(unit["end"], source, target, factor) - _map(unit["time"], source, target, factor)


def _requirements(query):
    notes = sorted(_get(query, "notes", []), key=lambda n: _get(n, "start_beats"))
    if notes:
        return [(_get(n, "start_beats"), n) for n in notes], notes, []
    step = _get(query, "step_beats", 0.5)
    cells = _get(query, "cells", [])
    return (
        [(i * step, c) for i, c in enumerate(cells) if _get(c, "state") == "required"],
        [],
        [i * step for i, c in enumerate(cells) if _get(c, "state") == "forbidden"],
    )


def _translations(beats, requirements, notes, forbidden, eligible, tolerance):
    """All piecewise eligibility/exclusion regions, with L1 minima and edges.

    A fixed correspondence is valid over an interval of translations. Its mean
    absolute error is minimized at an alignment center or a constraint edge.
    Midpoints and both sides of an edge handle half-open note exclusions without
    relying on a floating-point nudge as the only representative of a region.
    """
    first = beats[eligible[0]]
    low = requirements[0][0] - first[-1] - tolerance
    high = requirements[0][0] - first[0] + tolerance
    points = [low, high]
    for (target, _), mask in zip(requirements, eligible, strict=True):
        centers = target - beats[mask]
        points.extend(centers)
        points.extend(centers - tolerance)
        points.extend(centers + tolerance)
    for note in notes:
        points.extend(_get(note, "start_beats") - beats)
        points.extend(_get(note, "end_beats") - beats)
    for target in forbidden:
        points.extend(target - beats - tolerance)
        points.extend(target - beats + tolerance)
    edges = np.unique(np.round(points, 12))
    edges = edges[(edges >= low - EPS) & (edges <= high + EPS)]
    mids = (edges[:-1] + edges[1:]) / 2
    shifts = np.unique(np.concatenate((edges, mids, edges - 4 * EPS, edges + 4 * EPS)))
    return shifts[(shifts >= low - EPS) & (shifts <= high + EPS)]


def _match_fixed_pattern(pattern, query):
    """Return the best verified translation, or ``None`` when none is legal.

    ``pattern.plan`` is a previously compiled binary reference, conventionally
    at 120 BPM. Its source mapping is rescaled to the requested BPM; density is
    never interpreted as an independent playback-speed multiplier.
    """
    units, plan = pattern.get("units", []), pattern.get("plan", {})
    if not units or len(units) > 2048:
        return None
    density = plan.get("density", pattern.get("density"))
    if density not in _get(query, "densities", [1, 2, 4, 8]):
        return None
    if _get(query, "strategy") and plan.get("strategy") != _get(query, "strategy"):
        return None
    scope = pattern.get("scope", {})
    wanted_scope = _get(query, "scope", "both")
    kind = scope.get("kind", "whole")
    if wanted_scope == "whole" and kind != "whole":
        return None
    if wanted_scope == "segments" and kind != "segment":
        return None
    requirements, notes, forbidden = _requirements(query)
    if not requirements or len(requirements) > len(units):
        return None
    points = plan.get("unit_targets", [])
    end = plan.get("end_target")
    if len(points) != len(units) or not end:
        return None
    onset_source = np.array([p["source_seconds"] for p in points], dtype=float)
    source = np.append(onset_source, end["source_seconds"])
    target_beats = np.array([p["target_beat"] for p in points] + [end["target_beat"]], dtype=float)
    if not np.all(np.isfinite(source)) or not np.all(np.isfinite(target_beats)):
        return None
    if np.any(np.diff(source) <= 0) or np.any(np.diff(target_beats) <= 0):
        return None
    if any(abs(u["time"] - onset_source[i]) > 1e-6 for i, u in enumerate(units)):
        return None
    beat = 60 / _get(query, "bpm", 120)
    factor = plan.get("duration_multiplier", 1.0) * beat / plan.get("beat_seconds", 0.5)
    if not math.isfinite(factor) or factor <= 0:
        return None
    beats = target_beats[:-1]
    control_points = plan.get("control_targets", [])
    timing_points = sorted(points + control_points + [end], key=lambda p: p["source_seconds"])
    mapping_points = {}
    for point in timing_points:
        previous = mapping_points.get(point["source_seconds"])
        if previous is not None and abs(previous - point["target_beat"]) > EPS:
            return None
        mapping_points[point["source_seconds"]] = point["target_beat"]
    source = np.array(list(mapping_points), dtype=float)
    timing_beats = np.array(list(mapping_points.values()), dtype=float)
    if np.any(np.diff(source) <= 0) or np.any(np.diff(timing_beats) <= 0):
        return None
    target_seconds = timing_beats * beat
    source_start = scope.get("source_start", scope.get("source_start_seconds", float(source[0])))
    source_end = scope.get("source_end", scope.get("source_end_seconds", float(source[-1]) + 0.02))
    if source_end <= source[-1]:
        source_end = float(source[-1]) + 1 / 48000

    def timing_for_pattern():
        return schedule(
            {**plan, "beat_seconds": beat, "duration_multiplier": factor, "retain_query_canvas": False},
            source_start,
            round((source_end - source_start) * 48000),
        )

    needs_duration = any(
        _get(n, "duration_min_beats") is not None or _get(n, "duration_max_beats") is not None
        for _, n in requirements
    )
    timing = None
    if needs_duration:
        try:
            timing = timing_for_pattern()
        except ValueError:
            return None
    if needs_duration:
        exact_knots = np.array(timing["time_map"]["knots"])
        mapped_source, mapped_target = exact_knots[:, 0], exact_knots[:, 1]
    tolerance = _get(query, "tolerance_beats", 0.15)
    boundary = _get(query, "boundary", "anywhere")
    eligible = []
    cached = pattern.get("_eligibility_cache", {})
    for j, (_, requirement) in enumerate(requirements):
        if not needs_duration and j in cached:
            eligible.append(cached[j])
            continue
        mask = np.ones(len(units), dtype=bool)
        if j == 0 and boundary in {"start", "both"}:
            mask[1:] = False
        if j == len(requirements) - 1 and boundary in {"end", "both"}:
            mask[:-1] = False
        static_filters = any(
            _get(requirement, key) is not None
            for key in (
                "phone",
                "speaker",
                "pitch_trend",
                "pitch_register",
                "energy_relative_min_db",
                "strength_min",
            )
        )
        if not static_filters and not needs_duration:
            if not mask.any():
                return None
            eligible.append(mask)
            cached[j] = mask
            continue
        for i, unit in enumerate(units):
            phone = _get(requirement, "phone")
            duration = (
                _duration(unit, phone, mapped_source, mapped_target, factor) if needs_duration else None
            )
            if not satisfies(
                unit["features"] if "features" in unit else {"first_vowel": first_vowel(unit)}, requirement
            ):
                mask[i] = False
            strength = _get(requirement, "strength_min")
            if strength is not None and (unit.get("strength") is None or unit["strength"] < strength):
                mask[i] = False
            for key, lower in (("duration_min_beats", True), ("duration_max_beats", False)):
                bound = _get(requirement, key)
                if bound is not None and (
                    duration is None
                    or (duration / beat < bound - EPS if lower else duration / beat > bound + EPS)
                ):
                    mask[i] = False
        if not mask.any():
            return None
        eligible.append(mask)
        if not needs_duration:
            cached[j] = mask
    required = _get(query, "required_unit_indices")
    if required is not None:
        if len(required) != len(eligible): return None
        narrowed = []
        for mask, index in zip(eligible, required):
            if not 0 <= index < len(mask) or not mask[index]: return None
            only = np.zeros(len(mask), dtype=bool); only[index] = True
            narrowed.append(only)
        eligible = narrowed
    # The query validator guarantees these disjoint tolerance neighborhoods, so
    # every per-point nearest assignment is automatically ordered and injective.
    target = np.array([r[0] for r in requirements], dtype=float)
    if len(target) > 1 and np.any(np.diff(target) <= 2 * tolerance):
        raise ValueError("Query onset tolerance must be less than half the closest onset interval")
    shifts = _translations(beats, requirements, notes, forbidden, eligible, tolerance)
    best = None
    sustain_ends = None
    for offset in range(0, len(shifts), 256):
        chunk = shifts[offset : offset + 256]
        positions = chunk[:, None] + beats[None, :]
        valid = np.ones(len(chunk), dtype=bool)
        indices = np.zeros((len(chunk), len(target)), dtype=int)
        errors = np.zeros((len(chunk), len(target)))
        for f in forbidden:
            valid &= np.min(np.abs(positions - f), axis=1) > tolerance + EPS
        for j, (t, _) in enumerate(requirements):
            distances = np.where(eligible[j][None, :], np.abs(positions - t), np.inf)
            if notes:
                inside = (positions >= _get(notes[j], "start_beats") - EPS) & (
                    positions < _get(notes[j], "end_beats") - EPS
                )
                counts = inside.sum(axis=1)
                valid &= counts <= 1
                distances = np.where((counts[:, None] == 0) | inside, distances, np.inf)
            indices[:, j] = np.argmin(distances, axis=1)
            errors[:, j] = distances[np.arange(len(chunk)), indices[:, j]]
            valid &= errors[:, j] <= tolerance + EPS
        valid &= np.all(np.diff(indices, axis=1) > 0, axis=1)
        required = _get(query, "required_unit_indices")
        if required is not None:
            valid &= np.all(indices == np.asarray(required)[None, :], axis=1)
        # Defer sample-frame duration checks until onset geometry has candidates;
        # map unit endpoints once, not once per query note and translation chunk.
        sustained = [j for j, (_, req) in enumerate(requirements) if _get(req, "sustain_to_end", False)]
        if valid.any() and sustained:
            if timing is None:
                try:
                    timing = timing_for_pattern()
                except ValueError:
                    return None
            if sustain_ends is None:
                source_ends = np.array(
                    [(u.get("features") or {}).get("sustain_end") for u in units], dtype=float
                )
                known = np.isfinite(source_ends)
                sustain_ends = np.full(len(units), -np.inf)
                exact_knots = np.asarray(timing["time_map"]["knots"])
                sustain_ends[known] = (
                    np.interp(source_ends[known], exact_knots[:, 0], exact_knots[:, 1]) / beat
                )
            for j in sustained:
                valid &= (
                    sustain_ends[indices[:, j]] + chunk
                    >= _get(requirements[j][1], "end_beats") - 1 / 48000 / beat
                )
        for k in np.flatnonzero(valid):
            rank = (
                round(float(errors[k].mean()), 12),
                round(float(errors[k].max()), 12),
                abs(float(chunk[k])),
                float(chunk[k]),
            )
            if best is None or rank < best[0]:
                best = (rank, float(chunk[k]), indices[k].tolist(), errors[k].tolist())
    if best is None:
        return None
    if timing is None:
        try:
            timing = timing_for_pattern()
        except ValueError:
            return None
    speech_speed = timing["speech_playback_speed"]
    if not speech_speed:
        return None
    rank, shift, matched, errors = best
    shifted = target_beats + shift
    source_start = scope.get("source_start", scope.get("source_start_seconds", source[0]))
    source_end = scope.get("source_end", scope.get("source_end_seconds", source[-1]))
    knots = [[float(s), float((t + shift) * beat)] for s, t in zip(source, timing_beats, strict=True)]
    if source_start < source[0]:
        knots.insert(0, [source_start, knots[0][1] - (source[0] - source_start) * factor])
    if source_end > source[-1]:
        knots.append([source_end, knots[-1][1] + (source_end - source[-1]) * factor])
    local_ratios = np.diff(target_seconds) / np.diff(source)
    deformation = float(np.mean(np.abs(np.log(local_ratios / factor))))
    if _get(query, "speed_filter", False) and not (
        _get(query, "factor_min", 0.85) - EPS <= 1 / speech_speed <= _get(query, "factor_max", 1.18) + EPS
    ):
        return None
    speed = abs(math.log(speech_speed))
    mean_error, max_error = float(np.mean(errors)), float(max(errors))
    mapping = {**timing["time_map"], "knots": [[s, t + shift * beat] for s, t in timing["time_map"]["knots"]]}
    return {
        "category": "feasible",
        "engine": "quantized",
        "pattern_id": pattern.get("pattern_id"),
        "scope": scope,
        "density": density,
        "strategy": plan.get("strategy"),
        "placement_beats": shift,
        "duration_multiplier": float(factor),
        "offset_seconds": float(knots[0][1]),
        "rhythm_error": mean_error,
        "deformation_penalty": deformation,
        "speed_penalty": speed,
        "max_error_beats": max_error,
        "mean_error_beats": mean_error,
        "forbidden_violations": 0,
        "cost": mean_error + 0.03 * deformation + 0.02 * speed,
        "speech_playback_speed": speech_speed,
        "source_speech_seconds": timing["source_speech_seconds"],
        "target_speech_seconds": timing["target_speech_seconds"],
        "anchor_beats": shifted[:-1].tolist(),
        "target_beats": target.tolist(),
        "matched_anchor_indices": matched,
        "anchors": units,
        "origin_seconds": float(source_start),
        "query_span_beats": _get(query, "span_beats", max(target) + 1),
        "time_map": mapping,
        "shifted_unit_targets": [
            {
                **p,
                "target_beat": float(shifted[i]),
                "role": "matched" if i in matched else "automatic",
                "query_index": matched.index(i) if i in matched else None,
            }
            for i, p in enumerate(points)
        ],
        "shifted_end_target": {**end, "target_beat": float(shifted[-1])},
        "shifted_control_targets": [{**p, "target_beat": p["target_beat"] + shift} for p in control_points],
        "local_warp": True,
        "pause_adjusted": False,
        "exact_onsets": max_error * beat <= 0.001,
        "search_complete": True,
        "search_domain": "translations_of_this_compiled_pattern",
        "duration_filter_basis": "shared_sample_frame_map",
        "retrieval_score_unchanged": True,
    }


def _apply_rests(pattern, chosen):
    """Edit only inter-segment rest counts; segment heads and tails move together."""
    source_plan = pattern["plan"]
    # Only these dictionaries change. Phones, source features and provenance stay immutable.
    variant = {
        **pattern,
        "plan": {
            **source_plan,
            "unit_targets": [dict(x) for x in source_plan["unit_targets"]],
            "control_targets": [dict(x) for x in source_plan.get("control_targets", [])],
            "end_target": dict(source_plan["end_target"]),
            "links": [dict(x) for x in source_plan.get("links", [])],
        },
    }

    plan = variant["plan"]
    grid = plan.get("grid_beats", 1 / plan["density"])
    links = plan.get("links", [])
    deltas = [int(cells) - int(link["rest_cells"]) for link, cells in zip(links, chosen, strict=True)]

    def shift_for_unit(index):
        return (
            sum(delta for link, delta in zip(links, deltas, strict=True) if index >= link["next_unit_index"])
            * grid
        )

    for point in plan["unit_targets"]:
        point["target_beat"] += shift_for_unit(point["unit_index"])
    for point in plan.get("control_targets", []):
        point["target_beat"] += shift_for_unit(point["after_unit_index"])
    plan["end_target"]["target_beat"] += sum(deltas) * grid
    adjustments = []
    for index, (link, cells, delta) in enumerate(zip(links, chosen, deltas, strict=True)):
        adjustments.append(
            {
                "link_index": link.get("link_index", index),
                "after_unit_index": link["after_unit_index"],
                "next_unit_index": link["next_unit_index"],
                "source_start": link["source_start"],
                "source_end": link["source_end"],
                "original_rest_cells": link["rest_cells"],
                "rest_cells": int(cells),
                "delta_cells": delta,
                "delta_beats": delta * grid,
            }
        )
        link["rest_cells"] = int(cells)
    return variant, adjustments


def _rest_choices(pattern, query, limit=128):
    """Bounded, deterministic integer combinations, with explicit search coverage.

    A single connecting rest is cheap enough to enumerate completely. For more
    links we retain the original, query-derived single-link edits, distributed
    query-span edits, then nearby combinations. This is deliberately bounded;
    it makes no completeness claim for a large Cartesian product of rests.
    """
    plan = pattern["plan"]
    links = plan.get("links", [])
    original = tuple(int(link["rest_cells"]) for link in links)
    domains = [
        list(range(max(1, int(link.get("min_rest_cells", 1))), int(link.get("max_rest_cells", 32)) + 1))
        for link in links
    ]
    if any(not domain for domain in domains):
        return [], 0
    # A preserved default need not be discarded if a newly tightened manual
    # range excludes it. It remains an explicit, unchanged candidate.
    for domain, value in zip(domains, original, strict=True):
        if value not in domain:
            domain.append(value)
    size = math.prod(map(len, domains))
    if size <= limit:
        return sorted(
            product(*domains), key=lambda c: (sum(abs(a - b) for a, b in zip(c, original)), c)
        ), size
    requirements, _, _ = _requirements(query)
    required_beats = np.array([r[0] for r in requirements])
    source_beats = np.array([p["target_beat"] for p in plan["unit_targets"]])
    grid = plan.get("grid_beats", 1 / plan["density"])
    target_deltas = np.unique(np.r_[np.diff(required_beats), required_beats[-1] - required_beats[0]])
    options = []
    for link, domain, old in zip(links, domains, original, strict=True):
        # Any source pair spanning this seam can suggest its rest duration.
        left = source_beats[: link["after_unit_index"] + 1]
        right = source_beats[link["next_unit_index"] :]
        spans = (right[:, None] - left[None, :]).ravel()

        def option_score(value, old=old, spans=spans):
            if value == old:
                return (-1.0, 0, value)
            mismatch = float(np.min(np.abs(spans[:, None] + (value - old) * grid - target_deltas)))
            return (round(mismatch, 8), abs(value - old), value)

        options.append(sorted(domain, key=option_score))
    choices = {original: None}

    def add(values):
        value = tuple(values)
        if len(choices) < limit and all(v in d for v, d in zip(value, domains, strict=True)):
            choices.setdefault(value, None)

    # Span changes that require several gaps to move cannot be found by only
    # testing one-link edits. Distribute the desired integer change in several
    # deterministic orders, respecting every link's positive lower bound.
    source_span = source_beats[-1] - source_beats[0]
    desired_delta = round(((required_beats[-1] - required_beats[0]) - source_span) / grid)
    orders = [
        list(range(len(links))),
        list(reversed(range(len(links)))),
        sorted(range(len(links)), key=lambda i: -original[i]),
    ]
    for order in orders:
        cells, remaining = list(original), desired_delta
        for i in order:
            change = min(max(remaining, min(domains[i]) - cells[i]), max(domains[i]) - cells[i])
            cells[i] += change
            remaining -= change
        if remaining == 0:
            add(cells)
    even = list(original)
    remaining = desired_delta
    while remaining:
        progress = False
        for i in range(len(links)):
            step = 1 if remaining > 0 else -1
            if even[i] + step in domains[i]:
                even[i] += step
                remaining -= step
                progress = True
                if not remaining:
                    break
        if not progress:
            break
    if remaining == 0:
        add(even)
    # Reserve half the candidate budget for simultaneous nearby edits.
    for rank in range(1, max(map(len, options))):
        for i, values in enumerate(options):
            if rank < len(values) and len(choices) < limit // 2:
                cells = list(original)
                cells[i] = values[rank]
                add(cells)
    # Beam over the small best-ranked prefixes prevents exponential expansion.
    beam = [((), 0)]
    for values in options:
        expanded = [
            (prefix + (value,), score + rank)
            for prefix, score in beam
            for rank, value in enumerate(values[:8])
        ]
        expanded.sort(key=lambda x: (x[1], x[0]))
        beam = expanded[:limit]
    for cells, _ in beam:
        add(cells)
    return list(choices), size


def match_pattern(pattern, query):
    """Search compiled translation, and optional bounded adjacent-segment rests."""
    if hasattr(query, "model_dump"):
        query = query.model_dump()
    plan = pattern.get("plan", {})
    if plan.get("density", pattern.get("density")) not in _get(query, "densities", [1, 2, 4, 8]):
        return None
    if _get(query, "strategy") and plan.get("strategy") != _get(query, "strategy"):
        return None
    if not _requirements(query)[0]:
        return None
    links = plan.get("links", [])
    if not plan.get("composition") or not links or not _get(query, "adjust_pauses", False):
        result = _match_fixed_pattern(pattern, query)
        if result is not None:
            result["composition"] = bool(plan.get("composition"))
            result["adjusted_links"] = links
            result["rest_adjustments"] = []
            result["shifted_slots"] = plan.get("slots", [])
        return result
    if any(
        link["source_end"] <= link["source_start"]
        or int(link["rest_cells"]) < 1
        or link["next_unit_index"] <= link["after_unit_index"]
        for link in links
    ):
        return None
    pattern = {**pattern, "_eligibility_cache": {}}
    choices, domain_size = _rest_choices(pattern, query)
    best = None
    evaluated = 0
    proved_optimal = False
    for chosen in choices:
        evaluated += 1
        variant, adjustments = _apply_rests(pattern, chosen)
        result = _match_fixed_pattern(variant, query)
        if result is None:
            continue
        change = sum(abs(a["delta_cells"]) for a in adjustments)
        result.update(
            composition=True,
            adjusted_links=variant["plan"]["links"],
            rest_adjustments=adjustments,
            shifted_slots=variant["plan"].get("slots", []),
            pause_adjusted=bool(change),
            rest_change_penalty=change * 0.003,
        )
        result["cost"] += result["rest_change_penalty"]
        # Never replace the preserved mapping merely to improve the secondary
        # deformation score when its rhythm fit is already just as good.
        rank = (round(result["rhythm_error"], 9), change, result["cost"], chosen)
        if best is None or rank < best[0]:
            best = (rank, result)
        if rank[0] == 0 and change == 0:
            proved_optimal = True
            break  # No other rest assignment can improve zero error and zero change.
    if best is None:
        return None
    result = best[1]
    result["rest_search"] = {
        "evaluated_variants": evaluated,
        "optimal_unchanged": proved_optimal,
        "candidate_limit": 128,
        "domain_size": domain_size,
        "complete": len(choices) == domain_size,
    }
    result["search_complete"] = len(choices) == domain_size
    result["search_domain"] = "bounded_adjacent_rests_and_compiled_pattern_translations"
    return result
