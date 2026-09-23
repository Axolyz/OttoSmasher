from pathlib import Path

import numpy as np
import pytest
import soundfile as sf
from test_samples import library as library  # noqa: PLC0414 - pytest fixture

from ottosmasher import operation_jobs, sample_audio, source_separation, vocals
from ottosmasher import stream_preview as stream


def test_lazy_segments_keep_selected_stem_and_source_clock(tmp_path, monkeypatch):
    monkeypatch.setattr(stream, "DATA", tmp_path)
    video = tmp_path / "原片.mkv"
    video.write_bytes(b"video")
    stem = tmp_path / "对白.wav"
    stem.write_bytes(b"audio")
    a = {"path": str(stem), "start": 3, "end": 22, "role": "dialog", "audio_stream": 0}
    result = stream.register(video, 103, 122, a)
    key = result["url"].split("/")[-2]
    assert not list(tmp_path.rglob("*.ts"))
    assert "#EXTINF:3.000000" in stream.playlist(key)
    calls = []

    def encode(args):
        calls.append(args)
        Path(args[-1]).write_bytes(b"segment")

    monkeypatch.setattr(stream, "command", encode)
    stream.segment(key, 1)
    args = calls[0]
    assert args[args.index("-ss") + 1] == "111"
    assert str(stem) in args and "1:0" in args
    assert "11" in args  # selected stem's own local clock
    stream.segment(key, 1)
    assert len(calls) == 1
    with pytest.raises(ValueError):
        stream.segment(key, 3)
    with pytest.raises(ValueError):
        stream.load("../escape")
    video.write_bytes(b"changed")
    with pytest.raises(ValueError, match="改变"):
        stream.playlist(key)


def test_segment_cache_only_prunes_disposable_segments(tmp_path, monkeypatch):
    monkeypatch.setattr(stream, "DATA", tmp_path)
    monkeypatch.setattr(stream, "CACHE_BYTES", 10)
    folder = tmp_path / "cache/streams/k"
    folder.mkdir(parents=True)
    keep = folder / "1.ts"
    old = folder / "0.ts"
    old.write_bytes(b"x" * 8)
    keep.write_bytes(b"y" * 8)
    manifest = folder / "source.json"
    manifest.write_text("{}")
    stream.trim_cache(keep)
    assert not old.exists() and keep.exists() and manifest.exists()


def test_separation_available_before_any_phone_analysis(library, monkeypatch, tmp_path):
    db, material, _ = library

    class Borrow:
        def __enter__(self):
            return db

        def __exit__(self, *args):
            pass

    monkeypatch.setattr(vocals, "connect", Borrow)
    path = tmp_path / "vocals.wav"
    sf.write(path, np.ones(24000), 24000)
    cue = {
        "id": "no-text",
        "source_id": material["source_id"],
        "fingerprint": material["fingerprint"],
        "audio_stream": material["audio_stream"],
    }
    lineage = {"id": "prepared", "audio_path": str(path), "window_start": 0, "window_end": 1, "model": "test"}
    vocals.register_reference(cue, lineage)
    a = sample_audio.resolve(db, material["id"], "vocals")
    assert a["path"] == str(path)
    assert db.execute("SELECT count(*) FROM analyses").fetchone()[0] == 0
    vocals.register_reference(cue, lineage)
    assert db.execute("SELECT count(*) FROM shared_sample_audio").fetchone()[0] == 1
    with pytest.raises(ValueError, match="缺少完整"):
        sample_audio.resolve_range(db, material, 0, 1, "vocals", material["audio_stream"] + 1)


def test_three_stem_submission_independent_of_discovery(library, monkeypatch):
    db, _, _ = library
    monkeypatch.setattr(operation_jobs, "submit", lambda op, p: p)
    result = source_separation.submit(db, "tracks", {"routes": ["bandit-v2"]})
    assert result["request"]["routes"] == ["bandit-v2"]
