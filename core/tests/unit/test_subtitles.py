"""字幕读取与分类：规格 06 §6.1–§6.2、16 R4.4–R4.7、R5.1（合成数据；规格表格里的写法逐条成测）。"""

import pytest

from ottosmasher.core.errors import CoreError
from ottosmasher.domain import subtitle_rules as sr
from ottosmasher.domain import subtitles as subs

SRT = (
    "1\n00:00:01,000 --> 00:00:02,500\n（京子）こんにちは\n\n"
    "2\n00:00:03,000 --> 00:00:04,000  \n（ドア）\n（足音）\n\n"
    "3\n00:00:05,000 --> 00:00:05,000\nゼロ長\n\n"
    "oops not a timing\nbroken block\n\n"
    "4\n01:00:00,125 --> 01:00:01,9\n<i>斜体</i>{\\an8}　全角　空白\n"
)


def test_srt_utf8_bom_crlf_multiline_and_problems(tmp_path):
    p = tmp_path / "a.srt"
    p.write_bytes(b"\xef\xbb\xbf" + SRT.replace("\n", "\r\n").encode("utf-8"))
    r = subs.read(p)
    assert r.format == "srt"
    assert [c.ref for c in r.cues] == ["1", "2", "3", "4"]
    assert [(c.start, c.end) for c in r.cues] == [(1.0, 2.5), (3.0, 4.0), (5.0, 5.0), (3600.125, 3601.9)]
    assert r.cues[1].text == "（ドア）\n（足音）"  # 多行保留换行
    assert r.cues[3].text == "斜体　全角　空白"  # 去标签与样式块，全角空格原样
    assert r.problems == [{"line": 14, "reason": "no-timing"}]
    # 指纹只看内容：BOM 与 CRLF 不同、内容相同 → 同一指纹
    q = tmp_path / "b.srt"
    q.write_text(SRT, encoding="utf-8")
    assert subs.read(q).fingerprint == r.fingerprint
    q.write_text(SRT + "\n5\n00:00:09,000 --> 00:00:10,000\n追加\n", encoding="utf-8")
    assert subs.read(q).fingerprint != r.fingerprint


def test_srt_without_index_and_negative_time():
    cues, problems = subs.parse_srt("00:00:01.5 --> 00:00:02\nA\n\n-00:00:01,000 --> 00:00:00,500\nB\n")
    assert [(c.ref, c.start, c.end, c.text) for c in cues] == [("", 1.5, 2.0, "A"), ("", -1.0, 0.5, "B")]
    assert problems == []


ASS = """[Script Info]
Title: x

[V4+ Styles]
Format: Name, Fontname
Style: Default,Arial

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
Dialogue: 0,0:00:01.00,0:00:02.50,Default,,0,0,0,,{\\i1}（京子）{\\i0}こんにちは\\N二行目, 逗号也在正文里
Comment: 0,0:00:03.00,0:00:04.00,Default,,0,0,0,,不算字幕
Dialogue: 0,0:00:05.10,0:00:06.00,Default,,0,0,0,,a\\hb\\nc
Dialogue: 0,bad,0:00:06.00,Default,,0,0,0,,x
"""


def test_ass_plain_text_and_ignores_comments():
    r = subs.parse_text(ASS, "ass")
    assert [(c.ref, c.start, c.end, c.text) for c in r.cues] == [
        ("1", 1.0, 2.5, "（京子）こんにちは\n二行目, 逗号也在正文里"),
        ("2", 5.1, 6.0, "a b c"),
    ]
    assert r.problems == [{"line": 13, "reason": "no-timing"}]


def test_encoding_and_missing_are_explicit_errors(tmp_path):
    p = tmp_path / "gbk.srt"
    p.write_bytes("1\n00:00:01,000 --> 00:00:02,000\n中文\n".encode("gbk"))
    with pytest.raises(CoreError) as e:
        subs.read(p)
    assert e.value.code == "subtitle-encoding"
    with pytest.raises(CoreError) as e:
        subs.read(tmp_path / "none.srt")
    assert e.value.code == "subtitle-missing"
    (tmp_path / "x.txt").write_text("a", encoding="utf-8")
    with pytest.raises(CoreError) as e:
        subs.read(tmp_path / "x.txt")
    assert e.value.code == "subtitle-format"


DEFAULTS = {k: sr.default_value(k) for k in sr.KEYS}


@pytest.fixture(scope="module")
def rules():
    return sr.SubtitleRules.build(DEFAULTS, check=True)


