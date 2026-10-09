"""语音分析的 Core 侧（规格 08 §8.2.1、§8.4、§8.7、§8.8、16 S1.7、R11.5–R11.8）。

所有者 2026-10-08【基线变更，细化 D41】：分析只挂在“声音资产 + 文本单元”（字幕的一行 / 手输台词）上，不属于任何采样；
采样按两条规则读取覆盖它的句（有自己文本的只读自己那一句；没有的读范围内的句，只读到一部分的标 ◐，两句冲突报错）。
"""

from __future__ import annotations

import json
import sqlite3
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


def ann(c, start, end, auto="あ", manual=None, name=None):
    aid = new_id()
    ts = now_iso()
    c.conn.execute(
        'INSERT INTO annotation(id, source_id, kind, scope, scope_role, start, "end", raw_text, clean_text, align_text_auto, align_text_manual, tags, created_at, updated_at)'
        " VALUES (?, ?, 'line', 'role', 'vocal', ?, ?, ?, ?, ?, ?, '[]', ?, ?)",
        (aid, c.sid, start, end, auto, name or auto, auto, manual, ts, ts),
    )
    return aid


def sample(c, start, end, *, nature="speech", annotation=None, manual=None, parent=None, name="s"):
    sid = new_id()
    ts = now_iso()
    origin = dumps({"kind": "subtitle", "annotation": annotation}) if annotation else None
    c.conn.execute(
        'INSERT INTO sample(id, asset_id, start, "end", name, nature, created_via, origin, align_text_manual, parent_sample_id, created_at, updated_at)'
        " VALUES (?, ?, ?, ?, ?, ?, 'subtitle', ?, ?, ?, ?, ?)",
        (sid, c.aid, start, end, name, nature, origin, manual, parent, ts, ts),
    )
    return sid


def row(c, sid):
    return c.conn.execute(f"SELECT {c.speech._SAMPLE_COLS} FROM sample WHERE id=?", (sid,)).fetchone()


def line(c, a):
    return units.line_id(a, c.aid)


def _adopt(core, job, *, status="ok", mutate=None, phones=None):
    """不真的跑任务：直接写逐条结果文件并调用采纳函数（模拟任务成功结束）。默认每句一个音素 a 覆盖整个目标。"""
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


def _fake_run(core, ids, *, entry="samples", rerun=False, **kw):
    return _adopt(core, core.speech.submit(entry, ids, rerun), **kw)


def heads(core, unit):
    h = core.speech._head_row(unit)
    runs = core.conn.execute("SELECT status, manual FROM measure_run WHERE owner_id=? ORDER BY rowid", (unit,)).fetchall()
    return (h["run_id"] if h else None, [tuple(r) for r in runs])


def test_own_text_and_reading_rules(core):
    a = ann(core, 1.0, 2.0, auto="じどう")
    s1 = sample(core, 0.9, 2.1, annotation=a)
    t = core.speech.text_of(row(core, s1))
    assert (t["text"], t["source"], t["equalsSubtitle"]) == ("じどう", "line-auto", True)
    assert core.speech.own_unit(row(core, s1))["unitId"] == line(core, a)
    core.conn.execute("UPDATE annotation SET align_text_manual='ぎょう' WHERE id=?", (a,))
    assert core.speech.text_of(row(core, s1))["source"] == "line-manual"
    # 手输过台词的采样：自己的手输单元（采样选区），优先于字幕行
    core.conn.execute("UPDATE sample SET align_text_manual='しゅどう' WHERE id=?", (s1,))
    t = core.speech.text_of(row(core, s1))
    assert (t["text"], t["source"], t["equalsSubtitle"]) == ("しゅどう", "sample-manual", False)
    assert core.speech.own_unit(row(core, s1))["unitId"] == units.typed_id(core.aid, 0.9, 2.1)
    core.conn.execute("UPDATE sample SET align_text_manual=NULL WHERE id=?", (s1,))
    # 没有自己文本的截取：读范围内的句（这一行），不再是“截取范围与原台词不同”
    child = sample(core, 1.2, 1.5, parent=s1)
    assert core.speech.text_of(row(core, child)) == {"text": None, "reason": "no-text"}
    v = core.speech.sample_view(child)
    assert (v["own"], v["text"], v["textSource"], v["reason"]) == (False, "ぎょう", "units", None)
    assert [u["unitId"] for u in v["units"]] == [line(core, a)] and v["units"][0]["partial"] is True and v["head"] is None
    # 范围里没有句
    v = core.speech.sample_view(sample(core, 5.0, 6.0))
    assert (v["text"], v["reason"], v["units"]) == (None, "no-text", [])


