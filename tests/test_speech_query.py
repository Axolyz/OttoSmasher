import pytest

from ottosmasher.speech_query import SpeechQuery, match_units, unit_metrics


def unit(i, pitch=60, phrase=0, **fields):
    return {
        "id": str(i),
        "index": i,
        "start": i * 2.0,
        "end": i * 2.0 + 1.5,
        "phrase": phrase,
        "measurements": {
            "pitch_midi": pitch,
            "pitch_coverage": 1.0,
            "stability_cents": 10.0,
            "first_vowel": "a",
            "consonants": [],
            "span_seconds": 1.5,
            "sustain_seconds": 1.2,
            **fields,
        },
    }


def q(**kw):
    return SpeechQuery.model_validate(
        {
            "units": [
                {"pitch_class": 0},
                {"pitch_class": 4, "phone": "a"},
                {"pitch_class": 7, "duration_min": 1},
            ],
            **kw,
        }
    )


def test_ceg_adjacency_octaves_multiple_and_missing():
    values = [unit(0), unit(1, 64), unit(2, 79), unit(3, 72), unit(4, 76), unit(5, 67)]
    assert [x["unit_indices"] for x in match_units(values, q())] == [[0, 1, 2], [3, 4, 5]]
    # Invalid intervening unit must never be filtered away before establishing adjacency.
    values.insert(1, unit(8, 61))
    assert len(match_units(values, q())) == 1
    values[-1]["measurements"]["pitch_midi"] = None
    assert match_units(values, q()) == []


def test_constraints_and_boundaries():
    values = [unit(0), unit(1, 64, consonants=["k"]), unit(2, 67)]
    assert match_units(values, q(boundary="both"))
    assert match_units(
        values, q(units=[{"pitch_class": 0, "octave": 4}, {"consonants": ["k"]}, {"duration_min": 1.1}])
    )
    assert not match_units(values, q(units=[{"pitch_class": 0, "octave": 5}, {}, {}]))
    assert not match_units(values, q(units=[{}, {"consonants": []}, {}]))
    values[2]["phrase"] = 1
    assert not match_units(values, q())
    assert match_units(values, q(cross_pauses=True))
    assert not match_units(values, q(cross_pauses=True, max_gap=0.1))
    assert match_units(values, q(boundary="end", units=[{}, {}]))
    assert not match_units(values, q(boundary="end", boundary_basis="sample", units=[{}, {}]))
    assert match_units(values, q(boundary="start", units=[{}, {}]))


def test_pitch_threshold_coverage_and_duration_definition():
    x = unit(0, 60.49, stability_cents=90)
    assert match_units([x], q(units=[{"pitch_class": 0, "stability_cents": 100}]))
    assert not match_units([x], q(units=[{"pitch_class": 0, "tolerance_cents": 48}]))
    x["measurements"]["pitch_coverage"] = 0.49
    assert not match_units([x], q(units=[{"pitch_class": 0}]))
    assert match_units([x], q(units=[{"duration_min": 1.3, "duration_measure": "span"}]))
    assert not match_units([x], q(units=[{"duration_min": 1.3}]))
    x["measurements"]["sustain_seconds"] = None
    assert not match_units([x], q(units=[{"duration_max": 3}]))


def test_metrics_consonants_reliability_and_missing_not_zero():
    r = {
        "signature": "x",
        "analysis": {
            "phones": [{"start": 0, "end": 0.1, "label": "k"}, {"start": 0.1, "end": 0.5, "label": "a"}]
        },
        "view": {"units": [{"time": 0.1, "end": 0.5, "members": [{"phone_index": 1, "label": "a"}]}]},
        "features": [{"first_vowel": "a", "sustain_end": 0.5}],
        "frames": {
            "times": [0.1, 0.2, 0.3, 0.4],
            "f0_hz": [261.6256] * 4,
            "voiced": [True] * 4,
            "confidence": [1, 1, 1, 0],
        },
    }
    u = unit_metrics(r)[0]
    assert u["measurements"]["consonants"] == ["k"]
    assert u["start"] == 0
    assert u["measurements"]["pitch_coverage"] == 0.75
    assert u["measurements"]["pitch_midi"] == pytest.approx(60, abs=0.001)
    r["frames"] = {}
    assert unit_metrics(r)[0]["measurements"]["pitch_coverage"] is None


def rhythm_record():
    return {
        "strategy": "acoustic",
        "compiled": {"routes": {"acoustic": {}}},
        "view": {"units": [{"time": 0.0, "end": 0.5}, {"time": 1.0, "end": 1.5}, {"time": 2.0, "end": 3.0}]},
        "features": [{"sustain_end": 0.5}, {"sustain_end": 1.5}, {"sustain_end": 3.0}],
        "scope": {"kind": "whole"},
    }


def test_rhythm_strategies_shape_scope_occupancy_and_missing_sustain(monkeypatch):
    from ottosmasher import rhythm_index, sample_rhythm
    from ottosmasher.speech_query import rhythm_evidence

    record = rhythm_record()

    def prototype(r, s, d):
        return {
            "plan": {
                "unit_targets": [{"source_seconds": t, "target_beat": t / d} for t in (0, 1, 2)],
                "end_target": {"source_seconds": 3.0, "target_beat": 3.0 / d},
            }
        }

    monkeypatch.setattr(rhythm_index, "prototype", prototype)
    monkeypatch.setattr(
        sample_rhythm, "candidates", lambda *a: ([{"density": 1, "speech_playback_speed": 2}], [])
    )
    hit = {"unit_indices": [0, 1, 2]}
    query = {"notes": [{"start_beats": t, "end_beats": e} for t, e in ((0, 1), (2, 3), (4, 6))], "bpm": None}
    evidence = rhythm_evidence(record, hit, query)
    assert evidence["strict"] and evidence["basis"] == "normalized_shape"
    assert rhythm_evidence(record, hit, {**query, "scope": "segments"}) is None
    query["notes"][1]["start_beats"] = 2.8
    assert not rhythm_evidence(record, hit, query)["strict"]
    query["notes"][1]["start_beats"] = 2
    query["notes"][0]["end_beats"] = 3  # occupies the next onset
    assert rhythm_evidence(record, hit, query)["occupancy_collisions"][0] == [1]
    assert not rhythm_evidence(record, hit, query)["strict"]
    query["notes"][0]["sustain_to_end"] = True
    record["features"][0]["sustain_end"] = None
    assert rhythm_evidence(record, hit, query) is None
    query["notes"][0]["sustain_to_end"] = False
    assert rhythm_evidence(record, hit, {**query, "bpm": 120, "speed_filter": True}) is None


def test_query_condition_migration_preserves_union():
    query = SpeechQuery.model_validate(
        {
            "mode": "rhythm",
            "units": [{"pitch_class": 0, "consonants": ["ɾ"], "strength_min": 0.5}],
            "rhythm": {"slowdown_aversion": 2, "notes": []},
        }
    )
    assert query.rhythm_policy == "required"
    assert query.units[0].consonants == ["r"]
    assert "slowdown_aversion" not in query.rhythm


def test_onset_strength_unknown_is_not_zero_or_unconstrained():
    assert not match_units([unit(0)], q(units=[{"strength_min": 0}]))
    assert match_units([unit(0, strength=0.6)], q(units=[{"strength_min": 0.5}]))
    assert not match_units([unit(0, strength=0.6)], q(units=[{"strength_min": 0.7}]))
