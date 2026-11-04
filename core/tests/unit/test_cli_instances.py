"""otto 怎么找到正在运行的应用、怎么打开它（所有者 2026-11-04）。"""

from __future__ import annotations

import json
import os
import subprocess

import pytest

from ottosmasher import resources
from ottosmasher.cli import instances
from ottosmasher.cli.main import main, workspace_of


@pytest.fixture
def registry(tmp_path, monkeypatch):
    d = tmp_path / "registry"
    d.mkdir()
    monkeypatch.setenv("OTTO_REGISTRY_DIR", str(d))
    monkeypatch.delenv("OTTO_WORKSPACE", raising=False)
    monkeypatch.delenv("OTTO_RESOURCES", raising=False)
    return d


def put(d, name, **fields):
    info = {"pid": os.getpid(), "build": "source", "workspace": "/w/a", "startedAt": "2026-11-04T00:00:00Z", **fields}
    (d / f"{name}.json").write_text(json.dumps(info), encoding="utf-8")


class Args:
    workspace = None


def test_dead_instances_are_dropped(registry):
    dead = subprocess.Popen(["python3", "-c", "pass"])
    dead.wait()
    put(registry, "dead", pid=dead.pid)
    put(registry, "alive")
    (registry / "broken.json").write_text("{", encoding="utf-8")
    assert [i["workspace"] for i in instances.running()] == ["/w/a"]
    assert not (registry / "dead.json").exists()


def test_workspace_follows_the_running_app_of_the_same_kind(registry, monkeypatch):
    assert workspace_of(Args).as_posix() == resources.default_workspace().as_posix()  # 都没开：默认工作区
    put(registry, "other", build="packaged", workspace="/w/daily")
    assert workspace_of(Args).as_posix() == resources.default_workspace().as_posix()  # 开发版的 otto 不连发布版
    put(registry, "old", workspace="/w/old", startedAt="2026-11-01T00:00:00Z")
    put(registry, "new", workspace="/w/new", startedAt="2026-11-03T00:00:00Z")
    assert workspace_of(Args).as_posix() == "/w/new"  # 最新启动的
    put(registry, "default", workspace=str(resources.default_workspace()), startedAt="2026-10-01T00:00:00Z")
    assert workspace_of(Args).as_posix() == resources.default_workspace().as_posix()  # 默认工作区优先
    monkeypatch.setenv("OTTO_WORKSPACE", "/w/env")
    assert workspace_of(Args).as_posix() == "/w/env"  # 明确指定的优先


def test_packaged_otto_follows_the_packaged_app(registry, monkeypatch):
    put(registry, "dev", workspace="/w/dev")
    put(registry, "pkg", build="packaged", workspace="/w/daily")
    monkeypatch.setenv("OTTO_RESOURCES", "/Applications/OttoSmasher.app/Contents/Resources")
    assert instances.build() == "packaged"
    assert workspace_of(Args).as_posix() == "/w/daily"
    if os.name != "nt":
        assert instances.app_location().as_posix() == "/Applications/OttoSmasher.app"


def run_open(capsys, *args):
    code = main(["open", *args])
    return code, json.loads(capsys.readouterr().out)


def test_open_waits_until_ready(registry, tmp_path, monkeypatch, capsys):
    ws = tmp_path / "ws"
    calls = []
    monkeypatch.setattr(instances, "launch", lambda w: calls.append(w))
    seen = iter([None, None, {"pid": 1}])
    monkeypatch.setattr("ottosmasher.core.agent_link.read_endpoint", lambda data: next(seen))
    monkeypatch.setattr("time.sleep", lambda s: None)
    code, r = run_open(capsys, "--workspace", str(ws))
    assert code == 0 and r["opened"] is True and calls == [ws]  # 明确指定的工作区才传给应用


def test_open_does_nothing_when_running(registry, tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(instances, "launch", lambda w: pytest.fail("should not start a second app"))
    monkeypatch.setattr("ottosmasher.core.agent_link.read_endpoint", lambda data: {"pid": 1})
    code, r = run_open(capsys, "--workspace", str(tmp_path / "ws"))
    assert code == 0 and r["opened"] is False and r["running"] is True


def test_open_reports_timeout(registry, tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(instances, "launch", lambda w: None)
    monkeypatch.setattr("ottosmasher.core.agent_link.read_endpoint", lambda data: None)
    code, r = run_open(capsys, "--workspace", str(tmp_path / "ws"), "--timeout", "0")
    assert code == 2 and r["error"]["code"] == "agent-link-failed"


def test_open_starts_the_right_program(registry, monkeypatch):
    seen = {}
    monkeypatch.setattr(subprocess, "Popen", lambda cmd, **kw: seen.update(cmd=cmd, env=kw["env"]))
    monkeypatch.setattr(subprocess, "run", lambda cmd, **kw: seen.update(cmd=cmd, env=kw["env"]))
    monkeypatch.setattr(instances.sys, "platform", "darwin")
    instances.launch(None)
    assert seen["cmd"][-1] == "start" and seen["env"]["OTTO_DEV"] == "1"  # 源码运行：开发版
    monkeypatch.setenv("OTTO_RESOURCES", "/Applications/OttoSmasher.app/Contents/Resources")
    monkeypatch.setenv("PYTHONHOME", "/leak")
    instances.launch(None)
    assert seen["cmd"] == ["open", "-a", "/Applications/OttoSmasher.app"]
    assert not any(k.startswith(("OTTO_", "PYTHON")) for k in seen["env"])  # otto 的环境不漏给应用
    instances.launch(resources.Path("/w/x"))
    assert seen["cmd"][-2:] == ["--env", "OTTO_WORKSPACE=/w/x"]
