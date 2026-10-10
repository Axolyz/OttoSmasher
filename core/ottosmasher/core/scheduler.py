"""任务调度（ARCHITECTURE §11，规格 13 §13.1，16 R19）。

- 两条通道各自限流：模型（默认 1）、轻量（默认 2），并发数在启动下一个任务时读当前设置。
- 先持久化再执行：提交时写入“排队”行（冻结业务参数与设备设置），之后才可能启动进程。
- 排队任务不占进程；取消排队任务直接改为“已取消”。
- 取消运行中的任务 = 结束它的整棵进程树；结果不登记。
- 重试 = 相同业务参数的新任务（新 ID），设备设置用**当前**设置。
- Core 启动时，上次没完成的（排队、运行中）标为“已中断”。

数据库只在 Core 主线程访问：监视子进程的线程把回调投递回主线程（``post``）。
"""

from __future__ import annotations

import json
import logging
import sqlite3
import sys
import threading
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from ..jobs.kinds import channel_of
from ..platform.proc import ProcessTree, spawn_tree
from ..store.db import transaction
from . import actor as actor_mod
from .clock import new_id, now_iso
from .edits import dumps, loads
from .errors import CoreError

log = logging.getLogger(__name__)

TERMINAL = ("succeeded", "failed", "cancelled", "interrupted")
RETRYABLE = ("failed", "cancelled", "interrupted")

Adopter = Callable[[dict[str, Any], dict[str, Any]], None]  # (job 行, 结果) → 登记


@dataclass
class _Running:
    tree: ProcessTree
    cancel_requested: bool = False
    result: dict[str, Any] | None = None
    error: dict[str, Any] | None = None


