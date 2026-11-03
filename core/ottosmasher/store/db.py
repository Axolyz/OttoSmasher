"""SQLite 连接与结构迁移（规格 13 §13.3.5）。

- WAL，Core 单写连接；检索 worker 另开只读连接。
- 迁移按编号顺序执行，每个迁移一个事务；失败整体回滚。
- 对已有数据的库做迁移之前，先用 SQLite 在线备份 API 做一份一致性备份到 ``Data/Backups/``。
"""

from __future__ import annotations

import logging
import re
import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from importlib import resources
from pathlib import Path
from typing import Any

from ..core.clock import now_iso
from ..core.errors import CoreError

log = logging.getLogger(__name__)

_MIGRATION_NAME = re.compile(r"^(\d{4})_[a-z0-9_]+\.sql$")


@dataclass(frozen=True)
class Migration:
    version: int
    name: str
    sql: str


def bundled_migrations() -> list[Migration]:
    """包内 ``store/migrations/NNNN_name.sql``，按编号排序；编号必须从 1 连续。"""
    out: list[Migration] = []
    for entry in resources.files("ottosmasher.store.migrations").iterdir():
        m = _MIGRATION_NAME.match(entry.name)
        if m:
            out.append(Migration(int(m.group(1)), entry.name, entry.read_text(encoding="utf-8")))
    out.sort(key=lambda x: x.version)
    for i, mig in enumerate(out, start=1):
        if mig.version != i:
            raise RuntimeError(f"migration numbering gap at {mig.name}")
    return out


def connect(path: Path, *, readonly: bool = False) -> sqlite3.Connection:
    if readonly:
        conn = sqlite3.connect(f"{Path(path).resolve().as_uri()}?mode=ro", uri=True, isolation_level=None, check_same_thread=False)
    else:
        conn = sqlite3.connect(path, isolation_level=None, check_same_thread=False)
        conn.execute("PRAGMA journal_mode=WAL")
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")
    conn.execute("PRAGMA busy_timeout=5000")
    return conn


@contextmanager
def transaction(conn: sqlite3.Connection, *, immediate: bool = True) -> Iterator[sqlite3.Connection]:
    """显式事务：任何异常都回滚。"""
    conn.execute("BEGIN IMMEDIATE" if immediate else "BEGIN")
    try:
        yield conn
    except BaseException:
        conn.execute("ROLLBACK")
        raise
    else:
        conn.execute("COMMIT")


def current_version(conn: sqlite3.Connection) -> int:
    row = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='schema_migrations'"
    ).fetchone()
    if row is None:
        return 0
    v = conn.execute("SELECT MAX(version) FROM schema_migrations").fetchone()[0]
    return int(v or 0)


def backup_to(conn: sqlite3.Connection, dest: Path) -> Path:
    """一致性备份（在线备份 API，WAL 下也完整）。"""
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_name(dest.name + ".tmp")
    target = sqlite3.connect(tmp)
    try:
        conn.backup(target)
    finally:
        target.close()
    tmp.replace(dest)
    return dest


@dataclass
class MigrationReport:
    from_version: int
    to_version: int
    backup: Path | None


def migrate(conn: sqlite3.Connection, backups_dir: Path, migrations: list[Migration] | None = None) -> MigrationReport:
    migs = bundled_migrations() if migrations is None else migrations
    start = current_version(conn)
    latest = migs[-1].version if migs else 0
    if start > latest:
        raise CoreError("schema-too-new", found=start, supported=latest)
    pending = [m for m in migs if m.version > start]
    if not pending:
        return MigrationReport(start, start, None)

    backup: Path | None = None
    if start > 0:
        stamp = now_iso().replace(":", "").replace("-", "").replace(".", "")
        backup = backup_to(conn, backups_dir / f"library-v{start}-{stamp}.sqlite3")
        log.info("migration backup written: %s", backup)

    for mig in pending:
        try:
            with transaction(conn):
                conn.execute(
                    "CREATE TABLE IF NOT EXISTS schema_migrations ("
                    " version INTEGER PRIMARY KEY, name TEXT NOT NULL, applied_at TEXT NOT NULL)"
                )
                for stmt in _split_sql(mig.sql):
                    conn.execute(stmt)
                conn.execute(
                    "INSERT INTO schema_migrations(version, name, applied_at) VALUES (?, ?, ?)",
                    (mig.version, mig.name, now_iso()),
                )
        except sqlite3.Error as exc:
            log.error("migration %s failed: %s", mig.name, exc)
            raise CoreError(
                "schema-migration-failed", migration=mig.name, reason=str(exc), backup=str(backup or "")
            ) from exc
        log.info("migration applied: %s", mig.name)
    return MigrationReport(start, pending[-1].version, backup)


def _split_sql(sql: str) -> list[str]:
    """拆成完整的语句（``sqlite3.complete_statement``：触发器的 BEGIN … END 算一条）。整行注释先去掉。"""
    out, buf = [], ""
    for ln in sql.splitlines():
        if ln.strip().startswith("--"):
            continue
        buf += ln + "\n"
        if sqlite3.complete_statement(buf):
            if buf.strip().rstrip(";").strip():
                out.append(buf.strip())
            buf = ""
    if buf.strip():
        out.append(buf.strip())
    return out


def row_dict(row: sqlite3.Row | None) -> dict[str, Any] | None:
    return None if row is None else {k: row[k] for k in row.keys()}
