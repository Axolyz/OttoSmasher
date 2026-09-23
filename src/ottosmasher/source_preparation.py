"""Source-first ingestion and immutable subtitle revisions, shared by GUI and CLI."""

import json
import shutil
import time
from pathlib import Path

import pysubs2

from . import catalog, materials, source_regions
from .workspace import identity


def ensure(db):
    source_regions.ensure(db)
    db.execute(
        "CREATE TABLE IF NOT EXISTS source_preparation(source_id TEXT PRIMARY KEY, payload TEXT NOT NULL)"
    )


def listing(db):
    ensure(db)
    from .ui_catalog import ensure as ensure_labels

    ensure_labels(db)
    rows = []
    for s in db.execute(
        "SELECT s.*,l.work,l.episode,l.media_type,l.imported FROM sources s LEFT JOIN source_labels l ON l.source_id=s.id ORDER BY l.imported DESC,s.rowid DESC"
    ).fetchall():
        s = dict(s)
        setting = db.execute(
            "SELECT payload FROM source_preparation WHERE source_id=?", (s["id"],)
        ).fetchone()
        s["preparation"] = json.loads(setting[0]) if setting else {}
        s["tracks"] = [t for t in json.loads(s.pop("metadata"))["streams"] if t["codec_type"] == "audio"]
        s["regions"] = source_regions.listing(db, s["id"])
        s["versions"] = [
            dict(r)
            for r in db.execute(
                "SELECT * FROM subtitle_versions WHERE source_id=? ORDER BY created DESC", (s["id"],)
            )
        ]
        s["cues"] = db.execute(
            "SELECT count(*) FROM cues c WHERE source_id=? AND " + source_regions.sql_allowed("c"), (s["id"],)
        ).fetchone()[0]
        s["analyzed"] = db.execute(
            "SELECT count(DISTINCT c.id) FROM cues c JOIN analyses a ON a.cue_id=c.id WHERE c.source_id=? AND json_array_length(a.payload,'$.phones')>0 AND "
            + source_regions.sql_allowed("c"),
            (s["id"],),
        ).fetchone()[0]
        rows.append(s)
    return rows


def register(db, paths):
    from .sound_assets import source

    ensure(db)
    rows = []
    for value in paths:
        path = Path(value).expanduser().resolve(strict=True)
        meta = catalog.probe(path)
        tracks = [x for x in meta["streams"] if x["codec_type"] == "audio"]
        if not tracks:
            raise ValueError("原片没有音轨")
        preferred = [x for x in tracks if x.get("tags", {}).get("language") in ("jpn", "ja")]
        chosen = (preferred or tracks)[0]["index"]
        old = db.execute("SELECT id FROM sources WHERE path=?", (str(path),)).fetchone()
        sid = old[0] if old else source(db, {"path": str(path), "audio_stream": chosen})["source_id"]
        matches = [str(p) for suffix in (".srt", ".ass") if (p := path.with_suffix(suffix)).exists()]
        settings = {"subtitle_path": matches[0] if matches else "", "op_review": "pending"}
        db.execute("INSERT OR IGNORE INTO source_preparation VALUES(?,?)", (sid, json.dumps(settings)))
        rows.append(sid)
    db.commit()
    return {"source_ids": rows}


def configure(db, source_id, subtitle_path=None, audio_stream=None, op_review=None, import_speakers=None):
    ensure(db)
    s = db.execute("SELECT * FROM sources WHERE id=?", (source_id,)).fetchone()
    if not s:
        raise ValueError("原片不存在")
    if audio_stream is not None and audio_stream != s["audio_stream"]:
        if db.execute("SELECT 1 FROM cues WHERE source_id=? LIMIT 1", (source_id,)).fetchone():
            raise ValueError("已有字幕分析绑定此音轨；请在原片浏览选择参考轨，不覆盖历史分析音轨")
        tracks = [t["index"] for t in json.loads(s["metadata"])["streams"] if t["codec_type"] == "audio"]
        if audio_stream not in tracks:
            raise ValueError("音轨不存在")
        db.execute("UPDATE sources SET audio_stream=? WHERE id=?", (audio_stream, source_id))
    row = db.execute("SELECT payload FROM source_preparation WHERE source_id=?", (source_id,)).fetchone()
    settings = json.loads(row[0]) if row else {}
    if subtitle_path is not None:
        p = Path(subtitle_path).expanduser().resolve(strict=True)
        if p.suffix.lower() not in (".srt", ".ass"):
            raise ValueError("请选择已预处理的 SRT/ASS")
        settings["subtitle_path"] = str(p)
    if import_speakers is not None:
        settings["import_speakers"] = bool(import_speakers)
    if op_review is not None:
        if op_review not in ("pending", "reviewed", "skipped"):
            raise ValueError("未知检查状态")
        settings["op_review"] = op_review
    db.execute("INSERT OR REPLACE INTO source_preparation VALUES(?,?)", (source_id, json.dumps(settings)))
    db.commit()
    return settings


