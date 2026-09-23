"""Explicit actions on versioned hits. Temporary previews never create materials."""

import copy
from pathlib import Path

import numpy as np

from .speech_query import validate_hit
from .workspace import DATA, identity, write_json


def local_record(record, hit):
    from .beat_reference import compile_reference
    from .rhythm_scopes import VERSION, scope_context

    descriptor = {
        "kind": "segment",
        "parent_cue_id": record["cue"]["id"],
        "parent_analysis_id": identity(record["analysis"]),
        "parent_rhythm_id": identity(record["view"]),
        "source_start": hit["start"],
        "source_end": hit["end"],
        "parent_unit_indices": hit["unit_indices"],
        "label": "命中区",
    }
    descriptor["scope_id"] = identity(VERSION, descriptor)
    aa, vv = scope_context(record["cue"], record["analysis"], record["view"], descriptor)
    compiled = compile_reference(record["cue"], aa, vv, large_number_penalty=record["compiled"].get("large_number_penalty",1.0))
    return {**record, "analysis": aa, "view": vv, "compiled": compiled, "scope": descriptor, "entries": []}


def action(db, body):
    from .native_player import register
    from .sample_audio import pcm

    hit = body["hit"]
    record = validate_hit(db, hit)
    start, end = hit["start"], hit["end"]
    command = body.get("action", "play")
    if command in ("save", "flatten"):
        if command == "save":
            from .sample_ops import select

            return select(
                db, hit["material_id"], start, end, nature=body.get("nature"), title=body.get("title")
            )
        from .operation_jobs import submit

        return {
            "job": submit(
                "flatten",
                {
                    "material_id": hit["material_id"],
                    "start": start,
                    "end": end,
                    "mode": "all",
                    "input_asset": record["asset"],
                },
            )
        }
    if command == "play" and body.get("context"):
        start = max(0, start - 0.3)
        end = min(record["analysis"]["window_end"], end + 0.3)
    asset = copy.deepcopy(record["asset"])
    asset["start"] += start
    asset["end"] = record["asset"]["start"] + end
    knots = np.asarray(record["asset"]["root_knots"])
    asset["root_knots"] = [
        [0, float(np.interp(start, knots[:, 0], knots[:, 1]))],
        [end - start, float(np.interp(end, knots[:, 0], knots[:, 1]))],
    ]
    asset["provenance"] = {**asset.get("provenance", {}), "speech_hit": hit}
    if command in ("quantized", "export-quantized", "reaper"):
        from .beat_reference import generate_references
        from .sample_rhythm import candidates, original_speed_plan, speech_bounds
        from .strict_audio import render_strict

        r = local_record(record, hit)
        row = db.execute(
            "SELECT active_quantization_strategy FROM materials WHERE id=?", (hit["material_id"],)
        ).fetchone()
        strategy = row[0]
        bpm = body.get("bpm")
        if bpm is None:
            plan = original_speed_plan(r, strategy)
        else:
            options, _ = candidates(r, float(bpm), strategy)
            if not options:
                raise ValueError("命中区没有可用的卡拍方案")
            plan = generate_references(
                r["cue"],
                r["analysis"],
                r["view"],
                bpm=bpm,
                strategy=strategy,
                density=options[0]["density"],
                compiled=r["compiled"],
                persist=False,
            )["plans"][0]
            plan.update(options[0])
            plan["speech_bounds"] = speech_bounds(r)
        plan["plan_id"] = identity("speech-hit-plan-v1", hit, plan)
        if command == "reaper":
            from .reaper_export import export_reaper

            return export_reaper(r["cue"], r["analysis"], plan, "vocals", copy=True)
        path, meta = render_strict(r["cue"], r["analysis"], plan, "vocals")
        if command == "export-quantized":
            return {"path": str(path), "hit": hit, "manifest": meta}
        return (
            {
                **register(
                    path,
                    0,
                    meta["actual_duration"],
                    {
                        "path": str(path),
                        "start": 0,
                        "end": meta["actual_duration"],
                        "audio_stream": 0,
                        "role": "warped",
                    },
                    [{"index": 0, "codec_type": "audio"}],
                )
            }
            if body.get("native")
            else {"url": f"/api/previews/{path.stem}.wav", "duration": meta["actual_duration"]}
        )
    if command not in ("play", "export"):
        raise ValueError("未知命中操作")
    if command == "export":
        path = pcm(asset)
        return {"path": str(path), "hit": hit}
    if body.get("native") and asset.get("path"):
        from .catalog import probe

        return register(
            asset["path"], asset["start"], asset["end"], asset, probe(Path(asset["path"]))["streams"]
        )
    path = pcm(asset)
    key = identity("speech-hit-audio", asset)
    write_json(DATA / "cache/speech-hits" / (key + ".json"), {"path": str(path)})
    return {"url": "/api/samples/speech-hit-audio/" + key, "duration": end - start}
