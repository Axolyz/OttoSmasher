"""字幕规则与分类（规格 06 §6.2、16 R4.4–R4.7、R5.1）。原则 P10：程序里不写针对任何字幕写法的特判，全部是用户可编辑的规则。

五条规则（设置项，默认值见 ``default_rules.json``）：

- 音效整行（``subtitle.sfx_rule``，fullmatch）：整行完整匹配 → 音效；
- 注释括号（``subtitle.note_rule``，命名组 ``content``，search 全部）：行内的注释段；
- 说话人提取（``subtitle.speaker_rule``，命名组 ``name``，search 全部）：台词行里每个匹配 = 一个说话人；
- 说话人名拆分（``subtitle.speaker_split``，可空）：把一个匹配拆成多个名字；
- 说话人名清理（``subtitle.speaker_clean``，可空）：从名字里删掉匹配部分。

分类（默认规则下的例子见规格 06 §6.2.1 表格）：

- 音效：名称 = 各注释段内容（去首尾空白）用 `` / `` 连接；没有说话人、没有对齐文本；
- 台词：对齐文本 = 原文去掉所有注释段后逐行去首尾空白、去空行，保留换行；名称 = 对齐文本的换行换成空格；
  说话人 = 说话人规则的全部匹配，依次拆分、清理、去空白、去空、去重（保持出现顺序）。
- 规则执行超时不静默：抛 ``subtitle-rule-timeout``（哪条规则），调用方整批失败并告诉用户（P6）。
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, Literal

import regex

from ottosmasher.core.errors import CoreError

from . import rules as rules_mod

KEYS = ("subtitle.sfx_rule", "subtitle.note_rule", "subtitle.speaker_rule", "subtitle.speaker_split", "subtitle.speaker_clean")
REQUIRED_GROUP = {"subtitle.note_rule": "content", "subtitle.speaker_rule": "name"}
OPTIONAL = {"subtitle.speaker_split", "subtitle.speaker_clean"}
SFX_JOINER = " / "


def default_value(key: str) -> str:
    return str(rules_mod.defaults()[key])


def _samples() -> list[str]:
    return list(rules_mod.defaults()["subtitle.rule_samples"])


def _stress() -> list[str]:
    return [unit * int(times) + tail for unit, times, tail in rules_mod.defaults()["subtitle.rule_stress"]]


def compile_one(key: str, pattern: str, *, check: bool) -> regex.Pattern[str] | None:
    """编译一条字幕规则；``check`` 时做保存时的全部校验（命名组、长度、样例与压力样例不超时）。可选规则空串 = 关闭。"""
    if key in OPTIONAL and pattern == "":
        return None
    return rules_mod.compile_rule(
        pattern,
        required=[REQUIRED_GROUP[key]] if key in REQUIRED_GROUP else [],
        samples=_samples() if check else (),
        stress=check,
        stress_samples=_stress(),
        code="subtitle-rule-invalid",
        where={"setting": key},
    )


@dataclass(frozen=True)
class SubtitleRules:
    sfx: regex.Pattern[str]
    note: regex.Pattern[str]
    speaker: regex.Pattern[str]
    split: regex.Pattern[str] | None
    clean: regex.Pattern[str] | None
    patterns: Mapping[str, str]
    """规则原文（导入时随标记一起记下，便于说明这条标记是按什么规则分的）"""

    @classmethod
    def build(cls, values: Mapping[str, Any], *, check: bool = False) -> SubtitleRules:
        pats = {k: str(values[k]) for k in KEYS}
        c = {k: compile_one(k, pats[k], check=check) for k in KEYS}
        rs = cls(
            sfx=c["subtitle.sfx_rule"],  # type: ignore[arg-type]
            note=c["subtitle.note_rule"],  # type: ignore[arg-type]
            speaker=c["subtitle.speaker_rule"],  # type: ignore[arg-type]
            split=c["subtitle.speaker_split"],
            clean=c["subtitle.speaker_clean"],
            patterns=pats,
        )
        if check:
            # 整套规则按真实用法（fullmatch / 全部匹配 / 拆分 / 清理）在样例与压力样例上跑一遍
            for s in [*_samples(), *_stress()]:
                classify(s, rs)
        return rs


@dataclass(frozen=True)
class Classified:
    kind: Literal["line", "sfx"]
    name: str
    speakers: tuple[str, ...]
    align_text: str

    def wire(self) -> dict[str, Any]:
        return {"kind": self.kind, "name": self.name, "speakers": list(self.speakers), "alignText": self.align_text}


def _timeout(key: str) -> CoreError:
    return CoreError("subtitle-rule-timeout", setting=key)


def _finditer(pat: regex.Pattern[str], text: str, key: str) -> list[regex.Match[str]]:
    try:
        return list(pat.finditer(text, timeout=rules_mod.MATCH_TIMEOUT))
    except TimeoutError:
        raise _timeout(key) from None


def _lines(text: str) -> list[str]:
    return [ln.strip() for ln in text.split("\n") if ln.strip()]


def classify(text: str, rs: SubtitleRules) -> Classified:
    try:
        is_sfx = rs.sfx.fullmatch(text, timeout=rules_mod.MATCH_TIMEOUT) is not None
    except TimeoutError:
        raise _timeout("subtitle.sfx_rule") from None
    notes = _finditer(rs.note, text, "subtitle.note_rule")
    if is_sfx:
        parts = [(m.group("content") or "").strip() for m in notes]
        return Classified("sfx", SFX_JOINER.join(p for p in parts if p), (), "")
    # 去掉所有注释段（从后往前切，位置不受影响）
    body = text
    for m in reversed(notes):
        body = body[: m.start()] + body[m.end() :]
    align = "\n".join(_lines(body))
    return Classified("line", align.replace("\n", " "), tuple(_speakers(text, rs)), align)


def _speakers(text: str, rs: SubtitleRules) -> list[str]:
    out: list[str] = []
    for m in _finditer(rs.speaker, text, "subtitle.speaker_rule"):
        names = [m.group("name") or ""]
        if rs.split is not None:
            # 按分隔符的位置切开（不用 split()：规则里有捕获组时它会把分隔符本身也带出来）
            name = names[0]
            cuts = [(m.start(), m.end()) for m in _finditer(rs.split, name, "subtitle.speaker_split") if m.end() > m.start()]
            bounds = [0, *[x for c in cuts for x in c], len(name)]
            names = [name[bounds[i] : bounds[i + 1]] for i in range(0, len(bounds), 2)]
        for n in names:
            if rs.clean is not None:
                try:
                    n = rs.clean.sub("", n, timeout=rules_mod.MATCH_TIMEOUT)
                except TimeoutError:
                    raise _timeout("subtitle.speaker_clean") from None
            n = n.strip()
            if n and n not in out:
                out.append(n)
    return out


def validate_setting(key: str) -> Any:
    """设置项校验函数（单条）：可选规则允许空串。"""

    def check(v: Any) -> str:
        if not isinstance(v, str):
            raise CoreError("subtitle-rule-invalid", reason="not-text", setting=key)
        compile_one(key, v, check=True)
        return v

    return check
