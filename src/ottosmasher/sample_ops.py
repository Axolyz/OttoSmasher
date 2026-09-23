from .workspace import CODE_ROOT
"""GUI/CLI operations on immutable audio and derived sample identities."""

import json
from pathlib import Path

import numpy as np

from . import materials, sample_analysis, sample_audio, sample_rhythm
from . import sample_catalog as catalog
from .workspace import DATA, identity, write_json


def select(db, mid, start, end, role=None, folder_id="", batch_id=None, title=None, nature=None):
    parent = materials.get(db, mid)
    try:
        record = sample_analysis.ready(db, mid)
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
        if not title:
            words = list(dict.fromkeys(p["word_locator"]["word"] for p in phones if p.get("word_locator")))
            title = (
                parent["title"]
                + " — "
                + ("".join(words) + " " if words else "")
                + " ".join(p["label"] for p in phones)
            )
    source = sample_audio.resolve(db, mid, role)
    r = catalog.derive(
        db,
        mid,
        start=start,
        end=end,
        operation="cut",
        input_asset=source,
        locator=locator,
        title=title,
        folder_id=folder_id,
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
                folder_id="",
            )
            mid = child["id"]
            sample_analysis.prepare(db, mid)
    if video:
        from . import media_operations as media

        r = materials.get(db, mid)
        asset = sample_audio.resolve(db, mid)
        if asset["role"] == "warped":
            raise ValueError("变速采样的视频导出尚不支持；请导出 WAV")
        wav = sample_audio.pcm(asset)
        key = identity("sample-video-v1", asset, r["path"], r["start"], r["end"])
        target = DATA / "media/exports" / (key + ".mp4")
        target.parent.mkdir(parents=True, exist_ok=True)
        if not target.exists():
            tmp = target.with_suffix(".tmp.mp4")
            media.command(
                [
                    media.executable("ffmpeg"),
                    "-v",
                    "error",
                    "-nostdin",
                    "-y",
                    "-ss",
                    str(r["start"]),
                    "-t",
                    str(r["end"] - r["start"]),
                    "-i",
                    r["path"],
                    "-i",
                    str(wav),
                    "-map",
                    "0:v:0",
                    "-map",
                    "1:a:0",
                    "-c:v",
                    "libx264",
                    "-preset",
                    "fast",
                    "-crf",
                    "18",
                    "-c:a",
                    "aac",
                    "-movflags",
                    "+faststart",
                    str(tmp),
                ]
            )
            tmp.replace(target)
        write_json(
            target.with_suffix(".json"),
            {"material_id": mid, "audio_asset": asset, "root_range": [r["start"], r["end"]]},
        )
        return {"material_id": mid, "path": str(target)}
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


def flatten(db, mid, mode="vowels", batch_id=None, start=None, end=None, role=None, input_asset=None):
    if mode not in ("vowels", "all"):
        raise ValueError("未知拉平模式")
    source = input_asset or sample_audio.resolve(db, mid, role)
    duration = source["end"] - source["start"]
    start = 0.0 if start is None else float(start)
    end = duration if end is None else float(end)
    if not 0 <= start < end <= duration + 1e-6:
        raise ValueError("拉平选区越界")
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
    if mode == "vowels":
        record = sample_analysis.ready(db, mid)
        intervals = [
            [max(start, p["start"]) - start, min(end, p["end"]) - start]
            for p in record["analysis"]["phones"]
            if p["label"].lower().rstrip("ː:") in ("a", "i", "u", "e", "o")
            and p["end"] > start
            and p["start"] < end
        ]
    import subprocess

    from .job_worker import python_env
    from .workspace import ROOT

    req = DATA / "jobs" / (identity("flatten-request", str(path), mode, intervals) + ".json")
    write_json(req, {"path": str(path), "mode": mode, "intervals": intervals})
    subprocess.run(
        [python_env("features"), str(CODE_ROOT / "scripts/sample_flatten_worker.py"), str(req)], check=True
    )
    asset = json.loads(req.with_suffix(".result.json").read_text())
    r = catalog.derive(
        db,
        mid,
        operation="flatten",
        start=start,
        end=end,
        input_asset=source,
        locator=locator,
        asset=asset,
        parameters={"mode": mode, "target_note": asset["target_note"]},
        folder_id="",
        nature="pitched",
        batch_id=batch_id,
        title=materials.get(db, mid)["title"] + " · " + asset["target_note"]["name"],
    )
    sample_analysis.prepare(db, r["id"])
    return {"material_id": r["id"], "path": asset["path"], "target_note": asset["target_note"]}


def batch_search(db, payload, target="speech"):
    result = sample_rhythm.search(db, dict(payload))
    batch = catalog.batch(db, payload, target)
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
      (id,source_id,start,end,audio_stream,title,created,pool,folder_id)
      VALUES(?,?,0,?,?,?,?, 'source-browser','inbox')""",
        (mid, source_id, source["duration"], source["audio_stream"], source["title"], time.time()),
    )
    db.commit()
    return materials.get(db, mid)


def source_flatten(db, mid, start, end, role="raw", audio_stream=None):
    from .operation_jobs import submit

    r = materials.get(db, mid)
    # Preserve known sentence ancestry when the chosen source covers that whole parent.
    if r["start"] <= start < end <= r["end"] and r.get("cue_id"):
        try:
            asset = sample_audio.resolve_range(db, r, r["start"], r["end"], role, audio_stream)
            return submit(
                "flatten",
                {
                    "material_id": mid,
                    "mode": "all",
                    "input_asset": asset,
                    "start": start - r["start"],
                    "end": end - r["start"],
                    "role": role,
                },
            )
        except ValueError:
            pass
    parent = source_browser(db, r["source_id"])
    asset = sample_audio.resolve_range(db, r, start, end, role, audio_stream)
    return submit("flatten", {"material_id": parent["id"], "mode": "all", "input_asset": asset, "role": role})


def source_selection(
    db, mid, start, end, role="vocals", audio_stream=None, title=None, folder_id="", nature=None
):
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
    asset = sample_audio.resolve_range(db, r, start, end, role, audio_stream)
    child = catalog.derive(
        db,
        mid,
        start=left,
        end=right,
        input_asset=parent,
        asset=asset,
        title=title,
        folder_id=folder_id,
        nature=nature,
    )
    sample_analysis.prepare(db, child["id"])
    return child


def reference(db, mid, start, end, role="raw", audio_stream=None, streaming=False, native=False):
    """Preview only: temporary range resolution never registers a sample."""
    from . import media_operations as media
    from .sample_audio import resolve_range

    r = materials.get(db, mid)
    asset = resolve_range(db, r, start, end, role, audio_stream)
    metadata = json.loads(r["source_metadata"])
    video = any(s["codec_type"] == "video" for s in metadata["streams"])
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


def register(db, path, folder_id="inbox", copy=False, text=None, nature="unclassified"):
    r = materials.register_file(db, path, copy=copy)
    if r.get("_new_registration"):
        catalog.preferences(db, r["id"], folder_id=folder_id, nature="speech" if text else nature)
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


def batch_flatten(db, ids, target_folder="pitched", mode="vowels"):
    from .operation_jobs import submit

    if mode not in ("vowels", "all"):
        raise ValueError("未知拉平模式")
    for mid in ids:
        materials.get(db, mid)
    b = catalog.batch(db, {"operation": "flatten", "inputs": ids}, target_folder)
    jobs = [submit("flatten", {"material_id": mid, "batch_id": b["id"], "mode": mode}) for mid in ids]
    return {"batch": b, "jobs": jobs}
