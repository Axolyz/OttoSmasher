"""独立音高检索（规格 10 §10.2，16 R15）。纯函数 + numpy，不做 IO、不跑模型。

时钟：一律是**资产帧**（10 ms 一帧，第 k 帧 = 资产局部 [k × 10 ms, (k+1) × 10 ms)，10 §10.1）；台词标注是资产局部秒。

查询：1–16 个块首尾相接；块 = (帧数, 低 MIDI, 高 MIDI)，帧数 = floor(秒 / 0.01 + 0.5)，每块 ≥ 10 帧，总长 ≤ 1000 帧。
所有者 2026-10-08 新增：**滑音块**（两端各一个音带，块内第 j 帧的音带按 (j + 0.5) / d 线性插值）。

判定（10 §10.2.4 第 4 步的严格条件，【基线参数】）：
- 可靠帧 = 有声 且 F0 > 0 且 置信度 ≥ 0.5（未测的帧不可靠）；
- 整个查询窗内最长连续不可靠帧 ≤ 最长缺口；
- 每块：带内可靠帧（到音带的距离 ≤ 容差）/ 块帧数 ≥ 有效覆盖，且至少 1 个可靠帧；稳定度（可靠帧 MIDI 的 P90 − P10）、能量（全部帧的平均）若设置须满足；
- 窗口分 = 各块“可靠帧到音带的距离（音分，带内为 0）的平均值”再对各块取平均。

所有者 2026-10-08【基线变更 10 §10.2.4】**完整检索**：每个允许的 10 ms 起点都严格判定（不再 50 ms 粗筛、2000 候选、只留 100 个）；
同一段声音里相邻的合格起点为一组，每组留最好的一个窗口；全部返回。另有两个开关（默认关）：
- 忽略八度：整条查询一起移 12N 个半音（各块同一个 N）；
- 时长弹性：查询总长按倍数 r ∈ [下限, 上限]（步长 0.01）变成 T = floor(D × r + 0.5) 帧，各块边界按比例取整。
窗口的比较键 = (分数, |ln(T/D)|, |N|, N, 起点, T)，分数按 1e-4 音分取整后比较（前缀和的浮点误差不影响次序）。

基线的近似流程（50 ms 摘要粗筛 → 盆地分组 → 轮询 2000 候选 → ±50 ms 精排 → 最多 100）保留为 ``search_approx``，只作对照（测试用）。
"""

from __future__ import annotations

import math
import re
import warnings
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field

import numpy as np

from ..core.errors import CoreError
from .flatten import ENERGY_FLOOR, RELIABLE_CONF, VOICED_CONF, note_name, note_to_midi

ALGO_VERSION = "pitch-search-2"
FRAME = 0.01
MIN_BLOCK_FRAMES = 10
MAX_QUERY_FRAMES = 1000
MAX_BLOCKS = 16
MIDI_RANGE = (0, 127)
ELASTIC_DEFAULT = (0.8, 1.25)
ELASTIC_RANGE = (0.5, 2.0)
ELASTIC_STEP = 0.01
SCORE_QUANTUM = 1e-4  # 音分：比较分数时的取整
CHUNK = 1 << 18  # 稳定度 / 滑音逐块计算时每批的起点数

PARAM_DEFAULTS: dict[str, object] = {
    "tolerance": 50.0,  # 音分
    "coverage": 0.8,
    "maxGap": 0.12,  # 秒
    "stability": None,  # 音分（P90 − P10 上限）
    "energyMin": None,
    "energyMax": None,
    "ignoreOctave": False,
    "elastic": None,  # [下限, 上限]
    "headTolerance": None,  # 秒（原片模式：句首）
    "tailTolerance": None,  # 秒（原片模式：句尾）
}
_RANGES: dict[str, tuple[float, float]] = {
    "tolerance": (0.0, 1200.0),
    "coverage": (0.0, 1.0),
    "maxGap": (0.0, 10.0),
    "stability": (0.0, 12000.0),
    "energyMin": (0.0, math.inf),
    "energyMax": (0.0, math.inf),
    "headTolerance": (0.0, 5.0),
    "tailTolerance": (0.0, 5.0),
}


# ---------------------------------------------------------------- 查询


@dataclass(frozen=True)
class QBlock:
    frames: int
    lo: float
    hi: float
    lo2: float | None = None  # 滑音块的终点音带；None = 普通块
    hi2: float | None = None

    @property
    def glide(self) -> bool:
        return self.lo2 is not None

    def band(self, d: int) -> tuple[np.ndarray, np.ndarray]:
        """d 帧时逐帧的音带（滑音线性插值；普通块常数）。"""
        if not self.glide:
            return np.full(d, self.lo), np.full(d, self.hi)
        x = (np.arange(d) + 0.5) / d
        assert self.lo2 is not None and self.hi2 is not None
        return self.lo + (self.lo2 - self.lo) * x, self.hi + (self.hi2 - self.hi) * x

    @property
    def low_bound(self) -> float:
        return min(self.lo, self.lo2) if self.lo2 is not None else self.lo

    @property
    def high_bound(self) -> float:
        return max(self.hi, self.hi2) if self.hi2 is not None else self.hi


