from ottosmasher import materials, sample_scope, ui_catalog
from ottosmasher import sample_catalog as c
from ottosmasher.sample_deletion import folders, remove, reset

pytest_plugins = ["test_samples"]


def test_nature_is_independent_of_folder_and_all_pages(library):
    db, root, _ = library
    fid = c.folder(db, "我的目录")["id"]
    c.preferences(db, root["id"], folder_id=fid, nature="pitched")
    assert sample_scope.ids(db, {"nature": "speech"}) == []
    assert root["id"] in sample_scope.ids(db, {"nature": "pitched", "folder_ids": [fid]})
    result = ui_catalog.listing(db, {"scope": {"nature": "pitched"}, "ids_only": True, "offset": 100})
    assert result["ids"] == [root["id"]]
    folders(db, [fid])
    r = materials.get(db, root["id"])
    assert r["nature"] == "pitched" and r["folder_id"] == ""


def test_remove_parent_retains_child_source(library):
    db, root, _ = library
    child = c.derive(db, root["id"], start=0.1, end=0.5)
    assert remove(db, [root["id"]]) == 1
    r = materials.get(db, child["id"])
    assert r["derivation"]["parent_id"] is None
    assert r["derivation"]["payload"]["deleted_parent"]["id"] == root["id"]
    assert db.execute("PRAGMA foreign_key_check").fetchall() == []


def test_reset_stays_empty_after_sync_and_migration(library):
    db, root, _ = library
    c.folder(db, "历史 / 测试")
    db.execute(
        "INSERT INTO cues VALUES('cue-reset',?,1,0,.5,'a','a','a','a',NULL,'speech','[]')",
        (root["source_id"],),
    )
    source_count = db.execute("SELECT count(*) FROM sources").fetchone()[0]
    with db:
        assert reset(db)["samples"] == 1
    materials.sync_cues(db)
    c.migrate(db)
    assert db.execute("SELECT count(*) FROM materials").fetchone()[0] == 0
    assert db.execute("SELECT count(*) FROM sample_folders").fetchone()[0] == 0
    assert db.execute("SELECT count(*) FROM sources").fetchone()[0] == source_count
    fresh = materials.register_file(db, root["path"])
    c.preferences(db, fresh["id"], folder_id="inbox", nature="unpitched")
    assert materials.get(db, fresh["id"])["nature"] == "unpitched"


def test_nature_derivation_rules_and_duplicate_preservation(library):
    db, root, _ = library
    c.preferences(db, root["id"], nature="speech")
    cut = c.derive(db, root["id"], start=0.1, end=0.5, nature="unpitched")
    inherited = c.derive(db, cut["id"], start=0, end=0.2, operation="quantized")
    assert inherited["nature"] == "unpitched"
    separated = c.derive(db, cut["id"], operation="audio_source")
    assert separated["nature"] == "unpitched"
    flattened = c.derive(db, cut["id"], operation="flatten")
    assert flattened["nature"] == "pitched"
    c.preferences(db, root["id"], nature="pitched")
    assert materials.get(db, cut["id"])["nature"] == "unpitched"
    c.preferences(db, cut["id"], nature="speech")
    duplicate = c.derive(db, root["id"], start=0.1, end=0.5, nature="unpitched")
    assert duplicate["id"] == cut["id"] and duplicate["nature"] == "speech"
    c.preferences(db, cut["id"], folder_id="pitched")  # legacy destination is not a type setter
    assert materials.get(db, cut["id"])["nature"] == "speech"


def test_import_duplicate_preserves_user_choice(library):
    from ottosmasher import sample_ops

    db, root, _ = library
    c.preferences(db, root["id"], nature="unpitched")
    again = sample_ops.register(db, root["path"], nature="pitched")
    assert again["nature"] == "unpitched"


def test_source_delete_refuses_saved_samples_then_removes_analysis(library):
    from pathlib import Path

    import pytest

    from ottosmasher.source_deletion import remove_sources

    db, root, _ = library
    with pytest.raises(ValueError, match="关联采样"):
        remove_sources(db, [root["source_id"]])
    remove(db, [root["id"]])
    db.execute(
        "INSERT INTO cues VALUES('source-cue',?,1,0,.5,'a','a','a','a',NULL,'speech','[]')",
        (root["source_id"],),
    )
    db.execute("INSERT INTO analyses VALUES('source-cue','pydomino','v1','{}',0)")
    assert remove_sources(db, [root["source_id"]]) == 1
    assert db.execute("SELECT count(*) FROM cues").fetchone()[0] == 0
    assert db.execute("SELECT count(*) FROM analyses").fetchone()[0] == 0
    assert not db.execute("PRAGMA foreign_key_check").fetchall()
    assert Path(root["path"]).exists()
