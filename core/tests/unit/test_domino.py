"""pydomino 对齐（规格 14 §14.3）：序列准备、上游 tokenizer 与 Viterbi（本机扩展）、输出区间。"""

from __future__ import annotations

import os
from pathlib import Path

import numpy as np
import pytest

from ottosmasher.core.errors import CoreError
from ottosmasher.models import domino, registry
from ottosmasher.models.onnx import Device, create_session


def _native():
    try:
        return domino.native()
    except CoreError:
        pytest.skip("native _domino not built (tools/uv run --with setuptools python tools/build_domino.py)")


def test_prepare_sequence():
    # 清音 I/U → 小写、sil/sp → pau、每句后 pau、最前面 pau、相邻 pau 合并；重复元音不合并
    assert domino.prepare_sequence([["k", "I", "sil", "e", "e"], ["sp", "N"]]) == ["pau", "k", "i", "pau", "e", "e", "pau", "N", "pau"]
    assert domino.prepare_sequence([["a"]]) == ["pau", "a", "pau"]


def test_tokenizer_matches_upstream_rules():
    mod = _native()
    ids = mod.tokenize("pau k i pau")
    # 上游按自己的规则判定清音：k + i + pau → I
    assert mod.to_phonemes(ids) == ["pau", "k", "I", "pau"]
    assert mod.to_phonemes(mod.tokenize("pau a a pau")) == ["pau", "a", "a", "pau"]
    with pytest.raises(ValueError, match="not defined"):
        mod.tokenize("pau kw a pau")


class FakeSession:
    """输出可控的“模型”：在指定帧上让对应的转移概率最大。"""

    def __init__(self, frames: int, vocab: int, hits: dict[int, int]):
        self.frames, self.vocab, self.hits = frames, vocab, hits

    def run(self, outputs, feeds):
        assert outputs == ["transition_logprobs", "blank_logprobs"]
        trans = np.full((1, self.frames, self.vocab), -20.0, dtype=np.float32)
        blank = np.full((1, self.frames), -0.01, dtype=np.float32)
        for frame, token in self.hits.items():
            trans[0, frame, token] = -0.01
            blank[0, frame] = -20.0
        return [trans, blank]


def test_viterbi_places_transitions_where_the_model_says():
    mod = _native()
    seq = ["pau", "a", "i", "pau"]
    ids = mod.tokenize(" ".join(seq))
    sess = FakeSession(100, 557, {20: ids[0], 50: ids[1], 80: ids[2]})
    al = domino.Aligner(sess, mod).align(np.zeros(16000, dtype=np.float32), seq)  # type: ignore[arg-type]
    assert [x[2] for x in al.intervals] == ["pau", "a", "i", "pau"]
    assert [(round(a, 2), round(b, 2)) for a, b, _ in al.intervals] == [(0.0, 0.2), (0.2, 0.5), (0.5, 0.8), (0.8, 1.0)]
    assert al.frames == 100 and al.min_frames == 1


def test_min_frames_shrinks_and_errors():
    mod = _native()
    seq = ["pau", "a", "i", "u", "e", "pau"]
    ids = mod.tokenize(" ".join(seq))
    al = domino.Aligner(FakeSession(4, 557, {}), mod).align(np.zeros(640, dtype=np.float32), seq, min_frames=3)  # type: ignore[arg-type]
    assert al.min_frames == (4 - 1) // (len(ids) - 1)
    with pytest.raises(CoreError) as e:
        domino.Aligner(FakeSession(1, 557, {}), mod).align(np.zeros(160, dtype=np.float32), seq)  # type: ignore[arg-type]
    assert e.value.code == "align-audio-too-short"
    with pytest.raises(CoreError) as e:
        domino.Aligner(FakeSession(10, 557, {}), mod).align(np.zeros(1600, dtype=np.float32), ["pau", "kw", "a", "pau"])  # type: ignore[arg-type]
    assert e.value.code == "align-unsupported"
    with pytest.raises(CoreError):
        domino.Aligner(FakeSession(10, 557, {}), mod).align(np.zeros(1600, dtype=np.float32), ["pau"])  # type: ignore[arg-type]


MODELS = Path(os.environ.get("OTTO_DEV_MODELS", Path(__file__).resolve().parents[3] / "dev-workspace" / "Models"))


def test_real_model_runs_through_the_factory():
    mod = _native()
    path, sha = registry.locate("pydomino", domino.MODEL_FILE, MODELS, registry.default_support_dir())
    if not path.exists():
        pytest.skip("pydomino weights not in dev-workspace/Models")
    sess = create_session("pydomino", path, sha, Device())
    t = np.arange(16000) / 16000
    wave = (0.1 * np.sin(2 * np.pi * 220 * t)).astype(np.float32)
    al = domino.Aligner(sess, mod).align(wave, domino.prepare_sequence([["a", "i"]]))
    assert [x[2] for x in al.intervals] == ["pau", "a", "i", "pau"]
    ends = [b for _, b, _ in al.intervals]
    assert ends == sorted(ends) and ends[-1] == pytest.approx(1.0)
    assert sess.probe and sess.probe["status"] == "passed"
