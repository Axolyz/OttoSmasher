"""Ordered rhythm-unit queries. Retrieval never infers audio or registers samples."""

import json
import time
from itertools import pairwise
from typing import Literal

import numpy as np
from pydantic import BaseModel, ConfigDict, Field, model_validator

from .workspace import identity

VERSION = "speech-units-5"


def canonical_consonant(label):
    # Shared Japanese notation; retain IPA/model spelling separately in evidence.
    value = label.replace("ː", "").replace("̥", "")
    aliases = {
        "ɾ": "r",
        "ɹ": "r",
        "ɕ": "sh",
        "ʃ": "sh",
        "ʑ": "j",
        "dʑ": "j",
        "dʒ": "j",
        "tɕ": "ch",
        "tʃ": "ch",
        "ts": "ts",
        "ɸ": "f",
        "ç": "hy",
        "ɲ": "ny",
        "ʔ": "cl",
        "q": "cl",
        "t͡ɕ": "ch",
        "d͡ʑ": "j",
        "t͡s": "ts",
    }
    return aliases.get(value, value.replace("ʲ", "y"))


class UnitCondition(BaseModel):
    model_config = ConfigDict(extra="forbid")
    phone: str | None = None
    consonants: list[str] | None = None  # None: any; []: no onset consonant
    pitch_class: int | None = Field(default=None, ge=0, le=11)
    octave: int | None = Field(default=None, ge=-1, le=9)
    tolerance_cents: float = Field(default=50, ge=0, le=600)
    stability_cents: float | None = Field(default=None, ge=0)
    min_coverage: float = Field(default=0.5, ge=0, le=1)
    duration_min: float | None = Field(default=None, ge=0)
    duration_max: float | None = Field(default=None, ge=0)
    duration_measure: Literal["sustain", "span"] = "sustain"
    speaker: str | None = None
    pitch_trend: Literal["up", "down"] | None = None
    pitch_trend_min: float = Field(default=1, ge=0)
    pitch_register: Literal["high", "low"] | None = None
    pitch_register_min: float = Field(default=2, ge=0)
    strength_min: float | None = Field(default=None, ge=0, le=1)
    energy_relative_min_db: float | None = None

    @model_validator(mode="after")
    def valid(self):
        if self.consonants is not None:
            self.consonants = [canonical_consonant(x) for x in self.consonants]
        if self.phone and self.phone not in ("a", "i", "u", "e", "o"):
            raise ValueError("元音必须为 a/i/u/e/o")
        if (
            self.duration_min is not None
            and self.duration_max is not None
            and self.duration_min > self.duration_max
        ):
            raise ValueError("时长下限超过上限")
        return self


class SpeechQuery(BaseModel):
    model_config = ConfigDict(extra="forbid")
    rhythm_policy: Literal["none", "required", "rank"] = "none"

    @model_validator(mode="before")
    @classmethod
    def migrate_mode(cls, value):
        value = dict(value)
        old = value.pop("mode", None)
        if old is not None and "rhythm_policy" not in value:
            value["rhythm_policy"] = "required" if old == "rhythm" else "none"
        if value.get("rhythm"):
            value["rhythm"] = dict(value["rhythm"])
            value["rhythm"].pop("slowdown_aversion", None)
        return value

    scope: dict = Field(default_factory=dict)
    units: list[UnitCondition] = Field(min_length=1, max_length=64)
    boundary: Literal["anywhere", "start", "end", "both"] = "anywhere"
    boundary_basis: Literal["phrase", "sample"] = "phrase"
    cross_pauses: bool = False
    max_gap: float | None = Field(default=None, ge=0)
    rhythm: dict | None = None
    limit: int = Field(default=100, ge=1, le=500)


