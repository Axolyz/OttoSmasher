"""加工链（所有者 2026-10-12，docs/QUESTIONS.md「音素回到原素材时间线、去掉父采样」）。

采样之间不再有父子关系；声音是怎么一步步做出来的记在音轨上（``sound_asset.input_asset_id`` + 范围 + 加工方式）。
- ``chain``：从采样所在的轨沿输入往上的每一步（采样详情「加工链」）；删除原素材时断开的地方写到断开为止。
- ``back_track``：「返回原素材」换到的整轨 = 沿加工链往上第一条整轨（完整覆盖且未变速）；找不到用原素材的分析音轨或原混音。
  永远不把局部成品当音源（所有者 2026-10-12）。
"""

from __future__ import annotations

import sqlite3
from typing import Any

from ottosmasher.domain.mapping import Mapping

from . import assets as assets_mod
from . import units
from .edits import loads
from .errors import CoreError

CHAIN_MAX = 32


def chain(conn: sqlite3.Connection, asset_id: str) -> dict[str, Any]:
    """``{steps: [{asset, sourceStart, sourceEnd, full}], complete}``：第一步是采样所在的轨；full = 整轨（完整覆盖且未变速）；
    complete = 一直追到了原混音（容器音轨，或没有输入的整轨声部）。"""
    steps: list[dict[str, Any]] = []
    memo: dict[Any, Any] = {}
    cur: str | None = asset_id
    seen: set[str] = set()
    complete = False
    while cur and cur not in seen and len(steps) < CHAIN_MAX:
        seen.add(cur)
        try:
            a = assets_mod.get(conn, cur)
        except CoreError:
            break
        m = Mapping.of(a["mapping"])
        steps.append({"asset": a, "sourceStart": round(m.source_start, 6), "sourceEnd": round(m.source_end, 6), "full": _full(conn, a, memo)})
        if a["origin"] == "stream" or (a["origin"] == "separation" and a["input_asset_id"] is None):
            complete = True
            break
        cur = a["input_asset_id"]
    return {"steps": steps, "complete": complete}


def _full(conn: sqlite3.Connection, a: Any, memo: dict[str, Any]) -> bool:
    key = ("dur", a["source_id"])
    if key not in memo:
        r = conn.execute("SELECT duration FROM source WHERE id=?", (a["source_id"],)).fetchone()
        memo[key] = float(r[0]) if r and r[0] is not None else None
    dur = memo[key]
    m = a["mapping"]
    return dur is not None and Mapping.of(loads(m) if isinstance(m, str) else m).is_full_track(dur)


def back_track(conn: sqlite3.Connection, asset_id: str, memo: dict[str, Any] | None = None) -> str | None:
    """「返回原素材」换到的整轨。``memo`` 在一次列表查询里共用。"""
    memo = {} if memo is None else memo
    key = ("back", asset_id)
    if key in memo:
        return memo[key]
    out: str | None = None
    cur: str | None = asset_id
    seen: set[str] = set()
    source_id = None
    while cur and cur not in seen:
        seen.add(cur)
        a = conn.execute("SELECT id, source_id, origin, mapping, input_asset_id FROM sound_asset WHERE id=?", (cur,)).fetchone()
        if a is None:
            break
        source_id = a["source_id"]
        if _full(conn, a, memo):
            out = a["id"]
            break
        cur = a["input_asset_id"]
    if out is None and source_id is not None:
        out = units.analysis_track(conn, source_id)
        if out is None:
            r = conn.execute("SELECT id FROM sound_asset WHERE source_id=? AND origin='stream' ORDER BY stream_ordinal LIMIT 1", (source_id,)).fetchone()
            out = r[0] if r else None
    memo[key] = out
    return out
