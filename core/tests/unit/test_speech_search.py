"""语音检索（规格 09 §9.6，16 R14）：合成索引，数值例子逐条。"""

from __future__ import annotations

import math

import numpy as np
import pytest

from ottosmasher.algo import rhythm as rh
from ottosmasher.algo import speech_search as ss
from ottosmasher.algo import stretch as st
from ottosmasher.core.errors import CoreError

SR = 16000


def row(sample_id: str, specs: list[dict], *, pauses: list[tuple[float, float]] = (), cells: list[int] | None = None,
        window: tuple[float, float] | None = None, segments: list[tuple[int, int]] | None = None) -> ss.SampleIndex:
    """``specs``：每块 {onset, end, 以及可选属性}；``segments``：[(first, stop)] 语段（块序号）。"""
    blocks = [rh.Block(s["onset"], s["end"], s.get("vowel", "a"), (i,), s.get("strength", 0.5)) for i, s in enumerate(specs)]
    ps = [rh.Pause(a, b) for a, b in pauses]
    pseg = rh.pause_segments(blocks, ps)
    win = window or (blocks[0].onset - 0.05, blocks[-1].end + 0.05)
    dur = rh.durations(blocks, ps, win)
    cl = cells if cells is not None else rh.quantize_raw(dur, pseg).cells
    attrs = []
    for s in specs:
        attrs.append(ss.BlockAttr(
            onset=s["onset"], end=s["end"], lead=s.get("lead", s["onset"]), vowel=s.get("vowel", "a"), consonants=tuple(s.get("consonants", ())),
            midi=s.get("midi", 60.0), spread=s.get("spread", 10.0), coverage=s.get("coverage", 1.0), trend=s.get("trend", 0.0),
            rel_pitch=s.get("rel_pitch", 0.0), rel_loud=s.get("rel_loud", 0.0), strength=s.get("strength", 0.5),
            sustain=s.get("sustain", s["end"]), character=s.get("character"), pseg=0, seg=-1,
        ))
    for a, p in zip(attrs, pseg):
        a.pseg = p
    plans = [ss.PlanData(-1, 0, len(blocks), st.Plan(blocks, dur, list(cl), ps, [], win, SR))]
    gaps = []
    if segments:
        cuts = []
        for k, (f, t) in enumerate(segments):
            for i in range(f, t):
                attrs[i].seg = k
            sb = blocks[f:t]
            sw = (sb[0].onset - 0.02, sb[-1].end + 0.02)
            sp = [p for p in ps if p.end > sw[0] and p.start < sw[1]]
            sd = rh.durations(sb, sp, sw)
            sc = rh.quantize_raw(sd, [0] * len(sb)).cells
            plans.append(ss.PlanData(k, f, t, st.Plan(sb, sd, list(sc), sp, [], sw, SR)))
            if k:
                mid = (blocks[f - 1].end + blocks[f].onset) / 2
                cuts.append(rh.Cut(f, "auto", mid, mid))
                gaps.append(blocks[f].onset - blocks[f - 1].end)
        plans[0] = ss.PlanData(-1, 0, len(blocks), st.Plan(blocks, dur, list(cl), ps, cuts, win, SR))
    return ss.SampleIndex(sample_id, attrs, plans, gaps)


def chain(midis: list[float | None], d: float = 0.2, **kw) -> list[dict]:
    return [{"onset": i * d, "end": i * d + d * 0.9, "midi": m, "coverage": None if m is None else 1.0, **kw} for i, m in enumerate(midis)]


def Q(blocks: list[dict], **kw) -> ss.SpeechQuery:
    return ss.parse_query({"blocks": blocks, **kw})


def hits(rows: list[ss.SampleIndex], q: ss.SpeechQuery, bpm: float | None = None) -> list[tuple[str, int]]:
    out = ss.search(rows, q, bpm)
    return [(rows[h.sample].sample_id, h.first) for h in out.hits]


C, E, G = 0, 4, 7


# ---------------------------------------------------------------- R14.1 邻接


def test_ceg_adjacent_ordered_octave_free():
    q = Q([{"pitch": C}, {"pitch": E}, {"pitch": G}])
    r = row("s", chain([60, 64, 79, 72, 76, 67]))
    assert hits([r], q) == [("s", 0), ("s", 3)]
    r = row("s", chain([60, 64, 79, 72, 61, 76, 67]))  # 中间插入 61
    assert hits([r], q) == [("s", 0)]
    r = row("s", chain([60, 64, None]))  # 末块音高未知
    assert hits([r], q) == []


