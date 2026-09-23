"""Unified material directory. Membership never determines physical storage.

The cue-backed adapter retains existing measured analysis identities. A file or
selection with no compatible analysis is a valid material, never a fake cue.
"""

from __future__ import annotations

import hashlib
import json
import math
import shutil
import sqlite3
import time
from pathlib import Path

from .workspace import identity

SCHEMA = 1


def migrate(db):
    if db.execute("SELECT 1 FROM sqlite_master WHERE name='material_schema'").fetchone():
        return
    db.commit()
    filename = db.execute("PRAGMA database_list").fetchone()[2]
    if filename:
        target = Path(filename).parent / "backups" / f"pre-materials-{time.time_ns()}.sqlite3"
        target.parent.mkdir(parents=True, exist_ok=True)
        with sqlite3.connect(target) as backup:
            db.backup(backup)
    # Do not rename the old table: SQLite would rewrite existing FK references.
    db.execute("PRAGMA foreign_keys=OFF")
    try:
        db.executescript("""
        BEGIN IMMEDIATE;
        CREATE TABLE sources_nullable (
          id TEXT PRIMARY KEY,path TEXT UNIQUE NOT NULL,subtitle_path TEXT,
          fingerprint TEXT NOT NULL,title TEXT NOT NULL,duration REAL NOT NULL,
          audio_stream INTEGER NOT NULL,metadata TEXT NOT NULL);
        INSERT INTO sources_nullable SELECT * FROM sources;
        DROP TABLE sources;
        ALTER TABLE sources_nullable RENAME TO sources;
        CREATE TABLE material_schema(version INTEGER NOT NULL);
        INSERT INTO material_schema VALUES(1);
        CREATE TABLE materials(
          id TEXT PRIMARY KEY,source_id TEXT NOT NULL REFERENCES sources(id),
          start REAL NOT NULL,end REAL NOT NULL,audio_stream INTEGER NOT NULL,
          cue_id TEXT REFERENCES cues(id),scope_id TEXT,analysis_kind TEXT,
          title TEXT NOT NULL,notes TEXT NOT NULL DEFAULT '',rating INTEGER NOT NULL DEFAULT 0,
          preferred_version TEXT,created REAL NOT NULL, CHECK(start>=0 AND end>start));
        CREATE INDEX material_cue ON materials(cue_id);
        CREATE INDEX material_source ON materials(source_id,start,end);
        CREATE TABLE material_versions(
          id TEXT PRIMARY KEY,material_id TEXT NOT NULL REFERENCES materials(id),
          parent_id TEXT REFERENCES material_versions(id),path TEXT NOT NULL,
          fingerprint TEXT NOT NULL,operation TEXT NOT NULL,manifest TEXT NOT NULL,created REAL NOT NULL);
        CREATE TABLE collections(id TEXT PRIMARY KEY,name TEXT UNIQUE NOT NULL);
        INSERT INTO collections VALUES('favorites','精选');
        CREATE TABLE collection_members(collection_id TEXT NOT NULL REFERENCES collections(id),
          material_id TEXT NOT NULL REFERENCES materials(id),PRIMARY KEY(collection_id,material_id));
        CREATE TABLE material_tags(material_id TEXT NOT NULL REFERENCES materials(id),
          tag TEXT NOT NULL,origin TEXT NOT NULL DEFAULT 'manual',
          PRIMARY KEY(material_id,tag,origin));
        CREATE TABLE subtitle_versions(id TEXT PRIMARY KEY,source_id TEXT NOT NULL REFERENCES sources(id),
          path TEXT NOT NULL,fingerprint TEXT NOT NULL,selected INTEGER NOT NULL DEFAULT 0,created REAL NOT NULL);
        CREATE TABLE operation_jobs(id TEXT PRIMARY KEY,operation TEXT NOT NULL,payload TEXT NOT NULL,
          status TEXT NOT NULL,pid INTEGER,error TEXT,result TEXT,created REAL NOT NULL,updated REAL NOT NULL);
        COMMIT;
        """)
    except Exception:
        db.rollback()
        raise
    finally:
        db.execute("PRAGMA foreign_keys=ON")
    sync_cues(db)
    db.execute(
        "INSERT OR IGNORE INTO collection_members SELECT 'favorites',m.id FROM materials m JOIN feedback f ON f.cue_id=m.cue_id WHERE f.value='keep'"
    )
    db.commit()


