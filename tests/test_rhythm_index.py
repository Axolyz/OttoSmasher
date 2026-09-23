"""Index lifecycle, scope retrieval and exact match-plan handoff contracts."""

from copy import deepcopy

import numpy as np
import pytest
import soundfile as sf
import test_vocals

from ottosmasher import beat_reference, rhythm_index, workspace
from ottosmasher import cue_operations as ops
from ottosmasher.quantized_match import match_pattern
from ottosmasher.rhythm import RhythmQuery

separated_cue = test_vocals.separated_cue


@pytest.fixture
def indexed_cue(separated_cue):
    import hashlib
    from pathlib import Path

    db, cue, lineage = separated_cue
    y, sr = sf.read(lineage["audio_path"])
    y[round(0.65 * sr) : round(1.45 * sr)] = 0
    sf.write(lineage["audio_path"], y, sr)
    lineage["audio_sha256"] = hashlib.sha256(Path(lineage["audio_path"]).read_bytes()).hexdigest()
    phones, anchors = [], []
    for i, t in enumerate((0.2, 0.45, 1.6, 1.85)):
        phones.extend(
            [
                {"label": "k", "start": t - 0.06, "end": t, "mora_index": i},
                {"label": "a", "start": t, "end": t + 0.13, "mora_index": i},
            ]
        )
        anchors.append({"time": t, "end": t + 0.13, "duration": 0.13, "phone": "a", "strength": 0.7})
    analysis = {
        "version": "index-fixture-v1",
        "backend": "narabas",
        "input_variant": "vocals",
        "audio_lineage": lineage,
        "window_start": 0,
        "window_end": 3,
        "phones": phones,
        "anchors": anchors,
        "flags": [],
        "verified": False,
        "mora": {"count": 4, "sequence": ["か"] * 4, "reading": "かかかか", "phone_mapping": "ordered_g2p"},
    }
    workspace.save_analysis(db, cue["id"], "narabas", analysis["version"], analysis)
    record, entry = rhythm_index.entry_for(db, cue["id"], "narabas")
    assert len(record["entries"]) == 3
    return db, cue, analysis, record, entry


def query_for(pattern, **extra):
    beats = [u["target_beat"] for u in pattern["plan"]["unit_targets"]]
    return RhythmQuery(
        mode="narabas",
        strategy="acoustic",
        bpm=120,
        scope="segments",
        boundary="both",
        densities=[pattern["plan"]["density"]],
        tolerance_beats=0.02,
        notes=[{"start_beats": b, "end_beats": b + 0.05} for b in beats],
        span_beats=beats[-1] + 0.1,
        **extra,
    )


def test_compiled_patterns_preserve_whole_free_quantization(indexed_cue):
    _, cue, analysis, _record, entry = indexed_cue
    view = entry["view"]
    for strategy in beat_reference.STRATEGIES:
        generated = beat_reference.generate_references(cue, analysis, view, strategy=strategy, persist=False)
        for plan in generated["plans"]:
            p = rhythm_index.prototype(entry, strategy, plan["density"])["plan"]
            assert [t["target_beat"] for t in p["unit_targets"]] == [
                t["target_beat"] for t in plan["unit_targets"]
            ]
            assert p["end_target"] == plan["end_target"]
            assert p["duration_multiplier"] == plan["duration_multiplier"]
            assert p["local_duration_ratios"] == pytest.approx(plan["local_duration_ratios"])


def test_warm_search_uses_no_waveform_or_inference_and_keeps_selected_map(indexed_cue, monkeypatch):
    db, cue, _analysis, record, _entry = indexed_cue
    segment = record["entries"][1]
    pattern = rhythm_index.prototype(segment, "acoustic", 2)
    query = query_for(pattern)

    def forbidden(*args, **kwargs):
        raise AssertionError("Search must not reload audio or infer a rhythm")

    monkeypatch.setattr(rhythm_index, "compile_reference", forbidden)
    monkeypatch.setattr(beat_reference, "compile_reference", forbidden)
    monkeypatch.setattr(rhythm_index, "get_rhythm_view", forbidden)
    result = rhythm_index.search_index(db, query)
    assert result["index_status"]["rebuilt_cues"] == 0
    hit = next(h for h in result["results"] if h["scope"]["scope_id"] == segment["scope"]["scope_id"])
    assert hit["matched_anchor_indices"] == [0, 1]
    _, selected_analysis, plan = ops.resolve_plan(db, cue["id"], "narabas", hit["plan_id"])
    assert selected_analysis["audio_selection"]["scope_id"] == hit["scope"]["scope_id"]
    assert [u["target_beat"] for u in plan["unit_targets"]] == hit["anchor_beats"]


