"""画面绑定（规格 12 §12.4、04 §4.2.10；ARCHITECTURE §4.8 ``visual_binding``；UI_PLAN §3、§8「画面绑定…」）。

- 模式：同步视频（画面时间 = 采样本地时间经映射换算的原片时间 + 偏移）、静态图片、独立循环动画（本地时间 mod 动画时长）、
  独立化的画面片段（``materialized_clip``：按原片时间取，偏移 = −片段起点）。
- 优先级：采样自己的绑定 > 原片的默认画面绑定 > 原片自带的第一条视频流（同步）。没有视频流的原片默认无画面。
- 编辑：绑定行是不可变的记录（``visuals.prepare`` 登记文件 → 一条未挂上的绑定）；挂上 / 换掉 / 去掉 = 改采样或原片的
  ``visual_binding_id``，走统一编辑通道（可撤销）。绑定文件记录大小和修改时间，变了 → 报“画面文件已改变”，不换别的（P6）。
- 时钟：音频是唯一主时钟；画面一律静音。
"""

from __future__ import annotations

import math
import os
import sqlite3
from pathlib import Path
from typing import Any

from ..domain.mapping import Mapping
from ..media import probe as probe_mod
from .clock import new_id, now_iso
from .edits import dumps, loads
from .errors import CoreError
from .imports import IMAGE_EXT, ANIM_EXT, VIDEO_EXT, _Pictures

MODES = ("sync", "image", "loop", "materialized_clip")


def kind_of(path: str) -> str:
    ext = Path(path).suffix.lower()
    if ext in VIDEO_EXT:
        return "video"
    if ext in ANIM_EXT:
        return "anim"
    if ext in IMAGE_EXT:
        return "image"
    raise CoreError("visual-invalid", reason="not-picture", path=path)


def _stat(path: str) -> tuple[int, int] | None:
    try:
        st = os.stat(path)
    except OSError:
        return None
    return st.st_size, st.st_mtime_ns


def prepare(conn: sqlite3.Connection, owner_type: str, owner_id: str, path: str, mode: str | None = None, offset: float = 0.0,
            *, location: str = "external") -> str:
    """登记一个画面文件为一条（还没挂上的）绑定，在调用方事务里；返回绑定 ID。"""
    if owner_type not in ("sample", "source"):
        raise CoreError("visual-invalid", reason="owner")
    path = os.path.abspath(path)
    st = _stat(path)
    if st is None:
        raise CoreError("file-missing", path=path)
    kind = kind_of(path)
    ordinal, duration = 0, None
    if kind in ("video", "anim"):
        pr = probe_mod.probe(path)
        v = pr.video
        if not v:
            raise CoreError("visual-invalid", reason="no-video", path=path)
        ordinal, duration = v[0].ordinal, v[0].duration or pr.format_duration
    allowed = {"video": ("sync", "loop", "materialized_clip"), "anim": ("loop",), "image": ("image",)}[kind]
    mode = mode or allowed[0]
    if mode not in allowed:
        raise CoreError("visual-invalid", reason="mode-for-kind", mode=mode, kind=kind)
    if mode == "loop" and not (duration and duration > 0):
        raise CoreError("visual-invalid", reason="loop-duration", path=path)
    mid, vid, ts = new_id(), new_id(), now_iso()
    snap = {"size": st[0], "mtime_ns": st[1], "videoOrdinal": ordinal, "duration": duration}
    conn.execute(
        "INSERT INTO media_file(id, path, location, file_snapshot, format, created_at) VALUES (?, ?, ?, ?, ?, ?)",
        (mid, path, location, dumps(snap), kind, ts),
    )
    conn.execute(
        "INSERT INTO visual_binding(id, owner_type, owner_id, mode, media_file_id, clip_offset, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        (vid, owner_type, owner_id, mode, mid, float(offset) if mode in ("sync", "materialized_clip") else None, ts, ts),
    )
    return vid


def _binding(conn: sqlite3.Connection, vid: str, root: Path | None = None) -> dict[str, Any] | None:
    r = conn.execute(
        "SELECT v.id, v.mode, v.clip_offset, v.owner_type, v.owner_id, m.path, m.location, m.file_snapshot, m.format"
        " FROM visual_binding v JOIN media_file m ON m.id = v.media_file_id WHERE v.id = ?",
        (vid,),
    ).fetchone()
    if r is None:
        return None
    snap = loads(r["file_snapshot"]) if r["file_snapshot"] else {}
    path = r["path"]
    if r["location"] == "library" and root is not None and not os.path.isabs(path):
        path = str(root / path)
    st = _stat(path)
    state = "missing" if st is None else ("changed" if (st[0], st[1]) != (snap.get("size"), snap.get("mtime_ns")) else "ok")
    return {
        "bindingId": r["id"], "mode": r["mode"], "offset": float(r["clip_offset"] or 0.0), "path": path, "kind": r["format"],
        "ordinal": int(snap.get("videoOrdinal") or 0), "duration": snap.get("duration"), "state": state,
    }


