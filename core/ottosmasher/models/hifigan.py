"""PC-NSF-HiFiGAN 声码器重合成（规格 14 §14.5、11 §11.3 第 3 步）：前端与 HiFiShifter 一致。

每个声道分别做：
1. 线性插值重采样到 44.1 kHz；长度不足 4 个 hop 时末尾补零到 4 个 hop；
2. 两侧反射填充 (2048 − 512)/2 = 768 点；2048 点 Hann 窗、512 步长取帧，幅度谱乘 Slaney mel（128 带、40–16000 Hz、n_fft 2048）后取 ln(max(·, 1e-9))；
3. 第 j 个 mel 帧的时间 = (j × 512 + 256) / 44100（F0 由调用方按 11 §11.3 赋值，见 algo/flatten.assign_f0）；
4. ONNX 输入 ``mel`` [1, 128, T]（注意与 FCPE 的 [1, T, 128] 方向相反）与 ``f0`` [1, T]（Hz），输出 ``audio`` [1, 1, N]；
5. 线性插值回原采样率。

开发者决定（QUESTIONS 阶段 5）：重采样后的长度若不是 512 的整数倍，末尾再补零到整数倍——否则 T = floor(L/512) 帧的输出比输入短最多 511 点（11.6 ms），
末尾会没有重合成的声音；补零只影响最后一帧的内容，不改其他帧。Hann 窗与 FCPE 一样用 numpy ``hanning``（对称窗）。
"""

from __future__ import annotations

from functools import lru_cache

import numpy as np

from ..core.errors import CoreError
from .fcpe import _hz_to_mel, _mel_to_hz
from .onnx import Session

SR = 44100
HOP = 512
N_FFT = 2048
WIN = 2048
N_MELS = 128
FMIN = 40.0
FMAX = 16000.0
PAD = (WIN - HOP) // 2  # 768
MODEL_ID = "pc_nsf_hifigan"
MODEL_FILE = "flatten/pc_nsf_hifigan.onnx"
FRONTEND_VERSION = "hifigan-frontend-1"


def resample_linear(x: np.ndarray, sr_in: int, sr_out: int, n_out: int | None = None) -> np.ndarray:
    """线性插值：输出点 j 取原信号在 j × sr_in / sr_out 处的值（超出末尾按最后一个样本）。"""
    x = np.asarray(x, dtype=np.float64)
    if n_out is None:
        n_out = round(len(x) * sr_out / sr_in)
    if sr_in == sr_out and n_out == len(x):
        return x.copy()
    pos = np.arange(n_out, dtype=np.float64) * (sr_in / sr_out)
    return np.interp(pos, np.arange(len(x), dtype=np.float64), x)


@lru_cache(maxsize=1)
def mel_filters() -> np.ndarray:
    """librosa.filters.mel(sr=44100, n_fft=2048, n_mels=128, fmin=40, fmax=16000) 的同等实现（Slaney 刻度与归一化）。[128, 1025]"""
    n_freq = N_FFT // 2 + 1
    fftfreqs = np.linspace(0, SR / 2, n_freq)
    mel_f = _mel_to_hz(np.linspace(_hz_to_mel(np.array(FMIN)), _hz_to_mel(np.array(FMAX)), N_MELS + 2))
    fdiff = np.diff(mel_f)
    ramps = mel_f[:, None] - fftfreqs[None, :]
    weights = np.zeros((N_MELS, n_freq))
    for i in range(N_MELS):
        lower = -ramps[i] / fdiff[i]
        upper = ramps[i + 2] / fdiff[i + 1]
        weights[i] = np.maximum(0, np.minimum(lower, upper))
    enorm = 2.0 / (mel_f[2 : N_MELS + 2] - mel_f[:N_MELS])
    return weights * enorm[:, None]


def padded_length(n44: int) -> int:
    """送进 STFT 的长度：至少 4 个 hop，并补到 hop 的整数倍。"""
    n = max(n44, 4 * HOP)
    return -(-n // HOP) * HOP


def frame_count(n44: int) -> int:
    return padded_length(n44) // HOP


def mel_times(n_frames: int) -> np.ndarray:
    return (np.arange(n_frames) * HOP + HOP / 2) / SR


def log_mel(x44: np.ndarray) -> np.ndarray:
    """44.1 kHz 单声道 → log-mel [128, T]。"""
    n = padded_length(len(x44))
    x = np.zeros(n, dtype=np.float64)
    x[: len(x44)] = x44
    p = np.pad(x, (PAD, PAD), mode="reflect")
    frames = np.lib.stride_tricks.sliding_window_view(p, WIN)[::HOP][: n // HOP]
    mag = np.abs(np.fft.rfft(frames * np.hanning(WIN), axis=1))
    return np.log(np.maximum(mag @ mel_filters().T, 1e-9)).T.astype(np.float32)


def render(session: Session, audio: np.ndarray, sr: int, f0: np.ndarray) -> np.ndarray:
    """``audio`` [N, 声道]（原采样率）→ 重合成 [N, 声道]。``f0``：每个 mel 帧的 Hz（长度 = frame_count(44.1 kHz 长度)）。"""
    a = np.asarray(audio)
    if a.ndim == 1:
        a = a[:, None]
    n = a.shape[0]
    n44 = round(n * SR / sr)
    t = frame_count(n44)
    if len(f0) != t:
        raise CoreError("flatten-output-invalid", reason="frames", expected=t, got=len(f0))
    out = np.zeros(a.shape, dtype=np.float32)
    f0_in = np.asarray(f0, dtype=np.float32)[None]
    for c in range(a.shape[1]):
        x44 = resample_linear(a[:, c], sr, SR, n44)
        mel = log_mel(x44)
        (y,) = session.run(["audio"], {"mel": mel[None], "f0": f0_in})
        y = np.asarray(y, dtype=np.float64).reshape(-1)
        if len(y) != t * HOP:
            raise CoreError("flatten-output-invalid", reason="length", expected=t * HOP, got=len(y))
        if not np.all(np.isfinite(y)):
            raise CoreError("flatten-output-invalid", reason="non-finite")
        back = resample_linear(y[:n44], SR, sr, n)
        if abs(len(back) - n) > 1:
            raise CoreError("flatten-output-invalid", reason="length", expected=n, got=len(back))
        out[:, c] = back.astype(np.float32)
    return out
