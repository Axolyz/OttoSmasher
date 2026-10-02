"""One persistent full-source separation, shared by all production phone tasks."""

import json
import os
from functools import lru_cache
from pathlib import Path

import soundfile as sf

from .workspace import DATA, connect, identity, write_json


@lru_cache(maxsize=64)
def _digest(path, size, modified):
    from .materials import sha256

    return sha256(path)


def valid(asset, duration):
    path = Path(asset.get("path", ""))
    if not path.is_file() or abs(sf.info(path).duration - duration) >= 0.02:
        return False
    stat = path.stat()
    if _digest(str(path), stat.st_size, stat.st_mtime_ns) != asset["sha256"]:
        raise ValueError("整轨人声文件已改变，不能复用其来源记录")
    return True


def ensure(cue, model="becruily_deux"):
    from filelock import FileLock

    from .job_worker import run
    from .sample_ops import source_browser
    from .vocals import model_identity

    key = identity("whole-source-vocals-v1", cue["fingerprint"], cue["audio_stream"], model_identity(model))
    folder = DATA / "media/source-vocals" / key
    folder.mkdir(parents=True, exist_ok=True)
    manifest = folder / "source.json"
    with FileLock(str(folder / "prepare.lock")):
        print(f"Whole-source vocals {cue['source_id']}: waiting/reusing {model}", flush=True)
        if manifest.exists():
            a = json.loads(manifest.read_text())
            if valid(a, cue["source_duration"]):
                return a
        with connect() as db:
            r = source_browser(db, cue["source_id"])
            # Also reuse a previous successful full-source GUI separation.
            for row in db.execute(
                "SELECT payload FROM shared_sample_audio WHERE source_id=?", (cue["source_id"],)
            ):
                a = json.loads(row[0])
                p = a.get("provenance", {})
                k = a.get("root_knots", [])
                if (
                    a.get("role") == "vocals"
                    and p.get("model") == model
                    and p.get("source_audio_stream") == cue["audio_stream"]
                    and p.get("source_fingerprint") == cue["fingerprint"]
                    and k
                    and k[0][1] == 0
                    and k[-1][1] >= cue["source_duration"] - 0.01
                    and Path(a.get("path", "")).is_file()
                    and p.get("model_fingerprints") == model_identity(model)
                    and valid(a, cue["source_duration"])
                ):
                    write_json(manifest, a)
                    return a
        print(
            f"Full-source separation starts: {cue['source_duration']:.2f}s; phone alignment waits for this track",
            flush=True,
        )
        from .asset_timeline import AssetSelection, selection_asset
        from .selection_ops import from_source

        with connect() as db:
            selected = from_source(db, r["id"], 0, cue["source_duration"], "raw", cue["audio_stream"])
            input_asset = selection_asset(db, selected)
        completed = run(
            "separate",
            {
                "selection": selected.json(),
                "input_asset": input_asset,
                "source_id": cue["source_id"],
                "suggested_title": cue.get("title", "原片人声"),
                "model": model,
                "save": False,
            },
            os.environ.get("OTTO_JOB_ID") or "source-" + key,
        )
        with connect() as db:
            for output in completed.get("assets", []):
                if "vocal" not in output["stem"].lower() and output["stem"].lower() not in (
                    "dialog",
                    "dialogue",
                ):
                    continue
                a = selection_asset(db, AssetSelection(**output["selection"]))
                a.update(
                    role="vocals",
                    speech_analysis_eligible=True,
                    provenance={
                        **a.get("provenance", {}),
                        "model": model,
                        "model_fingerprints": model_identity(model),
                        "source_id": cue["source_id"],
                        "source_audio_stream": cue["audio_stream"],
                        "source_fingerprint": cue["fingerprint"],
                    },
                )
                if valid(a, cue["source_duration"]):
                    db.execute(
                        "INSERT OR REPLACE INTO shared_sample_audio VALUES(?,?,?)",
                        (key, cue["source_id"], json.dumps(a)),
                    )
                    write_json(manifest, a)
                    return a
        raise RuntimeError("Whole-source separation produced no registered vocals")


def clip(cue, asset, model):
    from .media import window
    from .vocals import model_identity

    start, end = window(cue)
    first, last = max(0, start - 3), min(cue["source_duration"], end + 3)
    key = identity("whole-vocal-clip-v1", asset["sha256"], start, end, first, last)
    # A crop is a view of the persistent track, never a second audio owner.
    folder = DATA / "vocals" / key
    folder.mkdir(parents=True, exist_ok=True)
    manifest = folder / "manifest.json"
    audio = Path(asset["path"])
    result = {
        "id": key,
        "cue_id": cue["id"],
        "input_variant": "vocals",
        "model": model,
        "model_hashes": model_identity(model),
        "stem": "vocals",
        "source_fingerprint": cue["fingerprint"],
        "source_path": cue["path"],
        "audio_stream": cue["audio_stream"],
        "window_start": start,
        "window_end": end,
        "context_start": 0,
        "context_end": cue["source_duration"],
        "folder": str(folder),
        "audio_path": str(audio),
        "audio_sha256": asset["sha256"],
        "audio_start": start,
        "audio_end": end,
        "separated_context": asset["path"],
        "full_source_asset": asset,
        "verified": False,
        "version": "whole-vocal-clip-v1",
    }
    write_json(manifest, result)
    return result
