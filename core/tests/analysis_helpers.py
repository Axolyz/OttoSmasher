"""测试用：在文本层登记一段并给它在某条资产上登记一次成功的分析（所有者 2026-10-09：分析属于“段 + 资产”）。"""

from __future__ import annotations

from typing import Any

from ottosmasher.core import units
from ottosmasher.core.clock import new_id, now_iso
from ottosmasher.core.edits import dumps


def add_segment(c: Any, start: float, end: float, text: str = "か", *, source_id: str | None = None, speakers: list[str] | None = None,
                origin: str = "typed", edited: bool = True) -> str:
    """直接写一段（原片秒）；同一原片同一区间的存活段已存在就复用。"""
    src = source_id or c.conn.execute("SELECT source_id FROM sound_asset WHERE id=?", (c.aid,)).fetchone()[0]
    r = c.conn.execute(
        'SELECT id FROM text_segment WHERE source_id=? AND deleted=0 AND abs(start-?)<1e-9 AND abs("end"-?)<1e-9', (src, start, end)
    ).fetchone()
    if r is not None:
        return r[0]
    sid, ts = new_id(), now_iso()
    c.conn.execute(
        'INSERT INTO text_segment(id, source_id, start, "end", text, speakers, origin, edited, created_at, updated_at) VALUES (?,?,?,?,?,?,?,?,?,?)',
        (sid, src, start, end, text, dumps(speakers or []), origin, int(edited), ts, ts),
    )
    return sid


def add_analysis(c: Any, start: float, end: float, phones: list[dict[str, Any]], *, text: str = "か", manual: bool = False,
                 snapshot: dict[str, Any] | None = None, asset_id: str | None = None, segment_id: str | None = None,
                 morae: list[str] | None = None) -> tuple[str, str]:
    """给段（没给就按 [start, end) 找或建）在资产上登记一次成功的分析并设为当前头。返回（版本 ID, 段 ID）。"""
    aid = asset_id or c.aid
    seg = segment_id or add_segment(c, start, end, text)
    t = c.conn.execute('SELECT start, "end", text FROM text_segment WHERE id=?', (seg,)).fetchone()
    snap = snapshot if snapshot is not None else c.flatten._freeze(aid, start, end)["_snap"]
    rid = new_id()
    sp = units.span_of({"phones": phones})
    unit = units.unit_id(seg, aid)
    c.conn.execute(
        "INSERT INTO measure_run(id, kind, owner_type, owner_id, asset_id, range_start, range_end, inputs, status, manual, result, created_at,"
        " span_start, span_end, seg_start, seg_end, seg_text) VALUES (?, 'alignment', 'asset_text', ?, ?, ?, ?, ?, 'ok', ?, ?, ?, ?, ?, ?, ?, ?)",
        (rid, unit, aid, start, end, dumps({"audio": {"snapshot": snap}, "text": t["text"]}), int(manual),
         dumps({"phones": phones, "morae": morae if morae is not None else [], "words": [], "frontend": {}}), now_iso(),
         sp[0] if sp else None, sp[1] if sp else None, t["start"], t["end"], t["text"]),
    )
    c.conn.execute(
        "INSERT INTO measure_head(owner_type, owner_id, kind, run_id, version) VALUES ('asset_text', ?, 'alignment', ?, 1)"
        " ON CONFLICT(owner_type, owner_id, kind) DO UPDATE SET run_id=excluded.run_id, version=version+1",
        (unit, rid),
    )
    return rid, seg
