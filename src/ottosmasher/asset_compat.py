"""Legacy route adapters to one asset/analysis authority after atomic cutover."""

import json

from . import asset_timeline as t

ACTIVE = "asset-catalog-v1-active"


def active(db):
    if not db.execute("SELECT 1 FROM sqlite_master WHERE name='asset_migrations'").fetchone():
        return False
    return bool(db.execute("SELECT 1 FROM asset_migrations WHERE id=?", (ACTIVE,)).fetchone())


def bind(db, mid, descriptor, *, replace=True, parent_selection=None, operation="import", parameters=None):
    if not active(db):
        db.execute(
            "INSERT OR " + ("REPLACE" if replace else "IGNORE") + " INTO sample_assets VALUES(?,?)",
            (mid, json.dumps(descriptor, ensure_ascii=False)),
        )
        return
    if not replace and db.execute("SELECT 1 FROM asset_samples WHERE sample_id=?", (mid,)).fetchone():
        return
    source = db.execute("SELECT source_id FROM materials WHERE id=?", (mid,)).fetchone()
    selection = t.register_asset(
        db,
        source[0],
        descriptor,
        input_selection=parent_selection,
        operation=operation,
        parameters=parameters,
        legacy_mapping=True,
    )
    t.bind_sample(db, mid, selection)


def bind_crop(db, mid, parent_id, start, end, descriptor, source):
    if active(db):
        parent = db.execute(
            "SELECT asset_id,start,end FROM asset_samples WHERE sample_id=?", (parent_id,)
        ).fetchone()
        if parent:
            selection = t.AssetSelection(**dict(parent))
            if t.selection_asset(db, selection) == source:
                t.bind_sample(
                    db,
                    mid,
                    t.AssetSelection(selection.asset_id, selection.start + start, selection.start + end),
                )
                return
    bind(db, mid, descriptor, replace=False)


def measurement(db, mid, kind, payload, *, replace=False):
    if not active(db):
        db.execute(
            "INSERT OR " + ("REPLACE" if replace else "IGNORE") + " INTO sample_measurements VALUES(?,?,?)",
            (mid, kind, json.dumps(payload, ensure_ascii=False)),
        )
        return
    exists = db.execute(
        "SELECT 1 FROM analysis_references WHERE owner_type='sample' AND owner_id=? AND kind=?", (mid, kind)
    ).fetchone()
    rid = t.add_analysis(db, kind, payload.get("version", "legacy-adapter"), payload)
    db.execute("INSERT OR IGNORE INTO analysis_history VALUES('sample',?,?,?)", (mid, kind, rid))
    if replace or not exists:
        t.adopt_analysis(db, "sample", mid, kind, rid, automatic=True)


def forget_measurement(db, mid, kind):
    if not active(db):
        db.execute("DELETE FROM sample_measurements WHERE material_id=? AND backend=?", (mid, kind))
        return
    db.execute(
        "DELETE FROM analysis_references WHERE owner_type='sample' AND owner_id=? AND kind=? AND run_id IN(SELECT id FROM analysis_runs WHERE human=0)",
        (mid, kind),
    )


def analysis_selection(db, cue_id, payload):
    selection = None
    lineage = payload.get("alignment_input_lineage") or payload.get("audio_lineage") or {}
    cue = db.execute("SELECT source_id FROM cues WHERE id=?", (cue_id,)).fetchone()
    if cue and lineage.get("audio_path") and lineage.get("window_end", 0) > lineage.get("window_start", 0):
        lo, hi = lineage["window_start"], lineage["window_end"]
        descriptor = {
            "path": lineage["audio_path"],
            "sha256": lineage.get("audio_sha256"),
            "start": lineage.get("audio_start", 0),
            "end": lineage.get("audio_end", lineage.get("audio_start", 0) + hi - lo),
            "audio_stream": 0,
            "role": lineage.get("input_variant", "analysis-input"),
            "root_knots": [[0, lo], [hi - lo, hi]],
            "provenance": lineage,
        }
        selection = t.register_asset(db, cue[0], descriptor, legacy_mapping=True)
    return selection


def save_analysis(db, cue_id, kind, version, payload):
    rid = t.add_analysis(db, kind, version, payload, selection=analysis_selection(db, cue_id, payload))
    db.execute("INSERT OR IGNORE INTO analysis_history VALUES('annotation',?,?,?)", (cue_id, kind, rid))
    if not payload.get("error"):
        t.adopt_analysis(db, "annotation", cue_id, kind, rid, automatic=True)
    return rid


def bind_raw_range(db, mid):
    if not active(db):
        return
    row = db.execute(
        "SELECT m.source_id,m.start,m.end,m.audio_stream,s.path,s.fingerprint,s.duration FROM materials m JOIN sources s ON s.id=m.source_id WHERE m.id=?",
        (mid,),
    ).fetchone()
    full = {
        "path": row["path"],
        "sha256": row["fingerprint"],
        "start": 0,
        "end": row["duration"],
        "audio_stream": row["audio_stream"],
        "role": "raw",
        "root_knots": [[0, 0], [row["duration"], row["duration"]]],
        "provenance": {"source_id": row["source_id"]},
    }
    selection = t.register_asset(db, row["source_id"], full)
    t.bind_sample(db, mid, t.AssetSelection(selection.asset_id, row["start"], row["end"]))


def bind_new_cues(db, ids):
    if not active(db):
        return
    from .sample_audio import resolve

    for mid in ids:
        sample = db.execute("SELECT * FROM materials WHERE id=?", (mid,)).fetchone()
        if not sample or db.execute("SELECT 1 FROM asset_samples WHERE sample_id=?", (mid,)).fetchone():
            continue
        try:
            descriptor = resolve(db, mid)
        except (ValueError, OSError) as exc:
            duration = sample["end"] - sample["start"]
            descriptor = {
                "start": 0,
                "end": duration,
                "role": "vocals",
                "root_knots": [[0, sample["start"]], [duration, sample["end"]]],
                "missing_reason": str(exc),
                "provenance": {"source_id": sample["source_id"]},
            }
        bind(db, mid, descriptor, replace=False)
