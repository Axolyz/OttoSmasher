"""原片上的文本层、音效提示、区段标签（所有者 2026-10-09；03 §3.4 台本、05 §5.8 统计、UI_PLAN §4 准备清单）。"""

import pytest

from conftest import make_sample, make_source
from ottosmasher.core import effective_tags
from ottosmasher.core import text_layer as tl
from ottosmasher.core.clock import new_id, now_iso
from ottosmasher.core.edits import EditService
from ottosmasher.core.errors import CoreError
from ottosmasher.core.subtitle_import import SubtitleImporter
from test_subtitle_import import srt
from test_tracks import asset


def setup(db, tmp_path, lines):
    sid = make_source(db)
    db.execute("UPDATE source SET duration=100.0 WHERE id=?", (sid,))
    p = tmp_path / "a.srt"
    p.write_text(srt(*lines), encoding="utf-8")
    db.execute("UPDATE source SET subtitle_path=? WHERE id=?", (str(p), sid))
    edits = EditService(db)
    imp = SubtitleImporter(db, edits)
    imp.import_(sid, imp.preview(sid)["token"], {"oped": False})
    return sid, edits, tl.TextLayer(db, edits)


def test_list_counts_and_oped(db, tmp_path):
    sid, _, _ = setup(db, tmp_path, [(1, 2, "（京子）あ"), (3, 4, "（足音）"), (10, 12, "♪～"), (11, 11.5, "歌"), (20, 21, "（京子）（結衣）い")])
    ts = now_iso()
    db.execute("INSERT INTO oped(id, source_id, kind, start, \"end\", origin, created_at, updated_at) VALUES (?, ?, 'OP', 10, 15, 'manual', ?, ?)", (new_id(), sid, ts, ts))
    v = tl.list_for_source(db, sid)
    assert [(s["ordinal"], s["text"], s["speakers"], s["oped"], s["protected"]) for s in v["segments"]] == [
        (1, "あ", ["京子"], None, False), (2, "♪～", [], "OP", False), (3, "歌", [], "OP", False), (4, "い", ["京子", "結衣"], None, False)]
    assert [(h["text"], h["protected"]) for h in v["hints"]] == [("足音", False)]
    c = tl.counts(db)[sid]
    assert (c["lines"], c["hasMarkers"], c["oped"]) == (2, True, 1)  # 句数 = 不在 OP/ED 里的段，不含音效提示


def test_prep_status(db, tmp_path):
    sid, edits, _ = setup(db, tmp_path, [(1, 2, "あ"), (3, 4, "（足音）")])
    p = tl.prep(db, sid)
    assert p["subtitle"] == {"ok": True, "markers": 2, "associated": True}
    assert (p["separation"]["ok"], p["defaultVocal"]["ok"], p["oped"]["ok"], p["lineSamples"]["count"]) == (False, False, False, 0)
    other = make_source(db, path="/x.mkv")
    assert tl.counts(db)[other] == {"lines": 0, "hasMarkers": False, "oped": 0, "samples": 0}


def test_derived_across_assets(db, tmp_path):
    sid, _, _ = setup(db, tmp_path, [(1, 2, "あ")])
    a1 = asset(db, sid, origin="separation", stem="vocals", snapshot="v", roles=["vocal"])
    db.execute("UPDATE sound_asset SET mapping='[[0,10],[5,15]]', duration=5 WHERE id=?", (a1,))  # 从原片 10 秒开始的分离声部
    s1 = make_sample(db, a1)  # 局部 1–2 → 原片 11–12
    other = make_source(db, path="/x.mkv")
    make_sample(db, asset(db, other, origin="separation", stem="vocals", snapshot="w", roles=["vocal"]))
    d = tl.list_for_source(db, sid)["derived"]
    assert [(x["id"], x["start"], x["end"]) for x in d] == [(s1, 11.0, 12.0)]


def eff(db, smp):
    return {(t["tag"], t["provenance"]) for t in effective_tags.of_sample(db, smp)}


