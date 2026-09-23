"""Persistent source rhythm skeletons; queries never re-estimate their timing.

The index contains no audio. Its dependencies include model output, grouping,
scope settings and the implementations that derive integer cell occupancy.
"""

from __future__ import annotations

import copy
import hashlib
import json
import math
import time
from functools import lru_cache
from pathlib import Path

import numpy as np

from . import workspace
from .beat_reference import DENSITIES, STRATEGIES, compile_reference, generate_references
from .catalog import normalize, reading_text
from .rhythm_units import get_rhythm_view
from .workspace import get_cue, get_speech_analysis, identity, write_json

PLAN_VERSION = "indexed-reference-v2"


@lru_cache(maxsize=1)
def index_version():
    here = Path(__file__).parent
    files = [
        "rhythm_index.py",
        "rhythm_scopes.py",
        "beat_reference.py",
        "rhythm_allocation.py",
        "mora_features.py",
        "rhythm_units.py",
    ]
    return identity(
        "rhythm-index-v1", {f: hashlib.sha256((here / f).read_bytes()).hexdigest() for f in files}
    )


def segment_settings(db, cue_id, kind, version):
    r = db.execute(
        "SELECT payload FROM segment_settings WHERE cue_id=? AND kind=? AND analysis_version=?",
        (cue_id, kind, version),
    ).fetchone()
    return json.loads(r[0]) if r else {}


def _rows(db, kind, cue_id=None):
    from .source_regions import ensure, sql_allowed
    ensure(db)
    sql = """SELECT c.*,s.title,a.version AS analysis_version,a.created,
        e.split_before,e.updated AS edited,cs.payload AS settings,ss.payload AS segments,
        ix.signature AS cached_signature,ix.payload AS indexed
        FROM cues c JOIN sources s ON s.id=c.source_id
        JOIN analyses a ON a.cue_id=c.id AND a.kind=?
        LEFT JOIN rhythm_edits e ON e.cue_id=c.id AND e.kind=a.kind AND e.analysis_version=a.version
        LEFT JOIN cue_settings cs ON cs.cue_id=c.id AND cs.kind=a.kind AND cs.analysis_id=a.version
        LEFT JOIN segment_settings ss ON ss.cue_id=c.id AND ss.kind=a.kind AND ss.analysis_version=a.version
        LEFT JOIN rhythm_index ix ON ix.cue_id=c.id AND ix.kind=a.kind
        WHERE a.created=(SELECT max(b.created) FROM analyses b WHERE b.cue_id=c.id AND b.kind=a.kind)
        AND json_extract(a.payload,'$.input_variant')='vocals'"""
    if cue_id is None:
        sql += " AND " + sql_allowed("c")
    params = [kind]
    if cue_id:
        sql += " AND c.id=?"
        params.append(cue_id)
    return db.execute(sql, params).fetchall()


def _signature(row, db=None):
    from .ui_catalog import settings
    penalty = settings(db)["large_number_penalty"] if db is not None else 1.0
    return identity(
        index_version(),
        penalty,
        row["id"],
        row["analysis_version"],
        row["created"],
        row["split_before"],
        row["edited"],
        row["settings"],
        row["segments"],
    )


@lru_cache(maxsize=512)
def _decode(payload):
    # Callers treat cached source records as immutable. All plan edits copy first.
    return json.loads(payload)


def speech_bounds(entry):
    from .rhythm_units import SILENCE, normalize_phone

    analysis = entry["analysis"]
    phones = [
        p
        for p in analysis.get("phones", [])
        if normalize_phone(p["label"]) not in SILENCE | {"AP", "[BOS]", "[EOS]"}
    ]
    first = entry["view"]["units"][0]["time"]
    start = max(analysis["window_start"], min(first, min((p["start"] for p in phones), default=first)))
    return [start, entry["compiled"]["measured"]["end"]]


