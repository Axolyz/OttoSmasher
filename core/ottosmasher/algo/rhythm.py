"""音块、停顿、停顿段、语段、时值与量化（规格 09 §9.2–§9.4，16 R12）【基线算法 / 基线参数】。纯函数 + numpy，不做 IO。

时钟：这里的时间都是调用方给的同一个时钟（Core 用资产局部秒）；分析窗口 = 采样或语段的范围 ``[w0, w1]``。

- 音块：只有元音（a i u e o；清音 I/U 视为 i/u）和拨音 N 参与，其他标签都打断；元音并入前一块要求前一个音素是元音（不是 N）、
  不是人工拆点、与前一块末尾的间隔在 [−1 ms, 35 ms]；N 只向后附着到前一个元音所在的块。最多 128 块，起音严格递增。
- 停顿：10 ms 不重叠块的 RMS，阈值 = max(P85 × 0.25 × 灵敏度, 1e-5)，安静段 ≥ 0.12 / 灵敏度；与促音重叠的不是停顿；
  裁到 [首个音素开始, 末个音素结束] 后仍须 ≥ 0.12 / 灵敏度；两侧各内缩 20 ms。
- 停顿段序号 = 结束 ≤ 该音块起音的停顿个数。
- 语段：内缩后 ≥ 阈值（默认 0.28 s）、左右各有完整音块（块尾 / 起音伸进停顿 ≤ 50 ms 也算，所有者 2026-10-08）、切点 = 停顿中点且不落在有声音素内部 → 自动切口；手动切分 / 合并。
- 时值：本块起音 → 下一块起音（末块见 §9.4.1），扣除与停顿重叠的休止秒数（最多扣到 5 ms），至少 5 ms。
- 量化：原节奏 · 无 mora（束搜索，§9.4.3）与纯 mora（+ 自动长音补格）；人工占格两条路线都生效。
  所有者 2026-10-08【基线变更】：去掉 mora 参考校准；纯 mora 只作临时试听与临时导出（不保存为采样的路线）。
- 目标拍（§9.4.4）。
"""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field

import numpy as np

from ..core.errors import CoreError

ALGO_VERSION = "rhythm-1"

VOWELS = frozenset("aiueo")
SYLLABIC = VOWELS | {"N"}
SOKUON = frozenset({"cl", "q", "Q", "\u3063"})
PAUSE_LABELS = frozenset({"pau", "sil", "sp", "SP", "AP"})
# 前导辅音向前取时遇到这些就停（09 §9.6.3：停顿、AP、spn、N、促音、元音）
CONSONANT_STOP = PAUSE_LABELS | {"spn", "N"} | SOKUON | VOWELS
# “有声音素”：切点不能落在它们内部（静音类与促音闭塞除外）
SILENT_LABELS = PAUSE_LABELS | SOKUON

MERGE_GAP_MIN = -0.001
MERGE_GAP_MAX = 0.035
MAX_BLOCKS = 128

RMS_BLOCK = 0.01
PAUSE_PERCENTILE = 85
PAUSE_RATIO = 0.25
PAUSE_FLOOR = 1e-5
PAUSE_MIN = 0.12
PAUSE_INSET = 0.02
SENSITIVITY_RANGE = (0.5, 2.0)
SEGMENT_THRESHOLD_RANGE = (0.16, 2.0)
DEFAULT_SENSITIVITY = 1.0
DEFAULT_SEGMENT_THRESHOLD = 0.28
# 所有者 2026-10-08【基线变更】09 §9.3.3：对齐边界有固有误差，块尾 / 起音伸进停顿 ≤ 50 ms 仍算“两侧各有完整音块”
SEGMENT_EDGE_TOLERANCE = 0.05

LAST_MIN = 0.001
MIN_DURATION = 0.005

ROUTES = ("raw", "mora")
MAX_CELLS = 64
BASE_COMPLEXITY = 0.045
PENALTY_RANGE = (0.0, 3.0)
CONTINUITY = 0.25
DRIFT = 0.055
SEED_MAX_N = 8
SEED_MIN_LOG_GAP = 0.035
SEED_COUNT = 12
BEAM = 48
REFINE_TOP = 3
ALTERNATIVES = 3
LONG_VOWEL_TAU_MIN = 0.04
LONG_VOWEL_RATE_MIN = 0.035


