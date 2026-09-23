"""Compiled-pattern retrieval preserves the exact rhythm used by audition/export."""

from copy import deepcopy
from types import SimpleNamespace

import numpy as np
import pytest

from ottosmasher.quantized_match import match_pattern


def pattern(beats=(0, 0.5, 1), *, density=2, source=(2, 2.1, 2.4), end=2.6):
    units = [
        {
            "time": t,
            "end": t + 0.05,
            "phone": "a",
            "label": "a",
            "strength": 0.8,
            "phone_runs": [{"phone": "a", "start": t, "end": t + 0.05}],
        }
        for t in source
    ]
    final = beats[-1] + 1 / density
    factor = final * 0.5 / (end - source[0])
    return {
        "pattern_id": "compiled-fixture",
        "units": units,
        "scope": {"kind": "whole", "source_start": 1.9, "source_end": end + 0.1},
        "plan": {
            "density": density,
            "strategy": "acoustic",
            "beat_seconds": 0.5,
            "duration_multiplier": factor,
            "unit_targets": [
                {"unit_index": i, "source_seconds": t, "target_beat": b}
                for i, (t, b) in enumerate(zip(source, beats, strict=True))
            ],
            "end_target": {"source_seconds": end, "target_beat": final},
            "pauses": [],
        },
    }


def note(start, end, **kwargs):
    return {"start_beats": start, "end_beats": end, **kwargs}


def query(notes=None, **kwargs):
    values = {
        "bpm": 120,
        "tolerance_beats": 0.1,
        "densities": [1, 2, 4, 8],
        "strategy": "acoustic",
        "scope": "both",
        "boundary": "anywhere",
        "notes": notes or [note(0, 0.25)],
        "cells": [],
        "span_beats": 8,
        "speed_filter": False,
        "factor_min": 0.85,
        "factor_max": 1.18,
    }
    values.update(kwargs)
    return SimpleNamespace(**values)


def test_beginning_and_ending_use_scope_onsets_and_keep_outer_audio():
    p = pattern()
    result = match_pattern(p, query([note(3, 3.3), note(4, 4.3)], boundary="both"))
    assert result["matched_anchor_indices"] == [0, 2]
    assert result["anchor_beats"] == pytest.approx([3, 3.5, 4])
    assert result["time_map"]["knots"][0][0] == 1.9
    assert result["time_map"]["knots"][0][1] < 1.5
    assert result["shifted_end_target"]["target_beat"] == pytest.approx(4.5)
    assert result["time_map"]["knots"][-1][0] == pytest.approx(2.7)
    assert match_pattern(p, query([note(0, 0.2)], boundary="start"))["matched_anchor_indices"] == [0]
    assert match_pattern(p, query([note(0, 0.2)], boundary="end"))["matched_anchor_indices"] == [2]
    assert match_pattern(p, query([note(0, 0.2)], boundary="both")) is None


def test_extra_onsets_inside_blocks_fail_even_when_required_points_match():
    p = pattern((0, 0.125, 0.25, 0.375), density=8, source=(2, 2.1, 2.2, 2.3), end=2.4)
    assert match_pattern(p, query([note(0, 0.375), note(0.375, 0.5)], boundary="both")) is None
    # The note end is half-open: a following onset exactly at that edge is legal.
    assert match_pattern(p, query([note(0, 0.125), note(0.375, 0.5)], boundary="both"))


def test_midpoint_translation_finds_a_fit_that_neither_anchor_center_can_supply():
    p = pattern((0, 1), density=1, source=(2, 2.2), end=2.4)
    result = match_pattern(p, query([note(0, 0.2), note(1.15, 1.3)], boundary="both", tolerance_beats=0.08))
    assert result is not None
    assert result["max_error_beats"] <= 0.08
    assert result["placement_beats"] == pytest.approx(0.075)
    assert np.diff(result["anchor_beats"]) == pytest.approx([1])
    assert result["rhythm_error"] == pytest.approx(0.075)


def test_target_bpm_scales_seconds_but_does_not_reinterpret_grid_density():
    p = pattern()
    slow = match_pattern(p, query([note(0, 0.2), note(1, 1.2)], boundary="both", bpm=120))
    fast = match_pattern(p, query([note(0, 0.2), note(1, 1.2)], boundary="both", bpm=240))
    assert slow["anchor_beats"] == fast["anchor_beats"]
    assert fast["duration_multiplier"] == pytest.approx(slow["duration_multiplier"] / 2)
    assert slow["density"] == fast["density"] == 2
    assert match_pattern(p, query(densities=[4])) is None
    assert match_pattern(p, query(speed_filter=True, factor_min=0.9, factor_max=1.1)) is None


