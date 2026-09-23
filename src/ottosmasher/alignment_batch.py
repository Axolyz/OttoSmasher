from .workspace import CODE_ROOT
"""One worker/model lifetime per requested backend; incremental durable item results."""

import json
import subprocess
import time
import uuid
from pathlib import Path

from .workspace import DATA, ROOT, connect, get_cue, get_speech_analysis, write_json


def run(material_ids, backends, vocal_model, update=lambda rows: None, switch_backend=None):
    from .alignment_results import import_result
    from .alignment_runner import worker_command
    from .backends import BACKENDS
    from .job_worker import python_env
    from .materials import get
    from .sample_analysis import prepare as project
    from .sample_audio import pcm, resolve
    from .source_preparation import selected_materials
    from .source_vocals import clip, ensure

    if not backends or any(b not in BACKENDS for b in backends):
        raise ValueError("未知对齐模型")
    folder = DATA / "alignment/batches" / uuid.uuid4().hex
    rows, items, full_by_source, failed_sources, records = [], [], {}, {}, {}
    with connect() as db:
        allowed = set(selected_materials(db, material_ids=material_ids))
    for mid in dict.fromkeys(material_ids):
        row = {"material_id": mid, "status": "preparing", "stages": {}}
        rows.append(row)
        try:
            with connect() as db:
                r = get(db, mid)
                row["title"] = r["title"]
                if mid not in allowed:
                    row["status"] = "excluded"
                    continue
                if not r["cue_id"]:
                    raise ValueError("没有台词文本，不能强制对齐")
                if r.get("derivation"):
                    # Existing parent measurements can be projected without altering derived audio.
                    projected = project(db, mid)
                    if all(projected.get(b, {}).get("status") == "ready" for b in backends):
                        if switch_backend:
                            db.execute(
                                "UPDATE materials SET active_phone_backend=? WHERE id=?",
                                (switch_backend, mid),
                            )
                        row.update(
                            status="ready", stages={b: {"status": "ready", "reused": True} for b in backends}
                        )
                        continue
                    raise ValueError("派生采样缺少可投影的原片分析；请先对原台词补齐该模型，绑定音源未改变")
                stored = db.execute(
                    "SELECT payload FROM sample_assets WHERE material_id=?", (mid,)
                ).fetchone()
                bound = json.loads(stored[0]) if stored else None
                cue = {**get_cue(db, r["cue_id"]), "audio_stream": r["audio_stream"]}
                from .source_regions import sql_allowed

                context = [
                    dict(x)
                    for x in db.execute(
                        "SELECT id,spoken,start,end FROM cues c WHERE source_id=? AND end>? AND start<? AND "
                        + sql_allowed("c")
                        + " ORDER BY start",
                        (r["source_id"], cue["start"] - 0.8, cue["end"] + 0.8),
                    )
                ]
            item_model = vocal_model
            if switch_backend and bound:
                item_model = bound.get("provenance", {}).get("model", vocal_model)
            key = (r["source_id"], r["audio_stream"], item_model)
            if key in failed_sources:
                raise ValueError(failed_sources[key])
            if key not in full_by_source:
                started = time.monotonic()
                try:
                    full_by_source[key] = ensure(cue, item_model)
                except Exception as e:
                    failed_sources[key] = str(e)
                    raise
                print(f"Stage whole-source vocals {key}: {time.monotonic() - started:.2f}s", flush=True)
            full = full_by_source[key]
            if (
                switch_backend
                and bound
                and (
                    bound.get("sha256") != full["sha256"]
                    or abs(bound["start"] - r["start"]) > 1e-6
                    or abs(bound["end"] - r["end"]) > 1e-6
                )
            ):
                raise ValueError("绑定音源不是该整轨人声，不能用另一音源补齐分析；原选择与音源均保留")
            with connect() as db:
                if not (switch_backend and bound):
                    db.execute(
                        "INSERT OR REPLACE INTO sample_assets VALUES(?,?)",
                        (
                            mid,
                            json.dumps(
                                {
                                    **full,
                                    "start": r["start"],
                                    "end": r["end"],
                                    "root_knots": [[0, r["start"]], [r["end"] - r["start"], r["end"]]],
                                }
                            ),
                        ),
                    )
                for backend in backends:
                    a = get_speech_analysis(db, cue["id"], backend)
                    reusable = bool(
                        a
                        and a.get("phones")
                        and not a.get("error")
                        and a.get("audio_lineage", {}).get("full_source_asset", {}).get("sha256")
                        == full["sha256"]
                    )
                    row["stages"][backend] = {
                        "status": "ready" if reusable else "pending",
                        "reused": reusable,
                    }
            item = {
                "id": cue["id"],
                "source_id": cue["source_id"],
                "audio_stream": r["audio_stream"],
                "retained": False,
                "selection_tags": [],
                "context": context,
            }
            records[mid] = {**item, "full_asset": full, "vocal_model": item_model, "cue": cue}
            if any(x["status"] == "pending" for x in row["stages"].values()):
                items.append(records[mid])
            row["status"] = "running"
        except Exception as e:  # noqa: BLE001 - persist item failure without aborting the batch
            row.update(status="failed", error=str(e))
        finally:
            update(rows)
    # Preparation operates only on selected, missing inputs, after full sources are available.
    write_json(folder / "manifest.json", {"cues": items, "count": len(items), "backends": backends})
    if items:
        started = time.monotonic()
        from .workspace import command, executable

        for item in items:
            try:
                context = item["context"]
                cue = {**item["cue"], "start": context[0]["start"], "end": context[-1]["end"]}
                lineage = clip(cue, item["full_asset"], item["vocal_model"])
                entry = {
                    **item,
                    "audio_lineage": lineage,
                    "input_variant": "vocals",
                    "source_fingerprint": cue["fingerprint"],
                    "window_start": lineage["window_start"],
                    "window_end": lineage["window_end"],
                }
                for sr in (16000, 44100):
                    wav = folder / "inputs" / f"{item['id']}-{sr}.wav"
                    wav.parent.mkdir(parents=True, exist_ok=True)
                    command(
                        [
                            executable("ffmpeg"),
                            "-v",
                            "error",
                            "-y",
                            "-i",
                            lineage["audio_path"],
                            "-ac",
                            "1",
                            "-ar",
                            sr,
                            "-c:a",
                            "pcm_s16le",
                            wav,
                        ]
                    )
                    entry[f"wav_{sr}"] = str(wav)
                write_json(folder / "inputs" / (item["id"] + ".json"), entry)
            except Exception as e:  # noqa: BLE001 - persist item failure without aborting the batch
                for row in rows:
                    if records.get(row["material_id"], {}).get("id") == item["id"]:
                        row.update(status="failed", error=str(e))
                update(rows)
        print(f"Stage prepare inputs: {time.monotonic() - started:.2f}s", flush=True)
    for backend in backends:
        pending = [
            r for r in rows if r["status"] == "running" and r["stages"][backend]["status"] == "pending"
        ]
        if not pending:
            continue
        work = folder / backend / "batch"
        write_json(work / "manifest.json", {"cues": [records[r["material_id"]] for r in pending]})
        work.mkdir(parents=True, exist_ok=True)
        (work / "inputs").symlink_to((folder / "inputs").resolve(), target_is_directory=True)
        imported = set()

        def ingest(pending=pending, work=work, backend=backend, imported=imported):
            for row in pending:
                mid = row["material_id"]
                cid = records[mid]["id"]
                output = work / backend / cid / "result.json"
                if mid in imported or not output.exists():
                    continue
                try:
                    started = time.monotonic()
                    item = json.loads((folder / "inputs" / (cid + ".json")).read_text())
                    value = import_result(work, item, backend, json.loads(output.read_text()))
                    row["stages"][backend] = (
                        {"status": "failed", "error": value["error"]}
                        if value.get("error")
                        else {"status": "ready"}
                    )
                    with connect() as db:
                        db.execute(
                            "DELETE FROM sample_measurements WHERE material_id=? AND backend=?",
                            (mid, backend),
                        )
                    print(f"Stage import {backend} {mid}: {time.monotonic() - started:.3f}s", flush=True)
                except Exception as e:  # noqa: BLE001 - persist item failure without aborting the batch
                    row["stages"][backend] = {"status": "failed", "error": str(e)}
                imported.add(mid)
                update(rows)

        started = time.monotonic()
        try:
            # Inherits the enclosing operation's process group; cancellation never touches another task.
            process = subprocess.Popen(
                worker_command(work, backend, len(pending), True, exclude_regions=False),
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
            )
            for line in process.stdout:
                print(line, end="", flush=True)
                ingest()
            code = process.wait()
            ingest()
            if code:
                print(f"{backend} worker exit {code}", flush=True)
        except Exception as e:  # noqa: BLE001 - persist item failure without aborting the batch
            print(f"{backend} worker failed: {e}", flush=True)
        for row in pending:
            if row["material_id"] not in imported:
                row["stages"][backend] = {"status": "failed", "error": "模型没有生成结果，请查看任务日志"}
        print(f"Stage batch {backend}: {time.monotonic() - started:.2f}s", flush=True)
        update(rows)
    feature_items = []
    for row in rows:
        if row["status"] != "running":
            continue
        try:
            with connect() as db:
                path = pcm(resolve(db, row["material_id"]))
            feature_items.append({"material_id": row["material_id"], "path": str(path)})
        except Exception as e:  # noqa: BLE001 - persist item failure without aborting the batch
            row["stages"]["features"] = {"status": "failed", "error": str(e)}
    if feature_items:
        manifest = folder / "features.json"
        write_json(manifest, feature_items)
        subprocess.run(
            [
                python_env("features"),
                str(CODE_ROOT / "scripts/sample_features_worker.py"),
                "--batch",
                str(manifest),
            ],
            check=False,
        )
    for row in rows:
        if row["status"] != "running":
            continue
        mid = row["material_id"]
        started = time.monotonic()
        try:
            item = next(x for x in feature_items if x["material_id"] == mid)
            if not Path(item["path"]).with_suffix(".features.json").exists():
                raise ValueError("音高特征提取失败，请查看日志")
            with connect() as db:
                db.execute("DELETE FROM sample_records WHERE material_id=?", (mid,))
                projections = project(db, mid)
                row["stages"]["projections"] = projections
                if (
                    switch_backend
                    and row["stages"].get(switch_backend, {}).get("status") == "ready"
                    and projections.get(switch_backend, {}).get("status") == "ready"
                ):
                    db.execute(
                        "UPDATE materials SET active_phone_backend=? WHERE id=?", (switch_backend, mid)
                    )
            row["status"] = (
                "failed" if any(v.get("status") == "failed" for v in row["stages"].values()) else "ready"
            )
        except Exception as e:  # noqa: BLE001 - persist item failure without aborting the batch
            row.update(status="failed", error=str(e))
        print(f"Stage projections/index {mid}: {time.monotonic() - started:.2f}s", flush=True)
        update(rows)
    write_json(folder / "status.json", rows)
    return rows