def test_line_target_is_the_subtitle_range_plus_pads_and_window_truncation(core):
    a = ann(core, 1.0, 2.0)
    it = core.speech.plan("samples", [sample(core, 0.9, 2.1, annotation=a)], False)["run"][0]
    assert it["owner"] == line(core, a) and it["target"] == [pytest.approx(0.9), pytest.approx(2.1)]
    s1 = sample(core, 0.3, 1.0, manual="あ")
    it = core.speech.plan("samples", [s1], False)["run"][0]
    assert it["window"][0] == pytest.approx(0.0) and it["truncated"] == [True, False]
    assert it["actual"][0] == pytest.approx(0.3) and it["actual"][1] == pytest.approx(0.65)
    assert it["requested"] == [0.65, 0.65] and it["frames"] == [0, round(1.65 * 48000)]
    it2 = core.speech.plan("samples", [sample(core, 19.5, 20.0, manual="あ")], False)["run"][0]
    assert it2["window"][1] == pytest.approx(20.0) and it2["truncated"] == [False, True]


def test_source_entry_analyzes_lines_without_samples(core):
    op = new_id()
    core.conn.execute("INSERT INTO oped(id, source_id, kind, start, \"end\", origin, created_at, updated_at) VALUES (?, ?, 'OP', 5.0, 8.0, 'manual', ?, ?)", (op, core.sid, now_iso(), now_iso()))
    keep = ann(core, 1.0, 2.0, auto="あ")
    ann(core, 6.0, 7.0, auto="い")  # 在 OP 里
    ann(core, 8.0, 9.0, auto="う")  # 端点相接不算交叠 → 在范围内
    ann(core, 10.0, 11.0, auto="")  # 没有对齐文本：不在范围里
    pv = core.speech.preview("source", [core.sid], False)
    assert (pv["run"], pv["fresh"], pv["blocked"]) == (2, 0, 0)
    assert pv["mixBound"] == 2  # 没有默认人声轨：原混音上
    # 原片上语音采样自己的那一句也算（手输台词）；同一行的字幕采样不重复；单音性质的不算
    sample(core, 12.0, 13.0, manual="え")
    sample(core, 14.0, 15.0, manual="お", nature="pitched")
    sample(core, 0.9, 2.1, annotation=keep)
    assert core.speech.preview("source", [core.sid], False)["run"] == 3
    # 采样入口：显式选的不按性质/OP/ED 过滤；范围里没有句的进 K
    nt = sample(core, 16.0, 17.0, name="ない")
    sub = sample(core, 0.9, 2.1, annotation=keep, name="字幕")
    pv = core.speech.preview("samples", [sub, nt], False)
    assert (pv["run"], pv["blocked"]) == (1, 1) and pv["blockedList"] == [{"id": nt, "name": "ない", "reason": "no-text"}]
    with pytest.raises(CoreError) as e:
        core.speech.submit("samples", [nt], False)
    assert e.value.code == "speech-nothing-to-do"
    # 分析完：不建采样也有原片页的音素层
    _fake_run(core, [core.sid], entry="source")
    layer = core.speech.for_asset(core.aid, 0.0, 20.0)
    assert {x["unitId"] for x in layer} >= {line(core, keep)} and all(x["kind"] in ("line", "typed") for x in layer)


def test_reuse_and_adoption_rules(core):
    a = ann(core, 1.0, 2.0, auto="あ")
    s1 = sample(core, 0.9, 2.1, annotation=a)
    u = line(core, a)
    _fake_run(core, [s1])
    head1, runs = heads(core, u)
    assert head1 and runs == [("ok", 0)]
    # 再发起：输入完全相同 → 跳过
    pv = core.speech.preview("samples", [s1], False)
    assert (pv["run"], pv["fresh"], pv["freshAll"]) == (0, 1, 1)
    assert core.speech.preview("samples", [s1], True)["run"] == 1
    # 改了这一行的对齐文本 → 重跑
    core.conn.execute("UPDATE annotation SET align_text_manual='い' WHERE id=?", (a,))
    assert core.speech.preview("samples", [s1], False)["run"] == 1
    # 失败结果只进历史，旧的成功结果不消失
    _fake_run(core, [s1], status="failed")
    head2, runs = heads(core, u)
    assert head2 == head1 and runs[-1] == ("failed", 0)
    # 任务期间输入又变了 → 只进历史
    _fake_run(core, [s1], mutate=lambda: core.conn.execute("UPDATE annotation SET align_text_manual='う' WHERE id=?", (a,)))
    head3, runs = heads(core, u)
    assert head3 == head1 and runs[-1] == ("ok", 0)
    # 正常重跑 → 新的当前头
    _fake_run(core, [s1])
    head4, _ = heads(core, u)
    assert head4 != head1
    # 改了字幕采样扩展量 → 目标变了 → 重跑
    core.conn.execute("INSERT INTO setting(key, value, version, updated_at) VALUES ('subtitle.pad_before', '0.2', 1, ?)", (now_iso(),))
    assert core.speech.preview("samples", [s1], False)["run"] == 1
    # 当前头是人工版本 → 新结果只进历史（S5.3）
    core.conn.execute("UPDATE measure_run SET manual=1 WHERE id=?", (head4,))
    _fake_run(core, [s1], rerun=True)
    head5, runs = heads(core, u)
    assert head5 == head4 and runs[-1] == ("ok", 0)


