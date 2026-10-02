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


@router.get("/visual-file/{key}")
def visual_file(key: str, native: bool = False):
    from .visual_media import load, browser_file

    return FileResponse(load(key)["path"] if native else browser_file(key))


@router.get("/visual-native/{key}")
def visual_native(key: str):
    from .visual_media import load

    data = load(key)
    return {
        "path": data["path"],
        "start": 0,
        "end": data.get("duration") or None,
        "audio_path": None,
        "aid": "no",
        "audio_delay": 0,
    }


@router.get("/{mid}/visual")
def visual_binding(mid: str, native: bool = False, role: str | None = None):
    from .visual_media import playback

    with database() as db:
        return playback(db, mid, native, role)


@router.get("/source/{sid}/visual")
def source_visual_binding(sid: str, native: bool = False):
    from .visual_media import playback

    with database() as db:
        parent = ops.source_browser(db, sid)
        return {"material_id": parent["id"], "binding": playback(db, parent["id"], native)}


@router.post("/selection/resolve")
def asset_selection(body: dict):
    from .selection_ops import from_sample, from_source

    with database() as db:
        selection = (
            from_source(
                db,
                body["material_id"],
                body["start"],
                body["end"],
                body.get("role", "raw"),
                body.get("audio_stream"),
            )
            if body.get("clock") == "source"
            else from_sample(db, body["material_id"], body.get("start"), body.get("end"), body.get("role"))
        )
        db.commit()
        return selection.json()


@router.post("/selection/save")
def save_asset_selection(body: dict):
    from .selection_ops import save

    with database() as db:
        return save(db, **body)


@router.post("/selection/preview")
def preview_asset_selection(body: dict):
    from .selection_ops import resolve
    from .workspace import identity

    with database() as db:
        _, descriptor = resolve(db, body["selection"])
        audio.pcm(descriptor)
        return {"url": "/api/samples/reference-files/" + identity("sample-pcm-v1", descriptor)}


@router.post("/selection/name")
def selection_name(body: dict):
    from .selection_ops import resolve
    from .selection_names import suggest

    with database() as db:
        selected, descriptor = resolve(db, body["selection"])
        sid = db.execute("SELECT source_id FROM sound_assets WHERE id=?", (selected.asset_id,)).fetchone()[0]
        from .track_roles import nature

        return {
            "title": suggest(db, sid, descriptor, 0, selected.end - selected.start, selection=selected),
            "nature": nature(db, selected.asset_id),
        }


@router.post("/pitch-hit/selection")
def pitch_hit_selection(body: dict):
    from .pitch_search import hit_selection

    with database() as db:
        selected = hit_selection(db, **body)
        db.commit()
        return selected.json()


@router.post("/selection/external-import-preview")
def preview_external_import(body: dict):
    from .selection_ops import import_range
    with database() as db:
        selected, asset, path, info = import_range(db, body['selection'], body['path'])
        return {'duration': info.duration, 'selection': selected.json(), 'root_knots': asset['root_knots']}


@router.post("/selection/external-import")
def reimport_selection(body: dict):
    from .selection_ops import external_import

    with database() as db:
        return external_import(db, **body)


@router.post("/selection/descendants")
def selection_descendants(body: dict):
    from .selection_ops import descendants

    with database() as db:
        return descendants(db, **body)


@router.post("/selection/separate")
def separate_selection(body: dict):
    from .operation_jobs import submit

    return submit("separate", body)


@router.post("/selection/flatten-context")
def flatten_context(body: dict):
    from .selection_ops import separation_snapshot
    from .workspace import identity
    import numpy as np
    import soundfile as sf
    with database() as db:
        context = separation_snapshot(db, body)
        descriptor = context['input_asset']
        path = audio.pcm(descriptor)
        y, rate = sf.read(path, always_2d=True, dtype='float32')
        mono = np.max(np.abs(y), axis=1)
        size = max(1, int(np.ceil(len(mono) / 1800)))
        peaks = [float(np.max(mono[i:i+size])) for i in range(0, len(mono), size)]
        db.commit()
        return {'selection': context['selection'], 'asset': descriptor,
                'title': context['suggested_title'], 'duration': len(y) / rate,
                'peaks': [peaks], 'url': '/api/samples/reference-files/' + identity('sample-pcm-v1', descriptor)}


@router.post("/selection/flatten-preview")
def flatten_preview(body: dict):
    from .flatten_preview import preview
    with database() as db:
        return preview(db, **body)


@router.post("/selection/flatten")
def flatten_asset_selection(body: dict):
    from .operation_jobs import submit

    return submit("flatten", body)


@router.post("/selection/reanalyse")
def analyse_asset_selection(body: dict):
    from .reanalysis import submit_selection

    with database() as db:
        return submit_selection(db, **body)


@router.post("/pitch-query")
def pitch_query(body: dict):
    from .pitch_search import query

    with database() as db:
        return query(db, body)


@router.post("/pitch-index")
def pitch_index(body: dict):
    from .pitch_indexing import selection_scope
    from .operation_jobs import submit

    with database() as db:
        selected = selection_scope(db, body)
    return submit("pitch-index", selected)


