"""One-way removal of retired alignment records, preserving media and manual work."""

import json
import time


def retire_alignment_records(db):
    db.execute("CREATE TABLE IF NOT EXISTS alignment_migrations(id TEXT PRIMARY KEY,created REAL)")
    marker = "retire-mfa-sofa-v2"
    if db.execute("SELECT 1 FROM alignment_migrations WHERE id=?", (marker,)).fetchone():
        return
    tables = {r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    db.execute("PRAGMA secure_delete=ON")
    for table in ("analyses", "rhythm_edits", "rhythm_index", "cue_settings", "segment_settings"):
        if table in tables:
            db.execute(f"DELETE FROM {table} WHERE kind IN ('mfa','sofa')")
    for table in ("sample_records", "sample_measurements", "sample_analysis_status"):
        if table in tables:
            db.execute(f"DELETE FROM {table} WHERE backend IN ('mfa','sofa')")
    if "speech_unit_indices" in tables:
        db.execute("DELETE FROM speech_unit_indices")
    db.execute("DROP TRIGGER IF EXISTS new_material_alignment_default")
    # Preserve each surviving model's measured result and manual grouping settings.
    for row in db.execute(
        "SELECT id,cue_id,active_phone_backend,analysis_settings FROM materials"
    ).fetchall():
        mid, cid, active, payload = row
        settings = json.loads(payload or "{}")
        settings.pop("retired_backend", None)
        for key in ("mfa", "sofa"):
            settings.get("backend_settings", {}).pop(key, None)
        if active in ("mfa", "sofa"):
            active = "narabas"
            for candidate in ("narabas", "phonetic", "pydomino"):
                measured = (
                    "sample_measurements" in tables
                    and db.execute(
                        "SELECT 1 FROM sample_measurements WHERE material_id=? AND backend=?",
                        (mid, candidate),
                    ).fetchone()
                )
                found = (
                    "analyses" in tables
                    and db.execute(
                        "SELECT 1 FROM analyses WHERE cue_id=? AND kind=? AND json_array_length(payload,'$.phones')>0",
                        (cid, candidate),
                    ).fetchone()
                )
                if measured or found:
                    active = candidate
                    break
        db.execute(
            "UPDATE materials SET active_phone_backend=?,analysis_settings=?,analysis_kind=CASE WHEN analysis_kind IN ('mfa','sofa') THEN NULL ELSE analysis_kind END WHERE id=?",
            (active, json.dumps(settings), mid),
        )
    db.execute("""CREATE TRIGGER new_material_alignment_default AFTER INSERT ON materials
        WHEN NEW.active_phone_backend IN ('mfa','sofa')
        BEGIN UPDATE materials SET active_phone_backend='narabas' WHERE id=NEW.id; END""")
    if "ui_settings" in tables:
        db.execute(
            "UPDATE ui_settings SET value='\"narabas\"' WHERE key='phone_backend' AND value IN ('\"mfa\"','\"sofa\"')"
        )
        db.execute("DELETE FROM ui_settings WHERE key LIKE '%aversion%'")
    db.execute("INSERT INTO alignment_migrations VALUES(?,?)", (marker, time.time()))
    db.commit()


def retire_tool_records(db):
    """Remove tool control state; preserve processed media and human review history."""
    marker = "retire-external-workflows-v1"
    db.execute("CREATE TABLE IF NOT EXISTS alignment_migrations(id TEXT PRIMARY KEY,created REAL)")
    if db.execute("SELECT 1 FROM alignment_migrations WHERE id=?", (marker,)).fetchone():
        return
    from .sound_assets import ensure

    ensure(db)
    for table in (
        "workflow_extensions",
        "plugin_configuration",
        "plugin_state",
        "plugin_grants",
        "region_indices",
        "query_results",
        "voice_samples",
        "sound_results",
        "sound_features",
    ):
        db.execute(f"DROP TABLE IF EXISTS {table}")
    if db.execute("SELECT 1 FROM sqlite_master WHERE name='material_tags'").fetchone():
        db.execute("DELETE FROM material_tags WHERE origin='speaker_cluster'")
    db.execute("INSERT INTO alignment_migrations VALUES(?,?)", (marker, time.time()))
    db.commit()
