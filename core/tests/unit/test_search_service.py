"""检索协调与固定结果（规格 09 §9.6.5、10 §10.2、04 §4.2.10，16 R14.10、R14.13、R15.3、R15.7；ARCHITECTURE §2.2）。"""

from __future__ import annotations

import math
import threading
import time
from pathlib import Path

import numpy as np
import pytest
from test_rhythm_service import align, core, sample  # noqa: F401 — 复用夹具
from test_search_index import run_index_job

from ottosmasher.core import search_worker as sw
from ottosmasher.core.errors import CoreError
from ottosmasher.models import f0store


def inline(c):
    c.search.inline = True
    return c


def run(c, fn, *a):
    sid = fn(*a)["searchId"]
    st = c.search.status(sid)
    assert st["status"] == "done", st
    return st, c.search.page(st["resultId"], 0, 100)


def test_speech_search_end_to_end(core, tmp_path):
    inline(core)
    a = sample(core, name="a")
    b = sample(core, name="b")
    align(core, a)
    align(core, b)
    run_index_job(core, [a], tmp_path)  # b 有分析但索引未就绪
    sample(core, start=6.0, end=9.0, name="c")  # 没有分析
    st, page = run(core, core.search.run_speech, {"blocks": [{"vowel": "a"}] * 3}, {})
    s = st["stats"]
    assert (s["total"], s["searched"], s["noAnalysis"], s["stale"]) == (3, 1, 1, 1)
    assert s["samples"] == 1 and s["hits"] == 3  # 停顿段 0：4 块 → 2 个窗口；停顿段 1：3 块 → 1 个
    row = page["rows"][0]
    assert row["sampleId"] == a and row["state"] == "ok" and row["sample"]["name"] == "a"
    assert [h["first"] for h in row["hits"]] == [0, 1, 4]
    # 节奏策略 + BPM：证据随命中保存
    core.rhythm.set_bpm(180)
    st, page = run(core, core.search.run_speech, {"blocks": [{"note": [0, 0.5]}, {"note": [1, 1.5]}], "strategy": "rank"}, {})
    ev = page["rows"][0]["hits"][0]["evidence"]
    assert ev["plan"] in ("near_fast", "near_slow") and ev["bpm"] == 180.0 and st["stats"]["bpm"] == 180.0
    # 查询不对：立即报错，不启动检索
    with pytest.raises(CoreError) as e:
        core.search.run_speech({"blocks": []}, {})
    assert e.value.code == "speech-query-invalid"


def test_search_does_not_decode_or_infer(core, tmp_path, monkeypatch):
    """R14.10：检索不跑模型、不读波形、不登记采样——相关函数一调用就失败。"""
    inline(core)
    a = sample(core)
    align(core, a)
    run_index_job(core, [a], tmp_path)
    _put_f0(core, a)

    def boom(*_a, **_k):
        raise AssertionError("search must not decode or infer")

    from ottosmasher.media import decode as dec
    from ottosmasher.models import domino, fcpe

    monkeypatch.setattr(dec, "decode_frames", boom)
    monkeypatch.setattr(dec, "decode_range", boom)
    monkeypatch.setattr(fcpe, "measure_chunk", boom)
    monkeypatch.setattr(domino, "Aligner", boom)
    n0 = core.conn.execute("SELECT COUNT(*) FROM sample").fetchone()[0]
    run(core, core.search.run_speech, {"blocks": [{"vowel": "a"}]}, {})
    run(core, core.search.run_pitch, [{"seconds": 0.5, "low": "A4"}], {}, "samples", {})
    assert core.conn.execute("SELECT COUNT(*) FROM sample").fetchone()[0] == n0