def sync_cues(db):
    from .source_regions import ensure, sql_allowed

    ensure(db)
    db.execute("CREATE TABLE IF NOT EXISTS deleted_sample_cues(cue_id TEXT PRIMARY KEY)")
    # Record the exact subtitle bytes independently of later preprocessing files.
    from .workspace import DATA

    for source in db.execute(
        "SELECT id,subtitle_path FROM sources WHERE subtitle_path IS NOT NULL"
    ).fetchall():
        path = Path(source["subtitle_path"])
        if not path.is_file():
            continue
        digest = sha256(path)
        vid = identity("subtitle-version", source["id"], digest)
        snapshot = DATA / "media" / "subtitles" / (vid + path.suffix)
        snapshot.parent.mkdir(parents=True, exist_ok=True)
        if not snapshot.exists():
            shutil.copy2(path, snapshot)
        db.execute(
            "INSERT OR IGNORE INTO subtitle_versions VALUES(?,?,?,?,?,?)",
            (vid, source["id"], str(snapshot), digest, 1, time.time()),
        )
    fresh = [r[0] for r in db.execute("SELECT id FROM cues WHERE id NOT IN (SELECT id FROM materials)")]
    db.execute(
        f"""INSERT OR IGNORE INTO materials(id,source_id,start,end,audio_stream,cue_id,title,created)
      SELECT c.id,c.source_id,c.start,c.end,s.audio_stream,c.id,
      CASE WHEN c.spoken<>'' THEN c.spoken ELSE c.original END,?
      FROM cues c JOIN sources s ON s.id=c.source_id WHERE c.id NOT IN (SELECT cue_id FROM deleted_sample_cues) AND c.end>c.start AND c.start>=0 AND {sql_allowed("c")}""",
        (time.time(),),
    )
    if fresh and "active_phone_backend" in {r[1] for r in db.execute("PRAGMA table_info(materials)")}:
        from .ui_catalog import settings

        if "nature" in {r[1] for r in db.execute("PRAGMA table_info(materials)")}:
            db.executemany(
                "UPDATE materials SET nature='speech',folder_id='' WHERE id=?", [(mid,) for mid in fresh]
            )
        defaults = settings(db)
        db.executemany(
            "UPDATE materials SET active_phone_backend=?,active_quantization_strategy=? WHERE id=?",
            [(defaults["phone_backend"], defaults["quantization"], mid) for mid in fresh],
        )
    db.commit()


