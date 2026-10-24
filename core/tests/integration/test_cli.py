"""命令行 otto（阶段 A）：对着独立进程跑的 Core（它的 stdio 一侧当作应用界面）。"""

from __future__ import annotations

import json
import os
import subprocess
import sys

import pytest
from test_core_process import CoreProc

pytestmark = pytest.mark.skipif(sys.platform == "win32", reason="Windows 未验收（L47）")


@pytest.fixture
def app(tmp_path, monkeypatch):
    monkeypatch.setenv("OTTO_AGENT_CONFIRM_SECONDS", "20")
    root = tmp_path / "空格 工作区"
    c = CoreProc(root)
    yield c, root
    c.p.stdin.close()
    c.p.wait(timeout=20)


def otto(root, *args, stdin=None, session="t-1"):
    env = {**os.environ, "OTTO_WORKSPACE": str(root), "OTTO_AGENT_SESSION": session}
    p = subprocess.run([sys.executable, "-m", "ottosmasher.cli", *args], capture_output=True, text=True, env=env, input=stdin, timeout=120)
    return p.returncode, (json.loads(p.stdout) if p.stdout.strip().startswith(("{", "[")) else p.stdout), p.stderr


def test_status_call_and_exit_codes(app):
    c, root = app
    rc, st, _ = otto(root, "status")
    assert rc == 0 and st["running"] and st["session"] == "t-1" and st["core"]["pid"] == c.p.pid
    rc, s, _ = otto(root, "call", "settings.list")
    assert rc == 0 and "jobs.concurrency_light" in s
    v = s["jobs.concurrency_light"]["version"]
    batch = {"batch": {"ops": [{"entity": "setting", "id": "jobs.concurrency_light", "version": v, "fields": {"value": 3}}]}}
    rc, r, _ = otto(root, "call", "edits.apply", "-", stdin=json.dumps(batch))
    assert rc == 0 and r["edit_id"]
    rc, h, _ = otto(root, "call", "edits.history", '{"session": "t-1"}')
    assert rc == 0 and [x["edit_id"] for x in h] == [r["edit_id"]] and h[0]["actor"]["kind"] == "agent"
    rc, e, _ = otto(root, "call", "samples.get", '{"id": "nope"}')
    assert rc == 1 and e["error"]["code"] == "sample-not-found" and e["error"]["message"]
    rc, e, _ = otto(root, "call", "no.such")
    assert rc == 2 and e["error"]["code"] == "unknown-method"
    rc, e, _ = otto(root, "call", "samples.get", '{"idx": 1}')
    assert rc == 2 and e["error"]["code"] == "bad-request"
    rc, e, _ = otto(root, "call", "ui.set", '{"page": "a", "key": "b", "value": 1}')
    assert rc == 2 and e["error"]["code"] == "agent-command-forbidden"
    rc, u, _ = otto(root, "call", "edits.undoSession", '{"session": "t-1"}')
    assert rc == 0 and u["undone"] == 1


def test_wait_follows_a_job(app):
    c, root = app
    rc, j, err = otto(root, "call", "jobs.submit", '{"kind": "selftest.sleep", "params": {"seconds": 0.5}}', "--wait")
    assert rc == 0 and j["status"] == "succeeded", (j, err)
    assert any(json.loads(line).get("event") == "job.updated" for line in err.splitlines() if line.startswith("{"))
    rc, j2, _ = otto(root, "wait", "job", j["id"])
    assert rc == 0 and j2["id"] == j["id"]


def test_dangerous_call_waits_for_the_owner(app):
    c, root = app
    env = {**os.environ, "OTTO_WORKSPACE": str(root), "OTTO_AGENT_SESSION": "d"}
    p = subprocess.Popen([sys.executable, "-m", "ottosmasher.cli", "call", "samples.delete", '{"ids": ["x"]}'],
                         stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, env=env)
    ev = c.wait_event(lambda e: e.get("e") == "agent.confirm", 30)
    assert ev["d"]["actor"] == {"kind": "agent", "session": "d"}
    assert c.call("agent.confirmReply", id=ev["d"]["id"], approve=False)["ok"]
    out, _ = p.communicate(timeout=30)
    assert p.returncode == 3 and json.loads(out)["error"]["code"] == "agent-confirm-declined"


def test_offline_commands(tmp_path):
    rc, st, _ = otto(tmp_path / "none", "status")
    assert rc == 2 and st["running"] is False
    rc, e, _ = otto(tmp_path / "none", "call", "core.hello")
    assert rc == 2 and e["error"]["code"] == "app-not-running"
    rc, rows, _ = otto(tmp_path, "commands", "--effect", "job")
    assert rc == 0 and {"speech.submit", "separation.submit"} <= {r["name"] for r in rows}
    rc, rows, _ = otto(tmp_path, "commands")
    assert "ui.set" not in {r["name"] for r in rows} and any(r.get("danger") == "always" for r in rows)
    rc, d, _ = otto(tmp_path, "describe", "tracks.setDefault")
    assert rc == 0 and sorted(d["params"]["properties"]["role"]["enum"]) == ["sfx", "vocal"] and d["callable"]
    rc, d, _ = otto(tmp_path, "describe", "search.finished")
    assert rc == 0 and "resultId" in d["payload"]["properties"]
    rc, ev, _ = otto(tmp_path, "commands", "--events")
    assert "job.updated" in {e["name"] for e in ev}


def test_wait_follows_a_search(app):
    c, root = app
    rc, st, _ = otto(root, "call", "search.speech", '{"query": {"blocks": [{"vowel": "a"}, {"vowel": "i"}]}}', "--wait", "--timeout", "60")
    assert rc == 0 and st["status"] == "done" and st["resultId"]
    rc, page, _ = otto(root, "call", "results.page", json.dumps({"id": st["resultId"]}))
    assert rc == 0 and page is not None
