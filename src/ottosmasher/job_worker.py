from .workspace import CODE_ROOT
import json
import os
import subprocess
import sys
import time
from pathlib import Path

from .workspace import DATA, ROOT, connect, identity, write_json


def python_env(name):
    from .inference_runtime import python_path
    if name in ("separation", "features", "narabas", "hubert", "pydomino"):
        name = "inference"
    p = python_path(name)
    if not p.is_file():
        raise ValueError(f"缺少项目环境：{name}")
    return str(p)


def run(operation, p, jid):
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
    if operation == "flatten":
        from .sample_ops import flatten

        with connect() as db:
            return flatten(
                db,
                p["material_id"],
                **{k: p[k] for k in ("mode", "batch_id", "start", "end", "role", "input_asset") if k in p},
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
        return media.cut(**p)
    if operation == "separate":
        write_json(
            DATA / "jobs" / f"{jid}-progress.json",
            {"stage": "preparing_audio", "message": "正在读取原片音轨及载入分离模型", "updated": time.time()},
        )
        from . import sample_audio, sample_catalog

        with connect() as db:
            if p.get("material_id"):
                r = m.get(db, p["material_id"])
                start = float(p.get("start", r["start"]))
                end = float(p.get("end", r["end"]))
                context_start = max(0, start - 2)
                context_end = min(r["source_duration"], end + 2)
                asset = sample_audio.resolve_range(
                    db, r, context_start, context_end, "raw", p.get("audio_stream")
                )
                source = str(sample_audio.pcm(asset))
            else:
                source = str(Path(p["path"]).expanduser().resolve(strict=True))
        output = Path(p.get("output") or DATA / "media" / "processed" / jid).resolve()
        output.mkdir(parents=True, exist_ok=True)
        req = {
            "path": source,
            "output": str(output),
            "model": p.get("model", "becruily_deux"),
            "device": p.get("device", "auto"),
            "stems": p.get("stems"),
            "progress_path": str(DATA / "jobs" / f"{jid}-progress.json"),
        }
        request = DATA / "jobs" / f"{jid}-separate.json"
        write_json(request, req)
        subprocess.run(
            [python_env("separation"), str(CODE_ROOT / "scripts/material_separate_worker.py"), str(request)],
            check=True,
        )
        result = json.loads(request.with_suffix(".result.json").read_text())
        if p.get("material_id"):
            with connect() as db:
                result["samples"] = []
                for x in result["outputs"]:
                    import soundfile as sf

                    info = sf.info(x["path"])
                    role = "vocals" if x["stem"].lower() == "vocals" else "residual"
                    a = {
                        "path": x["path"],
                        "sha256": m.sha256(x["path"]),
                        "start": 0,
                        "end": info.duration,
                        "sample_rate": info.samplerate,
                        "channels": info.channels,
                        "audio_stream": 0,
                        "role": role,
                        "root_knots": [[0, context_start], [info.duration, context_end]],
                        "provenance": {
                            **x,
                            "source_id": r["source_id"],
                            "raw_input": asset,
                            "model": req["model"],
                            "source_audio_stream": asset["audio_stream"],
                            "source_fingerprint": r["fingerprint"],
                        },
                    }
                    db.execute(
                        "INSERT OR REPLACE INTO shared_sample_audio VALUES(?,?,?)",
                        (identity(a), r["source_id"], json.dumps(a)),
                    )
                    if p.get("save", False):
                        # Explicit save creates a child; background separation remains a shared asset.
                        a = {
                            **a,
                            "start": start - context_start,
                            "end": end - context_start,
                            "root_knots": [[0, start], [end - start, end]],
                        }
                        input_audio = sample_audio.resolve_range(db, r, start, end, "raw")
                        result["samples"].append(
                            sample_catalog.derive(
                                db,
                                r["id"],
                                operation="separation",
                                asset=a,
                                input_asset=input_audio,
                                folder_id=p.get("folder_id", "inbox"),
                                parameters={"model": x["model"], "stem": x["stem"]},
                            )["id"]
                        )
                db.commit()
        return result
    if operation == "subtitles":
        script = "preprocess_subtitles.py"
        env = "core"
        args = [p.get("operation", "all")]
        if p.get("source_id"):
            args += ["--source-id", p["source_id"]]
    else:
        raise ValueError("未知处理操作")
    subprocess.run([python_env(env), str(CODE_ROOT / "scripts" / script), *args], check=True)
    return {"script": script, "arguments": args, "completed": True}


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
