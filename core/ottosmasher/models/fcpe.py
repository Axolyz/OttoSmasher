"""FCPE 音高与能量帧（规格 14 §14.4、10 §10.1）：前端与 HiFiShifter 一致。

1. 各声道平均成单声道，线性插值重采样到 16 kHz（采样点数 = round(N × 16000 / sr)）；
2. 两侧各反射填充 432 点（太短时补零到至少 1024 点）；
3. 窗长 1024、步长 160、对称 Hann 窗（numpy ``hanning``），取幅度谱；
4. 乘以 Slaney 归一化的 mel 滤波器组（128 带、0–8000 Hz、n_fft 1024，等同 librosa 默认）后取 ``ln(max(x, 1e-9))``；
5. ONNX 输入 ``mel`` [1, T, 128]，输出 ``latent`` [1, T, 360]；
6. 解码：360 个 bin 的中心音分在 1200·log2(32.7/10) 到 1200·log2(1975.5/10) 之间线性分布；每帧 argmax 左右各 4 个 bin 按 latent 加权平均音分，
   F0 = 10 × 2^(音分/1200)；置信度 = 该帧 latent 最大值；
7. 帧时间 = (i × 160 + 80) / 16000 秒；能量 = 该 10 ms 内（重采样后）样本平方的均值；
8. 有声 = 置信度 > 0.05 且能量 > 1e-10；可靠帧 = 有声 且 F0 > 0 且 置信度 ≥ 0.5（使用方统一判定）。

长音频分段：每段 60 秒、两侧各 1 秒上下文（mel 是逐帧精确的，上下文只给模型用），结果拼回连续网格。
"""

from __future__ import annotations

from functools import lru_cache

import numpy as np

from .onnx import Session

SR = 16000
HOP = 160
WIN = 1024
PAD = 432
N_MELS = 128
BINS = 360
SEGMENT_FRAMES = 6000  # 60 秒
CONTEXT_FRAMES = 100  # 1 秒
VOICED_CONF = 0.05
RELIABLE_CONF = 0.5
ENERGY_FLOOR = 1e-10
MODEL_ID = "fcpe"
MODEL_FILE = "features/fcpe.onnx"
FRONTEND_VERSION = "fcpe-frontend-1"


def to_mono(audio: np.ndarray) -> np.ndarray:
    a = np.asarray(audio, dtype=np.float64)
    return a.mean(axis=1) if a.ndim == 2 else a


def resample_linear(x: np.ndarray, sr: int) -> np.ndarray:
    """线性插值重采样到 16 kHz：输出点 j 取原信号在 j × sr / 16000 处的线性插值。"""
    if sr == SR:
        return np.asarray(x, dtype=np.float64)
    n_out = round(len(x) * SR / sr)
    pos = np.arange(n_out, dtype=np.float64) * (sr / SR)
    return np.interp(pos, np.arange(len(x), dtype=np.float64), np.asarray(x, dtype=np.float64))


def _hz_to_mel(f: np.ndarray) -> np.ndarray:
    f = np.asarray(f, dtype=np.float64)
    f_sp = 200.0 / 3
    mels = f / f_sp
    min_log_hz = 1000.0
    min_log_mel = min_log_hz / f_sp
    logstep = np.log(6.4) / 27.0
    return np.where(f >= min_log_hz, min_log_mel + np.log(np.maximum(f, 1e-10) / min_log_hz) / logstep, mels)


def _mel_to_hz(m: np.ndarray) -> np.ndarray:
    m = np.asarray(m, dtype=np.float64)
    f_sp = 200.0 / 3
    freqs = f_sp * m
    min_log_hz = 1000.0
    min_log_mel = min_log_hz / f_sp
    logstep = np.log(6.4) / 27.0
    return np.where(m >= min_log_mel, min_log_hz * np.exp(logstep * (m - min_log_mel)), freqs)


@lru_cache(maxsize=1)
def mel_filters() -> np.ndarray:
    """librosa.filters.mel(sr=16000, n_fft=1024, n_mels=128, fmin=0, fmax=8000) 的同等实现（Slaney 刻度与归一化）。[128, 513]"""
    n_freq = WIN // 2 + 1
    fftfreqs = np.linspace(0, SR / 2, n_freq)
    mel_f = _mel_to_hz(np.linspace(_hz_to_mel(np.array(0.0)), _hz_to_mel(np.array(8000.0)), N_MELS + 2))
    fdiff = np.diff(mel_f)
    ramps = mel_f[:, None] - fftfreqs[None, :]
    weights = np.zeros((N_MELS, n_freq))
    for i in range(N_MELS):
        lower = -ramps[i] / fdiff[i]
        upper = ramps[i + 2] / fdiff[i + 1]
        weights[i] = np.maximum(0, np.minimum(lower, upper))
    enorm = 2.0 / (mel_f[2 : N_MELS + 2] - mel_f[:N_MELS])
    return weights * enorm[:, None]


