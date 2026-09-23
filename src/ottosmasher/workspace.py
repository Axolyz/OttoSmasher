from __future__ import annotations

import hashlib
import json
import os
import shutil
import sqlite3
import subprocess
import tempfile
import threading
import time
from pathlib import Path

ROOT = Path(os.environ.get("OTTO_ROOT", Path(__file__).resolve().parents[2])).resolve()
CODE_ROOT = Path(os.environ.get("OTTO_CODE_ROOT", Path(__file__).resolve().parents[2])).resolve()
CORE_ENV = Path(os.environ.get("OTTO_CORE_ENV", ROOT / ".runtime/envs/core")).resolve()
DATA = ROOT / "data"


def identity(*parts) -> str:
    return hashlib.sha256(json.dumps(parts, ensure_ascii=False, sort_keys=True).encode()).hexdigest()[:24]


_DB_INIT_LOCK = threading.RLock()


def connect() -> sqlite3.Connection:
    # New workspaces receive concurrent GUI requests before migrations finish.
    # Serialize schema initialization across threads and local worker processes.
    with _DB_INIT_LOCK:
        DATA.mkdir(parents=True, exist_ok=True)
        from filelock import FileLock
        with FileLock(str(DATA / "schema.lock")):
            return _connect()


def _connect() -> sqlite3.Connection:
    DATA.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(DATA / "catalog.sqlite3", timeout=30)
    db.row_factory = sqlite3.Row
    db.execute("PRAGMA journal_mode=WAL")
    db.execute("PRAGMA foreign_keys=ON")
    db.executescript("""
    CREATE TABLE IF NOT EXISTS sources (
      id TEXT PRIMARY KEY, path TEXT UNIQUE NOT NULL, subtitle_path TEXT NOT NULL,
      fingerprint TEXT NOT NULL, title TEXT NOT NULL, duration REAL NOT NULL,
      audio_stream INTEGER NOT NULL, metadata TEXT NOT NULL
    );
    CREATE TABLE IF NOT EXISTS cues (
      id TEXT PRIMARY KEY, source_id TEXT NOT NULL REFERENCES sources(id),
      ordinal INTEGER NOT NULL, start REAL NOT NULL, end REAL NOT NULL,
      original TEXT NOT NULL, spoken TEXT NOT NULL, normalized TEXT NOT NULL,
      reading TEXT NOT NULL, speaker TEXT, kind TEXT NOT NULL, flags TEXT NOT NULL,
      UNIQUE(source_id, ordinal)
    );
    CREATE INDEX IF NOT EXISTS cue_source_order ON cues(source_id, ordinal);
    CREATE TABLE IF NOT EXISTS analyses (
      cue_id TEXT NOT NULL REFERENCES cues(id), kind TEXT NOT NULL, version TEXT NOT NULL,
      payload TEXT NOT NULL, created REAL NOT NULL,
      PRIMARY KEY(cue_id, kind, version)
    );
    CREATE TABLE IF NOT EXISTS jobs (
      id TEXT PRIMARY KEY, cue_id TEXT, operation TEXT NOT NULL,
      status TEXT NOT NULL, error TEXT, updated REAL NOT NULL
    );
    CREATE TABLE IF NOT EXISTS rhythm_edits (
      cue_id TEXT NOT NULL REFERENCES cues(id), kind TEXT NOT NULL, analysis_version TEXT NOT NULL,
      split_before TEXT NOT NULL, updated REAL NOT NULL,
      PRIMARY KEY(cue_id, kind, analysis_version)
    );
    CREATE TABLE IF NOT EXISTS cue_settings (
      cue_id TEXT NOT NULL REFERENCES cues(id), kind TEXT NOT NULL, analysis_id TEXT NOT NULL,
      payload TEXT NOT NULL, PRIMARY KEY(cue_id,kind,analysis_id)
    );
    CREATE TABLE IF NOT EXISTS segment_settings (
      cue_id TEXT NOT NULL REFERENCES cues(id), kind TEXT NOT NULL, analysis_version TEXT NOT NULL,
      payload TEXT NOT NULL, PRIMARY KEY(cue_id,kind,analysis_version)
    );
    CREATE TABLE IF NOT EXISTS rhythm_index (
      cue_id TEXT NOT NULL REFERENCES cues(id), kind TEXT NOT NULL,
      signature TEXT NOT NULL, payload TEXT NOT NULL, updated REAL NOT NULL,
      PRIMARY KEY(cue_id,kind)
    );
    CREATE TABLE IF NOT EXISTS speaker_annotations (
      id TEXT PRIMARY KEY, source_id TEXT NOT NULL, start REAL NOT NULL, end REAL NOT NULL,
      speaker TEXT NOT NULL, action_id TEXT NOT NULL, created REAL NOT NULL
    );
    CREATE TABLE IF NOT EXISTS speaker_actions (
      id TEXT PRIMARY KEY, operation TEXT NOT NULL, payload TEXT NOT NULL, undone INTEGER NOT NULL DEFAULT 0,
      created REAL NOT NULL
    );
    CREATE TABLE IF NOT EXISTS feedback (
      id INTEGER PRIMARY KEY, cue_id TEXT REFERENCES cues(id), value TEXT NOT NULL,
      context TEXT NOT NULL, created REAL NOT NULL
    );
    """)
    from .materials import migrate

    migrate(db)
    from .sample_catalog import migrate as migrate_samples

    migrate_samples(db)
    from .ui_catalog import ensure as ensure_presentation

    ensure_presentation(db)
    db.commit()
    return db


