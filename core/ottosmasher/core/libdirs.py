"""素材库目录（规格 12 §12.6、ARCHITECTURE §6；L23 统一）。

``Library/Tracks/<作品 集数> [<id8>]/{Separation, Flatten, Reimport}/``、``Library/Independent/<作品 集数> [<id8>]/``：
每个原片一个可读的目录名，**建立时**按作品与集数（没有就用文件名）取名，之后不随改名移动——按末尾的 ``[<id8>]`` 找回已有的目录。
长期固定的目录名一律英文；原片子目录可以用中日文（Q12）。
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

from ..domain import filename as fname
from ..store.workspace import Workspace

KINDS = ("Separation", "Flatten", "Reimport")


def source_key(ws: Workspace, conn: sqlite3.Connection, source_id: str, area: str = "Tracks") -> Path:
    """``Library/<area>/<可读名> [<id8>]``（已有就沿用）。"""
    base = ws.library / area
    tag = f"[{source_id[:8]}]"
    if base.is_dir():
        for d in base.iterdir():
            if d.is_dir() and d.name.endswith(tag):
                return d
    r = conn.execute("SELECT work, episode, path FROM source WHERE id = ?", (source_id,)).fetchone()
    readable = " ".join(x for x in ((r["work"] or ""), (r["episode"] or "")) if x).strip() if r else ""
    if not readable and r:
        readable = Path(r["path"]).stem
    readable = fname.truncate_utf8(fname.portable(readable or source_id[:8]), 80).strip(" .") or source_id[:8]
    return base / f"{readable} {tag}"


def track_dir(ws: Workspace, conn: sqlite3.Connection, source_id: str, kind: str) -> Path:
    """原片的库内音轨目录（分离声部 / 拉平成品 / 回导成品）；不存在就建。"""
    assert kind in KINDS
    d = source_key(ws, conn, source_id) / kind
    d.mkdir(parents=True, exist_ok=True)
    return d


def independent_dir(ws: Workspace, conn: sqlite3.Connection, source_id: str) -> Path:
    d = source_key(ws, conn, source_id, "Independent")
    d.mkdir(parents=True, exist_ok=True)
    return d
