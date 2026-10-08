from __future__ import annotations

import os
import sqlite3
from pathlib import Path

import pytest

from ottosmasher.core.clock import new_id, now_iso
from ottosmasher.store.db import connect, migrate
from ottosmasher.store.workspace import Workspace

# 测试里的 Core（含子进程）都核对命令返回值与命令目录一致（ROADMAP L2）
os.environ.setdefault("OTTO_STRICT_API", "1")


@pytest.fixture
def ws(tmp_path: Path) -> Workspace:
    # 路径带中文、空格、方括号（规格 13 §13.3.1、16 R23.1）
    w = Workspace(tmp_path / "工作区 [测试] ws")
    w.ensure()
    return w


@pytest.fixture
def db(ws: Workspace) -> sqlite3.Connection:
    conn = connect(ws.db_path)
    migrate(conn, ws.backups)
    yield conn
    conn.close()


def make_source(conn: sqlite3.Connection, **kw) -> str:
    sid = new_id()
    ts = now_iso()
    conn.execute(
        "INSERT INTO source(id, path, work, episode, source_type, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
        (sid, kw.get("path", "/media/a.mkv"), kw.get("work", "Yuru Yuri"), kw.get("episode", "01"), "动画", ts, ts),
    )
    return sid


def make_asset(conn: sqlite3.Connection, source_id: str) -> str:
    aid = new_id()
    conn.execute(
        "INSERT INTO sound_asset(id, source_id, origin, stream_ordinal, duration, mapping, created_at)"
        " VALUES (?, ?, 'stream', 1, 1436.0, '[[0,0],[1436,1436]]', ?)",
        (aid, source_id, now_iso()),
    )
    return aid


def make_sample(conn: sqlite3.Connection, asset_id: str, name: str = "やったー") -> str:
    sid = new_id()
    ts = now_iso()
    conn.execute(
        "INSERT INTO sample(id, asset_id, start, \"end\", name, created_via, created_at, updated_at)"
        " VALUES (?, ?, 1.0, 2.0, ?, 'manual', ?, ?)",
        (sid, asset_id, name, ts, ts),
    )
    return sid
