"""User-directed file relocation, without asserting content equivalence."""

from pathlib import Path
import json
import time


def ensure(db):
    db.execute(
        "CREATE TABLE IF NOT EXISTS source_locations(source_id TEXT,old_path TEXT,new_path TEXT,created REAL,PRIMARY KEY(source_id,old_path))"
    )


def relocate(db, source_id, path):
    ensure(db)
    target = str(Path(path).expanduser().resolve(strict=True))
    if not Path(target).is_file():
        raise ValueError("请选择文件")
    row = db.execute("SELECT path FROM sources WHERE id=?", (source_id,)).fetchone()
    if not row:
        raise ValueError("原片不存在")
    with db:
        db.execute("UPDATE source_locations SET new_path=? WHERE source_id=?", (target, source_id))
        db.execute(
            "INSERT INTO source_locations VALUES(?,?,?,?) ON CONFLICT(source_id,old_path) DO UPDATE SET new_path=excluded.new_path",
            (source_id, row[0], target, time.time()),
        )
        db.execute("UPDATE sources SET path=? WHERE id=?", (target, source_id))
    from .media_operations import _source_probe

    _source_probe.cache_clear()
    return {"source_id": source_id, "path": target, "identity_verified": False}


def resolve_descriptor(db, source_id, descriptor):
    if not db.execute("SELECT 1 FROM sqlite_master WHERE name='source_locations'").fetchone():
        return descriptor
    locations = dict(
        db.execute("SELECT old_path,new_path FROM source_locations WHERE source_id=?", (source_id,))
    )

    def walk(value):
        if isinstance(value, dict):
            return {
                k: (
                    locations.get(v, v)
                    if k in {"path", "source_path", "audio_path"} and isinstance(v, str)
                    else walk(v)
                )
                for k, v in value.items()
            }
        if isinstance(value, list):
            return [walk(v) for v in value]
        return value

    return walk(descriptor)


def original_path(db, path):
    if not db.execute("SELECT 1 FROM sqlite_master WHERE name='source_locations'").fetchone():
        return path
    row = db.execute(
        "SELECT old_path FROM source_locations WHERE new_path=? ORDER BY created LIMIT 1", (path,)
    ).fetchone()
    return row[0] if row else path


def identity_descriptor(db, descriptor):
    def walk(value):
        if isinstance(value, dict):
            return {
                k: (
                    original_path(db, v)
                    if k in {"path", "source_path", "audio_path"} and isinstance(v, str)
                    else walk(v)
                )
                for k, v in value.items()
            }
        if isinstance(value, list):
            return [walk(v) for v in value]
        return value

    return walk(descriptor)
