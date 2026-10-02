import json
import sqlite3

import pytest

from ottosmasher import asset_timeline as a, asset_migration, workspace
from test_samples import library


def test_selection_mapping_and_shared_measurements_survive_deletion(library):
    from ottosmasher.sample_deletion import remove

    db, root, _ = library
    descriptor = {
        "path": root["path"],
        "start": 0,
        "end": 1,
        "root_knots": [[0, 2], [0.4, 3], [1, 4]],
        "sha256": "fixture",
    }
    whole = a.register_asset(db, root["source_id"], descriptor)
    a.bind_sample(db, root["id"], a.AssetSelection(whole.asset_id, 0.2, 0.7))
    crop = a.selection_asset(db, a.sample_selection(db, root["id"]))
    assert crop["start"] == 0.2
    assert crop["root_knots"][0][1] == 2.5
    assert crop["root_knots"][1] == [0.2, 3]
    with pytest.raises(ValueError):
        a.map_time(descriptor["root_knots"], 1.1)
    rid = a.add_analysis(db, "narabas", "test", {"phones": []}, selection=whole)
    a.adopt_analysis(db, "sample", root["id"], "narabas", rid)
    remove(db, [root["id"]])
    assert db.execute("SELECT count(*) FROM sound_assets").fetchone()[0] == 1
    assert db.execute("SELECT count(*) FROM analysis_runs").fetchone()[0] == 1
    with pytest.raises(sqlite3.IntegrityError):
        db.execute("DELETE FROM analysis_runs")


def test_automatic_results_never_replace_human_or_stale_head(library):
    db, root, _ = library
    r1 = a.add_analysis(db, "narabas", "one", {"phones": []}, human=True)
    a.adopt_analysis(db, "sample", root["id"], "narabas", r1)
    r2 = a.add_analysis(db, "narabas", "two", {"phones": [1]})
    result = a.adopt_analysis(db, "sample", root["id"], "narabas", r2, automatic=True)
    assert result["reason"] == "human_timing"
    assert a.adopt_analysis(db, "sample", root["id"], "narabas", r2, expected_revision=0)["reason"] == "stale"
    assert db.execute("SELECT count(*) FROM analysis_history").fetchone()[0] == 2


def test_group_annotations_positive_overlap_only(library):
    db, root, _ = library
    whole = a.register_asset(
        db, root["source_id"], {"path": root["path"], "start": 0, "end": 1, "root_knots": [[0, 0], [1, 1]]}
    )
    db.execute(
        "INSERT INTO timeline_annotations VALUES(?,?,?,?,?,?,?,?,1,0)",
        (
            "cue",
            root["source_id"],
            0.4,
            0.6,
            "tag",
            "",
            '["character:京子"]',
            '{"type":"group","ids":["dialogue"]}',
        ),
    )
    assert not a.annotations_for(db, whole)
    db.execute("INSERT INTO asset_groups VALUES(?,?)", (whole.asset_id, "dialogue"))
    assert len(a.annotations_for(db, whole)) == 1
    assert not a.annotations_for(db, a.AssetSelection(whole.asset_id, 0, 0.4))


def test_migration_keeps_different_history_and_canonical_equal_snapshots(library):
    from ottosmasher.sample_inference import attach_text
    from ottosmasher.sample_audio import resolve

    db, root, _ = library
    descriptor = resolve(db, root["id"], "raw")
    db.execute("INSERT INTO sample_assets VALUES(?,?)", (root["id"], json.dumps(descriptor)))
    attach_text(db, root["id"], "ねえ")
    cue = db.execute("SELECT cue_id FROM materials WHERE id=?", (root["id"],)).fetchone()[0]
    payload = {"version": "same", "phones": [{"label": "e", "start": 0.1, "end": 0.9}]}
    workspace.save_analysis(db, cue, "narabas", "same", payload)
    db.execute(
        "INSERT INTO sample_measurements VALUES(?,?,?)",
        (root["id"], "narabas", json.dumps(payload, sort_keys=True, indent=4)),
    )
    db.execute(
        "INSERT INTO sample_measurements VALUES(?,?,?)",
        (root["id"], "pydomino", json.dumps({**payload, "phones": []})),
    )
    db.commit()
    result = asset_migration.prepare(db)
    assert result["analysis_runs"] == 2
    assert result["descriptor_mismatches"] == result["snapshot_mismatches"] == []
    assert asset_migration.prepare(db)["already_prepared"]
    assert db.execute("SELECT count(*) FROM analyses").fetchone()[0] == 1


def test_reading_measurement_does_not_create_snapshot(library, monkeypatch):
    from ottosmasher import sample_analysis

    db, root, _ = library
    monkeypatch.setattr(sample_analysis, "get_speech_analysis", lambda *args: {"phones": [1]})
    assert sample_analysis.measurement(db, {**root, "cue_id": "fixture"}, "narabas") == {"phones": [1]}
    assert db.execute("SELECT count(*) FROM sample_measurements").fetchone()[0] == 0


