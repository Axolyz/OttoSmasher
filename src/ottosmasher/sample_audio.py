"""Resolve selected audio without silently substituting original mix."""

import json
from pathlib import Path

from .workspace import DATA, get_speech_analysis, identity


def resolve(db, mid, role=None, range_row=None):
    from .audio_sources import separated_source
    from .materials import get

    r = range_row or get(db, mid)
    stored = db.execute("SELECT payload FROM sample_assets WHERE material_id=?", (mid,)).fetchone()
    if stored and range_row is None and role in (None, "selected"):
        a = json.loads(stored[0])
        if a.get("path") and not Path(a["path"]).is_file():
            raise ValueError("绑定的音频文件缺失")
        return a
    role = (None if role == "selected" else role) or ("vocals" if r["cue_id"] else "raw")
    if role.startswith("artifact:"):
        from .sound_tracks import resolve as resolve_track

        return resolve_track(db, role.removeprefix("artifact:"), r["source_id"], r["start"], r["end"])
    if role == "raw":
        return {
            "path": r["path"],
            "start": r["start"],
            "end": r["end"],
            "audio_stream": r["audio_stream"],
            "sha256": r["fingerprint"],
            "role": "raw",
            "root_knots": [[0, r["start"]], [r["end"] - r["start"], r["end"]]],
            "provenance": {"source_id": r["source_id"]},
        }
    if role not in ("vocals", "residual"):
        raise ValueError("未知音源")
    candidates = []
    if r["cue_id"]:
        for kind in (r["active_phone_backend"], "narabas", "phonetic", "pydomino"):
            a = get_speech_analysis(db, r["cue_id"], kind)
            if a and a.get("audio_lineage"):
                candidates.append(a["audio_lineage"])
    for row in db.execute(
        "SELECT payload FROM sample_assets UNION ALL SELECT payload FROM shared_sample_audio"
    ):
        a = json.loads(row[0])
        p = a.get("provenance", {})
        if a.get("role") == role and p.get("source_id") == r["source_id"]:
            raw = p.get("raw_input", {})
            recorded_stream = p.get("source_audio_stream", raw.get("audio_stream"))
            if recorded_stream is not None and recorded_stream != r["audio_stream"]:
                continue
            if (
                p.get("source_fingerprint", r["fingerprint"]) != r["fingerprint"]
                or not Path(a.get("path", "")).is_file()
            ):
                continue
            k = a.get("root_knots")
            if k and k[0][1] <= r["start"] and k[-1][1] >= r["end"]:
                return {
                    **a,
                    "start": a["start"] + r["start"] - k[0][1],
                    "end": a["start"] + r["end"] - k[0][1],
                    "root_knots": [[0, r["start"]], [r["end"] - r["start"], r["end"]]],
                }
    for lineage in candidates:
        parent = separated_source(lineage)
        if parent.get("audio_stream", r["audio_stream"]) != r["audio_stream"]:
            continue
        if parent.get("source_fingerprint", r["fingerprint"]) != r["fingerprint"]:
            continue
        full = parent.get("separated_context") or str(
            Path(parent.get("folder", "")) / "stems/context_vocals.wav"
        )
        if Path(full).is_file():
            path = full
            origin = parent.get("context_start", parent["window_start"])
            stop = parent.get("context_end", parent["window_end"])
        else:
            path = parent["audio_path"]
            origin = parent["window_start"]
            stop = parent["window_end"]
        if not (origin - 1e-6 <= r["start"] < r["end"] <= stop + 1e-6):
            continue
        if role == "residual":
            folder = Path(path).parent
            other = folder / "context_instrument.wav"
            if other.is_file():
                path = str(other)
            else:
                # Persisted residual recipe; materialize only at explicit audition/preparation.
                return {
                    "residual_of": {
                        "path": path,
                        "start": r["start"] - origin,
                        "end": r["end"] - origin,
                        "audio_stream": 0,
                    },
                    "raw": resolve(db, mid, "raw", range_row=r),
                    "role": "residual",
                    "start": 0,
                    "end": r["end"] - r["start"],
                    "sha256": identity(lineage, "residual"),
                    "root_knots": [[0, r["start"]], [r["end"] - r["start"], r["end"]]],
                    "provenance": {"method": "mix-minus-pymss-vocals", "lineage": lineage},
                }
        return {
            "path": path,
            "start": max(0, r["start"] - origin),
            "end": r["end"] - origin,
            "audio_stream": 0,
            "sha256": parent.get("audio_sha256"),
            "role": role,
            "root_knots": [[0, r["start"]], [r["end"] - r["start"], r["end"]]],
            "provenance": {"source_id": r["source_id"], "lineage": lineage},
        }
    raise ValueError("所选范围缺少完整分离音源；请先生成分离结果，不回退原混音")


def pcm(asset):
    import math

    import numpy as np
    import soundfile as sf
    from scipy.signal import resample_poly

    from .media_operations import cut

    key = identity("sample-pcm-v1", asset)
    path = DATA / "sample-cache" / f"{key}.wav"
    if not path.exists():
        path.parent.mkdir(parents=True, exist_ok=True)
        if "residual_of" in asset:
            v, sr = sf.read(pcm(asset["residual_of"]), always_2d=True, dtype="float32")
            raw, rr = sf.read(pcm(asset["raw"]), always_2d=True, dtype="float32")
            if sr != rr:
                g = math.gcd(sr, rr)
                raw = resample_poly(raw, sr // g, rr // g, axis=0)
            if len(raw) < len(v):
                raw = np.pad(raw, ((0, len(v) - len(raw)), (0, 0)))
            residual = raw[: len(v)] - v
            first = round(asset.get("start", 0) * sr)
            last = round(asset.get("end", len(residual) / sr) * sr)
            sf.write(path, residual[first:last], sr, subtype="FLOAT")
        elif Path(asset["path"]).suffix.lower() == ".wav" and asset.get("audio_stream", 0) == 0:
            # Prepared stems are seekable PCM; avoid spawning FFmpeg for every short event.
            info = sf.info(asset["path"])
            first = round(asset["start"] * info.samplerate)
            last = round(asset["end"] * info.samplerate)
            if not 0 <= first < last <= info.frames + 1:
                raise ValueError("音频选区越界")
            y, sr = sf.read(
                asset["path"], start=first, stop=min(last, info.frames), always_2d=True, dtype="float32"
            )
            sf.write(path, y, sr, subtype="FLOAT")
        else:
            cut(asset["path"], asset["start"], asset["end"], asset.get("audio_stream", 0), output=path)
    return path


def resolve_range(db, row, start, end, role, audio_stream=None):
    if not 0 <= start < end <= row["source_duration"]:
        raise ValueError("原片选区越界")
    return resolve(
        db,
        row["id"],
        role,
        range_row={
            **row,
            "start": start,
            "end": end,
            "audio_stream": row["audio_stream"] if audio_stream is None else audio_stream,
        },
    )
