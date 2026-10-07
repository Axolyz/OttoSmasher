"""命名：登记原片时从文件名推断作品与集数（规格 05 §5.1、16 R1.2）。

规则是用户可编辑的有序正则列表（设置 ``source.infer_rules``，原则 P10；所有者 2026-10-07 选定）：
对文件名（不含目录与扩展名，Unicode NFC）从上到下 ``search``，第一条匹配的规则生效，
命名组 ``work`` / ``episode`` 给出作品与集数（去首尾空白，空串视为未知）。
都不匹配时作品、集数都是未知（None），不拿文件名充当（所有者 2026-10-07 同意）。
只在首次登记时推断，之后以用户修改为准。默认规则见 ``default_rules.json``。
"""

from __future__ import annotations

import unicodedata
from collections.abc import Sequence
from dataclasses import dataclass, field
from pathlib import PurePath

from . import rules as rules_mod

GROUPS = ("work", "episode")


@dataclass(frozen=True)
class WorkEpisode:
    work: str | None
    episode: str | None
    rule: int | None = None
    """生效规则的序号（从 0 起）；都不匹配为 None。"""
    timed_out: tuple[int, ...] = field(default=())
    """执行超时被跳过的规则序号（要告诉用户，不静默）。"""


def default_rules() -> list[str]:
    return list(rules_mod.defaults()["source.infer_rules"])


def validate_rules(value: object) -> list[str]:
    """设置 ``source.infer_rules`` 的校验。"""
    return rules_mod.validate_list(value, any_of=GROUPS, samples=rules_mod.defaults()["source.infer_samples"])


def stem(filename: str) -> str:
    return unicodedata.normalize("NFC", PurePath(filename).stem)


def infer_work_episode(filename: str, rules: Sequence[str] | None = None) -> WorkEpisode:
    text = stem(filename)
    timed_out: list[int] = []
    for i, pattern in enumerate(default_rules() if rules is None else rules):
        pat = rules_mod.compile_rule(pattern, any_of=GROUPS, index=i, stress=False)
        try:
            m = rules_mod.search(pat, text, i)
        except rules_mod.RuleTimeout:
            timed_out.append(i)
            continue
        if m is None:
            continue
        found = {g: (m.groupdict().get(g) or "").strip() or None for g in GROUPS}
        return WorkEpisode(found["work"], found["episode"], i, tuple(timed_out))
    return WorkEpisode(None, None, None, tuple(timed_out))
