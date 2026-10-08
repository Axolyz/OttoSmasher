"""拉平的基线算法（规格 11 §11.2–§11.3、§11.7，14 §14.5，16 R17）【基线算法】。纯函数 + numpy，不做 IO。

时钟：这里的时间一律是**输入局部秒**（冻结的外选区 [a, b) 的起点 = 0，长度 d = b − a）；调用方负责换算。

- 目标音高：可靠帧（有声 且 F0 > 0 且 置信度 ≥ 0.5）的 MIDI，按置信度（下限 1e-6）加权取中位数（排序后累计权重首次达到一半的那一帧），
  再 floor(x + 0.5) 吸附半音；至少 3 帧。段内 = 处理区间内的帧；交界 = 所选一侧边界向内 100 ms 的帧，证据不足报错、**不换侧**。
- 手动：音名（A4、C#5、B♭3）→ 精确半音；带单位的频率（445Hz）→ 精确换算、不吸附，名称带音分后缀（A4+20c）；纯数字拒绝。
- 处理区间：整段 [0, d]；仅元音 = 各元音/N 区间（收紧后）；首元音起 = [首个元音/N 起点, d]；内部 = [a', b']（平台 ≥ 30 ms）。
- 内部拉平的过渡：MIDI 域按 smoothstep 权重从原音高过渡到目标。
- 拼接：采样域掩码，区间外逐样本复制；非整段模式每个区间两端 3 ms 线性淡化（不超过区间长度的 1/4）。
"""

from __future__ import annotations

import math
import re
from collections.abc import Sequence
from dataclasses import dataclass

import numpy as np

from ..core.errors import CoreError
from . import speech as derive

ALGO_VERSION = "flatten-1"
RANGES = ("whole", "vowels", "first", "inner")
TARGETS = ("auto", "edge", "manual")
SIDES = ("left", "right")
RELIABLE_CONF = 0.5
VOICED_CONF = 0.05
ENERGY_FLOOR = 1e-10
WEIGHT_FLOOR = 1e-6
MIN_FRAMES = 3
EDGE_SECONDS = 0.1
FADE_SECONDS = 0.003
TRANSITION = 0.05
MIN_PLATEAU = 0.03
NOTE_NAMES = ("C", "C♯", "D", "D♯", "E", "F", "F♯", "G", "G♯", "A", "A♯", "B")
_PITCH_CLASS = {"C": 0, "D": 2, "E": 4, "F": 5, "G": 7, "A": 9, "B": 11}
_ACCIDENTAL = {"": 0, "#": 1, "♯": 1, "b": -1, "♭": -1}
_NOTE_RE = re.compile(r"([A-Ga-g])\s*([#♯b♭]?)\s*(-?\d+)")
_HZ_RE = re.compile(r"(\d+(?:\.\d+)?|\.\d+)\s*[hH][zZ]")
_NUMBER_RE = re.compile(r"[-+]?(\d+(?:\.\d+)?|\.\d+)")


# ---------------------------------------------------------------- 音名与频率


def note_name(midi: int) -> str:
    """MIDI 整数 → 音名（MIDI 60 = C4，升号写 ♯）。"""
    return f"{NOTE_NAMES[midi % 12]}{midi // 12 - 1}"


def midi_to_hz(midi: float) -> float:
    return 440.0 * 2.0 ** ((midi - 69.0) / 12.0)


def hz_to_midi(hz: float) -> float:
    return 69.0 + 12.0 * math.log2(hz / 440.0)


def snap(midi: float) -> int:
    """吸附最近半音：floor(x + 0.5)。"""
    return int(math.floor(midi + 0.5))


def cents_name(midi: float) -> str:
    """非整数 MIDI 的名称：最近半音 + 音分后缀（69.196 → A4+20c）；整数不带后缀。"""
    n = snap(midi)
    c = int(math.floor((midi - n) * 100 + 0.5))
    return note_name(n) + (f"{c:+d}c" if c else "")


def note_to_midi(text: str) -> int | None:
    """音名 → MIDI 整数（A4 = 69；F#5 = G♭5 = 78）；不是音名返回 None。"""
    m = _NOTE_RE.fullmatch(text.strip())
    if m is None:
        return None
    return (int(m.group(3)) + 1) * 12 + _PITCH_CLASS[m.group(1).upper()] + _ACCIDENTAL[m.group(2)]


