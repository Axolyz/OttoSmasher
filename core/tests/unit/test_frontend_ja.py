"""日语文本前端（规格 08 §8.2、16 R10.1、R10.3、R10.4）。合成 G2P 测规则；真实 pyopenjtalk + tsqyomi 测规格里的例句（模型不在就跳过）。"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from ottosmasher.core.errors import CoreError
from ottosmasher.lang.ja import frontend as fe


def test_normalize_keeps_positions():
    assert fe.normalize("〜~～！\t。") == "ーーー、、、"
    assert fe.normalize("あ～, ええ") == "あー、、ええ"
    # 符号类字符按停顿处理（♪、☆）；长音符、踊り字保留
    assert fe.normalize("♪ラ☆ー々") == "、ラ、ー々"
    assert fe.normalize("全角　空白\n") == "全角、空白、"
    for s in ("〜~～！\t。", "あ～, ええ", "♪ラ☆"):
        assert len(fe.normalize(s)) == len(s)


def test_split_mora():
    assert fe.split_mora("キャーッテ") == ["キャ", "ー", "ッ", "テ"]
    assert fe.split_mora("トーキョー") == ["ト", "ー", "キョ", "ー"]
    assert fe.split_mora("ファン") == ["ファ", "ン"]


def entry(surface, phonemes, span, pron, mora_count):
    return {"surface": surface, "phonemes": phonemes, "char_span": span, "pron": pron, "mora_count": mora_count}


def test_analyze_spec_example_with_synthetic_g2p():
    text = "あ～, ええ"
    seen = []

    def g2p(norm):
        seen.append(norm)
        return [
            entry("あー", ["a", "a"], (0, 2), "アー", 2),
            entry("、", ["pau"], (2, 3), "、", 0),
            entry("、", ["pau"], (3, 4), "、", 0),
            entry("ええ", ["e", "e"], (4, 6), "エー", 2),
        ]

    r = fe.analyze(text, g2p, {"dictionary": "none"})
    assert seen == ["あー、、ええ"]
    assert r.phonemes == ["a", "a", "pau", "e", "e"]
    assert r.phoneme_mora == [0, 1, None, 2, 3]
    assert r.morae == ["ア", "ー", "エ", "ー"]
    assert r.words[r.mora_word[0]].text == "あ～"
    assert r.versions == {"frontend": fe.FRONTEND_VERSION, "dictionary": "none"}


def test_consonants_join_the_following_mora_and_mismatch_is_unknown():
    def g2p(norm):
        return [
            entry("東京", ["t", "o", "o", "ky", "o", "o"], (0, 2), "トーキョー", 4),
            entry("行っ", ["i", "cl"], (2, 4), "イッ", 2),
            entry("ます", ["m", "a", "s", "U"], (4, 6), "マス’", 2),
            # 核心音素数与 mora 数对不上：映射为未知，不硬凑
            entry("変", ["h", "e", "N", "N"], (6, 7), "ヘン", 2),
            # 数字展开：字符范围对不上
            entry("十", ["j", "u", "u"], (0, 0), "ジュー", 2),
        ]

    r = fe.analyze("東京行っます変十", g2p)
    assert r.phoneme_mora[:6] == [0, 0, 1, 2, 2, 3]
    assert r.phoneme_mora[6:8] == [4, 5]
    assert r.phoneme_mora[8:12] == [6, 6, 7, 7]
    assert r.phoneme_mora[12:16] == [None, None, None, None]
    assert r.words[3].mapped is False and r.words[3].morae == ["ヘ", "ン"]
    assert r.words[2].reading == "マス"
    assert r.words[4].start is None and r.words[4].text == "十"
    assert r.phoneme_mora[16:] == [10, 10, 11]


def test_frontend_failures():
    with pytest.raises(CoreError) as e:
        fe.analyze("！？　", lambda s: [])
    assert e.value.code == "frontend-failed" and e.value.args_["reason"] == "empty-text"

    def broken(_):
        raise RuntimeError("mecab")

    with pytest.raises(CoreError) as e:
        fe.analyze("あ", broken)
    assert e.value.args_["reason"] == "g2p"


def test_word_location_only_folds_long_vowels():
    words = [("まず", "マズ"), ("大きく", "オオキク"), ("５つ", "イツツ"), ("の", "ノ"), ("気候", "キコウ"), ("帯", "タイ"), ("に", "ニ"), ("分離", "ブンリ")]
    got = fe.locate_words(words, "マズオーキクイツツノキコータイニブンリ")
    assert got[1] == (2, 6) and got[4] == (10, 13) and got[5] == (13, 15)
    assert all(g is not None for g in got)
    assert fe.locate_words([("猫", "ネコ")], "イヌ") == [None]


# ---------------------------------------------------------------- 真实前端

MODELS = Path(os.environ.get("OTTO_DEV_MODELS", Path(__file__).resolve().parents[3] / "dev-workspace" / "Models"))


@pytest.fixture(scope="module")
def g2p():
    from ottosmasher.lang.ja import openjtalk
    from ottosmasher.models import registry
    from ottosmasher.models.onnx import Device, create_session

    support = registry.default_support_dir()
    path, sha = registry.locate("tsqyomi", "tsqyomi/model.onnx", MODELS, support)
    if not path.exists():
        pytest.skip("tsqyomi weights not in dev-workspace/Models")
    sess = create_session("tsqyomi", path, sha, Device(), probe=False)
    openjtalk.install_tsqyomi(sess, registry.locate("tsqyomi", "tsqyomi/tokenizer.json", MODELS, support), registry.locate("tsqyomi", "tsqyomi/metadata.json", MODELS, support))
    pj = openjtalk.load()
    return lambda s: pj.g2p_mapping(s, use_tsqyomi=True, normalize_mode="None")


def reading(r: fe.FrontendResult) -> str:
    return "".join(w.reading for w in r.words)


def test_r10_1_real(g2p):
    r = fe.analyze("あ～, ええ", g2p)
    assert r.phonemes == ["a", "a", "pau", "e", "e"]
    assert r.phoneme_mora == [0, 1, None, 2, 3]
    assert r.words[r.mora_word[0]].text == "あ～"


def test_r10_3_symbols_and_spaces_are_not_read(g2p):
    assert "キゴー" not in reading(fe.analyze("ねえ 何か言ってよ！", g2p))
    assert "キゴ" not in reading(fe.analyze("♪ラララ♪", g2p))
    r = fe.analyze("どうしたの？　ボス\n早く進めよう", g2p)
    assert reading(r).count("ボス") == 1
    assert r.phonemes.count("pau") >= 2


def test_japanese_spec_reference_sentence(g2p):
    # 参考输出第一句（去掉说话人后的正确对齐文本）
    r = fe.analyze("あなたってば何なの？おジャマします", g2p)
    assert all(w.mapped for w in r.words)
    assert r.phonemes[-4:] == ["m", "a", "s", "U"]


def test_language_registry():
    from ottosmasher import lang

    ja = lang.get(None)
    assert ja.code == "ja" and ja.normalize("～") == "ー" and "N" in ja.core_phonemes
    with pytest.raises(CoreError) as e:
        lang.get("zh")
    assert e.value.code == "language-unsupported"
