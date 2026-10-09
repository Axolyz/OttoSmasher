"""检索的准备自动在后台做（所有者 2026-10-08）：新采样测 F0、默认轨整轨测 F0、语音分析后建语音检索索引；后台任务排在用户任务后面；不重复提交；设置可关。"""

from __future__ import annotations

import json

from test_rhythm_service import align, core, sample, set_setting  # noqa: F401
from test_search_service import _put_f0


def queued(c, kind=None):
    rows = c.conn.execute("SELECT id, kind, params, background FROM job WHERE status = 'queued' ORDER BY created_at").fetchall()
    return [r for r in rows if kind is None or r["kind"] == kind]


def test_new_sample_and_default_track_get_f0_in_background(core):
    a = sample(core, start=2.0, end=5.6)
    core.auto.on_change({"sample": {a}})
    core.auto.run()
    jobs = queued(core, "f0.measure")
    assert jobs and all(j["background"] == 1 for j in jobs)
    chunks = {(e["asset"], k) for j in jobs for e in json.loads(j["params"])["plan"] for k in e["chunks"]}
    assert chunks == {(core.aid, 0)}  # 10 秒的资产只有一段；采样与整轨合并成一次，不重复
    # 正在排队的段不重复提交
    core.auto.kick_all()
    core.auto.run()
    assert len(queued(core, "f0.measure")) == len(jobs)
    # 任务结束（取消也算）后清掉记账，测好了就不再提交
    for j in jobs:
        core.jobs.cancel(j["id"])
    assert not core.auto.pending_f0
    _put_f0(core)
    core.auto.kick_all()
    core.auto.run()
    assert queued(core, "f0.measure") == []


def test_speech_index_after_analysis_and_setting_off(core):
    _put_f0(core)
    a = sample(core)
    align(core, a)
    core.auto.on_change({"measure": {a}})
    core.auto.run()
    jobs = queued(core, "search.index")
    assert len(jobs) == 1 and json.loads(jobs[0]["params"])["ids"] == [a] and jobs[0]["background"] == 1
    core.jobs.cancel(jobs[0]["id"])
    set_setting(core, "analysis.auto_prepare", False)
    core.auto.kick_all()
    core.auto.run()
    assert queued(core, "search.index") == []


def test_user_jobs_start_before_background_jobs(core):
    core.jobs.submit("search.index", {"ids": []}, background=True)
    user = core.jobs.submit("search.index", {"ids": []})
    row = core.conn.execute("SELECT id FROM job WHERE status='queued' AND channel='light' ORDER BY background, created_at, rowid LIMIT 1").fetchone()
    assert row[0] == user["id"]


def test_quit_prompt_ignores_background_jobs(core):
    core.jobs.submit("search.index", {"ids": []}, background=True)
    assert core.jobs.active_count(include_background=False) == 0
    core.jobs.submit("search.index", {"ids": []})
    assert core.jobs.active_count(include_background=False) == 1
