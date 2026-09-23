"""Shared measured-dialogue operations; CLI and HTTP use identical plans."""

from __future__ import annotations

import json
import time
from contextlib import contextmanager

from . import audition
from .backends import BACKENDS, PhoneKind
from .catalog import neighbors
from .contracts import *
from .media import export_bundle
from .quantization import load_plan
from .rhythm_units import VOWELS, get_rhythm_view, normalize_phone
from .workspace import DATA, connect, get_analysis, get_cue, get_speech_analysis, get_vocals_lineage, identity


@contextmanager
def database():
    db = connect()
    try:
        yield db
    finally:
        db.close()


def detail(cue_id: str):
    from .rhythm_index import segment_settings
    from .rhythm_scopes import list_scopes

    with database() as db:
        cue = get_cue(db, cue_id)
        rhythms = {}
        analyses = {}
        scopes = {}
        segment_options = {}
        for kind in BACKENDS:
            a = get_speech_analysis(db, cue_id, kind)
            analyses[kind] = a
            rhythms[kind] = get_rhythm_view(db, cue_id, kind, a)
            scopes[kind] = (
                list_scopes(cue, a, rhythms[kind], segment_settings(db, cue_id, kind, a["version"]))
                if a and rhythms[kind]
                else []
            )
            segment_options[kind] = segment_settings(db, cue_id, kind, a["version"]) if a else {}
        return {
            **analyses,
            "rhythms": rhythms,
            "scopes": scopes,
            "segment_settings": segment_options,
            "cue": cue,
            "neighbors": neighbors(db, cue_id),
            "acoustic": get_analysis(db, cue_id, "acoustic"),
            "phonetic": get_speech_analysis(db, cue_id, "phonetic"),
            "narabas": get_speech_analysis(db, cue_id, "narabas"),
            "vocals_energy": get_speech_analysis(db, cue_id, "vocals_energy"),
            "has_vocals": get_vocals_lineage(db, cue_id) is not None,
        }


def get_scope(cue_id: str, analysis_kind: PhoneKind = "narabas", scope_id: str | None = None):
    from .rhythm_index import entry_for

    with database() as db:
        record, entry = entry_for(db, cue_id, analysis_kind, scope_id)
        return {
            "analysis": entry["analysis"],
            "rhythm": entry["view"],
            "scope": entry["scope"],
            "scopes": [e["scope"] for e in record["entries"]],
        }


def edit_segments(cue_id: str, body: SegmentSettings):
    from .rhythm_scopes import list_scopes

    with database() as db:
        cue = get_cue(db, cue_id)
        a = get_speech_analysis(db, cue_id, body.analysis_kind)
        if not a or a["version"] != body.analysis_version:
            raise ValueError("Analysis changed; reload")
        v = get_rhythm_view(db, cue_id, body.analysis_kind, a)
        settings = body.model_dump(exclude={"analysis_kind", "analysis_version"})
        scopes = list_scopes(cue, a, v, settings)
        db.execute(
            "INSERT OR REPLACE INTO segment_settings VALUES(?,?,?,?)",
            (cue_id, body.analysis_kind, a["version"], json.dumps(settings)),
        )
        db.commit()
        return {"scopes": scopes, "settings": settings}


def export(cue_id: str, body: ExportRequest):
    with database() as db:
        if body.plan_id:
            cue, analysis, plan = resolve_plan(db, cue_id, body.analysis_kind, body.plan_id)
            return audition.export_witness(
                cue, analysis, {**(plan.get("witness") or {}), "strict_plan": plan}, body.variant
            )
        if body.query and body.query.notes:
            if body.query.engine == "quantized":
                raise ValueError("量化命中导出需要 plan_id，请选择已保存的命中方案")
            cue, analysis, _view, witness = resolve_witness(
                db, cue_id, body.query, body.analysis_version, body.rhythm_id
            )
            return audition.export_witness(cue, analysis, witness, body.variant)
        if body.scope_id:
            from .rhythm_index import entry_for

            record, entry = entry_for(db, cue_id, body.analysis_kind, body.scope_id)
            return export_bundle(
                record["cue"],
                entry["analysis"],
                body.factor,
                body.context,
                body.offset,
                body.variant,
                entry["analysis"].get("audio_lineage"),
            )
        return export_bundle(
            get_cue(db, cue_id),
            get_speech_analysis(db, cue_id, body.analysis_kind),
            body.factor,
            body.context,
            body.offset,
            body.variant,
            get_vocals_lineage(db, cue_id, body.analysis_kind),
        )


