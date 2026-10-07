"""统一编辑通道：规格 16 R9.1–R9.5。"""

import sqlite3

import pytest

from conftest import make_asset, make_sample, make_source
from ottosmasher.core.edits import EditService
from ottosmasher.core.errors import CoreError


@pytest.fixture
def svc(db: sqlite3.Connection) -> EditService:
    return EditService(db)


@pytest.fixture
def sample_id(db: sqlite3.Connection) -> str:
    return make_sample(db, make_asset(db, make_source(db)))


def row(db, table, id_):
    return db.execute(f"SELECT * FROM {table} WHERE id=?", (id_,)).fetchone()


def upd(entity, id_, version, **fields):
    return {"entity": entity, "id": id_, "version": version, "op": "update", "fields": fields}


# R9.1 预览不写库；过期版本不能应用；撤销恢复原值
def test_preview_does_not_write(db, svc, sample_id):
    out = svc.preview({"ops": [upd("sample", sample_id, 1, name="新名字")]})
    assert out["changes"][0]["diffs"] == [{"field": "name", "before": "やったー", "after": "新名字"}]
    assert row(db, "sample", sample_id)["name"] == "やったー"
    assert db.execute("SELECT COUNT(*) FROM edit").fetchone()[0] == 0


def test_stale_version_cannot_apply(db, svc, sample_id):
    svc.apply({"ops": [upd("sample", sample_id, 1, name="一")]})
    with pytest.raises(CoreError) as ei:
        svc.apply({"ops": [upd("sample", sample_id, 1, name="二")]})
    assert ei.value.code == "edit-conflict"
    assert ei.value.args_ == {"index": 0, "entity": "sample", "id": sample_id, "expected": 1, "actual": 2}
    assert row(db, "sample", sample_id)["name"] == "一"


def test_undo_restores_previous_value(db, svc, sample_id):
    svc.apply({"label": {"code": "rename", "args": {}}, "ops": [upd("sample", sample_id, 1, name="一", note="备注")]})
    assert svc.peek_undo()["label"]["code"] == "rename"
    res = svc.undo()
    r = row(db, "sample", sample_id)
    assert (r["name"], r["note"]) == ("やったー", "")
    assert res["label"]["code"] == "undo"
    # 撤销不能再被撤销（没有重做）
    assert svc.peek_undo() is None
    with pytest.raises(CoreError) as ei:
        svc.undo()
    assert ei.value.code == "undo-nothing-safe"


# R9.2 一批里第 2 个对象无效 → 整批不写，错误指出第几个对象
def test_batch_is_atomic_and_reports_index(db, svc, sample_id):
    other = make_sample(db, make_asset(db, make_source(db)), name="其他")
    with pytest.raises(CoreError) as ei:
        svc.apply({"ops": [upd("sample", sample_id, 1, name="改了"), upd("sample", other, 1, rating=9)]})
    assert ei.value.code == "edit-invalid"
    assert ei.value.args_["index"] == 1 and ei.value.args_["field"] == "rating"
    assert row(db, "sample", sample_id)["name"] == "やったー"
    assert db.execute("SELECT COUNT(*) FROM edit").fetchone()[0] == 0


def test_unknown_field_and_missing_object(db, svc, sample_id):
    with pytest.raises(CoreError) as ei:
        svc.preview({"ops": [upd("sample", sample_id, 1, bogus=1)]})
    assert ei.value.code == "edit-unknown-field"
    with pytest.raises(CoreError) as ei:
        svc.preview({"ops": [upd("sample", "nope", 1, name="x")]})
    assert ei.value.code == "edit-not-found"


# R9.3 别处后来改过的对象不能被撤销覆盖
def test_undo_skips_edit_whose_objects_changed_later(db, svc, sample_id):
    other = make_sample(db, make_asset(db, make_source(db)), name="其他")
    svc.apply({"label": {"code": "first", "args": {}}, "ops": [upd("sample", sample_id, 1, name="A")]})
    svc.apply({"label": {"code": "second", "args": {}}, "ops": [upd("sample", other, 1, name="B")]})
    # 第二次修改之后，other 又被“别处”改掉
    db.execute("UPDATE sample SET name='外部改动', version=version+1 WHERE id=?", (other,))
    # 最近的一次（second）不安全，跳过；找到 first
    assert svc.peek_undo()["label"]["code"] == "first"
    svc.undo()
    assert row(db, "sample", sample_id)["name"] == "やったー"
    assert row(db, "sample", other)["name"] == "外部改动"
    with pytest.raises(CoreError) as ei:
        svc.undo()
    assert ei.value.code == "undo-nothing-safe"


