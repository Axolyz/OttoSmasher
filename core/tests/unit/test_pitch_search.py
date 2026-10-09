"""音高检索（规格 10 §10.2，16 R15；所有者 2026-10-08：完整检索、忽略八度、时长弹性、滑音块）。合成 F0，不跑模型。"""

from __future__ import annotations

import math

import numpy as np
import pytest

from ottosmasher.algo import pitch_search as ps
from ottosmasher.core.errors import CoreError


def hz(midi: float) -> float:
    return 440.0 * 2.0 ** ((midi - 69.0) / 12.0)


def sound(segs: list[tuple[float, float | None]], *, key: str = "a", first: int = 0, spans: list[tuple[float, float]] | None = None,
          lines: list[tuple[float, float]] | None = None, conf: float = 0.9) -> ps.Sound:
    """``segs``：(秒, MIDI 或 None=无声)；MIDI 可以是 (起, 止) 表示线性滑音。``spans``：采样区间（秒，资产局部）；默认整段。"""
    f0, cf, en = [], [], []
    for sec, m in segs:
        n = ps.seconds_to_frames(sec)
        for j in range(n):
            if m is None:
                f0.append(0.0)
                cf.append(0.0)
                en.append(1e-12)
            else:
                mm = m[0] + (m[1] - m[0]) * (j + 0.5) / n if isinstance(m, tuple) else m
                f0.append(hz(mm))
                cf.append(conf)
                en.append(1e-3)
    n = len(f0)
    if spans is None:
        sp = [(first, first + n)]
    else:
        sp = [(math.ceil(a / ps.FRAME - 1e-9), math.floor(b / ps.FRAME + 1e-9)) for a, b in spans]
    return ps.Sound(key, first, np.array(f0, dtype=np.float32), np.array(cf, dtype=np.float32), np.array(en, dtype=np.float32), sp, lines)


def q(*items: tuple) -> ps.Query:
    out = []
    for it in items:
        sec, lo = it[0], it[1]
        d = {"seconds": sec, "low": lo, "high": it[2] if len(it) > 2 and it[2] and not str(it[2]).startswith("->") else None}
        if len(it) > 2 and str(it[2]).startswith("->"):
            d["glide"] = {"low": it[2][2:], "high": None}
        out.append(d)
    return ps.parse_query(out)


def P(**kw: object) -> dict[str, object]:
    return ps.check_params(kw)


def run(sounds: list[ps.Sound], query: ps.Query, **kw: object) -> list[ps.Hit]:
    return ps.search_exact(sounds, query, P(**kw)).hits


# ---------------------------------------------------------------- R15.1 查询编辑


def test_query_frames_and_validation() -> None:
    assert ps.parse_query([{"seconds": 0.404, "low": "A4"}]).blocks[0].frames == 40
    assert ps.parse_query([{"seconds": 0.405, "low": "A4"}]).blocks[0].frames == 41
    cases = [
        ([{"seconds": 0.09, "low": "A4"}], "too-short"),
        ([{"seconds": 6, "low": "A4"}, {"seconds": 4.5, "low": "A4"}], "too-long"),
        ([{"seconds": 0.4, "low": "G5", "high": "C4"}], "range-inverted"),
        ([{"seconds": 0.4, "low": "H4"}], "bad-note"),
        ([], "empty"),
        ([{"seconds": 0.2, "low": "A4"}] * 17, "too-many-blocks"),
    ]
    for items, reason in cases:
        qq, errors = ps.check_blocks(items)
        assert qq is None and reason in [e["reason"] for e in errors], (items, errors)
        with pytest.raises(CoreError) as ei:
            ps.parse_query(items)
        assert ei.value.code == "pitch-query-invalid"
    # 就地提示：每块各自的错误都给出（块号从 1 起）
    _, errors = ps.check_blocks([{"seconds": 0.05, "low": "A4"}, {"seconds": 0.4, "low": "X"}])
    assert [(e["block"], e["reason"]) for e in errors] == [(1, "too-short"), (2, "bad-note")]
    # ♯ 与 #、♭ 与 b 等价；A4 = 69
    a = ps.parse_query([{"seconds": 0.4, "low": "C♯5", "high": "D♭5"}]).blocks[0]
    b = ps.parse_query([{"seconds": 0.4, "low": "C#5", "high": "Db5"}]).blocks[0]
    assert a == b and a.lo == 73
    assert ps.parse_query([{"seconds": 0.4, "low": "A4"}]).blocks[0].lo == 69


