"""列表行的副信息（用途视图，规格 07 §7.9；UI_PLAN §2.2）：随性质变化，列表一页取一次（不进列表查询，不拖慢分页）。

- 语音 / 未分类：节奏字形——音块在整句窗口里的位置（0–1）与音块数，取自语音检索索引（失效键等于现在的才用；没有 = 未知，不画）；
- 调谐单音：音名（``pitch:`` 标签优先，其次测得的原始音高 = 单音指标里的 MIDI 中位数）+ 音高曲线（采样范围内 F0 可靠帧的 MIDI，取 32 点）；
- 非调谐单音：起音时间（单音指标）+ 包络（F0 测量里的逐帧能量，取 32 点）。
都只读已有的测量与索引，不触发计算；缺了就不显示（P7：未知不是零）。
"""

from __future__ import annotations

import sqlite3
from typing import Any

import msgspec
import numpy as np

from ..algo import flatten as fl
from . import acoustic as ac_core
from .edits import loads
from .errors import CoreError
from .search_index import speech_keys

POINTS = 32


def _resample(v: np.ndarray, n: int = POINTS) -> list[float | None]:
    if not len(v):
        return []
    edges = np.linspace(0, len(v), n + 1).astype(int)
    out: list[float | None] = []
    for a, b in zip(edges[:-1], edges[1:], strict=True):
        seg = v[a : max(b, a + 1)]
        seg = seg[np.isfinite(seg)]
        out.append(round(float(np.median(seg)), 2) if len(seg) else None)
    return out


class Glyphs:
    def __init__(self, conn: sqlite3.Connection, speech: Any) -> None:
        self.conn = conn
        self.speech = speech

    def get(self, ids: list[str]) -> dict[str, dict[str, Any]]:
        ids = list(dict.fromkeys(ids))[:200]
        if not ids:
            return {}
        marks = ",".join("?" * len(ids))
        rows = {r["id"]: r for r in self.conn.execute(f'SELECT id, nature, asset_id, start, "end" FROM sample WHERE id IN ({marks})', ids)}
        out: dict[str, dict[str, Any]] = {}
        speech_ids = [i for i in ids if i in rows and rows[i]["nature"] in ("speech", "unclassified")]
        if speech_ids:
            keys = speech_keys(self.conn, speech_ids)
            dec = msgspec.msgpack.Decoder()
            for sid, key, data in self.conn.execute(
                f"SELECT sample_id, input_key, data FROM speech_index WHERE status = 'ok' AND sample_id IN ({','.join('?' * len(speech_ids))})", speech_ids
            ):
                if keys.get(sid, ("",))[0] != key:
                    continue  # 索引过期（资料变了，后台会重建）：先不画
                w = dec.decode(data)
                w0, w1 = float(w["window"][0]), float(w["window"][1])
                span = max(w1 - w0, 1e-9)
                blocks = [[round((a - w0) / span, 4), round((b - w0) / span, 4)] for a, b in zip(w["b"]["onset"], w["b"]["end"], strict=True)]
                out[sid] = {"blocks": blocks}
        single = [i for i in ids if i in rows and rows[i]["nature"] in ("pitched", "unpitched")]
        if single:
            metrics: dict[str, dict[str, Any]] = {}
            for sid, m in self.conn.execute(
                f"SELECT s.id, m.metrics FROM sample s JOIN acoustic_metric m ON {ac_core.valid_clause('s')} WHERE s.id IN ({','.join('?' * len(single))})",
                [ac_core.algo_tag(), *single],
            ):
                metrics[sid] = loads(m)
            pitches: dict[str, str] = {}
            for sid, tag in self.conn.execute(
                f"SELECT sample_id, tag FROM sample_effective_tag WHERE facet = 'pitch' AND sample_id IN ({','.join('?' * len(single))})"
                " ORDER BY provenance = 'local' DESC, tag",
                single,
            ):
                pitches.setdefault(sid, tag.split(":", 1)[1])  # 本地的优先
            for sid in single:
                r = rows[sid]
                g: dict[str, Any] = {}
                frames = None
                try:
                    _i0, fr, have = self.speech.f0_frames(r["asset_id"], float(r["start"]), float(r["end"]))
                    frames = (np.asarray(fr, dtype=np.float64), np.asarray(have, dtype=bool))
                except CoreError:
                    frames = None
                mt = metrics.get(sid, {})
                if r["nature"] == "pitched":
                    if sid in pitches:
                        g["note"] = pitches[sid]
                    elif mt.get("pitch") is not None:
                        g["note"] = fl.note_name(int(np.floor(float(mt["pitch"]) + 0.5)))
                    if frames is not None and frames[1].any():
                        f0, conf, en = frames[0][:, 0], frames[0][:, 1], frames[0][:, 2]
                        ok = frames[1] & fl.reliable(np.nan_to_num(f0), np.nan_to_num(conf), np.nan_to_num(en))
                        midi = np.full(len(f0), np.nan)
                        with np.errstate(divide="ignore", invalid="ignore"):
                            midi[ok] = 69.0 + 12.0 * np.log2(f0[ok] / 440.0)
                        if ok.any():
                            g["curve"] = _resample(midi)
                else:
                    if mt.get("attackTime") is not None:
                        g["attackMs"] = round(float(mt["attackTime"]), 1)
                    if frames is not None and frames[1].any():
                        en = np.where(frames[1], frames[0][:, 2], np.nan)
                        g["envelope"] = _resample(en)
                if g:
                    out[sid] = g
        return out