def test_results_table_counts_and_rerun_by_unit(core):
    a, b = ann(core, 1.0, 2.0, auto="あ", name="一"), ann(core, 3.0, 4.0, auto="い", name="二")
    s1 = sample(core, 0.9, 2.1, annotation=a)
    s2 = sample(core, 2.9, 4.1, annotation=b)
    _fake_run(core, [s1])
    jid = _fake_run(core, [s1, s2], status="failed")
    rows = core.speech.results(jid)
    assert [(r["name"], r["status"], r["unitId"]) for r in rows] == [("二", "failed", line(core, b)), ("一", "skipped", line(core, a))]
    assert rows[0]["error"]["code"] == "align-unsupported" and rows[0]["sampleId"] is None
    # 结果表里勾选失败项再发起：按句
    assert core.speech.preview("units", [line(core, b)], False)["run"] == 1
    assert core.speech.analyzed_counts()[core.sid] == {"speech": 2, "analyzed": 1}
    prep = core.dispatch({"id": 1, "m": "sources.prep", "p": {"id": core.sid}})
    assert prep["ok"] and prep["r"]["speech"] == {"ok": False, "speech": 2, "analyzed": 1}


def test_one_line_shared_by_samples_cuts_and_merges(core):
    a, b = ann(core, 1.0, 2.0, auto="あ", name="一"), ann(core, 3.0, 4.0, auto="い", name="二")
    _fake_run(core, [core.sid], entry="source")  # 原片页直接分析台词行，没有采样
    s1 = sample(core, 0.9, 2.1, annotation=a)
    s2 = sample(core, 0.95, 2.05, annotation=a)  # 同一句的另一个字幕采样（扩展量不同）
    cut = sample(core, 1.2, 1.5)  # 截一个音节
    merged = sample(core, 0.9, 4.1)  # 跨两行的合并截取
    for s in (s1, s2):
        v = core.speech.sample_view(s)
        assert v["own"] and [u["unitId"] for u in v["units"]] == [line(core, a)] and v["head"]["units"] == [line(core, a)]
    assert [core.samples.get(s)["analysis"] for s in (s1, s2, cut, merged)] == ["ok", "ok", "partial", "ok"]
    vc = core.speech.sample_view(cut)
    assert vc["head"]["partial"] and [(p["start"], p["end"]) for p in vc["head"]["result"]["phones"]] == [(1.2, 1.5)]
    core.strict_api = True  # 返回值与声明的类型一致（合成的头、只读到一部分的头）
    for sid in (s1, cut, merged):
        assert core.dispatch({"id": 1, "m": "speech.sample", "p": {"id": sid}})["ok"]
        assert core.dispatch({"id": 2, "m": "rhythm.view", "p": {"id": sid}})["ok"]
    assert core.dispatch({"id": 3, "m": "speech.forAsset", "p": {"assetId": core.aid, "start": 0.0, "end": 20.0}})["ok"]
    vm = core.speech.sample_view(merged)
    assert vm["head"]["units"] == [line(core, a), line(core, b)] and not vm["head"]["partial"]
    ph = vm["head"]["result"]["phones"]
    assert [(p["label"], p["start"], p["end"], p.get("mora")) for p in ph] == [("a", 0.9, 2.1, 0), ("pau", 2.1, 2.9, None), ("a", 2.9, 4.1, 1)]
    assert vm["head"]["result"]["morae"] == ["ア", "ア"] and vm["text"] == "あ い"
    # 修音素时间修的是“这句”：所有读这句的采样同时生效，变更事件带上它们
    h = core.speech._head_row(line(core, a))
    core.changes.clear()
    r = core.speech.save_manual(line(core, a), h["version"], [{"label": "a", "start": 1.0, "end": 2.0}], None)
    changed = core.changes[-1].entities["measure"]
    assert {line(core, a), s1, s2, cut, merged} <= set(changed)
    for s in (s1, s2, cut, merged):
        assert core.speech.sample_view(s)["head"]["manual"] is True
    assert core.samples.get(s1)["analysis"] == "manual"
    # 删采样不删分析（P9）；重建后照样读到，人工修正还在
    core.samples.delete([s1])
    assert core.speech._head_row(line(core, a))["run_id"] == r["runId"]
    again = sample(core, 0.9, 2.1, annotation=a)
    assert core.speech.sample_view(again)["head"]["runId"] == r["runId"]