# ---------------------------------------------------------------- R14.2


def test_octave_consonants_pause_and_edge_basis():
    r = row("s", chain([60, 72]))
    assert hits([r], Q([{"pitch": C, "octave": 4}])) == [("s", 0)]
    assert hits([r], Q([{"pitch": C, "octave": 5}])) == [("s", 1)]
    k = row("s", [{"onset": 0.0, "end": 0.2, "consonants": ["k"]}, {"onset": 0.3, "end": 0.5, "consonants": []},
                  {"onset": 0.6, "end": 0.8, "consonants": ["k", "y"]}])
    assert hits([k], Q([{"consonants": ["k"]}])) == [("s", 0)]
    assert hits([k], Q([{"consonants": []}])) == [("s", 1)]
    assert hits([k], Q([{"consonants": ["k", "y"]}])) == [("s", 2)]
    # 停顿把两块分在不同停顿段：默认不跨停顿；允许跨停顿 + 最大间隔 0.1 也不行（间隔 0.5）
    p = row("s", [{"onset": 0.0, "end": 0.2}, {"onset": 0.7, "end": 0.9}], pauses=[(0.25, 0.65)])
    two = [{"vowel": "a"}, {"vowel": "a"}]
    assert hits([p], Q(two)) == []
    assert hits([p], Q(two, cross=True)) == [("s", 0)]
    assert hits([p], Q(two, cross=True, maxGap=0.1)) == []
    # 首尾依据：停顿段（第二块是停顿段的第一块 → 句首）/ 整个采样（只有采样第一块）
    assert hits([p], Q([{"vowel": "a"}], edge="head")) == [("s", 0), ("s", 1)]
    assert hits([p], Q([{"vowel": "a"}], edge="head", edgeBasis="sample")) == [("s", 0)]
    assert hits([p], Q([{"vowel": "a"}], edge="tail", edgeBasis="sample")) == [("s", 1)]


def test_max_gap_definition():
    r = row("s", [{"onset": 1.0, "end": 1.5}, {"onset": 2.0, "end": 2.3}])  # 结束 1.5、下一锚点 2.0 → 0.5
    two = [{}, {}]
    assert hits([r], Q(two, cross=True, maxGap=0.4)) == []
    assert hits([r], Q(two, cross=True, maxGap=0.5)) == [("s", 0)]


# ---------------------------------------------------------------- R14.4–R14.5


def test_tolerance_coverage_duration_unknowns():
    r = row("s", chain([60.49]))  # 偏 49 音分
    assert hits([r], Q([{"pitch": C, "pitchTolerance": 48}])) == []
    assert hits([r], Q([{"pitch": C, "pitchTolerance": 50}])) == [("s", 0)]
    cov = row("s", [{"onset": 0, "end": 0.2, "midi": 60, "coverage": 0.49}])
    assert hits([cov], Q([{"pitch": C}])) == []
    assert hits([cov], Q([{"pitch": C, "coverageMin": 0.4}])) == [("s", 0)]
    # 覆盖率没有帧 = 未知，不是 0：下限 0 也不通过
    unk = row("s", [{"onset": 0, "end": 0.2, "midi": 60, "coverage": None}])
    assert hits([unk], Q([{"pitch": C, "coverageMin": 0.0}])) == []
    # 只在给了音高或波动条件时生效
    assert hits([unk], Q([{"vowel": "a"}])) == [("s", 0)]
    # 时值默认按有效持续：min(结束, 持续终点) − 起音
    d = row("s", [{"onset": 0.0, "end": 0.5, "sustain": 0.3}])
    assert hits([d], Q([{"duration": [0.4, None]}])) == []
    assert hits([d], Q([{"duration": [0.4, None], "durationMode": "span"}])) == [("s", 0)]
    nos = row("s", [{"onset": 0.0, "end": 0.5, "sustain": None}])
    assert hits([nos], Q([{"duration": [None, 1.0]}])) == []  # 持续未知时上限也不通过
    st0 = row("s", [{"onset": 0.0, "end": 0.5, "strength": None}])
    assert hits([st0], Q([{"strengthMin": 0.0}])) == []  # 强度未知时 ≥0 也不命中


