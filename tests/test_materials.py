"""Directory membership, range identity, media frames and stale plan boundaries."""

from pathlib import Path

import numpy as np
import pytest
import soundfile as sf

from ottosmasher import material_operations, materials, media_operations, operation_jobs, workspace


@pytest.fixture
def directory(tmp_path, monkeypatch):
    data = tmp_path / "data"
    monkeypatch.setattr(workspace, "DATA", data)
    monkeypatch.setattr(media_operations, "DATA", data)
    monkeypatch.setattr(operation_jobs, "DATA", data)
    path = tmp_path / "日本語 中文.wav"
    # Unique quantized values expose a sample offset; stereo channels differ.
    y = np.arange(24000, dtype=np.int32) % 8000 - 4000
    samples = np.column_stack([y, -y]).astype(np.float64) / 8192
    sf.write(path, samples, 24000, subtype="PCM_24")
    db = workspace.connect()
    yield db, path, samples
    db.close()


def test_membership_is_not_copy_or_analysis(directory):
    db, path, _ = directory
    r = materials.register_file(db, path)
    assert db.execute("SELECT subtitle_path FROM sources").fetchone()[0] is None
    assert db.execute("SELECT COUNT(*) FROM cues").fetchone()[0] == 0
    before = set(path.parent.rglob("*.wav"))
    c = materials.collection(db, "rap 候选")
    materials.membership(db, r["id"], c["id"])
    materials.edit(db, r["id"], tags=["use:rap", "mood:excited"])
    assert set(path.parent.rglob("*.wav")) == before
    assert materials.query_ids(db, collection=c["id"], tags=["use:rap", "mood:excited"]) == [r["id"]]
    assert not materials.query_ids(db, tags=["use:rap", "absent"])
    assert not materials.get(db, r["id"])["rhythm_available"]
    with pytest.raises(ValueError, match="语音分析"):
        materials.binding(db, r["id"])
    materials.membership(db, r["id"], c["id"], False)
    assert materials.get(db, r["id"])["available"]


def test_cut_retains_exact_source_samples_and_manifest(directory):
    db, path, samples = directory
    first, last = 1927, 15319
    original = materials.sha256(path)
    out = media_operations.cut(path, first / 24000, last / 24000)
    y, sr = sf.read(out["path"])
    assert sr == 24000 and y.shape == (last - first, 2)
    np.testing.assert_allclose(y, samples[first:last], atol=1 / 2**23)
    assert out["source_start_frame"] == first and out["source_end_frame"] == last
    assert materials.sha256(path) == original
    assert media_operations.cut(path, first / 24000, last / 24000)["path"] == out["path"]
    with pytest.raises(ValueError, match="覆盖"):
        media_operations.cut(path, 0, 0.1, output=out["path"])
    mid = material_operations.import_manifest(db, out["path"] + ".json")[0]
    r = materials.get(db, mid)
    assert r["start"] == first / 24000 and r["end"] == last / 24000
    assert r["versions"][0]["manifest"]["time_mapping"]["source_origin"] == first / 24000


def test_version_and_missing_file_behavior(directory):
    db, path, _ = directory
    r = materials.register_file(db, path)
    out = material_operations.export(db, r["id"])
    assert materials.get(db, r["id"])["versions"][0]["id"] == out["id"]
    assert len(materials.query_ids(db)) == 1
    materials.edit(db, r["id"], preferred_version=out["id"])
    with pytest.raises(ValueError):
        materials.edit(db, r["id"], preferred_version="other")
    path.rename(path.with_suffix(".moved.wav"))
    r = materials.get(db, r["id"])
    assert not r["available"] and r["versions"][0]["available"]
    assert Path(material_operations.export(db, r["id"], version_id=out["id"])["path"]).is_file()


def test_migration_preserves_foreign_keys_and_is_idempotent(directory):
    db, path, _ = directory
    r = materials.register_file(db, path)
    backups = list((workspace.DATA / "backups").glob("*.sqlite3"))
    materials.migrate(db)
    assert db.execute("PRAGMA foreign_key_check").fetchall() == []
    assert materials.get(db, r["id"])["path"] == str(path)
    assert list((workspace.DATA / "backups").glob("*.sqlite3")) == backups


def test_jobs_persist_before_launch_and_cancel_queued(directory, monkeypatch):
    _db, path, _ = directory
    monkeypatch.setattr(operation_jobs, "launch", lambda jid: {"id": jid})
    job = operation_jobs.submit("cut", {"path": str(path), "start": 0, "end": 0.1})
    rows = operation_jobs.listing()
    assert rows[0]["status"] == "queued" and rows[0]["payload"]["end"] == 0.1
    assert operation_jobs.cancel(job["id"])["status"] == "cancelled"
    new = operation_jobs.retry(job["id"])
    assert new["id"] != job["id"]
    assert len(operation_jobs.listing()) == 2


def test_copy_is_version_not_duplicate_material(directory):
    db, path, _ = directory
    first = materials.register_file(db, path)
    copied = materials.register_file(db, path, copy=True)
    assert copied["id"] == first["id"]
    assert len(materials.query_ids(db)) == 1
    assert copied["preferred_version"]
    saved = material_operations.export(db, copied["id"], version_id=copied["preferred_version"])
    assert Path(saved["path"]).is_file() and saved["path"] != str(path)
    assert materials.sha256(saved["path"]) == materials.sha256(path)


def test_changed_export_is_not_silently_reused(directory):
    _db, path, _ = directory
    out = media_operations.cut(path, 0, 0.1)
    with open(out["path"], "ab") as f:
        f.write(b"changed")
    with pytest.raises(ValueError, match="被修改"):
        media_operations.cut(path, 0, 0.1)


def test_export_manifest_reimport_keeps_material_identity(directory):
    db, path, _ = directory
    r = materials.register_file(db, path)
    out = material_operations.export(db, r["id"])
    assert material_operations.import_manifest(db, out["path"] + ".json") == [r["id"]]
    assert materials.query_ids(db) == [r["id"]]
