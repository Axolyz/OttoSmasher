"""Persist completed result sets, never executable/live saved queries."""

import json
import time
import uuid

from .asset_timeline import canonical


def ensure(db):
    db.execute("""CREATE TABLE IF NOT EXISTS search_sessions(
        id TEXT PRIMARY KEY,kind TEXT NOT NULL,title TEXT NOT NULL,query TEXT NOT NULL,
        metadata TEXT NOT NULL,state TEXT NOT NULL,created REAL NOT NULL)""")
    db.execute("""CREATE TABLE IF NOT EXISTS search_session_rows(
        session_id TEXT NOT NULL,ordinal INTEGER NOT NULL,sample_id TEXT,binding TEXT,
        payload TEXT NOT NULL,PRIMARY KEY(session_id,ordinal))""")


def binding(db, mid):
    row = db.execute(
        "SELECT asset_id,start,end,revision FROM asset_samples WHERE sample_id=?", (mid,)
    ).fetchone()
    return canonical(dict(row)) if row else None


def create(db, kind, query, result, title=None):
    ensure(db)
    if kind not in ("speech", "pitch") or not isinstance(query, dict) or not isinstance(result, dict):
        raise ValueError("无效搜索结果类型")
    rows = result.get("results", [])
    if not isinstance(rows, list):
        raise ValueError("结果集合过大")
    sid = uuid.uuid4().hex
    name = (title or ("音高" if kind == "pitch" else "节奏") + " · " + time.strftime("%H:%M:%S"))[:200]
    meta = {k: v for k, v in result.items() if k != "results"}
    with db:
        db.execute(
            "INSERT INTO search_sessions VALUES(?,?,?,?,?,?,?)",
            (sid, kind, name, canonical(query), canonical(meta), "{}", time.time()),
        )
        for ordinal, row in enumerate(rows):
            mid = row.get("material_id") or row.get("id")
            if row.get("source_result"):
                mid = None
            db.execute(
                "INSERT INTO search_session_rows VALUES(?,?,?,?,?)",
                (sid, ordinal, mid, binding(db, mid) if mid else None, canonical(row)),
            )
    return {"id": sid, "kind": kind, "title": name, "count": len(rows), "state": {}}


def listing(db):
    ensure(db)
    return [
        {**dict(r), "state": json.loads(r["state"])}
        for r in db.execute("""SELECT s.id,s.kind,s.title,s.state,s.created,
        (SELECT count(*) FROM search_session_rows r WHERE r.session_id=s.id) count
        FROM search_sessions s ORDER BY s.created""")
    ]


def read(db, sid, offset=0, limit=100):
    ensure(db)
    if offset < 0 or not 1 <= limit <= 100:
        raise ValueError("无效分页")
    session = db.execute("SELECT * FROM search_sessions WHERE id=?", (sid,)).fetchone()
    if not session:
        raise ValueError("结果标签页不存在")
    metadata = json.loads(session["metadata"])
    invalid_tracks = set()
    if session["kind"] == "pitch":
        from .pitch_search import validate_track

        for tid, version in metadata.get("index_versions", {}).items():
            track = db.execute("SELECT * FROM pitch_tracks WHERE id=?", (tid,)).fetchone()
            try:
                if not track or track["signature"] != version:
                    raise ValueError("索引版本变化")
                validate_track(track)
            except (ValueError, OSError, KeyError):
                invalid_tracks.add(tid)
    rows = []
    for stored in db.execute(
        "SELECT * FROM search_session_rows WHERE session_id=? ORDER BY ordinal LIMIT ? OFFSET ?",
        (sid, limit, offset),
    ):
        row = json.loads(stored["payload"])
        if stored["sample_id"]:
            current = db.execute(
                "SELECT title,starred FROM materials WHERE id=?", (stored["sample_id"],)
            ).fetchone()
            if not current:
                row["result_status"] = "deleted"
            elif binding(db, stored["sample_id"]) != stored["binding"]:
                row["result_status"] = "changed"
            else:
                row.update(
                    title=current["title"], sample_title=current["title"], starred=bool(current["starred"])
                )
            if row.get("result_status"):
                row["hits"] = [{**h, "disabled": True} for h in row.get("hits", [])]
        if any(h.get("asset_id") in invalid_tracks for h in row.get("hits", [])):
            row["result_status"] = "changed"
            row["hits"] = [{**h, "disabled": True} for h in row.get("hits", [])]
        if (
            row.get("source_result")
            and not db.execute("SELECT 1 FROM sound_assets WHERE id=?", (row["id"],)).fetchone()
        ):
            row["result_status"] = "deleted"
            row["hits"] = [{**h, "disabled": True} for h in row.get("hits", [])]
        rows.append(row)
    return {
        **metadata,
        "results": rows,
        "query": json.loads(session["query"]),
        "kind": session["kind"],
        "state": json.loads(session["state"]),
        "total": db.execute("SELECT count(*) FROM search_session_rows WHERE session_id=?", (sid,)).fetchone()[
            0
        ],
    }


def update(db, sid, state):
    ensure(db)
    if set(state) - {"selected_id", "scroll", "offset", "active"}:
        raise ValueError("未知结果界面状态")
    old = db.execute("SELECT state FROM search_sessions WHERE id=?", (sid,)).fetchone()
    if not old:
        raise ValueError("结果标签页不存在")
    if "scroll" in state and (not isinstance(state["scroll"], (int, float)) or state["scroll"] < 0):
        raise ValueError("无效滚动位置")
    if "offset" in state and (type(state["offset"]) is not int or state["offset"] < 0):
        raise ValueError("无效分页")
    with db:
        if state.get("active"):
            for r in db.execute("SELECT id,state FROM search_sessions"):
                value = json.loads(r["state"])
                value["active"] = False
                db.execute("UPDATE search_sessions SET state=? WHERE id=?", (canonical(value), r["id"]))
        db.execute(
            "UPDATE search_sessions SET state=? WHERE id=?",
            (canonical({**json.loads(old["state"]), **state}), sid),
        )
    return {"saved": True}


def close(db, sid):
    ensure(db)
    with db:
        db.execute("DELETE FROM search_session_rows WHERE session_id=?", (sid,))
        db.execute("DELETE FROM search_sessions WHERE id=?", (sid,))
    return {"closed": True}
