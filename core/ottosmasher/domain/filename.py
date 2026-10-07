"""可移植文件名与导出文件名（规格 12 §12.1、16 R21.3；QUESTIONS C4）。

默认模板（旧版格式）：
    <内容>__[<处理信息>__]<音轨>__<原片段>_<起止>__<导出键前 12 位>.wav
- 内容 ≤72 字节；处理信息 ≤45 字节，为空整段省略；
- 原片段 = 原片名（≤35 字节，C4）+ ``__`` + 原片 ID 前 8 位，整段 ≤45 字节；
- 起止 = 原片时间 ``HH-MM-SS.mmm-HH-MM-SS.mmm``；资产没有映射时为“局部”词 + 资产时间；
- 整个文件名 ≤255 字节；超出时先缩内容、再缩音轨，处理信息段与导出键永远保留，以 12 位短 ID 结尾。
段里的固定词（音轨名、“局部-”“ · 片段”等）由调用方按界面语言传入，这里不写死任何语言。
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass

from ottosmasher.core.errors import CoreError

MAX_NAME_BYTES = 255
CONTENT_BYTES = 72
PROCESSING_BYTES = 45
SOURCE_NAME_BYTES = 35
SOURCE_SEGMENT_BYTES = 45
SHORT_ID_LEN = 12
SOURCE_ID_LEN = 8
SEP = "__"

_ILLEGAL = re.compile(r'[\\/:*?"<>|\x00-\x1f\x7f]')
_RESERVED = re.compile(r"^(?:CON|PRN|AUX|NUL|COM[1-9]|LPT[1-9])$", re.IGNORECASE)


def utf8_len(s: str) -> int:
    return len(s.encode("utf-8"))


def truncate_utf8(s: str, max_bytes: int) -> str:
    """按 UTF-8 字节截断，不切开字符，也不把组合字符和它的基字分开。"""
    if utf8_len(s) <= max_bytes:
        return s
    out, used = [], 0
    for ch in s:
        n = utf8_len(ch)
        if used + n > max_bytes:
            break
        out.append(ch)
        used += n
    while out and unicodedata.combining(out[-1]):
        out.pop()
    # 去掉被截断的组合序列的基字
    if len(out) < len(s) and unicodedata.combining(s[len(out)]) and out:
        out.pop()
    return "".join(out)


def portable(s: str) -> str:
    """一段文件名的可移植化：NFC；``\\ / : * ? " < > |`` 与控制字符换成 ``_``；去首尾空格和点；
    Windows 保留名（看第一个点之前的部分）前加 ``_``。"""
    s = unicodedata.normalize("NFC", s)
    s = _ILLEGAL.sub("_", s)
    s = s.strip(" .")
    if _RESERVED.match(s.split(".", 1)[0]):
        s = "_" + s
    return s


def _fit(s: str, max_bytes: int) -> str:
    """可移植化后截断；截断后再去一次首尾空格和点。"""
    return truncate_utf8(portable(s), max_bytes).strip(" .")


def format_clock(t: float) -> str:
    """``HH-MM-SS.mmm``（毫秒四舍五入；文件名里不能用冒号）。"""
    if t < 0:
        raise CoreError("time-out-of-range", t=t, start=0.0, end=None, clock="source")
    ms = round(t * 1000)
    h, rem = divmod(ms, 3_600_000)
    m, rem = divmod(rem, 60_000)
    s, ms = divmod(rem, 1000)
    return f"{h:02d}-{m:02d}-{s:02d}.{ms:03d}"


@dataclass(frozen=True)
class ExportNameParts:
    content: str
    """采样名称，或建议名 + “ · 片段”；没有原片时为“试听片段”（调用方按语言给出）。"""
    track: str
    """角色名（原混音 / 人声 / …）或声部原名（调用方给出）。"""
    source_name: str
    source_id: str
    start: float
    end: float
    export_key: str
    """稳定导出键（十六进制），文件名以它的前 12 位结尾。"""
    processing: str = ""
    """如 ``拉平-G♯5``、``卡拍-120BPM``，两者都有用 ``_`` 连接；为空整段省略。"""
    local_prefix: str | None = None
    """资产没有到原片的映射时，起止写成 ``<local_prefix><资产时间>``（如“局部-”）；有映射时为 None。"""
    ext: str = "wav"


def export_filename(p: ExportNameParts) -> str:
    key = p.export_key[:SHORT_ID_LEN]
    if len(key) < SHORT_ID_LEN or not re.fullmatch(r"[0-9a-zA-Z]+", key):
        raise CoreError("export-key-invalid", key=p.export_key)
    processing = _fit(p.processing, PROCESSING_BYTES)
    src_id = portable(p.source_id[:SOURCE_ID_LEN])
    src_name = _fit(p.source_name, SOURCE_NAME_BYTES)  # 35 + 2 + 8 = 45（C4）
    source_seg = f"{src_name}{SEP}{src_id}"
    span = f"{format_clock(p.start)}-{format_clock(p.end)}"
    if p.local_prefix is not None:
        span = portable(p.local_prefix) + span
    tail = f"{SEP}{source_seg}_{span}{SEP}{key}.{portable(p.ext)}"

    content = _fit(p.content, CONTENT_BYTES)
    track = portable(p.track)

    def build(c: str, t: str) -> str:
        head = c + (f"{SEP}{processing}" if processing else "")
        return f"{head}{SEP}{t}{tail}"

    name = build(content, track)
    over = utf8_len(name) - MAX_NAME_BYTES
    if over > 0:
        content = truncate_utf8(content, max(0, utf8_len(content) - over)).strip(" .")
        name = build(content, track)
        over = utf8_len(name) - MAX_NAME_BYTES
    if over > 0:
        track = truncate_utf8(track, max(0, utf8_len(track) - over)).strip(" .")
        name = build(content, track)
    if utf8_len(name) > MAX_NAME_BYTES:
        raise CoreError("filename-too-long", name=name)
    return name
