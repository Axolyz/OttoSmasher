from .workspace import CODE_ROOT
from ottosmasher.inference_runtime import onnx_session

"""Offline FCPE + PC-NSF-HiFiGAN adapter; no inference at retrieval time."""

import json
import math

import numpy as np

from .workspace import DATA, ROOT, identity, write_json


def model_info():
    return json.loads((CODE_ROOT / "dependencies/flatten-model.json").read_text())


def nearest_note(f0, confidence, valid):
    mask = np.asarray(valid, dtype=bool) & np.isfinite(f0) & (np.asarray(f0) > 0)
    if mask.sum() < 3:
        raise ValueError("可靠 F0 不足，无法自动确定目标音高")
    pitch = 69 + 12 * np.log2(np.asarray(f0)[mask] / 440)
    weight = np.maximum(np.asarray(confidence)[mask], 1e-6)
    order = np.argsort(pitch)
    pitch = pitch[order]
    weight = weight[order]
    median = float(pitch[np.searchsorted(np.cumsum(weight), weight.sum() / 2)])
    midi = math.floor(median + 0.5)
    hz = 440 * 2 ** ((midi - 69) / 12)
    names = ("C", "C♯", "D", "D♯", "E", "F", "F♯", "G", "G♯", "A", "A♯", "B")
    return {
        "midi": midi,
        "hz": hz,
        "name": names[midi % 12] + str(midi // 12 - 1),
        "original_midi": median,
        "shift_semitones": midi - median,
    }


def flatten(path, mode="vowels", intervals=None):
    import librosa
    import onnxruntime as ort
    import soundfile as sf

    from .materials import sha256
    from .sound_features import FCPE
    from .sound_features import model_info as fcpe_info

    if mode not in ("vowels", "all"):
        raise ValueError("请选择仅元音或整个选段")
    if mode == "vowels" and not intervals:
        raise ValueError("仅元音模式需要可靠音素范围")
    y, sr = sf.read(path, dtype="float32", always_2d=True)
    model = FCPE()
    frames = model.infer(y.mean(axis=1), sr)

    def in_region(t):
        return (
            np.ones(len(t), dtype=bool)
            if mode == "all"
            else np.array([any(a <= x < b for a, b in intervals) for x in t])
        )

    valid = np.asarray(frames["voiced"]) & in_region(np.asarray(frames["times"]))
    note = nearest_note(np.array(frames["f0_hz"]), np.array(frames["confidence"]), valid)
    info = model_info()
    weights = ROOT / info["path"]
    config = ROOT / info["config"]
    if sha256(weights) != info["sha256"] or sha256(config) != info["config_sha256"]:
        raise ValueError("重合成模型指纹改变")
    cfg = json.loads(config.read_text())
    rate = cfg["sampling_rate"]
    hop = cfg["hop_size"]
    nfft = cfg["n_fft"]
    win = cfg["win_size"]
    count = round(len(y) * rate / sr)
    padded_count = max(count, hop * 4)
    fb = librosa.filters.mel(sr=rate, n_fft=nfft, n_mels=cfg["num_mels"], fmin=cfg["fmin"], fmax=cfg["fmax"])
    options = ort.SessionOptions()
    options.intra_op_num_threads = 2
    session = onnx_session(weights, options)
    out = np.zeros_like(y)
    for channel in range(y.shape[1]):
        mono = np.interp(np.arange(count) * sr / rate, np.arange(len(y)), y[:, channel]).astype(np.float32)
        mono = np.pad(mono, (0, padded_count - count))
        pad = (win - hop) // 2
        padded = np.pad(mono, (pad, pad), mode="reflect" if len(mono) > 1 else "edge")
        slices = np.lib.stride_tricks.sliding_window_view(padded, win)[::hop]
        mag = np.abs(np.fft.rfft(slices * np.hanning(win), n=nfft, axis=1)).astype(np.float32)
        mel = np.log(np.maximum(fb @ mag.T, 1e-9)).astype(np.float32)
        times = (np.arange(len(slices)) * hop + hop / 2) / rate
        fi = np.clip(np.round((times - 0.005) / 0.01).astype(int), 0, len(frames["times"]) - 1)
        voiced = np.asarray(frames["voiced"])[fi]
        f0 = np.asarray(frames["f0_hz"], dtype=np.float32)[fi]
        f0[voiced & in_region(times)] = note["hz"]
        f0[~voiced] = 0
        audio = session.run(None, {"mel": mel[None], "f0": f0[None]})[0].reshape(-1)
        out[:, channel] = np.interp(np.arange(len(y)) * rate / sr, np.arange(len(audio)), audio)
    # The untouched consonant samples are copied directly, without resampling them.
    mask = in_region(np.arange(len(y)) / sr).astype(np.float32)
    if mode == "vowels":
        fade = max(1, round(0.003 * sr))
        for a, b in intervals:
            first = max(0, round(a * sr))
            last = min(len(y), round(b * sr))
            n = min(fade, max(0, (last - first) // 4))
            if n:
                mask[first : first + n] *= np.linspace(0, 1, n)
                mask[last - n : last] *= np.linspace(1, 0, n)
    out = out * mask[:, None] + y * (1 - mask[:, None])
    key = identity("flatten-v1", sha256(path), info, mode, intervals, note)
    target = DATA / "media/flattened" / (key + ".wav")
    target.parent.mkdir(parents=True, exist_ok=True)
    if not target.exists():
        sf.write(target, out, sr, subtype="FLOAT")
    write_json(target.with_suffix(".features.json"), model.infer(out.mean(axis=1), sr))
    result = {
        "path": str(target),
        "sha256": sha256(target),
        "start": 0,
        "end": len(out) / sr,
        "audio_stream": 0,
        "role": "flattened",
        "target_note": note,
        "provenance": {
            "operation": "flatten",
            "model": info,
            "fcpe": fcpe_info(),
            "mode": mode,
            "intervals": intervals,
            "source_path": str(path),
            "source_sha256": sha256(path),
        },
    }
    write_json(target.with_suffix(".json"), result)
    return result
