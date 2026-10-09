"""有效标签：规格 04 §4.2.9、16 R5.2–R5.4、R8.6–R8.8；所有者 2026-10-09：区段标签是独立对象，说话人是文本层的段的属性，按判定区间继承。"""

import pytest
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from conftest import make_source
from ottosmasher.core import effective_tags as eff
from ottosmasher.core.clock import new_id, now_iso
from ottosmasher.core.edits import EditService, dumps
from ottosmasher.core.samples import SampleService
from test_tracks import asset


@pytest.fixture
def env(db):
    sid = make_source(db, work="Yuru Yuri")
    db.execute("UPDATE source SET duration=100.0 WHERE id=?", (sid,))
    return sid, EditService(db), SampleService(db)


def ann(edits, sid, start, end, tags, *, scope="role", role="vocal", asset_id=None):
    """区段标签（用户显式画的）。"""
    fields = {"source_id": sid, "scope": scope, "start": start, "end": end, "tags": tags}
    if scope == "role":
        fields["scope_role"] = role
    if scope == "asset":
        fields["scope_asset_id"] = asset_id
    r = edits.apply({"ops": [{"entity": "range_tag", "op": "create", "fields": fields}]})
    return r["changes"][0]["id"]


def seg(edits, sid, start, end, speakers):
    """文本层的一段（说话人是它的属性）。"""
    r = edits.apply({"ops": [{"entity": "segment", "op": "create", "fields": {"source_id": sid, "start": start, "end": end, "text": "あ", "speakers": speakers, "origin": "subtitle"}}]})
    return r["changes"][0]["id"]


def tags(db, sample_id, prov=None):
    q = "SELECT tag FROM sample_effective_tag WHERE sample_id=?" + (" AND provenance=?" if prov else "") + " ORDER BY tag"
    return [r[0] for r in db.execute(q, (sample_id, prov) if prov else (sample_id,))]


def test_role_scope_positive_overlap_and_role_change(db, env):
    sid, edits, samples = env
    vocal = asset(db, sid, origin="separation", stem="vocals", snapshot="v")
    music = asset(db, sid, origin="separation", stem="instrument", snapshot="m")
    ann(edits, sid, 0.4, 0.6, ["character:京子"])
    on_vocal = samples.create(vocal, 0.5, 0.55, name="a")["id"]
    touching = samples.create(vocal, 0.6, 0.7, name="b")["id"]
    on_music = samples.create(music, 0.5, 0.55, name="c")["id"]
    # R5.3：资产没有该角色 → 不继承；端点相接不算
    assert tags(db, on_vocal, "segment") == []
    edits.apply({"ops": [{"entity": "asset", "id": vocal, "version": 1, "fields": {"roles": ["vocal"]}}]})
    assert tags(db, on_vocal, "segment") == ["character:京子"]
    assert tags(db, touching, "segment") == []
    # R5.4：说话人不泄漏到音乐轨
    assert tags(db, on_music, "segment") == []


def test_source_scope_asset_scope_and_live_source_tags(db, env):
    sid, edits, samples = env
    a = asset(db, sid, snapshot="a")
    b = asset(db, sid, snapshot="b", ordinal=1)
    ann(edits, sid, 10, 20, ["effect:door"], scope="source")
    ann(edits, sid, 1, 2, ["only:a"], scope="asset", asset_id=a)
    sa = samples.create(a, 15, 16, name="x")["id"]
    sb = samples.create(b, 1.5, 1.8, name="y")["id"]
    sa2 = samples.create(a, 1.5, 1.8, name="z")["id"]
    assert tags(db, sa) == ["effect:door", "type:动画", "work:Yuru Yuri"]
    assert "only:a" not in tags(db, sb) and "only:a" in tags(db, sa2)
    # R8.7：原片作品实时继承
    v = db.execute("SELECT version FROM source WHERE id=?", (sid,)).fetchone()[0]
    edits.apply({"ops": [{"entity": "source", "id": sid, "version": v, "fields": {"work": "新作品"}}]})
    assert "work:新作品" in tags(db, sa) and "work:Yuru Yuri" not in tags(db, sa)


def test_local_wins_and_counts_once(db, env):
    sid, edits, samples = env
    a = asset(db, sid, snapshot="a")
    ann(edits, sid, 0, 50, ["mood:happy"], scope="source")
    s = samples.create(a, 1, 2, name="x")["id"]
    edits.apply({"ops": [{"entity": "sample", "id": s, "version": 1, "fields": {"local_tags": ["mood:happy"]}}]})
    rows = db.execute("SELECT provenance FROM sample_effective_tag WHERE sample_id=? AND tag='mood:happy'", (s,)).fetchall()
    assert [r[0] for r in rows] == ["local"]


def test_speakers_from_segments_deleted_and_undo(db, env):
    sid, edits, samples = env
    a = asset(db, sid, snapshot="a", roles=["vocal"])
    t = seg(edits, sid, 1, 2, ["京子"])
    s = samples.create(a, 1.2, 1.5, name="x")["id"]
    assert tags(db, s, "segment") == ["character:京子"]
    v = db.execute("SELECT version FROM text_segment WHERE id=?", (t,)).fetchone()[0]
    edits.apply({"ops": [{"entity": "segment", "id": t, "version": v, "fields": {"deleted": True}}]})
    assert tags(db, s, "segment") == []
    edits.undo()
    assert tags(db, s, "segment") == ["character:京子"]


