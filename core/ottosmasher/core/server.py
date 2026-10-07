"""Core 进程（ARCHITECTURE §2）：唯一写库者；命令 = 公开业务接口。

主线程串行处理请求与内部回调（数据库只在这里访问）；读 stdin 的线程把帧放进队列；
任务监视线程把回调投递进同一个队列。stdin 结束（主进程退出或崩溃）→ 结束所有任务进程树 → 退出，
未完成的任务在下次启动时显示为“已中断”。
"""

from __future__ import annotations

import logging
import os
import queue
import sqlite3
import threading
from collections.abc import Callable
from pathlib import Path
from typing import Any, BinaryIO

from .. import __version__
from ..models import registry
from ..store.db import connect, current_version, migrate, transaction
from ..store.workspace import Workspace, WorkspaceLock
from . import settings as settings_mod
from .clock import now_iso
from .edits import ChangeSet, EditService, dumps, loads
from .errors import CoreError
from .rpc import FrameWriter, read_frame
from .scheduler import Scheduler

log = logging.getLogger(__name__)

Handler = Callable[[dict[str, Any]], Any]


class Core:
    def __init__(self, workspace: Path, *, support_dir: Path | None = None, dev: bool = False) -> None:
        self.ws = Workspace(workspace)
        self.support_dir = support_dir or registry.default_support_dir()
        self.dev = dev
        self.writer: FrameWriter | None = None
        self._q: queue.Queue[tuple[str, Any]] = queue.Queue()
        self._lock = WorkspaceLock(self.ws)
        self.conn: sqlite3.Connection
        self.edits: EditService
        self.jobs: Scheduler
        self.interrupted_on_start = 0
        self._stop = False
        self.commands: dict[str, Handler] = {
            "core.hello": self._hello,
            "settings.list": lambda p: settings_mod.read_all(self.conn),
            "edits.preview": lambda p: self.edits.preview(p["batch"]),
            "edits.apply": lambda p: self.edits.apply(p["batch"]),
            "edits.undo": lambda p: self.edits.undo(),
            "edits.peekUndo": lambda p: self.edits.peek_undo(),
            "jobs.list": lambda p: self.jobs.list(int(p.get("limit", 200))),
            "jobs.submit": lambda p: self.jobs.submit(p["kind"], p.get("params", {}), p.get("affects")),
            "jobs.cancel": lambda p: self.jobs.cancel(p["id"]),
            "jobs.retry": lambda p: self.jobs.retry(p["id"]),
            "models.status": self._models_status,
            "models.verify": self._models_verify,
            "ui.get": self._ui_get,
            "ui.set": self._ui_set,
            "app.prepareQuit": lambda p: {"active": self.jobs.active_count()},
            "app.quit": self._quit,
        }

    # ---------- 打开与关闭

    def open(self) -> None:
        self.ws.ensure()
        self._lock.acquire()
        self.conn = connect(self.ws.db_path)
        report = migrate(self.conn, self.ws.backups)
        if report.backup:
            log.info("schema migrated %s -> %s, backup %s", report.from_version, report.to_version, report.backup)
        self.edits = EditService(self.conn, on_change=self._on_change)
        self.jobs = Scheduler(
            self.conn,
            self.ws.jobs,
            get_setting=lambda k: settings_mod.values(self.conn)[k],
            device_snapshot=lambda: settings_mod.device_snapshot(settings_mod.values(self.conn)),
            post=self.post,
            emit=self.emit,
            dev=self.dev,
        )
        self.jobs.adopters["models.verify"] = self._adopt_hashes
        self.interrupted_on_start = self.jobs.recover()

    def close(self) -> None:
        try:
            self.jobs.kill_all()
        finally:
            self.conn.close()
            self._lock.release()

    # ---------- 事件与回调

    def emit(self, name: str, data: Any) -> None:
        if self.writer is not None:
            self.writer.event(name, data)

    def post(self, fn: Callable[[], None]) -> None:
        self._q.put(("call", fn))

    def _on_change(self, cs: ChangeSet) -> None:
        self.emit("data.changed", cs.to_wire())

    # ---------- 主循环

    def serve(self, stdin: BinaryIO, stdout: BinaryIO) -> None:
        self.writer = FrameWriter(stdout)
        threading.Thread(target=self._reader, args=(stdin,), name="stdin-reader", daemon=True).start()
        self.emit("core.ready", self._hello({}))
        while not self._stop:
            kind, item = self._q.get()
            if kind == "eof":
                log.info("stdin closed; shutting down")
                break
            if kind == "call":
                try:
                    item()
                except Exception:  # noqa: BLE001
                    log.exception("internal callback failed")
                continue
            self.writer.send(self.dispatch(item))

    def _reader(self, stdin: BinaryIO) -> None:
        try:
            while True:
                msg = read_frame(stdin)
                if msg is None:
                    break
                self._q.put(("req", msg))
        except Exception:  # noqa: BLE001
            log.exception("stdin reader failed")
        self._q.put(("eof", None))

    def dispatch(self, msg: dict[str, Any]) -> dict[str, Any]:
        rid = msg.get("id")
        method = msg.get("m")
        handler = self.commands.get(method)  # type: ignore[arg-type]
        try:
            if handler is None:
                raise CoreError("unknown-method", method=method)
            result = handler(msg.get("p") or {})
            return {"t": "res", "id": rid, "ok": True, "r": result}
        except CoreError as exc:
            return {"t": "res", "id": rid, "ok": False, "e": exc.to_wire()}
        except (KeyError, TypeError, ValueError) as exc:
            log.exception("bad request %s", method)
            return {"t": "res", "id": rid, "ok": False, "e": {"code": "bad-request", "args": {"method": method, "reason": repr(exc)}}}
        except Exception as exc:  # noqa: BLE001
            log.exception("command %s failed", method)
            return {"t": "res", "id": rid, "ok": False, "e": {"code": "internal-error", "args": {"method": method, "reason": repr(exc)}}}

    # ---------- 命令

    def _hello(self, p: dict[str, Any]) -> dict[str, Any]:
        return {
            "version": __version__,
            "pid": os.getpid(),
            "workspace": str(self.ws.root),
            "schema_version": current_version(self.conn),
            "interrupted_on_start": self.interrupted_on_start,
            "dev": self.dev,
        }

    def _cached_hashes(self) -> dict[str, tuple[int, int, str]]:
        return {r[0]: (r[1], r[2], r[3]) for r in self.conn.execute("SELECT path, size, mtime_ns, sha256 FROM file_hash_cache")}

    def _models_status(self, p: dict[str, Any]) -> dict[str, Any]:
        probes = [
            {"model": r["model"], "device": loads(r["device_setting"]), "status": r["status"], "error": loads(r["error"]), "tested_at": r["tested_at"]}
            for r in self.conn.execute("SELECT * FROM model_probe")
        ]
        return {
            "models_dir": str(self.ws.models),
            "support_dir": str(self.support_dir),
            "files": registry.file_status(self.ws.models, self.support_dir, self._cached_hashes()),
            "runtime": registry.runtime_status(),
            "probes": probes,
        }

    def _models_verify(self, p: dict[str, Any]) -> dict[str, Any]:
        paths = [str(x) for x in registry.all_files(self.ws.models, self.support_dir) if x.exists()]
        return self.jobs.submit("models.verify", {"paths": paths})

    def _adopt_hashes(self, job: dict[str, Any], result: dict[str, Any]) -> None:
        ts = now_iso()
        with transaction(self.conn):
            for path, h in result.get("hashes", {}).items():
                self.conn.execute(
                    "INSERT INTO file_hash_cache(path, size, mtime_ns, sha256, computed_at) VALUES (?, ?, ?, ?, ?)"
                    " ON CONFLICT(path) DO UPDATE SET size=excluded.size, mtime_ns=excluded.mtime_ns,"
                    " sha256=excluded.sha256, computed_at=excluded.computed_at",
                    (path, h["size"], h["mtime_ns"], h["sha256"], ts),
                )
        self.emit("models.changed", {})

    def _ui_get(self, p: dict[str, Any]) -> dict[str, Any]:
        rows = self.conn.execute(
            "SELECT key, value FROM ui_state WHERE window=? AND page=?", (p.get("window", "main"), p["page"])
        )
        return {r[0]: loads(r[1]) for r in rows}

    def _ui_set(self, p: dict[str, Any]) -> None:
        """界面状态（重启恢复）。不是用户资料，不走编辑通道。"""
        self.conn.execute(
            "INSERT INTO ui_state(window, page, key, value, updated_at) VALUES (?, ?, ?, ?, ?)"
            " ON CONFLICT(window, page, key) DO UPDATE SET value=excluded.value, updated_at=excluded.updated_at",
            (p.get("window", "main"), p["page"], p["key"], dumps(p["value"]), now_iso()),
        )

    def _quit(self, p: dict[str, Any]) -> dict[str, Any]:
        cancelled = self.jobs.cancel_all() if p.get("cancel_jobs", True) else 0
        self._stop = True
        return {"cancelled": cancelled}
