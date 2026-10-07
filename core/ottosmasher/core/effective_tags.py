"""有效标签（规格 04 §4.2.9、16 R5.2–R5.5、R8.6–R8.8；ARCHITECTURE §4 ``sample_effective_tag``）。

语义是**实时求值**、从不冻结到采样上：

- 本地：``sample_tag``；
- 原片：``work:作品``、``type:来源类型``（随原片属性实时变化）；
- 区段：时间标注上的标签，按作用域 + 正长度交叠继承——
  判定区间 = 采样的“标签判定区间”（字幕采样 = 原字幕时间，原片秒）或采样选区经资产映射到原片秒；
  原片作用域：所有资产；角色作用域：资产必须带该角色（state=on）；资产作用域：只对这一个资产，用资产局部秒比较；
  只算当前字幕版本的标注（手动建的标注没有版本，始终参与）和未删除的标注；端点相接不算交叠；
- 自动：拉平目标音 ``pitch:`` 等（阶段 5 起）。

同名只记一行：本地 ＞ 原片 ＞ 区段 ＞ 自动（本地优先，04 §4.2.9）；计数按采样计（R8.6）。

``sample_effective_tag`` 是派生索引：在**同一个写事务**里按受影响的采样增量刷新（编辑通道的每次写入、采样新建）。
所有刷新都走 ``refresh``（就是对受影响采样做完整重算），所以“增量 = 完整重算”（R8.8）只取决于受影响集合找得全不全——
``affected_by_change`` 集中列出各种变化影响哪些采样。
"""

from __future__ import annotations

import sqlite3
from collections.abc import Iterable
from typing import Any

from ottosmasher.domain.mapping import Mapping
from ottosmasher.domain.overlap import overlaps

from .edits import facet_of, loads
from .errors import CoreError

_PRIORITY = {"local": 0, "source": 1, "segment": 2, "auto": 3}


def compute(conn: sqlite3.Connection, sample_id: str) -> list[tuple[str, str, str | None]]:
    """一个采样的有效标签：[(tag, provenance, provenance_ref)]，按标签排序。"""
    s = conn.execute(
        'SELECT s.id, s.start, s."end", s.tag_judge_start, s.tag_judge_end, s.asset_id, a.mapping, a.source_id,'
        " src.work, src.source_type, src.current_subtitle_version_id"
        " FROM sample s JOIN sound_asset a ON a.id=s.asset_id JOIN source src ON src.id=a.source_id WHERE s.id=?",
        (sample_id,),
    ).fetchone()
    if s is None:
        return []
    found: dict[str, tuple[str, str | None]] = {}

    def add(tag: str, prov: str, ref: str | None = None) -> None:
        cur = found.get(tag)
        if cur is None or _PRIORITY[prov] < _PRIORITY[cur[0]]:
            found[tag] = (prov, ref)

    for (tag,) in conn.execute("SELECT tag FROM sample_tag WHERE sample_id=?", (sample_id,)):
        add(tag, "local")
    if s["work"]:
        add(f"work:{s['work']}", "source", s["source_id"])
    if s["source_type"]:
        add(f"type:{s['source_type']}", "source", s["source_id"])

    roles = {r[0] for r in conn.execute("SELECT role FROM asset_role WHERE asset_id=? AND state='on'", (s["asset_id"],))}
    # 原片秒的判定区间：字幕采样用标签判定区间，否则选区经映射换算；没有映射就只看资产作用域
    src_win: tuple[float, float] | None = None
    if s["tag_judge_start"] is not None and s["tag_judge_end"] is not None:
        src_win = (s["tag_judge_start"], s["tag_judge_end"])
    elif s["mapping"]:
        try:
            m = Mapping.of(loads(s["mapping"]))
            src_win = (m.to_source(s["start"]), m.to_source(s["end"]))
        except CoreError:
            src_win = None
    rows = conn.execute(
        'SELECT id, scope, scope_role, scope_asset_id, start, "end", tags FROM annotation'
        " WHERE source_id=? AND deleted=0 AND tags != '[]'"
        " AND (subtitle_version_id IS NULL OR subtitle_version_id IS ?)",
        (s["source_id"], s["current_subtitle_version_id"]),
    )
    for r in rows:
        if r["scope"] == "asset":
            if r["scope_asset_id"] != s["asset_id"] or not overlaps(s["start"], s["end"], r["start"], r["end"]):
                continue
        else:
            if src_win is None or not overlaps(src_win[0], src_win[1], r["start"], r["end"]):
                continue
            if r["scope"] == "role" and r["scope_role"] not in roles:
                continue
        for tag in loads(r["tags"]):
            add(tag, "segment", r["id"])
    return sorted((t, p, ref) for t, (p, ref) in found.items())


