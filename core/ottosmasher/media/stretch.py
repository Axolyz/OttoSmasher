"""卡拍渲染（规格 09 §9.5.3、16 R13.5–R13.7）：按时间映射逐段渲染。

- 核心逐样本复制（斜率 1）；桥（含首尾）用 Rubber Band R3 引擎保音高伸缩到**精确的目标帧数**（CLI ``-3 -D``，实测输出帧数精确）；
  桥内的语音片与弹性停顿片分别渲染（Rubber Band 的 time map 只是近似，实测偏 20 ms 以上，所以不用它）；源与目标等长的片原样复制。
- 每个桥的两端与相邻核心做 3 ms 线性交叉淡化：淡入的是桥的渲染，淡出的是核心之后（或之前）继续按斜率 1 的源音频——核心本身不被改动。
- 停顿里的低电平声音被伸缩但原样保留，不置零。
- 咔哒声（所有者 2026-10-08）：与每个音块的起音同步（卡拍时在卡拍后的起音处），不是按 BPM 打拍的节拍器。
外部工具找不到 → ``tool-missing``（不换别的伸缩算法，P6）。
"""

from __future__ import annotations

import subprocess
import tempfile
from collections.abc import Sequence
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import numpy as np

from ..algo.stretch import Piece, TimeMap
from ..core.errors import CoreError
from . import tools, wavfile

RENDER_VERSION = "render-1"
FADE_SECONDS = 0.003
MIN_RUBBERBAND_FRAMES = 64  # 太短的片用线性插值（Rubber Band 对几十个样本没有意义）
CLICK_SECONDS = 0.012
CLICK_HZ = 2000.0
CLICK_GAIN = 0.5
WORKERS = 4


def rubberband_version() -> str:
    exe = tools.find("rubberband")
    p = subprocess.run([exe, "--version"], capture_output=True, encoding="utf-8", errors="replace", check=False)
    return (p.stdout or p.stderr).strip().splitlines()[0] if (p.stdout or p.stderr) else "unknown"


def _stretch_rb(x: np.ndarray, n: int, sr: int, exe: str, tmp: Path, tag: str) -> np.ndarray:
    """Rubber Band R3：[帧, 声道] → 恰好 n 帧。"""
    chans = []
    groups = [x] if x.shape[1] <= 2 else [x[:, c : c + 1] for c in range(x.shape[1])]
    for g, part in enumerate(groups):
        src, dst = tmp / f"{tag}-{g}-in.wav", tmp / f"{tag}-{g}-out.wav"
        wavfile.save_wav_f32(src, np.ascontiguousarray(part, dtype=np.float32), sr)
        p = subprocess.run([exe, "-3", "-q", "-D", f"{n / sr:.9f}", str(src), str(dst)], capture_output=True, encoding="utf-8", errors="replace", check=False)
        if p.returncode != 0 or not dst.is_file():
            raise CoreError("stretch-render-failed", tool="rubberband", detail=(p.stderr or "")[-300:])
        y, _ = wavfile.load_wav_f32(dst)
        if len(y) < n:
            y = np.vstack([y, np.zeros((n - len(y), y.shape[1]), dtype=np.float32)])
        chans.append(y[:n])
    return np.hstack(chans)


def _stretch_linear(x: np.ndarray, n: int) -> np.ndarray:
    if n <= 0:
        return np.zeros((0, x.shape[1]), dtype=np.float32)
    if len(x) == 1:
        return np.repeat(x, n, axis=0)
    pos = np.linspace(0, len(x) - 1, n)
    return np.stack([np.interp(pos, np.arange(len(x)), x[:, c]) for c in range(x.shape[1])], axis=1).astype(np.float32)


