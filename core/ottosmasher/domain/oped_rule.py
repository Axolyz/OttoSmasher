"""OP/ED 的字幕规则（规格 05 §5.6.1、16 R6.3；fixtures 的 S10）。

1. 每条字幕去掉样式标记（读取时已去）和**所有**空白，把波浪号 U+301C 统一成 U+FF5E；
2. 整条恰好等于某个开始标记 → 开始；恰好等于某个结束标记 → 结束（标记是设置项，可各填多个，按同样规则规范化）；
3. 开始行的起点到结束行的终点是一个音乐区间；
4. 错误：重复开始、结束缺开始、开始缺结束、超出原片或时间倒置、超过两个区间（需要人工指定用途）——有错误就不自动登记，
   但仍列出已配对的区间（按前后半片给 OP/ED 建议）供逐对确认；
5. 恰好两个区间：前 OP 后 ED；其余按中点在前半片为 OP，否则 ED。

纯函数：输入字幕条与原片时长，输出配对与错误；登记、与已有区间的重叠判断在 ``core.oped``。
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from typing import Literal

from .subtitles import Cue

_WS = re.compile(r"\s+")
_WAVE_DASH = "\u301c"
_FULLWIDTH_TILDE = "\uff5e"
EPS = 1e-6


def normalize(text: str) -> str:
    return _WS.sub("", text).replace(_WAVE_DASH, _FULLWIDTH_TILDE)


@dataclass(frozen=True)
class Pair:
    start: float
    end: float
    suggest: Literal["OP", "ED"]
    start_ref: str
    end_ref: str


@dataclass
class RuleResult:
    pairs: list[Pair] = field(default_factory=list)
    errors: list[dict[str, object]] = field(default_factory=list)
    """``code``：duplicate-start / end-without-start / start-without-end / out-of-range / too-many；``refs``：字幕条编号"""


def identify(cues: Sequence[Cue], duration: float, starts: Iterable[str], ends: Iterable[str]) -> RuleResult:
    start_set = {normalize(s) for s in starts if normalize(s)}
    end_set = {normalize(s) for s in ends if normalize(s)}
    res = RuleResult()
    raw: list[tuple[Cue, Cue]] = []
    opened: Cue | None = None
    for cue in sorted(cues, key=lambda c: (c.start, c.order)):
        t = normalize(cue.text)
        if t in start_set:
            if opened is not None:
                res.errors.append({"code": "duplicate-start", "refs": [_ref(opened), _ref(cue)]})
            opened = cue  # 以后一个开始为准继续配对
        elif t in end_set:
            if opened is None:
                res.errors.append({"code": "end-without-start", "refs": [_ref(cue)]})
            else:
                raw.append((opened, cue))
                opened = None
    if opened is not None:
        res.errors.append({"code": "start-without-end", "refs": [_ref(opened)]})
    good: list[tuple[Cue, Cue]] = []
    for a, b in raw:
        if a.start < 0 or b.end > duration + EPS or not b.end > a.start:
            res.errors.append({"code": "out-of-range", "refs": [_ref(a), _ref(b)]})
        else:
            good.append((a, b))
    if len(good) > 2:
        res.errors.append({"code": "too-many", "count": len(good), "refs": [_ref(a) for a, _ in good]})
    for i, (a, b) in enumerate(good):
        if len(good) == 2:
            kind: Literal["OP", "ED"] = "OP" if i == 0 else "ED"
        else:
            kind = "OP" if (a.start + b.end) / 2 < duration / 2 else "ED"
        res.pairs.append(Pair(a.start, b.end, kind, _ref(a), _ref(b)))
    return res


def _ref(c: Cue) -> str:
    return c.ref or str(c.order)