def _norm(label: str) -> str:
    return {"I": "i", "U": "u"}.get(label, label)


# ---------------------------------------------------------------- 音块（§9.2）


@dataclass(frozen=True)
class Phone:
    label: str
    start: float
    end: float
    mora: int | None = None
    strength: float | None = None


@dataclass(frozen=True)
class Block:
    onset: float
    end: float
    vowel: str | None  # 首元音；只有 N 的块为 None（未知）
    members: tuple[int, ...]  # 成员音素的序号
    strength: float | None  # 成员起音强度的最大值；都未知为 None


def group_blocks(phones: Sequence[Phone], splits: Sequence[int] = ()) -> list[Block]:
    """``splits``：人工拆点，“在第 k 个音素之前”（k 从 0 起，指 ``phones`` 的序号）。"""
    split = set(splits)
    groups: list[list[int]] = []
    cur: list[int] | None = None
    for k, p in enumerate(phones):
        lab = _norm(p.label)
        if lab not in SYLLABIC:
            cur = None
            continue
        join = False
        if cur and cur[-1] == k - 1 and k not in split:
            prev = _norm(phones[k - 1].label)
            gap = p.start - phones[cur[-1]].end
            if MERGE_GAP_MIN - 1e-9 <= gap <= MERGE_GAP_MAX + 1e-9:
                join = prev in SYLLABIC if lab == "N" else prev in VOWELS
        if join and cur is not None:
            cur.append(k)
        else:
            cur = [k]
            groups.append(cur)
    out = []
    for g in groups:
        strengths = [phones[k].strength for k in g if phones[k].strength is not None]
        vowel = next((_norm(phones[k].label) for k in g if _norm(phones[k].label) in VOWELS), None)
        out.append(Block(phones[g[0]].start, phones[g[-1]].end, vowel, tuple(g), max(strengths) if strengths else None))
    if len(out) > MAX_BLOCKS:
        raise CoreError("rhythm-too-many-blocks", count=len(out), max=MAX_BLOCKS)
    for a, b in zip(out, out[1:]):
        if not b.onset > a.onset:
            raise CoreError("rhythm-onsets-not-increasing", at=round(b.onset, 6))
    return out


def leading_consonant_start(phones: Sequence[Phone], block: Block) -> float:
    """块的前导辅音开始：从第一个成员向前取，遇到停顿、AP、spn、N、促音或元音即停；没有前导辅音 = 起音。"""
    k = block.members[0] - 1
    start = block.onset
    while k >= 0 and _norm(phones[k].label) not in CONSONANT_STOP:
        start = phones[k].start
        k -= 1
    return start


# ---------------------------------------------------------------- 停顿（§9.3.1）


@dataclass(frozen=True)
class Pause:
    start: float
    end: float

    @property
    def length(self) -> float:
        return self.end - self.start


def _overlap(a0: float, a1: float, b0: float, b1: float) -> float:
    return max(0.0, min(a1, b1) - max(a0, b0))


def check_sensitivity(v: float) -> float:
    if not (SENSITIVITY_RANGE[0] - 1e-9 <= v <= SENSITIVITY_RANGE[1] + 1e-9):
        raise CoreError("rhythm-param-invalid", field="sensitivity", min=SENSITIVITY_RANGE[0], max=SENSITIVITY_RANGE[1])
    return float(v)


def block_rms(mono: np.ndarray, sr: int) -> np.ndarray:
    """不重叠的 10 ms 块的 RMS（原采样率；不足一块的尾巴不算）。"""
    x = np.asarray(mono, dtype=np.float64)
    n = int(math.floor(len(x) / (RMS_BLOCK * sr) + 1e-9))
    edges = [round(k * RMS_BLOCK * sr) for k in range(n + 1)]
    return np.array([math.sqrt(float(np.mean(np.square(x[edges[k] : edges[k + 1]])))) if edges[k + 1] > edges[k] else 0.0 for k in range(n)])


