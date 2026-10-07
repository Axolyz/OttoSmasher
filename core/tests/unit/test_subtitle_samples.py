"""字幕采样：规格 06 §6.4、04 §4.3.4；16 R4.8–R4.10、S1.6。"""

import pytest

from conftest import make_source
from ottosmasher.core.clock import new_id, now_iso
from ottosmasher.core.edits import EditService, loads
from ottosmasher.core.errors import CoreError
from ottosmasher.core.subtitle_import import SubtitleImporter
from ottosmasher.core.subtitle_samples import SubtitleSamples
from test_subtitle_import import srt
from test_tracks import asset

LINES = [
    (0.05, 0.3, "（殴る音）"),
    (1.0, 2.0, "（京子(きょうこ)たち）アッカリ～ン"),
    (2.05, 3.0, "（結衣）なに？"),
    (5.0, 6.0, "（足音）"),
    (8.0, 9.0, "（）"),  # 清洗后名称为空的音效
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
    imp.import_(sid, imp.preview(sid)["token"])
    return sid, edits, SubtitleSamples(db)


def set_default(db, edits, sid, role, aid):
    v = db.execute("SELECT version FROM source WHERE id=?", (sid,)).fetchone()[0]
    edits.apply({"ops": [{"entity": "source", "id": sid, "version": v, "fields": {f"default_{role}": aid}}]})


def by_name(pv):
    return {ln["name"]: ln for ln in pv["lines"]}


def test_missing_default_track_is_refused_not_mixed(db, env):
    sid, _, svc = env
    pv = svc.preview(sid, "sfx")
    assert pv["missingDefault"] is True
    assert [ln["status"] for ln in pv["lines"]] == ["pending", "pending", "no-name"]
    with pytest.raises(CoreError) as e:
        svc.create(sid, "sfx", pv["token"], [pv["lines"][0]["annotationId"]])
    assert (e.value.code, e.value.args_["role"]) == ("default-track-missing", "sfx")
    assert db.execute("SELECT COUNT(*) FROM sample").fetchone()[0] == 0


def test_sfx_samples_padding_clip_nature_and_every_create_is_new(db, env):
    sid, edits, svc = env
    sfx = asset(db, sid, origin="separation", stem="effect", snapshot="e", roles=["sfx"])
    set_default(db, edits, sid, "sfx", sfx)
    pv = svc.preview(sid, "sfx")
    ln = by_name(pv)
    hit = ln["殴る音"]
    assert (hit["status"], hit["sampleStart"], round(hit["sampleEnd"], 6)) == ("pending", 0.0, 0.4)  # 0.05−0.1 截到 0
    r = svc.create(sid, "sfx", pv["token"], [hit["annotationId"], ln["足音"]["annotationId"]])
    assert r["created"] == 2
    rows = db.execute('SELECT name, nature, asset_id, start, "end", created_via, text_snapshot FROM sample ORDER BY start').fetchall()
    assert [(x["name"], x["nature"], x["asset_id"], x["created_via"]) for x in rows] == [
        ("殴る音", "unpitched", sfx, "subtitle"),
        ("足音", "unpitched", sfx, "subtitle"),
    ]
    assert round(rows[1]["start"], 6) == 4.9 and round(rows[1]["end"], 6) == 6.1
    assert "alignText" not in loads(rows[0]["text_snapshot"])  # 音效的快照只作说明文字
    # 每次显式创建都新建（R4.8）
    pv = svc.preview(sid, "sfx")
    svc.create(sid, "sfx", pv["token"], [hit["annotationId"]])
    assert db.execute("SELECT COUNT(*) FROM sample WHERE name='殴る音'").fetchone()[0] == 2


def test_line_samples_snapshot_judge_interval_and_speaker(db, env):
    sid, edits, svc = env
    vocal = asset(db, sid, origin="separation", stem="vocals", snapshot="v", roles=["vocal"])
    set_default(db, edits, sid, "vocal", vocal)
    pv = svc.preview(sid, "line")
    ln = by_name(pv)["アッカリ～ン"]
    svc.create(sid, "line", pv["token"], [ln["annotationId"]])
    s = db.execute('SELECT id, name, nature, start, "end", tag_judge_start, tag_judge_end, text_snapshot FROM sample').fetchone()
    assert (s["name"], s["nature"]) == ("アッカリ～ン", "speech")
    assert (round(s["start"], 6), round(s["end"], 6), s["tag_judge_start"], s["tag_judge_end"]) == (0.9, 2.1, 1.0, 2.0)
    snap = loads(s["text_snapshot"])
    assert (snap["rawText"], snap["alignText"], snap["start"], snap["end"]) == ("（京子(きょうこ)たち）アッカリ～ン", "アッカリ～ン", 1.0, 2.0)
    # S1.6：扩展部分碰到的邻句（結衣 2.05–3.0）说话人不继承
    tags = [r[0] for r in db.execute("SELECT tag FROM sample_effective_tag WHERE sample_id=? AND facet='person'", (s["id"],))]
    assert tags == ["character:京子(きょうこ)たち"]
    # 编辑/删除标注不影响已建采样的快照与名称（R4.11、04 §4.4-7）
    a = db.execute("SELECT id, version FROM annotation WHERE id=?", (ln["annotationId"],)).fetchone()
    edits.apply({"ops": [{"entity": "annotation", "id": a[0], "version": a[1], "fields": {"clean_text": "改了", "deleted": True}}]})
    s2 = db.execute("SELECT name, text_snapshot FROM sample WHERE id=?", (s["id"],)).fetchone()
    assert (s2["name"], loads(s2["text_snapshot"])["alignText"]) == ("アッカリ～ン", "アッカリ～ン")


def test_statuses_oped_out_of_track_and_range_filter(db, env):
    sid, edits, svc = env
    vocal = asset(db, sid, origin="separation", stem="vocals", snapshot="v", roles=["vocal"])
    set_default(db, edits, sid, "vocal", vocal)
    ts = now_iso()
    db.execute("INSERT INTO oped(id, source_id, kind, start, \"end\", origin, created_at, updated_at) VALUES (?, ?, 'OP', 2.5, 4.0, 'manual', ?, ?)", (new_id(), sid, ts, ts))
    vid = db.execute("SELECT current_subtitle_version_id FROM source WHERE id=?", (sid,)).fetchone()[0]
    db.execute(
        'INSERT INTO annotation(id, source_id, kind, scope, scope_role, start, "end", raw_text, clean_text, subtitle_version_id, created_at, updated_at)'
        " VALUES (?, ?, 'line', 'role', 'vocal', 105, 106, 'x', '範囲外', ?, ?, ?)",
        (new_id(), sid, vid, ts, ts),
    )
    st = {ln["name"]: ln["status"] for ln in svc.preview(sid, "line")["lines"]}
    assert st == {"アッカリ～ン": "pending", "なに？": "oped", "範囲外": "out-of-track"}
    assert [ln["name"] for ln in svc.preview(sid, "line", 1.5, 2.06)["lines"]] == ["アッカリ～ン", "なに？"]


def test_stale_after_role_change_and_atomic(db, env):
    sid, edits, svc = env
    vocal = asset(db, sid, origin="separation", stem="vocals", snapshot="v", roles=["vocal", "sfx"])
    set_default(db, edits, sid, "vocal", vocal)
    pv = svc.preview(sid, "line")
    ids = [ln["annotationId"] for ln in pv["lines"]]
    # R4.10：其中一条不可创建（不在预览里）→ 整批回滚
    with pytest.raises(CoreError):
        svc.create(sid, "line", pv["token"], [ids[0], "nope"])
    assert db.execute("SELECT COUNT(*) FROM sample").fetchone()[0] == 0
    # R4.9：预览后角色变化 → 拒绝并要求重新预览
    ver = db.execute("SELECT version FROM sound_asset WHERE id=?", (vocal,)).fetchone()[0]
    edits.apply({"ops": [{"entity": "asset", "id": vocal, "version": ver, "fields": {"roles": ["vocal"]}}]})
    with pytest.raises(CoreError) as e:
        svc.create(sid, "line", pv["token"], ids[:1])
    assert e.value.code == "subtitle-sample-stale"
