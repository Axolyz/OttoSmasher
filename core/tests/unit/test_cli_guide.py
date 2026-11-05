"""agent 说明：说明书（只有英文，随版本）提到的命令都存在、示例参数合法；skill（中英各一份）符合 Agent Skills 规范、同步到工作区时不覆盖用户的修改。"""

from __future__ import annotations

import json
import re

import pytest
import yaml

from ottosmasher.api import catalog
from ottosmasher.api.registry import extra_keys
from ottosmasher.cli import skills
from ottosmasher.cli.main import GUIDE, main
from ottosmasher.core.settings import SPECS

CMD_RE = re.compile(r"`([a-z]+\.[a-zA-Z0-9]+)")
CALL_RE = re.compile(r"otto call ([a-z]+\.[a-zA-Z]+) '(\{.*?\})'")
LANGS = ("en", "zh-CN")
SKILLS = GUIDE / "skills"


def _skill_docs(lang):
    return sorted((SKILLS / lang).rglob("*.md"))


def _reference():
    return sorted((GUIDE / "reference").glob("*.md"))


def _front(text):
    return yaml.safe_load(text.split("---\n")[1])


def test_reference_is_english_with_no_owner_wording():
    assert len(_reference()) >= 8
    for p in _reference():
        text = p.read_text(encoding="utf-8")
        assert not re.search(r"\bowner\b", text, re.I), p.name
        assert not re.search(r"\brule \d", text), p.name  # 引用小节名，不引用序号


def test_named_commands_exist_and_examples_fit():
    api = catalog.default_commands()
    events = {e["name"] for e in catalog.build(api)["events"]}
    checked = 0
    for p in _reference() + _skill_docs("en") + _skill_docs("zh-CN"):
        text = p.read_text(encoding="utf-8")
        for name in CMD_RE.findall(text):
            if name.split(".")[0] in skills.NOT_COMMANDS:
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
    assert checked >= 5


def test_skills_follow_the_spec_and_match_between_languages():
    """Agent Skills 规范：name 与文件夹同名、小写加连字符；description 写清做什么、何时用；SKILL.md 不超过 500 行。中英两份逐节对应、命令相同。"""
    rel = {lang: sorted(p.relative_to(SKILLS / lang).as_posix() for p in _skill_docs(lang)) for lang in LANGS}
    assert rel["en"] == rel["zh-CN"] and rel["en"]
    for lang in LANGS:
        for f in (SKILLS / lang).glob("*/SKILL.md"):
            text = f.read_text(encoding="utf-8")
            head = _front(text)
            assert head["name"] == f.parent.name and re.fullmatch(r"[a-z0-9]+(-[a-z0-9]+)*", head["name"]), f
            assert 0 < len(head["description"]) <= 1024 and len(text.splitlines()) < 500, f
            assert not re.search(r"\bowner\b|所有者", text), f
    for name in rel["en"]:
        a, b = (SKILLS / "en" / name).read_text(encoding="utf-8"), (SKILLS / "zh-CN" / name).read_text(encoding="utf-8")
        assert [ln.split(" ")[0] for ln in a.splitlines() if ln.startswith("#")] == [ln.split(" ")[0] for ln in b.splitlines() if ln.startswith("#")], name
        assert a.count("```") == b.count("```"), name
        assert set(CMD_RE.findall(a)) == set(CMD_RE.findall(b)), name


def test_guide_command_prints_reference_and_skills(tmp_path, capsys, monkeypatch):
    monkeypatch.setenv("OTTO_WORKSPACE", str(tmp_path))
    assert main(["guide", "--lang", "zh-CN"]) == 0
    text = capsys.readouterr().out
    assert "Ground rules" in text and "cleaning-subtitles" in text and str(tmp_path / "Agent" / "skills") in text
    assert "把字幕文件整理成" in text  # skill 的说明用工作区的语言
    assert main(["guide", "undo"]) == 0
    assert "edits.undoSession" in capsys.readouterr().out
    assert main(["guide", "--all"]) == 0
    assert "primitives" in capsys.readouterr().out
    assert main(["guide", "retiming-lines"]) == 0
    assert "edits.apply" in capsys.readouterr().out
    assert main(["guide", "notes"]) == 0  # 旧名字：已经装好的入口 skill 还可能这么叫
    assert "grouping-speakers" in capsys.readouterr().out
    assert main(["guide", "nope"]) == 2


