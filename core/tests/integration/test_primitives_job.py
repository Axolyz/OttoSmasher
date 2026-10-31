"""原始能力端到端（真实 Core 进程 + 任务进程 + 模型；模型不在就跳过）：对齐、读音分析、测音高——输入可以是音轨或任意文件，不写资料库。"""

from __future__ import annotations

import json
import subprocess

import numpy as np
import pytest

from test_core_process import CoreProc
from test_speech_job import MODELS, wait

pytestmark = pytest.mark.skipif(not (MODELS / "pydomino" / "phoneme_transition_model.onnx").exists(), reason="dev models missing")


def ok(r):
    assert r["ok"], r
    return r["r"]


def test_align_analyze_and_f0_without_storing(tmp_path):
    root = tmp_path / "ws"
    root.mkdir()
    (root / "Models").symlink_to(MODELS)
    wav = tmp_path / "v.wav"
    subprocess.run(["ffmpeg", "-v", "error", "-f", "lavfi", "-i", "sine=frequency=220:duration=4", "-ar", "44100", "-ac", "1", str(wav)], check=True)
    c = CoreProc(root)
    try:
        add = ok(c.call("sources.add", paths=[str(wav)]))[0]
        aid = add["assets"][0]["assetId"]

        # 对齐：同一句话，一次给文件、一次给音轨；第三条只有符号 → 这一条失败，整批照样跑完
        job = ok(c.call("speech.align", items=[
            {"text": "あーあ", "path": str(wav), "start": 1.0, "end": 2.0},
            {"text": "あーあ", "assetId": aid, "start": 1.0, "end": 2.0},
            {"text": "♪♪", "path": str(wav), "start": 1.0, "end": 2.0},
        ]))
        assert wait(c, job["id"])["status"] == "succeeded"
        rows = ok(c.call("speech.alignResults", jobId=job["id"]))
        assert [r["status"] for r in rows] == ["ok", "ok", "failed"]
        assert rows[2]["error"]["code"] == "frontend-failed"
        f, a = rows[0]["result"], rows[1]["result"]
        assert (f["clock"], a["clock"]) == ("file", "asset")
        assert f["window"] == pytest.approx([1.0, 2.0], abs=1e-4)
        assert [m["text"] for m in f["morae"]] == ["ア", "ー", "ア"] and f["words"]
        assert 1.0 <= f["speech"]["start"] < f["speech"]["end"] <= 2.0
        assert f["edges"]["lead"] >= 0 and f["edges"]["tail"] >= 0 and f["longestPhone"]["seconds"] > 0
        assert "sourceStart" not in f["phones"][0]
        assert a["phones"][0]["sourceStart"] == pytest.approx(a["phones"][0]["start"])  # 原混音：资产秒 = 原片秒
        assert [p["label"] for p in a["phones"]] == [p["label"] for p in f["phones"]]

        # 多行：每行当一句对齐，另给每行的起止（第二行在第一行之后）
        job = ok(c.call("speech.align", items=[{"lines": ["あーあ", "いい"], "path": str(wav), "start": 0.5, "end": 3.0},
                                               {"lines": ["うっ", "イエ～イ！"], "path": str(wav), "start": 0.5, "end": 3.0}]))  # 有的音素没有音拍序号
        assert wait(c, job["id"])["status"] == "succeeded"
        r, r2 = ok(c.call("speech.alignResults", jobId=job["id"]))
        assert r2["status"] == "ok" and [x["text"] for x in r2["result"]["lines"]] == ["うっ", "イエ～イ！"]
        res = r["result"]
        assert r["status"] == "ok" and res["text"] == "あーあ\nいい" and [m["text"] for m in res["morae"]] == ["ア", "ー", "ア", "イ", "イ"]
        one, two = res["lines"]
        assert (one["text"], two["text"]) == ("あーあ", "いい")
        assert res["speech"]["start"] == one["start"] < one["end"] <= two["start"] < two["end"] == res["speech"]["end"]

        # 读音分析
        job = ok(c.call("text.analyze", texts=["今日はいい天気"]))
        assert wait(c, job["id"])["status"] == "succeeded"
        [r] = ok(c.call("text.analyzeResults", jobId=job["id"]))
        assert r["status"] == "ok" and "".join(r["result"]["morae"]).startswith("キョー") and r["result"]["words"][0]["reading"]

        # 测音高（任意文件，不进测量库）
        job = ok(c.call("f0.track", path=str(wav), start=0.5, end=3.5))
        assert wait(c, job["id"])["status"] == "succeeded"
        [r] = ok(c.call("f0.trackResults", jobId=job["id"]))
        res = r["result"]
        assert res["count"] == 300 and res["t0"] == pytest.approx(0.5) and res["summary"]["medianHz"] == pytest.approx(220, rel=0.02)
        assert res["summary"]["medianNote"].startswith("A3")
        assert len(np.frombuffer(res["f0"], "<f4")) == 300
        assert (root / "Data" / "Jobs" / job["id"] / "items" / "0.npy").is_file()  # 结果只在任务目录里，不登记进测量库
        assert not any((root / "Data" / "Measurements").rglob(f"*{job['id']}*"))
        # 结果命令和任务种类要对上
        assert c.call("speech.alignResults", jobId=job["id"])["e"]["code"] == "job-results-unavailable"
    finally:
        c.p.stdin.close()
        c.p.wait(timeout=15)


@pytest.mark.skipif(__import__("sys").platform == "win32", reason="Windows 未验收（L47）")
def test_cli_wait_prints_primitive_results(tmp_path):
    from test_cli import otto

    root = tmp_path / "ws"
    root.mkdir()
    (root / "Models").symlink_to(MODELS)
    wav = tmp_path / "v.wav"
    subprocess.run(["ffmpeg", "-v", "error", "-f", "lavfi", "-i", "sine=frequency=220:duration=2", "-ar", "44100", "-ac", "1", str(wav)], check=True)
    c = CoreProc(root)
    try:
        rc, out, _ = otto(root, "call", "text.analyze", '{"texts": ["ゲーム"]}', "--wait")
        assert rc == 0 and out["job"]["status"] == "succeeded"
        assert out["results"][0]["result"]["morae"] == ["ゲ", "ー", "ム"]
        rc, out, _ = otto(root, "call", "speech.align", json.dumps({"items": [{"text": "ゲーム", "path": str(wav), "start": 0.5, "end": 1.5}]}), "--wait")
        assert rc == 0 and out["results"][0]["status"] == "ok" and len(out["results"][0]["result"]["morae"]) == 3
    finally:
        c.p.stdin.close()
        c.p.wait(timeout=15)
