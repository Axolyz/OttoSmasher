"""Remove a registered source and its source-bound analysis, never its media file."""

from .sample_deletion import remove


def remove_sources(db, ids):
    db.execute("CREATE TEMP TABLE IF NOT EXISTS deleting_sources(id TEXT PRIMARY KEY)")
    db.execute("DELETE FROM deleting_sources")
    db.executemany("INSERT INTO deleting_sources VALUES(?)", [(x,) for x in set(ids)])
    if db.execute("SELECT 1 FROM operation_jobs WHERE status IN ('running','queued')").fetchone():
        raise ValueError("请先结束正在运行的任务，再删除原片")
    if db.execute(
        "SELECT 1 FROM materials WHERE source_id IN (SELECT id FROM deleting_sources) AND pool<>'source-browser'"
    ).fetchone():
        raise ValueError("这些原片仍有关联采样，请先删除关联采样，再删除原片")
    remove(
        db,
        [
            r[0]
            for r in db.execute(
                "SELECT id FROM materials WHERE source_id IN (SELECT id FROM deleting_sources)"
            )
        ],
    )
    tables = [r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table'")]
    for table in tables:
        columns = {r[1] for r in db.execute(f'PRAGMA table_info("{table}")')}
        if "cue_id" in columns:
            db.execute(
                f'DELETE FROM "{table}" WHERE cue_id IN (SELECT id FROM cues WHERE source_id IN (SELECT id FROM deleting_sources))'
            )
    for table in tables:
        if table == "cues":
            continue
        columns = {r[1] for r in db.execute(f'PRAGMA table_info("{table}")')}
        if "source_id" in columns:
            db.execute(f'DELETE FROM "{table}" WHERE source_id IN (SELECT id FROM deleting_sources)')
    db.execute("DELETE FROM cues WHERE source_id IN (SELECT id FROM deleting_sources)")
    return db.execute("DELETE FROM sources WHERE id IN (SELECT id FROM deleting_sources)").rowcount