def test_text_format_round_trip() -> None:
    items, errors = ps.text_to_blocks("0.40 A4\n0.30 C5..D5\n\n0.5 C5->E5\n0.2 C5..D5→E5\nfoo")
    assert errors == [{"line": 6, "reason": "bad-line"}]
    qq = ps.parse_query(items)
    assert [(b.frames, b.lo, b.hi, b.lo2, b.hi2) for b in qq.blocks] == [
        (40, 69, 69, None, None), (30, 72, 74, None, None), (50, 72, 72, 76, 76), (20, 72, 74, 76, 76),
    ]
    text = ps.blocks_to_text(qq)
    assert ps.parse_query(ps.text_to_blocks(text)[0]) == qq


def test_params_unknown_and_ranges() -> None:
    with pytest.raises(CoreError) as ei:
        ps.check_params({"confidence": 0.3})  # 可靠门槛不能调低：没有这个参数
    assert ei.value.code == "pitch-param-unknown"
    for k, v in [("tolerance", 1300), ("coverage", 1.2), ("maxGap", -1), ("stability", 20000), ("elastic", [0.3, 1.0]), ("elastic", [1.2, 1.1])]:
        with pytest.raises(CoreError) as ei:
            ps.check_params({k: v})
        assert ei.value.code == "pitch-param-invalid", k
    # 句首/句尾只在原片模式
    with pytest.raises(CoreError):
        ps.check_params({"headTolerance": 0.2})
    assert ps.check_params({"headTolerance": 0.2}, mode="sources")["headTolerance"] == 0.2


# ---------------------------------------------------------------- R15.2–R15.6


def test_two_blocks_hit_and_no_hit() -> None:
    s = sound([(0.4, 69), (0.3, 72)])
    hits = run([s], q((0.4, "A4"), (0.3, "C5")))
    assert [(h.start, h.end) for h in hits] == [(0, 70)]
    assert hits[0].score == pytest.approx(0.0, abs=1e-3)
    assert run([s], q((0.4, "F2"))) == []


def test_adjacent_samples_are_not_joined() -> None:
    whole = sound([(1.0, 69)])
    split = sound([(1.0, 69)], spans=[(0.0, 0.5), (0.5, 1.0)])
    assert len(run([whole], q((0.6, "A4")))) == 1
    assert run([split], q((0.6, "A4"))) == []


def test_gap_and_coverage() -> None:
    s = sound([(0.44, 69), (0.13, None), (0.43, 69)])  # 1 秒 A4，中间 130 ms 置信为 0
    assert run([s], q((1.0, "A4"))) == []
    hits = run([s], q((1.0, "A4")), maxGap=0.13)
    assert len(hits) == 1 and hits[0].blocks[0][1] == 87  # 覆盖 0.87
    assert run([s], q((1.0, "A4")), maxGap=0.13, coverage=0.9) == []


def test_loose_screening_never_becomes_a_hit() -> None:
    s = sound([(1.0, 69.8)])  # 偏 80 音分
    assert run([s], q((0.5, "A4"))) == []
    assert ps.search_approx([s], q((0.5, "A4")), P()).hits == []
    assert len(run([s], q((0.5, "A4")), tolerance=81)) == 1


