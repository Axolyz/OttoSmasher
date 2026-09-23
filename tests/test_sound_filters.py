import json

import numpy as np
import pytest
from pydantic import ValidationError
from test_quantized_match import note, pattern, query
from test_vocals import separated_cue as separated_cue  # noqa: PLC0414 - pytest fixture export

from ottosmasher.quantized_match import match_pattern
from ottosmasher.rhythm import RhythmQuery
from ottosmasher.sound_features import first_vowel, project, satisfies
from ottosmasher.time_mapping import map_seconds, schedule


def timing_plan():
    return {
        "unit_targets": [
            {"source_seconds": t, "target_beat": b} for t, b in [(0.2, 0), (1.2, 1), (4.2, 4), (5.2, 5)]
        ],
        "control_targets": [{"source_seconds": 1.5, "target_beat": 1.3}],
        "end_target": {"source_seconds": 5.5, "target_beat": 5.3},
        "duration_multiplier": 1,
        "beat_seconds": 1,
        "pauses": [{"start": 1.6, "end": 4.0}],
        "retain_query_canvas": False,
    }


def test_only_rest_and_canvas_changes_do_not_penalize_speech():
    p = timing_plan()
    a = schedule(p, 0, 6 * 48000)
    assert json.loads(json.dumps(a)) == a
    p["unit_targets"][2]["target_beat"] += 8
    p["unit_targets"][3]["target_beat"] += 8
    p["end_target"]["target_beat"] += 8
    b = schedule(p, 0, 6 * 48000)
    assert a["source_speech_seconds"] == pytest.approx(b["source_speech_seconds"])
    assert a["speech_playback_speed"] == pytest.approx(b["speech_playback_speed"], abs=1e-5)
    p["retain_query_canvas"] = True
    p["witness"] = {"query_span_beats": 50}
    c = schedule(p, 0, 6 * 48000)
    assert c["speech_playback_speed"] == pytest.approx(b["speech_playback_speed"])
    assert c["actual_duration"] > b["actual_duration"]


def test_speech_aggregate_uses_duration_not_mean_of_speeds():
    p = timing_plan()
    p["unit_targets"][1]["target_beat"] = 0.5
    p["control_targets"][0]["target_beat"] = 0.8
    p["unit_targets"][3]["target_beat"] = 6
    p["end_target"]["target_beat"] = 6.3
    result = schedule(p, 0, 6 * 48000)
    assert result["speech_playback_speed"] == pytest.approx(
        result["source_speech_seconds"] / result["target_speech_seconds"]
    )
    assert result["source_speech_seconds"] < 5.3


def test_map_is_translation_invariant_and_protected_cores_are_unit_slope():
    p = timing_plan()
    a = schedule(p, 0, 6 * 48000)
    assert json.loads(json.dumps(a)) == a
    for point in p["unit_targets"] + p["control_targets"] + [p["end_target"]]:
        point["target_beat"] += 3.125
    b = schedule(p, 0, 6 * 48000)
    assert b["speech_playback_speed"] == pytest.approx(a["speech_playback_speed"])
    for t in [0.1, 0.2, 1.5, 3.2, 5.5]:
        assert map_seconds(t, b["time_map"]) - map_seconds(t, a["time_map"]) == pytest.approx(
            3.125, abs=1 / 48000
        )
    for core in a["cores"]:
        assert core["source_end"] - core["source_start"] == core["target_end"] - core["target_start"]


def test_unknown_optional_conditions_do_not_pass():
    assert satisfies({}, {})
    for n in [
        {"pitch_trend": "up"},
        {"pitch_register": "low"},
        {"energy_relative_min_db": 3},
        {"speaker": "サーバル"},
        {"phone": "a"},
    ]:
        assert not satisfies({}, n)


def test_conditions_compose_and_compound_vowel_means_first():
    f = {
        "first_vowel": "a",
        "speaker": "サーバル",
        "pitch_trend_semitones": 3,
        "pitch_relative_semitones": -4,
        "energy_relative_db": 4,
    }
    assert satisfies(
        f,
        {
            "phone": "a",
            "speaker": "サーバル",
            "pitch_trend": "up",
            "pitch_register": "low",
            "energy_relative_min_db": 3,
        },
    )
    assert not satisfies(f, {"phone": "i"})
    assert first_vowel({"members": [{"phone": "a"}, {"phone": "i"}, {"phone": "N"}]}) == "a"
    assert first_vowel({"phone": "N"}) is None


