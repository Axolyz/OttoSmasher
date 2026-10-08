"""语音分析的 Core 侧（规格 08 §8.2.1、§8.4、16 S1.7、R11.5、R11.8）：对齐文本优先级、范围、复用、冻结、采纳规则。"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

from ottosmasher.core.clock import new_id, now_iso
from ottosmasher.core.edits import dumps
from ottosmasher.core.errors import CoreError
from ottosmasher.core.server import Core


@pytest.fixture
def core(tmp_path: Path):
    wav = tmp_path / "a.wav"
    subprocess.run(["ffmpeg", "-v", "error", "-f", "lavfi", "-i", "sine=frequency=220:duration=20", "-ar", "48000", str(wav)], check=True)
    c = Core(tmp_path / "ws")
    c.open()
    r = c.sources.add([str(wav)])[0]
    c.sid = r["sourceId"]
    c.aid = r["assets"][0]["assetId"]
    yield c
    c.close()


def ann(c, start, end, auto="あ", manual=None):
    aid = new_id()
    ts = now_iso()
    c.conn.execute(
        'INSERT INTO annotation(id, source_id, kind, scope, scope_role, start, "end", raw_text, clean_text, align_text_auto, align_text_manual, tags, created_at, updated_at)'
        " VALUES (?, ?, 'line', 'role', 'vocal', ?, ?, ?, ?, ?, ?, '[]', ?, ?)",
        (aid, c.sid, start, end, auto, auto, auto, manual, ts, ts),
    )
    return aid


def sample(c, start, end, *, nature="speech", annotation=None, snapshot=None, manual=None, parent=None, name="s"):
    sid = new_id()
    ts = now_iso()
    origin = dumps({"kind": "subtitle", "annotation": annotation}) if annotation else None
    c.conn.execute(
        'INSERT INTO sample(id, asset_id, start, "end", name, nature, created_via, origin, text_snapshot, align_text_manual, parent_sample_id, created_at, updated_at)'
        " VALUES (?, ?, ?, ?, ?, ?, 'subtitle', ?, ?, ?, ?, ?, ?)",
        (sid, c.aid, start, end, name, nature, origin, dumps(snapshot) if snapshot else None, manual, parent, ts, ts),
    )
    return sid


def row(c, sid):
    return c.conn.execute(f"SELECT {c.speech._SAMPLE_COLS} FROM sample WHERE id=?", (sid,)).fetchone()


def test_align_text_priority_and_reasons(core):
    a = ann(core, 1.0, 2.0, auto="じどう")
    s1 = sample(core, 0.9, 2.1, annotation=a, snapshot={"alignText": "すなっぷ", "start": 1.0, "end": 2.0})
    t = core.speech.text_of(row(core, s1))
    assert (t["text"], t["source"], t["equalsSubtitle"]) == ("じどう", "line-auto", True)
    core.conn.execute("UPDATE annotation SET align_text_manual='ぎょう' WHERE id=?", (a,))
    assert core.speech.text_of(row(core, s1))["source"] == "line-manual"
    core.conn.execute("UPDATE sample SET align_text_manual='しゅどう' WHERE id=?", (s1,))
    t = core.speech.text_of(row(core, s1))
    assert (t["text"], t["source"], t["equalsSubtitle"]) == ("しゅどう", "sample-manual", False)
    s2 = sample(core, 3.0, 4.0, snapshot={"alignText": "すなっぷ"})
    assert core.speech.text_of(row(core, s2))["source"] == "snapshot"
    # 没有文本：截取自有文本的父采样 → range-differs；否则 no-text
    s3 = sample(core, 1.2, 1.5, parent=s1)
    assert core.speech.text_of(row(core, s3)) == {"text": None, "reason": "range-differs"}
    assert core.speech.text_of(row(core, sample(core, 5.0, 6.0)))["reason"] == "no-text"


def test_window_extends_within_the_asset_and_records_truncation(core):
    s1 = sample(core, 0.3, 1.0, snapshot={"alignText": "あ"})
    it = core.speech.item_for(row(core, s1), core.speech._versions())
    assert it["window"][0] == pytest.approx(0.0) and it["truncated"] == [True, False]
    assert it["actual"][0] == pytest.approx(0.3) and it["actual"][1] == pytest.approx(0.65)
    assert it["requested"] == [0.65, 0.65]
    assert it["frames"] == [0, round(1.65 * 48000)]
    s2 = sample(core, 19.5, 20.0, snapshot={"alignText": "あ"})
    it2 = core.speech.item_for(row(core, s2), core.speech._versions())
    assert it2["window"][1] == pytest.approx(20.0) and it2["truncated"] == [False, True]


def test_source_scope_and_plan(core):
    op = new_id()
    core.conn.execute("INSERT INTO oped(id, source_id, kind, start, \"end\", origin, created_at, updated_at) VALUES (?, ?, 'OP', 5.0, 8.0, 'manual', ?, ?)", (op, core.sid, now_iso(), now_iso()))
    keep = sample(core, 1.0, 2.0, snapshot={"alignText": "あ", "start": 1.0, "end": 2.0})
    sample(core, 6.0, 7.0, snapshot={"alignText": "い", "start": 6.0, "end": 7.0})  # 原字幕区间在 OP 里
    sample(core, 7.95, 9.0, snapshot={"alignText": "う", "start": 8.0, "end": 9.0})  # 端点相接不算交叠 → 在范围内
    sample(core, 3.0, 4.0, nature="pitched", snapshot={"alignText": "え", "start": 3.0, "end": 4.0})  # 不是语音
    sample(core, 10.0, 11.0)  # 没有文本：不在原片入口的范围里
    pv = core.speech.preview("source", [core.sid], False)
    assert (pv["run"], pv["fresh"], pv["blocked"]) == (2, 0, 0)
    assert pv["mixBound"] == 2  # 都绑在原混音上
    # 采样入口：显式选的不再按性质/OP/ED 过滤；缺文本的进 K
    nt = sample(core, 12.0, 13.0, name="ない")
    pv = core.speech.preview("samples", [keep, nt], False)
    assert (pv["run"], pv["blocked"]) == (1, 1) and pv["blockedList"] == [{"id": nt, "name": "ない", "reason": "no-text"}]
    with pytest.raises(CoreError) as e:
        core.speech.submit("samples", [nt], False)
    assert e.value.code == "speech-nothing-to-do"


def _fake_run(core, sids, *, rerun=False, status="ok", mutate=None):
    """提交一个任务但不真的跑：直接写逐条结果文件并调用采纳函数（模拟任务成功结束）。"""
    job = core.speech.submit("samples", sids, rerun)
    params = json.loads(core.conn.execute("SELECT params FROM job WHERE id=?", (job["id"],)).fetchone()[0])
    core.jobs.cancel(job["id"])  # 不让真的工作进程跑起来
    d = core.jobs.jobs_dir / job["id"] / "items"
    d.mkdir(parents=True, exist_ok=True)
    if mutate:
        mutate()
    for it in params["items"]:
        if status == "ok":
            (d / f"{it['idx']}.json").write_text(json.dumps({"phones": [{"label": "a", "start": it["target"][0], "end": it["target"][1]}]}), encoding="utf-8")
            core.jobs._item(job["id"], {"idx": it["idx"], "status": "ok", "ref": f"{it['idx']}.json"})
        else:
            core.jobs._item(job["id"], {"idx": it["idx"], "status": "failed", "error": {"code": "align-unsupported", "args": {}}})
    jrow = dict(core.conn.execute("SELECT * FROM job WHERE id=?", (job["id"],)).fetchone())
    core.speech._adopt(jrow, {"probes": []})
    return job["id"]


def heads(core, sid):
    h = core.speech._head_row(sid)
    runs = core.conn.execute("SELECT status, manual FROM measure_run WHERE owner_id=? ORDER BY rowid", (sid,)).fetchall()
    return (h["run_id"] if h else None, [tuple(r) for r in runs])


def test_reuse_and_adoption_rules(core):
    s1 = sample(core, 1.0, 2.0, snapshot={"alignText": "あ"})
    _fake_run(core, [s1])
    head1, runs = heads(core, s1)
    assert head1 and runs == [("ok", 0)]
    # 再发起：输入完全相同 → 跳过
    pv = core.speech.preview("samples", [s1], False)
    assert (pv["run"], pv["fresh"], pv["freshAll"]) == (0, 1, 1)
    assert core.speech.preview("samples", [s1], True)["run"] == 1
    # 改了对齐文本 → 重跑
    core.conn.execute("UPDATE sample SET align_text_manual='い' WHERE id=?", (s1,))
    assert core.speech.preview("samples", [s1], False)["run"] == 1
    # 失败结果只进历史，旧的成功结果不消失
    _fake_run(core, [s1], status="failed")
    head2, runs = heads(core, s1)
    assert head2 == head1 and runs[-1] == ("failed", 0)
    # 任务期间输入又变了 → 只进历史
    _fake_run(core, [s1], mutate=lambda: core.conn.execute("UPDATE sample SET align_text_manual='う' WHERE id=?", (s1,)))
    head3, runs = heads(core, s1)
    assert head3 == head1 and runs[-1] == ("ok", 0)
    # 正常重跑 → 新的当前头
    _fake_run(core, [s1])
    head4, _ = heads(core, s1)
    assert head4 != head1
    # 当前头是人工版本 → 新结果只进历史（S5.3）
    core.conn.execute("UPDATE measure_run SET manual=1 WHERE id=?", (head4,))
    _fake_run(core, [s1], rerun=True)
    head5, runs = heads(core, s1)
    assert head5 == head4 and runs[-1] == ("ok", 0)


def test_results_table_and_counts(core):
    s1 = sample(core, 1.0, 2.0, snapshot={"alignText": "あ"}, name="一")
    s2 = sample(core, 3.0, 4.0, snapshot={"alignText": "い"}, name="二")
    _fake_run(core, [s1])
    jid = _fake_run(core, [s1, s2], status="failed")
    rows = core.speech.results(jid)
    assert [(r["name"], r["status"]) for r in rows] == [("二", "failed"), ("一", "skipped")]
    assert rows[0]["error"]["code"] == "align-unsupported"
    assert core.speech.analyzed_counts()[core.sid] == {"speech": 2, "analyzed": 1}
    prep = core.dispatch({"id": 1, "m": "sources.prep", "p": {"id": core.sid}})
    assert prep["ok"] and prep["r"]["speech"] == {"ok": False, "speech": 2, "analyzed": 1}