class Scheduler:
    def __init__(
        self,
        conn: sqlite3.Connection,
        jobs_dir: Path,
        *,
        get_setting: Callable[[str], Any],
        device_snapshot: Callable[[], dict[str, Any]],
        post: Callable[[Callable[[], None]], None],
        emit: Callable[[str, Any], None],
        dev: bool = False,
        python: str = sys.executable,
    ) -> None:
        self.conn = conn
        self.jobs_dir = jobs_dir
        self.get_setting = get_setting
        self.device_snapshot = device_snapshot
        self.post = post
        self.emit = emit
        self.dev = dev
        self.python = python
        self.adopters: dict[str, Adopter] = {}
        # 任务结束（任何结局）后的回调：(任务 ID, 种类, 结局)。自动准备用它清掉“正在准备”的记账
        self.finish_hooks: list[Callable[[str, str, str], None]] = []
        self._running: dict[str, _Running] = {}
        self._pump_scheduled = False

    # ---------- 生命周期

    def recover(self) -> int:
        """启动时：上次没完成的任务 → 已中断（“工作进程已退出，可重试”）。"""
        ts = now_iso()
        cur = self.conn.execute(
            "UPDATE job SET status='interrupted', finished_at=?, error=? WHERE status IN ('queued', 'running')",
            (ts, dumps({"code": "job-interrupted", "args": {}})),
        )
        return cur.rowcount

    def kill_all(self) -> None:
        """Core 退出：结束所有运行中的进程树（状态留给下次启动标为已中断）。"""
        for r in list(self._running.values()):
            r.cancel_requested = True
            r.tree.kill(grace=1.0)

    def cancel_all(self) -> int:
        """用户确认退出：取消全部排队与运行中的任务。"""
        ids = [r["id"] for r in self.conn.execute("SELECT id FROM job WHERE status IN ('queued', 'running')")]
        for jid in ids:
            self.cancel(jid)
        return len(ids)

    # ---------- 提交、取消、重试

    def submit(self, kind: str, params: dict[str, Any], affects: dict[str, list[str]] | None = None, *, retry_of: str | None = None,
               background: bool = False) -> dict[str, Any]:
        """``background``：自动准备之类的后台任务，同一通道里排在用户提交的任务后面。"""
        channel = channel_of(kind, dev=self.dev)
        if channel is None:
            raise CoreError("job-kind-unknown", kind=kind)
        jid = new_id()
        with transaction(self.conn):
            self.conn.execute(
                "INSERT INTO job(id, kind, channel, status, params, device, affects, retry_of, created_at, background)"
                " VALUES (?, ?, ?, 'queued', ?, ?, ?, ?, ?, ?)",
                (jid, kind, channel, dumps(params), dumps(self.device_snapshot()), dumps(affects or {}), retry_of, now_iso(), int(background)),
            )
        summary = self.summary(jid)
        self.emit("job.updated", summary)
        self._schedule_pump()
        return summary

    def cancel(self, jid: str) -> dict[str, Any]:
        row = self._row(jid)
        if row["status"] == "queued":
            self.conn.execute(
                "UPDATE job SET status='cancelled', finished_at=? WHERE id=? AND status='queued'", (now_iso(), jid)
            )
            self._emit(jid)
            for hook in list(self.finish_hooks):
                hook(jid, row["kind"], "cancelled")
        elif row["status"] == "running":
            r = self._running.get(jid)
            if r is not None and not r.cancel_requested:
                r.cancel_requested = True
                threading.Thread(target=r.tree.kill, name=f"kill-{jid[:8]}", daemon=True).start()
        else:
            raise CoreError("job-not-cancellable", id=jid, status=row["status"])
        return self.summary(jid)

    def retry(self, jid: str) -> dict[str, Any]:
        row = self._row(jid)
        if row["status"] not in RETRYABLE:
            raise CoreError("job-not-retryable", id=jid, status=row["status"])
        return self.submit(row["kind"], loads(row["params"]), loads(row["affects"]), retry_of=jid)

    # ---------- 查询

    def summary(self, jid: str) -> dict[str, Any]:
        return _summary(self._row(jid))

    def list(self, limit: int = 200) -> list[dict[str, Any]]:
        rows = self.conn.execute("SELECT * FROM job ORDER BY created_at DESC LIMIT ?", (limit,)).fetchall()
        return [_summary(r) for r in rows]

    def running_count(self, channel: str | None = None) -> int:
        q = "SELECT COUNT(*) FROM job WHERE status='running'" + (" AND channel=?" if channel else "")
        return self.conn.execute(q, (channel,) if channel else ()).fetchone()[0]

    def active_count(self, include_background: bool = True) -> int:
        q = "SELECT COUNT(*) FROM job WHERE status IN ('queued', 'running')" + ("" if include_background else " AND background = 0")
        return self.conn.execute(q).fetchone()[0]

    def _row(self, jid: str) -> sqlite3.Row:
        row = self.conn.execute("SELECT * FROM job WHERE id=?", (jid,)).fetchone()
        if row is None:
            raise CoreError("job-not-found", id=jid)
        return row

    def _emit(self, jid: str) -> None:
        self.emit("job.updated", self.summary(jid))

    # ---------- 启动

    def _schedule_pump(self) -> None:
        if not self._pump_scheduled:
            self._pump_scheduled = True
            self.post(self.pump)

    def pump(self) -> None:
        self._pump_scheduled = False
        for channel, key in (("model", "jobs.concurrency_model"), ("light", "jobs.concurrency_light")):
            limit = int(self.get_setting(key))
            while self.running_count(channel) < limit:
                row = self.conn.execute(
                    "SELECT * FROM job WHERE status='queued' AND channel=? ORDER BY background, created_at, rowid LIMIT 1", (channel,)
                ).fetchone()
                if row is None:
                    break
                self._start(row)

    def _start(self, row: sqlite3.Row) -> None:
        jid = row["id"]
        job_dir = self.jobs_dir / jid
        job_dir.mkdir(parents=True, exist_ok=True)
        (job_dir / "input.json").write_text(
            json.dumps({"kind": row["kind"], "params": loads(row["params"]), "device": loads(row["device"])}, ensure_ascii=False),
            encoding="utf-8",
        )
        self.conn.execute("UPDATE job SET status='running', started_at=? WHERE id=?", (now_iso(), jid))
        logf = open(job_dir / "log.txt", "ab")  # noqa: SIM115 — 子进程持有，结束时关闭
        try:
            tree = spawn_tree([self.python, "-m", "ottosmasher.jobs.worker", str(job_dir)], stderr=logf)
        except OSError as exc:
            logf.close()
            self._finish(jid, "failed", error={"code": "job-spawn-failed", "args": {"reason": str(exc)}})
            return
        run = _Running(tree)
        self._running[jid] = run
        self._emit(jid)
        threading.Thread(target=self._watch, args=(jid, run, logf), name=f"job-{jid[:8]}", daemon=True).start()

    def _watch(self, jid: str, run: _Running, logf: Any) -> None:
        """监视线程：读子进程的事件行；不碰数据库，只投递回调。"""
        stdout = run.tree.popen.stdout
        assert stdout is not None
        for raw in stdout:
            try:
                msg = json.loads(raw)
            except ValueError:
                continue
            t = msg.get("type")
            if t == "progress":
                prog = {k: msg.get(k) for k in ("stage", "done", "total", "code", "args")}
                total = prog.get("total") or 0
                prog["percent"] = round(100 * (prog.get("done") or 0) / total, 1) if total else None
                self.post(lambda p=prog: self._progress(jid, p))
            elif t == "item":
                self.post(lambda m=msg: self._item(jid, m))
            elif t == "result":
                run.result = msg.get("result") or {}
            elif t == "error":
                run.error = {"code": msg.get("code", "job-failed"), "args": msg.get("args", {})}
        code = run.tree.popen.wait()
        logf.close()
        run.tree.close()
        self.post(lambda: self._exited(jid, run, code))

    def add_items(self, jid: str, items: list[tuple[str, str]]) -> None:
        """批量任务的逐条记录（target, 初始状态 queued / skipped），提交后立即写（规格 08 §8.4 结果表）。"""
        with transaction(self.conn):
            self.conn.executemany(
                "INSERT INTO job_item(job_id, idx, target, status) VALUES (?, ?, ?, ?)", [(jid, i, t, st) for i, (t, st) in enumerate(items)]
            )
            self.conn.execute(
                "UPDATE job SET items_total=?, items_ok=0, items_failed=0 WHERE id=?", (sum(1 for _, st in items if st == "queued"), jid)
            )

    def _item(self, jid: str, msg: dict[str, Any]) -> None:
        """工作进程报告一条的结果：只记状态与原因；登记由任务结束时的采纳函数做（取消不留半成品登记）。"""
        status = "ok" if msg.get("status") == "ok" else "failed"
        err = msg.get("error")
        cur = self.conn.execute(
            "UPDATE job_item SET status=?, error=?, result_ref=? WHERE job_id=? AND idx=?",
            (status, dumps(err) if err else None, msg.get("ref"), jid, int(msg.get("idx", -1))),
        )
        if cur.rowcount:
            col = "items_ok" if status == "ok" else "items_failed"
            self.conn.execute(f"UPDATE job SET {col}=COALESCE({col}, 0) + 1 WHERE id=?", (jid,))

    def _progress(self, jid: str, prog: dict[str, Any]) -> None:
        cur = self.conn.execute("UPDATE job SET progress=? WHERE id=? AND status='running'", (dumps(prog), jid))
        if cur.rowcount:
            self._emit(jid)

    def _exited(self, jid: str, run: _Running, code: int) -> None:
        self._running.pop(jid, None)
        row = self._row(jid)
        if run.cancel_requested:
            self._finish(jid, "cancelled")
        elif code == 0 and run.error is None and run.result is not None:
            try:
                adopter = self.adopters.get(row["kind"])
                if adopter is not None:
                    # 登记结果时记成提交任务的那一方（ROADMAP L1）
                    with actor_mod.acting(self.conn, row["actor_kind"], row["actor_session"]):
                        adopter(dict(row), run.result)
            except CoreError as exc:
                self._finish(jid, "failed", error=exc.to_wire())
            else:
                self._finish(jid, "succeeded", result=_small(run.result))
        else:
            err = run.error or {"code": "job-worker-exited", "args": {"exit_code": code}}
            err = {**err, "args": {**err.get("args", {}), "log": str(self.jobs_dir / jid / "log.txt")}}
            self._finish(jid, "failed", error=err)
        self._schedule_pump()

    def _finish(self, jid: str, status: str, *, error: dict[str, Any] | None = None, result: Any = None) -> None:
        self.conn.execute(
            "UPDATE job SET status=?, finished_at=?, error=?, result=? WHERE id=?",
            (status, now_iso(), None if error is None else dumps(error), None if result is None else dumps(result), jid),
        )
        self._emit(jid)
        kind = self.conn.execute("SELECT kind FROM job WHERE id=?", (jid,)).fetchone()[0]
        for hook in list(self.finish_hooks):
            try:
                hook(jid, kind, status)
            except Exception:  # noqa: BLE001 — 回调出错不影响任务记录
                log.exception("finish hook failed")


def _small(result: dict[str, Any]) -> dict[str, Any]:
    """任务摘要里只留小结果（规格 16 R19.4）；大的结果由登记函数写进对应的表或文件。"""
    enc = dumps(result)
    if len(enc) <= 4096:
        return result
    # 任务级提醒（如语音分析里音高没测成）不能因为结果大就丢掉（P6）
    return {"truncated": True, "bytes": len(enc)} | ({"warnings": result["warnings"]} if result.get("warnings") else {})


def _summary(row: sqlite3.Row) -> dict[str, Any]:
    return {
        "id": row["id"],
        "kind": row["kind"],
        "channel": row["channel"],
        "status": row["status"],
        "affects": loads(row["affects"]),
        "progress": loads(row["progress"]),
        "error": loads(row["error"]),
        "result": loads(row["result"]),
        "device": loads(row["device"]),
        "retry_of": row["retry_of"],
        "items": None if row["items_total"] is None else {"total": row["items_total"], "ok": row["items_ok"], "failed": row["items_failed"]},
        "created_at": row["created_at"],
        "started_at": row["started_at"],
        "finished_at": row["finished_at"],
        "background": bool(row["background"]),
    }
