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
        run(
            "separate",
            {
                "material_id": r["id"],
                "start": 0,
                "end": cue["source_duration"],
                "audio_stream": cue["audio_stream"],
                "model": model,
                "output": str(folder),
                "save": False,
            },
            os.environ.get("OTTO_JOB_ID") or "source-" + key,
        )
        with connect() as db:
            for row in db.execute(
                "SELECT payload FROM shared_sample_audio WHERE source_id=?", (cue["source_id"],)
            ):
                a = json.loads(row[0])
                if (
                    a["role"] == "vocals"
                    and Path(a.get("path", "")).is_relative_to(folder)
                    and valid(a, cue["source_duration"])
                ):
                    write_json(manifest, a)
                    print("Full-source vocals published; alignment can now start", flush=True)
                    return a
        raise RuntimeError("Whole-source separation produced no registered vocals")


def clip(cue, asset, model):
    from .materials import sha256
    from .media import window
    from .vocals import model_identity
    from .workspace import command, executable

    start, end = window(cue)
    first, last = max(0, start - 3), min(cue["source_duration"], end + 3)
    key = identity("whole-vocal-clip-v1", asset["sha256"], start, end, first, last)
    folder = DATA / "vocals" / key
    manifest = folder / "manifest.json"
    if manifest.exists():
        result = json.loads(manifest.read_text())
        if Path(result["audio_path"]).exists():
            return {**result, "cue_id": cue["id"]}
    folder.mkdir(parents=True, exist_ok=True)
    audio = folder / "vocals.wav"
    command(
        [
            executable("ffmpeg"),
            "-v",
            "error",
            "-nostdin",
            "-y",
            "-ss",
            str(start),
            "-t",
            str(end - start),
            "-i",
            asset["path"],
            "-ar",
            "48000",
            "-c:a",
            "pcm_s24le",
            audio,
        ]
    )
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
        "audio_sha256": sha256(audio),
        "separated_context": asset["path"],
        "full_source_asset": asset,
        "verified": False,
        "version": "whole-vocal-clip-v1",
    }
    write_json(manifest, result)
    return result
