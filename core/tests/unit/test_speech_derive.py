"""有效范围与起音强度（规格 08 §8.5、§8.6，16 R11.4、R11.8 的 A15）。"""

from __future__ import annotations

import numpy as np
import pytest

from ottosmasher.algo import speech as sp

SR = 16000


def burst(total: float, a: float, b: float, amp: float = 0.1, channels: int = 1) -> np.ndarray:
    """只在 [a, b) 有能量（均方 = amp²）的音频。"""
    x = np.zeros((round(total * SR), channels), dtype=np.float32)
    x[round(a * SR) : round(b * SR)] = amp
    return x


def test_spec_example_energy_between_0_2_and_0_7():
    audio = burst(1.0, 0.2, 0.7)  # 能量 0.01
    assert sp.effective_range(audio, SR, "a", 0.0, 1.0) == (0.19, 0.71)
    assert sp.effective_range(audio, SR, "N", 0.0, 1.0)[1] == 0.71
    assert sp.effective_range(audio, SR, "n", 0.0, 1.0) is None
    assert sp.effective_range(audio, SR, "k", 0.0, 1.0) is None
    assert sp.effective_range(audio, SR, "U", 0.0, 1.0) == (0.19, 0.71)


def test_keep_original_when_evidence_is_missing_or_manual():
    audio = burst(1.0, 0.2, 0.7)
    assert sp.effective_range(audio, SR, "a", 0.0, 1.0, manual=True) == (0.0, 1.0)
    silent = np.zeros((SR, 1), dtype=np.float32)
    assert sp.effective_range(silent, SR, "a", 0.0, 1.0) == (0.0, 1.0)
    # 不足 4 帧
    assert sp.effective_range(audio, SR, "a", 0.2, 0.23) == (0.2, 0.23)
    # 活跃帧不足 3
    assert sp.effective_range(burst(1.0, 0.5, 0.52), SR, "a", 0.0, 1.0) == (0.0, 1.0)


def test_only_shrink_edges_with_30ms_quiet_and_keep_guard():
    # 前面只有 20 ms 安静：起点不收缩；后面 300 ms 安静：收缩并留 10 ms 护边
    audio = burst(1.0, 0.02, 0.7)
    assert sp.effective_range(audio, SR, "a", 0.0, 1.0) == (0.0, 0.71)
    # 三个活跃帧：两边都收缩并各留 10 ms 护边
    assert sp.effective_range(burst(0.2, 0.08, 0.11), SR, "a", 0.0, 0.2) == (0.07, 0.12)
    # 音素不从 0 开始：帧从音素起点算
    assert sp.effective_range(burst(2.0, 1.2, 1.7), SR, "o", 1.0, 2.0) == (1.19, 1.71)


def test_onset_strengths_relative_to_sentence_max():
    audio = np.concatenate([burst(0.5, 0.0, 0.5, 0.1), burst(0.5, 0.0, 0.5, 0.05, 1)])
    phones = [("k", 0.0, 0.1), ("a", 0.1, 0.5), ("N", 0.5, 1.0)]
    s = sp.onset_strengths(audio, SR, phones)
    assert s[0] is None and s[1] == pytest.approx(1.0) and s[2] == pytest.approx(0.5)
    # 多声道一起算
    stereo = burst(1.0, 0.0, 1.0, 0.1, 2)
    stereo[:, 1] = 0.0
    assert sp.onset_strengths(stereo, SR, [("a", 0.0, 1.0)]) == [pytest.approx(1.0)]
    # 全句没有能量：未知，不是 0
    assert sp.onset_strengths(np.zeros((SR, 1), np.float32), SR, [("a", 0.0, 1.0)]) == [None]
