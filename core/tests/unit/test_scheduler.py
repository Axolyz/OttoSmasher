"""任务系统：规格 16 R19.1–R19.6、13 §13.1.2。"""

from __future__ import annotations

import json
import os
import queue
import time
from collections.abc import Callable

import pytest

from ottosmasher.core import settings as settings_mod
from ottosmasher.core.edits import EditService
from ottosmasher.core.errors import CoreError
from ottosmasher.core.scheduler import Scheduler


class Harness:
    def __init__(self, db, ws) -> None:
        self.db = db
        self.q: queue.Queue = queue.Queue()
        self.events: list = []
        self.edits = EditService(db)
        self.s = Scheduler(
            db,
            ws.jobs,
            get_setting=lambda k: settings_mod.values(db)[k],
            device_snapshot=lambda: settings_mod.device_snapshot(settings_mod.values(db)),
            post=self.q.put,
            emit=lambda name, data: self.events.append((name, data)),
            dev=True,
        )

    def set(self, key: str, value) -> None:
        version = settings_mod.read_all(self.db)[key]["version"]
        self.edits.apply({"ops": [{"entity": "setting", "id": key, "version": version, "fields": {"value": value}}]})

    def pump_until(self, pred: Callable[[], bool], timeout: float = 15.0) -> None:
        end = time.monotonic() + timeout
        while time.monotonic() < end:
            if pred():
                return
            try:
                fn = self.q.get(timeout=0.05)
            except queue.Empty:
                continue
            fn()
        raise AssertionError("condition not reached")

    def status(self, jid: str) -> str:
        return self.s.summary(jid)["status"]

    def wait_status(self, jid: str, *statuses: str, timeout: float = 15.0) -> None:
        self.pump_until(lambda: self.status(jid) in statuses, timeout)

    def cleanup(self) -> None:
        self.s.cancel_all()
        self.pump_until(lambda: self.s.active_count() == 0 and not self.s._running, 20)


@pytest.fixture
def h(db, ws):
    harness = Harness(db, ws)
    yield harness
    harness.cleanup()


def alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    # 僵尸进程也算结束
    try:
        st = open(f"/proc/{pid}/stat").read().split()[2]  # Linux
        return st != "Z"
    except OSError:
        import subprocess

        out = subprocess.run(["ps", "-o", "stat=", "-p", str(pid)], capture_output=True, text=True).stdout.strip()
        return bool(out) and not out.startswith("Z")


def children_of(ws, jid: str) -> list[int]:
    p = ws.jobs / jid / "children.json"
    return json.loads(p.read_text()) if p.exists() else []


# R19.1 先持久化再执行；排队中的可以取消；重试生成新任务
def test_job_is_persisted_before_it_runs(h, ws):
    job = h.s.submit("selftest.sleep", {"seconds": 0.2})
    assert job["status"] == "queued"
    assert h.db.execute("SELECT status FROM job WHERE id=?", (job["id"],)).fetchone()[0] == "queued"
    assert not (ws.jobs / job["id"]).exists()  # 还没起进程
    h.wait_status(job["id"], "succeeded")
    assert h.s.summary(job["id"])["result"]["slept"] == 0.2


def test_cancel_queued_job_never_starts(h, ws):
    h.set("jobs.concurrency_light", 1)
    a = h.s.submit("selftest.sleep", {"seconds": 5})
    b = h.s.submit("selftest.sleep", {"seconds": 5})
    h.wait_status(a["id"], "running")
    assert h.status(b["id"]) == "queued"
    h.s.cancel(b["id"])
    assert h.status(b["id"]) == "cancelled"
    assert not (ws.jobs / b["id"]).exists()


def test_retry_creates_new_job_with_current_device(h):
    a = h.s.submit("selftest.fail", {"reason": "x"})
    h.wait_status(a["id"], "failed")
    s = h.s.summary(a["id"])
    assert s["error"]["code"] == "selftest-failed"
    assert os.path.exists(s["error"]["args"]["log"])
    h.set("inference.accelerate", True)
    b = h.s.retry(a["id"])
    assert b["id"] != a["id"] and b["retry_of"] == a["id"]
    assert b["device"]["accelerate"] is True and s["device"]["accelerate"] is False
    with pytest.raises(CoreError) as ei:
        h.s.retry(b["id"])  # 还在排队（泵还没跑），不能重试
    assert ei.value.code == "job-not-retryable"