def detect_pauses(mono: np.ndarray, sr: int, w0: float, phones: Sequence[Phone], sensitivity: float = DEFAULT_SENSITIVITY) -> list[Pause]:
    """``mono``：分析窗口的音频（声道已平均），第一个样本的时间 = ``w0``。只看能量，不看模型标签。"""
    sens = check_sensitivity(sensitivity)
    rms = block_rms(mono, sr)
    if not len(rms) or not phones:
        return []
    thr = max(float(np.percentile(rms, PAUSE_PERCENTILE)) * PAUSE_RATIO * sens, PAUSE_FLOOR)
    min_len = PAUSE_MIN / sens
    quiet = rms <= thr
    runs: list[tuple[float, float]] = []
    k = 0
    while k < len(quiet):
        if quiet[k]:
            j = k
            while j < len(quiet) and quiet[j]:
                j += 1
            runs.append((w0 + k * RMS_BLOCK, w0 + j * RMS_BLOCK))
            k = j
        else:
            k += 1
    closures = [(p.start, p.end) for p in phones if p.label in SOKUON]
    first, last = min(p.start for p in phones), max(p.end for p in phones)
    out = []
    for a, b in runs:
        if b - a < min_len - 1e-9:
            continue
        if any(_overlap(a, b, c0, c1) > 0 for c0, c1 in closures):
            continue  # 促音闭塞已计入占格
        a, b = max(a, first), min(b, last)
        if b - a < min_len - 1e-9:
            continue
        out.append(Pause(round(a + PAUSE_INSET, 6), round(b - PAUSE_INSET, 6)))
    return out


def pause_segments(blocks: Sequence[Block], pauses: Sequence[Pause]) -> list[int]:
    """每块的停顿段序号 = 结束时刻不晚于该块起音的停顿个数。"""
    return [sum(1 for p in pauses if p.end <= b.onset + 1e-9) for b in blocks]


# ---------------------------------------------------------------- 语段（§9.3.3）


@dataclass(frozen=True)
class Cut:
    k: int  # 切在第 k 块之前
    kind: str  # "auto" / "manual"
    left_end: float  # 左段终点
    right_start: float  # 右段起点
    merged: bool = False  # 自动切口被手动合并（抑制）


@dataclass(frozen=True)
class Segment:
    index: int
    start: float
    end: float
    first: int  # 第一块
    stop: int  # 末块之后（不含）


def check_threshold(v: float) -> float:
    if not (SEGMENT_THRESHOLD_RANGE[0] - 1e-9 <= v <= SEGMENT_THRESHOLD_RANGE[1] + 1e-9):
        raise CoreError("rhythm-param-invalid", field="segmentThreshold", min=SEGMENT_THRESHOLD_RANGE[0], max=SEGMENT_THRESHOLD_RANGE[1])
    return float(v)


def find_cuts(
    blocks: Sequence[Block],
    pauses: Sequence[Pause],
    phones: Sequence[Phone],
    threshold: float = DEFAULT_SEGMENT_THRESHOLD,
    manual: Sequence[int] = (),
    merges: Sequence[int] = (),
) -> list[Cut]:
    """全部切口（含被合并的自动切口，``merged=True``）。手动切分 k > 0；与自动切口同位时手动优先。"""
    thr = check_threshold(threshold)
    voiced = [(p.start, p.end) for p in phones if p.label not in SILENT_LABELS]
    cuts: dict[int, Cut] = {}
    for p in pauses:
        if p.length < thr - 1e-9:
            continue
        mid = (p.start + p.end) / 2
        if any(s < mid - 1e-9 and mid < e - 1e-9 for s, e in voiced):
            continue
        for k in range(1, len(blocks)):
            if blocks[k - 1].end <= p.start + SEGMENT_EDGE_TOLERANCE + 1e-9 and blocks[k].onset >= p.end - SEGMENT_EDGE_TOLERANCE - 1e-9:
                cuts[k] = Cut(k, "auto", round(mid, 6), round(mid, 6), merged=k in set(merges))
                break
    for k in manual:
        if not 0 < k < len(blocks):
            raise CoreError("rhythm-cut-invalid", k=k, count=len(blocks))
        cuts[k] = Cut(k, "manual", blocks[k - 1].end, leading_consonant_start(phones, blocks[k]))
    return [cuts[k] for k in sorted(cuts)]


