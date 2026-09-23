"""Native playback must retain exact source/stem clocks without transcoding video."""

import pytest

from ottosmasher import media_operations, native_player, sample_audio


def files(tmp_path):
    video = tmp_path / "原片 日本語.mkv"
    stem = tmp_path / "对白.wav"
    video.write_bytes(b"original")
    stem.write_bytes(b"stem")
    return video, stem


def test_external_stem_offset_and_lazy_waveform(tmp_path, monkeypatch):
    monkeypatch.setattr(native_player, "DATA", tmp_path)
    video, stem = files(tmp_path)
    monkeypatch.setattr(sample_audio, "pcm", lambda *a: pytest.fail("Existing stem must not be converted"))
    monkeypatch.setattr(media_operations, "proxy", lambda *a: pytest.fail("No video proxy"))
    a = {"path": str(stem), "start": 3, "end": 23, "audio_stream": 0, "role": "dialog"}
    result = native_player.register(video, 103, 123, a, [])
    key = result["url"].split("/")[-1]
    spec = native_player.load(key)
    assert spec["path"] == str(video)
    assert spec["audio_path"] == str(stem)
    assert spec["audio_delay"] == 100
    assert result["origin"] == 103 and result["duration"] == 20
    assert not list(tmp_path.rglob("*.mp4"))
    calls = []
    monkeypatch.setattr(media_operations, "waveform", lambda *a, **kw: calls.append((a, kw)))
    native_player.waveform(key)
    assert calls[0][0] == (str(stem), 3, 23, 0)
    stem.write_bytes(b"changed")
    with pytest.raises(ValueError, match="改变"):
        native_player.load(key)


def test_raw_stream_id_not_container_stream_index(tmp_path, monkeypatch):
    monkeypatch.setattr(native_player, "DATA", tmp_path)
    video, _ = files(tmp_path)
    streams = [
        {"index": 0, "codec_type": "video"},
        {"index": 2, "codec_type": "audio"},
        {"index": 4, "codec_type": "audio"},
    ]
    result = native_player.register(
        video, 0, 1400, {"path": str(video), "start": 0, "end": 1400, "role": "raw", "audio_stream": 4}, streams
    )
    spec = native_player.load(result["url"].split("/")[-1])
    assert spec["aid"] == 2 and spec["audio_path"] is None
    with pytest.raises(ValueError):
        native_player.load("../outside")


def test_missing_stem_is_failure_not_original_mix(tmp_path, monkeypatch):
    monkeypatch.setattr(native_player, "DATA", tmp_path)
    video, stem = files(tmp_path)
    stem.unlink()
    with pytest.raises(FileNotFoundError):
        native_player.register(video, 10, 20, {"path": str(stem), "start": 0, "end": 10, "role": "effects"}, [])
