"""语音检索（统一音块检索，规格 09 §9.6，16 R14）【基线算法】。纯函数 + numpy，不做 IO、不跑模型、不读波形。

时钟：音块、停顿、持续终点都是资产局部秒（与采样同一时钟）；拍 = 查询的拍；卡拍映射的目标端是卡拍输出的帧。

输入是每个采样的检索索引 ``SampleIndex``（逐块属性 + 整句与各语段的卡拍方案输入），由 Core 从节奏分析与测量构建（不推理）。

1. **先邻接，后过滤**：在每个采样里枚举连续 n 块的窗口；不跨停顿时窗口内都属于同一停顿段；最大间隔 = 下一块起音 − 上一块结束；
   首尾（依据停顿段或整个采样）；逐块条件（缺失一律不命中），中间夹一个不合格的块整个窗口不合格。——全部是数组运算。
2. **节奏证据**（只对通过的窗口）：在允许的范围（整句和/或语段）与候选方案（有 BPM：近快、近慢；无 BPM：归一化形状）里分别计算，
   取最优（排序键 = (round(代价, 10), 速度 < 1)，即同分取近快）。三种：平移拟合（必须满足节奏 + BPM）、中位数平移（按相似度 + BPM）、
   归一化形状（无 BPM）。
3. 命中分 = Σ 逐块分 + 节奏代价；同一采样同一组音块只留最好的；采样内按（分数, 起点）、结果按（最佳分数, 采样）排序。

开发者对规格没写细的地方的决定（QUESTIONS「阶段 7」）：
- 形变只看窗口内的控制点（窗口各块起音到末块之后的第一个控制点），命中卡拍试听渲染的也是这一段；
- 无 BPM 的归一化形状里“时值（拍）”条件按归一化后乘查询跨度（拍）换算；
- 命中区 = [首块的前导辅音开始, 末块结束]（资产局部秒）；
- 段间休止调整只改窗口内的连接（窗口前后的连接改了只是整体平移或不影响窗口），速度沿用原方案（休止都在停顿里，语音部分不变）。
"""

from __future__ import annotations

import math
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from typing import Any

import numpy as np

from ..core.errors import CoreError
from . import rhythm as rh
from . import stretch as st

ALGO_VERSION = "speech-search-1"

STRATEGIES = ("free", "strict", "rank")
EDGES = ("any", "head", "tail", "both")
EDGE_BASES = ("pause", "sample")
SCOPES = ("both", "sentence", "segment")
DURATION_MODES = ("effective", "span")
TRENDS = ("up", "down")
REL_PITCHES = ("high", "low")
VOWEL_SET = ("a", "i", "u", "e", "o")
MAX_QUERY_BLOCKS = 64
PITCH_TOL_RANGE = (0.0, 600.0)
DEFORM_WEIGHT = 0.03
REST_WEIGHT = 0.003
REST_COMBOS_MAX = 128
REST_RANGE_MIN = 32
SPEED_RANGE_DEFAULT = (0.8, 1.25)
SPEED_PREF_DEFAULT = 0.1
SUSTAIN_TAIL = 0.005
ACTIVE_PERCENTILE = 85
ACTIVE_RATIO = 0.0064
ACTIVE_FLOOR = 1e-10


# ---------------------------------------------------------------- 索引（每采样）


@dataclass
class BlockAttr:
    onset: float  # 有效开始（起音）
    end: float  # 有效结束
    lead: float  # 前导辅音开始（没有 = 起音）
    vowel: str | None
    consonants: tuple[str, ...]
    midi: float | None
    spread: float | None  # 音分
    coverage: float | None
    trend: float | None  # 半音
    rel_pitch: float | None
    rel_loud: float | None
    strength: float | None
    sustain: float | None  # 持续终点（秒）
    character: str | None
    pseg: int  # 停顿段
    seg: int  # 语段（没有语段 = -1）


@dataclass
class PlanData:
    """一个节奏范围（整句 scope = -1，或第 k 个语段）的卡拍方案输入。块序号是采样内的。"""

    scope: int
    first: int
    stop: int
    plan: st.Plan


@dataclass
class SampleIndex:
    sample_id: str
    blocks: list[BlockAttr]
    plans: list[PlanData]  # 整句在前，然后各语段
    gaps: list[float] = field(default_factory=list)  # 语段之间的源间隙（秒），段间休止调整用


def sustain_end(block: rh.Block, pauses: Sequence[rh.Pause], times: np.ndarray, energy: np.ndarray, measured: np.ndarray,
                threshold: float | None, manual: bool) -> float | None:
    """持续终点（09 §9.6.3）：从块结束开始，块内有停顿就截在第一个停顿开始，再截到块内最后一个活跃帧 + 5 ms；没有活跃帧为未知；人工版本取块结束。
    ``threshold`` = max(1e-10, 整个采样能量 P85 × 0.0064)，``None`` = 采样没有能量测量（未知）。"""
    if manual:
        return block.end
    if threshold is None:
        return None
    end = block.end
    inside = [p.start for p in pauses if block.onset < p.start < block.end]
    if inside:
        end = min(end, min(inside))
    inb = (times >= block.onset) & (times < block.end) & measured
    act = inb & (energy > threshold)
    if not act.any():
        return None
    last = float(times[np.flatnonzero(act)[-1]])
    return min(end, last + SUSTAIN_TAIL)


def active_threshold(energy: np.ndarray, measured: np.ndarray) -> float | None:
    e = energy[measured]
    if not len(e):
        return None
    return max(ACTIVE_FLOOR, float(np.percentile(e, ACTIVE_PERCENTILE)) * ACTIVE_RATIO)


