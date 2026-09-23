"""Timing contracts for independent text, guided and acoustic rhythm references."""

from copy import deepcopy
from itertools import pairwise

import pytest
import test_vocals

from ottosmasher import beat_reference as reference
from ottosmasher import quantization
from ottosmasher.workspace import write_json

separated_cue = test_vocals.separated_cue


def speech_fixture(durations=(0.11, 0.22, 0.10, 0.32, 0.11), counts=None):
    """Measured units are already grouped; durations include the final vowel tail."""
    counts = counts or [1] * len(durations)
    units = []
    time = 0.2
    mora_index = 0
    for duration, count in zip(durations, counts, strict=True):
        phone = {
            "label": "a",
            "phone": "a",
            "start": time,
            "end": time + duration,
            "mora_index": mora_index,
        }
        units.append(
            {
                "time": time,
                "end": time + duration,
                "duration": duration,
                "label": "a",
                "members": [phone],
                "phone_runs": [{"phone": "a", "start": time, "end": time + duration}],
                "phrase": 0,
                "strength": 1.0,
            }
        )
        time += duration
        mora_index += count
    analysis = {
        "version": "three-route-fixture",
        "backend": "narabas",
        "window_start": 0,
        "window_end": time + 0.1,
        "mora": {
            "count": sum(counts),
            "sequence": ["あ"] * sum(counts),
            "reading": "あ" * sum(counts),
            "phone_mapping": "ordered_g2p",
        },
    }
    return {"id": "three-route-cue", "reading": "あ" * sum(counts)}, analysis, {"units": units, "pauses": []}


@pytest.fixture(autouse=True)
def isolated_plans(tmp_path, monkeypatch):
    monkeypatch.setattr(reference, "DATA", tmp_path)
    monkeypatch.setattr(quantization, "DATA", tmp_path)


def plans_for(cue, analysis, view, **kwargs):
    result = reference.generate_references(cue, analysis, view, **kwargs)
    assert result["plans"], result.get("conflicts")
    return {p["density"]: p for p in result["plans"]}


def occupancies(plan):
    return [s["effective_slots"] for s in plan["slots"]]


def musical_mapping(plan):
    return (
        [u["target_beat"] for u in plan["unit_targets"]],
        plan["end_target"],
        plan["duration_multiplier"],
        plan["estimated_duration_seconds"],
        occupancies(plan),
        plan["algorithm_evidence"]["source_tick_seconds"],
    )


def test_pure_mora_preserves_text_counts_with_extension_off():
    c, a, v = speech_fixture((0.1, 0.1, 0.1, 0.8), counts=[1, 3, 2, 1])
    plain = plans_for(c, a, v, strategy="mora", auto_long_vowels=False)
    extended = plans_for(c, a, v, strategy="mora", auto_long_vowels=True)
    for density, p in plain.items():
        assert occupancies(p) == [1, 3, 2, 1]
        assert [s["text_mora_count"] for s in p["slots"]] == [1, 3, 2, 1]
        assert occupancies(extended[density])[-1] > 1
        assert len(extended[density]["unit_targets"]) == 4
        assert p["plan_id"] != extended[density]["plan_id"]


def test_pure_mora_missing_mapping_is_explicit_not_duration_inference():
    c, a, v = speech_fixture()
    for unit in v["units"]:
        unit["members"][0].pop("mora_index")
    result = reference.generate_references(c, a, v, strategy="mora", auto_long_vowels=False)
    assert not result["plans"]
    assert result["conflicts"] or result.get("message")
    # The recorded waveform is still enough for the independent acoustic route.
    assert plans_for(c, a, v, strategy="acoustic")


def test_acoustic_mapping_is_independent_of_all_mora_metadata():
    c, a, v = speech_fixture()
    original = plans_for(c, a, v, strategy="acoustic")
    changed_c, changed_a, changed_v = deepcopy((c, a, v))
    changed_c["reading"] = "ちいいっねええええええ"
    changed_a["mora"] = {
        "count": 70,
        "sequence": ["ね"] * 70,
        "reading": "ね" * 70,
        "phone_mapping": "ordered_g2p",
    }
    for index, unit in enumerate(changed_v["units"]):
        unit["members"][0]["mora_index"] = index * 12
    changed = plans_for(changed_c, changed_a, changed_v, strategy="acoustic")
    absent_c, absent_a, absent_v = deepcopy((c, a, v))
    absent_c.pop("reading")
    absent_a.pop("mora")
    for unit in absent_v["units"]:
        unit["members"][0].pop("mora_index")
    absent = plans_for(absent_c, absent_a, absent_v, strategy="acoustic")
    for density in original:
        assert musical_mapping(original[density]) == musical_mapping(changed[density])
        assert musical_mapping(original[density]) == musical_mapping(absent[density])


