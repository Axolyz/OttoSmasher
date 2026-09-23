from pathlib import Path

import pytest
from test_samples import library as library  # noqa: PLC0414

from ottosmasher import materials, source_regions
from ottosmasher import source_preparation as prep


def subtitle(tmp_path, text="ねえ"):
    p = tmp_path / "clean.srt"
    p.write_text(
        f"1\n00:00:00,000 --> 00:00:00,250\n{text}\n\n2\n00:00:00,300 --> 00:00:00,800\nこんにちは\n"
    )
    return p


def test_source_without_subtitles_and_immutable_revisions(library, tmp_path):
    db, root, _ = library
    before = db.execute("SELECT count(*) FROM materials").fetchone()[0]
    r = prep.register(db, [root["path"]])
    assert r["source_ids"] == [root["source_id"]]
    assert db.execute("SELECT count(*) FROM materials").fetchone()[0] == before
    rows = prep.listing(db)
    assert rows[0]["cues"] == 0
    p = subtitle(tmp_path)
    prep.configure(db, root["source_id"], subtitle_path=str(p), op_review="skipped")
    preview = prep.preview(db, root["source_id"])
    first = prep.ingest(db, root["source_id"], preview["token"])
    ids = set(prep.selected_materials(db, source_ids=[root["source_id"]]))
    assert len(ids) == 2
    prep.ingest(db, root["source_id"], preview["token"])
    assert ids == set(prep.selected_materials(db, source_ids=[root["source_id"]]))
    subtitle(tmp_path, "新しい")
    with pytest.raises(ValueError, match="改变"):
        prep.ingest(db, root["source_id"], preview["token"])
    preview = prep.preview(db, root["source_id"])
    second = prep.ingest(db, root["source_id"], preview["token"])
    assert first["version_id"] != second["version_id"]
    assert not ids & set(prep.selected_materials(db, source_ids=[root["source_id"]]))
    for mid in ids:
        assert materials.get(db, mid)["cue_id"] == mid
    versions = db.execute(
        "SELECT path FROM subtitle_versions WHERE source_id=?", (root["source_id"],)
    ).fetchall()
    assert any("ねえ" in Path(v[0]).read_text() for v in versions)


def test_review_gate_exclusion_and_manual_cut(library, tmp_path):
    from ottosmasher import sample_ops

    db, root, _ = library
    p = subtitle(tmp_path)
    prep.configure(db, root["source_id"], subtitle_path=str(p))
    before = prep.preview(db, root["source_id"])
    with pytest.raises(ValueError, match="OP/ED"):
        prep.ingest(db, root["source_id"], before["token"])
    source_regions.confirm(db, root["source_id"], 0.1, 0.26)
    prep.configure(db, root["source_id"], op_review="reviewed")
    preview = prep.preview(db, root["source_id"])
    assert preview["counts"]["excluded"] == 1 and preview["boundary_count"] == 1
    prep.ingest(db, root["source_id"], preview["token"])
    assert len(prep.selected_materials(db, source_ids=[root["source_id"]])) == 1
    child = sample_ops.source_selection(db, root["id"], 0.1, 0.2, role="raw")
    assert child["id"] in materials.query_ids(db)


def test_single_default_model_and_scope(library, monkeypatch):
    from ottosmasher import preparation_jobs

    db, root, _ = library
    db.execute(
        "INSERT INTO cues VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
        ("c", root["source_id"], 1, 0, 0.9, "あ", "あ", "あ", "あ", None, "dialogue", "[]"),
    )
    materials.sync_cues(db)
    report = preparation_jobs.inspect(db, material_ids=["c"])
    assert report["backends"] == ["narabas"] and report["material_ids"] == ["c"]
    source_regions.confirm(db, root["source_id"], 0.2, 0.4)
    assert preparation_jobs.inspect(db, material_ids=["c"])["total"] == 0


def test_fresh_workspace_concurrent_connections(tmp_path, monkeypatch):
    from concurrent.futures import ThreadPoolExecutor

    from ottosmasher import workspace

    monkeypatch.setattr(workspace, "DATA", tmp_path / "fresh")

    def one(_):
        db = workspace.connect()
        result = db.execute("SELECT count(*) FROM materials").fetchone()[0]
        db.close()
        return result

    with ThreadPoolExecutor(max_workers=6) as pool:
        assert list(pool.map(one, range(12))) == [0] * 12
