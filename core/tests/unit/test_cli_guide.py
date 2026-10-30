"""agent 说明书（阶段 A）：中英两份逐节对应；提到的命令都存在；能直接运行的示例参数符合命令定义。"""

from __future__ import annotations

import json
import re

import pytest

from ottosmasher.api import catalog
from ottosmasher.api.registry import extra_keys
from ottosmasher.cli.main import GUIDE, main
from ottosmasher.core.settings import SPECS

CMD_RE = re.compile(r"`([a-z]+\.[a-zA-Z0-9]+)")
CALL_RE = re.compile(r"otto call ([a-z]+\.[a-zA-Z]+) '(\{.*?\})'")


def _files(lang):
    return sorted((GUIDE / lang).glob("*.md")) + [GUIDE / "notes" / f"{lang}.md"]  # 经验层同样核对


def test_both_languages_have_the_same_topics_and_shape():
    en, zh = _files("en"), _files("zh-CN")
    assert [p.name for p in en if p.parent.name != "notes"] == [p.name for p in zh if p.parent.name != "notes"] and len(en) >= 8
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
            if name.split(".")[0] in ("video", "binding", "error", "result", "c"):  # 结果里的字段（video.path、result.path……）与脚本里的 c.call，不是命令
                continue
            if any(k == name or k.startswith(name + "_") for k in SPECS):  # 设置项（jobs.concurrency_model 之类），不是命令
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
    assert main(["guide", "notes", "--lang", lang]) == 0
    assert "edits.apply" in capsys.readouterr().out
    assert main(["guide", "--all", "--lang", lang]) == 0
    assert "primitives" in capsys.readouterr().out
    assert main(["guide", "nope", "--lang", lang]) == 2


def test_hosted_skill_is_an_entry_point():
    """仓库托管的 skill（所有者 2026-10-30）：只是入口——怎么找到 otto、先看 otto guide；提到的命令都存在、不抄说明书正文。"""
    import yaml

    f = GUIDE.parents[3] / "skills" / "ottosmasher" / "SKILL.md"
    text = f.read_text(encoding="utf-8")
    head = yaml.safe_load(text.split("---\n")[1])
    assert head["name"] == "ottosmasher" and "otto" in head["description"]
    for cmd in ("otto status", "otto guide", "otto guide playbook", "otto guide notes"):
        assert cmd in text
    assert len(text) < 3000  # 入口，不是说明书
    api = catalog.default_commands()
    assert all(n in api for n in CMD_RE.findall(text) if n.split(".")[0] not in ("c",))


def test_playbook_template_and_setup(tmp_path, capsys, monkeypatch):
    monkeypatch.setenv("OTTO_WORKSPACE", str(tmp_path))
    assert main(["guide", "playbook", "--lang", "en"]) == 0
    assert "does not exist yet" in capsys.readouterr().out
    assert main(["setup", "playbook", "--lang", "en"]) == 0
    assert json.loads(capsys.readouterr().out)["created"] is True
    f = tmp_path / "Agent" / "playbook.md"
    f.write_text("# mine\nalways separate whole episodes\n", encoding="utf-8")
    assert main(["guide", "playbook"]) == 0
    assert "always separate whole episodes" in capsys.readouterr().out
    assert main(["setup", "playbook"]) == 0 and json.loads(capsys.readouterr().out)["created"] is False  # 不覆盖


def test_setup_audio_prints_only(capsys):
    assert main(["setup", "audio", "--for", "claude-code"]) == 0
    assert "claude mcp add audio" in json.loads(capsys.readouterr().out)["run"]
    assert main(["setup", "audio", "--for", "codex"]) == 0
    assert "[mcp_servers.audio]" in json.loads(capsys.readouterr().out)["append"]
