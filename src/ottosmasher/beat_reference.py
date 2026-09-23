"""Three independent rhythm routes, rendered on four binary tempo grids."""

from __future__ import annotations

import math
from itertools import pairwise

import numpy as np

from .mora_features import mora_features
from .rhythm_allocation import infer_pattern, interval_measurements
from .workspace import DATA, identity, write_json

VERSION = "binary-reference-v5"
DENSITIES = (1, 2, 4, 8)
STRATEGIES = {"mora": "纯 mora", "mora_guided": "mora 参考校准", "acoustic": "原节奏量化（无 mora）"}


def slot_reference(analysis, view, reading="", overrides=None, auto_long_vowels=False):
    """Text occupancy only. Missing correspondence remains missing, never inferred."""
    units = view["units"]
    mora = mora_features(analysis, units, reading)
    starts = [
        min(
            (m["mora_index"] for m in u.get("members", []) if isinstance(m.get("mora_index"), int)),
            default=None,
        )
        for u in units
    ]
    counts = []
    for i, start in enumerate(starts):
        nxt = starts[i + 1] if i + 1 < len(starts) else mora.get("count")
        counts.append(
            nxt - start
            if isinstance(start, int) and isinstance(nxt, int) and start >= 0 and 0 < nxt - start <= 64
            else None
        )
    measured = interval_measurements(analysis, view)
    durations = measured["durations"]
    samples = [d / c for d, c in zip(durations, counts) if c and d / c > 0.035]
    tau = max(0.04, float(np.median(samples))) if samples else None
    slots = []
    for i, (u, count) in enumerate(zip(units, counts)):
        vowel_time = sum(
            r["end"] - r["start"] for r in u.get("phone_runs", []) if r["phone"] in {"a", "i", "u", "e", "o"}
        )
        crosses_pause = any(p["start"] < u["end"] and p["end"] > u["time"] for p in view["pauses"])
        inferred = count
        if auto_long_vowels and count and tau and not crosses_pause and vowel_time > (count + 0.5) * tau:
            inferred = min(64, max(count, round(vowel_time / tau)))
        chosen = (overrides or {}).get(str(i), inferred)
        slots.append(
            {
                "unit_index": i,
                "text_mora_count": count,
                "effective_slots": chosen,
                "basis": "manual"
                if str(i) in (overrides or {})
                else "missing_mora"
                if count is None
                else "long_vowel_extension"
                if inferred > count
                else "text_mora",
                "measured_speech_seconds": durations[i],
                "vowel_seconds": vowel_time,
                "uncertain": count is None,
            }
        )
    return {
        "mora": mora,
        "slots": slots,
        "mora_seconds": tau,
        "speech_seconds": measured["speech_seconds"],
        "text_mora_count": mora.get("count"),
    }


def compile_reference(cue, analysis, view, overrides=None, auto_long_vowels=False, large_number_penalty=1.0):
    """BPM-independent inference, persisted once for all grids and searches."""
    units = view["units"]
    if not units or len(units) > 128 or any(b["time"] <= a["time"] for a, b in pairwise(units)):
        raise ValueError("Need 1–128 strictly increasing rhythm onsets")
    measured = interval_measurements(analysis, view)
    # Acoustic inference is deliberately evaluated before constructing any mora
    # reference. Both initialization and fallback depend on measured intervals.
    acoustic = infer_pattern(units, measured, overrides=overrides, complexity_weight=0.045 * large_number_penalty)
    reference = slot_reference(analysis, view, cue.get("reading", ""), overrides, auto_long_vowels)
    text_counts = [s["text_mora_count"] for s in reference["slots"]]
    guided = infer_pattern(units, measured, priors=text_counts, overrides=overrides)
    base_slots = [s["effective_slots"] for s in reference["slots"]]
    routes = {"acoustic": acoustic, "mora_guided": guided}
    if all(n is not None for n in base_slots):
        routes["mora"] = {
            "slots": base_slots,
            "source_tick_seconds": measured["speech_seconds"] / sum(base_slots),
            "costs": {},
            "message": "文本 mora 直接决定占格"
            + ("；已开启连续长音补格" if auto_long_vowels else "；自动长音补格关闭"),
        }
    statuses = [
        {
            "strategy": k,
            "label": label,
            "available": k in routes,
            "reason": None
            if k in routes
            else "部分节奏单元没有可靠 mora 对应，请填写缺失占格或使用另外两条路线",
        }
        for k, label in STRATEGIES.items()
    ]
    comparisons = {k: route["slots"] for k, route in routes.items()}
    for i, s in enumerate(reference["slots"]):
        s["comparison_slots"] = {k: comparisons.get(k, [None] * len(units))[i] for k in STRATEGIES}
    return {
        "large_number_penalty": large_number_penalty,
        "measured": measured,
        "reference": reference,
        "routes": routes,
        "statuses": statuses,
    }


