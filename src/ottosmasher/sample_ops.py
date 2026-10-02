from .workspace import CODE_ROOT

"""GUI/CLI operations on immutable audio and derived sample identities."""

import json
from pathlib import Path

import numpy as np

from . import materials, sample_analysis, sample_audio, sample_rhythm
from . import sample_catalog as catalog
from .workspace import DATA, identity, write_json


def select(db, mid, start, end, role=None, batch_id=None, title=None, nature=None):
    parent = materials.get(db, mid)
    source = sample_audio.resolve(db, mid, role)
    try:
        record = sample_analysis.ready(db, mid)
        if record["asset"] != source:
            record = None
    except ValueError:
        record = None
    locator = None
    if record:
        phones = [p for p in record["analysis"]["phones"] if p["end"] > start and p["start"] < end]
        locator = {
            "root_cue_id": parent["cue_id"],
            "backend": record["backend"],
            "analysis_version": record["analysis"]["version"],
            "phones": [
                {
                    k: p.get(k)
                    for k in (
                        "root_phone_id",
                        "root_phone_index",
                        "root_interval",
                        "word_locator",
                        "label",
                        "partial",
                    )
                }
                for p in phones
            ],
        }
    source = sample_audio.resolve(db, mid, role)
    from .selection_names import suggest

    title = title or suggest(
        db, parent["source_id"], source, start, end, record=record if role in (None, "selected") else None
    )
    r = catalog.derive(
        db,
        mid,
        start=start,
        end=end,
        operation="cut",
        input_asset=source,
        locator=locator,
        title=title,
        nature=nature,
        batch_id=batch_id,
    )
    sample_analysis.prepare(db, r["id"])
    return materials.get(db, r["id"])


def preview(db, mid, payload):
    from .audition import preview_strict

    record, plan = sample_rhythm.load(db, mid, payload["plan_id"])
    return preview_strict(record["cue"], record["analysis"], plan, payload.get("mode", "strict"), "vocals")


def export(db, mid, plan_id=None, video=False, role=None):
    if role not in (None, "selected") and not plan_id:
        parent = sample_audio.resolve(db, mid)
        if role != parent["role"]:
            selected = sample_audio.resolve(db, mid, role)
            child = catalog.derive(
                db,
                mid,
                operation="audio_source",
                asset=selected,
                parameters={"role": role},
            )
            mid = child["id"]
            sample_analysis.prepare(db, mid)
    if video:
        if plan_id:
            raise ValueError("请先保存卡拍结果，再从该采样导出对应 PV 画面清单")
        from .visual_media import export as export_pv

        return export_pv(db, mid)
    if not plan_id:
        from .media_operations import cut

        a = sample_audio.resolve(db, mid)
        src = sample_audio.pcm(a)
        out = cut(src, 0, a["end"] - a["start"], title=materials.get(db, mid)["title"])
        manifest = {
            **out,
            "material_id": mid,
            "ancestry": materials.get(db, mid)["derivation"],
            "audio_asset": a,
        }
        write_json(Path(out["path"]).with_suffix(".wav.json"), manifest)
        return {"material_id": mid, "path": out["path"]}
    from .audition import export_witness

    record, plan = sample_rhythm.load(db, mid, plan_id)
    out = export_witness(record["cue"], record["analysis"], {"strict_plan": plan}, "vocals")
    meta = out["manifest"]
    source = sample_audio.resolve(db, mid)
    root = source["root_knots"]
    knots = meta["time_map"]["knots"]
    origin = meta["timeline_start_seconds"]
    mapped = [[float(t - origin), float(np.interp(s, *np.asarray(root).T))] for s, t in knots]
    asset = {
        "path": out["audio"],
        "start": 0,
        "end": meta["actual_duration"],
        "audio_stream": 0,
        "sha256": materials.sha256(out["audio"]),
        "role": "warped",
        **({"target_note": source["target_note"]} if source.get("target_note") else {}),
        "root_knots": mapped,
        "provenance": {"plan_id": plan_id, "manifest": meta},
    }
    r = catalog.derive(
        db,
        mid,
        operation="quantized",
        asset=asset,
        start=record["analysis"]["window_start"],
        end=record["analysis"]["window_end"],
        parameters={"plan_id": plan_id},
        title=materials.get(db, mid)["title"] + " · 卡拍",
    )
    sample_analysis.prepare(db, r["id"])
    from .operation_jobs import submit

    task = submit("sample-features", {"material_id": r["id"]})
    return {"material_id": r["id"], "path": out["audio"], "plan_id": plan_id, "feature_task": task}


