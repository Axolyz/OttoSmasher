from ottosmasher.g2p_frontend import generate, normalize_text, dictionary_entries
import pytest


def test_duplicate_vowels_pauses_and_same_result_mora_mapping():
    def mapping(text):
        assert text == 'あー、、ええ'
        return [
            {'phonemes': ['a', 'a'], 'pron': 'アー', 'mora_count': 2, 'char_span': [0, 2]},
            {'phonemes': ['pau'], 'pron': '、', 'mora_count': 0, 'char_span': [2, 3]},
            {'phonemes': ['pau'], 'pron': '、', 'mora_count': 0, 'char_span': [3, 4]},
            {'phonemes': ['e', 'e'], 'pron': 'エー', 'mora_count': 2, 'char_span': [4, 6]},
        ]
    r = generate('あ～, ええ', mapping_function=mapping)
    assert r['phones'] == ['a', 'a', 'pau', 'e', 'e']
    assert r['phone_mora'] == [0, 1, None, 2, 3]
    assert r['mora']['words']['0']['word'] == 'あ～'
    assert normalize_text('〜~～！\t。') == 'ーーー、、、'


def test_dictionary_validation():
    assert dictionary_entries('京子\tキョーコ\n') == [('京子', 'キョーコ')]
    with pytest.raises(ValueError, match='第 2 行'): dictionary_entries('京子\tキョーコ\n京子\tキョウコ')
    with pytest.raises(ValueError): dictionary_entries('京子\tきょうこ')
