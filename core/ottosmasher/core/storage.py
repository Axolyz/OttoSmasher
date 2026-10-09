"""存储与缓存（规格 13 §13.3.3–§13.3.5、16 R20.4–R20.5、S12.4；ARCHITECTURE §6）。

- **永不当缓存删**：原片；素材库里的正式音轨、独立化切片与画面片段、导出、REAPER 文件；测量结果（对齐、F0〔= 音高检索索引〕、清单）；数据库；模型。
- **可清理**：``Data/Cache/``（波形峰值、缩略图、帧索引、卡拍试听渲染、Studio 模型列表等）、``Data/Staging/`` 里残留的临时文件；
  另可选清掉语音检索索引与单音指标（数据库里的派生数据，后台会按需重建）。
- 保护：15 分钟内生成 / 修改的文件不删；不跟随符号链接；有任务排队或运行时拒绝手动清理。
- **自动整理**（设置「空闲时整理可重建缓存」，默认开）：用户空闲 ≥ 5 分钟（按界面上报的真实输入时间，界面轮询不算）、没有任务时，
  至多每小时一次：删除超过 1 天的可清理文件；总量仍超过 512 MiB 时从最旧的删到 384 MiB 以下。
- 面板：按类别列出占用、可清理量、近期（15 分钟内）数量；按原片列出库内持久音轨的占用。
"""

from __future__ import annotations

import os
import sqlite3
import time
from pathlib import Path
from typing import Any

from ..store.workspace import Workspace
from . import settings as settings_mod
from .errors import CoreError

RECENT = 15 * 60
IDLE = 5 * 60
INTERVAL = 60 * 60
AGE = 24 * 60 * 60
HIGH = 512 * 1024 * 1024
LOW = 384 * 1024 * 1024


def _walk(root: Path) -> list[tuple[Path, int, float]]:
    """root 下的普通文件（不跟随符号链接）：(路径, 大小, 修改时间)。"""
    out: list[tuple[Path, int, float]] = []
    if not root.is_dir():
        return out
    for dirpath, dirnames, filenames in os.walk(root, followlinks=False):
        dirnames[:] = [d for d in dirnames if not os.path.islink(os.path.join(dirpath, d))]
        for f in filenames:
            p = Path(dirpath) / f
            try:
                st = os.lstat(p)
            except OSError:
                continue
            if os.path.islink(p):
                continue
            out.append((p, st.st_size, st.st_mtime))
    return out


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

    def _cleanable(self) -> list[tuple[Path, int, float]]:
        return _walk(self.ws.data / "Cache") + _walk(self.ws.staging)

    def report(self) -> dict[str, Any]:
        now = time.time()
        cache = self._cleanable()
        lib = self.ws.library
        db = sum(p.stat().st_size for p in self.ws.data.glob("library.sqlite3*") if p.is_file())
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
            {"key": "jobs", "bytes": _size(self.ws.jobs), "cleanable": 0, "files": len(_walk(self.ws.jobs)), "recent": 0},
            {"key": "database", "bytes": db, "cleanable": 0, "files": 1, "recent": 0},
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
                "lastAuto": self.last_auto or None}

    # ------------------------------------------------------------ 清理

    def _busy(self) -> list[str]:
        return [r[0] for r in self.conn.execute("SELECT id FROM job WHERE status IN ('queued', 'running')")]

    def clean(self, *, derived: bool = False) -> dict[str, Any]:
        """手动清理：可清理文件里 15 分钟前的全部删除；``derived`` = 同时清掉语音检索索引与单音指标。有任务时拒绝。"""
        busy = self._busy()
        if busy:
            raise CoreError("storage-busy", jobs=",".join(busy))
        now = time.time()
        files = [(p, s, m) for p, s, m in self._cleanable() if now - m >= RECENT]
        freed = self._remove(files)
        rows = 0
        if derived:
            rows += self.conn.execute("DELETE FROM speech_index").rowcount
            rows += self.conn.execute("DELETE FROM acoustic_metric").rowcount
        return {"files": len(files), "bytes": freed, "rows": rows}

    def _remove(self, files: list[tuple[Path, int, float]]) -> int:
        freed = 0
        roots = [(self.ws.data / "Cache").resolve(), self.ws.staging.resolve()]
        for p, s, _m in files:
            rp = p.resolve()
            if not any(r in rp.parents for r in roots) or os.path.islink(p):
                continue  # 只删缓存目录里的普通文件
            try:
                p.unlink()
                freed += s
            except OSError:
                pass
        return freed

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
        files = [(p, s, m) for p, s, m in self._cleanable() if now - m >= RECENT]
        old = [x for x in files if now - x[2] >= AGE]
        freed = self._remove(old)
        rest = sorted((x for x in files if now - x[2] < AGE and x[0].exists()), key=lambda x: x[2])
        total = sum(s for _p, s, _m in rest)
        drop = []
        if total > HIGH:
            for x in rest:
                if total <= LOW:
                    break
                drop.append(x)
                total -= x[1]
        freed += self._remove(drop)
        return {"files": len(old) + len(drop), "bytes": freed}