@router.post("/pitch-query/parse")
def pitch_query_parse(body: dict):
    from .pitch_search import parse

    return {"rows": parse(body["text"])}


@router.post("/pitch-hit")
def pitch_hit(body: dict):
    import json
    import math
    from .workspace import identity
    from .pitch_search import ensure, validate_track

    with database() as db:
        ensure(db)
        row = db.execute("SELECT * FROM pitch_tracks WHERE id=?", (body["asset_id"],)).fetchone()
        if not row:
            raise ValueError("音高索引不存在")
        start, end = float(body["start"]), float(body["end"])
        if not all(math.isfinite(t) for t in (start, end)) or not 0 <= start < end <= row["frames"] * 0.01:
            raise ValueError("命中选区越界")
        data = validate_track(row)
        asset = {
            "path": data["path"],
            "sha256": data["sha256"],
            "audio_stream": data["audio_stream"],
            "start": start,
            "end": end,
            "role": "pitch_hit",
        }
        audio.pcm(asset)
        return {"url": "/api/samples/reference-files/" + identity("sample-pcm-v1", asset)}


@router.get("/frontend/dictionary")
def get_dictionary():
    from .frontend_service import dictionary

    return dictionary()


@router.post("/frontend/dictionary")
def set_dictionary(body: dict):
    from .frontend_service import save_dictionary

    return save_dictionary(body["text"], body["base_version"])


@router.post("/frontend/preview")
def frontend_preview(body: dict):
    from .frontend_service import batch

    return batch([body["text"]])[0]


@router.post("/edit/export")
def export_edit(body: dict):
    from .business_edits import export

    with database() as db:
        return export(db, body["objects"])


@router.post("/edit/promote-tags")
def promote_sample_tags(body: dict):
    from .business_edits import promote_tags

    with database() as db:
        result = promote_tags(db, **body)
        db.commit()
        return result


@router.post("/edit/new-annotation")
def new_annotation_edit(body: dict):
    from .business_edits import new_annotation

    with database() as db:
        return new_annotation(db, **body)


@router.post("/selection/annotations")
def selection_annotations(body: dict):
    from .asset_timeline import AssetSelection, annotations_for

    with database() as db:
        return annotations_for(db, AssetSelection(**body["selection"]))


@router.post("/selection/new-annotation")
def new_selection_annotation(body: dict):
    from .selection_ops import resolve
    from .business_edits import new_annotation

    with database() as db:
        selected, asset = resolve(db, body["selection"])
        sid = db.execute("SELECT source_id FROM sound_assets WHERE id=?", (selected.asset_id,)).fetchone()[0]
        knots = asset.get("root_knots")
        if not knots:
            raise ValueError("资产没有来源坐标")
        return new_annotation(
            db,
            sid,
            knots[0][1],
            knots[-1][1],
            kind=body.get("kind", "tag"),
            text=body.get("text", ""),
            tags=body.get("tags", []),
            scope=body.get("scope"),
        )


@router.post("/edit/preview")
def preview_edit(body: dict):
    from .business_edits import preview

    with database() as db:
        return preview(db, body)


@router.post("/edit/apply")
def apply_edit(body: dict):
    from .business_edits import apply

    with database() as db:
        return apply(db, body)


@router.post("/edit/undo")
def undo_edit(body: dict):
    from .business_edits import undo

    with database() as db:
        return undo(db, body.get("action_id"))


@router.post("/tags/validate")
def validate_tags(body: dict):
    from .tag_expression import parse, SyntaxError

    try:
        parse(body.get("expression", ""))
        return {"valid": True}
    except SyntaxError as e:
        return {"valid": False, "position": e.position, "error": str(e)}


@router.get("/info")
def info():
    from .ui_catalog import effective_all

    with database() as db:
        return {
            "backends": list(c.BACKENDS),
            "sources": [dict(x) for x in db.execute("SELECT id,title FROM sources")],
            "tags": sorted({t["tag"] for values in effective_all(db).values() for t in values}),
            "total": db.execute("SELECT COUNT(*) FROM materials WHERE status<>'discarded'").fetchone()[0],
        }


@router.get("")
def search(
    q: str = "",
    pool: str = "library",
    tags: list[str] = Query([]),  # noqa: B008 - FastAPI parameter
    tag_expression: str = "",
    starred: bool = False,
    offset: int = 0,
):
    with database() as db:
        ids = m.query_ids(db, text=q, tags=tags, tag_expression=tag_expression)
        rows = []
        for mid in ids:
            r = dict(db.execute("SELECT id,status,pool,starred FROM materials WHERE id=?", (mid,)).fetchone())
            if r["status"] == "discarded":
                continue
            if r["status"] == "pending" or (pool != "all" and r["pool"] != pool):
                continue
            if starred and not r["starred"]:
                continue
            rows.append(mid)
        return {
            "total": len(rows),
            "results": [m.get(db, x) for x in rows[max(0, offset) : max(0, offset) + 50]],
        }


