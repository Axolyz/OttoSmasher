"""（任务进程）一句台词的语音分析：文本前端 → 解码窗口 → 多相重采样 16 kHz → pydomino 对齐 → 归属校验 → 派生（规格 08 §8.1–§8.3、§8.5、§8.6）。

输入是 Core 在提交时冻结的条目（文本、目标与窗口、文件与样本区间）；这里只读文件、只算，不登记任何东西。
时间：结果里的音素时间一律是**资产局部秒**（窗口局部秒 + 窗口起点）。
"""

from __future__ import annotations

from math import gcd
from pathlib import Path
from typing import Any

import numpy as np
from scipy.signal import resample_poly

from ..algo import speech as derive
from ..core.errors import CoreError
from ..media import decode as dec
from ..models import domino

RESAMPLER = "scipy.resample_poly(kaiser 5.0)"


def to_16k(pcm: np.ndarray, sr: int) -> np.ndarray:
    """各声道平均成单声道，带抗混叠的多相重采样到 16 kHz（与旧版参考输出相同的做法，08 §8.3.1）。"""
    mono = np.asarray(pcm, dtype=np.float64)
    mono = mono.mean(axis=1) if mono.ndim == 2 else mono
    if sr == domino.SAMPLE_RATE:
        return mono.astype(np.float32)
    g = gcd(domino.SAMPLE_RATE, sr)
    return resample_poly(mono, domino.SAMPLE_RATE // g, sr // g).astype(np.float32)


def _strip_pau(seq: list[str]) -> list[str]:
    i, j = 0, len(seq)
    while i < j and seq[i] == "pau":
        i += 1
    while j > i and seq[j - 1] == "pau":
        j -= 1
    return seq[i:j]


def _norm(label: str) -> str:
    return {"I": "i", "U": "u"}.get(label, label)


def align_item(spec: dict[str, Any], frontend: Any, aligner: domino.Aligner, *, cache: Path, manual: bool = False) -> dict[str, Any]:
    """``frontend``：有 ``analyze(text)`` 的前端运行时（同一句文本在一个任务里只算一次由调用方缓存）。"""
    fe = frontend(spec["text"]) if callable(frontend) else frontend.analyze(spec["text"])
    f = spec["file"]
    ref = dec.StreamRef(f["path"], int(f["ordinal"]), int(f["sample_rate"]), int(f["channels"]), f.get("codec"), f.get("format"))
    a, b = spec["frames"]
    pcm = dec.decode_frames(ref, int(a), int(b), cache=cache)
    sr = ref.sample_rate
    w0 = float(spec["window"][0])  # 窗口起点（资产局部秒）
    wave = to_16k(pcm, sr)
    if len(wave) < 2 * 160:
        raise CoreError("align-audio-too-short", frames=len(wave) // 160)
    seq = domino.prepare_sequence([fe.phonemes])
    al = aligner.align(wave, seq)
    got = [_norm(x[2]) for x in al.intervals]
    want = [_norm(p) for p in seq]
    if [p for p in got if p != "pau"] != [p for p in want if p != "pau"] or len(got) != len(want):
        raise CoreError("align-ambiguous", expected=" ".join(want), got=" ".join(got))
    # 目标句的音素 = 去掉首尾 pau；句中停顿保留；零长度的边界静音不算失败
    lead = 0
    while lead < len(fe.phonemes) and fe.phonemes[lead] == "pau":
        lead += 1
    fe_core = _strip_pau(list(fe.phonemes))
    interior = al.intervals[1:-1]
    if [_norm(x[2]) for x in interior] != [_norm(p) for p in fe_core]:
        raise CoreError("align-ambiguous", expected=" ".join(fe_core), got=" ".join(x[2] for x in interior))
    labels = [_norm(p) for p in fe_core]
    local = [(labels[k], s, e) for k, (s, e, _) in enumerate(interior)]
    strengths = derive.onset_strengths(pcm, sr, [(fe_core[k], s, e) for k, (_, s, e) in enumerate(local)])
    phones = []
    for k, (label, s, e) in enumerate(local):
        orig = fe_core[k]
        eff = derive.effective_range(pcm, sr, orig, s, e, manual=manual)
        ph: dict[str, Any] = {
            "label": label,
            "start": round(w0 + s, 6),
            "end": round(w0 + e, 6),
            "mora": fe.phoneme_mora[lead + k],
            "word": fe.phoneme_word[lead + k],
        }
        if orig != label:
            ph["orig"] = orig
        if eff is not None:
            ph["eff"] = [round(w0 + eff[0], 6), round(w0 + eff[1], 6)]
        if strengths[k] is not None:
            ph["strength"] = round(float(strengths[k]), 6)
        phones.append(ph)
    return {
        "phones": phones,
        "morae": fe.morae,
        "words": [{"text": w.text, "start": w.start, "end": w.end, "reading": w.reading, "mapped": w.mapped, "moraStart": w.mora_start} for w in fe.words],
        "frontend": fe.versions,
        "aligner": {"model": domino.MODEL_ID, "decoder": domino.DECODER_VERSION, "minFrames": al.min_frames, "frames": al.frames, "resampler": RESAMPLER},
        "derived": {"effective": derive.EFFECTIVE_VERSION, "strength": derive.STRENGTH_VERSION},
        "window": spec["window"],
    }
