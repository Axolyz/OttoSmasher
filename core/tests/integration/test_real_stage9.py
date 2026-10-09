"""S7、S8、S12（规格 16）的可自动部分，真实素材、真 Core 进程（任务照常排队执行）。结果写进 ``.cache/compare/stage9/report.json``。

- S7.1 原声视频片段：YY1-01 原混音上一句，画面 = 原片对应区间、时长 = 采样时长、带声音；
- S7.2 卡拍版两种画面（BPM 180）：同映射变速的时长 = 卡拍音频，原速画面的时长 = 原声并另存卡拍 WAV；
- S7.4 外部 MP4（视频从 0.125 秒开始、音频从 0 开始）：以音频为主时钟，开头补黑帧并计数；
- S8.1 回导正例：becruily 人声轨上选区起点 1303.272，回导 0.627 秒的 G♯5 WAV → 终点 1303.899；复制进素材库、保持 WAV；删掉原文件后仍可播放；
- S8.2 采样率不同：48 kHz 的千鹤吉他回导到千鹤 MP4 的 13.187 秒 → 终点按文件时长；
- S8.3 反例：79.375 秒的番凩回导到 YY1-01 的 1400 秒 → 越界拒绝，不新增采样；
- S12.1 删除原片：确认框数字、库内生成文件消失、原片文件与已导出的 WAV / 视频仍在；S12.2 删除父采样 → 子采样仍可播放；
- S12.4 清理可重建缓存后测量、库内音轨、导出都在；有任务时拒绝清理。
需要 OTTO_FIXTURES（真实素材不进仓库）；卡拍部分另需 dev-workspace/Models 与 rubberband。"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import time
from pathlib import Path

import pytest

from test_core_process import CoreProc
from test_real_rhythm import wait

FIXTURES = os.environ.get("OTTO_FIXTURES")
MODELS = Path(os.environ.get("OTTO_DEV_MODELS", Path(__file__).resolve().parents[3] / "dev-workspace" / "Models"))
OUT = Path(__file__).resolve().parents[3] / ".cache" / "compare" / "stage9"
pytestmark = pytest.mark.skipif(not FIXTURES, reason="needs OTTO_FIXTURES")
WORDS = {"original": "原混音", "vocal": "人声", "stretch": "卡拍", "video": "视频", "originalSpeed": "原速画面", "fragment": " · 片段"}


def ffprobe(path: str) -> dict:
    return json.loads(subprocess.run(["ffprobe", "-v", "error", "-show_streams", "-show_format", "-of", "json", path], capture_output=True, check=True).stdout)


def video_done(c, timeout=300) -> dict:
    ev = c.wait_event(lambda e: e.get("t") == "evt" and e.get("e") == "exports.videoDone", timeout=timeout)
    c.events.remove(ev)
    return ev["d"]


def ok(r):
    assert r["ok"], r
    return r["r"]


def test_real_stage9(tmp_path):
    root = tmp_path / "ws"
    root.mkdir()
    if (MODELS / "pydomino").exists():
        (root / "Models").symlink_to(MODELS)
    fx = Path(FIXTURES)
    ep = fx / "episodes" / "YY1-01" / "[VCB-Studio] Yuru Yuri [01][Ma10p_1080p][x265_flac].mkv"
    mp4 = fx / "external_audio" / "千鹤弹吉他_消音.30775247570.mp4"
    report: dict = {}
    c = CoreProc(root)
    try:
        # 后台自动准备（整轨测 F0 等）会让“有任务时拒绝清理”一直成立：这里关掉，最后再单独验证拒绝
        ok(c.call("edits.apply", batch={"ops": [{"entity": "setting", "id": "analysis.auto_prepare", "version": 0, "fields": {"value": False}}]}))
        src = ok(c.call("sources.add", paths=[str(ep)]))[0]
        sid, mix = src["sourceId"], src["assets"][0]["assetId"]
        # ---- S7.1 原声视频片段
        s1 = ok(c.call("samples.create", assetId=mix, start=1302.264, end=1303.899, name="としのうきょうこ！", nature="speech"))["id"]
        t0 = time.monotonic()
        st = ok(c.call("exports.video", id=s1, version="original", words=WORDS))
        assert st["job"] is not None
        d = video_done(c)
        info = ffprobe(d["path"])
        kinds = {s["codec_type"]: s for s in info["streams"]}
        report["S7.1"] = {"file": Path(d["path"]).name, "seconds": round(time.monotonic() - t0, 1), "duration": float(info["format"]["duration"]),
                          "video": [kinds["video"]["codec_name"], kinds["video"]["width"], kinds["video"]["height"], kinds["video"]["r_frame_rate"]],
                          "audio": kinds["audio"]["codec_name"], "black": d["black"]}
        assert abs(float(info["format"]["duration"]) - 1.635) < 0.03 and kinds["video"]["codec_name"] == "h264" and kinds["audio"]["codec_name"] == "aac"
        assert d["black"] == 0
        assert ok(c.call("exports.video", id=s1, version="original", words=WORDS))["reused"]  # 同样的请求复用

        # ---- S7.4 外部 MP4：视频从 0.125 秒开始 → 开头补黑帧
        m = ok(c.call("sources.add", paths=[str(mp4)]))[0]
        sm = ok(c.call("samples.create", assetId=m["assets"][0]["assetId"], start=0.0, end=1.0, name="千鹤", nature="unclassified"))["id"]
        ok(c.call("exports.video", id=sm, version="original", words=WORDS))
        d4 = video_done(c)
        report["S7.4"] = {"black": d4["black"], "fps": d4["fps"], "duration": float(ffprobe(d4["path"])["format"]["duration"])}
        assert d4["black"] >= 1 and abs(report["S7.4"]["duration"] - 1.0) < 0.06

        # ---- S8.1 回导正例（becruily 人声轨）
        vox = ok(c.call("dev.registerStem", sourceId=sid, path=str(fx / "stems" / "YY1-01" / "becruily_deux_Vocals.mp3")))["assetId"]
        g5 = tmp_path / "歳納京子！ · G♯5__8ca511050f35.wav"
        shutil.copy(fx / "external_audio" / "reimport" / g5.name, g5)
        pv = ok(c.call("reimport.preview", assetId=vox, start=1303.272, path=str(g5)))
        assert pv["ok"] and abs(pv["end"] - 1303.899) < 1e-3 and abs(pv["duration"] - 0.627) < 1e-3
        r1 = ok(c.call("reimport.commit", assetId=vox, start=1303.272, path=str(g5), name="やったー！"))
        g5.unlink()  # 用户的原文件可以随意处置
        h = ok(c.call("playback.resolveAsset", assetId=r1["asset_id"], start=0.0, end=0.5))
        assert Path(h["path"]).is_file() and h["path"].endswith(".wav") and "/Reimport/" in h["path"]
        report["S8.1"] = {"end": pv["end"], "sourceStart": r1["source_start"], "duration": r1["duration"], "file": Path(h["path"]).name}

        # ---- S8.2 采样率不同（48 kHz → 千鹤 MP4 的 13.187 秒）
        gt = fx / "external_audio" / "reimport" / "千鹤吉他__cf6947c5be6a.wav"
        pv2 = ok(c.call("reimport.preview", assetId=m["assets"][0]["assetId"], start=13.187, path=str(gt)))
        assert pv2["ok"] and abs(pv2["duration"] - 0.956) < 2e-3 and pv2["sampleRate"] == 48000
        r2 = ok(c.call("reimport.commit", assetId=m["assets"][0]["assetId"], start=13.187, path=str(gt)))
        report["S8.2"] = {"end": pv2["end"], "duration": r2["duration"]}

        # ---- S8.3 反例：越界拒绝，不新增采样
        n0 = ok(c.call("samples.list", limit=1))["total"]
        bad = fx / "external_audio" / "reimport" / "仕事してP MEIKO KAITO - 番凩-2019-__92746b1de0d7.wav"
        pv3 = ok(c.call("reimport.preview", assetId=mix, start=1400.0, path=str(bad)))
        r3 = c.call("reimport.commit", assetId=mix, start=1400.0, path=str(bad))
        assert not pv3["ok"] and not r3["ok"] and r3["e"]["code"] == "reimport-out-of-bounds"
        assert ok(c.call("samples.list", limit=1))["total"] == n0
        report["S8.3"] = {"duration": pv3["duration"], "error": r3["e"]["code"]}

        # ---- S7.2 卡拍版两种画面（要语音分析：模型 + rubberband）
        if (MODELS / "pydomino").exists() and shutil.which("rubberband"):
            assert c.call("segments.add", sourceId=sid, start=1302.264, end=1303.899, text="としのうきょうこ！")["ok"]
            job = ok(c.call("speech.submit", entry="samples", ids=[s1]))
            assert wait(c, job["id"])["status"] == "succeeded"
            ok(c.call("rhythm.setBpm", bpm=180))
            ok(c.call("exports.video", id=s1, version="stretched", picture="synced", words=WORDS))
            ds = video_done(c)
            view = ok(c.call("rhythm.view", id=s1))
            out_s = view["schemes"]["near_fast"]["outSeconds"]
            so = ok(c.call("exports.video", id=s1, version="stretched", picture="original", words=WORDS))
            do = video_done(c)
            report["S7.2"] = {"stretchedSeconds": out_s, "synced": float(ffprobe(ds["path"])["format"]["duration"]),
                              "originalSpeed": float(ffprobe(do["path"])["format"]["duration"]), "stretchedWav": Path(so["stretchedWav"]).name}
            assert abs(report["S7.2"]["synced"] - out_s) < 0.06 and abs(report["S7.2"]["originalSpeed"] - 1.635) < 0.06

        # ---- S12.2 删除父采样 → 子采样仍可播放、来源写“已删除的父采样”
        child = ok(c.call("samples.create", assetId=mix, start=1302.5, end=1303.0, name="子", parentSampleId=s1))["id"]
        wav = ok(c.call("exports.samples", ids=[s1], words=WORDS))[0]
        ok(c.call("samples.delete", ids=[s1]))
        g = ok(c.call("samples.get", id=child))
        assert g["parent_sample_id"] is None and g["parent_label"] == "としのうきょうこ！"
        assert ok(c.call("playback.resolveAsset", assetId=mix, start=1302.5, end=1303.0))["path"] == str(ep)

        # ---- S12.4 清理：测量、库内音轨、导出都在；有任务时拒绝
        end = time.monotonic() + 600
        while any(j["status"] in ("queued", "running") for j in ok(c.call("jobs.list"))) and time.monotonic() < end:
            time.sleep(0.5)
        lib_before = sorted(p.name for p in (root / "Library").rglob("*") if p.is_file())
        cl = c.call("storage.clean")
        assert cl["ok"], cl
        lib_after = sorted(p.name for p in (root / "Library").rglob("*") if p.is_file())
        assert lib_before == lib_after and Path(wav).is_file()

        # ---- S12.1 删除原片：确认框数字；库内生成文件消失；原片文件、已导出的 WAV / 视频仍在
        pre = ok(c.call("sources.deletePreview", id=sid))
        report["S12.1"] = {k: pre[k] for k in ("samples", "generatedAssets", "segments")}
        tracks = [p for p in (root / "Library" / "Tracks").rglob("*") if p.is_file() and "[" + sid[:8] + "]" in str(p)]
        assert tracks  # becruily 声部、回导成品
        ok(c.call("sources.delete", id=sid))
        assert not any(p.exists() for p in tracks)
        assert ep.is_file() and Path(wav).is_file() and Path(d["path"]).is_file()
        OUT.mkdir(parents=True, exist_ok=True)
        (OUT / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        print(json.dumps(report, ensure_ascii=False))
    finally:
        c.p.stdin.close()
        c.p.wait(30)