def build_index(
    sample_id: str,
    phones: Sequence[rh.Phone],
    blocks: Sequence[rh.Block],
    pauses: Sequence[rh.Pause],
    pseg: Sequence[int],
    cuts: Sequence[rh.Cut],
    segments: Sequence[rh.Segment],
    dur: rh.Durations,
    cells: Sequence[int],
    window: tuple[float, float],
    sr: int,
    attrs: Sequence[dict[str, Any]],
    sustain: Sequence[float | None],
    characters: Sequence[str | None],
    manual_cells: dict[int, int],
    penalty: float,
) -> SampleIndex:
    """一个采样的检索索引：逐块属性 + 整句方案输入 + 各语段方案输入（语段的块单独量化：durations + quantize_raw）。"""
    seg_of = [-1] * len(blocks)
    for sg in segments:
        for k in range(sg.first, sg.stop):
            seg_of[k] = sg.index
    out_blocks = []
    for k, b in enumerate(blocks):
        a = attrs[k]
        out_blocks.append(BlockAttr(
            onset=b.onset, end=b.end, lead=rh.leading_consonant_start(phones, b), vowel=b.vowel, consonants=tuple(a["consonants"]),
            midi=a["midi"], spread=a["spreadCents"], coverage=a["coverage"], trend=a["trend"], rel_pitch=a["relPitch"], rel_loud=a["relLoudness"],
            strength=b.strength, sustain=sustain[k], character=characters[k], pseg=pseg[k], seg=seg_of[k],
        ))
    live = [c for c in cuts if not c.merged]
    plans = [PlanData(-1, 0, len(blocks), st.Plan(list(blocks), dur, list(cells), list(pauses), live, window, sr))]
    gaps = []
    for sg in segments:
        sb = list(blocks[sg.first : sg.stop])
        sw = (sg.start, sg.end)
        sp = [p for p in pauses if p.end > sw[0] and p.start < sw[1]]
        sd = rh.durations(sb, sp, sw)
        local_seg = [pseg[k] - pseg[sg.first] for k in range(sg.first, sg.stop)]
        man = {k - sg.first: v for k, v in manual_cells.items() if sg.first <= k < sg.stop}
        try:
            sc = rh.quantize_raw(sd, local_seg, man, penalty).cells
        except CoreError:
            sc = None
        if sc is not None:
            plans.append(PlanData(sg.index, sg.first, sg.stop, st.Plan(sb, sd, list(sc), sp, [], sw, sr)))
        if sg.index > 0:
            gaps.append(blocks[sg.first].onset - blocks[sg.first - 1].end)
    return SampleIndex(sample_id, out_blocks, plans, gaps)


INDEX_VERSION = 1
_NUM_COLS = ("onset", "end", "lead", "midi", "spread", "coverage", "trend", "rel_pitch", "rel_loud", "strength", "sustain")


def to_wire(idx: SampleIndex, members: Sequence[Sequence[int]]) -> dict[str, Any]:
    """落库格式（msgpack）：块属性按列存；方案输入只存不能便宜重算的（时值、方案由块 + 停顿 + 窗口现算）。"""
    sent = idx.plans[0].plan
    b = idx.blocks
    return {
        "v": INDEX_VERSION,
        "id": idx.sample_id,
        "b": {
            **{k: [getattr(x, k) for x in b] for k in _NUM_COLS},
            "pseg": [x.pseg for x in b], "seg": [x.seg for x in b], "vowel": [x.vowel for x in b],
            "cons": [list(x.consonants) for x in b], "char": [x.character for x in b], "members": [list(m) for m in members],
            "bstrength": [blk.strength for blk in sent.blocks],
        },
        "pauses": [[p.start, p.end] for p in sent.pauses],
        "cuts": [[c.k, c.kind, c.left_end, c.right_start] for c in sent.cuts],
        "window": list(sent.window),
        "sr": sent.sr,
        "cells": list(sent.cells),
        "segs": [[p.scope, p.first, p.stop, p.plan.window[0], p.plan.window[1], list(p.plan.cells)] for p in idx.plans[1:]],
    }


def from_wire(w: dict[str, Any]) -> SampleIndex:
    b = w["b"]
    n = len(b["onset"])
    attrs = [
        BlockAttr(
            onset=b["onset"][i], end=b["end"][i], lead=b["lead"][i], vowel=b["vowel"][i], consonants=tuple(b["cons"][i]), midi=b["midi"][i],
            spread=b["spread"][i], coverage=b["coverage"][i], trend=b["trend"][i], rel_pitch=b["rel_pitch"][i], rel_loud=b["rel_loud"][i],
            strength=b["strength"][i], sustain=b["sustain"][i], character=b["char"][i], pseg=b["pseg"][i], seg=b["seg"][i],
        )
        for i in range(n)
    ]
    blocks = [rh.Block(b["onset"][i], b["end"][i], b["vowel"][i], tuple(b["members"][i]), b["bstrength"][i]) for i in range(n)]
    pauses = [rh.Pause(p[0], p[1]) for p in w["pauses"]]
    cuts = [rh.Cut(c[0], c[1], c[2], c[3]) for c in w["cuts"]]
    window = (w["window"][0], w["window"][1])
    sr = int(w["sr"])
    plans = [PlanData(-1, 0, n, st.Plan(blocks, rh.durations(blocks, pauses, window), list(w["cells"]), pauses, cuts, window, sr))]
    gaps = []
    for scope, first, stop, a, e, cells in w["segs"]:
        sb = blocks[first:stop]
        sw = (a, e)
        sp = [p for p in pauses if p.end > sw[0] and p.start < sw[1]]
        plans.append(PlanData(scope, first, stop, st.Plan(sb, rh.durations(sb, sp, sw), list(cells), sp, [], sw, sr)))
        if scope > 0:
            gaps.append(blocks[first].onset - blocks[first - 1].end)
    return SampleIndex(w["id"], attrs, plans, gaps)


