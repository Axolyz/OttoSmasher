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


def resolve_source(conn: sqlite3.Connection, source_id: str, ordinal: int | None = None) -> dict[str, Any]:
    """原片播放器：原片文件 + 第几条音频流（mpv 的 aid = 序号 + 1，按音频流计数，不是容器流序号，R22.2）。"""
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
    return {"path": path, "aid": ordinal + 1, "duration": duration, "hasVideo": has_video}


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
