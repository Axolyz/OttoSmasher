"""标签表达式（规格 07 §7.2、16 R8.1、R8.2、R8.8）。纯函数：解析、Python 求值（完整计算的口径）、编译成 SQL。

- 语法：``NOT`` ``AND`` ``OR``（不区分大小写）、括号、双引号。优先级 NOT > AND > OR，左结合；**没有隐式 AND**（``a b`` 报错）。
- 标签名按完整名称匹配，区分大小写；带空格或与关键字同名的用双引号（引号内按 JSON 字符串规则转义）。
- 前缀通配：以 ``:*`` 结尾的词项匹配该命名空间下的任何标签（``participants:*``、``"pitch:*"``）；其他位置的 ``*`` 按字面。
- 空表达式 = 匹配全部（``parse`` 返回 None）。上限：≤ 8192 字符、≤ 256 个词项。
- 报错指出位置：``position`` 是第几个字符（从 1 起；在末尾 = 长度 + 1）。

SQL 口径：每个词项 = “这个采样的有效标签里有它”（``sample_effective_tag``），NOT 的补集由调用方 WHERE 里的其他条件限定在当前范围内。
"""

from __future__ import annotations

import json
from collections.abc import Iterable
from dataclasses import dataclass

MAX_CHARS = 8192
MAX_TERMS = 256
KEYWORDS = ("NOT", "AND", "OR")


class TagExprError(ValueError):
    def __init__(self, reason: str, position: int) -> None:
        super().__init__(f"{reason} at {position}")
        self.reason = reason
        self.position = position


@dataclass(frozen=True)
class Term:
    tag: str
    prefix: bool = False  # True：tag 是“命名空间:”，匹配以它开头的任何标签


@dataclass(frozen=True)
class Not:
    x: Node


@dataclass(frozen=True)
class And:
    a: Node
    b: Node


@dataclass(frozen=True)
class Or:
    a: Node
    b: Node


Node = Term | Not | And | Or


@dataclass(frozen=True)
class _Tok:
    kind: str  # term / NOT / AND / OR / ( / )
    pos: int  # 从 1 起
    value: str = ""
    quoted: bool = False


def _tokens(s: str) -> list[_Tok]:
    out: list[_Tok] = []
    i, n = 0, len(s)
    while i < n:
        ch = s[i]
        if ch.isspace():
            i += 1
            continue
        if ch in "()":
            out.append(_Tok(ch, i + 1))
            i += 1
            continue
        if ch == '"':
            j = i + 1
            while j < n and s[j] != '"':
                j += 2 if s[j] == "\\" else 1
            if j >= n:
                raise TagExprError("unclosed-quote", i + 1)
            try:
                value = json.loads(s[i : j + 1])
            except ValueError:
                raise TagExprError("bad-escape", i + 1) from None
            if value == "":
                raise TagExprError("empty-tag", i + 1)
            out.append(_Tok("term", i + 1, value, quoted=True))
            i = j + 1
            continue
        j = i
        while j < n and not s[j].isspace() and s[j] not in '()"':
            j += 1
        word = s[i:j]
        up = word.upper()
        out.append(_Tok(up, i + 1) if up in KEYWORDS else _Tok("term", i + 1, word))
        i = j
    return out


def _term(tok: _Tok) -> Term:
    v = tok.value
    if v.endswith(":*") and len(v) > 2:
        return Term(v[:-1], prefix=True)
    return Term(v)


