"""命名：登记原素材时从文件名推断作品与素材标识（规格 05 §5.1、16 R1.2；所有者 2026-10-10：“原片 / 集数”改叫“原素材 / 素材标识”）。

规则是用户可编辑的有序正则列表（设置 ``source.infer_rules``，原则 P10；所有者 2026-10-07 选定）：
对文件名（不含目录与扩展名，Unicode NFC）从上到下 ``search``，第一条匹配的规则生效，
命名组 ``work`` / ``episode`` 给出作品与素材标识（去首尾空白，空串视为未知；内部名仍是 episode）。
素材标识在一个作品里区分和排序原素材（集数、编号或名称，不一定是数字）：**没有给出时用文件名（不含扩展名）**（所有者 2026-10-10）；
作品推断不出就是未知（None），不拿文件名充当（所有者 2026-10-07）。
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
        return WorkEpisode(found["work"], found["episode"] or text, i, tuple(timed_out))
    return WorkEpisode(None, text, None, tuple(timed_out))


# ---------------------------------------------------------------- 采样建议名（规格 04 §4.7）


def clock_label(t: float) -> str:
    """名称里的时间：``M:SS.mmm``，满一小时 ``H:MM:SS.mmm``（与界面的时钟格式一致）。"""
    ms = round(max(t, 0.0) * 1000)
    h, rem = divmod(ms, 3_600_000)
    m, rem = divmod(rem, 60_000)
    s, ms = divmod(rem, 1000)
    return f"{h}:{m:02d}:{s:02d}.{ms:03d}" if h else f"{m}:{s:02d}.{ms:03d}"


def suggest_sample_name(
    *,
    source_name: str,
    start: float,
    end: float,
    mapped: bool = True,
    local_marker: str = "",
    aligned: tuple[str, str] | None = None,
    overlapping_texts: list[str] | None = None,
) -> str:
    """按优先级取第一个可用的：
    1. 可靠对齐结果：“原文 — かな”（阶段 4 起才有）；
    2. 与选区正长度交叠的台词/音效标注的清洗后文字，多条用 “ / ” 连接（调用方已按原片时间求交叠、按时间排序、去空）；
    3. “原片名 起–止”（原片时间）；资产没有映射时 “原片名 · <局部词> 起–止”（资产局部时间）。
    不自动加音高后缀；名称永远可以手改。
    """
    if aligned and aligned[0].strip():
        text, kana = aligned[0].strip(), aligned[1].strip()
        return f"{text} — {kana}" if kana else text
    texts = [x.strip() for x in (overlapping_texts or []) if x and x.strip()]
    if texts:
        return " / ".join(dict.fromkeys(texts))
    span = f"{clock_label(start)}–{clock_label(end)}"
    return f"{source_name} {span}" if mapped else f"{source_name} · {local_marker}{span}"


def nature_for_roles(roles: list[str] | set[str]) -> str:
    """截取、命中保存、分离结果保存的性质预填（规格 04 §4.2.7、16 R2.6）：
    只有人声 → 语音；只有音效 → 非调谐单音；都有或都没有 → 未分类。"""
    r = set(roles)
    if r == {"vocal"}:
        return "speech"
    if r == {"sfx"}:
        return "unpitched"
    return "unclassified"
