"""原始能力里不需要模型的部分：读字幕文件（按当前规则，不登记）、声音输入的校验、命令目录的分层。"""

from __future__ import annotations

import pytest

from ottosmasher.api import catalog
from ottosmasher.core.errors import CoreError
from ottosmasher.core.server import Core
from ottosmasher.jobs.primitives import join_lines, shape_alignment
from ottosmasher.lang.ja.frontend import FrontendResult, Word


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
    long = tmp_path / "long.srt"
    long.write_text("1\n00:00:01,000 --> 00:02:02,000\n（音楽）\n", encoding="utf-8")
    assert call(core, "subtitles.parse", path=str(long))["r"]["problems"] == [{"line": 1, "reason": "too-long"}]  # 导入时同样读成无效


def test_audio_input_checks(core, tmp_path):
    assert call(core, "speech.align", items=[{"text": "あ"}])["e"]["code"] == "primitive-input-invalid"
    assert call(core, "speech.align", items=[{"text": "あ", "assetId": "x", "path": "y"}])["e"]["code"] == "primitive-input-invalid"
    assert call(core, "speech.align", items=[])["e"]["code"] == "primitive-input-invalid"
    wav = str(tmp_path / "none.wav")
    for bad in ({"lines": []}, {"lines": ["あ", " "]}, {"lines": ["あ"], "text": "あ"}):
        r = call(core, "speech.align", items=[{**bad, "path": wav}])
        assert r["e"]["code"] == "primitive-input-invalid" and r["e"]["args"]["reason"] == "lines", bad
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


def _fe(text, phonemes, pm, pw, words, morae, mora_word):
    return FrontendResult(text=text, normalized=text, phonemes=phonemes, phoneme_mora=pm, phoneme_word=pw, words=words, morae=morae,
                          mora_word=mora_word, versions={"v": "1"})


def test_join_lines_numbers_morae_and_words_across_lines():
    """多行对齐：每行去掉首尾停顿、行间一个 pau（和 pydomino 的多句输入一样），音拍与词的序号接着数，每行的起止从音拍范围来。"""
    a = _fe("はい、", ["h", "a", "i", "pau"], [0, 0, 1, None], [0, 0, 0, None], [Word("はい", 0, 2, "ハイ", ["ハ", "イ"], 0, True)], ["ハ", "イ"], [0, 0])
    b = _fe("うん", ["pau", "u", "N"], [None, 0, 1], [None, 0, 0], [Word("うん", 0, 2, "ウン", ["ウ", "ン"], 0, True)], ["ウ", "ン"], [0, 0])
    fe, spans = join_lines(["はい、", "うん"], [a, b])
    assert fe.text == "はい、\nうん" and fe.phonemes == ["h", "a", "i", "pau", "u", "N"]
    assert fe.phoneme_mora == [0, 0, 1, None, 2, 3] and fe.phoneme_word == [0, 0, 0, None, 1, 1]
    assert fe.morae == ["ハ", "イ", "ウ", "ン"] and fe.mora_word == [0, 0, 1, 1]
    assert [(w.start, w.end, w.mora_start) for w in fe.words] == [(0, 2, 0), (4, 6, 2)]
    assert spans == [("はい、", 0, 3), ("うん", 4, 6)]  # 音素序列里的范围（行间的 pau 在 3）
    with pytest.raises(CoreError):
        join_lines(["はい", "、"], [a, _fe("、", ["pau"], [None], [None], [], [], [])])
    # 每行的起止 = 这一行第一个到最后一个音素（行间的 pau 不算；没有音拍序号的音素也照样算）
    t = [(0.0, 0.1), (0.1, 0.2), (0.2, 0.3), (0.3, 0.6), (0.6, 0.7), (0.7, 0.9)]
    phones = [{"label": p, "start": s, "end": e, "mora": m, "word": w} for p, (s, e), m, w in zip(fe.phonemes, t, fe.phoneme_mora, fe.phoneme_word)]
    phones[5]["mora"] = None
    out = shape_alignment({"text": fe.text, "clock": "file", "window": [0.0, 1.0]}, fe, {"phones": phones}, spans)
    assert [(x["text"], x["start"], x["end"]) for x in out["lines"]] == [("はい、", 0.0, 0.3), ("うん", 0.6, 0.9)]
    assert out["speech"]["start"] == 0.0 and out["speech"]["end"] == 0.9


def test_agent_skills_command_seeds_the_workspace_folder(core):
    r = call(core, "agent.skills", lang="en")
    assert r["ok"], r
    names = {x["name"] for x in r["r"]["skills"]}
    assert {"preparing-subtitles", "finding-op-ed"} <= names and r["r"]["path"].endswith("skills")
    assert all(x["builtin"] and x["update"] == [] and x["description"] for x in r["r"]["skills"])
    assert call(core, "agent.skills")["ok"]  # 语言已经定下，不传也行


@pytest.mark.parametrize("expr", ["character:京子 AND NOT topic:game", "(topic:game OR topic:food) AND character:*"])
def test_user_guide_tag_examples_parse(core, expr):
    r = call(core, "tags.checkExpr", expr=expr)
    assert r["ok"] and r["r"]["ok"], r


def test_follow_reads_all_pages_and_retains_failed_items():
    from ottosmasher.cli.main import follow

    job = {"id": "batch", "kind": "speech.align", "channel": "model", "status": "succeeded"}
    rows = [{"idx": i, "status": "failed" if i == 120 else "ok"} for i in range(205)]
    class Client:
        def call(self, method, params):
            assert method == "speech.alignResults"
            return rows[params["offset"]:params["offset"] + params["limit"]]
    result, ok = follow(Client(), "speech.align", job, None, False)
    assert ok and result["results"] == rows