def test_conflicting_lines_make_rhythm_unavailable(core):
    a = ann(core, 1.0, 2.0, auto="あ", name="一")
    _fake_run(core, [core.sid], entry="source")
    # 一段手输台词的选区与这一行的音素在时间上冲突
    _adopt(core, core.speech.submit_range(core.aid, 1.5, 2.5, "う"))
    s = sample(core, 0.9, 2.6)
    v = core.speech.sample_view(s)
    assert v["head"] is None and v["conflict"]["units"] == [line(core, a), units.typed_id(core.aid, 1.5, 2.5)]
    core.strict_api = True
    assert core.dispatch({"id": 1, "m": "speech.sample", "p": {"id": s}})["ok"]
    rv = core.rhythm.view(s)
    assert rv["status"] == "none" and rv["reason"]["code"] == "rhythm-units-conflict"
    # 有自己文本的采样只读自己那一句，不受冲突影响
    assert core.speech.sample_view(sample(core, 0.9, 2.1, annotation=a))["conflict"] is None


def test_asset_layer_and_no_side_effects(core):
    a = ann(core, 1.0, 2.0, auto="あ")
    s1 = sample(core, 0.9, 2.1, annotation=a)
    v = core.speech.sample_view(s1)
    assert v["head"] is None and v["text"] == "あ" and v["units"][0]["runs"] == []
    _fake_run(core, [s1])
    v = core.speech.sample_view(s1)
    assert v["head"]["status"] == "ok" and v["head"]["result"]["phones"][0]["label"] == "a" and len(v["units"][0]["runs"]) == 1
    layer = core.speech.for_asset(core.aid, 0.0, 20.0)
    assert [x["unitId"] for x in layer] == [line(core, a)] and layer[0]["phones"][0]["start"] == pytest.approx(0.9) and layer[0]["name"] == "あ"
    assert core.speech.for_asset(core.aid, 5.0, 20.0) == []
    # 文件指纹不同（记录里的快照对不上）→ 不显示（R11.10），没有自己文本的截取也不读
    rid = v["head"]["runId"]
    inp = json.loads(core.conn.execute("SELECT inputs FROM measure_run WHERE id=?", (rid,)).fetchone()[0])
    inp["audio"]["snapshot"]["size"] = 1
    core.conn.execute("UPDATE measure_run SET inputs=? WHERE id=?", (json.dumps(inp), rid))
    assert core.speech.for_asset(core.aid, 0.0, 20.0) == []
    assert core.speech.sample_view(sample(core, 1.2, 1.5))["head"] is None
    # 读取没有副作用
    n = core.conn.total_changes
    core.speech.sample_view(s1)
    core.speech.for_asset(core.aid, 0.0, 20.0)
    assert core.conn.total_changes == n


def _fake_ok(core, sid, phones):
    """直接登记一个成功的自动结果并设为当前头（模拟一次分析）。"""
    _fake_run(core, [sid], rerun=True)
    unit = core.speech.own_unit(row(core, sid))["unitId"]
    head = core.speech._head_row(unit)
    res = {"phones": phones, "morae": ["ア", "ア"], "words": [], "frontend": {}}
    core.conn.execute("UPDATE measure_run SET result=? WHERE id=?", (json.dumps(res), head["run_id"]))
    return unit, core.speech._head_row(unit)


