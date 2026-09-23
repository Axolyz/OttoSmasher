from .workspace import CODE_ROOT
from ottosmasher.inference_runtime import onnx_session

"""Versioned source-frame facts and model-dependent unit projections.

Only the offline worker imports ONNX Runtime. Retrieval never runs inference.
"""

import hashlib
import json
from functools import lru_cache
from pathlib import Path

import numpy as np

from .audio_sources import separated_source
from .workspace import DATA, ROOT, identity, write_json

VERSION = "fcpe-source-frames-v4"
PROJECTION_VERSION = "unit-prosody-v1"


def model_info():
    return json.loads((CODE_ROOT / "dependencies/features-models.json").read_text())["fcpe"]


def asset_id(lineage):
    lineage = separated_source(lineage)
    return identity(VERSION, lineage["audio_sha256"], model_info()["sha256"])


def asset_path(lineage):
    return DATA / "sound-features" / (asset_id(lineage) + ".json")


class FCPE:
    def __init__(self):
        import onnxruntime as ort

        model = model_info()
        path = ROOT / model["path"]
        if hashlib.sha256(path.read_bytes()).hexdigest() != model["sha256"]:
            raise ValueError("FCPE model fingerprint changed")
        options = ort.SessionOptions()
        options.intra_op_num_threads = 2
        self.session = onnx_session(path, options)

    def infer(self, y, sr):
        import librosa

        # Match the supplied HiFiShifter frontend's linear resampling and STFT.
        count = max(1, round(len(y) * 16000 / sr))
        mono = np.interp(np.arange(count) * sr / 16000, np.arange(len(y)), y).astype(np.float32)
        padded = np.pad(mono, (432, 432), mode="reflect" if len(mono) > 1 else "edge")
        if len(padded) < 1024:
            padded = np.pad(padded, (0, 1024 - len(padded)))
        frames = np.lib.stride_tricks.sliding_window_view(padded, 1024)[::160]
        magnitude = np.abs(np.fft.rfft(frames * np.hanning(1024), axis=1)).astype(np.float32)
        bank = librosa.filters.mel(sr=16000, n_fft=1024, n_mels=128, fmin=0, fmax=8000)
        mel = np.log(np.maximum(magnitude @ bank.T, 1e-9)).astype(np.float32)
        latent = self.session.run(None, {"mel": mel[None]})[0][0]
        centers = np.linspace(1200 * np.log2(32.7 / 10), 1200 * np.log2(1975.5 / 10), latent.shape[1])
        confidence = latent.max(axis=1)
        peaks = latent.argmax(axis=1)
        f0 = []
        for row, k in zip(latent, peaks):
            a, b = max(0, k - 4), min(len(row), k + 5)
            f0.append(float(10 * 2 ** (np.sum(row[a:b] * centers[a:b]) / max(1e-9, row[a:b].sum()) / 1200)))
        times = (np.arange(len(frames)) * 160 + 80) / 16000
        # Energy windows have the same centers, measured without inference normalization.
        energy = np.array(
            [
                np.mean(mono[i * 160 : min(len(mono), (i + 1) * 160)].astype(np.float64) ** 2)
                if i * 160 < len(mono)
                else 0.0
                for i in range(len(frames))
            ]
        )
        valid = (confidence > 0.05) & (energy > 1e-10)
        return {
            "times": times.tolist(),
            "f0_hz": f0,
            "confidence": confidence.tolist(),
            "voiced": valid.tolist(),
            "energy": energy.tolist(),
            "hop_seconds": 0.01,
            "frame_center_offset_seconds": 0.005,
        }


def build_asset(lineage, model):
    import soundfile as sf

    lineage = separated_source(lineage)

    path = asset_path(lineage)
    if path.exists():
        return json.loads(path.read_text())
    audio = Path(lineage["audio_path"])
    if (
        lineage.get("input_variant") not in (None, "vocals")
        or hashlib.sha256(audio.read_bytes()).hexdigest() != lineage["audio_sha256"]
    ):
        raise ValueError("Separated vocals lineage mismatch")
    y, sr = sf.read(audio, dtype="float32", always_2d=True)
    result = dict(
        version=VERSION,
        asset_id=asset_id(lineage),
        audio_sha256=lineage["audio_sha256"],
        input_variant="vocals",
        source_window_start=lineage["window_start"],
        source_window_end=lineage["window_end"],
        model=model_info(),
        **model.infer(y.mean(axis=1), sr),
    )
    write_json(path, result)
    return result


@lru_cache(maxsize=1024)
def read_asset(path, stamp):
    result = json.loads(Path(path).read_text())
    return {
        **result,
        **{k: np.asarray(result[k]) for k in ("times", "f0_hz", "confidence", "voiced", "energy")},
    }


def first_vowel(unit):
    labels = [m.get("phone", m.get("label")) for m in unit.get("members", [])]
    labels = labels or [unit.get("phone")]
    return next((str(p).lower() for p in labels if str(p).lower() in "aiueo" and len(str(p)) == 1), None)


