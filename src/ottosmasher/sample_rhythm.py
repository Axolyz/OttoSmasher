"""BPM-dependent three-candidate views of sample-local integer skeletons."""

import copy
import json
import math
import time
from functools import lru_cache

import numpy as np

from .beat_reference import generate_references
from .rhythm_index import compose_pattern, prototype, speech_bounds
from .sample_analysis import ready
from .time_mapping import schedule
from .workspace import DATA, identity, write_json


def candidates(record, bpm, strategy):
    if not math.isfinite(bpm) or bpm <= 0:
        raise ValueError("BPM 必须为正数")
    if strategy not in record["compiled"]["routes"]:
        raise ValueError("该算法缺少可靠的对应信息")
    slots = record["compiled"]["routes"][strategy]["slots"]
    speech = record["compiled"]["measured"]["speech_seconds"]
    exponent = math.ceil(math.log2(sum(slots) * (60 / bpm) / speech))
    tested = {}
    errors = []

    def at(k):
        if k in tested:
            return tested[k]
        if abs(k) > 40:
            raise ValueError("倍率超出可表示的采样帧范围")
        d = 2.0**k
        p = prototype(record, strategy, d)["plan"]
        p["beat_seconds"] = 60 / bpm
        p["duration_multiplier"] *= 120 / bpm
        p["speech_bounds"] = speech_bounds(record)
        try:
            timing = schedule(
                p,
                record["analysis"]["window_start"],
                round((record["analysis"]["window_end"] - record["analysis"]["window_start"]) * 48000),
            )
            speed = timing["speech_playback_speed"]
            out = (d, speed, p)
        except ValueError as e:
            errors.append({"density": d, "reason": str(e)})
            out = None
        tested[k] = out
        return out

    # Pure mapping, no inference or rendering. Only neighbouring powers are explored.
    for _ in range(24):
        p = at(exponent)
        if p and p[1] >= 1 - 1e-5:
            before = at(exponent - 1)
            if before and before[1] >= 1 - 1e-5:
                exponent -= 1
                continue
            break
        exponent += 1
    fast = at(exponent)
    if not fast or fast[1] < 1 - 1e-5:
        return [], errors
    result = []
    for label, k in [("near_fast", exponent), ("near_slow", exponent - 1), ("double_fast", exponent + 1)]:
        p = at(k)
        if p:
            result.append({"density": p[0], "speech_playback_speed": p[1], "candidate_role": label})
    return result, errors


def timing_view(record, plan):
    start = record["analysis"]["window_start"]
    duration = record["analysis"]["window_end"] - start
    mapped = schedule(plan, start, round(duration * 48000))
    return {
        "source_duration": duration,
        "target_duration": mapped["actual_duration"],
        "speech_playback_speed": mapped["speech_playback_speed"],
        "points": [
            {
                "label": u.get("label", ""),
                "source_seconds": u["source_seconds"] - start,
                "target_seconds": u["target_beat"] * plan["beat_seconds"] - mapped["timeline_start_seconds"],
            }
            for u in plan["unit_targets"]
        ],
    }


def original_speed_plan(record, strategy):
    options, _ = candidates(record, 120, strategy)
    if not options:
        raise ValueError("无法生成有效的原速卡拍方案")
    base = generate_references(
        record["cue"],
        record["analysis"],
        record["view"],
        bpm=120,
        strategy=strategy,
        density=options[0]["density"],
        compiled=record["compiled"],
        persist=False,
    )["plans"][0]
    base["speech_bounds"] = speech_bounds(record)
    low, high, best = 20.0, 400.0, None
    for _ in range(32):
        bpm = (low + high) / 2
        plan = copy.deepcopy(base)
        plan["beat_seconds"] = 60 / bpm
        plan["duration_multiplier"] = base["duration_multiplier"] * 120 / bpm
        plan["local_duration_ratios"] = [v * 120 / bpm for v in base.get("local_duration_ratios", [])]
        plan["min_duration_ratio"] = min(plan["local_duration_ratios"])
        plan["max_duration_ratio"] = max(plan["local_duration_ratios"])
        try:
            info = timing_view(record, plan)
        except ValueError:
            high = bpm
            continue
        error = abs(info["speech_playback_speed"] - 1)
        if best is None or error < best[0]:
            best = (error, plan, info)
        if error < 1e-5:
            break
        if info["speech_playback_speed"] < 1:
            low = bpm
        else:
            high = bpm
    if best is None or best[0] > 1e-3:
        raise ValueError("当前节奏在起音保护约束下无法保持原速")
    plan = best[1]
    plan["estimated_duration_seconds"] = best[2]["target_duration"]
    plan["score"] = abs(math.log(plan["duration_multiplier"]))
    plan.update(
        {
            "candidate_role": "original_speed",
            "target_bpm": None,
            "speech_playback_speed": best[2]["speech_playback_speed"],
            "label": "1.000× · 原速卡拍",
        }
    )
    return plan


