"""Validated business documents shared by text UI, HTTP and CLI.

Documents carry content revisions, not writable database rows. Unknown fields
are errors; missing objects/fields are unchanged. Saving and undo are atomic.
"""

from __future__ import annotations

import json
import math
import time

from .asset_timeline import canonical, validate_scope
from .workspace import identity

SAMPLE_FIELDS = {"title", "notes", "rating", "starred", "nature", "tags"}
ANNOTATION_FIELDS = {"start", "end", "text", "tags", "scope", "delete"}


def ensure(db):
    from .frontend_service import ensure_texts

    ensure_texts(db)
    db.execute(
        "CREATE TABLE IF NOT EXISTS business_edit_actions(id TEXT PRIMARY KEY,before_doc TEXT NOT NULL,after_doc TEXT NOT NULL,undone INTEGER NOT NULL DEFAULT 0,created REAL NOT NULL)"
    )
    db.execute(
        "CREATE TABLE IF NOT EXISTS business_edit_versions(kind TEXT NOT NULL,id TEXT NOT NULL,version INTEGER NOT NULL,PRIMARY KEY(kind,id))"
    )


def _data(db, kind, oid):
    if kind == "sample":
        row = db.execute(
            "SELECT title,notes,rating,starred,nature FROM materials WHERE id=?", (oid,)
        ).fetchone()
        if not row:
            raise ValueError("采样不存在：" + oid)
        data = dict(row)
        data["starred"] = bool(data["starred"])
        data["tags"] = [
            r[0]
            for r in db.execute(
                "SELECT tag FROM material_tags WHERE material_id=? AND origin='manual' ORDER BY tag", (oid,)
            )
        ]
    elif kind == "source_labels":
        row = db.execute("SELECT work,media_type FROM source_labels WHERE source_id=?", (oid,)).fetchone()
        if not row:
            raise ValueError("原片不存在")
        data = {
            "tags": [prefix + row[k] for k, prefix in (("work", "work:"), ("media_type", "type:")) if row[k]]
        }
    elif kind == "annotation":
        row = db.execute(
            "SELECT start,end,text,tags,scope,deleted FROM timeline_annotations WHERE id=?", (oid,)
        ).fetchone()
        if not row:
            raise ValueError("时间标注不存在：" + oid)
        data = dict(row)
        data["tags"] = json.loads(data["tags"])
        data["scope"] = json.loads(data["scope"])
        data["delete"] = bool(data.pop("deleted"))
    elif kind == "alignment_text":
        from .frontend_service import alignment_text

        cue = db.execute("SELECT id,spoken FROM cues WHERE id=?", (oid,)).fetchone()
        if not cue:
            from .subtitle_speakers import spoken_text

            annotation = db.execute(
                "SELECT id,text FROM timeline_annotations WHERE id=? AND deleted=0", (oid,)
            ).fetchone()
            if not annotation:
                raise ValueError("文字标注不存在")
            cue = {"id": oid, "spoken": spoken_text(annotation["text"])}
        data = {"text": alignment_text(db, dict(cue))["text"]}
    elif kind in {"sample_visual", "source_visual"}:
        from .visual_media import editable

        data = editable(db, kind, oid)
    elif kind == "track_group":
        if not db.execute("SELECT 1 FROM sound_assets WHERE id=?", (oid,)).fetchone():
            raise ValueError("声音资产不存在")
        data = {
            "groups": [
                r[0]
                for r in db.execute(
                    "SELECT group_name FROM asset_groups WHERE asset_id=? ORDER BY group_name", (oid,)
                )
            ]
        }
    else:
        raise ValueError("未知资料类型：" + kind)
    return data


def _object(db, kind, oid):
    data = _data(db, kind, oid)
    row = db.execute(
        "SELECT version FROM business_edit_versions WHERE kind=? AND id=?", (kind, oid)
    ).fetchone()
    revision = identity("business-edit-v1", kind, oid, data, row[0] if row else 0)
    return {"type": kind, "id": oid, "base_version": revision, "values": data}


def export(db, objects):
    ensure(db)
    if len(objects) > 100000:
        raise ValueError("每次最多编辑 100000 个对象")
    return {"schema": "otto.edit/1", "objects": [_object(db, o["type"], o["id"]) for o in objects]}


