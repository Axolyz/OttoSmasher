"""播放句柄（规格 05 §5.3、16 R22.1–R22.3；ARCHITECTURE §10.1）。

播放器在 preload 里，只加载 Core 解析出来的位置：页面给的是原片/资产 ID 和区间，不是路径。
解析时核对文件快照：缺失或被替换 → 报错，绝不换成原混音或别的轨（规格 04 §4.4 #5）。
不解码、不导出 PCM、不读采样的其他资料（R22.3）。
"""

from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Any

from ottosmasher.domain.mapping import check_range
from ottosmasher.media import probe as probe_mod

from . import assets as assets_mod
from .edits import loads
from .errors import CoreError


HANG_TOLERANCE = 0.020
"""挂到原片时间轴的条件（05 §5.4）：映射每个控制点的 原片秒 − 局部秒 相同（容差 20 ms），即未变速。"""


def hang_offset(mapping: list[list[float]]) -> float | None:
    """未变速的映射 → 原片秒 = 局部秒 + 偏移；变速了返回 None。"""
    offs = [src - loc for loc, src in mapping]
    return offs[0] if max(offs) - min(offs) <= HANG_TOLERANCE else None


def resolve_source(conn: sqlite3.Connection, source_id: str, ordinal: int | None = None, *, asset_id: str | None = None, workspace_root: Path | None = None) -> dict[str, Any]:
    """原片播放器：原片文件 + 第几条音频流（mpv 的 aid = 序号 + 1，按音频流计数，不是容器流序号，R22.2）。
    ``asset_id`` 是分离声部等非容器音轨时：画面仍来自原片文件，声音用外挂音轨（mpv audio-files），
    音频延迟 = 原片秒 − 局部秒（R22.1：原片 103–123、声部局部 3–23 → 延迟 100）；只接受未变速的资产；
    声部文件缺失或被改动 → 报错，不回退原混音。返回覆盖范围（原片秒），越界由界面报错。"""
    if asset_id is not None:
        asset = assets_mod.get(conn, asset_id)
        if asset["source_id"] != source_id:
            raise CoreError("asset-not-found", id=asset_id)
        if asset["origin"] == "stream":
            ordinal = asset["stream_ordinal"]
        else:
            offset = hang_offset(asset["mapping"])
            if offset is None:
                raise CoreError("asset-not-hangable", id=asset_id)
            base = resolve_source(conn, source_id, None)
            ref, win, media = assets_mod.locate(conn, workspace_root or Path("."), asset, 0.0, asset["duration"])
            assets_mod.check_media(media)
            n_audio = conn.execute("SELECT COUNT(*) FROM source_stream WHERE source_id=? AND kind='audio'", (source_id,)).fetchone()[0]
            return {
                **base,
                "aid": n_audio + 1,  # 外挂音轨排在容器音轨之后
                "audioFile": ref.path,
                "audioDelay": offset - win.file_start,
                "coverage": [offset, offset + asset["duration"]],
            }
    row = conn.execute("SELECT path, file_snapshot, duration, default_audio_stream FROM source WHERE id=?", (source_id,)).fetchone()
    if row is None:
        raise CoreError("source-not-found", id=source_id)
    path, snap, duration, default = row
    ordinal = default if ordinal is None else int(ordinal)
    if conn.execute(
        "SELECT 1 FROM source_stream WHERE source_id=? AND kind='audio' AND ordinal=?", (source_id, ordinal)
    ).fetchone() is None:
        raise CoreError("stream-not-found", source=source_id, ordinal=ordinal)
    probe_mod.check_unchanged(path, loads(snap) if snap else {})
    has_video = (
        conn.execute(
            "SELECT 1 FROM source_stream WHERE source_id=? AND kind='video' AND is_attached_pic=0", (source_id,)
        ).fetchone()
        is not None
    )
    return {"path": path, "aid": ordinal + 1, "duration": duration, "hasVideo": has_video, "audioFile": None, "audioDelay": 0.0, "coverage": [0.0, duration]}


def resolve_asset(conn: sqlite3.Connection, workspace_root: Path, asset_id: str, start: float, end: float) -> dict[str, Any]:
    """试听播放器：资产区间 → 文件、音轨与文件时间区间（引擎按文件秒截停，R22.5）。"""
    asset = assets_mod.get(conn, asset_id)
    start, end = check_range(start, end, asset["duration"], frame=1.0 / assets_mod.rate_of(conn, asset))
    ref, win, media = assets_mod.locate(conn, workspace_root, asset, start, end)
    assets_mod.check_media(media)
    return {
        "path": ref.path,
        "aid": ref.ordinal + 1,
        "fileStart": win.to_file(start),
        "fileEnd": win.to_file(end),
        "localStart": start,
        "localEnd": end,
    }
