"""Local HTTP adapter. Domain operations stay usable without this module."""

from pathlib import Path

from fastapi import APIRouter, Query
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

from . import material_operations as ops
from . import materials as m
from . import media_operations as media
from .cue_operations import database
from .workspace import DATA, ROOT

router = APIRouter(prefix="/api/helper")


@router.get("/info")
def info():
    with database() as db:
        return {
            "version": "0.11.0",
            "build_id": __import__("os").environ.get("OTTO_BUILD_ID", "development"),
            "root": str(ROOT),
            "workspace": str(DATA),
            "collections": [dict(r) for r in db.execute("SELECT * FROM collections ORDER BY name")],
            "sources": [dict(r) for r in db.execute("SELECT id,title FROM sources ORDER BY title")],
            "tags": [r[0] for r in db.execute("SELECT DISTINCT tag FROM material_tags ORDER BY tag")],
            "total": db.execute("SELECT COUNT(*) FROM materials").fetchone()[0],
        }


@router.get("/materials")
def search(
    q: str = "",
    collection: str | None = None,
    source_id: str | None = None,
    tags: list[str] = Query([]),  # noqa: B008 - FastAPI query declaration
    analyzed_only: bool = False,
    offset: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=200),
):
    with database() as db:
        return m.search(
            db,
            text=q,
            collection=collection or None,
            source_id=source_id or None,
            tags=tags,
            analyzed_only=analyzed_only,
            offset=offset,
            limit=limit,
        )


class Register(BaseModel):
    path: str
    copy_file: bool = Field(False, alias="copy")
    audio_stream: int | None = None


@router.post("/register")
def register(body: Register):
    with database() as db:
        return m.register_file(db, **body.model_dump(by_alias=True))


@router.post("/probe")
def probe(body: Register):
    from .catalog import probe

    return probe(Path(body.path).expanduser().resolve(strict=True))


class Selection(BaseModel):
    source_id: str
    start: float = Field(allow_inf_nan=False)
    end: float = Field(allow_inf_nan=False)
    title: str = ""
    audio_stream: int | None = None
    cue_id: str | None = None
    scope_id: str | None = None
    analysis_kind: str | None = None


@router.post("/selection")
def selection(body: Selection):
    with database() as db:
        return m.save_range(db, **body.model_dump())


@router.get("/materials/{mid}")
def detail(mid: str):
    with database() as db:
        return m.get(db, mid)


@router.post("/materials/{mid}/edit")
def edit(mid: str, body: dict):
    with database() as db:
        return m.edit(db, mid, **body)


@router.post("/collections")
def collection(body: dict):
    with database() as db:
        return m.collection(db, body["name"])


@router.post("/materials/{mid}/collection")
def member(mid: str, body: dict):
    with database() as db:
        return m.membership(db, mid, body["collection_id"], body.get("present", True))




@router.get("/materials/{mid}/binding")
def binding(mid: str, kind: str = "narabas"):
    with database() as db:
        return m.binding(db, mid, kind)


@router.post("/materials/{mid}/plans")
def plans(mid: str, body: dict):
    with database() as db:
        return ops.plans(db, mid, body)


@router.post("/materials/{mid}/preview")
def preview(mid: str, body: dict):
    with database() as db:
        return ops.preview(db, mid, body)


@router.post("/materials/{mid}/export")
def export(mid: str, body: dict):
    with database() as db:
        return ops.export(db, mid, **body)


@router.post("/materials/{mid}/reaper")
def reaper(mid: str, body: dict):
    with database() as db:
        return ops.reaper(db, mid, body)


@router.get("/materials/{mid}/media")
def raw(mid: str, version_id: str | None = None):
    with database() as db:
        r = m.get(db, mid)
        path = r["path"]
        if version_id:
            v = next((v for v in r["versions"] if v["id"] == version_id), None)
            if not v:
                raise ValueError("版本不属于此素材")
            path = v["path"]
    if not Path(path).is_file():
        raise ValueError("原媒体文件缺失")
    return FileResponse(path)


