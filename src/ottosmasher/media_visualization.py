"""Bounded display data, independent of acoustic analysis and library registration."""

import json
import math
import re
import subprocess

import numpy as np
from scipy.signal import stft

from .workspace import DATA, executable, identity, write_json


def register(spec):
    key = identity("display-source-v1", spec)
    write_json(DATA / "cache" / "visualizations" / (key + ".json"), spec)
    return key


def checked(key):
    if not re.fullmatch(r"[a-f0-9]{24}", key):
        raise ValueError("无效显示数据标识")
    return DATA / "cache" / "visualizations" / (key + ".json")


def detail(key, start, end):
    from .media_operations import source_spec

    spec = json.loads(checked(key).read_text())
    duration = spec["end"] - spec["start"]
    sr = spec["sample_rate"]
    # Presentation clocks may differ by less than one PCM frame. Larger errors remain errors.
    if not all(math.isfinite(x) for x in (start, end)) or not -1 / sr < start < end < duration + 1 / sr:
        raise ValueError("频谱范围越界")
    first, last = round(spec["start"] * sr), round(spec["end"] * sr)
    start = max(0, min(last - first, round(start * sr))) / sr
    end = max(0, min(last - first, round(end * sr))) / sr
    if end <= start:
        raise ValueError("频谱范围不足一个采样帧")
    if end - start > 30.001:
        raise ValueError("详细频谱每次最多 30 秒；整片播放不受限制")
    current = source_spec(spec["path"], spec["start"], spec["end"], spec["audio_stream"])
    if current["fingerprint"] != spec["fingerprint"]:
        raise ValueError("音源已经改变，请重新加载波形")
    out_key = identity("spectrum-display-v3", key, start, end)
    target = DATA / "cache" / "visualizations" / (out_key + ".spectrum.json")
    if not target.exists():
        # Decode ONLY this window. Never perform FFT on reduced waveform peaks.
        sr = 48000
        raw = subprocess.run(
            [
                executable("ffmpeg"),
                "-v",
                "error",
                "-nostdin",
                "-ss",
                str(first / spec["sample_rate"] + start),
                "-t",
                str(end - start),
                "-i",
                spec["path"],
                "-map",
                f"0:{spec['audio_stream']}",
                "-vn",
                "-ac",
                "1",
                "-ar",
                str(sr),
                "-f",
                "f32le",
                "pipe:1",
            ],
            capture_output=True,
            check=True,
        ).stdout
        y = np.frombuffer(raw, dtype="<f4")
        if not len(y):
            raise ValueError("选区没有可读取的声音")
        nfft = 2048
        if len(y) < nfft:
            y = np.pad(y, (0, nfft - len(y)))
        hop = max(512, math.ceil(len(y) / 1200))
        # 30 seconds at 48 kHz keeps hop below the FFT length.
        _, _, z = stft(y, fs=sr, nperseg=nfft, noverlap=nfft - hop, boundary="zeros")
        db = 20 * np.log10(np.maximum(np.abs(z[:-1]), 1e-12))
        values = np.rint(np.clip((db + 90) / 90, 0, 1) * 255).astype("uint8")
        write_json(target, [values.T.tolist()])
    return {
        "key": out_key,
        "start": start,
        "end": end,
        "sample_rate": 48000,
        "fft_samples": 2048,
        "range_db": 90,
        "url": f"/api/helper/visualizations/{out_key}/spectrum",
    }


def spectrum_path(key):
    return checked(key).with_suffix(".spectrum.json")
