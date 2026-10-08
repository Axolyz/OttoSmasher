"""原片文件夹（阶段 3.13；所有者 2026-10-07，QUESTIONS「阶段 3 验收反馈」）。

- 设置里指定一个或多个“原片文件夹”。第一层子文件夹 = 作品（作品文件夹）；更深的层级只显示为子目录，不另分组；直接放在根下的 = 未指定作品。
- **扫描**（启动时一次 + 手动「重新扫描」；不实时监视）：轻量任务 ``sources.scan`` 在任务进程里列出各原片文件夹里的音频与视频
  （与音频同名的视频/图片是它的画面，规则同导入），对还没登记的文件做准备（探测、确切时长、峰值）；登记在主线程：
  1. 先认移动/改名：文件快照（大小 + 修改时间 + 流签名）与某个“文件找不到”的原片相同 → 当作同一个原片换了位置（字幕标记、OP/ED、采样都保留）；
  2. 其余登记为新原片：作品 = 文件夹名，来源类型沿用作品文件夹的设置，同名画面按作品文件夹的开关绑定，同名字幕自动关联（只关联不导入）。
  文件从文件夹里删掉不删原片，只是“文件找不到”。结果发 ``sources.scanned`` 事件（新、移动、找不到的数量与新原片 ID）。
- **作品改名**（「作品设置…」）= 改磁盘上的作品文件夹名，并在一个事务里改这些原片的路径、作品名、媒体文件与字幕路径；
  数据库写入失败就把文件夹名改回去。目标名已有文件夹 / 原片文件夹不在 / 没权限 → 明确报错、什么都不动。改名不进撤销记录（是文件操作），再改一次即可。
- **作品设置**：来源类型（整组一起设，可撤销）、同名画面自动绑定（新文件用）——经编辑通道（``settings_batch`` 生成批次）。
"""

from __future__ import annotations

import logging
import os
import shutil
import unicodedata
from collections.abc import Callable
from pathlib import Path
from typing import Any

from ottosmasher.store.db import transaction

from . import rootpaths
from . import settings as settings_mod
from .clock import new_id, now_iso
from .edits import ChangeSet, loads
from .errors import CoreError
from .imports import _probe_of, bind_picture, collect, scan
from .sources import move_source, path_key

log = logging.getLogger(__name__)

NAME_MAX = 200
BAD_CHARS = set('/\\:*?"<>|') | {chr(c) for c in range(32)}


def scan_roots(roots: list[dict[str, str]], known: list[str], cache: Path, progress: Callable[[int, int], None]) -> dict[str, Any]:
    """任务进程里执行：列出原片文件夹里没登记过的音频/视频并做准备。不碰数据库。"""
    offline = [r["id"] for r in roots if not os.path.isdir(r["path"])]
    paths = [r["path"] for r in roots if r["id"] not in offline]
    seen = set(known)
    todo = [f for f, _root in collect(paths) if path_key(f) not in seen]
    res = scan(todo, cache, progress)
    folders: dict[str, list[str]] = {}
    for r in roots:
        if r["id"] in offline:
            continue
        try:
            folders[r["id"]] = sorted(p.name for p in Path(r["path"]).iterdir() if p.is_dir() and not p.name.startswith("."))
        except OSError:
            folders[r["id"]] = []
    return {"items": res["items"], "offline": offline, "folders": folders}


def _valid_name(name: str) -> str:
    name = unicodedata.normalize("NFC", name).strip()
    if not name or name in (".", "..") or name.startswith(".") or len(name) > NAME_MAX or any(c in BAD_CHARS for c in name):
        raise CoreError("work-name-invalid", name=name)
    return name


