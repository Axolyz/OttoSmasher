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


# ---------------------------------------------------------------- 文本层搜索（所有者 2026-10-31）

# 搜原料（文本层的段与音效提示），结果是原片上的位置，不是采样：采样库的筛选与三大搜索只对采样（已确认有价值的片段）。
# 匹配规则与采样的“原句”筛选相同（规范化原文子串，或读音子串），用同一份 segment_search 索引。
SEARCH_LIMIT_MAX = 5000
SEARCH_CATCH_UP = 300
"""检索前顺手补齐的读音段数上限（读音一段约 1 毫秒量级）；还没补上的段只按原文匹配，结果里报 ``readingPending``。"""


def norm_spans(text: str, needle: str) -> list[list[int]]:
    """规范化后的命中在原文里的字符范围（逐字规范化建立对应；对不上就不给高亮）。"""
    if not needle:
        return []
    chars: list[str] = []
    origin: list[int] = []
    for i, ch in enumerate(text):
        for c in norm(ch):
            chars.append(c)
            origin.append(i)
    flat = "".join(chars)
    out, start = [], flat.find(needle)
    while start >= 0:
        end = start + len(needle) - 1
        out.append([origin[start], origin[end] + 1])
        start = flat.find(needle, start + len(needle))
    return out


def search_layer(conn: sqlite3.Connection, reader: Reader | None, query: str, *, source_ids: list[str] | None = None, hints: bool = True,
                 speakers: list[str] | None = None, limit: int = 500, offset: int = 0) -> dict[str, Any]:
    from json import loads

    from .errors import CoreError

    if not 1 <= int(limit) <= SEARCH_LIMIT_MAX or int(offset) < 0:
        raise CoreError("bad-request", method="textLayer.search", reason="limit")
    n, r = query_parts(conn, reader, query)
    pending = 0
    if reader is not None and n:
        ensure(conn, reader, limit=SEARCH_CATCH_UP)
        pending = len(stale_ids(conn, reader.version(conn)[1]))
    scope, args = "", []
    if source_ids is not None:
        scope = f" AND t.source_id IN ({','.join('?' * len(source_ids))})"
        args = list(source_ids)
    hits: list[dict[str, Any]] = []
    if n:
        rows = conn.execute(
            'SELECT t.id, t.source_id, t.start, t."end", t.text, t.speakers, x.text AS xtext, x.norm, x.reading FROM text_segment t'
            f" LEFT JOIN segment_search x ON x.segment_id = t.id WHERE t.deleted = 0{scope}", args,
        ).fetchall()
        want = set(speakers or [])
        for row in rows:
            names = loads(row["speakers"])
            if want and not want & set(names):
                continue
            fresh = row["xtext"] is not None and row["xtext"] == row["text"]
            normed = row["norm"] if fresh else norm(row["text"])
            if n in normed:
                how = "text"
            elif fresh and r and r in row["reading"]:
                how = "reading"
            else:
                continue
            hits.append({"sourceId": row["source_id"], "kind": "segment", "id": row["id"], "start": row["start"], "end": row["end"], "text": row["text"],
                         "speakers": names, "match": how, "spans": norm_spans(row["text"], n) if how == "text" else []})
        if hints and not want:
            for row in conn.execute(f'SELECT t.id, t.source_id, t.start, t."end", t.text FROM sfx_hint t WHERE t.deleted = 0{scope}', args):
                if n in norm(row["text"]):
                    hits.append({"sourceId": row["source_id"], "kind": "hint", "id": row["id"], "start": row["start"], "end": row["end"], "text": row["text"],
                                 "speakers": [], "match": "text", "spans": norm_spans(row["text"], n)})
    hits.sort(key=lambda h: (h["sourceId"], h["start"], h["end"], h["kind"]))
    per: dict[str, int] = {}
    for h in hits:
        per[h["sourceId"]] = per.get(h["sourceId"], 0) + 1
    # 关联了字幕但文本层还是空的原素材：搜不到，告诉调用方
    sql = ("SELECT s.id FROM source s WHERE s.subtitle_path IS NOT NULL"
           " AND NOT EXISTS (SELECT 1 FROM text_segment t WHERE t.source_id = s.id AND t.deleted = 0)"
           " AND NOT EXISTS (SELECT 1 FROM sfx_hint h WHERE h.source_id = s.id AND h.deleted = 0)")
    if source_ids is not None:
        sql += f" AND s.id IN ({','.join('?' * len(source_ids))})"
    not_imported = [x[0] for x in conn.execute(sql, args)]
    return {"query": query, "total": len(hits), "hits": hits[int(offset): int(offset) + int(limit)],
            "bySource": [{"sourceId": k, "count": v} for k, v in per.items()], "notImported": not_imported, "readingPending": pending}
