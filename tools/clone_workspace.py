"""把日常用的工作区克隆一份给开发版复现 bug（所有者 2026-10-31，DEVELOPMENT「开发版与发布版并存」）。

用法：tools/clone-workspace [名字] [--from <工作区>] [--to <目标文件夹>]
  名字缺省 = repro-<月日-时分>；源缺省 = 发布版的默认工作区 ~/Documents/OttoSmasher Workspace。
  克隆放在仓库的 dev-workspace-clones/<名字>/（不进 Git；AGENTS.md：开发数据只写在项目里）。
  --to 指定别的目标（例如把开发用的工作区整个变成发布版的日常工作区）；目标必须还不存在。

做法：
- 整个工作区用 APFS 克隆复制（cp -c：几秒、几乎不占空间，改了才另占）；不在同一个 APFS 卷上就普通复制（会占空间，先提示）。
- 数据库另用 SQLite 在线备份重写一份：应用开着、正在写也能得到一致的快照（WAL 下直接复制文件可能不完整）。
- 删掉只属于原来那个运行实例的文件：agent 端点（否则 otto 会连回原来的应用）、工作区锁。
- 原素材是原地引用（绝对路径），克隆和原来指向同一批媒体文件，只读、不受影响；克隆里新生成的音轨、导出都写在克隆里。
克隆的数据库升级（开发版的表结构较新）只发生在克隆上，日常工作区不动。
"""

from __future__ import annotations

import argparse
import shutil
import sqlite3
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_SRC = Path.home() / "Documents" / "OttoSmasher Workspace"
CLONES = ROOT / "dev-workspace-clones"
RUNTIME_FILES = ("Data/agent-endpoint.json", "Data/core.lock")


def main() -> int:
    ap = argparse.ArgumentParser(prog="tools/clone-workspace", description=__doc__.split("\n\n")[0])
    ap.add_argument("name", nargs="?", default=time.strftime("repro-%m%d-%H%M"))
    ap.add_argument("--from", dest="src", default=str(DEFAULT_SRC), help=f"source workspace (default: {DEFAULT_SRC})")
    ap.add_argument("--to", dest="dest", help="target folder instead of dev-workspace-clones/<name> (must not exist)")
    a = ap.parse_args()
    src = Path(a.src).expanduser().resolve()
    db = src / "Data" / "library.sqlite3"
    if not db.is_file():
        print(f"不是工作区（没有 {db}）", file=sys.stderr)
        return 2
    if "/" in a.name or a.name in (".", ".."):
        print("名字里不能有 /", file=sys.stderr)
        return 2
    dest = Path(a.dest).expanduser().resolve() if a.dest else CLONES / a.name
    if dest.exists():
        print(f"已经有了：{dest}（换个名字，或先删掉它）", file=sys.stderr)
        return 2
    dest.parent.mkdir(parents=True, exist_ok=True)

    t0 = time.monotonic()
    cloned = subprocess.run(["cp", "-cR", str(src), str(dest)], capture_output=True, text=True)
    if cloned.returncode != 0:
        shutil.rmtree(dest, ignore_errors=True)
        size = subprocess.run(["du", "-sh", str(src)], capture_output=True, text=True).stdout.split("\t")[0]
        print(f"不能克隆复制（{cloned.stderr.strip() or '不在同一个 APFS 卷上'}），改为普通复制，约 {size}", file=sys.stderr)
        shutil.copytree(src, dest, symlinks=True)
    # 数据库：在线备份得到一致快照，替换克隆里的文件（连同 WAL）
    for suffix in ("", "-wal", "-shm"):
        (dest / "Data" / f"library.sqlite3{suffix}").unlink(missing_ok=True)
    source = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    target = sqlite3.connect(dest / "Data" / "library.sqlite3")
    try:
        source.backup(target)
    finally:
        target.close()
        source.close()
    for rel in RUNTIME_FILES:
        (dest / rel).unlink(missing_ok=True)

    print(f"克隆好了（{time.monotonic() - t0:.1f} 秒）：{dest}")
    print("用它启动开发版：")
    print(f'  OTTO_WORKSPACE="{dest}" tools/npm run dev')
    print("让 agent / otto 连它：")
    print(f'  OTTO_WORKSPACE="{dest}" tools/otto status')
    print(f'用完删掉：rm -rf "{dest}"')
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
