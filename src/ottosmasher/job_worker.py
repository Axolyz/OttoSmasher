import json
import os
import sys
import time
from pathlib import Path

from .workspace import DATA, connect, identity, write_json


def python_env(name):
    from .inference_runtime import python_path

    if name in ("separation", "features", "narabas", "hubert", "pydomino"):
        name = "onnx"
    p = python_path(name)
    if not p.is_file():
        raise ValueError(f"缺少项目环境：{name}")
    return str(p)


def run(operation, p, jid):
    from .editions import require_operation

    require_operation(operation, p)
    if p.get("runtime"):
        os.environ["OTTO_INFERENCE_SETTINGS"] = json.dumps(p["runtime"])
    from . import materials as m
    from . import media_operations as media

    if operation == "speech-prepare":
        from . import preparation_jobs

        return preparation_jobs.run(p, jid)

    if operation == "opening-scan":
        from .opening_scan import run as scan

        with connect() as db:
            return scan(db, p, jid)

    if operation == "source-separation":
        from .source_separation import run as run_sound

        with connect() as db:
            return run_sound(db, p, jid)

    if operation == "acoustic-features":
        from .timbre_features import analyze

        with connect() as db:
            return analyze(db, {"material_ids": p["material_ids"]})
    if operation == "native-alignment":
        from .native_alignment import run as align_native

        return align_native(p, jid)
    if operation == "sample-features":
        from .sample_ops import refresh_features

        with connect() as db:
            return refresh_features(db, p["material_id"], p.get("role", "selected"))
    if operation == "sample-phones":
        from .sample_inference import analyze

        return analyze(
            p["material_id"], p.get("retry", False), p.get("backends"), p.get("vocal_model", "becruily_deux")
        )
    if operation == "force-fa":
        from .reanalysis import run as force_fa
        return force_fa(p, jid)
    if operation == "pitch-index":
        from .pitch_indexing import run as index_pitch
        with connect() as db:
            return index_pitch(db,p,jid)
    if operation == 'flatten' and p.get('selection'):
        from .selection_ops import flatten
        return flatten(p,jid)
    if operation == "flatten":
        from .sample_ops import flatten

        with connect() as db:
            return flatten(
                db,
                p["material_id"],
                **{k: p[k] for k in ("mode", "batch_id", "start", "end", "role", "input_asset", "target", "inner", "transition", "title", "pitch_strategy", "boundary_side") if k in p},
            )
    if operation == "sample-prepare":
        from .sample_analysis import prepare

        results = {}
        with connect() as db:
            for i, mid in enumerate(p["material_ids"]):
                results[mid] = prepare(db, mid)
                print(f"Derived rhythm {i + 1}/{len(p['material_ids'])} {mid}", flush=True)
        return results
    if operation == "index":
        from .rhythm_index import rebuild_index

        with connect() as db:
            return rebuild_index(db, p.get("kind", "narabas"))
    if operation == "cut":
        return media.cut(**{k: v for k, v in p.items() if k not in {"runtime", "edition_context"}})
    if operation == "separate":
        if p.get('selection'):
            from .selection_ops import separate
            return separate(p,jid)
        if p.get('material_id'):
            raise ValueError('旧分离任务没有固定声音资产，请从当前选区重新提交')
        # Standalone CLI file processing has no source identity to bind.
        from .separation import separate
        source = str(Path(p['path']).expanduser().resolve(strict=True))
        output = Path(p.get('output') or DATA / 'media' / 'processed' / jid).resolve()
        output.mkdir(parents=True, exist_ok=True)
        from .inference_runtime import settings
        outputs = separate(p.get('model','becruily_deux'),[source],output,p.get('stems'),p.get('device') or settings()['inference_device'])[0]
        return {'outputs':outputs}
    raise ValueError("未知处理操作")


def main(jid):
    os.environ["OTTO_JOB_ID"] = jid
    # Separate model and lightweight lanes; admission remains transactional.
    while True:
        with connect() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute("SELECT * FROM operation_jobs WHERE id=?", (jid,)).fetchone()
            if not row or row["status"] == "cancelled":
                return
            others = db.execute(
                "SELECT pid,operation FROM operation_jobs WHERE status='running' AND id<>?", (jid,)
            ).fetchall()
            from .operation_jobs import resource_lane
            from .ui_catalog import settings

            lane = resource_lane(row["operation"])
            limit = settings(db)["model_concurrency" if lane == "model" else "utility_concurrency"]
            active = 0
            for other in others:
                try:
                    os.kill(other[0], 0)
                    active += resource_lane(other["operation"]) == lane
                except (ProcessLookupError, TypeError):
                    pass
            if active < limit:
                db.execute(
                    "UPDATE operation_jobs SET status='running',pid=?,updated=? WHERE id=?",
                    (os.getpid(), time.time(), jid),
                )
                break
        time.sleep(0.5)
    try:
        result = run(row["operation"], json.loads(row["payload"]), jid)
        status, error = "succeeded", None
    except Exception as exc:  # noqa: BLE001 - Persist failures at the process boundary.
        import traceback

        traceback.print_exc()
        result = None
        status, error = "failed", str(exc)
    with connect() as db:
        db.execute(
            "UPDATE operation_jobs SET status=?,result=?,error=?,updated=? WHERE id=? AND status<>'cancelled'",
            (status, json.dumps(result, ensure_ascii=False), error, time.time(), jid),
        )
    # Durable replacements have committed; generated masters are no longer owners.
    from .audio_storage import retire_encoded_outputs, trim_pcm
    with connect() as db:
        retire_encoded_outputs(db)
    trim_pcm()


if __name__ == "__main__":
    if sys.argv[1] == "--flatten":
        jid = sys.argv[2]
        with connect() as db:
            payload = json.loads(
                db.execute("SELECT payload FROM operation_jobs WHERE id=?", (jid,)).fetchone()[0]
            )
        result = run("flatten", payload, jid)
        write_json(DATA / "jobs" / f"{jid}-flatten.json", result)
    else:
        main(sys.argv[1])
