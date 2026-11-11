"""建采样 = 一个动作（所有者 2026-10-09【基线变更】）：来源是选区、段、音效提示、分离声部、整段；单条与批量同一套规则、产物完全相同。
（16 R4.8–R4.10、S1.6、R7.1、R2.6；C2：分离声部保存的性质按角色）"""

import pytest

from conftest import make_source
from ottosmasher.core.edits import EditService, loads
from ottosmasher.core.errors import CoreError
from ottosmasher.core.sample_plan import SamplePlanner
from ottosmasher.core.samples import SampleService
from ottosmasher.core.subtitle_import import SubtitleImporter
from test_subtitle_import import srt
from test_tracks import asset

LINES = [
    (0.05, 0.3, "（殴る音）"),
    (1.0, 2.0, "（京子(きょうこ)たち）アッカリ～ン"),
    (2.05, 3.0, "（結衣）なに？\nほんと？"),
    (5.0, 6.0, "（足音）"),
    (10.0, 12.0, "♪～"),
]


@pytest.fixture
def env(db, tmp_path):
    sid = make_source(db, work="Yuru Yuri")
    db.execute("UPDATE source SET duration=100.0 WHERE id=?", (sid,))
    p = tmp_path / "a.srt"
    p.write_text(srt(*LINES), encoding="utf-8")
    db.execute("UPDATE source SET subtitle_path=? WHERE id=?", (str(p), sid))
    edits = EditService(db)
    imp = SubtitleImporter(db, edits)
    imp.import_(sid, imp.preview(sid)["token"], {"oped": False})
    return sid, edits, SamplePlanner(db, SampleService(db))


def set_default(db, edits, sid, role, aid):
    v = db.execute("SELECT version FROM source WHERE id=?", (sid,)).fetchone()[0]
    edits.apply({"ops": [{"entity": "source", "id": sid, "version": v, "fields": {f"default_{role}": aid}}]})


def sample_rows(db):
    return [dict(r) for r in db.execute(
        'SELECT asset_id, start, "end", name, nature, created_via, origin, text_snapshot, tag_judge_start, tag_judge_end FROM sample ORDER BY created_at, rowid')]


def test_local_tags_are_saved_with_plan_and_invalid_tags_roll_back(db, env):
    sid, edits, plan = env
    vocal = asset(db, sid, origin="separation", stem="vocals", snapshot="v", roles=["vocal"])
    set_default(db, edits, sid, "vocal", vocal)
    src = {"kind": "segments", "sourceId": sid}
    preview = plan.plan(src)
    first, second = [it["key"] for it in preview["items"] if it["status"] == "pending"][:2]
    with pytest.raises(CoreError) as error:
        plan.create(src, preview["token"], [first, second], {
            first: {"localTags": ["project:test"]}, second: {"localTags": ["x" * 201]},
        })
    assert error.value.code == "sample-invalid" and error.value.args_["reason"] == "tag-too-long"
    assert not sample_rows(db)
    created = plan.create(src, preview["token"], [first], {
        first: {"localTags": [" project:test ", "", "project:test"]},
    })["ids"][0]
    tags = SampleService(db).get(created)["tags"]
    assert [t["tag"] for t in tags if t["provenance"] == "local"] == ["project:test"]
    assert db.execute("SELECT 1 FROM sample_effective_tag WHERE sample_id=? AND tag=?", (created, "project:test")).fetchone()


def test_missing_default_track_is_refused_not_mixed(db, env):
    sid, _, plan = env
    src = {"kind": "segments", "sourceId": sid}
    pv = plan.plan(src)
    assert pv["missingDefault"] == "vocal" and pv["track"] is None
    with pytest.raises(CoreError) as e:
        plan.create(src, pv["token"], [pv["items"][0]["key"]])
    assert (e.value.code, e.value.args_["role"]) == ("default-track-missing", "vocal")
    assert db.execute("SELECT COUNT(*) FROM sample").fetchone()[0] == 0