# R9.4 新建区段标注可预览、应用、撤销（撤销 = 软删除）
def test_create_annotation_preview_apply_undo(db, svc):
    src = make_source(db)
    op = {"entity": "annotation", "op": "create", "fields": {"source_id": src, "kind": "tag", "scope": "source", "start": 1.0, "end": 2.5, "tags": ["character:京子"]}}
    pv = svc.preview({"ops": [op]})
    assert pv["changes"][0]["op"] == "create"
    assert db.execute("SELECT COUNT(*) FROM annotation").fetchone()[0] == 0
    res = svc.apply({"ops": [op]})
    ann = res["changes"][0]["id"]
    r = row(db, "annotation", ann)
    assert r["deleted"] == 0 and r["tags"] == '["character:京子"]'
    svc.undo()
    r = row(db, "annotation", ann)
    assert r["deleted"] == 1
    # 每次编辑留版本
    assert db.execute("SELECT COUNT(*) FROM annotation_revision WHERE annotation_id=?", (ann,)).fetchone()[0] == 2


def test_annotation_range_must_be_positive(db, svc):
    src = make_source(db)
    with pytest.raises(CoreError) as ei:
        svc.apply({"ops": [{"entity": "annotation", "op": "create", "fields": {"source_id": src, "kind": "tag", "scope": "source", "start": 3.0, "end": 2.0}}]})
    assert ei.value.args_["reason"] == "end-not-after-start"


# R9.5 快捷编辑（改名、备注、评分、星标、性质、本地标签）也能被撤销
@pytest.mark.parametrize(
    "field,value,col,expect_before",
    [
        ("name", "改名", "name", "やったー"),
        ("note", "一条备注", "note", ""),
        ("rating", 4, "rating", None),
        ("starred", True, "starred", 0),
        ("nature", "pitched", "nature", "unclassified"),
    ],
)
def test_quick_edits_are_undoable(db, svc, sample_id, field, value, col, expect_before):
    svc.apply({"label": {"code": "quick", "args": {}}, "ops": [upd("sample", sample_id, 1, **{field: value})]})
    svc.undo()
    assert row(db, "sample", sample_id)[col] == expect_before


def test_local_tags_are_undoable_and_indexed(db, svc, sample_id):
    svc.apply({"ops": [upd("sample", sample_id, 1, local_tags=["好用", "pitch:G#5", " 好用 "])]})
    tags = [r[0] for r in db.execute("SELECT tag FROM sample_tag WHERE sample_id=? ORDER BY tag", (sample_id,))]
    assert tags == ["pitch:G#5", "好用"]
    eff = {(r[0], r[1]) for r in db.execute("SELECT tag, facet FROM sample_effective_tag WHERE sample_id=?", (sample_id,))}
    assert eff == {("pitch:G#5", "pitch"), ("好用", "other")}
    svc.undo()
    assert db.execute("SELECT COUNT(*) FROM sample_tag WHERE sample_id=?", (sample_id,)).fetchone()[0] == 0
    assert db.execute("SELECT COUNT(*) FROM sample_effective_tag WHERE sample_id=?", (sample_id,)).fetchone()[0] == 0


def test_settings_go_through_edit_channel(db, svc):
    # 没存过 = 默认值、版本 0
    with pytest.raises(CoreError) as ei:
        svc.apply({"ops": [upd("setting", "jobs.concurrency_light", 0, value=0)]})
    assert ei.value.code == "edit-invalid" and ei.value.args_["reason"] == "out-of-range"
    svc.apply({"ops": [upd("setting", "jobs.concurrency_light", 0, value=4)]})
    assert db.execute("SELECT value, version FROM setting WHERE key='jobs.concurrency_light'").fetchone()[:] == ("4", 1)
    svc.apply({"ops": [upd("setting", "jobs.concurrency_light", 1, value=3)]})
    svc.undo()
    assert db.execute("SELECT value FROM setting WHERE key='jobs.concurrency_light'").fetchone()[0] == "4"
    with pytest.raises(CoreError) as ei:
        svc.preview({"ops": [upd("setting", "no.such.key", 0, value=1)]})
    assert ei.value.code == "edit-not-found"


def test_noop_edit_records_nothing(db, svc, sample_id):
    res = svc.apply({"ops": [upd("sample", sample_id, 1, name="やったー")]})
    assert res["edit_id"] is None
    assert db.execute("SELECT COUNT(*) FROM edit").fetchone()[0] == 0


def test_change_set_is_reported(db, sample_id):
    seen = []
    svc = EditService(db, on_change=lambda cs: seen.append(cs.to_wire()))
    svc.apply({"ops": [upd("sample", sample_id, 1, starred=True)]})
    assert seen == [{"sample": [sample_id]}]
