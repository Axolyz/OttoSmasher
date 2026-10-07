"""字幕采样（规格 06 §6.4、04 §4.3.4；16 R4.8–R4.10、S1.6、S6.2）：从当前字幕版本的台词 / 音效标记批量新建采样。

- 声音来源：台词 → 默认人声轨，音效 → 默认音效轨；没有就报“请先指定默认人声轨 / 音效轨”，**不回退混音**（就地选择在界面上做，
  选好后重新预览）。
- 候选与状态（只有“待创建”可勾选）：``pending`` 待创建；``oped`` 与已确认 OP/ED 正长度交叠；``out-of-track`` 完全在默认轨覆盖范围外；
  ``no-name`` 清洗后名称为空。可按起止秒过滤显示。
- 区间：标记时间前后各扩展（设置 subtitle.pad_before / pad_after，默认 0.1 秒，允许与相邻句重叠）→ 裁到默认轨覆盖范围 → 换算成默认轨的资产选区。
- 新采样：名称 = 标记的清洗名；性质 台词 → 语音、音效 → 非调谐单音；文本快照（原文、对齐文本、原字幕时间；音效只作说明文字）；
  标签判定区间 = 原字幕区间裁到选区内（扩展部分碰到的邻句说话人不继承）；来源记录（标记、字幕版本）。说话人靠区段标签继承，不复制成本地标签。
- 每次显式创建都新建（允许重复、删后重建）；整批一个事务（任何一条失败则全部回滚）；预览后默认轨、角色、OP/ED、扩展设置或标记变了 → 拒绝并要求重新预览（R4.9）。
"""

from __future__ import annotations

import hashlib
import sqlite3
from collections.abc import Callable, Iterable
from typing import Any

from ottosmasher.domain.mapping import Mapping
from ottosmasher.domain.overlap import overlaps
from ottosmasher.store.db import transaction

from . import effective_tags
from . import settings as settings_mod
from .clock import new_id, now_iso
from .edits import ChangeSet, dumps, loads
from .errors import CoreError

ROLE_OF = {"line": "vocal", "sfx": "sfx"}
NATURE_OF = {"line": "speech", "sfx": "unpitched"}


