"""拉平基线算法（规格 11 §11.7、16 R17）：数值例子逐条。"""

from __future__ import annotations

import math

import numpy as np
import pytest

from ottosmasher.algo import flatten as fl
from ottosmasher.core.errors import CoreError
from ottosmasher.models import hifigan


def frames_for(f0_of_t, total: float, conf: float = 0.9, energy: float = 0.01) -> np.ndarray:
    """FCPE 网格上的合成帧（时间 = 帧中心）。"""
    n = int(total * 100)
    t = fl.frame_times(n)
    out = np.zeros((n, 3), dtype=np.float32)
    out[:, 0] = [f0_of_t(x) for x in t]
    out[:, 1] = conf
    out[:, 2] = energy
    return out


# ---------------------------------------------------------------- 交界定音


def test_edge_left_and_right_440_660():
    fr = frames_for(lambda t: 440.0 if t < 0.5 else 660.0, 1.0)
    iv = [(0.2, 0.8)]
    left = fl.edge_target(fr, iv, "left")
    assert left.midi == 69 and left.name == "A4" and left.ref == pytest.approx((0.2, 0.3))
    right = fl.edge_target(fr, iv, "right")
    assert right.midi == 76 and right.name == "E5" and right.ref == pytest.approx((0.7, 0.8))


def test_edge_insufficient_side_errors_and_never_switches():
    fr = frames_for(lambda t: 440.0 if t < 0.5 else 660.0, 1.0)
    fr[fl.frame_times(len(fr)) < 0.3, 1] = 0.0  # 前 0.3 秒置信度为 0
    with pytest.raises(CoreError) as e:
        fl.edge_target(fr, [(0.2, 0.8)], "left")
    assert e.value.code == "flatten-edge-insufficient" and e.value.args_["side"] == "left"
    assert fl.edge_target(fr, [(0.2, 0.8)], "right").midi == 76


# ---------------------------------------------------------------- 处理区间


def test_first_vowel_interval():
    assert fl.processing_intervals("first", 1.0, vowels=[(0.2, 0.5), (0.7, 0.8)]) == [(0.2, 1.0)]
    with pytest.raises(CoreError) as e:
        fl.processing_intervals("first", 1.0, vowels=[])
    assert e.value.code == "flatten-needs-alignment" and e.value.args_["reason"] == "no-vowel"
    with pytest.raises(CoreError):
        fl.processing_intervals("vowels", 1.0, vowels=None)


def test_first_vowel_tightened_by_energy():
    sr = 16000
    audio = np.zeros((sr, 1), dtype=np.float32)
    audio[round(0.3 * sr) : round(0.5 * sr)] = 0.1  # 元音 [0.2, 0.5] 的前 0.1 秒安静
    phones = [("k", 0.1, 0.2), ("a", 0.2, 0.5), ("o", 0.7, 0.8)]
    v = fl.vowel_intervals(phones, 1.0, audio=audio, sr=sr)
    iv = fl.processing_intervals("first", 1.0, vowels=v)
    assert iv[0][0] > 0.2 and iv[0][1] == 1.0
    # 人工版本不收紧
    assert fl.vowel_intervals(phones, 1.0, audio=audio, sr=sr, manual=True)[0] == (0.2, 0.5)


def test_vowels_only_are_the_vowel_intervals_and_clip_to_selection():
    phones = [("k", 0.0, 0.05), ("o", 0.05, 0.4), ("cl", 0.4, 0.5), ("N", 0.5, 1.3)]
    v = fl.vowel_intervals(phones, 1.0)
    assert fl.processing_intervals("vowels", 1.0, vowels=v) == [(0.05, 0.4), (0.5, 1.0)]