def flatten(
    db,
    mid,
    mode="vowels",
    batch_id=None,
    start=None,
    end=None,
    role=None,
    input_asset=None,
    target=None,
    inner=None,
    transition=(0.05, 0.05),
    title=None,
    pitch_strategy=None,
    boundary_side="left",
):
    if mode not in ("vowels", "all", "interior", "from_first_vowel"):
        raise ValueError("未知拉平模式")
    source = input_asset or sample_audio.resolve(db, mid, role)
    duration = source["end"] - source["start"]
    start = 0.0 if start is None else float(start)
    end = duration if end is None else float(end)
    if not 0 <= start < end <= duration + 1e-6:
        raise ValueError("拉平选区越界")
    if mode == "interior":
        from .sample_flatten import validate_interior

        inner, transition = validate_interior(end - start, inner, transition)
    if target is not None:
        from .pitch_values import midi

        midi(target)
    # Cache a range, not a library sample. Registration happens only after success.
    clip = {**source, "start": source["start"] + start, "end": source["start"] + end}
    path = sample_audio.pcm(clip)
    locator = None
    try:
        measured = sample_analysis.ready(db, mid)
        chosen = [p for p in measured["analysis"]["phones"] if p["end"] > start and p["start"] < end]
        locator = {
            "root_cue_id": measured["root_cue"]["id"],
            "backend": measured["backend"],
            "analysis_version": measured["analysis"]["version"],
            "phones": [
                {
                    **{
                        k: p.get(k)
                        for k in (
                            "root_phone_id",
                            "root_phone_index",
                            "root_interval",
                            "word_locator",
                            "label",
                        )
                    },
                    "partial": bool(p.get("partial") or start > p["start"] or end < p["end"]),
                }
                for p in chosen
            ],
        }
    except ValueError:
        pass
    intervals = None
    if mode in ("vowels", "from_first_vowel"):
        from .rhythm_units import normalize_phone

        record = sample_analysis.ready(db, mid)
        if record["asset"] != source:
            raise ValueError("当前试听音源与 FA 测量不一致，请先对该音源重新 FA，或使用整段拉平")
        intervals = [
            [max(start, p["start"]) - start, min(end, p["end"]) - start]
            for p in record["analysis"]["phones"]
            if normalize_phone(p["label"]) in ("a", "i", "u", "e", "o", "I", "U", "N")
            and p["end"] > start
            and p["start"] < end
        ]
    import subprocess

    from .job_worker import python_env
    from .workspace import ROOT

    parameters = {
        "preserve_boundaries": bool(mode in ("vowels", "from_first_vowel") and record["analysis"].get("manual_timing")),
        "mode": mode,
        "intervals": intervals,
        "target": target,
        "inner": inner,
        "transition": list(transition),
        "pitch_strategy": pitch_strategy,
        "boundary_side": boundary_side,
    }
    req = DATA / "jobs" / (identity("flatten-request-v2", str(path), parameters) + ".json")
    write_json(req, {"path": str(path), **parameters})
    subprocess.run(
        [python_env("features"), str(CODE_ROOT / "scripts/sample_flatten_worker.py"), str(req)], check=True
    )
    asset = json.loads(req.with_suffix(".result.json").read_text())
    from .selection_names import suggest

    r = catalog.derive(
        db,
        mid,
        operation="flatten",
        start=start,
        end=end,
        input_asset=source,
        locator=locator,
        asset=asset,
        parameters={**parameters, "target_note": asset["target_note"], "algorithm": "flatten-v2"},
        nature="pitched",
        batch_id=batch_id,
        title=title or suggest(db, materials.get(db, mid)["source_id"], source, start, end),
    )
    sample_analysis.prepare(db, r["id"])
    return {"material_id": r["id"], "path": asset["path"], "target_note": asset["target_note"]}


