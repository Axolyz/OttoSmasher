"""字幕标记导入：规格 06 §6.1、04 §4.2.2；16 R4.1–R4.3、R4.7、S11.3（合成字幕）。"""

import pytest

from conftest import make_source
from ottosmasher.core.clock import new_id, now_iso
from ottosmasher.core.edits import EditService, dumps
from ottosmasher.core.errors import CoreError
from ottosmasher.core.subtitle_import import SPEAKER_STATUS_MULTI, SubtitleImporter


def srt(*cues):
    out = []
    for i, (a, b, text) in enumerate(cues, start=1):
        def ts(x):
            sign = "-" if x < 0 else ""
            x = abs(x)
            return f"{sign}{int(x // 3600):02d}:{int(x % 3600 // 60):02d}:{int(x % 60):02d},{round(x % 1 * 1000):03d}"

        out.append(f"{i}\n{ts(a)} --> {ts(b)}\n{text}\n")
    return "\n".join(out)


LINES = [
    (1.0, 2.0, "（京子）こんにちは"),
    (3.0, 4.0, "（足音）"),
    (5.0, 6.0, "（京子）（結衣）ありがとう"),
    (8.0, 10.0, "♪～"),
    (11.0, 11.0, "ゼロ長"),
    (95.0, 120.0, "はみ出し"),
    (12.0, 13.0, "普通の台詞"),
]


@pytest.fixture
def env(db, tmp_path):
    sid = make_source(db)
    db.execute("UPDATE source SET duration=100.0 WHERE id=?", (sid,))
    p = tmp_path / "a.srt"
    p.write_text(srt(*LINES), encoding="utf-8")
    db.execute("UPDATE source SET subtitle_path=? WHERE id=?", (str(p), sid))
    changes = []
    edits = EditService(db, on_change=changes.append)
    return sid, p, SubtitleImporter(db, edits, on_change=changes.append), edits, changes


def annotations(db, sid, live=True):
    q = 'SELECT kind, start, "end", raw_text, clean_text, align_text_auto, tags, scope, scope_role, subtitle_version_id FROM annotation WHERE source_id=?'
    if live:
        q += " AND deleted=0"
    return [dict(r) for r in db.execute(q + " ORDER BY start", (sid,))]


def test_preview_statuses_and_default_import(db, env):
    sid, _, imp, _, changes = env
    pv = imp.preview(sid)
    st = {ln["no"]: (ln["status"], ln.get("reason")) for ln in pv["lines"]}
    assert st == {
        1: ("importable", None),
        2: ("importable", None),
        3: ("importable", None),
        4: ("importable", None),
        5: ("invalid", "empty"),
        6: ("invalid", "beyond-end"),
        7: ("importable", None),
    }
    assert pv["counts"] == {"importable": 5, "oped": 0, "invalid": 2, "registered": 0}
    assert pv["versionState"] == "new"
    r = imp.import_(sid, pv["token"])
    assert (r["imported"], r["newVersion"], r["switched"]) == (5, True, True)
    assert [x["reason"] for x in r["invalid"]] == ["empty", "beyond-end"]
    # R4.1：导入只登记标注，不建采样
    assert db.execute("SELECT COUNT(*) FROM sample").fetchone()[0] == 0
    a = annotations(db, sid)
    assert [(x["kind"], x["clean_text"]) for x in a] == [
        ("line", "こんにちは"),
        ("sfx", "足音"),
        ("line", "ありがとう"),
        ("line", "♪～"),
        ("line", "普通の台詞"),
    ]
    # 说话人：一人 character:，多人 participants: + speaker-status:多人未分段，作用域“人声”角色；音效行作用域原片、无标签
    assert (a[0]["tags"], a[0]["scope"], a[0]["scope_role"]) == (dumps(["character:京子"]), "role", "vocal")
    assert set(eval(a[2]["tags"])) == {"participants:京子", "participants:結衣", SPEAKER_STATUS_MULTI}
    assert (a[1]["tags"], a[1]["scope"], a[1]["align_text_auto"]) == ("[]", "source", None)
    vid = db.execute("SELECT current_subtitle_version_id FROM source WHERE id=?", (sid,)).fetchone()[0]
    assert {x["subtitle_version_id"] for x in a} == {vid}
    # 版本快照包含全部行（含无效行）
    assert db.execute("SELECT COUNT(*) FROM subtitle_line WHERE version_id=?", (vid,)).fetchone()[0] == 7
    assert "annotation" in changes[-1].entities