class Batch:
    """一批采样的索引：列（向量化条件用）一次建好；完整的 ``SampleIndex`` 只在要算证据或报告命中时才按需展开。"""

    def __init__(self, sample_ids: list[str], cols: "_Cols", wires: list[dict[str, Any]] | None = None, rows: list[SampleIndex] | None = None) -> None:
        self.sample_ids = sample_ids
        self.cols = cols
        self._wires = wires
        self._rows: dict[int, SampleIndex] = dict(enumerate(rows)) if rows is not None else {}

    def __len__(self) -> int:
        return len(self.sample_ids)

    @classmethod
    def of_rows(cls, rows: Sequence[SampleIndex]) -> "Batch":
        return cls([r.sample_id for r in rows], columns(rows), rows=list(rows))

    @classmethod
    def of_wires(cls, wires: list[dict[str, Any]]) -> "Batch":
        sample, local, num, pseg = [], [], {k: [] for k in _NUM_COLS}, []  # type: ignore[var-annotated]
        vowel: list[str | None] = []
        cons: list[tuple[str, ...]] = []
        char: list[str | None] = []
        for i, w in enumerate(wires):
            b = w["b"]
            n = len(b["onset"])
            sample.extend([i] * n)
            local.extend(range(n))
            for k in _NUM_COLS:
                num[k].extend(b[k])
            pseg.extend(b["pseg"])
            vowel.extend(b["vowel"])
            cons.extend(tuple(x) for x in b["cons"])
            char.extend(b["char"])
        f = lambda k: np.array([math.nan if x is None else x for x in num[k]], dtype=np.float64)  # noqa: E731
        cols = _Cols(
            sample=np.array(sample, dtype=np.int64), local=np.array(local, dtype=np.int64), onset=f("onset"), end=f("end"), midi=f("midi"),
            spread=f("spread"), coverage=f("coverage"), trend=f("trend"), rel_pitch=f("rel_pitch"), rel_loud=f("rel_loud"), strength=f("strength"),
            sustain=f("sustain"), pseg=np.array(pseg, dtype=np.int64), vowel=vowel, consonants=cons, character=char,
        )
        return cls([w["id"] for w in wires], cols, wires=wires)

    def row(self, i: int) -> SampleIndex:
        r = self._rows.get(i)
        if r is None:
            assert self._wires is not None
            r = self._rows[i] = from_wire(self._wires[i])
        return r


# ---------------------------------------------------------------- 查询


@dataclass(frozen=True)
class BlockCond:
    note: tuple[float, float] | None = None  # 节奏策略：[起拍, 止拍)
    pitch: int | None = None  # 音级 0–11
    octave: int | None = None
    pitch_tol: float = 50.0  # 音分
    spread_max: float | None = None  # 音分
    coverage_min: float = 0.5
    vowel: str | None = None
    consonants: tuple[str, ...] | None = None  # None = 任意；() = 无前导辅音
    duration: tuple[float | None, float | None] | None = None  # 秒
    duration_mode: str = "effective"
    character: str | None = None
    trend: str | None = None
    trend_thr: float = 1.0
    rel_pitch: str | None = None
    rel_thr: float = 2.0
    loud_min: float | None = None
    strength_min: float | None = None
    beats: tuple[float | None, float | None] | None = None  # 时值（拍）
    sustain: bool = False  # 声音必须持续到块尾


@dataclass(frozen=True)
class SpeechQuery:
    blocks: tuple[BlockCond, ...]
    strategy: str = "free"
    edge: str = "any"
    edge_basis: str = "pause"
    cross: bool = False
    max_gap: float | None = None
    scope: str = "both"
    tolerance: float = 0.1  # 拍
    speed_pref: float = SPEED_PREF_DEFAULT
    speed_range: tuple[float, float] | None = None
    rest_adjust: bool = False
    length: float | None = None  # 查询长度（拍）


def _num(v: object, field_: str, lo: float | None = None, hi: float | None = None) -> float:
    if isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(float(v)):
        raise CoreError("speech-query-invalid", field=field_, block=None, reason="not-a-number")
    x = float(v)
    if (lo is not None and x < lo - 1e-12) or (hi is not None and x > hi + 1e-12):
        raise CoreError("speech-query-invalid", field=field_, block=None, reason="out-of-range")
    return x


def _range(v: object, field_: str, lo: float = 0.0) -> tuple[float | None, float | None] | None:
    if v is None:
        return None
    if not isinstance(v, (list, tuple)) or len(v) != 2:
        raise CoreError("speech-query-invalid", field=field_, block=None, reason="not-a-range")
    a = None if v[0] is None else _num(v[0], field_, lo)
    b = None if v[1] is None else _num(v[1], field_, lo)
    if a is None and b is None:
        return None
    if a is not None and b is not None and a > b:
        raise CoreError("speech-query-invalid", field=field_, block=None, reason="range-inverted")
    return (a, b)


_COND_KEYS = {
    "note", "pitch", "octave", "pitchTolerance", "spreadMax", "coverageMin", "vowel", "consonants", "duration", "durationMode",
    "character", "trend", "trendThreshold", "relPitch", "relPitchThreshold", "loudnessMin", "strengthMin", "beats", "sustain",
}
_QUERY_KEYS = {"blocks", "strategy", "edge", "edgeBasis", "cross", "maxGap", "scope", "tolerance", "speedPreference", "speedRange", "restAdjust", "length"}


def parse_query(raw: object) -> SpeechQuery:
    """界面/脚本的查询 → ``SpeechQuery``；未知字段、越界、音块重叠都报错（就地提示由界面按错误参数定位）。"""
    if not isinstance(raw, dict):
        raise CoreError("speech-query-invalid", field="query", block=None, reason="not-an-object")
    unknown = set(raw) - _QUERY_KEYS
    if unknown:
        raise CoreError("speech-query-invalid", field=sorted(unknown)[0], block=None, reason="unknown-field")
    strategy = raw.get("strategy", "free")
    if strategy not in STRATEGIES:
        raise CoreError("speech-query-invalid", field="strategy", block=None, reason="bad-value")
    items = raw.get("blocks")
    if not isinstance(items, list) or not items:
        raise CoreError("speech-query-invalid", field="blocks", block=None, reason="empty")
    if len(items) > MAX_QUERY_BLOCKS:
        raise CoreError("speech-query-invalid", field="blocks", block=None, reason="too-many-blocks")
    blocks = []
    for i, it in enumerate(items, start=1):
        try:
            blocks.append(_parse_cond(it, strategy != "free"))
        except CoreError as e:
            e.args_["block"] = i
            raise
    edge = raw.get("edge", "any")
    basis = raw.get("edgeBasis", "pause")
    scope = raw.get("scope", "both")
    if edge not in EDGES:
        raise CoreError("speech-query-invalid", field="edge", block=None, reason="bad-value")
    if basis not in EDGE_BASES:
        raise CoreError("speech-query-invalid", field="edgeBasis", block=None, reason="bad-value")
    if scope not in SCOPES:
        raise CoreError("speech-query-invalid", field="scope", block=None, reason="bad-value")
    cross = raw.get("cross", False)
    if not isinstance(cross, bool):
        raise CoreError("speech-query-invalid", field="cross", block=None, reason="bad-value")
    max_gap = None if raw.get("maxGap") is None else _num(raw["maxGap"], "maxGap", 0.0)
    length = None if raw.get("length") is None else _num(raw["length"], "length", 0.0)
    tol = 0.1 if raw.get("tolerance") is None else _num(raw["tolerance"], "tolerance", 0.0, 4.0)
    pref = SPEED_PREF_DEFAULT if raw.get("speedPreference") is None else _num(raw["speedPreference"], "speedPreference", 0.0, 1.0)
    sr = raw.get("speedRange")
    speed_range = None
    if sr is not None:
        r = _range(sr, "speedRange", 1e-6)
        if r is None or r[0] is None or r[1] is None:
            raise CoreError("speech-query-invalid", field="speedRange", block=None, reason="not-a-range")
        speed_range = (r[0], r[1])
    rest = raw.get("restAdjust", False)
    if not isinstance(rest, bool):
        raise CoreError("speech-query-invalid", field="restAdjust", block=None, reason="bad-value")
    q = SpeechQuery(tuple(blocks), strategy, edge, basis, cross, max_gap, scope, tol, pref, speed_range, rest, length)
    if strategy != "free":
        prev = None
        for i, b in enumerate(q.blocks, start=1):
            assert b.note is not None
            a, e = b.note
            if not e > a or a < 0 or (length is not None and e > length + 1e-9):
                raise CoreError("speech-query-invalid", field="note", block=i, reason="note-bounds")
            if prev is not None:
                if a < prev[1] - 1e-9:
                    raise CoreError("speech-query-invalid", field="note", block=i, reason="note-overlap")
                if not a - prev[0] > 2 * tol + 1e-12:
                    raise CoreError("speech-query-invalid", field="note", block=i, reason="onsets-too-close")
            prev = (a, e)
    return q


