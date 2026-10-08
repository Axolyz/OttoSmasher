"""节奏与卡拍（规格 09 §9.2–§9.5、03 §3.3「节奏与卡拍」）：Core 侧——逐采样参数、节奏分析视图、方案按需计算、试听渲染、全局 BPM。

- 分析 = 采样**绑定**的声音上的当前语音测量（自己的，或覆盖它的同一物理声音测量的投影，08 §8.8）+ 采样范围内的音频能量（停顿）+ F0（逐音属性）；
  不跑模型。结果按“采样 + 范围 + 分析版本 + 参数 + 惩罚度 + 文件快照 + 算法版本”在内存里缓存，任一项变了就重算（方案身份，09 §9.5.3）。
- 量化只有「原节奏 · 无 mora」（加人工占格）；纯 mora 只作舞台上的临时试听与临时导出（所有者 2026-10-08，``mora=True`` 时临时使用，不保存）。
- 方案在需要时自动计算（不要求先打开节奏面板）：近快 / 近慢 / 倍快；全局 BPM 为空 = 原速卡拍。
- 试听渲染是普通命令（几秒的采样即时完成），结果放可清理缓存 ``Data/Cache/rhythm/<键>.wav``，按键复用。
- 单音（调谐/非调谐）没有卡拍（所有者 2026-10-06）。
时钟：音素、音块、停顿、切口都是资产局部秒；映射的目标时间是卡拍输出的秒。
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import sqlite3
from collections import OrderedDict
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np

from ..algo import rhythm as rh
from ..algo import stretch as st
from ..media import decode as dec
from ..media import stretch as render_mod
from ..media import wavfile
from ..models import fcpe
from ..store.workspace import Workspace
from . import assets as assets_mod
from . import settings as settings_mod
from .clock import new_id, now_iso
from .edits import loads
from .errors import CoreError

PLANS = ("near_fast", "near_slow", "double")
SOUNDS = ("voice", "voice+click", "click")
VERSIONS = ("original", "stretched")
SINGLE_SOUNDS = ("pitched", "unpitched")
CACHE_MAX = 64
_KEY_RE = re.compile(r"^[0-9a-f]{40}$")


def _sha(obj: Any) -> str:
    return hashlib.sha256(json.dumps(obj, sort_keys=True, ensure_ascii=False, separators=(",", ":"), default=str).encode("utf-8")).hexdigest()


@dataclass
class Analysis:
    sample_id: str
    name: str
    nature: str
    version: int
    asset_id: str
    window: tuple[float, float]
    sr: int
    channels: int
    identity: str
    run: str
    run_version: int
    projected_from: str | None
    params: dict[str, Any]
    manual_applied: bool
    manual_stale: bool
    ignored: list[str]
    phones: list[rh.Phone]
    morae: list[str]
    blocks: list[rh.Block]
    pauses: list[rh.Pause]
    seg: list[int]
    cuts: list[rh.Cut]
    segments: list[rh.Segment]
    dur: rh.Durations
    raw: rh.Quantized
    mora_cells: list[int | None]
    manual_cells: dict[int, int]
    attrs: list[dict[str, Any]]
    penalty: float


class RhythmService:
    def __init__(self, conn: sqlite3.Connection, ws: Workspace, speech: Any, edits: Any, emit: Callable[[str, Any], None] | None = None) -> None:
        self.conn = conn
        self.ws = ws
        self.speech = speech
        self.edits = edits
        self.emit = emit
        self._cache: OrderedDict[str, Analysis] = OrderedDict()
        self.render_dir = ws.data / "Cache" / "rhythm"

    # ------------------------------------------------------------ 全局 BPM（03 §3.1）

    def bpm(self) -> float | None:
        return settings_mod.values(self.conn)["rhythm.bpm"]

    def set_bpm(self, bpm: float | None) -> dict[str, Any]:
        """工作参数，不进撤销；所有窗口同步（事件 rhythm.bpm）、重启保留。"""
        value = st.check_bpm(None if bpm is None else float(bpm))
        self.conn.execute(
            "INSERT INTO setting(key, value, version, updated_at) VALUES ('rhythm.bpm', ?, 1, ?)"
            " ON CONFLICT(key) DO UPDATE SET value=excluded.value, version=version+1, updated_at=excluded.updated_at",
            (json.dumps(value), now_iso()),
        )
        if self.emit:
            self.emit("rhythm.bpm", {"bpm": value})
        return {"bpm": value}

    # ------------------------------------------------------------ 分析

    _COLS = 'id, asset_id, start, "end", name, nature, version, rhythm'

    def _row(self, sample_id: str) -> sqlite3.Row:
        r = self.conn.execute(f"SELECT {self._COLS} FROM sample WHERE id=?", (sample_id,)).fetchone()
        if r is None:
            raise CoreError("sample-not-found", id=sample_id)
        return r

    @staticmethod
    def params_of(row: sqlite3.Row) -> dict[str, Any]:
        return rh.validate_params(loads(row["rhythm"]) if row["rhythm"] else {})

    def _penalty(self) -> float:
        return float(settings_mod.values(self.conn)["analysis.penalty"])

    def _audio(self, asset_id: str, start: float, end: float) -> tuple[np.ndarray, int, dict[str, Any]]:
        """采样范围的音频 [帧, 声道]（帧 0 = start）与文件快照；文件缺失或被改动 → 明确报错（不换别的轨）。"""
        asset = assets_mod.get(self.conn, asset_id)
        ref, win, media = assets_mod.locate(self.conn, self.ws.root, asset, start, end)
        assets_mod.check_media(media)
        sr = ref.sample_rate
        a, b = round(win.to_file(start) * sr), round(win.to_file(end) * sr)
        pcm = dec.decode_frames(ref, a, b, cache=self.ws.data / "Cache")
        return pcm, sr, media

    def _snapshot(self, asset_id: str, start: float, end: float) -> tuple[Any, int, int]:
        asset = assets_mod.get(self.conn, asset_id)
        ref, _win, media = assets_mod.locate(self.conn, self.ws.root, asset, start, end)
        assets_mod.check_media(media)
        return media["snapshot"], ref.sample_rate, ref.channels

    def analysis(self, sample_id: str) -> Analysis:
        row = self._row(sample_id)
        start, end = float(row["start"]), float(row["end"])
        view = self.speech.sample_view(sample_id)
        head = view["head"]
        if head is None or head["status"] != "ok" or not head.get("result"):
            raise CoreError("rhythm-no-analysis", id=sample_id)
        params = self.params_of(row)
        penalty = self._penalty()
        snap, sr, channels = self._snapshot(row["asset_id"], start, end)
        identity = _sha([
            sample_id, row["asset_id"], start, end, head["runId"], head["version"], head.get("projectedFrom"), params, penalty, snap,
            rh.ALGO_VERSION, st.ALGO_VERSION,
        ])
        hit = self._cache.get(identity)
        if hit is not None:
            self._cache.move_to_end(identity)
            hit.name, hit.version, hit.nature = row["name"], int(row["version"]), row["nature"]
            return hit
        res = head["result"]
        phones: list[rh.Phone] = []
        for p in res["phones"]:
            if p["end"] <= start or p["start"] >= end:
                continue
            phones.append(rh.Phone(p["label"], max(float(p["start"]), start), min(float(p["end"]), end), p.get("mora"), p.get("strength")))
        manual = params["manual"]
        has_manual = bool(manual["splits"] or manual["cells"] or manual["cuts"] or manual["merges"])
        applied = has_manual and manual["run"] == head["runId"]
        stale = has_manual and not applied
        ignored: list[str] = []
        blocks = rh.group_blocks(phones, [k for k in manual["splits"] if 0 < k < len(phones)] if applied else ())
        if applied:
            ignored += [f"split:{k}" for k in manual["splits"] if not 0 < k < len(phones)]
        if not blocks:
            raise CoreError("rhythm-no-blocks")
        window = (start, end)
        pcm, sr, _media = self._audio(row["asset_id"], start, end)
        mono = pcm.mean(axis=1) if pcm.ndim == 2 else pcm
        pauses = rh.detect_pauses(mono, sr, start, phones, params["sensitivity"])
        seg = rh.pause_segments(blocks, pauses)
        n = len(blocks)
        m_cuts = [k for k in manual["cuts"] if 0 < k < n] if applied else []
        m_merges = [k for k in manual["merges"] if 0 < k < n] if applied else []
        m_cells = {int(k): v for k, v in manual["cells"].items() if int(k) < n} if applied else {}
        if applied:
            ignored += [f"cut:{k}" for k in manual["cuts"] if not 0 < k < n] + [f"merge:{k}" for k in manual["merges"] if not 0 < k < n]
            ignored += [f"cells:{k}" for k in manual["cells"] if int(k) >= n]
        cuts = rh.find_cuts(blocks, pauses, phones, params["segmentThreshold"], m_cuts, m_merges)
        segs = rh.segments(blocks, cuts, window)
        dur = rh.durations(blocks, pauses, window)
        raw = rh.quantize_raw(dur, seg, m_cells, penalty)
        mc = rh.mora_cells(phones, blocks, rh.mora_span(phones, window, strict=False))
        attrs = self._attributes(row["asset_id"], start, end, blocks, phones, seg)
        an = Analysis(
            sample_id=sample_id, name=row["name"], nature=row["nature"], version=int(row["version"]), asset_id=row["asset_id"], window=window,
            sr=sr, channels=pcm.shape[1] if pcm.ndim == 2 else 1, identity=identity, run=head["runId"], run_version=int(head["version"]),
            projected_from=head.get("projectedFrom"), params=params, manual_applied=applied, manual_stale=stale, ignored=ignored,
            phones=phones, morae=list(res.get("morae") or []), blocks=blocks, pauses=pauses, seg=seg, cuts=cuts, segments=segs, dur=dur, raw=raw,
            mora_cells=mc, manual_cells=m_cells, attrs=attrs, penalty=penalty,
        )
        self._cache[identity] = an
        while len(self._cache) > CACHE_MAX:
            self._cache.popitem(last=False)
        return an

    def _attributes(self, asset_id: str, start: float, end: float, blocks: list[rh.Block], phones: list[rh.Phone], seg: list[int]) -> list[dict[str, Any]]:
        try:
            i0, frames, have = self.speech.f0_frames(asset_id, start, end)
        except CoreError:
            frames, have, i0 = np.zeros((0, 3)), np.zeros(0, dtype=bool), 0
        times = ((i0 + np.arange(len(frames))) * fcpe.HOP + fcpe.HOP / 2) / fcpe.SR
        return rh.block_attributes(blocks, phones, seg, times, np.asarray(frames, dtype=np.float64), np.asarray(have, dtype=bool))

    # ------------------------------------------------------------ 方案

    def cells_for(self, an: Analysis, mora: bool = False, long_vowel: bool = False) -> list[int]:
        """量化结果：原节奏（加人工占格）；``mora=True`` = 临时用纯 mora（加人工占格，可选长音补格），缺 mora 报错。"""
        if not mora:
            assert an.raw.cells is not None
            return list(an.raw.cells)
        q = rh.quantize_mora(an.dur, an.blocks, an.phones, an.pauses, an.mora_cells, an.manual_cells, long_vowel)
        if q.cells is None:
            raise CoreError("rhythm-mora-unavailable", blocks=[i + 1 for i in q.missing])
        return q.cells

    def plan_of(self, an: Analysis, cells: list[int]) -> st.Plan:
        return st.Plan(an.blocks, an.dur, cells, an.pauses, [c for c in an.cuts if not c.merged], an.window, an.sr)

    def schemes(self, an: Analysis, cells: list[int], bpm: float | None) -> dict[str, st.Scheme]:
        return st.candidates(self.plan_of(an, cells), bpm)

    def _require_speech(self, an: Analysis) -> None:
        if an.nature in SINGLE_SOUNDS:
            raise CoreError("rhythm-not-for-single-sound", nature=an.nature)

    # ------------------------------------------------------------ 视图（舞台「节奏与卡拍」面板）

    def view(self, sample_id: str, mora: bool = False, long_vowel: bool = False) -> dict[str, Any]:
        row = self._row(sample_id)
        bpm = self.bpm()
        try:
            an = self.analysis(sample_id)
        except CoreError as e:
            if e.code in ("rhythm-no-analysis", "rhythm-no-blocks"):
                return {"sampleId": sample_id, "status": "none", "reason": e.to_wire(), "bpm": bpm, "version": int(row["version"])}
            raise
        out: dict[str, Any] = {
            "sampleId": sample_id, "status": "ok", "reason": None, "bpm": bpm, "version": an.version, "run": an.run,
            "projectedFrom": an.projected_from, "window": list(an.window),
            "params": {"sensitivity": an.params["sensitivity"], "segmentThreshold": an.params["segmentThreshold"]},
            "manual": {**an.params["manual"], "applied": an.manual_applied, "stale": an.manual_stale, "ignored": an.ignored},
            "penalty": an.penalty,
            "phones": [{"label": p.label, "start": p.start, "end": p.end} for p in an.phones],
            "pauses": [[p.start, p.end] for p in an.pauses],
            "cuts": [{"k": c.k, "kind": c.kind, "at": c.left_end, "rightStart": c.right_start, "merged": c.merged} for c in an.cuts],
            "segments": [[s.start, s.end] for s in an.segments],
            "tick": an.raw.tick, "alternatives": an.raw.alternatives,
            "mora": {"cells": an.mora_cells, "available": all(c is not None for c in an.mora_cells)},
        }
        try:
            cells = self.cells_for(an, mora, long_vowel)
            out["cells"] = cells
            out["route"] = "mora" if mora else "raw"
        except CoreError as e:
            out["cells"] = list(an.raw.cells or [])
            out["route"] = "raw"
            out["routeError"] = e.to_wire()
            cells = out["cells"]
        out["blocks"] = [
            {
                "onset": b.onset, "end": b.end, "vowel": b.vowel, "text": self._block_text(an, i), "strength": b.strength, "pauseSegment": an.seg[i],
                "cells": cells[i], "manual": i in an.manual_cells, "duration": an.dur.dur[i], "rest": an.dur.rest[i],
                "firstPhone": b.members[0], **an.attrs[i],
            }
            for i, b in enumerate(an.blocks)
        ]
        schemes: dict[str, Any] = {}
        try:
            for k, s in self.schemes(an, cells, bpm).items():
                schemes[k] = self._scheme_wire(an, s)
            out["schemeError"] = None
        except CoreError as e:
            out["schemeError"] = e.to_wire()
        out["schemes"] = schemes
        for i, b in enumerate(out["blocks"]):
            b["restCells"] = schemes["near_fast"]["restCells"][i] if schemes else None
        return out

    def _block_text(self, an: Analysis, i: int) -> str:
        """块的读音（显示用）：本块首 mora 到下一块首 mora 之前的假名；缺 mora 时用首元音。"""
        ms = [an.phones[k].mora for k in an.blocks[i].members if an.phones[k].mora is not None]
        if not ms or not an.morae:
            return an.blocks[i].vowel or "N"
        a = min(ms)
        nxt = None
        if i + 1 < len(an.blocks):
            n2 = [an.phones[k].mora for k in an.blocks[i + 1].members if an.phones[k].mora is not None]
            nxt = min(n2) if n2 else None
        b = nxt if nxt is not None and nxt > a else max(ms) + 1
        return "".join(an.morae[a:b])

    @staticmethod
    def _scheme_wire(an: Analysis, s: st.Scheme) -> dict[str, Any]:
        m = s.map
        return {
            "density": s.density, "bpm": s.bpm, "speed": s.speed, "ratio": s.ratio, "restCells": s.beats.rest_cells,
            "sourceSeconds": m.src_frames / m.sr, "outSeconds": m.out_frames / m.sr,
            "points": [{"src": round(c.src, 6), "tgt": round(f / m.sr, 6), "beat": c.beat, "kind": c.kind} for c, f in zip(m.cps, m.onsets)],
        }

    # ------------------------------------------------------------ 逐采样参数（经编辑通道，可撤销）

    def set_params(self, sample_id: str, version: int, patch: dict[str, Any]) -> dict[str, Any]:
        """改「分组与停顿」与人工占格。人工项绑定当前分析版本；人工项属于旧版本时先「重新套用」或「清除」，否则拒绝。
        拆点变了音块就变了：同时清掉人工占格与手动切分/合并（序号已经对不上）。"""
        row = self._row(sample_id)
        cur = self.params_of(row)
        new = json.loads(json.dumps(cur))
        man = new["manual"]
        head = self.speech.sample_view(sample_id)["head"]
        run = head["runId"] if head and head["status"] == "ok" else None
        for k in ("sensitivity", "segmentThreshold"):
            if k in patch and patch[k] is not None:
                new[k] = patch[k]
        if patch.get("clearManual"):
            new["manual"] = rh.empty_manual()
        elif patch.get("reapply"):
            if run is None:
                raise CoreError("rhythm-no-analysis", id=sample_id)
            man["run"] = run
        touches = [k for k in ("splits", "cells", "cuts", "merges", "moraToCells") if k in patch and patch[k] is not None]
        if touches:
            if run is None:
                raise CoreError("rhythm-no-analysis", id=sample_id)
            has_old = bool(man["splits"] or man["cells"] or man["cuts"] or man["merges"])
            if has_old and man["run"] != run:
                raise CoreError("rhythm-manual-stale")
            man["run"] = run
            if "splits" in patch and patch["splits"] is not None:
                if sorted(set(patch["splits"])) != man["splits"]:
                    man["cells"], man["cuts"], man["merges"] = {}, [], []
                man["splits"] = patch["splits"]
            if "cuts" in patch and patch["cuts"] is not None:
                man["cuts"] = patch["cuts"]
            if "merges" in patch and patch["merges"] is not None:
                man["merges"] = patch["merges"]
            if "cells" in patch and patch["cells"] is not None:
                cells = {str(k): v for k, v in patch["cells"].items() if v is not None}
                man["cells"] = cells
            if patch.get("moraToCells") is not None:
                an = self.analysis(sample_id)
                cells_list = self.cells_for(an, mora=True, long_vowel=bool(patch["moraToCells"].get("longVowel")))
                man["cells"] = {str(i): n for i, n in enumerate(cells_list)}
        validated = rh.validate_params(new)
        out = self.edits.apply({
            "label": {"code": "rhythm-params", "args": {"name": row["name"]}},
            "ops": [{"entity": "sample", "id": sample_id, "version": version, "fields": {"rhythm": validated}}],
        })
        return {"editId": out["edit_id"]}

    # ------------------------------------------------------------ 试听渲染

    def render(self, sample_id: str, version: str, sound: str, plan: str = "near_fast", mora: bool = False, long_vowel: bool = False) -> dict[str, Any]:
        if version not in VERSIONS:
            raise CoreError("rhythm-param-invalid", field="version", min=None, max=None)
        if sound not in SOUNDS:
            raise CoreError("rhythm-param-invalid", field="sound", min=None, max=None)
        if plan not in PLANS:
            raise CoreError("rhythm-param-invalid", field="plan", min=None, max=None)
        an = self.analysis(sample_id)
        self._require_speech(an)
        bpm = self.bpm()
        cells = self.cells_for(an, mora, long_vowel)
        s = self.schemes(an, cells, bpm)[plan] if version == "stretched" else None
        key, path = self._ensure_render(an, version, sound, cells, s)
        frames = wavfile.info(path)[3]
        return {
            "key": key, "duration": frames / an.sr, "version": version, "sound": sound, "plan": plan if s else None,
            "bpm": s.bpm if s else None, "density": s.density if s else None, "speed": s.speed if s else None, "originalSpeed": bpm is None,
        }

    def _ensure_render(self, an: Analysis, version: str, sound: str, cells: list[int], s: st.Scheme | None) -> tuple[str, Path]:
        """渲染（或复用缓存里已有的）试听文件：键 = 分析身份 + 版本 + 声音 + 占格 + 方案 + 渲染与 Rubber Band 版本。"""
        key = hashlib.sha1(_sha([
            an.identity, version, sound, cells, None if s is None else [s.density, s.bpm], render_mod.RENDER_VERSION, render_mod.rubberband_version() if s else None,
        ]).encode()).hexdigest()
        path = self.render_dir / f"{key}.wav"
        if not path.is_file():
            pcm, sr, media = self._audio(an.asset_id, *an.window)
            if s is not None:
                out = render_mod.render(pcm, s.map)
                onsets = [f for c, f in zip(s.map.cps, s.map.onsets) if c.kind == "onset"]
            else:
                out = pcm.astype(np.float32)
                onsets = [int(round((b.onset - an.window[0]) * sr)) for b in an.blocks]
            if sound != "voice":
                out = render_mod.mix_clicks(out, onsets, sr, voice=sound == "voice+click")
            assets_mod.check_media(media)  # 渲染期间源文件变了 → 报错
            self.render_dir.mkdir(parents=True, exist_ok=True)
            tmp = self.render_dir / f".{key}.{new_id()[:8]}.tmp"
            try:
                wavfile.save_wav24(tmp, out, sr)
                os.replace(tmp, path)
            finally:
                tmp.unlink(missing_ok=True)
        return key, path

    def stretched_pcm(self, sample_id: str, plan: str = "near_fast", mora: bool = False, long_vowel: bool = False) -> tuple[Analysis, st.Scheme, list[int], np.ndarray, int]:
        """卡拍后的声音（导出、拖出、REAPER 卡好拍版共用）：刚试听过就直接用试听渲染的结果，不再渲染一次；逐样本与渲染一致。"""
        an = self.analysis(sample_id)
        self._require_speech(an)
        cells = self.cells_for(an, mora, long_vowel)
        s = self.schemes(an, cells, self.bpm())[plan]
        _key, path = self._ensure_render(an, "stretched", "voice", cells, s)
        pcm, sr = wavfile.load_wav24(path)
        return an, s, cells, pcm, sr

    def resolve_render(self, key: str) -> dict[str, Any]:
        """试听播放器：渲染结果的位置（只接受本服务生成的键，不接受路径）。"""
        if not _KEY_RE.match(key or ""):
            raise CoreError("rhythm-render-missing", key=str(key)[:64])
        path = self.render_dir / f"{key}.wav"
        if not path.is_file():
            raise CoreError("rhythm-render-missing", key=key)
        rate, _ch, _bits, frames = wavfile.info(path)
        return {"path": str(path), "aid": 1, "fileStart": 0.0, "fileEnd": frames / rate, "localStart": 0.0, "localEnd": frames / rate}

