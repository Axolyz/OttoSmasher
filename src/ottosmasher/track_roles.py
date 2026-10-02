"""Shared track roles and per-source defaults; sample bindings never follow defaults."""

import json
from . import asset_timeline as t

GROUPS = {"speech": "dialogue", "effects": "effects"}


def ensure(db):
    t.ensure(db)
    db.execute(
        "CREATE TABLE IF NOT EXISTS source_default_tracks(source_id TEXT,role TEXT,asset_id TEXT REFERENCES sound_assets(id),PRIMARY KEY(source_id,role))"
    )


def listing(db, source_id):
    ensure(db)
    from .sound_assets import source

    row = db.execute("SELECT * FROM sources WHERE id=?", (source_id,)).fetchone()
    if not row:
        raise ValueError("原片不存在")
    # Register existing source audio streams, but do not require an available raw file to list old assets.
    from pathlib import Path

    if Path(row["path"]).is_file():
        for stream in json.loads(row["metadata"])["streams"]:
            if stream["codec_type"] == "audio":
                d = source(db, {"source_id": source_id, "audio_stream": stream["index"]})["asset"]
                t.register_asset(db, source_id, d)
    defaults = dict(
        db.execute("SELECT role,asset_id FROM source_default_tracks WHERE source_id=?", (source_id,))
    )
    result = []
    for a in db.execute("SELECT * FROM sound_assets WHERE source_id=? ORDER BY created", (source_id,)):
        from .source_locations import resolve_descriptor

        d = resolve_descriptor(db, source_id, json.loads(a["descriptor"]))
        groups = {
            r[0] for r in db.execute("SELECT group_name FROM asset_groups WHERE asset_id=?", (a["id"],))
        }
        mapping = json.loads(a["mapping"]) if a["mapping"] else None
        result.append(
            {
                "id": a["id"],
                "title": d.get("title") or d.get("role", "音轨"),
                "path": d.get("path"),
                "stream": d.get("audio_stream", 0),
                "start": mapping[0][1] if mapping else None,
                "end": mapping[-1][1] if mapping else None,
                "roles": [role for role, group in GROUPS.items() if group in groups],
                "defaults": [role for role, aid in defaults.items() if aid == a["id"]],
            }
        )
    db.commit()
    return result


def configure(db, source_id, asset_id, roles, defaults):
    ensure(db)
    if set(roles) - GROUPS.keys() or set(defaults) - set(roles):
        raise ValueError("默认轨必须具有对应角色")
    if not db.execute(
        "SELECT 1 FROM sound_assets WHERE id=? AND source_id=?", (asset_id, source_id)
    ).fetchone():
        raise ValueError("音轨不属于此原片")
    with db:
        for role, group in GROUPS.items():
            if role in roles:
                db.execute("INSERT OR IGNORE INTO asset_groups VALUES(?,?)", (asset_id, group))
            else:
                db.execute("DELETE FROM asset_groups WHERE asset_id=? AND group_name=?", (asset_id, group))
            if role in defaults:
                db.execute(
                    "INSERT OR REPLACE INTO source_default_tracks VALUES(?,?,?)", (source_id, role, asset_id)
                )
            else:
                db.execute(
                    "DELETE FROM source_default_tracks WHERE source_id=? AND role=? AND asset_id=?",
                    (source_id, role, asset_id),
                )
    return listing(db, source_id)


def default_asset(db, source_id, kind):
    ensure(db)
    role = "effects" if kind == "event" else "speech"
    row = db.execute(
        "SELECT a.* FROM source_default_tracks d JOIN sound_assets a ON a.id=d.asset_id JOIN asset_groups g ON g.asset_id=a.id AND g.group_name=? WHERE d.source_id=? AND d.role=?",
        (GROUPS[role], source_id, role),
    ).fetchone()
    if not row:
        raise ValueError("请先指定默认" + ("音效轨" if role == "effects" else "人声轨"))
    return row


def nature(db, asset_id):
    groups = {r[0] for r in db.execute("SELECT group_name FROM asset_groups WHERE asset_id=?", (asset_id,))}
    roles = groups & set(GROUPS.values())
    return "speech" if roles == {"dialogue"} else "unpitched" if roles == {"effects"} else "unclassified"
