"""本机 agent 端点（阶段 A）：Core 作为独立进程跑，界面一侧走 stdio，命令行一侧走端点。"""

from __future__ import annotations

import json
import os
import sqlite3
import subprocess
import sys
import threading
import time

import pytest

from ottosmasher.cli.client import LinkClient
from ottosmasher.core import agent_link
from ottosmasher.core.errors import CoreError
from ottosmasher.store.workspace import Workspace

from test_core_process import CoreProc

pytestmark = pytest.mark.skipif(sys.platform == "win32", reason="Windows 未验收（L47）")


@pytest.fixture
def app(tmp_path, monkeypatch):
    monkeypatch.setenv("OTTO_AGENT_CONFIRM_SECONDS", "3")
    root = tmp_path / "空格 工作区 [x]"
    c = CoreProc(root)
    yield c, root
    c.p.stdin.close()
    c.p.wait(timeout=20)


def _events(c: CoreProc, name: str) -> list:
    return [e for e in c.events if e.get("e") == name]


def _wait_ui_event(c: CoreProc, pred, timeout=10.0):
    return c.wait_event(lambda e: e.get("t") == "evt" and pred(e), timeout)


def test_endpoint_file_and_hello(app):
    c, root = app
    info = json.loads((Workspace(root).data / "agent-endpoint.json").read_text())
    assert info["pid"] == c.p.pid and info["family"] in ("AF_UNIX", "AF_PIPE")
    if info["family"] == "AF_UNIX":
        assert oct(os.stat(Workspace(root).data / "agent-endpoint.json").st_mode & 0o777) == "0o600"
    with LinkClient(root, session="s-1") as a:
        assert a.hello["workspace"] == str(root) and a.hello["peer"]
        sess = c.call("agent.sessions")["r"]
        assert [(s["kind"], s["session"]) for s in sess] == [("agent", "s-1")]
        _wait_ui_event(c, lambda e: e["e"] == "agent.sessions" and len(e["d"]) == 1)
    _wait_ui_event(c, lambda e: e["e"] == "agent.sessions" and e["d"] == [])


def test_wrong_key_refused(app):
    c, root = app
    info = agent_link.read_endpoint(Workspace(root).data)
    with pytest.raises(CoreError) as ei:
        agent_link.connect({**info, "key": "00" * 32}, {"kind": "agent"})
    assert ei.value.code == "agent-link-failed"
    with pytest.raises(CoreError):
        agent_link.connect(info, {"kind": "user"})  # 不能声明自己是用户
    assert c.call("core.hello")["ok"]  # Core 不受影响


def test_writes_are_recorded_as_agent_and_broadcast(app):
    c, root = app
    with LinkClient(root, session="run-42") as a, LinkClient(root, kind="script", session="other") as b:
        settings = a.call("settings.list")
        v = settings["jobs.concurrency_light"]["version"]
        # 消息里自称 user 也不算数
        a.conn.send_bytes(agent_link.pack({"t": "req", "id": 99, "m": "edits.apply", "actor": {"kind": "user"},
                                           "p": {"batch": {"ops": [{"entity": "setting", "id": "jobs.concurrency_light", "version": v, "fields": {"value": 3}}]}}}))
        while True:
            msg = a._recv(10)
            if msg.get("t") == "res":
                assert msg["id"] == 99 and msg["ok"], msg
                break
        # 另一个连接与界面都收到资料变化；界面那份不带请求标记（P8：别处的改动）
        ev = b.next_event(10)
        while ev["e"] != "data.changed":
            ev = b.next_event(10)
        ui = _wait_ui_event(c, lambda e: e["e"] == "data.changed")
        assert "req" not in ui
        assert b.call("core.hello")["pid"] == c.p.pid
    conn = sqlite3.connect(f"file:{Workspace(root).db_path}?mode=ro", uri=True)
    row = conn.execute("SELECT actor_kind, actor_session FROM edit ORDER BY rowid DESC LIMIT 1").fetchone()
    conn.close()
    assert row == ("agent", "run-42")


