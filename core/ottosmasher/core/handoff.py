"""卡拍导出与 REAPER 交接（规格 12 §12.1、§12.3、16 R21.4–R21.7）。

- 卡拍 WAV：只能导出**完整采样**（命中随阶段 7）；方案在需要时自动计算；文件名处理信息「卡拍-<BPM>BPM」（拉平成品为「拉平-<音名>_卡拍-<BPM>BPM」）；
  清单（``Data/Manifests/``）记录方案与组合后的映射（卡拍输出秒 → 原片秒，R21.4）。
- 拖出跟随最近一次成功试听的版本（列表/舞台：原声或卡拍；界面在本次运行内记住，规格 12 §12.1、D4）。
- REAPER：**未烘焙的原声** WAV 复制到 ``Library/REAPER/<日期>/``（``<名称>__<版本>__<内容哈希>.wav``；同名但内容不同 → 报错）
  + 卡拍拉伸标记；吸附 = 首个起音（设置可改为条目开头）；批量依次排开、每条间隔一小节（所有者 2026-10-08）；
  每次交接写一份交接清单（方案、版本、吸附方式）放在 REAPER 目录。剪贴板由主进程写入并回读校验（Windows 未实测 → 未验收）。
「版本」段（规格只写了占位）：开发者决定 = 音轨词（原混音 / 人声 / …）加拉平信息，说明这份原声是哪个声音。
"""

from __future__ import annotations

import hashlib
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Any

import numpy as np

from ..domain import filename as fname
from ..domain import reaper
from ..domain.mapping import Mapping
from ..media import stretch as render_mod
from ..media import wavfile
from ..store.workspace import Workspace
from . import assets as assets_mod
from . import settings as settings_mod
from .clock import new_id, now_iso
from .edits import dumps
from .errors import CoreError
from .exports import ExportService, export_samples, processing_label, track_label


def bpm_text(bpm: float) -> str:
    """文件名里的 BPM：整数就写整数，否则最多两位小数（原速卡拍时是求出的 BPM）。"""
    r = round(bpm, 2)
    return str(int(r)) if abs(r - round(r)) < 1e-9 else f"{r:.2f}".rstrip("0").rstrip(".")


