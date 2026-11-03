"""用户辞典（规格 08 §8.2.4、14 §14.2、16 R10.2）。

- 全局一份；每行 ``表记<Tab>片假名读音``：表记非空、不重复、≤200 字；读音只能是片假名（ァ–ヺ）与「ー」、≤200 字；空行忽略。错误报行号。
- 保存：编译成 MeCab 用户辞典（先编译到任务目录、加载验证），成功后由 Core 原子启用；失败时当前生效的辞典不变。
- 编译产物按内容命名（``user-<SHA-256 前 16 位>.dic``），不覆盖、不删除旧的——撤销就是指回旧的产物。
- 辞典里的读音受保护（不被 tsqyomi 的读音选择覆盖）。改辞典不自动重跑已有对齐。

本模块的解析与校验不依赖 pyopenjtalk（Core 主进程可用）；编译与加载只在任务进程里做。
"""

from __future__ import annotations

import hashlib
import os
import sys
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from ...core.errors import CoreError
from .frontend import LONG, split_mora

MAX_CHARS = 200
_KATA_LO, _KATA_HI = 0x30A1, 0x30FA


@dataclass(frozen=True)
class Entry:
    line: int
    surface: str
    reading: str


def _is_reading(s: str) -> bool:
    return bool(s) and all(_KATA_LO <= ord(c) <= _KATA_HI or c == LONG for c in s)


def parse(text: str) -> tuple[list[Entry], list[dict[str, Any]]]:
    """逐行解析与校验：返回（条目，错误列表 [{line, reason}]）。"""
    entries: list[Entry] = []
    errors: list[dict[str, Any]] = []
    seen: dict[str, int] = {}
    for i, raw in enumerate(text.replace("\r\n", "\n").replace("\r", "\n").split("\n"), start=1):
        if not raw.strip():
            continue
        if raw.count("\t") != 1:
            errors.append({"line": i, "reason": "dict-format"})
            continue
        surface, reading = (x.strip() for x in raw.split("\t"))
        if not surface:
            errors.append({"line": i, "reason": "dict-surface-empty"})
        elif len(surface) > MAX_CHARS:
            errors.append({"line": i, "reason": "dict-surface-too-long", "max": MAX_CHARS})
        elif surface in seen:
            errors.append({"line": i, "reason": "dict-duplicate", "first": seen[surface]})
        elif len(reading) > MAX_CHARS:
            errors.append({"line": i, "reason": "dict-reading-too-long", "max": MAX_CHARS})
        elif not _is_reading(reading):
            errors.append({"line": i, "reason": "dict-reading-not-katakana"})
        else:
            seen[surface] = i
            entries.append(Entry(i, surface, reading))
    return entries, errors


def check(text: str) -> list[Entry]:
    entries, errors = parse(text)
    if errors:
        raise CoreError("dictionary-invalid", **errors[0])
    return entries


def content_name(text: str) -> str | None:
    """编译产物的文件名（按辞典内容）；没有条目为 None（= 不用用户辞典）。"""
    entries = check(text)
    if not entries:
        return None
    canon = "\n".join(f"{e.surface}\t{e.reading}" for e in entries)
    return f"user-{hashlib.sha256(canon.encode('utf-8')).hexdigest()[:16]}.dic"


def version_of(compiled: str | None) -> str:
    """写进测量的辞典版本。"""
    return compiled.removesuffix(".dic") if compiled else "none"


def _csv_field(s: str) -> str:
    return '"' + s.replace('"', '""') + '"' if ("," in s or '"' in s) else s


def to_csv(entries: list[Entry]) -> str:
    """MeCab 用户辞典的 CSV（14 §14.2 的旧版格式：名詞,一般，mora 数取自读音）。"""
    noun, general = "\u540d\u8a5e", "\u4e00\u822c"  # 名詞、一般（core 里不写 CJK 字面量）
    lines = []
    for e in entries:
        s = _csv_field(e.surface)
        lines.append(f'{s},"","",1,{noun},{general},*,*,*,*,{s},{e.reading},{e.reading},0/{len(split_mora(e.reading))},*')
    return "\n".join(lines) + "\n"


@contextmanager
def _stdout_to_stderr():
    """MeCab 的编译进度直接写文件描述符 1；任务进程的 stdout 是事件通道，编译期间把它指到 stderr。"""
    sys.stdout.flush()
    _c_flush()
    saved = os.dup(1)
    try:
        os.dup2(2, 1)
        yield
    finally:
        # C 运行库的输出缓冲要在指回之前清掉，否则进程退出时才写到真正的 stdout
        _c_flush()
        sys.stdout.flush()
        os.dup2(saved, 1)
        os.close(saved)


def _c_flush() -> None:
    import ctypes
    import ctypes.util

    try:
        # Windows：Python 和扩展用的是通用 C 运行库 ucrtbase，不是旧的 msvcrt（各有各的缓冲）
        libc = ctypes.CDLL("ucrtbase" if sys.platform == "win32" else ctypes.util.find_library("c"))
        libc.fflush(None)
    except (OSError, AttributeError):
        pass


def compile_to(text: str, out: Path) -> str | None:
    """（任务进程）编译到 ``out`` 并加载验证；返回产物名。失败抛 dictionary-compile-failed，不留下产物。"""
    from . import openjtalk

    entries = check(text)
    name = content_name(text)
    if name is None:
        return None
    pj = openjtalk.load()
    csv = out.with_suffix(".csv")
    csv.write_text(to_csv(entries), encoding="utf-8")
    try:
        with _stdout_to_stderr():
            pj.mecab_dict_index(str(csv), str(out))
        jtalk_for(out)  # 加载验证
    except Exception as exc:  # noqa: BLE001
        out.unlink(missing_ok=True)
        raise CoreError("dictionary-compile-failed", detail=f"{type(exc).__name__}: {exc}") from None
    return name


def jtalk_for(path: Path | None) -> Any:
    """（任务进程）带用户辞典的 OpenJTalk 实例；``path`` 为 None = 系统辞典。辞典读音受保护。"""
    from pyopenjtalk.openjtalk import OpenJTalk

    from . import openjtalk

    pj = openjtalk.load()
    if path is None:
        return OpenJTalk(dn_mecab=pj.OPEN_JTALK_DICT_DIR)
    if not path.is_file():
        raise CoreError("frontend-failed", reason="dictionary-missing", detail=str(path))
    return OpenJTalk(dn_mecab=pj.OPEN_JTALK_DICT_DIR, userdic=str(path).encode("utf-8"), userdic_reading_protection=[True])
