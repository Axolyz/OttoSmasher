"""原片页的标注视图：03 §3.4 字幕上下文、05 §5.8 统计、UI_PLAN §4 准备清单。"""

import pytest

from conftest import make_source
from ottosmasher.core import annotations as ann
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
    imp.import_(sid, imp.preview(sid)["token"])
    return sid, edits


def test_list_counts_and_oped(db, tmp_path):
    sid, _ = setup(db, tmp_path, [(1, 2, "（京子）あ"), (3, 4, "（足音）"), (10, 12, "♪～"), (11, 11.5, "歌"), (20, 21, "（京子）（結衣）い")])
    ts = now_iso()
    db.execute("INSERT INTO oped(id, source_id, kind, start, \"end\", origin, created_at, updated_at) VALUES (?, ?, 'OP', 10, 15, 'manual', ?, ?)", (new_id(), sid, ts, ts))
    v = ann.list_for_source(db, sid)
    assert [(a["kind"], a["name"], a["speakers"], a["oped"]) for a in v["annotations"]] == [
        ("line", "あ", ["京子"], None),
        ("sfx", "足音", [], None),
        ("line", "♪～", [], "OP"),
        ("line", "歌", [], "OP"),
        ("line", "い", ["京子", "結衣"], None),
    ]
    c = ann.counts(db)[sid]
    assert (c["lines"], c["hasMarkers"], c["oped"]) == (2, True, 1)  # 句数不含 OP/ED 内的台词、不含音效


def test_prep_status(db, tmp_path):
    sid, edits = setup(db, tmp_path, [(1, 2, "あ")])
    p = ann.prep(db, sid)
    assert p["subtitle"] == {"ok": True, "markers": 1, "associated": True}
    assert (p["separation"]["ok"], p["defaultVocal"]["ok"], p["oped"]["ok"], p["lineSamples"]["count"]) == (False, False, False, 0)
    v = asset(db, sid, origin="separation", stem="vocals", snapshot="v", roles=["vocal"])
    ver = db.execute("SELECT version FROM source WHERE id=?", (sid,)).fetchone()[0]
    edits.apply({"ops": [{"entity": "source", "id": sid, "version": ver, "fields": {"default_vocal": v}}]})
    p = ann.prep(db, sid)
    assert p["separation"]["asset"]["stem"] == "vocals" and p["defaultVocal"]["asset"]["id"] == v
    other = make_source(db, path="/x.mkv")
    assert ann.counts(db)[other] == {"lines": 0, "hasMarkers": False, "oped": 0, "samples": 0}


def test_derived_across_assets(db, tmp_path):
    from conftest import make_sample

    sid, _ = setup(db, tmp_path, [(1, 2, "あ")])
    a1 = asset(db, sid, origin="separation", stem="vocals", snapshot="v", roles=["vocal"])
    db.execute("UPDATE sound_asset SET mapping='[[0,10],[5,15]]', duration=5 WHERE id=?", (a1,))  # 从原片 10 秒开始的分离声部
    s1 = make_sample(db, a1)  # 局部 1–2 → 原片 11–12
    other = make_source(db, path="/x.mkv")
    make_sample(db, asset(db, other, origin="separation", stem="vocals", snapshot="w", roles=["vocal"]))
    d = ann.list_for_source(db, sid)["derived"]
    assert [(x["id"], x["start"], x["end"]) for x in d] == [(s1, 11.0, 12.0)]  # 只有这个原片的；按原片时间


def eff(db, smp):
    from ottosmasher.core import effective_tags

    return {(t["tag"], t["provenance"]) for t in effective_tags.of_sample(db, smp)}