def test_other_conditions_and_block_score():
    r = row("s", [{"onset": 0, "end": 0.2, "midi": 60.3, "spread": 50, "trend": 1.2, "rel_pitch": -2.5, "rel_loud": 3.0, "character": "character:A"}])
    assert hits([r], Q([{"trend": "up"}])) == [("s", 0)]
    assert hits([r], Q([{"trend": "down"}])) == []
    assert hits([r], Q([{"relPitch": "low"}])) == [("s", 0)]
    assert hits([r], Q([{"relPitch": "low", "relPitchThreshold": 3}])) == []
    assert hits([r], Q([{"loudnessMin": 2}])) == [("s", 0)]
    assert hits([r], Q([{"character": "character:A"}])) == [("s", 0)]
    assert hits([r], Q([{"character": "character:B"}])) == []
    out = ss.search([r], Q([{"pitch": C, "spreadMax": 100}]), None)
    # 逐块分 = |偏差| / max(1, 容差) + 波动 / max(1, 上限) = 30/50 + 50/100
    assert out.hits[0].score == pytest.approx(0.6 + 0.5)


def test_query_validation():
    bad = [
        {"blocks": []},
        {"blocks": [{"octave": 4}]},  # 只填八度不填音名
        {"blocks": [{"pitch": 12}]},
        {"blocks": [{"foo": 1}]},
        {"blocks": [{}], "bar": 1},
        {"blocks": [{"note": [0, 0.5]}, {"note": [0.4, 1.0]}], "strategy": "strict"},  # 重叠
        {"blocks": [{"note": [0, 0.5]}, {"note": [0.5, 1.0]}], "strategy": "strict", "tolerance": 0.25},  # 起拍间距须 > 2 × 容差
        {"blocks": [{"note": [0.5, 0.5]}], "strategy": "rank"},
        {"blocks": [{"note": [0, 5]}], "strategy": "rank", "length": 4},
    ]
    for b in bad:
        with pytest.raises(CoreError) as e:
            ss.parse_query(b)
        assert e.value.code == "speech-query-invalid", b


# ---------------------------------------------------------------- R14.6 持续终点


def test_sustain_end_rules():
    blk = rh.Block(0.1, 0.6, "a", (0,), None)
    times = (np.arange(80) * 160 + 80) / 16000.0
    energy = np.full(80, 1e-3)
    energy[30:40] = 1e-9  # 无声帧缺口：不是停顿，不截断持续
    energy[55:] = 1e-9
    meas = np.ones(80, dtype=bool)
    thr = ss.active_threshold(energy, meas)
    assert ss.sustain_end(blk, [], times, energy, meas, thr, manual=False) == pytest.approx(times[54] + 0.005)
    # 显式停顿截断
    assert ss.sustain_end(blk, [rh.Pause(0.3, 0.45)], times, energy, meas, thr, manual=False) == pytest.approx(0.3)
    # 人工版本取块结束；没有活跃帧为未知
    assert ss.sustain_end(blk, [], times, energy, meas, thr, manual=True) == 0.6
    assert ss.sustain_end(blk, [], times, np.full(80, 1e-12), meas, ss.active_threshold(np.full(80, 1e-12), meas), manual=False) is None


# ---------------------------------------------------------------- R14.7 无 BPM：归一化形状


def x_xx(t0: float = 0.0, beat: float = 0.25) -> list[dict]:
    """x-xx：起音在第 0、2、3 个半拍（beat = 半拍秒数）。"""
    return [{"onset": t0 + k * beat, "end": t0 + k * beat + beat * 0.8} for k in (0, 2, 3)]


XXX_QUERY = [{"note": [0, 0.5]}, {"note": [1.0, 1.5]}, {"note": [1.5, 2.0]}]


