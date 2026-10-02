"""Forced FA on frozen, currently selected audio; never prepares separation."""

from __future__ import annotations

import copy
import json
import os
import subprocess
from pathlib import Path

from . import asset_timeline as timeline
from .workspace import CODE_ROOT, DATA, connect, identity, write_json


def padded_asset(db, sample, asset, before, after):
    """Extend only inside a recorded descriptor for the identical physical track."""
    candidates = [
        json.loads(r[0])
        for r in db.execute(
            "SELECT payload FROM shared_sample_audio WHERE source_id=?", (sample["source_id"],)
        )
    ]
    candidates.extend(
        json.loads(r[0])
        for r in db.execute(
            "SELECT descriptor FROM sound_assets WHERE source_id=? AND json_extract(descriptor,'$.path')=? AND json_extract(descriptor,'$.sha256')=?",
            (sample["source_id"], asset.get("path"), asset.get("sha256")),
        )
    )
    if asset.get("role") == "raw":
        source = db.execute(
            "SELECT duration,path,fingerprint FROM sources WHERE id=?", (sample["source_id"],)
        ).fetchone()
        candidates.append(
            {
                **asset,
                "start": 0,
                "end": source["duration"],
                "path": source["path"],
                "sha256": source["fingerprint"],
                "root_knots": [[0, 0], [source["duration"], source["duration"]]],
            }
        )
    candidates.append(asset)
    candidates.sort(key=lambda a: a["end"] - a["start"], reverse=True)
    for full in candidates:
        if any(full.get(k, 0) != asset.get(k, 0) for k in ("path", "sha256", "audio_stream")):
            continue
        if not full.get("root_knots") or not full["start"] <= asset["start"] < asset["end"] <= full["end"]:
            continue
        try:
            if any(
                abs(timeline.map_time(full["root_knots"], asset["start"] - full["start"] + x) - y) > 1e-7
                for x, y in asset.get("root_knots", [])
            ):
                continue
        except ValueError:
            continue
        lo, hi = max(full["start"], asset["start"] - before), min(full["end"], asset["end"] + after)
        registered = timeline.register_asset(db, sample["source_id"], full, legacy_mapping=True)
        selection = timeline.AssetSelection(registered.asset_id, lo - full["start"], hi - full["start"])
        return timeline.selection_asset(db, selection), selection, [asset["start"] - lo, hi - asset["end"]]
    selection = timeline.register_asset(db, sample["source_id"], asset, legacy_mapping=True)
    return asset, selection, [0, 0]


def snapshot(db, ids, backend=None):
    from . import materials, sample_audio
    from .backends import BACKENDS
    from .frontend_service import alignment_text, dictionary
    from .ui_catalog import settings

    defaults = settings(db)
    backend = backend or defaults["phone_model_order"][0]
    if backend not in BACKENDS:
        raise ValueError("未知 FA 模型")
    items, missing = [], []
    for mid in dict.fromkeys(ids):
        try:
            sample = materials.get(db, mid)
            if not sample["cue_id"]:
                raise ValueError("待补对齐文本")
            cue = dict(db.execute("SELECT * FROM cues WHERE id=?", (sample["cue_id"],)).fetchone())
            text = alignment_text(db, cue)
            if not text["text"].strip():
                raise ValueError("待补对齐文本")
            asset = sample_audio.resolve(db, mid)
            # Original sentence text is not a guessed transcript of a tiny crop.
            if (
                sample.get("derivation")
                and not db.execute(
                    "SELECT 1 FROM alignment_texts WHERE annotation_id=?", (cue["id"],)
                ).fetchone()
                and (abs(sample["start"] - cue["start"]) > 1e-6 or abs(sample["end"] - cue["end"]) > 1e-6)
            ):
                raise ValueError("裁切范围与原台词不同，待补对应对齐文本")
            signature = identity(asset)
            stat = Path(asset["path"]).stat()
            input_asset, selection, padding_actual = padded_asset(
                db, sample, asset, defaults["fa_padding_before"], defaults["fa_padding_after"]
            )
            head = db.execute(
                "SELECT revision FROM analysis_references WHERE owner_type='sample' AND owner_id=? AND kind=?",
                (mid, backend),
            ).fetchone()
            items.append(
                {
                    "material_id": mid,
                    "cue_id": cue["id"],
                    "source_id": sample["source_id"],
                    "asset": input_asset,
                    "selection": selection.json(),
                    "asset_signature": signature,
                    "alignment": text,
                    "head_revision": head[0] if head else 0,
                    "backend": backend,
                    "file_stat": [stat.st_size, stat.st_mtime_ns],
                    "padding_requested": [defaults["fa_padding_before"], defaults["fa_padding_after"]],
                    "input_range": [selection.start, selection.end],
                    "padding_actual": padding_actual,
                    "padding_clipped_to_asset": any(
                        abs(a - b) > 1e-8
                        for a, b in zip(
                            padding_actual, [defaults["fa_padding_before"], defaults["fa_padding_after"]]
                        )
                    ),
                }
            )
        except (ValueError, OSError) as exc:
            missing.append({"material_id": mid, "reason": str(exc)})
    return {
        "items": items,
        "missing": missing,
        "dictionary": dictionary(),
        "backend": backend,
        "frontend_version": "openjtalk-plus-tsqyomi-v1",
    }


