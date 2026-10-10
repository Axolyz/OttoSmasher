"""S3、S4.5、S5（规格 16）的可自动部分：YY1-01 hyperacev2 人声轨上的十句台词，语音分析 → 准备检索索引 → 三大搜索（真 Core 进程、真进程池）。

- S5：不限节奏两块（前导辅音 k + 元音 a，元音 a）——每处命中都核对是**相邻有序**的两块且条件逐块成立（用节奏视图的逐块属性）；
- S3：BPM 180、x-xx、到句末——必须满足节奏只有严格命中；按相似度排序有严格与近似，证据带倍速与方案；
- S4.5：音高检索（采样模式）0.40 秒的音高块；原片音轨模式（整轨测 F0）按音轨分行、命中带原片秒；忽略八度的同一查询命中不少于原查询。
结果数字写进 ``.cache/compare/search/report.json`` 供验收时看。需要 OTTO_FIXTURES 与 dev-workspace/Models；真实素材不进仓库。"""

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
OUT = Path(__file__).resolve().parents[3] / ".cache" / "compare" / "search"
pytestmark = pytest.mark.skipif(not FIXTURES or not (MODELS / "pydomino").exists() or shutil.which("rubberband") is None,
                                reason="needs OTTO_FIXTURES, dev models and rubberband")

LINES = [
    (182.278, 185.114, "予想外ってほどの展開ではないね"),
    (194.290, 197.059, "いけない！すぐ着替えてくる！"),
    (212.375, 216.145, "そういえばあかりの家に入るのも久しぶりだな"),
    (276.005, 278.341, "この前もカニさんパンツが…"),
    (284.547, 287.950, "あかりお姉さんの部屋入ったことある？"),
    (291.320, 295.091, "でもまあ姉妹でもプライベートは大切だよね"),
    (324.553, 327.089, "次はもっと濃いめなネタでひとつ"),
    (331.627, 335.164, "みんなのハートにドッキュ～ン！"),
    (1057.753, 1059.821, "よろしくおねがいします！"),
    (1302.264, 1303.899, "としのうきょうこ！"),
]


def search(c, method, **params):
    r = c.call(method, **params)
    assert r["ok"], r
    sid = r["r"]["searchId"]
    ev = c.wait_event(lambda e: e.get("t") == "evt" and e.get("e") == "search.finished" and e["d"]["searchId"] == sid, timeout=120)
    assert ev["d"]["status"] == "done", ev
    rid = ev["d"]["resultId"]
    rows = []
    off = 0
    while True:
        p = c.call("results.page", id=rid, offset=off, limit=100)["r"]
        rows += p["rows"]
        off += 100
        if off >= p["total"]:
            break
    return ev["d"]["stats"], rows, rid


