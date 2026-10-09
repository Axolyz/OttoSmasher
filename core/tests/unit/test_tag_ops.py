"""标签与资料的批量操作（规格 07 §7.4–§7.6、16 R8.5、R8.6、R9.1–R9.5；L33：全局改名 / 移除人物覆盖段的说话人）。"""

from __future__ import annotations

import pytest

from conftest import make_source
from ottosmasher.core.edits import EditService
from ottosmasher.core.errors import CoreError
from ottosmasher.core.samples import SampleService
from ottosmasher.core.tag_ops import TagOps
from test_tracks import asset


@pytest.fixture
def env(db):
    edits = EditService(db)
    svc = SampleService(db)
    src = make_source(db, work="Yuru Yuri")
    db.execute("UPDATE source SET duration=100.0 WHERE id=?", (src,))
    va = asset(db, src, origin="separation", stem="vocals", snapshot="v")
    edits.apply({"ops": [{"entity": "asset", "id": va, "version": 1, "fields": {"roles": ["vocal"]}}]})
    edits.apply({"ops": [{"entity": "segment", "op": "create", "fields": {"source_id": src, "start": 10, "end": 12, "text": "あ", "speakers": ["京子"], "origin": "subtitle"}}]})
    edits.apply({"ops": [{"entity": "segment", "op": "create", "fields": {"source_id": src, "start": 20, "end": 22, "text": "い", "speakers": ["京子", "結衣"], "origin": "subtitle"}}]})
    edits.apply({"ops": [{"entity": "range_tag", "op": "create", "fields": {"source_id": src, "scope": "source", "start": 0, "end": 50, "tags": ["好用", "scene:教室"]}}]})
    a = svc.create(va, 10, 12, name="a")["id"]
    b = svc.create(va, 20, 22, name="b")["id"]
    c = svc.create(va, 60, 61, name="c")["id"]
    return edits, svc, TagOps(db, edits), src, (a, b, c)


def tags(db, sid):
    return sorted(r[0] for r in db.execute("SELECT tag FROM sample_effective_tag WHERE sample_id=?", (sid,)))


def test_batch_edit_preview_apply_undo(db, env) -> None:
    edits, _svc, ops, _src, (a, b, c) = env
    plan = ops.batch_edit([a, b, c], {"nature": "speech", "starred": True, "rating": 0, "addTags": ["好用", "尖叫"], "removeTags": ["无"]})
    assert plan["samples"] == 3 and plan["unchanged"] == 0
    assert db.execute("SELECT COUNT(*) FROM sample_tag").fetchone()[0] == 0  # 预览不写库（R9.1）
    edits.apply(plan["batch"])
    assert [r[0] for r in db.execute("SELECT tag FROM sample_tag WHERE sample_id=? ORDER BY rowid", (c,))] == ["好用", "尖叫"]
    # 第二次同样的修改：没有变化的采样不进批次
    again = ops.batch_edit([a, b, c], {"starred": True, "addTags": ["好用"]})
    assert again["unchanged"] == 3 and again["batch"]["ops"] == []
    # 过期的批次不能应用（R9.1）：别处改过版本
    stale = ops.batch_edit([a], {"name": "新名"})
    v = db.execute("SELECT version FROM sample WHERE id=?", (a,)).fetchone()[0]
    edits.apply({"ops": [{"entity": "sample", "id": a, "version": v, "fields": {"note": "x"}}]})
    with pytest.raises(CoreError) as ei:
        edits.apply(stale["batch"])
    assert ei.value.code == "edit-conflict"
    # 撤销最近一次（备注）、再撤销批量编辑：全部恢复（R9.5 快捷编辑与批量都可撤销）
    edits.undo()
    edits.undo()
    assert db.execute("SELECT COUNT(*) FROM sample_tag").fetchone()[0] == 0
    assert db.execute("SELECT COUNT(*) FROM sample WHERE starred=1").fetchone()[0] == 0


def test_of_samples_counts_local_and_inherited_once(db, env) -> None:
    edits, _svc, ops, _src, (a, b, c) = env
    edits.apply(ops.batch_edit([a, c], {"addTags": ["好用"]})["batch"])
    got = {x["tag"]: x for x in ops.of_samples([a, b, c])}
    # 好用：a 本地 + 区段（本地优先只记一次）、b 区段、c 本地 → 本地 2 / 继承 1（R8.6 按采样计）
    assert (got["好用"]["local"], got["好用"]["inherited"]) == (2, 1)
    assert got["好用"]["sources"][0]["kind"] == "rangeTag"
    assert (got["character:京子"]["local"], got["character:京子"]["inherited"]) == (0, 1)
    assert got["character:京子"]["sources"][0]["kind"] == "segment"
    assert got["work:Yuru Yuri"]["sources"][0] == {"kind": "source", "id": got["work:Yuru Yuri"]["sources"][0]["sourceId"], "sourceId": got["work:Yuru Yuri"]["sources"][0]["sourceId"]}


def test_global_rename_covers_local_range_source_and_speakers(db, env) -> None:
    edits, _svc, ops, src, (a, b, c) = env
    edits.apply(ops.batch_edit([c], {"addTags": ["character:京子", "work:Yuru Yuri"]})["batch"])
    plan = ops.global_plan("rename", "character:京子", "character:歳納京子")
    assert plan["report"] == {"samples": 1, "rangeTags": 0, "sources": 0, "segments": 2, "folderSources": 0, "derived": 0}
    assert "character:京子" in tags(db, a)  # 预览不写库
    edits.apply(plan["batch"])
    assert "character:歳納京子" in tags(db, a) and "participants:歳納京子" in tags(db, b) and "character:歳納京子" in tags(db, c)
    assert db.execute("SELECT speaker_edited FROM text_segment WHERE start=10").fetchone()[0] == 1  # 记“说话人改过”
    # 作品：原片属性 + 本地标签一起改（R8.5 例：work:作品 → work:新作品）
    w = ops.global_plan("rename", "work:Yuru Yuri", "work:新作品")
    assert w["report"]["sources"] == 1 and w["report"]["samples"] == 1
    edits.apply(w["batch"])
    assert db.execute("SELECT work FROM source WHERE id=?", (src,)).fetchone()[0] == "新作品"
    assert "work:新作品" in tags(db, a)
    # 撤销一次恢复原样
    edits.undo()
    assert db.execute("SELECT work FROM source WHERE id=?", (src,)).fetchone()[0] == "Yuru Yuri"


def test_global_remove_and_limits(db, env) -> None:
    edits, _svc, ops, _src, (a, b, _c) = env
    plan = ops.global_plan("remove", "好用")
    assert plan["report"]["rangeTags"] == 1
    edits.apply(plan["batch"])
    assert "好用" not in tags(db, a)
    rm = ops.global_plan("remove", "participants:結衣")
    edits.apply(rm["batch"])
    assert [t for t in tags(db, b) if t.startswith(("character", "participants", "speaker"))] == ["character:京子"]  # 只剩一人 → 单人
    st = ops.global_plan("remove", "speaker-status:多人未分段")
    assert st["changes"] == 0
    with pytest.raises(CoreError):
        ops.global_plan("rename", "character:京子", "work:x")  # 人物只能改成人物
    with pytest.raises(CoreError):
        ops.global_plan("add", "x")  # 不允许全局添加
    usage = {u["tag"]: u for u in ops.list_all()}
    assert usage["character:京子"]["segments"] == 2 and usage["scene:教室"]["rangeTags"] == 1