# 规格 06 §6.2.1 表格 + 16 R4.4、R4.5、R5.1 的例子（种类、名称、说话人、对齐文本）
@pytest.mark.parametrize(
    "text,kind,name,speakers,align",
    [
        ("（ドア）（足音）", "sfx", "ドア / 足音", [], ""),
        ("(足音)(扉)", "sfx", "足音 / 扉", [], ""),
        ("（足音(走る)）（扉）", "sfx", "足音(走る) / 扉", [], ""),
        ("  （悲鳴）\n（倒れる音） ", "sfx", "悲鳴 / 倒れる音", [], ""),
        ("（京子）こんにちは", "line", "こんにちは", ["京子"], "こんにちは"),
        ("台詞（結衣）続き", "line", "台詞続き", ["結衣"], "台詞続き"),
        ("aaa（xxx）yyy", "line", "aaayyy", ["xxx"], "aaayyy"),
        ("（yy（zzz））aaa（xxx）yyy", "line", "aaayyy", ["yy（zzz）", "xxx"], "aaayyy"),
        ("(京子)(結衣)こんにちは", "line", "こんにちは", ["京子", "結衣"], "こんにちは"),
        ("（京子(きょうこ)たち）アッカリ～ン", "line", "アッカリ～ン", ["京子(きょうこ)たち"], "アッカリ～ン"),
        ("（京子(きょうこ)たち）台詞", "line", "台詞", ["京子(きょうこ)たち"], "台詞"),
        ("歳納(としのう)京子！", "line", "歳納京子！", ["としのう"], "歳納京子！"),
        ("（ドアチャイム）\nウワーッ！", "line", "ウワーッ！", ["ドアチャイム"], "ウワーッ！"),
        ("普通の台詞", "line", "普通の台詞", [], "普通の台詞"),
        # 名称里的换行以空格连接；对齐文本保留换行
        ("一行目\n二行目", "line", "一行目 二行目", [], "一行目\n二行目"),
        # 同一说话人出现两次只记一次
        ("（京子）あ\n（京子）い", "line", "あ い", ["京子"], "あ\nい"),
        ("♪～", "line", "♪～", [], "♪～"),
        ("", "line", "", [], ""),
    ],
)
def test_default_classification(rules, text, kind, name, speakers, align):
    c = sr.classify(text, rules)
    assert (c.kind, c.name, list(c.speakers), c.align_text) == (kind, name, speakers, align)


def test_split_and_clean_rules():
    rs = sr.SubtitleRules.build({**DEFAULTS, "subtitle.speaker_split": "[･・＆&、/／]", "subtitle.speaker_clean": "[（(][^（）()]*[）)]"}, check=True)
    assert sr.classify("（京子(きょうこ)）こんにちは", rs).speakers == ("京子",)
    assert sr.classify("（結衣･ちなつ）わあ…", rs).speakers == ("結衣", "ちなつ")
    # 拆分规则带捕获组也不会带出空名字
    rs2 = sr.SubtitleRules.build({**DEFAULTS, "subtitle.speaker_split": "(･)"}, check=True)
    assert sr.classify("（結衣･ちなつ）わあ", rs2).speakers == ("結衣", "ちなつ")


def test_rule_validation_errors():
    def reason(key, pattern):
        with pytest.raises(CoreError) as e:
            sr.validate_setting(key)(pattern)
        assert e.value.code == "subtitle-rule-invalid"
        assert e.value.args_["setting"] == key
        return e.value.args_["reason"]

    # 缺命名组（R4.6）、写法错误、空
    assert reason("subtitle.note_rule", r"\((.*?)\)") == "missing-group"
    assert reason("subtitle.speaker_rule", r"\((?P<who>.*?)\)") == "missing-group"
    assert reason("subtitle.sfx_rule", "(unclosed") == "syntax"
    assert reason("subtitle.sfx_rule", "") == "not-text"
    assert reason("subtitle.sfx_rule", "x" * 5000) == "too-long"
    # 可选规则空串 = 关闭；默认规则本身合格
    assert sr.validate_setting("subtitle.speaker_split")("") == ""
    for k in sr.KEYS:
        assert sr.validate_setting(k)(DEFAULTS[k]) == DEFAULTS[k]


def test_catastrophic_rule_times_out_on_100k_chars():
    """R4.6：`(a+)+$` 作用于 10 万字符 → 超时报错（保存时的压力样例里就有 10 万字符）。"""
    with pytest.raises(CoreError) as e:
        sr.validate_setting("subtitle.speaker_split")("(a+)+$")
    assert (e.value.code, e.value.args_["reason"]) == ("subtitle-rule-invalid", "timeout")


def test_runtime_timeout_is_not_swallowed():
    rs = sr.SubtitleRules.build({**DEFAULTS, "subtitle.speaker_split": "(a+)+$"})  # 运行时不再测压力（保存时已测）
    with pytest.raises(CoreError) as e:
        sr.classify("（" + "a" * 100000 + "!）x", rs)
    assert e.value.code == "subtitle-rule-timeout"