def prototype(entry, strategy, density):
    """Small search representation, numerically identical to the free reference."""
    c = entry["compiled"]
    route = c["routes"].get(strategy)
    if route is None:
        return None
    units, measured = entry["view"]["units"], c["measured"]
    slots = route["slots"]
    tick = measured["speech_seconds"] / sum(slots)
    rests = [max(0, round(s / tick)) for s in measured["rest_seconds"]]
    beats = [0.0]
    for n, r in zip(slots[:-1], rests[:-1]):
        beats.append(beats[-1] + (n + r) / density)
    end = beats[-1] + (slots[-1] + rests[-1]) / density
    ratio = sum(slots) / density * 0.5 / measured["speech_seconds"]
    local = (np.diff(beats + [end]) * 0.5 / np.diff([u["time"] for u in units] + [measured["end"]])).tolist()
    p = {
        "speech_bounds": speech_bounds(entry),
        "density": density,
        "strategy": strategy,
        "beat_seconds": 0.5,
        "grid_beats": 1 / density,
        "duration_multiplier": ratio,
        "local_duration_ratios": local,
        "pauses": entry["view"]["pauses"],
        "unit_targets": [
            {"unit_index": i, "source_seconds": u["time"], "target_beat": b, "label": u.get("label", "")}
            for i, (u, b) in enumerate(zip(units, beats))
        ],
        "end_target": {"source_seconds": measured["end"], "target_beat": end},
        "slots": [
            {**s, "effective_slots": n, "rest_slots_after": r}
            for s, n, r in zip(c["reference"]["slots"], slots, rests)
        ],
    }
    return {
        "pattern_id": identity(entry["scope"]["scope_id"], index_version(), strategy, slots, rests),
        "scope": entry["scope"],
        "units": units,
        "plan": p,
    }


def _build_cue(db, row, kind):
    from .rhythm_scopes import list_scopes, scope_context

    signature = _signature(row, db)
    cue = get_cue(db, row["id"])
    analysis = get_speech_analysis(db, row["id"], kind)
    view = get_rhythm_view(db, row["id"], kind, analysis)
    record = {"cue": cue, "signature": signature, "entries": [], "errors": []}
    try:
        if not view or not view["units"]:
            raise ValueError("没有有效节奏起点")
        settings = json.loads(row["settings"] or "{}")
        scopes = list_scopes(cue, analysis, view, json.loads(row["segments"] or "{}"))
        for scope in scopes:
            try:
                a, v = scope_context(cue, analysis, view, scope)
                indices = scope.get("parent_unit_indices", list(range(len(v["units"]))))
                overrides = {
                    str(i): settings["slots"][str(p)]
                    for i, p in enumerate(indices)
                    if str(p) in settings.get("slots", {})
                }
                from .ui_catalog import settings as ui_settings
                compiled = compile_reference(cue, a, v, overrides, large_number_penalty=ui_settings(db)["large_number_penalty"])
                entry = {
                    "scope": scope,
                    "analysis": a,
                    "view": v,
                    "compiled": compiled,
                    "overrides": overrides,
                    "signature": signature,
                }
                entry["patterns"] = [
                    prototype(entry, s, d) for s in STRATEGIES for d in DENSITIES if s in compiled["routes"]
                ]
                record["entries"].append(entry)
            except ValueError as e:
                record["errors"].append({"scope_id": scope["scope_id"], "reason": str(e)})
        record["compositions"] = [
            p for s in STRATEGIES for d in DENSITIES if (p := compose_pattern(record, s, d)) is not None
        ]
    except ValueError as e:
        record["errors"].append({"scope_id": None, "reason": str(e)})
    payload = json.dumps(record, ensure_ascii=False, allow_nan=False, separators=(",", ":"))
    db.execute(
        "INSERT OR REPLACE INTO rhythm_index VALUES(?,?,?,?,?)",
        (row["id"], kind, signature, payload, time.time()),
    )
    db.commit()
    return _decode(payload)


def ensure_record(db, row, kind):
    if row["cached_signature"] == _signature(row, db):
        return _decode(row["indexed"]), False
    return _build_cue(db, row, kind), True


