"""作品/集数推断：规格 16 R1.2、05 §5.1；规则可编辑（P10，所有者 2026-10-07）。"""

import pytest

from ottosmasher.core.errors import CoreError
from ottosmasher.domain import rules as rules_mod
from ottosmasher.domain.naming import default_rules, infer_work_episode, validate_rules


@pytest.mark.parametrize(
    "name,work,episode",
    [
        # 规格原文的例子
        ("[VCB-Studio] Yuru Yuri [01][1080p].mkv", "Yuru Yuri", "01"),
        ("[VCB-Studio] Yuru Yuri [01][Ma10p_1080p].mkv", "Yuru Yuri", "01"),
        ("[DBD-Raws][Kemono Friends][02][1080P].mkv", "Kemono Friends", "02"),
        ("[Kemono Friends][01].mkv", "Kemono Friends", "01"),
        ("作品名 - 01.mkv", "作品名", "01"),
        # 默认规则覆盖的常见变体
        ("[Group] Some Title - 03 [1080p][ABCD1234].mkv", "Some Title", "03"),
        ("[Group] Some Title - 03v2 (BD 1080p HEVC FLAC).mkv", "Some Title", "03"),
        ("[Group][Some Title][12v2][1080P][CHS].mp4", "Some Title", "12"),
        ("[Group][Some Title][12 END][1080P].mp4", "Some Title", "12"),
        ("【字幕组】【作品名】【07】【1080P】.mp4", "作品名", "07"),
        ("ゆるゆり 第05話.mp4", "ゆるゆり", "05"),
        ("作品名 第5集.mkv", "作品名", "5"),
        ("Dr. Stone - 11.mkv", "Dr. Stone", "11"),
        ("Title (2019) - 04.mkv", "Title (2019)", "04"),
        ("/some/dir with space/[Kemono Friends][01].mkv", "Kemono Friends", "01"),
        # 没有集数：第一个括号块视为发布组；4 位 19xx/20xx 不当集数（所有者 2026-10-07 同意）
        ("[Group] Title [2019][1080p].mkv", "Title", None),
        ("[Group] Title [1080p].mkv", "Title", None),
        ("[Group][Title][1080p].mkv", "Title", None),
        # 推断不出来就是未知，不拿文件名充当（所有者 2026-10-07 同意）
        ("Love Live 2.mp4", None, None),
        ("song ♪ ♯ remix.flac", None, None),
        ("[1080p].mkv", None, None),
    ],
)
def test_default_rules(name, work, episode):
    r = infer_work_episode(name)
    assert (r.work, r.episode) == (work, episode)


def test_never_uses_group_or_episode_as_work():
    for name in ["[VCB-Studio] Yuru Yuri [01][1080p].mkv", "[DBD-Raws][Kemono Friends][02][1080P].mkv"]:
        assert infer_work_episode(name).work not in ("VCB-Studio", "DBD-Raws", "01", "02")


def test_first_matching_rule_wins_and_reports_index():
    rules = [r"^(?P<work>nomatch)$", r"^(?P<work>.+?)_(?P<episode>\d+)$", r"^(?P<work>.+)$"]
    r = infer_work_episode("Show_07.mkv", rules)
    assert (r.work, r.episode, r.rule) == ("Show", "07", 1)
    r = infer_work_episode("Other.mkv", rules)
    assert (r.work, r.episode, r.rule) == ("Other", None, 2)
    r = infer_work_episode("x.mkv", [])
    assert (r.work, r.episode, r.rule) == (None, None, None)


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
