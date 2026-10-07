"""波形峰值：后台生成、点数上限、区间切片（规格 05 §5.3.2、16 R22.10）。"""

import shutil
import subprocess
import threading

import numpy as np
import pytest

from ottosmasher.core import assets as assets_mod
from ottosmasher.core.errors import CoreError
from ottosmasher.core.sources import SourceService
from ottosmasher.core.waveforms import WaveformService
from ottosmasher.media import peaks as peaks_mod
from ottosmasher.media.decode import StreamRef

pytestmark = pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="ffmpeg not on PATH")
SR = 48000


@pytest.fixture
def steps_wav(tmp_path):
    """0–1 秒静音，1–2 秒幅度 0.5，2–3 秒幅度 0.9（方波，峰值精确）。"""
    t = np.arange(SR * 3)
    sq = np.where((t // 24) % 2 == 0, 1.0, -1.0)
    amp = np.select([t < SR, t < 2 * SR], [0.0, 0.5], 0.9)
    x = (sq * amp * 32767).astype(np.int16)
    raw = tmp_path / "s.s16"
    x.tofile(raw)
    f = tmp_path / "steps ♪.wav"
    subprocess.run(["ffmpeg", "-v", "error", "-f", "s16le", "-ar", str(SR), "-ac", "1", "-i", str(raw), str(f)], check=True)
    return f


def ref_of(f):
    return StreamRef(str(f), 0, SR, 1, "pcm_s16le", "wav")


def test_build_and_query(steps_wav, tmp_path):
    pk = peaks_mod.build(ref_of(steps_wav), tmp_path)
    assert pk.frames == SR * 3
    for (a, b), amp in zip([(0.1, 0.9), (1.1, 1.9), (2.1, 2.9)], [0.0, 0.5, 0.9]):
        q = pk.query(a, b, 1)
        assert q["count"] == 1
        assert np.frombuffer(q["max"], dtype="<f4")[0] == pytest.approx(amp, abs=1e-3)
        assert np.frombuffer(q["min"], dtype="<f4")[0] == pytest.approx(-amp, abs=1e-3)
    q = pk.query(0.0, 3.0, 300)
    assert q["count"] <= 300 and q["start"] == 0.0
    assert q["step"] * q["count"] >= 3.0
    # 点数上限
    big = pk.query(0.0, 3.0, 10**6)
    assert big["count"] <= peaks_mod.MAX_POINTS
    assert pk.query(1.5, 2.5, 100)["count"] <= 100
    with pytest.raises(CoreError):
        pk.query(2.0, 3.5, 10)
    # 缓存：再读一次不重建；文件变了换新键
    assert peaks_mod.load(tmp_path, ref_of(steps_wav)) is not None
    with open(steps_wav, "ab") as fh:
        fh.write(b"\x00\x00")
    assert peaks_mod.load(tmp_path, ref_of(steps_wav)) is None


def test_service_pending_then_ready(db, ws, steps_wav):
    [r] = SourceService(db, workspace_root=ws.root).add([str(steps_wav)])
    aid = assets_mod.list_for_source(db, r["sourceId"])[0]["id"]
    events = []
    done = threading.Event()

    def emit(name, data):
        events.append((name, data))
        done.set()

    svc = WaveformService(db, ws, post=lambda fn: fn(), emit=emit)
    # 登记时已经顺带生成了峰值
    assert svc.get(aid, 0.0, 3.0, 300)["state"] == "ready"
    shutil.rmtree(ws.root / "Data" / "Cache" / "Peaks")
    first = svc.get(aid, 0.0, 3.0, 300)
    assert first == {"state": "pending"}
    assert svc.get(aid, 1.0, 2.0, 100) == {"state": "pending"}  # 同一文件只生成一次
    assert done.wait(30)
    assert events == [("peaks.ready", {"assetIds": [aid]})]
    q = svc.get(aid, 1.0, 2.0, 10)
    assert q["state"] == "ready" and q["count"] <= 10
    assert q["start"] == pytest.approx(1.0, abs=0.01)
    assert np.frombuffer(q["max"], dtype="<f4").max() == pytest.approx(0.5, abs=1e-3)
    with pytest.raises(CoreError):
        svc.get(aid, 2.5, 3.5, 10)
    svc.shutdown()


def test_detail_window_uses_exact_samples(db, ws, steps_wav):
    # 细节窗（≤30 秒）：放大到点数多于缓存桶时，直接解码这段，逐样本可见
    [r] = SourceService(db, workspace_root=ws.root).add([str(steps_wav)])
    aid = assets_mod.list_for_source(db, r["sourceId"])[0]["id"]
    svc = WaveformService(db, ws, post=lambda fn: fn(), emit=lambda *a: None)
    q = svc.get(aid, 1.0, 1.01, 2000)  # 480 个样本 < 2000 点 → 每点一个样本
    assert q["state"] == "ready" and q["count"] == 480
    assert q["step"] == pytest.approx(1 / SR) and q["start"] == pytest.approx(1.0)
    mx = np.frombuffer(q["max"], dtype="<f4")
    # 方波：每 24 个样本翻转一次，幅度 0.5
    assert mx[:24] == pytest.approx(0.5, abs=1e-3) and mx[24:48] == pytest.approx(-0.5, abs=1e-3)
    q2 = svc.get(aid, 0.0, 3.0, 300)  # 大于缓存分辨率需求的才走细节窗；这里仍用缓存
    assert q2["count"] <= 300
    svc.shutdown()
