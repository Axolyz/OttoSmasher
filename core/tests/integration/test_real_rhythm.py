"""S3.5–S3.6（规格 16）的可自动部分：YY1-01 hyperacev2 人声轨上的三句台词，语音分析 → 节奏 → 180 BPM 卡拍。
核对：近快速度 ≥ 1、近慢 < 1；卡拍 WAV 里每个起音样本与原声 WAV 的对应样本逐样本相等（核心逐样本复制、起音落拍）；
不设 BPM 时实测原速 = 1（±1e-3）；REAPER 交接文本格式与每个起音都有标记。卡拍与咔哒声文件复制到 .cache/compare/s3/ 供所有者听（含版权声音，只在本地）。
REAPER 里的实际粘贴是人工验收。需要 OTTO_FIXTURES 与 dev-workspace/Models；真实素材不进仓库。"""

from __future__ import annotations

import json
import os
import shutil
import time
from pathlib import Path

import numpy as np
import pytest
from scipy.io import wavfile as sw

from test_core_process import CoreProc

FIXTURES = os.environ.get("OTTO_FIXTURES")
MODELS = Path(os.environ.get("OTTO_DEV_MODELS", Path(__file__).resolve().parents[3] / "dev-workspace" / "Models"))
OUT = Path(__file__).resolve().parents[3] / ".cache" / "compare" / "s3"
pytestmark = pytest.mark.skipif(
    not FIXTURES or not (MODELS / "pydomino").exists() or shutil.which("rubberband") is None, reason="needs OTTO_FIXTURES, dev models and rubberband"
)

LINES = [
    ("toshinou", 1302.264, 1303.899, "としのうきょうこ！"),
    ("yoroshiku", 1057.753, 1059.821, "よろしくおねがいします！"),
    ("souieba", 212.375, 216.145, "そういえば あかりのいえにはいるのもひさしぶりだな"),
]
WORDS = {"original": "mix", "vocal": "vocal", "stretch": "stretch"}


def wait(c, jid, timeout=600):
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        j = next(x for x in c.call("jobs.list")["r"] if x["id"] == jid)
        if j["status"] not in ("queued", "running"):
            return j
        time.sleep(0.5)
    raise AssertionError("timeout")


def read(path: str) -> tuple[np.ndarray, int]:
    rate, y = sw.read(path)
    return (y if y.ndim == 2 else y[:, None]), rate


def test_s3_stretch_on_real_lines(tmp_path):
    root = tmp_path / "ws"
    root.mkdir()
    (root / "Models").symlink_to(MODELS)
    ep = Path(FIXTURES) / "episodes" / "YY1-01" / "[VCB-Studio] Yuru Yuri [01][Ma10p_1080p][x265_flac].mkv"
    c = CoreProc(root)
    try:
        sid = c.call("sources.add", paths=[str(ep)])["r"][0]["sourceId"]
        vox = c.call("dev.registerStem", sourceId=sid, path=str(Path(FIXTURES) / "stems" / "YY1-01" / "hyperacev2_vocals.mp3"))["r"]["assetId"]
        ids = []
        for name, a, b, text in LINES:
            s = c.call("samples.create", assetId=vox, start=a, end=b, name=name, nature="speech")["r"]
            assert c.call("edits.apply", batch={"ops": [{"entity": "sample", "id": s["id"], "version": s["version"], "fields": {"align_text_manual": text}}]})["ok"]
            ids.append(s["id"])
        job = c.call("speech.submit", entry="samples", ids=ids)["r"]
        assert wait(c, job["id"])["status"] == "succeeded"

        OUT.mkdir(parents=True, exist_ok=True)
        report = {}
        # 原速卡拍（不设 BPM）：实测语音播放速度 = 1
        for i in ids:
            v = c.call("rhythm.view", id=i)["r"]
            assert v["status"] == "ok", v
            assert abs(v["schemes"]["near_fast"]["speed"] - 1) <= 1e-3, v["schemes"]["near_fast"]
        assert c.call("rhythm.setBpm", bpm=180)["r"] == {"bpm": 180.0}
        for (name, a, b, _), i in zip(LINES, ids, strict=True):
            v = c.call("rhythm.view", id=i)["r"]
            nf, ns = v["schemes"]["near_fast"], v["schemes"]["near_slow"]
            assert nf["speed"] >= 1 - 1e-5 and ns["speed"] < 1
            orig, sr = read(c.call("exports.samples", ids=[i], words=WORDS)["r"][0])
            ex = c.call("exports.stretched", id=i, words=WORDS)["r"]
            st, sr2 = read(ex["path"])
            assert sr2 == sr and "stretch-180BPM" in Path(ex["path"]).name
            assert abs(len(st) / sr - nf["outSeconds"]) < 1e-3
            onsets = [p for p in nf["points"] if p["kind"] == "onset"]
            for p in onsets:  # 起音样本逐样本相等（核心逐样本复制、起音落在目标拍 ±1 样本）
                if p["src"] - a < 0.001 or b - p["src"] < 0.001:
                    continue  # 起音贴着采样边界：左（右）侧间距为 0，保护核心半径为 0（09 §9.5.2），没有逐样本复制的样本
                ti, si = round(p["tgt"] * sr), round((p["src"] - a) * sr)
                assert np.array_equal(st[ti], orig[si]), (name, p)
            h = c.call("reaper.handoff", ids=[i], words=WORDS)["r"]
            lines = h["clipboard"].rstrip("\0").split("\0")
            sm = next(ln for ln in lines if ln.startswith("SM ")).split(" + ")
            assert h["clipboard"].startswith("<ITEM\0") and len(sm) >= len(onsets)
            report[name] = {
                "blocks": len(v["blocks"]), "cells": v["cells"], "pauses": v["pauses"], "segments": v["segments"], "tickMs": round(v["tick"] * 1000, 1),
                "nearFast": {"density": nf["density"], "speed": round(nf["speed"], 3)}, "nearSlow": {"density": ns["density"], "speed": round(ns["speed"], 3)},
                "markers": len(sm),
            }
            shutil.copy(ex["path"], OUT / f"{name}_180bpm_near_fast.wav")
            r = c.call("rhythm.render", id=i, version="stretched", sound="voice+click")["r"]
            shutil.copy(root / "Data" / "Cache" / "rhythm" / f"{r['key']}.wav", OUT / f"{name}_180bpm_near_fast_click.wav")
            shutil.copy(c.call("exports.samples", ids=[i], words=WORDS)["r"][0], OUT / f"{name}_original.wav")
        (OUT / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=1), encoding="utf-8")
    finally:
        c.p.stdin.close()
        c.p.wait(timeout=30)