def resolve_witness(db, cue_id, query, version=None, rhythm_id=None):
    if not query.notes:
        raise ValueError("Timeline matching requires note blocks")
    if query.engine == "quantized":
        from .rhythm_index import entry_for, search_index

        record, entry = entry_for(db, cue_id, query.mode)
        if version and entry["analysis"]["version"] != version:
            raise ValueError("Analysis changed; search again")
        if rhythm_id and not any(identity(e["view"]) == rhythm_id for e in record["entries"]):
            raise ValueError("Rhythm groups changed; search again")
        results = search_index(db, query, cue_id)["results"]
        if not results:
            raise ValueError("当前句的量化节奏不满足查询；请换倍率或修改音块")
        result = results[0]
        cue, analysis, plan = resolve_plan(db, cue_id, query.mode, result["plan_id"])
        _, entry = entry_for(db, cue_id, query.mode, plan["scope"]["scope_id"])
        return (
            cue,
            analysis,
            entry["view"],
            {**plan["witness"], "beat_seconds": plan["beat_seconds"], "strict_plan": plan},
        )


def edit_rhythm(cue_id: str, body: RhythmEdit):
    with database() as db:
        analysis = get_speech_analysis(db, cue_id, body.kind)
        if not analysis or analysis["version"] != body.analysis_version:
            raise ValueError("Analysis changed; reload before editing")
        phones = analysis["phones"]
        for i in body.split_before:
            if i < 1 or i >= len(phones) or normalize_phone(phones[i]["label"]) not in VOWELS | {"N"}:
                raise ValueError("Split must refer to an existing vowel/nasal boundary")
        db.execute(
            "INSERT OR REPLACE INTO rhythm_edits VALUES (?,?,?,?,?)",
            (
                cue_id,
                body.kind,
                body.analysis_version,
                json.dumps(sorted(set(body.split_before))),
                time.time(),
            ),
        )
        segment_row = db.execute(
            "SELECT payload FROM segment_settings WHERE cue_id=? AND kind=? AND analysis_version=?",
            (cue_id, body.kind, body.analysis_version),
        ).fetchone()
        if segment_row:
            from .workspace import write_json

            retired = json.loads(segment_row[0])
            write_json(
                DATA / "analysis-history" / (identity(analysis, retired, "segments") + ".json"),
                {"retired_segment_settings": retired, "reason": "rhythm_groups_edited"},
            )
            retired.update(split_before=[], suppressed_split_before=[])
            db.execute(
                "UPDATE segment_settings SET payload=? WHERE cue_id=? AND kind=? AND analysis_version=?",
                (json.dumps(retired), cue_id, body.kind, body.analysis_version),
            )
        settings_row = db.execute(
            "SELECT payload FROM cue_settings WHERE cue_id=? AND kind=? AND analysis_id=?",
            (cue_id, body.kind, analysis["version"]),
        ).fetchone()
        if settings_row:
            from .workspace import save_analysis, write_json

            settings = json.loads(settings_row[0])
            if settings.get("slots"):
                write_json(
                    DATA / "analysis-history" / (identity(analysis, settings) + ".json"),
                    {"analysis": analysis, "retired_settings": settings, "reason": "rhythm_groups_edited"},
                )
                settings["slots"] = {}
                db.execute(
                    "UPDATE cue_settings SET payload=? WHERE cue_id=? AND kind=? AND analysis_id=?",
                    (json.dumps(settings), cue_id, body.kind, analysis["version"]),
                )
                analysis["reference_settings"] = settings
                save_analysis(db, cue_id, body.kind, analysis["version"], analysis)
        db.commit()
        return get_rhythm_view(db, cue_id, body.kind, analysis)


