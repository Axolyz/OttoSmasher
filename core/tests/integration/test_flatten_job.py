"""拉平任务端到端（真实 Core 进程 + 任务进程 + FCPE / PC-NSF-HiFiGAN；模型不在就跳过）：
冻结与核对、缓存预估、单个与批量、登记（新资产沿用映射、调谐单音、pitch: 标签、成品 F0）、复用成品音频但采样新建、只重跑失败项（规格 11、16 R17）。"""

from __future__ import annotations

import os
import time
from pathlib import Path

import numpy as np
import pytest

from ottosmasher.media import wavfile
from test_core_process import CoreProc

MODELS = Path(os.environ.get("OTTO_DEV_MODELS", Path(__file__).resolve().parents[3] / "dev-workspace" / "Models"))
pytestmark = pytest.mark.skipif(not (MODELS / "flatten" / "pc_nsf_hifigan.onnx").exists(), reason="dev models missing")
SR = 48000


def wait(c, jid, timeout=180):
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        j = next(x for x in c.call("jobs.list")["r"] if x["id"] == jid)
        if j["status"] not in ("queued", "running"):
            return j
        time.sleep(0.3)
    raise AssertionError("timeout")


def tone(path: Path) -> None:
    """3 秒立体声：0.5–2.5 秒是约 MIDI 58.3（A♯3 + 30 音分）带 ±0.4 半音颤音的谐波音，其余静音。"""
    t = np.arange(3 * SR) / SR
    f = 440 * 2 ** ((58.3 - 69) / 12) * 2 ** (0.4 * np.sin(2 * np.pi * 5 * t) / 12)
    ph = np.cumsum(2 * np.pi * f / SR)
    x = sum(0.15 / k * np.sin(k * ph) for k in range(1, 8))
    x[(t < 0.5) | (t >= 2.5)] = 0
    wavfile.save_wav24(path, np.stack([x, 0.8 * x], 1).astype(np.float32), SR)


def reliable_midi(f0: dict) -> np.ndarray:
    hz = np.frombuffer(f0["f0"], "<f4")
    conf = np.frombuffer(f0["confidence"], "<f4")
    en = np.frombuffer(f0["energy"], "<f4")
    ok = (conf >= 0.5) & (en > 1e-10) & (hz > 0)
    return 69 + 12 * np.log2(hz[ok] / 440)


