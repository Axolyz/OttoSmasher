from __future__ import annotations

import hashlib
import json
import re
import unicodedata
from pathlib import Path

import pykakasi
import pysubs2
from sudachipy import Dictionary, SplitMode

from .workspace import command, connect, executable, identity

KAKASI = pykakasi.kakasi()
SUDACHI = Dictionary(dict="core").create()
BRACKETS = re.compile(r"[（(]([^）)]*)[）)]")
EVENT_WORDS = ("寝息", "あくび", "息遣い", "泣き", "笑い", "鳴き", "足音", "物音", "拍手", "悲鳴")


def normalize(text):
    text = unicodedata.normalize("NFKC", text).lower()
    return "".join(c for c in text if not unicodedata.category(c).startswith(("P", "Z", "C")))


def reading_text(text):
    kana = "".join(
        token.reading_form() for token in SUDACHI.tokenize(text, SplitMode.C) if normalize(token.surface())
    )
    return normalize("".join(x["hira"] for x in KAKASI.convert(kana)))


def parse_text(text):
    original = text.replace("\\N", "\n")
    plain = re.sub(r"\{[^}]*\}|<[^>]*>", "", original).strip()
    from .subtitle_speakers import annotations, extract, spoken_text

    notes = annotations(plain)
    spoken = spoken_text(plain)
    attribution = extract(plain)
    speaker = attribution["names"][0] if attribution["status"] == "single" else None
    kind = "dialogue" if spoken else "event"
    flags = []
    if notes:
        flags.append("subtitle_annotations")
    if "♪" in spoken or "♬" in spoken:
        kind = "song"
    if "\n" in spoken:
        flags.append("multiline")
    reading = reading_text(spoken)
    return original, spoken, normalize(spoken), normalize(reading), speaker, kind, flags


def probe(path):
    return json.loads(
        command(
            [executable("ffprobe"), "-v", "error", "-show_format", "-show_streams", "-of", "json", path]
        ).stdout
    )


def import_directory(folder: Path, audio_stream: int | None = None):
    db = connect()
    result = {"imported": 0, "unchanged": 0, "cues": 0, "errors": []}
    for path in sorted(folder.resolve().iterdir()):
        if path.suffix.lower() not in {".mkv", ".mp4", ".wav", ".flac", ".m4a"}:
            continue
        subtitle = next((path.with_suffix(x) for x in (".srt", ".ass") if path.with_suffix(x).exists()), None)
        if subtitle is None:
            result["errors"].append({"file": path.name, "error": "No matching SRT/ASS"})
            continue
        try:
            stat = path.stat()
            fingerprint = identity(
                stat.st_size, stat.st_mtime_ns, hashlib.sha256(subtitle.read_bytes()).hexdigest()
            )
            sid = identity(str(path))
            existing = db.execute(
                "SELECT fingerprint,audio_stream,subtitle_path FROM sources WHERE id=?", (sid,)
            ).fetchone()
            if (
                existing
                and existing[0] == fingerprint
                and (audio_stream is None or audio_stream == existing[1])
            ):
                result["unchanged"] += 1
                continue
            if existing and existing[2]:
                raise ValueError(
                    "Source/subtitles changed: keep existing provenance; import a new source path"
                )
            if existing:
                from .materials import sha256

                if sha256(path) != existing[0]:
                    raise ValueError("预登记原片已改变，请检查文件；未覆盖来源")
                if db.execute("SELECT 1 FROM cues WHERE source_id=? LIMIT 1", (sid,)).fetchone():
                    raise ValueError("此原片已有字幕记录，不能覆盖")
            info = probe(path)
            tracks = [s for s in info["streams"] if s["codec_type"] == "audio"]
            if audio_stream is None:
                japanese = [s for s in tracks if s.get("tags", {}).get("language") in {"jpn", "ja"}]
                options = japanese or tracks
                if len(options) != 1:
                    raise ValueError(
                        f"Ambiguous audio tracks {[s['index'] for s in options]}; specify --audio-stream"
                    )
                chosen = options[0]["index"]
            else:
                if audio_stream not in [s["index"] for s in tracks]:
                    raise ValueError("Requested audio stream does not exist")
                chosen = audio_stream
            duration = float(info["format"]["duration"])
            subtitles = pysubs2.load(str(subtitle), encoding="utf-8-sig")
            with db:
                db.execute(
                    "INSERT INTO sources VALUES (?,?,?,?,?,?,?,?) ON CONFLICT(id) DO UPDATE SET subtitle_path=excluded.subtitle_path,fingerprint=excluded.fingerprint,audio_stream=excluded.audio_stream,metadata=excluded.metadata",
                    (
                        sid,
                        str(path),
                        str(subtitle),
                        fingerprint,
                        path.stem,
                        duration,
                        chosen,
                        json.dumps(info, ensure_ascii=False),
                    ),
                )
                for i, event in enumerate(subtitles):
                    start, end = event.start / 1000, event.end / 1000
                    if end <= start or start < 0 or start >= duration:
                        raise ValueError(f"Invalid subtitle interval at cue {i + 1}")
                    parsed = parse_text(event.text)
                    *fields, flags = parsed
                    db.execute(
                        "INSERT INTO cues VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                        (
                            identity(sid, fingerprint, i),
                            sid,
                            i,
                            start,
                            min(end, duration),
                            *fields,
                            json.dumps(flags, ensure_ascii=False),
                        ),
                    )
            result["imported"] += 1
            result["cues"] += len(subtitles)
        except Exception as exc:  # noqa: BLE001 - rollback failed episode and report it
            db.rollback()
            result["errors"].append({"file": path.name, "error": str(exc)})
    from .materials import sync_cues

    sync_cues(db)
    db.close()
    return result


