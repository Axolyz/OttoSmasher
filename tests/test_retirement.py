"""Destructive migrations remove retired machine state, never media/manual work."""

import json
import sqlite3

from ottosmasher.retirement import retire_alignment_records, retire_tool_records


def test_tool_retirement_keeps_media_identity_and_manual_tags():
    db = sqlite3.connect(":memory:")
    db.executescript("""CREATE TABLE workflow_artifacts(id TEXT PRIMARY KEY,payload TEXT);
    INSERT INTO workflow_artifacts VALUES('saved','{"path":"/original/audio.wav"}');
    CREATE TABLE plugin_state(id TEXT); CREATE TABLE sound_results(id TEXT);
    CREATE TABLE material_tags(material_id TEXT,tag TEXT,origin TEXT);
    INSERT INTO material_tags VALUES('saved','Alice','manual');
    INSERT INTO material_tags VALUES('saved','cluster:1','speaker_cluster');""")
    retire_tool_records(db)
    retire_tool_records(db)
    assert db.execute("SELECT id,payload FROM processed_audio_assets").fetchone() == (
        "saved",
        '{"path":"/original/audio.wav"}',
    )
    assert db.execute("SELECT tag FROM material_tags").fetchall() == [("Alice",)]
    assert not db.execute(
        "SELECT 1 FROM sqlite_master WHERE name IN ('workflow_artifacts','plugin_state','sound_results')"
    ).fetchall()


def test_retired_alignment_selects_survivor_without_reanalysis():
    db = sqlite3.connect(":memory:")
    db.executescript("""CREATE TABLE materials(id TEXT PRIMARY KEY,cue_id TEXT,active_phone_backend TEXT,analysis_settings TEXT,analysis_kind TEXT);
    CREATE TABLE analyses(cue_id TEXT,kind TEXT,payload TEXT);
    CREATE TABLE sample_measurements(material_id TEXT,backend TEXT,payload TEXT);
    CREATE TABLE sample_records(material_id TEXT,backend TEXT,payload TEXT);
    CREATE TABLE sample_analysis_status(material_id TEXT,backend TEXT,status TEXT);
    CREATE TABLE speech_unit_indices(material_id TEXT);""")
    db.execute(
        "INSERT INTO materials VALUES(?,?,?,?,?)",
        (
            "sample",
            "cue",
            "mfa",
            json.dumps({"backend_settings": {"mfa": {}, "phonetic": {"manual_groups": [1]}}}),
            "mfa",
        ),
    )
    for backend in ("mfa", "phonetic"):
        db.execute("INSERT INTO sample_measurements VALUES(?,?,?)", ("sample", backend, '{"phones":[1]}'))
    retire_alignment_records(db)
    retire_alignment_records(db)
    chosen, settings, kind = db.execute(
        "SELECT active_phone_backend,analysis_settings,analysis_kind FROM materials"
    ).fetchone()
    assert chosen == "phonetic" and kind is None
    assert json.loads(settings)["backend_settings"] == {"phonetic": {"manual_groups": [1]}}
    assert db.execute("SELECT backend FROM sample_measurements").fetchall() == [("phonetic",)]
