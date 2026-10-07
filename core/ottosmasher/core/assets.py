"""声音资产（规格 04 §4.2.3–§4.2.4、16 R2；ARCHITECTURE §4.2）。

阶段 2 只做原片自带音频流的整轨资产：登记时每条音频流一个资产（恒等映射，局部时间 = 原片时间），
物理存储指向原片文件本身（``media_file`` location=external，不复制）。资产创建后不可变。
角色与默认轨的编辑界面在阶段 3；这里先给出默认轨的资格判定（完整覆盖且未变速，容差 20 ms）。
"""

from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Any

from ottosmasher.domain.mapping import FileWindow, Mapping
from ottosmasher.media import decode as dec
from ottosmasher.media import probe as probe_mod

from .clock import new_id, now_iso
from .edits import dumps, loads
from .errors import CoreError


def create_stream_assets(
    conn: sqlite3.Connection, source_id: str, path: str, snap: dict[str, Any], pr: probe_mod.Probe
) -> list[dict[str, Any]]:
    """在调用方的事务里建原片文件的 media_file 和每条音频流的整轨资产。

    时长未知的音频流不建资产，如实返回在 ``skipped`` 里（不编时长）。
    """
    ts = now_iso()
    mid = new_id()
    conn.execute(
        "INSERT INTO media_file(id, path, location, file_snapshot, format, created_at) VALUES (?, ?, 'external', ?, ?, ?)",
        (mid, path, dumps(snap), pr.format_name, ts),
    )
    out: list[dict[str, Any]] = []
    for s in pr.audio:
        if s.duration is None or s.duration <= 0:
            out.append({"ordinal": s.ordinal, "assetId": None, "skipped": "no-duration"})
            continue
        aid = new_id()
        mapping = Mapping.identity(s.duration)
        conn.execute(
            "INSERT INTO sound_asset(id, source_id, origin, media_file_id, stream_ordinal, duration, mapping, language, created_at)"
            " VALUES (?, ?, 'stream', ?, ?, ?, ?, ?, ?)",
            (aid, source_id, mid, s.ordinal, s.duration, dumps(mapping.to_list()), s.language, ts),
        )
        conn.execute(
            "INSERT INTO asset_storage(asset_id, range_start, range_end, media_file_id, kind) VALUES (?, 0, ?, ?, 'primary')",
            (aid, s.duration, mid),
        )
        out.append({"ordinal": s.ordinal, "assetId": aid, "skipped": None})
    return out


def source_media_files(conn: sqlite3.Connection, source_id: str) -> list[str]:
    """原片文件本身对应的 media_file（重新定位时一起改位置）。"""
    return [
        r[0]
        for r in conn.execute(
            "SELECT DISTINCT media_file_id FROM sound_asset WHERE source_id=? AND origin='stream' AND media_file_id IS NOT NULL",
            (source_id,),
        )
    ]


def get(conn: sqlite3.Connection, asset_id: str) -> dict[str, Any]:
    row = conn.execute("SELECT * FROM sound_asset WHERE id=?", (asset_id,)).fetchone()
    if row is None:
        raise CoreError("asset-not-found", id=asset_id)
    d = dict(row)
    d["mapping"] = loads(d["mapping"])
    d["production"] = loads(d["production"]) if d["production"] else None
    d["roles"] = [
        r[0] for r in conn.execute("SELECT role FROM asset_role WHERE asset_id=? AND state='on' ORDER BY role", (asset_id,))
    ]
    return d


def list_for_source(conn: sqlite3.Connection, source_id: str) -> list[dict[str, Any]]:
    """原片的全部资产：整轨（完整覆盖且未变速）在前，同类按创建时间。"""
    src = conn.execute("SELECT duration FROM source WHERE id=?", (source_id,)).fetchone()
    if src is None:
        raise CoreError("source-not-found", id=source_id)
    out = []
    for (aid,) in conn.execute("SELECT id FROM sound_asset WHERE source_id=? ORDER BY created_at, stream_ordinal, rowid", (source_id,)):
        a = get(conn, aid)
        a["isFullTrack"] = Mapping.of(a["mapping"]).is_full_track(src[0])
        out.append(a)
    out.sort(key=lambda a: (not a["isFullTrack"], a["origin"] != "stream"))
    return out


