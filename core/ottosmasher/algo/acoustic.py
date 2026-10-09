"""单音 · 音色 / 单音 · 瞬态：采样整体的声学指标（规格 10 §10.3，16 R16）。纯函数 + numpy。

【基线参数】包络 5 ms RMS；有效范围 = 包络 ≥ 峰值 1%；频谱 40 ms 窗、1/4 步长（10 ms）；低频 20–200 Hz、中频 200–4000 Hz、高频 ≥ 4000 Hz；
分起音 / 主体 / 尾部三段；音高类用**采样自己的 F0 测量**（可靠帧：有声 且 F0 > 0 且 置信度 ≥ 0.5），不依赖对齐（修正 A16）。
规格没写细的定义（开发者决定，QUESTIONS「阶段 7」）：
- 有效范围 = 第一个到最后一个 ≥ 峰值 1% 的包络格；起音上升 = 首次到 10% → 首次到 90%（峰值之前）；尾部衰减 = 峰值后首次跌破 90% → 首次跌破 10%；
- 峰均比 = 20·log10(峰值样本绝对值 / 有效范围 RMS)（dB）；RMS（dB）= 20·log10(有效范围 RMS)；
- 频谱：有效范围内各帧功率谱相加（Hann 窗）；占比的分母 = ≥ 20 Hz 的总能量；谱质心（Hz）；谱平坦度 = 几何均值 / 算术均值（≥ 20 Hz 的箱，越接近 1 越像噪声）；
  三段：起音 = [有效起点, 峰值]、尾部 = [峰后跌破 10% 处, 有效终点]、主体 = 中间；某段不足一个窗时该段为未知；
- 原始音高 = 可靠帧 MIDI 中位数（≥ 3 帧）；音高波动 = P90 − P10（半音）；可靠发声时长 = 可靠帧数 × 10 ms；
- 谐波：可靠 F0 的频谱帧上，|f − k·F0| ≤ max(2 个频率箱, 3% × k·F0) 的箱算第 k 次谐波（k·F0 < 奈奎斯特）；
  谐波能量占比 = 谐波能量 / 这些帧 ≥ 20 Hz 的总能量；5 次以上高阶谐波占比 = k ≥ 5 的谐波能量 / 全部谐波能量。
- 静音（峰值为 0 或有效范围不足一个包络格）→ 全部未知；没有可靠 F0 → 音高类（原始音高、波动、谐波两项）未知，可靠发声时长 = 0。
"""

from __future__ import annotations

import math
from typing import Any

import numpy as np

ALGO_VERSION = "acoustic-1"
ENV_SECONDS = 0.005
EFFECTIVE_RATIO = 0.01
WIN_SECONDS = 0.04
HOP_DIV = 4
BANDS = {"low": (20.0, 200.0), "mid": (200.0, 4000.0), "high": (4000.0, math.inf)}
MIN_HZ = 20.0
HARMONIC_BINS = 2.0
HARMONIC_REL = 0.03
HIGH_HARMONIC = 5
MIN_PITCH_FRAMES = 3
F0_HOP = 0.01

TIMBRE = ("effectiveDuration", "pitch", "pitchSpread", "voicedDuration", "highHarmonicRatio", "harmonicRatio", "highRatio")
TRANSIENT = ("effectiveDuration", "attackTime", "decayTime", "crestDb", "lowRatio", "highRatio", "flatness")
ALL = (
    "effectiveDuration", "attackTime", "decayTime", "crestDb", "rmsDb", "lowRatio", "midRatio", "highRatio", "centroid", "flatness",
    "pitch", "pitchSpread", "voicedDuration", "harmonicRatio", "highHarmonicRatio",
    "attackLowRatio", "attackHighRatio", "attackCentroid", "attackFlatness", "bodyLowRatio", "bodyHighRatio", "bodyCentroid", "bodyFlatness",
    "tailLowRatio", "tailHighRatio", "tailCentroid", "tailFlatness",
)
# 单位（界面悬停显示定义与单位）
UNITS = {
    "effectiveDuration": "s", "attackTime": "ms", "decayTime": "ms", "crestDb": "dB", "rmsDb": "dB", "centroid": "Hz", "pitch": "MIDI",
    "pitchSpread": "semitone", "voicedDuration": "s", "attackCentroid": "Hz", "bodyCentroid": "Hz", "tailCentroid": "Hz",
}


