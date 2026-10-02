import json
import os
import time

import numpy as np
import soundfile as sf
from test_samples import library as library  # noqa: PLC0414

from ottosmasher import search_sessions


def test_all_results_survive_paging_and_restart(library):
    db, root, _ = library
    rows = [
        {"material_id": root["id"], "score": i, "hits": [{"start": 0, "end": 0.1, "id": str(i)}]}
        for i in range(1207)
    ]
    saved = search_sessions.create(db, "speech", {"units": [{}]}, {"results": rows})
    restored = []
    for offset in range(0, 1207, 100):
        page = search_sessions.read(db, saved["id"], offset)
        assert page["total"] == 1207
        restored.extend(page["results"])
    assert [r["score"] for r in restored] == list(range(1207))


def test_compressed_projection_legacy_compatibility():
    from ottosmasher.sample_analysis import decode_record, encode_record

    record = {"frames": {"f0": [42] * 1000}, "text": "音素"}
    assert decode_record(encode_record(record)) == record
    assert decode_record(json.dumps(record)) == record
    assert len(encode_record(record)) < len(json.dumps(record)) / 10


def test_projection_invalidates_only_affected_source(library, tmp_path):
    from ottosmasher.materials import register_file
    from ottosmasher.speech_search_index import ensure

    db, first, _ = library
    path = tmp_path / "other.wav"
    sf.write(path, np.zeros(2400), 24000)
    second = register_file(db, path)
    ensure(db)
    db.executemany(
        "INSERT INTO speech_search_index VALUES(?,?,?)", [(r["id"], "test", b"x") for r in (first, second)]
    )
    db.execute("UPDATE materials SET title=? WHERE id=?", ("new name", first["id"]))
    assert db.execute("SELECT count(*) FROM speech_search_index").fetchone()[0] == 2
    db.execute("UPDATE sources SET metadata=? WHERE id=?", ("{}", first["source_id"]))
    assert [r[0] for r in db.execute("SELECT material_id FROM speech_search_index")] == [second["id"]]


def test_migration_ranges_do_not_double_offset():
    from ottosmasher.storage_migration import rewrite

    mapping = {"crop.wav": {"path": "whole.mp3", "offset": 30, "sha256": "new", "duration": 4}}
    asset = {
        "path": "crop.wav",
        "sha256": "old",
        "start": 0.5,
        "end": 3,
        "root_knots": [[0, 30.5], [2.5, 33]],
    }
    moved = rewrite(asset, mapping)
    assert moved["start"] == 30.5 and moved["end"] == 33
    assert moved["root_knots"] == asset["root_knots"]
    assert rewrite(moved, mapping) == moved
    lineage = rewrite({"audio_path": "crop.wav", "window_start": 30, "window_end": 34}, mapping)
    assert (lineage["audio_start"], lineage["audio_end"]) == (30, 34)


def test_decoder_reads_only_virtual_range(tmp_path):
    from ottosmasher.audio_storage import read

    path = tmp_path / "whole.wav"
    y = np.arange(32000, dtype=np.float32) / 32000
    sf.write(path, y, 16000, subtype="FLOAT")
    actual, sr = read(path, 0.5, 1.5)
    assert sr == 16000
    np.testing.assert_array_equal(actual[:, 0], y[8000:24000])


def test_lru_does_not_delete_leased_pcm_or_features(tmp_path, monkeypatch):
    from ottosmasher import audio_storage

    monkeypatch.setattr(audio_storage, "DATA", tmp_path)
    folder = tmp_path / "sample-cache"
    folder.mkdir()
    first = folder / "a.wav"
    second = folder / "b.wav"
    feature = folder / "b.features.json"
    for p in (first, second, feature):
        p.write_bytes(b"x" * 100)
        os.utime(p, (time.time() - 90000,) * 2)
    with audio_storage.leased(first):
        audio_storage.trim_pcm(limit=50, low=0)
        assert first.exists() and not second.exists() and feature.exists()


def test_speed_limits_preference_and_only_two_candidates(monkeypatch):
    from test_speech_query import rhythm_record

    from ottosmasher import rhythm_index, sample_rhythm
    from ottosmasher.speech_query import rhythm_evidence

    record = rhythm_record()
    monkeypatch.setattr(
        sample_rhythm,
        "candidates",
        lambda *a: (
            [{"density": 1, "speech_playback_speed": 1.8}, {"density": 1, "speech_playback_speed": 0.9}],
            [],
        ),
    )
    monkeypatch.setattr(
        rhythm_index,
        "prototype",
        lambda *a: {
            "plan": {
                "unit_targets": [{"source_seconds": t, "target_beat": t} for t in (0, 1, 2)],
                "end_target": {"source_seconds": 3, "target_beat": 3},
            }
        },
    )
    query = {
        "bpm": 120,
        "notes": [{"start_beats": t, "end_beats": t + 0.5} for t in (0, 1, 2)],
        "speed_preference": 0.1,
    }
    hit = {"unit_indices": [0, 1, 2]}
    assert rhythm_evidence(record, hit, query)["candidate"]["speech_playback_speed"] == 0.9
    query.update(playback_speed_filter=True, playback_speed_min=1, playback_speed_max=1.8)
    assert rhythm_evidence(record, hit, query)["candidate"]["speech_playback_speed"] == 1.8
    query["playback_speed_max"] = 1.7
    assert rhythm_evidence(record, hit, query) is None


def test_migration_preserves_standalone_pitch_without_speech_record(tmp_path, monkeypatch):
    from ottosmasher import sample_acoustics, sample_audio
    from ottosmasher.materials import sha256
    from ottosmasher.storage_migration import preserve_feature_sidecars

    old, new = tmp_path / 'flattened.wav', tmp_path / 'compact.mp3'
    new.write_bytes(b'encoded audio')
    frames = {'times': [0, .1, .2], 'f0_hz': [440, 441, 439],
              'voiced': [True] * 3, 'energy': [.1] * 3, 'confidence': [.9] * 3}
    old.with_suffix('.features.json').write_text(json.dumps(frames))
    mapping = {str(old): {'source': str(old), 'path': str(new), 'offset': 0,
                         'sha256': sha256(new)}}
    asset = {'path': str(new), 'start': .1, 'end': .3, 'role': 'flattened'}
    monkeypatch.setattr(sample_audio, 'resolve', lambda *args: asset)
    monkeypatch.setattr(sample_audio, 'DATA', tmp_path)
    assert sample_acoustics.cached(None, 'sample')['status'] == 'missing'
    assert preserve_feature_sidecars(mapping) == [str(new.with_suffix('.features.json'))]
    restored = sample_acoustics.cached(None, 'sample')
    assert restored['status'] == 'ready'
    assert restored['frames']['f0_hz'] == [441, 439]
    assert restored['frames']['times'] == [0, .1]
    assert old.with_suffix('.features.json').read_bytes() == new.with_suffix('.features.json').read_bytes()
    assert preserve_feature_sidecars(mapping) == []


def test_migration_never_attaches_crop_measurements_to_parent(tmp_path):
    from ottosmasher.storage_migration import preserve_feature_sidecars

    crop, parent = tmp_path / 'crop.wav', tmp_path / 'parent.mp3'
    crop.with_suffix('.features.json').write_text('{}')
    assert preserve_feature_sidecars({str(crop): {
        'source': str(tmp_path / 'parent.wav'), 'path': str(parent), 'offset': 5,
        'sha256': 'unused'}}) == []
    assert not parent.with_suffix('.features.json').exists()