def test_promote_local_tags_r5_6(db, tmp_path):
    from conftest import make_sample

    sid, edits = setup(db, tmp_path, [(1, 2, "あ")])
    v = asset(db, sid, origin="separation", stem="vocals", snapshot="v", roles=["vocal"])
    smp = make_sample(db, v)
    db.execute("INSERT INTO sample_tag(sample_id, tag) VALUES (?, 'effect:door'), (?, '好用')", (smp, smp))
    from ottosmasher.core import effective_tags

    effective_tags.refresh(db, [smp])
    before = eff(db, smp)
    r = ann.promote_batch(db, smp, ["effect:door"])
    assert (r["scope"], r["role"], r["start"], r["end"]) == ("role", "vocal", 1.0, 2.0)
    edits.preview(r["batch"])
    assert eff(db, smp) == before  # 预览前后不变
    edits.apply(r["batch"])
    after = eff(db, smp)
    assert ("effect:door", "segment") in after and ("effect:door", "local") not in after  # 本地标签消失、有效标签仍在（来自区段）
    assert db.execute("SELECT tag FROM sample_tag WHERE sample_id=?", (smp,)).fetchall()[0][0] == "好用"
    edits.undo()
    assert eff(db, smp) == before  # 撤销后恢复

    # 两个角色 → 必须选；没有角色 → 资产作用域（资产局部秒）
    both = asset(db, sid, origin="separation", stem="mix", snapshot="m", roles=["vocal", "sfx"])
    s2 = make_sample(db, both)
    db.execute("INSERT INTO sample_tag(sample_id, tag) VALUES (?, 'x')", (s2,))
    with pytest.raises(CoreError):
        ann.promote_batch(db, s2, ["x"])
    assert ann.promote_batch(db, s2, ["x"], role="sfx")["role"] == "sfx"
    bare = asset(db, sid, origin="separation", stem="other", snapshot="o", roles=[])
    s3 = make_sample(db, bare)
    db.execute("INSERT INTO sample_tag(sample_id, tag) VALUES (?, 'y')", (s3,))
    r3 = ann.promote_batch(db, s3, ["y"])
    assert r3["scope"] == "asset"
    edits.apply(r3["batch"])
    assert ("y", "segment") in eff(db, s3)
    with pytest.raises(CoreError):
        ann.promote_batch(db, s3, ["not-local"])


def test_boundary_edit_shared_and_r4_11(db, tmp_path):
    from conftest import make_sample

    sid, edits = setup(db, tmp_path, [(1, 2, "あ"), (2, 3, "い")])
    v = asset(db, sid, origin="separation", stem="vocals", snapshot="v", roles=["vocal"])
    smp = make_sample(db, v)  # 1.0–2.0
    a, b = ann.list_for_source(db, sid)["annotations"]
    # 相邻共用的边界一起移动：一个批次两项
    edits.apply({"ops": [
        {"entity": "annotation", "id": a["id"], "version": a["version"], "fields": {"end": 2.4}},
        {"entity": "annotation", "id": b["id"], "version": b["version"], "fields": {"start": 2.4}},
    ]})  # fmt: skip
    a2, b2 = ann.list_for_source(db, sid)["annotations"]
    assert (a2["end"], b2["start"]) == (2.4, 2.4)
    assert db.execute("SELECT user_edited FROM annotation WHERE id=?", (a["id"],)).fetchone()[0] == 1
    assert db.execute('SELECT start, "end" FROM sample WHERE id=?', (smp,)).fetchone()[:] == (1.0, 2.0)  # R4.11 不移动采样
    edits.undo()
    assert db.execute('SELECT "end", user_edited FROM annotation WHERE id=?', (a["id"],)).fetchone()[:] == (2.0, 0)
    ver = ann.list_for_source(db, sid)["annotations"][0]["version"]
    # 超出原片时长、负数、作用域与角色不配对 → 拒绝
    for fields, reason in (({"end": 101.0}, "out-of-bounds"), ({"start": -0.5}, "out-of-bounds"), ({"scope": "role", "scope_role": None}, "scope-role-mismatch")):
        with pytest.raises(CoreError) as e:
            edits.apply({"ops": [{"entity": "annotation", "id": a["id"], "version": ver, "fields": fields}]})
        assert e.value.args_["reason"] == reason
    # 改成歌词
    edits.apply({"ops": [{"entity": "annotation", "id": a["id"], "version": ver, "fields": {"kind": "song"}}]})
    assert ann.list_for_source(db, sid)["annotations"][0]["kind"] == "song"