def test_shape_without_bpm():
    r = row("s", x_xx())
    q = Q(XXX_QUERY, strategy="strict")
    out = ss.search([r], q, None)
    assert [(h.first, h.evidence.strict) for h in out.hits] == [(0, True)]
    flat = row("f", [{"onset": k * 0.25, "end": k * 0.25 + 0.2} for k in range(3)])  # 等距：形状不对
    assert ss.search([flat], q, None).hits == []
    rank = ss.search([flat], Q(XXX_QUERY, strategy="rank"), None)
    assert len(rank.hits) == 1 and not rank.hits[0].evidence.strict
    # 占格冲突：中位数平移把窗口前一块的起音推进了第一个音符块 → 非严格
    extra = row("e", [{"onset": 0.92, "end": 0.97}, {"onset": 1.0, "end": 1.3}, {"onset": 1.4, "end": 1.6}, {"onset": 1.65, "end": 2.0}])
    ev = [h.evidence for h in ss.search([extra], Q(XXX_QUERY, strategy="rank"), None).hits if h.first == 1]
    assert ev and ev[0].conflicts == 1 and not ev[0].strict
    # 归一化：实际 [0, 0.4, 0.65]、查询 [0, 0.5, 0.75] → 平移 0.1（= 0.2 拍）、偏差 [0.1, 0, 0]；代价 = 平均 + 冲突数
    assert ev[0].shift == pytest.approx(0.2) and ev[0].cost == pytest.approx(0.1 / 3 + 1)
    # 要求持续但持续未知 → 不命中
    nos = row("n", [dict(b, sustain=None) for b in x_xx()])
    assert ss.search([nos], Q([dict(XXX_QUERY[0], sustain=True)] + XXX_QUERY[1:], strategy="rank"), None).hits == []
    assert ss.search([nos], Q(XXX_QUERY, strategy="rank"), None).hits


# ---------------------------------------------------------------- R14.8 有 BPM：近快 / 近慢


def even_row(sid: str, n: int, d: float) -> ss.SampleIndex:
    return row(sid, [{"onset": i * d, "end": i * d + d * 0.8} for i in range(n)], cells=[1] * n, window=(0.0, n * d + 0.001))


def test_near_fast_slow_selection():
    r = even_row("s", 3, 0.45)  # 120 BPM：近快密度 2（速度 ≈ 1.8）、近慢密度 1（≈ 0.9）
    one = [{"note": [0, 0.25]}]
    sv = ss.schemes_for(r, r.plans[0], 120.0, None)
    fast, slow = sv["near_fast"].speed, sv["near_slow"].speed
    assert sv["near_fast"].density == 2 * sv["near_slow"].density and fast > 1.5 and 0.75 < slow < 1
    assert abs(math.log2(slow)) < abs(math.log2(fast))
    pick = lambda **kw: [h.evidence.plan for h in ss.search([r], Q(one, strategy="rank", **kw), 120.0).hits if h.first == 0]  # noqa: E731
    assert pick(speedPreference=0.1) == ["near_slow"]  # 原速偏好 0.1：离 1 近的
    assert pick(speedPreference=0.1, speedRange=[1.0, fast + 0.05]) == ["near_fast"]  # 倍速范围排除近慢
    assert pick(speedPreference=0.1, speedRange=[1.0, fast - 0.05]) == []  # 上限低于近快：都不行
    assert pick(speedPreference=0.0) == ["near_fast"]  # 同分取近快


def test_strict_shift_fit_and_bpm_scaling():
    # 180 BPM：半拍 = 1/6 秒；x-xx 正好落拍
    beat = 60 / 180 / 2
    r = row("s", x_xx(beat=beat), cells=[2, 1, 1], window=(0.0, 4 * beat))
    q = Q(XXX_QUERY, strategy="strict", edge="tail")
    out = ss.search([r], q, 180.0)
    assert len(out.hits) == 1
    ev = out.hits[0].evidence
    assert ev.strict and ev.error == pytest.approx(0.0, abs=0.02) and ev.plan in ("near_fast", "near_slow")
    # 完全拟合也计入形变与速度代价（R14.11）
    assert ev.cost >= ev.error
    assert ev.cost == pytest.approx(ev.error + ss.DEFORM_WEIGHT * ev.deform + 0.1 * abs(math.log2(ev.speed)))
    # BPM 只缩放秒数不改密度：同一节奏型在 90 BPM 下秒数加倍、密度不变
    r2 = row("t", x_xx(beat=2 * beat), cells=[2, 1, 1], window=(0.0, 8 * beat))
    ev2 = ss.search([r2], q, 90.0).hits[0].evidence
    assert ev2.density == ev.density and ev2.speed == pytest.approx(ev.speed, rel=1e-3)
    # 纯函数：再算一次结果相同
    assert ss.search([r], q, 180.0).hits == out.hits