def test_manual_edit_rules_r11_6(core):
    s1 = sample(core, 0.0, 1.0, manual="ああ")
    unit, head = _fake_ok(core, s1, [{"label": "a", "start": 0.1, "end": 0.4, "mora": 0, "word": 0}, {"label": "a", "start": 0.4, "end": 0.8, "mora": 1, "word": 0, "eff": [0.45, 0.7]}])
    v = head["version"]
    with pytest.raises(CoreError) as e:
        core.speech.save_manual(unit, v, None, "0.1\t0.5\ta\n0.5\t0.8\ti")
    assert (e.value.code, e.value.args_["reason"], e.value.args_["line"]) == ("speech-edit-invalid", "label", 2)
    with pytest.raises(CoreError) as e:
        core.speech.save_manual(unit, v, None, "0.1\t0.5\ta")
    assert e.value.args_["reason"] == "count"
    with pytest.raises(CoreError) as e:
        core.speech.save_manual(unit, v, None, "0.1\t0.6\ta\n0.5\t0.8\ta")
    assert e.value.args_["reason"] == "order"
    # .1 .5 a / .5 .8 a → 新人工版本、mora [0, 1]、有效范围不收缩、强度按新时间重算
    r = core.speech.save_manual(unit, v, None, ".1\t.5\ta\n.5\t.8\ta")
    view = core.speech.sample_view(s1)
    ph = view["head"]["result"]["phones"]
    assert view["head"]["manual"] and view["head"]["version"] == r["version"] == v + 1
    assert [(p["start"], p["end"], p["mora"]) for p in ph] == [(0.1, 0.5, 0), (0.5, 0.8, 1)]
    assert ph[1]["eff"] == [0.5, 0.8] and "strength" in ph[0] and ph[0]["strength"] == pytest.approx(1.0, abs=0.05)
    assert tuple(core.conn.execute("SELECT span_start, span_end FROM measure_run WHERE id=?", (r["runId"],)).fetchone()) == (0.1, 0.8)
    with pytest.raises(CoreError) as e:
        core.speech.save_manual(unit, v, None, ".1\t.5\ta\n.5\t.8\ta")
    assert e.value.code == "speech-edit-conflict"
    # 之后的自动结果被拒（只进历史）
    _fake_run(core, [s1], rerun=True)
    assert core.speech.sample_view(s1)["head"]["runId"] == r["runId"]
    # 切换版本（R11.7）：选历史的模型结果 → 当前头更新
    model = next(x for x in core.speech.sample_view(s1)["units"][0]["runs"] if not x["manual"] and x["status"] == "ok")
    sw = core.speech.switch_head(unit, model["id"], r["version"])
    assert core.speech.sample_view(s1)["head"]["runId"] == model["id"] and sw["version"] == r["version"] + 1


def test_range_analysis_is_a_typed_unit(core):
    job = core.speech.submit_range(core.aid, 5.0, 6.0, "い")
    params = json.loads(core.conn.execute("SELECT params FROM job WHERE id=?", (job["id"],)).fetchone()[0])
    it = params["items"][0]
    assert it["ownerType"] == "asset_text" and it["owner"] == units.typed_id(core.aid, 5.0, 6.0) and it["unitKind"] == "typed"
    assert core.conn.execute("SELECT target FROM job_item WHERE job_id=?", (job["id"],)).fetchone()[0] == it["owner"]
    _adopt(core, job)
    # 之后在同一选区建的采样（没有自己的文本）读到它；同一选区再输入文字仍是同一句
    s = sample(core, 5.0, 6.0)
    assert core.speech.sample_view(s)["head"]["units"] == [it["owner"]]
    core.conn.execute("UPDATE sample SET align_text_manual='い' WHERE id=?", (s,))
    assert core.speech.own_unit(row(core, s))["unitId"] == it["owner"]
    assert core.speech.preview("samples", [s], False)["fresh"] == 1


def test_migration_moves_sample_owned_analysis_to_text_units(tmp_path: Path):
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
    run("r3", "s3", "line-auto", manual=1, created="2025-01-01T00:00:00Z")  # 同一句的人工版本优先
    run("r2", "s2", "sample-manual")
    run("r4", "hash", "selection", otype="asset_text")
    migrate(conn, tmp_path / "bk")
    rows = dict(conn.execute("SELECT id, owner_type || '|' || owner_id FROM measure_run").fetchall())
    assert rows == {"r1": "asset_text|line:L1@A", "r3": "asset_text|line:L1@A", "r2": "asset_text|typed:A@1.000000-2.000000", "r4": "asset_text|typed:A@1.000000-2.000000"}
    hs = dict(conn.execute("SELECT owner_id, run_id FROM measure_head").fetchall())
    assert hs["line:L1@A"] == "r3" and conn.execute("SELECT COUNT(*) FROM measure_head WHERE owner_type='sample'").fetchone()[0] == 0
    assert tuple(conn.execute("SELECT span_start, span_end FROM measure_run WHERE id='r1'").fetchone()) == (1.1, 1.9)
    assert isinstance(conn, sqlite3.Connection)
