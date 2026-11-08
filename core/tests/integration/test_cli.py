"""命令行 otto（阶段 A）：对着独立进程跑的 Core（它的 stdio 一侧当作应用界面）。"""

from __future__ import annotations

import base64
import json
import os
import subprocess
import sys

import pytest
from test_core_process import CoreProc


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
    p = subprocess.run([sys.executable, "-m", "ottosmasher.cli", *args], capture_output=True, encoding="utf-8", errors="replace", env=env, input=stdin, timeout=120)
    return p.returncode, (json.loads(p.stdout) if p.stdout.strip().startswith(("{", "[")) else p.stdout), p.stderr


def test_status_call_and_exit_codes(app):
    c, root = app
    rc, st, _ = otto(root, "status")
    assert rc == 0 and st["running"] and st["session"] == "t-1" and st["core"]["pid"] == c.call("core.hello")["r"]["pid"]
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
    rc, j, err = otto(root, "call", "jobs.submit", '{"kind": "selftest.sleep", "params": {"seconds": 0.5}}', "--wait", "--progress")
    assert rc == 0 and j["status"] == "succeeded", (j, err)
    assert any(json.loads(line).get("event") == "job.updated" for line in err.splitlines() if line.startswith("{"))
    rc, j2, _ = otto(root, "wait", "job", j["id"])
    assert rc == 0 and j2["id"] == j["id"]


def test_binary_measurements_and_spectrum_are_base64_json(app, tmp_path):
    import numpy as np
    from ottosmasher.media import wavfile

    c, root = app
    path = tmp_path / "tone.wav"
    t = np.arange(16000, dtype=np.float32) / 16000
    wavfile.save_wav24(path, (0.2 * np.sin(2 * np.pi * 220 * t))[:, None], 16000)
    aid = c.call("sources.add", paths=[str(path)])["r"][0]["assets"][0]["assetId"]
    for method, params, fields in [
        ("measure.f0", {"assetId": aid, "start": 0, "end": 0.5}, ["f0", "confidence", "energy"]),
        ("spectrum.get", {"assetId": aid, "start": 0, "end": 0.5, "cols": 32, "rows": 32, "scale": "log"}, ["data"]),
    ]:
        expected = c.call(method, **params)["r"]
        for pretty in [[], ["--pretty"]]:
            rc, actual, err = otto(root, "call", method, json.dumps(params), *pretty)
            assert rc == 0, err
            for field in fields:
                assert base64.b64decode(actual[field], validate=True) == expected[field]
            if method == "spectrum.get":
                assert actual["frequencies"] == expected["frequencies"]
                assert len(actual["frequencies"]) == actual["rows"]
                assert all(a < b for a, b in zip(actual["frequencies"], actual["frequencies"][1:]))


def test_dangerous_call_waits_for_the_owner(app):
    c, root = app
    env = {**os.environ, "OTTO_WORKSPACE": str(root), "OTTO_AGENT_SESSION": "d"}
    p = subprocess.Popen([sys.executable, "-m", "ottosmasher.cli", "call", "samples.delete", '{"ids": ["x"]}'],
                         stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, env=env)
    ev = c.wait_event(lambda e: e.get("e") == "agent.confirm", 30)
    assert ev["d"]["actor"] == {"kind": "agent", "session": "d"}
    assert c.call("agent.confirmReply", id=ev["d"]["id"], approve=False)["ok"]
    out, err = p.communicate(timeout=30)
    assert p.returncode == 3 and json.loads(out)["error"]["code"] == "agent-confirm-declined"
    # 等待时在 stderr 告诉 agent 正在等所有者放行
    assert any(json.loads(line).get("confirmId") == ev["d"]["id"] for line in err.splitlines() if line.startswith("{"))


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


def test_run_gives_the_script_one_session(app, tmp_path):
    # otto run：agent 自己的脚本用应用的 Python 跑，LinkClient.from_env() 连到同一个应用、整个脚本记在一个会话下
    c, root = app
    script = tmp_path / "my script.py"
    script.write_text(
        "import json, sys\n"
        "from ottosmasher.cli.client import LinkClient\n"
        "with LinkClient.from_env() as c:\n"
        "    v = c.call('settings.list')['jobs.concurrency_light']['version']\n"
        "    c.call('edits.apply', {'batch': {'ops': [{'entity': 'setting', 'id': 'jobs.concurrency_light', 'version': v, 'fields': {'value': int(sys.argv[1])}}]}})\n"
        "    print(json.dumps({'session': c.session}))\n",
        encoding="utf-8",
    )
    rc, out, err = otto(root, "run", str(script), "3", session="scripted")
    assert rc == 0 and out == {"session": "scripted"}, err
    h = c.call("edits.history", session="scripted")["r"]
    assert len(h) == 1 and h[0]["actor"] == {"kind": "agent", "session": "scripted"}