@dataclass(frozen=True)
class Query:
    blocks: tuple[QBlock, ...]

    @property
    def frames(self) -> int:
        return sum(b.frames for b in self.blocks)


def seconds_to_frames(seconds: float) -> int:
    return int(math.floor(seconds / FRAME + 0.5 + 1e-9))


def _note(text: object) -> int | None:
    if not isinstance(text, str):
        return None
    n = note_to_midi(text.replace("♯", "#").replace("♭", "b"))
    return n if n is not None and MIDI_RANGE[0] <= n <= MIDI_RANGE[1] else None


def _band(spec: object) -> tuple[int, int] | str:
    """{"low": "A4", "high": "C5" | None} → (低, 高)；出错返回原因码。"""
    if not isinstance(spec, dict):
        return "bad-note"
    lo = _note(spec.get("low"))
    hi_raw = spec.get("high")
    hi = lo if hi_raw in (None, "") else _note(hi_raw)
    if lo is None or hi is None:
        return "bad-note"
    if lo > hi:
        return "range-inverted"
    return lo, hi


def check_blocks(items: object) -> tuple[Query | None, list[dict[str, object]]]:
    """界面的块（``{"seconds", "low", "high"?, "glide"?: {"low", "high"?}}``）→ 查询；同时给出全部就地提示（块号从 1 起）。"""
    errors: list[dict[str, object]] = []
    if not isinstance(items, list) or not items:
        return None, [{"block": None, "reason": "empty"}]
    if len(items) > MAX_BLOCKS:
        errors.append({"block": None, "reason": "too-many-blocks", "max": MAX_BLOCKS})
    blocks: list[QBlock] = []
    for i, it in enumerate(items, start=1):
        if not isinstance(it, dict):
            errors.append({"block": i, "reason": "bad-block"})
            continue
        sec = it.get("seconds")
        if isinstance(sec, bool) or not isinstance(sec, (int, float)) or not math.isfinite(sec):
            errors.append({"block": i, "reason": "bad-duration"})
            continue
        frames = seconds_to_frames(float(sec))
        if frames < MIN_BLOCK_FRAMES:
            errors.append({"block": i, "reason": "too-short", "min": MIN_BLOCK_FRAMES * FRAME})
            continue
        a = _band(it)
        if isinstance(a, str):
            errors.append({"block": i, "reason": a})
            continue
        g = it.get("glide")
        if g is not None:
            b = _band(g)
            if isinstance(b, str):
                errors.append({"block": i, "reason": b})
                continue
            blocks.append(QBlock(frames, float(a[0]), float(a[1]), float(b[0]), float(b[1])))
        else:
            blocks.append(QBlock(frames, float(a[0]), float(a[1])))
    total = sum(b.frames for b in blocks)
    if total > MAX_QUERY_FRAMES:
        errors.append({"block": None, "reason": "too-long", "max": MAX_QUERY_FRAMES * FRAME})
    if errors:
        return None, errors
    return Query(tuple(blocks)), []


def parse_query(items: object) -> Query:
    q, errors = check_blocks(items)
    if q is None:
        e = errors[0]
        raise CoreError("pitch-query-invalid", block=e.get("block"), reason=e["reason"])
    return q


_LINE_RE = re.compile(r"^\s*([0-9]*\.?[0-9]+)\s+(\S+?)\s*$")


def _text_band(s: str) -> dict[str, object]:
    if ".." in s:
        lo, hi = s.split("..", 1)
        return {"low": lo.strip(), "high": hi.strip()}
    return {"low": s.strip(), "high": None}


def text_to_blocks(text: str) -> tuple[list[dict[str, object]], list[dict[str, object]]]:
    """文本辅助格式（复制/粘贴）：每行 ``秒数 音高`` / ``秒数 低..高`` / ``秒数 起->止``（滑音，也接受 →）。返回（块, 逐行错误）。"""
    out: list[dict[str, object]] = []
    errors: list[dict[str, object]] = []
    for no, raw in enumerate(text.splitlines(), start=1):
        if not raw.strip():
            continue
        line = raw.replace("→", "->")
        if "->" in line:
            head, _, tail = line.partition("->")
            parts = head.split()
            if len(parts) != 2 or not tail.strip():
                errors.append({"line": no, "reason": "bad-line"})
                continue
            try:
                sec = float(parts[0])
            except ValueError:
                errors.append({"line": no, "reason": "bad-line"})
                continue
            out.append({"seconds": sec, **_text_band(parts[1]), "glide": _text_band(tail.strip())})
            continue
        m = _LINE_RE.match(line)
        if m is None:
            errors.append({"line": no, "reason": "bad-line"})
            continue
        out.append({"seconds": float(m.group(1)), **_text_band(m.group(2))})
    return out, errors


def blocks_to_text(q: Query) -> str:
    def band(lo: float, hi: float) -> str:
        return note_name(int(lo)) if lo == hi else f"{note_name(int(lo))}..{note_name(int(hi))}"

    lines = []
    for b in q.blocks:
        s = f"{b.frames * FRAME:.2f} {band(b.lo, b.hi)}"
        if b.glide:
            assert b.lo2 is not None and b.hi2 is not None
            s += f"->{band(b.lo2, b.hi2)}"
        lines.append(s)
    return "\n".join(lines)


