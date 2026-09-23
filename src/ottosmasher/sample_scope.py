"""Shared read-only catalog scope, independent of query mode and UI."""

from .materials import query_ids


def ids(db, scope=None):
    s = scope or {}
    folders = set(s.get("folder_ids") or ([s["folder_id"]] if s.get("folder_id") else []))
    selected = set(s.get("material_ids") or [])
    eligible = set(
        query_ids(
            db, text=s.get("text", s.get("q", "")), tags=s.get("tags", []), source_id=s.get("source_id")
        )
    )
    return [
        r["id"]
        for r in db.execute("SELECT id,status,pool,folder_id,starred,nature FROM materials")
        if r["id"] in eligible
        and r["status"] != "discarded"
        and (not s.get("nature") or r["nature"] == s["nature"])
        and (not selected or r["id"] in selected)
        and (r["folder_id"] in folders if folders else r["status"] != "pending")
        and (folders or s.get("pool", "all") == "all" or r["pool"] == s["pool"])
        and (not s.get("starred") or r["starred"])
    ]


def search(db, scope=None, conditions=None, producer="otto.dsp", offset=0):
    from . import materials, timbre_features

    candidates = ids(db, scope)
    if conditions:
        filtered, unknown = timbre_features.filter_ids(db, candidates, conditions, producer)
    else:
        filtered, unknown = candidates, 0
    offset = max(0, int(offset))
    return {
        "total": len(filtered),
        "unknown": unknown,
        "results": [materials.get(db, mid) for mid in filtered[offset : offset + 50]],
    }