def test_acoustic_recovers_nonuniform_rhythm_without_mora_extension():
    c, a, v = speech_fixture()
    result = plans_for(c, a, v, strategy="acoustic")
    for p in result.values():
        assert occupancies(p) == [1, 2, 1, 3, 1]
        tick = p["algorithm_evidence"]["source_tick_seconds"]
        assert tick == pytest.approx(0.11, abs=0.025)
        assert len(p["unit_targets"]) == len(v["units"])
        assert p["end_target"]["source_seconds"] == pytest.approx(v["units"][-1]["end"])


@pytest.mark.parametrize("count", [1, 2, 3])
def test_short_acoustic_sentence_works_without_periodicity_or_mora(count):
    c, a, v = speech_fixture((0.1, 0.2, 0.1)[:count])
    c.pop("reading")
    a.pop("mora")
    for unit in v["units"]:
        unit["members"][0].pop("mora_index")
    result = reference.generate_references(c, a, v, strategy="acoustic")
    assert len(result["plans"]) == 4
    assert "periodicity" not in result
    for p in result["plans"]:
        assert len(p["unit_targets"]) == count
        assert all(s["effective_slots"] >= 1 for s in p["slots"])
        assert p["end_target"]["target_beat"] > p["unit_targets"][-1]["target_beat"]


def test_guided_can_shrink_and_grow_occupancy_beyond_one_cell():
    c, a, v = speech_fixture((0.1, 0.4, 0.1, 0.1, 0.1, 0.4, 0.1), counts=[4, 1, 1, 1, 1, 1, 1])
    plain = plans_for(c, a, v, strategy="mora", auto_long_vowels=False)[4]
    guided = plans_for(c, a, v, strategy="mora_guided", auto_long_vowels=False)[4]
    changes = [g - m for g, m in zip(occupancies(guided), occupancies(plain), strict=True)]
    assert min(changes) <= -2
    assert max(changes) >= 2


@pytest.mark.parametrize("strategy", ["mora", "mora_guided", "acoustic"])
def test_densities_render_one_inferred_pattern_and_select_nearest_speed(strategy):
    c, a, v = speech_fixture()
    result = reference.generate_references(c, a, v, bpm=137, strategy=strategy)
    plans = result["plans"]
    assert {p["density"] for p in plans} == {1, 2, 4, 8}
    assert plans[0]["score"] == min(p["score"] for p in plans)
    patterns = []
    tail_cells = []
    for p in plans:
        density = p["density"]
        cells = [u["target_beat"] * density for u in p["unit_targets"]]
        assert cells[0] == 0
        assert all(x == pytest.approx(round(x)) for x in cells)
        assert all(b > a for a, b in pairwise(cells))
        patterns.append(cells)
        tail_cells.append(p["end_target"]["target_beat"] * density)
        assert p["version"] == "binary-reference-v5"
        assert p["meter"] == [4, 4]
        assert p["witness"] is None
        assert p["retrieval_score_unchanged"]
    assert all(pattern == patterns[0] for pattern in patterns)
    assert all(end == tail_cells[0] for end in tail_cells)
    assert len({p["estimated_duration_seconds"] for p in plans}) == 4


def test_merged_long_vowel_and_geminate_occupancy_do_not_create_onsets():
    c, a, v = speech_fixture((0.3, 0.2, 0.1), counts=[3, 2, 1])
    # One perceptual long-vowel unit spans three explicitly indexed phones.
    first = v["units"][0]
    first["members"] = [
        {"label": "i", "start": 0.2 + 0.1 * i, "end": 0.3 + 0.1 * i, "mora_index": i} for i in range(3)
    ]
    # A geminate consumes the mora before the next onset; it is not a new unit.
    v["units"][1]["members"].append({"label": "cl", "start": 0.6, "end": 0.7, "mora_index": 4})
    for strategy in ("mora", "mora_guided", "acoustic"):
        p = plans_for(c, a, v, strategy=strategy)[4]
        assert len(p["unit_targets"]) == 3
        assert len(p["slots"]) == 3
    assert occupancies(plans_for(c, a, v, strategy="mora", auto_long_vowels=False)[4]) == [3, 2, 1]


def test_acoustic_pause_has_independent_rest_cells_and_retains_tail():
    c, a, v = speech_fixture((0.1, 0.2, 0.1))
    base = plans_for(c, a, v, strategy="acoustic")[4]
    # Insert one second of measured elastic pause without changing voiced durations.
    for unit in v["units"][1:]:
        unit["time"] += 1.0
        unit["end"] += 1.0
        unit["phrase"] = 1
        for phone in unit["members"] + unit["phone_runs"]:
            phone["start"] += 1.0
            phone["end"] += 1.0
    v["pauses"] = [{"start": 0.3, "end": 1.3, "preserve_audio": True}]
    a["window_end"] += 1.0
    paused = plans_for(c, a, v, strategy="acoustic")[4]
    assert occupancies(paused) == occupancies(base)
    assert paused["slots"][0]["rest_slots_after"] > 0
    assert paused["slots"][1]["rest_slots_after"] == 0
    assert paused["end_target"]["source_seconds"] == pytest.approx(v["units"][-1]["end"])
    assert len(paused["unit_targets"]) == 3
    assert paused["pauses"][0]["preserve_audio"]