def unit_metrics(record):
    units = record["view"]["units"]
    frames = record.get("frames") or {}
    times = np.asarray(frames.get("times", []))
    f0 = np.asarray(frames.get("f0_hz", []))
    voiced = np.asarray(frames.get("voiced", []), dtype=bool)
    confidence = np.asarray(frames.get("confidence", []))
    good = (
        voiced & (f0 > 0) & (confidence >= 0.5)
        if len(confidence) == len(times)
        else np.zeros(len(times), dtype=bool)
    )
    phones = record["analysis"].get("phones", [])
    output = []
    for i, u in enumerate(units):
        f = dict(record.get("features", [{}] * len(units))[i])
        start, end = u["time"], u["end"]
        mask = (times >= start) & (times < end)
        values = 69 + 12 * np.log2(f0[mask & good] / 440) if len(times) else np.array([])
        # Unit members retain canonical labels from the active backend's grouping.
        members = u.get("members") or []
        labels = [str(p.get("phone", p.get("label", ""))) for p in members]
        if not labels:
            labels = [p["label"] for p in phones if p["start"] < end and p["end"] > start]
        from .rhythm_units import SILENCE, normalize_phone

        indices = [m.get("phone_index") for m in members if isinstance(m.get("phone_index"), int)]
        first_phone = (
            min(indices) if indices else next((j for j, p in enumerate(phones) if p["end"] > start), 0)
        )
        onset = []
        onset_start = start
        for p in reversed(phones[:first_phone]):
            label = normalize_phone(p["label"])
            if label in SILENCE | {"AP", "spn", "N"} or label.lower() in ("a", "i", "u", "e", "o"):
                break
            onset.insert(0, canonical_consonant(label))
            onset_start = p["start"]
        f.update(
            strength=u.get("strength"),
            pitch_midi=float(np.median(values)) if len(values) >= 3 else None,
            stability_cents=float(np.diff(np.percentile(values, [10, 90]))[0] * 100)
            if len(values) >= 3
            else None,
            pitch_coverage=float(np.count_nonzero(mask & good) / np.count_nonzero(mask))
            if mask.any()
            else None,
            consonants=onset,
            raw_labels=[
                p.get("raw_label", p.get("label"))
                for p in phones
                if p["start"] < end and p["end"] > onset_start
            ],
            span_seconds=end - start,
            sustain_seconds=max(0, min(end, f["sustain_end"]) - start)
            if f.get("sustain_end") is not None
            else None,
        )
        output.append(
            {
                "id": identity(record["signature"], i, start, end),
                "index": i,
                "start": onset_start,
                "anchor": start,
                "end": end,
                "phrase": u.get("phrase", 0),
                "measurements": f,
            }
        )
    return output


def satisfies(unit, condition):
    from .sound_features import satisfies as existing

    f = unit["measurements"]
    if not existing(f, condition):
        return None
    if condition.strength_min is not None and (
        f.get("strength") is None or f["strength"] < condition.strength_min
    ):
        return None
    if condition.consonants is not None and f.get("consonants") != condition.consonants:
        return None
    d = f.get("sustain_seconds" if condition.duration_measure == "sustain" else "span_seconds")
    if condition.duration_min is not None and (d is None or d < condition.duration_min):
        return None
    if condition.duration_max is not None and (d is None or d > condition.duration_max):
        return None
    needs_pitch = condition.pitch_class is not None or condition.stability_cents is not None
    if needs_pitch and (
        f.get("pitch_coverage") is None
        or f["pitch_coverage"] < condition.min_coverage
        or f.get("pitch_midi") is None
    ):
        return None
    score, deviation = 0.0, None
    if condition.pitch_class is not None:
        target = (
            condition.pitch_class + 12 * (condition.octave + 1)
            if condition.octave is not None
            else condition.pitch_class
        )
        deviation = (
            (f["pitch_midi"] - target) * 100
            if condition.octave is not None
            else ((f["pitch_midi"] - target + 6) % 12 - 6) * 100
        )
        if abs(deviation) > condition.tolerance_cents + 1e-8:
            return None
        score += abs(deviation) / max(1, condition.tolerance_cents)
    if condition.stability_cents is not None:
        if f.get("stability_cents") is None or f["stability_cents"] > condition.stability_cents:
            return None
        score += f["stability_cents"] / max(1, condition.stability_cents)
    return {
        **f,
        "pitch_deviation_cents": deviation,
        "score": score,
        "requested": condition.model_dump(exclude_none=True),
    }


def match_units(units, query):
    n = len(query.units)
    hits = []
    # Adjacency is fixed here before inspecting any acoustic/linguistic conditions.
    for first in range(len(units) - n + 1):
        chosen = units[first : first + n]
        last = first + n - 1
        if not query.cross_pauses and any(a["phrase"] != b["phrase"] for a, b in pairwise(chosen)):
            continue
        if query.max_gap is not None and any(
            b["start"] - a["end"] > query.max_gap for a, b in pairwise(chosen)
        ):
            continue
        at_start = first == 0 or (
            query.boundary_basis == "phrase" and units[first - 1]["phrase"] != chosen[0]["phrase"]
        )
        at_end = last == len(units) - 1 or (
            query.boundary_basis == "phrase" and units[last + 1]["phrase"] != chosen[-1]["phrase"]
        )
        if query.boundary in ("start", "both") and not at_start:
            continue
        if query.boundary in ("end", "both") and not at_end:
            continue
        evidence = [satisfies(u, c) for u, c in zip(chosen, query.units)]
        if any(e is None for e in evidence):
            continue
        hits.append(
            {
                "unit_indices": [u["index"] for u in chosen],
                "unit_ids": [u["id"] for u in chosen],
                "start": chosen[0]["start"],
                "end": chosen[-1]["end"],
                "score": sum(e["score"] for e in evidence),
                "mapping": [
                    {"query_index": i, "unit_id": u["id"], "unit_index": u["index"], "measurements": e}
                    for i, (u, e) in enumerate(zip(chosen, evidence))
                ],
            }
        )
    return hits