def quantization_plans(cue_id: str, body: PlanRequest):
    if body.rest_overrides and not body.composition:
        raise ValueError("修改连接休止需要启用语段连接")
    with database() as db:
        from .rhythm_index import entry_for, reference_plans

        record, entry = entry_for(db, cue_id, body.analysis_kind, body.scope_id)
        if body.analysis_version and entry["analysis"]["version"] != body.analysis_version:
            raise ValueError("Analysis changed; reload")
        if body.rhythm_id and identity(entry["view"]) != body.rhythm_id:
            raise ValueError("Rhythm groups changed; reload")
        if body.composition:
            from .rhythm_index import composition_plans

            result = composition_plans(
                record,
                entry,
                body.bpm,
                body.strategy,
                body.density,
                body.rest_overrides,
                body.auto_long_vowels,
            )
        else:
            result = reference_plans(
                record, entry, body.bpm, body.strategy, body.density, body.auto_long_vowels
            )
        if body.matched_plan_id:
            _, _, selected = resolve_plan(db, cue_id, body.analysis_kind, body.matched_plan_id)
            if (
                selected["scope"]["scope_id"] != entry["scope"]["scope_id"]
                or selected["strategy"] != body.strategy
                or abs(selected["beat_seconds"] - 60 / body.bpm) > 1e-9
            ):
                raise ValueError("命中方案与当前语段、算法或 BPM 不一致，请重新检索")
            result["plans"] = [selected] + [p for p in result["plans"] if p["density"] != selected["density"]]
            result["selected_plan_id"] = selected["plan_id"]
        return result


def cue_settings(cue_id: str, body: CueSettings):
    from .workspace import save_analysis

    with database() as db:
        a = get_speech_analysis(db, cue_id, body.analysis_kind)
        if not a or a["version"] != body.analysis_version:
            raise ValueError("Analysis changed; reload")
        view = get_rhythm_view(db, cue_id, body.analysis_kind, a)
        for k, v in body.slots.items():
            if not k.isdigit() or not 0 <= int(k) < len(view["units"]) or not 1 <= v <= 64:
                raise ValueError("Invalid unit slot override")
        settings = {"pause_sensitivity": body.pause_sensitivity, "slots": body.slots}
        db.execute(
            "INSERT OR REPLACE INTO cue_settings VALUES (?,?,?,?)",
            (cue_id, body.analysis_kind, a["version"], json.dumps(settings)),
        )
        # Settings participate in analysis identity, invalidating all old plans.
        a["reference_settings"] = settings
        save_analysis(db, cue_id, body.analysis_kind, a["version"], a)
        return settings


def crop_edit(cue_id: str, body: CropEdit):
    from .manual_crop import apply_crop
    from .workspace import save_analysis, write_json

    with database() as db:
        a = get_speech_analysis(db, cue_id, body.analysis_kind)
        if not a or a["version"] != body.analysis_version:
            raise ValueError("Analysis changed; reload")
        write_json(DATA / "analysis-history" / (identity(a) + ".json"), a)
        edited = apply_crop(a, body.start, body.end)
        save_analysis(db, cue_id, body.analysis_kind, a["version"], edited)
        return {"start": edited["window_start"], "end": edited["window_end"]}