def test_fixed_result_paging_restore_and_invalidation(core, tmp_path):
    inline(core)
    a = sample(core, name="a")
    align(core, a)
    run_index_job(core, [a], tmp_path)
    st, _ = run(core, core.search.run_speech, {"blocks": [{"vowel": "a"}]}, {})
    rid = st["resultId"]
    # 1207 条按 100 条分页读取，合起来顺序完整（R14.13）
    hits = [{"start": 0.0, "end": 1.0, "score": float(i), "first": 0, "count": 1, "blockScore": 0.0, "evidence": None} for i in range(1)]
    big = core.search._write_set("speech", {}, {}, {}, st["stats"], [(a, None, core.search._speech_snapshots([a])[a], hits)] * 1207)
    ranks = []
    for off in range(0, 1300, 100):
        p = core.search.page(big, off, 100)
        assert len(p["rows"]) <= 100 and p["total"] == 1207
        ranks += [r["rank"] for r in p["rows"]]
    assert ranks == list(range(1207))
    # 恢复：列出打开的结果，不重新检索；界面状态保存
    core.search.set_ui(rid, {"active": True, "page": 0, "scroll": 120})
    heads = {h["id"]: h for h in core.search.results()}
    assert rid in heads and heads[rid]["uiState"]["scroll"] == 120 and heads[rid]["kind"] == "speech"
    # 成员改名 → 显示新名；重新绑定 → 音源已变化；分析换了 → 命中已失效
    v = core.samples.get(a)["version"]
    core.edits.apply({"ops": [{"entity": "sample", "id": a, "version": v, "fields": {"name": "新名"}}]})
    row = core.search.page(rid)["rows"][0]
    assert row["state"] == "ok" and row["sample"]["name"] == "新名"
    align(core, a)
    assert core.search.page(rid)["rows"][0]["state"] == "stale"
    core.conn.execute('UPDATE sample SET start = 2.1 WHERE id = ?', (a,))
    assert core.search.page(rid)["rows"][0]["state"] == "changed"
    # 关闭结果只删结果集合，不删采样
    core.search.close(rid)
    assert rid not in {h["id"] for h in core.search.results()}
    assert core.samples.get(a)["name"] == "新名"
    core.samples.delete([a])
    assert core.search.page(big, 0, 1)["rows"][0]["state"] == "deleted"
    with pytest.raises(CoreError):
        core.search.page(rid)


def _put_f0(c, sid=None, midi=69.0, seconds=10.0, conf=0.9):
    """把整条资产的 F0 放进测量目录（就像任务测好了）：A4 稳定音。"""
    _, ident = c.speech.f0_identity(c.aid, 0.0, seconds)
    n = f0store.total_frames(seconds)
    arr = np.zeros((n, 3), dtype=np.float32)
    arr[:, 0] = 440.0 * 2 ** ((midi - 69) / 12)
    arr[:, 1] = conf
    arr[:, 2] = 1e-3
    src = c.ws.root / "f0chunk.npy"
    np.save(src, arr)
    f0store.adopt_chunk(c.ws.f0, c.aid, ident, 0, src, {})
    return ident


