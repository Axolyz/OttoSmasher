"""波形峰值服务（规格 05 §5.3.2：后台生成、不阻塞打开与跳转；16 R22.10：点数有上限）。

细节窗（R22.10：≤30 秒）：视口不超过 30 秒、而缓存的峰值（每 256 样本一对）比请求的点数粗时，
直接精确解码这段（约 45 ms），按点数求每点的 (最小, 最大)；放大到底能看到逐个样本。
其余情况：有缓存就直接切片返回；没有就交给一个后台线程生成（同一文件只生成一次），先返回 ``pending``，
生成好后发 ``peaks.ready`` 事件（失败发 ``peaks.failed``，带错误码），界面再来取。
"""

from __future__ import annotations

import logging
import math
import threading
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from typing import Any

import numpy as np

from ottosmasher.media import decode as dec
from ottosmasher.media import peaks as peaks_mod
from ottosmasher.store.workspace import Workspace

from . import assets as assets_mod
from .errors import CoreError

log = logging.getLogger(__name__)

DETAIL_MAX = 30.0


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
        end = min(end, asset["duration"])
        points = max(1, min(int(points), peaks_mod.MAX_POINTS))
        if end - start <= DETAIL_MAX and points > (end - start) * ref.sample_rate / peaks_mod.BUCKET:
            return self._detail(ref, win, start, end, points)
        pk = peaks_mod.load(self.cache, ref)
        if pk is None:
            self._schedule(asset_id, ref)
            return {"state": "pending"}
        q = pk.query(win.to_file(start), win.to_file(end), points)
        q["start"] = win.to_local(q["start"])
        return {"state": "ready", **q}

    def _detail(self, ref: Any, win: Any, start: float, end: float, points: int) -> dict[str, Any]:
        sr = ref.sample_rate
        a, b = round(win.to_file(start) * sr), round(win.to_file(end) * sr)
        pcm = dec.decode_frames(ref, a, max(b, a + 1), cache=self.cache)
        lo, hi = pcm.min(axis=1), pcm.max(axis=1)
        n = len(lo)
        g = max(1, math.ceil(n / points))
        m = math.ceil(n / g)
        pad = m * g - n
        if pad:
            lo = np.concatenate([lo, np.full(pad, lo[-1], lo.dtype)])
            hi = np.concatenate([hi, np.full(pad, hi[-1], hi.dtype)])
        mins = lo.reshape(m, g).min(axis=1).astype("<f4")
        maxs = hi.reshape(m, g).max(axis=1).astype("<f4")
        return {
            "state": "ready",
            "start": win.to_local(a / sr),
            "step": g / sr,
            "min": mins.tobytes(),
            "max": maxs.tobytes(),
            "count": m,
        }

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
