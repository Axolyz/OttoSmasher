import pytest
from ottosmasher.tag_expression import parse, from_tags, SyntaxError


def test_precedence_quotes_and_complete_name():
    query = parse('(character:京子 OR character:結衣) AND NOT "speaker-status:多人未分段"')
    assert query.matches(['character:京子'])
    assert not query.matches(['character:京子', 'speaker-status:多人未分段'])
    assert not query.matches(['character:京子2'])
    assert parse('a or b and not c').matches(['a', 'c'])
    assert parse('"AND" AND "two words"').matches(['AND', 'two words'])
    assert parse(from_tags(['a"b', 'x\\y'])).matches(['a"b', 'x\\y'])


@pytest.mark.parametrize('text', ['a b', '(a OR)', 'a AND', '"unclosed', '()', 'a)', '""'])
def test_errors_located(text):
    with pytest.raises(SyntaxError) as e: parse(text)
    assert 0 <= e.value.position <= len(text)


def test_size_is_bounded():
    with pytest.raises(SyntaxError): parse('NOT ' * 257 + 'a')