def _strings(value, name):
    if (
        not isinstance(value, list)
        or len(value) > 512
        or any(not isinstance(x, str) or not x.strip() or len(x) > 500 for x in value)
    ):
        raise ValueError(name + "必须是非空文本列表（最多 512 项）")
    return sorted(set(value))


def _validate(db, kind, oid, value):
    if kind == "sample":
        if not isinstance(value["title"], str) or not value["title"].strip() or len(value["title"]) > 2000:
            raise ValueError("名称不能为空，最长 2000 字符")
        if not isinstance(value["notes"], str) or len(value["notes"]) > 100000:
            raise ValueError("备注最长 100000 字符")
        if type(value["rating"]) is not int or not 0 <= value["rating"] <= 5:
            raise ValueError("评分为 0–5 的整数")
        if type(value["starred"]) is not bool:
            raise ValueError("收藏应为 true/false")
        if value["nature"] not in ("speech", "pitched", "unpitched", "unclassified"):
            raise ValueError("未知采样性质")
        value["tags"] = _strings(value["tags"], "标签")
    elif kind == "source_labels":
        value["tags"] = _strings(value["tags"], "原片标签")
        if any(not t.startswith(("work:", "type:")) for t in value["tags"]):
            raise ValueError("原片属性标签必须保留 work: 或 type: 前缀")
        if any(sum(t.startswith(p) for t in value["tags"]) > 1 for p in ("work:", "type:")):
            raise ValueError("原片每类属性只能有一个值")
    elif kind == "annotation":
        lo, hi = value["start"], value["end"]
        if not all(type(t) in (float, int) and math.isfinite(t) for t in (lo, hi)) or not 0 <= lo < hi:
            raise ValueError("标注区间须为有限的半开区间")
        if not isinstance(value["text"], str) or len(value["text"]) > 100000:
            raise ValueError("文字过长")
        if type(value["delete"]) is not bool:
            raise ValueError("delete 必须是布尔值")
        value["tags"] = _strings(value["tags"], "标签")
        value["scope"] = validate_scope(value["scope"])
        existing = db.execute("SELECT source_id FROM timeline_annotations WHERE id=?", (oid,)).fetchone()
        sid = existing[0] if existing else value.get("source_id")
        if not db.execute("SELECT 1 FROM sources WHERE id=?", (sid,)).fetchone():
            raise ValueError("标注原片不存在")
        if not existing and value.get("kind") not in {"dialogue", "event", "tag", "song"}:
            raise ValueError("未知标注类型")
        if value["scope"]["type"] == "asset":
            if len(value["scope"]["ids"]) != 1:
                raise ValueError("资产局部坐标的标注必须指定一个资产")
            asset = db.execute(
                "SELECT source_id,duration FROM sound_assets WHERE id=?", (value["scope"]["ids"][0],)
            ).fetchone()
            if not asset or asset[0] != sid or hi > asset[1]:
                raise ValueError("标注超出声音资产范围")
        else:
            duration = db.execute("SELECT duration FROM sources WHERE id=?", (sid,)).fetchone()[0]
            if hi > duration:
                raise ValueError("标注超出原片范围")
    elif kind == "alignment_text":
        if not isinstance(value["text"], str) or not value["text"].strip() or len(value["text"]) > 10000:
            raise ValueError("对齐文本不能为空，最多 10000 字符")
    elif kind in {"sample_visual", "source_visual"}:
        from .visual_media import validate

        value = validate(value)
    elif kind == "track_group":
        value["groups"] = _strings(value["groups"], "轨道组")
    return value


