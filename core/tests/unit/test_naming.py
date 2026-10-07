"""作品/集数推断：规格 16 R1.2、05 §5.1。"""

import pytest

from ottosmasher.domain.naming import infer_work_episode


@pytest.mark.parametrize(
    "name,work,episode",
    [
        # 规格原文的例子
        ("[VCB-Studio] Yuru Yuri [01][1080p].mkv", "Yuru Yuri", "01"),
        ("[VCB-Studio] Yuru Yuri [01][Ma10p_1080p].mkv", "Yuru Yuri", "01"),
        ("[DBD-Raws][Kemono Friends][02][1080P].mkv", "Kemono Friends", "02"),
        ("[Kemono Friends][01].mkv", "Kemono Friends", "01"),
        ("作品名 - 01.mkv", "作品名", "01"),
        # 同一规则的常见变体
        ("[Group] Some Title - 03 [1080p][ABCD1234].mkv", "Some Title", "03"),
        ("[Group] Some Title - 03v2 (BD 1080p HEVC FLAC).mkv", "Some Title", "03"),
        ("[Group][Some Title][12v2][1080P][CHS].mp4", "Some Title", "12"),
        ("[Group][Some Title][12 END][1080P].mp4", "Some Title", "12"),
        ("【字幕组】【作品名】【07】【1080P】.mp4", "作品名", "07"),
        ("ゆるゆり 第05話.mp4", "ゆるゆり", "05"),
        ("作品名 第5集.mkv", "作品名", "5"),
        ("Some.Title.S02E07.1080p.WEB.mkv", "Some Title", "07"),
        ("Dr. Stone - 11.mkv", "Dr. Stone", "11"),
        ("Title (2019) - 04.mkv", "Title (2019)", "04"),
        ("[Group] Title [2019][1080p].mkv", "Title", None),  # 年份不是集数
        ("[Group] Title [1080p].mkv", "Title", None),
        ("[Group][Title][1080p].mkv", "Title", None),  # 没有集数时第一个括号块视为发布组
        ("Love Live 2.mp4", "Love Live 2", None),
        ("song ♪ ♯ remix.flac", "song ♪ ♯ remix", None),
        ("[1080p].mkv", None, None),
        ("/some/dir with space/[Kemono Friends][01].mkv", "Kemono Friends", "01"),
    ],
)
def test_infer(name, work, episode):
    r = infer_work_episode(name)
    assert (r.work, r.episode) == (work, episode)


def test_never_uses_group_or_episode_as_work():
    for name in [
        "[VCB-Studio] Yuru Yuri [01][1080p].mkv",
        "[DBD-Raws][Kemono Friends][02][1080P].mkv",
    ]:
        r = infer_work_episode(name)
        assert r.work not in ("VCB-Studio", "DBD-Raws", "01", "02")