def save(record, plan, settings):
    plan = {
        **plan,
        "visual_timing": timing_view(record, plan),
        "material_id": record["cue"]["id"],
        "sample_signature": record["signature"],
        "settings_signature": identity(settings),
        "scope": record["scope"],
    }
    plan["plan_id"] = identity("sample-plan-v1", plan)
    write_json(DATA / "sample-plans" / (plan["plan_id"] + ".json"), plan)
    return plan


def plans(db, mid, bpm=120, plan_id=None):
    from .materials import get

    r = get(db, mid)
    record = ready(db, mid)
    if plan_id:
        return {"plans": [load(db, mid, plan_id)[1]], "selected_plan_id": plan_id}
    if bpm is None:
        p = save(
            record, original_speed_plan(record, r["active_quantization_strategy"]), r["analysis_settings"]
        )
        return {"plans": [p], "selected_plan_id": p["plan_id"], "conflicts": []}
    chosen, errors = candidates(record, bpm, r["active_quantization_strategy"])
    out = []
    for c in chosen:
        p = generate_references(
            record["cue"],
            record["analysis"],
            record["view"],
            bpm=bpm,
            strategy=r["active_quantization_strategy"],
            density=c["density"],
            compiled=record["compiled"],
            persist=False,
        )["plans"][0]
        p.update(c)
        p["label"] = f"{c['speech_playback_speed']:.3f}× · {c['density']:g} 格/拍"
        p["speech_bounds"] = speech_bounds(record)
        out.append(save(record, p, r["analysis_settings"]))
    return {"plans": out, "selected_plan_id": out[0]["plan_id"] if out else None, "conflicts": errors}


def load(db, mid, pid):
    from .materials import get

    if len(pid) != 24 or any(c not in "0123456789abcdef" for c in pid):
        raise ValueError("无效方案")
    path = DATA / "sample-plans" / (pid + ".json")
    if not path.exists():
        raise ValueError("方案不存在")
    p = json.loads(path.read_text())
    r = get(db, mid)
    record = ready(db, mid)
    if (
        p.get("material_id") != mid
        or p["sample_signature"] != record["signature"]
        or p["strategy"] != r["active_quantization_strategy"]
        or p["analysis_kind"] != r["active_phone_backend"]
    ):
        raise ValueError("采样或分析选择已改变，请重新生成方案")
    if p.get("scope", {}).get("kind") == "segment":
        record = next(
            (e for e in record.get("entries", []) if e["scope"]["scope_id"] == p["scope"]["scope_id"]), None
        )
        if record is None:
            raise ValueError("语段方案已过期")
    p["visual_timing"] = timing_view(record, p)
    return record, p


@lru_cache(maxsize=1024)
def decode(payload):
    return json.loads(payload)


