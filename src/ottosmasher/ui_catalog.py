"""Presentation metadata and live inherited tags; no model inference or media copies."""

import json
import re
import time
from itertools import pairwise
from pathlib import Path

from .subtitle_import import EVENT_PATTERN, BRACKET_PATTERN

DEFAULTS = {
    "subtitle_event_pattern": EVENT_PATTERN,
    "subtitle_bracket_pattern": BRACKET_PATTERN,
    "subtitle_padding_before": 0.3,
    "subtitle_padding_after": 0.3,
    "studio_app": "",
    "studio_data": "",
    "phone_backend": "narabas",
    "phone_model_order": ["narabas", "phonetic", "pydomino"],
    "fa_padding_before": 0.65,
    "fa_padding_after": 0.65,
    "quantization": "acoustic",
    "vocal_model": "becruily_deux",
    "bpm": 120,
    "model_concurrency": 1,
    "utility_concurrency": 2,
    "separation_progress": True,
    "zoom_curve": "exponential",
    "zoom_threshold": 5,
    "export_directory": "",
    "inference_device": "auto",
    "cuda_device": 0,
    "onnx_acceleration": False,
    "onnx_device_id": 0,
    "large_number_penalty": 1.0,
    "cache_auto_trim": True,
}


def ensure(db):
    db.execute(
        "CREATE TABLE IF NOT EXISTS source_labels(source_id TEXT PRIMARY KEY,work TEXT NOT NULL,episode TEXT NOT NULL,media_type TEXT NOT NULL,imported REAL NOT NULL)"
    )
    db.execute("CREATE TABLE IF NOT EXISTS ui_settings(key TEXT PRIMARY KEY,value TEXT NOT NULL)")
    db.execute(
        "CREATE TABLE IF NOT EXISTS tag_rules(tag TEXT PRIMARY KEY,inherit INTEGER NOT NULL DEFAULT 0)"
    )
    db.execute(
        "CREATE TABLE IF NOT EXISTS tag_overrides(material_id TEXT NOT NULL,category TEXT NOT NULL,value TEXT,PRIMARY KEY(material_id,category))"
    )
    for s in db.execute(
        "SELECT id,title FROM sources WHERE id NOT IN (SELECT source_id FROM source_labels)"
    ).fetchall():
        work, episode = infer_name(s["title"])
        db.execute("INSERT INTO source_labels VALUES(?,?,?,?,?)", (s["id"], work, episode, "", time.time()))


def infer_name(title):
    stem = Path(title).stem
    parts = re.findall(r"\[([^]]+)\]", stem)
    episode_index = next((i for i, x in enumerate(parts) if re.fullmatch(r"\d{1,3}(?:v\d)?", x)), None)
    if episode_index is not None:
        episode = parts[episode_index]
        prefix = stem[: stem.index("[" + episode + "]")]
        outside = re.sub(r"\[[^]]+\]", "", prefix).strip(" ._-")
        candidates = parts[:episode_index]
        work = outside or (candidates[-1] if candidates else stem)
        return work, episode
    m = re.match(r"^(.*?)[ ._-]+(?:[Ee][Pp]?)?(\d{1,3})$", stem)
    return (m[1].strip(), m[2]) if m else (stem, "")


