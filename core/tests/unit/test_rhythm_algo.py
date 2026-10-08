"""节奏算法（规格 09 §9.2–§9.4、16 R12；mora 参考校准已由所有者 2026-10-08 去掉，R12.8 不再适用）：数值例子逐条。"""

from __future__ import annotations

import numpy as np
import pytest

from ottosmasher.algo import rhythm as rh
from ottosmasher.core.errors import CoreError


def seq(labels: str, step: float = 0.1, t0: float = 0.0, moras: list[int | None] | None = None) -> list[rh.Phone]:
    out = []
    for i, lab in enumerate(labels.split()):
        out.append(rh.Phone(lab, round(t0 + i * step, 6), round(t0 + (i + 1) * step, 6), None if moras is None else moras[i]))
    return out


def n_blocks(labels: str) -> int:
    return len(rh.group_blocks(seq(labels)))


# ---------------------------------------------------------------- 音块（§9.2、R12.1、R12.2、R12.9）


@pytest.mark.parametrize(
    "labels,count",
    [("ch i i i", 1), ("k a i", 1), ("k u i", 1), ("e i", 1), ("o u", 1), ("k a N", 1), ("a N i", 2), ("a SP a", 2), ("k a k a", 2)],
)
def test_grouping_examples(labels, count):
    assert n_blocks(labels) == count


def test_unvoiced_vowels_count_as_vowels_and_n_only_block_has_unknown_vowel():
    b = rh.group_blocks(seq("k I a"))
    assert len(b) == 1 and b[0].vowel == "i"
    b = rh.group_blocks(seq("s N"))
    assert len(b) == 1 and b[0].vowel is None


def test_manual_split_and_gap_limits():
    # 同一元音重复默认合成一块；人工“在第 3 个音素之前”拆开
    assert len(rh.group_blocks(seq("ch i i i"))) == 1
    assert len(rh.group_blocks(seq("ch i i i"), splits=[3])) == 2
    # 与前一块末尾的间隔：35 ms 内合并，超过就另起一块；−1 ms 的重叠仍合并
    p = [rh.Phone("a", 0.0, 0.1), rh.Phone("i", 0.135, 0.2)]
    assert len(rh.group_blocks(p)) == 1
    p = [rh.Phone("a", 0.0, 0.1), rh.Phone("i", 0.137, 0.2)]
    assert len(rh.group_blocks(p)) == 2
    p = [rh.Phone("a", 0.0, 0.1), rh.Phone("i", 0.099, 0.2)]
    assert len(rh.group_blocks(p)) == 1


def test_block_fields_and_long_vowel_sokuon_no_new_onset():
    ph = [rh.Phone("y", 0.0, 0.05), rh.Phone("a", 0.05, 0.2, strength=0.4), rh.Phone("cl", 0.2, 0.3), rh.Phone("t", 0.3, 0.35),
          rh.Phone("a", 0.35, 0.5, strength=1.0), rh.Phone("a", 0.5, 0.9, strength=0.7)]
    b = rh.group_blocks(ph)
    assert [(x.onset, x.end, x.vowel, x.members, x.strength) for x in b] == [(0.05, 0.2, "a", (1,), 0.4), (0.35, 0.9, "a", (4, 5), 1.0)]
    assert rh.leading_consonant_start(ph, b[0]) == 0.0
    # 促音 cl 不计入前导辅音（09 §9.6.3〔新：19 G3〕）
    assert rh.leading_consonant_start(ph, b[1]) == 0.3


def test_block_limits():
    with pytest.raises(CoreError) as e:
        rh.group_blocks(seq(" ".join(["k a"] * 129), step=0.01))
    assert e.value.code == "rhythm-too-many-blocks"
    with pytest.raises(CoreError) as e:
        rh.group_blocks([rh.Phone("a", 0.5, 0.6), rh.Phone("k", 0.6, 0.7), rh.Phone("a", 0.5, 0.8)])
    assert e.value.code == "rhythm-onsets-not-increasing"


# ---------------------------------------------------------------- 停顿（§9.3.1、R12.3）


def tone(total: float, sr: int = 16000, quiet: list[tuple[float, float, float]] = ()) -> np.ndarray:
    t = np.arange(round(total * sr)) / sr
    x = 0.5 * np.sin(2 * np.pi * 220 * t)
    for a, b, g in quiet:
        x[round(a * sr) : round(b * sr)] *= g
    return x


def test_pause_inside_phoneme_low_level_core():
    x = tone(1.0, quiet=[(0.3, 0.45, 0.002)])
    p = rh.detect_pauses(x, 16000, 0.0, [rh.Phone("a", 0.0, 1.0)])
    assert [(q.start, q.end) for q in p] == [(0.32, 0.43)]