def test_persisted_plan_preserves_selected_route_and_rejects_obsolete_versions(tmp_path):
    c, a, v = speech_fixture()
    plan = plans_for(c, a, v, strategy="acoustic")[4]
    loaded = quantization.load_plan(plan["plan_id"], c["id"], a, v)
    assert loaded["strategy"] == "acoustic"
    assert musical_mapping(loaded) == musical_mapping(plan)
    changed_view = deepcopy(v)
    changed_view["units"][0]["time"] += 0.001
    with pytest.raises(ValueError, match="changed|regenerate"):
        quantization.load_plan(plan["plan_id"], c["id"], a, changed_view)
    obsolete = {**plan, "version": "binary-reference-v2"}
    write_json(tmp_path / "quantization-plans" / (plan["plan_id"] + ".json"), obsolete)
    with pytest.raises(ValueError, match="changed|regenerate"):
        quantization.load_plan(plan["plan_id"], c["id"], a, v)


def test_route_comparison_metadata_matches_independently_generated_mappings():
    c, a, v = speech_fixture()
    routes = {name: plans_for(c, a, v, strategy=name) for name in ("mora", "mora_guided", "acoustic")}
    for name, densities in routes.items():
        for density, plan in densities.items():
            actual_same = set()
            for other_name, other_densities in routes.items():
                other = other_densities[density]
                for index, slot in enumerate(plan["slots"]):
                    assert slot["comparison_slots"][other_name] == occupancies(other)[index]
                if other_name != name and musical_mapping(plan)[:5] == musical_mapping(other)[:5]:
                    actual_same.add(other_name)
            assert set(plan["same_as_strategies"]) == actual_same


def test_extension_toggle_is_part_of_plan_identity_but_does_not_leak_into_acoustic():
    c, a, v = speech_fixture((0.1, 0.1, 0.1, 0.8))
    disabled = plans_for(c, a, v, strategy="acoustic", auto_long_vowels=False)[4]
    enabled = plans_for(c, a, v, strategy="acoustic", auto_long_vowels=True)[4]
    assert musical_mapping(disabled) == musical_mapping(enabled)
    assert disabled["plan_id"] != enabled["plan_id"]
    assert disabled["auto_long_vowels"] is False
    assert enabled["auto_long_vowels"] is True


def test_missing_mora_can_be_filled_explicitly_without_inventing_text_counts():
    c, a, v = speech_fixture((0.1, 0.2))
    for unit in v["units"]:
        unit["members"][0].pop("mora_index")
    p = plans_for(c, a, v, strategy="mora", overrides={"0": 2, "1": 3})[4]
    assert occupancies(p) == [2, 3]
    assert all(slot["text_mora_count"] is None for slot in p["slots"])
    assert all(slot["basis"] == "manual" for slot in p["slots"])
    assert len(p["unit_targets"]) == 2




def test_one_very_short_mark_does_not_force_whole_sentence_to_tiny_ruler():
    # Real SOFA failure shape: a 11 ms inter-onset interval amidst ordinary
    # speech previously forced even the fastest allowed grid to >2x length.
    durations = (
        0.6762,
        0.0725,
        0.122,
        0.2002,
        0.1829,
        0.1833,
        0.0112,
        0.2815,
        0.1393,
        0.1305,
        0.0784,
        0.0872,
        0.209,
    )
    c, a, v = speech_fixture(durations)
    # The same sentence has a real pause before the short marked interval.
    pause_start = v["units"][6]["time"]
    for unit in v["units"][6:]:
        unit["time"] += 0.36
        unit["end"] += 0.36
        unit["phrase"] = 1
        for phone in unit["members"] + unit["phone_runs"]:
            phone["start"] += 0.36
            phone["end"] += 0.36
    v["pauses"] = [{"start": pause_start, "end": pause_start + 0.36}]
    a["window_end"] += 0.36
    p = plans_for(c, a, v, strategy="acoustic")[8]
    assert len(p["unit_targets"]) == len(durations)
    assert p["slots"][6]["effective_slots"] >= 1
    assert p["duration_multiplier"] < 1.5
    assert p["algorithm_evidence"]["costs"]["mora_prior_weight"] == 0


def test_tiny_pause_overlap_does_not_create_an_extra_full_rest_cell():
    c, a, v = speech_fixture((0.2, 0.1, 0.2))
    # A real quiet interval extends 0.4 ms beyond the next model onset.
    second = v["units"][1]["time"]
    v["pauses"] = [{"start": second - 0.12, "end": second + 0.0004}]
    p = plans_for(c, a, v, strategy="acoustic")[4]
    assert p["slots"][0]["rest_slots_after"] > 0
    assert p["slots"][1]["rest_slots_after"] == 0
    assert p["pauses"] == v["pauses"]  # Keep the source gap for non-destructive rendering.