class SubtitleSamples:
    def __init__(self, conn: sqlite3.Connection, on_change: Callable[[ChangeSet], None] | None = None) -> None:
        self.conn = conn
        self.on_change = on_change

    def preview(self, source_id: str, kind: str, start: float | None = None, end: float | None = None) -> dict[str, Any]:
        if kind not in ROLE_OF:
            raise CoreError("subtitle-sample-invalid", reason="not-an-option", field="kind")
        src = self.conn.execute("SELECT id, version, current_subtitle_version_id FROM source WHERE id=?", (source_id,)).fetchone()
        if src is None:
            raise CoreError("source-not-found", id=source_id)
        role = ROLE_OF[kind]
        values = settings_mod.values(self.conn)
        pad_a, pad_b = float(values["subtitle.pad_before"]), float(values["subtitle.pad_after"])

        track = self.conn.execute(
            "SELECT a.id, a.mapping, a.duration, a.version FROM default_track d JOIN sound_asset a ON a.id=d.asset_id"
            " WHERE d.source_id=? AND d.role=?",
            (source_id, role),
        ).fetchone()
        mapping = Mapping.of(loads(track["mapping"])) if track is not None else None
        cov = (mapping.source_start, mapping.source_end) if mapping is not None else None

        opeds = list(self.conn.execute('SELECT id, start, "end", version FROM oped WHERE source_id=? AND deleted=0', (source_id,)))
        rows = (
            list(
                self.conn.execute(
                    'SELECT id, start, "end", raw_text, clean_text, align_text_auto, align_text_manual, tags, version FROM annotation'
                    " WHERE source_id=? AND kind=? AND deleted=0 AND subtitle_version_id=? ORDER BY start, rowid",
                    (source_id, kind, src["current_subtitle_version_id"]),
                )
            )
            if src["current_subtitle_version_id"]
            else []
        )
        lines: list[dict[str, Any]] = []
        counts = {"pending": 0, "oped": 0, "out-of-track": 0, "no-name": 0}
        for r in rows:
            if start is not None and r["end"] <= start:
                continue
            if end is not None and r["start"] >= end:
                continue
            a, b = r["start"] - pad_a, r["end"] + pad_b
            status = "pending"
            sel: tuple[float, float] | None = None
            if not (r["clean_text"] or "").strip():
                status = "no-name"
            elif any(overlaps(r["start"], r["end"], o["start"], o["end"]) for o in opeds):
                status = "oped"
            elif cov is not None:
                if not overlaps(r["start"], r["end"], cov[0], cov[1]):
                    status = "out-of-track"
                else:
                    sel = (max(a, cov[0]), min(b, cov[1]))
            lines.append(
                {
                    "annotationId": r["id"],
                    "name": (r["clean_text"] or "").strip(),
                    "rawText": r["raw_text"],
                    # 说话人显示层（R5.5）：只显示名字；采样按原字幕区间经区段标签继承
                    "speakers": [t.split(":", 1)[1] for t in loads(r["tags"]) if t.startswith(("character:", "participants:"))],
                    "start": r["start"],
                    "end": r["end"],
                    "sampleStart": sel[0] if sel else max(a, 0.0),
                    "sampleEnd": sel[1] if sel else b,
                    "status": status,
                }
            )
            counts[status] += 1
        basis = {
            "track": None if track is None else [track["id"], track["version"]],
            "roles": None if track is None else self._roles(track["id"]),
            "source": src["version"],
            "pads": [pad_a, pad_b],
            "oped": [[o["id"], o["version"]] for o in opeds],
            "ann": [[r["id"], r["version"]] for r in rows],
            "range": [start, end],
        }
        return {
            "sourceId": source_id,
            "kind": kind,
            "trackId": None if track is None else track["id"],
            "missingDefault": track is None,
            "pads": [pad_a, pad_b],
            "token": hashlib.sha256(dumps(basis).encode()).hexdigest()[:32],
            "lines": lines,
            "counts": counts,
            "noSubtitles": not src["current_subtitle_version_id"],
        }

    def _roles(self, asset_id: str) -> list[str]:
        return [r[0] for r in self.conn.execute("SELECT role FROM asset_role WHERE asset_id=? AND state='on' ORDER BY role", (asset_id,))]

    def create(
        self, source_id: str, kind: str, token: str, annotation_ids: Iterable[str], start: float | None = None, end: float | None = None
    ) -> dict[str, Any]:
        ids = list(dict.fromkeys(annotation_ids))
        created: list[str] = []
        with transaction(self.conn):
            pv = self.preview(source_id, kind, start, end)
            if pv["missingDefault"]:
                raise CoreError("default-track-missing", role=ROLE_OF[kind])
            if pv["token"] != token:
                raise CoreError("subtitle-sample-stale", id=source_id)
            by_id = {ln["annotationId"]: ln for ln in pv["lines"]}
            track = self.conn.execute("SELECT mapping, language, duration FROM sound_asset WHERE id=?", (pv["trackId"],)).fetchone()
            mapping = Mapping.of(loads(track["mapping"]))
            version_id = self.conn.execute("SELECT current_subtitle_version_id FROM source WHERE id=?", (source_id,)).fetchone()[0]
            ts = now_iso()
            for aid in ids:
                ln = by_id.get(aid)
                if ln is None or ln["status"] != "pending":
                    raise CoreError("subtitle-sample-not-pending", annotation=aid, status=None if ln is None else ln["status"])
                a_src, b_src = ln["sampleStart"], ln["sampleEnd"]
                local_a, local_b = mapping.to_local(a_src), mapping.to_local(b_src)
                if not local_b > local_a:
                    raise CoreError("subtitle-sample-not-pending", annotation=aid, status="out-of-track")
                ann = self.conn.execute("SELECT raw_text, align_text_auto, align_text_manual FROM annotation WHERE id=?", (aid,)).fetchone()
                snapshot: dict[str, Any] = {"rawText": ann["raw_text"], "start": ln["start"], "end": ln["end"]}
                if kind == "line":
                    snapshot["alignText"] = ann["align_text_manual"] or ann["align_text_auto"] or ""
                sid = new_id()
                self.conn.execute(
                    'INSERT INTO sample(id, asset_id, start, "end", name, nature, language, created_via, origin, text_snapshot,'
                    " tag_judge_start, tag_judge_end, created_at, updated_at) VALUES (?,?,?,?,?,?,?,'subtitle',?,?,?,?,?,?)",
                    (
                        sid,
                        pv["trackId"],
                        local_a,
                        local_b,
                        ln["name"],
                        NATURE_OF[kind],
                        track["language"],
                        dumps({"kind": "subtitle", "annotation": aid, "subtitleVersion": version_id}),
                        dumps(snapshot),
                        max(ln["start"], a_src),
                        min(ln["end"], b_src),
                        ts,
                        ts,
                    ),
                )
                created.append(sid)
            effective_tags.refresh(self.conn, created)
        if self.on_change and created:
            cs = ChangeSet()
            for sid in created:
                cs.add("sample", sid)
            self.on_change(cs)
        return {"created": len(created), "ids": created}
