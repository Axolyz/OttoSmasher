"""来源标记（actor，ROADMAP L1 / QUESTIONS Q23 / ARCHITECTURE §15.2 #3）：这次写入是谁做的——用户（界面）/ 脚本 / agent + 会话 ID。

- 记在 ``edit``、``job``、``source``、``sound_asset``、``sample`` 的 ``actor_kind`` / ``actor_session`` 上（迁移 0004）。
- 不在每条 INSERT 里传：Core 连接上建一张临时表放“当前来源”，再给这几张表各建一个 AFTER INSERT 临时触发器把它写进新行
  ——写入点再多也不会漏。没装（单元测试直接连库）时就是列默认值 user。
- 当前来源：RPC 请求可带 ``actor``（``{"kind": "script", "session": "…"}``，缺省 = user）；任务完成后登记结果时用提交任务时的来源。
"""

from __future__ import annotations

import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any

KINDS = ("user", "script", "agent")
TABLES = ("edit", "job", "source", "sound_asset", "sample", "measure_run")
SESSION_MAX = 200


def install(conn: sqlite3.Connection) -> None:
    conn.execute("CREATE TEMP TABLE IF NOT EXISTS actor_ctx (kind TEXT NOT NULL, session TEXT)")
    if conn.execute("SELECT COUNT(*) FROM temp.actor_ctx").fetchone()[0] == 0:
        conn.execute("INSERT INTO temp.actor_ctx(kind, session) VALUES ('user', NULL)")
    for t in TABLES:
        conn.execute(
            f"CREATE TEMP TRIGGER IF NOT EXISTS actor_{t} AFTER INSERT ON main.{t} BEGIN"
            f" UPDATE main.{t} SET actor_kind = (SELECT kind FROM temp.actor_ctx), actor_session = (SELECT session FROM temp.actor_ctx)"
            " WHERE rowid = NEW.rowid; END"
        )


def parse(value: Any) -> tuple[str, str | None]:
    """RPC 里的 actor 参数 → (kind, session)；不合法 → ValueError（按 bad-request 回）。"""
    if value is None:
        return "user", None
    if not isinstance(value, dict):
        raise ValueError("actor must be an object")
    kind = value.get("kind", "user")
    session = value.get("session")
    if kind not in KINDS:
        raise ValueError(f"actor.kind must be one of {KINDS}")
    if session is not None and (not isinstance(session, str) or not 1 <= len(session) <= SESSION_MAX):
        raise ValueError("actor.session must be a short string")
    return kind, session


def _installed(conn: sqlite3.Connection) -> bool:
    return conn.execute("SELECT 1 FROM temp.sqlite_master WHERE name='actor_ctx'").fetchone() is not None


def current(conn: sqlite3.Connection) -> tuple[str, str | None]:
    """当前来源 (kind, session)；没装 = 用户。"""
    if not _installed(conn):
        return "user", None
    row = conn.execute("SELECT kind, session FROM temp.actor_ctx").fetchone()
    return row[0], row[1]


@contextmanager
def acting(conn: sqlite3.Connection, kind: str, session: str | None) -> Iterator[None]:
    """在这段里写入的行记为 (kind, session)；结束后恢复。"""
    if not _installed(conn) or (kind == "user" and session is None):
        yield
        return
    prev = conn.execute("SELECT kind, session FROM temp.actor_ctx").fetchone()
    conn.execute("UPDATE temp.actor_ctx SET kind=?, session=?", (kind, session))
    try:
        yield
    finally:
        conn.execute("UPDATE temp.actor_ctx SET kind=?, session=?", (prev[0], prev[1]))
