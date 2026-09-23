"""Desktop adapter for unified derived samples."""

from fastapi import APIRouter, Query
from fastapi.responses import FileResponse, Response

from . import materials as m
from . import sample_analysis as analysis
from . import sample_audio as audio
from . import sample_catalog as c
from . import sample_ops as ops
from . import sample_rhythm as rhythm
from .cue_operations import database
from .workspace import DATA

router = APIRouter(prefix="/api/samples")


@router.get("/info")
def info():
    with database() as db:
        return {
            "folders": [
                dict(x)
                for x in db.execute(
                    "SELECT * FROM sample_folders f WHERE batch_id IS NULL OR EXISTS(SELECT 1 FROM materials m WHERE m.folder_id=f.id AND m.status<>'discarded') ORDER BY batch_id IS NOT NULL,name"
                )
            ],
            "backends": list(c.BACKENDS),
            "sources": [dict(x) for x in db.execute("SELECT id,title FROM sources")],
            "tags": [x[0] for x in db.execute("SELECT DISTINCT tag FROM material_tags ORDER BY tag")],
            "total": db.execute("SELECT COUNT(*) FROM materials WHERE status<>'discarded'").fetchone()[0],
        }


@router.get("")
def search(
    q: str = "",
    folder_id: str | None = None,
    pool: str = "library",
    tags: list[str] = Query([]),  # noqa: B008 - FastAPI parameter
    starred: bool = False,
    offset: int = 0,
):
    with database() as db:
        ids = m.query_ids(db, text=q, tags=tags)
        rows = []
        for mid in ids:
            r = dict(
                db.execute(
                    "SELECT id,status,pool,folder_id,starred FROM materials WHERE id=?", (mid,)
                ).fetchone()
            )
            if r["status"] == "discarded" or (folder_id and r["folder_id"] != folder_id):
                continue
            if not folder_id and (r["status"] == "pending" or (pool != "all" and r["pool"] != pool)):
                continue
            if starred and not r["starred"]:
                continue
            rows.append(mid)
        return {
            "total": len(rows),
            "results": [m.get(db, x) for x in rows[max(0, offset) : max(0, offset) + 50]],
        }


@router.post("/folders")
def folder(body: dict):
    with database() as db:
        return c.folder(db, body["name"], body.get("id"))


@router.post("/delete")
def delete_samples(body: dict):
    from .sample_deletion import remove

    with database() as db, db:
        return {"deleted": remove(db, body["ids"])}


@router.post("/folders/delete")
def delete_folders(body: dict):
    from .sample_deletion import folders

    with database() as db, db:
        folders(db, body["ids"])
        return {"ok": True}


@router.post("/review")
def review(body: dict):
    with database() as db:
        return {"ids": c.review(db, body["ids"], body.get("accept", True))}


@router.post("/speech-query")
def speech_query(body: dict):
    from .speech_query import query
    with database() as db:
        return query(db, body)


@router.post("/speech-hit")
def speech_hit(body: dict):
    from .speech_hits import action
    with database() as db:
        return action(db, body)


@router.get("/speech-hit-audio/{key}")
def speech_hit_audio(key: str):
    import json
    import re
    if not re.fullmatch(r"[a-f0-9]{24}", key): raise ValueError("无效试听标识")
    path = json.loads((DATA / "cache/speech-hits" / (key + ".json")).read_text())["path"]
    return FileResponse(path, media_type="audio/wav")


@router.post("/phone-models")
def phone_models(body: dict):
    from .model_selection import inspect, switch
    with database() as db:
        result = (switch if body.get("action") in ("switch", "analyze") else inspect)(db, body["ids"], body["backend"])
    if body.get("action") == "analyze":
        from .operation_jobs import submit
        missing = [r["id"] for r in result["missing"] + result["failed"]]
        if missing:
            result["job"] = submit("speech-prepare", {"material_ids": missing, "backends": [body["backend"]], "switch_backend": body["backend"]})
    return result


