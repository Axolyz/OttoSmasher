"""标签表达式（规格 07 §7.2、16 R8.1、R8.2 前缀通配、R8.8 SQL 与完整计算一致）。"""

from __future__ import annotations

import random
import sqlite3

import pytest

from ottosmasher.domain import tagexpr as tx


def m(expr: str, tags: list[str]) -> bool:
    return tx.matches(tx.parse(expr), tags)


def test_examples_from_spec() -> None:
    e = '(character:京子 OR character:結衣) AND NOT "speaker-status:多人未分段"'
    assert m(e, ["character:京子"])
    assert not m(e, ["character:京子", "speaker-status:多人未分段"])
    assert not m(e, ["character:京子2"])  # 完整名称匹配
    assert m("a or b and not c", ["a", "c"])  # NOT > AND > OR
    assert not m("a and b or c and d", ["a", "d"])
    assert m("a and b or c and d", ["c", "d"])
    assert m("", ["x"]) and tx.parse("   ") is None  # 空表达式 = 全部
    assert not m("A", ["a"])  # 区分大小写
    assert m('"AND"', ["AND"]) and m('"a b"', ["a b"]) and m('"q\\"x"', ['q"x'])  # 引号内 JSON 转义
    assert m("NOT NOT a", ["a"])


def test_prefix_wildcard() -> None:
    e = "character:京子 AND NOT participants:*"
    assert m(e, ["character:京子"])
    assert not m(e, ["character:京子", "participants:結衣"])
    assert m('"pitch:*"', ["pitch:G#5"]) and not m("pitch:*", ["pitches:x"])
    assert m("a*b", ["a*b"]) and not m("a*b", ["axb"])  # 其他位置的 * 按字面
    assert m("x:*", ["x:"])  # 命名空间下的空值也算


@pytest.mark.parametrize(
    ("expr", "reason", "pos"),
    [
        ("a b", "expect-operator", 3),
        ("(a OR)", "expect-term", 6),
        ("a AND", "expect-term", 6),
        ('"unclosed', "unclosed-quote", 1),
        ("()", "empty-group", 2),
        ("a)", "unexpected-close", 2),
        ('""', "empty-tag", 1),
        ("(a", "unclosed-group", 3),
        ("AND a", "expect-term", 1),
        ("a (b)", "expect-operator", 3),
        ('"\\x"', "bad-escape", 1),
    ],
)
def test_errors_report_position(expr: str, reason: str, pos: int) -> None:
    with pytest.raises(tx.TagExprError) as ei:
        tx.parse(expr)
    assert (ei.value.reason, ei.value.position) == (reason, pos)


def test_limits() -> None:
    tx.parse(" OR ".join(f"t{i}" for i in range(256)))
    with pytest.raises(tx.TagExprError) as ei:
        tx.parse(" OR ".join(f"t{i}" for i in range(257)))
    assert ei.value.reason == "too-many-terms"
    with pytest.raises(tx.TagExprError) as ei:
        tx.parse("a" * 8193)
    assert ei.value.reason == "expr-too-long"


def _random_expr(rng: random.Random, tags: list[str], depth: int = 0) -> str:
    r = rng.random()
    if depth > 3 or r < 0.35:
        t = rng.choice(tags)
        return f'"{t}"' if rng.random() < 0.3 and not t.startswith('"') else t
    if r < 0.5:
        return "NOT " + _random_expr(rng, tags, depth + 1)
    op = rng.choice(["AND", "OR", "and", "or"])
    inner = f"{_random_expr(rng, tags, depth + 1)} {op} {_random_expr(rng, tags, depth + 1)}"
    return f"({inner})" if rng.random() < 0.6 else inner


def test_sql_equals_full_computation() -> None:
    """R8.8：SQL（只按词项取采样）的结果恒等于对完整有效标签集合求值。"""
    rng = random.Random(7)
    vocab = ["character:京子", "character:結衣", "participants:京子", "speaker-status:多人未分段", "work:Yuru", "pitch:A4", "好用", "ab"]
    conn = sqlite3.connect(":memory:")
    conn.execute("CREATE TABLE sample (id TEXT PRIMARY KEY)")
    conn.execute("CREATE TABLE sample_effective_tag (sample_id TEXT, tag TEXT)")
    conn.execute("CREATE INDEX t ON sample_effective_tag(tag)")
    sets: dict[str, set[str]] = {}
    for i in range(200):
        sid = f"s{i}"
        sets[sid] = {t for t in vocab if rng.random() < 0.3}
        conn.execute("INSERT INTO sample VALUES (?)", (sid,))
        conn.executemany("INSERT INTO sample_effective_tag VALUES (?, ?)", [(sid, t) for t in sets[sid]])
    pats = [*vocab, "character:*", "participants:*", '"pitch:*"', "work:*"]
    for _ in range(300):
        e = _random_expr(rng, pats)
        node = tx.parse(e)
        clause, args = tx.to_sql(node)
        got = {r[0] for r in conn.execute(f"SELECT s.id FROM sample s WHERE {clause}", args)}
        want = {sid for sid, tags in sets.items() if tx.matches(node, tags)}
        assert got == want, e