def test_session_and_status_environment(app):
    _, root = app
    rc, j, _ = otto(root, "call", "jobs.submit", '{"kind": "selftest.sleep", "params": {"seconds": 0.2}}', "--wait", session="long-1")
    assert rc == 0
    rc, s, _ = otto(root, "session", session="long-1")
    assert rc == 0 and s["session"] == "long-1" and [x["id"] for x in s["jobs"]] == [j["id"]] and s["jobs"][0]["status"] == "succeeded"
    assert s["running"] == 0 and s["edits"]["count"] == 0
    rc, s, _ = otto(root, "session", session="nobody")
    assert rc == 0 and s["jobs"] == []
    rc, st, _ = otto(root, "status")
    env = st["environment"]
    assert rc == 0 and env["otto"] and "models" in env and env["playbook"] is None
    assert "preparing-subtitles" in env["skills"]["names"] and env["skills"]["updates"] == []  # status 把内置 skill 放进工作区并报告


def test_global_arguments_survive_subcommands_and_quiet_wait(app, monkeypatch):
    c, root = app
    monkeypatch.delenv("OTTO_AGENT_SESSION", raising=False)
    env = {k: v for k, v in os.environ.items() if k not in ("OTTO_WORKSPACE", "OTTO_AGENT_SESSION")}
    for args in (["--workspace", str(root), "--session", "before", "status"],
                 ["status", "--workspace", str(root), "--session", "after"]):
        p = subprocess.run([sys.executable, "-m", "ottosmasher.cli", *args], capture_output=True, text=True, env=env)
        assert p.returncode == 0, p.stdout + p.stderr
        st = json.loads(p.stdout)
        assert st["session"] in ("before", "after") and st["workspace"] == str(root)
    rc, job, err = otto(root, "call", "jobs.submit", '{"kind":"selftest.sleep","params":{"seconds":0.1}}', "--wait")
    assert rc == 0 and job["status"] == "succeeded" and "job.updated" not in err
    rc, detail, _ = otto(root, "call", "jobs.get", json.dumps({"id": job["id"]}))
    assert rc == 0 and detail == job
    rc, brief, _ = otto(root, "call", "jobs.summaries", '{"session":"t-1"}')
    assert rc == 0 and brief[0]["id"] == job["id"] and "result" not in brief[0] and "affects" not in brief[0]


def test_utf8_bom_file_and_invalid_json_hint(app, tmp_path):
    _, root = app
    params = tmp_path / "参数 file.json"
    params.write_text('{"text":"あかり"}', encoding="utf-8-sig")
    rc, rows, _ = otto(root, "call", "samples.list", "@" + str(params))
    assert rc == 0 and rows["rows"] == []
    rc, err, _ = otto(root, "call", "samples.list", '{text:あかり}')
    assert rc == 2 and "@params.json" in err["error"]["args"]["reason"]


def test_session_inventory_reports_only_its_created_objects(app, tmp_path):
    import numpy as np
    from ottosmasher.media import wavfile

    c, root = app
    path = tmp_path / "inventory.wav"
    wavfile.save_wav24(path, np.zeros((16000, 1), dtype=np.float32), 16000)
    rc, sources, err = otto(root, "call", "sources.add", json.dumps({"paths": [str(path)]}), session="inventory")
    assert rc == 0, err
    aid = sources[0]["assets"][0]["assetId"]
    for session in ("inventory", "other"):
        rc, row, err = otto(root, "call", "samples.create", json.dumps({"assetId": aid, "start": 0, "end": 0.5, "name": session}), session=session)
        assert rc == 0, err
    rc, result, err = otto(root, "session", session="inventory")
    assert rc == 0, err
    assert result["created"]["samples"]["count"] == 1
    assert result["created"]["assets"]["count"] == 1
    rc, assets, err = otto(root, "call", "assets.listForSession", '{"session":"inventory","limit":1}')
    assert rc == 0 and assets["total"] == 1 and assets["rows"][0]["id"] == aid, err