def render(pcm: np.ndarray, m: TimeMap) -> np.ndarray:
    """``pcm``：源窗口的音频 [帧, 声道]（帧 0 = 映射的源帧 0）。返回 [m.out_frames, 声道] float32。"""
    if pcm.ndim != 2:
        raise ValueError("pcm must be (frames, channels)")
    if len(pcm) < m.src_frames:
        pcm = np.vstack([pcm, np.zeros((m.src_frames - len(pcm), pcm.shape[1]), dtype=pcm.dtype)])
    pcm = pcm.astype(np.float32, copy=False)
    out = np.zeros((m.out_frames, pcm.shape[1]), dtype=np.float32)
    jobs: list[tuple[Piece, int]] = []
    for i, p in enumerate(m.pieces):
        ls, lt = p.sb - p.sa, p.tb - p.ta
        if p.kind == "core" or ls == lt:
            out[p.ta : p.tb] = pcm[p.sa : p.sb]
        elif ls < MIN_RUBBERBAND_FRAMES or lt < MIN_RUBBERBAND_FRAMES:
            out[p.ta : p.tb] = _stretch_linear(pcm[p.sa : p.sb], lt)
        else:
            jobs.append((p, i))
    if jobs:
        exe = tools.find("rubberband")
        with tempfile.TemporaryDirectory(prefix="otto-stretch-") as d, ThreadPoolExecutor(WORKERS) as pool:
            futs = [(p, pool.submit(_stretch_rb, pcm[p.sa : p.sb], p.tb - p.ta, m.sr, exe, Path(d), str(i))) for p, i in jobs]
            for p, f in futs:
                out[p.ta : p.tb] = f.result()
    _crossfade(out, pcm, m.pieces, m.sr)
    return out


def _crossfade(out: np.ndarray, pcm: np.ndarray, pieces: Sequence[Piece], sr: int) -> None:
    """每段非核心（桥、首尾）的两端与相邻核心做 3 ms 交叉淡化；核心不动。"""
    f_max = int(round(FADE_SECONDS * sr))
    runs: list[list[int]] = []
    for i, p in enumerate(pieces):
        if p.kind == "core":
            continue
        if runs and runs[-1][-1] == i - 1:
            runs[-1].append(i)
        else:
            runs.append([i])
    for run in runs:
        first, last = pieces[run[0]], pieces[run[-1]]
        if all(pieces[i].sb - pieces[i].sa == pieces[i].tb - pieces[i].ta for i in run):
            continue  # 整段原样复制：没有接缝
        length = last.tb - first.ta
        if run[0] > 0 and pieces[run[0] - 1].kind == "core":
            f = min(f_max, length // 2, len(pcm) - first.sa)
            if f > 0:
                w = np.linspace(0.0, 1.0, f, dtype=np.float32)[:, None]
                out[first.ta : first.ta + f] = out[first.ta : first.ta + f] * w + pcm[first.sa : first.sa + f] * (1 - w)
        if run[-1] + 1 < len(pieces) and pieces[run[-1] + 1].kind == "core":
            f = min(f_max, length // 2, last.sb)
            if f > 0:
                w = np.linspace(1.0, 0.0, f, dtype=np.float32)[:, None]
                out[last.tb - f : last.tb] = out[last.tb - f : last.tb] * w + pcm[last.sb - f : last.sb] * (1 - w)


def click(sr: int) -> np.ndarray:
    t = np.arange(int(round(CLICK_SECONDS * sr))) / sr
    return (CLICK_GAIN * np.sin(2 * np.pi * CLICK_HZ * t) * np.exp(-t / 0.003)).astype(np.float32)


def mix_clicks(audio: np.ndarray, frames: Sequence[int], sr: int, *, voice: bool) -> np.ndarray:
    """在 ``frames``（起音所在的帧）加咔哒声；``voice=False`` = 纯咔哒（同样长度的静音上只有咔哒）。"""
    out = audio.copy() if voice else np.zeros_like(audio)
    c = click(sr)
    for f in frames:
        if 0 <= f < len(out):
            n = min(len(c), len(out) - f)
            out[f : f + n] += c[:n, None]
    return out