def test_strict_note_blocks_half_open_and_no_extra_onsets():
    beat = 0.25  # 120 BPM 的半拍
    # 第一块音符 [0, 0.5) 拍里多出一个起音 → 必须满足节奏不命中
    extra = row("e", [{"onset": 0.0, "end": 0.1}, {"onset": 0.125, "end": 0.2}, {"onset": 2 * beat, "end": 2.8 * beat}, {"onset": 3 * beat, "end": 3.8 * beat}],
                cells=[1, 3, 2, 2], window=(0.0, 4 * beat))
    q = Q(XXX_QUERY, strategy="strict")
    got = [h.first for h in ss.search([extra], q, 120.0).hits]
    assert 0 not in got
    # 必需音块固定对应：窗口 1–3 的形状对不上就不命中，不会跳到别处（R14.9）
    assert all(h.evidence.strict for h in ss.search([extra], q, 120.0).hits)


def test_shift_fit_details():
    # 平移落在 [a − y, b − y) 时 y 进了音符块；可行平移里取（平均误差, 最大误差, |平移|）最小
    fit = ss._shift_fit([0.0, 1.0], [], [(0.0, 0.5), (1.0, 1.5)], 0.1, -math.inf)
    assert fit == (0.0, 0.0, 0.0)
    fit = ss._shift_fit([0.05, 1.05], [], [(0.0, 0.5), (1.0, 1.5)], 0.1, -math.inf)
    assert fit[0] == pytest.approx(-0.05) and fit[1] == pytest.approx(0.0)
    assert ss._shift_fit([0.0, 1.3], [], [(0.0, 0.5), (1.0, 1.5)], 0.1, -math.inf) is None
    # 另一个起音 0.3 会落进 [0, 0.5)：除非平移把它推出去（且不超容差）→ 不可行
    assert ss._shift_fit([0.0, 1.0], [0.3], [(0.0, 0.5), (1.0, 1.5)], 0.1, -math.inf) is None
    # 持续到块尾的下界
    assert ss._shift_fit([0.0], [], [(0.0, 0.5)], 0.1, 0.05)[0] == pytest.approx(0.05)


def test_any_power_of_two_density_in_strict_path():
    # 极短音块：近快密度 ≥ 16 的候选照样参与（K1）
    d = 0.012
    r = row("s", [{"onset": i * d, "end": i * d + d * 0.8} for i in range(3)], cells=[1, 1, 1], window=(0.0, 3 * d + 0.001))
    sv = ss.schemes_for(r, r.plans[0], 120.0, None)
    assert sv["near_fast"].density >= 16
    dens = sv["near_fast"].density
    q = Q([{"note": [0, 0.5 / dens * 2]}, {"note": [1 / dens, 1.5 / dens]}, {"note": [2 / dens, 2.5 / dens]}], strategy="strict", tolerance=0.1 / dens)
    out = ss.search([r], q, 120.0)
    assert [(h.first, h.evidence.plan, h.evidence.density, h.evidence.strict) for h in out.hits] == [(0, "near_fast", dens, True)]


# ---------------------------------------------------------------- 范围：整句和语段


def test_segment_scope_and_rest_adjust():
    beat = 0.25
    # 两个语段：[0,1] 块 0–1，[2,3] 块 2–3；段间停顿 0.6 秒
    specs = [{"onset": 0.0, "end": 0.2}, {"onset": 0.25, "end": 0.45}, {"onset": 1.1, "end": 1.3}, {"onset": 1.35, "end": 1.55}]
    r = row("s", specs, pauses=[(0.5, 1.05)], segments=[(0, 2), (2, 4)])
    two = [{"note": [0, 0.4]}, {"note": [0.5, 0.9]}]
    seg_only = ss.search([r], Q(two, strategy="rank", scope="segment"), 120.0)
    assert {h.first for h in seg_only.hits} == {0, 2} and all(h.evidence.scope >= 0 for h in seg_only.hits)
    sent = ss.search([r], Q(two, strategy="rank", scope="sentence"), 120.0)
    assert all(h.evidence.scope == -1 for h in sent.hits)
    # 跨语段的窗口（块 1–2）只有整句范围能算；段间休止调整只改段间整数休止
    cross = Q([{"note": [0, 0.4]}, {"note": [1.0, 1.4]}], strategy="rank", scope="sentence", cross=True)
    base = [h for h in ss.search([r], cross, 120.0).hits if h.first == 1]
    adj = [h for h in ss.search([r], Q([{"note": [0, 0.4]}, {"note": [1.0, 1.4]}], strategy="rank", scope="sentence", cross=True, restAdjust=True), 120.0).hits if h.first == 1]
    assert base and adj
    assert adj[0].evidence.error <= base[0].evidence.error + 1e-9
    if adj[0].evidence.changed:
        assert all(1 <= v <= 32 for v in adj[0].evidence.rests)
        assert adj[0].evidence.cost == pytest.approx(adj[0].evidence.error + adj[0].evidence.conflicts + ss.REST_WEIGHT * adj[0].evidence.changed
                                                     + 0.1 * abs(math.log2(adj[0].evidence.speed)))


