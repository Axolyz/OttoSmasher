"""原片文件夹的路径规则（阶段 3.13；不依赖其他 Core 模块，登记与扫描都用它）。

- 文件在某个原片文件夹之下 → (原片文件夹 ID, 相对路径（/ 分隔）, 作品 = 第一层子文件夹名；直接放在根下的为空 = 未指定作品)。
- 比较用与 ``sources.path_key`` 相同的规范化（绝对路径、NFC、按系统规则大小写），保存时保留原样。
"""

from __future__ import annotations

import os
import sqlite3
import unicodedata
from pathlib import Path, PurePath


def norm(path: str | os.PathLike[str]) -> str:
    return os.path.normcase(unicodedata.normalize("NFC", os.path.abspath(os.fspath(path))))


def _relative(root: str, path: str) -> tuple[str, ...] | None:
    if not norm(path).startswith(norm(root).rstrip(os.sep) + os.sep):
        return None
    # 前缀已按规范化形式比较，按组件数截下原样的后缀。relpath 会重新比较原字符串。
    return Path(os.path.abspath(path)).parts[len(Path(os.path.abspath(root)).parts) :]


def split(root: str, path: str) -> tuple[str, str] | None:
    """path 在 root 之下 → (相对路径, 作品)；否则 None。"""
    parts = _relative(root, path)
    if parts is None:
        return None
    work = unicodedata.normalize("NFC", parts[0]) if len(parts) > 1 else ""
    return PurePath(*parts).as_posix(), work


def locate(conn: sqlite3.Connection, path: str) -> tuple[str, str, str] | None:
    """文件所在的原片文件夹：(root_id, 相对路径, 作品)；不在任何原片文件夹里 → None。"""
    for rid, rpath in conn.execute("SELECT id, path FROM source_root"):
        hit = split(rpath, path)
        if hit is not None:
            return rid, hit[0], hit[1]
    return None


def work_folder(conn: sqlite3.Connection, root_id: str, name: str) -> sqlite3.Row | None:
    if not name:
        return None
    return conn.execute("SELECT * FROM work_folder WHERE root_id=? AND name=?", (root_id, name)).fetchone()


def replace_prefix(path: str | None, old: str, new: str) -> str | None:
    """path 以目录 old 开头（规范化比较）→ 换成 new 开头；否则 None。"""
    if not path:
        return None
    if norm(path) == norm(old):
        return new
    parts = _relative(old, path)
    return os.path.join(new, *parts) if parts is not None else None