def segments(blocks: Sequence[Block], cuts: Sequence[Cut], window: tuple[float, float]) -> list[Segment]:
    """生效的切口切出的语段（只有一段时返回空：整句本身不算语段）。"""
    live = [c for c in cuts if not c.merged]
    if not live or not blocks:
        return []
    out = []
    a, first = window[0], 0
    for i, c in enumerate(live):
        out.append(Segment(i, a, c.left_end, first, c.k))
        a, first = c.right_start, c.k
    out.append(Segment(len(live), a, window[1], first, len(blocks)))
    return out


# ---------------------------------------------------------------- mora（纯 mora 路线）


def mora_span(phones: Sequence[Phone], window: tuple[float, float], *, strict: bool = True) -> tuple[int, int] | None:
    """窗口内的 mora 起点与个数（从 0 重新编号，保留开头辅音和尾音）；次序倒退 → None。
    ``strict``（语段）：有音素缺 mora 就整段未知（不吞并别的文字）；整句（``strict=False``）跳过缺 mora 的音素，由逐块格数标出缺的块。"""
    ms = []
    for p in phones:
        if p.label in PAUSE_LABELS:
            continue
        mid = (p.start + p.end) / 2
        if not (window[0] - 1e-9 <= mid < window[1] + 1e-9):
            continue
        if p.mora is None:
            if strict:
                return None
            continue
        ms.append(p.mora)
    if not ms or any(b < a for a, b in zip(ms, ms[1:])):
        return None
    return ms[0], ms[-1] - ms[0] + 1


def mora_cells(phones: Sequence[Phone], blocks: Sequence[Block], span: tuple[int, int] | None) -> list[int | None]:
    """纯 mora 的逐块格数：首 mora = 成员 mora 的最小值；格数 = 下一块首 mora − 本块首 mora，末块 = mora 总数 − 末块首 mora；须在 1–64。"""
    if span is None:
        return [None] * len(blocks)
    base, total = span
    firsts: list[int | None] = []
    for b in blocks:
        ms = [phones[k].mora for k in b.members if phones[k].mora is not None]
        firsts.append(min(ms) - base if ms and len(ms) == len(b.members) else None)
    out: list[int | None] = []
    for i, f in enumerate(firsts):
        nxt = firsts[i + 1] if i + 1 < len(firsts) else total
        if f is None or nxt is None:
            out.append(None)
            continue
        n = nxt - f
        out.append(n if 1 <= n <= MAX_CELLS else None)
    return out


# ---------------------------------------------------------------- 时值（§9.4.1）


@dataclass(frozen=True)
class Durations:
    intervals: list[tuple[float, float]]  # 本块起音 → 下一块起音（末块终点按规则）
    rest: list[float]  # 休止秒数
    dur: list[float]  # 时值

    @property
    def total(self) -> float:
        return float(sum(self.dur))


def durations(blocks: Sequence[Block], pauses: Sequence[Pause], window: tuple[float, float]) -> Durations:
    iv, rest, dur = [], [], []
    for i, b in enumerate(blocks):
        if i + 1 < len(blocks):
            a1 = blocks[i + 1].onset
        else:
            a1 = min(max(b.end, b.onset + LAST_MIN), window[1] - LAST_MIN)
        span = a1 - b.onset
        r = sum(_overlap(b.onset, a1, p.start, p.end) for p in pauses)
        r = max(0.0, min(r, span - MIN_DURATION))
        iv.append((b.onset, a1))
        rest.append(r)
        dur.append(max(span - r, MIN_DURATION))
    return Durations(iv, rest, dur)


