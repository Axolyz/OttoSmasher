"""用户可编辑的正则规则（原则 P10；规格 06 §6.2.2）：字幕规则与原片推断规则共用。

- 方言：Python ``regex`` 库（支持递归 ``(?&name)`` 与单次匹配超时）；
- 保存时校验：能编译、包含要求的命名组、长度 ≤ 4096 字符、对试算样例单行匹配不超时（50 ms）；
- 运行时超时不静默吞掉：调用方拿到 ``RuleTimeout`` 后决定跳过并告诉用户（P6）。
默认值放在 ``default_rules.json``（含中日文括号，不写进代码）。
"""

from __future__ import annotations

import json
from collections.abc import Iterable
from functools import cache
from pathlib import Path
from typing import Any

import regex

from ottosmasher.core.errors import CoreError

MAX_PATTERN_CHARS = 4096
MATCH_TIMEOUT = 0.05
MAX_RULES = 32

# 校验用的压力样例：典型文件名长度上限附近的病态输入（灾难性回溯在这里会超时）
_STRESS = ["a" * 254 + "!", "[" * 120 + "1" * 120 + "!", " - " * 80 + "!"]


class RuleTimeout(Exception):
    def __init__(self, index: int) -> None:
        super().__init__(index)
        self.index = index


@cache
def defaults() -> dict[str, Any]:
    return json.loads((Path(__file__).with_name("default_rules.json")).read_text(encoding="utf-8"))


def compile_rule(
    pattern: str,
    *,
    required: Iterable[str] = (),
    any_of: Iterable[str] = (),
    samples: Iterable[str] = (),
    index: int | None = None,
    stress: bool = True,
    stress_samples: Iterable[str] | None = None,
    code: str = "rule-invalid",
    where: dict[str, Any] | None = None,
) -> regex.Pattern[str]:
    """编译并校验一条规则（``stress=False`` 用于运行时：已在保存时测过超时）；不合格抛 ``code``（默认 ``rule-invalid``；
    reason：not-text / too-long / syntax / missing-group / timeout）。``stress_samples`` 替换默认（文件名）压力样例；
    ``where`` 是报错时附带的定位参数（默认是规则序号）。"""
    where = where if where is not None else ({} if index is None else {"rule": index + 1})
    if not isinstance(pattern, str) or not pattern:
        raise CoreError(code, reason="not-text", **where)
    if len(pattern) > MAX_PATTERN_CHARS:
        raise CoreError(code, reason="too-long", max=MAX_PATTERN_CHARS, **where)
    try:
        pat = regex.compile(pattern)
    except regex.error as e:
        raise CoreError(code, reason="syntax", detail=str(e), **where) from None
    groups = set(pat.groupindex)
    for g in required:
        if g not in groups:
            raise CoreError(code, reason="missing-group", group=g, **where)
    any_of = list(any_of)
    if any_of and not groups.intersection(any_of):
        raise CoreError(code, reason="missing-group", group=" / ".join(any_of), **where)
    pressure = list(_STRESS if stress_samples is None else stress_samples) if stress else []
    for s in [*samples, *pressure]:
        try:
            pat.search(s, timeout=MATCH_TIMEOUT)
        except TimeoutError:
            raise CoreError(code, reason="timeout", sample=s[:40], **where) from None
    return pat


def search(pat: regex.Pattern[str], text: str, index: int) -> regex.Match[str] | None:
    try:
        return pat.search(text, timeout=MATCH_TIMEOUT)
    except TimeoutError:
        raise RuleTimeout(index) from None


def validate_list(
    value: Any, *, any_of: Iterable[str] = (), required: Iterable[str] = (), samples: Iterable[str] = ()
) -> list[str]:
    """设置项“有序规则列表”的校验：0–32 条，每条都合格。"""
    if not isinstance(value, list):
        raise CoreError("setting-invalid", reason="not-a-list")
    if len(value) > MAX_RULES:
        raise CoreError("setting-invalid", reason="too-many", max=MAX_RULES)
    samples = list(samples)
    for i, p in enumerate(value):
        compile_rule(p, required=required, any_of=any_of, samples=samples, index=i)
    return list(value)
