import hashlib
from pathlib import Path

import numpy as np
import pytest
import soundfile as sf
import test_vocals
from praatio import textgrid

from ottosmasher import audition, quantization, strict_audio, workspace
from ottosmasher.alignment_results import target_phones
from ottosmasher.beat_reference import generate_references
from ottosmasher.ctc import forced_ctc
from ottosmasher.mora_features import mora_features
from ottosmasher.rhythm import RhythmQuery
from ottosmasher.rhythm_units import rhythm_view
from ottosmasher.timeline import map_time

separated_cue = test_vocals.separated_cue


def fixture_analysis(lineage):
    # Separate consonants prevent accidental adjacent-vowel grouping.
    phones = []
    for t in [0.2, 0.62, 1.08, 2.7]:
        phones.extend(
            [{"start": t - 0.04, "end": t, "label": "k"}, {"start": t, "end": t + 0.08, "label": "a"}]
        )
    return {
        "version": "strict-fixture",
        "input_variant": "vocals",
        "audio_lineage": lineage,
        "phones": phones,
        "anchors": [
            {"time": t, "phone": "a", "duration": 0.08, "strength": 1} for t in [0.2, 0.62, 1.08, 2.7]
        ],
        "window_start": 0,
        "window_end": 3,
        "flags": [],
        "verified": False,
    }


def query():
    return RhythmQuery(
        bpm=120,
        notes=[{"start_beats": 0, "end_beats": 0.1}, {"start_beats": 1, "end_beats": 1.1}],
        factor_min=1,
        factor_max=1,
        tolerance_beats=0.1,
    )


def witness(view):
    return {"beat_seconds": 0.5, "query": query().model_dump()}


def test_repeated_ctc_tokens_need_blank_and_both_endpoints():
    # BOS, a, blank, a, EOS -- both repeated vowel labels must survive.
    labels = [1, 3, 0, 3, 2]
    x = np.full((5, 4), -20.0)
    x[np.arange(5), labels] = 20
    assert forced_ctc(x, [1, 3, 3, 2]) == [(0, 1), (1, 2), (3, 4), (4, 5)]
    with pytest.raises(ValueError):
        forced_ctc(x[:3], [1, 3, 3, 2])


def test_context_phone_ownership_is_exact_and_retains_target_silence():
    raw = {
        "phones": [
            {"start": i * 0.1, "end": (i + 1) * 0.1, "label": p}
            for i, p in enumerate(["k", "a", "SP", "i", "t", "o"])
        ],
        "phone_owners": [
            {"phone": p, "cue_id": c}
            for p, c in [("k", "before"), ("a", "target"), ("i", "target"), ("t", "after"), ("o", "after")]
        ],
    }
    phones = target_phones(raw, {"id": "target"}, "narabas")
    assert [p["label"] for p in phones] == ["a", "SP", "i"]
    raw["phone_owners"][0]["phone"] = "n"
    with pytest.raises(ValueError, match="sequence differs"):
        target_phones(raw, {"id": "target"}, "narabas")




def test_mora_count_does_not_create_extra_rhythm_points():
    m = mora_features({}, [{"members": []}], "ちいい")
    assert m["count"] == 3 and m["unit_counts"] == [None]
    assert "start" not in m and "end" not in m
    m = mora_features({}, [{"members": [{"mora_index": 0}]}, {"members": [{"mora_index": 2}]}], "かった")
    assert m["interval_mora_counts"] == [2]