def _parse_cond(it: object, rhythm: bool) -> BlockCond:
    if not isinstance(it, dict):
        raise CoreError("speech-query-invalid", field="block", block=None, reason="not-an-object")
    unknown = set(it) - _COND_KEYS
    if unknown:
        raise CoreError("speech-query-invalid", field=sorted(unknown)[0], block=None, reason="unknown-field")
    kw: dict[str, Any] = {}
    if rhythm:
        n = _range(it.get("note"), "note")
        if n is None or n[0] is None or n[1] is None:
            raise CoreError("speech-query-invalid", field="note", block=None, reason="note-bounds")
        kw["note"] = (n[0], n[1])
    pitch = it.get("pitch")
    octave = it.get("octave")
    if pitch is not None:
        if isinstance(pitch, bool) or not isinstance(pitch, int) or not 0 <= pitch <= 11:
            raise CoreError("speech-query-invalid", field="pitch", block=None, reason="bad-value")
        kw["pitch"] = pitch
    if octave is not None:
        if pitch is None:
            raise CoreError("speech-query-invalid", field="octave", block=None, reason="octave-without-pitch")
        if isinstance(octave, bool) or not isinstance(octave, int) or not -1 <= octave <= 9:
            raise CoreError("speech-query-invalid", field="octave", block=None, reason="bad-value")
        kw["octave"] = octave
    if it.get("pitchTolerance") is not None:
        kw["pitch_tol"] = _num(it["pitchTolerance"], "pitchTolerance", *PITCH_TOL_RANGE)
    if it.get("spreadMax") is not None:
        kw["spread_max"] = _num(it["spreadMax"], "spreadMax", 0.0)
    if it.get("coverageMin") is not None:
        kw["coverage_min"] = _num(it["coverageMin"], "coverageMin", 0.0, 1.0)
    v = it.get("vowel")
    if v is not None:
        if v not in VOWEL_SET:
            raise CoreError("speech-query-invalid", field="vowel", block=None, reason="bad-value")
        kw["vowel"] = v
    c = it.get("consonants")
    if c is not None:
        if not isinstance(c, list) or any(not isinstance(x, str) or not x for x in c):
            raise CoreError("speech-query-invalid", field="consonants", block=None, reason="bad-value")
        kw["consonants"] = tuple(c)
    kw["duration"] = _range(it.get("duration"), "duration")
    dm = it.get("durationMode", "effective")
    if dm not in DURATION_MODES:
        raise CoreError("speech-query-invalid", field="durationMode", block=None, reason="bad-value")
    kw["duration_mode"] = dm
    ch = it.get("character")
    if ch is not None:
        if not isinstance(ch, str) or not ch:
            raise CoreError("speech-query-invalid", field="character", block=None, reason="bad-value")
        kw["character"] = ch
    tr = it.get("trend")
    if tr is not None:
        if tr not in TRENDS:
            raise CoreError("speech-query-invalid", field="trend", block=None, reason="bad-value")
        kw["trend"] = tr
    if it.get("trendThreshold") is not None:
        kw["trend_thr"] = _num(it["trendThreshold"], "trendThreshold", 0.0)
    rp = it.get("relPitch")
    if rp is not None:
        if rp not in REL_PITCHES:
            raise CoreError("speech-query-invalid", field="relPitch", block=None, reason="bad-value")
        kw["rel_pitch"] = rp
    if it.get("relPitchThreshold") is not None:
        kw["rel_thr"] = _num(it["relPitchThreshold"], "relPitchThreshold", 0.0)
    if it.get("loudnessMin") is not None:
        kw["loud_min"] = _num(it["loudnessMin"], "loudnessMin")
    if it.get("strengthMin") is not None:
        kw["strength_min"] = _num(it["strengthMin"], "strengthMin", 0.0, 1.0)
    if rhythm:
        kw["beats"] = _range(it.get("beats"), "beats")
        s = it.get("sustain", False)
        if not isinstance(s, bool):
            raise CoreError("speech-query-invalid", field="sustain", block=None, reason="bad-value")
        kw["sustain"] = s
    return BlockCond(**kw)


# ---------------------------------------------------------------- 逐块条件（向量化）


@dataclass
class _Cols:
    """一批采样的块属性列（拼接）。"""

    sample: np.ndarray  # 每块属于第几个采样
    local: np.ndarray  # 采样内的块序号
    onset: np.ndarray
    end: np.ndarray
    midi: np.ndarray  # NaN = 未知
    spread: np.ndarray
    coverage: np.ndarray
    trend: np.ndarray
    rel_pitch: np.ndarray
    rel_loud: np.ndarray
    strength: np.ndarray
    sustain: np.ndarray
    pseg: np.ndarray
    vowel: list[str | None]
    consonants: list[tuple[str, ...]]
    character: list[str | None]