@dataclass(frozen=True)
class Target:
    """目标音：MIDI（手动频率时可以不是整数）、名称、Hz；``original`` 是定音时的原始 MIDI（加权中位数，吸附前）。"""

    midi: float
    name: str
    hz: float
    method: str
    original: float | None = None
    ref: tuple[float, float] | None = None
    side: str | None = None

    def wire(self) -> dict[str, object]:
        return {
            "midi": self.midi,
            "name": self.name,
            "hz": self.hz,
            "method": self.method,
            "originalMidi": self.original,
            "shiftSemitones": None if self.original is None else self.midi - self.original,
            "ref": list(self.ref) if self.ref else None,
            "side": self.side,
        }


def parse_manual(value: object) -> Target:
    """手动目标：音名 → 精确半音；带单位的频率 → 精确换算、不吸附；空、无法解析、纯数字（含义不明）拒绝。"""
    if not isinstance(value, str) or isinstance(value, bool):
        raise CoreError("flatten-target-invalid", reason="target-unparsable")
    s = value.strip()
    if not s:
        raise CoreError("flatten-target-invalid", reason="target-empty")
    m = _HZ_RE.fullmatch(s)
    if m is not None:
        hz = float(m.group(1))
        if not math.isfinite(hz) or hz <= 0:
            raise CoreError("flatten-target-invalid", reason="target-unparsable")
        midi = hz_to_midi(hz)
        return Target(midi, cents_name(midi), hz, "manual")
    if _NUMBER_RE.fullmatch(s):
        raise CoreError("flatten-target-invalid", reason="bare-number")
    n = note_to_midi(s)
    if n is None or not 0 <= n <= 127:
        raise CoreError("flatten-target-invalid", reason="target-unparsable")
    return Target(float(n), note_name(n), midi_to_hz(n), "manual")


# ---------------------------------------------------------------- 定音


def frame_times(n: int) -> np.ndarray:
    """FCPE 帧中心（输入局部秒）：(i × 160 + 80) / 16000。"""
    return (np.arange(n) * 160 + 80) / 16000.0


def voiced(f0: np.ndarray, conf: np.ndarray, energy: np.ndarray) -> np.ndarray:
    return (conf > VOICED_CONF) & (energy > ENERGY_FLOOR)


def reliable(f0: np.ndarray, conf: np.ndarray, energy: np.ndarray) -> np.ndarray:
    with np.errstate(invalid="ignore"):
        return voiced(f0, conf, energy) & np.isfinite(f0) & (f0 > 0) & (conf >= RELIABLE_CONF)


def weighted_median(values: np.ndarray, weights: np.ndarray) -> float:
    """排序后累计权重首次达到一半处的值。"""
    order = np.argsort(values, kind="stable")
    v, w = np.asarray(values, dtype=np.float64)[order], np.maximum(np.asarray(weights, dtype=np.float64)[order], WEIGHT_FLOOR)
    cum = np.cumsum(w)
    return float(v[int(np.searchsorted(cum, cum[-1] / 2.0 - 1e-12 * cum[-1]))])


def _in_windows(times: np.ndarray, windows: Sequence[tuple[float, float]]) -> np.ndarray:
    m = np.zeros(len(times), dtype=bool)
    for a, b in windows:
        m |= (times >= a - 1e-9) & (times < b - 1e-9)
    return m


def _median_target(frames: np.ndarray, times: np.ndarray, windows: Sequence[tuple[float, float]]) -> float | None:
    f0, conf, en = frames[:, 0], frames[:, 1], frames[:, 2]
    use = reliable(f0, conf, en) & _in_windows(times, windows)
    if int(use.sum()) < MIN_FRAMES:
        return None
    midi = 69.0 + 12.0 * np.log2(f0[use].astype(np.float64) / 440.0)
    return weighted_median(midi, conf[use])


def edge_window(intervals: Sequence[tuple[float, float]], side: str) -> tuple[float, float]:
    """交界参考区间：左 = [首个处理区间起点, +100 ms)；右 = [末个处理区间终点 − 100 ms, 终点)。"""
    if side == "left":
        a = intervals[0][0]
        return (a, a + EDGE_SECONDS)
    b = intervals[-1][1]
    return (b - EDGE_SECONDS, b)


