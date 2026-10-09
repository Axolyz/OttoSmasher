"""列表缩略图服务（规格 16 R22.11、ARCHITECTURE §10.2；UI_PLAN D2、§3 每行 88×50）。

- 原片：整片中点；采样：本地中点经资产映射换到原片时间（分段映射，变速的也对）。
- 取帧对象：原片有画面绑定时用绑定的媒体（图片 / 动图取第一帧，同步视频按原片时间）；否则原片的第一条真正的视频流（封面图不算）。
  没有画面、媒体已释放、文件找不到、映射换算失败 → ``none``，不生成占位图。
- 缓存键 = 文件路径 + 文件快照 + 视频流序号 + 取帧时间 + 尺寸的哈希；文件或绑定变了键就变，旧图自然不再用（可清理缓存）。
- 有缓存直接回 JPEG 字节；没有就排进后台（并发 2），先回 ``pending``，做好后发 ``thumbs.ready``（带等它的条目）；
  失败的键在本次运行里记住，回 ``failed``，不反复重试。
"""

from __future__ import annotations

import hashlib
import math
import logging
import os
import threading
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any

from ottosmasher.domain.mapping import Mapping
from ottosmasher.media import thumbs as thumbs_mod
from ottosmasher.store.workspace import Workspace

from . import visuals as visuals_mod
from .edits import loads
from .errors import CoreError

log = logging.getLogger(__name__)

MAX_ITEMS = 200


class ThumbnailService:
    def __init__(self, conn: Any, ws: Workspace, *, post: Callable[[Callable[[], None]], None], emit: Callable[[str, Any], None]) -> None:
        self.conn = conn
        self.ws = ws
        self.post = post
        self.emit = emit
        self._pool = ThreadPoolExecutor(max_workers=2, thread_name_prefix="thumbs")
        self._lock = threading.Lock()
        self._waiting: dict[str, list[dict[str, str]]] = {}  # 缓存文件 → 等它的条目
        self._failed: set[str] = set()
        self._procs: set[Any] = set()
        self._closing = False

    @property
    def dir(self) -> Path:
        return self.ws.data / "Cache" / "Thumbs"

    def _picture_target(self, b: dict[str, Any] | None, source_t: float, local_t: float, length_hint: float | None) -> tuple[str, int, float, str] | None:
        """有效画面（12 §12.4 的优先级）在这一刻的那一帧：同步 = 原片秒 + 偏移，图片 = 第一帧，循环 = 本地秒 mod 时长。"""
        if b is None or b["state"] != "ok":
            return None  # 没有画面、文件找不到或改过：不生成占位图
        st = os.stat(b["path"])
        snap = f"{st.st_size}:{st.st_mtime_ns}"
        tt = visuals_mod.picture_time(b, source_t, local_t)
        if not math.isfinite(tt):
            return None
        length = b["duration"] or length_hint
        if length:
            tt = min(tt, max(0.0, float(length) - 0.1))  # 末尾一帧之外取不到画面：贴到最后 0.1 秒之内
        return b["path"], int(b["ordinal"]), max(0.0, tt), snap

    def _source_target(self, source_id: str, t: float | None) -> tuple[str, int, float, str] | None:
        src = self.conn.execute("SELECT duration FROM source WHERE id=?", (source_id,)).fetchone()
        if src is None:
            return None
        b = visuals_mod.resolve(self.conn, source_id=source_id, root=self.ws.root)
        tt = (src["duration"] or 0.0) / 2 if t is None else t
        return self._picture_target(b, tt, tt, src["duration"])

    def _target(self, kind: str, item_id: str) -> tuple[str, int, float, str] | None:
        if kind == "source":
            return self._source_target(item_id, None)
        if kind == "sample":
            r = self.conn.execute(
                'SELECT s.start, s."end", a.mapping, a.source_id FROM sample s JOIN sound_asset a ON a.id=s.asset_id WHERE s.id=?', (item_id,)
            ).fetchone()
            if r is None:
                return None
            try:
                t = Mapping.of(loads(r["mapping"])).to_source((r["start"] + r["end"]) / 2)
            except CoreError:
                return None
            # 采样自己的画面绑定优先（12 §12.4）；缩略图取本地中点
            b = visuals_mod.resolve(self.conn, sample_id=item_id, root=self.ws.root)
            dur = self.conn.execute("SELECT duration FROM source WHERE id=?", (r["source_id"],)).fetchone()
            return self._picture_target(b, t, (r["end"] - r["start"]) / 2, dur[0] if dur else None)
        raise ValueError(f"thumbnail kind {kind!r}")

    def _path(self, target: tuple[str, int, float, str], size: str) -> Path:
        path, ordinal, t, snap = target
        w, h = thumbs_mod.SIZES[size]
        key = f"{path}\n{snap}\n{ordinal}\n{t:.2f}\n{w}x{h}"
        h = hashlib.sha1(key.encode("utf-8")).hexdigest()
        return self.dir / h[:2] / f"{h}.jpg"

    def get(self, items: list[dict[str, str]]) -> list[dict[str, Any]]:
        out = []
        for it in items[:MAX_ITEMS]:
            kind, item_id, size = str(it["kind"]), str(it["id"]), str(it.get("size", "list"))
            if size not in thumbs_mod.SIZES:
                raise ValueError(f"thumbnail size {size!r}")
            row: dict[str, Any] = {"kind": kind, "id": item_id, "size": size}
            target = self._target(kind, item_id)
            if target is None:
                row["state"] = "none"
            else:
                p = self._path(target, size)
                key = str(p)
                if p.is_file():
                    row["state"], row["data"] = "ready", p.read_bytes()
                elif key in self._failed:
                    row["state"] = "failed"
                else:
                    row["state"] = "pending"
                    self._schedule(key, target, size, {"kind": kind, "id": item_id, "size": size})
            out.append(row)
        return out

    def _schedule(self, key: str, target: tuple[str, int, float, str], size: str, item: dict[str, str]) -> None:
        with self._lock:
            if key in self._waiting:
                if item not in self._waiting[key]:
                    self._waiting[key].append(item)
                return
            self._waiting[key] = [item]
        self._pool.submit(self._build, key, target, size)

    def _build(self, key: str, target: tuple[str, int, float, str], size: str) -> None:
        ok = True
        try:
            if not self._closing:
                thumbs_mod.grab(target[0], target[1], target[2], Path(key), size=size, on_proc=self._track)
        except Exception as e:  # noqa: BLE001 - 后台线程：记下失败、告诉界面，不悄悄吞掉
            ok = False
            log.warning("thumbnail failed: %s @%.2f: %r", target[0], target[2], e)
        with self._lock:
            items = self._waiting.pop(key, [])
            if not ok:
                self._failed.add(key)
        if self._closing:
            return
        self.post(lambda: self.emit("thumbs.ready", {"items": items}))

    def _track(self, p: Any) -> None:
        with self._lock:
            self._procs = {x for x in self._procs if x.poll() is None}
            self._procs.add(p)
        if self._closing:
            p.kill()

    def shutdown(self) -> None:
        """退出时结束正在跑的 ffmpeg，不等（缩略图是缓存，下次再生成）。"""
        self._closing = True
        self._pool.shutdown(wait=False, cancel_futures=True)
        with self._lock:
            procs = list(self._procs)
        for p in procs:
            if p.poll() is None:
                p.kill()