def preview(db, document):
    ensure(db)
    if (
        not isinstance(document, dict)
        or set(document) != {"schema", "objects"}
        or document["schema"] != "otto.edit/1"
    ):
        raise ValueError("需要 otto.edit/1 业务文档")
    objects = document["objects"]
    if not isinstance(objects, list) or len(objects) > 100000:
        raise ValueError("objects 必须是最多 100000 项的列表")
    changes = []
    errors = []
    seen = set()
    for i, obj in enumerate(objects):
        try:
            if not isinstance(obj, dict) or set(obj) != {"type", "id", "base_version", "values"}:
                raise ValueError("对象只接受 type/id/base_version/values")
            kind, oid = obj["type"], obj["id"]
            if not isinstance(kind, str) or not isinstance(oid, str):
                raise ValueError("type/id 必须是文本")  # noqa: TRY004 - shared HTTP validation error
            if (kind, oid) in seen:
                raise ValueError("对象重复")
            seen.add((kind, oid))
            create = kind == "annotation" and obj["base_version"] == "new"
            if create:
                if db.execute("SELECT 1 FROM timeline_annotations WHERE id=?", (oid,)).fetchone():
                    raise ValueError("标注 ID 已存在")
                current = {"base_version": "new", "values": {}}
            else:
                current = _object(db, kind, oid)
            if current["base_version"] != obj["base_version"]:
                raise ValueError("版本过期，请重新载入后编辑")
            allowed = (
                SAMPLE_FIELDS
                if kind == "sample"
                else ANNOTATION_FIELDS
                if kind == "annotation"
                else {"tags"}
                if kind == "source_labels"
                else {"text"}
                if kind == "alignment_text"
                else {"mode", "path"}
                if kind in {"sample_visual", "source_visual"}
                else {"groups"}
            )
            if create:
                allowed = ANNOTATION_FIELDS | {"source_id", "kind"}
            if not isinstance(obj["values"], dict) or set(obj["values"]) - allowed:
                raise ValueError("包含不可编辑字段")
            after = _validate(db, kind, oid, {**current["values"], **obj["values"]})
            fields = {
                key: {"before": current["values"].get(key), "after": val}
                for key, val in after.items()
                if val != current["values"].get(key)
            }
            if fields:
                changes.append(
                    {
                        "create": create,
                        "type": kind,
                        "id": oid,
                        "fields": fields,
                        "before": current["values"],
                        "after": after,
                    }
                )
        except (ValueError, TypeError, KeyError, OSError) as exc:
            errors.append({"path": f"objects[{i}]", "message": str(exc)})
    return {
        "valid": not errors,
        "errors": errors,
        "changes": changes,
        "impact": {
            "objects": len(changes),
            "indexes": sorted(
                {
                    "tag_scope" if c["type"] in ("sample", "track_group") else "annotation_scope"
                    for c in changes
                }
            ),
            "media_changed": False,
        },
    }


def _write(db, kind, oid, value):
    if kind == "sample":
        db.execute(
            "UPDATE materials SET title=?,notes=?,rating=?,starred=?,nature=? WHERE id=?",
            tuple(value[k] for k in ("title", "notes", "rating", "starred", "nature")) + (oid,),
        )
        db.execute("DELETE FROM material_tags WHERE material_id=? AND origin='manual'", (oid,))
        db.executemany("INSERT INTO material_tags VALUES(?,?,'manual')", [(oid, t) for t in value["tags"]])
    elif kind == "source_labels":
        for key, prefix in (("work", "work:"), ("media_type", "type:")):
            text = next((t[len(prefix) :] for t in value["tags"] if t.startswith(prefix)), "")
            db.execute(f"UPDATE source_labels SET {key}=? WHERE source_id=?", (text, oid))
    elif kind == "annotation":
        db.execute(
            "UPDATE timeline_annotations SET start=?,end=?,text=?,tags=?,scope=?,deleted=?,revision=revision+1 WHERE id=?",
            (
                value["start"],
                value["end"],
                value["text"],
                canonical(value["tags"]),
                canonical(value["scope"]),
                int(value["delete"]),
                oid,
            ),
        )
        db.execute(
            "DELETE FROM sample_records WHERE material_id IN (SELECT id FROM materials WHERE cue_id=?)",
            (oid,),
        )
    elif kind == "alignment_text":
        db.execute(
            "INSERT INTO alignment_texts VALUES(?,?,1) ON CONFLICT(annotation_id) DO UPDATE SET text=excluded.text,revision=revision+1",
            (oid, value["text"]),
        )
    elif kind in {"sample_visual", "source_visual"}:
        from .visual_media import write

        write(db, kind, oid, value)
    elif kind == "track_group":
        db.execute("DELETE FROM asset_groups WHERE asset_id=?", (oid,))
        db.executemany("INSERT INTO asset_groups VALUES(?,?)", [(oid, g) for g in value["groups"]])
    db.execute(
        "INSERT INTO business_edit_versions VALUES(?,?,1) ON CONFLICT(kind,id) DO UPDATE SET version=version+1",
        (kind, oid),
    )


