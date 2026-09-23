from .workspace import CODE_ROOT
"""Persisted local jobs. Child processes outlive windows; retries get new IDs."""

import json
import os
import signal
import subprocess
import sys
import time
import uuid

from .workspace import DATA, ROOT, connect

OPERATIONS = {
    "speech-prepare",
    "native-alignment",
    "source-separation",
    "acoustic-features",
    "opening-scan",
    "sample-features",
    "sample-phones",
    "flatten",
    "sample-prepare",
    "separate",
    "subtitles",
    "index",
    "cut",
}


def resource_lane(operation):
    return (
        "utility"
        if operation in {"cut", "sample-prepare", "index", "opening-scan"}
        else "model"
    )


def submit(operation, payload):
    from .cache_storage import maintenance_lock
    with maintenance_lock():
        return _submit(operation, payload)


def _submit(operation, payload):
    if operation not in OPERATIONS:
        raise ValueError("未知操作")
    from .inference_runtime import settings as runtime_settings
    payload = {**payload, "runtime": payload.get("runtime") or runtime_settings()}
    jid = uuid.uuid4().hex
    with connect() as db:
        db.execute(
            "INSERT INTO operation_jobs VALUES(?,?,?,?,?,?,?,?,?)",
            (
                jid,
                operation,
                json.dumps(payload, ensure_ascii=False),
                "queued",
                None,
                None,
                None,
                time.time(),
                time.time(),
            ),
        )
    return launch(jid)


def launch(jid):
    folder = DATA / "logs" / "jobs"
    folder.mkdir(parents=True, exist_ok=True)
    env = {**os.environ, "OTTO_ROOT": str(ROOT), "PYTHONPATH": str(CODE_ROOT / "src")}
    with (folder / f"{jid}.log").open("ab") as log:
        child = subprocess.Popen(
            [sys.executable, "-m", "ottosmasher.job_worker", jid],
            cwd=ROOT,
            env=env,
            stdin=subprocess.DEVNULL,
            stdout=log,
            stderr=log,
            start_new_session=True,
        )
    with connect() as db:
        db.execute("UPDATE operation_jobs SET pid=?,updated=? WHERE id=?", (child.pid, time.time(), jid))
    return {"id": jid, "status": "queued", "pid": child.pid}


def listing():
    with connect() as db:
        rows = [dict(r) for r in db.execute("SELECT * FROM operation_jobs ORDER BY created DESC LIMIT 200")]
        for r in rows:
            if r["status"] in ("running", "queued") and r["pid"]:
                try:
                    import psutil
                    if not psutil.pid_exists(r['pid']):
                        raise ProcessLookupError()
                except ProcessLookupError:
                    r["status"] = "interrupted"
                    r["error"] = "工作进程已退出，可重试"
                    db.execute(
                        "UPDATE operation_jobs SET status=?,error=?,updated=? WHERE id=?",
                        (r["status"], r["error"], time.time(), r["id"]),
                    )
            progress_path = DATA / "jobs" / f"{r['id']}-progress.json"
            if progress_path.is_file():
                try:
                    r["progress"] = json.loads(progress_path.read_text())
                except (OSError, ValueError):
                    pass
            r["resource_lane"] = resource_lane(r["operation"])
            r["payload"] = json.loads(r["payload"])
            r["result"] = json.loads(r["result"]) if r["result"] else None
        return rows


def cancel(jid):
    with connect() as db:
        row = db.execute("SELECT * FROM operation_jobs WHERE id=?", (jid,)).fetchone()
        if not row:
            raise ValueError("任务不存在")
        if row["status"] not in ("running", "queued"):
            return {"status": row["status"]}
        db.execute("UPDATE operation_jobs SET status='cancelled',updated=? WHERE id=?", (time.time(), jid))
        db.commit()
        if row["pid"]:
            try:
                if os.name == "posix":
                    os.killpg(row["pid"], signal.SIGTERM)
                else:
                    subprocess.run(["taskkill", "/PID", str(row["pid"]), "/T", "/F"], check=False, capture_output=True)
            except ProcessLookupError:
                pass
    return {"status": "cancelled"}


def retry(jid):
    with connect() as db:
        row = db.execute("SELECT * FROM operation_jobs WHERE id=?", (jid,)).fetchone()
        if not row or row["status"] in ("running", "queued"):
            raise ValueError("只能重试已结束任务")
    return submit(row["operation"], json.loads(row["payload"]))


def read_log(jid):
    with connect() as db:
        if not db.execute("SELECT 1 FROM operation_jobs WHERE id=?", (jid,)).fetchone():
            raise ValueError("任务不存在")
    p = DATA / "logs" / "jobs" / f"{jid}.log"
    if not p.exists():
        return ""
    with p.open("rb") as f:
        f.seek(max(0, p.stat().st_size - 32000))
        return f.read().decode(errors="replace")