def settings(db, values=None):
    ensure(db)
    if values is not None:
        values = dict(values)
        if "phone_model_order" in values:
            order = values["phone_model_order"]
            if (
                not isinstance(order, list)
                or len(order) != 3
                or set(order) != {"narabas", "phonetic", "pydomino"}
            ):
                raise ValueError("FA 模型排序必须恰好包含 narabas、phonetic、pydomino 各一次")
            values["phone_backend"] = order[0]
        elif "phone_backend" in values:
            order = settings(db)["phone_model_order"]
            values["phone_model_order"] = [
                values["phone_backend"],
                *[x for x in order if x != values["phone_backend"]],
            ]
        for key in ("fa_padding_before", "fa_padding_after"):
            value = values.get(key, 0.65)
            if isinstance(value, bool) or not isinstance(value, (int, float)) or not 0 <= value <= 5:
                raise ValueError("FA 前后容差必须为 0–5 秒")
        if values.get("inference_device", "auto") not in ("auto", "cpu", "cuda", "mps"):
            raise ValueError("未知推理设备")
        if not isinstance(values.get("cuda_device", 0), int) or values.get("cuda_device", 0) < 0:
            raise ValueError("CUDA 设备编号必须为非负整数")
        if not 0 <= float(values.get("large_number_penalty", 1)) <= 3:
            raise ValueError("大数字惩罚度必须为 0–3 倍")
        if not isinstance(values.get("cache_auto_trim", True), bool):
            raise ValueError("自动缓存整理必须为开关")
        if not isinstance(values.get("onnx_acceleration", False), bool):
            raise ValueError("ONNX 加速必须为开关")
        index = values.get("onnx_device_id", 0)
        if isinstance(index, bool) or not isinstance(index, int) or index < 0:
            raise ValueError("GPU 设备编号必须为非负整数")
        from .subtitle_import import classify

        classify("(話者) 台詞", {**DEFAULTS, **values})
        for key in ("subtitle_padding_before", "subtitle_padding_after"):
            v = values.get(key, 0.3)
            if isinstance(v, bool) or not isinstance(v, (float, int)) or not 0 <= v <= 5:
                raise ValueError("字幕容差必须为 0–5 秒")
        unknown = set(values) - set(DEFAULTS)
        if unknown:
            raise ValueError("未知设置: " + ",".join(unknown))
        from .sample_catalog import BACKENDS

        if values.get("phone_backend", "narabas") not in BACKENDS:
            raise ValueError("未知音素模型")
        if values.get("quantization", "acoustic") not in ("acoustic", "mora", "mora_guided"):
            raise ValueError("未知量化路线")
        if (
            not 30 <= float(values.get("bpm", 120)) <= 300
            or not 1 <= float(values.get("zoom_threshold", 5)) <= 100
        ):
            raise ValueError("BPM 或缩放阈值无效")
        for key in ("model_concurrency", "utility_concurrency"):
            value = values.get(key, DEFAULTS[key])
            if isinstance(value, bool) or not isinstance(value, int) or not 1 <= value <= 4:
                raise ValueError("并发数须为 1–4 的整数")
        if not isinstance(values.get("separation_progress", True), bool):
            raise ValueError("进度显示必须为开关")
        for key, value in values.items():
            db.execute("INSERT OR REPLACE INTO ui_settings VALUES(?,?)", (key, json.dumps(value)))
        db.commit()
    stored = {r[0]: json.loads(r[1]) for r in db.execute("SELECT * FROM ui_settings")}
    result = {**DEFAULTS, **stored}
    if "phone_model_order" not in stored:
        result["phone_model_order"] = [
            result["phone_backend"],
            *[x for x in DEFAULTS["phone_model_order"] if x != result["phone_backend"]],
        ]
    return result


def label_source(db, source_id, **values):
    ensure(db)
    if not db.execute("SELECT 1 FROM sources WHERE id=?", (source_id,)).fetchone():
        raise ValueError("原片不存在")
    for key in ("work", "episode", "media_type"):
        if key in values:
            db.execute(
                f"UPDATE source_labels SET {key}=? WHERE source_id=?",
                (str(values[key]).strip()[:200], source_id),
            )
    db.commit()