def test_vowels_only_consonants_unchanged_sample_by_sample_and_3ms_fade():
    sr = 48000
    n = sr
    rng = np.random.default_rng(1)
    orig = rng.uniform(-0.5, 0.5, (n, 2)).astype(np.float32)
    rend = rng.uniform(-0.5, 0.5, (n, 2)).astype(np.float32)
    iv = [(0.1, 0.3), (0.5, 0.9)]
    m = fl.splice_mask(n, sr, iv, fade=True)
    out = fl.splice(orig, rend, m)
    outside = m == 0
    assert np.array_equal(out[outside], orig[outside])  # 区间之间逐样本不变
    f = round(0.003 * sr)
    i0 = round(0.1 * sr)
    assert m[i0] == 0 and 0 < m[i0 + 1] < 1 and m[i0 + f] == 1  # 3 ms 线性淡入
    assert np.allclose(np.diff(m[i0 : i0 + f]), 1 / f)
    i1 = round(0.3 * sr)
    assert m[i1 - 1] < 1 and m[i1] == 0
    # 淡化不超过区间长度的 1/4
    short = fl.splice_mask(n, sr, [(0.1, 0.104)], fade=True)
    assert int((short[round(0.1 * sr) : round(0.104 * sr)] < 1).sum()) <= 2 * (round(0.004 * sr) // 4)
    # 整段模式两端不淡化
    whole = fl.splice_mask(n, sr, [(0.0, 1.0)], fade=False)
    assert whole.min() == 1.0


def test_splice_rejects_non_finite_and_length_change():
    orig = np.zeros((100, 1), dtype=np.float32)
    bad = orig.copy()
    bad[5] = np.nan
    with pytest.raises(CoreError) as e:
        fl.splice(orig, bad, np.ones(100))
    assert e.value.args_["reason"] == "non-finite"
    with pytest.raises(CoreError) as e:
        fl.splice(orig, np.zeros((99, 1), dtype=np.float32), np.ones(100))
    assert e.value.args_["reason"] == "length"


# ---------------------------------------------------------------- 内部拉平


def test_inner_weights():
    inner = (0.2, 0.8)
    w = lambda t: float(fl.inner_weight(t, inner))  # noqa: E731
    assert w(0.19) == 0 and w(0.8) == 0 and w(0.85) == 0
    for t in (0.25, 0.4, 0.6, 0.75):
        assert w(t) == pytest.approx(1.0)
    assert w(0.225) == pytest.approx(0.5)
    assert w(0.201) < 0.002
    with pytest.raises(CoreError) as e:
        fl.check_inner(1.0, (0.2, 0.31))
    assert e.value.code == "flatten-inner-invalid" and e.value.args_["ms"] == 30
    with pytest.raises(CoreError):
        fl.check_inner(1.0, (0.2, 1.2))
    assert fl.default_inner(1.0) == (0.1, 0.9)
    assert fl.default_inner(0.2) == pytest.approx((0.05, 0.15))


def test_inner_transition_mixes_in_midi_domain():
    fr = frames_for(lambda t: 440.0, 1.0)
    times = np.array([0.1, 0.225, 0.5, 0.9])
    out = fl.assign_f0(times, fr, [(0.2, 0.8)], 81.0, inner=(0.2, 0.8))
    assert out[0] == pytest.approx(440.0)  # 区间外保持原 F0
    assert out[1] == pytest.approx(fl.midi_to_hz(75.0))  # 69 与 81 各半
    assert out[2] == pytest.approx(fl.midi_to_hz(81.0))
    assert out[3] == pytest.approx(440.0)


def test_assign_f0_unvoiced_zero_and_nearest_frame():
    fr = frames_for(lambda t: 300.0, 1.0)
    fr[50:60, 1] = 0.01  # 0.50–0.60 无声
    times = hifigan.mel_times(hifigan.frame_count(44100))
    out = fl.assign_f0(times, fr, [(0.0, 1.0)], 69.0)
    k = np.clip(np.floor((times - 0.005) / 0.01 + 0.5).astype(int), 0, 99)
    unvoiced = (k >= 50) & (k < 60)
    assert np.all(out[unvoiced] == 0)
    inside = times < 1.0
    assert np.allclose(out[~unvoiced & inside], 440.0)
    assert np.allclose(out[~inside], 300.0)  # 区间外的有声帧保持原 F0


# ---------------------------------------------------------------- 加权中位数与段内定音


def test_weighted_median_is_robust():
    fr = np.array([[439, 0.9, 0.01], [440, 0.9, 0.01], [441, 0.9, 0.01], [880, 0.9, 0.01]], dtype=np.float32)
    t = fl.auto_target(fr, [(0.0, 1.0)], times=np.array([0.1, 0.2, 0.3, 0.4]))
    assert t.name == "A4" and t.hz == pytest.approx(440.0)
    with pytest.raises(CoreError) as e:
        fl.auto_target(fr * np.array([1, 0, 1], dtype=np.float32), [(0.0, 1.0)], times=np.array([0.1, 0.2, 0.3, 0.4]))
    assert e.value.code == "flatten-f0-insufficient"


def test_auto_uses_only_reliable_frames_inside_intervals():
    fr = frames_for(lambda t: 440.0 if 0.3 <= t < 0.6 else 1000.0, 1.0)
    fr[fl.frame_times(100) >= 0.6, 1] = 0.3  # 不可靠
    t = fl.auto_target(fr, [(0.3, 1.0)])
    assert t.midi == 69 and t.original == pytest.approx(69.0, abs=1e-6)
    # 正压在分界上也是 floor(x + 0.5)
    assert fl.snap(79.5) == 80 and fl.snap(79.4999) == 79


# ---------------------------------------------------------------- 音名换算与手动目标


def test_note_conversion():
    assert fl.note_to_midi("A4") == 69
    assert fl.note_to_midi("F#5") == fl.note_to_midi("G♭5") == fl.note_to_midi("F♯5") == fl.note_to_midi("Gb5") == 78
    assert fl.midi_to_hz(69) == pytest.approx(440.0)
    assert fl.note_name(80) == "G♯5" and fl.note_name(60) == "C4"
    t = fl.parse_manual("445Hz")
    assert t.midi == pytest.approx(69.196, abs=1e-3) and t.name == "A4+20c" and t.hz == 445.0
    assert fl.parse_manual("445 hz").name == "A4+20c"
    assert fl.parse_manual("C#5").midi == 73 and fl.parse_manual("B♭3").name == "A♯3"
    assert fl.parse_manual("440Hz").name == "A4"


@pytest.mark.parametrize("value,reason", [("440", "bare-number"), ("69", "bare-number"), ("", "target-empty"), ("   ", "target-empty"), ("H4", "target-unparsable"),
                                          ("A", "target-unparsable"), (float("nan"), "target-unparsable"), (True, "target-unparsable"), (69, "target-unparsable"), ("0Hz", "target-unparsable")])  # fmt: skip
def test_manual_rejects(value, reason):
    with pytest.raises(CoreError) as e:
        fl.parse_manual(value)
    assert e.value.code == "flatten-target-invalid" and e.value.args_["reason"] == reason


def test_target_wire_records_shift():
    fr = frames_for(lambda t: fl.midi_to_hz(79.5045), 0.6)
    w = fl.auto_target(fr, [(0.0, 0.6)]).wire()
    assert w["name"] == "G♯5" and w["midi"] == 80 and w["originalMidi"] == pytest.approx(79.5045, abs=1e-3)
    assert w["shiftSemitones"] == pytest.approx(0.4955, abs=1e-3)
    assert not math.isnan(w["hz"])


# ---------------------------------------------------------------- 声码器前端


class FakeVocoder:
    """伪 PC-NSF-HiFiGAN：输出长度 = T × 512，内容 = 按 F0 的正弦（检查输入形状与方向）。"""

    def __init__(self) -> None:
        self.calls: list[tuple[tuple[int, ...], tuple[int, ...]]] = []

    def run(self, names, feeds):
        mel, f0 = feeds["mel"], feeds["f0"]
        self.calls.append((mel.shape, f0.shape))
        assert mel.shape[1] == 128 and mel.shape[2] == f0.shape[1]
        t = mel.shape[2]
        hz = np.repeat(f0[0], 512)
        phase = np.cumsum(2 * np.pi * hz / 44100)
        return [(0.3 * np.sin(phase))[None, None].astype(np.float32)]


def test_render_shapes_and_length():
    sr = 48000
    n = 30011
    audio = np.random.default_rng(0).uniform(-0.1, 0.1, (n, 2)).astype(np.float32)
    n44 = round(n * 44100 / sr)
    t = hifigan.frame_count(n44)
    assert t * 512 >= n44 and t == -(-n44 // 512)
    v = FakeVocoder()
    out = hifigan.render(v, audio, sr, np.full(t, 440.0))
    assert out.shape == audio.shape and len(v.calls) == 2  # 每个声道分别做
    assert v.calls[0] == ((1, 128, t), (1, t))
    with pytest.raises(CoreError):
        hifigan.render(v, audio, sr, np.full(t - 1, 440.0))
    # 不足 4 个 hop：补零到 4 个 hop
    assert hifigan.frame_count(100) == 4


def test_log_mel_matches_spec_frontend():
    x = np.sin(2 * np.pi * 440 * np.arange(44100) / 44100)
    mel = hifigan.log_mel(x)
    assert mel.shape == (128, hifigan.frame_count(44100))
    fb = hifigan.mel_filters()
    assert fb.shape == (128, 1025)
    peak_band = int(np.argmax(mel[:, mel.shape[1] // 2]))
    centers = (fb * np.linspace(0, 22050, 1025)).sum(1) / fb.sum(1)
    assert abs(centers[peak_band] - 440) < 60