def test_segment_samples_pads_judge_name_and_single_equals_batch(db, env):
    sid, edits, plan = env
    vocal = asset(db, sid, origin="separation", stem="vocals", snapshot="v", roles=["vocal"])
    set_default(db, edits, sid, "vocal", vocal)
    batch = {"kind": "segments", "sourceId": sid}
    pv = plan.plan(batch)
    items = {it["name"]: it for it in pv["items"]}
    a = items["アッカリ～ン"]
    assert (a["assetId"], a["start"], a["end"]) == (vocal, pytest.approx(0.9), pytest.approx(2.1))  # 段 ± 0.1（R4.8）
    assert (a["judgeStart"], a["judgeEnd"], a["nature"], a["createdVia"], a["status"]) == (1.0, 2.0, "speech", "segment", "pending")
    assert "なに？ ほんと？" in items and items["♪～"]["status"] == "pending"
    # 逐句建（右键这一段）与批量建：同一套规则、产物完全相同
    one = {"kind": "segments", "sourceId": sid, "ids": [a["key"]]}
    pv1 = plan.plan(one)
    assert pv1["items"] == [a]
    plan.create(one, pv1["token"], [a["key"]])
    plan.create(batch, pv["token"], [a["key"]])  # 每次显式创建都新建（R7.1）
    r1, r2 = sample_rows(db)
    assert r1 == r2 and r1["name"] == "アッカリ～ン" and r1["tag_judge_start"] == 1.0 and r1["tag_judge_end"] == 2.0
    assert loads(r1["origin"]) == {"kind": "segment", "segment": a["key"]} and loads(r1["text_snapshot"])["speakers"] == ["京子たち"]
    # 在当前查看的轨（原混音）上建：同样的规则，判定区间不变
    mix = asset(db, sid, snapshot="m")
    pvm = plan.plan({"kind": "segments", "sourceId": sid, "track": "current", "assetId": mix, "ids": [a["key"]]})
    assert pvm["items"][0]["assetId"] == mix and pvm["items"][0]["judgeStart"] == 1.0
    # 段改了 → 计划过期
    seg = db.execute("SELECT id, version FROM text_segment WHERE id=?", (a["key"],)).fetchone()
    edits.apply({"ops": [{"entity": "segment", "id": seg[0], "version": seg[1], "fields": {"text": "かえた"}}]})
    with pytest.raises(CoreError) as e:
        plan.create(batch, pv["token"], [a["key"]])
    assert e.value.code == "sample-plan-stale"


def test_hint_samples_current_track_and_default_sfx(db, env):
    sid, edits, plan = env
    mix = asset(db, sid, snapshot="m")
    src = {"kind": "hints", "sourceId": sid, "track": "current", "assetId": mix}
    pv = plan.plan(src)
    names = [it["name"] for it in pv["items"]]
    assert names == ["殴る音", "足音"] and all(it["nature"] == "unpitched" and it["createdVia"] == "hint" for it in pv["items"])
    assert pv["items"][0]["start"] == pytest.approx(0.0)  # 扩展后裁到 0
    # 批量默认在默认音效轨上（缺 → 就地指定）
    assert plan.plan({"kind": "hints", "sourceId": sid})["missingDefault"] == "sfx"
    sfx = asset(db, sid, origin="separation", stem="effect", snapshot="e", roles=["sfx"])
    set_default(db, edits, sid, "sfx", sfx)
    pv2 = plan.plan({"kind": "hints", "sourceId": sid})
    assert {it["assetId"] for it in pv2["items"]} == {sfx}


def test_statuses_oped_out_of_track_and_range_filter(db, env):
    sid, edits, plan = env
    part = asset(db, sid, origin="separation", stem="vocals", snapshot="p", duration=2.5, mapping=[[0, 0], [2.5, 2.5]], roles=["vocal"])
    db.execute("INSERT INTO oped(id, source_id, kind, start, \"end\", origin, created_at, updated_at) VALUES ('o', ?, 'OP', 9, 13, 'manual', '', '')", (sid,))
    cur = {"kind": "segments", "sourceId": sid, "track": "current", "assetId": part}
    st = {it["name"]: it["status"] for it in plan.plan(cur)["items"]}
    assert st == {"アッカリ～ン": "pending", "なに？ ほんと？": "pending", "♪～": "oped"}
    clipped = next(it for it in plan.plan(cur)["items"] if it["name"].startswith("なに"))
    assert clipped["end"] == pytest.approx(2.5) and clipped["judgeEnd"] == pytest.approx(2.5)  # 裁到音轨覆盖范围，判定区间也在范围内
    db.execute("UPDATE sound_asset SET duration=1.5, mapping='[[0,0],[1.5,1.5]]' WHERE id=?", (part,))
    st = {it["name"]: it["status"] for it in plan.plan(cur)["items"]}
    assert st["なに？ ほんと？"] == "out-of-track"
    assert [it["name"] for it in plan.plan(cur | {"start": 1.5, "end": 2.5})["items"]] == ["アッカリ～ン", "なに？ ほんと？"]


