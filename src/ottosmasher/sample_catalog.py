"""Sample identities, single-folder membership and immutable derivation edges."""

import json
import sqlite3
import time
from pathlib import Path

from .backends import BACKENDS as BACKEND_SPECS
from .workspace import identity

BACKENDS = tuple(BACKEND_SPECS)
FOLDERS = {"speech": "语音", "pitched": "调谐单音", "unpitched": "非调谐单音", "inbox": "未归档"}


def migrate(db):
    db.executescript(
        """CREATE TABLE IF NOT EXISTS sample_measurements(material_id TEXT,backend TEXT,payload TEXT,PRIMARY KEY(material_id,backend)); CREATE TABLE IF NOT EXISTS shared_sample_audio(id TEXT PRIMARY KEY,source_id TEXT,payload TEXT); CREATE TABLE IF NOT EXISTS sample_analysis_status(material_id TEXT,backend TEXT,status TEXT,error TEXT,PRIMARY KEY(material_id,backend));"""
    )
    if db.execute("SELECT 1 FROM sqlite_master WHERE name='sample_edges'").fetchone():
        migrate_nature(db)
        migrate_history(db)
        migrate_parent_maps(db)
        migrate_alignment_choices(db)
        return
    db.commit()
    filename = db.execute("PRAGMA database_list").fetchone()[2]
    if filename:
        target = Path(filename).parent / "backups" / f"pre-derivations-{time.time_ns()}.sqlite3"
        target.parent.mkdir(parents=True, exist_ok=True)
        with sqlite3.connect(target) as backup:
            db.backup(backup)
    db.executescript("""BEGIN IMMEDIATE;
      ALTER TABLE materials ADD COLUMN folder_id TEXT NOT NULL DEFAULT 'inbox';
      ALTER TABLE materials ADD COLUMN status TEXT NOT NULL DEFAULT 'confirmed';
      ALTER TABLE materials ADD COLUMN starred INTEGER NOT NULL DEFAULT 0;
      ALTER TABLE materials ADD COLUMN pool TEXT NOT NULL DEFAULT 'library';
      ALTER TABLE materials ADD COLUMN active_phone_backend TEXT NOT NULL DEFAULT 'narabas';
      ALTER TABLE materials ADD COLUMN active_quantization_strategy TEXT NOT NULL DEFAULT 'acoustic';
      ALTER TABLE materials ADD COLUMN analysis_settings TEXT NOT NULL DEFAULT '{}';
      CREATE TABLE sample_folders(id TEXT PRIMARY KEY,name TEXT NOT NULL,batch_id TEXT);
      CREATE TABLE sample_batches(id TEXT PRIMARY KEY,folder_id TEXT,target_folder TEXT,query TEXT,created REAL);
      CREATE TABLE sample_edges(child_id TEXT PRIMARY KEY REFERENCES materials(id),parent_id TEXT REFERENCES materials(id),operation TEXT NOT NULL,payload TEXT NOT NULL);
      CREATE TABLE sample_assets(material_id TEXT PRIMARY KEY REFERENCES materials(id),payload TEXT NOT NULL);
      CREATE TABLE sample_records(material_id TEXT,backend TEXT,signature TEXT,payload TEXT,PRIMARY KEY(material_id,backend));
      CREATE TABLE sample_batch_items(batch_id TEXT,candidate_id TEXT,accepted_id TEXT,state TEXT,PRIMARY KEY(batch_id,candidate_id));
      UPDATE materials SET pool='corpus',folder_id='speech' WHERE id=cue_id;
      UPDATE materials SET active_phone_backend=analysis_kind WHERE analysis_kind IN ('narabas','phonetic','pydomino');
      UPDATE materials SET starred=1,pool='library' WHERE id IN(SELECT material_id FROM collection_members WHERE collection_id='favorites');
      UPDATE materials SET pool='library' WHERE notes<>'' OR rating>0 OR id IN(SELECT material_id FROM material_tags WHERE origin='manual');
      COMMIT;""")
    for fid, name in FOLDERS.items():
        db.execute("INSERT INTO sample_folders VALUES(?,?,NULL)", (fid, name))
    for c in db.execute("SELECT * FROM collections WHERE id<>'favorites' ORDER BY id").fetchall():
        db.execute("INSERT OR IGNORE INTO sample_folders VALUES(?,?,NULL)", (c["id"], c["name"]))
    for r in db.execute(
        "SELECT material_id,collection_id FROM collection_members WHERE collection_id<>'favorites' ORDER BY collection_id"
    ).fetchall():
        old = db.execute("SELECT folder_id FROM materials WHERE id=?", (r[0],)).fetchone()[0]
        if old in ("inbox", "speech"):
            db.execute("UPDATE materials SET folder_id=?,pool='library' WHERE id=?", (r[1], r[0]))
        else:
            db.execute(
                "INSERT OR IGNORE INTO material_tags VALUES(?,?,?)", (r[0], "旧集合:" + r[1], "migration")
            )
    migrate_nature(db)
    # Keep legacy rows for old CLI manifests, expose real processed outputs as children.
    for v in db.execute("SELECT * FROM material_versions ORDER BY created").fetchall():
        manifest = json.loads(v["manifest"])
        if v["operation"] == "original_copy":
            if Path(v["path"]).is_file():
                bind_file(db, v["material_id"], v["path"], {"operation": "storage_copy"})
            continue
        if not Path(v["path"]).is_file():
            continue
        parent = dict(db.execute("SELECT * FROM materials WHERE id=?", (v["material_id"],)).fetchone())
        child = identity("legacy-derived", v["id"])
        _insert(
            db,
            child,
            parent,
            parent["start"],
            parent["end"],
            parent["title"] + " · " + v["operation"],
            parent["folder_id"],
            "confirmed",
        )
        db.execute(
            "INSERT OR IGNORE INTO sample_edges VALUES(?,?,?,?)",
            (
                child,
                parent["id"],
                v["operation"],
                json.dumps({"legacy_manifest": manifest, "legacy_version_id": v["id"]}),
            ),
        )
        bind_file(
            db,
            child,
            v["path"],
            {
                "operation": v["operation"],
                "legacy_manifest": manifest,
                "root_knots": [
                    [t - manifest.get("timeline_start_seconds", 0), s]
                    for s, t in manifest.get("time_map", {}).get("knots", [])
                ]
                or None,
                "role": "warped" if manifest.get("local_warp") else manifest.get("variant", "processed"),
            },
        )
    db.commit()
    migrate_nature(db)
    migrate_history(db)
    migrate_parent_maps(db)
    migrate_alignment_choices(db)


