"""真实素材 KF08（所有者 2026-10-09「原片上的四类对象」）：字幕里本来就重叠的行（两人同时说话）不自动处理——
导入到文本层 → 从段批量建采样（判定区间 = 段）→ 原片入口语音分析 → 数一数读到重叠段的采样有多少“不可用 + 原因（第 X 段与第 Y 段在 a–b 秒重叠）”，
另外数 ◐（读到的段有音素伸出采样范围）。这一集没有分离好的人声，用原混音（赋予人声角色、设为默认人声轨）。
结果写进 ``.cache/compare/textlayer/report.json`` 供验收时看。需要 OTTO_FIXTURES 与 dev-workspace/Models；真实素材不进仓库。"""

from __future__ import annotations

import json
import os
import time
from collections import Counter
from pathlib import Path

import pytest

from test_core_process import CoreProc
from test_real_rhythm import wait

FIXTURES = os.environ.get("OTTO_FIXTURES")
MODELS = Path(os.environ.get("OTTO_DEV_MODELS", Path(__file__).resolve().parents[3] / "dev-workspace" / "Models"))
OUT = Path(__file__).resolve().parents[3] / ".cache" / "compare" / "textlayer"
pytestmark = pytest.mark.skipif(not FIXTURES or not (MODELS / "pydomino").exists(), reason="needs OTTO_FIXTURES and dev models")


def test_real_kf08_overlapping_lines(tmp_path):
    root = tmp_path / "ws"
    root.mkdir()
    (root / "Models").symlink_to(MODELS)
    ep = Path(FIXTURES) / "episodes" / "KF08" / "[DBD-Raws][Kemono Friends][08][1080P][BDRip][HEVC-10bit][FLAC].mkv"
    c = CoreProc(root)
    report: dict = {}
    try:
        src = c.call("sources.add", paths=[str(ep)])["r"][0]["sourceId"]
        imp = c.call("subtitles.importDefault", sourceId=src)["r"]
        report["import"] = imp["created"] | {"opedErrors": imp["opedErrors"]}
        segs = c.call("textLayer.list", sourceId=src)["r"]["segments"]
        pairs = [
            (a["ordinal"], b["ordinal"], round(max(a["start"], b["start"]), 3), round(min(a["end"], b["end"]), 3))
            for i, a in enumerate(segs) for b in segs[i + 1:] if b["start"] < a["end"] - 1e-6 and a["start"] < b["end"] - 1e-6
        ]
        report["segments"] = len(segs)
        report["overlapPairs"] = len(pairs)
        report["overlapPairsAtLeast0.3s"] = sum(1 for p in pairs if p[3] - p[2] >= 0.3)

        # 原混音设为默认人声轨（同时赋予人声角色）
        tk = c.call("assets.tracks", sourceId=src)["r"]
        mix = tk["tracks"][0]
        ops = [
            {"entity": "asset", "id": mix["id"], "version": mix["version"], "fields": {"roles": ["vocal"]}},
            {"entity": "source", "id": src, "version": tk["sourceVersion"], "fields": {"default_vocal": mix["id"]}},
        ]
        assert c.call("edits.apply", batch={"ops": ops})["ok"]

        # 从段批量建采样（OP/ED 里的段跳过）
        frm = {"kind": "segments", "sourceId": src, "track": "default"}
        plan = c.call("samples.plan", **{"from": frm})["r"]
        keys = [it["key"] for it in plan["items"] if it["status"] == "pending"]
        made = c.call("samples.createPlanned", **{"from": frm, "token": plan["token"], "keys": keys})["r"]
        report["samples"] = made["created"]

        # 原片入口语音分析（默认人声轨 = 原混音）
        t0 = time.monotonic()
        job = c.call("speech.submit", entry="source", ids=[src])["r"]
        j = wait(c, job["id"], timeout=1800)
        assert j["status"] == "succeeded", j
        report["analysis"] = {"seconds": round(time.monotonic() - t0, 1), "items": j["items"]}

        states: Counter[str] = Counter()
        conflicts = []
        reads_two = 0
        for sid in made["ids"]:
            v = c.call("speech.sample", id=sid)["r"]
            reads_two += len(v["units"]) > 1
            if v["conflict"]:
                k = v["conflict"]
                conflicts.append(f"第 {k['a']} 段与第 {k['b']} 段在 {k['start']}–{k['end']} 秒重叠")
            if v["blocked"]:
                states[v["blocked"]["code"]] += 1
            else:
                states["partial" if v["head"]["partial"] else "ok"] += 1
        report["samplesReadingTwoOrMore"] = reads_two
        report["reading"] = dict(states)
        report["conflictExamples"] = conflicts[:12]
        OUT.mkdir(parents=True, exist_ok=True)
        (OUT / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        print(json.dumps(report, ensure_ascii=False, indent=2))

        # 原始字幕 424 行里 9 对重叠（QUESTIONS 答复 10），其中 5 对涉及音效行：分成段与音效提示两类以后，段之间只剩 4 对
        assert report["overlapPairs"] == 4
        assert states["rhythm-units-conflict"] == len(conflicts) <= reads_two <= 2 * report["overlapPairs"]
    finally:
        c.p.stdin.close()
        c.p.wait(timeout=30)