class _Parser:
    def __init__(self, toks: list[_Tok], end: int) -> None:
        self.toks = toks
        self.i = 0
        self.end = end

    def peek(self) -> _Tok | None:
        return self.toks[self.i] if self.i < len(self.toks) else None

    def here(self) -> int:
        t = self.peek()
        return t.pos if t else self.end

    def or_(self) -> Node:
        x = self.and_()
        while (t := self.peek()) and t.kind == "OR":
            self.i += 1
            x = Or(x, self.and_())
        return x

    def and_(self) -> Node:
        x = self.not_()
        while (t := self.peek()) and t.kind == "AND":
            self.i += 1
            x = And(x, self.not_())
        return x

    def not_(self) -> Node:
        t = self.peek()
        if t and t.kind == "NOT":
            self.i += 1
            return Not(self.not_())
        return self.primary()

    def primary(self) -> Node:
        t = self.peek()
        if t is None:
            raise TagExprError("expect-term", self.end)
        if t.kind == "term":
            self.i += 1
            return _term(t)
        if t.kind == "(":
            self.i += 1
            if (u := self.peek()) and u.kind == ")":
                raise TagExprError("empty-group", u.pos)
            x = self.or_()
            u = self.peek()
            if u is None or u.kind != ")":
                raise TagExprError("unclosed-group" if u is None else ("expect-operator" if u.kind in ("term", "(", "NOT") else "expect-term"), self.here())
            self.i += 1
            return x
        if t.kind == ")":
            raise TagExprError("expect-term", t.pos)
        raise TagExprError("expect-term", t.pos)  # AND / OR 出现在该有词项的地方


def parse(expr: str | None) -> Node | None:
    """解析；空表达式返回 None（匹配全部）。出错抛 ``TagExprError``（原因 + 第几个字符）。"""
    s = expr or ""
    if len(s) > MAX_CHARS:
        raise TagExprError("expr-too-long", MAX_CHARS + 1)
    toks = _tokens(s)
    if not toks:
        return None
    terms = [t for t in toks if t.kind == "term"]
    if len(terms) > MAX_TERMS:
        raise TagExprError("too-many-terms", terms[MAX_TERMS].pos)
    p = _Parser(toks, len(s) + 1)
    x = p.or_()
    t = p.peek()
    if t is not None:
        # 一个完整的表达式之后还有东西：词项 / 左括号 / NOT = 少了 AND 或 OR；右括号 = 多余
        raise TagExprError("unexpected-close" if t.kind == ")" else "expect-operator", t.pos)
    return x


def terms(node: Node | None) -> list[Term]:
    if node is None:
        return []
    if isinstance(node, Term):
        return [node]
    if isinstance(node, Not):
        return terms(node.x)
    return terms(node.a) + terms(node.b)


def matches(node: Node | None, tags: Iterable[str]) -> bool:
    """完整计算的口径：对一个采样的全部有效标签求值。"""
    if node is None:
        return True
    have = tags if isinstance(tags, (set, frozenset)) else set(tags)
    return _eval(node, have)


def _eval(node: Node, have: set[str] | frozenset[str]) -> bool:
    if isinstance(node, Term):
        if node.prefix:
            return any(t.startswith(node.tag) for t in have)
        return node.tag in have
    if isinstance(node, Not):
        return not _eval(node.x, have)
    if isinstance(node, And):
        return _eval(node.a, have) and _eval(node.b, have)
    return _eval(node.a, have) or _eval(node.b, have)


def prefix_upper(prefix: str) -> str:
    """``tag >= prefix AND tag < upper`` 的上界（最后一个字符加一）。"""
    return prefix[:-1] + chr(ord(prefix[-1]) + 1)


def to_sql(node: Node | None, id_col: str = "s.id") -> tuple[str, list[str]]:
    """编译成 SQL 布尔表达式（参数化）。每个词项 = ``id_col IN (该标签的采样)``，走 ``sample_effective_tag(tag)`` 索引。"""
    if node is None:
        return "1=1", []
    args: list[str] = []

    def go(x: Node) -> str:
        if isinstance(x, Term):
            if x.prefix:
                args.extend([x.tag, prefix_upper(x.tag)])
                return f"{id_col} IN (SELECT sample_id FROM sample_effective_tag WHERE tag >= ? AND tag < ?)"
            args.append(x.tag)
            return f"{id_col} IN (SELECT sample_id FROM sample_effective_tag WHERE tag = ?)"
        if isinstance(x, Not):
            return f"NOT ({go(x.x)})"
        op = "AND" if isinstance(x, And) else "OR"
        return f"({go(x.a)} {op} {go(x.b)})"

    return go(node), args