def _f(x: float | None) -> float:
    return math.nan if x is None else float(x)


def columns(rows: Sequence[SampleIndex]) -> _Cols:
    bl = [(i, k, b) for i, r in enumerate(rows) for k, b in enumerate(r.blocks)]
    arr = lambda g: np.array([g(b) for _, _, b in bl], dtype=np.float64)  # noqa: E731
    return _Cols(
        sample=np.array([i for i, _, _ in bl], dtype=np.int64),
        local=np.array([k for _, k, _ in bl], dtype=np.int64),
        onset=arr(lambda b: b.onset), end=arr(lambda b: b.end), midi=arr(lambda b: _f(b.midi)), spread=arr(lambda b: _f(b.spread)),
        coverage=arr(lambda b: _f(b.coverage)), trend=arr(lambda b: _f(b.trend)), rel_pitch=arr(lambda b: _f(b.rel_pitch)),
        rel_loud=arr(lambda b: _f(b.rel_loud)), strength=arr(lambda b: _f(b.strength)), sustain=arr(lambda b: _f(b.sustain)),
        pseg=np.array([b.pseg for _, _, b in bl], dtype=np.int64),
        vowel=[b.vowel for _, _, b in bl], consonants=[b.consonants for _, _, b in bl], character=[b.character for _, _, b in bl],
    )


def pitch_deviation(midi: np.ndarray, pitch: int, octave: int | None) -> np.ndarray:
    """音分：给了八度 = 与 音级 + 12 × (八度 + 1) 的绝对差；只给音级 = 圆周距离 ((x − 音级 + 6) mod 12 − 6)。"""
    if octave is not None:
        return np.abs(midi - (pitch + 12 * (octave + 1))) * 100.0
    return np.abs(np.mod(midi - pitch + 6.0, 12.0) - 6.0) * 100.0


def block_match(c: _Cols, cond: BlockCond) -> tuple[np.ndarray, np.ndarray]:
    """（合格, 逐块分）。未知（NaN）在任何比较里都是 False（P7）。"""
    with np.errstate(invalid="ignore"):
        ok = np.ones(len(c.onset), dtype=bool)
        score = np.zeros(len(c.onset))
        if cond.pitch is not None:
            dev = pitch_deviation(c.midi, cond.pitch, cond.octave)
            ok &= dev <= cond.pitch_tol + 1e-9
            score += np.nan_to_num(dev) / max(1.0, cond.pitch_tol)
        if cond.spread_max is not None:
            ok &= c.spread <= cond.spread_max + 1e-9
            score += np.nan_to_num(c.spread) / max(1.0, cond.spread_max)
        if cond.pitch is not None or cond.spread_max is not None:
            ok &= c.coverage >= cond.coverage_min - 1e-12
        if cond.vowel is not None:
            ok &= np.array([v == cond.vowel for v in c.vowel], dtype=bool)
        if cond.consonants is not None:
            ok &= np.array([x == cond.consonants for x in c.consonants], dtype=bool)
        if cond.duration is not None:
            if cond.duration_mode == "effective":
                d = np.maximum(0.0, np.minimum(c.end, c.sustain) - c.onset)  # 持续未知 → NaN → 不通过
            else:
                d = c.end - c.onset
            lo, hi = cond.duration
            if lo is not None:
                ok &= d >= lo - 1e-9
            if hi is not None:
                ok &= d <= hi + 1e-9
        if cond.character is not None:
            ok &= np.array([x == cond.character for x in c.character], dtype=bool)
        if cond.trend is not None:
            ok &= (c.trend >= cond.trend_thr - 1e-9) if cond.trend == "up" else (c.trend <= -cond.trend_thr + 1e-9)
        if cond.rel_pitch is not None:
            ok &= (c.rel_pitch >= cond.rel_thr - 1e-9) if cond.rel_pitch == "high" else (c.rel_pitch <= -cond.rel_thr + 1e-9)
        if cond.loud_min is not None:
            ok &= c.rel_loud >= cond.loud_min - 1e-9
        if cond.strength_min is not None:
            ok &= c.strength >= cond.strength_min - 1e-12
        if cond.sustain:
            ok &= np.isfinite(c.sustain)  # 要求持续但持续未知 → 不命中（R14.7）
    return ok, score


def windows(c: _Cols, q: SpeechQuery) -> tuple[np.ndarray, np.ndarray]:
    """合格窗口的首块（拼接序号）与逐块分之和。"""
    n = len(q.blocks)
    N = len(c.onset)
    if N < n:
        return np.zeros(0, dtype=np.int64), np.zeros(0)
    W = N - n + 1
    ok = np.ones(W, dtype=bool)
    score = np.zeros(W)
    same = c.sample[n - 1 :] == c.sample[:W]  # 同一采样（采样内连续）
    ok &= same
    for j, cond in enumerate(q.blocks):
        m, s = block_match(c, cond)
        ok &= m[j : j + W]
        score += s[j : j + W]
    if not q.cross:
        ok &= c.pseg[n - 1 :] == c.pseg[:W]
    if q.max_gap is not None and n > 1:
        gap = c.onset[1:] - c.end[:-1]  # 下一块起音 − 上一块结束
        bad = gap > q.max_gap + 1e-9
        P = np.zeros(len(bad) + 1, dtype=np.int64)
        np.cumsum(bad, out=P[1:])
        ok &= (P[np.arange(W) + n - 1] - P[np.arange(W)]) == 0
    if q.edge != "any":
        first = np.ones(N, dtype=bool)
        first[1:] = c.sample[1:] != c.sample[:-1]
        last = np.ones(N, dtype=bool)
        last[:-1] = c.sample[1:] != c.sample[:-1]
        if q.edge_basis == "pause":
            first[1:] |= c.pseg[1:] != c.pseg[:-1]
            last[:-1] |= c.pseg[1:] != c.pseg[:-1]
        if q.edge in ("head", "both"):
            ok &= first[:W]
        if q.edge in ("tail", "both"):
            ok &= last[n - 1 :]
    idx = np.flatnonzero(ok)
    return idx, score[idx]