def blocks_in(blocks: Sequence[Block], seg: Segment) -> list[Block]:
    return list(blocks[seg.first : seg.stop])


# ---------------------------------------------------------------- 量化（§9.4.2–§9.4.3）


@dataclass
class Quantized:
    route: str
    cells: list[int] | None  # None = 路线不可用
    tick: float | None = None  # 原节奏路线的尺子（秒/格）
    cost: float | None = None
    alternatives: list[list[int]] = field(default_factory=list)  # 最多 3 个互不相同的方案（含最优）
    unavailable: str | None = None  # 不可用的原因码
    missing: list[int] = field(default_factory=list)  # 缺 mora 的块


def _clip(n: int) -> int:
    return max(1, min(MAX_CELLS, n))


def _round(x: float) -> int:
    return int(round(x))


@dataclass(frozen=True)
class _Prepared:
    d: list[float]
    w: list[float]
    seg: list[int]
    prev_rest: list[float]  # 上一块的休止秒数（第 0 块为 0）
    manual: Mapping[int, int]
    cw: float
    lo: float
    hi: float
    m: float


def _block_cost(p: _Prepared, i: int, n: int, tick: float) -> float:
    r = math.log(n * tick / p.d[i])
    return p.w[i] * r * r + p.cw * math.log(n) ** 2


def _base_cost(p: _Prepared, tick: float) -> float:
    total = 0.0
    for i, di in enumerate(p.d):
        n = p.manual[i] if i in p.manual else _clip(_round(di / tick))
        total += _block_cost(p, i, n, tick)
    return total / len(p.d)


def _beam(p: _Prepared, tick: float) -> tuple[float, tuple[int, ...]]:
    # 状态：(累计代价, 已选格数, 上一块的对数比, 当前累计格数, 当前累计秒数, 步数)
    states: list[tuple[float, tuple[int, ...], float, int, float, int]] = [(0.0, (), 0.0, 0, 0.0, 0)]
    for i, di in enumerate(p.d):
        reset = i == 0 or p.seg[i] != p.seg[i - 1] or p.prev_rest[i] > 0
        if i in p.manual:
            cands = [p.manual[i]]
        else:
            base = _round(di / tick)
            cands = sorted({1} | {_clip(base + j) for j in range(-2, 3)})
        best: dict[tuple[int, int], tuple[float, tuple[int, ...], float, int, float, int]] = {}
        for cost, seq, pr, cumc, cums, steps in states:
            c0, s0, st = (0, 0.0, 1) if reset else (cumc, cums, steps + 1)
            for n in cands:
                r = math.log(n * tick / di)
                add = _block_cost(p, i, n, tick)
                if not reset:
                    add += CONTINUITY * min(p.w[i], p.w[i - 1]) * (r - pr) ** 2
                add += DRIFT * ((c0 + n - (s0 + di) / tick) / math.sqrt(st)) ** 2
                key = (c0 + n, n)
                cand = (cost + add, seq + (n,), r, c0 + n, s0 + di, st)
                old = best.get(key)
                if old is None or cand[0] < old[0]:
                    best[key] = cand
        states = sorted(best.values(), key=lambda s: (s[0], s[1]))[:BEAM]
    top = min(states, key=lambda s: (s[0], s[1]))
    return top[0] / len(p.d), top[1]


def _prepare(dur: Durations, seg: Sequence[int], manual: Mapping[int, int], cw: float) -> _Prepared:
    d = list(dur.dur)
    m = float(np.median(d))
    return _Prepared(
        d=d,
        w=[min(1.0, max(0.25, x / m)) for x in d],
        seg=list(seg),
        prev_rest=[0.0] + list(dur.rest[:-1]),
        manual=dict(manual),
        cw=cw,
        lo=max(0.015, m / 5),
        hi=max(2 * m, 0.03),
        m=m,
    )