def check_params(params: object, *, mode: str = "samples") -> dict[str, object]:
    """参数：未知参数报错；越界报错；可靠门槛不能调低（没有这个参数）。原片模式才有句首/句尾容差。"""
    if params is None:
        params = {}
    if not isinstance(params, dict):
        raise CoreError("pitch-param-invalid", field="params", min=None, max=None)
    out = dict(PARAM_DEFAULTS)
    for k, v in params.items():
        if k not in PARAM_DEFAULTS:
            raise CoreError("pitch-param-unknown", field=str(k))
        if v is None:
            out[k] = None if k not in ("tolerance", "coverage", "maxGap", "ignoreOctave") else PARAM_DEFAULTS[k]
            continue
        if k == "ignoreOctave":
            if not isinstance(v, bool):
                raise CoreError("pitch-param-invalid", field=k, min=None, max=None)
            out[k] = v
            continue
        if k == "elastic":
            if (
                not isinstance(v, (list, tuple)) or len(v) != 2
                or any(isinstance(x, bool) or not isinstance(x, (int, float)) for x in v)
                or not (ELASTIC_RANGE[0] - 1e-9 <= v[0] <= v[1] <= ELASTIC_RANGE[1] + 1e-9)
            ):
                raise CoreError("pitch-param-invalid", field=k, min=ELASTIC_RANGE[0], max=ELASTIC_RANGE[1])
            out[k] = (float(v[0]), float(v[1]))
            continue
        lo, hi = _RANGES[k]
        if isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(float(v)) or not lo <= float(v) <= hi:
            raise CoreError("pitch-param-invalid", field=k, min=lo, max=None if math.isinf(hi) else hi)
        out[k] = float(v)
    if out["energyMin"] is not None and out["energyMax"] is not None and out["energyMin"] > out["energyMax"]:  # type: ignore[operator]
        raise CoreError("pitch-param-invalid", field="energyMax", min=out["energyMin"], max=None)
    if mode != "sources" and (out["headTolerance"] is not None or out["tailTolerance"] is not None):
        raise CoreError("pitch-param-unknown", field="headTolerance" if out["headTolerance"] is not None else "tailTolerance")
    return out


def variants(q: Query, elastic: tuple[float, float] | None) -> list[tuple[int, tuple[int, ...]]]:
    """时长弹性的变体：(总帧数 T, 各块帧数)。不开弹性 = 只有原查询。"""
    D = q.frames
    lengths = [b.frames for b in q.blocks]
    if elastic is None:
        return [(D, tuple(lengths))]
    lo, hi = elastic
    n = int(round((hi - lo) / ELASTIC_STEP))
    totals = sorted({int(math.floor(D * (lo + k * ELASTIC_STEP) + 0.5 + 1e-9)) for k in range(n + 1)})
    cum = np.cumsum([0] + lengths)
    out = []
    for T in totals:
        edges = [int(math.floor(c * T / D + 0.5 + 1e-9)) for c in cum]
        ls = tuple(b - a for a, b in zip(edges, edges[1:]))
        if min(ls) >= 1:
            out.append((T, ls))
    return out


# ---------------------------------------------------------------- 输入的声音


@dataclass
class Sound:
    """一段连续的已测帧（资产帧 ``first`` 起）与它上面的检索范围。

    ``spans``：每个候选（采样，或原片模式的整条音轨）的帧区间 [s, e)（资产帧）；窗口必须完整落在某一个区间里（不拼接相邻采样）。
    ``lines``：原片模式的台词（资产局部秒 [起, 止)）；``None`` = 没有标注或没有映射（句首/句尾条件下记为“边界未知”）。"""

    key: str
    first: int
    f0: np.ndarray
    conf: np.ndarray
    energy: np.ndarray
    spans: list[tuple[int, int]]
    lines: list[tuple[float, float]] | None = None

    def __len__(self) -> int:
        return len(self.f0)


@dataclass(frozen=True)
class Hit:
    sound: int  # 输入 ``sounds`` 的序号
    start: int  # 资产帧
    frames: int  # T
    octave: int  # N
    score: float  # 音分
    blocks: tuple[tuple[int, int, float], ...] = ()  # 每块（帧数, 带内可靠帧, 平均距离）

    @property
    def end(self) -> int:
        return self.start + self.frames


@dataclass
class Outcome:
    hits: list[Hit]
    windows: int = 0  # 判定过的（起点 × 变体）个数
    unknown_bounds: int = 0  # 句首/句尾条件下没有标注的声音
    cancelled: bool = False
    stats: dict[str, object] = field(default_factory=dict)


def reliable_mask(f0: np.ndarray, conf: np.ndarray, energy: np.ndarray) -> np.ndarray:
    with np.errstate(invalid="ignore"):
        return (conf > VOICED_CONF) & (energy > ENERGY_FLOOR) & np.isfinite(f0) & (f0 > 0) & (conf >= RELIABLE_CONF)


