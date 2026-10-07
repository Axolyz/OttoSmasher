"""OP/ED 区间（规格 05 §5.6、04 §4.3.3、§4.4 第 15 条；16 R6、S1.5、S10）。

- 从字幕识别（显式操作，单个或批量）：读原片关联的字幕文件（不是已导入的标记），按设置里的开始/结束标记配对（domain.oped_rule）。
  没有错误 → 结果直接登记（来源“字幕规则”），与已有区间（含人工）正长度交叠的不登记、不覆盖（幂等）；
  有错误 → 一个都不自动登记，只报告，并列出已配对的区间供逐对「确认此区间」（来源“人工确认”）。
- 手动标记：开始秒 + 用途 + 长度，必须在原片时长内，不能与已有区间交叠。
- 新建与删除都走统一编辑通道（可撤销；删除 = 软删除）；OP/ED 绑定原片实体，重新定位文件后仍有效。
- 排除语义（只排除字幕采样导入与批量语音分析）由使用方用 domain.overlap 判断，这里只管区间本身。

``origin`` 列只有 subtitle_rule / manual 两个值；人工的两种来源记在 ``evidence.via``：``confirm``（确认规则配对）/ ``mark``（手动标记）。
"""

from __future__ import annotations

import sqlite3
from collections.abc import Callable, Iterable
from typing import Any

from ottosmasher.domain import oped_rule, subtitles
from ottosmasher.domain.overlap import overlaps
from ottosmasher.store.db import transaction

from . import settings as settings_mod
from .edits import ChangeSet, EditService, loads
from .errors import CoreError

MAX_MARKERS = 8
MAX_MARKER_CHARS = 50


def validate_markers(v: Any) -> list[str]:
    """设置 subtitle.oped_start / oped_end：1–8 个非空标记（去空白后比较）。"""
    if not isinstance(v, list) or not all(isinstance(x, str) for x in v):
        raise CoreError("setting-invalid", reason="not-a-list")
    out = [x for x in v if oped_rule.normalize(x)]
    if not out:
        raise CoreError("setting-invalid", reason="too-short")
    if len(out) > MAX_MARKERS:
        raise CoreError("setting-invalid", reason="too-many", max=MAX_MARKERS)
    if any(len(x) > MAX_MARKER_CHARS for x in out):
        raise CoreError("setting-invalid", reason="too-long", max=MAX_MARKER_CHARS)
    return out


