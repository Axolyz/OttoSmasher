"""Compact, disposable speech projections. No audio/model work during retrieval."""

from pathlib import Path

from .sample_analysis import decode_record, encode_record, ready
from .workspace import identity

VERSION = "speech-search-3"


def ensure(db):
    db.execute(
        "CREATE TABLE IF NOT EXISTS speech_search_index(material_id TEXT PRIMARY KEY, signature TEXT, payload BLOB)"
    )
    tables = {r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    # A head/asset edit must not leave apparently current measurements searchable.
    for table in (
        "analysis_references",
        "analysis_runs",
        "sound_assets",
        "asset_samples",
        "speaker_annotations",
        "legacy_sample_measurements",
        "legacy_analyses",
        "cue_settings",
        "segment_settings",
        "rhythm_edits",
        "timeline_annotations",
        "sources",
    ):
        if table not in tables:
            continue
        for event in ("INSERT", "UPDATE", "DELETE"):
            db.execute(f"DROP TRIGGER IF EXISTS speech_dirty_{table}_{event}")
            keys = ("OLD", "NEW") if event == "UPDATE" else ("OLD",) if event == "DELETE" else ("NEW",)
            predicates = []
            for key in keys:
                source = None
                if table == "asset_samples":
                    predicates.append(f"material_id={key}.sample_id")
                    continue
                if table in ("sound_assets", "speaker_annotations", "timeline_annotations"):
                    source = f"{key}.source_id"
                elif table == "sources":
                    source = f"{key}.id"
                elif table == "analysis_runs":
                    source = f"(SELECT source_id FROM sound_assets WHERE id={key}.asset_id)"
                elif table == "analysis_references":
                    source = f"(SELECT s.source_id FROM analysis_runs a JOIN sound_assets s ON s.id=a.asset_id WHERE a.id={key}.run_id)"
                    predicates.append(f"material_id={key}.owner_id")
                elif table in ("cue_settings", "segment_settings", "rhythm_edits"):
                    source = f"(SELECT source_id FROM cues WHERE id={key}.cue_id)"
                if source:
                    predicates.append(f"material_id IN (SELECT id FROM materials WHERE source_id={source})")
            where = " WHERE " + " OR ".join(predicates) if predicates else ""
            db.execute(
                f"CREATE TRIGGER IF NOT EXISTS speech_dirty2_{table}_{event} AFTER {event} ON {table} BEGIN DELETE FROM speech_search_index{where}; END"
            )
    db.execute("""CREATE TRIGGER IF NOT EXISTS speech_dirty_material UPDATE OF source_id,start,end,cue_id,analysis_settings,active_phone_backend,active_quantization_strategy ON materials
        BEGIN DELETE FROM speech_search_index WHERE material_id=NEW.id; END""")
    for event in ("INSERT", "UPDATE", "DELETE"):
        key = "OLD" if event == "DELETE" else "NEW"
        db.execute(
            f"CREATE TRIGGER IF NOT EXISTS speech_dirty_records_{event} AFTER {event} ON sample_records BEGIN DELETE FROM speech_search_index WHERE material_id={key}.material_id; END"
        )
    if "ui_settings" in tables:
        for event in ("INSERT", "UPDATE", "DELETE"):
            key = "OLD" if event == "DELETE" else "NEW"
            db.execute(
                f"CREATE TRIGGER IF NOT EXISTS speech_dirty_settings_{event} AFTER {event} ON ui_settings WHEN {key}.key='large_number_penalty' BEGIN DELETE FROM speech_search_index; END"
            )


def compact(record):
    keep = (
        "cue",
        "analysis",
        "view",
        "compiled",
        "scope",
        "features",
        "signature",
        "asset",
        "root_cue",
        "backend",
    )
    result = {k: record[k] for k in keep if k in record}
    result["analysis"] = {
        k: record["analysis"][k] for k in ("version", "window_start", "window_end") if k in record["analysis"]
    }
    result["entries"] = [compact(e) for e in record.get("entries", [])]
    return result


def records(db, eligible):
    from .rhythm_index import index_version
    from .sample_rhythm import with_speakers
    from .speech_query import VERSION as units_version
    from .speech_query import unit_metrics

    ensure(db)
    eligible = set(eligible)
    file_stats = {}
    rows = db.execute("""SELECT m.*,r.signature record_signature,i.signature index_signature,i.payload index_payload
        FROM materials m LEFT JOIN sample_records r ON r.material_id=m.id AND r.backend=m.active_phone_backend
        LEFT JOIN speech_search_index i ON i.material_id=m.id""").fetchall()
    for row in rows:
        mid = row["id"]
        if mid not in eligible:
            continue
        try:
            key = identity(
                VERSION,
                units_version,
                index_version(),
                row["record_signature"],
                row["active_phone_backend"],
                row["active_quantization_strategy"],
                row["analysis_settings"],
            )
            if row["index_payload"] and row["index_signature"] == key:
                value = decode_record(row["index_payload"])
            else:
                record = ready(db, mid, materialize=False)
                units = unit_metrics(record)
                for variant in [record, *record.get("entries", [])]:
                    speakers = with_speakers(db, variant, variant["view"]["units"])
                    variant["features"] = [u["features"] for u in speakers]
                for unit, features in zip(units, record["features"]):
                    unit["measurements"].update(
                        {k: v for k, v in features.items() if k.startswith("speaker")}
                    )
                stat = Path(record["asset"]["path"]).stat()
                value = {
                    "record": compact(record),
                    "units": units,
                    "file_stat": [stat.st_size, stat.st_mtime_ns],
                }
                db.execute(
                    "INSERT OR REPLACE INTO speech_search_index VALUES(?,?,?)",
                    (mid, key, encode_record(value)),
                )
            record = value["record"]
            path = record["asset"]["path"]
            if path not in file_stats:
                stat = Path(path).stat()
                file_stats[path] = [stat.st_size, stat.st_mtime_ns]
            if value["file_stat"] != file_stats[path]:
                raise ValueError("声音文件已改变，请重新分析")
            record["strategy"] = row["active_quantization_strategy"]
            yield dict(row), record, value["units"], None
        except (ValueError, KeyError, OSError) as exc:
            yield dict(row), None, None, str(exc)