def test_long_note_is_one_hit_separated_regions_are_two() -> None:
    s = sound([(10.0, 69), (1.0, None), (10.0, 69)])
    hits = run([s], q((1.0, "A4")))
    assert len(hits) == 2
    # 同分取起点早的：窗口可以带着 ≤ 最长缺口的静音开头（覆盖仍 ≥ 0.8）
    assert hits[0].start == 0 and hits[1].start == 1100 - 12


def test_tolerance_band_and_score() -> None:
    s = sound([(0.5, 69.3)])  # 偏 30 音分：带内（容差 50）但分数 = 30
    hits = run([s], q((0.5, "A4")))
    assert len(hits) == 1 and hits[0].score == pytest.approx(30.0, abs=1e-3)
    s2 = sound([(0.5, 69.4)])
    best = run([s, ps.Sound("b", 0, s2.f0, s2.conf, s2.energy, s2.spans)], q((0.5, "A4")))
    assert [h.sound for h in best] == [0, 1]  # 分数低的在前
    rng = sound([(0.5, 70.5)])
    assert len(run([rng], q((0.5, "A4", "B4")))) == 1  # 范围内 = 0 距离
    assert run([rng], q((0.5, "A4", "B4")))[0].score == pytest.approx(0.0, abs=1e-3)


def test_stability_and_energy() -> None:
    wobble = sound([(0.25, 69.0), (0.25, 69.4)])
    assert len(run([wobble], q((0.5, "A4")))) == 1
    assert run([wobble], q((0.5, "A4")), stability=30) == []
    assert len(run([wobble], q((0.5, "A4")), stability=50)) == 1
    assert run([wobble], q((0.5, "A4")), energyMin=2e-3) == []
    assert len(run([wobble], q((0.5, "A4")), energyMin=5e-4, energyMax=2e-3)) == 1


def test_head_tail_need_annotations() -> None:
    s = sound([(0.3, None), (1.0, 69), (0.3, None)], lines=[(0.3, 1.3)])
    bare = sound([(0.3, None), (1.0, 69), (0.3, None)], key="b")
    out = ps.search_exact([s, bare], q((1.0, "A4")), ps.check_params({"headTolerance": 0.05, "tailTolerance": 0.05}, mode="sources"))
    assert [(h.sound, h.start) for h in out.hits] == [(0, 25)] and out.unknown_bounds == 1  # 起点 0.25–0.35，同分取早
    out = ps.search_exact([s], q((0.5, "A4")), ps.check_params({"headTolerance": 0.02}, mode="sources"))
    assert [h.start for h in out.hits] == [28]
    out = ps.search_exact([s], q((0.5, "A4")), ps.check_params({"tailTolerance": 0.0}, mode="sources"))
    assert [h.end for h in out.hits] == [130]


def test_candidate_budget_gives_every_sound_a_chance_in_approx() -> None:
    sounds = [sound([(3.0, 69)], key=f"s{i:03d}") for i in range(30)]
    out = ps.search_approx(sounds, q((0.5, "A4")), P())
    assert len({h.sound for h in out.hits}) == 30


# ---------------------------------------------------------------- 批量 = 逐点；完整检索 ⊇ 基线近似


def _random_sound(rng: np.random.Generator, key: str, n: int) -> ps.Sound:
    midi = np.cumsum(rng.normal(0, 0.15, n)) + rng.uniform(55, 80)
    steps = rng.random(n) < 0.02
    midi += np.cumsum(steps * rng.integers(-5, 6, n))
    f0 = 440.0 * 2.0 ** ((midi - 69) / 12)
    conf = np.where(rng.random(n) < 0.08, 0.1, 0.9)
    conf[rng.integers(0, n, 3)] = 0.0
    en = rng.uniform(1e-4, 1e-2, n)
    cut = sorted(rng.integers(0, n, 4))
    spans = [(0, int(cut[1])), (int(cut[1]), int(cut[3])), (int(cut[0]), n)]
    return ps.Sound(key, 100, f0.astype(np.float32), conf.astype(np.float32), en.astype(np.float32), [(a + 100, b + 100) for a, b in spans])


