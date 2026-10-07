"""波形峰值服务（规格 05 §5.3.2：后台生成、不阻塞打开与跳转；16 R22.10：点数有上限）。

请求时有缓存就直接切片返回；没有就交给一个后台线程生成（同一文件只生成一次），先返回 ``pending``，
生成好后发 ``peaks.ready`` 事件（失败发 ``peaks.failed``，带错误码），界面再来取。
"""

from __future__ import annotations

import logging
import threading
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from typing import Any

from ottosmasher.media import peaks as peaks_mod
from ottosmasher.store.workspace import Workspace

from . import assets as assets_mod
from .errors import CoreError

log = logging.getLogger(__name__)


class WaveformService:
    def __init__(self, conn: Any, ws: Workspace, *, post: Callable[[Callable[[], None]], None], emit: Callable[[str, Any], None]) -> None:
        self.conn = conn
        self.ws = ws
        self.post = post
        self.emit = emit
        self._pool = ThreadPoolExecutor(max_workers=1, thread_name_prefix="peaks")
        self._lock = threading.Lock()
        self._waiting: dict[str, set[str]] = {}  # 缓存文件 → 等它的资产
        self._proc: Any = None
        self._closing = False

    @property
    def cache(self):
        return self.ws.data / "Cache"

    def get(self, asset_id: str, start: float, end: float, points: int) -> dict[str, Any]:
        asset = assets_mod.get(self.conn, asset_id)
        if not (0 <= start < end <= asset["duration"] + 1e-6):
            raise CoreError("range-invalid", reason="out-of-bounds", start=start, end=end, duration=asset["duration"])
        ref, win, media = assets_mod.locate(self.conn, self.ws.root, asset, start, min(end, asset["duration"]))
        assets_mod.check_media(media)
        pk = peaks_mod.load(self.cache, ref)
        if pk is None:
            self._schedule(asset_id, ref)
            return {"state": "pending"}
        q = pk.query(win.to_file(start), win.to_file(min(end, asset["duration"])), points)
        q["start"] = win.to_local(q["start"])
        return {"state": "ready", **q}

    def _schedule(self, asset_id: str, ref: Any) -> None:
        key = str(peaks_mod.cache_path(self.cache, ref))
        with self._lock:
            if key in self._waiting:
                self._waiting[key].add(asset_id)
                return
            self._waiting[key] = {asset_id}
        self._pool.submit(self._build, key, ref)

    def _build(self, key: str, ref: Any) -> None:
        error: dict[str, Any] | None = None
        try:
            peaks_mod.build(ref, self.cache, on_proc=self._set_proc)
        except CoreError as e:
            error = e.to_wire()
        except Exception as e:  # noqa: BLE001 - 后台线程里的任何异常都要告诉界面，不能悄悄吞掉
            log.exception("peaks build failed")
            error = {"code": "decode-failed", "args": {"path": ref.path, "detail": repr(e)}}
        finally:
            self._proc = None
        with self._lock:
            assets = sorted(self._waiting.pop(key, set()))
        if self._closing:
            return
        if error is None:
            self.post(lambda: self.emit("peaks.ready", {"assetIds": assets}))
        else:
            self.post(lambda: self.emit("peaks.failed", {"assetIds": assets, "error": error}))

    def _set_proc(self, p: Any) -> None:
        self._proc = p
        if self._closing:
            p.kill()

    def shutdown(self) -> None:
        """退出时结束正在跑的 ffmpeg，不等它（峰值是缓存，下次再生成）。"""
        self._closing = True
        self._pool.shutdown(wait=False, cancel_futures=True)
        p = self._proc
        if p is not None:
            p.kill()