def to_midi(f0: np.ndarray, rel: np.ndarray) -> np.ndarray:
    m = np.full(len(f0), np.nan)
    with np.errstate(divide="ignore", invalid="ignore"):
        m[rel] = 69.0 + 12.0 * np.log2(f0[rel].astype(np.float64) / 440.0)
    return m


def _cum(x: np.ndarray) -> np.ndarray:
    out = np.zeros(len(x) + 1, dtype=np.int64 if x.dtype == bool or np.issubdtype(x.dtype, np.integer) else np.float64)
    np.cumsum(x, out=out[1:])
    return out


def _dist(m: np.ndarray, lo: np.ndarray | float, hi: np.ndarray | float, fold: bool) -> np.ndarray:
    """可靠帧到音带的距离（半音，带内 0）；``fold`` = 到任一 12N 平移的音带的最近距离（忽略八度的预筛下界）。NaN 帧给 NaN。"""
    if not fold:
        return np.maximum(0.0, np.maximum(lo - m, m - hi))
    w = np.asarray(hi) - np.asarray(lo)
    x = np.mod(m - lo, 12.0)
    return np.where(x <= w, 0.0, np.minimum(x - w, 12.0 - x))


# ---------------------------------------------------------------- 完整检索


@dataclass
class _Concat:
    rel: np.ndarray
    midi: np.ndarray
    energy: np.ndarray
    measured: np.ndarray
    owner: np.ndarray  # 每帧属于第几个声音
    offsets: list[int]  # 每个声音在拼接数组里的起点
    P_rel: np.ndarray
    P_unmeas: np.ndarray
    P_energy: np.ndarray


def _concat(sounds: Sequence[Sound]) -> _Concat:
    offsets, pos = [], 0
    for s in sounds:
        offsets.append(pos)
        pos += len(s)
    f0 = np.concatenate([np.asarray(s.f0, dtype=np.float64) for s in sounds]) if sounds else np.zeros(0)
    conf = np.concatenate([np.asarray(s.conf, dtype=np.float64) for s in sounds]) if sounds else np.zeros(0)
    en = np.concatenate([np.asarray(s.energy, dtype=np.float64) for s in sounds]) if sounds else np.zeros(0)
    measured = np.isfinite(f0) & np.isfinite(conf) & np.isfinite(en)
    rel = reliable_mask(np.nan_to_num(f0, nan=0.0), np.nan_to_num(conf, nan=0.0), np.nan_to_num(en, nan=0.0)) & measured
    midi = to_midi(f0, rel)
    owner = np.repeat(np.arange(len(sounds)), [len(s) for s in sounds]) if sounds else np.zeros(0, dtype=np.int64)
    return _Concat(
        rel, midi, en, measured, owner, offsets, _cum(rel), _cum(~measured), _cum(np.where(measured, en, 0.0)),
    )


def _span_table(sounds: Sequence[Sound], cc: _Concat, head: float | None, tail: float | None) -> tuple[np.ndarray, np.ndarray, int]:
    """全部区间在拼接坐标里的 [起, 止)（已裁到声音范围）；有句首/句尾条件时没有标注的声音不参与（计数）。"""
    a_list: list[int] = []
    b_list: list[int] = []
    unknown = 0
    for i, s in enumerate(sounds):
        if (head is not None or tail is not None) and not s.lines:
            unknown += 1
            continue
        off = cc.offsets[i] - s.first
        for a, b in s.spans:
            a0, b0 = max(a, s.first), min(b, s.first + len(s))
            if b0 > a0:
                a_list.append(off + a0)
                b_list.append(off + b0)
    return np.array(a_list, dtype=np.int64), np.array(b_list, dtype=np.int64), unknown


def _allowed(sounds: Sequence[Sound], cc: _Concat, spans: tuple[np.ndarray, np.ndarray], T: int, head: float | None, tail: float | None) -> np.ndarray:
    """拼接坐标里允许的起点（升序）：窗口 [s, s+T) 完整落在某个区间里；有句首/句尾条件时还要靠近台词边界。"""
    n = len(cc.rel)
    a, b = spans
    keep = b - T >= a
    diff = np.zeros(n + 1, dtype=np.int64)
    np.add.at(diff, a[keep], 1)
    np.add.at(diff, b[keep] - T + 1, -1)
    mask = np.cumsum(diff[:-1]) > 0
    if head is not None or tail is not None:
        for i, s in enumerate(sounds):
            if not s.lines:
                continue
            lo, hi = cc.offsets[i], cc.offsets[i] + len(s)
            off = cc.offsets[i] - s.first
            for tol, attr in ((head, 0), (tail, 1)):
                if tol is None:
                    continue
                m = np.zeros(hi - lo + 1, dtype=np.int64)
                for ln in s.lines:
                    t = ln[attr]
                    # 起点帧 k：句首 |k × 10 ms − 台词起点| ≤ 容差；句尾 |(k + T) × 10 ms − 台词终点| ≤ 容差
                    k0 = math.ceil((t - tol) / FRAME - 1e-9) - (T if attr else 0)
                    k1 = math.floor((t + tol) / FRAME + 1e-9) - (T if attr else 0)
                    x, y = max(k0 + off, lo), min(k1 + off, hi - 1)
                    if y >= x:
                        m[x - lo] += 1
                        m[y - lo + 1] -= 1
                mask[lo:hi] &= np.cumsum(m[:-1]) > 0
    return np.flatnonzero(mask)


