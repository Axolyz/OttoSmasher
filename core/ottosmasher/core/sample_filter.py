"""采样浏览的条件（规格 07 §7.1–§7.3；UI_PLAN §2.3；Q16、Q17）。列表、全选全部、检索范围、覆盖预检、单音指标用同一套。

条件之间取交集：
- 顶栏用途 = 性质（多选取并集）；查找栏 = 文字、主标签表达式、★ 只看星标；从原片页跳来时的临时“原片：…”；
- 范围行（``tags``，保存筛选器存的就是它，只有标签条件）：分面条件（作品 / 类型 / 人物 / 音高 / 其他；同一分面多个值取并集；
  人物同时匹配 ``character:`` 与 ``participants:``，``single`` = 只要单人 → 只匹配 ``character:``）+ 可选的标签表达式；
- 单音 · 音色 / 瞬态的指标条件（检索浮层里，缺失的不命中）；语言（04 §4.9，界面入口等支持第二种语言后再加）。
NOT 的补集只在其他条件筛出的范围里取（都在同一个 WHERE 里）。分面与表达式都按有效标签（``sample_effective_tag``）求值。
"""

from __future__ import annotations

import sqlite3
from typing import Any

from ..domain import tagexpr
from . import text_search
from .errors import CoreError

NATURES = ("speech", "pitched", "unpitched", "unclassified")
FACETS = ("work", "type", "person", "pitch", "other")
_PREFIX = {"work": "work:", "type": "type:", "pitch": "pitch:"}


def parse_expr(expr: str | None, where: str) -> tagexpr.Node | None:
    try:
        return tagexpr.parse(expr)
    except tagexpr.TagExprError as e:
        raise CoreError("tag-expr-invalid", where=where, reason=e.reason, position=e.position) from None


def check_expr(expr: str) -> dict[str, Any]:
    try:
        tagexpr.parse(expr)
    except tagexpr.TagExprError as e:
        return {"ok": False, "position": e.position, "reason": e.reason}
    return {"ok": True}


def facet_tags(facet: str, value: str, single: bool = False) -> list[str]:
    """一个分面值对应的完整标签（“其他”分面的值就是完整标签）。"""
    if facet == "person":
        return [f"character:{value}"] if single else [f"character:{value}", f"participants:{value}"]
    if facet in _PREFIX:
        return [_PREFIX[facet] + value]
    if facet == "other":
        return [value]
    raise CoreError("sample-invalid", reason="not-an-option", field="facet")


def check_tags(tags: Any) -> dict[str, Any]:
    """范围行的标签条件（也是保存筛选器的内容）：``{facets: [{facet, values, single?}], expr?}``。校验并规范化。"""
    if tags is None:
        return {"facets": [], "expr": ""}
    if not isinstance(tags, dict) or set(tags) - {"facets", "expr"}:
        raise CoreError("sample-invalid", reason="not-an-option", field="tags")
    facets = []
    for f in tags.get("facets") or []:
        if not isinstance(f, dict) or f.get("facet") not in FACETS or set(f) - {"facet", "values", "single"}:
            raise CoreError("sample-invalid", reason="not-an-option", field="facet")
        values = f.get("values") or []
        if not isinstance(values, list) or not values or not all(isinstance(v, str) and 0 < len(v) <= 500 for v in values):
            raise CoreError("sample-invalid", reason="not-an-option", field="facet")
        facets.append({"facet": f["facet"], "values": list(dict.fromkeys(values)), "single": bool(f.get("single")) and f["facet"] == "person"})
    expr = tags.get("expr") or ""
    if not isinstance(expr, str):
        raise CoreError("sample-invalid", reason="not-an-option", field="tags")
    parse_expr(expr, "scope")
    return {"facets": facets, "expr": expr}