def resolve(conn: sqlite3.Connection, *, sample_id: str | None = None, source_id: str | None = None, root: Path | None = None) -> dict[str, Any] | None:
    """有效的画面（12 §12.4 优先级）：{origin: sample|source|stream, mode, path, ordinal, duration, offset, state, bindingId?}；没有 → None。"""
    if sample_id is not None:
        r = conn.execute(
            "SELECT s.visual_binding_id, a.source_id FROM sample s JOIN sound_asset a ON a.id = s.asset_id WHERE s.id = ?", (sample_id,)
        ).fetchone()
        if r is None:
            raise CoreError("sample-not-found", id=sample_id)
        if r[0]:
            b = _binding(conn, r[0], root)
            if b is not None:
                return {"origin": "sample", **b}
        source_id = r[1]
    if source_id is None:
        return None
    src = conn.execute("SELECT path, visual_binding_id, media_state FROM source WHERE id = ?", (source_id,)).fetchone()
    if src is None:
        raise CoreError("source-not-found", id=source_id)
    if src["visual_binding_id"]:
        b = _binding(conn, src["visual_binding_id"], root)
        if b is not None:
            return {"origin": "source", **b}
    if src["media_state"] != "available":
        return None
    v = conn.execute(
        "SELECT ordinal, duration, start_time FROM source_stream WHERE source_id = ? AND kind = 'video' AND is_attached_pic = 0 ORDER BY ordinal LIMIT 1",
        (source_id,),
    ).fetchone()
    if v is None:
        return None
    return {"origin": "stream", "bindingId": None, "mode": "sync", "offset": 0.0, "path": src["path"], "kind": "video", "ordinal": int(v["ordinal"]),
            "duration": v["duration"], "state": "ok" if os.path.isfile(src["path"]) else "missing"}


def picture_time(b: dict[str, Any], source_t: float | None, local_t: float) -> float:
    """画面文件里的时间：同步 = 原片秒 + 偏移；图片 = 0；循环 = 本地秒 mod 时长。原片秒未知 → NaN（黑帧 / 不画）。"""
    if b["mode"] == "image":
        return 0.0
    if b["mode"] == "loop":
        d = float(b["duration"] or 0.0)
        return local_t % d if d > 0 else 0.0
    if source_t is None:
        return math.nan
    return source_t + float(b["offset"] or 0.0)


def check_ok(b: dict[str, Any]) -> None:
    if b["state"] == "missing":
        raise CoreError("file-missing", path=b["path"])
    if b["state"] == "changed":
        raise CoreError("visual-changed", path=b["path"])


def for_sample(conn: sqlite3.Connection, sample_id: str, root: Path | None = None) -> dict[str, Any]:
    """舞台画面（UI_PLAN §3）：有效绑定 + 采样范围 + 映射控制点（本地秒 → 原片秒），界面按播放位置换算画面时间。"""
    r = conn.execute('SELECT s.asset_id, s.start, s."end", a.mapping FROM sample s JOIN sound_asset a ON a.id = s.asset_id WHERE s.id = ?',
                     (sample_id,)).fetchone()
    if r is None:
        raise CoreError("sample-not-found", id=sample_id)
    b = resolve(conn, sample_id=sample_id, root=root)
    knots = None
    try:
        knots = Mapping.of(loads(r["mapping"])).to_list() if r["mapping"] else None
    except CoreError:
        knots = None
    return {"binding": b, "start": r["start"], "end": r["end"], "mapping": knots}


def match_plan(conn: sqlite3.Connection, source_ids: list[str]) -> list[dict[str, Any]]:
    """原片批量“匹配同名画面”（ARCHITECTURE §4.10）：同一文件夹里与原片同名（不含扩展名）的视频 / 动图 / 图片；视频 > 动图 > 图片。
    只看不写。自己有视频流的原片也列出（绑定会盖过自带画面）。"""
    pics = _Pictures(probe_mod.probe)
    out = []
    for sid in dict.fromkeys(source_ids):
        r = conn.execute("SELECT path, visual_binding_id FROM source WHERE id = ?", (sid,)).fetchone()
        if r is None:
            raise CoreError("source-not-found", id=sid)
        found = pics.find(r["path"])
        out.append({"sourceId": sid, "picture": found["path"] if found else None, "kind": found["kind"] if found else None,
                    "conflicts": found["conflicts"] if found else [], "hasBinding": bool(r["visual_binding_id"])})
    return out