def hit_record(mid, record, hit, mode="sequence", plan_id=None):
    result = {
        **hit,
        "material_id": mid,
        "mode": mode,
        "backend": record["backend"],
        "revision": record["signature"],
        "audio_identity": identity(record["asset"]),
        "analysis_version": record["analysis"]["version"],
        "plan_id": plan_id,
    }
    result["id"] = identity(result)
    return result


def rhythm_evidence(record, hit, rhythm):
    """Compare the same adjacent units in explicitly selected whole/phrase scopes."""
    wanted = [record["view"]["units"][i]["time"] for i in hit["unit_indices"]]
    variants = [record, *record.get("entries", [])]
    results = []
    for variant in variants:
        kind = variant.get("scope", {}).get("kind", "whole")
        scope = rhythm.get("scope", "both")
        if scope == "whole" and kind != "whole" or scope == "segments" and kind != "segment":
            continue
        local = []
        for t in wanted:
            found = next(
                (i for i, u in enumerate(variant["view"]["units"]) if abs(u["time"] - t) < 1e-6), None
            )
            if found is None:
                break
            local.append(found)
        if len(local) != len(wanted) or local != list(range(local[0], local[-1] + 1)):
            continue
        evidence = _rhythm_evidence(
            {**variant, "strategy": record.get("strategy", "acoustic")},
            {**hit, "unit_indices": local},
            rhythm,
        )
        if evidence:
            evidence["scope"] = variant.get("scope", {"kind": "whole"})
            results.append(evidence)
    return min(results, key=lambda m: m["mean_deviation"]) if results else None


