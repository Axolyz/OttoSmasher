"""Derived identities, exact source composition, and adaptive timing contracts."""

from pathlib import Path

import numpy as np
import pytest
import soundfile as sf
from test_three_routes import speech_fixture

from ottosmasher import materials, media_operations, workspace
from ottosmasher import sample_audio as audio
from ottosmasher import sample_catalog as c
from ottosmasher import sample_rhythm as rhythm
from ottosmasher.beat_reference import compile_reference
from ottosmasher.sample_flatten import nearest_note


@pytest.fixture
def library(tmp_path, monkeypatch):
    for module in (workspace, audio, rhythm, media_operations):
        monkeypatch.setattr(module, "DATA", tmp_path / "data")
    path = tmp_path / "原声.wav"
    y = np.linspace(-0.3, 0.3, 24000, dtype=np.float32)
    sf.write(path, y, 24000, subtype="FLOAT")
    db = workspace.connect()
    root = materials.register_file(db, path)
    yield db, root, y
    db.close()


def test_two_crops_compose_original_frames_without_copy(library):
    db, root, y = library
    child = c.derive(
        db, root["id"], start=0.1, end=0.7, locator={"phones": [{"root_phone_id": "original-u"}]}
    )
    grand = c.derive(db, child["id"], start=0.125, end=0.225)
    assert grand["derivation"]["parent_id"] == child["id"]
    assert grand["derivation"]["payload"]["parent_range"] == [0.125, 0.225]
    assert grand["start"] == pytest.approx(0.225) and grand["end"] == pytest.approx(0.325)
    assert grand["derivation"]["payload"]["locator"]["phones"][0]["root_phone_id"] == "original-u"
    assert audio.resolve(db, grand["id"])["path"] == root["path"]
    signal, _sr = sf.read(audio.pcm(audio.resolve(db, grand["id"])))
    assert len(signal) == 2400
    np.testing.assert_allclose(signal, y[5400:7800], atol=2e-7)


def test_pending_accept_does_not_move_existing_or_duplicate_shared_source(library):
    db, root, _ = library
    c.preferences(db, root["id"], nature="unpitched")
    batch = c.batch(db, {"notes": [0]}, target="pitched")
    pending = c.derive(db, root["id"], operation="candidate", batch_id=batch["id"])
    assert pending["status"] == "pending"
    assert c.review(db, [pending["id"]]) == [root["id"]]
    assert materials.get(db, root["id"])["nature"] == "unpitched"
    assert Path(root["path"]).exists()
    first = c.derive(db, root["id"], start=0.1, end=0.5, batch_id=batch["id"])
    c.review(db, [first["id"]])
    b2 = c.batch(db, {}, target="speech")
    same = c.derive(db, root["id"], start=0.1, end=0.5, batch_id=b2["id"])
    assert c.review(db, [same["id"]]) == [first["id"]]
    assert materials.get(db, first["id"])["nature"] == "unpitched"
    lost = c.derive(db, root["id"], start=0.1, end=0.6, batch_id=b2["id"])
    c.review(db, [lost["id"]], False)
    assert Path(root["path"]).exists() and materials.get(db, root["id"])["status"] == "confirmed"


def test_child_preferences_snapshot_and_partial_source_mapping(library):
    db, root, _ = library
    c.preferences(db, root["id"], active_phone_backend="narabas", active_quantization_strategy="mora")
    child = c.derive(db, root["id"], start=0.1, end=0.7)
    c.preferences(db, root["id"], active_phone_backend="narabas", active_quantization_strategy="acoustic")
    child = materials.get(db, child["id"])
    assert child["active_phone_backend"] == "narabas" and child["active_quantization_strategy"] == "mora"
    # A nonlinear warp must compose its actual control mapping, never a duration ratio.
    a = audio.resolve(db, child["id"])
    a = {**a, "root_knots": [[0, 0.1], [0.3, 0.2], [0.6, 0.7]]}
    warped = c.derive(db, child["id"], operation="quantized", asset=a)
    cut = c.derive(db, warped["id"], start=0.3, end=0.45)
    assert cut["start"] == pytest.approx(0.2) and cut["end"] == pytest.approx(0.45)


def timing_record(durations):
    cue, a, v = speech_fixture(durations)
    return {
        "cue": cue,
        "analysis": a,
        "view": v,
        "compiled": compile_reference(cue, a, v),
        "scope": {"scope_id": "fixture", "source_start": 0, "source_end": a["window_end"]},
    }


