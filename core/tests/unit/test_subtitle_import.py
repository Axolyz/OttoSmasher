"""字幕导入 = 一次显式操作，四类一起进（所有者 2026-10-09【基线变更】；docs/history/QUESTIONS.md「原片上的四类对象」B 节）。

台词 → 文本层的段；音效行 → 音效提示；说话人 → 段的属性；♪～ / ～♪ → OP/ED。重新导入按 新增 / 无变化 / 替换 / 跳过 处理，受保护的不动；
整次导入原子、可撤销。不建采样（R4.1）；无效范围不导入（R4.3）。
"""

import pytest

from conftest import make_asset, make_source
from ottosmasher.core.clock import new_id, now_iso
from ottosmasher.core.edits import EditService
from ottosmasher.core.errors import CoreError
from ottosmasher.core.subtitle_import import SubtitleImporter


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
    (8.0, 9.0, "♪～"),
    (9.0, 10.0, "うた"),
    (10.0, 30.0, "～♪"),
    (11.0, 11.0, "ゼロ長"),
    (95.0, 120.0, "はみ出し"),
    (40.0, 41.0, "普通の\n台詞"),
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


def segs(db, sid):
    return [dict(r) for r in db.execute('SELECT id, start, "end", text, speakers, origin, provenance, edited, version FROM text_segment WHERE source_id=? AND deleted=0 ORDER BY start', (sid,))]


def hints(db, sid):
    return [dict(r) for r in db.execute('SELECT id, start, "end", text, origin FROM sfx_hint WHERE source_id=? AND deleted=0 ORDER BY start', (sid,))]


def opeds(db, sid):
    return [tuple(r) for r in db.execute('SELECT kind, start, "end", origin FROM oped WHERE source_id=? AND deleted=0 ORDER BY start', (sid,))]


def test_first_import_four_categories(db, env):
    sid, _, imp, edits, _ = env
    pv = imp.preview(sid)
    st = {r["no"]: (r["status"], r["reason"]) for r in pv["segments"] + pv["hints"]}
    assert st == {1: ("new", None), 2: ("new", None), 3: ("new", None), 4: ("new", None), 5: ("new", None), 6: ("new", None),
                  7: ("invalid", "empty"), 8: ("invalid", "beyond-end"), 9: ("new", None)}
    assert [r["no"] for r in pv["hints"]] == [2]
    assert pv["counts"]["segments"]["new"] == 6 and pv["counts"]["hints"]["new"] == 1
    assert [(s["name"], s["count"]) for s in pv["speakers"]] == [("京子", 2), ("結衣", 1)]
    assert [(p["kind"], p["start"], p["end"], p["status"]) for p in pv["oped"]["pairs"]] == [("OP", 8.0, 30.0, "new")]
    r = imp.import_(sid, pv["token"])
    assert r["created"] == {"segments": 6, "hints": 1, "oped": 1} and [x["reason"] for x in r["invalid"]] == ["empty", "beyond-end"]
    assert db.execute("SELECT COUNT(*) FROM sample").fetchone()[0] == 0  # R4.1：不建采样
    got = segs(db, sid)
    assert [(s["text"], s["speakers"], s["origin"], s["edited"]) for s in got] == [
        ("こんにちは", '["京子"]', "subtitle", 0), ("ありがとう", '["京子","結衣"]', "subtitle", 0), ("♪～", "[]", "subtitle", 0),
        ("うた", "[]", "subtitle", 0), ("～♪", "[]", "subtitle", 0), ("普通の\n台詞", "[]", "subtitle", 0)]
    assert '"raw":"（京子）こんにちは"' in got[0]["provenance"] and '"line":1' in got[0]["provenance"]
    assert [(h["text"], h["origin"]) for h in hints(db, sid)] == [("足音", "subtitle")]
    assert opeds(db, sid) == [("OP", 8.0, 30.0, "subtitle_rule")]
    # 整次导入一个编辑、可撤销
    edits.undo()
    assert segs(db, sid) == [] and hints(db, sid) == [] and opeds(db, sid) == []


def test_reimport_unchanged_and_categories_off(db, env):
    sid, _, imp, _, _ = env
    imp.import_(sid, imp.preview(sid)["token"], {"speakers": False, "oped": False})
    assert all(s["speakers"] == "[]" for s in segs(db, sid)) and opeds(db, sid) == []
    pv = imp.preview(sid)
    assert pv["counts"]["segments"]["unchanged"] == 6 and pv["counts"]["hints"]["unchanged"] == 1
    r = imp.import_(sid, pv["token"], {"segments": False, "hints": False})
    assert r["created"] == {"segments": 0, "hints": 0, "oped": 1}