def effective_all(db, material_ids=None, *, only_tags=None):
    """One bounded catalog pass; annotations are resolved over root-media ranges."""
    ensure(db)
    from .asset_compat import active

    unified = active(db)
    # Large scopes use a bounded catalog pass, not an unbounded SQL IN list.
    if material_ids is not None:
        material_ids = list(material_ids)
        if len(material_ids) > 800:
            material_ids = None
    # A detail read loads only its ancestors and source annotations, never the full catalog.
    args = []
    clause = ""
    if material_ids is not None:
        ids = set(material_ids)
        frontier = list(ids)
        if db.execute("SELECT 1 FROM sqlite_master WHERE name='sample_edges'").fetchone():
            while frontier:
                placeholders = ",".join("?" for _ in frontier)
                parents = {
                    r[0]
                    for r in db.execute(
                        f"SELECT parent_id FROM sample_edges WHERE child_id IN ({placeholders})", frontier
                    )
                } - ids
                ids.update(parents)
                frontier = list(parents)
        if not ids:
            return {}
        args = list(ids)
        clause = " WHERE id IN (" + ",".join("?" for _ in args) + ")"
    rows = {
        r["id"]: dict(r)
        for r in db.execute("SELECT id,source_id,start,end,cue_id FROM materials" + clause, args)
    }

    def subset(table, field, values):
        if material_ids is None:
            return db.execute("SELECT * FROM " + table)
        values = list(set(values))
        if not values:
            return []
        return db.execute(
            "SELECT * FROM " + table + " WHERE " + field + " IN (" + ",".join("?" for _ in values) + ")",
            values,
        )

    sources = {r["source_id"] for r in rows.values()}
    labels = {r["source_id"]: dict(r) for r in subset("source_labels", "source_id", sources)}
    rules = {r[0] for r in db.execute("SELECT tag FROM tag_rules WHERE inherit=1")}
    local = {mid: [] for mid in rows}
    for t in subset("material_tags", "material_id", rows):
        if (
            t["material_id"] in local
            and t["origin"] != "speaker_manual"
            and (only_tags is None or t["tag"] in only_tags)
        ):
            local[t["material_id"]].append({"tag": t["tag"], "origin": t["origin"], "inherited": False})
    edges = (
        {r["child_id"]: r["parent_id"] for r in subset("sample_edges", "child_id", rows)}
        if db.execute("SELECT 1 FROM sqlite_master WHERE name='sample_edges'").fetchone()
        else {}
    )
    annotations = {}
    if not unified and db.execute("SELECT 1 FROM sqlite_master WHERE name='speaker_annotations'").fetchone():
        for a in sorted(
            subset("speaker_annotations", "source_id", sources), key=lambda x: x["created"], reverse=True
        ):
            annotations.setdefault(a["source_id"], []).append(dict(a))
    overrides = {}
    for o in subset("tag_overrides", "material_id", rows):
        overrides.setdefault(o["material_id"], {})[o["category"]] = o["value"]
    from .subtitle_speakers import ensure as ensure_speakers

    ensure_speakers(db)
    subtitle = (
        {}
        if unified
        else {
            r[0]: json.loads(r[1])
            for r in subset(
                "subtitle_speakers", "cue_id", [r["cue_id"] for r in rows.values() if r["cue_id"]]
            )
        }
    )
    if only_tags is not None and not any(t.startswith("pitch:") for t in only_tags):
        assets = {}
    elif unified:
        if material_ids is None:
            notes = {
                r[0]: json.loads(r[1]) if r[1] else None
                for r in db.execute("SELECT id,json_extract(descriptor,'$.target_note') FROM sound_assets")
            }
            assets = {
                r[0]: {"target_note": notes.get(r[1])}
                for r in db.execute("SELECT sample_id,asset_id FROM asset_samples")
                if r[0] in rows
            }
        else:
            assets = {
                r[0]: {"target_note": json.loads(r[1]) if r[1] else None}
                for r in db.execute(
                    "SELECT s.sample_id,json_extract(a.descriptor,'$.target_note') FROM asset_samples s JOIN sound_assets a ON a.id=s.asset_id WHERE s.sample_id IN ("
                    + ",".join("?" for _ in rows)
                    + ")",
                    list(rows),
                )
            }
    else:
        assets = (
            {r[0]: json.loads(r[1]) for r in subset("sample_assets", "material_id", rows)}
            if db.execute("SELECT 1 FROM sqlite_master WHERE name='sample_assets'").fetchone()
            else {}
        )
    from .timeline_labels import effective

    scoped = effective(db, rows, only_tags=only_tags) if unified else {}
    result = {}
    for mid, r in rows.items():
        tags = list(local[mid])
        s = labels.get(r["source_id"], {})
        for key, prefix in (("work", "work:"), ("media_type", "type:")):
            value = s.get(key)
            if value and (only_tags is None or prefix + value in only_tags):
                tags.append(
                    {
                        "tag": prefix + value,
                        "origin": "source",
                        "inherited": True,
                        "source_id": r["source_id"],
                    }
                )
        if unified:
            tags.extend(scoped.get(mid, []))
        else:
            aa = [
                a
                for a in annotations.get(r["source_id"], [])
                if a["start"] < r["end"] and a["end"] > r["start"]
            ]
            cuts = sorted(
                {
                    r["start"],
                    r["end"],
                    *[max(r["start"], min(r["end"], a[k])) for a in aa for k in ("start", "end")],
                }
            )
            for lo, hi in pairwise(cuts):
                a = next((a for a in aa if a["start"] <= (lo + hi) / 2 < a["end"]), None)
                if a:
                    tags.append(
                        {"tag": "character:" + a["speaker"], "origin": "speaker_manual", "inherited": True}
                    )
            attribution = subtitle.get(r.get("cue_id"), {})
            if not any(t["origin"] == "speaker_manual" for t in tags):
                prefix = "character:" if attribution.get("status") == "single" else "participants:"
                tags.extend(
                    {"tag": prefix + name, "origin": "subtitle", "inherited": True, "confirmed": False}
                    for name in attribution.get("names", [])
                )
                if attribution.get("status") == "multiple_or_group":
                    tags.append({"tag": "speaker-status:多人未分段", "origin": "subtitle", "inherited": True})
        note = assets.get(mid, {}).get("target_note")
        if note and note.get("name"):
            tags.append(
                {
                    "tag": "pitch:" + note["name"],
                    "origin": "flatten_target",
                    "inherited": bool(edges.get(mid)),
                }
            )
        parent, seen = edges.get(mid), {mid}
        while parent and parent not in seen:
            seen.add(parent)
            tags.extend(
                {**t, "inherited": True, "origin": "ancestor"}
                for t in local.get(parent, [])
                if t["tag"] in rules
            )
            parent = edges.get(parent)
        for category, value in overrides.get(mid, {}).items():
            tags = [t for t in tags if not t["tag"].startswith(category + ":")]
            if value:
                tags.append({"tag": category + ":" + value, "origin": "local_override", "inherited": False})
        if only_tags is not None:
            # Query callers need membership, not sorted presentation/provenance.
            # The same inheritance and override rules above still apply.
            result[mid] = {t["tag"] for t in tags if t["tag"] in only_tags}
            continue
        # Prefer explicit local labels without deleting historical records.
        dedup = {}
        for t in sorted(tags, key=lambda t: not t["inherited"]):
            dedup[t["tag"]] = t
        result[mid] = [
            {**t, "inheritable": t["tag"] in rules} for t in sorted(dedup.values(), key=lambda t: t["tag"])
        ]
    return result


