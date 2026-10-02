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
    "force-fa",
    "pitch-index",
    "flatten",
    "sample-prepare",
    "separate",
    "subtitles",
    "index",
    "cut",
}


def resource_lane(operation):
    return "utility" if operation in {"cut", "sample-prepare", "index", "opening-scan"} else "model"


def submit(operation, payload):
    from .cache_storage import maintenance_lock
    from .editions import transition_lock

    with transition_lock(), maintenance_lock():
        return _submit(operation, payload)


def _submit(operation, payload):
    from .editions import identity as edition_identity
    from .editions import require_operation

    require_operation(operation, payload)
    context_file = DATA / "edition-context.json"
    if context_file.exists() and json.loads(context_file.read_text()) != edition_identity():
        raise ValueError("当前工作区运行另一版本；请先从启动器切换版本")
    if operation not in OPERATIONS:
        raise ValueError("未知操作")
    from .inference_runtime import settings as runtime_settings

    payload = {
        **payload,
        "edition_context": edition_identity(),
        "runtime": payload.get("runtime") or runtime_settings(),
    }
    jid = uuid.uuid4().hex
    with connect() as db:
        if (operation == 'separate' and (payload.get('selection') or payload.get('material_id'))) or (operation=='flatten' and payload.get('selection')):
            from .selection_ops import separation_snapshot
            payload = separation_snapshot(db,payload)
            if operation == 'flatten' and (payload.get('pitch_strategy') is not None or payload.get('mode') == 'from_first_vowel'):
                from .flatten_pitch import VERSION
                payload['flatten_algorithm'] = VERSION
            if operation == 'flatten' and payload.get('expected_asset') is not None:
                if payload['expected_asset'] != payload['input_asset']:
                    raise ValueError('声音资产已改变，请重新打开拉平弹窗')
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


def listing(summary=False):
    with connect() as db:
        fields = "*" if not summary else """id,operation,status,error,updated,created,pid,payload,
            CASE WHEN result IS NULL THEN NULL ELSE json_object(
              'type',json_extract(result,'$.type'),'completed',json_extract(result,'$.completed'),
              'total',json_extract(result,'$.total'),'stage_revision',json_extract(result,'$.stage_revision'),
              'material_id',json_extract(result,'$.material_id'),'sample_id',json_extract(result,'$.sample.id')
            ) END result"""
        rows = [dict(r) for r in db.execute(f"SELECT {fields} FROM operation_jobs ORDER BY created DESC LIMIT 200")]
        for r in rows:
            if r["status"] in ("running", "queued") and r["pid"]:
                try:
                    import psutil

                    if not psutil.pid_exists(r["pid"]):
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
            payload=r['payload']; mids=set(payload.get('material_ids',[]) or [])
            if payload.get('material_id'):mids.add(payload['material_id'])
            for item in payload.get('inputs',[]) or []:
                if isinstance(item,dict) and item.get('material_id'):mids.add(item['material_id'])
            sources=set(payload.get('source_ids',[]) or [])
            if payload.get('source_id'):sources.add(payload['source_id'])
            if mids:
                sources.update(x[0] for x in db.execute('SELECT DISTINCT source_id FROM materials WHERE id IN ('+','.join('?' for _ in mids)+')',tuple(mids)))
            selection=payload.get('selection') or {}
            if selection.get('asset_id'):
                sources.update(x[0] for x in db.execute('SELECT source_id FROM sound_assets WHERE id=?',(selection['asset_id'],)))
            r['affected']={'sample_ids':sorted(mids),'source_ids':sorted(sources)}
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
                    subprocess.run(
                        ["taskkill", "/PID", str(row["pid"]), "/T", "/F"], check=False, capture_output=True
                    )
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