def migrate_nature(db):
    if "nature" not in {r[1] for r in db.execute("PRAGMA table_info(materials)")}:
        db.execute("ALTER TABLE materials ADD COLUMN nature TEXT NOT NULL DEFAULT 'unclassified'")
        db.execute(
            "UPDATE materials SET nature=CASE WHEN folder_id IN ('speech','pitched','unpitched') THEN folder_id WHEN cue_id IS NOT NULL THEN 'speech' ELSE 'unclassified' END"
        )
        db.execute(
            "UPDATE materials SET folder_id='' WHERE folder_id IN ('speech','pitched','unpitched','inbox')"
        )
        db.execute("DELETE FROM sample_folders WHERE id IN ('speech','pitched','unpitched','inbox')")
        db.commit()


def _insert(db, mid, parent, start, end, title, folder, status, nature=None):
    nature = nature or parent.get("nature", "unclassified")
    folder = "" if folder in FOLDERS else folder
    inserted = db.execute(
        """INSERT OR IGNORE INTO materials(id,source_id,start,end,audio_stream,cue_id,title,created,folder_id,status,pool,active_phone_backend,active_quantization_strategy)
        VALUES(?,?,?,?,?,?,?,?,?,?,'library',?,?)""",
        (
            mid,
            parent["source_id"],
            start,
            end,
            parent["audio_stream"],
            parent.get("cue_id"),
            title,
            time.time(),
            folder,
            status,
            parent.get("active_phone_backend", "narabas"),
            parent.get("active_quantization_strategy", "acoustic"),
        ),
    )

    if inserted.rowcount:
        db.execute("UPDATE materials SET nature=? WHERE id=?", (nature, mid))


def bind_file(db, mid, path, provenance):
    import soundfile as sf

    from .materials import sha256

    info = sf.info(path)
    asset = {
        "path": str(Path(path).resolve()),
        "sha256": sha256(path),
        "start": 0,
        "end": info.duration,
        "sample_rate": info.samplerate,
        "channels": info.channels,
        "root_knots": provenance.get("root_knots"),
        "provenance": provenance,
        "role": provenance.get("role", "processed"),
    }
    db.execute("INSERT OR REPLACE INTO sample_assets VALUES(?,?)", (mid, json.dumps(asset)))
    return asset