def test_scoped_quantization_restarts_ruler_and_mora_count(indexed_cue):
    _, cue, _, record, _whole = indexed_cue
    first, second = record["entries"][1:]
    assert first["analysis"]["mora"]["count"] == second["analysis"]["mora"]["count"] == 2
    for segment in (first, second):
        actual = beat_reference.compile_reference(cue, segment["analysis"], segment["view"])
        assert actual["routes"]["acoustic"] == segment["compiled"]["routes"]["acoustic"]
        assert rhythm_index.prototype(segment, "acoustic", 2)["plan"]["unit_targets"][0]["target_beat"] == 0


def test_link_edits_preserve_internal_heads_tails_and_selected_plan(indexed_cue):
    db, cue, _, record, entry = indexed_cue
    baseline = rhythm_index.compose_pattern(record, "acoustic", 2)
    changed = rhythm_index.compose_pattern(record, "acoustic", 2, {"0": 5})
    cut = changed["plan"]["links"][0]["next_unit_index"]
    for start, stop in ((0, cut), (cut, len(entry["view"]["units"]))):
        a = [t["target_beat"] for t in baseline["plan"]["unit_targets"][start:stop]]
        b = [t["target_beat"] for t in changed["plan"]["unit_targets"][start:stop]]
        assert np.diff(a) == pytest.approx(np.diff(b))
    assert baseline["plan"]["control_targets"][0] == changed["plan"]["control_targets"][0]
    q = query_for(changed, adjust_pauses=True).model_copy(update={"scope": "whole"})
    match = match_pattern(baseline, q)
    assert match["adjusted_links"][0]["rest_cells"] == 5
    plan = rhythm_index.materialize_match(record, entry, match, q)
    assert plan["links"][0]["rest_cells"] == 5
    assert plan["unit_targets"] == match["shifted_unit_targets"]
    assert plan["control_targets"] == match["shifted_control_targets"]
    assert plan["witness"]["time_map"] == match["time_map"]
    assert ops.resolve_plan(db, cue["id"], "narabas", plan["plan_id"])[2] == plan


def test_unavailable_route_remains_indexed_failure_not_fallback(indexed_cue):
    db, cue, analysis, _, _ = indexed_cue
    changed = deepcopy(analysis)
    for p in changed["phones"]:
        p.pop("mora_index", None)
    workspace.save_analysis(db, cue["id"], "narabas", changed["version"], changed)
    record, entry = rhythm_index.entry_for(db, cue["id"], "narabas")
    assert "mora" not in entry["compiled"]["routes"]
    assert rhythm_index.reference_plans(record, entry, strategy="mora")["plans"] == []
    assert rhythm_index.reference_plans(record, entry, strategy="acoustic")["plans"]


def test_default_long_connecting_rest_is_not_truncated_to_search_budget(indexed_cue):
    _, _, _, record, _ = indexed_cue
    record = deepcopy(record)
    last = record["entries"][-1]
    for u in last["view"]["units"]:
        u["time"] += 10
        u["end"] += 10
    last["compiled"]["measured"]["end"] += 10
    pattern = rhythm_index.compose_pattern(record, "acoustic", 2)
    link = pattern["plan"]["links"][0]
    assert link["rest_cells"] > 32
    assert link["rest_cells"] == link["default_rest_cells"] == link["max_rest_cells"]