# ---------------------------------------------------------------- 节奏证据


@dataclass(frozen=True)
class Evidence:
    strict: bool
    cost: float
    error: float  # 平均起音误差（拍；归一化形状下是查询拍）
    conflicts: int
    deficit: float  # 持续不足的平均（拍）
    speed: float | None
    density: float | None
    bpm: float | None
    plan: str | None  # near_fast / near_slow / None（无 BPM）
    scope: int  # -1 整句 / 语段号
    shift: float  # 拍
    deform: float
    rests: tuple[int, ...] = ()  # 段间休止调整后的格数（窗口内的连接；没调整为空）
    changed: int = 0


@dataclass
class _SchemeView:
    """一个方案在检索里要用的量（帧域精确映射 → 拍）。"""

    density: float
    bpm: float
    speed: float
    ratio: float
    cps: list[st.ControlPoint]
    tm: st.TimeMap
    beat0: float
    t0: int

    def beat_exact(self, src: float) -> float:
        f = self.tm.to_target((src - self.tm.w0) * self.tm.sr)
        return self.beat0 + (f - self.t0) / (self.tm.beat_seconds * self.tm.sr)

    def beat_linear(self, src: float) -> float:
        """控制点之间线性插值（09 §9.6.4 (2)）；两端外推用首末两段的斜率。"""
        xs = [c.src for c in self.cps]
        ys = [c.beat for c in self.cps]
        if len(xs) == 1:
            return ys[0]
        if src <= xs[0]:
            return ys[0] + (src - xs[0]) * (ys[1] - ys[0]) / (xs[1] - xs[0])
        if src >= xs[-1]:
            return ys[-1] + (src - xs[-1]) * (ys[-1] - ys[-2]) / (xs[-1] - xs[-2])
        return float(np.interp(src, xs, ys))


def scheme_view(s: st.Scheme) -> _SchemeView:
    m = s.map
    return _SchemeView(s.density, s.bpm, s.speed, s.ratio, m.cps, m, m.cps[0].beat, m.onsets[0])


SchemeCache = dict[tuple[str, int, float | None], dict[str, _SchemeView] | None]


def schemes_for(row: SampleIndex, plan: PlanData, bpm: float, cache: SchemeCache | None) -> dict[str, _SchemeView] | None:
    key = (row.sample_id, plan.scope, bpm)
    if cache is not None and key in cache:
        return cache[key]
    try:
        cand = st.candidates(plan.plan, bpm)
        out: dict[str, _SchemeView] | None = {k: scheme_view(cand[k]) for k in ("near_fast", "near_slow")}
    except CoreError:
        out = None
    if cache is not None:
        cache[key] = out
    return out


def _deform(sv: _SchemeView, first_onset: float, last_onset: float) -> float:
    """形变：窗口内相邻控制点（窗口各块起音 … 末块之后的第一个控制点）的局部时长比 ÷ 整体倍率，取 |ln| 的平均。"""
    pts = [i for i, c in enumerate(sv.cps) if first_onset - 1e-9 <= c.src <= last_onset + 1e-9]
    if not pts:
        return 0.0
    hi = pts[-1] + 1 if pts[-1] + 1 < len(sv.cps) else pts[-1]
    idx = list(range(pts[0], hi + 1))
    vals = []
    for a, b in zip(idx, idx[1:]):
        ds = sv.cps[b].src - sv.cps[a].src
        dt = (sv.cps[b].beat - sv.cps[a].beat) * sv.tm.beat_seconds
        if ds > 0 and dt > 0:
            vals.append(abs(math.log(dt / ds / sv.ratio)))
    return float(np.mean(vals)) if vals else 0.0


def _shift_fit(x: list[float], others: list[float], notes: list[tuple[float, float]], tol: float, lower: float) -> tuple[float, float, float] | None:
    """平移拟合：可行平移里取（平均误差, 最大误差, |平移|）最小者；无可行返回 None。返回（平移, 平均误差, 最大误差）。
    可行 = 每个起音偏差 ≤ 容差、每个音符块 [起拍, 止拍) 内没有其他起音、平移 ≥ ``lower``（持续到块尾的要求）。"""
    d = [a - xi for (a, _b), xi in zip(notes, x)]
    L = max(max(di - tol for di in d), lower)
    U = min(di + tol for di in d)
    if L > U + 1e-12:
        return None
    excl = [(a - y, b - y) for y in others for (a, b) in notes]  # 平移落在 [a − y, b − y) 时 y 进了这个音符块
    cands = {L, U, 0.0, *d}
    for i in range(len(d)):
        for j in range(i + 1, len(d)):
            cands.add((d[i] + d[j]) / 2)
    for a, b in excl:
        cands.add(b)
        cands.add(a - 1e-9)
    best: tuple[float, float, float, float] | None = None
    for s in sorted(cands):
        if not (L - 1e-12 <= s <= U + 1e-12):
            continue
        if any(a - 1e-12 <= s < b - 1e-12 for a, b in excl):
            continue
        errs = [abs(xi + s - a) for xi, (a, _b) in zip(x, notes)]
        key = (float(np.mean(errs)), max(errs), abs(s), s)
        if best is None or key < best:
            best = key
    if best is None:
        return None
    return best[3], best[0], best[1]


def _conflicts(others: list[float], notes: list[tuple[float, float]], shift: float) -> int:
    return sum(1 for y in others for a, b in notes if a - 1e-9 <= y + shift < b - 1e-9)


