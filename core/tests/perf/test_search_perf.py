"""三大搜索的性能（规格 15 §15.2、09 §9.6.5、16 R14.15、R15.8；ARCHITECTURE §9.5）。

只在设置了 ``OTTO_PERF_WS``（``tools/synth_library.py`` 生成的合成工作区）时运行；真进程池、端到端（含写固定结果）。
每个查询跑 ``OTTO_PERF_RUNS`` 次（默认 3）：第一次是冷的（进程启动、方案缓存为空），之后是热的。报告写到 ``.cache/perf/report.json``。
"""

from __future__ import annotations

import json
import os
import platform
import threading
import time
from pathlib import Path

import pytest

WS = os.environ.get("OTTO_PERF_WS")
pytestmark = pytest.mark.skipif(not WS, reason="set OTTO_PERF_WS to a workspace made by tools/synth_library.py")
RUNS = int(os.environ.get("OTTO_PERF_RUNS", "3"))
LIMIT = 30.0

XXX = [{"note": [0, 0.5]}, {"note": [1.0, 1.5]}, {"note": [1.5, 2.0]}]
SPEECH = {
    "S3 必须满足节奏 x-xx 到句末 @180": ({"blocks": XXX, "strategy": "strict", "edge": "tail"}, 180.0),
    "S3 按相似度 x-xx 到句末 @180": ({"blocks": XXX, "strategy": "rank", "edge": "tail"}, 180.0),
    "S3 按相似度 x-xx 无 BPM": ({"blocks": XXX, "strategy": "rank", "edge": "tail"}, None),
    "C-E-G（音级）": ({"blocks": [{"pitch": 0}, {"pitch": 4}, {"pitch": 7}]}, None),
    "S5 人力 k+a、a": ({"blocks": [{"consonants": ["k"], "vowel": "a"}, {"vowel": "a"}]}, None),
    "几块带音高/元音条件": ({"blocks": [{"vowel": "a", "pitch": 9, "octave": 4, "pitchTolerance": 150}, {"vowel": "i"}, {"vowel": "o", "spreadMax": 100}]}, None),
    "不限节奏 1 块无条件（最坏）": ({"blocks": [{}]}, None),
}
PITCH = {
    "音高 A4 0.4 + C5 0.3": ([{"seconds": 0.4, "low": "A4"}, {"seconds": 0.3, "low": "C5"}], {}),
    "音高 一行 A4 0.2": ([{"seconds": 0.2, "low": "A4"}], {}),
    "音高 C-E 忽略八度": ([{"seconds": 0.15, "low": "C4"}, {"seconds": 0.15, "low": "E4"}], {"ignoreOctave": True}),
    "音高 C-E-G 忽略八度（附加）": ([{"seconds": 0.15, "low": "C4"}, {"seconds": 0.15, "low": "E4"}, {"seconds": 0.15, "low": "G4"}], {"ignoreOctave": True}),
    "音高 两块 时长弹性 0.8–1.25": ([{"seconds": 0.2, "low": "A4"}, {"seconds": 0.15, "low": "C5"}], {"elastic": [0.8, 1.25]}),
    "音高 滑音块 C4→E4": ([{"seconds": 0.2, "low": "C4", "glide": {"low": "E4"}}], {"tolerance": 100}),
}


@pytest.fixture(scope="module")
def core():
    from ottosmasher.core.server import Core

    c = Core(Path(WS))
    c.open()
    done = threading.Event()
    box: dict = {}

    def emit(name, data):
        if name == "search.finished":
            box["r"] = data
            done.set()

    c.search.emit = emit
    c.search.post = lambda fn: fn()
    c._perf = (done, box)
    yield c
    c.close()


def _run(c, start):
    done, box = c._perf
    done.clear()
    t0 = time.perf_counter()
    start()
    assert done.wait(300)
    wall = time.perf_counter() - t0
    r = box["r"]
    assert r["status"] == "done", r
    return wall, r["stats"]


def test_search_perf(core):
    report = {"machine": {"platform": platform.platform(), "cpu": os.cpu_count(), "python": platform.python_version()}, "queries": []}
    total = core.conn.execute("SELECT COUNT(*) FROM sample").fetchone()[0]
    report["samples"] = total
    for label, (q, bpm) in SPEECH.items():
        core.rhythm.set_bpm(bpm)
        times, stats = [], None
        for _ in range(RUNS):
            wall, stats = _run(core, lambda: core.search.run_speech(q, {}))
            times.append(wall)
        report["queries"].append({"query": label, "cold": times[0], "warm": sorted(times[1:])[len(times[1:]) // 2] if len(times) > 1 else None,
                                  "hits": stats["hits"], "samples": stats["samples"], "searched": stats["searched"]})
    for label, (blocks, prm) in PITCH.items():
        times, stats = [], None
        for _ in range(RUNS):
            wall, stats = _run(core, lambda: core.search.run_pitch(blocks, prm, "samples", {}))
            times.append(wall)
        report["queries"].append({"query": label, "cold": times[0], "warm": sorted(times[1:])[len(times[1:]) // 2] if len(times) > 1 else None,
                                  "hits": stats["hits"], "samples": stats["samples"], "searched": stats["searched"]})
    out = Path(__file__).resolve().parents[3] / ".cache" / "perf" / "report.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    for q in report["queries"]:
        print(f"{q['query']:<36} cold {q['cold']:6.2f}s  warm {q['warm'] or 0:6.2f}s  hits {q['hits']:>7}  rows {q['samples']:>6}")
    slow = [q for q in report["queries"] if q["cold"] > LIMIT and "附加" not in q["query"]]
    assert not slow, slow


def test_list_state_perf(core):
    """列表一页 100 条带分析状态（`units.state_sql`：判定区间读到的段 + 段长 120 秒的下界）与各原片的已分析计数：
    3 万条时要在 0.1 秒级（QUESTIONS「原片上的四类对象」段长度一条）。报告写到 ``.cache/perf/list.json``。"""
    out: dict = {}
    for label, fn in {
        "列表第一页": lambda: core.samples.list(offset=0, limit=100),
        "列表中间一页": lambda: core.samples.list(offset=15000, limit=100),
        "只看语音性质": lambda: core.samples.list(offset=0, limit=100, natures=["speech"]),
        "各原片已分析计数": lambda: core.speech.analyzed_counts(),
    }.items():
        times = []
        for _ in range(RUNS):
            t0 = time.perf_counter()
            fn()
            times.append(round(time.perf_counter() - t0, 3))
        out[label] = times
    p = Path(__file__).resolve().parents[3] / ".cache" / "perf" / "list.json"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(out, ensure_ascii=False))
    assert all(min(t) < 1.0 for t in out.values()), out