def submit(db, ids, backend=None):
    from .operation_jobs import submit as queue

    payload = snapshot(db, ids, backend)
    db.commit()
    if not payload["items"]:
        return {"missing": payload["missing"], "job": None}
    return {
        "missing": payload["missing"],
        "inputs": [
            {
                k: x[k]
                for k in (
                    "material_id",
                    "selection",
                    "input_range",
                    "padding_requested",
                    "padding_clipped_to_asset",
                )
            }
            for x in payload["items"]
        ],
        "job": queue("force-fa", payload),
    }


def current_text(db, annotation_id):
    from .frontend_service import alignment_text

    row = db.execute("SELECT * FROM cues WHERE id=?", (annotation_id,)).fetchone()
    if row:
        return alignment_text(db, dict(row))
    row = db.execute(
        "SELECT id,text FROM timeline_annotations WHERE id=? AND deleted=0", (annotation_id,)
    ).fetchone()
    if not row:
        return None
    from .subtitle_speakers import spoken_text

    return alignment_text(db, {"id": row["id"], "spoken": spoken_text(row["text"])})


def submit_selection(db, selection, annotation_id, backend=None):
    from .backends import BACKENDS
    from .frontend_service import dictionary
    from .operation_jobs import submit as queue
    from .selection_ops import resolve
    from .ui_catalog import settings

    defaults = settings(db)
    backend = backend or defaults["phone_model_order"][0]
    if backend not in BACKENDS:
        raise ValueError("未知 FA 模型")
    selected, asset = resolve(db, selection)
    text = current_text(db, annotation_id)
    if not text or not text["text"].strip():
        raise ValueError("待补对齐文本")
    source = db.execute(
        "SELECT source_id,duration FROM sound_assets WHERE id=?", (selected.asset_id,)
    ).fetchone()
    cue = (
        db.execute("SELECT source_id FROM cues WHERE id=?", (annotation_id,)).fetchone()
        or db.execute("SELECT source_id FROM timeline_annotations WHERE id=?", (annotation_id,)).fetchone()
    )
    if not cue or cue[0] != source[0]:
        raise ValueError("文本区段属于另一原片")
    descriptor, padded, padding_actual = padded_asset(
        db, {"source_id": source[0]}, asset, defaults["fa_padding_before"], defaults["fa_padding_after"]
    )
    owner = identity("asset-text-analysis", padded.asset_id, padded.start, padded.end, annotation_id)
    head = db.execute(
        "SELECT revision FROM analysis_references WHERE owner_type='asset_text' AND owner_id=? AND kind=?",
        (owner, backend),
    ).fetchone()
    stat = Path(descriptor["path"]).stat()
    item = {
        "material_id": owner,
        "owner_type": "asset_text",
        "owner_id": owner,
        "cue_id": annotation_id,
        "source_id": source[0],
        "asset": descriptor,
        "selection": padded.json(),
        "asset_signature": identity(descriptor),
        "alignment": text,
        "head_revision": head[0] if head else 0,
        "backend": backend,
        "file_stat": [stat.st_size, stat.st_mtime_ns],
        "padding_requested": [defaults["fa_padding_before"], defaults["fa_padding_after"]],
        "padding_actual": padding_actual,
        "input_range": [padded.start, padded.end],
        "padding_clipped_to_asset": any(
            abs(a - b) > 1e-8
            for a, b in zip(padding_actual, [defaults["fa_padding_before"], defaults["fa_padding_after"]])
        ),
    }
    payload = {
        "items": [item],
        "missing": [],
        "dictionary": dictionary(),
        "backend": backend,
        "frontend_version": "openjtalk-plus-tsqyomi-v1",
    }
    db.commit()
    return {"inputs": [item], "job": queue("force-fa", payload)}