def evidence_for_window(
    row: SampleIndex, i0: int, q: SpeechQuery, bpm: float | None, cache: SchemeCache | None = None
) -> Evidence | None:
    """窗口（采样内首块 ``i0``）在允许的范围与候选方案里的最优证据；算不出返回 None（计入“缺少有效分析”）。"""
    n = len(q.blocks)
    notes = [b.note for b in q.blocks]
    assert all(nt is not None for nt in notes)
    notes_ = [(float(a), float(b)) for a, b in notes]  # type: ignore[misc]
    plans = []
    for p in row.plans:
        if not (p.first <= i0 and i0 + n <= p.stop):
            continue
        if p.scope < 0 and q.scope == "segment":
            continue
        if p.scope >= 0 and q.scope == "sentence":
            continue
        plans.append(p)
    best: tuple[tuple[float, bool], Evidence] | None = None
    for p in plans:
        if bpm is None:
            ev = _shape_evidence(row, p, i0, q, notes_)
            cands = [ev] if ev is not None else []
        else:
            sv = schemes_for(row, p, bpm, cache)
            if sv is None:
                continue
            cands = []
            for name in ("near_fast", "near_slow"):
                v = sv[name]
                if q.speed_range is not None and not (q.speed_range[0] - 1e-9 <= v.speed <= q.speed_range[1] + 1e-9):
                    continue
                ev = _beat_evidence(row, p, i0, q, notes_, v, name)
                if ev is not None:
                    cands.append(ev)
        for ev in cands:
            if q.strategy == "strict" and not ev.strict:
                continue
            key = (round(ev.cost, 10), ev.speed is not None and ev.speed < 1)
            if best is None or key < best[0]:
                best = (key, ev)
    return None if best is None else best[1]


def _beat_evidence(row: SampleIndex, p: PlanData, i0: int, q: SpeechQuery, notes: list[tuple[float, float]], sv: _SchemeView, name: str) -> Evidence | None:
    n = len(q.blocks)
    blocks = row.blocks
    win = range(i0, i0 + n)
    # 起音的拍 = 该块控制点的目标拍（精确）
    onset_beat = {c.block + p.first: c.beat for c in sv.cps if c.kind == "onset"}
    exact = q.strategy == "strict"
    x = [onset_beat[k] for k in win]
    others = [onset_beat[k] for k in range(p.first, p.stop) if k not in win]
    to_beat = sv.beat_exact if exact else sv.beat_linear
    # 时值（拍）：按精确映射（平移拟合）或线性插值（中位数平移）；不满足 → 这个候选作废
    for j, k in enumerate(win):
        cond = q.blocks[j]
        if cond.beats is not None:
            dur = to_beat(blocks[k].end) - (x[j] if exact else to_beat(blocks[k].onset))
            lo, hi = cond.beats
            if (lo is not None and dur < lo - 1e-9) or (hi is not None and dur > hi + 1e-9):
                return None
    sus: list[float | None] = []
    for j, k in enumerate(win):
        if q.blocks[j].sustain:
            s = blocks[k].sustain
            if s is None:
                return None
            sus.append(to_beat(s))
        else:
            sus.append(None)
    deform = _deform(sv, blocks[i0].onset, blocks[i0 + n - 1].onset)
    speed_cost = q.speed_pref * abs(math.log2(sv.speed)) if sv.speed > 0 else math.inf
    rests_base: tuple[int, ...] = ()
    combos: list[tuple[tuple[int, ...], int, list[float]]] = [((), 0, x)]
    if q.rest_adjust and p.scope < 0:
        combos = _rest_combos(row, p, i0, n, sv, notes, x)
        rests_base = combos[0][0]
    results: list[tuple[tuple[float, int, float], Evidence]] = []
    for rests, changed, xs in combos:
        shift_x = [xs[j] - x[j] for j in range(n)]
        sus_ = [None if s is None else s + shift_x[j] for j, s in enumerate(sus)]
        oth = _shift_others(others, x, xs, p, i0, n, onset_beat)
        if exact:
            lower = max([b - s for (a, b), s in zip(notes, sus_) if s is not None], default=-math.inf)
            fit = _shift_fit(xs, oth, notes, q.tolerance, lower)
            if fit is None:
                continue
            delta, err, _mx = fit
            cost = err + DEFORM_WEIGHT * deform + REST_WEIGHT * changed + speed_cost
            ev = Evidence(True, cost, err, 0, 0.0, sv.speed, sv.density, sv.bpm, name, p.scope, delta, deform, rests if rests != rests_base else (), changed)
            rank_err = err
        else:
            delta = float(np.median([a - xi for (a, _b), xi in zip(notes, xs)]))
            dev = [abs(xi + delta - a) for xi, (a, _b) in zip(xs, notes)]
            deficit = [0.0 if s is None else max(0.0, b - (s + delta)) for (a, b), s in zip(notes, sus_)]
            conf = _conflicts(oth, notes, delta)
            worst = [max(dv, df) for dv, df in zip(dev, deficit)]
            err = float(np.mean(worst))
            cost = err + conf + REST_WEIGHT * changed + speed_cost
            strict = max(worst) <= q.tolerance + 1e-9 and conf == 0
            ev = Evidence(strict, cost, float(np.mean(dev)), conf, float(np.mean(deficit)), sv.speed, sv.density, sv.bpm, name, p.scope, delta, deform,
                          rests if rests != rests_base else (), changed)
            rank_err = err + conf
        results.append(((rank_err, changed, cost), ev))
        if rank_err == 0 and changed == 0:
            break
    if not results:
        return None
    results.sort(key=lambda r: r[0])
    return results[0][1]


def _shift_others(others: list[float], x: list[float], xs: list[float], p: PlanData, i0: int, n: int, onset_beat: dict[int, float]) -> list[float]:
    """段间休止调整后，窗口之后的其他起音跟着末块平移（窗口之前的不动）。"""
    if xs == x:
        return others
    tail = xs[-1] - x[-1]
    out = []
    for k in range(p.first, p.stop):
        if i0 <= k < i0 + n:
            continue
        out.append(onset_beat[k] + (tail if k >= i0 + n else 0.0))
    return out