def test_interface_commands_forbidden(app):
    c, root = app
    with LinkClient(root) as a:
        for m, p in (("ui.set", {"page": "x", "key": "y", "value": 1}), ("app.quit", {}), ("agent.confirmReply", {"id": "x", "approve": True})):
            with pytest.raises(CoreError) as ei:
                a.call(m, p)
            assert ei.value.code == "agent-command-forbidden", m
    assert c.call("core.hello")["ok"]


def _ask_delete(a: LinkClient, out: dict) -> threading.Thread:
    def run():
        out["res"] = a.request("samples.delete", {"ids": ["no-such-sample"]}, timeout=30)
    t = threading.Thread(target=run)
    t.start()
    return t


def test_dangerous_command_waits_for_owner(app):
    c, root = app
    with LinkClient(root, session="d") as a:
        # 拒绝
        out: dict = {}
        t = _ask_delete(a, out)
        ev = _wait_ui_event(c, lambda e: e["e"] == "agent.confirm")
        assert ev["d"]["method"] == "samples.delete" and ev["d"]["actor"] == {"kind": "agent", "session": "d"}
        assert ev["d"]["preview"] == {"count": 1, "names": []}
        assert c.call("agent.confirmReply", id=ev["d"]["id"], approve=False)["ok"]
        t.join(10)
        assert out["res"]["e"]["code"] == "agent-confirm-declined"
        # 同意 → 真的执行（这里执行结果是“没有这个采样”）
        c.events.clear()
        out = {}
        t = _ask_delete(a, out)
        ev = _wait_ui_event(c, lambda e: e["e"] == "agent.confirm")
        assert c.call("agent.confirmReply", id=ev["d"]["id"], approve=True)["ok"]
        t.join(10)
        assert out["res"]["e"]["code"] == "sample-not-found"
        # 再回答一次 → 已经没有了
        r = c.call("agent.confirmReply", id=ev["d"]["id"], approve=True)
        assert r["e"]["code"] == "agent-confirm-unknown"
        # 没人回答 → 超时（测试里 3 秒）
        c.events.clear()
        out = {}
        t0 = time.monotonic()
        t = _ask_delete(a, out)
        _wait_ui_event(c, lambda e: e["e"] == "agent.confirm")
        t.join(15)
        assert out["res"]["e"]["code"] == "agent-confirm-timeout" and time.monotonic() - t0 >= 2.5
        _wait_ui_event(c, lambda e: e["e"] == "agent.confirmClosed")


def test_pending_confirmation_dropped_when_connection_closes(app):
    c, root = app
    a = LinkClient(root)
    a.send("samples.delete", {"ids": ["x"]})
    ev = _wait_ui_event(c, lambda e: e["e"] == "agent.confirm")
    a.close()
    _wait_ui_event(c, lambda e: e["e"] == "agent.confirmClosed" and e["d"]["id"] == ev["d"]["id"])
    assert c.call("agent.confirmReply", id=ev["d"]["id"], approve=True)["e"]["code"] == "agent-confirm-unknown"


def test_app_not_running(tmp_path):
    root = tmp_path / "ws"
    c = CoreProc(root)
    assert (Workspace(root).data / "agent-endpoint.json").exists()
    c.p.stdin.close()
    c.p.wait(timeout=20)
    assert not (Workspace(root).data / "agent-endpoint.json").exists()
    with pytest.raises(CoreError) as ei:
        LinkClient(root)
    assert ei.value.code == "app-not-running"


def test_confirmation_default_limit_and_missed_requests(tmp_path, monkeypatch):
    # 所有者 2026-10-24 定：缺省限时 2 分钟；超时或连接断了的请求记进“错过的请求”，所有者回来能看到
    monkeypatch.delenv("OTTO_AGENT_CONFIRM_SECONDS", raising=False)
    root = tmp_path / "ws"
    c = CoreProc(root)
    try:
        a = LinkClient(root, session="late")
        a.send("samples.delete", {"ids": ["x"]})
        ev = _wait_ui_event(c, lambda e: e["e"] == "agent.confirm")
        assert ev["d"]["seconds"] == 120
        a.close()
        missed = _wait_ui_event(c, lambda e: e["e"] == "agent.missed")["d"]
        assert [(m["id"], m["reason"], m["method"], m["actor"]["session"]) for m in missed] == [(ev["d"]["id"], "closed", "samples.delete", "late")]
        assert c.call("agent.missed")["r"] == missed
        assert c.call("agent.dismissMissed")["ok"] and c.call("agent.missed")["r"] == []
    finally:
        c.p.stdin.close()
        c.p.wait(timeout=20)


