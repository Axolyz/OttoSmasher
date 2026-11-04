"""命中上的操作（规格 09 §9.7、10 §10.2.6、03 §3.4.4；ROADMAP L22、L25）。

- 命中用（固定结果, 行, 第几处）指认；执行任何动作前先核对仍有效（采样未删、绑定未变、分析/测量没变），失效报 ``hit-stale``（“命中已失效，请重新查询”）。
- 卡拍用**该命中证据所选的方案**（K3）：范围（整句 / 语段）、近快或近慢、检索时的 BPM（无 BPM = 原速卡拍）、段间休止调整后的格数；
  不限节奏的命中没有证据 → 整句近快、当前全局 BPM（与列表行默认卡拍相同）。
- 渲染：把整个范围（整句或语段窗口）按方案渲染，再按映射裁出命中段（09 §9.5.3、R13.7“裁掉空画布但保留所选音频与核心”）；结果放试听缓存。
- 音高命中没有卡拍（10 §10.2.6）。
时钟：命中起止、范围窗口 = 资产局部秒；渲染输出 = 卡拍输出的帧（命中段的第一帧 = 0）。
"""

from __future__ import annotations

import hashlib
import json
import os
import sqlite3
from pathlib import Path
from typing import Any

import numpy as np

from ..algo import rhythm as rh
from ..algo import speech_search as ss
from ..algo import stretch as st
from ..domain import reaper
from ..domain.mapping import Mapping
from ..media import stretch as render_mod
from ..media import wavfile
from . import assets as assets_mod
from . import settings as settings_mod
from .clock import new_id, now_iso
from .errors import CoreError
from .exports import processing_label, track_label
from .handoff import bpm_text

SOUNDS = ("voice", "voice+click", "click")