def _rest_combos(row: SampleIndex, p: PlanData, i0: int, n: int, sv: _SchemeView, notes: list[tuple[float, float]], x: list[float]) -> list[tuple[tuple[int, ...], int, list[float]]]:
    """段间休止调整（09 §9.6.6）：窗口内各语段连接的休止格数组合（≤ 128 种），返回（格数, 改动格数, 调整后的起音拍）。
    默认格数 = 方案里该连接的休止格（目标拍差 − 左段末块占格 / 密度，换成格）；范围 1 – max(32, 默认)。"""
    seg = [row.blocks[k].seg for k in range(i0, i0 + n)]
    joints = [j for j in range(1, n) if seg[j] != seg[j - 1]]  # 窗口内第 j 块是新语段的第一块
    if not joints:
        return [((), 0, list(x))]
    dens = sv.density
    cells = list(p.plan.cells)
    defaults = []
    for j in joints:
        k = i0 + j - 1  # 左段末块（采样内）
        gap_beats = x[j] - x[j - 1] - cells[k - p.first] / dens
        defaults.append(max(1, int(round(gap_beats * dens))))
    ranges = [(1, max(REST_RANGE_MIN, d)) for d in defaults]
    per: list[list[int]] = []
    for jj, (j, d) in enumerate(zip(joints, defaults)):
        want = (notes[j][0] - notes[j - 1][0]) - (x[j] - x[j - 1])  # 查询要的起音间距 − 方案的
        need = d + int(round(want * dens))
        lo, hi = ranges[jj]
        vals = [d]
        for v in (need, need - 1, need + 1, d - 1, d + 1, d - 2, d + 2):
            v = max(lo, min(hi, v))
            if v not in vals:
                vals.append(v)
        if len(joints) == 1:
            vals = [d] + [v for v in range(lo, hi + 1) if v != d]
        per.append(vals)
    combos: list[tuple[int, ...]] = [()]
    for vals in per:
        combos = [c + (v,) for c in combos for v in vals][:REST_COMBOS_MAX]
    out = []
    for combo in combos[:REST_COMBOS_MAX]:
        xs = list(x)
        acc = 0.0
        for j in range(n):
            if j in joints:
                jj = joints.index(j)
                acc += (combo[jj] - defaults[jj]) / dens
            xs[j] = x[j] + acc
        changed = sum(abs(c - d) for c, d in zip(combo, defaults))
        out.append((tuple(combo), changed, xs))
    return out


def _shape_evidence(row: SampleIndex, p: PlanData, i0: int, q: SpeechQuery, notes: list[tuple[float, float]]) -> Evidence | None:
    """无 BPM：实际位置按 [首个命中起音, 末个命中块尾] 归一到 0–1，查询按 [首块起拍, 末块止拍]，容差也除以查询跨度；其余同中位数平移，没有速度项。"""
    n = len(q.blocks)
    blocks = row.blocks
    t0, t1 = blocks[i0].onset, blocks[i0 + n - 1].end
    if not t1 > t0:
        return None
    a0, a1 = notes[0][0], notes[-1][1]
    span_q = a1 - a0
    norm = lambda t: (t - t0) / (t1 - t0)  # noqa: E731
    qn = [((a - a0) / span_q, (b - a0) / span_q) for a, b in notes]
    tol = q.tolerance / span_q
    x = [norm(blocks[k].onset) for k in range(i0, i0 + n)]
    others = [norm(blocks[k].onset) for k in range(p.first, p.stop) if not i0 <= k < i0 + n]
    for j, k in enumerate(range(i0, i0 + n)):
        cond = q.blocks[j]
        if cond.beats is not None:
            dur = (norm(blocks[k].end) - x[j]) * span_q
            lo, hi = cond.beats
            if (lo is not None and dur < lo - 1e-9) or (hi is not None and dur > hi + 1e-9):
                return None
    sus: list[float | None] = []
    for j, k in enumerate(range(i0, i0 + n)):
        if q.blocks[j].sustain:
            s = blocks[k].sustain
            if s is None:
                return None
            sus.append(norm(s))
        else:
            sus.append(None)
    delta = float(np.median([a - xi for (a, _b), xi in zip(qn, x)]))
    dev = [abs(xi + delta - a) for xi, (a, _b) in zip(x, qn)]
    deficit = [0.0 if s is None else max(0.0, b - (s + delta)) for (a, b), s in zip(qn, sus)]
    conf = _conflicts(others, qn, delta)
    worst = [max(dv, df) for dv, df in zip(dev, deficit)]
    err = float(np.mean(worst))
    strict = max(worst) <= tol + 1e-9 and conf == 0
    return Evidence(strict, err + conf, float(np.mean(dev)) * span_q, conf, float(np.mean(deficit)) * span_q, None, None, None, None, p.scope, delta * span_q, 0.0)


# ---------------------------------------------------------------- 检索


@dataclass(frozen=True)
class SpeechHit:
    sample: int  # 输入 ``rows`` 的序号
    first: int  # 采样内首块
    count: int
    start: float  # 命中区（资产局部秒）：首块前导辅音开始
    end: float  # 末块结束
    score: float
    block_score: float
    evidence: Evidence | None


@dataclass
class SpeechOutcome:
    hits: list[SpeechHit]  # 已排序：按（最佳分数, 采样）分组，采样内按（分数, 起点）
    windows: int = 0
    no_evidence: int = 0
    cancelled: bool = False


def search(rows: "Batch | Sequence[SampleIndex]", q: SpeechQuery, bpm: float | None, cache: SchemeCache | None = None,
           cancel: Callable[[], bool] | None = None) -> SpeechOutcome:
    batch = rows if isinstance(rows, Batch) else Batch.of_rows(rows)
    c = batch.cols
    idx, bscore = windows(c, q)
    n = len(q.blocks)
    hits: list[SpeechHit] = []
    no_ev = 0
    for w, (g, s) in enumerate(zip(idx, bscore)):
        if cancel is not None and w % 256 == 0 and cancel():
            return SpeechOutcome([], len(idx), no_ev, cancelled=True)
        si = int(c.sample[g])
        i0 = int(c.local[g])
        row = batch.row(si)
        ev = None
        if q.strategy != "free":
            ev = evidence_for_window(row, i0, q, bpm, cache)
            if ev is None:
                no_ev += 1
                continue
        total = float(s) + (ev.cost if ev is not None else 0.0)
        b0, b1 = row.blocks[i0], row.blocks[i0 + n - 1]
        hits.append(SpeechHit(si, i0, n, b0.lead, b1.end, total, float(s), ev))
    return SpeechOutcome(order_hits(hits, batch.sample_ids), len(idx), no_ev)


def order_hits(hits: list[SpeechHit], sample_ids: Sequence[str]) -> list[SpeechHit]:
    by: dict[int, list[SpeechHit]] = {}
    for h in hits:
        by.setdefault(h.sample, []).append(h)
    groups = []
    for si, hs in by.items():
        hs.sort(key=lambda h: (round(h.score, 10), h.start, h.first))
        groups.append((round(hs[0].score, 10), sample_ids[si], hs))
    groups.sort(key=lambda g: (g[0], g[1]))
    return [h for _, _, hs in groups for h in hs]