def search_text(db, text="", source_id=None, limit=50, offset=0, analyzed_only=False):
    conditions, params = [], []
    if text:
        query = normalize(text)
        conditions.append("(instr(c.normalized,?)>0 OR instr(c.reading,?)>0 OR instr(c.original,?)>0)")
        reading = reading_text(text)
        params.extend((query, reading, text))
    if source_id:
        conditions.append("c.source_id=?")
        params.append(source_id)
    if analyzed_only:
        conditions.append(
            "EXISTS (SELECT 1 FROM analyses a WHERE a.cue_id=c.id AND a.created=(SELECT max(b.created) FROM analyses b WHERE b.cue_id=a.cue_id AND b.kind=a.kind) AND json_array_length(a.payload,'$.phones')>0 AND json_extract(a.payload,'$.input_variant')='vocals')"
        )
    where = " WHERE " + " AND ".join(conditions) if conditions else ""
    rows = db.execute(
        "SELECT c.*,s.title FROM cues c JOIN sources s ON c.source_id=s.id"
        + where
        + " ORDER BY s.path,c.ordinal LIMIT ? OFFSET ?",
        (*params, limit, offset),
    ).fetchall()
    return [with_analysis_status(db, dict(r)) for r in rows]


def with_analysis_status(db, cue):
    cue["analysis_status"] = {
        r["kind"]: ("success" if json.loads(r["payload"]).get("phones") else "failed")
        for r in db.execute(
            "SELECT a.kind,a.payload FROM analyses a WHERE a.cue_id=? AND a.kind IN ('narabas','phonetic','pydomino') AND a.created=(SELECT max(b.created) FROM analyses b WHERE b.cue_id=a.cue_id AND b.kind=a.kind)",
            (cue["id"],),
        )
    }
    return cue


def neighbors(db, cue_id, radius=2):
    cue = db.execute("SELECT source_id,ordinal FROM cues WHERE id=?", (cue_id,)).fetchone()
    if not cue:
        return []
    return [
        dict(r)
        for r in db.execute(
            "SELECT * FROM cues WHERE source_id=? AND ordinal BETWEEN ? AND ? ORDER BY ordinal",
            (cue[0], cue[1] - radius, cue[1] + radius),
        )
    ]


def stats(db):
    return {
        "sources": [
            dict(x) for x in db.execute("SELECT id,title,duration,audio_stream FROM sources ORDER BY path")
        ],
        "cues": db.execute("SELECT count(*) FROM cues").fetchone()[0],
        "kinds": dict(db.execute("SELECT kind,count(*) FROM cues GROUP BY kind")),
        "analyses": dict(
            db.execute("""SELECT kind,count(DISTINCT cue_id) FROM analyses a
            WHERE a.created=(SELECT max(b.created) FROM analyses b WHERE b.kind=a.kind AND b.cue_id=a.cue_id)
                AND json_extract(a.payload,'$.error') IS NULL
                AND (a.kind='acoustic' OR json_extract(a.payload,'$.input_variant')='vocals') GROUP BY kind""")
        ),
        "jobs": [
            dict(x)
            for x in db.execute(
                "SELECT status,operation,count(*) AS count FROM jobs GROUP BY status,operation"
            )
        ],
    }
