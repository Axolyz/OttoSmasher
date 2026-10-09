"""拉平的 Core 侧（规格 11 §11.2、§11.4、16 R17）：对齐的选取（同一物理声音、覆盖外选区）、仅元音 / 首元音起的区间、人工版本不收紧、
缓存预估（只读已测的 F0）、批量里没有对齐的项单独失败、pitch: 标签按绑定资产实时求值。"""

from __future__ import annotations

import subprocess
from pathlib import Path

import numpy as np
import pytest

from ottosmasher.core import effective_tags
from analysis_helpers import add_analysis
from ottosmasher.core.clock import new_id, now_iso
from ottosmasher.core.edits import dumps, loads
from ottosmasher.core.errors import CoreError
from ottosmasher.core.server import Core
from ottosmasher.models import f0store


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


def sample(c, start, end, name="s", asset=None):
    return c.samples.create(asset or c.aid, start, end, name=name, nature="speech")["id"]


PHONES = [
    {"label": "k", "start": 1.0, "end": 1.05},
    {"label": "a", "start": 1.05, "end": 1.4, "eff": [1.1, 1.38]},
    {"label": "cl", "start": 1.4, "end": 1.5},
    {"label": "N", "start": 1.5, "end": 2.2, "eff": [1.5, 2.15]},
]


def alignment(c, owner, start, end, *, manual=False, snapshot=None, phones=PHONES):
    """在 [start, end) 上登记一段及它在这条资产上的一次成功分析（采样、选区按范围读到它）。"""
    rid, _ = add_analysis(c, start, end, phones, manual=manual, snapshot=snapshot)
    return rid


def test_alignment_intervals_first_vowel_and_vowels_only(core):
    s = sample(core, 1.0, 2.0)
    alignment(core, s, 1.0, 2.0)
    op = core.flatten.open(core.aid, 1.0, 2.0, "detail", s)
    assert op["alignment"]["manual"] is False
    assert [p["label"] for p in op["alignment"]["phones"]] == ["k", "a", "cl", "N"]
    assert op["alignment"]["phones"][-1]["end"] == pytest.approx(1.0)  # 裁到外选区（输入局部秒）
    tok = op["token"]
    # 令牌经过界面（JS）：不能带超过 2^53 的整数（mtime_ns），快照写成字符串指纹
    assert isinstance(tok["snapshot"], str) and "_snap" not in tok
    assert all(not isinstance(v, int) or abs(v) < 2**53 for v in tok.values())
    est = core.flatten.estimate(tok, {"range": "first", "target": "edge", "side": "left"}, s)
    assert est["status"] == "in-job"  # 还没测过 F0
    assert est["intervals"] == [pytest.approx([0.1, 1.0])]  # 首个元音的有效起点（收紧后）
    est = core.flatten.estimate(tok, {"range": "vowels", "target": "auto"}, s)
    assert est["intervals"] == [pytest.approx([0.1, 0.38]), pytest.approx([0.5, 1.0])]
    # 送进任务的音素：输入局部秒、原始标签；指纹含对齐内容
    it = core.flatten._item(0, tok, core.flatten._options({"range": "vowels", "target": "auto"}, batch=False), "n", s, core.flatten._versions())
    assert it["phones"][1] == ["a", pytest.approx(0.05), pytest.approx(0.4)] and it["manual"] is False
    assert it["frames"] == [48000, 96000]


def test_manual_alignment_is_not_tightened(core):
    s = sample(core, 1.0, 2.0)
    alignment(core, s, 1.0, 2.0, manual=True)
    tok = core.flatten.open(core.aid, 1.0, 2.0, "detail", s)["token"]
    est = core.flatten.estimate(tok, {"range": "vowels", "target": "auto"}, s)
    assert est["intervals"] == [pytest.approx([0.05, 0.4]), pytest.approx([0.5, 1.0])]


def test_alignment_must_cover_the_selection_and_be_the_same_physical_sound(core):
    s = sample(core, 1.0, 2.0)
    alignment(core, s, 1.2, 2.0)  # 没有覆盖外选区
    tok = core.flatten.open(core.aid, 1.0, 2.0, "single", s)["token"]
    with pytest.raises(CoreError) as e:
        core.flatten.estimate(tok, {"range": "first", "target": "auto"}, s)
    assert e.value.code == "flatten-needs-alignment"
    alignment(core, s, 1.0, 2.0, snapshot={"size": 1, "mtime_ns": 2})  # 文件快照不同 = 别的声音
    assert core.flatten.open(core.aid, 1.0, 2.0, "single", s)["alignment"] is None
    # 判定区间读到的段只要有一段不可用（这里是别的声音上测的）→ 不可用；只剩覆盖它的那一段时可以用
    big = sample(core, 0.5, 3.0)
    alignment(core, big, 0.5, 3.0)
    assert core.flatten.open(core.aid, 1.0, 2.0, "single", s)["alignment"] is None
    core.conn.execute('UPDATE text_segment SET deleted=1 WHERE NOT (abs(start-0.5)<1e-9 AND abs("end"-3.0)<1e-9)')
    op = core.flatten.open(core.aid, 1.0, 2.0, "single", s)
    assert op["alignment"] is not None and op["name"] == "s"


