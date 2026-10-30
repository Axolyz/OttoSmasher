"""原始能力里不需要模型的部分：读字幕文件（按当前规则，不登记）、声音输入的校验、命令目录的分层。"""

from __future__ import annotations

import pytest

from ottosmasher.api import catalog
from ottosmasher.core.server import Core


@pytest.fixture
def core(tmp_path):
    c = Core(tmp_path / "ws", agent_link=False)
    c.open()
    yield c
    c.close()


def call(core, m, **p):
    return core.dispatch({"id": 1, "m": m, "p": p})


def test_parse_subtitle_file_without_registering(core, tmp_path):
    srt = tmp_path / "a.srt"
    srt.write_text(
        "1\n00:00:01,000 --> 00:00:02,000\n♪～\n\n"
        "2\n00:00:03,000 --> 00:00:04,000\n（京子(きょうこ)たち）こんにちは\n\n"
        "3\n00:00:05,000 --> 00:00:06,000\n（足音）\n\n"
        "4\n00:01:00,000 --> 00:01:01,000\n～♪\n\nbroken\n",
        encoding="utf-8",
    )
    r = call(core, "subtitles.parse", path=str(srt), duration=1440.0)  # 媒体时长：OP / ED 按它判定
    assert r["ok"], r
    p = r["r"]
    line = next(c for c in p["cues"] if c["no"] == 2)
    assert (line["kind"], line["text"], line["speakers"]) == ("line", "こんにちは", ["京子たち"])
    assert next(c for c in p["cues"] if c["no"] == 3)["kind"] == "sfx"
    assert p["speakers"] == [{"name": "京子たち", "count": 1}]
    assert [(x["kind"], x["start"], x["end"]) for x in p["oped"]["pairs"]] == [("OP", 1.0, 61.0)]
    assert p["problems"]
    assert core.conn.execute("SELECT COUNT(*) FROM text_segment").fetchone()[0] == 0
    assert call(core, "subtitles.parse", path=str(tmp_path / "none.srt"))["e"]["code"] == "file-missing"


def test_audio_input_checks(core, tmp_path):
    assert call(core, "speech.align", items=[{"text": "あ"}])["e"]["code"] == "primitive-input-invalid"
    assert call(core, "speech.align", items=[{"text": "あ", "assetId": "x", "path": "y"}])["e"]["code"] == "primitive-input-invalid"
    assert call(core, "speech.align", items=[])["e"]["code"] == "primitive-input-invalid"
    assert call(core, "f0.track", path=str(tmp_path / "none.wav"))["e"]["code"] == "file-missing"
    assert call(core, "f0.track", assetId="nope")["e"]["code"] == "asset-not-found"


def test_catalog_marks_the_two_layers():
    cmds = {c["name"]: c for c in catalog.build(catalog.default_commands())["commands"]}
    for name in ("speech.align", "speech.alignResults", "text.analyze", "f0.track", "subtitles.parse", "subtitles.ruleTest", "spectrum.get"):
        assert cmds[name]["layer"] == "primitive", name
    assert cmds["samples.batchEdit"]["layer"] == "library" and cmds["speech.submit"]["layer"] == "library"
    # 原始能力不改资料库：没有 write 类
    assert not [n for n, c in cmds.items() if c["layer"] == "primitive" and c["effect"] == "write"]


def test_cli_lists_primitives(capsys):
    import json

    from ottosmasher.cli.main import main

    assert main(["commands", "--layer", "primitive"]) == 0
    names = {c["name"] for c in json.loads(capsys.readouterr().out)}
    assert {"speech.align", "text.analyze", "f0.track", "subtitles.parse"} <= names and "samples.batchEdit" not in names