def auto_target(frames: np.ndarray, intervals: Sequence[tuple[float, float]], times: np.ndarray | None = None) -> Target:
    """段内自动：处理区间内的可靠帧。``frames``：[n, 3]（F0、置信度、能量），帧 i 在 ``times[i]``（默认 FCPE 网格）。"""
    times = frame_times(len(frames)) if times is None else times
    x = _median_target(frames, times, intervals)
    if x is None:
        raise CoreError("flatten-f0-insufficient", frames=MIN_FRAMES)
    n = snap(x)
    return Target(float(n), note_name(n), midi_to_hz(n), "auto", original=x, ref=(intervals[0][0], intervals[-1][1]))


def edge_target(frames: np.ndarray, intervals: Sequence[tuple[float, float]], side: str, times: np.ndarray | None = None) -> Target:
    """交界自动：所选一侧向内 100 ms；证据不足报错并建议换侧 / 段内 / 手动，绝不自动换侧。"""
    if side not in SIDES:
        raise CoreError("flatten-invalid", reason="not-an-option", field="side")
    times = frame_times(len(frames)) if times is None else times
    w = edge_window(intervals, side)
    x = _median_target(frames, times, [w])
    if x is None:
        raise CoreError("flatten-edge-insufficient", side=side, frames=MIN_FRAMES)
    n = snap(x)
    return Target(float(n), note_name(n), midi_to_hz(n), "edge", original=x, ref=w, side=side)


# ---------------------------------------------------------------- 处理区间


def default_inner(d: float) -> tuple[float, float]:
    """内部拉平的初始内区：[min(0.1, d/4), max(d − 0.1, 0.75d)]。"""
    return (min(0.1, d / 4), max(d - 0.1, 0.75 * d))


def check_inner(d: float, inner: tuple[float, float], trans: tuple[float, float] = (TRANSITION, TRANSITION)) -> tuple[float, float]:
    a, b = float(inner[0]), float(inner[1])
    tl, tr = float(trans[0]), float(trans[1])
    if not all(math.isfinite(x) for x in (a, b, tl, tr)) or tl < 0 or tr < 0:
        raise CoreError("flatten-inner-invalid", reason="number")
    if a < -1e-9 or b > d + 1e-9 or not a < b:
        raise CoreError("flatten-inner-invalid", reason="out-of-bounds")
    if (b - a) - tl - tr < MIN_PLATEAU - 1e-9:
        raise CoreError("flatten-inner-invalid", reason="plateau", ms=round(MIN_PLATEAU * 1000))
    return (max(0.0, a), min(d, b))


def smoothstep(x: np.ndarray | float) -> np.ndarray:
    x = np.clip(np.asarray(x, dtype=np.float64), 0.0, 1.0)
    return x * x * (3.0 - 2.0 * x)


def inner_weight(t: np.ndarray | float, inner: tuple[float, float], trans: tuple[float, float] = (TRANSITION, TRANSITION)) -> np.ndarray:
    """内部拉平在时间 t 的目标权重：内区外为 0；两侧过渡段按 smoothstep 从 0 到 1；平台为 1。"""
    t = np.asarray(t, dtype=np.float64)
    a, b = inner
    tl, tr = trans
    up = np.ones_like(t) if tl <= 0 else smoothstep((t - a) / tl)
    down = np.ones_like(t) if tr <= 0 else smoothstep((b - t) / tr)
    w = np.minimum(up, down)
    return np.where((t < a - 1e-12) | (t >= b - 1e-12), 0.0, w)


def vowel_intervals(
    phones: Sequence[tuple[str, float, float]], d: float, *, audio: np.ndarray | None = None, sr: int = 0, manual: bool = False
) -> list[tuple[float, float]]:
    """元音/N 的处理区间：裁到 [0, d] 后按 08 §8.5 用这段输入的能量收紧（人工版本不收紧）。``phones``：(原始标签, 起, 止)，输入局部秒。"""
    out = []
    for label, s, e in phones:
        if label not in derive.EFFECTIVE_LABELS:
            continue
        s, e = max(0.0, float(s)), min(d, float(e))
        if e - s <= 1e-9:
            continue
        if audio is not None and not manual:
            r = derive.effective_range(audio, sr, label, s, e)
            if r is not None:
                s, e = r
        out.append((s, e))
    return out


