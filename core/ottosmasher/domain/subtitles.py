"""字幕文件读取（规格 06 §6.1、16 R4）：SRT / ASS → 按文件顺序的字幕条（原片秒）。

- 编码：UTF-8，有无 BOM 都行；LF / CRLF / CR。别的编码明确报错（``subtitle-encoding``），不猜、不静默替换（P6）。
- ASS 转纯文本：``\\N`` → 换行，``\\n`` / ``\\h`` → 空格，去掉 ``{…}`` 样式块；SRT 与 ASS 都去掉 ``<…>`` 标签与 ``{…}`` 块
  （字幕只当纯文本，不执行样式指令）。多行保留换行；全角空格、全角数字、各种破折号/引号原样保留。
- 只解析，不判断有效性：开始 < 0、结束 ≤ 开始、超出时长这些“无效范围”由导入预览按原片时长判定（R4.3）。
  写法坏到读不出时间的块记进 ``problems``（行号 + 原因），不静默丢弃。
- 内容指纹（字幕版本，R4.2）：解码后的文本去 BOM、统一换行后的 SHA-256。
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field
from pathlib import Path

from ottosmasher.core.errors import CoreError

SUBTITLE_EXTS = (".srt", ".ass", ".ssa")
"""能读的字幕格式（原片关联同名字幕只看 .srt / .ass，见 core.sources）"""

_SRT_TIME = re.compile(
    r"^\s*(?P<a>-?\d+:\d{1,2}:\d{1,2}(?:[,.]\d{1,3})?)\s*-->\s*(?P<b>-?\d+:\d{1,2}:\d{1,2}(?:[,.]\d{1,3})?)(?:\s.*)?$"
)
_TAG = re.compile(r"<[^<>\n]*>")
_BLOCK = re.compile(r"\{[^{}\n]*\}")


@dataclass(frozen=True)
class Cue:
    order: int
    """文件中的顺序（从 1 起，只算读出来的条目）"""
    ref: str
    """文件里的编号：SRT 的序号行；ASS 为 Dialogue 行的序号（从 1 起）"""
    start: float
    end: float
    """原片秒（字幕时间轴与原片一致）"""
    text: str
    """纯文本，多行以 ``\\n`` 连接"""
    line: int
    """在文件中的起始行号（从 1 起），报告问题用"""


@dataclass
class ParsedSubtitle:
    format: str
    cues: list[Cue]
    fingerprint: str
    problems: list[dict[str, object]] = field(default_factory=list)


def decode(data: bytes, *, path: str = "") -> str:
    try:
        text = data.decode("utf-8-sig")
    except UnicodeDecodeError:
        raise CoreError("subtitle-encoding", path=path) from None
    return text.replace("\r\n", "\n").replace("\r", "\n")


def fingerprint(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _clock(s: str) -> float:
    neg = s.startswith("-")
    s = s.lstrip("-").replace(",", ".")
    h, m, sec = s.split(":")
    if "." in sec:
        whole, frac = sec.split(".")
        ms = int((frac + "00")[:3])
    else:
        whole, ms = sec, 0
    v = int(h) * 3600 + int(m) * 60 + int(whole) + ms / 1000
    return -v if neg else v


def clean_text(text: str) -> str:
    """去掉样式块与标签，逐行去行尾空白；保留换行与全角字符。"""
    text = _BLOCK.sub("", text)
    text = _TAG.sub("", text)
    return "\n".join(line.rstrip() for line in text.split("\n")).strip("\n")


def parse_srt(text: str) -> tuple[list[Cue], list[dict[str, object]]]:
    lines = text.split("\n")
    cues: list[Cue] = []
    problems: list[dict[str, object]] = []
    i = 0
    n = len(lines)
    while i < n:
        while i < n and not lines[i].strip():
            i += 1
        if i >= n:
            break
        start_line = i
        ref = ""
        m = _SRT_TIME.match(lines[i])
        if m is None and i + 1 < n:
            ref = lines[i].strip()
            m = _SRT_TIME.match(lines[i + 1])
            if m is not None:
                i += 1
        if m is None:
            # 读不出时间：跳过这一块并报告
            problems.append({"line": start_line + 1, "reason": "no-timing"})
            while i < n and lines[i].strip():
                i += 1
            continue
        i += 1
        body: list[str] = []
        while i < n and lines[i].strip():
            body.append(lines[i])
            i += 1
        cues.append(
            Cue(
                order=len(cues) + 1,
                ref=ref,
                start=_clock(m["a"]),
                end=_clock(m["b"]),
                text=clean_text("\n".join(body)),
                line=start_line + 1,
            )
        )
    return cues, problems


def _ass_text(raw: str) -> str:
    t = _BLOCK.sub("", raw)
    t = t.replace("\\N", "\n").replace("\\n", " ").replace("\\h", " ")
    return clean_text(t)


def parse_ass(text: str) -> tuple[list[Cue], list[dict[str, object]]]:
    cues: list[Cue] = []
    problems: list[dict[str, object]] = []
    section = ""
    fmt: list[str] | None = None
    dialogue_no = 0
    for ln, line in enumerate(text.split("\n"), start=1):
        s = line.strip()
        if s.startswith("[") and s.endswith("]"):
            section = s.lower()
            fmt = None
            continue
        if section != "[events]":
            continue
        key, sep, rest = s.partition(":")
        if not sep:
            continue
        key = key.strip().lower()
        if key == "format":
            fmt = [x.strip().lower() for x in rest.split(",")]
            continue
        if key != "dialogue":
            continue  # Comment 等不算字幕
        dialogue_no += 1
        cols = fmt or ["layer", "start", "end", "style", "name", "marginl", "marginr", "marginv", "effect", "text"]
        parts = rest.lstrip().split(",", len(cols) - 1)
        if len(parts) < len(cols) or "start" not in cols or "end" not in cols or "text" not in cols:
            problems.append({"line": ln, "reason": "bad-dialogue"})
            continue
        rec = dict(zip(cols, parts, strict=False))
        try:
            a, b = _clock(rec["start"].strip()), _clock(rec["end"].strip())
        except ValueError:
            problems.append({"line": ln, "reason": "no-timing"})
            continue
        cues.append(Cue(order=len(cues) + 1, ref=str(dialogue_no), start=a, end=b, text=_ass_text(rec["text"]), line=ln))
    return cues, problems


def parse_text(text: str, fmt: str) -> ParsedSubtitle:
    if fmt == "srt":
        cues, problems = parse_srt(text)
    elif fmt in ("ass", "ssa"):
        cues, problems = parse_ass(text)
        fmt = "ass"
    else:
        raise CoreError("subtitle-format", format=fmt)
    return ParsedSubtitle(format=fmt, cues=cues, fingerprint=fingerprint(text), problems=problems)


def read(path: str | Path) -> ParsedSubtitle:
    p = Path(path)
    try:
        data = p.read_bytes()
    except FileNotFoundError:
        raise CoreError("subtitle-missing", path=str(p)) from None
    except OSError as e:
        raise CoreError("subtitle-unreadable", path=str(p), detail=str(e)) from None
    ext = p.suffix.lower().lstrip(".")
    if f".{ext}" not in SUBTITLE_EXTS:
        raise CoreError("subtitle-format", format=ext)
    return parse_text(decode(data, path=str(p)), ext)
