"""可移植文件名与导出文件名：规格 16 R21.3、12 §12.1、QUESTIONS C4。"""

import unicodedata

import pytest
from hypothesis import given
from hypothesis import strategies as st

from ottosmasher.core.errors import CoreError
from ottosmasher.domain.filename import (
    ExportNameParts,
    export_filename,
    format_clock,
    portable,
    truncate_utf8,
    utf8_len,
)

KEY = "0123456789abcdef" * 4
SRC_ID = "fedcba9876543210" * 2


def parts(**kw) -> ExportNameParts:
    base = dict(
        content="やったー",
        track="原混音",
        source_name="[VCB-Studio] Yuru Yuri [01][1080p]",
        source_id=SRC_ID,
        start=62.5,
        end=64.0126,
        export_key=KEY,
    )
    base.update(kw)
    return ExportNameParts(**base)


# R21.3 可移植：CON.txt → _CON.txt；a<>:"/\|?*\n → a__________
@pytest.mark.parametrize(
    "raw,out",
    [
        ("CON.txt", "_CON.txt"),
        ("con", "_con"),
        ("LPT9.wav", "_LPT9.wav"),
        ("COM10.wav", "COM10.wav"),
        ("CONSOLE.wav", "CONSOLE.wav"),
        ('a<>:"/\\|?*\n', "a__________"),
        ("日本語 / 中文", "日本語 _ 中文"),
        ("  .name.  ", "name"),
        ("♪ ♯ 【】", "♪ ♯ 【】"),
        ("é", "é"),  # NFC
    ],
)
def test_portable(raw, out):
    assert portable(raw) == out


def test_truncate_does_not_split_characters():
    s = "日本語テキスト"  # 每字 3 字节
    assert truncate_utf8(s, 7) == "日本"
    assert truncate_utf8(s, 9) == "日本語"
    assert truncate_utf8("abc", 10) == "abc"
    # 组合字符不与基字分开（NFD 的 é = e + U+0301）
    assert truncate_utf8("aé", 2) == "a"


def test_format_clock():
    assert format_clock(0) == "00-00-00.000"
    assert format_clock(3725.0004) == "01-02-05.000"
    assert format_clock(59.9996) == "00-01-00.000"
    assert format_clock(0.123) == "00-00-00.123"


def test_default_layout():
    name = export_filename(parts())
    assert name == (
        "やったー__原混音__[VCB-Studio] Yuru Yuri [01][1080p]__fedcba98"
        "_00-01-02.500-00-01-04.013__0123456789ab.wav"
    )


def test_processing_and_local_span():
    name = export_filename(parts(processing="拉平-G♯5_卡拍-120BPM", local_prefix="局部-"))
    assert "__拉平-G♯5_卡拍-120BPM__原混音__" in name
    assert "_局部-00-01-02.500-00-01-04.013__" in name
    # 处理信息为空时整段省略（不留空段）
    assert "____" not in export_filename(parts(processing=""))


def test_segment_limits():
    long = "あ" * 100
    name = export_filename(parts(content=long, source_name=long, processing="拉平-" + "x" * 80))
    content, processing = name.split("__")[:2]
    assert utf8_len(content) <= 72
    assert utf8_len(processing) <= 45
    # 原片段 ≤45 字节：原片名截到 35 字节 + __ + 8 位 ID（C4）
    src_seg = name.split("__原混音__")[1].split("_00-")[0]
    assert utf8_len(src_seg) <= 45 and src_seg.endswith("__fedcba98")


@given(
    st.text(min_size=0, max_size=200),
    st.text(min_size=1, max_size=200),
    st.text(min_size=0, max_size=200),
    st.text(min_size=0, max_size=80),
)
def test_always_portable_and_bounded(content, track, source_name, processing):
    name = export_filename(
        parts(content=content, track=track, source_name=source_name, processing=processing)
    )
    assert utf8_len(name) <= 255
    assert name.endswith("__0123456789ab.wav")  # 以 12 位短 ID 结尾
    assert name == unicodedata.normalize("NFC", name)
    assert not any(c in name for c in '\\/:*?"<>|') and all(ord(c) >= 32 and ord(c) != 127 for c in name)
    if processing.strip(" ."):
        # 处理信息段被保留（可移植化、截断后仍然在）
        assert portable(processing)[:5].strip(" .")[:1] in name


def test_bad_export_key():
    with pytest.raises(CoreError):
        export_filename(parts(export_key="short"))
