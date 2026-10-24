"""命令目录（ROADMAP L2）：生成物最新、错误码登记齐全、严格模式能抓住返回值走样。"""

from __future__ import annotations

import ast
import json
from pathlib import Path
from typing import Any, NotRequired, TypedDict

import pytest

from ottosmasher.api import catalog
from ottosmasher.api.registry import CommandSet, extra_keys
from ottosmasher.core.errors import ERRORS, CoreError

ROOT = Path(__file__).resolve().parents[3]
PKG = ROOT / "core" / "ottosmasher"


def test_generated_files_are_current():
    for path, text in catalog.outputs().items():
        assert path.exists(), f"missing {path}; run: .venv/bin/python -m ottosmasher.api.catalog"
        assert path.read_text(encoding="utf-8") == text, f"stale {path.name}; run: .venv/bin/python -m ottosmasher.api.catalog"


def test_catalog_shape():
    cat = catalog.build(catalog.default_commands())
    names = [c["name"] for c in cat["commands"]]
    assert names == sorted(names) and len(names) == len(set(names))
    assert {"core.hello", "samples.list", "edits.apply", "jobs.submit"} <= set(names)
    for c in cat["commands"]:
        assert c["effect"] in ("read", "write", "job", "ui", "app", "dev")
        assert c["summary"] and c["summary"][-1] in ".)"
        assert c["params"]["$ref"].startswith("#/$defs/")
    # 所有引用都能在 $defs 里找到
    text = json.dumps(cat)
    for ref in {r.split('"')[0] for r in text.split('"$ref": "#/$defs/')[1:]}:
        assert ref in cat["$defs"], ref
    assert {e["code"] for e in cat["errors"]} == set(ERRORS)


def test_every_emitted_event_is_registered():
    """源码里 emit("名称", …) 的每个事件都登记在 api/events.py（命令目录的 events 一节，阶段 A）。"""
    import re

    from ottosmasher.api.events import EVENTS

    seen = set()
    for f in PKG.rglob("*.py"):
        text = f.read_text(encoding="utf-8")
        seen |= set(re.findall(r'\bemit\(\s*"([a-zA-Z]+\.[a-zA-Z]+)"', text))
        seen |= set(re.findall(r'\.event\(\s*"([a-zA-Z]+\.[a-zA-Z]+)"', text))
    assert seen and seen <= set(EVENTS), sorted(seen - set(EVENTS))
    cat = catalog.build(catalog.default_commands())
    assert [e["name"] for e in cat["events"]] == sorted(EVENTS)
    dangerous = {c["name"]: c["danger"] for c in cat["commands"] if "danger" in c}
    assert dangerous == {"sources.delete": "always", "samples.delete": "always", "works.rename": "always",
                         "storage.clean": "always", "samples.independ": "conditional"}


def _literal_codes() -> dict[str, set[str]]:
    """源码里出现的错误码 → 用到的参数名：CoreError("码", k=…)、code="码" 传给规则校验、{"code": "码", "args": {…}}。"""
    found: dict[str, set[str]] = {}
    for f in PKG.rglob("*.py"):
        tree = ast.parse(f.read_text(encoding="utf-8"))
        # 编辑标签 {"code", "args"} 不是错误：跳过 "label" 键的值与赋给 label 变量的字典
        labels: set[int] = set()
        for n in ast.walk(tree):
            if isinstance(n, ast.Dict):
                for k, v in zip(n.keys, n.values, strict=True):
                    if isinstance(k, ast.Constant) and k.value == "label":
                        labels.add(id(v))
            if isinstance(n, ast.Assign) and any(isinstance(t, ast.Name) and t.id == "label" for t in n.targets):
                labels.update(id(x) for x in ast.walk(n.value))
        for n in ast.walk(tree):
            if isinstance(n, ast.Call):
                fname = getattr(n.func, "id", getattr(n.func, "attr", None))
                if fname == "CoreError" and n.args and isinstance(n.args[0], ast.Constant):
                    found.setdefault(n.args[0].value, set()).update(k.arg for k in n.keywords if k.arg)
                for k in n.keywords:
                    if k.arg == "code" and isinstance(k.value, ast.Constant) and isinstance(k.value.value, str):
                        found.setdefault(k.value.value, set())
            if isinstance(n, ast.Dict) and id(n) not in labels:
                keys = [k.value for k in n.keys if isinstance(k, ast.Constant)]
                if "code" in keys and "args" in keys:
                    v = n.values[keys.index("code")]
                    a = n.values[keys.index("args")]
                    if isinstance(v, ast.Constant):
                        names = {k.value for k in a.keys if isinstance(k, ast.Constant)} if isinstance(a, ast.Dict) else set()
                        found.setdefault(v.value, set()).update(names)
    return found


