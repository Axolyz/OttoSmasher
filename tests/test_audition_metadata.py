"""Audition mapping and inherited assertions must describe the actual source."""

import json
from pathlib import Path

import pytest
from test_samples import library as library  # noqa: PLC0414
from test_samples import timing_record
from test_source_preparation import subtitle

from ottosmasher import (
    catalog,
    materials,
    sample_audio,
    sample_catalog,
    sample_rhythm,
    sample_thumbnails,
    source_preparation,
    subtitle_speakers,
)


def test_native_list_audition_reads_bound_cut_without_pcm(library, monkeypatch, tmp_path):
    from contextlib import nullcontext

    from ottosmasher import native_player, sample_api

    db, root, _ = library
    child = sample_catalog.derive(db, root["id"], start=0.2, end=0.6)
    monkeypatch.setattr(sample_api, "database", lambda: nullcontext(db))
    monkeypatch.setattr(native_player, "DATA", tmp_path / "native")
    monkeypatch.setattr(sample_audio, "pcm", lambda *_: pytest.fail("No PCM export before native audition"))
    result = sample_api.audition_source(child["id"], {"native": True})
    spec = native_player.load(result["url"].rsplit("/", 1)[1])
    assert spec["path"] == root["path"]
    assert spec["start"] == pytest.approx(0.2) and spec["end"] == pytest.approx(0.6)
    assert spec["asset"]["role"] == "raw"


@pytest.mark.parametrize("durations", [[0.25] * 4, [0.1, 0.31, 0.16, 0.65], [0.012, 0.024, 0.012, 0.024]])
def test_unset_bpm_has_measured_unity_speed(durations):
    record = timing_record(durations)
    p = sample_rhythm.original_speed_plan(record, "acoustic")
    timing = sample_rhythm.timing_view(record, p)
    assert timing["speech_playback_speed"] == pytest.approx(1, abs=1e-3)
    assert p["target_bpm"] is None and p["candidate_role"] == "original_speed"
    assert len(timing["points"]) == len(record["view"]["units"])


def test_graph_coordinates_use_actual_duration_not_two_normalized_axes():
    record = timing_record([0.18, 0.3, 0.12, 0.4])
    from ottosmasher.beat_reference import generate_references

    p = generate_references(
        record["cue"],
        record["analysis"],
        record["view"],
        bpm=120,
        strategy="acoustic",
        density=8,
        compiled=record["compiled"],
        persist=False,
    )["plans"][0]
    p["speech_bounds"] = sample_rhythm.speech_bounds(record)
    t = sample_rhythm.timing_view(record, p)
    assert t["speech_playback_speed"] > 1
    assert t["target_duration"] < t["source_duration"]
    assert t["points"][-1]["target_seconds"] < t["points"][-1]["source_seconds"]


def test_nested_ruby_multiple_speakers_and_sound_annotations():
    original = "（京子(きょうこ)）アッカリ～ン"
    parsed = catalog.parse_text(original)
    assert parsed[0] == original and parsed[1] == "アッカリ～ン" and parsed[4] == "京子"
    group = subtitle_speakers.extract("（京子(きょうこ)たち）アッカリ～ン")
    assert group["status"] == "multiple_or_group" and group["names"] == ["京子たち"]
    duo = subtitle_speakers.extract("（A）ああ（B）いい")
    assert duo["names"] == ["A", "B"] and [t["text"] for t in duo["turns"]] == ["ああ", "いい"]
    assert duo["timing"] == "unknown" and not duo["confirmed"]
    assert subtitle_speakers.extract("（殴る音）（倒れる音）")["names"] == []
    assert catalog.parse_text("（殴る音）（倒れる音）")[5] == "event"


def test_optional_import_speaker_tags_and_reimport_without_duplicates(library, tmp_path):
    db, root, _ = library
    path = subtitle(tmp_path, "（あかり）ねえ")
    source_preparation.configure(db, root["source_id"], subtitle_path=str(path), op_review="skipped")
    p = source_preparation.preview(db, root["source_id"])
    source_preparation.ingest(db, root["source_id"], p["token"])
    assert not list(db.execute("SELECT * FROM subtitle_speakers"))
    count = db.execute("SELECT count(*) FROM materials").fetchone()[0]
    source_preparation.configure(db, root["source_id"], import_speakers=True)
    source_preparation.ingest(db, root["source_id"], p["token"])
    assert db.execute("SELECT count(*) FROM materials").fetchone()[0] == count
    mid = materials.query_ids(db, tags=["character:あかり"])[0]
    child = sample_catalog.derive(
        db, mid, start=0.02, end=0.1, input_asset=sample_audio.resolve(db, mid, "raw")
    )
    tags = materials.get(db, child["id"])["tags"]
    assert any(t["tag"] == "character:あかり" and not t["confirmed"] for t in tags)
    assert child["id"] in materials.query_ids(db, tags=["character:あかり"])