def resolve_plan(db, cue_id, kind, plan_id):
    import re

    from . import quantization, workspace
    from .rhythm_index import PLAN_VERSION, entry_for

    if not re.fullmatch("[a-f0-9]{24}", plan_id):
        raise ValueError("Invalid plan id")
    path = workspace.DATA / "quantization-plans" / (plan_id + ".json")
    if not path.is_file():
        path = quantization.DATA / "quantization-plans" / (plan_id + ".json")
    if not path.is_file():
        raise ValueError("Plan missing; regenerate")
    saved = json.loads(path.read_text())
    if saved.get("version") == PLAN_VERSION:
        record, entry = entry_for(db, cue_id, kind, saved["scope"]["scope_id"])
        if (
            saved["cue_id"] != cue_id
            or saved["index_signature"] != record["signature"]
            or saved["analysis_id"] != identity(entry["analysis"])
            or saved["rhythm_id"] != identity(entry["view"])
        ):
            raise ValueError("Analysis or scope changed; 分析、分组或语段边界已改变，请重新生成方案")
        return record["cue"], entry["analysis"], saved
    cue = get_cue(db, cue_id)
    analysis = get_speech_analysis(db, cue_id, kind)
    view = get_rhythm_view(db, cue_id, kind, analysis)
    if not view:
        raise ValueError("No current rhythm analysis for this plan")
    return cue, analysis, load_plan(plan_id, cue_id, analysis, view)


def copy_reaper(cue_id: str, body: ReaperRequest):
    from .reaper_export import export_reaper

    with database() as db:
        cue, analysis, plan = resolve_plan(db, cue_id, body.analysis_kind, body.plan_id)
        return export_reaper(cue, analysis, plan, body.variant, body.directory, body.origin)


def sound_features(cue_id: str, analysis_kind: PhoneKind = "narabas", scope_id: str | None = None):
    from .rhythm_index import entry_for
    from .sound_features import asset_path, read_asset, record_features
    from .speakers import labels_for_units

    with database() as db:
        record, entry = entry_for(db, cue_id, analysis_kind, scope_id)
        features = record_features(record)
        indices = entry["scope"].get("parent_unit_indices", list(range(len(entry["view"]["units"]))))
        roles = labels_for_units(db, record["cue"], entry["view"]["units"])
        units = [
            dict(unit_index=i, label=u["label"], start=u["time"], end=u["end"], **features[parent], **role)
            for i, (u, parent, role) in enumerate(zip(entry["view"]["units"], indices, roles))
        ]
        lineage = entry["analysis"]["audio_lineage"]
        path = asset_path(lineage)
        frames = []
        if path.exists():
            f = read_asset(str(path), path.stat().st_mtime_ns)
            for t, hz, v, c in zip(f["times"], f["f0_hz"], f["voiced"], f["confidence"]):
                absolute = float(t + f["source_window_start"])
                if entry["analysis"]["window_start"] <= absolute <= entry["analysis"]["window_end"]:
                    frames.append({"time": absolute, "hz": float(hz) if v else None, "confidence": float(c)})
        return {"status": "ready" if path.exists() else "pending", "units": units, "frames": frames}


def rhythm_preview(cue_id: str, body: PreviewRequest):
    with database() as db:
        if body.mode.startswith("strict"):
            if not body.plan_id:
                raise ValueError("Select a strict plan first")
            cue, analysis, plan = resolve_plan(db, cue_id, body.analysis_kind, body.plan_id)
            return audition.preview_strict(cue, analysis, plan, body.mode, body.variant)
        if body.mode == "aligned":
            if body.plan_id:
                cue, analysis, plan = resolve_plan(db, cue_id, body.analysis_kind, body.plan_id)
                return audition.preview_strict(cue, analysis, plan, "strict_overlay", body.variant)
            if body.query and body.query.engine == "quantized":
                raise ValueError("量化命中试听需要 plan_id，请选择已保存的命中方案")
            if not body.query or not body.query.notes:
                raise ValueError("Aligned playback requires a note-block query")
            cue, analysis, view, witness = resolve_witness(
                db, cue_id, body.query, body.analysis_version, body.rhythm_id
            )
        else:
            cue = get_cue(db, cue_id)
            analysis = get_speech_analysis(db, cue_id, body.analysis_kind)
            view = get_rhythm_view(db, cue_id, body.analysis_kind, analysis)
            if body.scope_id:
                from .rhythm_index import entry_for

                _, entry = entry_for(db, cue_id, body.analysis_kind, body.scope_id)
                analysis, view = entry["analysis"], entry["view"]
            if not view or not view["units"]:
                raise ValueError("No rhythm groups available")
            witness = None
        return audition.preview(cue, analysis, view, body.mode, body.variant, witness)