def test_every_error_code_is_registered_with_its_args():
    problems = []
    for code, args in sorted(_literal_codes().items()):
        if code not in ERRORS:
            problems.append(f"unregistered: {code}")
            continue
        extra = args - set(ERRORS[code][0])
        if extra:
            problems.append(f"{code}: unregistered args {sorted(extra)}")
    assert not problems, problems


def test_every_error_code_has_a_message():
    zh = json.loads((ROOT / "app" / "renderer" / "i18n" / "locales" / "zh-CN.json").read_text(encoding="utf-8"))
    missing = [c for c in ERRORS if f"error.{c}" not in zh]
    assert not missing, missing


# ---------------------------------------------------------------- 分发与严格模式


class _P(TypedDict):
    id: str
    n: NotRequired[float | None]


class _Item(TypedDict):
    a: int


class _R(TypedDict):
    ok: bool
    items: list[_Item]
    maybe: _Item | None


def _set(handler) -> CommandSet:
    cs = CommandSet()
    cs.add("t.cmd", "read", _P, _R, "Test.", handler)
    return cs


def test_params_are_validated_and_coerced():
    cmd = _set(lambda p: p).get("t.cmd")
    assert cmd.parse({"id": "x", "n": 2}) == {"id": "x", "n": 2.0}
    assert cmd.parse({"id": "x", "n": None}) == {"id": "x", "n": None}
    with pytest.raises(CoreError) as e:
        cmd.parse({"n": 1})
    assert e.value.code == "bad-request" and e.value.args_["method"] == "t.cmd"
    with pytest.raises(CoreError):
        cmd.parse({"id": 3})


def test_strict_result_check_catches_wrong_types_and_undeclared_keys():
    cmd = _set(lambda p: p).get("t.cmd")
    cmd.check_result({"ok": True, "items": [{"a": 1}], "maybe": None})
    for bad in (
        {"ok": True, "items": [{"a": "1"}], "maybe": None},
        {"ok": True, "items": [], "maybe": None, "extra": 1},
        {"ok": True, "items": [{"a": 1, "b": 2}], "maybe": None},
        {"ok": True, "items": [], "maybe": {"a": 1, "z": 0}},
        {"ok": True, "items": []},
    ):
        with pytest.raises(CoreError) as e:
            cmd.check_result(bad)
        assert e.value.code == "result-mismatch"


def test_extra_keys_walks_dicts_and_lists():
    tp: Any = dict[str, list[_Item]]
    assert extra_keys({"k": [{"a": 1}, {"a": 2, "q": 3}]}, tp) == ["$.k[1].q"]


def test_registry_rejects_bad_definitions():
    cs = CommandSet()
    cs.add("a.b", "read", _P, None, "X.", lambda p: None)
    with pytest.raises(ValueError):
        cs.add("a.b", "read", _P, None, "X.", lambda p: None)
    with pytest.raises(ValueError):
        cs.add("a.c", "delete", _P, None, "X.", lambda p: None)
    with pytest.raises(TypeError):
        cs.add("a.d", "read", dict, None, "X.", lambda p: None)
