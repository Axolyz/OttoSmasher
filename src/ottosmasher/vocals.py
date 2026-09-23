"""Versioned stereo separation before any production speech analysis."""

from __future__ import annotations
from .workspace import CODE_ROOT

import hashlib
import json
from functools import lru_cache
from pathlib import Path

import soundfile as sf

from .inference_runtime import python_path
from .media import window
from .workspace import DATA, ROOT, command, connect, executable, identity, set_job, write_json

MODEL_NAME = "becruily_deux"
VOCAL_MODELS = (MODEL_NAME, "bs_roformer_voc_hyperacev2")
STEM = "vocals"


@lru_cache(maxsize=4)
def model_identity(model_name=MODEL_NAME):
    if model_name not in VOCAL_MODELS:
        raise ValueError("Unsupported vocal separation model")
    paths = sorted((ROOT / "models/separation").rglob(model_name + ".*"))
    if not {".ckpt", ".yaml"}.issubset({p.suffix for p in paths}):
        raise RuntimeError("Missing configured pymss model/config; run the separation setup first")
    return {str(p.relative_to(ROOT)): hashlib.sha256(p.read_bytes()).hexdigest() for p in paths}


def register_reference(cue, lineage):
    """Publish completed separation immediately, independently of phone alignment."""
    from .materials import sha256

    full = Path(
        lineage.get("separated_context") or Path(lineage.get("folder", "")) / "stems/context_vocals.wav"
    )
    context = full.is_file()
    if not context:
        full = Path(lineage["audio_path"])
    first = lineage.get("context_start", lineage["window_start"]) if context else lineage["window_start"]
    last = lineage.get("context_end", lineage["window_end"]) if context else lineage["window_end"]
    paths = [("vocals", full)]
    residual = full.parent / "context_instrument.wav"
    if context and residual.is_file():
        paths.append(("residual", residual))
    with connect() as db:
        db.execute(
            "CREATE TABLE IF NOT EXISTS shared_sample_audio(id TEXT PRIMARY KEY,source_id TEXT,payload TEXT)"
        )
        for role, path in paths:
            info = sf.info(path)
            if abs(info.duration - (last - first)) > 0.01:
                raise ValueError("分离参考音轨时长与原片范围不一致")
            key = identity("vocal-reference-v1", cue["source_id"], lineage["id"], role)
            if db.execute("SELECT 1 FROM shared_sample_audio WHERE id=?", (key,)).fetchone():
                continue
            asset = {
                "path": str(path),
                "sha256": sha256(path),
                "start": 0,
                "end": last - first,
                "sample_rate": info.samplerate,
                "channels": info.channels,
                "audio_stream": 0,
                "role": role,
                "root_knots": [[0, first], [last - first, last]],
                "provenance": {
                    "source_id": cue["source_id"],
                    "source_fingerprint": cue["fingerprint"],
                    "source_audio_stream": cue["audio_stream"],
                    "model": lineage["model"],
                    "lineage": lineage,
                },
            }
            db.execute(
                "INSERT INTO shared_sample_audio VALUES(?,?,?)", (key, cue["source_id"], json.dumps(asset))
            )
        db.commit()