def sha256(path):
    h = hashlib.sha256()
    with Path(path).open("rb") as f:
        for block in iter(lambda: f.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def register_file(db, path, *, copy=False, audio_stream=None, selected_range=None):
    from .catalog import probe
    from .workspace import DATA

    path = Path(path).expanduser().resolve(strict=True)
    if not path.is_file():
        raise ValueError("请选择实际媒体文件")
    old = db.execute("SELECT * FROM sources WHERE path=?", (str(path),)).fetchone()
    if old:
        sid, info = old["id"], json.loads(old["metadata"])
        stream = old["audio_stream"] if audio_stream is None else audio_stream
    else:
        info = probe(path)
        tracks = [s["index"] for s in info["streams"] if s["codec_type"] == "audio"]
        stream = audio_stream
        if stream is None:
            if len(tracks) != 1:
                raise ValueError(f"请选择音轨：{tracks}")
            stream = tracks[0]
        fingerprint = sha256(path)
        sid = identity(str(path))
        db.execute(
            "INSERT OR IGNORE INTO sources VALUES(?,?,?,?,?,?,?,?)",
            (
                sid,
                str(path),
                None,
                fingerprint,
                path.stem,
                float(info["format"]["duration"]),
                stream,
                json.dumps(info),
            ),
        )
    if stream not in [s["index"] for s in info["streams"] if s["codec_type"] == "audio"]:
        raise ValueError("音轨不存在")
    r = save_range(
        db,
        sid,
        *(selected_range or (0, float(info["format"]["duration"]))),
        audio_stream=stream,
        title=path.stem,
    )
    is_new = r.get("_new_registration", False)
    if copy:
        fingerprint = sha256(path)
        target = DATA / "media" / "imports" / fingerprint[:16] / path.name
        target.parent.mkdir(parents=True, exist_ok=True)
        if not target.exists():
            shutil.copy2(path, target)
        if sha256(target) != fingerprint:
            raise ValueError("持久副本校验失败，保留原文件")
        v = add_version(
            db, r["id"], target, "original_copy", {"source_path": str(path), "source_sha256": fingerprint}
        )
        edit(db, r["id"], preferred_version=v["id"])
        r = get(db, r["id"])
    return {**r, "_new_registration": is_new}


def save_range(
    db, source_id, start, end, *, title="", audio_stream=None, cue_id=None, scope_id=None, analysis_kind=None
):
    source = db.execute("SELECT * FROM sources WHERE id=?", (source_id,)).fetchone()
    if not source:
        raise ValueError("片源不存在")
    if not all(math.isfinite(x) for x in (start, end)) or not 0 <= start < end <= source["duration"] + 0.001:
        raise ValueError("选区必须位于原片范围内")
    stream = source["audio_stream"] if audio_stream is None else audio_stream
    if stream not in [
        s["index"] for s in json.loads(source["metadata"])["streams"] if s["codec_type"] == "audio"
    ]:
        raise ValueError("所选音轨不存在")
    mid = identity("material-range-v1", source_id, stream, start, end)
    if cue_id:
        cue = db.execute("SELECT * FROM cues WHERE id=?", (cue_id,)).fetchone()
        if not cue or cue["source_id"] != source_id or stream != source["audio_stream"]:
            raise ValueError("分析与片源／音轨不一致")
        from .rhythm_index import entry_for

        _, entry = entry_for(db, cue_id, analysis_kind or "narabas", scope_id)
        scope = entry["scope"]
        if abs(scope["source_start"] - start) > 1e-6 or abs(scope["source_end"] - end) > 1e-6:
            raise ValueError("裁切改变了分析范围，请保存为待分析选区")
        scope_id = scope["scope_id"]
    inserted = db.execute(
        """INSERT OR IGNORE INTO materials(id,source_id,start,end,audio_stream,cue_id,scope_id,analysis_kind,title,created)
                  VALUES(?,?,?,?,?,?,?,?,?,?)""",
        (
            mid,
            source_id,
            start,
            end,
            stream,
            cue_id,
            scope_id,
            analysis_kind,
            title or source["title"],
            time.time(),
        ),
    )
    if inserted.rowcount and "active_phone_backend" in {
        x[1] for x in db.execute("PRAGMA table_info(materials)")
    }:
        from .ui_catalog import settings

        defaults = settings(db)
        db.execute(
            "UPDATE materials SET active_phone_backend=?,active_quantization_strategy=? WHERE id=?",
            (analysis_kind or defaults["phone_backend"], defaults["quantization"], mid),
        )
    if inserted.rowcount:
        db.execute(
            "UPDATE materials SET nature=?,folder_id='' WHERE id=?",
            ("speech" if cue_id else "unclassified", mid),
        )
    db.commit()
    return {**get(db, mid), "_new_registration": bool(inserted.rowcount)}


def get(db, mid):
    row = db.execute(
        """SELECT m.*,s.path,s.fingerprint,s.duration source_duration,s.title source_title,
      s.metadata source_metadata FROM materials m JOIN sources s ON s.id=m.source_id WHERE m.id=?""",
        (mid,),
    ).fetchone()
    if not row:
        raise ValueError("素材不存在")
    r = dict(row)
    r["tags"] = [
        dict(x)
        for x in db.execute("SELECT tag,origin FROM material_tags WHERE material_id=? ORDER BY tag", (mid,))
    ]
    from .ui_catalog import effective_all

    r["tags"] = effective_all(db, [mid]).get(mid, r["tags"])
    r["collections"] = [
        x[0] for x in db.execute("SELECT collection_id FROM collection_members WHERE material_id=?", (mid,))
    ]
    r["versions"] = [
        dict(x)
        for x in db.execute("SELECT * FROM material_versions WHERE material_id=? ORDER BY created", (mid,))
    ]
    for v in r["versions"]:
        v["manifest"] = json.loads(v["manifest"])
        v["available"] = Path(v["path"]).is_file()
    r["available"] = Path(r["path"]).is_file()
    r["analysis_status"] = {}
    r["range_origin"] = "manual_selection" if not r["cue_id"] else "subtitle_coarse"
    if r["cue_id"]:
        # Read status/range scalars in SQLite, not four large phone/energy payloads in Python.
        from .backends import BACKENDS
        for kind in BACKENDS:
            a = db.execute("SELECT CASE WHEN json_extract(payload,'$.input_variant')='vocals' THEN json_array_length(payload,'$.phones') ELSE 0 END n,json_extract(payload,'$.error') error,json_extract(payload,'$.window_start') start,json_extract(payload,'$.window_end') end FROM analyses WHERE cue_id=? AND kind=? ORDER BY created DESC LIMIT 1", (r["cue_id"], kind)).fetchone()
            available = bool(a and a["n"] and not a["error"])
            r["analysis_status"][kind] = "ready" if available else "unavailable"
            if available and r["id"] == r["cue_id"] and r["range_origin"] == "subtitle_coarse":
                r["subtitle_start"], r["subtitle_end"] = r["start"], r["end"]
                r["start"], r["end"] = a["start"], a["end"]
                r["range_origin"] = "model_crop_unverified"
    if r["scope_id"]:
        r["range_origin"] = "analysis_scope_unverified"
    r["rhythm_available"] = any(v == "ready" for v in r["analysis_status"].values())
    if not db.execute("SELECT 1 FROM sqlite_master WHERE name='sample_edges'").fetchone():
        return r
    edge = db.execute(
        "SELECT parent_id,operation,payload FROM sample_edges WHERE child_id=?", (mid,)
    ).fetchone()
    r["derivation"] = {**dict(edge), "payload": json.loads(edge["payload"])} if edge else None
    asset = db.execute("SELECT payload FROM sample_assets WHERE material_id=?", (mid,)).fetchone()
    r["audio_asset"] = json.loads(asset[0]) if asset else None
    if r["audio_asset"]:
        knots = r["audio_asset"].get("root_knots")
        if knots:
            r["start"], r["end"] = knots[0][1], knots[-1][1]
        r["available"] = (
            Path(r["audio_asset"]["path"]).is_file() if r["audio_asset"].get("path") else r["available"]
        )
    r["local_analysis_status"] = {
        x["backend"]: {"status": x["status"], "error": x["error"]}
        for x in db.execute("SELECT * FROM sample_analysis_status WHERE material_id=?", (mid,))
    }
    r["children"] = [
        dict(x)
        for x in db.execute(
            "SELECT m.id,m.title,e.operation FROM sample_edges e JOIN materials m ON m.id=e.child_id WHERE e.parent_id=? AND m.status='confirmed'",
            (mid,),
        )
    ]
    r["analysis_settings"] = json.loads(r.get("analysis_settings") or "{}")
    return r


def query_ids(db, text="", collection=None, tags=(), source_id=None, analyzed_only=False):
    from .catalog import normalize, reading_text
    from .source_regions import ensure, sql_allowed

    ensure(db)
    where, args = (
        ["m.pool<>'source-browser'", f"(m.id<>m.cue_id OR m.cue_id IS NULL OR {sql_allowed('m')})"],
        [],
    )
    if text:
        where.append("(m.title LIKE ? OR m.notes LIKE ? OR c.normalized LIKE ? OR c.reading LIKE ?)")
        args.extend([f"%{text}%", f"%{text}%", f"%{normalize(text)}%", f"%{reading_text(text)}%"])
    if collection:
        where.append(
            "EXISTS(SELECT 1 FROM collection_members x WHERE x.material_id=m.id AND x.collection_id=?)"
        )
        args.append(collection)
    if source_id:
        where.append("m.source_id=?")
        args.append(source_id)
    if analyzed_only:
        where.append(
            "EXISTS(SELECT 1 FROM analyses a WHERE a.cue_id=m.cue_id AND a.kind IN ('narabas','phonetic','pydomino'))"
        )
    sql = "SELECT m.id FROM materials m LEFT JOIN cues c ON c.id=m.cue_id"
    if where:
        sql += " WHERE " + " AND ".join(where)
    result = [r[0] for r in db.execute(sql + " ORDER BY m.created DESC,m.source_id,m.start,m.id", args)]
    if tags:
        from .ui_catalog import effective_all

        effective = effective_all(db)
        result = [mid for mid in result if set(tags) <= {t["tag"] for t in effective[mid]}]
    return result


def search(db, *, limit=50, offset=0, **filters):
    ids = query_ids(db, **filters)
    return {"total": len(ids), "results": [get(db, x) for x in ids[offset : offset + limit]]}


def edit(db, mid, *, title=None, notes=None, rating=None, tags=None, preferred_version=None):
    get(db, mid)
    for name, value in [
        ("title", title),
        ("notes", notes),
        ("rating", rating),
        ("preferred_version", preferred_version),
    ]:
        if value is not None:
            if name == "rating" and (not isinstance(value, int) or not 0 <= value <= 5):
                raise ValueError("评分范围 0–5")
            if (
                name == "preferred_version"
                and value
                and not db.execute(
                    "SELECT 1 FROM material_versions WHERE id=? AND material_id=?", (value, mid)
                ).fetchone()
            ):
                raise ValueError("版本不属于此素材")
            db.execute(f"UPDATE materials SET {name}=? WHERE id=?", (value, mid))
    if tags is not None:
        db.execute("DELETE FROM material_tags WHERE material_id=? AND origin='manual'", (mid,))
        for tag in {t.strip() for t in tags if t.strip()}:
            db.execute("INSERT OR IGNORE INTO material_tags VALUES(?,?,?)", (mid, tag, "manual"))
    db.commit()
    return get(db, mid)


def collection(db, name):
    name = name.strip()
    if not name:
        raise ValueError("集合名称不能为空")
    cid = "favorites" if name == "精选" else identity("collection", name)
    db.execute("INSERT OR IGNORE INTO collections VALUES(?,?)", (cid, name))
    db.commit()
    return {"id": cid, "name": name}


def membership(db, mid, cid, present=True):
    get(db, mid)
    if not db.execute("SELECT 1 FROM collections WHERE id=?", (cid,)).fetchone():
        raise ValueError("集合不存在")
    if present:
        db.execute("INSERT OR IGNORE INTO collection_members VALUES(?,?)", (cid, mid))
    else:
        db.execute("DELETE FROM collection_members WHERE collection_id=? AND material_id=?", (cid, mid))
    db.commit()
    return get(db, mid)


def add_version(db, mid, path, operation, manifest, parent_id=None):
    get(db, mid)
    if (
        parent_id
        and not db.execute(
            "SELECT 1 FROM material_versions WHERE id=? AND material_id=?", (parent_id, mid)
        ).fetchone()
    ):
        raise ValueError("父版本不属于此素材")
    path = Path(path).resolve(strict=True)
    fingerprint = sha256(path)
    vid = identity("material-version", mid, fingerprint, operation, manifest, parent_id)
    db.execute(
        "INSERT OR IGNORE INTO material_versions VALUES(?,?,?,?,?,?,?,?)",
        (
            vid,
            mid,
            parent_id,
            str(path),
            fingerprint,
            operation,
            json.dumps(manifest, ensure_ascii=False),
            time.time(),
        ),
    )
    db.commit()
    return {"id": vid, "path": str(path), "fingerprint": fingerprint}




def binding(db, mid, kind="narabas"):
    r = get(db, mid)
    if not r["cue_id"] or r["analysis_status"].get(kind) != "ready":
        raise ValueError("此素材没有可复用的语音分析，不支持节奏搜索或卡拍")
    if r["analysis_kind"] and r["analysis_kind"] != kind:
        raise ValueError("此选区绑定另一模型；请从该模型重新保存范围")
    if r["scope_id"]:
        from .rhythm_index import entry_for

        _, entry = entry_for(db, r["cue_id"], kind, r["scope_id"])
        if (
            abs(entry["scope"]["source_start"] - r["start"]) > 1e-6
            or abs(entry["scope"]["source_end"] - r["end"]) > 1e-6
        ):
            raise ValueError("选区分析已改变，请重新保存范围")
    return r
