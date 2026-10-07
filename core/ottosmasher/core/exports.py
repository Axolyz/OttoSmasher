"""导出 WAV（规格 12 §12.1、16 R21.1–R21.3、R21.6；ARCHITECTURE §6、§10.3）。

- 内容：资产的真实区间，PCM 24-bit，采样率与声道跟随源；不含试听留白，不新增采样、分析、任务；
- 位置：显式目录优先，否则素材库 ``Library/Exports/<日期>/``；
- 复用：按“资产 + 文件身份 + 区间 + 版本 + 名称”的稳定键复用已生成的文件；文件被外部改过 → 报错不覆盖；
  目标位置已有不是本应用记录的同名文件 → 报错不覆盖；
- 安全：导出前后都核对源文件快照（生成期间源文件变化 → 报错）；绑定音轨缺失 → 报错，绝不换成原混音；
- 原子发布：先写 ``Data/Staging``，同卷 ``os.replace``；跨卷先复制为目标目录里的隐藏临时名再改名。
段里的固定词（音轨名、“ · 片段”等）由调用方按界面语言给出。
"""

from __future__ import annotations

import hashlib
import os
import shutil
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Any

from ottosmasher.domain import filename as fname
from ottosmasher.domain.mapping import FileWindow, Mapping, check_range
from ottosmasher.media import decode as dec
from ottosmasher.media import probe as probe_mod
from ottosmasher.media import wavfile
from ottosmasher.store.workspace import Workspace

from . import assets as assets_mod
from .clock import new_id, now_iso
from .edits import dumps, loads
from .errors import CoreError

VERSION_ORIGINAL = "original"


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


