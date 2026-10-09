"""保存筛选器（规格 07 §7.3；Q16、Q17；UI_PLAN §2.3）：范围行的命名预设，**只存标签条件**（分面 + 可选的标签表达式）。

新建、改名、更新条件、删除（软删除）、排序都走统一编辑通道（``saved_filter`` 实体：预览 → 原子应用 → 可撤销）；
排序是一次编辑里改所有筛选器的 ``sort_order``（原子）。这里只有读取。选用一个筛选器 = 用它替换范围行（界面状态，不存）。
"""

from __future__ import annotations

import sqlite3
from typing import Any

from .edits import loads


def list_filters(conn: sqlite3.Connection) -> list[dict[str, Any]]:
    return [
        {"id": r[0], "name": r[1], "conditions": loads(r[2]), "sortOrder": r[3], "version": r[4]}
        for r in conn.execute("SELECT id, name, conditions, sort_order, version FROM saved_filter WHERE deleted = 0 ORDER BY sort_order, created_at, rowid")
    ]
