import json
import subprocess

import numpy as np
import pytest
import soundfile as sf

from ottosmasher import media_operations as media
from ottosmasher import media_visualization as display


@pytest.fixture
def audio(tmp_path, monkeypatch):
    monkeypatch.setattr(display, "DATA", tmp_path)
    monkeypatch.setattr(media, "DATA", tmp_path)
    path = tmp_path / "原声.wav"
    sr = 48000
    y = np.concatenate([np.sin(2 * np.pi * f * np.arange(sr) / sr) * 0.3 for f in (440, 2000)])
    sf.write(path, y, sr)
    return path


def test_spectrum_uses_selected_audio_window_not_waveform_peaks(audio):
    w = media.waveform(audio, 0.5, 2, bins=64)
    d = display.detail(w["visualization_key"], 0.6, 1.3)
    matrix = np.asarray(json.loads(display.spectrum_path(d["key"]).read_text()))[0]
    peak = np.argmax(matrix[2:-2].mean(axis=0)) * d["sample_rate"] / d["fft_samples"]
    assert abs(peak - 2000) < 30
    assert d["start"] == 0.6 and d["end"] == 1.3
    assert matrix.shape[1] == 1024
    assert display.detail(w["visualization_key"], 0.6, 1.3) == d
    with pytest.raises(ValueError, match="越界"):
        display.detail(w["visualization_key"], 0, 2)
    audio.touch()
    with pytest.raises(ValueError, match="改变"):
        display.detail(w["visualization_key"], 0, 1)


def test_long_waveform_streams_with_bounded_peaks_and_spectrum(audio, tmp_path):
    path = tmp_path / "20分钟.wav"
    # Write in chunks instead of allocating an episode-size array.
    with sf.SoundFile(path, "w", samplerate=8000, channels=1) as out:
        for _ in range(1201):
            out.write(np.zeros(8000))
    w = media.waveform(path, bins=32000)
    assert w["duration"] == 1201
    assert len(w["peaks"][0]) <= 32000
    with pytest.raises(ValueError, match="最多 30"):
        display.detail(w["visualization_key"], 0, 1201)
    assert display.detail(w["visualization_key"], 1190, 1201)["end"] == 1201


def test_full_proxy_supports_seekable_video_and_http_ranges(audio, tmp_path, monkeypatch):
    from fastapi import FastAPI
    from fastapi.responses import FileResponse
    from fastapi.testclient import TestClient

    source = tmp_path / "clip.mkv"
    subprocess.run(
        [
            media.executable("ffmpeg"),
            "-v",
            "error",
            "-f",
            "lavfi",
            "-i",
            "color=size=96x64:rate=10:duration=2",
            "-i",
            str(audio),
            "-c:v",
            "libx264",
            "-c:a",
            "flac",
            str(source),
        ],
        check=True,
    )
    p = media.proxy(source, 0, 2, 1)
    assert p["duration"] == 2
    assert media.proxy(source, 0, 2, 1) == p
    app = FastAPI()

    @app.get("/video")
    def video():
        return FileResponse(p["path"])

    client = TestClient(app)
    r = client.get("/video", headers={"Range": "bytes=100-199"})
    assert r.status_code == 206 and len(r.content) == 100