def test_adaptive_extreme_short_units_and_exact_original_speed():
    short = timing_record([0.012, 0.024, 0.012, 0.024])
    options, _errors = rhythm.candidates(short, 120, "acoustic")
    assert len(options) == 3 and options[0]["density"] > 8
    assert options[0]["speech_playback_speed"] >= 1
    assert options[1]["speech_playback_speed"] < 1
    assert options[2]["density"] == options[0]["density"] * 2
    exact = timing_record([0.25] * 4)
    choices, _ = rhythm.candidates(exact, 120, "mora")
    assert choices[0]["density"] == 2 and choices[0]["speech_playback_speed"] == pytest.approx(1, abs=2e-5)
    assert choices[1]["density"] == 1


def test_nearest_pitch_uses_one_robust_note_and_rejects_no_voice():
    note = nearest_note(np.array([439, 440, 441, 880]), np.ones(4), np.ones(4, dtype=bool))
    assert note["name"] == "A4" and note["hz"] == 440
    with pytest.raises(ValueError, match="F0"):
        nearest_note(np.array([0, 0, 0]), np.ones(3), np.zeros(3, dtype=bool))


def test_missing_separation_does_not_fall_back(library):
    db, root, _ = library
    with pytest.raises(ValueError, match="分离音源"):
        audio.resolve(db, root["id"], "vocals")


def test_pcm_rounding_does_not_reject_full_candidate(library):
    db, root, _ = library
    candidate = c.derive(db, root["id"], end=1 + 1 / 48000, operation="candidate")
    assert candidate["end"] == 1
    with pytest.raises(ValueError):
        c.derive(db, root["id"], end=1.01)


def test_word_locator_normalizes_only_equivalent_long_readings():
    from ottosmasher import sample_analysis as analysis

    cue = {"spoken": "まず大きく５つの気候帯に分離"}
    a = {"mora": {"sequence": list("マズオーキクイツツノキコータイニブンリ")}}
    words = analysis.words(cue, a)
    assert words[2]["word"] == "大きく" and words[12]["word"] == "気候帯"
    assert analysis.words({"spoken": "猫"}, {"mora": {"sequence": ["イ", "ヌ"]}}) == {}


def test_parent_reanalysis_does_not_replace_child_measurement(library, monkeypatch):
    from ottosmasher import sample_analysis as a
    from ottosmasher.sample_inference import attach_text

    db, root, _ = library
    raw = audio.resolve(db, root["id"])
    attach_text(db, root["id"], "ねえ")
    result = {"version": "same-model", "phones": [{"label": "e", "start": 0.1, "end": 0.8}]}
    monkeypatch.setattr(a, "get_speech_analysis", lambda *_: result)
    child = c.derive(db, root["id"], start=0.2, end=0.6, input_asset=raw)
    result = {"version": "same-model", "phones": [{"label": "e", "start": 0.3, "end": 0.9}]}
    db.execute("DELETE FROM sample_measurements WHERE material_id=?", (root["id"],))
    db.commit()
    assert a.measurement(db, materials.get(db, root["id"]), "narabas")["phones"][0]["start"] == 0.3
    assert a.measurement(db, child, "narabas")["phones"][0]["start"] == 0.1
    assert child["derivation"]["payload"]["parent_time_map"] == [[0, 0.2], [0.4, 0.6]] or np.allclose(
        child["derivation"]["payload"]["parent_time_map"], [[0, 0.2], [0.4, 0.6]]
    )


def test_retired_alignment_migration_purges_retired_results_preserves_materials(library):
    db, root, _ = library
    assert root["active_phone_backend"] == "narabas"
    db.execute("UPDATE materials SET active_phone_backend='sofa' WHERE id=?", (root["id"],))
    db.execute(
        "INSERT OR REPLACE INTO sample_measurements VALUES(?,?,?)",
        (root["id"], "sofa", '{"historical":true}'),
    )
    db.execute("DELETE FROM alignment_migrations WHERE id='retire-mfa-sofa-v2'")
    c.migrate_alignment_choices(db)
    assert materials.get(db, root["id"])["active_phone_backend"] == "narabas"
    assert db.execute("SELECT payload FROM sample_measurements WHERE material_id=? AND backend='sofa'", (root['id'],)).fetchone() is None
    assert materials.get(db, root['id'])['id'] == root['id']
    c.preferences(db, root["id"], active_phone_backend="narabas")
    c.migrate_alignment_choices(db)
    assert materials.get(db, root["id"])["active_phone_backend"] == "narabas"


def test_pydomino_remains_explicit_backup_and_existing_preference_is_preserved(library):
    db, root, _ = library
    assert root["active_phone_backend"] == "narabas"
    c.preferences(db, root["id"], active_phone_backend="pydomino")
    c.migrate(db)
    again = materials.register_file(db, root["path"])
    assert again["active_phone_backend"] == "pydomino"
    child = c.derive(db, root["id"], start=0.1, end=0.7)
    assert child["active_phone_backend"] == "pydomino"