def test_rest_combos_bounded_and_default_first():
    beat = 0.25
    specs = [{"onset": 0.0 + 0.6 * k, "end": 0.2 + 0.6 * k} for k in range(5)]
    pauses = [(0.25 + 0.6 * k, 0.55 + 0.6 * k) for k in range(4)]
    r = row("s", specs, pauses=pauses, segments=[(k, k + 1) for k in range(5)])
    sv = ss.schemes_for(r, r.plans[0], 120.0, None)["near_fast"]
    onset_beat = [c.beat for c in sv.cps if c.kind == "onset"]
    notes = [(k * 1.0, k * 1.0 + 0.4) for k in range(5)]
    combos = ss._rest_combos(r, r.plans[0], 0, 5, sv, notes, onset_beat)
    assert 1 < len(combos) <= ss.REST_COMBOS_MAX
    assert combos[0][1] == 0 and combos[0][2] == onset_beat  # 默认（不改）在第一个


# ---------------------------------------------------------------- 结果顺序


def test_result_order_and_one_hit_per_window():
    a = row("a", chain([60.4, 60.0]))
    b = row("b", chain([60.1]))
    out = ss.search([a, b], Q([{"pitch": C}]), None)
    assert [(a_b.sample, a_b.first) for a_b in out.hits] == [(0, 1), (0, 0), (1, 0)]  # a 的最好分 0 < b 的 0.2；采样内按分数


def test_build_index_from_rhythm_analysis():
    ph = [rh.Phone("k", 0.0, 0.05), rh.Phone("a", 0.05, 0.25), rh.Phone("pau", 0.25, 0.75), rh.Phone("t", 0.75, 0.8), rh.Phone("a", 0.8, 1.0),
          rh.Phone("cl", 1.0, 1.05), rh.Phone("k", 1.05, 1.1), rh.Phone("o", 1.1, 1.3)]
    blocks = rh.group_blocks(ph)
    pauses = [rh.Pause(0.3, 0.7)]
    pseg = rh.pause_segments(blocks, pauses)
    cuts = rh.find_cuts(blocks, pauses, ph)
    window = (0.0, 1.35)
    segs = rh.segments(blocks, cuts, window)
    dur = rh.durations(blocks, pauses, window)
    raw = rh.quantize_raw(dur, pseg)
    attrs = [{"midi": 60.0, "spreadCents": 5.0, "coverage": 1.0, "trend": 0.0, "relPitch": 0.0, "relLoudness": 0.0, "consonants": rh.leading_consonants(ph, b)} for b in blocks]
    idx = ss.build_index("s", ph, blocks, pauses, pseg, cuts, segs, dur, raw.cells, window, SR, attrs, [b.end for b in blocks], [None] * 3, {}, 1.0)
    assert [b.consonants for b in idx.blocks] == [("k",), ("t",), ("k",)]  # 促音 cl 不计入
    assert [b.lead for b in idx.blocks] == [0.0, 0.75, 1.05]
    assert [b.pseg for b in idx.blocks] == [0, 1, 1]
    assert [b.seg for b in idx.blocks] == [0, 1, 1]
    assert [(p.scope, p.first, p.stop) for p in idx.plans] == [(-1, 0, 3), (0, 0, 1), (1, 1, 3)]
    # 检索直接可用
    out = ss.search([idx], Q([{"consonants": ["t"], "vowel": "a"}, {"consonants": ["k"], "vowel": "o"}]), None)
    assert [(h.first, h.start, h.end) for h in out.hits] == [(1, 0.75, 1.3)]