def _envelope(x: np.ndarray, sr: int) -> np.ndarray:
    n = max(1, int(round(ENV_SECONDS * sr)))
    m = len(x) // n
    if m == 0:
        return np.zeros(0)
    return np.sqrt(np.mean(np.square(x[: m * n].reshape(m, n)), axis=1))


def _spectra(x: np.ndarray, sr: int) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """（帧中心秒, 频率, 功率谱 [帧, 箱]）。"""
    n = int(round(WIN_SECONDS * sr))
    hop = max(1, n // HOP_DIV)
    if len(x) < n:
        return np.zeros(0), np.fft.rfftfreq(n, 1 / sr), np.zeros((0, n // 2 + 1))
    k = 1 + (len(x) - n) // hop
    idx = np.arange(n)[None, :] + hop * np.arange(k)[:, None]
    win = np.hanning(n)
    spec = np.abs(np.fft.rfft(x[idx] * win, axis=1)) ** 2
    return (np.arange(k) * hop + n / 2) / sr, np.fft.rfftfreq(n, 1 / sr), spec


def _shape(freqs: np.ndarray, power: np.ndarray) -> dict[str, float | None]:
    sel = freqs >= MIN_HZ
    p = power[sel]
    f = freqs[sel]
    total = float(p.sum())
    if total <= 0:
        return {"low": None, "mid": None, "high": None, "centroid": None, "flatness": None}
    out: dict[str, float | None] = {}
    for name, (a, b) in BANDS.items():
        out[name] = float(p[(f >= a) & (f < b)].sum()) / total
    out["centroid"] = float((f * p).sum() / total)
    pp = np.maximum(p, 1e-30)
    out["flatness"] = float(np.exp(np.mean(np.log(pp))) / np.mean(pp))
    return out


def metrics(pcm: np.ndarray, sr: int, f0: np.ndarray, conf: np.ndarray, energy: np.ndarray, measured: np.ndarray, f0_start: float = 0.0) -> dict[str, float | None]:
    """``pcm``：采样范围的音频（单声道或 [帧, 声道]）；F0 帧的第 i 帧中心 = ``f0_start`` + (i × 160 + 80) / 16000 秒（相对 ``pcm`` 第一个样本）。
    音高类只看落在采样范围里的 F0 帧。未知 = None。"""
    from .flatten import hz_to_midi, reliable

    x = np.asarray(pcm, dtype=np.float64)
    if x.ndim == 2:
        x = x.mean(axis=1)
    out: dict[str, float | None] = {k: None for k in ALL}
    env = _envelope(x, sr)
    peak_env = float(env.max()) if len(env) else 0.0
    if peak_env <= 0:
        return out
    above = np.flatnonzero(env >= EFFECTIVE_RATIO * peak_env)
    a, b = int(above[0]), int(above[-1]) + 1
    step = ENV_SECONDS
    t0, t1 = a * step, b * step
    if b - a < 1:
        return out
    out["effectiveDuration"] = t1 - t0
    p = int(np.argmax(env))
    lvl = env / peak_env
    first10 = next((i for i in range(a, p + 1) if lvl[i] >= 0.1), p)
    first90 = next((i for i in range(a, p + 1) if lvl[i] >= 0.9), p)
    out["attackTime"] = max(0, first90 - first10) * step * 1000.0
    below90 = next((i for i in range(p, b) if lvl[i] < 0.9), b)
    below10 = next((i for i in range(p, b) if lvl[i] < 0.1), b)
    out["decayTime"] = max(0, below10 - below90) * step * 1000.0
    seg = x[int(round(t0 * sr)) : int(round(t1 * sr))]
    rms = float(np.sqrt(np.mean(np.square(seg)))) if len(seg) else 0.0
    if rms > 0:
        out["crestDb"] = 20 * math.log10(float(np.max(np.abs(seg))) / rms)
        out["rmsDb"] = 20 * math.log10(rms)
    times, freqs, spec = _spectra(seg, sr)
    if len(spec):
        whole = _shape(freqs, spec.sum(axis=0))
        out["lowRatio"], out["midRatio"], out["highRatio"] = whole["low"], whole["mid"], whole["high"]
        out["centroid"], out["flatness"] = whole["centroid"], whole["flatness"]
        tp = (p * step) - t0
        tt = (below10 * step) - t0
        for name, lo, hi in (("attack", 0.0, tp), ("body", tp, tt), ("tail", tt, t1 - t0)):
            sel = (times >= lo) & (times < hi)
            if sel.any():
                sh = _shape(freqs, spec[sel].sum(axis=0))
                out[f"{name}LowRatio"], out[f"{name}HighRatio"] = sh["low"], sh["high"]
                out[f"{name}Centroid"], out[f"{name}Flatness"] = sh["centroid"], sh["flatness"]
    # 音高类：采样自己的 F0（可靠帧）
    f0 = np.asarray(f0, dtype=np.float64)
    centers = f0_start + (np.arange(len(f0)) * 160 + 80) / 16000.0
    inside = (centers >= 0) & (centers < len(x) / sr)
    f0, conf, energy, measured = f0[inside], np.asarray(conf)[inside], np.asarray(energy)[inside], np.asarray(measured, dtype=bool)[inside]
    centers = centers[inside]
    ok = np.asarray(measured, dtype=bool) & reliable(np.nan_to_num(f0), np.nan_to_num(np.asarray(conf, dtype=np.float64)), np.nan_to_num(np.asarray(energy, dtype=np.float64)))
    out["voicedDuration"] = float(ok.sum()) * F0_HOP if len(f0) and np.asarray(measured, dtype=bool).all() else None
    if ok.sum() >= MIN_PITCH_FRAMES:
        midi = np.array([hz_to_midi(float(v)) for v in f0[ok]])
        out["pitch"] = float(np.median(midi))
        out["pitchSpread"] = float(np.percentile(midi, 90) - np.percentile(midi, 10))
        if len(spec):
            harm = high = total = 0.0
            fr_t = centers - t0  # F0 帧中心（有效范围的时钟）
            bin_w = freqs[1] - freqs[0]
            sel = freqs >= MIN_HZ
            nyq = freqs[-1]
            for ti, row in zip(times, spec):
                j = int(np.argmin(np.abs(fr_t - ti)))
                if abs(fr_t[j] - ti) > F0_HOP / 2 + 1e-9 or not ok[j]:
                    continue
                hz = float(f0[j])
                total += float(row[sel].sum())
                k = 1
                while k * hz < nyq:
                    half = max(HARMONIC_BINS * bin_w, HARMONIC_REL * k * hz)
                    e = float(row[sel & (np.abs(freqs - k * hz) <= half)].sum())
                    harm += e
                    if k >= HIGH_HARMONIC:
                        high += e
                    k += 1
            if total > 0 and harm > 0:
                out["harmonicRatio"] = harm / total
                out["highHarmonicRatio"] = high / harm
    return out


def check_conditions(conds: Any, mode: str) -> list[tuple[str, float | None, float | None]]:
    """筛选条件：[{metric, min?, max?}]；指标名必须是已知的；min ≤ max。"""
    from ..core.errors import CoreError

    if mode not in ("timbre", "transient"):
        raise CoreError("search-invalid", field="mode")
    if not isinstance(conds, list):
        raise CoreError("search-invalid", field="conditions")
    out = []
    for c in conds:
        if not isinstance(c, dict) or c.get("metric") not in ALL:
            raise CoreError("search-invalid", field="metric")
        lo, hi = c.get("min"), c.get("max")
        for v in (lo, hi):
            if v is not None and (isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(float(v))):
                raise CoreError("search-invalid", field="metric")
        if lo is not None and hi is not None and lo > hi:
            raise CoreError("search-invalid", field="metric")
        if lo is None and hi is None:
            continue
        out.append((str(c["metric"]), None if lo is None else float(lo), None if hi is None else float(hi)))
    return out