def test_pitch_tags_follow_bound_audio_not_just_parent(library):
    db, root, _ = library
    raw = sample_audio.resolve(db, root["id"])
    pitched = sample_catalog.derive(
        db,
        root["id"],
        operation="flatten",
        asset={**raw, "role": "flattened", "target_note": {"name": "A4", "hz": 440}},
    )
    cut = sample_catalog.derive(db, pitched["id"], start=0.1, end=0.4)
    assert cut["id"] in materials.query_ids(db, tags=["pitch:A4"])
    reset = sample_catalog.derive(db, pitched["id"], start=0.1, end=0.4, input_asset=raw)
    assert reset["id"] not in materials.query_ids(db, tags=["pitch:A4"])
    assert not list(db.execute("SELECT * FROM material_tags WHERE tag='pitch:A4'"))


def test_thumbnail_uses_root_time_and_cache_without_analysis(library, tmp_path, monkeypatch):
    db, root, _ = library
    monkeypatch.setattr(sample_thumbnails, "DATA", tmp_path)
    assert sample_thumbnails.thumbnail(db, root["id"]) is None
    db.execute(
        "UPDATE sources SET metadata=? WHERE id=?",
        (json.dumps({"streams": [{"codec_type": "video", "index": 0}]}), root["source_id"]),
    )
    raw = sample_audio.resolve(db, root["id"])
    warped = sample_catalog.derive(
        db, root["id"], operation="quantized", asset={**raw, "root_knots": [[0, 0.1], [0.5, 0.4], [1, 0.9]]}
    )
    calls = []

    def ffmpeg(argv, **kwargs):
        calls.append(argv)
        Path(argv[-1]).write_bytes(b"fake jpeg")

    monkeypatch.setattr(sample_thumbnails.subprocess, "run", ffmpeg)
    result = sample_thumbnails.thumbnail(db, warped["id"])
    assert float(calls[0][calls[0].index("-ss") + 1]) == pytest.approx(0.5)
    assert sample_thumbnails.thumbnail(db, warped["id"]) == result and len(calls) == 1


def test_original_speed_excludes_elastic_pause_and_padding():
    from test_three_routes import speech_fixture

    from ottosmasher.beat_reference import compile_reference

    cue, analysis, view = speech_fixture((0.1, 0.2, 0.1))
    for unit in view["units"][1:]:
        unit["time"] += 1
        unit["end"] += 1
        unit["phrase"] = 1
        for phone in unit["members"] + unit["phone_runs"]:
            phone["start"] += 1
            phone["end"] += 1
    view["pauses"] = [{"start": 0.3, "end": 1.3, "preserve_audio": True}]
    analysis["window_end"] += 1
    record = {
        "cue": cue,
        "analysis": analysis,
        "view": view,
        "compiled": compile_reference(cue, analysis, view),
        "scope": {"scope_id": "pause-fixture"},
    }
    p = sample_rhythm.original_speed_plan(record, "acoustic")
    assert sample_rhythm.timing_view(record, p)["speech_playback_speed"] == pytest.approx(1, abs=1e-3)


def test_complete_track_flag_does_not_remove_short_assets(library):
    from ottosmasher import sound_tracks

    db, root, _ = library
    sound_tracks.ensure(db)
    db.executemany(
        "INSERT INTO sound_reference_tracks VALUES(?,?,?,?,?,?)",
        [
            ("whole", root["source_id"], "人声", 0, 1, "test"),
            ("short", root["source_id"], "人声", 0.2, 0.4, "test"),
        ],
    )
    tracks = sound_tracks.listing(db, root["source_id"])
    assert [t["artifact_id"] for t in tracks] == ["whole", "short"]
    assert [t["complete"] for t in tracks] == [True, False]