def _naive(sounds: list[ps.Sound], query: ps.Query, prm: dict[str, object]) -> set[tuple[int, int, int, int]]:
    out = set()
    for si, s in enumerate(sounds):
        for T, lengths in ps.variants(query, prm["elastic"]):  # type: ignore[arg-type]
            starts = sorted({k for a, b in s.spans for k in range(a, b - T + 1)})
            shifts = range(-4, 5) if prm["ignoreOctave"] else [0]
            for k in starts:
                for N in shifts:
                    if ps.window_eval(s, k, query, lengths, N, prm) is not None:
                        out.add((si, k, T, N))
    return out


@pytest.mark.parametrize("seed", [1, 2, 3])
def test_batch_equals_pointwise(seed: int) -> None:
    rng = np.random.default_rng(seed)
    sounds = [_random_sound(rng, f"k{i}", 700) for i in range(3)]
    base = sounds[0].f0[200:260].astype(np.float64)
    mid = 69 + 12 * np.log2(float(np.median(base)) / 440)
    note = int(round(mid))
    names = ["C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B"]
    nm = lambda m: f"{names[m % 12]}{m // 12 - 1}"  # noqa: E731
    query = ps.parse_query([{"seconds": 0.3, "low": nm(note)}, {"seconds": 0.2, "low": nm(note - 1), "high": nm(note + 1)}])
    for kw in [{}, {"tolerance": 100, "coverage": 0.6}, {"stability": 80, "tolerance": 120, "coverage": 0.5}, {"tolerance": 150, "coverage": 0.5, "maxGap": 0.03}]:
        prm = P(**kw)
        hits = ps.search_exact(sounds, query, prm).hits
        naive = _naive(sounds, query, prm)
        got = {(h.sound, h.start, h.frames, h.octave) for h in hits}
        assert got <= naive
        # 每个合格起点都落在某个命中所在的组里：组 = 相邻合格起点
        starts = sorted({(si, k) for si, k, _T, _N in naive})
        groups: list[list[tuple[int, int]]] = []
        for si, k in starts:
            if groups and groups[-1][-1] == (si, k - 1):
                groups[-1].append((si, k))
            else:
                groups.append([(si, k)])
        assert len(groups) == len(hits)


def test_batch_equals_pointwise_extensions() -> None:
    rng = np.random.default_rng(7)
    sounds = [_random_sound(rng, f"k{i}", 400) for i in range(2)]
    base = float(np.median(sounds[1].f0[100:140]))
    note = int(round(69 + 12 * math.log2(base / 440)))
    names = ["C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B"]
    nm = lambda m: f"{names[m % 12]}{m // 12 - 1}"  # noqa: E731
    query = ps.parse_query([{"seconds": 0.2, "low": nm(note + 12)}, {"seconds": 0.15, "low": nm(note + 12), "glide": {"low": nm(note + 14)}}])
    prm = P(tolerance=300, coverage=0.4, ignoreOctave=True, elastic=[0.9, 1.1])
    hits = ps.search_exact(sounds, query, prm).hits
    naive = _naive(sounds, query, prm)
    assert {(h.sound, h.start, h.frames, h.octave) for h in hits} <= naive
    starts = sorted({(si, k) for si, k, _T, _N in naive})
    n_groups = sum(1 for i, x in enumerate(starts) if i == 0 or starts[i - 1] != (x[0], x[1] - 1))
    assert len(hits) == n_groups > 0