def generate_references(
    cue,
    analysis,
    view,
    bpm=120,
    strategy="mora",
    density=None,
    witness=None,
    overrides=None,
    auto_long_vowels=False,
    compiled=None,
    persist=True,
):
    if witness:
        raise ValueError("Query redistribution retired; use matched plan_id")
    if strategy not in STRATEGIES:
        raise ValueError("Unknown reference strategy; use mora, mora_guided or acoustic")
    if not math.isfinite(bpm) or not 20 <= bpm <= 400:
        raise ValueError("BPM must be between 20 and 400")
    if density is not None and (not math.isfinite(density) or density<=0 or abs(math.log2(density)-round(math.log2(density)))>1e-9):
        raise ValueError("Density must be a positive power of two")
    units = view["units"]
    if not units or len(units) > 128 or any(b["time"] <= a["time"] for a, b in pairwise(units)):
        raise ValueError("Need 1–128 strictly increasing rhythm onsets")
    for k, v in (overrides or {}).items():
        if (
            not str(k).isdigit()
            or not 0 <= int(k) < len(units)
            or isinstance(v, bool)
            or not isinstance(v, int)
            or not 1 <= v <= 64
        ):
            raise ValueError("Slot edit must name an existing unit and occupy 1–64 cells")
    import copy

    compiled = compiled or compile_reference(cue, analysis, view, overrides, auto_long_vowels)
    measured, routes = compiled["measured"], compiled["routes"]
    reference = copy.deepcopy(compiled["reference"])
    statuses = compiled["statuses"]
    reference["mora"]["used_as"] = {
        "mora": "text occupancy with optional acoustic long-vowel extension",
        "mora_guided": "soft prior for measured-interval allocation",
        "acoustic": "display and route comparison only; no input to acoustic timing",
    }[strategy]
    common = {
        "algorithm_statuses": statuses,
        "mora": reference["mora"],
        "reference": reference,
        "retrieval_score_unchanged": True,
    }
    if strategy not in routes:
        return {
            **common,
            "plans": [],
            "conflicts": [],
            "message": next(s["reason"] for s in statuses if s["strategy"] == strategy),
        }
    plans, conflicts = [], []
    beat = 60 / bpm
    for d in DENSITIES if density is None else [density]:
        grid = 1 / d
        mappings = {}
        for name, route in routes.items():
            slots = list(route["slots"])
            # A single inferred pattern is played at four densities. Do not
            # re-estimate the source ruler per density and cancel the speed change.
            factor = sum(slots) * grid * beat / measured["speech_seconds"]
            tick = measured["speech_seconds"] / sum(slots)
            rests = [max(0, round(seconds / tick)) for seconds in measured["rest_seconds"]]
            targets = [0.0]
            for i in range(len(units) - 1):
                targets.append(targets[-1] + (slots[i] + rests[i]) * grid)
            mappings[name] = {
                "targets": targets,
                "slots": slots,
                "rests": rests,
                "factor": factor,
                "end": targets[-1] + (slots[-1] + rests[-1]) * grid,
            }
        if strategy not in mappings:
            continue
        route, mapping = routes[strategy], mappings[strategy]
        slots, targets, rests, factor = (
            mapping["slots"],
            mapping["targets"],
            mapping["rests"],
            mapping["factor"],
        )
        baseline = mappings.get("mora")
        same = [
            k
            for k, m in mappings.items()
            if k != strategy
            and np.allclose(targets, m["targets"], rtol=0, atol=1e-8)
            and abs(mapping["end"] - m["end"]) < 1e-8
            and abs(factor - m["factor"]) < 1e-8
        ]
        diffs = [i for i, t in enumerate(targets) if baseline and abs(t - baseline["targets"][i]) > 1e-8]
        if baseline and abs(mapping["end"] - baseline["end"]) > 1e-8 and len(units) - 1 not in diffs:
            diffs.append(len(units) - 1)
        matches = witness["matched_anchor_indices"] if witness else []
        # Include the final sustained sound when reporting local deformation.
        source_points = [u["time"] for u in units] + [measured["end"]]
        ratios = np.diff(targets + [mapping["end"]]) * beat / np.diff(source_points)
        plan = {
            "version": VERSION,
            "cue_id": cue["id"],
            "analysis_kind": analysis.get("backend", "phonetic"),
            "analysis_version": analysis["version"],
            "analysis_id": identity(analysis),
            "rhythm_id": identity(view),
            "strategy": strategy,
            "auto_long_vowels": auto_long_vowels,
            "comparison_status": "baseline"
            if strategy == "mora"
            else "unavailable_baseline"
            if not baseline
            else "same_as_baseline"
            if "mora" in same
            else "different",
            "same_as_strategies": same,
            "changed_unit_indices": diffs,
            "density": d,
            "grid_beats": grid,
            "meter": [4, 4],
            "beat_seconds": beat,
            "duration_multiplier": factor,
            "estimated_duration_seconds": max(
                mapping["end"] * beat + (analysis["window_end"] - measured["end"]) * factor,
                (witness or {}).get("query_span_beats", 0) * beat,
            )
            - min(0, targets[0] * beat - (units[0]["time"] - analysis["window_start"]) * factor),
            "score": abs(math.log(factor)),
            "label": f"×{d} · {STRATEGIES[strategy]}",
            "slots": [
                {
                    **s,
                    "effective_slots": slots[i],
                    "inferred_slots": route["slots"][i],
                    "baseline_slots": baseline["slots"][i] if baseline else None,
                    "comparison_slots": {
                        k: mappings[k]["slots"][i] if k in mappings else None for k in STRATEGIES
                    },
                    "rest_slots_after": rests[i],
                    "basis": "search_lock"
                    if slots[i] != route["slots"][i]
                    else s["basis"]
                    if strategy == "mora" or str(i) in (overrides or {})
                    else strategy,
                }
                for i, s in enumerate(reference["slots"])
            ],
            "unit_targets": [
                {
                    "unit_index": i,
                    "source_seconds": u["time"],
                    "target_beat": targets[i],
                    "baseline_target_beat": baseline["targets"][i] if baseline else None,
                    "label": u.get("label", ""),
                    "role": "matched" if i in matches else "automatic",
                    "query_index": matches.index(i) if i in matches else None,
                }
                for i, u in enumerate(units)
            ],
            "end_target": {"source_seconds": measured["end"], "target_beat": mapping["end"]},
            "local_duration_ratios": ratios.tolist(),
            "min_duration_ratio": float(min(ratios)),
            "max_duration_ratio": float(max(ratios)),
            "pauses": view["pauses"],
                "algorithm_evidence": {k: v for k, v in route.items() if k != "slots"},
            "mora": reference["mora"],
            "mora_seconds": reference["mora_seconds"],
            "witness": witness,
            "preserves_all_units": True,
            "retrieval_score_unchanged": True,
        }
        plan["plan_id"] = identity(VERSION, plan)
        if persist:
            write_json(DATA / "quantization-plans" / (plan["plan_id"] + ".json"), plan)
        plans.append(plan)
    plans.sort(key=lambda p: (p["score"], p["density"]))
    return {
        **common,
        "plans": plans,
        "conflicts": conflicts,
        "message": None if plans else "所选倍率没有满足锁点条件的方案",
    }
