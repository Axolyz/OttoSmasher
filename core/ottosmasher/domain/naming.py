"""命名：登记原片时从文件名推断作品与集数（规格 05 §5.1、16 R1.2）。

例子（规格原文）：
    [VCB-Studio] Yuru Yuri [01][Ma10p_1080p].mkv → ("Yuru Yuri", "01")
    [DBD-Raws][Kemono Friends][02][1080P].mkv   → ("Kemono Friends", "02")
    [Kemono Friends][01].mkv                     → ("Kemono Friends", "01")
    作品名 - 01.mkv                              → ("作品名", "01")
不能把发布组名或集数当作品名。只在首次登记时推断，之后以用户修改为准；推断不出来就是未知（None），不编造。

规则：
1. 去掉扩展名，切成“括号块”（[]、【】）和括号外的“自由文字”；圆括号留在自由文字里（常是作品名的一部分）。
2. 集数：第一个内容是纯集数的括号块（``01``、``01v2``、``12 END``；4 位的 19xx/20xx 视为年份）；否则自由文字里的
   ``- 01``、``第01話/话/集``、``S01E02``、``EP01``、``#01`` 形式。
3. 作品：集数之前的自由文字（去掉分隔符）；没有自由文字时取集数括号块紧挨着的前一个括号块；
   没有集数时取第一段自由文字，再没有就取第二个非技术括号块（第一个通常是发布组），只有一个括号块就取它。
   技术括号块（分辨率、编码、音频、片源、字幕语言、CRC）永远不当作品名。
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from pathlib import PurePath

_BRACKETS = re.compile(r"\[([^\[\]]*)\]|\u3010([^\u3010\u3011]*)\u3011")

_EP_TOKEN = re.compile(r"^\s*(?:EP?|#)?\s*(\d{1,4})(?:v\d+)?(?:\s*END)?\s*$", re.IGNORECASE)

# 自由文字里的集数（正则里用转义：u7b2c 第，u8a71 話，u8bdd 话，u96c6 集；u2013/u2014/uff0d 破折号）
_EP_IN_TEXT = [
    re.compile(r"(?:^|\s)[-\u2013\u2014\uff0d]\s*(\d{1,4})(?:v\d+)?(?:\s|$)"),
    re.compile(r"\u7b2c\s*(\d{1,4})\s*[\u8a71\u8bdd\u96c6]"),
    re.compile(r"\bS\d{1,2}\s*E(\d{1,4})\b", re.IGNORECASE),
    re.compile(r"\b(?:EP\s*|E)(\d{1,4})\b", re.IGNORECASE),
    re.compile(r"#\s*(\d{1,4})\b"),
]

_TECH = re.compile(
    r"^(?:"
    r"\d{3,4}[pi]|\d{3,4}x\d{3,4}|[248]k|uhd|fhd|hd"
    r"|ma10p|hi10p|main10|10bit|8bit|hevc|avc|x26[45]|h\.?26[45]|av1|vp9"
    r"|flac|aac|ac3|eac3|dts|opus|mp3|truehd|lpcm|pcm"
    r"|bd|bdrip|bdremux|bluray|blu-ray|web|web-?dl|webrip|tvrip|dvdrip|remux"
    r"|chs|cht|gb|big5|jpn?|eng?|sc|tc|chs_jp|cht_jp|jpsc|jptc|ass|srt"
    r"|[0-9a-f]{8}"
    r")$",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class WorkEpisode:
    work: str | None
    episode: str | None


def _is_tech(token: str) -> bool:
    parts = [p for p in re.split(r"[\s_\-+&,.]+", token.strip()) if p]
    return bool(parts) and all(_TECH.match(p) for p in parts)


def _is_year(digits: str) -> bool:
    return len(digits) == 4 and digits[:2] in ("19", "20")


def _clean(text: str) -> str:
    # 点和下划线只在整段没有空格时当分隔符（Yuru.Yuri.S01E01），否则保留（Dr. Stone）
    text = text.strip()
    if " " not in text:
        text = re.sub(r"[_.]+", " ", text)
    text = re.sub(r"\s+", " ", text)
    return text.strip(" -\u2013\u2014\uff0d~\u301c")


def _ep_from_text(text: str) -> tuple[str, str] | None:
    """返回 (集数, 集数之前的文字)。"""
    for pat in _EP_IN_TEXT:
        for m in pat.finditer(text):
            if not _is_year(m.group(1)):
                return m.group(1), text[: m.start()]
    return None


def infer_work_episode(filename: str) -> WorkEpisode:
    stem = unicodedata.normalize("NFC", PurePath(filename).stem)
    # 切块：("b", 括号内容) / ("t", 自由文字)
    parts: list[tuple[str, str]] = []
    pos = 0
    for m in _BRACKETS.finditer(stem):
        if m.start() > pos:
            parts.append(("t", stem[pos : m.start()]))
        parts.append(("b", (m.group(1) if m.group(1) is not None else m.group(2)).strip()))
        pos = m.end()
    if pos < len(stem):
        parts.append(("t", stem[pos:]))
    parts = [(k, v) for k, v in parts if v.strip()]

    # 集数：括号块优先
    episode: str | None = None
    work: str | None = None
    for i, (kind, val) in enumerate(parts):
        if kind == "b" and (m := _EP_TOKEN.match(val)) and not _is_year(m.group(1)):
            episode = m.group(1)
            before = [v for k, v in parts[:i] if k == "t" and _clean(v)]
            if before:
                work = _clean(before[-1])
            else:
                prev = [v for k, v in parts[:i] if k == "b" and not _is_tech(v)]
                # 只有发布组一个括号块在前时，它也可能就是作品名（[Kemono Friends][01]）
                work = _clean(prev[-1]) if prev else None
            break

    if episode is None:
        for i, (kind, val) in enumerate(parts):
            if kind != "t":
                continue
            found = _ep_from_text(val)
            if found:
                episode, before = found
                work = _clean(before) or None
                if work is None:
                    prev = [v for k, v in parts[:i] if k == "b" and not _is_tech(v)]
                    work = _clean(prev[-1]) if prev else None
                break

    if work is None and episode is None:
        texts = [_clean(v) for k, v in parts if k == "t" and _clean(v)]
        if texts:
            work = texts[0]
        else:
            blocks = [v for k, v in parts if k == "b" and not _is_tech(v)]
            if len(blocks) >= 2:
                work = _clean(blocks[1])
            elif blocks:
                work = _clean(blocks[0])

    return WorkEpisode(work or None, episode)
