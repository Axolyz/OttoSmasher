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
    if sys.platform == "win32":
        from ottosmasher.core.agent_link import _alive

        return _alive(pid)
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


def test_retry_restores_batch_rows_without_old_results(h):
    old = h.s.submit("selftest.sleep", {"seconds": 60})
    h.s.add_items(old["id"], [("seg:a", "queued"), ("seg:b", "queued"), ("seg:c", "skipped")])
    h.s._item(old["id"], {"idx": 0, "status": "ok", "ref": "old.json"})
    h.s._item(old["id"], {"idx": 1, "status": "failed", "error": {"code": "selftest-failed", "args": {}}})
    h.s.cancel(old["id"])

    new = h.s.retry(old["id"])
    assert new["items"] == {"total": 2, "ok": 0, "failed": 0}
    rows = h.db.execute("SELECT idx, target, status, error, result_ref FROM job_item WHERE job_id=? ORDER BY idx", (new["id"],)).fetchall()
    assert [tuple(r) for r in rows] == [(0, "seg:a", "queued", None, None), (1, "seg:b", "queued", None, None), (2, "seg:c", "skipped", None, None)]
    h.s._item(new["id"], {"idx": 0, "status": "ok", "ref": "new.json"})
    assert h.db.execute("SELECT result_ref FROM job_item WHERE job_id=? AND idx=0", (new["id"],)).fetchone()[0] == "new.json"
    assert h.db.execute("SELECT result_ref FROM job_item WHERE job_id=? AND idx=0", (old["id"],)).fetchone()[0] == "old.json"


# L50 排队中的任务可以提到最前（最近提的在前，后台任务也一样），运行中的不打断
def test_promote_moves_queued_job_to_front(h):
    h.set("jobs.concurrency_light", 1)
    a = h.s.submit("selftest.sleep", {"seconds": 30})
    h.wait_status(a["id"], "running")
    b = h.s.submit("selftest.sleep", {"seconds": 30})
    c = h.s.submit("selftest.sleep", {"seconds": 30})
    d = h.s.submit("selftest.sleep", {"seconds": 30}, background=True)
    with pytest.raises(CoreError) as ei:
        h.s.promote(a["id"])
    assert ei.value.code == "job-not-queued"
    assert h.s.promote(c["id"])["promoted"] is True
    h.s.promote(d["id"])
    order = [r[0] for r in h.db.execute(
        "SELECT id FROM job WHERE status='queued' ORDER BY promote_seq IS NULL, promote_seq DESC, background, created_at, rowid")]
    assert order == [d["id"], c["id"], b["id"]]
    h.s.cancel(a["id"])
    h.wait_status(d["id"], "running")
    assert h.status(a["id"]) == "cancelled" and h.status(c["id"]) == h.status(b["id"]) == "queued"


# L51 有逐条工作、一条都没做成 = 失败；结果照样登记。有一条做成就是成功
@pytest.mark.parametrize("statuses, expect", [(["failed", "failed"], "failed"), (["ok", "failed"], "succeeded")])
def test_all_items_failed_fails_the_job(h, statuses, expect):
    job = h.s.submit("selftest.sleep", {"seconds": 0.1})
    h.s.add_items(job["id"], [("a", "queued"), ("b", "queued"), ("c", "skipped")])
    for i, st in enumerate(statuses):
        h.s._item(job["id"], {"idx": i, "status": st, "error": None if st == "ok" else {"code": "selftest-failed", "args": {}}})
    h.wait_status(job["id"], "succeeded", "failed")
    s = h.s.summary(job["id"])
    assert s["status"] == expect and s["result"]["slept"] == 0.1
    assert s["error"] == ({"code": "job-all-items-failed", "args": {"failed": 2}} if expect == "failed" else None)


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


def test_separation_device_uses_frozen_studio_settings_and_retry_refreshes_them(h):
    a = h.s.submit('separate', {'device': 'auto', 'deviceId': 0})
    assert a['device']['accelerate'] is False
    assert a['separationDevice'] == {'requested': 'auto', 'deviceId': 0}
    h.s.cancel(a['id'])
    h.set('studio.device', 'cuda')
    h.set('studio.device_id', 2)
    assert h.s.summary(a['id'])['separationDevice']['requested'] == 'auto'
    b = h.s.retry(a['id'])
    assert b['separationDevice'] == {'requested': 'cuda', 'deviceId': 2}
    h.s.cancel(b['id'])
    legacy = h.s.submit('separate', {})
    assert legacy['separationDevice'] == {'requested': None, 'deviceId': None}
    h.s.cancel(legacy['id'])
    non_sep = h.s.submit('selftest.sleep', {'seconds': 0})
    assert 'separationDevice' not in non_sep
    h.s.cancel(non_sep['id'])