def test_pause_zeroed_second_and_window_offset():
    x = tone(3.0, quiet=[(1.0, 2.0, 0.0)])
    p = rh.detect_pauses(x, 16000, 10.0, [rh.Phone("a", 10.0, 11.0), rh.Phone("a", 12.0, 13.0)])
    assert [(q.start, q.end) for q in p] == [(11.02, 11.98)]


def test_pause_label_with_sound_is_not_a_pause_and_sokuon_closure_is_not():
    x = tone(1.0)
    assert rh.detect_pauses(x, 16000, 0.0, [rh.Phone("a", 0, 0.4), rh.Phone("SP", 0.4, 0.6), rh.Phone("a", 0.6, 1.0)]) == []
    x = tone(1.0, quiet=[(0.4, 0.6, 0.0)])
    assert rh.detect_pauses(x, 16000, 0.0, [rh.Phone("a", 0, 0.4), rh.Phone("cl", 0.4, 0.6), rh.Phone("a", 0.6, 1.0)]) == []


def test_pause_sensitivity_length_and_clip_to_phonemes():
    x = tone(1.0, quiet=[(0.4, 0.5, 0.0)])  # 0.10 秒：灵敏度 1 时太短，灵敏度 2 时够（0.06）
    ph = [rh.Phone("a", 0, 1.0)]
    assert rh.detect_pauses(x, 16000, 0.0, ph, 1.0) == []
    assert [(q.start, q.end) for q in rh.detect_pauses(x, 16000, 0.0, ph, 2.0)] == [(0.42, 0.48)]
    # 窗口两头的安静（首个音素之前）裁掉后太短 → 不是停顿
    x = tone(1.0, quiet=[(0.0, 0.2, 0.0)])
    assert rh.detect_pauses(x, 16000, 0.0, [rh.Phone("a", 0.15, 1.0)]) == []
    with pytest.raises(CoreError):
        rh.detect_pauses(x, 16000, 0.0, ph, 3.0)


def test_pause_segment_index():
    blocks = rh.group_blocks(seq("a k a k a k a", step=0.2))
    pauses = [rh.Pause(0.25, 0.35), rh.Pause(0.9, 1.1)]
    assert rh.pause_segments(blocks, pauses) == [0, 1, 1, 2]


# ---------------------------------------------------------------- 语段（§9.3.3、R12.4、R12.5）


def sentence_with_gap(gap: tuple[float, float], labels_gap: str = "pau"):
    """整句 10–12.4：k a k a | 间隙 | k a k a（相对 10 秒）。"""
    g0, g1 = 10 + gap[0], 10 + gap[1]
    left = [("k", 10.0, 10.2), ("a", 10.2, 10.45), ("k", 10.45, 10.55), ("a", 10.55, g0)]
    right = [("k", g1, g1 + 0.1), ("a", g1 + 0.1, g1 + 0.4), ("k", g1 + 0.4, g1 + 0.5), ("a", g1 + 0.5, 12.4)]
    mid = [(labels_gap, g0, g1)] if labels_gap else []
    ph = [rh.Phone(l, a, b) for l, a, b in left + mid + right]
    x = tone(2.4, quiet=[(gap[0], gap[1], 0.0)])
    return ph, x


def test_acoustic_gap_splits_sentence_at_pause_midpoint():
    ph, x = sentence_with_gap((0.70, 1.35))
    blocks = rh.group_blocks(ph)
    pauses = rh.detect_pauses(x, 16000, 10.0, ph)
    cuts = rh.find_cuts(blocks, pauses, ph)
    assert [(c.k, c.kind, c.left_end) for c in cuts] == [(2, "auto", 11.025)]
    segs = rh.segments(blocks, cuts, (10.0, 12.4))
    assert [(s.start, s.end, s.first, s.stop) for s in segs] == [(10.0, 11.025, 0, 2), (11.025, 12.4, 2, 4)]


def test_model_blank_and_short_gap_do_not_split():
    # 模型标了停顿但实际有声（0.65 秒的模型空白）→ 不切
    ph, _ = sentence_with_gap((0.70, 1.35))
    x = tone(2.4)
    blocks = rh.group_blocks(ph)
    assert rh.find_cuts(blocks, rh.detect_pauses(x, 16000, 10.0, ph), ph) == []
    # 0.15 秒的声学停顿 → 不切
    ph, x = sentence_with_gap((0.70, 0.85))
    blocks = rh.group_blocks(ph)
    assert rh.find_cuts(blocks, rh.detect_pauses(x, 16000, 10.0, ph), ph) == []


