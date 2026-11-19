"""作品/集数推断：规格 16 R1.2、05 §5.1；规则可编辑（P10，所有者 2026-10-07）。"""

import pytest

from ottosmasher.core.errors import CoreError
from ottosmasher.domain import rules as rules_mod
from ottosmasher.domain.naming import default_rules, infer_work_episode, validate_rules


@pytest.mark.parametrize(
    "name,work,episode",
    [
        ("[VCB-Studio] Yuru Yuri [01v2][1080p].mkv", "Yuru Yuri", "01v2"),
        ("Yuru Yuri [01].mkv", "Yuru Yuri", "01"),
        ("作品名 - 03.mkv", "作品名", "03"),
        (
            "[Erai-raws] FX Senshi Kurumi-chan - 04 [1080p CR WEBRip HEVC AAC][MultiSub][0504E70E].mkv",
            "FX Senshi Kurumi-chan", "04",
        ),
        ("Gabriel Dropout 2017 S01E11-[1080p][BDRIP][AV1.OPUS].mkv", "Gabriel Dropout 2017", "S01E11"),
        ("/some/dir with space/[Group] Title (2019) [02].mkv", "Title (2019)", "02"),
        ("[Group] Title - 03v2 (BD 1080p).mkv", "Title", "03v2"),
        ("Title S02E03.mkv", "Title", "S02E03"),
    ],
)
def test_default_rules(name, work, episode):
    r = infer_work_episode(name)
    assert (r.work, r.episode) == (work, episode)


@pytest.mark.parametrize("stem", [
    "[Yuru Yuri][1080p]", "[Group] Title [1080p]", "[Group] Title [2019]",
    "[Group][Title][01]", "[Title][01]", "[Group] Title - 1080p",
    "Title - 1080p", "Title 第05話", "Title [1080p]", "Title [2019]", "Title_01", "Title S01E11extra",
])
def test_default_rules_leave_other_formats_unmatched(stem):
    result = infer_work_episode(f"{stem}.mkv")
    assert (result.work, result.episode, result.rule) == (None, stem, None)


def test_first_matching_rule_wins_and_reports_index():
    rules = [r"^(?P<work>nomatch)$", r"^(?P<work>.+?)_(?P<episode>\d+)$", r"^(?P<work>.+)$"]
    r = infer_work_episode("Show_07.mkv", rules)
    assert (r.work, r.episode, r.rule) == ("Show", "07", 1)
    r = infer_work_episode("Other.mkv", rules)
    assert (r.work, r.episode, r.rule) == ("Other", "Other", 2)
    r = infer_work_episode("x.mkv", [])
    assert (r.work, r.episode, r.rule) == (None, "x", None)


def test_rule_with_only_episode_group():
    r = infer_work_episode("ep12.wav", [r"ep(?P<episode>\d+)"])
    assert (r.work, r.episode) == (None, "12")


def test_runtime_timeout_is_reported_not_silent():
    slow = r"^(?P<work>(a|aa)*)$"
    r = infer_work_episode("a" * 254 + "!.mkv", [slow, r"^(?P<work>a)"])
    assert r.timed_out == (0,)
    assert (r.work, r.rule) == ("a", 1)


def test_defaults_pass_their_own_validation():
    assert validate_rules(default_rules()) == default_rules()


@pytest.mark.parametrize(
    "value,reason",
    [
        ("not a list", "not-a-list"),
        ([r"^(?P<work>"], "syntax"),
        ([r"^(.+) - (\d+)$"], "missing-group"),
        ([""], "not-text"),
        (["x" * 4097], "too-long"),
        ([r"^(?P<work>(a|aa)*)$"], "timeout"),  # 灾难性回溯 → 超时报错（规格 16 R4.6 同类）
        ([r"(?P<work>a)"] * 33, "too-many"),
    ],
)
def test_validation_errors(value, reason):
    with pytest.raises(CoreError) as ei:
        validate_rules(value)
    assert ei.value.args_["reason"] == reason


def test_validation_reports_rule_number():
    with pytest.raises(CoreError) as ei:
        validate_rules([r"(?P<work>a)", r"(?P<work>"])
    assert ei.value.code == "rule-invalid" and ei.value.args_["rule"] == 2


def test_recursive_dialect_supported():
    # 字幕规则要用的递归括号写法在同一方言下可用（规格 06 §6.2.2）
    pat = rules_mod.compile_rule(r"(?P<b>[（(](?P<content>(?:[^（）()]|(?&b))*)[）)])", required=["content"])
    assert pat.search("（京子(きょうこ)たち）台詞").group("content") == "京子(きょうこ)たち"


# ---------------------------------------------------------------- 采样建议名与性质预填（04 §4.7、R2.6、R7.5）
from ottosmasher.domain.naming import clock_label, nature_for_roles, suggest_sample_name  # noqa: E402


def test_clock_label():
    assert clock_label(80.2) == "1:20.200"
    assert clock_label(3725.0004) == "1:02:05.000"
    assert clock_label(0) == "0:00.000"


def test_suggest_name_priority():
    base = dict(source_name="Yuru Yuri 01", start=80.2, end=82.0)
    assert suggest_sample_name(**base) == "Yuru Yuri 01 1:20.200–1:22.000"
    assert suggest_sample_name(**base, mapped=False, local_marker="局部 ") == "Yuru Yuri 01 · 局部 1:20.200–1:22.000"
    # R7.5：与音效标注交叠 → 用清洗后的文字
    assert suggest_sample_name(**base, overlapping_texts=["足音"]) == "足音"
    assert suggest_sample_name(**base, overlapping_texts=["ちょっと待って", " ", "足音", "足音"]) == "ちょっと待って / 足音"
    # 对齐结果优先
    assert suggest_sample_name(**base, aligned=("待って", "まって"), overlapping_texts=["足音"]) == "待って — まって"


@pytest.mark.parametrize(
    "roles,nature",
    [(["vocal"], "speech"), (["sfx"], "unpitched"), (["vocal", "sfx"], "unclassified"), ([], "unclassified")],
)
def test_nature_for_roles(roles, nature):
    assert nature_for_roles(roles) == nature
