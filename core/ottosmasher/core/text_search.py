"""文字搜索（规格 07 §7.1；所有者 2026-10-09 的四类对象：采样的“原句”= 它读到的文本层的段）。

- 名称、备注：子串匹配（拉丁字母不区分大小写，SQLite LIKE）；
- 原句文本：段文本与查询词都做 NFKC、小写、去掉标点/空白/控制字符后子串匹配；
- 读音：段文本与查询词都转成平假名读音（再按上一条规范化）后子串匹配。例：搜“きょう”能找到“今日はいい天気”。
  读音用 pyopenjtalk-plus（带用户辞典）的读音；**不经 tsqyomi**（那是 ONNX 模型，跑在任务进程里；搜索要在 Core 里同步、快）——
  所以个别多音汉字的读音可能与语音分析时不同（开发者决定，见 QUESTIONS「阶段 8 / 9 开发者定的细节」）。
- 段的规范化文本与读音存在 ``segment_search``（可重建）；检索前补齐过期的行（文本或辞典版本变了），资料变化后也在后台补。
- 〔中英文预留〕读音按语言选择转换方式；本轮只有日语。
"""

from __future__ import annotations

import sqlite3
import threading
import unicodedata
from pathlib import Path
from typing import Any

from . import settings as settings_mod

_KATA_START, _KATA_END = 0x30A1, 0x30F6


def norm(text: str) -> str:
    """NFKC → 小写 → 去掉标点、空白、控制字符（Unicode 类别 P*、Z*、C*）。"""
    out = []
    for ch in unicodedata.normalize("NFKC", text).lower():
        cat = unicodedata.category(ch)
        if cat[0] in "PZC" or ch.isspace():
            continue
        out.append(ch)
    return "".join(out)


def to_hiragana(kana: str) -> str:
    return "".join(chr(ord(c) - 0x60) if _KATA_START <= ord(c) <= _KATA_END else c for c in kana)


def like_needle(s: str) -> str:
    return "%" + s.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"


class Reader:
    """日语读音（Core 进程内，按用户辞典缓存 OpenJTalk 实例）。线程安全：一次只算一句。"""

    def __init__(self, dictionary_dir: Path) -> None:
        self.dictionary_dir = dictionary_dir
        self._lock = threading.Lock()
        self._jtalk: Any = None
        self._compiled: str | None = "\0"

    def version(self, conn: sqlite3.Connection) -> tuple[str | None, str]:
        from ..lang.ja import dictionary as dict_mod

        compiled = settings_mod.values(conn)["frontend.user_dictionary"]["compiled"]
        return compiled, dict_mod.version_of(compiled)

    def reading(self, text: str, compiled: str | None) -> str:
        from ..lang.ja import dictionary as dict_mod
        from ..lang.ja import frontend, openjtalk

        if not text.strip():
            return ""
        with self._lock:
            pj = openjtalk.load()
            if compiled != self._compiled:
                self._jtalk = dict_mod.jtalk_for(self.dictionary_dir / compiled if compiled else None)
                self._compiled = compiled
            kana = pj.g2p(frontend.normalize(text), kana=True, use_tsqyomi=False, predict_nani=False, jtalk=self._jtalk)
        return norm(to_hiragana(str(kana)))


def stale_ids(conn: sqlite3.Connection, dict_version: str, limit: int | None = None) -> list[tuple[str, str]]:
    sql = (
        "SELECT t.id, t.text FROM text_segment t LEFT JOIN segment_search x ON x.segment_id = t.id"
        " WHERE t.deleted = 0 AND (x.segment_id IS NULL OR x.text != t.text OR x.dict_version != ?)"
    )
    if limit:
        sql += f" LIMIT {int(limit)}"
    return [(r[0], r[1]) for r in conn.execute(sql, (dict_version,))]


def ensure(conn: sqlite3.Connection, reader: Reader, limit: int | None = None) -> int:
    """补齐过期的行（在调用方线程里、自己的写事务里）。返回补了几段。"""
    from ottosmasher.store.db import transaction

    compiled, ver = reader.version(conn)
    todo = stale_ids(conn, ver, limit)
    if not todo:
        return 0
    rows = [(sid, text, ver, norm(text), reader.reading(text, compiled)) for sid, text in todo]
    with transaction(conn):
        conn.executemany(
            "INSERT INTO segment_search(segment_id, text, dict_version, norm, reading) VALUES (?, ?, ?, ?, ?)"
            " ON CONFLICT(segment_id) DO UPDATE SET text = excluded.text, dict_version = excluded.dict_version,"
            " norm = excluded.norm, reading = excluded.reading",
            rows,
        )
    return len(rows)


def query_parts(conn: sqlite3.Connection, reader: Reader | None, text: str) -> tuple[str, str]:
    """查询词 → (规范化原文, 规范化读音)。没有读音器（单元测试）时读音 = 只把片假名换成平假名。"""
    q = text.strip()
    n = norm(q)
    if reader is None:
        return n, norm(to_hiragana(q))
    compiled, _ver = reader.version(conn)
    return n, reader.reading(q, compiled)