def preferences(db, mid, **values):
    if values.get("active_phone_backend") not in (*BACKENDS, None):
        raise ValueError("请选择 narabas、HubertFA 或 pydomino")
    if values.get("active_quantization_strategy") not in ("mora", "mora_guided", "acoustic", None):
        raise ValueError("未知量化方法")
    allowed = {
        "active_phone_backend",
        "active_quantization_strategy",
        "folder_id",
        "nature",
        "starred",
        "analysis_settings",
    }
    for key, value in values.items():
        if key not in allowed:
            raise ValueError("未知采样属性")
        if key == "nature" and value not in ("speech", "pitched", "unpitched", "unclassified"):
            raise ValueError("未知采样性质")
        if key == "folder_id" and value in FOLDERS:
            value = ""
        if (
            key == "folder_id"
            and value
            and not db.execute("SELECT 1 FROM sample_folders WHERE id=?", (value,)).fetchone()
        ):
            raise ValueError("文件夹不存在")
        if key == "analysis_settings":
            value = json.dumps(value)
        db.execute(f"UPDATE materials SET {key}=? WHERE id=?", (value, mid))
    db.commit()


def folder(db, name, fid=None):
    name = name.strip()
    if not name:
        raise ValueError("文件夹名不能为空")
    fid = fid or identity("folder", name, time.time_ns())
    db.execute(
        "INSERT INTO sample_folders VALUES(?,?,NULL) ON CONFLICT(id) DO UPDATE SET name=excluded.name",
        (fid, name),
    )
    db.commit()
    return {"id": fid, "name": name}


def batch(db, query, target="inbox"):
    if (
        target
        and target not in FOLDERS
        and not db.execute(
            "SELECT 1 FROM sample_folders WHERE id=? AND batch_id IS NULL", (target,)
        ).fetchone()
    ):
        raise ValueError("接收目标必须是普通文件夹")
    bid = identity("batch", query, time.time_ns())
    fid = "batch-" + bid
    db.execute("INSERT INTO sample_folders VALUES(?,?,?)", (fid, time.strftime("检索 %m-%d %H:%M:%S"), bid))
    db.execute(
        "INSERT INTO sample_batches VALUES(?,?,?,?,?)", (bid, fid, target, json.dumps(query), time.time())
    )
    db.commit()
    return {"id": bid, "folder_id": fid, "target_folder": target}