def rebuild_index(db, kind, progress=None):
    started = time.perf_counter()
    summary = {"analysis_kind": kind, "cues": 0, "rebuilt": 0, "scopes": 0, "patterns": 0, "errors": []}
    for row in _rows(db, kind):
        record, rebuilt = ensure_record(db, row, kind)
        summary["cues"] += 1
        summary["rebuilt"] += rebuilt
        summary["scopes"] += len(record["entries"])
        summary["patterns"] += sum(len(e["patterns"]) for e in record["entries"])
        summary["errors"] += [{"cue_id": row["id"], **e} for e in record["errors"]]
        if progress:
            progress(summary)
    return {
        **summary,
        "elapsed_ms": round((time.perf_counter() - started) * 1000, 2),
        "version": index_version(),
    }


def entry_for(db, cue_id, kind, scope_id=None):
    rows = _rows(db, kind, cue_id)
    if not rows:
        raise ValueError("当前模型没有可用的人声分析")
    record, _ = ensure_record(db, rows[0], kind)
    entry = (
        next((e for e in record["entries"] if e["scope"]["scope_id"] == scope_id), None)
        if scope_id
        else next((e for e in record["entries"] if e["scope"]["kind"] == "whole"), None)
    )
    if entry is None:
        reasons = "; ".join(e["reason"] for e in record["errors"])
        raise ValueError("Scope changed or unavailable; 语段已改变或没有可用节奏，请重新选择。" + reasons)
    return record, entry


def save_plan(plan, entry):
    plan = copy.deepcopy(plan)
    plan.pop("plan_id", None)
    plan.update(version=PLAN_VERSION, scope=entry["scope"], index_signature=entry["signature"])
    plan["retain_query_canvas"] = False
    plan["speech_bounds"] = speech_bounds(entry)
    from .time_mapping import VERSION as TIMING_VERSION

    plan["timing_version"] = TIMING_VERSION
    plan["plan_id"] = identity(PLAN_VERSION, plan)
    write_json(workspace.DATA / "quantization-plans" / (plan["plan_id"] + ".json"), plan)
    return plan


def reference_plans(record, entry, bpm=120, strategy="acoustic", density=None, auto_long_vowels=False):
    compiled = entry["compiled"] if not auto_long_vowels else None
    result = generate_references(
        record["cue"],
        entry["analysis"],
        entry["view"],
        bpm,
        strategy,
        density,
        overrides=entry["overrides"],
        auto_long_vowels=auto_long_vowels,
        compiled=compiled,
        persist=False,
    )
    result["plans"] = [save_plan(p, entry) for p in result["plans"]]
    result["scope"] = entry["scope"]
    return result


