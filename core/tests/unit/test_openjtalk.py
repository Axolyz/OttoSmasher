"""pyopenjtalk-plus 的加载（规格 14 §14.2）：导入时不加载任何模型；tsqyomi 用应用建的会话。"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

from ottosmasher.models import registry
from ottosmasher.models.onnx import Device, create_session

SPY = r"""
import sys
import onnxruntime
made = []
class Spy(onnxruntime.InferenceSession):
    def __init__(self, path, *a, **k):
        made.append(str(path))
        super().__init__(path, *a, **k)
onnxruntime.InferenceSession = Spy
from ottosmasher.lang.ja import openjtalk
pj = openjtalk.load()
assert hasattr(pj, "g2p_mapping")
print("sessions", len(made))
print("hf", "huggingface_hub" in sys.modules)
print("tsqyomi", openjtalk.tsqyomi_loaded())
"""


def test_import_loads_no_model():
    out = subprocess.run([sys.executable, "-c", SPY], capture_output=True, text=True, timeout=120, check=True).stdout
    assert "sessions 0" in out
    assert "hf False" in out
    assert "tsqyomi False" in out


def test_import_without_guard_is_refused():
    code = "import pyopenjtalk\nfrom ottosmasher.lang.ja import openjtalk\ntry:\n    openjtalk.load()\nexcept RuntimeError as e:\n    print('refused', e)\n"
    out = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, timeout=120, check=True).stdout
    assert "refused" in out


MODELS = Path(os.environ.get("OTTO_DEV_MODELS", Path(__file__).resolve().parents[3] / "dev-workspace" / "Models"))


def test_tsqyomi_runs_on_the_app_session():
    support = registry.default_support_dir()
    path, sha = registry.locate("tsqyomi", "tsqyomi/model.onnx", MODELS, support)
    if not path.exists():
        pytest.skip("tsqyomi weights not in dev-workspace/Models")
    from ottosmasher.lang.ja import openjtalk
    from ottosmasher.models.probe import PROBE_SENTENCE

    sess = create_session("tsqyomi", path, sha, Device())
    openjtalk.install_tsqyomi(sess, registry.locate("tsqyomi", "tsqyomi/tokenizer.json", MODELS, support), registry.locate("tsqyomi", "tsqyomi/metadata.json", MODELS, support))
    m = openjtalk.load().g2p_mapping(PROBE_SENTENCE, use_tsqyomi=True, normalize_mode="None")
    assert m[0]["phonemes"] == ["n", "a", "n", "i"]
    assert sess.probe and sess.probe["status"] == "passed"