@router.post("/rhythm")
def rhythm_search(body: dict):
    with database() as db:
        return rhythm.search(db, body)


@router.post("/rhythm-batch")
def rhythm_batch(body: dict):
    with database() as db:
        return ops.batch_search(db, body["query"], body.get("target_folder", "speech"))


@router.post("/source-browser")
def source_browser(body: dict):
    with database() as db:
        return ops.source_browser(db, body["source_id"])


@router.post("/register")
def register(body: dict):
    with database() as db:
        return ops.register(db, **body)


@router.post("/batch-flatten")
def batch_flatten(body: dict):
    with database() as db:
        return ops.batch_flatten(db, **body)


@router.get("/reference-files/{key}")
def reference_file(key: str):
    import re

    if not re.fullmatch("[a-f0-9]{24}", key):
        raise ValueError("无效预览标识")
    return FileResponse(DATA / "sample-cache" / (key + ".wav"), media_type="audio/wav")


@router.get("/{mid}")
def get(mid: str):
    with database() as db:
        return m.get(db, mid)


@router.post("/{mid}/preferences")
def preferences(mid: str, body: dict):
    with database() as db:
        c.preferences(db, mid, **body)
        if "analysis_settings" in body:
            analysis.prepare(db, mid)
        return m.get(db, mid)


@router.post("/{mid}/prepare")
def prepare(mid: str):
    with database() as db:
        return analysis.prepare(db, mid)


@router.get("/{mid}/analysis")
def detail(mid: str, part: str = "full"):
    with database() as db:
        record = analysis.ready(db, mid)
        if part == "display":
            return {k: record[k] for k in ("signature", "backend", "view", "frames", "root_cue")} | {"analysis": {k:record["analysis"].get(k) for k in ("phones","window_start","window_end","version")}}
        if part == "features": return {"features": record["features"]}
        return record


@router.get("/{mid}/thumbnail")
def thumbnail(mid: str):
    from .sample_thumbnails import thumbnail as make

    with database() as db:
        path = make(db, mid)
    return (
        FileResponse(path, media_type="image/jpeg", headers={"Cache-Control": "private, max-age=3600"})
        if path
        else Response(status_code=204)
    )


@router.post("/{mid}/audition")
def audition_source(mid: str, body: dict):
    import json

    with database() as db:
        # Resolve just the selected sound, not all four optional alternatives.
        asset = audio.resolve(db, mid, body.get("role"))
        if body.get("native"):
            from .native_player import register

            source = db.execute(
                "SELECT s.path,s.metadata FROM sources s JOIN materials m ON m.source_id=s.id WHERE m.id=?",
                (mid,),
            ).fetchone()
            streams = (
                json.loads(source["metadata"]).get("streams", [])
                if source and asset.get("path") == source["path"]
                else [{"index": asset.get("audio_stream", 0), "codec_type": "audio"}]
            )
            if asset.get("path"):
                return register(asset["path"], asset["start"], asset["end"], asset, streams)
        return {"url": f"/api/samples/{mid}/audio?role={body.get('role') or 'selected'}", "audio_source": asset["role"]}


@router.get("/{mid}/audio-capabilities")
def audio_capabilities(mid: str):
    from .sample_acoustics import capabilities

    with database() as db:
        return capabilities(db, mid)


@router.get("/{mid}/acoustics")
def acoustics(mid: str, role: str = "selected"):
    from .sample_acoustics import cached

    with database() as db:
        return cached(db, mid, role)


@router.post("/{mid}/select")
def select(mid: str, body: dict):
    with database() as db:
        return ops.select(db, mid, **body)


@router.post("/{mid}/plans")
def plans(mid: str, body: dict):
    with database() as db:
        if not body.get("plan_id"):
            try:
                analysis.ready(db, mid)
            except ValueError:
                # Explicit audition may rebuild derived features, never run a model.
                analysis.build(db, mid, m.get(db, mid)["active_phone_backend"])
        return rhythm.plans(db, mid, body.get("bpm"), body.get("plan_id"))


