"""外部回导（规格 06 §6.7、16 S8、R3.7–R3.8；UI_PLAN §8 动作条「回导」；原型 reimportModal）。

- 只用当前选区的**起点**；终点 = 起点 + 回导文件自身的时长（手选终点被忽略）；终点超出当前资产（超过一帧）→ 拒绝，不保存；
- 沿用该段的时间映射；不补静音、不裁切、不变速、不推断成品内部的剪辑；采样率可以与原音频不同（时长按文件自身算）；
- 文件**复制进素材库、保持原格式（无损）**：``Library/Tracks/<作品 集数> [id8]/Reimport/``，之后用户的原文件可以随意处置；
- 结果：新的“外部回导”资产（不能借用来源测量；继承输入资产的角色）+ 一个新采样（整段；名称可改、性质默认未分类；父采样 = 发起回导的采样）。
时钟：起点是输入资产的局部秒；新资产的局部秒 0 = 起点。
"""

from __future__ import annotations

import os
import shutil
import sqlite3
from pathlib import Path
from typing import Any

from ..domain import filename as fname
from ..domain.mapping import Mapping
from ..media import probe as probe_mod
from ..store.db import transaction
from ..store.workspace import Workspace
from . import assets as assets_mod
from . import effective_tags, libdirs
from .clock import new_id, now_iso
from .edits import ChangeSet, dumps
from .errors import CoreError


def _file_audio(path: str) -> tuple[float, int, probe_mod.Probe]:
    pr = probe_mod.probe(path)
    a = pr.audio
    if not a:
        raise CoreError("reimport-invalid", reason="no-audio", path=path)
    dur = a[0].duration or pr.format_duration
    if not dur or dur <= 0:
        raise CoreError("reimport-invalid", reason="no-duration", path=path)
    return float(dur), int(a[0].sample_rate or 0), pr


class ReimportService:
    def __init__(self, conn: sqlite3.Connection, ws: Workspace, samples: Any, on_change: Any = None) -> None:
        self.conn = conn
        self.ws = ws
        self.samples = samples
        self.on_change = on_change

    def preview(self, asset_id: str, start: float, path: str) -> dict[str, Any]:
        """弹窗预览：“文件时长 D 秒 · 回导终点 E 秒”；越界时给出原因（不抛错，界面就地显示）。"""
        asset = assets_mod.get(self.conn, asset_id)
        dur, rate, _pr = _file_audio(path)
        mapping = Mapping.of(asset["mapping"])
        end = start + dur
        ok, reason = True, None
        try:
            mapping.reimport(start, dur, frame=1.0 / assets_mod.rate_of(self.conn, asset))
        except CoreError:
            ok, reason = False, "out-of-bounds"
        src_end = None
        if ok:
            src_end = mapping.to_source(min(end, mapping.duration))
        return {"duration": dur, "sampleRate": rate, "start": start, "end": end, "ok": ok, "reason": reason,
                "sourceStart": mapping.to_source(start), "sourceEnd": src_end, "assetDuration": float(asset["duration"])}

    def commit(self, asset_id: str, start: float, path: str, *, name: str | None = None, nature: str = "unclassified",
               parent_sample_id: str | None = None) -> dict[str, Any]:
        asset = assets_mod.get(self.conn, asset_id)
        dur, rate, pr = _file_audio(path)
        mapping = Mapping.of(asset["mapping"])
        try:
            new_map = mapping.reimport(start, dur, frame=1.0 / assets_mod.rate_of(self.conn, asset))
        except CoreError:
            raise CoreError("reimport-out-of-bounds", start=start, end=start + dur, duration=float(asset["duration"])) from None
        src = Path(path)
        aid, mid, ts = new_id(), new_id(), now_iso()
        target_dir = libdirs.track_dir(self.ws, self.conn, asset["source_id"], "Reimport")
        stem = fname.truncate_utf8(fname.portable(src.stem), 120).strip(" .") or "reimport"
        target = target_dir / f"{stem}__{aid[:12]}{src.suffix.lower()}"
        # 原样复制（保持格式、无损）：先复制到同目录的隐藏临时名再改名，用户可见目录里不留半成品
        tmp = target_dir / f".{target.name}.{new_id()[:8]}.tmp"
        shutil.copyfile(src, tmp)
        os.replace(tmp, target)
        try:
            pr2 = probe_mod.probe(target)
            rel = target.relative_to(self.ws.root).as_posix()
            with transaction(self.conn):
                self.conn.execute(
                    "INSERT INTO media_file(id, path, location, file_snapshot, format, sample_rate, created_at) VALUES (?, ?, 'library', ?, ?, ?, ?)",
                    (mid, rel, dumps(probe_mod.snapshot(target, pr2)), pr.format_name, rate or None, ts),
                )
                production = {"op": "reimport", "file": src.name, "inputStart": start, "fileDuration": dur, "sampleRate": rate}
                self.conn.execute(
                    "INSERT INTO sound_asset(id, source_id, origin, media_file_id, duration, mapping, input_asset_id, input_start, input_end,"
                    " production, language, created_at) VALUES (?, ?, 'reimport', ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (aid, asset["source_id"], mid, dur, dumps(new_map.to_list()), asset_id, start, start + dur, dumps(production), asset["language"], ts),
                )
                self.conn.execute(
                    "INSERT INTO asset_storage(asset_id, range_start, range_end, media_file_id, kind) VALUES (?, 0, ?, ?, 'primary')", (aid, dur, mid)
                )
                # 继承输入资产的角色（04 §4.2.4）
                for role, state in self.conn.execute("SELECT role, state FROM asset_role WHERE asset_id = ?", (asset_id,)).fetchall():
                    self.conn.execute("INSERT INTO asset_role(asset_id, role, state) VALUES (?, ?, ?)", (aid, role, state))
                label = (name or "").strip() or self.samples.suggest(asset_id, start, min(start + dur, float(asset["duration"])))["name"]
                sid = self.samples.insert_checked(aid, 0.0, dur, name=label, nature=nature, created_via="reimport", parent_sample_id=parent_sample_id,
                                                  origin={"kind": "reimport", "inputAsset": asset_id, "inputStart": start, "file": src.name})
                effective_tags.refresh(self.conn, [sid])
        except Exception:
            target.unlink(missing_ok=True)
            raise
        if self.on_change:
            cs = ChangeSet()
            cs.add("asset", aid)
            cs.add("sample", sid)
            cs.add("source", asset["source_id"])
            self.on_change(cs)
        return self.samples.get(sid)