def derive(
    db,
    parent_id,
    *,
    start=0,
    end=None,
    operation="cut",
    asset=None,
    title=None,
    locator=None,
    folder_id="",
    nature=None,
    batch_id=None,
    parameters=None,
    input_asset=None,
):
    import numpy as np

    from .materials import get
    from .sample_audio import resolve

    p = get(db, parent_id)
    if nature not in (None, "speech", "pitched", "unpitched", "unclassified"):
        raise ValueError("未知采样性质")
    if operation == "flatten" and nature not in (None, "pitched"):
        raise ValueError("拉平结果的性质必须是调谐单音")
    resolved_nature = "pitched" if operation == "flatten" else nature or p.get("nature", "unclassified")
    source = input_asset or resolve(db, parent_id)
    duration = source["end"] - source["start"]
    end = duration if end is None else end
    # Aligned crops and materialized PCM can differ by half a source frame.
    if end > duration and end - duration <= 1 / 8000:
        end = duration
    if -1 / 8000 <= start < 0:
        start = 0
    if not 0 <= start < end <= duration + 1e-9:
        raise ValueError("选区超出父采样")
    knots = source.get("root_knots") or [[0, p["start"]], [duration, p["end"]]]
    root_start = float(np.interp(start, *np.asarray(knots).T))
    root_end = float(np.interp(end, *np.asarray(knots).T))
    cropped = [
        [0, root_start],
        *[[x - start, y] for x, y in knots if start < x < end],
        [end - start, root_end],
    ]
    payload = {
        "nature_at_creation": {
            "value": resolved_nature,
            "rule": "flatten" if operation == "flatten" else "explicit" if nature else "parent_snapshot",
        },
        "parent_audio": source,
        "parent_range": [start, end],
        "root_knots": (asset or {}).get("root_knots") or cropped,
        "parent_time_map": [
            [t, float(np.interp(root, *np.asarray(knots).T[::-1]))]
            for t, root in ((asset or {}).get("root_knots") or cropped)
        ],
        "locator": locator or source.get("provenance", {}).get("locator"),
        "parameters": parameters or {},
    }
    content = identity(
        "sample-content-v2",
        parent_id,
        source,
        start,
        end,
        operation,
        {} if operation == "candidate" else (parameters or {}),
        asset.get("sha256") if asset else None,
    )
    payload["content_id"] = content
    mid = identity(content, batch_id) if batch_id else content
    if batch_id:
        b = db.execute("SELECT * FROM sample_batches WHERE id=?", (batch_id,)).fetchone()
        if not b:
            raise ValueError("批次不存在")
        folder_id = b["folder_id"]
    if (
        folder_id
        and folder_id not in FOLDERS
        and not db.execute("SELECT 1 FROM sample_folders WHERE id=?", (folder_id,)).fetchone()
    ):
        raise ValueError("文件夹不存在")
    _insert(
        db,
        mid,
        p,
        root_start,
        root_end,
        title
        or (
            p["title"]
            if operation == "candidate"
            else p["title"]
            + " · "
            + {
                "cut": "裁切",
                "quantized": "卡拍",
                "flatten": "拉平",
                "separation": "分离",
                "audio_source": "音源派生",
            }.get(operation, operation)
        ),
        folder_id,
        "pending" if batch_id else "confirmed",
        nature=resolved_nature,
    )
    db.execute(
        "UPDATE materials SET analysis_settings=? WHERE id=? AND NOT EXISTS(SELECT 1 FROM sample_edges WHERE child_id=?)",
        (
            json.dumps(
                {
                    k: v
                    for k, v in p["analysis_settings"].items()
                    if k not in ("slots", "split_before", "segments", "backend_settings")
                }
            ),
            mid,
            mid,
        ),
    )
    db.execute(
        "INSERT OR IGNORE INTO sample_edges VALUES(?,?,?,?)",
        (mid, parent_id, operation, json.dumps(payload, ensure_ascii=False)),
    )
    if asset:
        asset = {
            **asset,
            "provenance": {**asset.get("provenance", {}), **payload},
            "root_knots": asset.get("root_knots") or cropped,
        }
    else:
        asset = {
            **source,
            "start": source["start"] + start,
            "end": source["start"] + end,
            "root_knots": cropped,
            "provenance": payload,
        }
    db.execute(
        "INSERT OR IGNORE INTO sample_assets VALUES(?,?)", (mid, json.dumps(asset, ensure_ascii=False))
    )
    if p.get("cue_id"):
        from .sample_analysis import measurement

        for kind in BACKENDS:
            measured = measurement(db, p, kind)
            if measured:
                db.execute(
                    "INSERT OR IGNORE INTO sample_measurements VALUES(?,?,?)",
                    (mid, kind, json.dumps(measured)),
                )
    # Inheritable labels are resolved through ancestry, never frozen onto the child.
    if batch_id:
        db.execute("INSERT OR IGNORE INTO sample_batch_items VALUES(?,?,NULL,?)", (batch_id, mid, "pending"))
        db.execute("INSERT OR IGNORE INTO material_tags VALUES(?,?,?)", (mid, "批次:" + batch_id, "batch"))
    db.commit()
    return get(db, mid)


def review(db, ids, accept=True):
    result = []
    for mid in ids:
        b = db.execute(
            "SELECT b.* FROM sample_batches b JOIN sample_batch_items i ON i.batch_id=b.id WHERE i.candidate_id=? AND i.state='pending'",
            (mid,),
        ).fetchone()
        if not b:
            continue
        accepted = mid
        if accept:
            edge = db.execute("SELECT * FROM sample_edges WHERE child_id=?", (mid,)).fetchone()
            p = json.loads(edge["payload"])
            if edge["operation"] == "candidate" and p["parent_range"] == [
                0,
                p["parent_audio"]["end"] - p["parent_audio"]["start"],
            ]:
                old = db.execute(
                    "SELECT id FROM materials WHERE id=? AND pool='library' AND status='confirmed'",
                    (edge["parent_id"],),
                ).fetchone()
                if old:
                    accepted = old["id"]
            if accepted == mid and p.get("content_id"):
                duplicate = db.execute(
                    "SELECT m.id FROM sample_edges e JOIN materials m ON m.id=e.child_id WHERE json_extract(e.payload,'$.content_id')=? AND m.status='confirmed' AND m.id<>? LIMIT 1",
                    (p["content_id"], mid),
                ).fetchone()
                if duplicate:
                    accepted = duplicate["id"]
            if accepted == mid:
                db.execute(
                    "UPDATE materials SET status='confirmed',folder_id=? WHERE id=?",
                    ("" if b["target_folder"] in FOLDERS else b["target_folder"], mid),
                )
            else:
                db.execute("UPDATE materials SET status='discarded' WHERE id=?", (mid,))
            db.execute(
                "INSERT OR IGNORE INTO material_tags VALUES(?,?,?)", (accepted, "批次:" + b["id"], "batch")
            )
        else:
            db.execute("UPDATE materials SET status='discarded' WHERE id=?", (mid,))
        db.execute(
            "UPDATE sample_batch_items SET state=?,accepted_id=? WHERE candidate_id=?",
            ("accepted" if accept else "discarded", accepted if accept else None, mid),
        )
        result.append(accepted)
    db.commit()
    return result


