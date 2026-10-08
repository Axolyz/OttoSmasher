"""来源标记（ROADMAP L1 / Q23）：编辑记录、任务、新建原片 / 资产 / 采样记下“谁做的”，缺省 user；RPC 可带 actor。"""

import pytest

from conftest import make_asset, make_sample, make_source
from ottosmasher.core import actor
from ottosmasher.core.edits import EditService
from ottosmasher.core.server import Core


def who(db, table, row_id):
    return tuple(db.execute(f"SELECT actor_kind, actor_session FROM {table} WHERE id=?", (row_id,)).fetchone())


def test_default_user_and_acting(db):
    actor.install(db)
    sid = make_source(db)
    assert who(db, "source", sid) == ("user", None)
    with actor.acting(db, "agent", "sess-1"):
        aid = make_asset(db, sid)
        smp = make_sample(db, aid)
        r = EditService(db).apply({"ops": [{"entity": "sample", "id": smp, "version": 1, "fields": {"name": "x"}}]})
    assert who(db, "sound_asset", aid) == ("agent", "sess-1")
    assert who(db, "sample", smp) == ("agent", "sess-1")
    assert who(db, "edit", r["edit_id"]) == ("agent", "sess-1")
    # 结束后恢复为 user
    assert who(db, "source", make_source(db, path="/b.mkv")) == ("user", None)


def test_without_install_defaults_to_user(db):
    sid = make_source(db)
    with actor.acting(db, "script", "s"):  # 没装触发器：不报错，列默认值
        sid2 = make_source(db, path="/c.mkv")
    assert who(db, "source", sid) == who(db, "source", sid2) == ("user", None)


@pytest.mark.parametrize("bad", ["x", {"kind": "robot"}, {"kind": "agent", "session": ""}, {"kind": "agent", "session": 3}])
def test_parse_rejects_bad_actor(bad):
    with pytest.raises(ValueError):
        actor.parse(bad)


def test_rpc_actor(tmp_path):
    srv = Core(tmp_path / "ws")
    srv.open()
    try:
        res = srv.dispatch({"id": 1, "m": "edits.apply", "p": {"batch": {"ops": [{"entity": "setting", "id": "jobs.concurrency_light", "version": 0, "fields": {"value": 3}}]}}, "actor": {"kind": "script", "session": "run-7"}})
        assert res["ok"], res
        assert who(srv.conn, "edit", res["r"]["edit_id"]) == ("script", "run-7")
        bad = srv.dispatch({"id": 2, "m": "core.hello", "p": {}, "actor": {"kind": "robot"}})
        assert not bad["ok"] and bad["e"]["code"] == "bad-request"
    finally:
        srv.close()
