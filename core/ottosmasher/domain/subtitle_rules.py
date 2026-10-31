"""字幕规则与分类（规格 06 §6.2、16 R4.4–R4.7、R5.1；所有者 2026-10-31【基线变更】：逐行读、宁可丢不写错）。原则 P10：程序里不写针对任何字幕写法的特判，全部是用户可编辑的规则。

五条规则（设置项，默认值见 ``default_rules.json``），都按**行**用：

- 音效行（``subtitle.sfx_rule``，fullmatch）：一行完整匹配 → 这一行是音效；
- 注释括号（``subtitle.note_rule``，命名组 ``content``，search 全部）：行内的注释段（读音、说明），台词里去掉；
- 说话人标注（``subtitle.speaker_rule``，命名组 ``name``）：**只在台词行的行首**匹配（可以连着几个）；台词中间的括号从不当人名；
- 说话人名拆分（``subtitle.speaker_split``，默认 ``、`` = 几个人同时说）：把一个标注拆成多个名字；
- 说话人名清理（``subtitle.speaker_clean``，可空）：从名字里删掉匹配部分。

一条字幕先按行切开（括号里的换行不算，跨行的括号算一行），逐行读：

- 音效行：这一条的音效；**但下一行是没有标注的台词时两样都不认**（可能是单独占一行的人名），记“有标注没记”；
- 台词行：行首有标注 = 这一行的说话人；没有 = 不知道，从不跟上一行；
- 整条的说话人：每个台词行都有标注 → 这些名字（拆分、清理、去空、去重，保持顺序）；有一行没有 → 不记，有标注的话记“有标注没记”（``withheld``）。

结果：台词（对齐文本 = 台词行去掉注释段后逐行去首尾空白、去空行，保留换行；名称 = 对齐文本的换行换成空格）与音效（名称 = 各音效行的注释段内容用 `` / `` 连接）可以同时有。
规则执行超时不静默：抛 ``subtitle-rule-timeout``（哪条规则），调用方整批失败并告诉用户（P6）。
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
    """``kind``：有台词 = line，只有音效 = sfx；``sfx``：这一条的音效名称（没有 = 空）；``withheld``：原文里有标注，但没法确定每一行是谁说的，所以没记。"""

    kind: Literal["line", "sfx"]
    name: str
    speakers: tuple[str, ...]
    align_text: str
    sfx: str = ""
    withheld: bool = False

    def wire(self) -> dict[str, Any]:
        return {"kind": self.kind, "name": self.name, "speakers": list(self.speakers), "alignText": self.align_text, "sfx": self.sfx, "withheld": self.withheld}


def _timeout(key: str) -> CoreError:
    return CoreError("subtitle-rule-timeout", setting=key)


def _finditer(pat: regex.Pattern[str], text: str, key: str) -> list[regex.Match[str]]:
    try:
        return list(pat.finditer(text, timeout=rules_mod.MATCH_TIMEOUT))
    except TimeoutError:
        raise _timeout(key) from None


OPEN, CLOSE = "\uff08(", "\uff09)"  # 全角、半角括号


def logical_lines(text: str) -> list[str]:
    """按换行切成行，括号里的换行不切（跨行的音效描述算一行）；去首尾空白、去空行。"""
    out, cur, depth = [], [], 0
    for ch in text:
        if ch == "\n" and depth == 0:
            out.append("".join(cur))
            cur = []
            continue
        depth += ch in OPEN
        depth = max(0, depth - (ch in CLOSE))
        cur.append(ch)
    out.append("".join(cur))
    return [x.strip() for x in out if x.strip()]


def _is_sfx(line: str, rs: SubtitleRules) -> bool:
    try:
        return rs.sfx.fullmatch(line, timeout=rules_mod.MATCH_TIMEOUT) is not None
    except TimeoutError:
        raise _timeout("subtitle.sfx_rule") from None


def _labels(line: str, rs: SubtitleRules) -> list[regex.Match[str]]:
    """行首连着的说话人标注（一个都没有 = 空）。"""
    out, pos = [], 0
    while True:
        try:
            m = rs.speaker.match(line, pos, timeout=rules_mod.MATCH_TIMEOUT)
        except TimeoutError:
            raise _timeout("subtitle.speaker_rule") from None
        if m is None or m.end() <= pos:
            return out
        out.append(m)
        pos = m.end()
        while pos < len(line) and line[pos].isspace():
            pos += 1


def _strip_notes(line: str, rs: SubtitleRules) -> str:
    body = line
    for m in reversed(_finditer(rs.note, line, "subtitle.note_rule")):  # 从后往前切，位置不受影响
        body = body[: m.start()] + body[m.end() :]
    return body.strip()


def classify(text: str, rs: SubtitleRules) -> Classified:
    lines = logical_lines(text)
    sfx_lines = [_is_sfx(ln, rs) for ln in lines]
    sfx_names: list[str] = []
    dialog: list[tuple[list[str] | None, str]] = []  # (这一行的名字；None = 没有标注, 去掉注释后的台词)
    withheld = False
    for i, ln in enumerate(lines):
        if sfx_lines[i]:
            nxt = i + 1
            if nxt < len(lines) and not sfx_lines[nxt] and not _labels(lines[nxt], rs):
                withheld = True  # 可能是单独占一行的人名：音效、说话人都不认
                continue
            sfx_names += [p for p in ((m.group("content") or "").strip() for m in _finditer(rs.note, ln, "subtitle.note_rule")) if p]
            continue
        labels = _labels(ln, rs)
        body = _strip_notes(ln, rs)
        if body:
            dialog.append((_names(labels, rs) if labels else None, body))
    sfx = SFX_JOINER.join(sfx_names)
    if not dialog and (sfx or not lines or all(sfx_lines)):
        return Classified("sfx", sfx, (), "", sfx, False) if lines else Classified("line", "", (), "")
    align = "\n".join(b for _, b in dialog)
    names: list[str] = []
    if dialog and all(n is not None for n, _ in dialog):
        for n, _ in dialog:
            names += [x for x in n or () if x not in names]
    elif any(n is not None for n, _ in dialog):
        withheld = True
    return Classified("line", align.replace("\n", " "), tuple(names), align, sfx, withheld)


def _names(labels: list[regex.Match[str]], rs: SubtitleRules) -> list[str]:
    out: list[str] = []
    for m in labels:
        names = [m.group("name") or ""]
        if rs.split is not None:
            # 按分隔符的位置切开（不用 split()：规则里有捕获组时它会把分隔符本身也带出来）
            name = names[0]
            cuts = [(x.start(), x.end()) for x in _finditer(rs.split, name, "subtitle.speaker_split") if x.end() > x.start()]
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
