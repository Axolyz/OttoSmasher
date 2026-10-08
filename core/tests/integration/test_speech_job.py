"""语音分析任务端到端（真实 Core 进程 + 任务进程 + 模型；模型不在就跳过）：逐条结果、采纳、再发起时跳过（S1.7 的流程部分）。"""

from __future__ import annotations

import os
import subprocess
import time
from pathlib import Path

import pytest

from test_core_process import CoreProc

MODELS = Path(os.environ.get("OTTO_DEV_MODELS", Path(__file__).resolve().parents[3] / "dev-workspace" / "Models"))
pytestmark = pytest.mark.skipif(not (MODELS / "pydomino" / "phoneme_transition_model.onnx").exists(), reason="dev models missing")


def wait(c, jid, timeout=120):
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        j = next(x for x in c.call("jobs.list")["r"] if x["id"] == jid)
        if j["status"] not in ("queued", "running"):
            return j
        time.sleep(0.3)
    raise AssertionError("timeout")


def test_speech_job_end_to_end(tmp_path):
    root = tmp_path / "ws"
    root.mkdir()
    (root / "Models").symlink_to(MODELS)
    wav = tmp_path / "v.wav"
    subprocess.run(["ffmpeg", "-v", "error", "-f", "lavfi", "-i", "sine=frequency=220:duration=6", "-ar", "44100", "-ac", "2", str(wav)], check=True)
    c = CoreProc(root)
    try:
        add = c.call("sources.add", paths=[str(wav)])["r"][0]
        aid = add["assets"][0]["assetId"]
        smp = [c.call("samples.create", assetId=aid, start=s, end=e, name=n, nature="speech")["r"]["id"] for s, e, n in ((1.0, 2.0, "x"), (3.0, 4.0, "y"))]
        # 手输文本（人工对齐文本）
        for sid, text in zip(smp, ("あーあ", "♪♪"), strict=True):
            v = c.call("samples.get", id=sid)["r"]["version"]
            r = c.call("edits.apply", batch={"ops": [{"entity": "sample", "id": sid, "version": v, "fields": {"align_text_manual": text}}]})
            assert r["ok"], r
        pv = c.call("speech.preview", entry="samples", ids=smp)["r"]
        assert (pv["run"], pv["fresh"], pv["blocked"]) == (2, 0, 0)
        job = c.call("speech.submit", entry="samples", ids=smp)["r"]
        j = wait(c, job["id"])
        assert j["status"] == "succeeded", j
        assert j["items"] == {"total": 2, "ok": 1, "failed": 1}
        rows = {r["name"]: r for r in c.call("speech.results", jobId=job["id"])["r"]}
        assert rows["x"]["status"] == "ok"
        assert rows["y"]["status"] == "failed"  # 只有符号：文本前端失败，写明原因
        assert rows["y"]["error"]["code"] == "frontend-failed"
        # 再发起：成功的那条跳过，失败的那条重跑
        pv = c.call("speech.preview", entry="samples", ids=smp)["r"]
        assert (pv["run"], pv["fresh"]) == (1, 1)
        # 实测记录随任务交回
        probes = {p["model"]: p["status"] for p in c.call("models.status")["r"]["probes"]}
        assert probes.get("pydomino") == "passed"
        # F0 随分析测量（该声音没测过才测）：样本区间的帧都已测，220 Hz 正弦测出约 220 Hz
        import numpy as np

        f0 = c.call("measure.f0", assetId=aid, start=1.0, end=2.0)["r"]
        assert f0["count"] == 100 and f0["measured"] == 100
        hz = np.frombuffer(f0["f0"], "<f4")
        conf = np.frombuffer(f0["confidence"], "<f4")
        assert np.median(hz[conf >= 0.5]) == pytest.approx(220, rel=0.02)
        chunks = list((root / "Data" / "Measurements" / "f0" / aid).rglob("*.npy"))
        assert len(chunks) == 1
        # 没测过的段：帧为 NaN（6 秒的文件只有第 0 段，已测；这里只核对读取不越界、不产生副作用）
        assert c.call("measure.f0", assetId=aid, start=5.0, end=6.0)["r"]["measured"] == 100
        # 任务目录：成功后清理中间文件
        assert not (root / "Data" / "Jobs" / job["id"] / "cache").exists()
    finally:
        c.p.stdin.close()
        c.p.wait(timeout=15)
