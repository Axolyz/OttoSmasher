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
from ottosmasher.domain.mapping import Mapping, check_range
from ottosmasher.media import decode as dec
from ottosmasher.media import wavfile
from ottosmasher.store.workspace import Workspace

from . import assets as assets_mod
from .clock import new_id, now_iso
from .edits import dumps
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
        start, end = check_range(start, end, asset["duration"], frame=1.0 / assets_mod.rate_of(self.conn, asset))
        ref, win, media = assets_mod.locate(self.conn, self.ws.root, asset, start, end)
        assets_mod.check_media(media)
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
        assets_mod.check_media(media)  # 生成期间源文件变化 → 报错
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


def track_label(asset: dict[str, Any], words: dict[str, str]) -> str:
    """导出文件名的“音轨”段（规格 12 §12.1）：按角色写 原混音 / 人声 / 音效，加工成品写 拉平 / 回导，
    其他声部写声部原名（大小写原样）。固定词由调用方按界面语言给出。"""
    if asset["origin"] == "flatten":
        return words.get("flatten", "flatten")
    if asset["origin"] == "reimport":
        return words.get("reimport", "reimport")
    roles = set(asset.get("roles") or [])
    if roles:
        return "+".join(words.get(r, r) for r in ("vocal", "sfx") if r in roles)
    if asset["origin"] == "separation" and asset.get("stem_name"):
        return str(asset["stem_name"])
    return words.get("original", "original")


def processing_label(asset: dict[str, Any], words: dict[str, str]) -> str:
    """导出文件名的“处理信息”段（规格 12 §12.1）：拉平成品为「拉平-<音名>」（音名取登记时记录的目标音）；其余为空（整段省略）。"""
    if asset["origin"] == "flatten":
        name = ((asset.get("production") or {}).get("target") or {}).get("name")
        if name:
            return f"{words.get('flatten', 'flatten')}-{name}"
    return ""


def export_samples(svc: ExportService, ids: list[str], words: dict[str, str]) -> list[str]:
    """整个采样导出 WAV（拖出、交接）：内容 = 采样当前名称；同一请求复用同一文件。"""
    out = []
    for sid in dict.fromkeys(ids):
        row = svc.conn.execute('SELECT asset_id, start, "end", name FROM sample WHERE id=?', (sid,)).fetchone()
        if row is None:
            raise CoreError("sample-not-found", id=sid)
        asset = assets_mod.get(svc.conn, row[0])
        r = svc.export_wav(row[0], row[1], row[2], content=row[3], track=track_label(asset, words), processing=processing_label(asset, words))
        out.append(r["path"])
    return out