def _search(p: _Prepared) -> Quantized:
    seeds = {round(di / n, 6) for di in p.d for n in range(1, SEED_MAX_N + 1) if p.lo - 1e-12 <= di / n <= p.hi + 1e-12}
    seeds.add(round(p.m, 6))
    ranked = sorted(seeds, key=lambda t: (_base_cost(p, t), t))
    chosen: list[float] = []
    for t in ranked:
        if all(abs(math.log(t) - math.log(s)) >= SEED_MIN_LOG_GAP for s in chosen):
            chosen.append(t)
        if len(chosen) >= SEED_COUNT:
            break
    results = []
    for t in chosen:
        cost, seq = _beam(p, t)
        results.append((cost, seq, t))
    results.sort(key=lambda r: (r[0], r[1]))
    for cost, seq, _t in list(results[:REFINE_TOP]):
        sw = sum(p.w)
        t2 = math.exp(sum(w * math.log(di / n) for w, di, n in zip(p.w, p.d, seq)) / sw)
        if p.lo - 1e-12 <= t2 <= p.hi + 1e-12:
            c2, s2 = _beam(p, t2)
            results.append((c2, s2, t2))
    results.sort(key=lambda r: (r[0], r[1]))
    alts: list[list[int]] = []
    for _c, seq, _t in results:
        if list(seq) not in alts:
            alts.append(list(seq))
        if len(alts) >= ALTERNATIVES:
            break
    best = results[0]
    return Quantized("raw", list(best[1]), tick=best[2], cost=best[0], alternatives=alts)


def check_penalty(v: float) -> float:
    if not (PENALTY_RANGE[0] - 1e-9 <= v <= PENALTY_RANGE[1] + 1e-9):
        raise CoreError("rhythm-param-invalid", field="penalty", min=PENALTY_RANGE[0], max=PENALTY_RANGE[1])
    return float(v)


def check_manual_cells(manual: Mapping[int, int], count: int) -> dict[int, int]:
    out = {}
    for k, n in manual.items():
        k, n = int(k), int(n)
        if not 0 <= k < count:
            raise CoreError("rhythm-cells-invalid", block=k, count=count)
        if not 1 <= n <= MAX_CELLS:
            raise CoreError("rhythm-cells-invalid", block=k, cells=n, max=MAX_CELLS)
        out[k] = n
    return out


def quantize_raw(dur: Durations, seg: Sequence[int], manual: Mapping[int, int] | None = None, penalty: float = 1.0) -> Quantized:
    """原节奏 · 无 mora：只按实测时值推断，完全不依赖 mora；大数字惩罚 cw = 0.045 × 惩罚度。"""
    if not dur.dur:
        raise CoreError("rhythm-no-blocks")
    man = check_manual_cells(manual or {}, len(dur.dur))
    return _search(_prepare(dur, seg, man, BASE_COMPLEXITY * check_penalty(penalty)))


def quantize_mora(
    dur: Durations,
    blocks: Sequence[Block],
    phones: Sequence[Phone],
    pauses: Sequence[Pause],
    mora: Sequence[int | None],
    manual: Mapping[int, int] | None = None,
    long_vowel: bool = False,
) -> Quantized:
    """纯 mora：格数 = 文本 mora 数；任一块缺 mora（且没有人工占格）→ 整条路线显式不可用（不拿时长去猜）。"""
    man = check_manual_cells(manual or {}, len(dur.dur))
    cells: list[int | None] = [man.get(i, m) for i, m in enumerate(mora)]
    missing = [i for i, n in enumerate(cells) if n is None]
    if missing:
        return Quantized("mora", None, unavailable="mora-missing", missing=missing)
    out = [int(n) for n in cells]  # type: ignore[arg-type]
    if long_vowel:
        rates = [d / n for d, n in zip(dur.dur, out) if d / n > LONG_VOWEL_RATE_MIN]
        tau = max(LONG_VOWEL_TAU_MIN, float(np.median(rates))) if rates else LONG_VOWEL_TAU_MIN
        for i, b in enumerate(blocks):
            if i in man or any(_overlap(b.onset, b.end, p.start, p.end) > 0 for p in pauses):
                continue
            vowel = sum(phones[k].end - phones[k].start for k in b.members if _norm(phones[k].label) in VOWELS)
            if vowel > (out[i] + 0.5) * tau:
                out[i] = min(MAX_CELLS, max(out[i], _round(vowel / tau)))
    return Quantized("mora", out)