def test_pitch_search_samples_and_sources(core):
    inline(core)
    a = sample(core, start=1.0, end=2.0, name="a")
    b = sample(core, start=2.0, end=3.0, name="b")  # 与 a 相邻：不拼接（R15.3）
    cov = core.search.coverage("pitch", {})
    assert (cov["ready"], cov["stale"]) == (0, 2)
    tc = core.search.coverage("pitchSources", {})
    assert (tc["total"], tc["ready"], tc["stale"]) == (1, 0, 1)
    job = core.search.prepare("pitchSources", {})
    assert job["kind"] == "f0.measure"
    plan = __import__("json").loads(core.conn.execute("SELECT params FROM job WHERE id = ?", (job["id"],)).fetchone()[0])["plan"]
    assert [(p["asset"], p["chunks"]) for p in plan] == [(core.aid, [0])]  # 整轨（10 秒 = 1 段）
    _put_f0(core)
    tc = core.search.coverage("pitchSources", {})
    assert (tc["ready"], tc["stale"]) == (1, 0)
    st, page = run(core, core.search.run_pitch, [{"seconds": 0.6, "low": "A4"}], {}, "samples", {})
    assert sorted(r["sample"]["name"] for r in page["rows"]) == ["a", "b"]
    for r in page["rows"]:
        s = r["sample"]
        assert [(h["start"], h["end"]) for h in r["hits"]] == [(pytest.approx(s["start"]), pytest.approx(s["start"] + 0.6))]  # 同分取起点早
    st, page = run(core, core.search.run_pitch, [{"seconds": 1.2, "low": "A4"}], {}, "samples", {})
    assert page["rows"] == []  # 相邻的 a、b 不能拼出 1.2 秒
    # 同一段声音里连续合格的起点只算一个命中，附在所有完整包含它的采样上（10 §10.2.6）
    sample(core, start=0.5, end=4.0, name="big")
    st, page = run(core, core.search.run_pitch, [{"seconds": 0.6, "low": "A4"}], {}, "samples", {})
    assert [r["sample"]["name"] for r in page["rows"]] == ["big"] and st["stats"]["hits"] == 1
    st, page = run(core, core.search.run_pitch, [{"seconds": 1.2, "low": "A4"}], {}, "samples", {})
    assert [r["sample"]["name"] for r in page["rows"]] == ["big"]
    # 参数非法时即使范围为空也报错（R15.7）
    with pytest.raises(CoreError) as e:
        core.search.run_pitch([{"seconds": 0.6, "low": "A4"}], {"coverage": 2}, "samples", {"text": "没有这个"})
    assert e.value.code == "pitch-param-invalid"
    # 原片音轨模式：一条音轨一行，命中带原片秒；采样专用条件拒绝
    st, page = run(core, core.search.run_pitch, [{"seconds": 0.6, "low": "A4"}], {}, "sources", {})
    row = page["rows"][0]
    assert row["assetId"] == core.aid and row["sample"] is None and row["asset"]["sourceId"]
    assert len(row["hits"]) == 1 and row["hits"][0]["sourceStart"] == pytest.approx(row["hits"][0]["start"])
    with pytest.raises(CoreError) as e:
        core.search.run_pitch([{"seconds": 0.6, "low": "A4"}], {}, "sources", {"natures": ["speech"]})
    assert (e.value.code, e.value.args_["field"]) == ("search-invalid", "natures")
    # 句首/句尾需要台词标注：没有 → 边界未知
    st, page = run(core, core.search.run_pitch, [{"seconds": 0.6, "low": "A4"}], {"headTolerance": 0.1}, "sources", {})
    assert st["stats"]["unknownBounds"] == 1 and page["rows"] == []


def test_pitch_check_hints():
    from ottosmasher.core.search import SearchService

    svc = SearchService.__new__(SearchService)
    r = svc.pitch_check([{"seconds": 0.404, "low": "A4"}, {"seconds": 0.3, "low": "C5", "glide": {"low": "E5"}}], None)
    assert r["ok"] and r["frames"] == [40, 30] and r["text"] == "0.40 A4\n0.30 C5->E5"
    r = svc.pitch_check(None, "0.4 A4\nfoo\n0.05 C5")
    assert not r["ok"] and {p.get("line") for p in r["problems"]} >= {2} and any(p["reason"] == "too-short" for p in r["problems"])


def test_pool_cancel_and_rebuild(tmp_path):
    db = tmp_path / "x.sqlite3"
    import sqlite3

    sqlite3.connect(db).close()
    pool = sw.SearchPool(db, tmp_path, workers=2)
    try:
        slot = pool.acquire()
        out: dict = {}
        t = threading.Thread(target=lambda: out.setdefault("r", pool.run(sw.selftest_wait, [(30.0,), (30.0,)], slot)))
        t0 = time.monotonic()
        t.start()
        time.sleep(1.5)  # 进程启动
        pool.cancel(slot)
        t.join(10)
        assert out["r"] is None and time.monotonic() - t0 < 6
        pool.release(slot)
        # 不理会取消的分片：2 秒后强制结束并重建进程池
        slot = pool.acquire()
        out = {}
        t = threading.Thread(target=lambda: out.setdefault("r", pool.run(sw.selftest_hang, [(60.0,)], slot)))
        t.start()
        time.sleep(1.5)
        old = pool._pool
        pool.cancel(slot)
        t.join(10)
        assert out["r"] is None and pool._pool is None and old is not None
        pool.release(slot)
        slot = pool.acquire()
        res = pool.run(sw.selftest_wait, [(0.05,)], slot)
        assert res and not res[0]["cancelled"]  # 新的进程池可用
    finally:
        pool.shutdown()