def project(units, segments, frames, origin, pauses):
    """Use canonical segment membership, never the current search selection."""
    times = frames["times"] + origin
    voiced = frames["voiced"] & (frames["f0_hz"] > 0)
    pitch = np.full(len(times), np.nan)
    pitch[voiced] = 69 + 12 * np.log2(frames["f0_hz"][voiced] / 440)
    out = []
    for unit in units:
        start, end = unit["time"], unit.get("end", unit["time"])
        mask = (times >= start) & (times < end)
        values = pitch[mask & voiced]
        t = times[mask & voiced]
        trend = None
        if len(t) >= 5 and t[-1] - t[0] >= 0.06:
            span = t[-1] - t[0]
            trend = float(np.median(values[t >= t[-1] - span / 3]) - np.median(values[t <= t[0] + span / 3]))
        energy = (
            float(10 * np.log10(max(1e-12, float(np.mean(frames["energy"][mask]))))) if mask.any() else None
        )
        # Definite acoustic gaps truncate sustain; CTC blanks and unvoiced frames do not.
        sustain = end
        for gap in pauses:
            if start < gap["start"] < sustain:
                sustain = gap["start"]
        # Reject model coverage stretching far into quiet audio, preserve brief weak regions.
        active = mask & (frames["energy"] > max(1e-10, float(np.quantile(frames["energy"], 0.85)) * 0.0064))
        if active.any():
            sustain = min(sustain, float(times[np.flatnonzero(active)[-1]]) + 0.005)
        else:
            sustain = None
        out.append(
            {
                "first_vowel": first_vowel(unit),
                "pitch_midi": float(np.median(values)) if len(values) >= 3 else None,
                "pitch_trend_semitones": trend,
                "energy_db": energy,
                "sustain_end": sustain,
                "voiced_fraction": float(np.mean(voiced[mask])) if mask.any() else 0.0,
                "pitch_relative_semitones": None,
                "energy_relative_db": None,
            }
        )
    groups = segments or [{"parent_unit_indices": list(range(len(units)))}]
    for segment in groups:
        indices = segment.get("parent_unit_indices", list(range(len(units))))
        indices = [i for i in indices if i < len(units)]
        if not indices:
            continue
        a, b = units[indices[0]]["time"], units[indices[-1]]["end"]
        values = pitch[(times >= a) & (times < b) & voiced]
        base = float(np.median(values)) if len(values) >= 3 else None
        energies = [out[i]["energy_db"] for i in indices if out[i]["energy_db"] is not None]
        baseline = float(np.median(energies)) if energies else None
        for i in indices:
            f = out[i]
            if base is not None and f["pitch_midi"] is not None:
                f["pitch_relative_semitones"] = f["pitch_midi"] - base
            if baseline is not None and f["energy_db"] is not None:
                f["energy_relative_db"] = f["energy_db"] - baseline
    return out


@lru_cache(maxsize=1024)
def _project_cached(view_json, scopes_json, path, stamp, origin):
    key = identity(PROJECTION_VERSION, view_json, scopes_json, Path(path).stem, stamp, origin)
    cached = DATA / "unit-features" / (key + ".json")
    if cached.exists():
        return json.loads(cached.read_text())["units"]
    view = json.loads(view_json)
    units = project(view["units"], json.loads(scopes_json), read_asset(path, stamp), origin, view["pauses"])
    write_json(cached, {"version": PROJECTION_VERSION, "frame_asset": Path(path).stem, "units": units})
    return units


def record_features(record):
    whole = next((e for e in record["entries"] if e["scope"]["kind"] == "whole"), None)
    if not whole:
        return []
    lineage = separated_source(whole["analysis"]["audio_lineage"])
    path = asset_path(lineage)
    if not path.exists():
        return [{"first_vowel": first_vowel(u)} for u in whole["view"]["units"]]
    return _project_cached(
        json.dumps(whole["view"]),
        json.dumps([e["scope"] for e in record["entries"] if e["scope"]["kind"] == "segment"]),
        str(path),
        path.stat().st_mtime_ns,
        lineage["window_start"],
    )


def satisfies(features, note):
    get = lambda k, d=None: note.get(k, d) if isinstance(note, dict) else getattr(note, k, d)
    phone = get("phone")
    if phone and features.get("first_vowel") != phone:
        return False
    if get("speaker") and features.get("speaker") != get("speaker"):
        return False
    for setting, field, threshold in (
        ("pitch_trend", "pitch_trend_semitones", get("pitch_trend_min", 1)),
        ("pitch_register", "pitch_relative_semitones", get("pitch_register_min", 2)),
    ):
        direction = get(setting)
        if direction:
            value = features.get(field)
            if value is None or (value if direction in ("up", "high") else -value) < threshold:
                return False
    bound = get("energy_relative_min_db")
    return not (
        bound is not None
        and (features.get("energy_relative_db") is None or features["energy_relative_db"] < bound)
    )