class _Ctx:
    """一次检索的公共量：拼接数组、按音带缓存的前缀和。"""

    def __init__(self, cc: _Concat, tol_cents: float) -> None:
        self.cc = cc
        self.tol = tol_cents
        self._prefix: dict[tuple[float, float, int | None], tuple[np.ndarray, np.ndarray]] = {}
        self._gap: dict[int, np.ndarray] = {}

    def prefix(self, lo: float, hi: float, shift: int | None) -> tuple[np.ndarray, np.ndarray]:
        """普通块的（带内可靠帧, 距离和）前缀；``shift=None`` = 忽略八度的折叠下界（距离和不用）。"""
        key = (lo, hi, shift)
        hit = self._prefix.get(key)
        if hit is None:
            m = self.cc.midi
            with np.errstate(invalid="ignore"):
                if shift is None:
                    d = _dist(m, lo, hi, fold=True)
                else:
                    d = _dist(m, lo + 12 * shift, hi + 12 * shift, fold=False)
                inb = self.cc.rel & (d * 100.0 <= self.tol + 1e-6)
            dsum = np.where(self.cc.rel, d * 100.0, 0.0)
            hit = (_cum(inb), _cum(dsum))
            self._prefix[key] = hit
        return hit

    def gap_prefix(self, G: int) -> np.ndarray:
        hit = self._gap.get(G)
        if hit is None:
            P_un = _cum(~self.cc.rel)
            n = len(self.cc.rel)
            c = np.zeros(n, dtype=bool)
            if n >= G + 1:
                c[: n - G] = (P_un[G + 1 :] - P_un[: n - G]) == G + 1
            hit = _cum(c)
            self._gap[G] = hit
        return hit


def _glide_stats(cc: _Concat, starts: np.ndarray, o: int, d: int, blk: QBlock, shift: int | None, tol: float) -> tuple[np.ndarray, np.ndarray]:
    """滑音块：逐帧音带，逐个偏移累计（带内可靠帧, 距离和）。``tol``：音分。"""
    lo, hi = blk.band(d)
    inb = np.zeros(len(starts), dtype=np.int64)
    dsum = np.zeros(len(starts))
    for j in range(d):
        f = starts + o + j
        m = cc.midi[f]
        r = cc.rel[f]
        with np.errstate(invalid="ignore"):
            if shift is None:
                dist = _dist(m, lo[j], hi[j], fold=True)
            else:
                dist = _dist(m, lo[j] + 12 * shift, hi[j] + 12 * shift, fold=False)
            inb += r & (dist * 100.0 <= tol + 1e-6)
        dsum += np.where(r, dist * 100.0, 0.0)
    return inb, dsum