@router.post("/delete")
def delete_samples(body: dict):
    from .sample_deletion import remove

    with database() as db, db:
        return {"deleted": remove(db, body["ids"])}


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

    if not re.fullmatch(r"[a-f0-9]{24}", key):
        raise ValueError("无效试听标识")
    path = json.loads((DATA / "cache/speech-hits" / (key + ".json")).read_text())["path"]
    return FileResponse(path, media_type="audio/wav")


@router.post("/phone-models")
def phone_models(body: dict):
    from .model_selection import inspect, switch

    with database() as db:
        result = (switch if body.get("action") in ("switch", "analyze") else inspect)(
            db, body["ids"], body["backend"]
        )
    if body.get("action") == "analyze":
        from .operation_jobs import submit

        missing = [r["id"] for r in result["missing"] + result["failed"]]
        if missing:
            result["job"] = submit(
                "speech-prepare",
                {"material_ids": missing, "backends": [body["backend"]], "switch_backend": body["backend"]},
            )
    return result


@router.post("/reanalyse")
def reanalyse(body: dict):
    from .reanalysis import submit

    with database() as db:
        return submit(db, body["ids"], body.get("backend"))


@router.post("/phone-times/export")
def phone_times_export(body: dict):
    from .phone_timing import document

    with database() as db:
        return document(db, body["material_id"], body.get("backend"))


@router.post("/phone-times/apply")
def phone_times_apply(body: dict):
    from .phone_timing import apply

    with database() as db:
        return apply(db, body)


@router.post("/phone-times/versions")
def phone_times_versions(body: dict):
    from .phone_timing import versions

    with database() as db:
        head = db.execute(
            "SELECT revision FROM analysis_references WHERE owner_type='sample' AND owner_id=? AND kind=?",
            (body["material_id"], body["backend"]),
        ).fetchone()
        return {
            "versions": versions(db, body["material_id"], body["backend"]),
            "revision": head[0] if head else 0,
        }


@router.post("/phone-times/choose")
def phone_times_choose(body: dict):
    from .phone_timing import choose

    with database() as db:
        return choose(db, body["material_id"], body["backend"], body["run_id"], body["base_revision"])


@router.post("/rhythm")
def rhythm_search(body: dict):
    with database() as db:
        return rhythm.search(db, body)


@router.post("/rhythm-batch")
def rhythm_batch(body: dict):
    with database() as db:
        return ops.batch_search(db, body["query"])


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
        record = (
            analysis.display_ready(db, mid) if part in ("display", "features") else analysis.ready(db, mid)
        )
        if part == "display":
            return {k: record[k] for k in ("signature", "backend", "view", "frames", "root_cue")} | {
                "analysis": {
                    k: record["analysis"].get(k) for k in ("phones", "window_start", "window_end", "version")
                }
            }
        if part == "features":
            return {"features": record["features"]}
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
        return {
            "url": f"/api/samples/{mid}/audio?role={body.get('role') or 'selected'}",
            "audio_source": asset["role"],
        }


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
    return submit("native-alignment", {"model": body["model"], "material_ids": [mid]})


@router.post("/{mid}/native-alignment/play")
def native_alignment_play(mid: str, body: dict):
    from .native_alignment import play

    with database() as db:
        value = play(db, mid, body["model"], body["index"], body.get("native", False))
    if "path" in value:
        return {
            "url": "/api/samples/"
            + mid
            + "/native-alignment/audio?model="
            + body["model"]
            + "&index="
            + str(body["index"])
        }
    return value


@router.get("/{mid}/native-alignment/audio")
def native_alignment_audio(mid: str, model: str, index: int):
    from .native_alignment import play

    with database() as db:
        return FileResponse(play(db, mid, model, index)["path"], media_type="audio/wav")


@router.post("/selection/timeline")
def selection_timeline(body: dict):
    from .analysis_scope import intersecting
    from .asset_timeline import AssetSelection, annotations_for, map_time
    from .selection_ops import resolve

    with database() as db:
        selected, asset = resolve(db, body["selection"])
        annotations = []
        for row in annotations_for(db, selected):
            try:
                if row["scope"]["type"] == "asset":
                    start, end = row["start"] - selected.start, row["end"] - selected.start
                else:
                    knots = asset["root_knots"]
                    start = map_time(knots, max(row["start"], knots[0][1]), inverse=True)
                    end = map_time(knots, min(row["end"], knots[-1][1]), inverse=True)
                annotations.append(
                    {
                        "id": "timeline-" + row["id"],
                        "annotation_id": row["id"],
                        "start": start,
                        "end": end,
                        "label": row["text"] or " · ".join(row["tags"]),
                        "edit_clock": row["scope"]["type"],
                        "edit_offset": selected.start,
                        "edit_knots": asset["root_knots"],
                        "layer": "tags" if row["kind"] == "tag" else "subtitles",
                    }
                )
            except (ValueError, KeyError):
                continue
        return {
            "phones": intersecting(db, body["selection"], body.get("backend", "pydomino")),
            "annotations": annotations,
        }


@router.post("/pitch-query/coverage")
def pitch_coverage(body: dict):
    from .pitch_search import query

    with database() as db:
        return query(db, body, coverage_only=True)["coverage"]
