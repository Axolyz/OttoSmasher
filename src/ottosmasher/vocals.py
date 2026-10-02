"""Versioned stereo separation before any production speech analysis."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import soundfile as sf

from .media import window
from .workspace import DATA, command, connect, executable, identity, set_job, write_json

MODEL_NAME = "becruily_deux"
STEM = "vocals"


def model_identity(model_name=MODEL_NAME):
    from .separation import model_identity as identify

    return identify(model_name)


class VocalModels:
    def __iter__(self):
        from .separation import model_names

        return iter(model_names())

    def __contains__(self, name):
        from .separation import adapter

        backend = adapter()
        return any(
            (name == m["name"] or name in m.get("aliases", []))
            and "vocals" in [s.lower() for s in backend.stems(m)]
            for m in backend.models()
        )


VOCAL_MODELS = VocalModels()


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
            import shutil

            from .separation import separate

            results = separate(model_name, [e["input_path"] for e in pending], batch / "stems", ["vocals"])
            for entry, outputs in zip(pending, results):
                produced = next(x for x in outputs if x["stem"].lower() == "vocals")
                target = Path(entry["folder"]) / "stems/context_vocals.wav"
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(produced["path"], target)
                entry["provider"] = produced["provider"]
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
    from .audio_storage import lineage_audio, read
    y, sr = read(*lineage_audio(lineage))
    return y.mean(axis=1), sr, item["window_start"], item["window_end"]


class PersistentVocals:
    """Compatibility context; batches use the Studio worker's shared model lifetime."""

    def close(self):
        pass
