"""原片页用的标注视图（规格 03 §3.4 字幕上下文、05 §5.8 统计、UI_PLAN §4 准备清单）。只读。

- 台本 / 时间线车道：当前字幕版本的台词、音效、（用户标的）歌词标记，加上手动建立的标注（没有版本，始终参与）；未删除；按时间。
  每条带说话人（显示层：只给名字）、区段标签、是否在已确认 OP/ED 里（端点相接不算）。
- 派生轨（规格 03 §3.9 / 16 R7.6）：该原片的所有用户采样（跨音轨和资产），区间经各自资产的映射换到原片时间（分段映射，首尾分别换算）。
- 原片列表统计（05 §5.8）：句数 = 当前字幕版本中、不在 OP/ED 区间内的台词标记数；“无字幕” = 没有导入过标记；OP/ED 区间数。
  “已分析”在语音分析（阶段 4）之后补。
- 准备清单：字幕标记、整轨人声分离、默认人声轨、默认音效轨、OP/ED、台词采样（语音分析在阶段 4 加入）。每项给现状，没有顺序、不强制。
"""

from __future__ import annotations

import sqlite3
from typing import Any

from ottosmasher.domain.mapping import Mapping
from ottosmasher.domain.overlap import overlaps

from .edits import loads
from .errors import CoreError


def _speakers(tags: list[str]) -> list[str]:
    return [t.split(":", 1)[1] for t in tags if t.startswith(("character:", "participants:"))]


def list_for_source(conn: sqlite3.Connection, source_id: str) -> dict[str, Any]:
    src = conn.execute("SELECT current_subtitle_version_id FROM source WHERE id=?", (source_id,)).fetchone()
    if src is None:
        raise CoreError("source-not-found", id=source_id)
    opeds = [dict(r) for r in conn.execute('SELECT id, kind, start, "end" FROM oped WHERE source_id=? AND deleted=0 ORDER BY start', (source_id,))]
    rows = conn.execute(
        'SELECT id, kind, scope, scope_role, start, "end", raw_text, clean_text, tags, subtitle_version_id FROM annotation'
        " WHERE source_id=? AND deleted=0 AND (subtitle_version_id IS NULL OR subtitle_version_id IS ?) ORDER BY start, rowid",
        (source_id, src[0]),
    )
    out = []
    for r in rows:
        tags = loads(r["tags"])
        hit = next((o for o in opeds if overlaps(r["start"], r["end"], o["start"], o["end"])), None)
        out.append(
            {
                "id": r["id"],
                "kind": r["kind"],
                "scope": r["scope"],
                "start": r["start"],
                "end": r["end"],
                "text": r["raw_text"],
                "name": r["clean_text"],
                "speakers": _speakers(tags),
                "tags": tags,
                "fromSubtitle": r["subtitle_version_id"] is not None,
                "oped": hit["kind"] if hit else None,
            }
        )
    return {"annotations": out, "opeds": opeds, "derived": derived(conn, source_id)}


def derived(conn: sqlite3.Connection, source_id: str) -> list[dict[str, Any]]:
    out = []
    rows = conn.execute(
        'SELECT s.id, s.name, s.nature, s.start, s."end", s.asset_id, a.mapping FROM sample s JOIN sound_asset a ON a.id=s.asset_id WHERE a.source_id=?',
        (source_id,),
    )
    for r in rows:
        try:
            m = Mapping.of(loads(r["mapping"]))
            a, b = m.to_source(r["start"]), m.to_source(r["end"])
        except CoreError:
            continue  # 映射坏了的不画（采样本身仍在采样库里）
        out.append({"id": r["id"], "name": r["name"], "nature": r["nature"], "assetId": r["asset_id"], "start": a, "end": b})
    out.sort(key=lambda d: (d["start"], d["end"]))
    return out