def executable(name: str) -> str:
    override = os.environ.get(f"OTTO_{name.upper()}")
    base = CORE_ENV
    candidates = [base / "Library/bin" / (name + ".exe"), base / "Scripts" / (name + ".exe"), base / (name + ".exe")] if os.name == "nt" else [base / "bin" / name]
    local = next((p for p in candidates if p.is_file()), None)
    found = override or (str(local) if local else shutil.which(name))
    if not found:
        raise RuntimeError(f"Missing {name}; run the environment setup first")
    return found


def command(args: list, **kwargs) -> subprocess.CompletedProcess:
    p = subprocess.run([str(x) for x in args], capture_output=True, text=True, check=False, **kwargs)
    if p.returncode:
        raise RuntimeError(f"{args[0]} exited {p.returncode}: {p.stderr[-5000:]}")
    return p


def write_json(path: Path, payload):
    path.parent.mkdir(parents=True, exist_ok=True)
    # FastAPI can materialize the same plan on concurrent worker threads. A
    # process-only temporary name lets one writer remove another one's file.
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w", encoding="utf-8", dir=path.parent, prefix=f".{path.name}.", suffix=".tmp", delete=False
        ) as out:
            temporary = Path(out.name)
            json.dump(payload, out, ensure_ascii=False, indent=2, allow_nan=False)
            out.write("\n")
        os.replace(temporary, path)
    finally:
        if temporary:
            temporary.unlink(missing_ok=True)


def save_analysis(db, cue_id, kind, version, payload):
    db.execute(
        "INSERT OR REPLACE INTO analyses VALUES (?,?,?,?,?)",
        (cue_id, kind, version, json.dumps(payload, ensure_ascii=False, allow_nan=False), time.time()),
    )
    db.commit()


def set_job(db, job_id, cue_id, operation, status, error=None):
    db.execute(
        "INSERT OR REPLACE INTO jobs VALUES (?,?,?,?,?,?)",
        (job_id, cue_id, operation, status, error, time.time()),
    )
    db.commit()


def get_cue(db, cue_id):
    row = db.execute(
        """SELECT c.*, s.path, s.audio_stream, s.duration AS source_duration,
                       s.fingerprint, s.title FROM cues c JOIN sources s ON c.source_id=s.id
                       WHERE c.id=?""",
        (cue_id,),
    ).fetchone()
    if row is None:
        raise ValueError("Unknown cue")
    return dict(row)


def get_analysis(db, cue_id, kind):
    row = db.execute(
        "SELECT payload FROM analyses WHERE cue_id=? AND kind=? ORDER BY created DESC LIMIT 1", (cue_id, kind)
    ).fetchone()
    return json.loads(row[0]) if row else None


def get_speech_analysis(db, cue_id, kind):
    result = get_analysis(db, cue_id, kind)
    # Never silently reuse the original mixed-audio experiment as speech data.
    if not result or result.get("input_variant") != "vocals":
        return None
    return result


def get_vocals_lineage(db, cue_id, preferred_kind=None):
    if preferred_kind and preferred_kind != "acoustic":
        analysis = get_speech_analysis(db, cue_id, preferred_kind)
        if analysis:
            return analysis.get("audio_lineage")
    if preferred_kind and preferred_kind != "acoustic":
        return None
    for kind in ("narabas", "phonetic", "pydomino", "vocals_energy"):
        analysis = get_speech_analysis(db, cue_id, kind)
        if analysis and analysis.get("audio_lineage"):
            return analysis["audio_lineage"]
    return None