def test_exact_finds_everything_approx_finds() -> None:
    rng = np.random.default_rng(11)
    sounds = [_random_sound(rng, f"k{i}", 900) for i in range(4)]
    base = float(np.median(sounds[2].f0[300:340]))
    note = int(round(69 + 12 * math.log2(base / 440)))
    names = ["C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B"]
    query = ps.parse_query([{"seconds": 0.3, "low": f"{names[note % 12]}{note // 12 - 1}"}])
    prm = P(tolerance=100, coverage=0.6)
    approx = ps.search_approx(sounds, query, prm).hits
    exact = ps.search_exact(sounds, query, prm).hits
    assert approx
    naive = _naive(sounds, query, prm)
    for h in approx:
        assert (h.sound, h.start, h.frames, 0) in naive
        # 同一组的完整检索命中分数不比它差
        g = [e for e in exact if e.sound == h.sound and abs(e.start - h.start) < 400]
        assert g and min(e.score for e in g) <= h.score + 1e-6
    assert len(exact) >= len(approx)


# ---------------------------------------------------------------- 扩展（所有者 2026-10-08）


def test_ignore_octave_same_shift_for_all_blocks() -> None:
    up = sound([(0.4, 72), (0.4, 76)])  # C5 E5
    query = q((0.4, "C4"), (0.4, "E4"))
    assert run([up], query) == []
    hits = run([up], query, ignoreOctave=True)
    assert [(h.start, h.octave) for h in hits] == [(0, 1)]
    mixed = sound([(0.4, 60), (0.4, 76)])  # C4 E5：两块要不同的八度 → 不算
    assert run([mixed], query, ignoreOctave=True) == []
    down = sound([(0.4, 36), (0.4, 40), (0.4, 43)])  # C2 E2 G2
    assert [h.octave for h in run([down], q((0.4, "C4"), (0.4, "E4"), (0.4, "G4")), ignoreOctave=True)] == [-2]


def test_elastic_duration() -> None:
    s = sound([(0.2, None), (0.3, 69), (0.225, 72), (0.2, None)])  # 0.4 A4 + 0.3 C5 的 0.75 倍
    query = q((0.4, "A4"), (0.3, "C5"))
    assert run([s], query) == []
    hits = run([s], query, elastic=[0.7, 1.0])
    # 同分取 |ln r| 小的：覆盖 0.8 允许窗口带一点静音，所以选的是最接近 1 的可行倍数
    assert len(hits) == 1 and hits[0].score == pytest.approx(0.0, abs=1e-3)
    tight = run([s], query, elastic=[0.7, 1.0], coverage=1.0)
    assert [(h.start, h.frames) for h in tight] == [(20, 53)]  # 30 + 23 帧 = 0.76 倍
    assert run([s], query, elastic=[0.8, 1.25], coverage=1.0) == []


def test_elastic_variants_cover_every_step() -> None:
    query = q((0.4, "A4"), (0.3, "C5"))
    var = ps.variants(query, (0.8, 1.25))
    totals = [t for t, _ in var]
    assert totals == list(range(56, 89))  # 70 × 0.8 … 70 × 1.25，每帧一个
    assert all(sum(ls) == t for t, ls in var)
    long = ps.parse_query([{"seconds": 5.0, "low": "A4"}, {"seconds": 5.0, "low": "C5"}])
    lv = ps.variants(long, (0.8, 1.25))
    assert len(lv) == 46 and lv[0][0] == 800 and lv[-1][0] == 1250  # 长查询按 0.01 倍步进


def test_glide_block() -> None:
    s = sound([(0.2, None), (0.5, (72.0, 76.0)), (0.2, None)])
    glide = q((0.5, "C5", "->E5"))
    hits = run([s], glide)
    assert len(hits) == 1 and hits[0].start == 20 and hits[0].score == pytest.approx(0.0, abs=1e-3)
    assert run([s], q((0.5, "C5"))) == []
    assert run([s], q((0.5, "E5", "->C5"))) == []  # 方向反了
    # 滑音 + 忽略八度
    assert [h.octave for h in run([s], q((0.5, "C4", "->E4")), ignoreOctave=True)] == [1]