def check_default_track(conn: sqlite3.Connection, source_id: str, asset_id: str, role: str) -> None:
    """默认轨只能从带该角色、属于该原片、完整覆盖原片且未变速（容差 20 ms）的资产里选（R2.1–R2.2）。"""
    a = get(conn, asset_id)
    if a["source_id"] != source_id:
        raise CoreError("default-track-invalid", reason="other-source", asset=asset_id)
    src = conn.execute("SELECT duration FROM source WHERE id=?", (source_id,)).fetchone()
    if not Mapping.of(a["mapping"]).is_full_track(src[0]):
        raise CoreError("default-track-invalid", reason="not-full-track", asset=asset_id)
    if role not in a["roles"]:
        raise CoreError("default-track-invalid", reason="missing-role", asset=asset_id, role=role)


# ---------------------------------------------------------------- 定位声音（导出、波形、播放共用）


def rate_of(conn: sqlite3.Connection, asset: dict[str, Any]) -> int:
    """资产的采样率（端点一帧容差用）。"""
    if asset["origin"] == "stream":
        r = conn.execute(
            "SELECT sample_rate FROM source_stream WHERE source_id=? AND kind='audio' AND ordinal=?",
            (asset["source_id"], asset["stream_ordinal"]),
        ).fetchone()
        if r and r[0]:
            return int(r[0])
    r = conn.execute("SELECT sample_rate FROM media_file WHERE id=?", (asset["media_file_id"],)).fetchone()
    if r and r[0]:
        return int(r[0])
    raise CoreError("decode-failed", path=None, detail="unknown-sample-rate")


def locate(
    conn: sqlite3.Connection, workspace_root: Path, asset: dict[str, Any], start: float, end: float
) -> tuple[dec.StreamRef, FileWindow, dict[str, Any]]:
    """资产局部区间 [start, end) → 存放它的文件、流与文件时间窗口（主存储优先）。找不到覆盖它的存储 → 报错。"""
    rows = conn.execute(
        "SELECT s.range_start, s.range_end, m.id, m.path, m.location, m.file_snapshot, m.format"
        " FROM asset_storage s JOIN media_file m ON m.id = s.media_file_id WHERE s.asset_id=?"
        " ORDER BY s.kind='primary' DESC",
        (asset["id"],),
    ).fetchall()
    for r in rows:
        win = FileWindow(r[0], r[1])
        if not win.covers(start, end):
            continue
        path = r[3] if r[4] == "external" else str(workspace_root / r[3])
        snap = loads(r[5]) if r[5] else {}
        if asset["origin"] == "stream":
            st = conn.execute(
                "SELECT sample_rate, channels, codec FROM source_stream WHERE source_id=? AND kind='audio' AND ordinal=?",
                (asset["source_id"], asset["stream_ordinal"]),
            ).fetchone()
            ordinal, rate, channels, codec = asset["stream_ordinal"], st[0], st[1], st[2]
        else:
            check_media({"path": path, "snapshot": snap})
            pr = probe_mod.probe(path)
            ordinal, rate, channels, codec = 0, pr.audio[0].sample_rate, pr.audio[0].channels, pr.audio[0].codec
        if not rate or not channels:
            raise CoreError("decode-failed", path=path, detail="unknown-format")
        return dec.StreamRef(path, ordinal, rate, channels, codec, r[6]), win, {"media_file_id": r[2], "path": path, "snapshot": snap}
    raise CoreError("asset-file-missing", id=asset["id"])


def check_media(media: dict[str, Any]) -> None:
    """用之前核对文件：缺失 → “绑定音轨缺失”；大小/修改时间变了 → “音源已改变”。不回退到别的轨。"""
    try:
        probe_mod.check_unchanged(media["path"], media["snapshot"])
    except CoreError as e:
        if e.code == "file-missing":
            raise CoreError("asset-file-missing", path=media["path"]) from None
        raise