def processing_intervals(
    mode: str, d: float, *, vowels: Sequence[tuple[float, float]] | None = None, inner: tuple[float, float] | None = None,
    trans: tuple[float, float] = (TRANSITION, TRANSITION),
) -> list[tuple[float, float]]:  # fmt: skip
    if mode == "whole":
        return [(0.0, d)]
    if mode == "inner":
        return [check_inner(d, inner if inner is not None else default_inner(d), trans)]
    if mode in ("vowels", "first"):
        if vowels is None:
            raise CoreError("flatten-needs-alignment", reason="no-alignment")
        if not vowels:
            raise CoreError("flatten-needs-alignment", reason="no-vowel")
        if mode == "vowels":
            return [(float(a), float(b)) for a, b in vowels]
        return [(float(vowels[0][0]), d)]
    raise CoreError("flatten-invalid", reason="not-an-option", field="range")


# ---------------------------------------------------------------- 声码器的 F0 与拼接


def assign_f0(
    mel_times: np.ndarray, frames: np.ndarray, intervals: Sequence[tuple[float, float]], target_midi: float, *,
    inner: tuple[float, float] | None = None, trans: tuple[float, float] = (TRANSITION, TRANSITION),
) -> np.ndarray:  # fmt: skip
    """每个 mel 帧的 F0（Hz）：取最近的 FCPE 帧 round((t − 0.005)/0.01)；处理区间内、有声、F0 有限且 > 0 → 目标
    （内部拉平：MIDI 域按权重混合原音高与目标）；无声帧 = 0（不补音）；其余保持测得的 F0。"""
    n = len(frames)
    f0, conf, en = frames[:, 0].astype(np.float64), frames[:, 1], frames[:, 2]
    k = np.clip(np.floor((mel_times - 0.005) / 0.01 + 0.5).astype(np.int64), 0, max(0, n - 1))
    v = voiced(f0, conf, en)[k]
    with np.errstate(invalid="ignore"):
        good = v & np.isfinite(f0[k]) & (f0[k] > 0)
    inside = _in_windows(mel_times, intervals)
    out = np.where(good, f0[k], 0.0)
    sel = inside & good
    if inner is None:
        out[sel] = midi_to_hz(target_midi)
    else:
        w = inner_weight(mel_times[sel], inner, trans)
        orig = 69.0 + 12.0 * np.log2(f0[k][sel] / 440.0)
        out[sel] = 440.0 * 2.0 ** (((1.0 - w) * orig + w * target_midi - 69.0) / 12.0)
    return out


def splice_mask(n: int, sr: int, intervals: Sequence[tuple[float, float]], *, fade: bool) -> np.ndarray:
    """采样域掩码（0 = 原样，1 = 重合成）；``fade``：每个区间两端 3 ms 线性淡化（不超过区间长度的 1/4），淡化在区间内部。"""
    m = np.zeros(n, dtype=np.float64)
    for s, e in intervals:
        i0, i1 = max(0, round(s * sr)), min(n, round(e * sr))
        if i1 <= i0:
            continue
        seg = np.ones(i1 - i0)
        if fade:
            f = min(round(FADE_SECONDS * sr), (i1 - i0) // 4)
            if f > 0:
                ramp = np.arange(f) / f
                seg[:f] = np.minimum(seg[:f], ramp)
                seg[-f:] = np.minimum(seg[-f:], ramp[::-1])
        m[i0:i1] = np.maximum(m[i0:i1], seg)
    return m


def splice(original: np.ndarray, rendered: np.ndarray, mask: np.ndarray) -> np.ndarray:
    """区间外逐样本原样复制；``original`` / ``rendered``：[N, 声道]。"""
    if original.shape != rendered.shape:
        raise CoreError("flatten-output-invalid", reason="length", expected=int(original.shape[0]), got=int(rendered.shape[0]))
    if not np.all(np.isfinite(rendered)):
        raise CoreError("flatten-output-invalid", reason="non-finite")
    out = original.astype(np.float32).copy()
    sel = mask > 0
    m = mask[sel][:, None]
    out[sel] = (original[sel].astype(np.float64) * (1.0 - m) + rendered[sel].astype(np.float64) * m).astype(np.float32)
    return out