def migrate_history(db):
    db.execute("CREATE TABLE IF NOT EXISTS sample_history_migrated(version INTEGER)")
    if db.execute("SELECT 1 FROM sample_history_migrated").fetchone():
        return
    for row in db.execute("SELECT * FROM sample_edges WHERE operation='strict_quantization'").fetchall():
        payload = json.loads(row["payload"])
        manifest = payload.get("legacy_manifest", {})
        if manifest.get("time_map", {}).get("knots"):
            bind_file(
                db,
                row["child_id"],
                json.loads(
                    db.execute(
                        "SELECT payload FROM sample_assets WHERE material_id=?", (row["child_id"],)
                    ).fetchone()[0]
                )["path"],
                {
                    "operation": row["operation"],
                    "legacy_manifest": manifest,
                    "role": "warped",
                    "root_knots": [
                        [t - manifest.get("timeline_start_seconds", 0), s]
                        for s, t in manifest["time_map"]["knots"]
                    ],
                },
            )
    for r in db.execute("SELECT id,active_phone_backend FROM materials WHERE id=cue_id").fetchall():
        settings = {}
        for kind in BACKENDS:
            raw = db.execute(
                "SELECT payload FROM cue_settings WHERE cue_id=? AND kind=? ORDER BY rowid DESC LIMIT 1",
                (r["id"], kind),
            ).fetchone()
            value = json.loads(raw[0]) if raw else {}
            split = db.execute(
                "SELECT split_before FROM rhythm_edits WHERE cue_id=? AND kind=? ORDER BY updated DESC LIMIT 1",
                (r["id"], kind),
            ).fetchone()
            if split:
                value["split_before"] = json.loads(split[0])
            seg = db.execute(
                "SELECT payload FROM segment_settings WHERE cue_id=? AND kind=? ORDER BY rowid DESC LIMIT 1",
                (r["id"], kind),
            ).fetchone()
            if seg:
                value["segments"] = json.loads(seg[0])
            if value:
                settings[kind] = value
        if settings:
            db.execute(
                "UPDATE materials SET analysis_settings=? WHERE id=? AND analysis_settings='{}'",
                (json.dumps({"backend_settings": settings}), r["id"]),
            )
    db.execute("INSERT INTO sample_history_migrated VALUES(1)")
    db.commit()


def migrate_parent_maps(db):
    import numpy as np

    if db.execute("SELECT 1 FROM sample_history_migrated WHERE version=2").fetchone():
        return
    for row in db.execute("SELECT * FROM sample_edges").fetchall():
        p = json.loads(row["payload"])
        if p.get("parent_time_map"):
            continue
        parent = p.get("parent_audio")
        if not parent:
            asset = db.execute(
                "SELECT payload FROM sample_assets WHERE material_id=?", (row["parent_id"],)
            ).fetchone()
            parent = json.loads(asset[0]) if asset else {}
        asset = db.execute(
            "SELECT payload FROM sample_assets WHERE material_id=?", (row["child_id"],)
        ).fetchone()
        child = json.loads(asset[0]) if asset else {}
        parent_knots = parent.get("root_knots")
        child_knots = child.get("root_knots")
        if parent_knots and child_knots:
            xx, yy = np.asarray(parent_knots).T
            if (
                min(y for _, y in child_knots) >= min(yy) - 1 / 8000
                and max(y for _, y in child_knots) <= max(yy) + 1 / 8000
            ):
                p["parent_time_map"] = [[t, float(np.interp(root, yy, xx))] for t, root in child_knots]
                p["root_knots"] = child_knots
            else:
                p["parent_mapping_status"] = "legacy_range_exceeds_current_parent; original map retained"
        else:
            p["parent_mapping_status"] = "legacy_reference_missing; original manifest retained"
        db.execute("UPDATE sample_edges SET payload=? WHERE child_id=?", (json.dumps(p), row["child_id"]))
    db.execute("INSERT INTO sample_history_migrated VALUES(2)")
    db.commit()


def migrate_alignment_choices(db):
    """One-way retirement; measured media and manual tags are never deleted."""
    from .retirement import retire_alignment_records, retire_tool_records
    retire_alignment_records(db)
    retire_tool_records(db)
