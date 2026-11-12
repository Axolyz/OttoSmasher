"""存储与缓存（规格 13 §13.3.3–§13.3.5、16 R20.4–R20.5、S12.4；ARCHITECTURE §6）。

- **永不当缓存删**：原片；素材库里的正式音轨、独立化切片与画面片段、导出、REAPER 文件；测量结果（对齐、F0〔= 音高检索索引〕、清单）；数据库；模型。
- **可清理**：``Data/Cache/``（波形峰值、缩略图、帧索引、卡拍试听渲染、Studio 模型列表等）、``Data/Staging/`` 里残留的临时文件、
  成功任务留下的私有解码缓存、分离中间音频及与正式测量一致的 F0 副本；手动整理也归档旧的原始对齐结果；
  另可选清掉语音检索索引与单音指标（数据库里的派生数据，后台会按需重建）。
- 保护：15 分钟内生成 / 修改的文件不删；不跟随符号链接；有任务排队或运行时拒绝手动清理。
- **自动整理**（设置「空闲时整理可重建缓存」，默认开）：用户空闲 ≥ 5 分钟（按界面上报的真实输入时间，界面轮询不算）、没有任务时，
  至多每小时一次：删除超过 1 天的可清理文件；总量仍超过 512 MiB 时从最旧的删到 384 MiB 以下。
- 面板：按类别列出占用、可清理量、近期（15 分钟内）数量；按原片列出库内持久音轨的占用。
"""

from __future__ import annotations

import logging
import shutil
import sqlite3
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from ..jobs.artifacts import INTERMEDIATE_JOBS, archive_alignment, intermediate_files, job_directory, regular_files, remove_intermediate
from ..store.db import transaction
from ..store.workspace import Workspace
from . import settings as settings_mod
from .edits import loads
from .errors import CoreError

log = logging.getLogger(__name__)

RECENT = 15 * 60
IDLE = 5 * 60
INTERVAL = 60 * 60
AGE = 24 * 60 * 60
HIGH = 512 * 1024 * 1024
LOW = 384 * 1024 * 1024
HISTORY_DAYS = 90

_OLD_JOBS = """
WITH RECURSIVE kept(id, retry_of) AS (
    SELECT id, retry_of FROM job WHERE status IN ('queued', 'running') OR COALESCE(finished_at, created_at) >= ?
    UNION
    SELECT j.id, j.retry_of FROM job j JOIN kept k ON j.id = k.retry_of
)
SELECT id FROM job WHERE id NOT IN (SELECT id FROM kept)
"""


def _walk(root: Path) -> list[tuple[Path, int, float]]:
    return list(regular_files(root))


def _size(root: Path) -> int:
    return sum(s for _p, s, _m in _walk(root))


