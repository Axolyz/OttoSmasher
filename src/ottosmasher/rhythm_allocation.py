"""Integer rhythm inference from measured intervals, with an optional text prior.

The source tick is a quantization ruler, not a claim of a unique speech BPM.
No subtitle, phone-to-mora mapping or mora-derived initialization enters here.
"""

from __future__ import annotations

import math

import numpy as np


def interval_measurements(analysis, view):
    units = view["units"]
    end = min(max(units[-1]["end"], units[-1]["time"] + 0.001), analysis["window_end"] - 0.001)
    ends = [u["time"] for u in units[1:]] + [end]
    durations, rests = [], []
    for u, stop in zip(units, ends):
        start = u["time"]
        if stop <= start:
            raise ValueError("节奏点或句末控制点没有正的声音时长，请检查边界")
        spans = sorted((max(start, p["start"]), min(stop, p["end"])) for p in view["pauses"])
        quiet, until = 0.0, start
        for a, b in spans:
            quiet += max(0, b - max(a, until))
            until = max(until, b)
        quiet = min(quiet, max(0, stop - start - 0.005))
        durations.append(max(0.005, stop - start - quiet))
        rests.append(quiet)
    return {"durations": durations, "rest_seconds": rests, "speech_seconds": sum(durations), "end": end}


def infer_pattern(units, measurements, priors=None, overrides=None, complexity_weight=0.045):
    if not 0 <= complexity_weight <= 0.135:
        raise ValueError("Invalid integer complexity weight")
    durations = np.asarray(measurements["durations"])
    manual = {int(k): v for k, v in (overrides or {}).items()}
    prior = priors or [None] * len(units)
    median = float(np.median(durations))
    # Very short marked intervals must retain an onset, but should not set
    # the ruler for the entire sentence. Weight by acoustic duration with a
    # positive floor, independently of text or mora.
    weights = np.clip(durations / median, 0.25, 1.0)
    # A bounded, data-relative ruler range prevents arbitrarily tiny grids. The
    # complexity cost below chooses simpler integer patterns when fit is similar.
    lo, hi = max(0.015, median / 5), max(median * 2, 0.03)
    seeds = [float(d / n) for d in durations for n in range(1, 9) if lo <= d / n <= hi]
    seeds += [median]
    seeds = sorted({round(s, 6) for s in seeds})

    def basic_cost(tick):
        n = np.clip(np.round(durations / tick), 1, 64)
        for i, value in manual.items():
            n[i] = value
        fit = weights * np.log(n * tick / durations) ** 2
        complexity = complexity_weight * np.log(n) ** 2
        text = [0.10 * math.log(n[i] / c) ** 2 if c else 0 for i, c in enumerate(prior)]
        return float(np.mean(fit + complexity + text))

    # Keep distinct scales, including half/double interpretations, without
    # forcing their presence in the UI as different musical candidates.
    ticks = []
    for tick in sorted(seeds, key=basic_cost):
        if not any(abs(math.log(tick / old)) < 0.035 for old in ticks):
            ticks.append(tick)
        if len(ticks) == 12:
            break

    def solve(tick):
        # state: cost, slots, prior interval log-ratio, phrase cumulative cells,
        # phrase measured seconds. All transitions change integer occupancy.
        states = [(0.0, [], 0.0, 0, 0.0)]
        phrase_steps = 0
        for i, duration in enumerate(durations):
            reset = (
                i == 0
                or units[i].get("phrase", 0) != units[i - 1].get("phrase", 0)
                or measurements["rest_seconds"][i - 1] > 0
            )
            phrase_steps = 1 if reset else phrase_steps + 1
            ideal = duration / tick
            choices = (
                [manual[i]]
                if i in manual
                else sorted({1, *[max(1, min(64, round(ideal) + j)) for j in (-2, -1, 0, 1, 2)]})
            )
            next_states = {}
            for cost, path, previous, cells, elapsed in states:
                if reset:
                    cells, elapsed = 0, 0.0
                for n in choices:
                    ratio = math.log(n * tick / duration)
                    fit = weights[i] * ratio**2
                    continuity = (
                        0 if reset else 0.25 * min(weights[i], weights[i - 1]) * (ratio - previous) ** 2
                    )
                    drift = 0.055 * ((cells + n - (elapsed + duration) / tick) / math.sqrt(phrase_steps)) ** 2
                    complexity = complexity_weight * math.log(n) ** 2
                    text = 0.10 * math.log(n / prior[i]) ** 2 if prior[i] else 0
                    state = (
                        cost + fit + continuity + drift + complexity + text,
                        path + [n],
                        ratio,
                        cells + n,
                        elapsed + duration,
                    )
                    key = (cells + n, n)
                    if key not in next_states or state[0] < next_states[key][0]:
                        next_states[key] = state
            states = sorted(next_states.values(), key=lambda x: x[0])[:48]
        best = states[0]
        return {
            "slots": best[1],
            "cost": best[0] / len(units),
            "source_tick_seconds": tick,
        }

    candidates = [solve(t) for t in ticks]
    # Refine the ruler for promising patterns; this moves no measured boundaries.
    for old in sorted(candidates, key=lambda x: x["cost"])[:3]:
        tick = float(np.exp(np.average(np.log(durations / np.array(old["slots"])), weights=weights)))
        if lo <= tick <= hi:
            candidates.append(solve(tick))
    candidates.sort(key=lambda x: x["cost"])
    best = candidates[0]
    ratios = np.array(best["slots"]) * best["source_tick_seconds"] / durations
    best["costs"] = {
        "mean_log_interval_error": float(np.mean(np.log(ratios) ** 2)),
        "complexity": float(np.mean(np.log(best["slots"]) ** 2)),
        "objective": best["cost"],
        "mora_prior_weight": 0.10 if any(prior) else 0.0,
    }
    alternatives, seen = [], set()
    for c in candidates:
        pattern = tuple(c["slots"])
        if pattern not in seen:
            alternatives.append({k: c[k] for k in ("slots", "cost", "source_tick_seconds")})
            seen.add(pattern)
        if len(alternatives) == 3:
            break
    best["alternatives"] = alternatives
    best["short_interval_unit_indices"] = np.flatnonzero(weights < 0.5).tolist()
    best["interval_weights"] = weights.tolist()
    best["message"] = "以实测间隔联合分配整数格距；" + (
        "mora 仅作软约束"
        if any(prior)
        else "mora 对应不足，校准项未启用；使用独立声学量化"
        if priors is not None
        else "不使用 mora 或 mora 时长；短句同样直接量化"
    )
    return best