def counts(conn: sqlite3.Connection) -> dict[str, dict[str, Any]]:
    """每个原片：句数（当前版本、不在 OP/ED 的台词）、是否导入过标记、OP/ED 数、派生采样数。"""
    opeds: dict[str, list[tuple[float, float]]] = {}
    for sid, a, b in conn.execute('SELECT source_id, start, "end" FROM oped WHERE deleted=0'):
        opeds.setdefault(sid, []).append((a, b))
    out: dict[str, dict[str, Any]] = {}
    for sid, cur in conn.execute("SELECT id, current_subtitle_version_id FROM source"):
        lines = 0
        if cur is not None:
            for a, b in conn.execute(
                "SELECT start, \"end\" FROM annotation WHERE source_id=? AND kind='line' AND deleted=0 AND subtitle_version_id=?", (sid, cur)
            ):
                if not any(overlaps(a, b, x, y) for x, y in opeds.get(sid, [])):
                    lines += 1
        out[sid] = {"lines": lines, "hasMarkers": cur is not None, "oped": len(opeds.get(sid, [])), "samples": 0}
    for sid, n in conn.execute("SELECT a.source_id, COUNT(*) FROM sample s JOIN sound_asset a ON a.id=s.asset_id GROUP BY a.source_id"):
        if sid in out:
            out[sid]["samples"] = n
    return out


def prep(conn: sqlite3.Connection, source_id: str) -> dict[str, Any]:
    """准备清单的现状（UI_PLAN §4；没有顺序、不强制）。"""
    src = conn.execute("SELECT id, subtitle_path, current_subtitle_version_id, duration FROM source WHERE id=?", (source_id,)).fetchone()
    if src is None:
        raise CoreError("source-not-found", id=source_id)
    c = counts(conn).get(source_id, {"lines": 0, "oped": 0})
    total_lines = 0
    if src["current_subtitle_version_id"]:
        total_lines = conn.execute(
            "SELECT COUNT(*) FROM annotation WHERE source_id=? AND deleted=0 AND subtitle_version_id=?", (source_id, src["current_subtitle_version_id"])
        ).fetchone()[0]
    defaults = {r[0]: r[1] for r in conn.execute("SELECT role, asset_id FROM default_track WHERE source_id=?", (source_id,))}

    def label(asset_id: str | None) -> dict[str, Any] | None:
        if asset_id is None:
            return None
        a = conn.execute("SELECT origin, stream_ordinal, stem_name, production FROM sound_asset WHERE id=?", (asset_id,)).fetchone()
        prod = loads(a["production"]) if a["production"] else {}
        return {"id": asset_id, "origin": a["origin"], "streamOrdinal": a["stream_ordinal"], "stem": a["stem_name"], "model": prod.get("model")}

    vocal_sep = conn.execute(
        "SELECT a.id FROM sound_asset a JOIN asset_role r ON r.asset_id=a.id AND r.role='vocal' AND r.state='on'"
        " WHERE a.source_id=? AND a.origin='separation' ORDER BY a.created_at LIMIT 1",
        (source_id,),
    ).fetchone()
    line_samples = conn.execute(
        "SELECT COUNT(*) FROM sample s JOIN sound_asset a ON a.id=s.asset_id WHERE a.source_id=? AND s.created_via='subtitle'", (source_id,)
    ).fetchone()[0]
    return {
        "subtitle": {"ok": total_lines > 0, "markers": total_lines, "associated": src["subtitle_path"] is not None},
        "separation": {"ok": vocal_sep is not None, "asset": label(vocal_sep[0]) if vocal_sep else None},
        "defaultVocal": {"ok": "vocal" in defaults, "asset": label(defaults.get("vocal"))},
        "defaultSfx": {"ok": "sfx" in defaults, "asset": label(defaults.get("sfx"))},
        "oped": {"ok": c["oped"] > 0, "count": c["oped"]},
        "lineSamples": {"ok": line_samples > 0, "count": line_samples},
    }