class StorageService:
    def __init__(self, conn: sqlite3.Connection, ws: Workspace, jobs: Any) -> None:
        self.conn = conn
        self.ws = ws
        self.jobs = jobs
        self.last_input = time.time()  # 界面上报的最后一次真实输入
        self.last_auto = 0.0

    # ------------------------------------------------------------ 统计

    def _cleanable(self) -> list[tuple[Path, int, float, Path | None]]:
        return [(*f, None) for f in _walk(self.ws.data / "Cache") + _walk(self.ws.staging)] + self._job_cleanable()

    def _job_cleanable(self) -> list[tuple[Path, int, float, Path | None]]:
        files = []
        for jid, kind in self.conn.execute("SELECT id, kind FROM job WHERE status='succeeded'"):
            if kind not in INTERMEDIATE_JOBS:
                continue
            job = job_directory(self.ws.jobs, jid)
            if job is None:
                continue
            plan = ()
            if kind in ("f0.measure", "speech.analyze", "acoustic.measure") and (job / "f0").is_dir():
                params, result = self.conn.execute("SELECT params, result FROM job WHERE id=?", (jid,)).fetchone()
                params = loads(params)
                plan = params.get("plan") or params.get("f0") or (loads(result) or {}).get("f0") or ()
            files.extend(intermediate_files(job, kind, self.ws.f0, plan))
        return files

    def history_preview(self) -> dict[str, int]:
        return {"days": HISTORY_DAYS, "count": len(self._old_jobs())}

    def _old_jobs(self) -> list[str]:
        cutoff = (datetime.now(UTC) - timedelta(days=HISTORY_DAYS)).isoformat(timespec="milliseconds").replace("+00:00", "Z")
        return [r[0] for r in self.conn.execute(_OLD_JOBS, (cutoff,))]

    def report(self) -> dict[str, Any]:
        now = time.time()
        cache = _walk(self.ws.data / "Cache") + _walk(self.ws.staging)
        job_files = self._job_cleanable()
        job_contents = _walk(self.ws.jobs)
        lib = self.ws.library
        db = sum(p.stat().st_size for p in self.ws.data.glob("library.sqlite3*") if p.is_file())
        backups = self._backups()
        speech_index = self.conn.execute("SELECT COALESCE(SUM(length(data)), 0), COUNT(*) FROM speech_index").fetchone()
        metrics = self.conn.execute("SELECT COALESCE(SUM(length(metrics)), 0), COUNT(*) FROM acoustic_metric").fetchone()
        cats = [
            {"key": "cache", "bytes": sum(s for _p, s, _m in cache), "cleanable": sum(s for _p, s, m in cache if now - m >= RECENT),
             "files": len(cache), "recent": sum(1 for _p, _s, m in cache if now - m < RECENT)},
            {"key": "searchIndex", "bytes": int(speech_index[0]) + int(metrics[0]), "cleanable": int(speech_index[0]) + int(metrics[0]),
             "files": int(speech_index[1]) + int(metrics[1]), "recent": 0},
            {"key": "measurements", "bytes": _size(self.ws.data / "Measurements"), "cleanable": 0, "files": len(_walk(self.ws.data / "Measurements")), "recent": 0},
            {"key": "tracks", "bytes": _size(lib / "Tracks"), "cleanable": 0, "files": len(_walk(lib / "Tracks")), "recent": 0},
            {"key": "independent", "bytes": _size(lib / "Independent"), "cleanable": 0, "files": len(_walk(lib / "Independent")), "recent": 0},
            {"key": "exports", "bytes": _size(lib / "Exports") + _size(lib / "REAPER"), "cleanable": 0,
             "files": len(_walk(lib / "Exports")) + len(_walk(lib / "REAPER")), "recent": 0},
            {"key": "jobs", "bytes": sum(s for _p, s, _m in job_contents), "cleanable": sum(s for _p, s, m, _formal in job_files if now - m >= RECENT),
             "files": len(job_contents), "recent": sum(1 for _p, _s, m, _formal in job_files if now - m < RECENT)},
            {"key": "database", "bytes": db, "cleanable": 0, "files": 1, "recent": 0},
            {"key": "backups", "bytes": sum(s for _p, s, _m in backups), "cleanable": sum(s for _p, s, _m in backups[:-1]), "files": len(backups), "recent": 0},
        ]
        # 按原片：库内持久音轨（分离、拉平、回导）与独立化切片的占用（引用来自数据库，不靠路径字符串）
        per: dict[str, dict[str, Any]] = {}
        for sid, work, episode, path, rel in self.conn.execute(
            "SELECT DISTINCT a.source_id, s.work, s.episode, s.path, m.path FROM sound_asset a JOIN source s ON s.id = a.source_id"
            " JOIN asset_storage st ON st.asset_id = a.id JOIN media_file m ON m.id = st.media_file_id WHERE m.location = 'library'"
        ):
            p = self.ws.root / rel
            try:
                size = p.stat().st_size
            except OSError:
                continue
            row = per.setdefault(sid, {"sourceId": sid, "name": " ".join(x for x in (work, episode) if x) or Path(path).stem, "bytes": 0, "files": 0})
            row["bytes"] += size
            row["files"] += 1
        return {"categories": cats, "sources": sorted(per.values(), key=lambda r: -r["bytes"]), "idleCleanup": bool(settings_mod.values(self.conn)["storage.idle_cleanup"]),
                "jobHistory": self.history_preview(),
                "lastAuto": self.last_auto or None, "folders": {"exports": str(lib / "Exports"), "reaper": str(lib / "REAPER")}}

    def _backups(self) -> list[tuple[Path, int, float]]:
        """升级前的数据库备份，旧的在前。"""
        return sorted(_walk(self.ws.data / "Backups"), key=lambda x: x[2])

    def clean_backups(self) -> dict[str, Any]:
        """删掉旧备份，留最新一份（换回上一版时要用）。"""
        old = self._backups()[:-1]
        freed = 0
        for p, s, _m in old:
            try:
                p.unlink()
                freed += s
            except OSError:
                pass
        return {"files": len(old), "bytes": freed, "rows": 0}

    # ------------------------------------------------------------ 清理

    def _busy(self) -> list[str]:
        return [r[0] for r in self.conn.execute("SELECT id FROM job WHERE status IN ('queued', 'running')")]

    def _require_idle(self) -> None:
        if busy := self._busy():
            raise CoreError("storage-busy", jobs=",".join(busy))

    def clean_job_history(self) -> dict[str, int]:
        self._require_idle()
        ids = self._old_jobs()
        markers = self.ws.jobs / ".history-cleanup"
        with transaction(self.conn):
            for jid in ids:
                job = job_directory(self.ws.jobs, jid)
                if job is None or not job.is_dir() or markers.is_symlink() or markers.is_junction():
                    continue
                markers.mkdir(exist_ok=True)
                marker = markers / jid
                try:
                    marker.touch(exist_ok=False)
                except FileExistsError:
                    if marker.is_symlink() or not marker.is_file():
                        raise
            # The self-reference has no ON DELETE action. Both ends of any discarded retry chain are old.
            self.conn.executemany("UPDATE job SET retry_of=NULL WHERE id=? AND retry_of IS NOT NULL", ((jid,) for jid in ids))
            self.conn.executemany("DELETE FROM job WHERE id=?", ((jid,) for jid in ids))
        files, freed = self._remove_retired_jobs()
        return {"files": files, "bytes": freed, "rows": len(ids)}

    def _remove_retired_jobs(self) -> tuple[int, int]:
        markers = self.ws.jobs / ".history-cleanup"
        if self.ws.jobs.is_symlink() or self.ws.jobs.is_junction() or markers.is_symlink() or markers.is_junction() or not markers.is_dir():
            return 0, 0
        count = freed = 0
        for marker in markers.iterdir():
            job = job_directory(self.ws.jobs, marker.name)
            if job is None or marker.is_symlink() or not marker.is_file():
                continue
            if self.conn.execute("SELECT 1 FROM job WHERE id=?", (marker.name,)).fetchone() is not None:
                continue
            try:
                if job.is_dir():
                    files = _walk(job)
                    shutil.rmtree(job)
                    count += len(files)
                    freed += sum(s for _p, s, _m in files)
                marker.unlink()
            except OSError:
                log.exception("Could not remove retired job files for %s", marker.name)
        return count, freed

    def clean(self, *, derived: bool = False) -> dict[str, Any]:
        """手动清理 15 分钟前的中间文件和缓存，归档旧对齐结果。有任务时拒绝。"""
        self._require_idle()
        now = time.time()
        count, freed = self._remove([f for f in self._cleanable() if now - f[2] >= RECENT])
        for (jid,) in self.conn.execute("SELECT id FROM job WHERE kind='speech.align' AND status='succeeded'"):
            if (job := job_directory(self.ws.jobs, jid)) is not None:
                n, size = archive_alignment(job, before=now - RECENT)
                count += n
                freed += size
        retired_count, retired_freed = self._remove_retired_jobs()
        rows = 0
        if derived:
            rows += self.conn.execute("DELETE FROM speech_index").rowcount
            rows += self.conn.execute("DELETE FROM acoustic_metric").rowcount
        return {"files": count + retired_count, "bytes": freed + retired_freed, "rows": rows}

    def _remove(self, files: list[tuple[Path, int, float, Path | None]]) -> tuple[int, int]:
        count = freed = 0
        for p, s, _m, formal in files:
            try:
                if remove_intermediate(p, formal):
                    freed += s
                    count += 1
            except OSError:
                pass
        return count, freed

    # ------------------------------------------------------------ 空闲时自动整理

    def user_input(self) -> None:
        self.last_input = time.time()

    def tick(self) -> dict[str, Any] | None:
        """主循环每分钟调一次：满足条件才整理。返回这次整理的结果（没整理 → None）。"""
        now = time.time()
        if not settings_mod.values(self.conn)["storage.idle_cleanup"]:
            return None
        if now - self.last_input < IDLE or now - self.last_auto < INTERVAL or self._busy():
            return None
        self.last_auto = now
        files = [f for f in self._cleanable() if now - f[2] >= RECENT]
        old = [x for x in files if now - x[2] >= AGE]
        count, freed = self._remove(old)
        rest = sorted((x for x in files if now - x[2] < AGE and x[0].exists()), key=lambda x: x[2])
        total = sum(f[1] for f in rest)
        drop = []
        if total > HIGH:
            for x in rest:
                if total <= LOW:
                    break
                drop.append(x)
                total -= x[1]
        drop_count, drop_freed = self._remove(drop)
        retired_count, retired_freed = self._remove_retired_jobs()
        return {"files": count + drop_count + retired_count, "bytes": freed + drop_freed + retired_freed}
