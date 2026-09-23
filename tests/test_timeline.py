import copy

import pytest
import soundfile as sf
import test_vocals
from pydantic import ValidationError

separated_cue = test_vocals.separated_cue

from ottosmasher.rhythm import RhythmQuery
from ottosmasher.rhythm_units import group_phones, measured_pauses


def q(starts, width=0.25, **kwargs):
    return RhythmQuery(
        engine="original",
        adjust_pauses=kwargs.pop("adjust_pauses", True),
        bpm=60,
        notes=[{"start_beats": t, "end_beats": t + width} for t in starts],
        factor_min=kwargs.pop("factor_min", 1),
        factor_max=kwargs.pop("factor_max", 1),
        tolerance_beats=0.1,
        **kwargs,
    )


def units(times):
    return [
        {"time": t, "end": t + 0.1, "phone": "a", "duration": 0.1, "label": "a", "strength": 0.8}
        for t in times
    ]


def phones(labels):
    return [{"label": p, "start": i * 0.2, "end": (i + 1) * 0.2} for i, p in enumerate(labels)]


@pytest.mark.parametrize(
    "labels,expected",
    [
        (["ch", "i", "i", "i"], 1),
        (["k", "a", "i"], 1),
        (["k", "u", "i"], 1),
        (["e", "i"], 1),
        (["o", "u"], 1),
        (["k", "a", "N"], 1),
        (["a", "N", "i"], 2),
        (["a", "SP", "a"], 2),
        (["k", "a", "k", "a"], 2),
        (["oː"], 1),
        (["a", "ɴ"], 1),
    ],
)
def test_grouping_retains_original_phones(labels, expected):
    raw = phones(labels)
    before = copy.deepcopy(raw)
    result = group_phones(raw)
    assert len(result) == expected
    assert raw == before
    assert sum(len(u["members"]) for u in result) == sum(p not in {"ch", "k", "SP"} for p in labels)


def test_manual_split_and_same_vowel_duration():
    raw = phones(["ch", "i", "i", "i"])
    a = group_phones(raw)
    assert a[0]["phone_runs"][0]["end"] - a[0]["phone_runs"][0]["start"] == pytest.approx(0.6)
    assert len(group_phones(raw, split_before=[2])) == 2
    assert len(group_phones(phones(["k", "a", "i"]))[0]["phone_runs"]) == 2


def test_long_vowel_and_loud_mislabeled_silence_are_not_editable(separated_cue):
    _, _, lineage = separated_cue
    analysis = {
        "audio_lineage": lineage,
        "window_start": 0,
        "phones": [
            {"label": "a", "start": 0, "end": 1},
            {"label": "SP", "start": 1, "end": 2},
            {"label": "i", "start": 2, "end": 3},
        ],
    }
    assert measured_pauses(analysis) == []
    y, sr = sf.read(lineage["audio_path"])
    y[sr : 2 * sr] = 0
    sf.write(lineage["audio_path"], y, sr)
    pause = measured_pauses(analysis)
    assert pause[0]["start"] == pytest.approx(1.02)
    analysis["phones"][1]["label"] = "a"
    assert measured_pauses(analysis) == pause  # waveform evidence is independent of model labels
    analysis["phones"][1]["label"] = "AP"
    assert measured_pauses(analysis) == pause  # elastic gap preserves even mislabeled breath audio




def test_invalid_overlapping_blocks_are_rejected():
    with pytest.raises(ValidationError):
        q([0, 0.5], width=1)
    with pytest.raises(ValidationError):
        q([0], width=0)


def test_mfa_unlabeled_quiet_gap_is_adjustable(separated_cue):
    _, _, lineage = separated_cue
    y, sr = sf.read(lineage["audio_path"])
    y[sr : 2 * sr] = 0
    sf.write(lineage["audio_path"], y, sr)
    a = {
        "audio_lineage": lineage,
        "window_start": 0,
        "phones": [{"label": "a", "start": 0, "end": 1}, {"label": "i", "start": 2, "end": 3}],
    }
    assert len(measured_pauses(a)) == 1
