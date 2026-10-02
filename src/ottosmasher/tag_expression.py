"""Small, bounded boolean grammar over complete tag names. Never eval/SQL."""

from __future__ import annotations

import json
from dataclasses import dataclass


class SyntaxError(ValueError):
    def __init__(self, message, position):
        self.position = position
        super().__init__(f"第 {position + 1} 字符：{message}")


@dataclass(frozen=True)
class Expression:
    node: tuple

    def tag_names(self):
        def visit(node):
            if node[0] == "tag":
                return {node[1]}
            return set().union(*(visit(child) for child in node[1:] if isinstance(child, tuple)))

        return visit(self.node)

    def matches(self, tags):
        if self.node[0] == "all":
            return True
        tags = tags if isinstance(tags, (set, frozenset)) else set(tags)

        def visit(n):
            op = n[0]
            if op == "tag":
                return n[1] in tags
            if op == "all":
                return True
            if op == "NOT":
                return not visit(n[1])
            if op == "AND":
                return visit(n[1]) and visit(n[2])
            return visit(n[1]) or visit(n[2])

        return visit(self.node)


def parse(text):
    if not isinstance(text, str):
        raise ValueError("标签表达式必须是文本")  # noqa: TRY004 - user input validation
    if len(text) > 8192:
        raise SyntaxError("表达式最多 8192 字符", 8192)
    tokens = []
    i = 0
    while i < len(text):
        if text[i].isspace():
            i += 1
            continue
        at = i
        c = text[i]
        if c in "()":
            tokens.append((c, c, i))
            i += 1
            continue
        if c == '"':
            try:
                value, count = json.JSONDecoder().raw_decode(text[i:])
            except json.JSONDecodeError as e:
                raise SyntaxError("引号或转义未闭合", i + e.pos) from e
            if not value:
                raise SyntaxError("标签名不能为空", at)
            tokens.append(("tag", value, at))
            i += count
        else:
            while i < len(text) and not text[i].isspace() and text[i] not in '()"':
                i += 1
            word = text[at:i]
            tokens.append((word.upper() if word.upper() in {"NOT", "AND", "OR"} else "tag", word, at))
        if len(tokens) > 256:
            raise SyntaxError("表达式最多 256 个词项", at)
    tokens.append(("end", "", len(text)))
    cursor = 0

    def take(kind):
        nonlocal cursor
        if tokens[cursor][0] == kind:
            token = tokens[cursor]
            cursor += 1
            return token
        return None

    def atom():
        if take("NOT"):
            return ("NOT", atom())
        if take("("):
            node = disjunction()
            if not take(")"):
                raise SyntaxError("缺少右括号", tokens[cursor][2])
            return node
        word = take("tag")
        if word:
            return ("tag", word[1])
        raise SyntaxError("需要标签、NOT 或左括号", tokens[cursor][2])

    def conjunction():
        node = atom()
        while take("AND"):
            node = ("AND", node, atom())
        return node

    def disjunction():
        node = conjunction()
        while take("OR"):
            node = ("OR", node, conjunction())
        return node

    if tokens[0][0] == "end":
        return Expression(("all",))
    node = disjunction()
    if tokens[cursor][0] != "end":
        raise SyntaxError("需要 AND 或 OR", tokens[cursor][2])
    return Expression(node)


def from_tags(tags):
    return " AND ".join(json.dumps(tag, ensure_ascii=False) for tag in tags)