def test_judge_interval_decides_inheritance(db, env):
    """判定区间（从段建的 = 段区间）：扩展部分碰到的邻句说话人不继承（S1.6）；判定区间可见可改。"""
    sid, edits, samples = env
    a = asset(db, sid, snapshot="a", roles=["vocal"])
    seg(edits, sid, 1.0, 2.0, ["京子"])
    seg(edits, sid, 2.05, 3.0, ["結衣"])
    s = samples.create(a, 0.9, 2.1, name="x")["id"]  # 选区 ±0.1，碰到結衣
    assert tags(db, s, "segment") == ["character:京子", "character:結衣"]
    edits.apply({"ops": [{"entity": "sample", "id": s, "version": 1, "fields": {"judge": [1.0, 2.0]}}]})
    assert tags(db, s, "segment") == ["character:京子"]


# ---------------------------------------------------------------- R8.8：增量 = 完整重算

OPS = st.lists(
    st.tuples(
        st.sampled_from(["ann", "del_ann", "move_ann", "seg", "seg_speak", "judge", "roles", "work", "local", "sample"]),
        st.integers(0, 3),
        st.floats(0, 9),
        st.floats(0.05, 3),
    ),
    min_size=1,
    max_size=25,
)


@settings(max_examples=40, deadline=None, suppress_health_check=[HealthCheck.function_scoped_fixture])
@given(ops=OPS)
def test_incremental_equals_full_rebuild(db, ops):
    sid = make_source(db)
    db.execute("UPDATE source SET duration=100.0 WHERE id=?", (sid,))
    edits, samples = EditService(db), SampleService(db)
    assets = [asset(db, sid, snapshot=f"s{i}", ordinal=i) for i in range(2)]
    smps = [samples.create(assets[i % 2], i, i + 1.5, name=f"s{i}")["id"] for i in range(4)]
    anns: list[str] = []
    segs: list[str] = []
    for kind, k, x, w in ops:
        if kind == "ann":
            scope = ["source", "role", "asset"][k % 3]
            fields = {"source_id": sid, "scope": scope, "start": x, "end": x + w, "tags": [f"t:{k}", "character:京子" if k % 2 else "x:y"]}
            if scope == "role":
                fields["scope_role"] = ["vocal", "sfx"][k % 2]
            if scope == "asset":
                fields["scope_asset_id"] = assets[k % 2]
            anns.append(edits.apply({"ops": [{"entity": "range_tag", "op": "create", "fields": fields}]})["changes"][0]["id"])
        elif kind in ("del_ann", "move_ann") and anns:
            a_id, ver = db.execute("SELECT id, version FROM range_tag WHERE id=?", (anns[k % len(anns)],)).fetchone()
            f = {"deleted": True} if kind == "del_ann" else {"start": x, "end": x + w}
            edits.apply({"ops": [{"entity": "range_tag", "id": a_id, "version": ver, "fields": f}]})
        elif kind == "seg":
            segs.append(seg(edits, sid, x, x + w, [["京子"], ["結衣"], ["京子", "結衣"], []][k]))
        elif kind == "seg_speak" and segs:
            t_id, ver = db.execute("SELECT id, version FROM text_segment WHERE id=?", (segs[k % len(segs)],)).fetchone()
            edits.apply({"ops": [{"entity": "segment", "id": t_id, "version": ver, "fields": {"speakers": [f"P{k}"], "start": x, "end": x + w}}]})
        elif kind == "judge":
            s = smps[k % len(smps)]
            st_, en_, ver = db.execute('SELECT start, "end", version FROM sample WHERE id=?', (s,)).fetchone()
            edits.apply({"ops": [{"entity": "sample", "id": s, "version": ver, "fields": {"judge": [st_, st_ + (en_ - st_) * (k + 1) / 4]}}]})
        elif kind == "roles":
            a = assets[k % 2]
            ver = db.execute("SELECT version FROM sound_asset WHERE id=?", (a,)).fetchone()[0]
            edits.apply({"ops": [{"entity": "asset", "id": a, "version": ver, "fields": {"roles": [["vocal"], ["sfx"], [], ["vocal", "sfx"]][k]}}]})
        elif kind == "work":
            ver = db.execute("SELECT version FROM source WHERE id=?", (sid,)).fetchone()[0]
            edits.apply({"ops": [{"entity": "source", "id": sid, "version": ver, "fields": {"work": f"W{k}"}}]})
        elif kind == "local":
            s = smps[k]
            ver = db.execute("SELECT version FROM sample WHERE id=?", (s,)).fetchone()[0]
            edits.apply({"ops": [{"entity": "sample", "id": s, "version": ver, "fields": {"local_tags": [f"t:{k}"]}}]})
        elif kind == "sample":
            smps.append(samples.create(assets[k % 2], x, x + w, name="n")["id"])
        if k == 3:
            try:
                edits.undo()
            except Exception:
                pass
        q = "SELECT sample_id, tag, facet, provenance, COALESCE(provenance_ref, '') FROM sample_effective_tag"
        snapshot = sorted(tuple(r) for r in db.execute(q))
        eff.rebuild_all(db)
        assert snapshot == sorted(tuple(r) for r in db.execute(q))
    _ = dumps
