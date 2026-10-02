"""Anki-style explicit tag edits via the versioned business document service."""

from . import business_edits as edits
from .ui_catalog import effective_all


def plan(db, ids=None, tags=None, operation="add", replacement=None, global_scope=False):
    tags = sorted(set(tags or []))
    if not tags or any(not isinstance(t, str) or not t.strip() for t in tags):
        raise ValueError("请指定非空标签")
    if operation not in {"add", "remove", "rename"}:
        raise ValueError("未知标签操作")
    if operation == "rename" and (
        len(tags) != 1 or not isinstance(replacement, str) or not replacement.strip()
    ):
        raise ValueError("重命名需要一个标签和新名称")
    if global_scope and operation == "add":
        raise ValueError("全局管理只支持删除或重命名")
    ids = list(dict.fromkeys(ids or []))
    objects = []
    if global_scope:
        ids = [
            r[0]
            for r in db.execute(
                "SELECT DISTINCT material_id FROM material_tags WHERE origin='manual' AND tag IN ("
                + ",".join("?" for _ in tags)
                + ")",
                tags,
            )
        ]
    objects.extend({"type": "sample", "id": mid} for mid in ids)
    if global_scope:
        import json

        objects.extend(
            {"type": "annotation", "id": r["id"]}
            for r in db.execute("SELECT id,tags FROM timeline_annotations WHERE deleted=0")
            if set(json.loads(r["tags"])) & set(tags)
        )
        objects.extend(
            {"type": "source_labels", "id": r["source_id"]}
            for r in db.execute("SELECT source_id,work,media_type FROM source_labels")
            if any(t in tags for t in ("work:" + r["work"], "type:" + r["media_type"]))
        )
    doc = edits.export(db, objects)
    counts = {tag: sum(tag in obj["values"]["tags"] for obj in doc["objects"]) for tag in tags}
    for obj in doc["objects"]:
        old = set(obj["values"]["tags"])
        new = old | set(tags) if operation == "add" else old - set(tags)
        if operation == "rename" and old & set(tags):
            new.add(replacement.strip())
        obj["values"] = {"tags": sorted(new)}
    inherited = []
    for mid, labels in effective_all(db, ids).items():
        inherited.extend({"sample_id": mid, **t} for t in labels if t["inherited"] and t["tag"] in tags)
    preview = edits.preview(db, doc)
    return {
        "document": doc,
        "preview": preview,
        "inherited": inherited,
        "affected": len(preview["changes"]),
        "tag_counts": counts,
    }


def options(db, ids):
    result = {}
    for labels in effective_all(db, ids).values():
        counted = set()
        for t in labels:
            scope = "local" if not t["inherited"] and t.get("origin") == "manual" else "inherited"
            key = (t["tag"], scope)
            if key in counted:
                continue
            counted.add(key)
            entry = result.setdefault(t["tag"], {"tag": t["tag"], "local": 0, "inherited": 0})
            entry[scope] += 1
    return sorted(result.values(), key=lambda r: r["tag"])
