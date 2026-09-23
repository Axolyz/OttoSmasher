import numpy as np
import pytest
import soundfile as sf

from ottosmasher import beat_reference as reference
from ottosmasher.boundaries import acoustic_crop, estimate_ctc_coverage
from ottosmasher.catalog import reading_text
from ottosmasher.rhythm_units import group_phones, measured_pauses


def fixture():
    units = []
    for i, t in enumerate([0.2, 0.4, 0.8, 1.0, 1.4, 1.6, 2.0]):
        p = {"label": "a", "phone": "a", "start": t, "end": t + 0.12, "mora_index": i}
        units.append(
            {
                "time": t,
                "end": t + 0.12,
                "members": [p],
                "label": "a",
                "phrase": 0,
                "phone_runs": [{"phone": "a", "start": t, "end": t + 0.12}],
            }
        )
    analysis = {
        "version": "fixture",
        "backend": "sofa",
        "window_start": 0,
        "window_end": 2.2,
        "mora": {"count": 7, "sequence": list("あ" * 7), "phone_mapping": "ordered_g2p"},
    }
    return {"id": "cue"}, analysis, {"units": units, "pauses": []}


def test_four_binary_densities_without_search(tmp_path, monkeypatch):
    monkeypatch.setattr(reference, "DATA", tmp_path)
    c, a, v = fixture()
    r = reference.generate_references(c, a, v)
    assert {p["density"] for p in r["plans"]} == {1, 2, 4, 8}
    assert r["plans"][0]["score"] == min(p["score"] for p in r["plans"])
    assert all(p["witness"] is None for p in r["plans"])
    for p in r["plans"]:
        assert p["unit_targets"][0]["target_beat"] == 0
        assert len(p["unit_targets"]) == len(v["units"])
        assert all(
            x["target_beat"] * p["density"] == round(x["target_beat"] * p["density"])
            for x in p["unit_targets"]
        )
        assert p["end_target"]["target_beat"] > p["unit_targets"][-1]["target_beat"]


def test_extension_adds_slots_not_onsets_and_manual_override():
    _c, a, v = fixture()
    v["units"][-1]["end"] += 0.8
    v["units"][-1]["phone_runs"][0]["end"] += 0.8
    r = reference.slot_reference(a, v, auto_long_vowels=True)
    assert r["slots"][-1]["text_mora_count"] == 1
    assert r["slots"][-1]["effective_slots"] > 1
    assert r["slots"][-1]["basis"] == "long_vowel_extension"
    assert len(r["slots"]) == len(v["units"])
    assert reference.slot_reference(a, v, overrides={"6": 2})["slots"][-1]["effective_slots"] == 2


def test_experiment_changes_internal_allocation_and_retains_phase(tmp_path, monkeypatch):
    monkeypatch.setattr(reference, "DATA", tmp_path)
    c, a, v = fixture()
    r = reference.generate_references(c, a, v, strategy="acoustic")
    assert any(p["changed_unit_indices"] for p in r["plans"])
    assert "periodicity" not in r
    assert r["plans"][0]["algorithm_evidence"]["source_tick_seconds"] > 0
    v["units"] = v["units"][:2]
    r = reference.generate_references(c, a, v, strategy="acoustic")
    assert r["plans"] and all(p["strategy"] == "acoustic" for p in r["plans"])


def test_text_whitespace_is_not_spoken():
    assert "きごう" not in reading_text("ねえ 何か言ってよ！")
    assert reading_text("どうしたの？　ボス\n早く進めよう").count("ぼす") == 1


def test_ctc_blank_does_not_cut_tail_or_split_continuous_vowel(tmp_path):
    sr = 16000
    y = np.zeros(sr * 2)
    y[3200:24000] = 0.2 * np.sin(np.arange(20800) * 2 * np.pi * 220 / sr)
    path = tmp_path / "v.wav"
    sf.write(path, y, sr)
    item = {
        "id": "c",
        "window_start": 0.0,
        "window_end": 2.0,
        "audio_lineage": {"audio_path": str(path)},
        "context": [{"id": "c", "start": 0.2, "end": 1.5}],
    }
    phones = [
        {"label": "o", "start": 0.3, "end": 0.32, "mora_index": 0},
        {"label": "o", "start": 0.4, "end": 0.42, "mora_index": 1},
    ]
    start, end, e = acoustic_crop(item, phones, {"phones": phones})
    assert end >= 1.5 and start < 0.3
    repaired = estimate_ctc_coverage(phones, e)
    assert repaired[-1]["end"] >= 1.5
    assert repaired[0]["emission_end"] == 0.32
    assert len(group_phones(repaired)) == 1
    assert len(group_phones(repaired, split_before=[1])) == 2


def test_short_quiet_core_inside_phone_detected_without_sil_label(tmp_path):
    sr = 16000
    y = np.ones(sr) * 0.2
    y[4800:7200] = 0.001
    path = tmp_path / "v.wav"
    sf.write(path, y, sr)
    a = {
        "audio_lineage": {"audio_path": str(path)},
        "window_start": 0,
        "phones": [{"label": "u", "start": 0, "end": 1}],
    }
    p = measured_pauses(a)
    assert len(p) == 1 and p[0]["preserve_audio"]
    assert p[0]["start"] == pytest.approx(0.32)
    assert p[0]["end"] == pytest.approx(0.43)


def test_quiet_seam_spanning_last_model_end_does_not_add_long_padding(tmp_path):
    sr = 16000
    y = np.zeros(sr * 2)
    y[3200:16000] = 0.2
    path = tmp_path / "tail.wav"
    sf.write(path, y, sr)
    phones = [{"label": "a", "start": 0.2, "end": 1.1}]
    item = {
        "id": "c",
        "window_start": 0.0,
        "window_end": 2.0,
        "audio_lineage": {"audio_path": str(path)},
        "context": [{"id": "c", "start": 0.2, "end": 1.6}],
    }
    _, end, e = acoustic_crop(item, phones, {"phones": phones})
    assert end == pytest.approx(1.15)
    assert not e["uncertain_end"]


def test_geminate_closure_is_not_an_extra_rest(tmp_path):
    sr = 16000
    y = np.ones(sr) * 0.2
    y[4800:8000] = 0
    path = tmp_path / "closure.wav"
    sf.write(path, y, sr)
    a = {
        "audio_lineage": {"audio_path": str(path)},
        "window_start": 0,
        "phones": [
            {"label": "a", "start": 0, "end": 0.3},
            {"label": "cl", "start": 0.3, "end": 0.5},
            {"label": "a", "start": 0.5, "end": 1.0},
        ],
    }
    assert measured_pauses(a) == []


def test_experiment_comparison_is_the_actual_independent_baseline(tmp_path, monkeypatch):
    monkeypatch.setattr(reference, "DATA", tmp_path)
    c, a, v = fixture()
    v["pauses"] = [{"start": 0.52, "end": 0.68}]
    base = {p["density"]: p for p in reference.generate_references(c, a, v)["plans"]}
    experiment = reference.generate_references(c, a, v, strategy="acoustic")["plans"]
    for p in experiment:
        assert [u["baseline_target_beat"] for u in p["unit_targets"]] == [
            u["target_beat"] for u in base[p["density"]]["unit_targets"]
        ]
