"""Explicit offline indexing jobs. Querying imports neither FCPE nor ONNX."""

import json
import os
import subprocess
import time
from pathlib import Path

from .workspace import CODE_ROOT, DATA, identity, write_json


def prepare(db, sample_ids, asset_ids=None):
    from .pitch_search import VERSION, ensure
    from .sample_audio import resolve
    from .sound_features import model_info

    ensure(db)
    model = model_info()
    wanted = set(sample_ids)
    tracks = {}
    missing = []
    existing = {r["id"]: dict(r) for r in db.execute("SELECT * FROM pitch_tracks")}
    stored = {r[0]: json.loads(r[1]) for r in db.execute("SELECT * FROM sample_assets") if r[0] in wanted}
    sources = {r["id"]: dict(r) for r in db.execute("SELECT * FROM sources")}
    for sample in db.execute("SELECT id,source_id,start,end,audio_stream,cue_id FROM materials"):
        mid = sample["id"]
        if mid not in wanted:
            continue
        try:
            descriptor = stored.get(mid) or resolve(db, mid)
            if not descriptor.get("path") or not descriptor.get("sha256"):
                raise ValueError("索引需要已固定文件及可靠内容身份")
            path = Path(descriptor["path"])
            stat = path.stat()
            signature = identity(
                VERSION, descriptor["sha256"], descriptor.get("audio_stream", 0), model["sha256"]
            )
            full = tracks.setdefault(
                signature,
                {
                    "id": signature,
                    "signature": signature,
                    "path": str(path),
                    "sha256": descriptor["sha256"],
                    "audio_stream": descriptor.get("audio_stream", 0),
                    "file_stat": [stat.st_size, stat.st_mtime_ns],
                    "source_duration": sources[sample["source_id"]]["duration"],
                    "samples": [],
                    "assets": [],
                },
            )
            if signature in existing:
                full["index_path"] = existing[signature]["path"]
            full["samples"].append(
                {
                    "sample_id": mid,
                    "start": descriptor["start"],
                    "end": descriptor["end"],
                    "asset_signature": identity(descriptor),
                    "source_id": sample["source_id"],
                    "role": descriptor.get("role", "raw"),
                }
            )
        except (ValueError, OSError) as e:
            missing.append({"sample_id": mid, "error": str(e)})
    for aid in dict.fromkeys(asset_ids or []):
        try:
            row = db.execute("SELECT * FROM sound_assets WHERE id=?", (aid,)).fetchone()
            if not row:
                raise ValueError("声音资产不存在")
            descriptor = json.loads(row["descriptor"])
            path = Path(descriptor["path"])
            stat = path.stat()
            if not descriptor.get("sha256"):
                raise ValueError("声音资产缺少内容指纹")
            signature = identity(
                VERSION, descriptor["sha256"], descriptor.get("audio_stream", 0), model["sha256"]
            )
            full = tracks.setdefault(
                signature,
                {
                    "id": signature,
                    "signature": signature,
                    "path": str(path),
                    "sha256": descriptor["sha256"],
                    "audio_stream": descriptor.get("audio_stream", 0),
                    "file_stat": [stat.st_size, stat.st_mtime_ns],
                    "source_duration": sources[row["source_id"]]["duration"],
                    "samples": [],
                    "assets": [],
                },
            )
            if signature in existing:
                full["index_path"] = existing[signature]["path"]
            full["assets"].append(
                {
                    "asset_id": aid,
                    "start": descriptor["start"],
                    "end": descriptor["end"],
                    "source_id": row["source_id"],
                    "role": descriptor.get("role", "raw"),
                }
            )
        except (ValueError, OSError, KeyError) as e:
            missing.append({"asset_id": aid, "error": str(e)})
    return {"tracks": list(tracks.values()), "missing": missing, "model": model, "version": VERSION}


def run(db, payload, jid):
    from .inference_runtime import python_path
    from .pitch_search import ensure
    from .sample_audio import resolve

    ensure(db)
    inputs = prepare(db, payload.get("ids", []), payload.get("asset_ids"))
    db.commit()
    folder = DATA / "jobs"
    folder.mkdir(parents=True, exist_ok=True)
    request = folder / (jid + "-pitch-index.json")
    output = folder / (jid + "-pitch-index.result.json")
    write_json(request, inputs)
    subprocess.run(
        [str(python_path()), str(CODE_ROOT / "scripts/pitch_index_worker.py"), str(request), str(output)],
        env={**os.environ, "PYTHONPATH": str(CODE_ROOT / "src")},
        check=True,
    )
    results = json.loads(output.read_text())
    indexed = 0
    for track in results["tracks"]:
        if track.get("error"):
            continue
        with db:
            db.execute(
                "INSERT OR REPLACE INTO pitch_tracks VALUES(?,?,?,?,?,?)",
                (
                    track["id"],
                    track["signature"],
                    track["index_path"],
                    track["frames"],
                    json.dumps({k: v for k, v in track.items() if k != "samples"}),
                    time.time(),
                ),
            )
            for asset in track.get("assets", []):
                db.execute(
                    "INSERT OR REPLACE INTO pitch_asset_ranges VALUES(?,?,?,?,?,?)",
                    (
                        asset["asset_id"],
                        track["id"],
                        asset["start"],
                        asset["end"],
                        asset["source_id"],
                        asset["role"],
                    ),
                )
            for sample in track["samples"]:
                try:
                    if identity(resolve(db, sample["sample_id"])) != sample["asset_signature"]:
                        continue
                except (ValueError, OSError):
                    continue
                db.execute(
                    "INSERT OR REPLACE INTO pitch_sample_ranges VALUES(?,?,?,?,?,?,?)",
                    (
                        sample["sample_id"],
                        track["id"],
                        sample["start"],
                        sample["end"],
                        sample["asset_signature"],
                        sample["source_id"],
                        sample["role"],
                    ),
                )
                indexed += 1
    return {
        "indexed_samples": indexed,
        "tracks": [{k: v for k, v in t.items() if k != "samples"} for t in results["tracks"]],
        "missing": inputs["missing"],
    }


def selection_scope(db, body):
    from .sample_scope import ids

    if body.get("mode", "samples") == "samples":
        return {"ids": ids(db, body.get("scope"))}
    if body["mode"] != "sources":
        raise ValueError("音高检索模式应为 samples/sources")
    from .pitch_scope import source_assets, tag_ranges

    return {
        "asset_ids": [
            r["id"] for r in source_assets(db, body) if tag_ranges(db, r, 0.01, body.get("scope") or {})
        ]
    }
