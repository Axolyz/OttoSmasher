"""原片页的标注视图：03 §3.4 字幕上下文、05 §5.8 统计、UI_PLAN §4 准备清单。"""

from conftest import make_source
from ottosmasher.core import annotations as ann
from ottosmasher.core.clock import new_id, now_iso
from ottosmasher.core.edits import EditService
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
