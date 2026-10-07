"""角色与默认轨：规格 04 §4.2.3、05 §5.4；16 R2.1–R2.5。"""

import pytest

from conftest import make_source
from ottosmasher.core import assets as assets_mod
from ottosmasher.core.clock import new_id, now_iso
from ottosmasher.core.edits import EditService, dumps
from ottosmasher.core.errors import CoreError

DUR = 100.0


@pytest.fixture
def src(db):
    sid = make_source(db)
    db.execute("UPDATE source SET duration=? WHERE id=?", (DUR, sid))
    return sid


def asset(db, sid, *, origin="stream", mapping=None, duration=DUR, ordinal=0, stem=None, snapshot="snap-a", roles=()):
    mid = new_id()
    db.execute(
        "INSERT INTO media_file(id, path, location, file_snapshot, created_at) VALUES (?, ?, 'library', ?, ?)",
        (mid, f"/lib/{mid}.mp3", snapshot, now_iso()),
    )
    aid = new_id()
    db.execute(
        "INSERT INTO sound_asset(id, source_id, origin, media_file_id, stream_ordinal, duration, mapping, stem_name, created_at)"
        " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (aid, sid, origin, mid, ordinal if origin == "stream" else None, duration, dumps(mapping or [[0, 0], [DUR, DUR]]), stem, now_iso()),
    )
    for r in roles:
        db.execute("INSERT INTO asset_role(asset_id, role, state) VALUES (?, ?, 'on')", (aid, r))
    return aid


def roles(db, aid):
    return assets_mod.get(db, aid)["roles"]


def set_default(edits, db, sid, role, aid, extra=()):
    v = db.execute("SELECT version FROM source WHERE id=?", (sid,)).fetchone()[0]
    return edits.apply({"ops": [*extra, {"entity": "source", "id": sid, "version": v, "fields": {f"default_{role}": aid}}]})


def test_tracks_lists_streams_and_full_tracks_only(db, src):
    mix = asset(db, src)
    vocals = asset(db, src, origin="separation", stem="vocals", snapshot="v", roles=["vocal"])
    clip = asset(db, src, origin="separation", stem="vocals", snapshot="c", duration=0.3, mapping=[[0, 10], [0.3, 10.3]], roles=["vocal"])
    warped = asset(db, src, origin="separation", stem="vocals", snapshot="w", mapping=[[0, 0], [50, 20], [DUR, DUR]], roles=["vocal"])
    ids = [t["id"] for t in assets_mod.tracks(db, src)["tracks"]]
    assert ids == [mix, vocals]  # R2.1 逐句片段不出现；R2.2 变速的不是整轨
    edits = EditService(db)
    for bad in (clip, warped):
        with pytest.raises(CoreError) as e:
            set_default(edits, db, src, "vocal", bad)
        assert (e.value.code, e.value.args_["reason"]) == ("edit-invalid", "not-full-track")


def test_same_content_full_tracks_shown_once_prefer_default(db, src):
    a = asset(db, src, origin="separation", stem="vocals", snapshot="same", roles=["vocal"])
    b = asset(db, src, origin="separation", stem="vocals", snapshot="same", roles=["vocal"])
    t = assets_mod.tracks(db, src)["tracks"]
    assert [(x["id"], x["duplicates"]) for x in t] == [(a, 1)]
    set_default(EditService(db), db, src, "vocal", b)
    t = assets_mod.tracks(db, src)["tracks"]
    assert [(x["id"], x["duplicates"]) for x in t] == [(b, 1)]


def test_default_needs_role_and_role_plus_default_in_one_undoable_batch(db, src):
    mix = asset(db, src)
    edits = EditService(db)
    with pytest.raises(CoreError) as e:
        set_default(edits, db, src, "vocal", mix)  # 原混音没有角色
    assert e.value.args_["reason"] == "missing-role"
    # 「同时赋予人声角色」：一次批次里加角色并设为默认
    set_default(edits, db, src, "vocal", mix, extra=[{"entity": "asset", "id": mix, "version": 1, "fields": {"roles": ["vocal"]}}])
    assert roles(db, mix) == ["vocal"]
    assert assets_mod.tracks(db, src)["defaults"] == {"vocal": mix}
    # 默认轨的角色不能单独去掉
    with pytest.raises(CoreError) as e:
        edits.apply({"ops": [{"entity": "asset", "id": mix, "version": 2, "fields": {"roles": []}}]})
    assert e.value.args_["reason"] == "still-default"
    # 撤销一次：角色与默认都回去
    edits.undo()
    assert roles(db, mix) == []
    assert assets_mod.tracks(db, src)["defaults"] == {}


def test_role_aliases_and_user_removal_is_respected(db, src):
    aliases = assets_mod.validate_role_aliases([["Vocals", "vocal"], ["dialog", "vocal"], ["effect", "sfx"], ["mix", "vocal"], ["mix", "sfx"]])
    assert assets_mod.roles_for_stem("vocals", aliases) == ["vocal"]
    assert assets_mod.roles_for_stem("EFFECT ", aliases) == ["sfx"]
    assert assets_mod.roles_for_stem("instrument", aliases) == []
    assert assets_mod.roles_for_stem("mix", aliases) == ["sfx", "vocal"]
    with pytest.raises(CoreError):
        assets_mod.validate_role_aliases([["vocals", "music"]])
    # R2.5：预填后用户移除 → 再次预填不加回
    a = asset(db, src, origin="separation", stem="vocals", snapshot="v")
    assert assets_mod.prefill_roles(db, a, ["vocal"]) == ["vocal"]
    EditService(db).apply({"ops": [{"entity": "asset", "id": a, "version": 1, "fields": {"roles": []}}]})
    assert assets_mod.prefill_roles(db, a, ["vocal"]) == []
    assert roles(db, a) == []
    # 用户自己再加回来可以
    EditService(db).apply({"ops": [{"entity": "asset", "id": a, "version": 2, "fields": {"roles": ["vocal"]}}]})
    assert roles(db, a) == ["vocal"]


def test_changing_default_does_not_rebind_existing_samples(db, src):
    """R2.4：更换默认轨后，旧采样的绑定不变。"""
    a = asset(db, src, origin="separation", stem="vocals", snapshot="a", roles=["vocal"])
    b = asset(db, src, origin="separation", stem="dialog", snapshot="b", roles=["vocal"])
    edits = EditService(db)
    set_default(edits, db, src, "vocal", a)
    smp = new_id()
    db.execute(
        "INSERT INTO sample(id, asset_id, start, \"end\", name, created_via, created_at, updated_at) VALUES (?, ?, 1, 2, 'x', 'subtitle', ?, ?)",
        (smp, a, now_iso(), now_iso()),
    )
    set_default(edits, db, src, "vocal", b)
    assert db.execute("SELECT asset_id FROM sample WHERE id=?", (smp,)).fetchone()[0] == a