def _rhythm_evidence(record, hit, rhythm):
    """Measure the fixed adjacent correspondence; never force source into query rhythm."""
    from .rhythm_index import prototype
    from .sample_rhythm import candidates

    notes = rhythm["notes"]
    indices = hit["unit_indices"]
    desired = np.asarray([n["start_beats"] for n in notes], dtype=float)
    desired_ends = np.asarray([n["end_beats"] for n in notes], dtype=float)
    strategy = record.get("strategy", "acoustic")
    if strategy not in record["compiled"]["routes"]:
        return None
    bpm = rhythm.get("bpm")
    options = candidates(record, bpm, strategy)[0] if bpm else [{"density": 1}]
    measured = []
    for option in options:
        if rhythm.get("speed_filter") and bpm:
            multiplier = 1 / option["speech_playback_speed"]
            if not rhythm.get("factor_min", 0.85) <= multiplier <= rhythm.get("factor_max", 1.18):
                continue
        pattern = prototype(record, strategy, option["density"])
        plan = pattern["plan"]
        rest_adjustments = []
        if rhythm.get("adjust_pauses") and record.get("entries"):
            from .quantized_match import match_pattern
            from .rhythm_index import compose_pattern

            combined = compose_pattern(
                {"cue": record["cue"], "entries": [record, *record["entries"]]}, strategy, option["density"]
            )
            if combined:
                # Existing bounded rest solver, with fixed contiguous correspondence.
                params = {
                    **rhythm,
                    "bpm": bpm or 120,
                    "strategy": strategy,
                    "densities": [option["density"]],
                    "required_unit_indices": indices,
                    "speed_filter": False,
                }
                matched = match_pattern(combined, params)
                if matched:
                    plan = {
                        **combined["plan"],
                        "unit_targets": matched["shifted_unit_targets"],
                        "end_target": matched["shifted_end_target"],
                    }
                    rest_adjustments = matched.get("rest_adjustments", [])
        points = plan["unit_targets"] + [plan["end_target"]]
        source = np.asarray([u["source_seconds"] for u in points])
        target = np.asarray([u["target_beat"] for u in points])
        anchors = np.asarray([record["view"]["units"][i]["time"] for i in indices])
        ends = np.asarray([record["view"]["units"][i]["end"] for i in indices])
        sustained = np.asarray(
            [
                record.get("features", [{}] * len(record["view"]["units"]))[i].get("sustain_end", np.nan)
                for i in indices
            ],
            dtype=float,
        )
        all_positions = np.interp([u["time"] for u in record["view"]["units"]], source, target)
        actual = np.interp(anchors, source, target)
        actual_ends = np.interp(ends, source, target)
        sustain_ends = np.interp(sustained, source, target)
        durations = actual_ends - actual
        duration_ok = all(
            (n.get("duration_min_beats") is None or d >= n["duration_min_beats"])
            and (n.get("duration_max_beats") is None or d <= n["duration_max_beats"])
            for n, d in zip(notes, durations)
        )
        if not duration_ok:
            continue
        goal, goal_ends = desired.copy(), desired_ends.copy()
        if bpm is None:
            width = max(float(actual_ends[-1] - actual[0]), 1e-8)
            goal_width = max(float(goal_ends[-1] - goal[0]), 1e-8)
            all_positions = (all_positions - actual[0]) / width
            sustain_ends = (sustain_ends - actual[0]) / width
            actual_ends = (actual_ends - actual[0]) / width
            actual = (actual - actual[0]) / width
            goal_ends = (goal_ends - goal[0]) / goal_width
            goal = (goal - goal[0]) / goal_width
        else:
            shift = float(np.median(goal - actual))
            all_positions += shift
            sustain_ends += shift
            actual += shift
            actual_ends += shift
        deviations = abs(actual - goal)
        sustain_shortfalls = np.asarray(
            [
                max(0, b - a) if note.get("sustain_to_end") else 0
                for a, b, note in zip(sustain_ends, goal_ends, notes)
            ]
        )
        tolerance = float(rhythm.get("tolerance_beats", 0.1))
        if bpm is None:
            tolerance /= max(float(desired_ends[-1] - desired[0]), 1e-8)
        if any(note.get("sustain_to_end") and not np.isfinite(t) for note, t in zip(notes, sustain_ends)):
            continue
        # A note occupies a half-open interval: no additional onset may live inside it.
        collisions = []
        for j, (lo, hi) in enumerate(zip(goal, goal_ends)):
            collisions.append(
                [i for i, t in enumerate(all_positions) if i != indices[j] and lo <= t < hi - 1e-9]
            )
        combined = np.maximum(deviations, sustain_shortfalls)
        occupancy_cost = sum(len(c) for c in collisions)
        measured.append(
            {
                "strict": bool(np.max(combined) <= tolerance + 1e-8 and not occupancy_cost),
                "basis": "beats" if bpm else "normalized_shape",
                "mean_deviation": float(np.mean(combined)) + occupancy_cost,
                "rest_adjustments": rest_adjustments,
                "occupancy_collisions": collisions,
                "mapped_durations_beats": durations.tolist(),
                "max_deviation": float(np.max(combined)),
                "onset_deviations": deviations.tolist(),
                "sustain_shortfalls": sustain_shortfalls.tolist(),
                "tolerance": tolerance,
                "candidate": option,
                "actual": actual.tolist(),
                "target": goal.tolist(),
            }
        )
    return min(measured, key=lambda m: m["mean_deviation"]) if measured else None