def compose_pattern(record, strategy, density, rest_overrides=None):
    """Connect independent segments; only rests between their fixed tails change."""
    segments = sorted(
        (e for e in record["entries"] if e["scope"]["kind"] == "segment"), key=lambda e: e["scope"]["ordinal"]
    )
    whole = next((e for e in record["entries"] if e["scope"]["kind"] == "whole"), None)
    if not whole or len(segments) < 2:
        return None
    parts = [prototype(e, strategy, density) for e in segments]
    if not all(parts):
        return None
    for key, value in (rest_overrides or {}).items():
        if (
            not key.isdigit()
            or not 0 <= int(key) < len(parts) - 1
            or isinstance(value, bool)
            or not isinstance(value, int)
            or value < 1
        ):
            raise ValueError("连接休止须为正整数，并指向现有语段间隙；尾音控制点之间须保留正时长")
    speech = sum(e["compiled"]["measured"]["speech_seconds"] for e in segments)
    occupied = sum(sum(s["effective_slots"] for s in p["plan"]["slots"]) for p in parts)
    tick = speech / occupied
    targets, slots, controls, links = [], [], [], []
    shift = 0.0
    end = None
    for j, (entry, part) in enumerate(zip(segments, parts)):
        indices = entry["scope"]["parent_unit_indices"]
        pp = part["plan"]
        if j:
            gap = pp["unit_targets"][0]["source_seconds"] - end["source_seconds"]
            if gap <= 0:
                raise ValueError("语段尾音与下一起点重叠，不能独立连接")
            default = max(1, round(gap / tick))
            cells = (rest_overrides or {}).get(str(j - 1), default)
            if cells > max(32, default):
                raise ValueError(f"连接 {j} 的休止应为 1–{max(32, default)} 格")
            links.append(
                {
                    "link_index": j - 1,
                    "after_unit_index": targets[-1]["unit_index"],
                    "next_unit_index": indices[0],
                    "source_start": end["source_seconds"],
                    "source_end": pp["unit_targets"][0]["source_seconds"],
                    "source_gap_seconds": gap,
                    "rest_cells": cells,
                    "default_rest_cells": default,
                    "min_rest_cells": 1,
                    "max_rest_cells": max(32, default),
                    "from_scope_id": segments[j - 1]["scope"]["scope_id"],
                    "to_scope_id": entry["scope"]["scope_id"],
                }
            )
            shift = end["target_beat"] + cells / density
        for parent, target, slot in zip(indices, pp["unit_targets"], pp["slots"]):
            targets.append(
                {
                    **target,
                    "unit_index": parent,
                    "target_beat": target["target_beat"] + shift,
                    "role": "automatic",
                    "query_index": None,
                }
            )
            slots.append(
                {
                    **slot,
                    "unit_index": parent,
                    "basis": "independent_segment",
                    "component_scope_id": entry["scope"]["scope_id"],
                    "comparison_slots": {strategy: slot["effective_slots"]},
                }
            )
        end = {**pp["end_target"], "target_beat": pp["end_target"]["target_beat"] + shift}
        if j < len(parts) - 1:
            controls.append({**end, "after_unit_index": indices[-1], "role": "segment_end"})
    if len(targets) != len(whole["view"]["units"]):
        raise ValueError("语段连接未覆盖父句全部起点")
    source = [u["source_seconds"] for u in targets] + [end["source_seconds"]]
    target = [u["target_beat"] for u in targets] + [end["target_beat"]]
    plan = {
        "composition": True,
        "speech_bounds": speech_bounds(whole),
        "density": density,
        "strategy": strategy,
        "grid_beats": 1 / density,
        "beat_seconds": 0.5,
        "duration_multiplier": occupied / density * 0.5 / speech,
        "slots": slots,
        "unit_targets": targets,
        "end_target": end,
        "control_targets": controls,
        "links": links,
        "pauses": whole["view"]["pauses"],
        "local_duration_ratios": (np.diff(target) * 0.5 / np.diff(source)).tolist(),
        "component_patterns": [
            {"scope_id": e["scope"]["scope_id"], "pattern_id": p["pattern_id"]}
            for e, p in zip(segments, parts)
        ],
    }
    return {
        "pattern_id": identity(index_version(), plan["component_patterns"], strategy, "linked"),
        "scope": whole["scope"],
        "units": whole["view"]["units"],
        "plan": plan,
    }