def test_skills_sync_never_overwrites_user_edits(tmp_path, monkeypatch):
    """按 dpkg 处理配置文件的办法：没改过的更新，改过的不动并在旁边放 .new，处理过的同一版本不再提示，删掉的不补回来。"""
    bundled = tmp_path / "bundled"
    (bundled / "common" / "a" / "scripts").mkdir(parents=True)
    (bundled / "en" / "a").mkdir(parents=True)
    (bundled / "en" / "b").mkdir(parents=True)
    (bundled / "zh-CN" / "a").mkdir(parents=True)
    (bundled / "common" / "a" / "scripts" / "s.py").write_text("v1", encoding="utf-8")
    (bundled / "en" / "a" / "SKILL.md").write_text('---\nname: a\ndescription: "does a"\n---\nv1\n', encoding="utf-8")
    (bundled / "en" / "b" / "SKILL.md").write_text("---\nname: b\n---\nv1\n", encoding="utf-8")
    (bundled / "zh-CN" / "a" / "SKILL.md").write_text("zh", encoding="utf-8")
    monkeypatch.setattr(skills, "BUNDLED", bundled)
    ws = tmp_path / "ws"
    d = skills.skills_dir(ws)

    first = skills.sync(ws, "en")
    assert sorted(first["installed"]) == ["a/SKILL.md", "a/scripts/s.py", "b/SKILL.md"] and first["lang"] == "en"
    assert [(r["name"], r["description"], r["builtin"]) for r in skills.listing(ws)] == [("a", "does a", True), ("b", "", True)]
    # 重复运行没有变化；语言在第一次定下，之后不变
    assert skills.sync(ws, "zh-CN") == {"path": str(d), "lang": "en", "installed": [], "updated": [], "conflicts": []}

    # 用户改了 a，删了 b；内置都出了新版本
    (d / "a" / "SKILL.md").write_text("mine", encoding="utf-8")
    (d / "b" / "SKILL.md").unlink()
    (bundled / "en" / "a" / "SKILL.md").write_text("v2", encoding="utf-8")
    (bundled / "en" / "b" / "SKILL.md").write_text("v2", encoding="utf-8")
    (bundled / "common" / "a" / "scripts" / "s.py").write_text("v2", encoding="utf-8")
    r = skills.sync(ws, "en")
    assert r["updated"] == ["a/scripts/s.py"] and r["conflicts"] == ["a/SKILL.md"]
    assert (d / "a" / "SKILL.md").read_text(encoding="utf-8") == "mine"
    assert (d / "a" / "SKILL.md.new").read_text(encoding="utf-8") == "v2"
    assert (d / "a" / "scripts" / "s.py").read_text(encoding="utf-8") == "v2"
    assert not (d / "b" / "SKILL.md").exists()
    assert skills.listing(ws)[0]["update"] == ["a/SKILL.md"]

    # 用户处理完删掉 .new：同一版本不再提示；再出新版本才提示
    (d / "a" / "SKILL.md.new").unlink()
    assert skills.sync(ws, "en")["conflicts"] == [] and not (d / "a" / "SKILL.md.new").exists()
    (bundled / "en" / "a" / "SKILL.md").write_text("v3", encoding="utf-8")
    assert skills.sync(ws, "en")["conflicts"] == ["a/SKILL.md"]
    # 用户的内容和新版本一样了：算合并完
    (d / "a" / "SKILL.md").write_text("v3", encoding="utf-8")
    assert skills.sync(ws, "en")["conflicts"] == [] and not (d / "a" / "SKILL.md.new").exists()

    # 内置版本不再有的文件：没改过的删掉，改过的留下
    (d / "a" / "scripts" / "mine.py").write_text("x", encoding="utf-8")
    (bundled / "common" / "a" / "scripts" / "s.py").unlink()
    skills.sync(ws, "en")
    assert not (d / "a" / "scripts" / "s.py").exists() and (d / "a" / "scripts" / "mine.py").exists()

    # 用户自己加的 skill 也列出来；已有同名文件时不覆盖
    (d / "own").mkdir()
    (d / "own" / "SKILL.md").write_text('---\nname: own\ndescription: mine\n---\n', encoding="utf-8")
    assert [r["builtin"] for r in skills.listing(ws) if r["name"] == "own"] == [False]


