"""卡拍导出与 REAPER 交接（规格 12 §12.1、§12.3、16 R21.4–R21.7）。

- 卡拍 WAV：只能导出**完整采样**（命中随阶段 7）；方案在需要时自动计算；文件名处理信息「卡拍-<BPM>BPM」（拉平成品为「拉平-<音名>_卡拍-<BPM>BPM」）；
  清单（``Data/Manifests/``）记录方案与组合后的映射（卡拍输出秒 → 原片秒，R21.4）。
- 拖出由按键决定（⌥ 原声、⌥⇧ 卡拍，不跟随最近一次试听）；单条卡拍用舞台上选的方案，批量用默认方案。
- REAPER（两种，所有者 2026-11-04 明确）：都用**未烘焙的原声** WAV，复制到 ``Library/REAPER/<日期>/``（``<名称>__<版本>__<内容哈希>.wav``；同名但内容不同 → 报错）。
  ``original`` = 不卡拍，每个音头一个 1 倍速标记，方便手动卡；``fitted`` = 拉伸标记把它卡好，听上去是卡拍后的，删掉标记就回到原声。
  吸附 = 首个起音（设置可改为条目开头）；批量依次排开、每条间隔一小节（所有者 2026-10-08）；
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
        self.hits: Any = None  # HitService（检索命中的交接，09 §9.7）

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
            # 刚试听过卡拍就直接用那次渲染（拖出时不用再等）
            _an, _s, _cells, pcm, sr = self.rhythm.stretched_pcm(sample_id, plan, mora, long_vowel)
            return pcm, sr

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

    def export_samples(self, ids: list[str], words: dict[str, str], versions: dict[str, str] | None = None,
                       plan: str = "near_fast", mora: bool = False, long_vowel: bool = False) -> list[str]:
        """拖出与交接：每个采样按给定版本（原声 / 卡拍），没给 = 原声。卡拍按给定方案。"""
        out = []
        for sid in dict.fromkeys(ids):
            if (versions or {}).get(sid) == "stretched":
                out.append(self.export_stretched(sid, words, plan, mora, long_vowel)["path"])
                continue
            out += export_samples(self.exports, [sid], words)
        return out

    # ------------------------------------------------------------ REAPER

    def _reaper_dir(self) -> Path:
        return self.ws.library / "REAPER" / datetime.now().strftime("%Y-%m-%d")

    def _reaper_file(self, row: sqlite3.Row, pcm: np.ndarray, sr: int, media: dict[str, Any] | None, version: str) -> Path:
        """交接用的 WAV（PCM 24-bit）→ REAPER 目录 ``<名称>__<版本>__<内容哈希>.wav``；同名同内容复用，同名不同内容报错。"""
        self.ws.staging.mkdir(parents=True, exist_ok=True)
        staged = self.ws.staging / f"{new_id()}.wav"
        try:
            wavfile.save_wav24(staged, pcm, sr)
            if media is not None:
                assets_mod.check_media(media)
            h = hashlib.sha256(staged.read_bytes()).hexdigest()
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
        return target

    def _items(self, ids: list[str], words: dict[str, str], plan: str, mora: bool, long_vowel: bool, kind: str) -> tuple[list[reaper.Item], list[dict[str, Any]]]:
        """``original``：原声 + 音头处的 1 倍速标记；``fitted``：同一份原声 + 卡拍拉伸标记（每个起音都有，保护核心的锚点）。"""
        snap_mode = settings_mod.values(self.conn)["export.reaper_snap"]
        items, meta = [], []
        for sid in dict.fromkeys(ids):
            row = self._sample(sid)
            asset = assets_mod.get(self.conn, row["asset_id"])
            label = "_".join(x for x in (track_label(asset, words), processing_label(asset, words)) if x)
            an, s, cells = self._scheme(sid, plan, mora, long_vowel)
            pcm, sr, media = self.rhythm._audio(row["asset_id"], float(row["start"]), float(row["end"]))
            path = self._reaper_file(row, pcm, sr, media, label)
            m = s.map
            onsets = [(f, int(round((c.src - an.window[0]) * sr))) for c, f in zip(m.cps, m.onsets) if c.kind == "onset"]
            if kind == "original":
                markers = reaper.onset_markers([src for _f, src in onsets], len(pcm), sr)
                length = len(pcm) / sr
                first_onset = min(src for _f, src in onsets) / sr
            else:
                tp = dict((t, src) for src, t in m.knots)
                tp.update(onsets)
                markers = [(t / sr, tp[t] / sr) for t in sorted(tp)]
                length = m.out_frames / sr
                first_onset = onsets[0][0] / sr
            beat = 60.0 / s.bpm
            items.append(reaper.Item(0.0, first_onset if snap_mode == "onset" else 0.0, length, beat, row["name"], markers, str(path)))
            meta.append({"sample": sid, "file": str(path), "kind": kind, "plan": plan, "density": s.density, "bpm": s.bpm, "speed": s.speed, "cells": cells,
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

    def _kind(self, kind: str | None) -> str:
        return kind or settings_mod.values(self.conn)["export.reaper_kind"]

    def reaper_handoff(self, ids: list[str], words: dict[str, str], plan: str = "near_fast", mora: bool = False, long_vowel: bool = False, kind: str | None = None,
                       hits: list[dict[str, Any]] | None = None) -> dict[str, Any]:
        """返回剪贴板文本（由主进程写入 ``REAPERMedia`` 并回读校验）。``kind=None`` = 按设置「导出 → ⌘C 复制哪种」。``hits``：检索命中（各用证据方案）。"""
        if not ids and not hits:
            raise CoreError("reaper-empty")
        kind = self._kind(kind)
        items, meta = self.hits.reaper_items(hits, words, kind) if hits else self._items(ids, words, plan, mora, long_vowel, kind)
        text = reaper.clipboard(items)
        manifest = self._write_manifest(meta, "clipboard")
        return {"clipboard": text, "files": [m["file"] for m in meta], "manifest": str(manifest), "count": len(items)}

    def reaper_template(self, ids: list[str], words: dict[str, str], plan: str = "near_fast", mora: bool = False, long_vowel: bool = False, kind: str | None = None,
                        hits: list[dict[str, Any]] | None = None) -> dict[str, Any]:
        """``.RTrackTemplate``：同内容的 ITEM，换行分隔；直接拖进 REAPER 就是带拉伸标记的条目。``kind=None`` = 按设置「导出 → ⌘C 复制哪种」。"""
        if not ids and not hits:
            raise CoreError("reaper-empty")
        kind = self._kind(kind)
        items, meta = self.hits.reaper_items(hits, words, kind) if hits else self._items(ids, words, plan, mora, long_vowel, kind)
        d = self._reaper_dir()
        base = fname.truncate_utf8(fname.portable(items[0].name), 100).strip(" .") or "item"
        p = d / f"{base}__{new_id()[:8]}.RTrackTemplate"
        p.write_text(reaper.template(items), encoding="utf-8")
        manifest = self._write_manifest(meta, "rtracktemplate")
        return {"path": str(p), "files": [m["file"] for m in meta], "manifest": str(manifest), "count": len(items)}
