
import numpy as np
import pytest
import soundfile as sf

from ottosmasher import sample_audio, sound_tracks
from ottosmasher import sound_assets as a
from ottosmasher import source_separation as lab

pytest_plugins = ["test_samples"]




def test_continuous_tracks_overlap_samples_and_gap(tmp_path):
    sr = 24000
    y = np.random.default_rng(7).normal(0, 0.1, (sr * 13, 2)).astype("float32")
    p, q = tmp_path / "one.wav", tmp_path / "two.wav"
    sf.write(p, y[: sr * 8], sr, subtype="FLOAT")
    sf.write(q, y[sr * 6 :], sr, subtype="FLOAT")
    result = sound_tracks.stitch([(0, p), (6, q)], 13, tmp_path / "joined.wav")
    z, actual_sr = sf.read(result, always_2d=True)
    assert actual_sr == sr and len(z) == len(y)
    np.testing.assert_allclose(z, y, atol=1e-7)
    with pytest.raises(ValueError, match="缺口"):
        sound_tracks.stitch([(0, p), (9, q)], 13, tmp_path / "bad.wav")
    assert not (tmp_path / "bad.wav").exists()


def test_reference_track_source_and_save_without_promotion(library, tmp_path):
    db, m, y = library
    d = artifact(library, tmp_path)
    before = db.execute("select count(*) from materials").fetchone()[0]
    sound_tracks.register(db, d, "test · effects")
    assert len(sound_tracks.listing(db, m["source_id"])) == 1
    assert db.execute("select count(*) from materials").fetchone()[0] == before
    resolved = sample_audio.resolve_range(db, m, 0.1, 0.4, "artifact:" + d["id"])
    assert resolved["role"] == "effect"
    assert resolved["root_knots"] == [[0, 0.1], [pytest.approx(0.3), 0.4]]
    out, _ = sf.read(sample_audio.pcm(resolved))
    np.testing.assert_allclose(out, y[2400:9600] * 0.1, atol=2e-7)
    with pytest.raises(ValueError, match="原片不一致"):
        sound_tracks.resolve(db, d["id"], "wrong", 0.1, 0.4)
    with pytest.raises(ValueError, match="仅覆盖"):
        sound_tracks.resolve(db, d["id"], m["source_id"], 0, 2)


















def test_direct_source_registration_has_no_library_sample(library, tmp_path):
    db, _, y = library
    p = tmp_path / "second.wav"
    sf.write(p, y, 24000)
    before = db.execute("select count(*) from materials").fetchone()[0]
    d = lab.register_input(db, {"path": str(p), "start": 0.1, "end": 0.5})
    assert d["material_id"] is None and d["asset"]["root_knots"][0][1] == 0.1
    assert db.execute("select count(*) from materials").fetchone()[0] == before




def test_cutter_can_send_original_range_outside_selected_child(library):
    from ottosmasher import sample_catalog

    db, root, _ = library
    child = sample_catalog.derive(db, root["id"], start=0.1, end=0.3)
    d = lab.register_input(
        db, {"material_id": child["id"], "clock": "source", "role": "raw", "start": 0.5, "end": 0.8}
    )
    assert d["material_id"] is None
    assert d["source_id"] == root["source_id"] and d["asset"]["root_knots"] == [
        [0, 0.5],
        [pytest.approx(0.3), 0.8],
    ]


def test_subject_identity_normalizes_json_integer_times():
    assert a.subject_key({"artifact_id": "x", "start": 0, "end": 1}) == a.subject_key(
        {"artifact_id": "x", "start": 0.0, "end": 1.0}
    )

def artifact(library, tmp_path):
    db, m, y = library
    source = lab.register_input(db, {"material_id": m["id"]})
    p = tmp_path / "音效.wav"
    sf.write(p, y * 0.1, 24000, subtype="FLOAT")
    d = a.put(
        db,
        {
            "source_id": m["source_id"],
            "material_id": m["id"],
            "title": "effect",
            "asset": {"path": str(p), "role": "effect"},
        },
        "test.separate",
        "weights-v1",
        {},
        source,
    )
    return d
