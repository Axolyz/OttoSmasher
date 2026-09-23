"""Explicit batch selection, never changes the sample's bound audio."""

from .backends import BACKENDS
from .sample_analysis import ready


def inspect(db, ids, backend):
    if backend not in BACKENDS:
        raise ValueError("未知音素模型")
    result = {"backend": backend, "ready": [], "missing": [], "failed": [], "ineligible": []}
    for mid in dict.fromkeys(ids):
        row = db.execute("SELECT title,cue_id,nature FROM materials WHERE id=?", (mid,)).fetchone()
        if not row:
            raise ValueError("采样不存在")
        item = {"id": mid, "title": row["title"]}
        if not row["cue_id"] or row["nature"] != "speech":
            result["ineligible"].append(item)
            continue
        try:
            ready(db, mid, backend)
            result["ready"].append(item)
        except ValueError as e:
            state = db.execute(
                "SELECT status,error FROM sample_analysis_status WHERE material_id=? AND backend=?",
                (mid, backend),
            ).fetchone()
            result["failed" if state and state["status"] == "failed" else "missing"].append(
                {**item, "reason": str(e)}
            )
    return result


def switch(db, ids, backend):
    result = inspect(db, ids, backend)
    for item in result["ready"]:
        db.execute("UPDATE materials SET active_phone_backend=? WHERE id=?", (backend, item["id"]))
    db.commit()
    return {**result, "switched": [x["id"] for x in result["ready"]]}
