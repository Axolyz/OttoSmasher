import hashlib
from copy import deepcopy

import numpy as np
import pytest
import soundfile as sf

from ottosmasher import media
from ottosmasher.beat_reference import slot_reference
from ottosmasher.rhythm_scopes import SELECTION_VERSION, list_scopes, scope_context
from ottosmasher.rhythm_units import group_phones
from ottosmasher.workspace import identity


def fixture():
    phones = [
        {"label": "k", "start": 10.10, "end": 10.20, "mora_index": 0},
        {"label": "a", "start": 10.20, "end": 10.40, "mora_index": 0},
        {"label": "t", "start": 10.40, "end": 10.50, "mora_index": 1},
        {"label": "o", "start": 10.50, "end": 10.65, "mora_index": 1},
        {"label": "SP", "start": 10.65, "end": 11.40},
        {"label": "n", "start": 11.40, "end": 11.50, "mora_index": 2},
        {"label": "e", "start": 11.50, "end": 11.70, "mora_index": 2},
        {"label": "e", "start": 11.70, "end": 11.90, "mora_index": 3},
        {"label": "y", "start": 11.90, "end": 12.00, "mora_index": 4},
        {"label": "o", "start": 12.00, "end": 12.20, "mora_index": 4},
    ]
    analysis = {
        "version": "fixture-v1",
        "input_variant": "vocals",
        "backend": "sofa",
        "window_start": 10.0,
        "window_end": 12.4,
        "phones": phones,
        "anchors": [{"time": p["start"]} for p in phones if p["label"] in {"a", "e", "o"}],
        "mora": {
            "count": 5,
            "sequence": list("かとねえよ"),
            "reading": "かとねえよ",
            "phone_mapping": "ordered_g2p",
        },
        "audio_lineage": {
            "target_cue_id": "cue",
            "window_start": 10.0,
            "window_end": 12.4,
            "audio_sha256": "voice-sha",
            "source_fingerprint": "source-sha",
        },
    }
    units = group_phones(phones)
    for unit in units:
        unit["phrase"] = int(unit["time"] > 11)
    view = {
        "version": "fixture-view",
        "units": units,
        "pauses": [
            {
                "start": 10.70,
                "end": 11.35,
                "kind": "acoustic_elastic_gap",
                "preserve_audio": True,
                "verified": False,
            }
        ],
        "split_before": [],
    }
    cue = {"id": "cue", "fingerprint": "source-sha", "start": 10.1, "end": 12.2, "spoken": "かと　ねえよ"}
    return cue, analysis, view


def test_long_acoustic_gap_yields_virtual_scopes_without_mutating_whole():
    cue, analysis, view = fixture()
    before = deepcopy((cue, analysis, view))
    scopes = list_scopes(cue, analysis, view)
    assert [s["kind"] for s in scopes] == ["whole", "segment", "segment"]
    assert scopes[1]["parent_unit_indices"] == [0, 1]
    assert scopes[2]["parent_unit_indices"] == [2, 3]
    assert scopes[1]["source_end"] == scopes[2]["source_start"] == pytest.approx(11.025)
    assert scopes[1]["source_start"] == 10 and scopes[-1]["source_end"] == 12.4
    assert scopes[1]["next_scope_id"] == scopes[2]["scope_id"]
    assert scopes[2]["previous_scope_id"] == scopes[1]["scope_id"]
    same_a, same_v = scope_context(cue, analysis, view, scopes[0])
    assert same_a is analysis and same_v is view
    assert (cue, analysis, view) == before


@pytest.mark.parametrize(
    "kind,duration", [("ctc_blank", 0.65), ("model_pause", 0.65), ("acoustic_elastic_gap", 0.15)]
)
def test_ctc_blank_and_short_elastic_gap_do_not_create_boundaries(kind, duration):
    cue, analysis, view = fixture()
    view["pauses"][0].update(kind=kind, end=10.70 + duration)
    assert len(list_scopes(cue, analysis, view)) == 1


@pytest.mark.parametrize("label", ["a", "cl", "n"])
def test_long_model_phone_crossing_quiet_seam_is_not_automatically_split(label):
    cue, analysis, view = fixture()
    analysis["phones"].append({"label": label, "start": 10.8, "end": 11.2})
    assert len(list_scopes(cue, analysis, view)) == 1


def test_sustained_group_spanning_pause_does_not_split_even_if_sparse_ctc_phones_do_not():
    cue, analysis, view = fixture()
    view["units"][1]["end"] = 11.2
    assert len(list_scopes(cue, analysis, view)) == 1


def test_manual_merge_split_and_parameter_changes_invalidate_scopes():
    cue, analysis, view = fixture()
    original = list_scopes(cue, analysis, view)
    merged = list_scopes(cue, analysis, view, {"suppressed_split_before": [2]})
    assert len(merged) == 1
    assert merged[0]["detected_boundaries"][0]["suppressed"]
    assert merged[0]["scope_id"] != original[0]["scope_id"]
    manual = list_scopes(cue, analysis, view, {"suppressed_split_before": [2], "split_before": [1]})
    assert manual[1]["source_end"] == pytest.approx(10.4)
    assert manual[2]["source_start"] <= analysis["phones"][2]["start"]
    assert manual[0]["boundaries"][0]["manual"]
    with pytest.raises(ValueError, match="non-first"):
        list_scopes(cue, analysis, view, {"split_before": [0]})