def apply(db, document):
    ensure(db)
    if db.in_transaction:
        raise ValueError("编辑必须使用独立事务")
    with db:
        db.execute("BEGIN IMMEDIATE")
        result = preview(db, document)
        if not result["valid"]:
            return result
        before = []
        after = []
        for change in result["changes"]:
            kind, oid = change["type"], change["id"]
            if change.get("create"):
                v = change["after"]
                db.execute(
                    "INSERT INTO timeline_annotations VALUES(?,?,?,?,?,?,?,?,1,1)",
                    (
                        oid,
                        v["source_id"],
                        v["start"],
                        v["end"],
                        v["kind"],
                        v["text"],
                        canonical(v["tags"]),
                        canonical(v["scope"]),
                    ),
                )
            before.append(_object(db, kind, oid))
            _write(db, kind, oid, change["after"])
            after.append(_object(db, kind, oid))
        action_id = None
        if before:
            action_id = identity("business-edit", before, after, time.time_ns())
            db.execute(
                "INSERT INTO business_edit_actions VALUES(?,?,?,0,?)",
                (action_id, canonical(before), canonical(after), time.time()),
            )
    return {**result, "action_id": action_id, "document": {"schema": "otto.edit/1", "objects": after}}


def undo(db, action_id=None):
    ensure(db)
    if db.in_transaction:
        raise ValueError("撤销必须使用独立事务")
    with db:
        db.execute("BEGIN IMMEDIATE")
        rows = db.execute(
            "SELECT * FROM business_edit_actions WHERE undone=0"
            + (" AND id=?" if action_id else "")
            + " ORDER BY created DESC",
            (action_id,) if action_id else (),
        ).fetchall()
        for row in rows:
            before, after = json.loads(row["before_doc"]), json.loads(row["after_doc"])
            try:
                current = [_object(db, o["type"], o["id"]) for o in after]
            except ValueError:
                continue
            if any(c["base_version"] != o["base_version"] for c, o in zip(current, after)):
                continue
            for old in before:
                value = _validate(db, old["type"], old["id"], old["values"])
                _write(db, old["type"], old["id"], value)
            db.execute("UPDATE business_edit_actions SET undone=1 WHERE id=?", (row["id"],))
            return {"undone": row["id"], "objects": [_object(db, o["type"], o["id"]) for o in before]}
        raise ValueError("没有仍可安全撤销的资料修改；后续编辑不会被覆盖")


def new_annotation(db, source_id, start, end, kind="tag", text="", tags=None, scope=None):
    ensure(db)
    oid = identity("timeline-annotation", source_id, time.time_ns())
    values = {
        "source_id": source_id,
        "start": start,
        "end": end,
        "kind": kind,
        "text": text,
        "tags": tags or [],
        "scope": scope or {"type": "source", "ids": []},
        "delete": False,
    }
    return {
        "schema": "otto.edit/1",
        "objects": [{"type": "annotation", "id": oid, "base_version": "new", "values": values}],
    }


def promote_tags(db, sample_id, scope=None):
    """Return one editable transaction; nothing is promoted until it is saved."""
    from .selection_ops import from_sample, resolve

    current = export(db, [{"type": "sample", "id": sample_id}])
    sample = current["objects"][0]
    tags = sample["values"]["tags"]
    if not tags:
        raise ValueError("当前采样没有可提升的本地人工标签")
    selected, asset = resolve(db, from_sample(db, sample_id))
    sid = db.execute("SELECT source_id FROM sound_assets WHERE id=?", (selected.asset_id,)).fetchone()[0]
    groups = [
        r[0] for r in db.execute("SELECT group_name FROM asset_groups WHERE asset_id=?", (selected.asset_id,))
    ]
    scope = scope or (
        {"type": "group", "ids": groups} if groups else {"type": "asset", "ids": [selected.asset_id]}
    )
    if scope["type"] == "asset":
        lo, hi = selected.start, selected.end
    else:
        knots = asset.get("root_knots")
        if not knots:
            raise ValueError("没有可提升到原片的时间映射")
        lo, hi = knots[0][1], knots[-1][1]
    draft = new_annotation(db, sid, lo, hi, tags=tags, scope=scope)
    sample["values"] = {"tags": []}
    draft["objects"].append(sample)
    return draft