@router.get("/materials/{mid}/waveform")
def waveform(
    mid: str,
    start: float | None = None,
    end: float | None = None,
    bins: int = 4000,
    audio_stream: int | None = None,
    version_id: str | None = None,
):
    with database() as db:
        r = m.get(db, mid)
    if version_id:
        v = next((v for v in r["versions"] if v["id"] == version_id), None)
        if not v:
            raise ValueError("版本不属于此素材")
        return media.waveform(v["path"], bins=bins)
    return media.waveform(
        r["path"],
        r["start"] if start is None else start,
        r["end"] if end is None else end,
        r["audio_stream"] if audio_stream is None else audio_stream,
        bins,
    )


@router.post("/materials/{mid}/proxy")
def proxy(mid: str, body: dict):
    with database() as db:
        r = m.get(db, mid)
    start = float(body.get("start", max(0, r["start"] - 10)))
    end = float(body.get("end", min(r["source_duration"], r["end"] + 10)))
    p = media.proxy(r["path"], start, end, body.get("audio_stream", r["audio_stream"]))
    return {**p, "url": f"/api/helper/proxies/{p['key']}"}


@router.get("/proxies/{key}")
def proxy_file(key: str):
    import re

    if not re.fullmatch("[a-f0-9]{24}", key):
        raise ValueError("无效预览标识")
    return FileResponse(DATA / "cache" / "proxies" / f"{key}.mp4")


@router.get("/materials/{mid}/audition")
def audition(mid: str):
    with database() as db:
        r = m.get(db, mid)
    from .workspace import identity

    key = identity("material-audition", r["id"], r["fingerprint"], r["start"], r["end"])
    p = media.cut(
        r["path"], r["start"], r["end"], r["audio_stream"], output=DATA / "cache" / "audition" / f"{key}.wav"
    )
    return FileResponse(p["path"], media_type="audio/wav")


@router.get("/jobs")
def jobs():
    from .operation_jobs import listing

    return listing()


@router.post("/jobs")
def submit_job(body: dict):
    from .operation_jobs import submit

    return submit(body["operation"], body.get("payload", {}))


@router.post("/jobs/{jid}/cancel")
def cancel_job(jid: str):
    from .operation_jobs import cancel

    return cancel(jid)


@router.post("/jobs/{jid}/retry")
def retry_job(jid: str):
    from .operation_jobs import retry

    return retry(jid)


@router.get("/jobs/{jid}/log")
def job_log(jid: str):
    from .operation_jobs import read_log

    return {"text": read_log(jid)}


@router.get("/materials/{mid}/context")
def context(mid: str, start: float, end: float):
    with database() as db:
        r = m.get(db, mid)
        return [
            dict(x)
            for x in db.execute(
                "SELECT id,start,end,original FROM cues c WHERE source_id=? AND end>? AND start<? AND NOT EXISTS(SELECT 1 FROM cue_subtitle_versions cv JOIN subtitle_versions sv ON sv.id=cv.version_id WHERE cv.cue_id=c.id AND sv.selected=0) ORDER BY start",
                (r["source_id"], start, end),
            )
        ]


@router.get("/visualizations/{key}/detail")
def visualization_detail(key: str, start: float, end: float):
    from .media_visualization import detail

    return detail(key, start, end)


@router.get("/visualizations/{key}/spectrum")
def visualization_spectrum(key: str):
    from .media_visualization import spectrum_path

    return FileResponse(spectrum_path(key), media_type="application/json")


@router.get("/streams/{key}/index.m3u8")
def stream_playlist(key: str):
    from fastapi.responses import Response

    from .stream_preview import playlist

    return Response(playlist(key), media_type="application/vnd.apple.mpegurl")


@router.get("/streams/{key}/waveform")
def stream_waveform(key: str):
    from .stream_preview import waveform

    return waveform(key)


@router.get("/streams/{key}/{index}.ts")
def stream_segment(key: str, index: int):
    # Read before returning so concurrent cache pruning cannot invalidate FileResponse.
    from fastapi.responses import Response

    from .stream_preview import segment_bytes

    return Response(segment_bytes(key, index), media_type="video/mp2t")


@router.get("/native-player/{key}")
def native_player_descriptor(key: str):
    from .native_player import load

    return load(key)


@router.get("/native-player/{key}/waveform")
def native_player_waveform(key: str):
    from .native_player import waveform

    return waveform(key)