def test_partial_batches_same_version_only_add_missing(db, env):
    sid, _, imp, _, _ = env
    pv = imp.preview(sid)
    imp.import_(sid, pv["token"], [1, 2])
    pv2 = imp.preview(sid)
    assert pv2["versionState"] == "current"
    assert [ln["status"] for ln in pv2["lines"][:3]] == ["registered", "registered", "importable"]
    r = imp.import_(sid, pv2["token"])
    assert (r["imported"], r["newVersion"], r["switched"], r["skipped"]["registered"]) == (3, False, False, 2)
    assert len(annotations(db, sid)) == 5
    # 同一内容再导入一次：什么都不新增
    pv3 = imp.preview(sid)
    assert pv3["counts"]["importable"] == 0
    assert imp.import_(sid, pv3["token"])["imported"] == 0
    assert len(annotations(db, sid)) == 5


def test_invalid_or_registered_lines_cannot_be_chosen(db, env):
    sid, _, imp, _, _ = env
    pv = imp.preview(sid)
    with pytest.raises(CoreError) as e:
        imp.import_(sid, pv["token"], [1, 5])
    assert (e.value.code, e.value.args_["line"], e.value.args_["status"]) == ("subtitle-line-not-importable", 5, "invalid")
    # 原子：整批不登记
    assert annotations(db, sid) == []
    assert db.execute("SELECT COUNT(*) FROM subtitle_version").fetchone()[0] == 0


def test_preview_goes_stale(db, env):
    sid, p, imp, edits, _ = env
    pv = imp.preview(sid)
    # 字幕内容变了
    p.write_text(srt(*LINES, (14.0, 15.0, "追加")), encoding="utf-8")
    with pytest.raises(CoreError) as e:
        imp.import_(sid, pv["token"])
    assert e.value.code == "subtitle-preview-stale"
    # OP/ED 变了
    pv = imp.preview(sid)
    ts = now_iso()
    db.execute(
        "INSERT INTO oped(id, source_id, kind, start, \"end\", origin, created_at, updated_at) VALUES (?, ?, 'OP', 7.5, 9.0, 'manual', ?, ?)",
        (new_id(), sid, ts, ts),
    )
    with pytest.raises(CoreError):
        imp.import_(sid, pv["token"])
    # 规则变了
    pv = imp.preview(sid)
    edits.apply({"ops": [{"entity": "setting", "id": "subtitle.speaker_split", "version": 0, "fields": {"value": "[･]"}}]})
    with pytest.raises(CoreError):
        imp.import_(sid, pv["token"])
    # 音轨（原片资料）变了
    pv = imp.preview(sid)
    db.execute("UPDATE source SET version=version+1 WHERE id=?", (sid,))
    with pytest.raises(CoreError):
        imp.import_(sid, pv["token"])


def test_oped_lines_are_flagged_but_importable(db, env):
    sid, _, imp, _, _ = env
    ts = now_iso()
    db.execute(
        "INSERT INTO oped(id, source_id, kind, start, \"end\", origin, created_at, updated_at) VALUES (?, ?, 'OP', 7.5, 9.0, 'manual', ?, ?)",
        (new_id(), sid, ts, ts),
    )
    # 端点相接不算交叠：6.0 结束的那行不受 7.5 开始的 OP 影响
    pv = imp.preview(sid)
    line = pv["lines"][3]
    assert (line["status"], line["oped"], line["opedPartial"]) == ("oped", "OP", True)  # 8–10 跨出 9.0
    assert pv["lines"][2]["status"] == "importable"
    assert pv["counts"]["oped"] == 1
    assert imp.import_(sid, pv["token"])["imported"] == 5  # OP/ED 内的行也导入（取样与批量分析时再跳过）