def test_promote_local_tags_to_range_tags_r5_6(db, tmp_path):
    sid, edits, _ = setup(db, tmp_path, [(5, 6, "あ")])
    v = asset(db, sid, origin="separation", stem="vocals", snapshot="v", roles=["vocal"])
    smp = make_sample(db, v)
    db.execute("INSERT INTO sample_tag(sample_id, tag) VALUES (?, 'effect:door'), (?, '好用')", (smp, smp))
    effective_tags.refresh(db, [smp])
    before = eff(db, smp)
    r = tl.promote_batch(db, smp, ["effect:door"])
    assert (r["scope"], r["role"], r["start"], r["end"]) == ("role", "vocal", 1.0, 2.0)
    edits.apply(r["batch"])
    after = eff(db, smp)
    assert ("effect:door", "segment") in after and ("effect:door", "local") not in after
    edits.undo()
    assert eff(db, smp) == before
    both = asset(db, sid, origin="separation", stem="mix", snapshot="m", roles=["vocal", "sfx"])
    s2 = make_sample(db, both)
    db.execute("INSERT INTO sample_tag(sample_id, tag) VALUES (?, 'x')", (s2,))
    with pytest.raises(CoreError):
        tl.promote_batch(db, s2, ["x"])
    bare = asset(db, sid, origin="separation", stem="other", snapshot="o", roles=[])
    s3 = make_sample(db, bare)
    db.execute("INSERT INTO sample_tag(sample_id, tag) VALUES (?, 'y')", (s3,))
    r3 = tl.promote_batch(db, s3, ["y"])
    assert r3["scope"] == "asset"
    edits.apply(r3["batch"])
    assert ("y", "segment") in eff(db, s3)


def test_add_segment_replace_cut_cancel(db, tmp_path):
    sid, edits, layer = setup(db, tmp_path, [(1, 3, "あいうえお"), (4, 6, "かきくけこ")])
    # 不重叠 → 直接加（手输段，受保护）
    r = layer.add_segment(sid, 7.0, 8.0, "さしす")
    row = db.execute("SELECT origin, edited FROM text_segment WHERE id=?", (r["id"],)).fetchone()
    assert tuple(row) == ("typed", 1)
    # 重叠：不给选择 → 报错并说明能否切开
    chk = layer.check_add(sid, 2.5, 4.5)
    assert len(chk["conflicts"]) == 2 and chk["canCut"] is True
    with pytest.raises(CoreError) as e:
        layer.add_segment(sid, 2.5, 4.5, "たち")
    assert e.value.code == "segment-overlap"
    # 新段落在旧段中间 → 不能切开
    assert layer.check_add(sid, 1.5, 2.0)["canCut"] is False
    with pytest.raises(CoreError):
        layer.add_segment(sid, 1.5, 2.0, "い", resolve="cut")
    # 切开 = 只改时间边界：旧段缩到新段外面，文字不动，算改过
    layer.add_segment(sid, 2.5, 4.5, "たち", resolve="cut")
    got = [tuple(x) for x in db.execute('SELECT start, "end", text, edited FROM text_segment WHERE source_id=? AND deleted=0 ORDER BY start', (sid,))]
    assert got == [(1.0, 2.5, "あいうえお", 1), (2.5, 4.5, "たち", 1), (4.5, 6.0, "かきくけこ", 1), (7.0, 8.0, "さしす", 1)]
    # 替换 = 删掉重叠段；撤销恢复
    layer.add_segment(sid, 0.5, 4.0, "ぜんぶ", resolve="replace")
    assert [x[0] for x in db.execute("SELECT text FROM text_segment WHERE source_id=? AND deleted=0 ORDER BY start", (sid,))] == ["ぜんぶ", "かきくけこ", "さしす"]
    edits.undo()
    assert len(db.execute("SELECT 1 FROM text_segment WHERE source_id=? AND deleted=0", (sid,)).fetchall()) == 4


def test_get_segment_matches_list_row(db, tmp_path):
    # 舞台「编辑这段…」按 id 取一段：与 list 里的那一行相同（序号、受保护标记、使用数）
    sid, edits, layer = setup(db, tmp_path, [(1, 3, "あいうえお"), (4, 6, "かきくけこ"), (4, 5, "かき")])
    rows = tl.list_for_source(db, sid)["segments"]
    assert [tl.get_segment(db, r["id"]) == r for r in rows] == [True, True, True]
    assert [r["ordinal"] for r in rows] == [1, 2, 3] and [r["text"] for r in rows] == ["あいうえお", "かき", "かきくけこ"]
    edits.apply({"ops": [{"entity": "segment", "id": rows[0]["id"], "version": rows[0]["version"], "fields": {"deleted": True}}]})
    with pytest.raises(CoreError) as e:
        tl.get_segment(db, rows[0]["id"])
    assert e.value.code == "segment-not-found"
    assert tl.get_segment(db, rows[1]["id"])["ordinal"] == 1