def listing(db, body):
    from .sample_scope import ids
    from .timbre_features import filter_ids

    scope = dict(body.get("scope") or {})
    wanted = scope.pop("tags", [])
    candidates = set(ids(db, scope))
    tags = effective_all(db)
    if wanted:
        candidates = {mid for mid in candidates if set(wanted) <= {t["tag"] for t in tags[mid]}}
    unknown = 0
    if body.get("conditions"):
        candidates, unknown = filter_ids(
            db, list(candidates), body["conditions"], body.get("producer", "otto.dsp")
        )
        candidates = set(candidates)
    columns = {"created": "m.created", "title": "m.title", "duration": "(m.end-m.start)", "work": "l.work"}
    order = columns.get(body.get("sort"), "m.created")
    direction = "ASC" if body.get("order") == "asc" else "DESC"
    rows = []
    for r in db.execute(
        f"SELECT m.id,m.title,m.source_id,m.start,m.end,m.starred,m.nature,m.rating,m.status,m.created,l.work,l.episode,l.media_type FROM materials m LEFT JOIN source_labels l ON l.source_id=m.source_id ORDER BY {order} {direction},m.id"
    ):
        if r["id"] in candidates:
            rows.append({**dict(r), "tags": tags[r["id"]], "duration": r["end"] - r["start"]})
    if body.get("ids_only"):
        return {"ids": [r["id"] for r in rows]}
    offset, limit = max(0, int(body.get("offset", 0))), min(200, max(1, int(body.get("limit", 100))))
    return {
        "total": len(rows),
        "unknown": unknown,
        "results": rows[offset : offset + limit],
        "tags": sorted({t["tag"] for mid in candidates for t in tags[mid]}),
    }


def place_export(db, result):
    """Copy to a user-selected persistent directory without changing ancestry assets."""
    import shutil

    directory = settings(db)["export_directory"]
    if not directory:
        return result
    target_dir = Path(directory).expanduser().resolve()
    target_dir.mkdir(parents=True, exist_ok=True)
    source = Path(result["path"])
    target = target_dir / source.name
    from .materials import sha256

    if target.exists() and target.resolve() != source.resolve() and sha256(target) != sha256(source):
        target = target_dir / (source.stem + "__" + sha256(source)[:12] + source.suffix)
    if source.resolve() != target.resolve():
        shutil.copy2(source, target)
        for sidecar in source.parent.glob(source.stem + "*"):
            if sidecar.is_file() and sidecar != source and sidecar.suffix.lower() in (".json", ".textgrid"):
                shutil.copy2(sidecar, target_dir / (target.stem + sidecar.name[len(source.stem) :]))
    return {**result, "path": str(target), "persistent_origin": str(source)}
