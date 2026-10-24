"""agent 说明书（阶段 A）：中英两份逐节对应；提到的命令都存在；能直接运行的示例参数符合命令定义。"""

from __future__ import annotations

import json
import re

import pytest

from ottosmasher.api import catalog
from ottosmasher.api.registry import extra_keys
from ottosmasher.cli.main import GUIDE, main

CMD_RE = re.compile(r"`([a-z]+\.[a-zA-Z]+)")
CALL_RE = re.compile(r"otto call ([a-z]+\.[a-zA-Z]+) '(\{.*?\})'")


def _files(lang):
    return sorted((GUIDE / lang).glob("*.md"))


def test_both_languages_have_the_same_topics_and_shape():
    en, zh = _files("en"), _files("zh-CN")
    assert [p.name for p in en] == [p.name for p in zh] and len(en) >= 8
    for a, b in zip(en, zh, strict=True):
        ta, tb = a.read_text(encoding="utf-8"), b.read_text(encoding="utf-8")
        assert [ln.split(" ")[0] for ln in ta.splitlines() if ln.startswith("#")] == [ln.split(" ")[0] for ln in tb.splitlines() if ln.startswith("#")], a.name
        assert ta.count("```") == tb.count("```"), a.name
        assert set(CMD_RE.findall(ta)) == set(CMD_RE.findall(tb)), a.name
        assert [m[0] for m in CALL_RE.findall(ta)] == [m[0] for m in CALL_RE.findall(tb)], a.name


def test_named_commands_exist_and_examples_fit():
    api = catalog.default_commands()
    events = {e["name"] for e in catalog.build(api)["events"]}
    checked = 0
    for p in _files("en") + _files("zh-CN"):
        text = p.read_text(encoding="utf-8")
        for name in CMD_RE.findall(text):
            if name.split(".")[0] in ("video", "binding", "error"):  # 结果里的字段（video.path、binding.path），不是命令
                continue
            assert name in api or name in events, f"{p.name}: {name}"
        for name, raw in CALL_RE.findall(text):
            try:
                params = json.loads(raw)
            except ValueError:
                continue  # 带占位符的示例
            cmd = api.get(name)
            cmd.parse(params)
            assert not extra_keys(params, cmd.params), f"{p.name}: {name} {raw}"
            checked += 1
    assert checked >= 10


@pytest.mark.parametrize("lang", ["en", "zh-CN"])
def test_guide_command_prints_topics(lang, capsys):
    assert main(["guide", "--lang", lang]) == 0
    assert "undo" in capsys.readouterr().out
    assert main(["guide", "undo", "--lang", lang]) == 0
    assert "edits.undoSession" in capsys.readouterr().out
    assert main(["guide", "--skill", "--lang", lang]) == 0
    out = capsys.readouterr().out
    assert out.startswith("---\nname: ottosmasher\n") and "samples.createPlanned" in out
    assert main(["guide", "nope", "--lang", lang]) == 2