def composition_plans(
    record, entry, bpm=120, strategy="acoustic", density=None, rest_overrides=None, auto_long_vowels=False
):
    if entry["scope"]["kind"] != "whole":
        raise ValueError("请先选择整句，再连接其相邻语段")
    if auto_long_vowels:
        record = {
            **record,
            "entries": [
                {
                    **e,
                    "compiled": compile_reference(
                        record["cue"], e["analysis"], e["view"], e["overrides"], True, e["compiled"].get("large_number_penalty",1.0)
                    ),
                }
                if e["scope"]["kind"] == "segment"
                else e
                for e in record["entries"]
            ],
        }
    result = reference_plans(record, entry, bpm, strategy, density, auto_long_vowels)
    plans = []
    for base in result["plans"]:
        pattern = compose_pattern(record, strategy, base["density"], rest_overrides)
        if pattern is None:
            continue
        p = copy.deepcopy(base)
        p.update(copy.deepcopy(pattern["plan"]))
        p["beat_seconds"] = 60 / bpm
        scale = p["beat_seconds"] / 0.5
        p["duration_multiplier"] *= scale
        p["local_duration_ratios"] = [r * scale for r in p["local_duration_ratios"]]
        p["min_duration_ratio"], p["max_duration_ratio"] = (
            min(p["local_duration_ratios"]),
            max(p["local_duration_ratios"]),
        )
        p["score"] = abs(math.log(p["duration_multiplier"]))
        a = entry["analysis"]
        p["estimated_duration_seconds"] = (
            p["end_target"]["target_beat"] * p["beat_seconds"]
            + (
                a["window_end"]
                - p["end_target"]["source_seconds"]
                + p["unit_targets"][0]["source_seconds"]
                - a["window_start"]
            )
            * p["duration_multiplier"]
        )
        p["label"] += " · 独立语段连接"
        p["comparison_status"] = "independent_segments"
        p["same_as_strategies"], p["changed_unit_indices"] = [], []
        p["algorithm_evidence"] = {
            "message": "各语段独立推断占格，连接处只修改休止格数",
            "component_patterns": p["component_patterns"],
        }
        p["pattern_id"] = pattern["pattern_id"]
        plans.append(save_plan(p, entry))
    plans.sort(key=lambda p: (p["score"], p["density"]))
    result["plans"] = plans
    if not plans:
        result["message"] = "当前整句没有两个可用的独立语段，或所选算法的语段读音对应不足"
    return result


def materialize_match(record, entry, match, query):
    result = (
        composition_plans(
            record,
            entry,
            query.bpm,
            query.strategy,
            match["density"],
            {str(l["link_index"]): l["rest_cells"] for l in match.get("adjusted_links", [])},
        )
        if match.get("composition")
        else reference_plans(record, entry, query.bpm, query.strategy, match["density"])
    )
    plan = copy.deepcopy(result["plans"][0])
    plan["unit_targets"] = match["shifted_unit_targets"]
    plan["end_target"] = match["shifted_end_target"]
    if match.get("shifted_control_targets") is not None:
        plan["control_targets"] = match["shifted_control_targets"]
    if match.get("composition"):
        plan["links"] = match["adjusted_links"]
    start_seconds = entry["analysis"]["window_start"]
    end_seconds = entry["analysis"]["window_end"]
    factor, beat = plan["duration_multiplier"], plan["beat_seconds"]
    points = plan["unit_targets"]
    first = points[0]["target_beat"] * beat - (points[0]["source_seconds"] - start_seconds) * factor
    last = (
        plan["end_target"]["target_beat"] * beat
        + (end_seconds - plan["end_target"]["source_seconds"]) * factor
    )
    plan["estimated_duration_seconds"] = last - first
    for t in plan["unit_targets"]:
        hits = match["matched_anchor_indices"]
        t["role"] = "matched" if t["unit_index"] in hits else "automatic"
        t["query_index"] = hits.index(t["unit_index"]) if t["unit_index"] in hits else None
    plan["pattern_id"] = match["pattern_id"]
    plan["witness"] = {k: v for k, v in match.items() if not k.startswith("shifted_")}
    plan["witness"]["query"] = query.model_dump()
    plan["retrieval_score_unchanged"] = True
    return save_plan(plan, entry)


