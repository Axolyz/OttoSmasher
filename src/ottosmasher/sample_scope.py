"""Shared read-only catalog scope, independent of query mode and UI."""

from .materials import query_ids


def ids(db, scope=None):
    s = scope or {}

    natures = set(s.get("natures") or [])
    selected = set(s.get("material_ids") or [])
    eligible = set(
        query_ids(
            db,
            text=s.get("text", s.get("q", "")),
            tags=s.get("tags", []),
            source_id=s.get("source_id"),
            tag_expression=s.get("tag_expression", ""),
        )
    )
    if s.get("work"):
        eligible.intersection_update(
            r[0]
            for r in db.execute(
                "SELECT m.id FROM materials m JOIN source_labels l ON l.source_id=m.source_id WHERE l.work=?",
                (s["work"],),
            )
        )
    if s.get("single_tag"):
        eligible.intersection_update(query_ids(db, tags=[s["single_tag"]]))
    for scope in s.get("intersections", []):
        if scope.get("intersections"):
            raise ValueError("筛选范围不支持递归引用")
        subset = ids(db, scope)
        if scope.get("conditions"):
            from .timbre_features import filter_ids

            subset, _ = filter_ids(db, subset, scope["conditions"], scope.get("producer", "otto.dsp"))
        eligible.intersection_update(subset)
    return [
        r["id"]
        for r in db.execute("SELECT id,status,pool,starred,nature FROM materials")
        if r["id"] in eligible
        and r["status"] != "discarded"
        and (not natures or r["nature"] in natures)
        and (not s.get("nature") or r["nature"] == s["nature"])
        and (not selected or r["id"] in selected)
        and r["status"] != "pending"
        and (s.get("pool", "all") == "all" or r["pool"] == s["pool"])
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