class RootService:
    def __init__(self, conn: Any, ws: Any, jobs: Any, sources: Any, *, on_change: Callable[[ChangeSet], None] | None, emit: Callable[[str, Any], None]) -> None:
        self.conn = conn
        self.ws = ws
        self.jobs = jobs
        self.sources = sources
        self.on_change = on_change
        self.emit = emit
        jobs.adopters["sources.scan"] = self._adopt_scan

    def _changed(self, cs: ChangeSet) -> None:
        if cs.entities and self.on_change:
            self.on_change(cs)

    # ------------------------------------------------------------ 原片文件夹

    def list(self) -> list[dict[str, Any]]:
        out = []
        for r in self.conn.execute("SELECT id, path FROM source_root ORDER BY created_at, rowid"):
            n = self.conn.execute("SELECT COUNT(*) FROM source WHERE root_id=?", (r["id"],)).fetchone()[0]
            w = self.conn.execute("SELECT COUNT(*) FROM work_folder WHERE root_id=?", (r["id"],)).fetchone()[0]
            out.append({"id": r["id"], "path": r["path"], "online": os.path.isdir(r["path"]), "sources": n, "works": w})
        return out

    def add(self, path: str) -> dict[str, Any]:
        path = os.path.abspath(path)
        if not os.path.isdir(path):
            raise CoreError("root-invalid", reason="not-a-folder", path=path)
        for (other,) in self.conn.execute("SELECT path FROM source_root"):
            if rootpaths.split(other, path) or rootpaths.split(path, other) or rootpaths.norm(other) == rootpaths.norm(path):
                raise CoreError("root-invalid", reason="overlaps", path=path, other=other)
        rid = new_id()
        cs = ChangeSet()
        with transaction(self.conn):
            self.conn.execute("INSERT INTO source_root(id, path, created_at) VALUES (?, ?, ?)", (rid, path, now_iso()))
            # 已经登记过、正好在这个文件夹里的原片：归到它下面，作品跟着文件夹走
            for (sid,) in self.conn.execute("SELECT id FROM source").fetchall():
                p = self.conn.execute("SELECT path FROM source WHERE id=?", (sid,)).fetchone()[0]
                if rootpaths.split(path, p) is not None:
                    move_source(self.conn, sid, p)
                    cs.add("source", sid)
            self._ensure_folders(rid)
        self._changed(cs)
        return {"id": rid, "adopted": len(cs.entities.get("source", ())), "job": self.rescan()}

    def remove(self, root_id: str) -> dict[str, Any]:
        """不再把它当原片文件夹：原片照旧（作品名保留、之后可在应用里改），只去掉文件夹关系。"""
        cs = ChangeSet()
        with transaction(self.conn):
            for (sid,) in self.conn.execute("SELECT id FROM source WHERE root_id=?", (root_id,)).fetchall():
                cs.add("source", sid)
            self.conn.execute("UPDATE source SET root_id=NULL, rel_path=NULL WHERE root_id=?", (root_id,))
            self.conn.execute("DELETE FROM source_root WHERE id=?", (root_id,))
        self._changed(cs)
        return {"released": len(cs.entities.get("source", ()))}

    def relocate(self, root_id: str, new_path: str) -> dict[str, Any]:
        """原片文件夹整体换了位置（例如换了硬盘）：按相对路径改所有原片的位置，然后重新扫描。"""
        new_path = os.path.abspath(new_path)
        row = self.conn.execute("SELECT path FROM source_root WHERE id=?", (root_id,)).fetchone()
        if row is None:
            raise CoreError("root-invalid", reason="not-found", path=root_id)
        if not os.path.isdir(new_path):
            raise CoreError("root-invalid", reason="not-a-folder", path=new_path)
        cs = ChangeSet()
        with transaction(self.conn):
            self.conn.execute("UPDATE source_root SET path=? WHERE id=?", (new_path, root_id))
            cs = self._rewrite(row[0], new_path)
        self._changed(cs)
        return {"moved": len(cs.entities.get("source", ())), "job": self.rescan()}

    def _rewrite(self, old: str, new: str) -> ChangeSet:
        """在调用方的事务里：路径以目录 old 开头的原片、媒体文件、字幕、画面一起换成 new 开头。"""
        cs = ChangeSet()
        for r in self.conn.execute("SELECT id, path, subtitle_path FROM source").fetchall():
            np = rootpaths.replace_prefix(r["path"], old, new)
            ns = rootpaths.replace_prefix(r["subtitle_path"], old, new)
            if np is None and ns is None:
                continue
            if ns is not None:
                self.conn.execute("UPDATE source SET subtitle_path=? WHERE id=?", (ns, r["id"]))
            if np is not None:
                move_source(self.conn, r["id"], np)
            cs.add("source", r["id"])
        for r in self.conn.execute("SELECT id, path FROM media_file WHERE location='external'").fetchall():
            np = rootpaths.replace_prefix(r["path"], old, new)
            if np is not None:
                self.conn.execute("UPDATE media_file SET path=? WHERE id=?", (np, r["id"]))
        return cs

    def _ensure_folders(self, root_id: str, names: list[str] | None = None) -> None:
        if names is None:
            path = self.conn.execute("SELECT path FROM source_root WHERE id=?", (root_id,)).fetchone()[0]
            try:
                names = sorted(p.name for p in Path(path).iterdir() if p.is_dir() and not p.name.startswith("."))
            except OSError:
                names = []
        ts = now_iso()
        for n in names:
            n = unicodedata.normalize("NFC", n)
            self.conn.execute(
                "INSERT OR IGNORE INTO work_folder(id, root_id, name, created_at, updated_at) VALUES (?, ?, ?, ?, ?)", (new_id(), root_id, n, ts, ts)
            )

    # ------------------------------------------------------------ 扫描

    def rescan(self) -> dict[str, Any] | None:
        roots = [{"id": r[0], "path": r[1]} for r in self.conn.execute("SELECT id, path FROM source_root")]
        if not roots:
            return None
        for j in self.conn.execute("SELECT id FROM job WHERE kind='sources.scan' AND status IN ('queued', 'running')"):
            return {"id": j[0]}  # 已经在扫了
        known = [r[0] for r in self.conn.execute("SELECT path_key FROM source")]
        return {"id": self.jobs.submit("sources.scan", {"roots": roots, "known": known})["id"]}

    def _adopt_scan(self, job: dict[str, Any], result: dict[str, Any]) -> None:
        src = self.jobs.jobs_dir / job["id"] / "cache" / "Peaks"
        if src.is_dir():
            dst = self.ws.data / "Cache" / "Peaks"
            dst.mkdir(parents=True, exist_ok=True)
            for f in src.iterdir():
                if not (dst / f.name).exists():
                    shutil.move(str(f), dst / f.name)
        values = settings_mod.values(self.conn)
        rules, preferred = values["source.infer_rules"], values["source.sample_language"]
        cs = ChangeSet()
        new_ids: list[str] = []
        moved: list[str] = []
        failed: list[dict[str, Any]] = []
        with transaction(self.conn):
            for rid, names in result.get("folders", {}).items():
                if self.conn.execute("SELECT 1 FROM source_root WHERE id=?", (rid,)).fetchone():
                    self._ensure_folders(rid, names)
        # 文件找不到的原片：用文件快照认移动/改名
        missing: dict[tuple[Any, Any, Any], str] = {}
        for r in self.conn.execute("SELECT id, path, file_snapshot FROM source WHERE media_state='available'"):
            if not os.path.exists(r["path"]) and r["file_snapshot"]:
                snap = loads(r["file_snapshot"])
                missing[(snap.get("size"), snap.get("mtime_ns"), repr(snap.get("streams")))] = r["id"]
        from ottosmasher.media import probe as probe_mod

        for it in result["items"]:
            if not it["ok"]:
                failed.append({"path": it["path"], "error": it["error"]})
                continue
            if self.conn.execute("SELECT 1 FROM source WHERE path_key=?", (path_key(it["path"]),)).fetchone():
                continue  # 扫描期间别处登记了
            try:
                pr = _probe_of(it["probe"])
                st = os.stat(it["path"])
                key = (st.st_size, st.st_mtime_ns, repr(probe_mod.snapshot(it["path"], pr)["streams"]))
                with transaction(self.conn):
                    if key in missing:
                        sid = missing.pop(key)
                        move_source(self.conn, sid, it["path"])
                        moved.append(sid)
                    else:
                        r = self.sources.insert(it["path"], pr, rules, preferred, None, cs, tx=False)
                        sid = r["sourceId"]
                        where = rootpaths.locate(self.conn, it["path"])
                        wf = rootpaths.work_folder(self.conn, where[0], where[2]) if where else None
                        bind = bool(wf["bind_pictures"]) if wf is not None else True
                        if bind and it.get("picture"):
                            bind_picture(self.conn, sid, it["picture"])
                        new_ids.append(sid)
                    cs.add("source", sid)
            except CoreError as e:
                failed.append({"path": it["path"], "error": e.to_wire()})
        missing_now = sum(1 for r in self.conn.execute("SELECT path FROM source WHERE root_id IS NOT NULL AND media_state='available'") if not os.path.exists(r[0]))
        by_work: dict[str, int] = {}
        for sid in new_ids:
            w = self.conn.execute("SELECT work FROM source WHERE id=?", (sid,)).fetchone()[0]
            by_work[w] = by_work.get(w, 0) + 1
        self._changed(cs)
        offline = [r[0] for r in self.conn.execute("SELECT path FROM source_root") if not os.path.isdir(r[0])]
        self.emit(
            "sources.scanned",
            {
                "new": len(new_ids),
                "moved": len(moved),
                "missing": missing_now,
                "failed": failed[:50],
                "newIds": new_ids,
                "byWork": sorted(by_work.items(), key=lambda kv: (-kv[1], kv[0])),
                "offline": offline,
            },
        )

    # ------------------------------------------------------------ 作品文件夹

    def works(self) -> list[dict[str, Any]]:
        rows = self.conn.execute(
            "SELECT w.id, w.root_id, w.name, w.source_type, w.bind_pictures, w.version, r.path AS root_path FROM work_folder w"
            " JOIN source_root r ON r.id=w.root_id ORDER BY w.name"
        )
        out = []
        for w in rows:
            n = self.conn.execute(
                "SELECT COUNT(*) FROM source WHERE root_id=? AND (rel_path LIKE ? || '/%')", (w["root_id"], w["name"])
            ).fetchone()[0]
            out.append(
                {
                    "id": w["id"],
                    "rootId": w["root_id"],
                    "name": w["name"],
                    "sourceType": w["source_type"],
                    "bindPictures": bool(w["bind_pictures"]),
                    "version": w["version"],
                    "path": os.path.join(w["root_path"], w["name"]),
                    "sources": n,
                }
            )
        return out

    def _folder(self, folder_id: str) -> Any:
        w = self.conn.execute(
            "SELECT w.*, r.path AS root_path FROM work_folder w JOIN source_root r ON r.id=w.root_id WHERE w.id=?", (folder_id,)
        ).fetchone()
        if w is None:
            raise CoreError("work-folder-missing", name=folder_id)
        return w

    def _source_ids(self, w: Any) -> list[str]:
        return [r[0] for r in self.conn.execute("SELECT id FROM source WHERE root_id=? AND rel_path LIKE ? || '/%'", (w["root_id"], w["name"]))]

    def settings_batch(self, folder_id: str, source_type: str, bind_pictures: bool) -> dict[str, Any]:
        """作品设置的编辑批次：作品文件夹的类型与画面开关 + 组内每个原片的来源类型（整组一起设）；由编辑通道预览、应用、撤销。"""
        w = self._folder(folder_id)
        ops: list[dict[str, Any]] = [
            {"entity": "work_folder", "id": folder_id, "version": w["version"], "fields": {"source_type": source_type, "bind_pictures": bool(bind_pictures)}}
        ]
        for sid in self._source_ids(w):
            v = self.conn.execute("SELECT version, source_type FROM source WHERE id=?", (sid,)).fetchone()
            if v["source_type"] != source_type.strip():
                ops.append({"entity": "source", "id": sid, "version": v["version"], "fields": {"source_type": source_type}})
        return {"label": {"code": "work-settings", "args": {"name": w["name"]}}, "ops": ops}

    def rename(self, folder_id: str, new_name: str) -> dict[str, Any]:
        w = self._folder(folder_id)
        name = _valid_name(new_name)
        if name == w["name"]:
            return {"renamed": 0}
        root = w["root_path"]
        if not os.path.isdir(root):
            raise CoreError("root-offline", path=root)
        old_dir, new_dir = os.path.join(root, w["name"]), os.path.join(root, name)
        if not os.path.isdir(old_dir):
            raise CoreError("work-folder-missing", name=w["name"])
        case_only = rootpaths.norm(old_dir) == rootpaths.norm(new_dir)
        clash = self.conn.execute("SELECT 1 FROM work_folder WHERE root_id=? AND name=? AND id<>?", (w["root_id"], name, folder_id)).fetchone()
        if clash or (os.path.exists(new_dir) and not case_only):
            raise CoreError("work-folder-exists", name=name)
        try:
            os.rename(old_dir, new_dir)
        except OSError as e:
            raise CoreError("work-rename-failed", name=name, detail=str(e)) from None
        try:
            with transaction(self.conn):
                self.conn.execute("UPDATE work_folder SET name=?, updated_at=? WHERE id=?", (name, now_iso(), folder_id))
                cs = self._rewrite(old_dir, new_dir)  # 作品跟着新文件夹名走；派生采样的 work: 标签在 move_source 里重算
        except Exception:
            os.rename(new_dir, old_dir)  # 数据库没改成：文件夹名改回去
            raise
        self._changed(cs)
        return {"renamed": len(cs.entities.get("source", ()))}
