import sys

import numpy as np
import pytest
import soundfile as sf

from ottosmasher import studio


def test_worker_forbids_downloads_and_keeps_external_environment(tmp_path, monkeypatch):
    script = tmp_path / "worker.py"
    script.write_text("""import json,sys
p=json.load(open(sys.argv[-1]))
assert p['download'] is False
print(json.dumps({'type':'task_done','payload':{'seen':p}}))
""")
    monkeypatch.setattr(
        studio,
        "configuration",
        lambda: {"python": sys.executable, "worker": str(script), "models": str(tmp_path), "env": {}},
    )
    result = studio.call("infer", {"download": True}, tmp_path)
    assert result[-1]["payload"]["seen"]["download"] is False


def test_worker_error_is_not_a_fallback(tmp_path, monkeypatch):
    script = tmp_path / "worker.py"
    script.write_text('print(\'{"type":"error","payload":{"code":"MODEL_NOT_FOUND"}}\')')
    monkeypatch.setattr(
        studio,
        "configuration",
        lambda: {"python": sys.executable, "worker": str(script), "models": str(tmp_path), "env": {}},
    )
    with pytest.raises(RuntimeError, match="MODEL_NOT_FOUND"):
        studio.call("infer", {}, tmp_path)


def test_installed_models_and_aliases_only(monkeypatch):
    monkeypatch.setattr(
        studio,
        "models",
        lambda: [{"name": "a.ckpt", "aliases": ["a"], "configInstruments": "vocals|instrument"}],
    )
    assert studio.select("a", ["vocals"])["name"] == "a.ckpt"
    with pytest.raises(ValueError, match="已下载"):
        studio.select("missing")
    with pytest.raises(ValueError, match="声部"):
        studio.select("a", ["speech"])


def test_incomplete_or_time_changed_output_never_registered(tmp_path, monkeypatch):
    inp = tmp_path / "input.wav"
    out = tmp_path / "result"
    out.mkdir()
    target = out / "vocals.wav"
    sf.write(inp, np.zeros(1600), 16000)
    sf.write(target, np.zeros(800), 16000)
    monkeypatch.setattr(studio, "select", lambda *a: {"name": "a", "configInstruments": "vocals"})
    monkeypatch.setattr(studio, "fingerprint", lambda *a: {"model": "a", "provider": "studio"})
    monkeypatch.setattr(
        studio,
        "call",
        lambda *a, **k: [
            {
                "type": "task_done",
                "taskId": "input-0",
                "payload": {"outputs": [{"path": str(target), "stem": "vocals"}]},
            }
        ],
    )
    with pytest.raises(ValueError, match="时长"):
        studio.separate_many("a", [inp], out, ["vocals"])
    assert not (out / "manifest.json").exists()
    monkeypatch.setattr(studio, "call", lambda *a, **k: [])
    with pytest.raises(RuntimeError, match="全部输入"):
        studio.separate_many("a", [inp], out, ["vocals"])