@router.post("/{mid}/preview")
def preview(mid: str, body: dict):
    with database() as db:
        return ops.preview(db, mid, body)


@router.post("/{mid}/export")
def export(mid: str, body: dict):
    with database() as db:
        result = ops.export(db, mid, body.get("plan_id"), body.get("video", False), body.get("role"))
        from .ui_catalog import place_export

        return place_export(db, result)


@router.post("/{mid}/flatten")
def flatten(mid: str, body: dict):
    from .operation_jobs import submit

    return submit("flatten", {"material_id": mid, **body})


@router.post("/{mid}/reaper")
def reaper(mid: str, body: dict):
    from .reaper_export import export_reaper

    with database() as db:
        record, plan = rhythm.load(db, mid, body["plan_id"])
        return export_reaper(
            record["cue"],
            record["analysis"],
            plan,
            "vocals",
            body.get("directory"),
            body.get("origin", "first_onset"),
        )


@router.get("/{mid}/audio")
def media(mid: str, role: str | None = None):
    with database() as db:
        path = audio.pcm(audio.resolve(db, mid, role))
    return FileResponse(path, media_type="audio/wav")


@router.get("/{mid}/waveform")
def waveform(mid: str, role: str | None = None):
    from .media_operations import waveform

    with database() as db:
        a = audio.resolve(db, mid, role)
    if a.get("path"):
        return waveform(a["path"], a["start"], a["end"], a.get("audio_stream", 0))
    path = audio.pcm(a)
    return waveform(path, 0, a["end"] - a["start"])


@router.post("/{mid}/reference")
def reference(mid: str, body: dict):
    with database() as db:
        return ops.reference(db, mid, **body)


@router.post("/{mid}/source-selection")
def source_selection(mid: str, body: dict):
    with database() as db:
        return ops.source_selection(db, mid, **body)


@router.post("/{mid}/separate")
def separate(mid: str, body: dict):
    from .operation_jobs import submit

    return submit("separate", {"material_id": mid, **body})


@router.post("/{mid}/original-clicks")
def original_clicks(mid: str, body: dict):
    from .audition import preview

    with database() as db:
        r = analysis.ready(db, mid)
    return preview(
        r["cue"], r["analysis"], r["view"], "overlay" if body.get("overlay") else "rhythm", "vocals"
    )


@router.post("/{mid}/analyze")
def analyze(mid: str, body: dict):
    with database() as db:
        return ops.start_analysis(db, mid, **body)


@router.post("/{mid}/source-flatten")
def source_flatten(mid: str, body: dict):
    with database() as db:
        return ops.source_flatten(db, mid, **body)


@router.get("/{mid}/native-alignment")
def native_alignment(mid: str):
    from .native_alignment import listing
    with database() as db:
        return listing(db, mid)


@router.post("/{mid}/native-alignment")
def align_native(mid: str, body: dict):
    from .native_alignment import MODELS
    from .operation_jobs import submit
    if body.get("model") not in MODELS:
        raise ValueError("未知字符/音节模型")
    return submit("native-alignment", {"model":body["model"], "material_ids":[mid]})


@router.post("/{mid}/native-alignment/play")
def native_alignment_play(mid: str, body: dict):
    from .native_alignment import play
    with database() as db:
        value = play(db,mid,body['model'],body['index'],body.get('native',False))
    if 'path' in value:
        return {'url':'/api/samples/'+mid+'/native-alignment/audio?model='+body['model']+'&index='+str(body['index'])}
    return value


@router.get("/{mid}/native-alignment/audio")
def native_alignment_audio(mid: str, model: str, index: int):
    from .native_alignment import play
    with database() as db:
        return FileResponse(play(db,mid,model,index)['path'],media_type='audio/wav')