def test_cutover_keeps_legacy_readonly_and_crops_share_asset(library):
    from ottosmasher.sample_catalog import derive
    from ottosmasher.sample_audio import resolve
    from ottosmasher.sample_deletion import remove
    from ottosmasher.asset_compat import active

    db, root, _ = library
    result = asset_migration.activate(db)
    assert result["active"] and active(db)
    original = a.sample_selection(db, root["id"])
    child = derive(db, root["id"], start=0.2, end=0.7)
    selected = a.sample_selection(db, child["id"])
    assert selected.asset_id == original.asset_id
    assert (selected.start, selected.end) == (0.2, 0.7)
    before = resolve(db, child["id"])
    remove(db, [root["id"]])
    db.commit()
    assert resolve(db, child["id"]) == before
    with pytest.raises(sqlite3.IntegrityError, match="read-only"):
        db.execute("INSERT INTO legacy_sample_assets VALUES('forbidden','{}')")
    assert asset_migration.activate(db)["already_active"]
    # A subsequent normal connection must accept the compatibility views.
    with workspace.connect() as reopened:
        assert resolve(reopened, child["id"]) == before


def test_new_registration_after_cutover_binds_without_inference(library):
    from ottosmasher.materials import save_range
    from ottosmasher.sample_audio import resolve

    db, root, _ = library
    asset_migration.activate(db)
    new = save_range(db, root["source_id"], 0.1, 0.5, title="新增")
    assert new["asset_selection"]
    assert resolve(db, new["id"])["start"] == 0.1
    assert db.execute("SELECT count(*) FROM legacy_sample_assets").fetchone()[0] == 0


def test_migration_rechecks_changes_and_keeps_manual_head(library):
    from ottosmasher.sample_inference import attach_text

    db, root, _ = library
    attach_text(db, root["id"], "あ")
    payload = {"version": "old", "phones": [{"label": "a", "start": 0, "end": 1}]}
    db.execute("INSERT INTO sample_measurements VALUES(?,?,?)", (root["id"], "narabas", json.dumps(payload)))
    db.commit()
    rid = a.add_analysis(db, "narabas", "human", {"phones": []}, human=True)
    a.adopt_analysis(db, "sample", root["id"], "narabas", rid)
    db.commit()
    asset_migration.prepare(db)
    assert (
        db.execute(
            "SELECT run_id FROM analysis_references WHERE owner_type='sample' AND owner_id=?", (root["id"],)
        ).fetchone()[0]
        == rid
    )
    db.execute("UPDATE materials SET title=? WHERE id=?", ("准备后改名", root["id"]))
    db.commit()
    with pytest.raises(ValueError, match="旧资料已改变"):
        asset_migration.activate(db)
    asset_migration.prepare(db, refresh=True)
    assert asset_migration.activate(db)["active"]
    assert (
        db.execute(
            "SELECT run_id FROM analysis_references WHERE owner_type='sample' AND owner_id=?", (root["id"],)
        ).fetchone()[0]
        == rid
    )


def test_new_cue_binding_and_caption_edits_do_not_move_sample(library):
    from ottosmasher.materials import sync_cues
    from ottosmasher.workspace import get_cue
    from ottosmasher import business_edits

    db, root, _ = library
    asset_migration.activate(db)
    # A newly imported dialogue has no separated audio: retain that absence.
    cols = [r[1] for r in db.execute("PRAGMA table_info(cues)")]
    values = {
        "id": "new-cue",
        "source_id": root["source_id"],
        "ordinal": 0,
        "start": 0.1,
        "end": 0.4,
        "original": "台詞",
        "spoken": "台詞",
        "kind": "dialogue",
        "speaker": "",
        "style": "",
        "normalized": "台詞",
        "reading": "だいし",
        "flags": "[]",
    }
    selected = [k for k in values if k in cols]
    db.execute(
        "INSERT INTO cues(" + ",".join(selected) + ") VALUES(" + ",".join("?" for _ in selected) + ")",
        [values[k] for k in selected],
    )
    db.commit()
    sync_cues(db)
    from test_revision_workflows import import_dialogue

    assert not db.execute("SELECT 1 FROM materials WHERE cue_id='new-cue'").fetchone()
    mid = import_dialogue(db, root)[0]
    old = a.sample_selection(db, mid)
    descriptor = a.selection_asset(db, old)
    assert descriptor["role"] == "raw"  # Explicitly selected as the speech default.
    doc = business_edits.export(db, [{"type": "annotation", "id": "new-cue"}])
    doc["objects"][0]["values"].update(start=0.2, end=0.6, text="新しい台詞")
    db.commit()
    assert business_edits.apply(db, doc)["valid"]
    assert a.sample_selection(db, mid) == old
    assert get_cue(db, "new-cue")["start"] == 0.2
    assert get_cue(db, "new-cue")["original"] == "新しい台詞"
    assert db.execute("SELECT original FROM cues WHERE id='new-cue'").fetchone()[0] == "台詞"