def test_segments_rebase_mora_and_preserve_leading_consonants_and_tail():
    cue, analysis, view = fixture()
    scopes = list_scopes(cue, analysis, view)
    first_a, first_v = scope_context(cue, analysis, view, scopes[1])
    last_a, last_v = scope_context(cue, analysis, view, scopes[2])
    assert first_a["mora"]["count"] == 2
    assert [s["text_mora_count"] for s in slot_reference(first_a, first_v)["slots"]] == [1, 1]
    assert last_a["mora"]["count"] == 3
    assert last_a["mora"]["sequence"] == list("ねえよ")
    assert [s["text_mora_count"] for s in slot_reference(last_a, last_v)["slots"]] == [2, 1]
    assert last_v["units"][0]["parent_unit_index"] == 2
    assert last_v["units"][0]["members"][0]["mora_index"] == 0
    assert last_v["units"][0]["members"][0]["parent_mora_index"] == 2
    assert last_a["phones"][1]["label"] == "n"
    assert last_a["window_start"] < last_a["phones"][1]["start"] < last_v["units"][0]["time"]
    assert last_a["window_end"] == analysis["window_end"]
    assert last_a["audio_lineage"] == analysis["audio_lineage"]
    assert last_a["audio_selection"]["source_start"] == scopes[2]["source_start"]
    # The silence interval is a derived selection clip, never an upstream edit.
    assert last_a["phones"][0]["parent_interval"] == [10.65, 11.4]
    assert analysis["phones"][4]["start"] == 10.65


def test_unreliable_scope_mora_does_not_consume_remaining_parent_text():
    cue, analysis, view = fixture()
    for member in view["units"][2]["members"]:
        member.pop("mora_index")
    scopes = list_scopes(cue, analysis, view)
    first_a, first_v = scope_context(cue, analysis, view, scopes[1])
    assert first_a["mora"]["count"] is None
    assert all(s["text_mora_count"] is None for s in slot_reference(first_a, first_v)["slots"])
    stale = deepcopy(analysis)
    stale["version"] = "new-model-output"
    with pytest.raises(ValueError, match="stale"):
        scope_context(cue, stale, view, scopes[1])
    changed_bounds = deepcopy(scopes[1])
    changed_bounds["source_end"] -= 0.1
    with pytest.raises(ValueError, match="stale"):
        scope_context(cue, analysis, view, changed_bounds)


def test_selection_media_reads_correct_parent_samples_and_rejects_wrong_lineage(tmp_path, monkeypatch):
    monkeypatch.setattr(media, "DATA", tmp_path / "data")
    monkeypatch.setattr(media, "ROOT", tmp_path)
    cue, analysis, view = fixture()
    sr = 48000
    parent = np.zeros(round(2.4 * sr), dtype=np.float32)
    parent[round(1.4 * sr) : round(1.42 * sr)] = 0.25
    voice = tmp_path / "人声.wav"
    original = tmp_path / "原声.wav"
    sf.write(voice, parent, sr, subtype="PCM_24")
    sf.write(original, np.r_[np.zeros(10 * sr), parent, np.zeros(sr)], sr, subtype="PCM_24")
    cue.update(path=str(original), source_id="source", source_duration=13.4, audio_stream=0)
    analysis["audio_lineage"].update(
        audio_path=str(voice), audio_sha256=hashlib.sha256(voice.read_bytes()).hexdigest()
    )
    scope = list_scopes(cue, analysis, view)[2]
    selected, _ = scope_context(cue, analysis, view, scope)
    path, manifest = media.render(
        cue, variant="vocals", lineage=analysis["audio_lineage"], selection=selected["audio_selection"]
    )
    output, rate = sf.read(path)
    source_index = round((scope["source_start"] - 10) * sr)
    assert rate == sr
    assert np.array_equal(output, parent[source_index:])
    assert manifest["source_start"] == scope["source_start"]
    assert manifest["audio_selection"]["scope_id"] == scope["scope_id"]
    raw_path, raw_manifest = media.render(
        cue, variant="raw", lineage=analysis["audio_lineage"], selection=selected["audio_selection"]
    )
    raw, _ = sf.read(raw_path)
    assert np.array_equal(raw, output)
    assert raw_manifest["source_end"] == scope["source_end"]
    cue.update(original=cue["spoken"], title="fixture")
    exported = media.export_bundle(cue, selected, variant="raw")
    assert exported["manifest"]["spoken_text"] == "ねえよ"
    assert exported["manifest"]["parent_spoken_text"] == cue["spoken"]
    bad = deepcopy(selected["audio_selection"])
    bad["source_start"] += 0.1
    with pytest.raises(ValueError, match="changed"):
        media.render(cue, variant="vocals", lineage=analysis["audio_lineage"], selection=bad)
    bad = deepcopy(selected["audio_selection"])
    bad["source_start"] = 9
    bad["selection_id"] = identity(SELECTION_VERSION, {k: v for k, v in bad.items() if k != "selection_id"})
    with pytest.raises(ValueError, match="outside"):
        media.render(cue, variant="vocals", lineage=analysis["audio_lineage"], selection=bad)
    voice.write_bytes(voice.read_bytes() + b"corrupted")
    with pytest.raises(ValueError, match="checksum"):
        media.render(
            cue, variant="raw", lineage=analysis["audio_lineage"], selection=selected["audio_selection"]
        )