def search(db, payload, *, all_matches=False):
    from .quantized_match import match_pattern
    from .rhythm import RhythmQuery
    from .sample_scope import ids

    start = time.perf_counter()
    payload = dict(payload)
    eligible = set(ids(db, payload))
    for key in ("pool", "folder_id", "folder_ids", "starred", "material_ids", "target_folder", "nature"):
        payload.pop(key, None)
    q = RhythmQuery.model_validate(payload)
    rows = db.execute(
        "SELECT m.*,r.payload FROM materials m JOIN sample_records r ON r.material_id=m.id AND r.backend=m.active_phone_backend WHERE m.status<>'discarded'"
    ).fetchall()
    def matches(pattern, local):
        if not all_matches:
            found = match_pattern(pattern, local)
            return [found] if found else []
        from .quantized_match import _requirements
        count = len(_requirements(local)[0])
        result = []
        for first in range(len(pattern.get("units", []))-count+1):
            candidate = {**local.model_dump(), "required_unit_indices": list(range(first, first+count))}
            found = match_pattern(pattern, candidate)
            if found: result.append(found)
        return result
    hits = []
    errors = []
    searched = 0
    searched_scopes = 0
    for row in rows:
        if row["id"] not in eligible:
            continue
        parent = decode(row["payload"])
        strategy = row["active_quantization_strategy"]
        searched += 1
        from .sample_analysis import measurement, signature

        if parent["signature"] != signature(
            {"analysis_settings": json.loads(row["analysis_settings"])},
            parent["asset"],
            measurement(db, dict(row), row["active_phone_backend"]),
            db,
        ):
            errors.append({"material_id": row["id"], "reason": "索引已过期，请重建局部分析"})
            continue
        for record in [parent, *parent.get("entries", [])]:
            if q.scope == "whole" and record["scope"]["kind"] != "whole":
                continue
            if q.scope == "segments" and record["scope"]["kind"] != "segment":
                continue
            searched_scopes += 1
            try:
                options, _failures = candidates(record, q.bpm, strategy)
            except ValueError as e:
                errors.append({"material_id": row["id"], "reason": str(e)})
                continue
            for option in options:
                pattern = prototype(record, strategy, option["density"])
                pattern["units"] = with_speakers(db, record, pattern["units"])
                local = q.model_copy(
                    update={
                        "mode": row["active_phone_backend"],
                        "strategy": strategy,
                        "densities": [option["density"]],
                        "speed_filter": False,
                    }
                )
                hits.extend((match, record, dict(row), option) for match in matches(pattern, local))
                if q.adjust_pauses and record["scope"]["kind"] == "whole" and parent.get("entries"):
                    combined = compose_pattern(
                        {"cue": record["cue"], "entries": [parent, *parent["entries"]]},
                        strategy,
                        option["density"],
                    )
                    if combined:
                        combined["units"] = with_speakers(db, record, combined["units"])
                        hits.extend((match, record, dict(row), option) for match in matches(combined, local))
    hits.sort(key=lambda x: x[0]["cost"])
    results = []
    from .ui_catalog import effective_all

    display_tags = effective_all(db, list({h[2]["id"] for h in hits})) if hits else {}
    for match, record, r, opt in (hits if all_matches else hits[: q.limit]):
        p = generate_references(
            record["cue"],
            record["analysis"],
            record["view"],
            bpm=q.bpm,
            strategy=r["active_quantization_strategy"],
            density=opt["density"],
            compiled=record["compiled"],
            persist=False,
        )["plans"][0]
        if match.get("adjusted_links"):
            combined = compose_pattern(
                {"cue": record["cue"], "entries": [record, *record.get("entries", [])]},
                r["active_quantization_strategy"],
                opt["density"],
                {str(x["link_index"]): x["rest_cells"] for x in match["adjusted_links"]},
            )
            if combined:
                p.update(copy.deepcopy(combined["plan"]))
                p["beat_seconds"] = 60 / q.bpm
                p["duration_multiplier"] *= 120 / q.bpm
        p["speech_bounds"] = speech_bounds(record)
        p["unit_targets"] = match["shifted_unit_targets"]
        p["end_target"] = match["shifted_end_target"]
        p["control_targets"] = match.get("shifted_control_targets", [])
        p["witness"] = {k: v for k, v in match.items() if not k.startswith("shifted_")}
        p.update(opt)
        p["speech_playback_speed"] = match["speech_playback_speed"]
        p["label"] = f"{match['speech_playback_speed']:.3f}× · {opt['density']:g} 格/拍"
        for point in p["unit_targets"]:
            indices = match["matched_anchor_indices"]
            i = point["unit_index"]
            point.update(
                role="matched" if i in indices else "automatic",
                query_index=indices.index(i) if i in indices else None,
            )
        p = save(record, p, json.loads(r["analysis_settings"]))
        results.append(
            {
                **{k: v for k, v in match.items() if not k.startswith("shifted_")},
                "material_id": r["id"],
                "cue_id": r["id"],
                "source_id": r["source_id"],
                "title": record["root_cue"].get("title", r["title"]),
                "sample_title": r["title"],
                "tags": display_tags.get(r["id"], []),
                "starred": bool(r["starred"]),
                "spoken": r["title"],
                "start": r["start"],
                "end": r["end"],
                "analysis_kind": r["active_phone_backend"],
                "strategy": r["active_quantization_strategy"],
                "plan_id": p["plan_id"],
                "analysis_version": record["analysis"]["version"],
                "flags": [],
            }
        )
    return {
        "results": results,
        "searched_cues": searched,
        "searched_scopes": searched_scopes,
        "feasible_found": len(hits),
        "fuzzy_found": 0,
        "query": q.model_dump(),
        "elapsed_ms": round((time.perf_counter() - start) * 1000, 2),
        "index_status": {"ready": True, "rebuilt_cues": 0, "errors": errors},
        "interpretation": "每个采样使用自己的模型与算法；三个自适应倍率直接参与匹配。",
    }


def with_speakers(db, record, units):
    from .speakers import labels_for_units

    knots = record["asset"]["root_knots"]
    local, root = np.asarray(knots).T
    mapped = [
        {"time": float(np.interp(u["time"], local, root)), "end": float(np.interp(u["end"], local, root))}
        for u in units
    ]
    labels = labels_for_units(db, record["root_cue"], mapped)
    return [{**u, "features": {**f, **s}} for u, f, s in zip(units, record["features"], labels)]
