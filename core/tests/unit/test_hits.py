"""命中上的操作（规格 09 §9.7、10 §10.2.6；ROADMAP L22、L25）：核对有效、证据方案卡拍（裁出命中段）、导出、REAPER。"""

from __future__ import annotations

import pytest
from test_rhythm_service import align, core, need_rb, sample  # noqa: F401
from test_search_index import run_index_job
from test_search_service import _put_f0, inline, run

from ottosmasher.core.errors import CoreError
from ottosmasher.media import wavfile

WORDS = {"stretch": "stretch", "fragment": " · frag"}


def speech_hit(c, tmp_path, query, bpm=180.0):
    inline(c)
    s = sample(c, name="台词")
    align(c, s)
    run_index_job(c, [s], tmp_path)
    c.rhythm.set_bpm(bpm)
    st, page = run(c, c.search.run_speech, query, {})
    return s, st["resultId"], page["rows"][0]


@need_rb
def test_hit_render_uses_evidence_scheme_and_cuts_the_hit(core, tmp_path):
    s, rid, row = speech_hit(core, tmp_path, {"blocks": [{"note": [0, 0.5]}, {"note": [1, 1.5]}], "strategy": "rank"})
    h = row["hits"][0]
    info = core.hits.wire(rid, row["rank"], 0)
    assert info["stretch"] and info["plan"] == h["evidence"]["plan"] and info["bpm"] == 180.0
    assert (info["start"], info["end"]) == (h["start"], h["end"])
    r = core.hits.render(rid, row["rank"], 0, "stretched", "voice")
    assert r["plan"] == h["evidence"]["plan"] and r["bpm"] == 180.0
    path = core.rhythm.resolve_render(r["key"])["path"]
    rate, _ch, _b, frames = wavfile.info(path)
    # 命中段 ≈ 原长 / 速度（只渲染命中这段，不是整句）
    whole = core.rhythm.render(s, "stretched", "voice", h["evidence"]["plan"])["duration"]
    assert 0 < frames / rate < whole
    assert frames / rate == pytest.approx((h["end"] - h["start"]) / h["evidence"]["speed"], rel=0.35)
    # 再要一次：复用缓存
    assert core.hits.render(rid, row["rank"], 0, "stretched", "voice")["key"] == r["key"]
    o = core.hits.render(rid, row["rank"], 0, "original", "voice+click")
    assert o["duration"] == pytest.approx(h["end"] - h["start"], abs=1e-3)
    # 导出：原声与卡拍；REAPER 两种
    p0 = core.hits.export(rid, row["rank"], 0, "original", WORDS)["path"]
    p1 = core.hits.export(rid, row["rank"], 0, "stretched", WORDS)["path"]
    assert " · frag" in p0 and "stretch-180BPM" in p1
    for baked in (True, False):
        out = core.handoff.reaper_handoff([], WORDS, baked=baked, hits=[{"resultId": rid, "rank": row["rank"], "index": 0}])
        assert out["count"] == 1 and out["clipboard"].startswith("<ITEM")


def test_hit_validity_and_pitch_has_no_stretch(core, tmp_path):
    s, rid, row = speech_hit(core, tmp_path, {"blocks": [{"vowel": "a"}]})
    assert core.hits.wire(rid, row["rank"], 0)["plan"] == "near_fast"  # 不限节奏：整句近快
    with pytest.raises(CoreError) as e:
        core.hits.wire(rid, row["rank"], 99)
    assert e.value.code == "hit-not-found"
    align(core, s)  # 分析换了 → 命中已失效
    with pytest.raises(CoreError) as e:
        core.hits.render(rid, row["rank"], 0, "stretched", "voice")
    assert (e.value.code, e.value.args_["state"]) == ("hit-stale", "stale")
    p = sample(core, start=6.0, end=8.0, name="音")
    _put_f0(core)
    st, page = run(core, core.search.run_pitch, [{"seconds": 0.5, "low": "A4"}], {}, "samples", {"text": "音"})
    prow = page["rows"][0]
    assert prow["sampleId"] == p
    info = core.hits.wire(st["resultId"], prow["rank"], 0)
    assert not info["stretch"] and info["plan"] is None
    with pytest.raises(CoreError) as e:
        core.hits.render(st["resultId"], prow["rank"], 0, "stretched", "voice")
    assert e.value.code == "hit-no-stretch"


def test_slice_knots_strictly_increasing():
    from ottosmasher.core.hits import _slice_knots

    knots = [(0, 0), (100, 150), (101, 300), (400, 500)]
    for a, b in [(150, 300), (149, 301), (0, 500), (151, 299), (10, 20)]:
        pts = _slice_knots(knots, a, b)
        assert pts[0][1] == a and pts[-1][1] == b or len(pts) >= 2
        assert all(q[0] > p[0] and q[1] > p[1] for p, q in zip(pts, pts[1:]))