def test_attributes_use_actual_piecewise_unit_or_requested_phone_duration():
    p = pattern()
    # 50 ms in the first 100 ms source interval occupies .25 target beats.
    assert match_pattern(
        p,
        query([note(0, 0.2, phone="a", duration_min_beats=0.24, duration_max_beats=0.26)], boundary="start"),
    )
    assert match_pattern(p, query([note(0, 0.2, duration_max_beats=0.2)], boundary="start")) is None
    p["units"][0]["phone_runs"].append({"phone": "i", "start": 2.05, "end": 2.08})
    assert (
        match_pattern(
            p,
            query(
                [note(0, 0.2, phone="i", duration_min_beats=0.14, duration_max_beats=0.16)], boundary="start"
            ),
        )
        is None
    )
    assert match_pattern(p, query([note(0, 0.2, phone="u")], boundary="start")) is None
    assert match_pattern(p, query([note(0, 0.2, strength_min=0.9)], boundary="start")) is None
    p["units"][0]["strength"] = None
    assert match_pattern(p, query([note(0, 0.2, strength_min=0.1)], boundary="start")) is None


def test_unknown_duration_cannot_pass_duration_filter():
    p = pattern()
    p["units"][0].pop("end")
    assert match_pattern(p, query([note(0, 0.2, duration_min_beats=0)], boundary="start")) is None


def test_legacy_cells_keep_forbidden_positions_and_ordered_injective_hits():
    p = pattern()
    q = query(
        notes=[],
        cells=[{"state": "required"}, {"state": "forbidden"}, {"state": "required"}],
        step_beats=0.5,
        boundary="both",
    )
    q.notes = []
    assert match_pattern(p, q) is None
    q.cells[1]["state"] = "any"
    result = match_pattern(p, q)
    assert result["matched_anchor_indices"] == [0, 2]
    assert result["target_beats"] == [0, 1]


def test_exact_quantized_fit_retains_source_deformation_and_speed_costs():
    p = pattern()
    result = match_pattern(p, query([note(0, 0.2), note(1, 1.2)], boundary="both"))
    assert result["rhythm_error"] == pytest.approx(0)
    assert result["deformation_penalty"] > 0
    assert result["speed_penalty"] > 0
    assert result["cost"] > 0


def test_match_does_not_mutate_pattern_or_call_audio_or_optimizer(monkeypatch):
    import scipy.optimize

    from ottosmasher import beat_reference, rhythm_allocation

    def forbidden(*args, **kwargs):
        raise AssertionError("Compiled pattern search must not infer, optimize or load audio")

    monkeypatch.setattr(scipy.optimize, "linprog", forbidden)
    monkeypatch.setattr(beat_reference, "generate_references", forbidden)
    monkeypatch.setattr(rhythm_allocation, "infer_pattern", forbidden)
    p = pattern()
    saved = deepcopy(p)
    assert match_pattern(p, query())
    assert p == saved


def test_scoped_patterns_match_their_own_ends_and_respect_scope_filter():
    p = pattern()
    p["scope"].update(kind="segment", scope_id="parent-segment-1", parent_unit_indices=[5, 6, 7])
    result = match_pattern(p, query([note(0, 0.2)], boundary="end", scope="segments"))
    assert result["matched_anchor_indices"] == [2]
    assert result["scope"]["parent_unit_indices"][-1] == 7
    assert match_pattern(p, query(scope="whole")) is None


def test_malformed_or_nonmonotonic_compiled_mapping_fails_without_guessing():
    p = pattern()
    p["plan"]["unit_targets"][1]["source_seconds"] = 1.8
    assert match_pattern(p, query()) is None
    p = pattern()
    p["plan"]["unit_targets"].pop()
    assert match_pattern(p, query()) is None


def composition(segments=2):
    source = [2 + j + k * 0.1 for j in range(segments) for k in (0, 1)]
    beats = [j * 2 + k * 0.5 for j in range(segments) for k in (0, 1)]
    p = pattern(beats, source=source, end=2 + segments - 1 + 0.2)
    p["plan"].update(
        composition=True,
        grid_beats=0.5,
        links=[
            {
                "link_index": j,
                "after_unit_index": j * 2 + 1,
                "next_unit_index": j * 2 + 2,
                "source_start": 2 + j + 0.2,
                "source_end": 3 + j,
                "rest_cells": 2,
                "min_rest_cells": 1,
                "max_rest_cells": 32,
            }
            for j in range(segments - 1)
        ],
        control_targets=[
            {
                "source_seconds": 2 + j + 0.2,
                "target_beat": j * 2 + 1,
                "after_unit_index": j * 2 + 1,
                "role": "segment_end",
            }
            for j in range(segments - 1)
        ],
        slots=[
            {"effective_slots": 1, "rest_slots_after": 2 if i % 2 and i < segments * 2 - 1 else 0}
            for i in range(segments * 2)
        ],
    )
    return p


