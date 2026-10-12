"""音素回到原素材时间线、去掉父采样（所有者 2026-10-12，docs/QUESTIONS.md「音素回到原素材时间线、去掉父采样」）。

- 一句台词只有一份音素，原素材上所有含人声的音轨都读它（换到各自的时间，盖不全的标 ◐）；回导成品和从它加工出来的另有一份；
- 只在盖住整句、含人声的轨上测；不含人声的轨（只标音效、没标角色的声部、以及它们的加工成品）不读音素；
- 从只盖住半句的轨上也能改音素时间（只改它盖得住的那几个）；
- 加工链、「返回原素材」的整轨、相关采样、局部命名；迁移 0015。
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from analysis_helpers import add_analysis, add_segment
from ottosmasher.core import lineage, text_layer, units
from ottosmasher.core.clock import new_id, now_iso
from ottosmasher.core.edits import dumps, loads
from ottosmasher.core.server import Core
from ottosmasher.domain import naming
from ottosmasher.store.db import bundled_migrations, connect, migrate


@pytest.fixture
def core(tmp_path: Path):
    wav = tmp_path / "a.wav"
    subprocess.run(["ffmpeg", "-v", "error", "-f", "lavfi", "-i", "sine=frequency=220:duration=20", "-ar", "48000", str(wav)], check=True)
    c = Core(tmp_path / "ws")
    c.open()
    r = c.sources.add([str(wav)])[0]
    c.sid = r["sourceId"]
    c.aid = r["assets"][0]["assetId"]
    yield c
    c.close()


def track(c, origin: str, mapping: list[list[float]], input_id: str | None, roles: tuple[str, ...] = (), stem: str | None = None) -> str:
    """直接登记一条音轨记录（读取不需要声音文件；媒体记录只为取采样率，文件不存在）。"""
    aid, mf = new_id(), new_id()
    c.conn.execute("INSERT INTO media_file(id, path, location, file_snapshot, format, sample_rate, created_at) VALUES (?, ?, 'library', '{}', 'wav', 48000, ?)",
                   (mf, f"Library/{aid}.wav", now_iso()))
    c.conn.execute(
        "INSERT INTO sound_asset(id, source_id, origin, media_file_id, duration, mapping, input_asset_id, stem_name, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (aid, c.sid, origin, mf, mapping[-1][0], dumps(mapping), input_id, stem, now_iso()),
    )
    for r in roles:
        c.conn.execute("INSERT INTO asset_role(asset_id, role, state) VALUES (?, ?, 'on')", (aid, r))
    return aid


def smp(c, asset: str, start: float, end: float, name: str = "s") -> str:
    return c.samples.create(asset, start, end, name=name, nature="speech")["id"]


# 一句 9.5–12.5 秒；音素（原混音上测的，原混音局部秒 = 原素材秒）
PHONES = [
    {"label": "k", "start": 9.6, "end": 10.4, "mora": 0, "word": 0},
    {"label": "a", "start": 10.4, "end": 11.5, "mora": 0, "word": 0},
    {"label": "N", "start": 11.5, "end": 12.4, "mora": 1, "word": 0},
]


def test_lineage_facts_are_copied_when_tracks_are_created(core):
    sep = track(core, "separation", [[0, 0], [20, 20]], core.aid, ("vocal",))
    fl = track(core, "flatten", [[0, 10], [2, 12]], sep, ("vocal",))
    re = track(core, "reimport", [[0, 10], [2, 12]], sep)
    sep2 = track(core, "separation", [[0, 10], [2, 12]], re)
    mixfl = track(core, "flatten", [[0, 10], [2, 12]], core.aid)
    got = {r[0]: (r[1], r[2]) for r in core.conn.execute("SELECT id, reimport_id, from_separation FROM sound_asset")}
    assert got[core.aid] == (None, 0) and got[sep] == (None, 1) and got[fl] == (None, 1) and got[mixfl] == (None, 0)
    assert got[re] == (re, 1) and got[sep2] == (re, 1)
    assert units.base_of(core.conn.execute("SELECT * FROM sound_asset WHERE id=?", (sep2,)).fetchone()) == re


def test_one_analysis_read_by_every_voiced_track(core):
    seg = add_segment(core, 9.5, 12.5, "かん")
    add_analysis(core, 9.5, 12.5, PHONES, segment_id=seg)
    sep = track(core, "separation", [[0, 0], [20, 20]], core.aid, ("vocal",))
    fl = track(core, "flatten", [[0, 10], [2, 12]], sep, ("vocal",))
    whole = smp(core, core.aid, 9.5, 12.5, "whole")
    part = smp(core, fl, 0.0, 2.0, "part")
    on_sep = smp(core, sep, 9.5, 12.5, "sep")
    # 原混音、人声轨上：整句；拉平成品上：换到它的时间（10 秒 = 局部 0 秒），两头的音素被这条轨的边界裁掉（◐）
    assert core.samples.get(whole)["analysis"] == "ok" and core.samples.get(on_sep)["analysis"] == "ok"
    v = core.speech.sample_view(part)
    ph = v["head"]["result"]["phones"]
    assert [(p["label"], round(p["start"], 6), round(p["end"], 6), bool(p.get("clipped"))) for p in ph] == [
        ("k", 0.0, 0.4, True), ("a", 0.4, 1.5, False), ("N", 1.5, 2.0, True)]
    assert v["units"][0]["partial"] and v["units"][0]["measuredOn"]["id"] == core.aid
    assert v["units"][0]["unitId"] == units.unit_id(seg, core.sid)
    assert core.samples.get(part)["analysis"] == "partial"
    layer = core.speech.for_asset(fl, 0.0, 2.0)
    assert [p["label"] for p in layer[0]["phones"]] == ["k", "a", "N"] and layer[0]["phones"][0]["start"] == pytest.approx(0.0)
    # 分析变了通知所有读这句的采样（不管在哪条轨上）
    assert core.speech.samples_reading([units.unit_id(seg, core.sid)]) == {whole, part, on_sep}
    # 回导成品读它自己那一份（还没有）
    re = track(core, "reimport", [[0, 9.5], [3, 12.5]], core.aid)
    on_re = smp(core, re, 0.0, 3.0, "re")
    assert core.samples.get(on_re)["analysis"] == "none" and core.speech.for_asset(re, 0.0, 3.0) == []


def test_tracks_without_voice_do_not_read_phonemes(core):
    seg = add_segment(core, 9.5, 12.5, "かん")
    add_analysis(core, 9.5, 12.5, PHONES, segment_id=seg)
    sfx = track(core, "separation", [[0, 0], [20, 20]], core.aid, ("sfx",), "effects")
    music = track(core, "separation", [[0, 0], [20, 20]], core.aid, (), "music")
    music_fl = track(core, "flatten", [[0, 10], [2, 12]], music)
    mix_fl = track(core, "flatten", [[0, 10], [2, 12]], core.aid)  # 原混音的拉平成品（没有角色）：含人声
    for aid in (sfx, music, music_fl):
        s = smp(core, aid, 0.0, 2.0) if aid == music_fl else smp(core, aid, 9.5, 12.5)
        assert core.samples.get(s)["analysis"] == "novoice" and core.speech.sample_view(s)["reason"] == "no-voice"
        assert core.speech.for_asset(aid, 0.0, 20.0) == []
    assert core.samples.get(smp(core, mix_fl, 0.0, 2.0))["analysis"] == "partial"
    # 不能在不含人声的轨上分析（写原因，不偷偷换轨）
    p = core.speech.preview("segments", [seg], False, sfx)
    assert p["run"] == 0 and p["blockedList"][0]["reason"] == "no-voice"
    # 给音乐声部开人声角色：立即读得到
    core.conn.execute("INSERT INTO asset_role(asset_id, role, state) VALUES (?, 'vocal', 'on')", (music,))
    assert len(core.speech.for_asset(music, 0.0, 20.0)) == 1


def test_analysis_only_on_tracks_covering_the_whole_segment(core):
    seg = add_segment(core, 9.5, 12.5, "かん")
    fl = track(core, "flatten", [[0, 10], [2, 12]], core.aid)
    p = core.speech.preview("segments", [seg], False, fl)
    assert p["run"] == 0 and p["blockedList"][0]["reason"] == "partial-track"
    # 采样入口：在原素材的分析音轨上测（没有默认人声轨 = 原混音），拉平成品上的采样和整句采样只分析一次
    a = smp(core, fl, 0.0, 2.0)
    b = smp(core, core.aid, 9.5, 12.5)
    plan = core.speech.plan("samples", [a, b], False)
    assert [(it["asset"], it["owner"]) for it in plan["run"]] == [(core.aid, units.unit_id(seg, core.sid))]
    # 详情区「添加台词…」发起的 seg:<段>@<采样所在的轨>：给这条轨上的读取方测（同采样入口选轨），不在半句的成品上硬测
    plan = core.speech.plan("units", [f"seg:{seg}@{fl}"], False)
    assert [(it["asset"], it["owner"]) for it in plan["run"]] == [(core.aid, units.unit_id(seg, core.sid))]
    # 没有默认人声轨时：采样在整轨人声上 → 就在它上面测（不退回原混音）；设了默认人声轨 → 在默认人声轨上测
    vox = track(core, "separation", [[0, 0], [20, 20]], core.aid, ("vocal",), "vocals")
    fl2 = track(core, "flatten", [[0, 10], [2, 12]], vox, ("vocal",))
    c = smp(core, fl2, 0.0, 2.0)
    assert core.speech.sample_track(core.speech._asset(fl2, {}), core.speech._segment(seg)) == vox
    vox2 = track(core, "separation", [[0, 0], [20, 20]], core.aid, ("vocal",), "vocals2")
    core.conn.execute("INSERT INTO default_track(source_id, role, asset_id) VALUES (?, 'vocal', ?)", (core.sid, vox2))
    assert core.speech.sample_track(core.speech._asset(fl2, {}), core.speech._segment(seg)) == vox2
    assert c


def test_manual_edit_from_a_partial_track_changes_only_what_it_covers(core):
    seg = add_segment(core, 9.5, 12.5, "かん")
    add_analysis(core, 9.5, 12.5, PHONES, segment_id=seg)
    fl = track(core, "flatten", [[0, 10], [2, 12]], core.aid)
    u = units.unit_id(seg, core.sid)
    seen = core.speech.sample_view(smp(core, fl, 0.0, 2.0))["units"][0]["head"]["result"]["phones"]
    edited = [{"label": p["label"], "start": p["start"], "end": p["end"]} for p in seen]
    edited[1]["end"] = edited[2]["start"] = 1.45  # 在拉平成品的时间里把 a/N 的边界往前挪 0.05 秒
    core.speech.save_manual(u, 1, edited, None, fl)
    run = core.conn.execute("SELECT r.result, r.manual FROM measure_head h JOIN measure_run r ON r.id=h.run_id WHERE h.owner_id=?", (u,)).fetchone()
    ph = loads(run["result"])["phones"]
    # 被边界裁过、没改的端点保持原值；改了的换回原素材秒
    assert run["manual"] == 1 and [(p["start"], p["end"]) for p in ph] == [(9.6, 10.4), (10.4, pytest.approx(11.45)), (pytest.approx(11.45), 12.4)]
    # 原混音上的采样同时生效
    whole = core.speech.sample_view(smp(core, core.aid, 9.5, 12.5))
    assert whole["head"]["result"]["phones"][1]["end"] == pytest.approx(11.45) and whole["head"]["manual"]


def test_back_track_chain_and_related(core):
    sep = track(core, "separation", [[0, 0], [20, 20]], core.aid, ("vocal",), "vocals")
    fl = track(core, "flatten", [[0, 10], [2, 12]], sep, ("vocal",))
    fl2 = track(core, "flatten", [[0, 10.5], [1, 11.5]], fl, ("vocal",))
    s = smp(core, fl2, 0.0, 1.0)
    row = core.samples.get(s)
    assert row["back_asset_id"] == sep and row["source_start"] == pytest.approx(10.5) and row["source_end"] == pytest.approx(11.5)
    ch = row["detail"]["chain"]
    assert [st["asset"]["id"] for st in ch["steps"]] == [fl2, fl, sep, core.aid] and ch["complete"]
    assert ch["steps"][1]["sourceStart"] == pytest.approx(10.0)
    assert lineage.back_track(core.conn, core.aid) == core.aid
    near = smp(core, core.aid, 11.0, 13.0, "near")
    smp(core, core.aid, 11.5, 13.0, "touch")  # 端点相接不算
    rel = core.samples.related(s)
    assert [r["sample"]["id"] for r in rel["rows"]] == [near] and rel["rows"][0]["overlap"] == pytest.approx(0.5)
    # 原素材页“采样”车道：原素材秒
    lane = {d["id"]: (d["start"], d["end"]) for d in text_layer.derived(core.conn, core.sid)}
    assert lane[s] == (pytest.approx(10.5), pytest.approx(11.5))


def _naming_analysis(core):
    seg = add_segment(core, 1.0, 2.4, "入部希望です")
    phones = []
    for i, (lab, w) in enumerate([("ny", 0), ("u", 0), ("u", 0), ("b", 0), ("u", 0), ("k", 1), ("i", 1), ("b", 1), ("o", 1), ("o", 1),
                                  ("d", 2), ("e", 2), ("s", 2), ("u", 2)]):
        phones.append({"label": lab, "start": round(1.0 + i * 0.1, 6), "end": round(1.1 + i * 0.1, 6), "mora": None, "word": w})
    words = [{"text": "入部", "start": 0, "end": 2, "reading": "", "mapped": True, "moraStart": 0},
             {"text": "希望", "start": 2, "end": 4, "reading": "", "mapped": True, "moraStart": 3},
             {"text": "です", "start": 4, "end": 6, "reading": "", "mapped": True, "moraStart": 6}]
    rid, _ = add_analysis(core, 1.0, 2.4, phones, segment_id=seg, text="入部希望です")
    res = loads(core.conn.execute("SELECT result FROM measure_run WHERE id=?", (rid,)).fetchone()[0])
    core.conn.execute("UPDATE measure_run SET result=? WHERE id=?", (dumps(res | {"words": words}), rid))
    return seg


def test_partial_naming(core):
    _naming_analysis(core)
    name = lambda a, b: core.samples.suggest(core.aid, a, b)["name"]  # noqa: E731
    assert name(1.0, 1.3) == "nyuu（入部希望です）"  # 只覆盖一个词的一部分 → 罗马字
    assert name(1.0, 1.5) == "入部（入部希望です）"  # 完整覆盖的词 → 原文
    assert name(1.0, 1.7) == "入部ki（入部希望です）"  # 7/14 = 一半，仍然算
    assert name(1.0, 1.8) == "入部希望です"  # 超过一半 → 照旧整句
    # 选区同时盖到音效提示 → 照旧“A / B”
    core.conn.execute("INSERT INTO sfx_hint(id, source_id, start, \"end\", text, origin, created_at, updated_at) VALUES (?, ?, 1.0, 1.2, '足音', 'manual', ?, ?)",
                      (new_id(), core.sid, now_iso(), now_iso()))
    assert name(1.0, 1.3) == "足音 / 入部希望です"


def test_romaji_and_name_length():
    assert naming.romaji("ch o cl t o".split()) == "chotto" and naming.romaji("m a cl t e".split()) == "matte"
    assert naming.romaji("k a cl".split()) == "ka" and naming.romaji("h o N d a pau".split()) == "honda"
    long = naming.partial_name("a", "x" * 600)
    assert len(long) <= 500 and long.endswith("…）")


def test_migration_0015(tmp_path: Path):
    conn = connect(tmp_path / "db.sqlite")
    base = bundled_migrations()
    migrate(conn, tmp_path / "bk", base[:14])
    ts = now_iso()
    x = conn.execute
    x("INSERT INTO source(id, path, work, episode, source_type, created_at, updated_at, duration) VALUES ('S', '/a.mkv', 'w', '1', 't', ?, ?, 100)", (ts, ts))
    x("INSERT INTO sound_asset(id, source_id, origin, stream_ordinal, duration, mapping, created_at) VALUES ('A', 'S', 'stream', 0, 100, '[[0,0],[100,100]]', ?)", (ts,))
    x("INSERT INTO sound_asset(id, source_id, origin, duration, mapping, input_asset_id, created_at) VALUES ('V', 'S', 'separation', 100, '[[0,0],[100,100]]', 'A', ?)", (ts,))
    x("INSERT INTO sound_asset(id, source_id, origin, duration, mapping, input_asset_id, created_at) VALUES ('R', 'S', 'reimport', 2, '[[0,10],[2,12]]', 'V', ?)", (ts,))
    x("INSERT INTO sound_asset(id, source_id, origin, duration, mapping, input_asset_id, created_at) VALUES ('F', 'S', 'flatten', 2, '[[0,10],[2,12]]', 'R', ?)", (ts,))
    x('INSERT INTO sample(id, asset_id, start, "end", name, created_via, created_at, updated_at) VALUES (\'P\', \'A\', 1, 3, \'p\', \'manual\', ?, ?)', (ts, ts))
    x('INSERT INTO sample(id, asset_id, start, "end", name, created_via, parent_sample_id, parent_label, origin, created_at, updated_at)'
      " VALUES ('C', 'F', 0.5, 1.5, 'c', 'processed', 'P', 'p', ?, ?, ?)", (dumps({"kind": "flatten", "job": "j", "idx": 0, "from": "P"}), ts, ts))
    x("INSERT INTO measure_run(id, kind, owner_type, owner_id, asset_id, inputs, status, manual, result, created_at) VALUES ('M', 'alignment', 'asset_text', 'seg:x@A', 'A', '{}', 'ok', 0, '{}', ?)", (ts,))
    x("INSERT INTO measure_head(owner_type, owner_id, kind, run_id) VALUES ('asset_text', 'seg:x@A', 'alignment', 'M')")
    migrate(conn, tmp_path / "bk")
    lin = {r[0]: (r[1], r[2]) for r in x("SELECT id, reimport_id, from_separation FROM sound_asset")}
    assert lin == {"A": (None, 0), "V": (None, 1), "R": ("R", 1), "F": ("R", 1)}
    cols = {r[1] for r in x("PRAGMA table_info(sample)")}
    assert "parent_sample_id" not in cols and "parent_label" not in cols
    assert tuple(x("SELECT src_start, src_end FROM sample WHERE id='C'").fetchone()) == (10.5, 11.5)
    assert loads(x("SELECT origin FROM sample WHERE id='C'").fetchone()[0]) == {"kind": "flatten", "job": "j", "idx": 0}
    assert x("SELECT COUNT(*) FROM measure_run WHERE owner_type='asset_text'").fetchone()[0] == 0
    assert x("SELECT COUNT(*) FROM measure_head WHERE owner_type='asset_text'").fetchone()[0] == 0
    x("INSERT INTO sound_asset(id, source_id, origin, duration, mapping, input_asset_id, created_at) VALUES ('F2', 'S', 'flatten', 1, '[[0,10.5],[1,11.5]]', 'F', ?)", (ts,))
    assert tuple(x("SELECT reimport_id, from_separation FROM sound_asset WHERE id='F2'").fetchone()) == ("R", 1)
    x('INSERT INTO sample(id, asset_id, start, "end", name, created_via, created_at, updated_at) VALUES (\'N\', \'F2\', 0.25, 0.75, \'n\', \'manual\', ?, ?)', (ts, ts))
    assert tuple(x("SELECT src_start, src_end FROM sample WHERE id='N'").fetchone()) == (10.75, 11.25)
    assert x("PRAGMA foreign_key_check").fetchall() == []


def test_release_keeps_phonemes_measured_on_a_dropped_track(core):
    """删除原素材、留下独立化采样：音素和文本层一起留下；测它用的人声轨只留一条记录（没有声音）。"""
    from test_independence import independ

    seg = add_segment(core, 9.5, 12.5, "かん")
    vox = track(core, "separation", [[0, 0], [20, 20]], core.aid, ("vocal",), "vocals")
    add_analysis(core, 9.5, 12.5, PHONES, segment_id=seg, asset_id=vox, snapshot={})
    keep = smp(core, core.aid, 9.5, 12.5, "keep")
    before = core.speech.sample_view(keep)["head"]
    assert before is not None and core.speech.sample_view(keep)["units"][0]["measuredOn"]["id"] == vox
    independ(core, [keep])
    core.sources.delete(core.sid, release=True)
    assert core.conn.execute("SELECT media_file_id FROM sound_asset WHERE id=?", (vox,)).fetchone()[0] is None
    after = core.speech.sample_view(keep)["head"]
    assert after is not None and after["runId"] == before["runId"]
