import sqlite3

import pytest

from ottosmasher.core.errors import CoreError
from ottosmasher.store.db import Migration, bundled_migrations, connect, current_version, migrate
from ottosmasher.store.workspace import FIXED_DIRS, Workspace, WorkspaceLock


def test_fresh_workspace_has_english_fixed_dirs(ws: Workspace):
    for rel in FIXED_DIRS:
        assert (ws.root / rel).is_dir()
        assert rel.isascii()


def test_ensure_is_idempotent(ws: Workspace):
    ws.ensure()
    ws.ensure()


def test_fresh_migration_no_backup(ws: Workspace):
    conn = connect(ws.db_path)
    rep = migrate(conn, ws.backups)
    assert rep.from_version == 0 and rep.to_version == len(bundled_migrations())
    assert rep.backup is None
    assert current_version(conn) == rep.to_version
    assert conn.execute("PRAGMA journal_mode").fetchone()[0] == "wal"
    # 再迁移一次什么也不做
    assert migrate(conn, ws.backups).backup is None


def test_migration_of_existing_db_writes_consistent_backup(ws: Workspace, db: sqlite3.Connection):
    db.execute("INSERT INTO setting(key, value, version, updated_at) VALUES ('x', '1', 1, 'now')")
    base = bundled_migrations()
    extra = Migration(len(base) + 1, f"{len(base) + 1:04d}_extra.sql", "CREATE TABLE extra_t (a INTEGER)")
    rep = migrate(db, ws.backups, base + [extra])
    assert rep.backup is not None and rep.backup.exists()
    bk = sqlite3.connect(rep.backup)
    assert bk.execute("SELECT value FROM setting WHERE key='x'").fetchone()[0] == "1"
    assert current_version(bk) == len(base)


def test_failed_migration_rolls_back_and_keeps_backup(ws: Workspace, db: sqlite3.Connection):
    base = bundled_migrations()
    bad = Migration(len(base) + 1, f"{len(base) + 1:04d}_bad.sql", "CREATE TABLE ok_t (a INTEGER);\nSELECT * FROM no_such_table")
    with pytest.raises(CoreError) as ei:
        migrate(db, ws.backups, base + [bad])
    assert ei.value.code == "schema-migration-failed"
    assert ei.value.args_["backup"]
    assert current_version(db) == len(base)
    assert db.execute("SELECT name FROM sqlite_master WHERE name='ok_t'").fetchone() is None


def test_schema_too_new_is_refused(ws: Workspace, db: sqlite3.Connection):
    db.execute("INSERT INTO schema_migrations(version, name, applied_at) VALUES (999, 'future', 'now')")
    with pytest.raises(CoreError) as ei:
        migrate(db, ws.backups)
    assert ei.value.code == "schema-too-new"


def test_workspace_lock_is_exclusive(ws: Workspace):
    a = WorkspaceLock(ws)
    a.acquire()
    b = WorkspaceLock(ws)
    with pytest.raises(CoreError) as ei:
        b.acquire()
    assert ei.value.code == "workspace-locked"
    a.release()
    b.acquire()
    b.release()