def preview(db, source_id):
    ensure(db)
    s = db.execute("SELECT * FROM sources WHERE id=?", (source_id,)).fetchone()
    if not s:
        raise ValueError("原片不存在")
    conf = db.execute("SELECT payload FROM source_preparation WHERE source_id=?", (source_id,)).fetchone()
    settings = json.loads(conf[0]) if conf else {}
    path = Path(settings.get("subtitle_path") or s["subtitle_path"] or "")
    if not path.is_file():
        raise ValueError("请先关联已预处理字幕")
    regions = source_regions.listing(db, source_id)
    rows = []
    for i, event in enumerate(pysubs2.load(str(path), encoding="utf-8-sig")):
        a, b = event.start / 1000, min(event.end / 1000, s["duration"])
        overlap = [r for r in regions if r["start"] < b and r["end"] > a]
        status = "invalid" if not 0 <= a < b <= s["duration"] else "excluded" if overlap else "ready"
        boundary = bool(overlap) and not any(r["start"] <= a and b <= r["end"] for r in overlap)
        rows.append(
            {"ordinal": i, "start": a, "end": b, "text": event.text, "status": status, "boundary": boundary}
        )
    digest = materials.sha256(path)
    token = identity(
        source_regions.media_fingerprint(db, source_id),
        digest,
        s["audio_stream"],
        [(r["id"], r["start"], r["end"]) for r in regions],
    )
    return {
        "source_id": source_id,
        "path": str(path),
        "fingerprint": digest,
        "token": token,
        "op_review": settings.get("op_review", "pending"),
        "import_speakers": settings.get("import_speakers", False),
        "rows": rows,
        "counts": {k: sum(r["status"] == k for r in rows) for k in ("ready", "excluded", "invalid")},
        "boundary_count": sum(r["boundary"] for r in rows),
    }


def ingest(db, source_id, token):
    from . import workspace

    p = preview(db, source_id)
    if p["token"] != token:
        raise ValueError("字幕、音轨或 OP/ED 已改变，请重新预览")
    if p["op_review"] == "pending":
        raise ValueError("请先确认 OP/ED 检查完成，或明确选择暂时跳过")
    if p["counts"]["invalid"]:
        raise ValueError("字幕包含无效范围，请先修正")
    vid = identity("subtitle-version", source_id, p["fingerprint"])
    # Pin all legacy cues to the previous immutable subtitle revision before adding another.
    for old in db.execute(
        "SELECT id FROM subtitle_versions WHERE source_id=? AND selected=1", (source_id,)
    ).fetchall():
        db.execute(
            "INSERT OR IGNORE INTO cue_subtitle_versions SELECT id,?,ordinal FROM cues WHERE source_id=?",
            (old[0], source_id),
        )
    target = workspace.DATA / "media/subtitles" / (vid + Path(p["path"]).suffix)
    target.parent.mkdir(parents=True, exist_ok=True)
    if not target.exists():
        shutil.copy2(p["path"], target)
    with db:
        db.execute("UPDATE subtitle_versions SET selected=0 WHERE source_id=?", (source_id,))
        db.execute(
            "INSERT INTO subtitle_versions VALUES(?,?,?,?,1,?) ON CONFLICT(id) DO UPDATE SET selected=1",
            (vid, source_id, str(target), p["fingerprint"], time.time()),
        )
        ordinal = db.execute(
            "SELECT coalesce(max(ordinal),-1)+1 FROM cues WHERE source_id=?", (source_id,)
        ).fetchone()[0]
        for row in p["rows"]:
            cid = identity("subtitle-cue-v2", vid, row["ordinal"])
            fields = catalog.parse_text(row["text"])
            db.execute(
                "INSERT OR IGNORE INTO cues VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
                (
                    cid,
                    source_id,
                    ordinal + row["ordinal"],
                    row["start"],
                    row["end"],
                    *fields[:-1],
                    json.dumps(fields[-1]),
                ),
            )
            if p["import_speakers"]:
                from .subtitle_speakers import record

                record(db, cid, row["text"])
            db.execute(
                "INSERT OR IGNORE INTO cue_subtitle_versions VALUES(?,?,?)", (cid, vid, row["ordinal"])
            )
        db.execute("UPDATE sources SET subtitle_path=? WHERE id=?", (str(target), source_id))
    db.execute("CREATE TABLE IF NOT EXISTS deleted_sample_cues(cue_id TEXT PRIMARY KEY)")
    db.execute(
        "DELETE FROM deleted_sample_cues WHERE cue_id IN (SELECT cue_id FROM cue_subtitle_versions WHERE version_id=?)",
        (vid,),
    )
    materials.sync_cues(db)
    db.execute(
        "UPDATE materials SET nature='speech',folder_id='' WHERE id IN (SELECT cue_id FROM cue_subtitle_versions WHERE version_id=?) AND folder_id='inbox'",
        (vid,),
    )
    db.commit()
    return {"version_id": vid, **p["counts"]}


def selected_materials(db, source_ids=None, material_ids=None):
    ensure(db)
    if material_ids:
        placeholders = ",".join("?" for _ in material_ids)
        return [
            r[0]
            for r in db.execute(
                f"SELECT m.id FROM materials m WHERE m.id IN ({placeholders}) AND m.cue_id IS NOT NULL AND "
                + source_regions.sql_allowed("m"),
                material_ids,
            )
        ]
    if not source_ids:
        raise ValueError("请明确选择原片或采样范围")
    placeholders = ",".join("?" for _ in source_ids)
    return [
        r[0]
        for r in db.execute(
            f"SELECT m.id FROM materials m JOIN cues c ON m.cue_id=c.id WHERE m.id=c.id AND m.source_id IN ({placeholders}) AND "
            + source_regions.sql_allowed("c"),
            source_ids,
        )
    ]
