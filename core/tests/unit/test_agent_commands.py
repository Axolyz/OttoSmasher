"""阶段 A 挪进 Core 的命令：设默认轨 / 角色、画面绑定、按会话列出与撤回编辑。"""

from __future__ import annotations

import subprocess

import pytest

from conftest import make_sample, make_source
from ottosmasher.core.server import Core
from test_tracks import asset


@pytest.fixture
def core(tmp_path):
    c = Core(tmp_path / "ws", agent_link=False)
    c.open()
    yield c
    c.close()


def call(core, m, actor=None, **p):
    msg = {"id": 1, "m": m, "p": p}
    if actor:
        msg["actor"] = actor
    res = core.dispatch(msg)
    assert res is not None
    return res


def ok(res):
    assert res["ok"], res
    return res["r"]


def defaults(core, sid):
    return dict(core.conn.execute("SELECT role, asset_id FROM default_track WHERE source_id=?", (sid,)).fetchall())


def test_set_default_gives_role_and_undoes_in_one_step(core):
    sid = make_source(core.conn)
    core.conn.execute("UPDATE source SET duration=100 WHERE id=?", (sid,))
    mix = asset(core.conn, sid)
    r = ok(call(core, "tracks.setDefault", sourceId=sid, role="vocal", assetId=mix))
    assert r["edit_id"] and defaults(core, sid) == {"vocal": mix}
    assert ok(call(core, "assets.get", id=mix))["roles"] == ["vocal"]
    ok(call(core, "edits.undo"))  # 一次撤销同时撤回角色与默认轨
    assert defaults(core, sid) == {} and ok(call(core, "assets.get", id=mix))["roles"] == []
    ok(call(core, "tracks.setDefault", sourceId=sid, role="vocal", assetId=mix))
    ok(call(core, "tracks.setDefault", sourceId=sid, role="vocal", assetId=None))
    assert defaults(core, sid) == {} and ok(call(core, "assets.get", id=mix))["roles"] == ["vocal"]
    assert call(core, "tracks.setDefault", sourceId=sid, role="vocal", assetId="nope")["e"]["code"] == "asset-not-found"


def test_role_off_clears_default(core):
    sid = make_source(core.conn)
    core.conn.execute("UPDATE source SET duration=100 WHERE id=?", (sid,))
    mix = asset(core.conn, sid)
    ok(call(core, "tracks.setDefault", sourceId=sid, role="sfx", assetId=mix))
    ok(call(core, "tracks.setRole", assetId=mix, role="vocal", on=True))
    assert sorted(ok(call(core, "assets.get", id=mix))["roles"]) == ["sfx", "vocal"]
    ok(call(core, "tracks.setRole", assetId=mix, role="sfx", on=False))
    assert ok(call(core, "assets.get", id=mix))["roles"] == ["vocal"] and defaults(core, sid) == {}


def test_visual_bind_and_unbind(core, tmp_path):
    png = tmp_path / "pic.png"
    subprocess.run(["ffmpeg", "-v", "error", "-f", "lavfi", "-i", "color=c=red:s=64x36:d=0.1", "-frames:v", "1", str(png)], check=True)
    sid = make_source(core.conn)
    core.conn.execute("UPDATE source SET duration=100 WHERE id=?", (sid,))
    smp = make_sample(core.conn, asset(core.conn, sid), name="nyuu")
    r = ok(call(core, "visuals.bind", ownerType="sample", ownerId=smp, path=str(png)))
    b = ok(call(core, "visuals.forSample", id=smp))["binding"]
    assert b["origin"] == "sample" and b["mode"] == "image"  # 按文件认出图片
    label = core.conn.execute("SELECT label_args FROM edit WHERE id=?", (r["edit_id"],)).fetchone()[0]
    assert "nyuu" in label
    ok(call(core, "visuals.bind", ownerType="sample", ownerId=smp, path=None))
    assert (ok(call(core, "visuals.forSample", id=smp))["binding"] or {}).get("origin") != "sample"
    assert call(core, "visuals.bind", ownerType="sample", ownerId="nope", path=None)["e"]["code"] == "sample-not-found"


def _set(core, key, value, actor=None):
    v = ok(call(core, "settings.list"))[key]["version"]
    return ok(call(core, "edits.apply", actor, batch={"ops": [{"entity": "setting", "id": key, "version": v, "fields": {"value": value}}]}))


def test_history_and_undo_session(core):
    agent = {"kind": "agent", "session": "s1"}
    a = _set(core, "jobs.concurrency_light", 3, agent)
    b = _set(core, "jobs.concurrency_model", 2, agent)
    other = _set(core, "jobs.concurrency_light", 4, {"kind": "agent", "session": "s2"})
    hist = ok(call(core, "edits.history", session="s1"))
    assert [h["edit_id"] for h in hist] == [b["edit_id"], a["edit_id"]]
    assert hist[0]["actor"] == {"kind": "agent", "session": "s1"} and hist[0]["changes"] == 1
    assert {h["edit_id"] for h in ok(call(core, "edits.history", actorKind="agent"))} == {a["edit_id"], b["edit_id"], other["edit_id"]}
    # s2 后来又改了 a 改过的那项 → 撤到 a 就停下
    r = ok(call(core, "edits.undoSession", session="s1"))
    assert r["undone"] == 1 and r["blocked"]["edit_id"] == a["edit_id"] and r["remaining"] == 1
    s = ok(call(core, "settings.list"))
    assert s["jobs.concurrency_model"]["value"] == 1 and s["jobs.concurrency_light"]["value"] == 4
    # s2 撤回后，s1 剩下的也能撤
    assert ok(call(core, "edits.undoSession", session="s2"))["undone"] == 1
    r = ok(call(core, "edits.undoSession", session="s1"))
    assert r == {"undone": 1, "blocked": None, "remaining": 0}
    assert ok(call(core, "settings.list"))["jobs.concurrency_light"]["value"] == ok(call(core, "settings.list"))["jobs.concurrency_light"]["default"]
    assert ok(call(core, "edits.undoSession", session="s1")) == {"undone": 0, "blocked": None, "remaining": 0}


def test_pitch_search_scope_keeps_tag_conditions(core):
    """以前 search.pitch 的范围没声明 tags / expr，参数校验时被静默丢掉（P6）。"""
    cmd = core.api.get("search.pitch")
    p = cmd.parse({"blocks": [], "mode": "samples", "scope": {"tags": {"expr": "topic:game"}, "expr": "character:*", "natures": ["speech"]}})
    assert p["scope"] == {"tags": {"expr": "topic:game"}, "expr": "character:*", "natures": ["speech"]}
    # 原片音轨模式：采样专用条件明确拒绝，不静默忽略
    r = call(core, "search.pitch", blocks=[{"seconds": 0.3, "low": "C4"}], mode="sources", scope={"languages": ["ja"]})
    assert (r["e"]["code"], r["e"]["args"]["field"]) == ("search-invalid", "languages"), r