def test_timeout_is_recorded_as_missed(app):
    c, root = app
    with LinkClient(root, session="t") as a:
        out: dict = {}
        t = _ask_delete(a, out)
        _wait_ui_event(c, lambda e: e["e"] == "agent.confirm")
        t.join(15)
        assert out["res"]["e"]["code"] == "agent-confirm-timeout"
        missed = _wait_ui_event(c, lambda e: e["e"] == "agent.missed")["d"]
        assert missed[0]["reason"] == "timeout" and missed[0]["preview"] == {"count": 1, "names": []}


def test_approval_rechecks_the_data(app, tmp_path):
    # 放行时资料和提问时不一样（这里：采样被改了名）→ 不执行，带新预览重新问；再放行才执行
    c, root = app
    wav = tmp_path / "a.wav"
    subprocess.run(["ffmpeg", "-v", "error", "-f", "lavfi", "-i", "sine=f=440:sample_rate=48000:duration=2", str(wav)], check=True)
    sid = c.call("sources.add", paths=[str(wav)])["r"][0]["sourceId"]
    aid = c.call("assets.listForSource", sourceId=sid)["r"][0]["id"]
    smp = c.call("samples.create", assetId=aid, start=0.2, end=1.2, name="before")["r"]
    with LinkClient(root, session="r") as a:
        out: dict = {}
        t = threading.Thread(target=lambda: out.update(res=a.request("samples.delete", {"ids": [smp["id"]]}, timeout=30)))
        t.start()
        ev = _wait_ui_event(c, lambda e: e["e"] == "agent.confirm")
        assert ev["d"]["preview"]["names"] == ["before"]
        cur = c.call("samples.get", id=smp["id"])["r"]
        assert c.call("edits.apply", batch={"ops": [{"entity": "sample", "id": smp["id"], "version": cur["version"], "fields": {"name": "after"}}]})["ok"]
        c.events.clear()
        r = c.call("agent.confirmReply", id=ev["d"]["id"], approve=True)
        assert r["r"] == {"reasked": True}
        ev2 = _wait_ui_event(c, lambda e: e["e"] == "agent.confirm")
        assert ev2["d"]["id"] != ev["d"]["id"] and ev2["d"]["preview"]["names"] == ["after"]
        assert "res" not in out
        assert c.call("agent.confirmReply", id=ev2["d"]["id"], approve=True)["r"] == {}
        t.join(10)
        assert out["res"]["ok"] and out["res"]["r"]["deleted"] == 1


def _skip_confirm(version: int, value: bool) -> dict:
    return {"batch": {"label": {"code": "setting", "args": {"key": "agent.skip_confirm"}},
                      "ops": [{"entity": "setting", "id": "agent.skip_confirm", "version": version, "fields": {"value": value}}]}}


def test_skip_confirm_setting_is_human_only(app):
    c, root = app
    with LinkClient(root, session="sneaky") as a:
        # 命令行改不了这一项
        with pytest.raises(CoreError) as ei:
            a.call("edits.apply", _skip_confirm(0, True))
        assert ei.value.code == "setting-human-only"
        # 所有者在界面里打开 → 撤销不了的命令直接执行，不弹框
        assert c.call("edits.apply", **_skip_confirm(0, True))["ok"]
        c.events.clear()
        with pytest.raises(CoreError) as ei:
            a.call("samples.delete", {"ids": ["no-such-sample"]}, timeout=10)
        assert ei.value.code == "sample-not-found"
        assert not _events(c, "agent.confirm")
        # 命令行也撤销不了所有者对它的修改（撤销最近一次 = 这一条）
        with pytest.raises(CoreError) as ei:
            a.call("edits.undo")
        assert ei.value.code == "setting-human-only"
        assert c.call("settings.list")["r"]["agent.skip_confirm"]["value"] is True