class HitService:
    def __init__(self, conn: sqlite3.Connection, search: Any, rhythm: Any, handoff: Any, exports: Any) -> None:
        self.conn = conn
        self.search = search
        self.rhythm = rhythm
        self.handoff = handoff
        self.exports = exports

    # ------------------------------------------------------------ 指认与核对

    def resolve(self, result_id: str, rank: int, index: int) -> dict[str, Any]:
        page = self.search.page(result_id, int(rank), 1)
        rows = page["rows"]
        if not rows or rows[0]["rank"] != rank or not 0 <= index < len(rows[0]["hits"]):
            raise CoreError("hit-not-found", result=result_id, rank=rank, index=index)
        row = rows[0]
        if row["state"] != "ok":
            raise CoreError("hit-stale", state=row["state"])
        h = row["hits"][index]
        sample = row["sample"]
        return {
            "kind": page["result"]["kind"], "sampleId": row["sampleId"], "assetId": sample["asset_id"] if sample else row["assetId"],
            "name": sample["name"] if sample else None, "start": h["start"], "end": h["end"], "hit": h, "stretch": page["result"]["kind"] == "speech",
            "sourceStart": h.get("sourceStart"), "sourceEnd": h.get("sourceEnd"),
        }

    def wire(self, result_id: str, rank: int, index: int) -> dict[str, Any]:
        r = self.resolve(result_id, rank, index)
        ev = r["hit"].get("evidence")
        return {
            "kind": r["kind"], "sampleId": r["sampleId"], "assetId": r["assetId"], "start": r["start"], "end": r["end"], "stretch": r["stretch"],
            "plan": (ev or {}).get("plan") or ("near_fast" if r["stretch"] else None), "bpm": (ev or {}).get("bpm"),
            "sourceStart": r["sourceStart"], "sourceEnd": r["sourceEnd"],
        }

    # ------------------------------------------------------------ 方案

    def _scheme(self, r: dict[str, Any]) -> tuple[Any, st.Plan, st.Scheme, str]:
        if not r["stretch"]:
            raise CoreError("hit-no-stretch")
        an = self.rhythm.analysis(r["sampleId"])
        self.rhythm._require_speech(an)
        h = r["hit"]
        ev = h.get("evidence")
        scope = ev["scope"] if ev else -1
        name = (ev or {}).get("plan") or "near_fast"
        bpm = ev["bpm"] if ev else self.rhythm.bpm()
        cells = list(an.raw.cells or [])
        if scope < 0:
            plan = self.rhythm.plan_of(an, cells)
        else:
            sg = next((x for x in an.segments if x.index == scope), None)
            plan = None if sg is None else ss.segment_plan(an.blocks, an.pauses, an.seg, sg, an.manual_cells, an.penalty, an.sr)
            if plan is None:
                raise CoreError("hit-stale", state="segment")
        cand = st.candidates(plan, bpm, (name,))[name]
        rests = None
        if ev and ev.get("changed") and ev.get("rests"):
            seg_of = {k: sg.index for sg in an.segments for k in range(sg.first, sg.stop)}
            first, count = int(h["first"]), int(h["count"])
            joints = [j for j in range(first + 1, first + count) if seg_of.get(j) != seg_of.get(j - 1)]
            rests = {j - 1: int(v) for j, v in zip(joints, ev["rests"])}
            cand = st.scheme(plan, cand.density, cand.bpm, rests)
        return an, plan, cand, name

    def _slice(self, an: Any, plan: st.Plan, s: st.Scheme, start: float, end: float) -> tuple[int, int]:
        m = s.map
        w0 = plan.window[0]
        a = int(round(m.to_target((max(start, w0) - w0) * m.sr)))
        b = int(round(m.to_target((min(end, plan.window[1]) - w0) * m.sr)))
        return max(0, a), min(m.out_frames, max(a + 1, b))

    def _stretched(self, r: dict[str, Any]) -> tuple[Any, st.Plan, st.Scheme, str, np.ndarray, int, tuple[int, int]]:
        an, plan, s, name = self._scheme(r)
        pcm, sr, media = self.rhythm._audio(an.asset_id, *plan.window)
        out = render_mod.render(pcm, s.map)
        assets_mod.check_media(media)
        a, b = self._slice(an, plan, s, r["start"], r["end"])
        return an, plan, s, name, out[a:b], sr, (a, b)

    # ------------------------------------------------------------ 试听

    def render(self, result_id: str, rank: int, index: int, version: str, sound: str) -> dict[str, Any]:
        if version not in ("original", "stretched") or sound not in SOUNDS:
            raise CoreError("rhythm-param-invalid", field="version" if version not in ("original", "stretched") else "sound", min=None, max=None)
        r = self.resolve(result_id, rank, index)
        if version == "stretched":
            an, plan, s, name = self._scheme(r)
            key = hashlib.sha1(json.dumps([an.identity, plan.window, plan.cells, s.density, s.bpm, sorted(s.beats.rest_cells), r["start"], r["end"], sound,
                                           render_mod.RENDER_VERSION, render_mod.rubberband_version()], default=str).encode()).hexdigest()
        else:
            an = self.rhythm.analysis(r["sampleId"]) if r["sampleId"] and r["stretch"] else None
            key = hashlib.sha1(json.dumps(["hit-original", r["assetId"], r["start"], r["end"], sound, an.identity if an else None]).encode()).hexdigest()
        path = self.rhythm.render_dir / f"{key}.wav"
        sr = None
        if not path.is_file():
            if version == "stretched":
                an, plan, s, name, out, sr, (a, b) = self._stretched(r)
                onsets = [f - a for c, f in zip(s.map.cps, s.map.onsets) if c.kind == "onset" and a <= f < b]
            else:
                pcm, sr, _media = self.rhythm._audio(r["assetId"], r["start"], r["end"])
                out = pcm.astype(np.float32)
                onsets = []
                if an is not None:
                    onsets = [int(round((bl.onset - r["start"]) * sr)) for bl in an.blocks if r["start"] <= bl.onset < r["end"]]
            if sound != "voice":
                out = render_mod.mix_clicks(out, onsets, sr, voice=sound == "voice+click")
            self.rhythm.render_dir.mkdir(parents=True, exist_ok=True)
            tmp = self.rhythm.render_dir / f".{key}.{new_id()[:8]}.tmp"
            try:
                wavfile.save_wav24(tmp, out, sr)
                os.replace(tmp, path)
            finally:
                tmp.unlink(missing_ok=True)
        rate, _ch, _bits, frames = wavfile.info(path)
        ev = r["hit"].get("evidence") or {}
        return {"key": key, "duration": frames / rate, "version": version, "sound": sound, "plan": ev.get("plan") if version == "stretched" else None,
                "bpm": ev.get("bpm") if version == "stretched" else None, "density": ev.get("density") if version == "stretched" else None,
                "speed": ev.get("speed") if version == "stretched" else None, "originalSpeed": version == "stretched" and ev.get("bpm") is None}

    # ------------------------------------------------------------ 导出

    def export(self, result_id: str, rank: int, index: int, version: str, words: dict[str, str]) -> dict[str, Any]:
        r = self.resolve(result_id, rank, index)
        asset = assets_mod.get(self.conn, r["assetId"])
        content = (r["name"] or "") + words.get("fragment", "")
        if version == "original":
            return self.exports.export_wav(r["assetId"], r["start"], r["end"], content=content, track=track_label(asset, words), processing=processing_label(asset, words))
        if version != "stretched":
            raise CoreError("rhythm-param-invalid", field="version", min=None, max=None)
        an, plan, s, name = self._scheme(r)
        stretch = f"{words.get('stretch', 'stretch')}-{bpm_text(s.bpm)}BPM"
        processing = "_".join(x for x in (processing_label(asset, words), stretch) if x)
        cache: dict[str, Any] = {}

        def make(ref: Any, a: int, b: int) -> tuple[np.ndarray, int]:
            _an, _plan, _s, _n, out, sr, rng = self._stretched(r)
            cache["range"] = rng
            return out, sr

        def manifest(path: str, key: str) -> dict[str, Any]:
            a, b = cache["range"]
            knots = _slice_knots(s.map.knots, a, b)
            w0 = plan.window[0]
            inner = Mapping.of([[(t - a) / s.map.sr, w0 + src / s.map.sr] for src, t in knots])
            return {
                "kind": "stretched-hit-wav", "file": path, "key": key, "sample": r["sampleId"], "asset": r["assetId"], "range": [r["start"], r["end"]],
                "scheme": {"plan": name, "density": s.density, "bpm": s.bpm, "speed": s.speed, "scope": (r["hit"].get("evidence") or {}).get("scope", -1)},
                "analysis": {"run": an.run, "identity": an.identity}, "mapping": Mapping.of(asset["mapping"]).compose(inner).to_list(), "createdAt": now_iso(),
            }

        return self.exports.export_generated(
            r["assetId"], r["start"], r["end"], version=["stretched-hit", an.identity, plan.window, s.density, s.bpm, sorted(s.beats.rest_cells), render_mod.RENDER_VERSION],
            make=make, content=content, track=track_label(asset, words), processing=processing, manifest=manifest,
        )

    def stretched_video(self, result_id: str, rank: int, index: int, words: dict[str, str]) -> tuple[dict[str, Any], dict[str, Any]]:
        """命中的卡拍视频要的东西（``VideoExportService.range`` 的 ``stretched``）：与命中卡拍试听 / WAV 同一个方案、同一段渲染结果，
        映射 = 命中段输出秒 → 资产局部秒（与卡拍 WAV 清单里的同一条）。"""
        r = self.resolve(result_id, rank, index)
        an, plan, s, name, out, sr, (a, b) = self._stretched(r)
        w0 = plan.window[0]
        inner = Mapping.of([[(t - a) / s.map.sr, w0 + src / s.map.sr] for src, t in _slice_knots(s.map.knots, a, b)])
        bundle = {
            "pcm": out, "sr": sr, "bpm": s.bpm, "inner": inner,
            "key": ["hit", an.identity, plan.window, name, s.density, s.bpm, sorted(s.beats.rest_cells), r["start"], r["end"]],
            "wav": lambda: self.export(result_id, rank, index, "stretched", words)["path"],
        }
        return r, bundle

    # ------------------------------------------------------------ REAPER

    def reaper_items(self, refs: list[dict[str, Any]], words: dict[str, str], kind: str) -> tuple[list[reaper.Item], list[dict[str, Any]]]:
        snap_mode = settings_mod.values(self.conn)["export.reaper_snap"]
        items, meta = [], []
        for ref in refs:
            r = self.resolve(ref["resultId"], int(ref["rank"]), int(ref["index"]))
            asset = assets_mod.get(self.conn, r["assetId"])
            label = "_".join(x for x in (track_label(asset, words), processing_label(asset, words)) if x)
            row = {"name": (r["name"] or "") + words.get("fragment", "")}
            an, plan, s, name = self._scheme(r)
            pcm, sr, media = self.rhythm._audio(r["assetId"], r["start"], r["end"])
            path = self.handoff._reaper_file(row, pcm, sr, media, label)
            a, b = self._slice(an, plan, s, r["start"], r["end"])
            off = int(round((r["start"] - plan.window[0]) * sr))
            pairs = [(f - a, int(round((c.src - plan.window[0]) * sr)) - off) for c, f in zip(s.map.cps, s.map.onsets) if c.kind == "onset" and a <= f < b]
            if kind == "original":
                onsets = [src for _t, src in pairs]
                markers = reaper.onset_markers(onsets, len(pcm), sr)
                length = len(pcm) / sr
            else:
                tp = {int(round(t)) - a: int(round(src)) - off for src, t in _slice_knots(s.map.knots, a, b)}
                tp.update(pairs)
                markers = [(t / sr, max(0, min(len(pcm), tp[t])) / sr) for t in sorted(tp)]
                length = (b - a) / sr
                onsets = [t for t, _src in pairs]
            first_onset = (min(onsets) / sr) if onsets else 0.0
            items.append(reaper.Item(0.0, first_onset if snap_mode == "onset" else 0.0, length, 60.0 / s.bpm, row["name"], markers, str(path)))
            meta.append({"hit": ref, "sample": r["sampleId"], "file": str(path), "kind": kind, "plan": name, "density": s.density, "bpm": s.bpm,
                         "speed": s.speed, "range": [r["start"], r["end"]], "analysis": an.run, "markers": len(markers)})
        pos = reaper.lay_out([it.length for it in items], [it.beat for it in items])
        return [reaper.Item(p, it.snap, it.length, it.beat, it.name, it.markers, it.path) for p, it in zip(pos, items)], meta


def _slice_knots(knots: list[tuple[int, int]], a: int, b: int) -> list[tuple[float, float]]:
    """映射（源帧, 目标帧）在目标 [a, b] 里的部分，两端插值补点；只保留两边都严格递增的点（映射要求单调）。"""
    def src_at(t: float) -> float:
        if t <= knots[0][1]:
            return float(knots[0][0])
        for (s0, t0), (s1, t1) in zip(knots, knots[1:]):
            if t <= t1:
                return s0 + (t - t0) * (s1 - s0) / (t1 - t0)
        return float(knots[-1][0])

    pts = [(src_at(a), float(a))] + [(float(s_), float(t)) for s_, t in knots if a < t < b] + [(src_at(b), float(b))]
    out = [pts[0]]
    for p in pts[1:]:
        if p[0] > out[-1][0] + 1e-9 and p[1] > out[-1][1] + 1e-9:
            out.append(p)
    return out