def test_adjacent_gap_change_preserves_each_segment_and_its_tail_control():
    p = composition()
    saved = deepcopy(p)
    q = query([note(t, t + 0.25) for t in (0, 0.5, 1.5, 2)], boundary="both", adjust_pauses=True)
    result = match_pattern(p, q)
    assert result["anchor_beats"] == pytest.approx([0, 0.5, 1.5, 2])
    assert result["shifted_control_targets"][0]["target_beat"] == pytest.approx(1)
    assert result["shifted_end_target"]["target_beat"] == pytest.approx(2.5)
    assert result["rest_adjustments"][0]["delta_cells"] == -1
    assert result["adjusted_links"][0]["rest_cells"] == 1
    assert result["shifted_slots"] == saved["plan"]["slots"]
    assert result["rest_search"]["complete"]
    assert result["rest_search"]["evaluated_variants"] == 32
    assert p == saved
    assert match_pattern(p, query(q.notes, boundary="both", adjust_pauses=False)) is None


def test_adjusted_gap_still_obeys_protected_note_exclusions():
    p = composition()
    # Moving segment B to 1.5 leaves its first onset inside the first block.
    assert (
        match_pattern(p, query([note(0, 1.75), note(2, 2.25)], boundary="both", adjust_pauses=True)) is None
    )
    result = match_pattern(p, query([note(0.5, 1.5), note(1.5, 2)], boundary="anywhere", adjust_pauses=True))
    assert result is not None
    for j, index in enumerate(result["matched_anchor_indices"]):
        n = [note(0.5, 1.5), note(1.5, 2)][j]
        assert not any(
            i != index and n["start_beats"] <= b < n["end_beats"]
            for i, b in enumerate(result["anchor_beats"])
        )


def test_link_cannot_delete_gap_or_tail_or_apply_the_shift_twice():
    p = composition()
    # The two complete segments occupy two beats even before the positive gap.
    assert (
        match_pattern(
            p,
            query([note(0, 0.2), note(1.5, 1.7)], boundary="both", adjust_pauses=True, tolerance_beats=0.05),
        )
        is None
    )
    result = match_pattern(p, query([note(0, 0.2), note(4, 4.2)], boundary="both", adjust_pauses=True))
    assert result["anchor_beats"] == pytest.approx([0, 0.5, 3.5, 4])
    assert result["shifted_end_target"]["target_beat"] == pytest.approx(4.5)
    assert result["shifted_control_targets"][0]["target_beat"] == pytest.approx(1)
    assert result["rest_adjustments"][0]["delta_cells"] == 3


def test_multilink_candidates_are_bounded_and_preserve_the_default_on_equal_fit():
    p = composition(4)
    notes = [note(0, 0.2), note(6.5, 6.7)]
    result = match_pattern(p, query(notes, boundary="both", adjust_pauses=True))
    assert result["rest_search"]["domain_size"] == 32**3
    assert result["rest_search"]["evaluated_variants"] <= 128
    assert result["rest_search"]["complete"] is False
    assert result["search_complete"] is False
    assert result["pause_adjusted"] is False
    assert [x["rest_cells"] for x in result["adjusted_links"]] == [2, 2, 2]
    assert [x["target_beat"] for x in result["shifted_control_targets"]] == [1, 3, 5]


def test_multilink_span_proposal_changes_only_gaps_and_keeps_tails_monotonic():
    p = composition(4)
    result = match_pattern(p, query([note(0, 0.2), note(5, 5.2)], boundary="both", adjust_pauses=True))
    assert result is not None
    assert [x["rest_cells"] for x in result["adjusted_links"]] == [1, 1, 1]
    assert result["anchor_beats"] == pytest.approx([0, 0.5, 1.5, 2, 3, 3.5, 4.5, 5])
    assert [x["target_beat"] for x in result["shifted_control_targets"]] == pytest.approx([1, 2.5, 4])
    assert all(b[1] > a[1] for a, b in zip(result["time_map"]["knots"], result["time_map"]["knots"][1:]))


def test_segment_tail_control_is_used_for_duration_filter_not_next_segment_head():
    p = composition()
    # The second onset's vowel lasts half its .1 s span to the protected tail,
    # thus .25 beats, regardless of the .8 s following source pause.
    result = match_pattern(
        p,
        query([note(0, 0.2, duration_min_beats=0.24, duration_max_beats=0.26)], boundary="end"),
    )
    assert result is not None
    p["units"][1]["phone"] = "i"
    p["units"][1]["phone_runs"][0]["phone"] = "i"
    assert match_pattern(
        p, query([note(0, 0.2, phone="i", duration_min_beats=0.24, duration_max_beats=0.26)])
    )