def batch_search(db, payload):
    result = sample_rhythm.search(db, dict(payload))
    batch = catalog.batch(db, payload)
    for hit in result["results"]:
        r = catalog.derive(
            db,
            hit["material_id"],
            start=hit["scope"]["source_start"],
            end=hit["scope"]["source_end"],
            operation="candidate",
            batch_id=batch["id"],
            parameters={"matched_plan_id": hit["plan_id"]},
        )
        hit["candidate_id"] = r["id"]
    db.execute(
        "UPDATE sample_batches SET query=? WHERE id=?",
        (
            json.dumps(
                {
                    "query": payload,
                    "candidates": [
                        {
                            "material_id": h["material_id"],
                            "candidate_id": h["candidate_id"],
                            "plan_id": h["plan_id"],
                        }
                        for h in result["results"]
                    ],
                }
            ),
            batch["id"],
        ),
    )
    db.commit()
    if result["results"]:
        from .operation_jobs import submit

        batch["preparation_task"] = submit(
            "sample-prepare",
            {"material_ids": list(dict.fromkeys(h["candidate_id"] for h in result["results"]))},
        )
    return {**result, "batch": batch}


def source_browser(db, source_id):
    """Technical source parent, excluded from everyday sample queries."""
    import time

    source = db.execute("SELECT * FROM sources WHERE id=?", (source_id,)).fetchone()
    if not source:
        raise ValueError("原片不存在")
    mid = identity("source-browser", source_id)
    db.execute(
        """INSERT OR IGNORE INTO materials
      (id,source_id,start,end,audio_stream,title,created,pool)
      VALUES(?,?,0,?,?,?,?, 'source-browser')""",
        (mid, source_id, source["duration"], source["audio_stream"], source["title"], time.time()),
    )
    if not db.execute("SELECT 1 FROM asset_samples WHERE sample_id=?", (mid,)).fetchone():
        from .asset_compat import bind_raw_range

        bind_raw_range(db, mid)
    db.commit()
    return materials.get(db, mid)


def source_flatten(
    db,
    mid,
    start,
    end,
    role="raw",
    audio_stream=None,
    mode="all",
    target=None,
    inner=None,
    transition=(0.05, 0.05),
    title=None,
    pitch_strategy=None,
    boundary_side="left",
):
    from .operation_jobs import submit
    from .selection_ops import from_source

    selection = from_source(db, mid, start, end, role, audio_stream)
    db.commit()
    return submit(
        "flatten",
        {
            "selection": selection.json(),
            "mode": mode,
            "target": target,
            "inner": inner,
            "transition": transition,
            "pitch_strategy": pitch_strategy,
            "boundary_side": boundary_side,
            "title": title,
        },
    )


def source_selection(db, mid, start, end, role="vocals", audio_stream=None, title=None, nature=None):
    """Cutter coordinates are always original-media seconds."""
    r = materials.get(db, mid)
    parent = sample_audio.resolve(db, mid, "raw" if not r.get("audio_asset") else None)
    knots = parent.get("root_knots")
    if not knots or not knots[0][1] <= start < end <= knots[-1][1]:
        r = source_browser(db, r["source_id"])
        mid = r["id"]
        parent = sample_audio.resolve(db, mid, "raw")
        knots = parent["root_knots"]
    local, root = np.asarray(knots).T
    left, right = float(np.interp(start, root, local)), float(np.interp(end, root, local))
    from .selection_ops import from_source, resolve as resolve_selection

    selected, asset = resolve_selection(db, from_source(db, mid, start, end, role, audio_stream))
    from .selection_names import suggest

    title = title or suggest(db, r["source_id"], asset, 0, asset["end"] - asset["start"])
    if nature is None:
        from .track_roles import nature as track_nature

        nature = track_nature(db, selected.asset_id)
    child = catalog.derive(
        db,
        mid,
        start=left,
        end=right,
        input_asset=parent,
        asset=asset,
        asset_selection=selected,
        title=title,
        nature=nature,
    )
    sample_analysis.prepare(db, child["id"])
    return child


