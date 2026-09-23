import json
import os
import sqlite3
import time

import pytest

from ottosmasher.cache_storage import clean, status


def setup(tmp_path):
    db = sqlite3.connect(":memory:")
    for name in ("sample_assets", "processed_audio_assets", "sample_records"):
        db.execute(f"CREATE TABLE {name}(id TEXT, payload TEXT)")
    db.execute("CREATE TABLE operation_jobs(status TEXT)")
    return db


def file(root, name, content="cache"):
    p = root / name
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(content)
    os.utime(p, (time.time() - 86400 * 10,) * 2)
    return p


def test_keep_saved_assets_and_lineage_but_delete_orphan_outputs(tmp_path):
    db = setup(tmp_path)
    saved = file(tmp_path, "data/media/plugin-output/saved.wav")
    raw = file(tmp_path, "data/alignment/raw.json", json.dumps({"input": str(saved)}))
    unused = file(tmp_path, "data/media/plugin-output/unused.wav")
    cache = file(tmp_path, "data/cache/proxies/old.mp4")
    original = file(tmp_path, "bangumi/original.mkv")
    model = file(tmp_path, "models/model.pt")
    features = file(tmp_path, "data/sample-cache/a.features.json")
    db.execute(
        "INSERT INTO sample_assets VALUES(?,?)",
        ("sample", json.dumps({"path": str(saved), "raw_output": str(raw)})),
    )
    for name, p in [("used", saved), ("unused", unused)]:
        db.execute(
            "INSERT INTO processed_audio_assets VALUES(?,?)", (name, json.dumps({"asset": {"path": str(p)}}))
        )
    result = clean(db, tmp_path)
    assert result["removed_files"] == 2
    assert saved.exists() and raw.exists() and features.exists() and original.exists() and model.exists()
    assert not cache.exists() and not unused.exists()
    assert list(db.execute("SELECT id FROM processed_audio_assets")) == [("used",)]


def test_no_symlink_traversal_and_recent_files_kept(tmp_path):
    db = setup(tmp_path)
    outside = tmp_path / "private"
    outside.mkdir()
    target = file(tmp_path, "private/important.wav")
    recent = file(tmp_path, "data/sample-cache/new.wav")
    os.utime(recent, None)
    (tmp_path / "data/sample-cache/linked").symlink_to(outside, target_is_directory=True)
    (tmp_path / "data/sample-cache/linked.wav").symlink_to(target)
    clean(db, tmp_path)
    assert target.exists() and recent.exists()


def test_active_jobs_block_cleanup(tmp_path):
    db = setup(tmp_path)
    p = file(tmp_path, "data/cache/old.wav")
    db.execute("INSERT INTO operation_jobs VALUES('queued')")
    assert status(db, tmp_path)["active_jobs"]
    with pytest.raises(ValueError, match="任务"):
        clean(db, tmp_path)
    assert p.exists()


def test_auto_only_evicts_expired_cheap_caches(tmp_path):
    db = setup(tmp_path)
    p = file(tmp_path, "data/cache/old.wav")
    model_result = file(tmp_path, "data/media/processed/expensive.wav")
    clean(db, tmp_path, automatic=True)
    assert not p.exists() and model_result.exists()