class HandoffService:
    def __init__(self, conn: sqlite3.Connection, ws: Workspace, exports: ExportService, rhythm: Any) -> None:
        self.conn = conn
        self.ws = ws
        self.exports = exports
        self.rhythm = rhythm

    def _sample(self, sample_id: str) -> sqlite3.Row:
        r = self.conn.execute('SELECT id, asset_id, start, "end", name FROM sample WHERE id=?', (sample_id,)).fetchone()
        if r is None:
            raise CoreError("sample-not-found", id=sample_id)
        return r

    def _scheme(self, sample_id: str, plan: str, mora: bool, long_vowel: bool) -> tuple[Any, Any, list[int]]:
        an = self.rhythm.analysis(sample_id)
        self.rhythm._require_speech(an)
        cells = self.rhythm.cells_for(an, mora, long_vowel)
        return an, self.rhythm.schemes(an, cells, self.rhythm.bpm())[plan], cells

    # ------------------------------------------------------------ 卡拍 WAV

    def export_stretched(self, sample_id: str, words: dict[str, str], plan: str = "near_fast", mora: bool = False, long_vowel: bool = False) -> dict[str, Any]:
        row = self._sample(sample_id)
        an, s, cells = self._scheme(sample_id, plan, mora, long_vowel)
        asset = assets_mod.get(self.conn, row["asset_id"])
        stretch = f"{words.get('stretch', 'stretch')}-{bpm_text(s.bpm)}BPM"
        processing = "_".join(x for x in (processing_label(asset, words), stretch) if x)
        m = s.map

        def make(ref: Any, a: int, b: int) -> tuple[np.ndarray, int]:
            pcm, sr, _media = self.rhythm._audio(row["asset_id"], float(row["start"]), float(row["end"]))
            return render_mod.render(pcm, m), sr

        def manifest(path: str, key: str) -> dict[str, Any]:
            inner = Mapping.of([[0.0, float(row["start"])]] + [[t / m.sr, float(row["start"]) + src / m.sr] for src, t in m.knots[1:]])
            composed = Mapping.of(asset["mapping"]).compose(inner)
            return {
                "kind": "stretched-wav", "file": path, "key": key, "sample": sample_id, "asset": row["asset_id"], "range": [row["start"], row["end"]],
                "scheme": {"plan": plan, "density": s.density, "bpm": s.bpm, "speed": s.speed, "cells": cells, "route": "mora" if mora else "raw",
                           "originalSpeed": self.rhythm.bpm() is None},
                "analysis": {"run": an.run, "identity": an.identity},
                "mapping": composed.to_list(),  # 卡拍输出秒 → 原片秒
                "createdAt": now_iso(),
            }

        return self.exports.export_generated(
            row["asset_id"], float(row["start"]), float(row["end"]),
            version=["stretched", an.identity, plan, s.density, s.bpm, cells, render_mod.RENDER_VERSION],
            make=make, content=row["name"], track=track_label(asset, words), processing=processing, manifest=manifest,
        )

    def export_samples(self, ids: list[str], words: dict[str, str], versions: dict[str, str] | None = None) -> list[str]:
        """拖出与交接：每个采样按给定版本（原声 / 卡拍），没给 = 原声。"""
        out = []
        for sid in dict.fromkeys(ids):
            if (versions or {}).get(sid) == "stretched":
                out.append(self.export_stretched(sid, words)["path"])
                continue
            out += export_samples(self.exports, [sid], words)
        return out

    # ------------------------------------------------------------ REAPER

    def _reaper_dir(self) -> Path:
        return self.ws.library / "REAPER" / datetime.now().strftime("%Y-%m-%d")

    def _original_copy(self, row: sqlite3.Row, asset: dict[str, Any], words: dict[str, str]) -> tuple[Path, int]:
        """未烘焙的原声 WAV（PCM 24-bit）→ REAPER 目录；同名同内容复用，同名不同内容报错。"""
        pcm, sr, media = self.rhythm._audio(row["asset_id"], float(row["start"]), float(row["end"]))
        self.ws.staging.mkdir(parents=True, exist_ok=True)
        staged = self.ws.staging / f"{new_id()}.wav"
        try:
            wavfile.save_wav24(staged, pcm, sr)
            assets_mod.check_media(media)
            h = hashlib.sha256(staged.read_bytes()).hexdigest()
            version = "_".join(x for x in (track_label(asset, words), processing_label(asset, words)) if x)
            name = f"{fname.truncate_utf8(fname.portable(row['name']), 120).strip(' .')}__{fname.portable(version)}__{h[:12]}.wav"
            d = self._reaper_dir()
            d.mkdir(parents=True, exist_ok=True)
            target = d / name
            if target.exists():
                if hashlib.sha256(target.read_bytes()).hexdigest() != h:
                    raise CoreError("reaper-file-conflict", path=str(target))
            else:
                self.exports._publish(staged, target)
        finally:
            staged.unlink(missing_ok=True)
        return target, sr

    def _items(self, ids: list[str], words: dict[str, str], plan: str, mora: bool, long_vowel: bool) -> tuple[list[reaper.Item], list[dict[str, Any]]]:
        snap_mode = settings_mod.values(self.conn)["export.reaper_snap"]
        items, meta = [], []
        for sid in dict.fromkeys(ids):
            row = self._sample(sid)
            an, s, cells = self._scheme(sid, plan, mora, long_vowel)
            asset = assets_mod.get(self.conn, row["asset_id"])
            path, sr = self._original_copy(row, asset, words)
            m = s.map
            pts = dict((t, src) for src, t in m.knots)
            for c, f in zip(m.cps, m.onsets):
                if c.kind == "onset":
                    pts[f] = int(round((c.src - an.window[0]) * sr))  # 每个起音都有标记（保护核心的锚点）
            markers = [(t / sr, pts[t] / sr) for t in sorted(pts)]
            first_onset = next(f for c, f in zip(m.cps, m.onsets) if c.kind == "onset") / sr
            beat = 60.0 / s.bpm
            items.append(reaper.Item(0.0, first_onset if snap_mode == "onset" else 0.0, m.out_frames / sr, beat, row["name"], markers, str(path)))
            meta.append({"sample": sid, "file": str(path), "plan": plan, "density": s.density, "bpm": s.bpm, "speed": s.speed, "cells": cells,
                         "route": "mora" if mora else "raw", "analysis": an.run, "markers": len(markers)})
        pos = reaper.lay_out([it.length for it in items], [it.beat for it in items])
        items = [reaper.Item(p, it.snap, it.length, it.beat, it.name, it.markers, it.path) for p, it in zip(pos, items)]
        return items, meta

    def _write_manifest(self, meta: list[dict[str, Any]], kind: str) -> Path:
        d = self._reaper_dir()
        d.mkdir(parents=True, exist_ok=True)
        p = d / f"handoff-{datetime.now().strftime('%H%M%S')}-{new_id()[:6]}.json"
        p.write_text(dumps({"kind": kind, "snap": settings_mod.values(self.conn)["export.reaper_snap"], "items": meta, "createdAt": now_iso()}), encoding="utf-8")
        return p

    def reaper_handoff(self, ids: list[str], words: dict[str, str], plan: str = "near_fast", mora: bool = False, long_vowel: bool = False) -> dict[str, Any]:
        """返回剪贴板文本（由主进程写入 ``REAPERMedia`` 并回读校验）。"""
        if not ids:
            raise CoreError("reaper-empty")
        items, meta = self._items(ids, words, plan, mora, long_vowel)
        text = reaper.clipboard(items)
        manifest = self._write_manifest(meta, "clipboard")
        return {"clipboard": text, "files": [m["file"] for m in meta], "manifest": str(manifest), "count": len(items)}

    def reaper_template(self, ids: list[str], words: dict[str, str], plan: str = "near_fast", mora: bool = False, long_vowel: bool = False) -> dict[str, Any]:
        """``.RTrackTemplate``（试验入口）：同内容的 ITEM，换行分隔。"""
        if not ids:
            raise CoreError("reaper-empty")
        items, meta = self._items(ids, words, plan, mora, long_vowel)
        d = self._reaper_dir()
        base = fname.truncate_utf8(fname.portable(items[0].name), 100).strip(" .") or "item"
        p = d / f"{base}__{new_id()[:8]}.RTrackTemplate"
        p.write_text(reaper.template(items), encoding="utf-8")
        manifest = self._write_manifest(meta, "rtracktemplate")
        return {"path": str(p), "files": [m["file"] for m in meta], "manifest": str(manifest), "count": len(items)}