def test_overlap_rules_replace_keep_protected_force(db, env, tmp_path):
    sid, p, imp, edits, _ = env
    imp.import_(sid, imp.preview(sid)["token"])
    old = {s["text"]: s for s in segs(db, sid)}
    # 用户改过“ありがとう”这段（受保护）；“こんにちは”在某条轨上有人工音素版本（受保护）
    edits.apply({"ops": [{"entity": "segment", "id": old["ありがとう"]["id"], "version": old["ありがとう"]["version"], "fields": {"end": 6.2}}]})
    aid = make_asset(db, sid)
    db.execute(
        "INSERT INTO measure_run(id, kind, owner_type, owner_id, asset_id, inputs, status, manual, result, created_at) VALUES (?, 'alignment', 'asset_text', ?, ?, '{}', 'ok', 1, '{}', ?)",
        (new_id(), f"seg:{old['こんにちは']['id']}@{aid}", aid, now_iso()),
    )
    p.write_text(srt((1.0, 2.1, "（京子）こんにちは！"), (5.0, 6.0, "（京子）（結衣）ありがとう"), (40.0, 41.0, "ふつうの台詞"), (50.0, 51.0, "新しい")), encoding="utf-8")
    pv = imp.preview(sid)
    st = {r["no"]: (r["status"], r["reason"]) for r in pv["segments"]}
    # 1 碰到有人工版本的段 → 跳过；2 区间相同但那段改过（不同）→ 碰到受保护 → 跳过；3 只碰到未受保护的 → 替换；4 新增
    assert st == {1: ("skip", "protected"), 2: ("skip", "protected"), 3: ("replace", None), 4: ("new", None)}
    assert pv["counts"]["segments"]["removed"] == 1
    keep = imp.preview(sid, options={"replace": False})
    assert {r["no"]: r["status"] for r in keep["segments"]}[3] == "skip"
    # 不勾的行不替换任何东西
    ex = imp.preview(sid, options={"exclude": [3]})
    assert {r["no"]: r["status"] for r in ex["segments"]}[3] == "excluded" and ex["counts"]["segments"]["removed"] == 0
    # 逐行强制替换受保护的：写清会丢掉什么
    forced = imp.preview(sid, options={"force": [1]})
    assert forced["counts"]["segments"]["removedProtected"] == 1 and forced["removed"]["segments"][0]["manual"] is True
    r = imp.import_(sid, forced["token"], {"force": [1]})
    texts = [s["text"] for s in segs(db, sid)]
    assert "こんにちは！" in texts and "こんにちは" not in texts and "ありがとう" in texts and "ふつうの台詞" in texts and "新しい" in texts
    assert r["counts"]["segments"]["replace"] == 2


def test_oped_errors_need_confirmation(db, env):
    sid, p, imp, _, _ = env
    p.write_text(srt((8.0, 9.0, "♪～"), (9.0, 10.0, "♪～"), (10.0, 30.0, "～♪"), (40.0, 41.0, "台詞")), encoding="utf-8")
    pv = imp.preview(sid)
    assert pv["oped"]["errors"] and [p["status"] for p in pv["oped"]["pairs"]] == ["excluded"]
    r = imp.import_(sid, pv["token"])
    assert r["opedErrors"] == 1 and opeds(db, sid) == []
    pv = imp.preview(sid, options={"opedConfirm": [{"index": 0, "kind": "ED"}]})
    imp.import_(sid, pv["token"], {"opedConfirm": [{"index": 0, "kind": "ED"}]})
    assert opeds(db, sid) == [("ED", 9.0, 30.0, "manual")]


def test_preview_goes_stale_when_the_layer_changes(db, env):
    sid, _, imp, edits, _ = env
    imp.import_(sid, imp.preview(sid)["token"])
    pv = imp.preview(sid)
    s = segs(db, sid)[0]
    edits.apply({"ops": [{"entity": "segment", "id": s["id"], "version": s["version"], "fields": {"text": "かえた"}}]})
    with pytest.raises(CoreError) as e:
        imp.import_(sid, pv["token"])
    assert e.value.code == "subtitle-preview-stale"


def test_batch_and_one_click(db, env, tmp_path):
    sid, _, imp, _, _ = env
    other = make_source(db)
    rows = imp.preview_many([sid, other])
    assert rows[1] == {"sourceId": other, "skipped": "no-subtitle"} and rows[0]["counts"]["segments"]["new"] == 6
    out = imp.import_many([{"sourceId": sid, "token": rows[0]["token"]}])
    assert out[0]["created"]["segments"] == 6
    again = imp.import_default(sid)
    assert again["created"] == {"segments": 0, "hints": 0, "oped": 0} and again["counts"]["segments"]["unchanged"] == 6


def test_preview_marks_what_import_would_refuse_as_too_long(db, env, tmp_path):
    """超过 120 秒的条目（2026-11-04 字幕任务的反馈：音效提示预览通过、导入时整个原素材被拒）：预览写明无效，其余照常导入。"""
    sid, _p, imp, _edits, _changes = env
    db.execute("UPDATE source SET duration=400.0 WHERE id=?", (sid,))
    f = tmp_path / "long.srt"
    f.write_text(srt((1.0, 2.0, "こんにちは"), (3.0, 334.0, "（音楽）"), (340.0, 470.0 - 5.0, "長い台詞")), encoding="utf-8")
    db.execute("UPDATE source SET duration=500.0, subtitle_path=? WHERE id=?", (str(f), sid))
    pv = imp.preview(sid)
    assert [(r["status"], r["reason"]) for r in pv["hints"]] == [("invalid", "too-long")]
    assert [(r["status"], r["reason"]) for r in pv["segments"]] == [("new", None), ("invalid", "too-long")]
    r = imp.import_(sid, pv["token"])
    assert r["created"]["segments"] == 1 and r["created"]["hints"] == 0
    assert sorted(x["reason"] for x in r["invalid"]) == ["too-long", "too-long"]
