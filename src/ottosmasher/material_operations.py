"""Shared material operations for native windows, scripts and HTTP adapters."""

from pathlib import Path

from . import cue_operations as cues
from . import materials
from . import media_operations as media
from .contracts import PlanRequest, PreviewRequest, ReaperRequest


def analyzed(db, mid, kind="narabas"):
    return materials.binding(db, mid, kind)


def plans(db, mid, payload):
    request = PlanRequest.model_validate(payload)
    r = analyzed(db, mid, request.analysis_kind)
    if r["scope_id"]:
        if request.scope_id and request.scope_id != r["scope_id"]:
            raise ValueError("方案超出素材范围")
        request.scope_id = r["scope_id"]
    return cues.quantization_plans(r["cue_id"], request)


def checked_plan(db, mid, kind, plan_id):
    r = analyzed(db, mid, kind)
    cue, a, plan = cues.resolve_plan(db, r["cue_id"], kind, plan_id)
    if r["scope_id"] and plan.get("scope", {}).get("scope_id") != r["scope_id"]:
        raise ValueError("方案属于不同素材范围")
    return r, cue, a, plan


def preview(db, mid, payload):
    req = PreviewRequest.model_validate(payload)
    r = analyzed(db, mid, req.analysis_kind)
    if req.plan_id:
        checked_plan(db, mid, req.analysis_kind, req.plan_id)
    if r["scope_id"]:
        req.scope_id = r["scope_id"]
    return cues.rhythm_preview(r["cue_id"], req)


def export(
    db, mid, *, version_id=None, plan_id=None, analysis_kind="narabas", variant="vocals", video=False
):
    r = materials.get(db, mid)
    if version_id:
        v = next((v for v in r["versions"] if v["id"] == version_id), None)
        if not v or not v["available"]:
            raise ValueError("版本文件不存在")
        if materials.sha256(v["path"]) != v["fingerprint"]:
            raise ValueError("版本文件已被修改")
        return v
    if plan_id:
        r, cue, a, plan = checked_plan(db, mid, analysis_kind, plan_id)
        from .audition import export_witness

        out = export_witness(cue, a, {"strict_plan": plan}, variant)
        return materials.add_version(
            db,
            mid,
            out["audio"],
            "strict_quantization",
            {**out["manifest"], "plan_id": plan_id, "analysis_kind": analysis_kind, "variant": variant},
        )
    out = media.cut(r["path"], r["start"], r["end"], r["audio_stream"], video=video, title=r["title"])
    out = {**out, "material_id": mid}
    from .workspace import write_json

    write_json(Path(out["path"]).with_suffix(Path(out["path"]).suffix + ".json"), out)
    return materials.add_version(db, mid, out["path"], out["operation"], out)


def reaper(db, mid, payload):
    req = ReaperRequest.model_validate(payload)
    _r, cue, a, plan = checked_plan(db, mid, req.analysis_kind, req.plan_id)
    from .reaper_export import export_reaper

    return export_reaper(cue, a, plan, req.variant, req.directory, req.origin)


def import_manifest(db, path):
    import json

    payload = json.loads(Path(path).read_text())
    rows = payload if isinstance(payload, list) else payload.get("outputs", [payload])
    result = []
    for item in rows:
        output = Path(item.get("path") or item.get("audio") or item.get("audio_file") or "")
        if not output.is_absolute():
            output = Path(path).resolve().parent / output
        src = item.get("source")
        if (
            not src
            and item.get("source_path")
            and item.get("source_start") is not None
            and item.get("source_end") is not None
        ):
            src = {
                "path": item["source_path"],
                "start": item["source_start"],
                "end": item["source_end"],
                "audio_stream": item.get("audio_stream"),
            }
        if src and Path(src["path"]).is_file():
            bounds = (item.get("source_start", src["start"]), item.get("source_end", src["end"]))
            mid = item.get("material_id")
            if mid and db.execute("SELECT 1 FROM materials WHERE id=?", (mid,)).fetchone():
                r = materials.get(db, mid)
                if (
                    r["path"] != str(Path(src["path"]).resolve())
                    or abs(r["start"] - bounds[0]) > 0.001
                    or abs(r["end"] - bounds[1]) > 0.001
                ):
                    raise ValueError("清单与登记素材来源不一致")
            else:
                r = materials.register_file(
                    db, src["path"], audio_stream=src.get("audio_stream"), selected_range=bounds
                )
            materials.add_version(db, r["id"], output, item.get("operation", "external"), item)
        else:
            r = materials.register_file(db, output)
            materials.add_version(db, r["id"], output, item.get("operation", "external"), item)
        result.append(r["id"])
    return result