class ExportService:
    def __init__(self, conn: sqlite3.Connection, ws: Workspace) -> None:
        self.conn = conn
        self.ws = ws

    # ------------------------------------------------------------ 定位声音

    def _stream_of(self, asset: dict[str, Any], start: float, end: float) -> tuple[dec.StreamRef, FileWindow, dict[str, Any]]:
        """资产区间 → 存放它的文件、流与文件时间窗口。"""
        rows = self.conn.execute(
            "SELECT s.range_start, s.range_end, m.id, m.path, m.location, m.file_snapshot, m.format"
            " FROM asset_storage s JOIN media_file m ON m.id = s.media_file_id WHERE s.asset_id=?"
            " ORDER BY s.kind='primary' DESC",
            (asset["id"],),
        ).fetchall()
        for r in rows:
            win = FileWindow(r[0], r[1])
            if not win.covers(start, end):
                continue
            path = r[3] if r[4] == "external" else str(self.ws.root / r[3])
            snap = loads(r[5]) if r[5] else {}
            if asset["origin"] == "stream":
                st = self.conn.execute(
                    "SELECT sample_rate, channels, codec FROM source_stream WHERE source_id=? AND kind='audio' AND ordinal=?",
                    (asset["source_id"], asset["stream_ordinal"]),
                ).fetchone()
                ordinal = asset["stream_ordinal"]
                rate, channels, codec = st[0], st[1], st[2]
            else:
                pr = probe_mod.probe(path)
                ordinal, rate, channels, codec = 0, pr.audio[0].sample_rate, pr.audio[0].channels, pr.audio[0].codec
            if not rate or not channels:
                raise CoreError("decode-failed", path=path, detail="unknown-format")
            ref = dec.StreamRef(path, ordinal, rate, channels, codec, r[6])
            return ref, win, {"media_file_id": r[2], "path": path, "snapshot": snap}
        raise CoreError("asset-file-missing", id=asset["id"])

    def _rate_of(self, asset: dict[str, Any]) -> int:
        if asset["origin"] == "stream":
            r = self.conn.execute(
                "SELECT sample_rate FROM source_stream WHERE source_id=? AND kind='audio' AND ordinal=?",
                (asset["source_id"], asset["stream_ordinal"]),
            ).fetchone()
            if r and r[0]:
                return int(r[0])
        r = self.conn.execute("SELECT sample_rate FROM media_file WHERE id=?", (asset["media_file_id"],)).fetchone()
        if r and r[0]:
            return int(r[0])
        raise CoreError("decode-failed", path=None, detail="unknown-sample-rate")

    def _check_file(self, media: dict[str, Any]) -> None:
        try:
            probe_mod.check_unchanged(media["path"], media["snapshot"])
        except CoreError as e:
            if e.code == "file-missing":
                raise CoreError("asset-file-missing", path=media["path"]) from None
            raise

    # ------------------------------------------------------------ 导出

    def export_wav(
        self,
        asset_id: str,
        start: float,
        end: float,
        *,
        content: str,
        track: str,
        local_prefix: str | None = None,
        processing: str = "",
        directory: str | None = None,
    ) -> dict[str, Any]:
        asset = assets_mod.get(self.conn, asset_id)
        mapping = Mapping.of(asset["mapping"])
        # 先按资产时长做一帧容差的端点校验（R3.4），再找存放这段的文件
        start, end = check_range(start, end, asset["duration"], frame=1.0 / self._rate_of(asset))
        ref, win, media = self._stream_of(asset, start, end)
        self._check_file(media)
        sr = ref.sample_rate
        a, b = round(win.to_file(start) * sr), round(win.to_file(end) * sr)
        key = hashlib.sha256(
            dumps([asset_id, media["media_file_id"], media["snapshot"], a, b, sr, VERSION_ORIGINAL, content, track, processing]).encode()
        ).hexdigest()

        src = self.conn.execute("SELECT id, path FROM source WHERE id=?", (asset["source_id"],)).fetchone()
        if local_prefix is None:
            s0, s1 = mapping.to_source(start), mapping.to_source(end)
        else:
            s0, s1 = start, end
        name = fname.export_filename(
            fname.ExportNameParts(
                content=content,
                track=track,
                source_name=Path(src[1]).stem,
                source_id=src[0],
                start=s0,
                end=s1,
                export_key=key,
                processing=processing,
                local_prefix=local_prefix,
            )
        )
        target_dir = Path(directory) if directory else self.ws.library / "Exports" / datetime.now().strftime("%Y-%m-%d")

        # 复用：同一稳定键
        row = self.conn.execute("SELECT path, size, mtime_ns FROM export_file WHERE stable_key=?", (key,)).fetchone()
        if row is not None and (not directory or Path(row[0]).parent == target_dir):
            p = Path(row[0])
            if p.is_file():
                st = p.stat()
                if (st.st_size, st.st_mtime_ns) != (row[1], row[2]):
                    raise CoreError("export-modified", path=str(p))
                return {"path": str(p), "reused": True, "key": key}
        target = target_dir / name
        if target.exists():
            raise CoreError("export-exists", path=str(target))

        pcm = dec.decode_frames(ref, a, b, cache=self.ws.data / "Cache")
        self._check_file(media)  # 生成期间源文件变化 → 报错
        target_dir.mkdir(parents=True, exist_ok=True)
        staged = self.ws.staging / f"{new_id()}.wav"
        self.ws.staging.mkdir(parents=True, exist_ok=True)
        try:
            wavfile.save_wav24(staged, pcm, sr)
            self._publish(staged, target)
        finally:
            staged.unlink(missing_ok=True)
        st = target.stat()
        self.conn.execute(
            "INSERT OR REPLACE INTO export_file(stable_key, path, kind, size, mtime_ns, sha256, created_at) VALUES (?, ?, 'wav', ?, ?, ?, ?)",
            (key, str(target), st.st_size, st.st_mtime_ns, _sha256(target), now_iso()),
        )
        return {"path": str(target), "reused": False, "key": key}

    def _publish(self, staged: Path, target: Path) -> None:
        """原子发布，不覆盖已有文件。"""
        try:
            same_volume = os.stat(staged).st_dev == os.stat(target.parent).st_dev
        except FileNotFoundError:
            same_volume = False
        src = staged
        tmp: Path | None = None
        if not same_volume:
            tmp = target.parent / f".{target.name}.{new_id()[:8]}.tmp"
            shutil.copyfile(staged, tmp)
            src = tmp
        try:
            try:
                os.link(src, target)  # 目标已存在就失败（原子的“不覆盖”）
            except FileExistsError:
                raise CoreError("export-exists", path=str(target)) from None
            except OSError:
                # 文件系统不支持硬链接（如部分网络盘）：先查再改名
                if target.exists():
                    raise CoreError("export-exists", path=str(target)) from None
                os.replace(src, target)
        finally:
            if tmp is not None:
                tmp.unlink(missing_ok=True)
