"""语音分析的 Core 侧（规格 08 §8.4、§8.7、§8.8、16 S1.7、R11.5–R11.8）。

所有者 2026-10-09【基线变更】：分析属于“文本层的段 + 具体那条资产”；采样不拥有分析，只读与判定区间正长度交叠的所有段在它所在资产上的分析；
任何一段不可用（没分析 / 段改过）→ 节奏不可用并写明；被采样范围裁掉一部分的非停顿音素标 ◐；两段音素重叠 → 冲突，不自动裁决。
改了段的文本或边界 → 旧分析立即停用，撤销那次修改立即恢复；人工版本保护只对内容与段一致的头生效。
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

from ottosmasher.core import units
from ottosmasher.core.clock import new_id, now_iso
from ottosmasher.core.edits import dumps
from ottosmasher.core.errors import CoreError
from ottosmasher.core.server import Core
from ottosmasher.store.db import bundled_migrations, connect, migrate


@pytest.fixture
def core(tmp_path: Path):
    wav = tmp_path / "a.wav"
    subprocess.run(["ffmpeg", "-v", "error", "-f", "lavfi", "-i", "sine=frequency=220:duration=20", "-ar", "48000", str(wav)], check=True)
    c = Core(tmp_path / "ws")
    c.open()
    r = c.sources.add([str(wav)])[0]
    c.sid = r["sourceId"]
    c.aid = r["assets"][0]["assetId"]
    c.changes = []
    inner = c.speech.on_change
    c.speech.on_change = lambda cs: (c.changes.append(cs), inner and inner(cs))
    yield c
    c.close()


def seg(c, start, end, text="あ", speakers=None):
    """经编辑通道加一段（字幕来源，未受保护）。"""
    r = c.edits.apply({"ops": [{"entity": "segment", "op": "create", "fields": {
        "source_id": c.sid, "start": start, "end": end, "text": text, "speakers": speakers or [], "origin": "subtitle"}}]})
    return r["changes"][0]["id"]


def edit_seg(c, sid, **fields):
    v = c.conn.execute("SELECT version FROM text_segment WHERE id=?", (sid,)).fetchone()[0]
    return c.edits.apply({"ops": [{"entity": "segment", "id": sid, "version": v, "fields": fields}]})


def sample(c, start, end, name="s"):
    return c.samples.create(c.aid, start, end, name=name, nature="speech")["id"]


def unit(c, segment):
    return units.unit_id(segment, c.aid)


def _adopt(core, job, *, status="ok", mutate=None, phones=None):
    """不真的跑任务：直接写逐条结果文件并调用采纳函数（模拟任务成功结束）。默认每段一个音素 a 覆盖整个目标。"""
    params = json.loads(core.conn.execute("SELECT params FROM job WHERE id=?", (job["id"],)).fetchone()[0])
    core.jobs.cancel(job["id"])  # 不让真的工作进程跑起来
    d = core.jobs.jobs_dir / job["id"] / "items"
    d.mkdir(parents=True, exist_ok=True)
    if mutate:
        mutate()
    for it in params["items"]:
        if status == "ok":
            ph = phones(it) if phones else [{"label": "a", "start": it["target"][0], "end": it["target"][1], "mora": 0, "word": 0}]
            (d / f"{it['idx']}.json").write_text(json.dumps({"phones": ph, "morae": ["ア"], "words": [], "frontend": {}}), encoding="utf-8")
            core.jobs._item(job["id"], {"idx": it["idx"], "status": "ok", "ref": f"{it['idx']}.json"})
        else:
            core.jobs._item(job["id"], {"idx": it["idx"], "status": "failed", "error": {"code": "align-unsupported", "args": {}}})
    jrow = dict(core.conn.execute("SELECT * FROM job WHERE id=?", (job["id"],)).fetchone())
    core.speech._adopt(jrow, {"probes": []})
    return job["id"]


def _run(core, ids, *, entry="samples", rerun=False, asset=None, **kw):
    return _adopt(core, core.speech.submit(entry, ids, rerun, asset), **kw)


def heads(core, u):
    h = core.speech._head_row(u)
    runs = core.conn.execute("SELECT status, manual FROM measure_run WHERE owner_id=? ORDER BY rowid", (u,)).fetchall()
    return (h["run_id"] if h else None, [tuple(r) for r in runs])


def test_source_entry_analyzes_segments_without_samples(core):
    op = new_id()
    core.conn.execute("INSERT INTO oped(id, source_id, kind, start, \"end\", origin, created_at, updated_at) VALUES (?, ?, 'OP', 5.0, 8.0, 'manual', ?, ?)", (op, core.sid, now_iso(), now_iso()))
    a = seg(core, 1.0, 2.0, "あ")
    seg(core, 6.0, 7.0, "い")  # 在 OP 里
    seg(core, 8.0, 9.0, "う")  # 端点相接不算交叠 → 在范围内
    pv = core.speech.preview("source", [core.sid], False)
    assert (pv["run"], pv["fresh"], pv["blocked"]) == (2, 0, 0) and pv["mixBound"] == 2  # 没有默认人声轨：原混音
    # 目标 = 段区间（不含字幕采样扩展），窗口 = 目标 ± 容差
    it = next(i for i in core.speech.plan("source", [core.sid], False)["run"] if i["owner"] == unit(core, a))
    assert it["target"] == [pytest.approx(1.0), pytest.approx(2.0)] and it["window"][0] == pytest.approx(0.35)
    _run(core, [core.sid], entry="source")
    assert core.speech.preview("source", [core.sid], False)["fresh"] == 2
    layer = core.speech.for_asset(core.aid, 0.0, 20.0)
    assert [(x["segmentId"], x["ordinal"]) for x in layer][0] == (a, 1)
    # 段右键分析（同一个确认框、同一套跳过规则）
    assert core.speech.preview("segments", [a], False)["fresh"] == 1
    # 采样入口：判定区间读到的段；没读到段的进 K
    s = sample(core, 0.9, 2.1)
    nt = sample(core, 15.0, 16.0, name="ない")
    pv = core.speech.preview("samples", [s, nt], False)
    assert (pv["fresh"], pv["blocked"]) == (1, 1) and pv["blockedList"] == [{"id": nt, "name": "ない", "reason": "no-text"}]


def test_window_truncation_at_asset_edges(core):
    a, b = seg(core, 0.3, 1.0), seg(core, 19.5, 20.0)
    run = {i["owner"]: i for i in core.speech.plan("segments", [a, b], False)["run"]}
    ia, ib = run[unit(core, a)], run[unit(core, b)]
    assert ia["window"][0] == pytest.approx(0.0) and ia["truncated"] == [True, False] and ia["actual"][0] == pytest.approx(0.3)
    assert ib["window"][1] == pytest.approx(20.0) and ib["truncated"] == [False, True]


def test_reuse_adoption_and_stopping_after_edits(core):
    a = seg(core, 1.0, 2.0, "あ")
    u = unit(core, a)
    s = sample(core, 0.9, 2.1)
    _run(core, [s])
    head1, runs = heads(core, u)
    assert head1 and runs == [("ok", 0)] and core.samples.get(s)["analysis"] == "ok"
    assert core.speech.preview("samples", [s], False)["fresh"] == 1  # 输入没变 → 跳过
    # 改了段的文本 → 旧分析立即停用（采样显示“第 1 段改过”），再发起会重跑
    edit_seg(core, a, text="いえ")
    assert core.samples.get(s)["analysis"] == "stale"
    v = core.speech.sample_view(s)
    assert v["head"] is None and v["blocked"] == {"code": "rhythm-segment-stale", "args": {"segments": "1", "n": 1}}
    assert core.rhythm.view(s)["reason"]["code"] == "rhythm-segment-stale"
    assert core.speech.preview("samples", [s], False)["run"] == 1
    # 撤销那次修改 → 内容又一致，立即恢复（不用重跑）
    core.edits.undo()
    assert core.samples.get(s)["analysis"] == "ok" and core.speech.sample_view(s)["head"]["runId"] == head1
    # 失败结果只进历史
    _run(core, [s], rerun=True, status="failed")
    assert heads(core, u)[0] == head1
    # 任务期间段又改了 → 只进历史
    _run(core, [s], rerun=True, mutate=lambda: edit_seg(core, a, end=2.2))
    assert heads(core, u)[0] == head1
    core.edits.undo()
    # 当前头是人工版本（内容与段一致）→ 新结果只进历史（S5.3）
    core.conn.execute("UPDATE measure_run SET manual=1 WHERE id=?", (head1,))
    _run(core, [s], rerun=True)
    assert heads(core, u)[0] == head1
    # 段改过之后：人工保护不再生效，重跑成为新头
    edit_seg(core, a, end=2.3)
    _run(core, [s])
    head2, _ = heads(core, u)
    assert head2 != head1 and core.samples.get(s)["analysis"] == "partial"  # 段变长到 2.3，被采样范围（到 2.1）裁掉一部分 → ◐


def test_reading_rules_partial_merge_missing_conflict(core):
    a, b = seg(core, 1.0, 2.0, "あ"), seg(core, 3.0, 4.0, "い")
    _run(core, [core.sid], entry="source")
    sub = sample(core, 0.9, 2.1)  # 默认判定区间 = 选区，只碰到第 1 段
    cut = sample(core, 1.2, 1.5)  # 截一个音节
    merged = sample(core, 0.9, 4.1)  # 跨两段
    assert [core.samples.get(x)["analysis"] for x in (sub, cut, merged)] == ["ok", "partial", "ok"]
    vc = core.speech.sample_view(cut)
    assert vc["head"]["partial"] and [(p["start"], p["end"], p.get("clipped")) for p in vc["head"]["result"]["phones"]] == [(1.2, 1.5, True)]
    vm = core.speech.sample_view(merged)
    assert vm["head"]["units"] == [unit(core, a), unit(core, b)]
    assert [(p["label"], p["start"], p["end"], p.get("mora"), p.get("seg")) for p in vm["head"]["result"]["phones"]] == [
        ("a", 1.0, 2.0, 0, 0), ("pau", 2.0, 3.0, None, 1), ("a", 3.0, 4.0, 1, 1)]
    assert vm["text"] == "あ い"
    core.strict_api = True  # 返回值与声明的类型一致
    for x in (sub, cut, merged):
        assert core.dispatch({"id": 1, "m": "speech.sample", "p": {"id": x}})["ok"]
        assert core.dispatch({"id": 2, "m": "rhythm.view", "p": {"id": x}})["ok"]
    assert core.dispatch({"id": 3, "m": "speech.forAsset", "p": {"assetId": core.aid, "start": 0.0, "end": 20.0}})["ok"]
    # 加一段还没分析的 → 读到它的采样“部分段未分析”，节奏不可用
    c3 = seg(core, 3.5, 3.8, "う")
    assert core.samples.get(merged)["analysis"] == "incomplete"
    assert core.speech.sample_view(merged)["blocked"]["code"] == "rhythm-segments-missing"
    # 分析它（音素与第 2 段重叠）→ 冲突：写明第几段与第几段在哪重叠
    _run(core, [c3], entry="segments")
    vm = core.speech.sample_view(merged)
    assert vm["head"] is None and vm["conflict"]["a"] == 2 and vm["conflict"]["b"] == 3
    assert core.rhythm.view(merged)["reason"]["code"] == "rhythm-units-conflict"
    # 缩小判定区间（必须在采样范围内）→ 只读第 1 段
    core.edits.apply({"ops": [{"entity": "sample", "id": merged, "version": core.samples.get(merged)["version"], "fields": {"judge": [0.9, 2.5]}}]})
    assert core.speech.sample_view(merged)["head"]["units"] == [unit(core, a)]


def test_manual_edits_belong_to_the_segment_and_follow_samples(core):
    a = seg(core, 0.0, 1.0, "ああ")
    s1, s2, cut = sample(core, 0.0, 1.0), sample(core, 0.05, 0.95), sample(core, 0.2, 0.6)
    _run(core, [s1], phones=lambda it: [{"label": "a", "start": 0.1, "end": 0.4, "mora": 0, "word": 0}, {"label": "a", "start": 0.4, "end": 0.8, "mora": 1, "word": 0, "eff": [0.45, 0.7]}])
    u = unit(core, a)
    v = core.speech._head_row(u)["version"]
    with pytest.raises(CoreError) as e:
        core.speech.save_manual(u, v, None, "0.1\t0.5\ta\n0.5\t0.8\ti")
    assert (e.value.code, e.value.args_["reason"], e.value.args_["line"]) == ("speech-edit-invalid", "label", 2)
    with pytest.raises(CoreError) as e:
        core.speech.save_manual(u, v, None, "0.1\t0.5\ta")
    assert e.value.args_["reason"] == "count"
    core.changes.clear()
    r = core.speech.save_manual(u, v, None, ".1\t.5\ta\n.5\t.8\ta")
    changed = core.changes[-1].entities["measure"]
    assert {u, s1, s2, cut} <= set(changed)  # 所有读这段的采样同时生效
    for x in (s1, s2, cut):
        assert core.speech.sample_view(x)["head"]["manual"] is True
    ph = core.speech.sample_view(s1)["head"]["result"]["phones"]
    assert [(p["start"], p["end"], p["mora"]) for p in ph] == [(0.1, 0.5, 0), (0.5, 0.8, 1)] and ph[1]["eff"] == [0.5, 0.8]
    assert tuple(core.conn.execute("SELECT span_start, span_end FROM measure_run WHERE id=?", (r["runId"],)).fetchone()) == (0.1, 0.8)
    # 段受保护（有人工音素版本）
    from ottosmasher.core import text_layer as tl

    assert next(x for x in tl.list_for_source(core.conn, core.sid)["segments"] if x["id"] == a)["protected"] is True
    with pytest.raises(CoreError) as e:
        core.speech.save_manual(u, v, None, ".1\t.5\ta\n.5\t.8\ta")
    assert e.value.code == "speech-edit-conflict"
    # 切换版本（R11.7）
    model = next(x for x in core.speech.sample_view(s1)["units"][0]["runs"] if not x["manual"] and x["status"] == "ok")
    sw = core.speech.switch_head(u, model["id"], r["version"])
    assert core.speech.sample_view(s1)["head"]["runId"] == model["id"] and sw["version"] == r["version"] + 1
    # 段改过之后不能在旧头上存人工时间
    edit_seg(core, a, text="あい")
    with pytest.raises(CoreError) as e:
        core.speech.save_manual(u, sw["version"], None, ".1\t.5\ta\n.5\t.8\ta")
    assert e.value.args_["reason"] == "segment-changed"
    # 删采样不删分析（P9）
    core.edits.undo()
    core.samples.delete([s1])
    assert core.speech._head_row(u) is not None


def test_asset_layer_and_no_side_effects(core):
    a = seg(core, 1.0, 2.0, "あ")
    s1 = sample(core, 0.9, 2.1)
    v = core.speech.sample_view(s1)
    assert v["head"] is None and v["text"] == "あ" and v["units"][0]["state"] == "none"
    _run(core, [s1])
    v = core.speech.sample_view(s1)
    assert v["head"]["status"] == "ok" and len(v["units"][0]["runs"]) == 1
    layer = core.speech.for_asset(core.aid, 0.0, 20.0)
    assert [x["unitId"] for x in layer] == [unit(core, a)] and layer[0]["phones"][0]["start"] == pytest.approx(1.0)
    assert core.speech.for_asset(core.aid, 5.0, 20.0) == []
    # 文件指纹不同（记录里的快照对不上）→ 不显示、不读（R11.10）
    rid = v["head"]["runId"]
    inp = json.loads(core.conn.execute("SELECT inputs FROM measure_run WHERE id=?", (rid,)).fetchone()[0])
    inp["audio"]["snapshot"]["size"] = 1
    core.conn.execute("UPDATE measure_run SET inputs=? WHERE id=?", (json.dumps(inp), rid))
    assert core.speech.for_asset(core.aid, 0.0, 20.0) == []
    assert core.speech.sample_view(s1)["units"][0]["state"] == "other-sound"
    n = core.conn.total_changes
    core.speech.sample_view(s1)
    core.speech.for_asset(core.aid, 0.0, 20.0)
    assert core.conn.total_changes == n  # 读取没有副作用


def test_results_table_counts_and_rerun_by_unit(core):
    a, b = seg(core, 1.0, 2.0, "一"), seg(core, 3.0, 4.0, "二")
    s1, s2 = sample(core, 0.9, 2.1), sample(core, 2.9, 4.1)
    _run(core, [s1])
    jid = _run(core, [s1, s2], status="failed")
    rows = core.speech.results(jid)
    assert [(r["name"], r["status"], r["unitId"]) for r in rows] == [("二", "failed", unit(core, b)), ("一", "skipped", unit(core, a))]
    assert core.speech.preview("units", [unit(core, b)], False)["run"] == 1
    assert core.speech.analyzed_counts()[core.sid] == {"speech": 2, "analyzed": 1}
    prep = core.dispatch({"id": 1, "m": "sources.prep", "p": {"id": core.sid}})
    assert prep["ok"] and prep["r"]["speech"] == {"ok": False, "speech": 2, "analyzed": 1}


def test_missing_fcpe_keeps_alignments_and_reports_f0(core, monkeypatch, capsys):
    """只放了 pydomino + tsqyomi、没有 FCPE（2026-10-10 起模型可以逐个下载）：工作进程照样交出对齐结果，
    音高没测成写成任务级提醒（P6，不静默）；Core 照常采纳对齐，任务记为成功，提醒留在任务摘要里（结果再大也不丢）。"""
    from types import SimpleNamespace

    from ottosmasher.core.scheduler import _Running, _small
    from ottosmasher.jobs import speech as speech_job
    from ottosmasher.jobs import worker
    from ottosmasher.lang.ja import runtime
    from ottosmasher.models import domino, onnx

    a = seg(core, 1.0, 2.0, "あ")
    job = core.speech.submit("segments", [a], False)
    jid = job["id"]
    row = core.conn.execute("SELECT params, device FROM job WHERE id=?", (jid,)).fetchone()
    params = json.loads(row["params"])
    core.jobs.cancel(jid)  # 不让真的工作进程跑起来；下面在本进程里跑工作进程的同一段代码
    assert params["f0"] and not (Path(params["models_dir"]) / "features" / "fcpe.onnx").exists()

    # 对齐这一侧换成假的（不需要真模型）；FCPE 走真实的定位与建会话 → 文件不在
    fake = SimpleNamespace(probe=None)
    real_create = onnx.create_session
    monkeypatch.setattr(runtime, "JaRuntime", lambda *a, **k: SimpleNamespace(session=fake, analyze=lambda text: object()))
    monkeypatch.setattr(onnx, "create_session", lambda model, *a, **k: fake if model == domino.MODEL_ID else real_create(model, *a, **k))
    monkeypatch.setattr(domino, "Aligner", lambda session: SimpleNamespace(session=session))
    phones = lambda it: [{"label": "a", "start": it["target"][0], "end": it["target"][1], "mora": 0, "word": 0}]  # noqa: E731
    monkeypatch.setattr(speech_job, "align_item", lambda it, front, aligner, cache: {"phones": phones(it), "morae": ["ア"], "words": [], "frontend": {}})

    job_dir = core.jobs.jobs_dir / jid
    job_dir.mkdir(parents=True, exist_ok=True)
    capsys.readouterr()
    result = worker._speech_analyze(params, worker.Ctx(job_dir, json.loads(row["device"])))
    events = [json.loads(x) for x in capsys.readouterr().out.splitlines()]
    total = sum(len(e["chunks"]) for e in params["f0"])
    assert (result["ok"], result["failed"], result["f0"]) == (1, 0, [])
    assert result["warnings"] == [{"code": "speech-f0-failed", "args": {"failed": total, "total": total}, "cause": result["f0Errors"][0]["error"]}]
    assert result["f0Errors"][0]["error"]["code"] == "model-file-missing"

    # 交给调度器的收尾（与真的任务进程退出时同一条路）
    for ev in events:
        if ev["type"] == "item":
            core.jobs._item(jid, ev)
    core.jobs._exited(jid, _Running(tree=None, result=result), 0)  # type: ignore[arg-type]
    summary = core.jobs.summary(jid)
    assert summary["status"] == "succeeded" and summary["items"] == {"total": 1, "ok": 1, "failed": 0}
    assert summary["result"]["warnings"] == result["warnings"]
    assert heads(core, unit(core, a))[1] == [("ok", 0)] and heads(core, unit(core, a))[0] is not None  # 对齐已采纳为当前头
    assert core.conn.execute("SELECT COUNT(*) FROM measure_run WHERE kind='f0'").fetchone()[0] == 0
    big = _small({"warnings": result["warnings"], "f0": ["x" * 5000]})
    assert big["truncated"] and big["warnings"] == result["warnings"]


def test_auto_rerun_after_segment_edits_is_a_setting(core):
    a = seg(core, 1.0, 2.0, "あ")
    _run(core, [a], entry="segments")
    submitted = []
    real = core.speech.submit
    core.speech.submit = lambda *args, **kw: (submitted.append(args), real(*args, **kw))[1]
    edit_seg(core, a, text="いえ")
    core.auto.run()
    assert submitted == []  # 默认关
    cur = core.conn.execute("SELECT version FROM setting WHERE key='analysis.auto_rerun_segments'").fetchone()
    core.edits.apply({"ops": [{"entity": "setting", "id": "analysis.auto_rerun_segments", "version": cur[0] if cur else 0, "fields": {"value": True}}]})
    edit_seg(core, a, text="うお")
    core.auto.run()
    assert submitted and submitted[0][0] == "units" and submitted[0][1] == [unit(core, a)]


# ---------------------------------------------------------------- 迁移


def test_migration_0011_moves_sample_owned_analysis_to_text_units(tmp_path: Path):
    conn = connect(tmp_path / "db.sqlite")
    base = bundled_migrations()
    migrate(conn, tmp_path / "bk", base[:10])
    conn.execute("PRAGMA foreign_keys=OFF")
    ts = now_iso()
    x = conn.execute
    for sid, origin, manual in (("s1", dumps({"kind": "subtitle", "annotation": "L1"}), None), ("s2", None, "て"), ("s3", dumps({"kind": "subtitle", "annotation": "L1"}), None)):
        x("INSERT INTO sample(id, asset_id, start, \"end\", name, created_via, origin, align_text_manual, created_at, updated_at) VALUES (?, 'A', 1.0, 2.0, 'n', 'subtitle', ?, ?, ?, ?)",
          (sid, origin, manual, ts, ts))
    res = dumps({"phones": [{"label": "pau", "start": 0.5, "end": 1.1}, {"label": "a", "start": 1.1, "end": 1.9}, {"label": "pau", "start": 1.9, "end": 2.5}]})

    def run(rid, owner, source, manual=0, created=ts, otype="sample"):
        x("INSERT INTO measure_run(id, kind, owner_type, owner_id, asset_id, range_start, range_end, inputs, status, manual, result, created_at)"
          " VALUES (?, 'alignment', ?, ?, 'A', 1.0, 2.0, ?, 'ok', ?, ?, ?)", (rid, otype, owner, dumps({"textSource": source}), manual, res, created))
        x("INSERT OR REPLACE INTO measure_head(owner_type, owner_id, kind, run_id, version) VALUES (?, ?, 'alignment', ?, 3)", (otype, owner, rid))

    run("r1", "s1", "line-auto", created="2026-01-01T00:00:00Z")
    run("r3", "s3", "line-auto", manual=1, created="2025-01-01T00:00:00Z")
    run("r2", "s2", "sample-manual")
    run("r4", "hash", "selection", otype="asset_text")
    migrate(conn, tmp_path / "bk", base[:11])
    rows = dict(conn.execute("SELECT id, owner_type || '|' || owner_id FROM measure_run").fetchall())
    assert rows == {"r1": "asset_text|line:L1@A", "r3": "asset_text|line:L1@A", "r2": "asset_text|typed:A@1.000000-2.000000", "r4": "asset_text|typed:A@1.000000-2.000000"}
    assert dict(conn.execute("SELECT owner_id, run_id FROM measure_head").fetchall())["line:L1@A"] == "r3"


def test_migration_0012_builds_the_text_layer(tmp_path: Path):
    """旧标注 → 段 / 音效提示 / 区段标签；分析 → “段 + 资产”；判定区间补齐；只在有历史时插屏障（外键开着迁移）。"""
    conn = connect(tmp_path / "db.sqlite")
    base = bundled_migrations()
    migrate(conn, tmp_path / "bk", base[:11])
    ts = now_iso()
    x = conn.execute
    x("INSERT INTO source(id, path, work, episode, source_type, created_at, updated_at, duration) VALUES ('S', '/a.mkv', 'w', '1', 't', ?, ?, 100)", (ts, ts))
    x("INSERT INTO sound_asset(id, source_id, origin, stream_ordinal, duration, mapping, created_at) VALUES ('A', 'S', 'stream', 0, 50, '[[0,10],[50,60]]', ?)", (ts,))
    for vid in ("V1", "V0"):
        x("INSERT INTO subtitle_version(id, source_id, content_hash, file_name, imported_at) VALUES (?, 'S', ?, 'a.srt', ?)", (vid, vid, ts))
    x("UPDATE source SET current_subtitle_version_id='V1' WHERE id='S'")
    x("INSERT INTO subtitle_line(id, version_id, line_no, start, \"end\", raw_text) VALUES ('SL1', 'V1', 1, 11, 12, '（京子）あ')")
    x("INSERT INTO subtitle_line(id, version_id, line_no, start, \"end\", raw_text) VALUES ('SL2', 'V1', 2, 13, 14, '（足音）')")

    def ann(aid, kind, a, b, clean, auto, tags, ver="V1", line=None, scope="role", role="vocal", manual=None):
        x('INSERT INTO annotation(id, source_id, kind, scope, scope_role, start, "end", raw_text, clean_text, align_text_auto, align_text_manual, tags,'
          " subtitle_version_id, subtitle_line_id, created_at, updated_at) VALUES (?, 'S', ?, ?, ?, ?, ?, '', ?, ?, ?, ?, ?, ?, ?, ?)",
          (aid, kind, scope, role if scope == "role" else None, a, b, clean, auto, manual, dumps(tags), ver, line, ts, ts))

    ann("L1", "line", 11, 12, "あ", "あ", ["character:京子", "mood:x"], line="SL1")
    ann("L2", "sfx", 13, 14, "足音", None, [], scope="source", line="SL2")
    ann("L3", "song", 15, 16, "うた", "うた", [], manual="うたう")
    ann("OLD", "line", 11, 12, "旧", "旧", [], ver="V0")
    ann("T1", "tag", 20, 21, "门", None, ["effect:door"], scope="source", ver=None)
    x('INSERT INTO sample(id, asset_id, start, "end", name, created_via, origin, align_text_manual, created_at, updated_at)'
      " VALUES ('SM1', 'A', 0.9, 2.1, 'あ', 'subtitle', ?, NULL, ?, ?)", (dumps({"kind": "subtitle", "annotation": "L1"}), ts, ts))
    x('INSERT INTO sample(id, asset_id, start, "end", name, created_via, origin, align_text_manual, created_at, updated_at)'
      " VALUES ('SM2', 'A', 30, 31, 'て', 'manual', NULL, 'てがき', ?, ?)", (ts, ts))
    res = dumps({"phones": [{"label": "a", "start": 1.0, "end": 2.0}]})
    for rid, owner in (("R1", "line:L1@A"), ("R0", "line:OLD@A"), ("R2", "typed:A@30.000000-31.000000")):
        x("INSERT INTO measure_run(id, kind, owner_type, owner_id, asset_id, range_start, range_end, inputs, status, manual, result, created_at, span_start, span_end)"
          " VALUES (?, 'alignment', 'asset_text', ?, 'A', ?, ?, ?, 'ok', 0, ?, ?, 1.0, 2.0)",
          (rid, owner, 30.0 if rid == "R2" else 0.9, 31.0 if rid == "R2" else 2.1, dumps({"text": "てがき" if rid == "R2" else "あ"}), res, ts))
        x("INSERT INTO measure_head(owner_type, owner_id, kind, run_id, version) VALUES ('asset_text', ?, 'alignment', ?, 1)", (owner, rid))
    x("INSERT INTO edit(id, seq, created_at, label_code, label_args) VALUES ('E1', 1, ?, 'subtitle-import', '{}')", (ts,))
    migrate(conn, tmp_path / "bk", base[:12])
    segs = {r[0]: tuple(r[1:]) for r in x('SELECT id, start, "end", text, speakers, origin, edited FROM text_segment')}
    assert segs["L1"] == (11.0, 12.0, "あ", '["京子"]', "subtitle", 0) and segs["L3"] == (15.0, 16.0, "うたう", "[]", "subtitle", 1)
    assert "OLD" not in segs
    typed = [k for k, v in segs.items() if v[2] == "てがき"]
    assert len(typed) == 1 and segs[typed[0]][:2] == (40.0, 41.0) and segs[typed[0]][4:] == ("typed", 1)  # 资产局部 30 秒 = 原片 40 秒
    assert '"raw":"（京子）あ"' in x("SELECT provenance FROM text_segment WHERE id='L1'").fetchone()[0]
    assert [tuple(r) for r in x('SELECT id, text FROM sfx_hint')] == [("L2", "足音")]
    tags = sorted(tuple(r) for r in x("SELECT tags FROM range_tag"))
    assert tags == [('["effect:door"]',), ('["mood:x"]',)]
    runs = {r[0]: tuple(r[1:]) for r in x("SELECT id, owner_id, seg_start, seg_end, seg_text FROM measure_run")}
    assert runs["R1"] == ("seg:L1@A", 11.0, 12.0, "あ") and "R0" not in runs and runs["R2"][0] == f"seg:{typed[0]}@A"
    assert {r[0] for r in x("SELECT owner_id FROM measure_head")} == {"seg:L1@A", f"seg:{typed[0]}@A"}
    sm = {r[0]: tuple(r[1:]) for r in x("SELECT id, created_via, origin, tag_judge_start, tag_judge_end, align_text_manual FROM sample")}
    assert sm["SM1"][:2] == ("segment", '{"kind":"segment","segment":"L1"}') and sm["SM2"][2:] == (40.0, 41.0, None)
    assert x("SELECT label_code FROM edit ORDER BY seq DESC LIMIT 1").fetchone()[0] == "barrier"
    # 新采样没给判定区间 → 触发器按映射补成选区
    x("INSERT INTO sample(id, asset_id, start, \"end\", name, created_via, created_at, updated_at) VALUES ('SM3', 'A', 5, 6, 'x', 'manual', ?, ?)", (ts, ts))
    assert tuple(x("SELECT tag_judge_start, tag_judge_end FROM sample WHERE id='SM3'").fetchone()) == (15.0, 16.0)
    assert x("SELECT name FROM upgrade_pending").fetchone()[0] == "effective-tags"
    # 0013：删掉旧表与旧列；文本层与分析原样留着，外键完整
    migrate(conn, tmp_path / "bk")
    names = {r[0] for r in x("SELECT name FROM sqlite_master WHERE type='table'")}
    assert not names & {"annotation", "annotation_revision", "subtitle_line", "subtitle_version"}
    assert "align_text_manual" not in {r[1] for r in x("PRAGMA table_info(sample)")}
    assert "current_subtitle_version_id" not in {r[1] for r in x("PRAGMA table_info(source)")}
    assert x("SELECT COUNT(*) FROM text_segment").fetchone()[0] == len(segs) and x("SELECT owner_id FROM measure_run WHERE id='R1'").fetchone()[0] == "seg:L1@A"
    assert x("PRAGMA foreign_key_check").fetchall() == []
    x("INSERT INTO sample(id, asset_id, start, \"end\", name, created_via, created_at, updated_at) VALUES ('SM4', 'A', 7, 8, 'y', 'manual', ?, ?)", (ts, ts))
    assert tuple(x("SELECT tag_judge_start, tag_judge_end FROM sample WHERE id='SM4'").fetchone()) == (17.0, 18.0)