def search_index(db, query, cue_id=None):
    from .quantized_match import match_pattern
    from .sound_features import record_features
    from .speakers import labels_for_units

    if query.mode not in {"narabas", "phonetic", "pydomino"}:
        raise ValueError("节奏检索需要选择已有音素分析的模型")
    start = time.perf_counter()
    from .materials import query_ids

    allowed = None
    if query.material_ids is not None or query.collection_id or query.tags:
        ids = set(query_ids(db, collection=query.collection_id, tags=query.tags))
        if query.material_ids is not None:
            ids.intersection_update(query.material_ids)
        allowed = {}
        for r in db.execute(
            "SELECT id,cue_id,scope_id,analysis_kind FROM materials WHERE cue_id IS NOT NULL"
        ):
            if r["id"] in ids and (not r["analysis_kind"] or r["analysis_kind"] == query.mode):
                allowed.setdefault(r["cue_id"], []).append(dict(r))
    found, searched, scopes, rebuilt, errors = [], 0, 0, 0, []
    for row in _rows(db, query.mode, cue_id):
        if allowed is not None and row["id"] not in allowed:
            continue
        if query.source_id and row["source_id"] != query.source_id:
            continue
        if (
            query.text
            and normalize(query.text) not in row["normalized"]
            and reading_text(query.text) not in row["reading"]
        ):
            continue
        record, built = ensure_record(db, row, query.mode)
        rebuilt += built
        searched += 1
        features = record_features(record)
        whole = next((e for e in record["entries"] if e["scope"]["kind"] == "whole"), None)
        roles = labels_for_units(db, record["cue"], whole["view"]["units"]) if whole else []
        features = [{**f, **r} for f, r in zip(features, roles)]
        errors += [{"cue_id": row["id"], **e} for e in record["errors"]]
        for entry in record["entries"]:
            if allowed is not None and not any(
                not m["scope_id"] or m["scope_id"] == entry["scope"]["scope_id"] for m in allowed[row["id"]]
            ):
                continue
            if query.scope == "whole" and entry["scope"]["kind"] != "whole":
                continue
            if query.scope == "segments" and entry["scope"]["kind"] != "segment":
                continue
            scopes += 1
            best = None
            for pattern in entry["patterns"]:
                if (
                    pattern["plan"]["strategy"] != query.strategy
                    or pattern["plan"]["density"] not in query.densities
                ):
                    continue
                indices = entry["scope"].get("parent_unit_indices", list(range(len(pattern["units"]))))
                enriched = {
                    **pattern,
                    "units": [{**u, "features": features[i]} for u, i in zip(pattern["units"], indices)],
                }
                m = match_pattern(enriched, query)
                if m and (best is None or m["cost"] < best["cost"]):
                    best = m
            if query.adjust_pauses and entry["scope"]["kind"] == "whole":
                for pattern in record.get("compositions", []):
                    if (
                        pattern["plan"]["strategy"] != query.strategy
                        or pattern["plan"]["density"] not in query.densities
                    ):
                        continue
                    enriched = {
                        **pattern,
                        "units": [{**u, "features": f} for u, f in zip(pattern["units"], features)],
                    }
                    m = match_pattern(enriched, query)
                    if m and (best is None or m["cost"] < best["cost"]):
                        best = m
            if best:
                found.append((best, record, entry))
    found.sort(
        key=lambda x: (
            x[0]["category"] != "feasible",
            x[0]["cost"],
            x[1]["cue"]["id"],
            x[2]["scope"]["ordinal"],
        )
    )
    results = []
    for match, record, entry in found[: query.limit]:
        plan = materialize_match(record, entry, match, query)
        cue, a, v = record["cue"], entry["analysis"], entry["view"]
        results.append(
            {
                **{k: cue[k] for k in ("source_id", "spoken", "title", "start", "end")},
                "cue_id": cue["id"],
                "parent_cue_id": cue["id"],
                "analysis_kind": query.mode,
                "analysis_version": a["version"],
                "analysis_verified": a.get("verified", False),
                "flags": a.get("flags", []),
                "rhythm_version": v.get("version"),
                "rhythm_id": identity(v),
                **{k: v for k, v in match.items() if not k.startswith("shifted_")},
                "plan_id": plan["plan_id"],
                "strategy": query.strategy,
                "engine": "quantized",
            }
        )
    return {
        "results": results,
        "searched_cues": searched,
        "searched_scopes": scopes,
        "feasible_found": len(found),
        "fuzzy_found": 0,
        "query": query.model_dump(),
        "elapsed_ms": round((time.perf_counter() - start) * 1000, 2),
        "index_status": {"rebuilt_cues": rebuilt, "ready": True, "errors": errors},
        "interpretation": "比较已保存量化节奏；网格误差与原素材形变分别显示。起点不因搜索重新量化。",
    }