def test_split_merge_and_hint(db, tmp_path):
    sid, edits, layer = setup(db, tmp_path, [(1, 3, "あいう\nえお"), (3, 4, "か")])
    a, b = tl.list_for_source(db, sid)["segments"]
    r = layer.split(a["id"], a["version"], 2.0, "あいう", "えお")
    assert len(r["ids"]) == 2
    rows = [tuple(x) for x in db.execute('SELECT start, "end", text, edited, deleted FROM text_segment WHERE source_id=? ORDER BY deleted, start', (sid,))]
    assert rows[:3] == [(1.0, 2.0, "あいう", 1, 0), (2.0, 3.0, "えお", 1, 0), (3.0, 4.0, "か", 0, 0)] and rows[3][4] == 1  # 旧段删掉
    with pytest.raises(CoreError):
        layer.split(b["id"], b["version"], 5.0, "x", "y")
    right = db.execute("SELECT id FROM text_segment WHERE source_id=? AND deleted=0 AND abs(start-2.0)<1e-9", (sid,)).fetchone()[0]
    m = layer.merge([right, b["id"]])
    t = db.execute('SELECT start, "end", text, edited FROM text_segment WHERE id=?', (m["id"],)).fetchone()
    assert tuple(t) == (2.0, 4.0, "えお\nか", 1)
    h = layer.add_hint(sid, 5.0, 6.0, "ドア")
    v = tl.list_for_source(db, sid)
    assert [(x["text"], x["origin"], x["protected"]) for x in v["hints"]] == [("ドア", "manual", True)]
    assert h["id"]


def test_regenerate_speakers_skips_protected_and_hand_edited(db, tmp_path):
    sid, edits, layer = setup(db, tmp_path, [(1, 2, "（京子）あ"), (3, 4, "（結衣）い"), (5, 6, "（綾乃）う")])
    a, b, c = tl.list_for_source(db, sid)["segments"]
    edits.apply({"ops": [{"entity": "segment", "id": b["id"], "version": b["version"], "fields": {"speakers": ["ちなつ"]}}]})  # 手改说话人
    edits.apply({"ops": [{"entity": "segment", "id": c["id"], "version": c["version"], "fields": {"end": 6.5}}]})  # 改过边界（受保护）
    # 规则改成“不提取说话人”：重新生成只动 a
    cur = db.execute("SELECT version FROM setting WHERE key='subtitle.speaker_rule'").fetchone()
    edits.apply({"ops": [{"entity": "setting", "id": "subtitle.speaker_rule", "version": cur[0] if cur else 0, "fields": {"value": r"(?P<name>\[[^\]]*\])"}}]})
    r = layer.regenerate_speakers(sid)
    assert r["changed"] == 1
    got = [x[0] for x in db.execute("SELECT speakers FROM text_segment WHERE source_id=? AND deleted=0 ORDER BY start", (sid,))]
    assert got == ["[]", '["ちなつ"]', '["綾乃"]']


def test_speakers_follow_segments_and_only_vocal_assets(db, tmp_path):
    sid, edits, _ = setup(db, tmp_path, [(1, 2, "（京子）あ"), (2, 3, "（結衣）い")])
    vocal = asset(db, sid, origin="separation", stem="vocals", snapshot="v", roles=["vocal"])
    music = asset(db, sid, origin="separation", stem="music", snapshot="m", roles=[])
    sv, sm = make_sample(db, vocal), make_sample(db, music)  # 1.0–2.0：判定区间 = 选区
    effective_tags.refresh(db, [sv, sm])
    assert ("character:京子", "segment") in eff(db, sv) and not any(t.startswith("character:") for t, _ in eff(db, sm))
    # 改判定区间 → 读到另一段的说话人（撤销恢复）
    edits.apply({"ops": [{"entity": "sample", "id": sv, "version": 1, "fields": {"judge": [1.5, 2.0]}}]})
    assert ("character:京子", "segment") in eff(db, sv)
    with pytest.raises(CoreError) as e:
        edits.apply({"ops": [{"entity": "sample", "id": sv, "version": 2, "fields": {"judge": [0.5, 2.0]}}]})
    assert e.value.args_["reason"] == "outside-sample"  # 判定区间必须在采样范围内
    # 改段的说话人 → 继承跟着变
    s0 = tl.list_for_source(db, sid)["segments"][0]
    edits.apply({"ops": [{"entity": "segment", "id": s0["id"], "version": s0["version"], "fields": {"speakers": ["京子", "結衣"]}}]})
    assert {("participants:京子", "segment"), ("participants:結衣", "segment")} <= eff(db, sv)