def test_indexed_render_trims_empty_canvas_but_keeps_selected_audio_and_cores(indexed_cue, monkeypatch):
    from ottosmasher import media, strict_audio

    _, cue, _, record, _ = indexed_cue
    monkeypatch.setattr(strict_audio, "DATA", workspace.DATA)
    segment = record["entries"][1]
    plan = rhythm_index.reference_plans(record, segment, strategy="acoustic", density=1)["plans"][0]
    for p in plan["unit_targets"]:
        p["target_beat"] += 16
    plan["end_target"]["target_beat"] += 16
    plan["witness"] = {"query_span_beats": 1024}
    plan = rhythm_index.save_plan(plan, segment)
    a = segment["analysis"]
    raw, raw_meta = media.render(
        cue, variant="vocals", lineage=a["audio_lineage"], selection=a["audio_selection"]
    )
    target, meta = strict_audio.render_strict(cue, a, plan)
    assert meta["actual_duration"] < 5
    assert meta["timeline_start_seconds"] > 0
    original, _ = sf.read(raw, always_2d=True)
    rendered, _ = sf.read(target, always_2d=True)
    assert meta["source_start"] == raw_meta["source_start"]
    assert meta["source_end"] == raw_meta["source_end"]
    for core in meta["cores"]:
        assert np.array_equal(
            original[core["source_start"] : core["source_end"]],
            rendered[core["target_start"] : core["target_end"]],
        )


def test_concurrent_plan_writes_are_atomic(tmp_path):
    import json
    from concurrent.futures import ThreadPoolExecutor

    path = tmp_path / "plan.json"
    with ThreadPoolExecutor(max_workers=8) as pool:
        list(
            pool.map(
                lambda i: workspace.write_json(path, {"writer": i, "points": list(range(100))}), range(32)
            )
        )
    assert json.loads(path.read_text())["points"] == list(range(100))
    assert list(tmp_path.glob("*.tmp")) == []




def test_composition_honors_long_vowel_option_for_each_segment(indexed_cue, monkeypatch):
    _, _, _, record, entry = indexed_cue
    compiled_scopes = []
    compiler = rhythm_index.compile_reference

    def tracked(cue, analysis, view, overrides, enabled, penalty=1):
        compiled_scopes.append((analysis["scope"]["scope_id"], enabled))
        return compiler(cue, analysis, view, overrides, enabled, penalty)

    monkeypatch.setattr(rhythm_index, "compile_reference", tracked)
    plans = rhythm_index.composition_plans(record, entry, strategy="mora", auto_long_vowels=True)["plans"]
    assert plans and all(p["auto_long_vowels"] for p in plans)
    assert len(compiled_scopes) == 2 and all(enabled for _, enabled in compiled_scopes)


def test_material_collection_limits_scope_and_keeps_plan_identity(indexed_cue):
    from ottosmasher import material_operations, materials

    db, cue, _analysis, record, _ = indexed_cue
    materials.sync_cues(db)
    segment = record["entries"][1]
    scope = segment["scope"]
    r = materials.save_range(
        db,
        cue["source_id"],
        scope["source_start"],
        scope["source_end"],
        cue_id=cue["id"],
        scope_id=scope["scope_id"],
        analysis_kind="narabas",
    )
    coll = materials.collection(db, "independent segment")
    materials.membership(db, r["id"], coll["id"])
    materials.edit(db, r["id"], tags=["test-scope"])
    pattern = rhythm_index.prototype(segment, "acoustic", 2)
    results = rhythm_index.search_index(db, query_for(pattern, collection_id=coll["id"], tags=["test-scope"]))
    assert results["results"]
    assert all(h["scope"]["scope_id"] == scope["scope_id"] for h in results["results"])
    assert not rhythm_index.search_index(db, query_for(pattern, collection_id=coll["id"], tags=["absent"]))[
        "results"
    ]
    hit = results["results"][0]
    plans = material_operations.plans(
        db,
        r["id"],
        {
            "analysis_kind": "narabas",
            "scope_id": scope["scope_id"],
            "strategy": "acoustic",
            "matched_plan_id": hit["plan_id"],
            "bpm": 120,
        },
    )
    assert plans["selected_plan_id"] == hit["plan_id"]
    whole = rhythm_index.reference_plans(record, record["entries"][0], strategy="acoustic")["plans"][0]
    with pytest.raises(ValueError, match="不同素材范围"):
        material_operations.checked_plan(db, r["id"], "narabas", whole["plan_id"])