def refresh(conn: sqlite3.Connection, sample_ids: Iterable[str]) -> None:
    """在调用方的写事务里重算这些采样的有效标签。"""
    for sid in dict.fromkeys(sample_ids):
        conn.execute("DELETE FROM sample_effective_tag WHERE sample_id=?", (sid,))
        conn.executemany(
            "INSERT INTO sample_effective_tag(sample_id, tag, facet, provenance, provenance_ref) VALUES (?, ?, ?, ?, ?)",
            [(sid, t, facet_of(t), p, ref) for t, p, ref in compute(conn, sid)],
        )


def rebuild_all(conn: sqlite3.Connection) -> None:
    refresh(conn, [r[0] for r in conn.execute("SELECT id FROM sample")])


def samples_of_source(conn: sqlite3.Connection, source_id: str) -> list[str]:
    return [r[0] for r in conn.execute("SELECT s.id FROM sample s JOIN sound_asset a ON a.id=s.asset_id WHERE a.source_id=?", (source_id,))]


def samples_of_asset(conn: sqlite3.Connection, asset_id: str) -> list[str]:
    return [r[0] for r in conn.execute("SELECT id FROM sample WHERE asset_id=?", (asset_id,))]


_SOURCE_FIELDS = {"work", "source_type", "current_subtitle_version_id"}


def affected_by_change(conn: sqlite3.Connection, entity: str, entity_id: str, fields: Iterable[str]) -> list[str]:
    """一个对象的一次修改会影响哪些采样的有效标签。"""
    fields = set(fields)
    if entity == "sample":
        return [entity_id] if "local_tags" in fields else []
    if entity == "source":
        return samples_of_source(conn, entity_id) if fields & _SOURCE_FIELDS else []
    if entity == "asset":
        return samples_of_asset(conn, entity_id) if "roles" in fields else []
    if entity == "annotation":
        row = conn.execute("SELECT source_id FROM annotation WHERE id=?", (entity_id,)).fetchone()
        return samples_of_source(conn, row[0]) if row else []
    return []


def people(conn: sqlite3.Connection, sample_ids: list[str]) -> dict[str, list[str]]:
    """列表第二行的“人物”（R5.5 说话人显示层：只显示名字，底层标签不变）：character: 在前，participants: 在后。"""
    if not sample_ids:
        return {}
    marks = ",".join("?" * len(sample_ids))
    out: dict[str, list[str]] = {}
    for sid, tag in conn.execute(
        f"SELECT sample_id, tag FROM sample_effective_tag WHERE facet='person' AND sample_id IN ({marks})"
        " ORDER BY sample_id, CASE WHEN tag LIKE 'character:%' THEN 0 ELSE 1 END, tag",
        sample_ids,
    ):
        name = tag.split(":", 1)[1]
        if name not in out.setdefault(sid, []):
            out[sid].append(name)
    return out


def of_sample(conn: sqlite3.Connection, sample_id: str) -> list[dict[str, Any]]:
    return [
        {"tag": r[0], "facet": r[1], "provenance": r[2], "ref": r[3]}
        for r in conn.execute(
            "SELECT tag, facet, provenance, provenance_ref FROM sample_effective_tag WHERE sample_id=? ORDER BY facet, tag", (sample_id,)
        )
    ]
