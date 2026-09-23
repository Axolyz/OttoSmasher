"""Prevent raw-audio fallback and cross-version analysis/render mismatches."""

import hashlib
from pathlib import Path

import numpy as np
import pytest
import soundfile as sf

from ottosmasher import catalog, media, workspace
from ottosmasher.rhythm import RhythmQuery, search_rhythm
from ottosmasher.vocals import read_aligned_input


@pytest.fixture
def separated_cue(tmp_path, monkeypatch):
    monkeypatch.setattr(workspace, "DATA", tmp_path / "data")
    monkeypatch.setattr(media, "DATA", tmp_path / "data")
    monkeypatch.setattr(media, "ROOT", tmp_path)
    raw = tmp_path / "素材"
    raw.mkdir()
    sr = 48000
    t = np.arange(3 * sr) / sr
    sf.write(raw / "test.wav", 0.2 * np.sin(2 * np.pi * 220 * t) + 0.1 * np.sin(2 * np.pi * 880 * t), sr)
    (raw / "test.srt").write_text("1\n00:00:00,650 --> 00:00:02,350\nああ\n")
    catalog.import_directory(raw)
    db = workspace.connect()
    cue = workspace.get_cue(db, catalog.search_text(db)[0]["id"])
    vocal = tmp_path / "vocals.wav"
    sf.write(vocal, 0.2 * np.sin(2 * np.pi * 220 * t), sr)
    lineage = {
        "audio_path": str(vocal),
        "audio_sha256": hashlib.sha256(vocal.read_bytes()).hexdigest(),
        "source_fingerprint": cue["fingerprint"],
        "window_start": 0,
        "window_end": 3,
        "model": "test-separation-fixture",
        "stem": "vocals",
    }
    yield db, cue, lineage
    db.close()


def test_mixed_alignment_cannot_enter_normal_speech_search(separated_cue):
    db, cue, _ = separated_cue
    payload = {
        "window_start": 0,
        "window_end": 3,
        "anchors": [{"time": 0}, {"time": 0.5}],
        "flags": ["mixed_audio"],
        "verified": False,
        "version": "mixed-test",
    }
    workspace.save_analysis(db, cue["id"], "phonetic", "mixed-test", payload)
    query = RhythmQuery(cells=[{"state": "required"}, {"state": "any"}])
    assert search_rhythm(db, query)["searched_cues"] == 0
    assert workspace.get_speech_analysis(db, cue["id"], "phonetic") is None
    assert workspace.get_analysis(db, cue["id"], "phonetic") is not None


def test_missing_or_changed_vocals_fail_without_raw_fallback(separated_cue):
    _, cue, lineage = separated_cue
    with pytest.raises(ValueError, match="No separated vocals"):
        media.render(cue, variant="vocals")
    with pytest.raises(ValueError, match="requires a recorded vocals"):
        read_aligned_input({"input_variant": "raw"})
    Path(lineage["audio_path"]).write_bytes(b"changed")
    with pytest.raises(ValueError, match="checksum"):
        media.render(cue, variant="vocals", lineage=lineage)


def test_audition_and_export_use_selected_stem(separated_cue):
    _, cue, lineage = separated_cue
    raw, _ = media.render(cue)
    vocals, manifest = media.render(cue, variant="vocals", lineage=lineage)
    assert raw != vocals
    y, sr = sf.read(vocals)
    spectrum = abs(np.fft.rfft(y))
    frequencies = np.fft.rfftfreq(len(y), 1 / sr)
    assert spectrum[np.argmin(abs(frequencies - 880))] < spectrum[np.argmin(abs(frequencies - 220))] * 0.001
    exported = media.export_bundle(cue, variant="vocals", lineage=lineage)
    assert "ああ__vocals" in Path(exported["audio"]).name
    assert exported["manifest"]["audio_variant"] == "vocals"
    assert exported["manifest"]["audio_lineage"]["audio_sha256"] == lineage["audio_sha256"]
    assert manifest["source_start"] == 0


def test_only_complete_matching_lineage_is_read_for_features(separated_cue):
    _, _, lineage = separated_cue
    y, sr, start, end = read_aligned_input(
        {"input_variant": "vocals", "audio_lineage": lineage, "window_start": 0, "window_end": 3}
    )
    assert len(y) / sr == pytest.approx(end - start)
    with pytest.raises(ValueError, match="window does not match"):
        read_aligned_input(
            {"input_variant": "vocals", "audio_lineage": lineage, "window_start": 1, "window_end": 4}
        )


def test_selected_backend_controls_vocals_asset(separated_cue):
    db, cue, lineage = separated_cue
    alternate = {**lineage, "model": "different-separation-version"}
    for kind, asset in (("phonetic", lineage), ("mfa", alternate)):
        workspace.save_analysis(
            db, cue["id"], kind, "test", {"input_variant": "vocals", "audio_lineage": asset}
        )
    assert workspace.get_vocals_lineage(db, cue["id"], "mfa") == alternate
    exported = media.export_bundle(
        cue,
        analysis={"input_variant": "vocals", "audio_lineage": alternate},
        variant="vocals",
        lineage=lineage,
    )
    assert exported["manifest"]["audio_lineage"] == alternate
    with pytest.raises(ValueError, match="must reference separated vocals"):
        media.export_bundle(cue, analysis={"input_variant": "raw"}, variant="vocals", lineage=lineage)
