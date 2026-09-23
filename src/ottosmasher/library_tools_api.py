"""Core saved views, acoustic metrics and source exclusions."""

import json

from fastapi import APIRouter

from . import timbre_features as tf
from .cue_operations import database
from .workspace import DATA, identity

router = APIRouter(prefix="/api/library-tools")


def ensure_views(db):
    db.execute("CREATE TABLE IF NOT EXISTS saved_views(id TEXT PRIMARY KEY,name TEXT,payload TEXT)")


@router.get("/views")
def views():
    with database() as db:
        ensure_views(db)
        return [
            {**dict(r), "scope": json.loads(r["payload"])}
            for r in db.execute("SELECT * FROM saved_views ORDER BY name")
        ]


@router.post("/views")
def view(body: dict):
    with database() as db:
        ensure_views(db)
        key = identity(body["name"])
        db.execute(
            "INSERT OR REPLACE INTO saved_views VALUES(?,?,?)", (key, body["name"], json.dumps(body["scope"]))
        )
        db.commit()
        return {"id": key}


@router.post("/filter")
def catalog_filter(body: dict):
    from .sample_scope import search

    with database() as db:
        return search(db, **body)


@router.get("/features/{mid}")
def features(mid: str):
    with database() as db:
        return tf.read(db, mid)


@router.get("/openings/state")
def openings_state():
    from .source_regions import listing

    with database() as db:
        return {
            "regions": listing(db),
            "scans": [
                json.loads(p.read_text())
                for p in sorted(
                    (DATA / "opening-scans").glob("*.json"), key=lambda p: p.stat().st_mtime, reverse=True
                )[:20]
            ],
        }


@router.post("/openings/scan")
def openings_scan(body: dict):
    from .opening_scan import reference
    from .operation_jobs import submit

    path = reference(body.pop("image"))
    return submit("opening-scan", {**body, "reference_path": str(path)})


@router.post("/openings/confirm")
def openings_confirm(body: dict):
    from .source_regions import confirm

    with database() as db:
        sid = body["source_id"]
        from .source_regions import media_fingerprint

        if body.get("source_fingerprint") and media_fingerprint(db, sid) != body["source_fingerprint"]:
            raise ValueError("原片已更换，请重新搜索")
        return confirm(db, sid, body["start"], body["end"], body.get("kind", "op"), body.get("evidence"))


@router.post("/openings/remove")
def openings_remove(body: dict):
    from .source_regions import remove

    with database() as db:
        remove(db, body["id"])
        # Retained raw subtitles can register again after undo. Never delete human annotations.
        from .materials import sync_cues

        sync_cues(db)
        return {"ok": True}


@router.post("/openings/sources")
def openings_sources(body: dict):
    from .catalog import probe
    from .sound_assets import source

    with database() as db:
        results = []
        for path in body["paths"]:
            meta = probe(path)
            tracks = [s for s in meta["streams"] if s["codec_type"] == "audio"]
            preferred = [s for s in tracks if s.get("tags", {}).get("language") in ("ja", "jpn")]
            if not tracks or not any(s["codec_type"] == "video" for s in meta["streams"]):
                raise ValueError("请选择有声音的视频原片")
            selected = (preferred or tracks)[0]["index"]
            d = source(db, {"path": path, "audio_stream": body.get("audio_stream", selected)})
            results.append({"id": d["source_id"], "title": d["title"]})
        return results


@router.get("")
def definitions():
    return {"feature_definitions": [{**d, "producer": "otto.dsp"} for d in tf.definitions()]}


@router.post("/features")
def prepare_features(body: dict):
    from .operation_jobs import submit
    from .sample_scope import ids

    with database() as db:
        selected = ids(db, body.get("scope", {}))
    return submit("acoustic-features", {"material_ids": selected})


@router.get("/runtime")
def runtime_check():
    from .inference_runtime import check

    return check()