def test_selection_hit_and_stem_follow_roles(db, env):
    sid, _, plan = env
    vocal = asset(db, sid, origin="separation", stem="vocals", snapshot="v", roles=["vocal"])
    pv = plan.plan({"kind": "selection", "assetId": vocal, "start": 1.2, "end": 1.6})
    it = pv["items"][0]
    assert (it["name"], it["nature"], it["createdVia"], it["judgeStart"], it["judgeEnd"]) == ("アッカリ～ン", "speech", "manual", 1.2, 1.6)  # A23
    hit = plan.plan({"kind": "selection", "assetId": vocal, "start": 1.2, "end": 1.6, "via": "hit"})
    assert hit["items"][0]["createdVia"] == "hit"
    r = plan.create({"kind": "selection", "assetId": vocal, "start": 1.2, "end": 1.6}, pv["token"], [it["key"]], overrides={it["key"]: {"name": "か"}})
    assert db.execute("SELECT name FROM sample WHERE id=?", (r["ids"][0],)).fetchone()[0] == "か"
    other = asset(db, sid, origin="separation", stem="other", snapshot="o", roles=[])
    st = plan.plan({"kind": "stem", "assetId": other})["items"][0]
    assert st["nature"] == "unclassified" and st["start"] == 0.0 and "other" in st["name"]  # C2：按角色预填
    assert plan.plan({"kind": "stem", "assetId": vocal})["items"][0]["nature"] == "speech"


def _second_source(db, tmp_path, lines):
    sid = make_source(db, work="Yuru Yuri", path=str(tmp_path / "ep2.mkv"))
    db.execute("UPDATE source SET duration=100.0 WHERE id=?", (sid,))
    p = tmp_path / "b.srt"
    p.write_text(srt(*lines), encoding="utf-8")
    db.execute("UPDATE source SET subtitle_path=? WHERE id=?", (str(p), sid))
    edits = EditService(db)
    imp = SubtitleImporter(db, edits)
    imp.import_(sid, imp.preview(sid)["token"], {"oped": False})
    return sid


def test_many_sources_use_their_own_default_tracks(db, tmp_path, env):
    """多个原素材一起建（所有者 2026-11-03）：各用各的默认轨；规则与单个相同，整批原子创建。"""
    a, edits, planner = env
    b = _second_source(db, tmp_path, [(1.0, 2.0, "（結衣）二話"), (3.0, 4.0, "（結衣）もう一つ")])
    va, vb = asset(db, a, origin="separation", stem="vocals", snapshot="va", roles=["vocal"]), asset(db, b, origin="separation", stem="vocals", snapshot="vb", roles=["vocal"])
    set_default(db, edits, a, "vocal", va)
    set_default(db, edits, b, "vocal", vb)
    src = {"kind": "segments", "sourceIds": [a, b]}
    pv = planner.plan(src)
    assert pv["missingDefault"] is None and pv["missingSources"] == [] and pv["track"] is None
    assert {it["sourceId"] for it in pv["items"]} == {a, b}
    assert {it["assetId"] for it in pv["items"]} == {va, vb}
    assert all(it["sourceName"] for it in pv["items"])
    # 和单个原素材的计划是同一套规则
    one = {it["key"]: it for it in planner.plan({"kind": "segments", "sourceId": b})["items"]}
    for it in pv["items"]:
        if it["sourceId"] == b:
            assert (it["start"], it["end"], it["name"], it["status"]) == (one[it["key"]]["start"], one[it["key"]]["end"], one[it["key"]]["name"], one[it["key"]]["status"])
    keys = [it["key"] for it in pv["items"] if it["status"] == "pending"]
    r = planner.create(src, pv["token"], keys)
    assert r["created"] == len(keys)
    assert {x["asset_id"] for x in sample_rows(db)} == {va, vb}


def test_many_sources_without_default_track_are_reported_not_mixed(db, tmp_path, env):
    """缺默认轨的不回退混音（R4.8）：不列出来，记在 missingSources；有轨的照常建。没有内容的不算缺。"""
    a, edits, planner = env
    b = _second_source(db, tmp_path, [(1.0, 2.0, "（結衣）二話")])
    empty = make_source(db, work="Yuru Yuri", path=str(tmp_path / "ep3.mkv"))
    va = asset(db, a, origin="separation", stem="vocals", snapshot="va", roles=["vocal"])
    set_default(db, edits, a, "vocal", va)
    pv = planner.plan({"kind": "segments", "sourceIds": [a, b, empty]})
    assert pv["missingSources"] == [b]
    assert {it["sourceId"] for it in pv["items"]} == {a}
    assert pv["missingDefault"] is None
