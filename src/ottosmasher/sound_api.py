"""Source stem separation and synchronized playback."""
from fastapi import APIRouter

from . import sound_assets as a
from . import sound_models as models
from . import source_separation as lab
from .cue_operations import database

router = APIRouter(prefix="/api/sound")

@router.get("/tracks")
def tracks(source_id: str | None = None):
    from .sound_tracks import listing

    with database() as db:
        return listing(db, source_id)


@router.post("/track-preview")
def track_preview(body: dict):
    """Reuse the cutter's continuous-media path, preserving selected stem and source clock."""
    from .sample_ops import reference, source_browser

    with database() as db:
        row = source_browser(db, body["source_id"])
        start, end = float(body["start"]), float(body["end"])
        role = "artifact:" + body["artifact_id"] if body.get("artifact_id") else "raw"
        result = reference(
            db, row["id"], start, end, role, row["audio_stream"], native=body.get("native", False)
        )
        result["subtitles"] = [
            dict(r)
            for r in db.execute(
                "SELECT id,start,end,original FROM cues WHERE source_id=? AND end>? AND start<? ORDER BY start",
                (row["source_id"], start, end),
            )
        ]
        return result


@router.get("/info")
def info():
    with database() as db:
        a.ensure(db)
        return {
            "models": models.statuses(),
            "sources": [dict(r) for r in db.execute("SELECT id,title,duration FROM sources ORDER BY title")],

        }


@router.post("/run/{action}")
def run(action: str, body: dict):
    with database() as db:
        return lab.submit(db, action, body)