def test_setup_skills_reports_commands_the_app_no_longer_has(tmp_path, capsys, monkeypatch):
    monkeypatch.setenv("OTTO_WORKSPACE", str(tmp_path))
    assert main(["setup", "skills", "--lang", "en"]) == 0
    r = json.loads(capsys.readouterr().out)
    assert r["unknownCommands"] == [] and {"cleaning-subtitles", "grouping-speakers"} <= {s["name"] for s in r["skills"]}
    f = skills.skills_dir(tmp_path) / "retiming-lines" / "SKILL.md"
    f.write_text(f.read_text(encoding="utf-8") + "\nUse `samples.gone` here.\n", encoding="utf-8")
    assert main(["setup", "skills"]) == 0
    assert json.loads(capsys.readouterr().out)["unknownCommands"] == [{"file": "retiming-lines/SKILL.md", "command": "samples.gone"}]


def test_hosted_skill_is_an_entry_point():
    """仓库托管的 skill（所有者 2026-10-30）：只是入口——怎么找到 otto、先看 otto guide；提到的命令都存在、不抄说明书正文。"""
    f = GUIDE.parents[3] / "skills" / "ottosmasher" / "SKILL.md"
    text = f.read_text(encoding="utf-8")
    head = _front(text)
    assert head["name"] == "ottosmasher" and "otto" in head["description"]
    for cmd in ("otto status", "otto open", "otto guide", "otto guide playbook", "/Applications/OttoSmasher.app"):
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


def test_speaker_embed_script(tmp_path):
    """grouping-speakers 附带的脚本：不需要模型的部分（时间换算、补零）在这里测。"""
    import importlib.util

    import numpy as np

    script = SKILLS / "common" / "grouping-speakers" / "scripts" / "speaker_embed.py"
    assert script.read_text(encoding="utf-8").startswith("# /// script")  # uv 认得的内联依赖
    for lang in LANGS:
        assert "scripts/speaker_embed.py" in (SKILLS / lang / "grouping-speakers" / "SKILL.md").read_text(encoding="utf-8")
    spec = importlib.util.spec_from_file_location("speaker_embed", script)
    se = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(se)  # 模型与 torch 只在 main 里导入
    # exports.wav 的 mapping（文件秒 → 原片秒）反过来用：原片秒 → 文件秒
    f = se.source_to_file([[0.0, 100.0], [10.0, 110.0], [20.0, 130.0]])
    assert f(105.0) == 5.0 and f(120.0) == 15.0 and f(130.0) == 20.0
    with pytest.raises(SystemExit):
        f(99.0)
    (tmp_path / "r.json").write_text(json.dumps([{"id": "a", "start": 101.0, "end": 102.5}]), encoding="utf-8")
    (tmp_path / "m.json").write_text(json.dumps({"path": "x.wav", "mapping": [[0.0, 100.0], [10.0, 110.0]]}), encoding="utf-8")
    assert se.load_ranges(str(tmp_path / "r.json"), str(tmp_path / "m.json")) == [{"id": "a", "start": 1.0, "end": 2.5}]
    w = np.ones(16000, np.float32)
    assert len(se.cut(w, 0.5, 0.51)) == 1600 and len(se.cut(w, 0.0, 0.5)) == 8000
    assert se.cut(np.frombuffer(w.tobytes(), np.float32), 0.0, 0.5).flags.writeable  # torch.from_numpy 要可写的数组


def test_commands_grep_is_a_plain_substring(capsys):
    assert main(["commands", "--grep", "SAMPLES.LIST"]) == 0
    assert any(c["name"] == "samples.list" for c in json.loads(capsys.readouterr().out))
    assert main(["commands", "--grep", "samples.list|samples.get"]) == 0
    got = capsys.readouterr()
    assert json.loads(got.out) == [] and "not a regular expression" in got.err


def test_status_hints_only_about_models_that_are_really_broken(tmp_path):
    """“未校验”是文件在、还没校验（2026-11-04 实测：agent 把它当成模型未就绪转告用户），不提示；缺文件、文件不对才提示。"""
    import argparse

    from ottosmasher.cli.main import environment
    from ottosmasher.core.errors import CoreError

    class Fake:
        def __init__(self, states):
            self.states = states

        def call(self, method, params=None):
            if method == "models.status":
                return {"files": [{"model": k, "state": v} for k, v in self.states.items()]}
            raise CoreError("agent-link-failed", reason="not needed here")

    args = argparse.Namespace(lang="en")
    ok = environment(args, tmp_path, Fake({"fcpe": "unverified", "pydomino": "ready"}))
    assert ok["models"]["fcpe"] == "unverified" and not [h for h in ok["hints"] if "models" in h]
    bad = environment(args, tmp_path, Fake({"fcpe": "missing", "pydomino": "mismatch", "tsqyomi": "ready"}))
    assert [h for h in bad["hints"] if "fcpe, pydomino" in h]
