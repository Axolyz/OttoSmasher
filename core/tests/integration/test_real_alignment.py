"""S1.8（规格 16）：YY1-01 人声轨上 9 句台词的对齐与旧版参考输出对比（采样选区 ± 0.65 秒、只送本句）。
需要 OTTO_FIXTURES 与 dev-workspace/Models 里的 pydomino、tsqyomi；只在本地跑，素材不进仓库。"""

from __future__ import annotations

import json
import os
from pathlib import Path

import numpy as np
import pytest

FIXTURES = os.environ.get("OTTO_FIXTURES")
MODELS = Path(os.environ.get("OTTO_DEV_MODELS", Path(__file__).resolve().parents[3] / "dev-workspace" / "Models"))
pytestmark = pytest.mark.skipif(not FIXTURES or not (MODELS / "pydomino").exists(), reason="needs OTTO_FIXTURES and dev models")

# 第一句的正确对齐文本（旧版把说话人「千歳」读进去了，14 §14.3）
FIRST = "あなたってば何なの？おジャマします"


@pytest.fixture(scope="module")
def setup(tmp_path_factory):
    from ottosmasher.lang.ja.runtime import JaRuntime
    from ottosmasher.media import probe
    from ottosmasher.models import domino, registry
    from ottosmasher.models.onnx import Device, create_session

    support = registry.default_support_dir()
    rt = JaRuntime(MODELS, support, Device(), None, "none")
    path, sha = registry.locate("pydomino", domino.MODEL_FILE, MODELS, support)
    aligner = domino.Aligner(create_session("pydomino", path, sha, Device()))
    vox = Path(FIXTURES) / "stems" / "YY1-01" / "hyperacev2_vocals.mp3"
    pr = probe.probe(str(vox))
    ref = json.loads((Path(FIXTURES) / "reference" / "YY1-01_pydomino_fa_old_output.json").read_text(encoding="utf-8"))
    return rt, aligner, vox, pr, ref["runs"], tmp_path_factory.mktemp("cache")


def run(setup, i: int, text: str):
    from ottosmasher.jobs.speech import align_item

    rt, aligner, vox, pr, runs, cache = setup
    a0 = pr.audio[0]
    sr = a0.sample_rate
    s, e = runs[i]["sample_range_source_seconds_padded"]
    a, b = round((s - 0.65) * sr), round((e + 0.65) * sr)
    spec = {
        "text": text,
        "file": {"path": str(vox), "ordinal": 0, "sample_rate": sr, "channels": a0.channels, "codec": a0.codec, "format": pr.format_name},
        "frames": [a, b],
        "window": [a / sr, b / sr],
    }
    return align_item(spec, rt, aligner, cache=cache), runs[i]


@pytest.mark.parametrize("i", range(1, 9))
def test_eight_sentences_match_reference(setup, i):
    res, ref = run(setup, i, setup[4][i]["sample_title_in_old_app"].replace("\n", " "))
    ours = [(p["label"], p["start"], p["end"]) for p in res["phones"]]
    theirs = [(p["label"], p["start"], p["end"]) for p in ref["phones"]]
    assert [x[0] for x in ours] == [x[0] for x in theirs]
    d = np.abs(np.array([[o[1] - t[1], o[2] - t[2]] for o, t in zip(ours, theirs, strict=True)]))
    assert d.max() < 0.011  # 一帧以内
    # 派生：每个元音/N 都有有效范围与强度
    for p in res["phones"]:
        if p["label"] in ("a", "i", "u", "e", "o", "N"):
            assert "eff" in p and p["eff"][0] >= p["start"] - 1e-9 and p["eff"][1] <= p["end"] + 1e-9


def test_first_sentence_without_the_speaker_name(setup):
    res, ref = run(setup, 0, FIRST)
    labels = [p["label"] for p in res["phones"]]
    assert labels == "a n a t a cl t e b a n a N n a n o pau o j a m a sh i m a s u".split()
    # 说话人之前的部分与参考的边界接近
    for o, t in zip(res["phones"][:17], ref["phones"][:17], strict=True):
        assert o["label"] == t["label"] and abs(o["start"] - t["start"]) < 0.05
