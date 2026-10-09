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


# R9.4 新建区段标签可预览、应用、撤销（撤销 = 软删除；所有者 2026-10-09：区段标签是独立对象 range_tag）
def test_create_range_tag_preview_apply_undo(db, svc):
    src = make_source(db)
    op = {"entity": "range_tag", "op": "create", "fields": {"source_id": src, "scope": "source", "start": 1.0, "end": 2.5, "tags": ["effect:door"]}}
    pv = svc.preview({"ops": [op]})
    assert pv["changes"][0]["op"] == "create"
    assert db.execute("SELECT COUNT(*) FROM range_tag").fetchone()[0] == 0
    res = svc.apply({"ops": [op]})
    tid = res["changes"][0]["id"]
    r = row(db, "range_tag", tid)
    assert r["deleted"] == 0 and r["tags"] == '["effect:door"]'
    svc.undo()
    assert row(db, "range_tag", tid)["deleted"] == 1


def test_range_must_be_positive(db, svc):
    src = make_source(db)
    with pytest.raises(CoreError) as ei:
        svc.apply({"ops": [{"entity": "range_tag", "op": "create", "fields": {"source_id": src, "scope": "source", "start": 3.0, "end": 2.0}}]})
    assert ei.value.args_["reason"] == "end-not-after-start"
    with pytest.raises(CoreError) as ei:
        svc.apply({"ops": [{"entity": "segment", "op": "create", "fields": {"source_id": src, "start": 3.0, "end": 2.0, "text": "あ", "origin": "typed"}}]})
    assert ei.value.args_["reason"] == "end-not-after-start"


# 段：改文本或边界自动标“改过”（受保护），改说话人只标“说话人改过”；撤销一起恢复
def test_segment_edit_flags_and_undo(db, svc):
    src = make_source(db)
    sid = svc.apply({"ops": [{"entity": "segment", "op": "create", "fields": {
        "source_id": src, "start": 1.0, "end": 2.0, "text": "  こんにちは\nみなさん  ", "origin": "subtitle", "speakers": ["京子", "京子", " 結衣 "]}}]})["changes"][0]["id"]
    r = row(db, "text_segment", sid)
    assert (r["text"], r["speakers"], r["edited"], r["speaker_edited"]) == ("こんにちは\nみなさん", '["京子","結衣"]', 0, 0)
    svc.apply({"ops": [upd("segment", sid, 1, speakers=["京子"])]})
    r = row(db, "text_segment", sid)
    assert (r["edited"], r["speaker_edited"]) == (0, 1)
    svc.apply({"ops": [upd("segment", sid, 2, text="こんばんは")]})
    assert row(db, "text_segment", sid)["edited"] == 1
    svc.undo()
    r = row(db, "text_segment", sid)
    assert (r["text"], r["edited"], r["speaker_edited"]) == ("こんにちは\nみなさん", 0, 1)
    # 段长度上限 120 秒
    with pytest.raises(CoreError) as ei:
        svc.apply({"ops": [upd("segment", sid, 4, end=200.0)]})
    assert ei.value.args_["reason"] in ("too-long", "out-of-bounds")


# 迁移 0012 的屏障：之前的修改（已取消的对象）不再可撤销，撤销不越过它
def test_undo_stops_at_the_barrier(db, svc, sample_id):
    svc.apply({"ops": [upd("sample", sample_id, 1, name="改名")]})
    db.execute("INSERT INTO edit(id, seq, created_at, label_code, label_args) VALUES ('barrier-x', (SELECT MAX(seq) + 1 FROM edit), '', 'barrier', '{}')")
    with pytest.raises(CoreError) as ei:
        svc.undo()
    assert ei.value.code == "undo-nothing-safe"
    # 未知对象（旧的标注）的历史也只是不可撤销，不报错
    db.execute("INSERT INTO edit(id, seq, created_at, label_code, label_args) VALUES ('old', (SELECT MAX(seq) + 1 FROM edit), '', 'x', '{}')")
    db.execute("INSERT INTO edit_change(edit_id, idx, entity, entity_id, op, after, version_after) VALUES ('old', 0, 'annotation', 'a', 'create', '{}', 1)")
    assert svc.peek_undo() is None


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
    eff = {(r[0], r[1], r[2]) for r in db.execute("SELECT tag, facet, provenance FROM sample_effective_tag WHERE sample_id=?", (sample_id,))}
    # 本地标签 + 原片的 work:/type:（阶段 3.5 起有效标签完整求值）
    assert {e for e in eff if e[2] == "local"} == {("pitch:G#5", "pitch", "local"), ("好用", "other", "local")}
    assert {e[0] for e in eff if e[2] == "source"} == {"work:Yuru Yuri", "type:动画"}
    svc.undo()
    assert db.execute("SELECT COUNT(*) FROM sample_tag WHERE sample_id=?", (sample_id,)).fetchone()[0] == 0
    assert db.execute("SELECT COUNT(*) FROM sample_effective_tag WHERE sample_id=? AND provenance='local'", (sample_id,)).fetchone()[0] == 0


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


# 原片推断规则（P10，所有者 2026-10-07）：有序正则列表也走编辑通道，保存时校验
def test_infer_rules_setting(db, svc):
    from ottosmasher.core import settings as settings_mod
    from ottosmasher.domain.naming import default_rules

    assert settings_mod.values(db)["source.infer_rules"] == default_rules()
    with pytest.raises(CoreError) as ei:
        svc.apply({"ops": [upd("setting", "source.infer_rules", 0, value=[r"(?P<work>a)", r"(?P<work>"])]})
    assert ei.value.code == "edit-invalid"
    assert (ei.value.args_["reason"], ei.value.args_["rule"]) == ("syntax", 2)
    mine = [r"^(?P<work>.+?)_(?P<episode>\d+)$"]
    svc.apply({"ops": [upd("setting", "source.infer_rules", 0, value=mine)]})
    assert settings_mod.values(db)["source.infer_rules"] == mine
    svc.undo()
    assert settings_mod.values(db)["source.infer_rules"] == default_rules()


# 「作品与输入设置」：分析音轨必须存在；字幕文件必须是存在的 .srt/.ass，可清除
def test_source_input_settings(db, svc, tmp_path):
    sid = make_source(db)
    db.execute(
        "INSERT INTO source_stream(source_id, kind, ordinal, container_index) VALUES (?, 'audio', 0, 1), (?, 'audio', 1, 2)",
        (sid, sid),
    )
    svc.apply({"ops": [upd("source", sid, 1, default_audio_stream=1)]})
    assert row(db, "source", sid)["default_audio_stream"] == 1
    srt = tmp_path / "字幕 [x].srt"
    srt.write_text("1\n", encoding="utf-8")
    txt = tmp_path / "a.txt"
    txt.write_text("x", encoding="utf-8")
    for fields, reason in [
        ({"default_audio_stream": 5}, "no-such-stream"),
        ({"default_audio_stream": None}, "no-such-stream"),
        ({"subtitle_path": str(tmp_path / "gone.srt")}, "file-missing"),
        ({"subtitle_path": str(txt)}, "not-subtitle"),
    ]:
        with pytest.raises(CoreError) as ei:
            svc.apply({"ops": [upd("source", sid, 2, **fields)]})
        assert ei.value.args_["reason"] == reason
    svc.apply({"ops": [upd("source", sid, 2, subtitle_path=str(srt))]})
    assert row(db, "source", sid)["subtitle_path"] == str(srt)
    svc.apply({"ops": [upd("source", sid, 3, subtitle_path=None)]})
    assert row(db, "source", sid)["subtitle_path"] is None