def prepare_vocals(cues, session=None, model_name=MODEL_NAME, full_source=False):
    """Separate padded stereo clips as one model session, then crop for alignment.

    Failure never falls back to the mixed track. The extra three seconds are
    separation context, not extra transcript passed to the forced aligner.
    """
    if full_source:
        from .source_vocals import clip, ensure

        return {c["id"]: clip(c, ensure(c, model_name), model_name) for c in cues}
    model = model_identity(model_name)
    entries = []
    for cue in cues:
        start, end = window(cue)
        context_start, context_end = max(0, start - 3), min(cue["source_duration"], end + 3)
        key = identity(
            cue["fingerprint"],
            cue["audio_stream"],
            start,
            end,
            context_start,
            context_end,
            model,
            STEM,
            "pymss-stereo-context-v1",
        )
        folder = DATA / "vocals" / key
        manifest_path = folder / "manifest.json"
        cached = json.loads(manifest_path.read_text()) if manifest_path.exists() else None
        if cached and Path(cached["audio_path"]).is_file():
            digest = hashlib.sha256(Path(cached["audio_path"]).read_bytes()).hexdigest()
            if digest != cached["audio_sha256"]:
                raise RuntimeError(f"Cached vocals changed: {folder}")
            register_reference(cue, cached)
            entries.append(cached)
            continue
        folder.mkdir(parents=True, exist_ok=True)
        raw = folder / "context.wav"
        command(
            [
                executable("ffmpeg"),
                "-v",
                "error",
                "-nostdin",
                "-y",
                "-ss",
                str(context_start),
                "-t",
                str(context_end - context_start),
                "-i",
                cue["path"],
                "-map",
                f"0:{cue['audio_stream']}",
                "-vn",
                "-ar",
                "44100",
                "-ac",
                "2",
                "-c:a",
                "pcm_s24le",
                raw,
            ]
        )
        entry = {
            "id": key,
            "cue_id": cue["id"],
            "input_variant": "vocals",
            "model": model_name,
            "model_hashes": model,
            "stem": STEM,
            "source_fingerprint": cue["fingerprint"],
            "audio_stream": cue["audio_stream"],
            "source_path": cue["path"],
            "window_start": start,
            "window_end": end,
            "context_start": context_start,
            "context_end": context_end,
            "input_path": str(raw),
            "input_sha256": hashlib.sha256(raw.read_bytes()).hexdigest(),
            "folder": str(folder),
            "audio_path": str(folder / "vocals.wav"),
            "verified": False,
            "device": "auto",
            "version": "pymss-stereo-context-v1",
        }
        entries.append(entry)
    pending = [e for e in entries if "audio_sha256" not in e]
    if pending:
        batch = DATA / "vocals" / ("batch-" + identity([e["id"] for e in pending]))
        write_json(batch / "request.json", {"entries": pending})
        db = connect()
        for e in pending:
            set_job(db, e["id"], e["cue_id"], "pymss-vocals", "running")
        try:
            result = (
                session.run(batch / "request.json")
                if session
                else command(
                    [
                        python_path(),
                        CODE_ROOT / "scripts/vocals_worker.py",
                        batch / "request.json",
                    ],
                    timeout=7200,
                )
            )
            (batch / "run.log").write_text(result.stdout + "\n" + result.stderr)
            for e in pending:
                # The pinned worker selects the stem explicitly and records its output.
                separated = Path(e["folder"]) / "stems" / "context_vocals.wav"
                before, after = sf.info(e["input_path"]), sf.info(separated)
                if abs(before.duration - after.duration) > 0.01:
                    raise RuntimeError(
                        f"Separation changed duration for {e['cue_id']}; no automatic time correction"
                    )
                command(
                    [
                        executable("ffmpeg"),
                        "-v",
                        "error",
                        "-nostdin",
                        "-y",
                        "-ss",
                        str(e["window_start"] - e["context_start"]),
                        "-t",
                        str(e["window_end"] - e["window_start"]),
                        "-i",
                        separated,
                        "-ar",
                        "48000",
                        "-c:a",
                        "pcm_s24le",
                        e["audio_path"],
                    ]
                )
                e["audio_sha256"] = hashlib.sha256(Path(e["audio_path"]).read_bytes()).hexdigest()
                e["separated_context"] = str(separated)
                e["duration_error_seconds"] = after.duration - before.duration
                write_json(Path(e["folder"]) / "manifest.json", e)
                owner = next(c for c in cues if c["id"] == e["cue_id"])
                register_reference(owner, e)
                set_job(db, e["id"], e["cue_id"], "pymss-vocals", "done")
        except Exception as exc:
            for e in pending:
                if "audio_sha256" not in e:
                    set_job(db, e["id"], e["cue_id"], "pymss-vocals", "failed", str(exc))
            raise
        finally:
            db.close()
    # Adjacent target cues can share exactly the same contextual audio asset.
    # A cached manifest's first requesting cue must not determine the batch keys.
    return {cue["id"]: {**e, "cue_id": cue["id"]} for cue, e in zip(cues, entries)}


def read_aligned_input(item):
    if item.get("input_variant") != "vocals":
        raise ValueError("Speech analysis requires a recorded vocals input; raw mix is diagnostic only")
    lineage = item["audio_lineage"]
    if any(abs(item[key] - lineage[key]) > 0.001 for key in ("window_start", "window_end")):
        raise ValueError("Alignment window does not match vocals provenance")
    path = Path(lineage["audio_path"])
    if not path.is_file():
        raise ValueError("Separated vocals file is missing; rerun preprocessing")
    if hashlib.sha256(path.read_bytes()).hexdigest() != lineage["audio_sha256"]:
        raise ValueError("Vocals asset no longer matches alignment provenance")
    y, sr = sf.read(path, dtype="float32", always_2d=True)
    return y.mean(axis=1), sr, item["window_start"], item["window_end"]


class PersistentVocals:
    """A single owned pymss process for a resumable corpus job."""

    def __init__(self):
        import subprocess

        DATA.mkdir(exist_ok=True)
        self.log = (DATA / "speaker-separation.log").open("a")
        self.process = subprocess.Popen(
            [python_path(), CODE_ROOT / "scripts/vocals_worker.py", "--server"],
            stdin=subprocess.PIPE,
            stdout=self.log,
            stderr=self.log,
            text=True,
        )

    def run(self, request):
        import time
        from types import SimpleNamespace

        result = request.with_suffix(".result.json")
        result.unlink(missing_ok=True)
        self.process.stdin.write(str(request) + "\n")
        self.process.stdin.flush()
        deadline = time.monotonic() + 7200
        while not result.exists():
            if self.process.poll() is not None:
                raise RuntimeError("Persistent separation worker stopped; see speaker-separation.log")
            if time.monotonic() > deadline:
                raise RuntimeError("Separation timed out")
            time.sleep(0.1)
        value = json.loads(result.read_text())
        if not value["ok"]:
            raise RuntimeError(value["error"])
        return SimpleNamespace(stdout="Persistent pymss session; see data/speaker-separation.log", stderr="")

    def close(self):
        if self.process.poll() is None:
            self.process.stdin.close()
            try:
                self.process.wait(timeout=15)
            except Exception:  # noqa: BLE001 - worker must report adapter failures
                self.process.terminate()
                self.process.wait(timeout=15)
        self.log.close()
