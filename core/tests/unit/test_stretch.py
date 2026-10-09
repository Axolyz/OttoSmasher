"""卡拍（规格 09 §9.5、16 R13）：候选密度、原速、映射、渲染。渲染用本机 Rubber Band（找不到就跳过）。"""

from __future__ import annotations

import shutil

import numpy as np
import pytest

from ottosmasher.algo import rhythm as rh
from ottosmasher.algo import stretch as st
from ottosmasher.core.errors import CoreError
from ottosmasher.media import stretch as render

SR = 16000
need_rb = pytest.mark.skipif(shutil.which("rubberband") is None, reason="rubberband not installed")


def plan_of(onsets, ends, window, cells=None, pauses=(), cuts=(), sr=SR) -> st.Plan:
    blocks = [rh.Block(a, b, "a", (i,), None) for i, (a, b) in enumerate(zip(onsets, ends))]
    dur = rh.durations(blocks, list(pauses), window)
    if cells is None:
        cells = rh.quantize_raw(dur, rh.pause_segments(blocks, list(pauses))).cells
    return st.Plan(blocks, dur, cells, list(pauses), list(cuts), window, sr)


def even(n=4, d=0.25, t0=0.0):
    on = [t0 + d * i for i in range(n)]
    return plan_of(on, [o + d for o in on], (t0, t0 + n * d + 0.001), cells=[1] * n)


# ---------------------------------------------------------------- 候选密度（§9.5.1、R13.1）


def test_candidates_reference_example():
    c = st.candidates(even(), 120)
    assert c["near_fast"].density == 2 and c["near_fast"].speed == pytest.approx(1.0, abs=1e-9)
    assert c["near_slow"].density == 1 and c["near_slow"].speed < 1
    assert c["double"].density == 4 and c["double"].speed > 1


def test_very_short_blocks_density_above_8():
    c = st.candidates(even(n=4, d=0.015), 120)
    assert c["near_fast"].density > 8 and c["near_fast"].speed >= 1 - 1e-5
    assert c["near_slow"].speed < 1


def test_bpm_range():
    with pytest.raises(CoreError) as e:
        st.candidates(even(), 10)
    assert e.value.code == "bpm-invalid"


# ---------------------------------------------------------------- 原速（R13.2）


def irregular(gap: float = 0.0):
    on = [0.1, 0.21, 0.43, 0.53 + gap, 0.85 + gap]
    pauses = [rh.Pause(0.48, 0.48 + gap)] if gap else []
    return plan_of(on, [o + 0.09 for o in on], (0.0, 1.0 + gap), pauses=pauses)


@pytest.mark.parametrize("gap", [0.0, 1.0])
def test_original_speed_is_one_even_with_inserted_pause(gap):
    c = st.candidates(irregular(gap), None)
    assert c["near_fast"].speed == pytest.approx(1.0, abs=1e-3)
    assert st.BPM_RANGE[0] <= c["near_fast"].bpm <= st.BPM_RANGE[1]
    assert c["near_slow"].bpm == c["near_fast"].bpm and c["near_slow"].density == c["near_fast"].density / 2


def test_rest_change_does_not_change_speech_speed():
    # 停顿变长 → 休止格变多，语音部分的映射不变（弹性停顿吸收）
    a = st.scheme(irregular(1.0), 2, 150)
    b = st.scheme(irregular(1.7), 2, 150)
    assert a.beats.rest_cells != b.beats.rest_cells
    assert a.speed == pytest.approx(b.speed, rel=1e-6)


# ---------------------------------------------------------------- 映射（§9.5.2、R13.3–R13.6）


def test_map_real_seconds_and_onsets_on_beats():
    s = st.scheme(irregular(), 4, 180)
    m = s.map
    beat = 60 / 180 * SR
    on = [m.onsets[i] for i, c in enumerate(m.cps) if c.kind == "onset"]
    for (cp, f) in zip([c for c in m.cps if c.kind == "onset"], on):
        assert f - on[0] == pytest.approx((cp.beat - m.cps[0].beat) * beat, abs=1)
    # 卡拍后变短：末点目标秒 < 源秒（R13.3：映射图用真实秒数）
    assert s.speed > 1 and m.out_frames < m.src_frames
    # 核心斜率 1、源与目标都严格递增
    for p in m.pieces:
        if p.kind == "core":
            assert p.sb - p.sa == p.tb - p.ta
    assert all(b[0] > a[0] and b[1] > a[1] for a, b in zip(m.knots, m.knots[1:]))


def test_translation_invariance():
    a = st.scheme(irregular(), 2, 150).map
    p = irregular()
    shifted = st.Plan(
        [rh.Block(b.onset + 3.0, b.end + 3.0, b.vowel, b.members, None) for b in p.blocks],
        rh.Durations([(x + 3.0, y + 3.0) for x, y in p.dur.intervals], p.dur.rest, p.dur.dur),
        p.cells, [], [], (3.0, 4.0), SR,
    )
    b = st.scheme(shifted, 2, 150).map
    assert [(x.sa, x.sb, x.ta, x.tb, x.kind) for x in a.pieces] == [(x.sa, x.sb, x.ta, x.tb, x.kind) for x in b.pieces]


def test_long_silence_only_changes_elastic_gap():
    m = st.scheme(irregular(1.0), 2, 150).map
    pause = [p for p in m.pieces if p.kind == "pause"]
    assert len(pause) == 1
    cores = [p for p in m.pieces if p.kind == "core"]
    assert all(c.sb - c.sa == c.tb - c.ta for c in cores)