def where(conn: sqlite3.Connection, f: dict[str, Any] | None, reader: text_search.Reader | None = None) -> tuple[str, list[Any]]:
    """WHERE 子句（别名 s = sample、a = sound_asset、src = source）与参数。"""
    f = f or {}
    clauses, args = ["1=1"], []
    natures = f.get("natures")
    if natures:
        if any(n not in NATURES for n in natures):
            raise CoreError("sample-invalid", reason="not-an-option", field="nature")
        clauses.append(f"s.nature IN ({','.join('?' * len(natures))})")
        args += list(natures)
    if f.get("starred"):
        clauses.append("s.starred = 1")
    langs = f.get("languages")
    if langs:
        clauses.append(f"s.language IN ({','.join('?' * len(langs))})")
        args += list(langs)
    if f.get("sourceId"):
        clauses.append("a.source_id = ?")
        args.append(f["sourceId"])
    text = str(f.get("text") or "").strip()
    if text:
        c, a = _text_clause(conn, reader, text)
        clauses.append(c)
        args += a
    metrics = f.get("metrics")
    if metrics:
        # 单音 · 音色 / 瞬态的即时筛选（10 §10.3）：缺少所选指标的不命中
        from ..algo import acoustic as ac
        from .acoustic import filter_sql

        conds = ac.check_conditions(metrics.get("conditions") or [], str(metrics.get("mode")))
        if conds:
            c, a = filter_sql(conds)
            clauses.append(c)
            args += a
    tags = check_tags(f.get("tags"))
    for fc in tags["facets"]:
        wanted = [t for v in fc["values"] for t in facet_tags(fc["facet"], v, fc["single"])]
        clauses.append(f"s.id IN (SELECT sample_id FROM sample_effective_tag WHERE tag IN ({','.join('?' * len(wanted))}))")
        args += wanted
    for node in (parse_expr(tags["expr"], "scope"), parse_expr(f.get("expr"), "main")):
        if node is not None:
            c, a = tagexpr.to_sql(node)
            clauses.append(c)
            args += a
    return " WHERE " + " AND ".join(clauses), args


def _text_clause(conn: sqlite3.Connection, reader: text_search.Reader | None, text: str) -> tuple[str, list[Any]]:
    """名称、备注子串；或读到的段（与判定区间正长度交叠、未删除）的规范化原文 / 读音子串。"""
    from .edits import SEGMENT_MAX

    parts = ["s.name LIKE ? ESCAPE '\\'", "s.note LIKE ? ESCAPE '\\'"]
    needle = text_search.like_needle(text)
    args: list[Any] = [needle, needle]
    if reader is not None:
        text_search.ensure(conn, reader)
    n, r = text_search.query_parts(conn, reader, text)
    seg_conds, seg_args = [], []
    if n:
        seg_conds.append("x.norm LIKE ? ESCAPE '\\'")
        seg_args.append(text_search.like_needle(n))
    if r:
        seg_conds.append("x.reading LIKE ? ESCAPE '\\'")
        seg_args.append(text_search.like_needle(r))
    if seg_conds:
        parts.append(
            "EXISTS (SELECT 1 FROM text_segment t JOIN segment_search x ON x.segment_id = t.id"
            " WHERE t.source_id = a.source_id AND t.deleted = 0 AND t.start < s.tag_judge_end AND t.\"end\" > s.tag_judge_start"
            f" AND t.start > s.tag_judge_start - {SEGMENT_MAX + 1e-6} AND x.text = t.text AND ({' OR '.join(seg_conds)}))"
        )
        args += seg_args
    return "(" + " OR ".join(parts) + ")", args


# ---------------------------------------------------------------- 分面的值与计数（范围行「＋」）


def facet_values(conn: sqlite3.Connection) -> dict[str, list[dict[str, Any]]]:
    """每个分面现有的值与采样数（按采样计，同一采样多条继承路径只算一次，R8.6）。人物：名字（character: 与 participants: 合并）+ 单人数。"""
    out: dict[str, list[dict[str, Any]]] = {k: [] for k in FACETS}
    for facet, tag, n in conn.execute(
        "SELECT facet, tag, COUNT(DISTINCT sample_id) FROM sample_effective_tag WHERE facet != 'person' GROUP BY facet, tag ORDER BY facet, tag"
    ):
        value = tag if facet == "other" else tag.split(":", 1)[1]
        out.setdefault(facet, []).append({"value": value, "count": n})
    people: dict[str, dict[str, Any]] = {}
    for name, n, single in conn.execute(
        "SELECT substr(tag, instr(tag, ':') + 1) AS name, COUNT(DISTINCT sample_id),"
        " COUNT(DISTINCT CASE WHEN tag LIKE 'character:%' THEN sample_id END)"
        " FROM sample_effective_tag WHERE facet = 'person' GROUP BY name ORDER BY name"
    ):
        people[name] = {"value": name, "count": n, "single": single}
    out["person"] = list(people.values())
    return out


def tag_predicate(f: dict[str, Any] | None) -> Any:
    """范围行的标签条件 + 主表达式，作用在一组标签上（原片音轨模式的音高检索按“查询窗与标注交叠”求值，D1）。没有标签条件 → None。"""
    f = f or {}
    tags = check_tags(f.get("tags"))
    nodes = [n for n in (parse_expr(tags["expr"], "scope"), parse_expr(f.get("expr"), "main")) if n is not None]
    facets = [{t for v in fc["values"] for t in facet_tags(fc["facet"], v, fc["single"])} for fc in tags["facets"]]
    if not nodes and not facets:
        return None

    def pred(have: set[str]) -> bool:
        return all(have & want for want in facets) and all(tagexpr.matches(n, have) for n in nodes)

    return pred