def query(db, payload):
    from .sample_analysis import ready
    from .sample_rhythm import with_speakers
    from .sample_scope import ids
    from .ui_catalog import effective_all

    begun = time.perf_counter()
    q = SpeechQuery.model_validate(payload)
    eligible = ids(db, q.scope)
    if q.rhythm_policy != "none":
        if not q.rhythm or len(q.rhythm.get("notes", [])) != len(q.units):
            raise ValueError("节奏布局必须和音块一一对应")
        from .rhythm import RhythmQuery

        checked = RhythmQuery.model_validate({**q.rhythm, "bpm": q.rhythm.get("bpm") or 120})
        if [n.start_beats for n in checked.notes] != sorted(n.start_beats for n in checked.notes):
            raise ValueError("音块和节奏布局顺序不一致")
    results, errors = [], []
    legacy = None
    if q.rhythm_policy == "required" and q.rhythm and q.rhythm.get("bpm") is not None:
        from .sample_rhythm import search

        if not q.rhythm:
            raise ValueError("缺少节奏布局")
        legacy = search(
            db,
            {
                **q.scope,
                **q.rhythm,
                "boundary": q.boundary if q.boundary_basis == "sample" else "anywhere",
                "limit": 100,
            },
            all_matches=True,
        )
    legacy_by_sample = {}
    for h in (legacy or {}).get("results", []):
        legacy_by_sample.setdefault(h["material_id"], []).append(h)
    for mid in eligible:
        if legacy is not None and mid not in legacy_by_sample:
            continue
        try:
            record = ready(db, mid)
            key = identity(VERSION, record["signature"])
            db.execute(
                "CREATE TABLE IF NOT EXISTS speech_unit_indices(material_id TEXT, revision TEXT, payload TEXT, PRIMARY KEY(material_id,revision))"
            )
            cached = db.execute(
                "SELECT payload FROM speech_unit_indices WHERE material_id=? AND revision=?", (mid, key)
            ).fetchone()
            if cached:
                units = json.loads(cached[0])
            else:
                units = unit_metrics(record)
                db.execute("INSERT INTO speech_unit_indices VALUES(?,?,?)", (mid, key, json.dumps(units)))
            speakers = with_speakers(db, record, record["view"]["units"])
            for u, s in zip(units, speakers):
                u["measurements"].update({k: v for k, v in s["features"].items() if k.startswith("speaker")})
            record["strategy"] = db.execute(
                "SELECT active_quantization_strategy FROM materials WHERE id=?", (mid,)
            ).fetchone()[0]
            hits = []
            for hit in match_units(units, q):
                if legacy is None:
                    if q.rhythm_policy != "none":
                        evidence = rhythm_evidence(record, hit, q.rhythm)
                        if evidence is None or q.rhythm_policy == "required" and not evidence["strict"]:
                            continue
                        hit = {
                            **hit,
                            "rhythm_evidence": evidence,
                            "score": hit["score"] + evidence["mean_deviation"],
                            "match_kind": "strict" if evidence["strict"] else "approximate",
                        }
                    hits.append(hit_record(mid, record, hit, q.rhythm_policy))
                else:
                    for old in legacy_by_sample[mid]:
                        # Legacy indices are local to its recorded scope. Map through saved plan.
                        from .sample_rhythm import load

                        _record, pp = load(db, mid, old["plan_id"])
                        matched = [t for t in pp["unit_targets"] if t.get("role") == "matched"]
                        times = [t["source_seconds"] for t in matched]
                        selected_times = [record["view"]["units"][i]["time"] for i in hit["unit_indices"]]
                        if len(times) == len(selected_times) and all(
                            abs(a - b) < 1e-5 for a, b in zip(times, selected_times)
                        ):
                            hits.append(
                                hit_record(
                                    mid,
                                    record,
                                    {**hit, "score": old.get("cost", hit["score"])},
                                    "rhythm",
                                    old["plan_id"],
                                )
                            )
            if not hits:
                continue
            distinct = {}
            for h in sorted(hits, key=lambda x: x["score"]):
                distinct.setdefault(tuple(h["unit_indices"]), h)
            hits = list(distinct.values())
            row = dict(
                db.execute(
                    "SELECT id,title,source_id,start,end,starred,nature FROM materials WHERE id=?", (mid,)
                ).fetchone()
            )
            hits.sort(key=lambda h: (h["score"], h["start"]))
            results.append(
                {
                    **row,
                    "material_id": mid,
                    "sample_title": row["title"],
                    "hits": hits,
                    "hit_count": len(hits),
                    "score": hits[0]["score"],
                }
            )
        except (ValueError, KeyError) as e:
            errors.append({"material_id": mid, "reason": str(e)})
    results.sort(key=lambda r: (r["score"], r["material_id"]))
    results = results[: q.limit]
    tags = effective_all(db, [r["id"] for r in results])
    for r in results:
        r["tags"] = tags.get(r["id"], [])
    db.commit()
    return {
        "version": "speech-query-v2",
        "results": results,
        "query": q.model_dump(),
        "elapsed_ms": round((time.perf_counter() - begun) * 1000, 2),
        "index_status": {"errors": errors},
        "hit_count": sum(r["hit_count"] for r in results),
    }


def validate_hit(db, hit):
    from .sample_analysis import ready

    r = ready(db, hit["material_id"])
    if (
        hit["revision"] != r["signature"]
        or hit["audio_identity"] != identity(r["asset"])
        or hit["backend"] != r["backend"]
    ):
        raise ValueError("命中已失效，请重新查询")
    units = unit_metrics(r)
    indices = hit["unit_indices"]
    if (
        not indices
        or indices != list(range(indices[0], indices[-1] + 1))
        or indices[0] < 0
        or indices[-1] >= len(units)
    ):
        raise ValueError("无效命中音块")
    if [units[i]["id"] for i in indices] != hit["unit_ids"]:
        raise ValueError("命中音块已改变")
    a, b = units[indices[0]]["start"], units[indices[-1]]["end"]
    if abs(a - hit["start"]) > 1e-8 or abs(b - hit["end"]) > 1e-8:
        raise ValueError("命中范围不匹配")
    return r