def test_manual_cut_merge_and_first_block():
    ph, x = sentence_with_gap((0.70, 1.35))
    blocks = rh.group_blocks(ph)
    pauses = rh.detect_pauses(x, 16000, 10.0, ph)
    # 手动合并 = 抑制自动切口
    cuts = rh.find_cuts(blocks, pauses, ph, merges=[2])
    assert cuts[0].merged and rh.segments(blocks, cuts, (10.0, 12.4)) == []
    # 手动切分：左侧取前一块结束，右侧取下一块的前导辅音开始（辅音归右）
    cuts = rh.find_cuts(blocks, pauses, ph, manual=[1], merges=[2])
    assert [(c.k, c.kind, c.left_end, c.right_start) for c in cuts if not c.merged] == [(1, "manual", 10.45, 10.45)]
    # 阈值改了 → 切口变了（语段身份随之变）
    assert rh.find_cuts(blocks, pauses, ph, threshold=0.7) == []
    with pytest.raises(CoreError) as e:
        rh.find_cuts(blocks, pauses, ph, manual=[0])
    assert e.value.code == "rhythm-cut-invalid"


def test_segment_mora_renumbered_and_unknown():
    ph = seq("k a k a pau s o r e", moras=[0, 0, 1, 1, None, 2, 2, 3, 3])
    assert rh.mora_span(ph, (0.0, 0.4)) == (0, 2)
    assert rh.mora_span(ph, (0.5, 0.9)) == (2, 2)  # 从 0 重新编号：首 mora 2，共 2 个
    ph2 = seq("k a k a", moras=[0, 0, None, 1])
    assert rh.mora_span(ph2, (0.0, 0.4)) is None


# ---------------------------------------------------------------- 时值（§9.4.1）


def test_durations_rest_and_last_block():
    blocks = [rh.Block(0.0, 0.1, "a", (0,), None), rh.Block(0.3, 0.35, "a", (1,), None)]
    d = rh.durations(blocks, [rh.Pause(0.12, 0.28)], (0.0, 1.0))
    assert d.intervals == [(0.0, 0.3), (0.3, 0.35)]
    assert d.rest == pytest.approx([0.16, 0.0]) and d.dur == pytest.approx([0.14, 0.05])
    # 末块终点 = min(max(末块结束, 起音 + 1 ms), 窗口终点 − 1 ms)；休止最多扣到只剩 5 ms
    d = rh.durations([rh.Block(0.5, 0.5, "a", (0,), None)], [], (0.0, 1.0))
    assert d.intervals == [(0.5, 0.501)] and d.dur == [0.005]
    d = rh.durations([rh.Block(0.0, 0.9, "a", (0,), None)], [rh.Pause(0.0, 0.95)], (0.0, 0.92))
    assert d.intervals[0][1] == pytest.approx(0.9) and d.dur == pytest.approx([0.005])


# ---------------------------------------------------------------- 量化（§9.4.3、R12.6–R12.8、R12.10）


def dur_of(ds, rest=None) -> rh.Durations:
    t, iv = 0.0, []
    rest = rest or [0.0] * len(ds)
    for d, r in zip(ds, rest):
        iv.append((t, t + d + r))
        t += d + r
    return rh.Durations(iv, list(rest), list(ds))


def test_raw_route_reference_example():
    q = rh.quantize_raw(dur_of([0.11, 0.22, 0.10, 0.32, 0.11]), [0] * 5)
    assert q.cells == [1, 2, 1, 3, 1]
    assert q.tick == pytest.approx(0.11, abs=0.025)
    assert q.alternatives[0] == q.cells and 1 <= len(q.alternatives) <= 3
    assert len({tuple(a) for a in q.alternatives}) == len(q.alternatives)


@pytest.mark.parametrize("ds", [[0.2], [0.2, 0.4], [0.15, 0.3, 0.15]])
def test_short_sentences_have_a_scheme(ds):
    q = rh.quantize_raw(dur_of(ds), [0] * len(ds))
    assert q.cells and len(q.cells) == len(ds) and all(n >= 1 for n in q.cells)


def test_tiny_interval_does_not_force_fine_grid():
    # 尺子下限 = max(0.015, 中位时值 / 5)：11 ms 的间隔不会把尺子拉到 11 ms 那么细
    q = rh.quantize_raw(dur_of([0.2, 0.011, 0.2, 0.2, 0.4]), [0] * 5)
    assert q.tick >= 0.04 - 1e-9 and q.cells[1] == 1