def test_new_content_becomes_current_and_old_file_switches_back(db, env, tmp_path):
    sid, p, imp, _, _ = env
    imp.import_(sid, imp.preview(sid)["token"])
    v1 = db.execute("SELECT current_subtitle_version_id FROM source WHERE id=?", (sid,)).fetchone()[0]
    # 整体晚 0.404 秒的另一版本 → 新版本成为当前
    q = tmp_path / "late.srt"
    q.write_text(srt(*[(a + 0.404, b + 0.404, t) for a, b, t in LINES]), encoding="utf-8")
    pv = imp.preview(sid, str(q))
    assert pv["versionState"] == "new"
    r = imp.import_(sid, pv["token"], path=str(q))
    assert (r["newVersion"], r["switched"]) == (True, True)
    v2 = r["versionId"]
    assert v2 != v1
    # 旧版本的标注保留（在旧版本里）
    assert len(annotations(db, sid)) == 10
    # 重新导入旧文件 = 切回旧版本（没有可补登的行也切换）
    pv = imp.preview(sid)
    assert (pv["versionState"], pv["counts"]["registered"]) == ("switch", 5)
    r = imp.import_(sid, pv["token"])
    assert (r["imported"], r["switched"], r["versionId"]) == (0, True, v1)


def test_import_is_one_undoable_edit(db, env):
    sid, _, imp, edits, _ = env
    imp.import_(sid, imp.preview(sid)["token"])
    assert edits.peek_undo()["label"]["code"] == "subtitle-import"
    edits.undo()
    assert annotations(db, sid) == []
    assert db.execute("SELECT current_subtitle_version_id FROM source WHERE id=?", (sid,)).fetchone()[0] is None
    # 撤销后可以重新导入（软删除的不算“已登记”）
    pv = imp.preview(sid)
    assert pv["counts"]["importable"] == 5
    assert imp.import_(sid, pv["token"])["imported"] == 5


def test_rules_at_import_time_and_no_retroactive_change(db, env):
    """R4.7：改规则不追改已导入的标记；新导入按新规则。"""
    sid, _, imp, edits, _ = env
    imp.import_(sid, imp.preview(sid)["token"], [3])
    edits.apply({"ops": [{"entity": "setting", "id": "subtitle.speaker_rule", "version": 0, "fields": {"value": r"(?P<name>京子)"}}]})
    imp.import_(sid, imp.preview(sid)["token"], [1])
    a = {x["clean_text"]: x["tags"] for x in annotations(db, sid)}
    assert set(eval(a["ありがとう"])) == {"participants:京子", "participants:結衣", SPEAKER_STATUS_MULTI}
    assert a["こんにちは"] == dumps(["character:京子"])


def test_batch_skips_sources_without_subtitle(db, env):
    sid, _, imp, _, _ = env
    other = make_source(db, path="/m/other.mkv")
    rows = imp.preview_many([sid, other])
    assert rows[1] == {"sourceId": other, "skipped": "no-subtitle"}
    assert rows[0]["counts"]["importable"] == 5
    res = imp.import_many([{"sourceId": sid, "token": rows[0]["token"]}, {"sourceId": sid, "token": "stale"}])
    assert res[0]["imported"] == 5
    assert res[1]["error"]["code"] == "subtitle-preview-stale"


def test_unassociated_source_needs_a_file(db, env):
    sid, _, imp, _, _ = env
    other = make_source(db, path="/m/other.mkv")
    with pytest.raises(CoreError) as e:
        imp.preview(other)
    assert e.value.code == "subtitle-not-associated"


def test_clip_name_uses_imported_lines_of_current_version_only(db, env, tmp_path):
    """R7.5 + 04 §4.2.2：截取建议名用交叠的台词/音效文字（台词标注作用域是人声角色，文字仍对原混音生效）；非当前版本不参与。"""
    from ottosmasher.core.samples import SampleService
    from test_samples import asset as make_asset

    sid, _, imp, _, _ = env
    imp.import_(sid, imp.preview(sid)["token"])
    aid = make_asset(db, sid)
    svc = SampleService(db)
    assert svc.suggest(aid, 1.2, 1.8)["name"] == "こんにちは"
    assert svc.suggest(aid, 3.1, 3.5)["name"] == "足音"
    q = tmp_path / "other.srt"
    q.write_text(srt((1.0, 2.0, "（京子）別の版")), encoding="utf-8")
    imp.import_(sid, imp.preview(sid, str(q))["token"], path=str(q))
    assert svc.suggest(aid, 1.2, 1.8)["name"] == "別の版"
    assert "足音" not in svc.suggest(aid, 3.1, 3.5)["name"]