def test_protected_audio_cores_and_export_are_really_fixed(separated_cue, monkeypatch):
    _, cue, lineage = separated_cue
    root = Path(lineage["audio_path"]).parent
    for module in (quantization, strict_audio, audition):
        monkeypatch.setattr(module, "DATA", root / "data")
    monkeypatch.setattr(audition, "ROOT", root)
    a = fixture_analysis(lineage)
    v = rhythm_view(a)
    w = witness(v)
    p = generate_references(cue, a, v, strategy="acoustic", persist=False)["plans"][0]
    # Exercise severe local deformation as explicitly authorized by the user.
    p["unit_targets"][-1]["target_beat"] = 12
    p["end_target"]["target_beat"] = 12.5
    p["plan_id"] = workspace.identity(p)
    path, meta = strict_audio.render_strict(cue, a, p)
    output, sr = sf.read(path, dtype="float32", always_2d=True)
    original, _ = sf.read(lineage["audio_path"], dtype="float32", always_2d=True)
    for c in meta["cores"]:
        assert np.array_equal(
            output[c["target_start"] : c["target_end"]], original[c["source_start"] : c["source_end"]]
        )
        expected = (p["unit_targets"] + [p["end_target"]])[meta["cores"].index(c)]["target_beat"] * 0.5
        assert map_time(c["source_anchor"] / sr, meta["time_map"]) == pytest.approx(expected, abs=1 / sr)
    assert len(output) > 3 * sr
    preview = audition.preview_strict(cue, a, p, "strict")
    exported = audition.export_witness(cue, a, {**w, "strict_plan": p})
    assert (
        hashlib.sha256(path.read_bytes()).digest()
        == hashlib.sha256(Path(exported["audio"]).read_bytes()).digest()
    )
    tg = textgrid.openTextgrid(
        str(Path(exported["audio"]).with_suffix(".TextGrid")), includeEmptyIntervals=False
    )
    assert [x.time for x in tg.getTier("rhythm_groups").entries] == pytest.approx(
        preview["source_click_seconds"], abs=1 / sr
    )
    clicks, click_sr = sf.read(exported["click_audio"], always_2d=True)
    assert click_sr == sr and len(clicks) == len(output)
    assert all(np.max(abs(clicks[round(t * sr)])) > 0 for t in preview["source_click_seconds"])




def test_selected_missing_backend_does_not_fall_back(separated_cue):
    db, cue, lineage = separated_cue
    workspace.save_analysis(db, cue["id"], "phonetic", "test", fixture_analysis(lineage))
    assert workspace.get_vocals_lineage(db, cue["id"], "narabas") is None


def test_shared_context_cache_is_returned_for_each_requested_cue(separated_cue, monkeypatch):
    from ottosmasher import vocals
    from ottosmasher.media import window

    _, cue, lineage = separated_cue
    root = Path(lineage["audio_path"]).parent / "cache"
    monkeypatch.setattr(vocals, "DATA", root)
    monkeypatch.setattr(vocals, "register_reference", lambda *args: None)
    monkeypatch.setattr(vocals, "model_identity", lambda *args: {"fixture": "sha"})
    start, end = window(cue)
    key = workspace.identity(
        cue["fingerprint"],
        cue["audio_stream"],
        start,
        end,
        0,
        cue["source_duration"],
        {"fixture": "sha"},
        "vocals",
        "pymss-stereo-context-v1",
    )
    workspace.write_json(root / "vocals" / key / "manifest.json", {**lineage, "cue_id": cue["id"]})
    other = {**cue, "id": "other-target-same-context"}
    result = vocals.prepare_vocals([cue, other])
    assert set(result) == {cue["id"], other["id"]}
    assert result[other["id"]]["cue_id"] == other["id"]
    assert result[other["id"]]["audio_sha256"] == result[cue["id"]]["audio_sha256"]


def test_long_silence_is_changed_without_moving_audio_cores(separated_cue, monkeypatch):
    _, cue, lineage = separated_cue
    root = Path(lineage["audio_path"]).parent
    for module in (quantization, strict_audio):
        monkeypatch.setattr(module, "DATA", root / "data")
    y, sr = sf.read(lineage["audio_path"])
    y[round(1.2 * sr) : round(2.5 * sr)] = 0
    sf.write(lineage["audio_path"], y, sr)
    lineage["audio_sha256"] = hashlib.sha256(Path(lineage["audio_path"]).read_bytes()).hexdigest()
    a = fixture_analysis(lineage)
    a["phones"].insert(-2, {"start": 1.2, "end": 2.5, "label": "SP"})
    v = rhythm_view(a)
    assert len(v["pauses"]) == 1
    witness(v)
    p = generate_references(cue, a, v, strategy="acoustic", persist=False)["plans"][0]
    _, meta = strict_audio.render_strict(cue, a, p)
    assert any(s["kind"] == "elastic_gap" for s in meta["segments"])
    for i, c in enumerate(meta["cores"]):
        assert c["target_anchor"] / sr + meta["timeline_start_seconds"] == pytest.approx(
            (p["unit_targets"] + [p["end_target"]])[i]["target_beat"] * 0.5, abs=1 / sr
        )
