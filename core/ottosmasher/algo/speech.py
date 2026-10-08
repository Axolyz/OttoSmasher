"""语音分析的派生值（规格 08 §8.5、§8.6）【基线算法】。纯函数，不做 IO；时间单位为秒（调用方注明时钟）。

- 有效范围（元音 a i u e o、清音 I U、拨音 N；不含辅音 n）：10 ms 帧能量，峰值取第 85 百分位，活跃帧 = 能量 > max(1e-10, 峰值 × 0.0064)；
  帧数 ≥ 4、活跃帧 ≥ 3 才算；有效起点 = 首个活跃帧中心 − 5 ms、终点 = 末个活跃帧中心 + 5 ms；边缘有 ≥ 30 ms 的安静段才收缩，收缩后向外留 10 ms 护边；
  收缩后不足 30 ms 保留原范围；人工版本不收缩；证据不足（能量全零等）保留原范围；不以“无音高”或模型空白判断静音。
- 起音强度：每个元音或 N 取整个音素区间的 RMS（多声道一起算），除以全句元音/N 的最大值，得 0–1；全句都没有能量时为未知（None），不是 0。
"""

from __future__ import annotations

from collections.abc import Sequence

import numpy as np

EFFECTIVE_VERSION = "effective-range-1"
STRENGTH_VERSION = "onset-strength-1"
EFFECTIVE_LABELS = frozenset({"a", "i", "u", "e", "o", "I", "U", "N"})
FRAME = 0.01
MIN_FRAMES = 4
MIN_ACTIVE = 3
PEAK_PERCENTILE = 85
ACTIVE_RATIO = 0.0064
ENERGY_FLOOR = 1e-10
EDGE = 0.005
QUIET_MIN = 0.03
GUARD = 0.01
MIN_LENGTH = 0.03


def _slice(audio: np.ndarray, sr: int, a: float, b: float) -> np.ndarray:
    """``audio``：[样本, 声道]，时间 0 = 第一个样本。"""
    i, j = max(0, round(a * sr)), min(len(audio), round(b * sr))
    return audio[i:j] if j > i else audio[0:0]


def frame_energy(audio: np.ndarray, sr: int, start: float, end: float) -> np.ndarray:
    """[start, end) 内从 start 起每 10 ms 一帧的功率（多声道一起取均方）；不足一帧的尾巴不算。"""
    n = int(np.floor((end - start) / FRAME + 1e-9))
    out = np.zeros(n, dtype=np.float64)
    for k in range(n):
        x = _slice(audio, sr, start + k * FRAME, start + (k + 1) * FRAME)
        out[k] = float(np.mean(np.square(x, dtype=np.float64))) if x.size else 0.0
    return out


def effective_range(audio: np.ndarray, sr: int, label: str, start: float, end: float, *, manual: bool = False) -> tuple[float, float] | None:
    """一个音素的有效范围；不适用的音素返回 None（没有有效范围）。"""
    if label not in EFFECTIVE_LABELS:
        return None
    if manual:
        return (start, end)
    e = frame_energy(audio, sr, start, end)
    if len(e) < MIN_FRAMES:
        return (start, end)
    peak = float(np.percentile(e, PEAK_PERCENTILE))
    active = np.flatnonzero(e > max(ENERGY_FLOOR, peak * ACTIVE_RATIO))
    if len(active) < MIN_ACTIVE:
        return (start, end)
    eff_a = start + (active[0] + 0.5) * FRAME - EDGE
    eff_b = start + (active[-1] + 0.5) * FRAME + EDGE
    a = eff_a - GUARD if eff_a - start >= QUIET_MIN - 1e-9 else start
    b = eff_b + GUARD if end - eff_b >= QUIET_MIN - 1e-9 else end
    a, b = max(a, start), min(b, end)
    if b - a < MIN_LENGTH - 1e-9:
        return (start, end)
    return (round(a, 6), round(b, 6))


def onset_strengths(audio: np.ndarray, sr: int, phones: Sequence[tuple[str, float, float]]) -> list[float | None]:
    """每个音素的起音强度（只给元音与 N；其余为 None）。"""
    rms: list[float | None] = []
    for label, a, b in phones:
        if label not in EFFECTIVE_LABELS:
            rms.append(None)
            continue
        x = _slice(audio, sr, a, b)
        rms.append(float(np.sqrt(np.mean(np.square(x, dtype=np.float64)))) if x.size else 0.0)
    peak = max((r for r in rms if r is not None), default=0.0)
    if peak <= 0:
        return [None] * len(rms)
    return [None if r is None else r / peak for r in rms]
