"""FCPE 前端（规格 14 §14.4、ROADMAP 阶段 4 验收的“FCPE 前端数值”）。"""

from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

import numpy as np
import pytest

from ottosmasher.models import fcpe, registry
from ottosmasher.models.onnx import Device, create_session

MODELS = Path(os.environ.get("OTTO_DEV_MODELS", Path(__file__).resolve().parents[3] / "dev-workspace" / "Models"))
FIXTURES = os.environ.get("OTTO_FIXTURES")


def test_frontend_shapes_and_grid():
    assert fcpe.frame_count(16000) == 100
    assert fcpe.frame_times(3).tolist() == pytest.approx([0.005, 0.015, 0.025])
    # 线性插值：输出点数 = round(N × 16000 / sr)，第 j 点取原信号 j × sr / 16000 处
    x = np.arange(441, dtype=np.float64)
    y = fcpe.resample_linear(x, 44100)
    assert len(y) == 160 and y[1] == pytest.approx(44100 / 16000)
    f = fcpe.mel_filters()
    assert f.shape == (128, 513) and (f >= 0).all() and (f.sum(axis=1) > 0).all()
    # 太短的信号补零到至少一帧
    assert fcpe.frame_count(10) == 1 and len(fcpe.padded(np.zeros(10))) >= 1024
    # 解码：argmax 左右各 4 个 bin 加权；全零 → 音分 0 → 10 Hz
    lat = np.zeros((2, 360), np.float32)
    lat[0, 100] = 1.0
    f0, conf = fcpe.decode(lat)
    assert f0[0] == pytest.approx(10 * 2 ** (fcpe.cents_table()[100] / 1200)) and conf[0] == 1.0
    assert f0[1] == pytest.approx(10.0) and conf[1] == 0.0


@pytest.fixture(scope="module")
def session():
    path, sha = registry.locate("fcpe", fcpe.MODEL_FILE, MODELS, registry.default_support_dir())
    if not path.exists():
        pytest.skip("fcpe weights not in dev-workspace/Models")
    return create_session("fcpe", path, sha, Device(), probe=False)


def test_sine_is_measured(session):
    sr = 44100
    t = np.arange(int(1.0 * sr)) / sr
    x = (0.3 * np.sin(2 * np.pi * 440 * t)).astype(np.float32)[:, None]
    fr = fcpe.measure(session, x, sr)
    assert len(fr) == 100
    rel = fcpe.reliable(fr)
    assert rel[10:90].all()
    cents = 1200 * np.abs(np.log2(fr[10:90, 0] / 440))
    assert np.median(cents) < 10
    assert fr[50, 2] == pytest.approx(0.045, rel=0.05)  # 0.3² / 2


def test_segments_join_into_one_grid(session, monkeypatch):
    sr = 16000
    t = np.arange(int(8.0 * sr)) / sr
    x = (0.3 * np.sin(2 * np.pi * 300 * t)).astype(np.float32)[:, None]
    whole = fcpe.measure(session, x, sr)
    monkeypatch.setattr(fcpe, "SEGMENT_FRAMES", 300)
    monkeypatch.setattr(fcpe, "CONTEXT_FRAMES", 100)
    parts = fcpe.measure(session, x, sr)
    assert parts.shape == whole.shape
    r = fcpe.reliable(whole) & fcpe.reliable(parts)
    assert r.mean() > 0.9
    assert np.median(1200 * np.abs(np.log2(parts[r, 0] / whole[r, 0]))) < 2


@pytest.mark.skipif(not FIXTURES, reason="needs OTTO_FIXTURES")
@pytest.mark.parametrize("name", ["D4", "E5", "Gs5"])
def test_matches_old_reference_features(session, name):
    """旧版对拉平成品算的逐帧特征（参考是编码前的 PCM，我们只能读有损的 MP3，所以留容差）。"""
    d = Path(FIXTURES) / "reference" / "YY1-01_flatten"
    ref = json.loads((d / f"flatten_{name}.features.json").read_text(encoding="utf-8"))
    raw = subprocess.run(["ffmpeg", "-v", "error", "-i", str(d / f"flatten_{name}.mp3"), "-f", "f32le", "-ac", "2", "-"], capture_output=True, check=True).stdout
    audio = np.frombuffer(raw, np.float32).reshape(-1, 2)
    fr = fcpe.measure(session, audio, 44100)
    rf, rc, re_ = np.array(ref["f0_hz"]), np.array(ref["confidence"]), np.array(ref["energy"])
    assert len(fr) == len(rf)
    assert np.allclose(fcpe.frame_times(len(fr)), ref["times"])
    m = rc > 0.5
    assert np.abs(1200 * np.log2(fr[m, 0] / rf[m])).max() < 2.0
    assert np.abs(fr[:, 1] - rc).max() < 0.06
    assert (np.abs(fr[:, 2] - re_) / np.maximum(re_, 1e-9)).max() < 0.06