def test_sustain_rejects_empty_tail_but_default_preserves_onset_only_behavior():
    p = pattern()
    p["units"][0]["features"] = {"first_vowel": "a", "sustain_end": 2.03}
    assert match_pattern(p, query([note(0, 0.3)], boundary="start"))
    assert match_pattern(p, query([note(0, 0.3, sustain_to_end=True)], boundary="start")) is None
    assert match_pattern(p, query([note(0, 0.1, sustain_to_end=True)], boundary="start"))


def test_sustain_unknown_does_not_pass():
    assert match_pattern(pattern(), query([note(0, 0.1, sustain_to_end=True)], boundary="start")) is None


def test_energy_uses_average_not_duration_and_voicing_gaps_are_not_silence():
    t = np.arange(0.005, 1, 0.01)
    f0 = 200 * 2 ** (t / 12)
    frames = {"times": t, "f0_hz": f0, "voiced": np.ones(len(t), bool), "energy": np.ones(len(t)) * 0.01}
    units = [{"time": 0, "end": 0.2, "phone": "a"}, {"time": 0.2, "end": 1, "phone": "i"}]
    result = project(units, [], frames, 0, [])
    assert result[0]["energy_relative_db"] == pytest.approx(result[1]["energy_relative_db"])
    frames["voiced"][50:70] = False
    result = project(units, [], frames, 0, [])
    assert result[1]["sustain_end"] == pytest.approx(1)
    assert result[1]["pitch_trend_semitones"] > 0
    silence = project(units, [], frames, 0, [{"start": 0.6, "end": 0.8}])
    assert silence[1]["sustain_end"] == 0.6


def test_relative_features_are_canonical_segment_properties():
    t = np.arange(0.005, 2, 0.01)
    frames = {
        "times": t,
        "f0_hz": np.where(t < 1, 200, 400),
        "voiced": np.ones(len(t), bool),
        "energy": np.where(t < 1, 0.01, 0.001),
    }
    units = [
        {"time": 0, "end": 0.4},
        {"time": 0.4, "end": 0.8},
        {"time": 1, "end": 1.4},
        {"time": 1.4, "end": 1.8},
    ]
    segments = [{"parent_unit_indices": [0, 1]}, {"parent_unit_indices": [2, 3]}]
    result = project(units, segments, frames, 0, [])
    assert all(abs(f["pitch_relative_semitones"]) < 1e-8 for f in result)
    assert all(abs(f["energy_relative_db"]) < 1e-8 for f in result)


def test_retired_search_and_invalid_filters_are_rejected():
    for extra in [{"engine": "original"}, {"slowdown_aversion": 101}]:
        with pytest.raises(ValidationError):
            RhythmQuery(notes=[{"start_beats": 0, "end_beats": 1}], **extra)
    with pytest.raises(ValidationError):
        RhythmQuery(notes=[{"start_beats": 0, "end_beats": 1, "phone": "N"}])






def test_source_features_share_parent_despite_different_model_crops(tmp_path, monkeypatch):
    import hashlib

    import soundfile as sf

    from ottosmasher import sound_features
    from ottosmasher.audio_sources import separated_source

    y = np.sin(np.arange(32000) * 0.1).astype(np.float32)
    wav = tmp_path / "vocals.wav"
    sf.write(wav, y, 16000)
    base = {
        "audio_path": str(wav),
        "audio_sha256": hashlib.sha256(wav.read_bytes()).hexdigest(),
        "window_start": 10.0,
        "window_end": 12.0,
        "input_variant": "vocals",
        "source_fingerprint": "source",
    }
    (tmp_path / "manifest.json").write_text(json.dumps(base))
    one = {
        **base,
        "folder": str(tmp_path),
        "audio_sha256": "first-crop",
        "window_start": 10.7,
        "crop_backend": "phonetic",
    }
    two = {**one, "audio_sha256": "second-crop", "window_start": 11.2, "crop_backend": "narabas"}
    monkeypatch.setattr(sound_features, "model_info", lambda: {"sha256": "fixed"})
    monkeypatch.setattr(sound_features, "DATA", tmp_path)
    assert sound_features.asset_id(one) == sound_features.asset_id(two)
    assert separated_source(one)["window_start"] == 10

    class Model:
        def infer(self, audio, sr):
            assert len(audio) == 32000 and sr == 16000
            return {"times": [0.005], "f0_hz": [200], "voiced": [True], "energy": [0.01], "confidence": [0.9]}

    result = sound_features.build_asset(two, Model())
    assert result["source_window_start"] == 10