def _stability_ok(cc: _Concat, a: np.ndarray, d: int, limit: float) -> np.ndarray:
    """每块可靠帧 MIDI 的 P90 − P10（音分）≤ 上限；窗口逐批取出。"""
    out = np.zeros(len(a), dtype=bool)
    view = np.lib.stride_tricks.sliding_window_view(cc.midi, d)
    step = max(1, CHUNK // max(1, d))
    for i in range(0, len(a), step):
        w = view[a[i : i + step]]
        with warnings.catch_warnings(), np.errstate(invalid="ignore"):
            warnings.simplefilter("ignore", RuntimeWarning)  # 全 NaN 的行（没有可靠帧）给 NaN
            spread = (np.nanpercentile(w, 90, axis=1) - np.nanpercentile(w, 10, axis=1)) * 100.0
        out[i : i + step] = np.isfinite(spread) & (spread <= limit + 1e-9)
    return out


def _octave_range(cc: _Concat, q: Query, tol_semi: float) -> list[int]:
    m = cc.midi[cc.rel]
    if not len(m):
        return []
    lo = min(b.low_bound for b in q.blocks)
    hi = max(b.high_bound for b in q.blocks)
    a = int(math.floor((float(m.min()) - hi - tol_semi) / 12.0)) - 1
    b = int(math.ceil((float(m.max()) - lo + tol_semi) / 12.0)) + 1
    return list(range(a, b + 1))


def _evaluate(
    ctx: _Ctx, q: Query, lengths: tuple[int, ...], starts: np.ndarray, shift: int | None, prm: dict[str, object]
) -> tuple[np.ndarray, np.ndarray, list[tuple[np.ndarray, np.ndarray, np.ndarray]]]:
    """对给定起点逐块判定：返回（合格掩码, 窗口分, 每块（帧数, 带内, 平均距离））。``shift=None`` = 折叠预筛（不算分）。"""
    cc = ctx.cc
    tol = ctx.tol
    cov = float(prm["coverage"])  # type: ignore[arg-type]
    ok = np.ones(len(starts), dtype=bool)
    score = np.zeros(len(starts))
    per: list[tuple[np.ndarray, np.ndarray, np.ndarray]] = []
    o = 0
    order = sorted(range(len(q.blocks)), key=lambda i: q.blocks[i].glide)  # 普通块先判（便宜），滑音块只算剩下的
    offs = np.cumsum([0] + list(lengths))
    results: dict[int, tuple[np.ndarray, np.ndarray, np.ndarray]] = {}
    for bi in order:
        blk, d, o = q.blocks[bi], lengths[bi], int(offs[bi])
        idx = np.flatnonzero(ok)
        s = starts[idx]
        a = s + o
        b = a + d
        reln = cc.P_rel[b] - cc.P_rel[a]
        if blk.glide:
            inb, dsum = _glide_stats(cc, s, o, d, blk, shift, tol)
        else:
            P_inb, P_d = ctx.prefix(blk.lo, blk.hi, shift)
            inb = P_inb[b] - P_inb[a]
            dsum = P_d[b] - P_d[a]
        good = (reln >= 1) & (inb >= cov * d - 1e-9)
        if prm["energyMin"] is not None or prm["energyMax"] is not None:
            whole = (cc.P_unmeas[b] - cc.P_unmeas[a]) == 0
            mean = (cc.P_energy[b] - cc.P_energy[a]) / d
            good &= whole
            if prm["energyMin"] is not None:
                good &= mean >= float(prm["energyMin"]) - 1e-15  # type: ignore[arg-type]
            if prm["energyMax"] is not None:
                good &= mean <= float(prm["energyMax"]) + 1e-15  # type: ignore[arg-type]
        ok[idx] = good
        full_inb = np.zeros(len(starts), dtype=np.int64)
        full_d = np.zeros(len(starts))
        full_inb[idx] = inb
        with np.errstate(invalid="ignore", divide="ignore"):
            full_d[idx] = np.where(reln >= 1, dsum / np.maximum(reln, 1), np.nan)
        results[bi] = (np.full(len(starts), d), full_inb, full_d)
    if prm["stability"] is not None and shift is not None:
        for bi, blk in enumerate(q.blocks):
            idx = np.flatnonzero(ok)
            if not len(idx):
                break
            ok[idx] = _stability_ok(cc, starts[idx] + int(offs[bi]), lengths[bi], float(prm["stability"]))  # type: ignore[arg-type]
    for bi in range(len(q.blocks)):
        per.append(results[bi])
        score += np.nan_to_num(results[bi][2])
    score /= len(q.blocks)
    return ok, score, per


def search_exact(
    sounds: Sequence[Sound], q: Query, params: dict[str, object], cancel: Callable[[], bool] | None = None
) -> Outcome:
    """完整检索（所有者 2026-10-08）：每个允许的起点、每个变体（时长弹性）、每个八度平移（忽略八度）都严格判定。"""
    prm = params
    cc = _concat(sounds)
    tol = float(prm["tolerance"]) / 100.0  # type: ignore[arg-type]
    G = int(math.floor(float(prm["maxGap"]) / FRAME + 0.5 + 1e-9))  # type: ignore[arg-type]
    ctx = _Ctx(cc, float(prm["tolerance"]))  # type: ignore[arg-type]
    D = q.frames
    head = prm.get("headTolerance")
    tail = prm.get("tailTolerance")
    shifts: list[int] = _octave_range(cc, q, tol) if prm["ignoreOctave"] else [0]
    found_s: list[np.ndarray] = []
    found_T: list[np.ndarray] = []
    found_N: list[np.ndarray] = []
    found_score: list[np.ndarray] = []
    var = variants(q, prm["elastic"])  # type: ignore[arg-type]
    by_total = dict(var)
    windows = 0
    sa, sb, unknown = _span_table(sounds, cc, head, tail)  # type: ignore[arg-type]
    for T, lengths in var:
        if cancel is not None and cancel():
            return Outcome([], windows, unknown, cancelled=True)
        starts = _allowed(sounds, cc, (sa, sb), T, head, tail)  # type: ignore[arg-type]
        if not len(starts):
            continue
        windows += len(starts)
        # 便宜的必要条件先筛：缺口；每块可靠帧数 ≥ max(1, 覆盖 × 帧数)
        if T > G:
            run = ctx.gap_prefix(G)
            starts = starts[(run[starts + T - G] - run[starts]) == 0]
        cov = float(prm["coverage"])  # type: ignore[arg-type]
        o = 0
        for d in lengths:
            if not len(starts):
                break
            reln = cc.P_rel[starts + o + d] - cc.P_rel[starts + o]
            starts = starts[(reln >= 1) & (reln >= cov * d - 1e-9)]
            o += d
        if not len(starts):
            continue
        if prm["ignoreOctave"]:
            pre, _, _ = _evaluate(ctx, q, lengths, starts, None, prm)
            starts = starts[pre]
            if not len(starts):
                continue
        for N in shifts:
            if cancel is not None and cancel():
                return Outcome([], windows, unknown, cancelled=True)
            ok, score, _per = _evaluate(ctx, q, lengths, starts, N, prm)
            if ok.any():
                found_s.append(starts[ok])
                found_T.append(np.full(int(ok.sum()), T))
                found_N.append(np.full(int(ok.sum()), N))
                found_score.append(score[ok])
    if not found_s:
        return Outcome([], windows, unknown)
    S = np.concatenate(found_s)
    TT = np.concatenate(found_T)
    NN = np.concatenate(found_N)
    SC = np.round(np.concatenate(found_score) / SCORE_QUANTUM) * SCORE_QUANTUM
    # 每个起点取最好的（分数, |ln r|, |N|, N, T），再按相邻起点成组取最好的
    lr = np.abs(np.log(TT / D))
    order = np.lexsort((TT, NN, np.abs(NN), lr, SC, S))  # 主键 S
    S, TT, NN, SC, lr = S[order], TT[order], NN[order], SC[order], lr[order]
    first = np.ones(len(S), dtype=bool)
    first[1:] = S[1:] != S[:-1]
    S, TT, NN, SC, lr = S[first], TT[first], NN[first], SC[first], lr[first]
    owner = cc.owner[S]
    new_group = np.ones(len(S), dtype=bool)
    new_group[1:] = (S[1:] != S[:-1] + 1) | (owner[1:] != owner[:-1])
    gid = np.cumsum(new_group) - 1
    order = np.lexsort((TT, S, NN, np.abs(NN), lr, SC, gid))  # 主键 gid
    pick = order[np.r_[True, gid[order][1:] != gid[order][:-1]]]
    hits: list[Hit] = []
    for k in pick:
        i = int(owner[k])
        start = int(S[k]) - cc.offsets[i] + sounds[i].first
        T = int(TT[k])
        exact = window_eval(sounds[i], start, q, by_total[T], int(NN[k]), prm)
        assert exact is not None, "batch and pointwise evaluation disagree"
        hits.append(Hit(i, start, T, int(NN[k]), exact[0], exact[1]))
    hits.sort(key=lambda h: (round(h.score / SCORE_QUANTUM), sounds[h.sound].key, h.start, h.frames))
    return Outcome(hits, windows, unknown)


def window_eval(
    s: Sound, start: int, q: Query, lengths: Sequence[int], shift: int, prm: dict[str, object]
) -> tuple[float, tuple[tuple[int, int, float], ...]] | None:
    """逐点判定一个窗口（资产帧 ``start``）：合格返回（窗口分, 每块（帧数, 带内, 平均距离））；不合格 None。批量判定的对照。"""
    T = sum(lengths)
    i0 = start - s.first
    if i0 < 0 or i0 + T > len(s):
        return None
    f0 = np.asarray(s.f0[i0 : i0 + T], dtype=np.float64)
    conf = np.asarray(s.conf[i0 : i0 + T], dtype=np.float64)
    en = np.asarray(s.energy[i0 : i0 + T], dtype=np.float64)
    measured = np.isfinite(f0) & np.isfinite(conf) & np.isfinite(en)
    rel = reliable_mask(np.nan_to_num(f0), np.nan_to_num(conf), np.nan_to_num(en)) & measured
    G = int(math.floor(float(prm["maxGap"]) / FRAME + 0.5 + 1e-9))  # type: ignore[arg-type]
    run = best = 0
    for r in rel:
        run = 0 if r else run + 1
        best = max(best, run)
    if best > G:
        return None
    m = to_midi(f0, rel)
    tol = float(prm["tolerance"])  # type: ignore[arg-type]
    cov = float(prm["coverage"])  # type: ignore[arg-type]
    o = 0
    per = []
    for blk, d in zip(q.blocks, lengths):
        lo, hi = blk.band(d)
        mm, rr = m[o : o + d], rel[o : o + d]
        with np.errstate(invalid="ignore"):
            dist = _dist(mm, lo + 12 * shift, hi + 12 * shift, fold=False) * 100.0
        inb = int((rr & (dist <= tol + 1e-6)).sum())
        reln = int(rr.sum())
        if reln < 1 or inb < cov * d - 1e-9:
            return None
        if prm["stability"] is not None:
            v = mm[rr]
            if float(np.percentile(v, 90) - np.percentile(v, 10)) * 100.0 > float(prm["stability"]) + 1e-9:  # type: ignore[arg-type]
                return None
        if prm["energyMin"] is not None or prm["energyMax"] is not None:
            if not measured[o : o + d].all():
                return None
            mean = float(en[o : o + d].mean())
            if prm["energyMin"] is not None and mean < float(prm["energyMin"]) - 1e-15:  # type: ignore[arg-type]
                return None
            if prm["energyMax"] is not None and mean > float(prm["energyMax"]) + 1e-15:  # type: ignore[arg-type]
                return None
        per.append((d, inb, float(dist[rr].mean())))
        o += d
    return float(np.mean([p[2] for p in per])), tuple(per)


# ---------------------------------------------------------------- 基线近似流程（对照实现；界面不用）

COARSE = 5  # 50 ms 摘要格 = 5 帧
COARSE_SLACK = 0.15
COARSE_MARGIN = 1.0  # 半音（100 音分）
CANDIDATE_BUDGET = 2000
GROUP_BUDGET = 2000
REFINE_RADIUS = 5  # ±50 ms
RESULT_MAX = 100


def summary(s: Sound) -> tuple[int, np.ndarray, np.ndarray, np.ndarray]:
    """50 ms 摘要（资产网格对齐：格 c = 资产帧 [5c, 5c+5)）：（首格号, 可靠帧 MIDI 均值, 可靠覆盖率, 平均能量）。只含完整落在声音里的格。"""
    c0 = -(-s.first // COARSE)
    c1 = (s.first + len(s)) // COARSE
    n = max(0, c1 - c0)
    f0 = np.asarray(s.f0, dtype=np.float64)
    conf = np.asarray(s.conf, dtype=np.float64)
    en = np.asarray(s.energy, dtype=np.float64)
    measured = np.isfinite(f0) & np.isfinite(conf) & np.isfinite(en)
    rel = reliable_mask(np.nan_to_num(f0), np.nan_to_num(conf), np.nan_to_num(en)) & measured
    m = to_midi(f0, rel)
    a = c0 * COARSE - s.first
    sl = slice(a, a + n * COARSE)
    rr = rel[sl].reshape(n, COARSE)
    mm = np.where(rr, m[sl].reshape(n, COARSE), 0.0)
    cnt = rr.sum(axis=1)
    with np.errstate(invalid="ignore", divide="ignore"):
        mean = np.where(cnt > 0, mm.sum(axis=1) / np.maximum(cnt, 1), np.nan)
    ee = np.nan_to_num(en[sl]).reshape(n, COARSE).mean(axis=1)
    return c0, mean, cnt / COARSE, ee


def search_approx(sounds: Sequence[Sound], q: Query, params: dict[str, object]) -> Outcome:
    """规格 10 §10.2.4 的基线近似流程（普通块、不开扩展）。"""
    prm = params
    if prm["ignoreOctave"] or prm["elastic"] is not None or any(b.glide for b in q.blocks):
        raise CoreError("pitch-param-invalid", field="approx", min=None, max=None)
    D = q.frames
    tol = float(prm["tolerance"]) / 100.0  # type: ignore[arg-type]
    cov = float(prm["coverage"])  # type: ignore[arg-type]
    lengths = tuple(b.frames for b in q.blocks)
    groups: list[tuple[float, int, int, list[tuple[float, int]]]] = []  # (最好粗分, 声音, 首起点, [(粗分, 起点)])
    for si, s in enumerate(sounds):
        c0, mean, cover, _en = summary(s)
        allowed: set[int] = set()
        for a, b in s.spans:
            for k in range(a, b - D + 1):
                allowed.add(k)
        coarse: list[tuple[float, int]] = []
        for k in sorted(x for x in allowed if x % COARSE == 0):
            total = 0.0
            ok = True
            o = 0
            for blk, d in zip(q.blocks, lengths):
                ca = (k + o) // COARSE - c0
                cb = -(-(k + o + d) // COARSE) - c0
                if ca < 0 or cb > len(mean):
                    ok = False
                    break
                mm, cv = mean[ca:cb], cover[ca:cb]
                with np.errstate(invalid="ignore"):
                    inband = (mm >= blk.lo - tol - COARSE_MARGIN) & (mm <= blk.hi + tol + COARSE_MARGIN)
                c = float(cv[inband].sum()) / (cb - ca)
                if c < max(0.0, cov - COARSE_SLACK) - 1e-12:
                    ok = False
                    break
                total += 1.0 - c
                o += d
            if ok:
                coarse.append((total, k))
        coarse.sort(key=lambda x: x[1])
        cur: list[tuple[float, int]] = []
        for sc, k in coarse:
            if cur and k - cur[-1][1] > 2 * COARSE:
                groups.append((min(x[0] for x in cur), si, cur[0][1], sorted(cur)))
                cur = []
            cur.append((sc, k))
        if cur:
            groups.append((min(x[0] for x in cur), si, cur[0][1], sorted(cur)))
    groups.sort(key=lambda g: (g[0], sounds[g[1]].key, g[2]))
    groups = groups[:GROUP_BUDGET]
    cands: list[tuple[int, int]] = []  # (组号, 起点)
    depth = 0
    while len(cands) < CANDIDATE_BUDGET:
        added = False
        for gi, g in enumerate(groups):
            if depth < len(g[3]):
                cands.append((gi, g[3][depth][1]))
                added = True
                if len(cands) >= CANDIDATE_BUDGET:
                    break
        if not added:
            break
        depth += 1
    best: dict[int, tuple[float, int]] = {}
    for gi, k in cands:
        si = groups[gi][1]
        s = sounds[si]
        allowed_k = [x for x in range(k - REFINE_RADIUS, k + REFINE_RADIUS + 1) if any(a <= x <= b - D for a, b in s.spans)]
        for x in allowed_k:
            r = window_eval(s, x, q, lengths, 0, prm)
            if r is None:
                continue
            cur_b = best.get(gi)
            if cur_b is None or (r[0], x) < cur_b:
                best[gi] = (r[0], x)
    seen: set[tuple[int, int]] = set()
    hits = []
    for gi, (sc, x) in best.items():
        si = groups[gi][1]
        if (si, x) in seen:
            continue
        seen.add((si, x))
        hits.append(Hit(si, x, D, 0, sc))
    hits.sort(key=lambda h: (h.score, sounds[h.sound].key, h.start))
    truncated = len(hits) > RESULT_MAX
    out = Outcome(hits[:RESULT_MAX])
    out.stats["truncated"] = truncated
    return out
