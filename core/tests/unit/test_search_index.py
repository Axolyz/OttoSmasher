"""检索索引（规格 09 §9.6.5、10 §10.2.5，16 R14.14）：失效键、准备任务（进程内直接跑）与采纳、F0 覆盖。"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest
from test_rhythm_service import ONSETS, align, core, sample, set_setting  # noqa: F401 — 复用夹具

from ottosmasher.algo import speech_search as ss
from ottosmasher.core import search_index as si
from ottosmasher.core.errors import CoreError
from ottosmasher.jobs import search as search_jobs
from ottosmasher.models import f0store


class Ctx:
    def __init__(self, d: Path) -> None:
        self.job_dir = d
        self.device = {}
        self.events: list[tuple] = []

    def progress(self, *a, **k) -> None:
        self.events.append(a)


def run_index_job(c, ids, tmp_path, workers=1):
    d = tmp_path / "job"
    d.mkdir(exist_ok=True)
    ctx = Ctx(d)
    params = {"ids": ids, "db": str(c.ws.db_path), "workspace": str(c.ws.root), "support_dir": str(c.support_dir), "workers": workers}
    res = search_jobs.index(params, ctx)
    c.search.jobs.jobs_dir = tmp_path
    c.search._adopt_index({"id": "job"}, res)
    return res


def key(c, sid):
    return si.speech_keys(c.conn, [sid])[sid]


def test_keys_change_only_with_relevant_inputs(core):
    s = sample(core)
    k0, has = key(core, s)
    assert not has  # 没有分析
    align(core, s)
    k1, has = key(core, s)
    assert has and k1 != k0
    v = core.samples.get(s)["version"]
    core.edits.apply({"ops": [{"entity": "sample", "id": s, "version": v, "fields": {"name": "改名", "starred": True}}]})
    assert key(core, s)[0] == k1  # 改名、星标不失效（R14.14）
    core.edits.apply({"ops": [{"entity": "sample", "id": s, "version": core.samples.get(s)["version"], "fields": {"local_tags": ["好用"]}}]})
    assert key(core, s)[0] == k1
    core.edits.apply({"ops": [{"entity": "sample", "id": s, "version": core.samples.get(s)["version"], "fields": {"local_tags": ["好用", "character:京子"]}}]})
    k2 = key(core, s)[0]
    assert k2 != k1  # 角色标签进逐块属性
    core.rhythm.set_params(s, core.samples.get(s)["version"], {"sensitivity": 1.5})
    k3 = key(core, s)[0]
    assert k3 != k2
    set_setting(core, "analysis.penalty", 2.0)
    assert key(core, s)[0] != k3
    align(core, s)  # 新的分析头
    assert key(core, s)[0] not in (k1, k2, k3)


def test_prepare_build_adopt_and_search(core, tmp_path):
    a = sample(core, name="a")
    b = sample(core, name="b")
    sample(core, start=6.0, end=9.0, name="c")  # 没有分析（也没有覆盖它的测量可投影）
    align(core, a)
    align(core, b)
    cov = core.search.coverage("speech", {})
    assert (cov["total"], cov["ready"], cov["stale"], cov["noAnalysis"]) == (3, 0, 2, 1)
    res = run_index_job(core, [a, b], tmp_path)
    assert res["built"] == 2
    cov = core.search.coverage("speech", {})
    assert (cov["ready"], cov["stale"], cov["noAnalysis"]) == (2, 0, 1)
    with pytest.raises(CoreError) as e:
        core.search.prepare("speech", {})
    assert e.value.code == "search-nothing-to-prepare"
    wires = si.read_wires(core.conn, [a, b])
    assert [w["id"] for w in wires] == [a, b]
    batch = ss.Batch.of_wires(wires)
    # 索引与节奏视图一致：音块数、起音、前导辅音、停顿段
    v = core.rhythm.view(a)
    row = batch.row(0)
    assert [x.onset for x in row.blocks] == pytest.approx([x["onset"] for x in v["blocks"]])
    assert [x.consonants for x in row.blocks] == [tuple(x["consonants"]) for x in v["blocks"]]
    assert [x.pseg for x in row.blocks] == [x["pauseSegment"] for x in v["blocks"]]
    assert [p.scope for p in row.plans] == [-1, 0, 1]  # 整句 + 两个语段
    q = ss.parse_query({"blocks": [{"consonants": ["k"], "vowel": "a"}] * 2})
    out = ss.search(batch, q, None)
    # 不跨停顿：停顿段 0 有 4 块（3 个窗口）、停顿段 1 有 3 块（2 个窗口）
    first, second = sorted([a, b])  # 同分按采样排
    assert [(batch.sample_ids[h.sample], h.first) for h in out.hits] == [(first, k) for k in (0, 1, 2, 4, 5)] + [(second, k) for k in (0, 1, 2, 4, 5)]
    assert out.hits[0].start == pytest.approx(ONSETS[0] - 0.05)  # 命中区从前导辅音开始
    # 节奏证据可算（整句与语段方案都从索引现算）
    rq = ss.parse_query({"blocks": [{"note": [0, 0.5]}, {"note": [1, 1.5]}], "strategy": "rank"})
    assert ss.search(batch, rq, 180.0).hits
    # 改了节奏参数 → 过期（R14.14：只在相关变化时失效）
    core.rhythm.set_params(a, core.samples.get(a)["version"], {"segmentThreshold": 0.5})
    cov = core.search.coverage("speech", {})
    assert (cov["ready"], cov["stale"]) == (1, 1)
    assert core.search.prepare("speech", {})["kind"] == "search.index"


def test_adoption_drops_rows_whose_inputs_changed(core, tmp_path):
    s = sample(core)
    align(core, s)
    d = tmp_path / "job"
    d.mkdir()
    params = {"ids": [s], "db": str(core.ws.db_path), "workspace": str(core.ws.root), "support_dir": str(core.support_dir), "workers": 1}
    res = search_jobs.index(params, Ctx(d))
    core.rhythm.set_params(s, core.samples.get(s)["version"], {"sensitivity": 1.5})  # 任务跑完、采纳之前资料变了
    core.search.jobs.jobs_dir = tmp_path
    core.search._adopt_index({"id": "job"}, res)
    assert core.conn.execute("SELECT COUNT(*) FROM speech_index").fetchone()[0] == 0
    assert core.search.coverage("speech", {})["stale"] == 1


def test_index_rows_for_unbuildable_analysis_are_none(core, tmp_path):
    s = sample(core)
    align(core, s, ph=[{"label": "k", "start": 2.1, "end": 2.2, "mora": 0}])  # 没有元音 → 没有音块
    run_index_job(core, [s], tmp_path)
    r = core.conn.execute("SELECT status, reason FROM speech_index").fetchone()
    assert tuple(r) == ("none", "rhythm-no-blocks")
    assert core.search.coverage("speech", {})["noAnalysis"] == 1


def test_parallel_build_equals_serial(core, tmp_path, monkeypatch):
    ids = []
    for i in range(6):
        s = sample(core, name=f"s{i}")
        align(core, s)
        ids.append(s)
    serial = search_jobs.build_batch(str(core.ws.db_path), str(core.ws.root), str(core.support_dir), [(s, si.speech_keys(core.conn, [s])[s][0]) for s in ids])
    monkeypatch.setattr(search_jobs, "PARALLEL_MIN", 2)
    monkeypatch.setattr(search_jobs, "BATCH", 2)
    run_index_job(core, ids, tmp_path, workers=3)
    got = {r[0]: bytes(r[1]) for r in core.conn.execute("SELECT sample_id, data FROM speech_index")}
    assert got == {r[0]: r[4] for r in serial}


def test_f0_identity_from_db_equals_service_and_pitch_coverage(core):
    s = sample(core, start=2.0, end=5.6)
    ident_db = si.asset_identities(core.conn, {core.aid: [(2.0, 5.6)]})[core.aid]["identities"][(2.0, 5.6)]
    _, ident = core.speech.f0_identity(core.aid, 2.0, 5.6)
    assert ident_db == ident
    cov = core.search.coverage("pitch", {})
    assert (cov["total"], cov["ready"], cov["stale"]) == (1, 0, 1)
    plan = core.search._f0_plan(si.pitch_coverage(core.conn, core.ws.f0, [(s, core.aid, 2.0, 5.6)]))
    assert [(p["asset"], p["chunks"]) for p in plan] == [(core.aid, [0])]
    # 放进一段 F0（就像任务测好了）→ 已索引
    src = core.ws.root / "chunk.npy"
    np.save(src, np.zeros((f0store.total_frames(10.0), 3), dtype=np.float32))
    f0store.adopt_chunk(core.ws.f0, core.aid, ident, 0, src, {})
    cov = core.search.coverage("pitch", {})
    assert (cov["ready"], cov["stale"]) == (1, 0)


def test_preloaded_decode_gives_identical_rows(core):
    """阶段 7 提速：同一资产上相邻采样一次解码再切片，与逐条解码得到的索引逐字节相同。"""
    from ottosmasher.jobs.search import _services

    ids = []
    for k, (a, b) in enumerate([(2.0, 3.5), (3.5, 5.6), (2.3, 4.9)]):
        s = sample(core, start=a, end=b, name=f"p{k}")
        align(core, s, a, b, ph=[p for p in __import__("test_rhythm_service").phones() if a <= p["start"] and p["end"] <= b])
        core.conn.execute("UPDATE sample SET align_text_manual='か' WHERE id=?", (s,))  # 各自手输过台词：只读自己那一句（三句互相交叠）
        ids.append(s)
    keys = si.speech_keys(core.conn, ids)
    batch = search_jobs.build_batch(str(core.ws.db_path), str(core.ws.root), str(core.support_dir), [(s, keys[s][0]) for s in ids])
    conn, rhythm = _services(str(core.ws.db_path), str(core.ws.root), str(core.support_dir))
    try:
        single = [si.build_row(rhythm, conn, s) for s in ids]
    finally:
        conn.close()
    assert [tuple(r[2:]) for r in batch] == single
    assert all(r[2] == "ok" for r in batch)
