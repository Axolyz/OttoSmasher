import hashlib
from pathlib import Path

import numpy as np
import pytest
import soundfile as sf
from praatio import textgrid

from ottosmasher import catalog, media, workspace


@pytest.fixture
def corpus(tmp_path, monkeypatch):
    monkeypatch.setattr(workspace, "DATA", tmp_path / "data")
    monkeypatch.setattr(media, "DATA", tmp_path / "data")
    monkeypatch.setattr(media, "ROOT", tmp_path)
    folder = tmp_path / "素材_日本語"
    folder.mkdir()
    sr = 16000
    t = np.arange(4 * sr) / sr
    audio = folder / "第01集.wav"
    sf.write(audio, 0.2 * np.sin(2 * np.pi * 220 * t), sr)
    (folder / "第01集.srt").write_text(
        "1\n00:00:00,100 --> 00:00:01,100\n(サーバル)すごーい！\n\n"
        "2\n00:00:01,300 --> 00:00:02,000\n(サーバルの寝息)\n\n"
        "3\n00:00:02,200 --> 00:00:03,500\n今日はいい天気\n",
        encoding="utf-8-sig",
    )
    return folder, audio


def test_import_unicode_annotations_resume_and_source_changes(corpus):
    folder, audio = corpus
    digest = hashlib.sha256(audio.read_bytes()).hexdigest()
    assert catalog.import_directory(folder) == {"imported": 1, "unchanged": 0, "cues": 3, "errors": []}
    assert catalog.import_directory(folder)["unchanged"] == 1
    with workspace.connect() as db:
        rows = catalog.search_text(db, "すごーい")
        assert len(rows) == 1 and rows[0]["speaker"] == "サーバル"
        assert rows[0]["spoken"] == "すごーい！"
        assert len(catalog.neighbors(db, rows[0]["id"])) == 3
        events = catalog.search_text(db, "寝息")
        assert events[0]["spoken"] == "" and events[0]["kind"] == "event"
        assert len(catalog.search_text(db, "きょう")) == 1
    assert hashlib.sha256(audio.read_bytes()).hexdigest() == digest
    audio.with_suffix(".srt").write_text("changed")
    assert len(catalog.import_directory(folder)["errors"]) == 1


def test_subtitle_padding_clamps_to_media_and_export_tracks_origin(corpus):
    folder, _audio = corpus
    catalog.import_directory(folder)
    db = workspace.connect()
    cue = workspace.get_cue(db, catalog.search_text(db, "すごーい")[0]["id"])
    assert media.window(cue) == pytest.approx((0, 1.75))
    y, sr, _start, _end = media.read_window(cue)
    assert len(y) / sr == pytest.approx(1.75)
    path, manifest = media.render(cue, 1.25)
    assert manifest["actual_duration"] == pytest.approx(1.75 * 1.25, abs=0.06)
    original_peak = np.fft.rfftfreq(len(y), 1 / sr)[np.argmax(abs(np.fft.rfft(y)))]
    warped, sr2 = sf.read(path)
    warped_peak = np.fft.rfftfreq(len(warped), 1 / sr2)[np.argmax(abs(np.fft.rfft(warped)))]
    assert abs(warped_peak - original_peak) < 3
    result = media.export_bundle(cue)
    assert Path(result["path"], "manifest.json").exists()
    tg = textgrid.openTextgrid(
        str(Path(result["audio"]).with_suffix(".TextGrid")), includeEmptyIntervals=False
    )
    assert "subtitle_unverified" in tg.tierNames
    db.close()


def test_import_failure_rolls_back_entire_episode(corpus):
    folder, audio = corpus
    with audio.with_suffix(".srt").open("a") as f:
        f.write("\n4\n00:00:09,000 --> 00:00:10,000\nout of range\n")
    assert catalog.import_directory(folder)["errors"]
    with workspace.connect() as db:
        assert db.execute("SELECT count(*) FROM sources").fetchone()[0] == 0
        assert db.execute("SELECT count(*) FROM cues").fetchone()[0] == 0


def test_api_validates_missing_features_and_local_access(corpus):
    from fastapi.testclient import TestClient

    from ottosmasher.api import app

    catalog.import_directory(corpus[0])
    client = TestClient(app)
    assert client.get("/api/ui/settings").status_code == 200
    assert client.get("/api/ui/settings", headers={"Host": "evil.example"}).status_code == 403
    assert client.post("/api/samples/rhythm", json={}, headers={"Origin": "https://evil.example"}).status_code == 403
    assert client.get("/api/stats").status_code == 404  # retired demo
    assert client.get("/api/workflows").status_code == 404


def test_failed_new_analysis_never_falls_back_to_old_success(corpus):
    catalog.import_directory(corpus[0])
    with workspace.connect() as db:
        cue_id = catalog.search_text(db, "すごーい")[0]["id"]
        workspace.save_analysis(db, cue_id, "mfa", "v1", {"anchors": [{"time": 1}]})
        workspace.save_analysis(db, cue_id, "mfa", "v2", {"anchors": [], "error": "alignment failed"})
        assert workspace.get_analysis(db, cue_id, "mfa")["anchors"] == []
        assert catalog.stats(db)["analyses"].get("mfa", 0) == 0


def test_rendered_rhythm_anchors_follow_global_scale(corpus):
    from scipy.signal import find_peaks

    folder, audio = corpus
    sr = 16000
    t = np.arange(4 * sr) / sr
    envelope = sum(np.exp(-(((t - center) / 0.035) ** 2)) for center in [0.5, 1.5, 2.5])
    sf.write(audio, 0.5 * envelope * np.sin(2 * np.pi * 220 * t), sr)
    catalog.import_directory(folder)
    db = workspace.connect()
    cue = workspace.get_cue(db, catalog.search_text(db, "すごーい")[0]["id"])
    cue["start"] = 0
    cue["end"] = 3.2
    path, _ = media.render(cue, factor=1.25, padding=0)
    y, sr = sf.read(path)
    frames = y[: len(y) // 480 * 480].reshape(-1, 480)
    rms = np.sqrt(np.mean(frames**2, axis=1))
    peaks, _ = find_peaks(rms, prominence=0.05, distance=30)
    times = (peaks * 480 + 240) / sr
    assert times == pytest.approx(np.array([0.5, 1.5, 2.5]) * 1.25, abs=0.055)
    db.close()
