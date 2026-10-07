"""有效标签：规格 04 §4.2.9、16 R5.2–R5.4、R8.6–R8.8。"""

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


def ann(edits, sid, start, end, tags, *, scope="role", role="vocal", asset_id=None, kind="tag"):
    fields = {"source_id": sid, "kind": kind, "scope": scope, "start": start, "end": end, "tags": tags}
    if scope == "role":
        fields["scope_role"] = role
    if scope == "asset":
        fields["scope_asset_id"] = asset_id
    r = edits.apply({"ops": [{"entity": "annotation", "op": "create", "fields": fields}]})
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


def test_only_current_subtitle_version_and_deleted_annotations(db, env):
    sid, edits, samples = env
    a = asset(db, sid, snapshot="a", roles=["vocal"])
    v_old, v_new = new_id(), new_id()
    for v in (v_old, v_new):
        db.execute(
            "INSERT INTO subtitle_version(id, source_id, content_hash, file_name, imported_at) VALUES (?, ?, ?, 'x.srt', ?)", (v, sid, v, now_iso())
        )
    edits.apply({"ops": [{"entity": "annotation", "op": "create", "fields": {"source_id": sid, "kind": "line", "scope": "role", "scope_role": "vocal", "start": 1, "end": 2, "tags": ["character:旧"], "subtitle_version_id": v_old}}]})
    edits.apply({"ops": [{"entity": "annotation", "op": "create", "fields": {"source_id": sid, "kind": "line", "scope": "role", "scope_role": "vocal", "start": 1, "end": 2, "tags": ["character:新"], "subtitle_version_id": v_new}}]})
    s = samples.create(a, 1.2, 1.5, name="x")["id"]
    src_v = lambda: db.execute("SELECT version FROM source WHERE id=?", (sid,)).fetchone()[0]  # noqa: E731
    edits.apply({"ops": [{"entity": "source", "id": sid, "version": src_v(), "fields": {"current_subtitle_version_id": v_old}}]})
    assert tags(db, s, "segment") == ["character:旧"]
    edits.apply({"ops": [{"entity": "source", "id": sid, "version": src_v(), "fields": {"current_subtitle_version_id": v_new}}]})
    assert tags(db, s, "segment") == ["character:新"]
    # 删除标注（软删除）→ 不再继承；撤销 → 回来
    aid = db.execute("SELECT id, version FROM annotation WHERE subtitle_version_id=?", (v_new,)).fetchone()
    edits.apply({"ops": [{"entity": "annotation", "id": aid[0], "version": aid[1], "fields": {"deleted": True}}]})
    assert tags(db, s, "segment") == []
    edits.undo()
    assert tags(db, s, "segment") == ["character:新"]


def test_subtitle_sample_uses_tag_judge_interval(db, env):
    """字幕采样用标签判定区间（原字幕时间）：扩展部分碰到的邻句说话人不继承（S1.6、R4.8）。"""
    sid, edits, samples = env
    a = asset(db, sid, snapshot="a", roles=["vocal"])
    ann(edits, sid, 1.0, 2.0, ["character:京子"])
    ann(edits, sid, 2.05, 3.0, ["character:結衣"])
    s = samples.create(a, 0.9, 2.1, name="x")["id"]  # 选区 ±0.1，碰到結衣
    db.execute("UPDATE sample SET tag_judge_start=1.0, tag_judge_end=2.0 WHERE id=?", (s,))
    eff.refresh(db, [s])
    assert tags(db, s, "segment") == ["character:京子"]


# ---------------------------------------------------------------- R8.8：增量 = 完整重算

OPS = st.lists(
    st.tuples(
        st.sampled_from(["ann", "del_ann", "move_ann", "roles", "work", "local", "sample"]),
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
    for kind, k, x, w in ops:
        if kind == "ann":
            scope = ["source", "role", "asset"][k % 3]
            fields = {"source_id": sid, "kind": "tag", "scope": scope, "start": x, "end": x + w, "tags": [f"t:{k}", "character:京子" if k % 2 else "x:y"]}
            if scope == "role":
                fields["scope_role"] = ["vocal", "sfx"][k % 2]
            if scope == "asset":
                fields["scope_asset_id"] = assets[k % 2]
            anns.append(edits.apply({"ops": [{"entity": "annotation", "op": "create", "fields": fields}]})["changes"][0]["id"])
        elif kind in ("del_ann", "move_ann") and anns:
            a_id, ver = db.execute("SELECT id, version FROM annotation WHERE id=?", (anns[k % len(anns)],)).fetchone()
            f = {"deleted": True} if kind == "del_ann" else {"start": x, "end": x + w}
            edits.apply({"ops": [{"entity": "annotation", "id": a_id, "version": ver, "fields": f}]})
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