def test_inserted_pause_keeps_cells_and_counts_rest_separately():
    def build(gap: float):
        on = [0.0, 0.11, 0.33, 0.43 + gap, 0.75 + gap]
        blocks = [rh.Block(o, o + 0.08, "a", (i,), None) for i, o in enumerate(on)]
        pauses = [rh.Pause(0.40, 0.40 + gap)] if gap else []
        d = rh.durations(blocks, pauses, (0.0, 0.86 + gap))
        return d, rh.pause_segments(blocks, pauses)

    d0, s0 = build(0.0)
    d1, s1 = build(1.0)
    q0, q1 = rh.quantize_raw(d0, s0), rh.quantize_raw(d1, s1)
    assert q0.cells == q1.cells
    assert d1.rest[2] == pytest.approx(1.0) and d1.dur == pytest.approx(d0.dur)
    b = rh.target_beats(q1.cells, d1, 2)
    assert b.rest_cells[2] >= 1 and sum(b.rest_cells) == b.rest_cells[2]


def test_penalty_scales_complexity_and_range():
    d = dur_of([0.1, 0.1, 0.43, 0.1])
    assert rh.quantize_raw(d, [0] * 4, penalty=0).cells == rh.quantize_raw(d, [0] * 4, penalty=0.0).cells
    with pytest.raises(CoreError):
        rh.quantize_raw(d, [0] * 4, penalty=3.5)


def test_manual_cells_lock_only_changed_blocks():
    d = dur_of([0.11, 0.22, 0.10, 0.32, 0.11])
    q = rh.quantize_raw(d, [0] * 5, manual={1: 3})
    assert q.cells[1] == 3 and q.cells[3] >= 2
    with pytest.raises(CoreError):
        rh.quantize_raw(d, [0] * 5, manual={1: 65})


def test_pure_mora_route_and_long_vowel_fill():
    # や っ た ー：促音、长音的 mora 计入前一块
    ph = [rh.Phone("y", 0, 0.05, 0), rh.Phone("a", 0.05, 0.2, 0), rh.Phone("cl", 0.2, 0.3, 1), rh.Phone("t", 0.3, 0.35, 2),
          rh.Phone("a", 0.35, 0.5, 2), rh.Phone("a", 0.5, 0.9, 3)]
    blocks = rh.group_blocks(ph)
    span = rh.mora_span(ph, (0.0, 0.9))
    mc = rh.mora_cells(ph, blocks, span)
    assert mc == [2, 2]
    d = rh.durations(blocks, [], (0.0, 0.9))
    assert rh.quantize_mora(d, blocks, ph, [], mc).cells == [2, 2]
    # 长音补格：拖长的元音只加格、不加起音
    ph = []
    for i in range(3):
        ph += [rh.Phone("k", 0.2 * i, 0.2 * i + 0.05, i), rh.Phone("a", 0.2 * i + 0.05, 0.2 * i + 0.2, i)]
    ph += [rh.Phone("k", 0.6, 0.65, 3), rh.Phone("a", 0.65, 1.45, 3)]
    blocks = rh.group_blocks(ph)
    mc = rh.mora_cells(ph, blocks, rh.mora_span(ph, (0.0, 1.5)))
    d = rh.durations(blocks, [], (0.0, 1.5))
    assert rh.quantize_mora(d, blocks, ph, [], mc).cells == [1, 1, 1, 1]
    filled = rh.quantize_mora(d, blocks, ph, [], mc, long_vowel=True)
    assert filled.cells == [1, 1, 1, 4] and len(blocks) == 4


def test_pure_mora_missing_is_explicitly_unavailable_but_raw_still_works():
    ph = [rh.Phone("a", 0, 0.2, 0), rh.Phone("a", 0.4, 0.6, None), rh.Phone("a", 0.8, 1.0, 2)]
    blocks = rh.group_blocks(ph)
    mc = rh.mora_cells(ph, blocks, rh.mora_span(ph, (0.0, 1.0)))
    d = rh.durations(blocks, [], (0.0, 1.0))
    q = rh.quantize_mora(d, blocks, ph, [], mc)
    assert q.cells is None and q.unavailable == "mora-missing"
    assert rh.quantize_raw(d, [0, 0, 0]).cells
    # 缺 mora 时可以手动填占格（不伪造 mora 数）
    assert rh.quantize_mora(d, blocks, ph, [], [None, None, None], manual={0: 2, 1: 2, 2: 1}).cells == [2, 2, 1]


# ---------------------------------------------------------------- 目标拍（§9.4.4）


def test_target_beats_and_ratio():
    d = dur_of([0.25, 0.5, 0.25], rest=[0.0, 0.25, 0.0])
    b = rh.target_beats([1, 2, 1], d, 2)
    assert b.tick == pytest.approx(0.25) and b.rest_cells == [0, 1, 0]
    assert b.onsets == [0.0, 0.5, 2.0] and b.tail == 2.5
    assert rh.overall_ratio(b, d, 0.5) == pytest.approx(4 / 2 * 0.5 / 1.0)
