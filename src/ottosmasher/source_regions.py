"""Original-media exclusion ranges, independent of any plugin or subtitle version.

Confirmed manual ranges and explicitly applied subtitle rules exclude automatic work. Saved derivatives and
manual cuts remain available. A scan proposal is never itself an exclusion.
"""

import json
import time
from pathlib import Path

from .workspace import identity


def ensure(db):
    db.execute(
        "CREATE TABLE IF NOT EXISTS cue_subtitle_versions(cue_id TEXT PRIMARY KEY,version_id TEXT NOT NULL,ordinal INTEGER NOT NULL)"
    )
    db.execute("""CREATE TABLE IF NOT EXISTS source_regions(
      id TEXT PRIMARY KEY,source_id TEXT NOT NULL REFERENCES sources(id),
      kind TEXT NOT NULL,start REAL NOT NULL,end REAL NOT NULL,
      fingerprint TEXT NOT NULL,origin TEXT NOT NULL,payload TEXT NOT NULL,created REAL NOT NULL)""")
    db.execute("CREATE INDEX IF NOT EXISTS source_region_range ON source_regions(source_id,start,end)")

    db.execute(
        "CREATE TABLE IF NOT EXISTS source_media_identity(source_id TEXT PRIMARY KEY,fingerprint TEXT NOT NULL)"
    )
    for row in db.execute(
        "SELECT s.id,s.path,m.fingerprint FROM sources s LEFT JOIN source_media_identity m ON m.source_id=s.id"
    ).fetchall():
        try:
            st = Path(row["path"]).stat()
            fp = identity("original-media-v1", row["path"], st.st_size, st.st_mtime_ns)
        except OSError:
            fp = "missing"
        if row["fingerprint"] == fp:
            continue
        db.execute(
            "INSERT INTO source_media_identity VALUES(?,?) ON CONFLICT(source_id) DO UPDATE SET fingerprint=excluded.fingerprint WHERE fingerprint<>excluded.fingerprint",
            (row["id"], fp),
        )


def media_fingerprint(db, source_id):
    ensure(db)
    row = db.execute(
        "SELECT fingerprint FROM source_media_identity WHERE source_id=?", (source_id,)
    ).fetchone()
    if not row or row[0] == "missing":
        raise ValueError("原片文件缺失")
    return row[0]


def listing(db, source_id=None):
    ensure(db)
    return [
        dict(r)
        for r in db.execute(
            "SELECT r.*,s.title FROM source_regions r JOIN sources s ON s.id=r.source_id JOIN source_media_identity mi ON mi.source_id=s.id WHERE r.fingerprint=mi.fingerprint"
            + (" AND r.source_id=?" if source_id else "")
            + " ORDER BY s.title,r.start",
            (source_id,) if source_id else (),
        )
    ]


def blocked(db, source_id, start, end):
    ensure(db)
    return bool(
        db.execute(
            """SELECT 1 FROM source_regions r JOIN source_media_identity s ON s.source_id=r.source_id
      WHERE r.source_id=? AND r.fingerprint=s.fingerprint AND r.start<? AND r.end>? LIMIT 1""",
            (source_id, end - 1e-6, start + 1e-6),
        ).fetchone()
    )


def sql_allowed(alias="c"):
    # Caller must ensure the table. Identifiers are fixed internal aliases, never request text.
    assert alias in ("c", "m")
    return f"NOT EXISTS(SELECT 1 FROM cue_subtitle_versions cv JOIN subtitle_versions sv ON sv.id=cv.version_id WHERE cv.cue_id={alias}.{'id' if alias == 'c' else 'cue_id'} AND sv.selected=0) AND NOT EXISTS(SELECT 1 FROM source_regions r JOIN source_media_identity rs ON rs.source_id=r.source_id WHERE r.source_id={alias}.source_id AND r.fingerprint=rs.fingerprint AND r.start<{alias}.end AND r.end>{alias}.start)"


def confirm(db, source_id, start, end, kind="op", evidence=None, origin="manual-review"):
    ensure(db)
    s = db.execute("SELECT * FROM sources WHERE id=?", (source_id,)).fetchone()
    start, end = float(start), float(end)
    if not s or kind not in ("op", "ed") or not 0 <= start < end <= s["duration"]:
        raise ValueError("OP/ED 标记范围无效；必须在原片时长内")
    fp = media_fingerprint(db, source_id)
    key = identity("source-region", source_id, fp, kind, start, end)
    db.execute(
        "INSERT OR REPLACE INTO source_regions VALUES(?,?,?,?,?,?,?,?,?)",
        (
            key,
            source_id,
            kind,
            start,
            end,
            fp,
            origin,
            json.dumps(evidence or {}, ensure_ascii=False),
            time.time(),
        ),
    )
    db.commit()
    return {"id": key, "source_id": source_id, "start": start, "end": end, "kind": kind}


def remove(db, key):
    ensure(db)
    db.execute("DELETE FROM source_regions WHERE id=?", (key,))
    db.commit()


def eligible_cues(db, rows):
    return [r for r in rows if not blocked(db, r["source_id"], r["start"], r["end"])]