# ---------------------------------------------------------------- 目标拍（§9.4.4）


@dataclass(frozen=True)
class Beats:
    density: float  # 每拍格数（2^k）
    onsets: list[float]  # 各块起音的目标拍
    tail: float  # 句尾控制点的目标拍
    rest_cells: list[int]
    tick: float  # 语音总时长 / 总格数（秒/格）
    total_cells: int


def target_beats(cells: Sequence[int], dur: Durations, density: float) -> Beats:
    total = int(sum(cells))
    tick = dur.total / total
    rest = [max(0, _round(r / tick)) for r in dur.rest]
    beats = [0.0]
    for i in range(len(cells) - 1):
        beats.append(beats[-1] + (cells[i] + rest[i]) / density)
    tail = beats[-1] + (cells[-1] + rest[-1]) / density
    return Beats(density, beats, tail, rest, tick, total)


def overall_ratio(beats: Beats, dur: Durations, beat_seconds: float) -> float:
    """整体倍率（时长倍率）= 总格数 / 密度 × 拍长 / 语音总时长（不含休止）。"""
    return beats.total_cells / beats.density * beat_seconds / dur.total


# ---------------------------------------------------------------- 逐音属性（09 §9.6.3 的块级量；舞台「逐音属性」显示，阶段 7 检索复用）

TREND_MIN_FRAMES = 5
TREND_MIN_SPAN = 0.06
MIN_PITCH_FRAMES = 3


def leading_consonants(phones: Sequence[Phone], block: Block) -> list[str]:
    """前导辅音序列（模型标签）：从第一个成员向前取，遇到停顿、AP、spn、N、促音或元音即停（〔新：19 G3〕cl 不计入）。"""
    out = []
    k = block.members[0] - 1
    while k >= 0 and _norm(phones[k].label) not in CONSONANT_STOP:
        out.append(phones[k].label)
        k -= 1
    return out[::-1]


def block_attributes(
    blocks: Sequence[Block],
    phones: Sequence[Phone],
    seg: Sequence[int],
    times: np.ndarray,
    frames: np.ndarray,
    measured: np.ndarray,
) -> list[dict[str, object]]:
    """``frames``：F0 帧 [n, 3]（F0、置信度、能量），``times`` 帧中心（与音块同一时钟），``measured`` 该帧是否已测。
    音高类只用可靠帧（有声 且 F0 > 0 且 置信度 ≥ 0.5，〔新：19 G4〕）；缺失一律未知（None），不是 0。"""
    from .flatten import hz_to_midi, reliable

    f0, conf, en = frames[:, 0], frames[:, 1], frames[:, 2]
    ok = measured & reliable(np.nan_to_num(f0), np.nan_to_num(conf), np.nan_to_num(en))
    midi = np.full(len(f0), np.nan)
    midi[ok] = [hz_to_midi(float(x)) for x in f0[ok]]
    per: list[dict[str, object]] = []
    for b in blocks:
        inb = (times >= b.onset) & (times < b.end)
        n = int(inb.sum())
        all_measured = n > 0 and bool(measured[inb].all())
        rel = inb & ok
        m = midi[rel]
        t = times[rel]
        med = float(np.median(m)) if len(m) >= MIN_PITCH_FRAMES else None
        spread = float((np.percentile(m, 90) - np.percentile(m, 10)) * 100) if len(m) >= MIN_PITCH_FRAMES else None
        trend = None
        if len(m) >= TREND_MIN_FRAMES and t[-1] - t[0] >= TREND_MIN_SPAN - 1e-9:
            third = (t[-1] - t[0]) / 3
            head, tail = m[t <= t[0] + third], m[t >= t[-1] - third]
            if len(head) and len(tail):
                trend = float(np.median(tail) - np.median(head))
        energy = en[inb] if all_measured else np.array([])
        db = float(10 * np.log10(max(float(np.mean(energy)), 1e-12))) if len(energy) else None
        per.append({
            "midi": med, "spreadCents": spread, "coverage": (int(rel.sum()) / n) if all_measured else None, "trend": trend, "loudnessDb": db,
            "consonants": leading_consonants(phones, b), "_rel": rel,
        })
    for i, a in enumerate(per):
        same = [j for j in range(len(blocks)) if seg[j] == seg[i]]
        pool = np.concatenate([midi[per[j]["_rel"]] for j in same])  # type: ignore[index]
        a["relPitch"] = float(a["midi"] - np.median(pool)) if a["midi"] is not None and len(pool) >= MIN_PITCH_FRAMES else None  # type: ignore[operator]
        dbs = [per[j]["loudnessDb"] for j in same if per[j]["loudnessDb"] is not None]
        a["relLoudness"] = float(a["loudnessDb"] - np.median(dbs)) if a["loudnessDb"] is not None and dbs else None  # type: ignore[operator]
    for a in per:
        a.pop("_rel")
    return per


