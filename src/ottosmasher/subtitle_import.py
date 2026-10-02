"""Explicit subtitle sample creation, independent of annotation ingestion."""

import json
import regex
from . import asset_timeline as t
from .workspace import identity

EVENT_PATTERN = r"^\s*(?:[（(][^（）()]+[）)]\s*)+$"
BRACKET_PATTERN = r"[（(](?P<content>[^（）()]+)[）)]"


def classify(text, settings):
    for key, default in (
        ("subtitle_event_pattern", EVENT_PATTERN),
        ("subtitle_bracket_pattern", BRACKET_PATTERN),
    ):
        pattern = settings.get(key, default)
        if not isinstance(pattern, str) or len(pattern) > 4096:
            raise ValueError("字幕正则须为不超过 4096 字符的文本")
    plain = regex.sub(r"\{[^}]*\}|<[^>]*>", "", text.replace("\\N", "\n")).strip()
    try:
        bracket = regex.compile(settings.get("subtitle_bracket_pattern", BRACKET_PATTERN))
        event = regex.compile(settings.get("subtitle_event_pattern", EVENT_PATTERN))
        if "content" not in bracket.groupindex:
            raise ValueError("括号提取正则必须包含命名组 (?P<content>...)")
        marks = list(bracket.finditer(plain, timeout=0.05))
        contents = [
            m.group("content").strip() for m in marks if m.group("content") and m.group("content").strip()
        ]
        effect = bool(event.fullmatch(plain, timeout=0.05))
        title = " / ".join(contents) if effect else bracket.sub("", plain, timeout=0.05).strip()
        speakers = list(
            dict.fromkeys(n.strip() for c in contents for n in regex.split(r"[・＆&、/／]", c) if n.strip())
        )
        return {
            "kind": "event" if effect else "dialogue",
            "title": title,
            "speakers": [] if effect else speakers,
        }
    except (regex.error, TimeoutError) as exc:
        raise ValueError("字幕正则无效或执行超时：" + str(exc)) from exc


def ensure(db):
    db.execute(
        "CREATE TABLE IF NOT EXISTS subtitle_classifications(annotation_id TEXT PRIMARY KEY,payload TEXT)"
    )
    db.execute(
        "CREATE TABLE IF NOT EXISTS subtitle_sample_imports(annotation_id TEXT,kind TEXT,asset_id TEXT,sample_id TEXT,PRIMARY KEY(annotation_id,kind))"
    )


def preview(db, source_id, kind, annotation_ids=None, start=None, end=None):
    from .ui_catalog import settings
    from .source_regions import listing
    from .track_roles import default_asset

    if kind not in {"dialogue", "event"}:
        raise ValueError("未知字幕采样类型")
    ensure(db)
    conf = settings(db)
    asset = default_asset(db, source_id, kind)
    knots = json.loads(asset["mapping"]) if asset["mapping"] else None
    if not knots:
        raise ValueError("默认轨没有原片时间映射")
    excluded = listing(db, source_id)
    result = []
    for row in db.execute(
        "SELECT * FROM timeline_annotations WHERE source_id=? AND deleted=0 AND kind IN ('dialogue','event','song') ORDER BY start,id",
        (source_id,),
    ):
        if annotation_ids is not None and row["id"] not in annotation_ids:
            continue
        if start is not None and row["end"] <= start:
            continue
        if end is not None and row["start"] >= end:
            continue
        hidden = db.execute(
            "SELECT 1 FROM cue_subtitle_versions c JOIN subtitle_versions v ON v.id=c.version_id WHERE c.cue_id=? AND v.selected=0",
            (row["id"],),
        ).fetchone()
        if hidden:
            continue
        # Classification is saved with the annotation; changed settings only affect new imports.
        if row["kind"] != kind:
            continue
        saved = db.execute(
            "SELECT payload FROM subtitle_classifications WHERE annotation_id=?", (row["id"],)
        ).fetchone()
        parsed = json.loads(saved[0]) if saved else classify(row["text"], {})
        status = "ready"
        if (
            db.execute(
                "SELECT 1 FROM subtitle_sample_imports WHERE annotation_id=? AND kind=?", (row["id"], kind)
            ).fetchone()
            or db.execute("SELECT 1 FROM materials WHERE cue_id=?", (row["id"],)).fetchone()
        ):
            status = "imported"
        elif db.execute("SELECT 1 FROM deleted_sample_cues WHERE cue_id=?", (row["id"],)).fetchone():
            status = "deleted"
        elif any(r["start"] < row["end"] and r["end"] > row["start"] for r in excluded):
            status = "excluded"
        elif row["end"] <= knots[0][1] or row["start"] >= knots[-1][1]:
            status = "outside"
        if not parsed["title"]:
            status = "empty"
        lo = max(knots[0][1], row["start"] - conf["subtitle_padding_before"])
        hi = min(knots[-1][1], row["end"] + conf["subtitle_padding_after"])
        result.append(
            {
                "id": row["id"],
                "text": row["text"],
                "title": parsed["title"],
                "start": lo,
                "end": hi,
                "status": status,
                "selection": t.AssetSelection(
                    asset["id"], t.map_time(knots, lo, inverse=True), t.map_time(knots, hi, inverse=True)
                ).json()
                if status == "ready"
                else None,
            }
        )
    token = identity(source_id, kind, dict(asset), result)
    return {"rows": result, "token": token, "asset_id": asset["id"]}


def create(db, source_id, kind, token, selected_ids=None, **scope):
    from .selection_ops import save

    plan = preview(db, source_id, kind, **scope)
    if plan["token"] != token:
        raise ValueError("字幕、默认轨或设置已改变，请重新预览")
    ids = []
    # save(commit=False) keeps registration and deduplication in the same transaction.
    with db:
        for row in plan["rows"]:
            if row["status"] != "ready" or (selected_ids is not None and row["id"] not in selected_ids):
                continue
            sample = save(
                db,
                row["selection"],
                title=row["title"],
                nature="unpitched" if kind == "event" else "speech",
                commit=False,
            )
            db.execute("UPDATE materials SET cue_id=? WHERE id=?", (row["id"], sample["id"]))
            db.execute(
                "INSERT INTO subtitle_sample_imports VALUES(?,?,?,?)",
                (row["id"], kind, plan["asset_id"], sample["id"]),
            )
            ids.append(sample["id"])
    return {"sample_ids": ids, "created": len(ids)}