def test_segment_tail_control_point_pins_voiced_end():
    on = [0.1, 0.3, 1.2, 1.4]
    ends = [0.28, 0.5, 1.38, 1.6]
    pauses = [rh.Pause(0.52, 1.18)]
    cut = rh.Cut(2, "auto", 0.85, 0.85)
    p = plan_of(on, ends, (0.0, 1.7), cells=[1, 1, 1, 1], pauses=pauses, cuts=[cut])
    s = st.scheme(p, 2, 120)
    kinds = [c.kind for c in s.map.cps]
    assert kinds == ["onset", "onset", "segment-tail", "onset", "onset", "tail"]
    tail = s.map.cps[2]
    assert tail.src == pytest.approx(0.5) and tail.beat == pytest.approx(s.beats.onsets[1] + 1 / 2)


def test_output_limit():
    p = plan_of([0.0, 1.0], [0.5, 1.5], (0.0, 2.0), cells=[1, 1])
    with pytest.raises(CoreError) as e:
        st.scheme(p, 2.0**-12, 20)
    assert e.value.code == "rhythm-output-too-long"


# ---------------------------------------------------------------- 渲染（§9.5.3、R13.5–R13.6）


def voice(total: float, onsets, pause=None, sr=SR) -> np.ndarray:
    rng = np.random.default_rng(7)
    t = np.arange(round(total * sr)) / sr
    x = 0.002 * rng.standard_normal(len(t))  # 底噪（弹性间隙里的低电平声音）
    for o in onsets:
        seg = (t >= o) & (t < o + 0.09)
        x[seg] += 0.4 * np.sin(2 * np.pi * 330 * (t[seg] - o))
    return np.stack([x, -x], axis=1).astype(np.float32)


@need_rb
@pytest.mark.parametrize("bpm,density", [(180, 4), (90, 1), (300, 8)])
def test_render_cores_sample_exact_and_gap_kept(bpm, density):
    p = irregular(1.0)
    pcm = voice(2.0, [b.onset for b in p.blocks])
    s = st.scheme(p, density, bpm)
    out = render.render(pcm, s.map)
    assert out.shape == (s.map.out_frames, 2)
    for piece in s.map.pieces:
        if piece.kind == "core":
            assert np.array_equal(out[piece.ta : piece.tb], pcm[piece.sa : piece.sb])
    # 起音样本落在目标帧
    for cp, f in zip(s.map.cps, s.map.onsets):
        if cp.kind == "onset":
            src = int(round((cp.src - p.window[0]) * SR))
            assert out[f, 0] == pcm[src, 0]
    # 弹性间隙里的低电平声音保留（不置零）
    gap = next(x for x in s.map.pieces if x.kind == "pause")
    mid = out[gap.ta + (gap.tb - gap.ta) // 4 : gap.tb - (gap.tb - gap.ta) // 4, 0]
    assert np.sqrt(np.mean(mid**2)) > 1e-4
    assert np.isfinite(out).all()


def test_clicks_follow_onsets_not_beats():
    a = np.zeros((1000, 1), dtype=np.float32)
    only = render.mix_clicks(a, [100, 700], 16000, voice=False)
    nz = np.flatnonzero(np.abs(only[:, 0]) > 1e-6)
    assert nz[0] == 101 and 700 <= nz[-1] < 700 + len(render.click(16000))
    v = render.mix_clicks(np.full((1000, 1), 0.1, np.float32), [100], 16000, voice=True)
    assert v[0, 0] == pytest.approx(0.1)


def test_edge_onset_keeps_its_inner_core():
    # 起音贴着窗口起点（所有者 2026-10-08【基线变更】）：左侧 0，右侧照常保护
    p = plan_of([0.0, 0.25, 0.5, 0.75], [0.25, 0.5, 0.75, 1.0], (0.0, 1.001), cells=[1, 1, 1, 1])
    m = st.scheme(p, 2, 150).map
    first = next(x for x in m.pieces if x.kind == "core")
    assert first.sa == 0 and first.ta == 0 and first.sb - first.sa == round(st.CORE_MAX * SR)


@need_rb
def test_render_edge_onset_is_sample_exact():
    p = plan_of([0.0, 0.25, 0.5, 0.75], [0.2, 0.45, 0.7, 0.95], (0.0, 1.001), cells=[1, 1, 1, 1])
    pcm = voice(1.001, [b.onset for b in p.blocks])
    s = st.scheme(p, 2, 150)
    out = render.render(pcm, s.map)
    assert np.array_equal(out[: round(st.CORE_MAX * SR)], pcm[: round(st.CORE_MAX * SR)])


def test_candidates_memo_equals_fresh_schemes():
    """阶段 7 提速：同一次求解里记住建好的方案、只要近快近慢时不建倍快——结果与逐个新建完全相同。"""
    for plan, bpm in [(even(), 120.0), (even(n=5, d=0.37), 180.0), (irregular(0.6), 97.0), (even(n=4, d=0.015), 120.0)]:
        full = st.candidates(plan, bpm)
        part = st.candidates(plan, bpm, ("near_fast", "near_slow"))
        for name in ("near_fast", "near_slow"):
            fresh = st.scheme(plan, full[name].density, full[name].bpm)
            for s in (full[name], part[name]):
                assert (s.density, s.bpm, s.speed, s.ratio) == (fresh.density, fresh.bpm, fresh.speed, fresh.ratio)
                assert s.map.pieces == fresh.map.pieces and s.map.knots == fresh.map.knots and s.map.onsets == fresh.map.onsets
        assert set(part) == {"near_fast", "near_slow"}