# ---------------------------------------------------------------- 逐采样参数（sample.rhythm，经编辑通道修改）


def default_params(sensitivity: float = DEFAULT_SENSITIVITY, threshold: float = DEFAULT_SEGMENT_THRESHOLD) -> dict[str, object]:
    return {"sensitivity": sensitivity, "segmentThreshold": threshold, "manual": empty_manual()}


def empty_manual() -> dict[str, object]:
    return {"run": None, "splits": [], "cells": {}, "cuts": [], "merges": []}


def _int_list(v: object, name: str) -> list[int]:
    if not isinstance(v, list) or any(isinstance(x, bool) or not isinstance(x, int) or x < 0 for x in v):
        raise CoreError("rhythm-param-invalid", field=name, min=0, max=None)
    return sorted(set(v))


def validate_params(v: object) -> dict[str, object]:
    """``sample.rhythm`` 的校验：灵敏度 0.5–2、语段阈值 0.16–2；人工项（拆点、占格、手动切分/合并）是非负整数，绑定分析版本 ``run``。"""
    if not isinstance(v, dict):
        raise CoreError("rhythm-param-invalid", field="rhythm", min=None, max=None)
    out = default_params()
    if "sensitivity" in v:
        x = v["sensitivity"]
        if isinstance(x, bool) or not isinstance(x, (int, float)):
            raise CoreError("rhythm-param-invalid", field="sensitivity", min=SENSITIVITY_RANGE[0], max=SENSITIVITY_RANGE[1])
        out["sensitivity"] = check_sensitivity(float(x))
    if "segmentThreshold" in v:
        x = v["segmentThreshold"]
        if isinstance(x, bool) or not isinstance(x, (int, float)):
            raise CoreError("rhythm-param-invalid", field="segmentThreshold", min=SEGMENT_THRESHOLD_RANGE[0], max=SEGMENT_THRESHOLD_RANGE[1])
        out["segmentThreshold"] = check_threshold(float(x))
    m = v.get("manual") or {}
    if not isinstance(m, dict):
        raise CoreError("rhythm-param-invalid", field="manual", min=None, max=None)
    run = m.get("run")
    if run is not None and not isinstance(run, str):
        raise CoreError("rhythm-param-invalid", field="run", min=None, max=None)
    cells_in = m.get("cells") or {}
    if not isinstance(cells_in, dict):
        raise CoreError("rhythm-param-invalid", field="cells", min=1, max=MAX_CELLS)
    cells: dict[str, int] = {}
    for k, n in cells_in.items():
        if not str(k).isdigit() or isinstance(n, bool) or not isinstance(n, int) or not 1 <= n <= MAX_CELLS:
            raise CoreError("rhythm-cells-invalid", block=k, count=None, cells=n, max=MAX_CELLS)
        cells[str(int(k))] = n
    out["manual"] = {
        "run": run, "splits": _int_list(m.get("splits", []), "splits"), "cells": cells,
        "cuts": [k for k in _int_list(m.get("cuts", []), "cuts") if k > 0], "merges": _int_list(m.get("merges", []), "merges"),
    }
    return out