def test_flatten_end_to_end(tmp_path):
    root = tmp_path / "ws"
    root.mkdir()
    (root / "Models").symlink_to(MODELS)
    wav = tmp_path / "tone.wav"
    tone(wav)
    c = CoreProc(root)
    try:
        # 避免后台测音高抢先填好输入缓存；这里验证拉平自己的测量和登记。
        assert c.call("edits.apply", batch={"ops": [{
            "entity": "setting", "id": "analysis.auto_prepare", "version": 0, "fields": {"value": False},
        }]})["ok"]
        aid = c.call("sources.add", paths=[str(wav)])["r"][0]["assets"][0]["assetId"]
        smp = c.call("samples.create", assetId=aid, start=0.2, end=2.8, name="tone", nature="speech")["r"]["id"]

        # ---- 打开：默认值按入口；没有对齐；建议名 = 采样名（外选区就是采样）
        op = c.call("flatten.open", assetId=aid, start=0.2, end=2.8, entry="detail", sampleId=smp)["r"]
        assert op["defaults"] == {"range": "first", "target": "edge", "side": "left"}
        assert op["alignment"] is None and op["name"] == "tone"
        assert op["duration"] == pytest.approx(2.6) and op["inner"] == pytest.approx([0.1, 2.5])
        assert c.call("flatten.open", assetId=aid, start=0.2, end=2.8, entry="single")["r"]["defaults"] == {"range": "whole", "target": "auto", "side": "left"}
        tok = op["token"]
        # 仅元音 / 首元音起：没有覆盖外选区的对齐 → 拒绝并说明
        e = c.call("flatten.estimate", token=tok, options={"range": "first", "target": "edge", "side": "left"})
        assert e["e"]["code"] == "flatten-needs-alignment"
        # 预估只读缓存：还没测过 F0 → 任务中确定
        assert c.call("flatten.estimate", token=tok, options={"range": "whole", "target": "auto"})["r"]["status"] == "in-job"
        # 手动：纯数字拒绝；445Hz → A4+20c（不吸附）
        assert c.call("flatten.estimate", token=tok, options={"range": "whole", "target": "manual", "manual": "440"})["e"]["args"]["reason"] == "bare-number"
        assert c.call("flatten.estimate", token=tok, options={"range": "whole", "target": "manual", "manual": "445Hz"})["r"]["target"]["name"] == "A4+20c"
        # 内部：平台不足 30 ms 拒绝
        bad = c.call("flatten.submit", token=tok, name="x", options={"range": "inner", "target": "auto", "inner": [0.4, 0.51], "transition": [0.05, 0.05]})
        assert bad["e"]["code"] == "flatten-inner-invalid"

        # ---- 单个：整段 + 段内自动
        n_samples = c.call("samples.list")["r"]["total"]
        job = c.call("flatten.submit", token=tok, name="tone", sampleId=smp, localTags=["project:dil"], options={"range": "whole", "target": "auto"})["r"]
        j = wait(c, job["id"])
        assert j["status"] == "succeeded", j
        rows = c.call("flatten.results", jobId=job["id"])["r"]
        assert len(rows) == 1 and rows[0]["status"] == "ok" and rows[0]["target"] == "A♯3"
        pid = rows[0]["productId"]
        assert c.call("samples.list")["r"]["total"] == n_samples + 1  # 只登记一个采样
        p = c.call("samples.get", id=pid)["r"]
        assert [t["tag"] for t in p["tags"] if t["provenance"] == "local"] == ["project:dil"]
        assert p["nature"] == "pitched" and p["name"] == "tone"  # 名称不加音名
        assert "pitch:A♯3" in [t["tag"] for t in p["tags"] if t["provenance"] == "auto"]
        a = c.call("assets.get", id=p["asset_id"])["r"]
        assert a["origin"] == "flatten" and a["input_asset_id"] == aid
        assert a["mapping"][0] == pytest.approx([0, 0.2]) and a["mapping"][-1][1] == pytest.approx(2.8)
        prod = a["production"]
        assert prod["target"]["midi"] == 58 and prod["target"]["originalMidi"] == pytest.approx(58.3, abs=0.1)
        assert prod["inputFrames"] == round(2.6 * SR)  # 送进处理的恰好是外选区的样本数
        assert prod["range"] == "whole" and prod["intervals"] == [[0.0, pytest.approx(2.6)]]
        assert a["duration"] == pytest.approx(2.6, abs=1 / SR)
        # 成品重新测了 F0（波形 F0 线、音高检索用）：颤音被压平到目标附近
        f0 = c.call("measure.f0", assetId=a["id"], start=0.4, end=2.2)["r"]
        assert f0["measured"] == f0["count"]
        m = reliable_midi(f0)
        assert len(m) > 100 and abs(np.median(m) - 58) < 0.1 and np.percentile(m, 90) - np.percentile(m, 10) < 0.15
        # 当前采样、列表不变：任务只提示资料已更新（这里只核对没有改原采样）
        assert c.call("samples.get", id=smp)["r"]["asset_id"] == aid
        # 预估：现在仍没有输入资产的 F0（成品的 F0 不算输入的）
        assert c.call("flatten.estimate", token=tok, options={"range": "whole", "target": "auto"})["r"]["status"] == "in-job"

        # ---- 复用：相同输入 + 参数 + 模型 → 成品音频复用，采样新建
        job2 = c.call("flatten.submit", token=tok, name="tone again", localTags=["project:other"], options={"range": "whole", "target": "auto"})["r"]
        assert wait(c, job2["id"])["status"] == "succeeded"
        p2 = c.call("samples.get", id=c.call("flatten.results", jobId=job2["id"])["r"][0]["productId"])["r"]
        assert p2["id"] != pid and p2["asset_id"] == p["asset_id"]
        assert [t["tag"] for t in p2["tags"] if t["provenance"] == "local"] == ["project:other"]

        # ---- 批量：仅元音（没有对齐）→ 逐项失败并说明；整段 → 成功
        smp2 = c.call("samples.create", assetId=aid, start=0.6, end=1.4, name="t2", nature="speech")["r"]["id"]
        jb = c.call("flatten.submitBatch", ids=[smp, smp2], options={"range": "vowels", "target": "auto"})["r"]
        jbr = wait(c, jb["id"])
        # 一条都没做成 = 任务失败（L51），逐条原因照样在结果里
        assert jbr["status"] == "failed" and jbr["error"]["code"] == "job-all-items-failed" and jbr["items"] == {"total": 2, "ok": 0, "failed": 2}
        assert {r["error"]["code"] for r in c.call("flatten.results", jobId=jb["id"])["r"]} == {"flatten-needs-alignment"}
        # 批量不接受手动 / 内部（Q10）
        assert c.call("flatten.submitBatch", ids=[smp], options={"range": "whole", "target": "manual", "manual": "A4"})["e"]["code"] == "flatten-invalid"
        assert c.call("flatten.submitBatch", ids=[smp], options={"range": "inner", "target": "auto"})["e"]["code"] == "flatten-invalid"
        jw = c.call("flatten.submitBatch", ids=[smp2], localTags=["project:batch"], options={"range": "whole", "target": "edge", "side": "right"})["r"]
        assert wait(c, jw["id"])["status"] == "succeeded"
        rw = c.call("flatten.results", jobId=jw["id"])["r"][0]
        assert rw["status"] == "ok" and rw["target"] == "A♯3"
        assert c.call("samples.ids", projectTag="project:batch")["r"] == [rw["productId"]]
        # 只重跑失败项：同一组选项，仍然失败（没有对齐）
        rr = c.call("flatten.rerunFailed", jobId=jb["id"])["r"]
        assert wait(c, rr["id"])["items"]["failed"] == 2

        # ---- 单个失败 = 任务失败，不留任何登记：交界左侧在静音里（外选区 0.0–0.45 全是静音）
        n_before = c.call("samples.list")["r"]["total"]
        t2 = c.call("flatten.open", assetId=aid, start=0.0, end=0.45, entry="single")["r"]["token"]
        jf = c.call("flatten.submit", token=t2, name="silence", options={"range": "whole", "target": "edge", "side": "left"})["r"]
        jfr = wait(c, jf["id"])
        assert jfr["status"] == "failed" and jfr["error"]["code"] == "flatten-edge-insufficient"
        assert c.call("samples.list")["r"]["total"] == n_before

        # ---- 冻结核对：文件被改动 → “声音资产已改变”
        os.utime(wav, (time.time() + 5, time.time() + 5))
        e = c.call("flatten.submit", token=tok, name="x", options={"range": "whole", "target": "auto"})
        assert e["e"]["code"] == "flatten-asset-changed"
        # 任务目录：成功后清理中间文件
        assert not (root / "Data" / "Jobs" / job["id"] / "cache").exists()
        assert list((root / "Library" / "Tracks").rglob("Flatten/*.mp3"))
    finally:
        c.p.stdin.close()
        c.p.wait(timeout=15)