def padded(x16: np.ndarray) -> np.ndarray:
    if len(x16) > PAD:
        p = np.pad(x16, (PAD, PAD), mode="reflect")
    else:
        p = np.pad(x16, (PAD, PAD))
    if len(p) < WIN:
        p = np.pad(p, (0, WIN - len(p)))
    return p


def frame_count(n16: int) -> int:
    return 1 + (max(n16 + 2 * PAD, WIN) - WIN) // HOP


def log_mel(p: np.ndarray, f0: int, f1: int) -> np.ndarray:
    """帧 [f0, f1) 的 log-mel [T, 128]（``p`` = 填充后的整段信号）。"""
    win = np.hanning(WIN)
    frames = np.lib.stride_tricks.sliding_window_view(p, WIN)[::HOP][f0:f1]
    mag = np.abs(np.fft.rfft(frames * win, axis=1))
    mel = mag @ mel_filters().T
    return np.log(np.maximum(mel, 1e-9)).astype(np.float32)


@lru_cache(maxsize=1)
def cents_table() -> np.ndarray:
    return np.linspace(1200 * np.log2(32.7 / 10), 1200 * np.log2(1975.5 / 10), BINS)


def decode(latent: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """latent [T, 360] → (F0 Hz, 置信度)。"""
    cents = cents_table()
    idx = np.argmax(latent, axis=1)
    conf = latent[np.arange(len(latent)), idx]
    f0 = np.empty(len(latent))
    for t, i in enumerate(idx):
        a, b = max(0, i - 4), min(BINS, i + 5)
        w = latent[t, a:b].astype(np.float64)
        s = float(w.sum())
        c = float((w * cents[a:b]).sum() / s) if s != 0 else 0.0
        f0[t] = 10.0 * 2 ** (c / 1200)
    return f0, conf.astype(np.float64)


def energy(x16: np.ndarray, frames: int) -> np.ndarray:
    out = np.zeros(frames)
    for i in range(frames):
        seg = x16[i * HOP : i * HOP + HOP]
        out[i] = float(np.mean(np.square(seg))) if len(seg) else 0.0
    return out


def measure(session: Session, audio: np.ndarray, sr: int) -> np.ndarray:
    """整段音频（时间 0 = 第一个样本）→ [T, 3] float32：F0、置信度、能量。帧 i 的时间 = (i × 160 + 80) / 16000。"""
    x16 = resample_linear(to_mono(audio), sr)
    p = padded(x16)
    n = frame_count(len(x16))
    out = np.zeros((n, 3), dtype=np.float32)
    for s0 in range(0, n, SEGMENT_FRAMES):
        s1 = min(n, s0 + SEGMENT_FRAMES)
        c0, c1 = max(0, s0 - CONTEXT_FRAMES), min(n, s1 + CONTEXT_FRAMES)
        mel = log_mel(p, c0, c1)
        (latent,) = session.run(["latent"], {"mel": mel[None]})
        f0, conf = decode(np.asarray(latent)[0][s0 - c0 : s1 - c0])
        out[s0:s1, 0] = f0
        out[s0:s1, 1] = conf
    out[:, 2] = energy(x16, n)
    return out


def measure_chunk(session: Session, audio: np.ndarray, sr: int, skip: int, frames: int) -> np.ndarray:
    """一段带上下文的音频（时间 0 = 第一个样本，落在 10 ms 网格上）→ 去掉前 ``skip`` 帧上下文后的 ``frames`` 帧 [frames, 3]。
    整段一次推理（段长约 62 秒）。"""
    x16 = resample_linear(to_mono(audio), sr)
    p = padded(x16)
    n = frame_count(len(x16))
    mel = log_mel(p, 0, n)
    (latent,) = session.run(["latent"], {"mel": mel[None]})
    f0, conf = decode(np.asarray(latent)[0])
    e = energy(x16, n)
    out = np.zeros((frames, 3), dtype=np.float32)
    m = max(0, min(frames, n - skip))
    out[:m, 0] = f0[skip : skip + m]
    out[:m, 1] = conf[skip : skip + m]
    out[:m, 2] = e[skip : skip + m]
    return out


def frame_times(n: int) -> np.ndarray:
    return (np.arange(n) * HOP + HOP / 2) / SR


def voiced(frames: np.ndarray) -> np.ndarray:
    return (frames[:, 1] > VOICED_CONF) & (frames[:, 2] > ENERGY_FLOOR)


def reliable(frames: np.ndarray) -> np.ndarray:
    return voiced(frames) & (frames[:, 0] > 0) & (frames[:, 1] >= RELIABLE_CONF)
