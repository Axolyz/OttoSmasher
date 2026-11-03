"""只读打开数据库（检索进程用）：路径里的特殊字符不能被当成 URI 语法。"""

from __future__ import annotations

from pathlib import Path

import pytest

from ottosmasher.store.db import connect


@pytest.mark.parametrize("name", ["普通", "空格 工作区", "作品#1", "100%", "问[号]", "a&b=c"])
def test_readonly_open_with_special_characters(tmp_path: Path, name: str):
    db = tmp_path / name / "otto.db"
    db.parent.mkdir()
    w = connect(db)
    w.execute("CREATE TABLE t(x)")
    w.execute("INSERT INTO t VALUES (1)")
    w.close()
    r = connect(db, readonly=True)
    assert r.execute("SELECT x FROM t").fetchone()[0] == 1
    r.close()