class OpedService:
    def __init__(self, conn: sqlite3.Connection, edits: EditService, on_change: Callable[[ChangeSet], None] | None = None) -> None:
        self.conn = conn
        self.edits = edits
        self.on_change = on_change

    def _source(self, source_id: str) -> sqlite3.Row:
        row = self.conn.execute("SELECT id, duration, subtitle_path FROM source WHERE id=?", (source_id,)).fetchone()
        if row is None:
            raise CoreError("source-not-found", id=source_id)
        return row

    def list(self, source_id: str) -> list[dict[str, Any]]:
        rows = self.conn.execute(
            'SELECT id, kind, start, "end", origin, evidence, version, created_at FROM oped WHERE source_id=? AND deleted=0 ORDER BY start',
            (source_id,),
        )
        out = []
        for r in rows:
            ev = loads(r["evidence"]) if r["evidence"] else None
            via = "rule" if r["origin"] == "subtitle_rule" else (ev or {}).get("via", "mark")
            out.append({"id": r["id"], "kind": r["kind"], "start": r["start"], "end": r["end"], "via": via, "version": r["version"]})
        return out

    def _overlapping(self, source_id: str, start: float, end: float) -> dict[str, Any] | None:
        for o in self.list(source_id):
            if overlaps(start, end, o["start"], o["end"]):
                return o
        return None

    # ---------- 从字幕识别

    def identify(self, source_id: str) -> dict[str, Any]:
        src = self._source(source_id)
        if not src["subtitle_path"]:
            raise CoreError("subtitle-not-associated", id=source_id)
        parsed = subtitles.read(src["subtitle_path"])
        values = settings_mod.values(self.conn)
        res = oped_rule.identify(parsed.cues, float(src["duration"] or 0.0), values["subtitle.oped_start"], values["subtitle.oped_end"])
        pairs = []
        for p in res.pairs:
            hit = self._overlapping(source_id, p.start, p.end)
            pairs.append(
                {"start": p.start, "end": p.end, "suggest": p.suggest, "refs": [p.start_ref, p.end_ref], "overlaps": None if hit is None else hit["id"]}
            )
        applied: list[str] = []
        if not res.errors:
            ops = [
                {
                    "entity": "oped",
                    "op": "create",
                    "fields": {
                        "source_id": source_id,
                        "kind": p["suggest"],
                        "start": p["start"],
                        "end": p["end"],
                        "origin": "subtitle_rule",
                        "evidence": {"refs": p["refs"], "file": parsed.fingerprint[:16]},
                    },
                }
                for p in pairs
                if p["overlaps"] is None
            ]
            if ops:
                with transaction(self.conn):
                    _, changes = self.edits.apply_within({"label": {"code": "oped-identify", "args": {"n": len(ops)}}, "ops": ops})
                applied = sorted(changes.entities.get("oped", set()))
                self._changed(changes, source_id)
        return {
            "sourceId": source_id,
            "pairs": pairs,
            "errors": res.errors,
            "applied": len(applied),
            "skippedOverlap": sum(1 for p in pairs if p["overlaps"] is not None) if not res.errors else 0,
        }

    def identify_many(self, source_ids: Iterable[str]) -> list[dict[str, Any]]:
        out = []
        for sid in source_ids:
            try:
                out.append(self.identify(sid))
            except CoreError as e:
                out.append({"sourceId": sid, "error": e.to_wire()})
        return out

    # ---------- 人工确认 / 手动标记 / 删除

    def add(self, source_id: str, kind: str, start: float, end: float, via: str, refs: list[str] | None = None) -> dict[str, Any]:
        src = self._source(source_id)
        duration = float(src["duration"] or 0.0)
        if kind not in ("OP", "ED"):
            raise CoreError("oped-invalid", reason="not-an-option")
        if via not in ("confirm", "mark"):
            raise CoreError("oped-invalid", reason="not-an-option")
        if start < 0 or not end > start or end > duration + oped_rule.EPS:
            raise CoreError("oped-invalid", reason="out-of-source", duration=round(duration, 3))
        hit = self._overlapping(source_id, start, end)
        if hit is not None:
            raise CoreError("oped-overlap", kind=hit["kind"], start=round(hit["start"], 3), end=round(hit["end"], 3))
        evidence: dict[str, Any] = {"via": via}
        if refs:
            evidence["refs"] = refs
        with transaction(self.conn):
            edit_id, changes = self.edits.apply_within(
                {
                    "label": {"code": "oped-add", "args": {"kind": kind}},
                    "ops": [
                        {
                            "entity": "oped",
                            "op": "create",
                            "fields": {"source_id": source_id, "kind": kind, "start": start, "end": end, "origin": "manual", "evidence": evidence},
                        }
                    ],
                }
            )
        self._changed(changes, source_id)
        return {"id": next(iter(changes.entities["oped"])), "editId": edit_id}

    def delete(self, oped_id: str) -> dict[str, Any]:
        row = self.conn.execute("SELECT source_id, version, kind FROM oped WHERE id=? AND deleted=0", (oped_id,)).fetchone()
        if row is None:
            raise CoreError("oped-not-found", id=oped_id)
        with transaction(self.conn):
            edit_id, changes = self.edits.apply_within(
                {
                    "label": {"code": "oped-delete", "args": {"kind": row["kind"]}},
                    "ops": [{"entity": "oped", "id": oped_id, "version": row["version"], "fields": {"deleted": True}}],
                }
            )
        self._changed(changes, row["source_id"])
        return {"editId": edit_id}

    def _changed(self, changes: ChangeSet, source_id: str) -> None:
        if self.on_change and changes.entities:
            changes.add("source", source_id)
            self.on_change(changes)