# R19.2 取消只结束本任务的进程树
def test_cancel_kills_only_its_own_tree(h, ws):
    a = h.s.submit("selftest.sleep", {"seconds": 60, "children": 2})
    b = h.s.submit("selftest.sleep", {"seconds": 60, "children": 2})
    h.pump_until(lambda: len(children_of(ws, a["id"])) == 2 and len(children_of(ws, b["id"])) == 2)
    ca, cb = children_of(ws, a["id"]), children_of(ws, b["id"])
    assert all(alive(p) for p in ca + cb)
    h.s.cancel(a["id"])
    h.wait_status(a["id"], "cancelled")
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline and any(alive(p) for p in ca):
        time.sleep(0.05)
    assert not any(alive(p) for p in ca)
    assert all(alive(p) for p in cb)
    assert h.status(b["id"]) == "running"
    assert h.s.summary(a["id"])["result"] is None  # 取消的结果不登记


# R19.3 两条通道各自限流
def test_channels_are_limited_independently(h):
    m = [h.s.submit("selftest.sleep_model", {"seconds": 30}) for _ in range(2)]
    light = [h.s.submit("selftest.sleep", {"seconds": 30}) for _ in range(3)]
    h.pump_until(lambda: h.s.running_count("model") == 1 and h.s.running_count("light") == 2)
    time.sleep(0.3)
    h.pump_until(lambda: True)
    assert h.s.running_count("model") == 1
    assert h.s.running_count("light") == 2
    assert [h.status(j["id"]) for j in m].count("queued") == 1
    assert [h.status(j["id"]) for j in light].count("queued") == 1


# R19.4 摘要不嵌大结果，并声明受影响的对象
def test_summary_is_small_and_declares_affects(h):
    a = h.s.submit("selftest.sleep", {"seconds": 0.1}, {"samples": ["s1"], "sources": ["e1"]})
    h.wait_status(a["id"], "succeeded")
    s = h.s.summary(a["id"])
    assert s["affects"] == {"samples": ["s1"], "sources": ["e1"]}
    assert len(json.dumps(s)) < 4096


# R19.6 设备设置在提交时冻结
def test_device_settings_frozen_at_submit(h):
    h.set("jobs.concurrency_light", 1)
    h.set("inference.accelerate", True)
    h.set("inference.directml_device", 2)
    blocker = h.s.submit("selftest.sleep", {"seconds": 1})
    job = h.s.submit("selftest.sleep", {"seconds": 0.1})
    h.wait_status(blocker["id"], "running")
    h.set("inference.accelerate", False)
    h.set("inference.directml_device", 0)
    h.wait_status(job["id"], "succeeded")
    assert h.s.summary(job["id"])["result"]["device"] == {"accelerate": True, "directml_device": 2}


def test_recover_marks_unfinished_as_interrupted(h, db, ws):
    a = h.s.submit("selftest.sleep", {"seconds": 0.1})
    db.execute("UPDATE job SET status='running' WHERE id=?", (a["id"],))
    b = h.s.submit("selftest.sleep", {"seconds": 0.1})
    s2 = Scheduler(db, ws.jobs, get_setting=lambda k: 1, device_snapshot=dict, post=lambda f: None, emit=lambda *a: None)
    assert s2.recover() == 2
    assert h.status(a["id"]) == "interrupted" and h.status(b["id"]) == "interrupted"
    assert h.s.summary(a["id"])["error"]["code"] == "job-interrupted"
    # 中断的可以重试
    c = h.s.retry(a["id"])
    assert c["retry_of"] == a["id"]


def test_unknown_and_dev_kinds(db, ws):
    s = Scheduler(db, ws.jobs, get_setting=lambda k: 1, device_snapshot=dict, post=lambda f: None, emit=lambda *a: None, dev=False)
    for kind in ("no.such", "selftest.sleep"):
        with pytest.raises(CoreError) as ei:
            s.submit(kind, {})
        assert ei.value.code == "job-kind-unknown"