def test_real_three_searches(tmp_path):
    root = tmp_path / "ws"
    root.mkdir()
    (root / "Models").symlink_to(MODELS)
    ep = Path(FIXTURES) / "episodes" / "YY1-01" / "[VCB-Studio] Yuru Yuri [01][Ma10p_1080p][x265_flac].mkv"
    c = CoreProc(root)
    report: dict = {}
    try:
        src = c.call("sources.add", paths=[str(ep)])["r"][0]["sourceId"]
        vox = c.call("dev.registerStem", sourceId=src, path=str(Path(FIXTURES) / "stems" / "YY1-01" / "hyperacev2_vocals.mp3"))["r"]["assetId"]
        ids = []
        for a, b, text in LINES:
            s = c.call("samples.create", assetId=vox, start=a - 0.1, end=b + 0.1, name=text, nature="speech")["r"]
            assert c.call("segments.add", sourceId=src, start=a, end=b, text=text)["ok"]  # 手输台词 = 在文本层加一段（所有者 2026-10-09）
            ids.append(s["id"])
        t0 = time.monotonic()
        job = c.call("speech.submit", entry="samples", ids=ids)["r"]
        assert wait(c, job["id"])["status"] == "succeeded"
        report["analysisSeconds"] = round(time.monotonic() - t0, 1)

        # ---- 准备检索索引（任务），覆盖从 0 到全部
        cov = c.call("search.coverage", mode="speech", scope={})["r"]
        assert (cov["total"], cov["ready"], cov["stale"]) == (10, 0, 10), cov
        t0 = time.monotonic()
        job = c.call("search.prepare", mode="speech", scope={})["r"]
        assert wait(c, job["id"])["status"] == "succeeded"
        report["indexSeconds"] = round(time.monotonic() - t0, 2)
        cov = c.call("search.coverage", mode="speech", scope={})["r"]
        assert cov["ready"] + cov["noAnalysis"] == 10 and cov["stale"] == 0, cov
        views = {i: c.call("rhythm.view", id=i)["r"] for i in ids}

        # ---- S5：相邻有序的音块条件（k+a、a；以及一定有命中的 a、i）
        def ok(cond, b):
            return all(b[k] == v for k, v in cond.items())

        report["s5"] = {}
        for label, conds in [("k+a,a", [{"consonants": ["k"], "vowel": "a"}, {"vowel": "a"}]), ("a,i", [{"vowel": "a"}, {"vowel": "i"}])]:
            stats, rows, _ = search(c, "search.speech", query={"blocks": conds}, scope={})
            report["s5"][label] = {"samples": stats["samples"], "hits": stats["hits"], "ms": stats["ms"]}
            for r in rows:
                blocks = views[r["sampleId"]]["blocks"]
                for h in r["hits"]:
                    b0, b1 = blocks[h["first"]], blocks[h["first"] + 1]
                    assert h["count"] == 2 and ok(conds[0], b0) and ok(conds[1], b1)
                    assert b0["pauseSegment"] == b1["pauseSegment"]  # 默认不跨停顿
            # 每一对相邻且同一停顿段、条件成立的块都在结果里（不漏），反之亦然
            want = {(i, k) for i in ids if views[i]["status"] == "ok" for k, (x, y) in enumerate(zip(views[i]["blocks"], views[i]["blocks"][1:]))
                    if ok(conds[0], x) and ok(conds[1], y) and x["pauseSegment"] == y["pauseSegment"]}
            got = {(r["sampleId"], h["first"]) for r in rows for h in r["hits"]}
            assert got == want
        assert report["s5"]["a,i"]["hits"] > 0

        # ---- S3：BPM 180、x-xx 到句末
        assert c.call("rhythm.setBpm", bpm=180)["ok"]
        xxx = [{"note": [0, 0.5]}, {"note": [1.0, 1.5]}, {"note": [1.5, 2.0]}]
        stats, strict_rows, _ = search(c, "search.speech", query={"blocks": xxx, "strategy": "strict", "edge": "tail"}, scope={})
        assert all(h["evidence"]["strict"] for r in strict_rows for h in r["hits"])
        stats2, rank_rows, rid = search(c, "search.speech", query={"blocks": xxx, "strategy": "rank", "edge": "tail"}, scope={})
        evs = [h["evidence"] for r in rank_rows for h in r["hits"]]
        assert evs and all(e["plan"] in ("near_fast", "near_slow") and e["bpm"] == 180.0 and e["speed"] > 0 for e in evs)
        # 严格命中的窗口都在排序结果里（排序的“严格”标记按中位数平移判断，严格检索按最佳平移拟合判断，可能不同）
        assert {(r["sampleId"], h["first"]) for r in strict_rows for h in r["hits"]} <= {(r["sampleId"], h["first"]) for r in rank_rows for h in r["hits"]}
        report["s3"] = {"strict": stats["hits"], "rank": stats2["hits"], "rankStrict": sum(e["strict"] for e in evs), "ms": [stats["ms"], stats2["ms"]]}
        # 命中的卡拍试听用证据方案；导出卡拍命中
        r0 = rank_rows[0]
        ren = c.call("hits.render", resultId=rid, rank=r0["rank"], index=0, version="stretched", sound="voice")["r"]
        assert ren["plan"] == r0["hits"][0]["evidence"]["plan"] and ren["bpm"] == 180.0 and ren["duration"] > 0
        ex = c.call("hits.export", resultId=rid, rank=r0["rank"], index=0, version="stretched", words={"stretch": "stretch"})
        assert ex["ok"], ex
        # 命中的卡拍视频（L36）：画面按同一映射变速 → 视频时长 = 命中卡拍试听的时长
        hv = c.call("hits.video", resultId=rid, rank=r0["rank"], index=0, version="stretched", picture="synced", words={"stretch": "stretch", "video": "video"})
        assert hv["ok"] and hv["r"]["job"], hv
        ev = c.wait_event(lambda e: e.get("t") == "evt" and e.get("e") == "exports.videoDone", timeout=300)
        probe = json.loads(subprocess.run(["ffprobe", "-v", "error", "-show_format", "-show_streams", "-of", "json", ev["d"]["path"]], capture_output=True, check=True).stdout)
        dur = float(probe["format"]["duration"])
        report["hitVideo"] = {"stretched": ren["duration"], "video": dur, "black": ev["d"]["black"], "codecs": sorted(x["codec_name"] for x in probe["streams"])}
        assert abs(dur - ren["duration"]) < 0.06 and ev["d"]["black"] == 0 and "stretch-180BPM" in ev["d"]["path"]

        # ---- S4.5：音高检索（采样模式）——「歳納京子！」附近约 MIDI 79.5（G5/G♯5 之间）
        cov = c.call("search.coverage", mode="pitch", scope={})["r"]
        assert cov["ready"] == 10, cov  # 语音分析时已测这些采样范围的 F0
        res = {}
        for label, blocks, params in [
            ("G#5", [{"seconds": 0.4, "low": "G#5"}], {}),
            ("G5..G#5", [{"seconds": 0.4, "low": "G5", "high": "G#5"}], {}),
            ("G#4 octave-free", [{"seconds": 0.4, "low": "G#4"}], {"ignoreOctave": True}),
        ]:
            st, rows, _ = search(c, "search.pitch", blocks=blocks, params=params, mode="samples", scope={})
            res[label] = {"samples": [r["sample"]["name"] for r in rows], "hits": st["hits"], "ms": st["ms"],
                          "octaves": sorted({h["octave"] for r in rows for h in r["hits"]})}
        report["s45_samples"] = res
        assert set(res["G#5"]["samples"]) <= set(res["G5..G#5"]["samples"])
        assert set(res["G#5"]["samples"]) <= set(res["G#4 octave-free"]["samples"])
        # 原片音轨模式：先整轨测 F0（一条 24 分钟的人声轨）
        cov = c.call("search.coverage", mode="pitchSources", scope={})["r"]
        assert cov["stale"] >= 1
        t0 = time.monotonic()
        job = c.call("search.prepare", mode="pitchSources", scope={"roles": ["vocal"]})["r"]
        assert wait(c, job["id"], timeout=1800)["status"] == "succeeded"
        report["trackF0Seconds"] = round(time.monotonic() - t0, 1)
        st, rows, _ = search(c, "search.pitch", blocks=[{"seconds": 0.4, "low": "G5", "high": "G#5"}], params={}, mode="sources", scope={"roles": ["vocal"]})
        assert rows and all(r["sampleId"] is None and r["assetId"] == vox for r in rows)
        hs = rows[0]["hits"]
        assert all(h["sourceStart"] is not None and h["sourceEnd"] - h["sourceStart"] == pytest.approx(0.4, abs=0.011) for h in hs)
        report["s45_sources"] = {"hits": st["hits"], "ms": st["ms"], "first": [(round(h["sourceStart"], 2), round(h["score"], 1)) for h in hs[:10]],
                                 "hasToshinou": any(1302.2 <= h["sourceStart"] <= 1304.0 for h in hs)}
    finally:
        OUT.mkdir(parents=True, exist_ok=True)
        (OUT / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        c.p.stdin.close()
        c.p.wait(timeout=30)
