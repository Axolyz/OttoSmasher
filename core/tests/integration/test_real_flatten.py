"""S4（规格 16）：YY1-01 becruily 人声轨上的三个拉平参考（「歳納京子！」G♯5、E5、D4），都用“仅元音 + 段内自动”。
流程：整句采样做语音分析 → 参考区间截取的子采样借用覆盖它的测量 → 拉平。只核对 S4 写明的数值（原始 MIDI 79.5 ± 0.15，G5 或 G♯5 都可以），
其余如实记下来（不调参凑旧值：旧版对齐来自别的模型）；成品复制到 .cache/compare/s4/ 供所有者与参考成品对比听感（含版权声音，只在本地）。
需要 OTTO_FIXTURES 与 dev-workspace/Models；真实素材不进仓库。"""

from __future__ import annotations

import json
import os
import shutil
import time
from pathlib import Path

import pytest

from test_core_process import CoreProc

FIXTURES = os.environ.get("OTTO_FIXTURES")
MODELS = Path(os.environ.get("OTTO_DEV_MODELS", Path(__file__).resolve().parents[3] / "dev-workspace" / "Models"))
OUT = Path(__file__).resolve().parents[3] / ".cache" / "compare" / "s4"
pytestmark = pytest.mark.skipif(not FIXTURES or not (MODELS / "flatten").exists(), reason="needs OTTO_FIXTURES and dev models")

# (参考名, 整句台词区间与对齐文本, 参考成品的外选区)
CASES = [
    ("Gs5", (1302.264, 1303.899, "としのうきょうこ！"), (1303.272, 1303.899)),
    ("E5", (1057.753, 1059.821, "よろしくおねがいします！"), (1058.804, 1059.303)),
    ("D4", (212.375, 216.145, "そういえば あかりのいえにはいるのもひさしぶりだな"), (212.425, 212.845)),
]


def wait(c, jid, timeout=600):
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        j = next(x for x in c.call("jobs.list")["r"] if x["id"] == jid)
        if j["status"] not in ("queued", "running"):
            return j
        time.sleep(0.5)
    raise AssertionError("timeout")


def test_s4_flatten_references(tmp_path):
    root = tmp_path / "ws"
    root.mkdir()
    (root / "Models").symlink_to(MODELS)
    ep = Path(FIXTURES) / "episodes" / "YY1-01" / "[VCB-Studio] Yuru Yuri [01][Ma10p_1080p][x265_flac].mkv"
    c = CoreProc(root)
    try:
        sid = c.call("sources.add", paths=[str(ep)])["r"][0]["sourceId"]
        vox = c.call("dev.registerStem", sourceId=sid, path=str(Path(FIXTURES) / "stems" / "YY1-01" / "becruily_deux_Vocals.mp3"))["r"]["assetId"]
        lines, subs = [], []
        for _, (a, b, text), (fa, fb) in CASES:
            s = c.call("samples.create", assetId=vox, start=a, end=b, name=text, nature="speech")["r"]
            r = c.call("segments.add", sourceId=sid, start=a, end=b, text=text)  # 手输台词 = 在文本层加一段（所有者 2026-10-09）
            assert r["ok"], r
            lines.append(s["id"])
            subs.append(c.call("samples.create", assetId=vox, start=fa, end=fb, name=text, nature="speech", parentSampleId=s["id"])["r"]["id"])
        job = c.call("speech.submit", entry="samples", ids=lines)["r"]
        assert wait(c, job["id"])["status"] == "succeeded"
        assert {r["status"] for r in c.call("speech.results", jobId=job["id"])["r"]} == {"ok"}

        OUT.mkdir(parents=True, exist_ok=True)
        report = {}
        for (name, _, (fa, fb)), sub in zip(CASES, subs, strict=True):
            op = c.call("flatten.open", assetId=vox, start=fa, end=fb, entry="single", sampleId=sub)["r"]
            assert op["alignment"] is not None  # 子采样借用覆盖它的整句测量（同一物理声音）
            fj = c.call("flatten.submit", token=op["token"], name=op["name"], sampleId=sub, options={"range": "vowels", "target": "auto"})["r"]
            j = wait(c, fj["id"])
            assert j["status"] == "succeeded", j
            pid = c.call("flatten.results", jobId=fj["id"])["r"][0]["productId"]
            p = c.call("samples.get", id=pid)["r"]
            a = c.call("assets.get", id=p["asset_id"])["r"]
            prod = a["production"]
            report[name] = {
                "target": prod["target"]["name"], "originalMidi": round(prod["target"]["originalMidi"], 4),
                "intervals": prod["intervals"], "tags": [t["tag"] for t in p["tags"] if t["tag"].startswith("pitch:")], "nature": p["nature"],
            }
            src = next((root / "Library").rglob(f"{a['id']}.mp3"))
            shutil.copy(src, OUT / f"new_{name}_{prod['target']['name'].replace(chr(0x266F), 's')}.mp3")
            assert p["nature"] == "pitched" and p["name"] == op["name"]
            assert report[name]["tags"] == [f"pitch:{prod['target']['name']}"]
        (OUT / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=1), encoding="utf-8")
        for ref in ("flatten_Gs5.mp3", "flatten_E5.mp3", "flatten_D4.mp3"):
            shutil.copy(Path(FIXTURES) / "reference" / "YY1-01_flatten" / ref, OUT / f"old_{ref}")
        # S4 写明的唯一数值：「歳納京子！」原始音高约 MIDI 79.5 ± 0.15，G5 或 G♯5 都可接受
        g = report["Gs5"]
        assert abs(g["originalMidi"] - 79.5) <= 0.15, report
        assert g["target"] in ("G5", "G♯5"), report
    finally:
        c.p.stdin.close()
        c.p.wait(timeout=30)
