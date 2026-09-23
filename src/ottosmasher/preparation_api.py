"""Thin GUI adapter for source preparation and bounded production tasks."""

from fastapi import APIRouter

from . import source_preparation as prep
from .cue_operations import database

router = APIRouter(prefix="/api/preparation")


@router.get("")
def listing():
    with database() as db:
        return {"sources": prep.listing(db)}


@router.post("/delete")
def delete_sources(body: dict):
    from .source_deletion import remove_sources

    with database() as db, db:
        return {"deleted": remove_sources(db, body["ids"])}


@router.post("/register")
def register(body: dict):
    with database() as db:
        return prep.register(db, body["paths"])


@router.post("/configure")
def configure(body: dict):
    with database() as db:
        return prep.configure(db, **body)


@router.post("/preview")
def preview(body: dict):
    with database() as db:
        return prep.preview(db, body["source_id"])


@router.post("/import")
def ingest(body: dict):
    with database() as db:
        return prep.ingest(db, body["source_id"], body["token"])


@router.post("/analysis")
def analysis(body: dict):
    from . import preparation_jobs
    from .operation_jobs import submit

    with database() as db:
        report = preparation_jobs.inspect(
            db, **{k: body[k] for k in ("source_ids", "material_ids", "backends", "vocal_model") if k in body}
        )
        if not body.get("run"):
            return report
        if not report["total"]:
            raise ValueError("所选范围没有可处理的已导入台词")
        return submit(
            "speech-prepare",
            {k: report[k] for k in ("material_ids", "backends", "vocal_model")},
        )


@router.post("/track-preview")
def track_preview(body: dict):
    from .media_operations import proxy

    with database() as db:
        s = db.execute("SELECT * FROM sources WHERE id=?", (body["source_id"],)).fetchone()
        if not s:
            raise ValueError("原片不存在")
        start = max(0, min(float(body.get("start", 30)), s["duration"] - 0.1))
        stream = int(body.get("audio_stream", s["audio_stream"]))
        import json

        if stream not in [
            x["index"] for x in json.loads(s["metadata"])["streams"] if x["codec_type"] == "audio"
        ]:
            raise ValueError("音轨不存在")
        p = proxy(s["path"], start, min(start + 12, s["duration"]), stream)
        return {"url": "/api/helper/proxies/" + p["key"]}


@router.post("/import-direct")
def direct_import(body: dict):
    with database() as db:
        if "import_speakers" in body:
            prep.configure(db, body["source_id"], import_speakers=body["import_speakers"])
        # The explicit import click also acknowledges proceeding without unmarked OP/ED.
        current = prep.preview(db, body["source_id"])
        if current["op_review"] == "pending" or body.get("op_review"):
            prep.configure(db, body["source_id"], op_review=body.get("op_review", "skipped"))
        p = prep.preview(db, body["source_id"])
        return prep.ingest(db, body["source_id"], p["token"])


@router.post("/music-markers")
def music_markers(body: dict):
    from .opening_subtitles import run

    with database() as db:
        return run(db, body["source_ids"], body.get("apply", True))