def test_estimate_reads_cached_f0_only(core):
    s = sample(core, 1.0, 2.0)
    alignment(core, s, 1.0, 2.0)
    _, ident = core.speech.f0_identity(core.aid, 0.0, 20.0)
    n = f0store.total_frames(20.0)
    t = (np.arange(n) * 160 + 80) / 16000
    fr = np.zeros((n, 3), dtype=np.float32)
    fr[:, 0] = np.where(t < 1.5, 440.0, 660.0)
    fr[:, 1] = 0.9
    fr[:, 2] = 0.01
    src = core.ws.data / "f.npy"
    np.save(src, fr)
    f0store.adopt_chunk(core.ws.f0, core.aid, ident, 0, src, {})
    tok = core.flatten.open(core.aid, 1.0, 2.0, "detail", s)["token"]
    left = core.flatten.estimate(tok, {"range": "first", "target": "edge", "side": "left"}, s)
    assert left["status"] == "ok" and left["target"]["name"] == "A4" and left["target"]["ref"] == pytest.approx([0.1, 0.2])
    right = core.flatten.estimate(tok, {"range": "first", "target": "edge", "side": "right"}, s)
    assert right["target"]["name"] == "E5"
    whole = core.flatten.estimate(tok, {"range": "whole", "target": "auto"}, s)
    assert whole["status"] == "ok" and whole["target"]["name"] in ("A4", "E5")
    # 缓存里证据不足：给出原因，不换侧
    fr[(t >= 1.0) & (t < 1.2), 1] = 0.0
    np.save(src, fr)
    for p in (core.ws.f0 / core.aid / ident).glob("*.npy"):
        p.unlink()
    f0store.adopt_chunk(core.ws.f0, core.aid, ident, 0, src, {})
    ins = core.flatten.estimate(tok, {"range": "first", "target": "edge", "side": "left"}, s)
    assert ins["status"] == "insufficient" and ins["error"]["code"] == "flatten-edge-insufficient"


def test_batch_items_without_alignment_fail_individually(core):
    ok = sample(core, 1.0, 2.0, "ok")
    alignment(core, ok, 1.0, 2.0)
    bad = sample(core, 5.0, 6.0, "bad")
    o = core.flatten._options({"range": "vowels", "target": "auto"}, batch=True)
    items = core.flatten._batch_items([ok, bad], o, core.flatten._versions())
    assert "error" not in items[0] and items[0]["phones"]
    assert items[1]["error"]["code"] == "flatten-needs-alignment"
    with pytest.raises(CoreError):
        core.flatten._options({"range": "whole", "target": "manual", "manual": "A4"}, batch=True)


def test_defaults_follow_settings(core):
    from ottosmasher.core import settings as settings_mod
    from ottosmasher.core.flatten import defaults_for

    v = settings_mod.values(core.conn)
    assert defaults_for(v, "detail") == {"range": "first", "target": "edge", "side": "left"}
    assert defaults_for(v, "single") == {"range": "whole", "target": "auto", "side": "left"}
    assert defaults_for(v, "batch") == {"range": "vowels", "target": "auto", "side": "left"}


def test_pitch_tag_follows_the_bound_asset(core):
    """pitch: 取登记时记录的目标音；在成品上再截取也带；同范围绑回原音频则不带（11 §11.4）。"""
    a = core.conn.execute("SELECT * FROM sound_asset WHERE id=?", (core.aid,)).fetchone()
    fid = new_id()
    prod = {"op": "flatten", "target": {"name": "G♯5", "midi": 80}}
    core.conn.execute(
        "INSERT INTO sound_asset(id, source_id, origin, media_file_id, duration, mapping, input_asset_id, input_start, input_end, production, created_at)"
        " VALUES (?, ?, 'flatten', ?, 1.0, ?, ?, 1.0, 2.0, ?, ?)",
        (fid, core.sid, a["media_file_id"], dumps([[0, 1.0], [1.0, 2.0]]), core.aid, dumps(prod), now_iso()),
    )
    core.conn.execute("INSERT INTO asset_storage(asset_id, range_start, range_end, media_file_id, kind) VALUES (?, 0, 1.0, ?, 'primary')", (fid, a["media_file_id"]))
    core.conn.execute("UPDATE media_file SET sample_rate=48000 WHERE id=?", (a["media_file_id"],))  # 伪成品借用原文件，补上采样率
    whole = sample(core, 0.0, 1.0, "w", asset=fid)
    sub = sample(core, 0.2, 0.5, "sub", asset=fid)
    back = sample(core, 1.0, 2.0, "back")
    tags = lambda sid: {(t["tag"], t["provenance"]) for t in effective_tags.of_sample(core.conn, sid)}  # noqa: E731
    assert ("pitch:G♯5", "auto") in tags(whole)
    assert ("pitch:G♯5", "auto") in tags(sub)
    assert not any(t.startswith("pitch:") for t, _ in tags(back))
    # 本地同名标签优先（04 §4.2.9）
    assert loads(core.conn.execute("SELECT production FROM sound_asset WHERE id=?", (fid,)).fetchone()[0])["target"]["name"] == "G♯5"
