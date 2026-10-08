"""一句台词的对齐流水线（规格 08 §8.3.2、16 R11.2、R11.3）：用伪前端与伪对齐器控制输出。"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

from ottosmasher.core.errors import CoreError
from ottosmasher.jobs.speech import align_item, to_16k
from ottosmasher.lang.ja import frontend as fe
from ottosmasher.media.wavfile import save_wav24
from ottosmasher.models.domino import Alignment

SR = 48000


def _frontend(phonemes, morae):
    def analyze(text):
        return fe.FrontendResult(text, text, phonemes, list(range(len(phonemes))), [0] * len(phonemes), [], morae, [0] * len(morae), {"frontend": "x"})

    return analyze


class FakeAligner:
    def __init__(self, labels_times):
        self.out = labels_times
        self.seen = None

    def align(self, wave, seq, min_frames=1):
        self.seen = (len(wave), seq)
        return Alignment(self.out, 100, 1)


@pytest.fixture
def spec(tmp_path: Path):
    x = np.zeros((SR, 2), dtype=np.float32)
    x[int(0.3 * SR) : int(0.6 * SR)] = 0.2
    p = tmp_path / "a.wav"
    save_wav24(p, x, SR)
    return {"text": "x", "file": {"path": str(p), "ordinal": 0, "sample_rate": SR, "channels": 2, "codec": "pcm_s24le", "format": "wav"}, "frames": [0, SR], "window": [10.0, 11.0]}


def test_times_become_asset_local_and_devoiced_vowels_keep_original(spec, tmp_path):
    al = FakeAligner([(0.0, 0.2, "pau"), (0.2, 0.3, "k"), (0.3, 0.6, "I"), (0.6, 0.6, "pau"), (0.6, 0.7, "a"), (0.7, 1.0, "pau")])
    r = align_item(spec, _frontend(["k", "I", "pau", "a"], ["キ", "ア"]), al, cache=tmp_path)
    assert al.seen == (16000, ["pau", "k", "i", "pau", "a", "pau"])  # 送进模型的是小写 i
    assert [(p["label"], p["start"], p["end"]) for p in r["phones"]] == [("k", 10.2, 10.3), ("i", 10.3, 10.6), ("pau", 10.6, 10.6), ("a", 10.6, 10.7)]
    assert r["phones"][1]["orig"] == "I" and "orig" not in r["phones"][0]
    assert r["phones"][1]["eff"][0] >= 10.3 and "strength" in r["phones"][1]
    assert "eff" not in r["phones"][0]


def test_attribution_must_be_exact(spec, tmp_path):
    al = FakeAligner([(0.0, 0.2, "pau"), (0.2, 0.3, "k"), (0.3, 0.6, "o"), (0.6, 1.0, "pau")])
    with pytest.raises(CoreError) as e:
        align_item(spec, _frontend(["k", "a"], ["カ"]), al, cache=tmp_path)
    assert e.value.code == "align-ambiguous"


def test_resample_to_16k():
    t = np.arange(SR) / SR
    x = np.stack([np.sin(2 * np.pi * 100 * t)] * 2, axis=1)
    y = to_16k(x, SR)
    assert y.dtype == np.float32 and len(y) == 16000
    assert np.max(np.abs(y[100:-100] - np.sin(2 * np.pi * 100 * np.arange(16000) / 16000)[100:-100])) < 1e-3
