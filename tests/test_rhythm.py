import pytest
from pydantic import ValidationError

from ottosmasher.rhythm import RhythmQuery


def test_query_rejects_ambiguous_or_unavailable_constraints():
    with pytest.raises(ValidationError):
        RhythmQuery(cells=[{"state": "required", "pitch": "A2"}, {"state": "any"}])
    with pytest.raises(ValidationError):
        RhythmQuery(cells=[{"state": "any"}] * 8)
    with pytest.raises(ValidationError):
        RhythmQuery(cells=[{"state": "required", "phone": "a"}, {"state": "any"}], mode="acoustic")
    with pytest.raises(ValidationError):
        RhythmQuery(cells=[{"state": "forbidden", "phone": "a"}, {"state": "required"}])
