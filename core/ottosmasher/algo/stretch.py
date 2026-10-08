"""卡拍：控制点、时间映射、语音播放速度、候选密度与原速（规格 09 §9.4.4、§9.5.1–§9.5.2，16 R13）【基线算法】。纯函数，不做 IO。

时钟：源时间 = 调用方的时钟（Core 用资产局部秒）；目标时间 = 卡拍输出的秒（输出第一个样本 = 0）。
映射以**源采样率的帧**计算（``frames``），渲染与 REAPER 标记都用它，保证核心逐样本复制、起音落在目标拍（±1 样本）。

- 控制点 = 各音块起音 + 语段段尾控制点 + 句尾控制点。语段段尾（规格没写定义，开发者决定，见 QUESTIONS「阶段 6 开始」）：
  源 = 该语段末块的发声终点（块结束；块内有停顿就截在停顿开始），目标拍 = 末块目标拍 + 末块占格 / 密度；与下一起音同拍时不加。
- 保护核心：每个控制点左右各 r 个样本原样复制，r = min(8 ms, 左右源侧间距 / 4, 左右目标侧间距 / 4)；核心斜率 1。
  所有者 2026-10-08【基线变更】：控制点贴着窗口边界（那一侧间距为 0）时，那一侧为 0、另一侧照常取 min(8 ms, 该侧间距 / 4)。
- 首个核心之前、末个核心之后按整体倍率；核心之间是桥：桥内停顿是弹性片，先给停顿保留 min(停顿总长, 桥目标长度 × 2%)，
  语音部分的伸缩比不超过整体倍率，剩下的由停顿吸收；没有停顿的桥整体伸缩。
- 语音播放速度 = 源语音时长（[首个起音, 句尾控制点] 去掉停顿）/ 它们映射后的时长，用真实映射算。
- 候选密度：近快 = 速度 ≥ 1 的最小 2^k，近慢 = 再低一档，倍快 = 再高一档（任意 2^k，|k| ≤ 40，最多 24 步）。
  不设 BPM（原速）：先在 120 BPM 下求近快密度，再固定密度在 20–400 BPM 间二分（最多 32 次）使速度 = 1。
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass, field

from ..core.errors import CoreError
from . import rhythm as rh

ALGO_VERSION = "stretch-1"
CORE_MAX = 0.008
PAUSE_RESERVE = 0.02
BPM_RANGE = (20.0, 400.0)
ORIGINAL_PROBE_BPM = 120.0
MAX_STEPS = 24
MAX_K = 40
SPEED_EPS = 1e-5
BISECT_MAX = 32
ORIGINAL_TOLERANCE = 1e-3
MAX_OUTPUT_SECONDS = 600.0


@dataclass(frozen=True)
class ControlPoint:
    src: float  # 源时间（秒）
    beat: float  # 目标拍
    kind: str  # "onset" / "segment-tail" / "tail"
    block: int  # 对应的音块


def control_points(blocks: Sequence[rh.Block], dur: rh.Durations, beats: rh.Beats, cells: Sequence[int], pauses: Sequence[rh.Pause], cuts: Sequence[rh.Cut] = ()) -> list[ControlPoint]:
    cps = [ControlPoint(b.onset, beats.onsets[i], "onset", i) for i, b in enumerate(blocks)]
    for c in cuts:
        if c.merged:
            continue
        j = c.k - 1
        if beats.rest_cells[j] < 1:
            continue  # 段尾与下一起音同拍：不加
        end = min([blocks[j].end] + [p.start for p in pauses if blocks[j].onset < p.start < blocks[c.k].onset])
        if blocks[j].onset < end < blocks[c.k].onset:
            cps.append(ControlPoint(end, beats.onsets[j] + cells[j] / beats.density, "segment-tail", j))
    cps.append(ControlPoint(dur.intervals[-1][1], beats.tail, "tail", len(blocks) - 1))
    cps.sort(key=lambda c: c.src)
    for a, b in zip(cps, cps[1:]):
        if not (b.src > a.src and b.beat > a.beat):
            raise CoreError("rhythm-map-not-monotonic", at=round(b.src, 6))
    return cps


@dataclass(frozen=True)
class Piece:
    """映射的一段（帧）：源 [sa, sb) → 目标 [ta, tb)。``kind``：core（逐样本复制）/ bridge / pause / edge（首尾，整体倍率）。"""

    sa: int
    sb: int
    ta: int
    tb: int
    kind: str
    bridge: int = -1  # 属于第几个桥（交叉淡化只在桥的两端做）


@dataclass
class TimeMap:
    sr: int
    w0: float  # 源窗口起点（秒）：帧 0
    src_frames: int
    out_frames: int
    pieces: list[Piece]
    onsets: list[int]  # 各控制点的目标帧（与 cps 同序）
    cps: list[ControlPoint]
    ratio: float
    beat_seconds: float
    knots: list[tuple[int, int]] = field(default_factory=list)  # (源帧, 目标帧)，严格递增，分段线性

    def to_target(self, src_frame: float) -> float:
        k = self.knots
        if src_frame <= k[0][0]:
            return float(k[0][1])
        for (s0, t0), (s1, t1) in zip(k, k[1:]):
            if src_frame <= s1:
                return t0 + (src_frame - s0) * (t1 - t0) / (s1 - s0)
        return float(k[-1][1])

    def to_source(self, tgt_frame: float) -> float:
        k = self.knots
        if tgt_frame <= k[0][1]:
            return float(k[0][0])
        for (s0, t0), (s1, t1) in zip(k, k[1:]):
            if tgt_frame <= t1:
                return s0 + (tgt_frame - t0) * (s1 - s0) / (t1 - t0)
        return float(k[-1][0])


def build_map(
    cps: Sequence[ControlPoint],
    window: tuple[float, float],
    pauses: Sequence[rh.Pause],
    ratio: float,
    beat_seconds: float,
    sr: int,
) -> TimeMap:
    w0, w1 = window
    F = lambda t: int(round((t - w0) * sr))  # noqa: E731 — 源秒 → 源帧
    n_src = F(w1)
    src = [F(c.src) for c in cps]
    # 目标帧（相对首个控制点）= (目标拍 − 首拍) × 拍长；整体平移不改变映射的形状（平移不变）
    rel = [int(round((c.beat - cps[0].beat) * beat_seconds * sr)) for c in cps]
    # 保护核心半径（帧）：min(8 ms, 左右源侧间距 / 4, 左右目标侧间距 / 4)；首尾外侧的目标间距按整体倍率
    # 贴边（所有者 2026-10-08【基线变更】09 §9.5.2）：控制点贴着窗口边界、那一侧间距为 0 时，那一侧半径为 0、另一侧照常（不再被拖成 0）
    lft, rgt = [], []
    for i in range(len(cps)):
        sl = src[i] - (src[i - 1] if i else 0)
        sr_ = (src[i + 1] if i + 1 < len(cps) else n_src) - src[i]
        tl = rel[i] - rel[i - 1] if i else int(src[0] * ratio)
        tr = rel[i + 1] - rel[i] if i + 1 < len(cps) else int((n_src - src[-1]) * ratio)
        cap = int(round(CORE_MAX * sr))
        left_edge = i == 0 and (sl == 0 or tl == 0)
        right_edge = i + 1 == len(cps) and (sr_ == 0 or tr == 0)
        if left_edge or right_edge:
            lft.append(0 if left_edge else max(0, min(cap, sl // 4, tl // 4)))
            rgt.append(0 if right_edge else max(0, min(cap, sr_ // 4, tr // 4)))
        else:
            r = max(0, min(cap, sl // 4, sr_ // 4, tl // 4, tr // 4))
            lft.append(r)
            rgt.append(r)
    # 首个核心之前、末个核心之后按整体倍率
    offset = int(round((src[0] - lft[0]) * ratio)) + lft[0]
    tgt = [r + offset for r in rel]
    n_out = tgt[-1] + rgt[-1] + int(round((n_src - src[-1] - rgt[-1]) * ratio))
    if n_out / sr > MAX_OUTPUT_SECONDS:
        raise CoreError("rhythm-output-too-long", seconds=round(n_out / sr, 1), max=MAX_OUTPUT_SECONDS)
    pieces: list[Piece] = []
    knots: list[tuple[int, int]] = [(0, 0)]

    def add(p: Piece) -> None:
        if p.sb <= p.sa and p.tb <= p.ta:
            return
        pieces.append(p)
        if (p.sb, p.tb) != knots[-1]:
            knots.append((p.sb, p.tb))

    # 首段（整体倍率）
    add(Piece(0, src[0] - lft[0], 0, tgt[0] - lft[0], "edge"))
    for i in range(len(cps)):
        add(Piece(src[i] - lft[i], src[i] + rgt[i], tgt[i] - lft[i], tgt[i] + rgt[i], "core"))
        if i + 1 < len(cps):
            sa, sb = src[i] + rgt[i], src[i + 1] - lft[i + 1]
            ta, tb = tgt[i] + rgt[i], tgt[i + 1] - lft[i + 1]
            for p in _bridge(sa, sb, ta, tb, pauses, w0, sr, ratio, i):
                add(p)
    add(Piece(src[-1] + rgt[-1], n_src, tgt[-1] + rgt[-1], n_out, "edge"))
    for a, b in zip(knots, knots[1:]):
        if not (b[0] > a[0] and b[1] > a[1]):
            raise CoreError("rhythm-map-not-monotonic", at=round(w0 + b[0] / sr, 6))
    return TimeMap(sr, w0, n_src, n_out, pieces, tgt, list(cps), ratio, beat_seconds, knots)


def _bridge(sa: int, sb: int, ta: int, tb: int, pauses: Sequence[rh.Pause], w0: float, sr: int, ratio: float, idx: int) -> list[Piece]:
    """桥内的弹性停顿：先给停顿保留 min(停顿总长, 桥目标长度 × 2%)，语音伸缩比 ≤ 整体倍率，剩下的给停顿。"""
    L = tb - ta
    cuts: list[tuple[int, int]] = []
    for p in pauses:
        a = max(sa, int(round((p.start - w0) * sr)))
        b = min(sb, int(round((p.end - w0) * sr)))
        if b > a:
            cuts.append((a, b))
    cuts.sort()
    P = sum(b - a for a, b in cuts)
    V = (sb - sa) - P
    if P == 0 or V <= 0:
        return [Piece(sa, sb, ta, tb, "bridge" if P == 0 else "pause", idx)]
    reserve = min(P, PAUSE_RESERVE * L)
    v_tgt = min(V * ratio, L - reserve)
    p_tgt = L - v_tgt
    fv, fp = v_tgt / V, p_tgt / P
    out = []
    pos_s, pos_t = sa, float(ta)
    segs: list[tuple[int, int, str]] = []
    for a, b in cuts:
        if a > pos_s:
            segs.append((pos_s, a, "bridge"))
        segs.append((a, b, "pause"))
        pos_s = b
    if sb > pos_s:
        segs.append((pos_s, sb, "bridge"))
    for k, (a, b, kind) in enumerate(segs):
        t1 = tb if k == len(segs) - 1 else pos_t + (b - a) * (fp if kind == "pause" else fv)
        out.append(Piece(a, b, int(round(pos_t)), int(round(t1)), kind, idx))
        pos_t = t1
    return [p for p in out if p.tb > p.ta and p.sb > p.sa]


def speech_speed(m: TimeMap, pauses: Sequence[rh.Pause]) -> float:
    """语音播放速度 = 源语音时长 / 目标语音时长（[首个起音, 句尾控制点] 去掉停顿，按真实映射）。"""
    a = (m.cps[0].src - m.w0) * m.sr
    b = (m.cps[-1].src - m.w0) * m.sr
    voiced = [(a, b)]
    for p in sorted(pauses, key=lambda p: p.start):
        pa, pb = (p.start - m.w0) * m.sr, (p.end - m.w0) * m.sr
        nxt = []
        for x, y in voiced:
            if pb <= x or pa >= y:
                nxt.append((x, y))
                continue
            if pa > x:
                nxt.append((x, pa))
            if pb < y:
                nxt.append((pb, y))
        voiced = nxt
    src = sum(y - x for x, y in voiced)
    tgt = sum(m.to_target(y) - m.to_target(x) for x, y in voiced)
    return src / tgt if tgt > 0 else math.inf


# ---------------------------------------------------------------- 方案（§9.5.1）


@dataclass(frozen=True)
class Scheme:
    density: float
    bpm: float
    speed: float
    ratio: float
    beats: rh.Beats
    map: TimeMap


@dataclass(frozen=True)
class Plan:
    """一次求解的输入：同一句（或语段）的音块、时值、占格、停顿、切口与窗口。"""

    blocks: Sequence[rh.Block]
    dur: rh.Durations
    cells: Sequence[int]
    pauses: Sequence[rh.Pause]
    cuts: Sequence[rh.Cut]
    window: tuple[float, float]
    sr: int


def scheme(plan: Plan, density: float, bpm: float) -> Scheme:
    beat_s = 60.0 / bpm
    beats = rh.target_beats(plan.cells, plan.dur, density)
    ratio = rh.overall_ratio(beats, plan.dur, beat_s)
    cps = control_points(plan.blocks, plan.dur, beats, plan.cells, plan.pauses, plan.cuts)
    m = build_map(cps, plan.window, plan.pauses, ratio, beat_s, plan.sr)
    return Scheme(density, bpm, speech_speed(m, plan.pauses), ratio, beats, m)


def check_bpm(bpm: float | None) -> float | None:
    if bpm is None:
        return None
    if not (BPM_RANGE[0] <= bpm <= BPM_RANGE[1]):
        raise CoreError("bpm-invalid", min=BPM_RANGE[0], max=BPM_RANGE[1])
    return float(bpm)


def _near_fast_k(plan: Plan, bpm: float) -> int:
    total_cells = sum(plan.cells)
    k = math.ceil(math.log2(total_cells * (60.0 / bpm) / plan.dur.total))
    k = max(-MAX_K, min(MAX_K, k))
    fast = lambda k: scheme(plan, 2.0**k, bpm).speed >= 1 - SPEED_EPS  # noqa: E731
    if fast(k):
        for _ in range(MAX_STEPS):
            if k - 1 < -MAX_K or not fast(k - 1):
                break
            k -= 1
    else:
        for _ in range(MAX_STEPS):
            if k + 1 > MAX_K:
                break
            k += 1
            if fast(k):
                break
    return k


def candidates(plan: Plan, bpm: float | None) -> dict[str, Scheme]:
    """近快（near_fast）、近慢（near_slow）、倍快（double）。``bpm=None`` = 原速卡拍。"""
    bpm = check_bpm(bpm)
    if bpm is None:
        k = _near_fast_k(plan, ORIGINAL_PROBE_BPM)
        bpm = original_bpm(plan, 2.0**k)
    else:
        k = _near_fast_k(plan, bpm)
    return {"near_fast": scheme(plan, 2.0**k, bpm), "near_slow": scheme(plan, 2.0 ** (k - 1), bpm), "double": scheme(plan, 2.0 ** (k + 1), bpm)}


def original_bpm(plan: Plan, density: float) -> float:
    """固定密度，在 20–400 BPM 间二分，使语音播放速度 = 1。"""
    lo, hi = BPM_RANGE
    best, err = lo, math.inf
    for _ in range(BISECT_MAX):
        mid = (lo + hi) / 2
        sp = scheme(plan, density, mid).speed
        if abs(sp - 1) < err:
            best, err = mid, abs(sp - 1)
        if abs(sp - 1) < SPEED_EPS:
            break
        if sp < 1:
            lo = mid
        else:
            hi = mid
    if err > ORIGINAL_TOLERANCE:
        raise CoreError("rhythm-original-speed-impossible", error=round(err, 6))
    return best