def reference(
    db, mid, start, end, role="raw", audio_stream=None, streaming=False, native=False, audio_only=False
):
    """Preview only: temporary range resolution never registers a sample."""
    from . import media_operations as media
    from .sample_audio import resolve_range

    r = materials.playback_record(db, mid)
    asset = resolve_range(db, r, start, end, role, audio_stream)
    metadata = json.loads(r["source_metadata"])
    video = not audio_only and any(s["codec_type"] == "video" for s in metadata["streams"])
    track = r["audio_stream"] if audio_stream is None else audio_stream
    if native and video:
        from .native_player import register

        return register(r["path"], start, end, asset, metadata["streams"])
    if streaming and video:
        from .stream_preview import register

        return register(r["path"], start, end, asset)
    if role == "raw" and video:
        base = media.proxy(r["path"], start, end, track)
        return {
            "url": "/api/helper/proxies/" + base["key"],
            "origin": start,
            "duration": end - start,
            "audio_source": role,
            "waveform": media.waveform(r["path"], start, end, track, bins=32000),
        }
    wav = sample_audio.pcm(asset)
    peaks = media.waveform(wav, 0, end - start, bins=32000)
    if not video:
        return {
            "url": "/api/samples/reference-files/" + identity("sample-pcm-v1", asset),
            "origin": start,
            "duration": end - start,
            "waveform": peaks,
            "asset": asset,
        }
    base = media.proxy(r["path"], start, end, track)
    key = identity("reference-v1", base["key"], asset)
    target = DATA / "cache/proxies" / (key + ".mp4")
    if not target.exists():
        from .media_operations import command, executable

        temp = target.with_suffix(".tmp.mp4")
        command(
            [
                executable("ffmpeg"),
                "-v",
                "error",
                "-nostdin",
                "-y",
                "-i",
                base["path"],
                "-i",
                str(wav),
                "-map",
                "0:v:0",
                "-map",
                "1:a:0",
                "-c:v",
                "copy",
                "-c:a",
                "aac",
                "-movflags",
                "+faststart",
                str(temp),
            ]
        )
        temp.replace(target)
    return {
        "url": "/api/helper/proxies/" + key,
        "origin": start,
        "duration": end - start,
        "waveform": peaks,
        "audio_source": role,
    }


def refresh_features(db, mid, role="selected"):
    import subprocess

    from .job_worker import python_env
    from .workspace import ROOT

    path = sample_audio.pcm(sample_audio.resolve(db, mid, role))
    subprocess.run(
        [python_env("features"), str(CODE_ROOT / "scripts/sample_features_worker.py"), str(path)], check=True
    )
    if role == "selected":
        db.execute("DELETE FROM sample_records WHERE material_id=?", (mid,))
        db.commit()
    return {
        "material_id": mid,
        "features_path": str(path.with_suffix(".features.json")),
        "analysis": sample_analysis.prepare(db, mid) if role == "selected" else None,
    }


def register(db, path, copy=False, text=None, nature="unclassified"):
    r = materials.register_file(db, path, copy=copy)
    if r.get("_new_registration"):
        catalog.preferences(db, r["id"], nature="speech" if text else nature)
    if copy and r.get("preferred_version"):
        v = next(v for v in r["versions"] if v["id"] == r["preferred_version"])
        catalog.bind_file(
            db,
            r["id"],
            v["path"],
            {
                "role": "raw",
                "source_id": r["source_id"],
                "root_knots": [[0, r["start"]], [r["end"] - r["start"], r["end"]]],
                "operation": "storage_copy",
            },
        )
        db.commit()
    result = materials.get(db, r["id"])
    if text:
        result["task"] = start_analysis(db, r["id"], text=text)
    return result


def start_analysis(db, mid, text=None, retry=False):
    from .operation_jobs import submit
    from .sample_inference import attach_text

    if text:
        attach_text(db, mid, text)
    return submit("sample-phones", {"material_id": mid, "retry": retry})


def batch_flatten(db, ids, mode="vowels"):
    from .operation_jobs import submit

    if mode not in ("vowels", "all"):
        raise ValueError("未知拉平模式")
    for mid in ids:
        materials.get(db, mid)
    b = catalog.batch(db, {"operation": "flatten", "inputs": ids})
    jobs = [submit("flatten", {"material_id": mid, "batch_id": b["id"], "mode": mode}) for mid in ids]
    return {"batch": b, "jobs": jobs}
