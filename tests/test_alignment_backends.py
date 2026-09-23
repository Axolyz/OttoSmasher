import pytest

from ottosmasher.alignment_results import target_phones
from ottosmasher.alignment_runner import worker_command
from ottosmasher.backends import BACKENDS, DEFAULT_BACKEND
from ottosmasher.sound_models import CINEMATIC, MODELS


def test_local_backend_order_and_retired_execution():
    assert list(BACKENDS) == ["narabas", "phonetic", "pydomino"]
    assert DEFAULT_BACKEND == "narabas"
    for retired in ["mfa", "sofa", "maus"]:
        with pytest.raises(ValueError):
            worker_command("/tmp", retired)
    assert "audiosep" not in MODELS
    assert CINEMATIC == ("bandit-v2",)




def test_pydomino_devoicing_does_not_break_ownership():
    raw = {
        "phone_owners": [{"phone": "u", "cue_id": "a", "mora_index": 0}],
        "phones": [{"label": "U", "start": 0.1, "end": 0.2}],
    }
    result = target_phones(raw, {"id": "a"}, "pydomino")
    assert result[0]["label"] == "u" and result[0]["raw_label"] == "U"
    assert raw["phones"][0]["label"] == "U"


def test_zero_length_boundary_silence_is_not_a_failed_alignment():
    raw = {
        "phone_owners": [{"phone": "a", "cue_id": "x"}],
        "phones": [{"label": "pau", "start": 0, "end": 0}, {"label": "a", "start": 0, "end": 0.2}],
    }
    assert len(target_phones(raw, {"id": "x"}, "pydomino")) == 1