def compatible_payload(db, row):
    """Project a current asset-local measurement for legacy rhythm readers only."""
    payload = json.loads(row["payload"])
    if payload.get("clock") != "asset":
        return payload
    selection = timeline.AssetSelection(**payload["input_selection"])
    asset = db.execute("SELECT descriptor FROM sound_assets WHERE id=?", (selection.asset_id,)).fetchone()
    descriptor = json.loads(asset[0])
    knots = descriptor.get("root_knots")
    if not knots:
        raise ValueError("此资产没有来源时间映射，不能投影到旧节奏接口")
    result = copy.deepcopy(payload)
    result["phones"] = [
        {**p, "start": timeline.map_time(knots, p["start"]), "end": timeline.map_time(knots, p["end"])}
        for p in payload["phones"]
    ]
    result.update(
        clock="source", _measured_current_asset=True, window_start=knots[0][1], window_end=knots[-1][1]
    )
    return result


def run(payload, jid):
    from .alignment_results import target_phones
    from .alignment_runner import worker_command
    from .frontend_service import batch
    from .sample_audio import pcm, resolve
    from .workspace import command, executable

    folder = DATA / "alignment/forced" / jid
    (folder / "inputs").mkdir(parents=True, exist_ok=True)
    items = payload["items"]
    backend = payload["backend"]
    frontends = batch([x["alignment"]["text"] for x in items], payload["dictionary"])
    specs = []
    for item, frontend in zip(items, frontends):
        mid = item["material_id"]
        duration = item["selection"]["end"] - item["selection"]["start"]
        frontend["mora"]["original_matches"] = item["alignment"]["original_matches"]
        stat = Path(item["asset"]["path"]).stat()
        if item.get("file_stat") and [stat.st_size, stat.st_mtime_ns] != item["file_stat"]:
            raise ValueError("提交后声音文件已改变，FA 未运行")

        spec = {
            "id": mid,
            "context": [{"id": mid, "spoken": item["alignment"]["text"]}],
            "frontends": {mid: frontend},
            "window_start": 0,
            "window_end": duration,
            "audio_lineage": {"audio_sha256": item["asset"].get("sha256")},
        }
        spec["input_audio"] = {"audio_path": item["asset"]["path"], "audio_start": item["asset"]["start"],
            "audio_end": item["asset"]["end"], "file_audio_stream": item["asset"].get("audio_stream", 0),
            "window_start": 0, "window_end": duration}
        write_json(folder / "inputs" / (mid + ".json"), spec)
        specs.append(spec)
    write_json(folder / "manifest.json", {"cues": specs})
    subprocess.run(
        worker_command(folder, backend, limit=len(specs), retry=True, exclude_regions=False),
        env={**os.environ, "PYTHONPATH": str(CODE_ROOT / "src")},
        check=True,
    )
    results = []
    for item, spec, frontend in zip(items, specs, frontends):
        mid = item["material_id"]
        raw = json.loads((folder / backend / mid / "result.json").read_text())
        if raw.get("error"):
            results.append({"material_id": mid, "status": "failed", "error": raw["error"]})
            continue
        try:
            phones = [
                {
                    **p,
                    "start": p["start"] + item["selection"]["start"],
                    "end": p["end"] + item["selection"]["start"],
                }
                for p in target_phones(raw, spec, backend)
            ]
            measured = {
                "version": identity("force-fa-v1", raw),
                "clock": "asset",
                "backend": backend,
                "input_selection": item["selection"],
                "input_descriptor_signature": item["asset_signature"],
                "annotation_id": item["cue_id"],
                "phones": phones,
                "mora": frontend["mora"],
                "g2p": frontend,
                "frontend_version": payload["frontend_version"],
                "dictionary_version": payload["dictionary"]["version"],
                "alignment_text_version": item["alignment"]["version"],
                "audio_lineage": {
                    "audio_path": str(pcm(item["asset"])),
                    "audio_sha256": item["asset"].get("sha256"),
                    "window_start": 0,
                    "window_end": item["selection"]["end"] - item["selection"]["start"],
                    "input_variant": item["asset"]["role"],
                },
                "raw_output": str(folder / backend / mid / "result.json"),
                "verified": False,
                "flags": ["unverified_alignment"],
            }
            with connect() as db, db:
                db.execute("BEGIN IMMEDIATE")
                status = db.execute("SELECT status FROM operation_jobs WHERE id=?", (jid,)).fetchone()
                if status and status[0] == "cancelled":
                    raise ValueError("任务已取消")
                rid = timeline.add_analysis(
                    db,
                    backend,
                    identity(raw, frontend),
                    measured,
                    selection=timeline.AssetSelection(**item["selection"]),
                    text_revision=item["alignment"]["version"],
                )
                current = current_text(db, item["cue_id"])
                same = current and current["version"] == item["alignment"]["version"]
                from .frontend_service import dictionary

                same = same and dictionary()["version"] == payload["dictionary"]["version"]
                owner_type, owner_id = item.get("owner_type", "sample"), item.get("owner_id", mid)
                if owner_type == "sample":
                    try:
                        same = same and identity(resolve(db, mid)) == item["asset_signature"]
                    except ValueError:
                        same = False
                stat = Path(item["asset"]["path"]).stat()
                same = same and (
                    not item.get("file_stat") or [stat.st_size, stat.st_mtime_ns] == item["file_stat"]
                )
                from .analysis_scope import covering

                inherited = (
                    covering(db, resolve(db, mid), backend) if owner_type == "sample" and same else None
                )
                if inherited and inherited["human"]:
                    db.execute(
                        "INSERT OR IGNORE INTO analysis_history VALUES(?,?,?,?)",
                        (owner_type, owner_id, backend, rid),
                    )
                    adopted = {"adopted": False, "reason": "human_timing"}
                else:
                    adopted = timeline.adopt_analysis(
                        db,
                        owner_type,
                        owner_id,
                        backend,
                        rid,
                        automatic=True,
                        expected_revision=item["head_revision"] if same else -1,
                    )
                if adopted["adopted"] and owner_type == "sample":
                    db.execute("DELETE FROM sample_records WHERE material_id=? AND backend=?", (mid, backend))
                    db.execute("UPDATE materials SET active_phone_backend=? WHERE id=?", (backend, mid))
                    from .analysis_scope import publish

                    publish(db, rid, item["cue_id"], automatic=True)
                results.append({"material_id": mid, "status": "ready", "run_id": rid, **adopted})
        except (ValueError, OSError) as exc:
            results.append({"material_id": mid, "status": "failed", "error": str(exc)})
    return {"results": results, "missing": payload["missing"]}
