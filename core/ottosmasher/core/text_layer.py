"""原片上的文本层、音效提示、区段标签（所有者 2026-10-09【基线变更】，docs/history/QUESTIONS.md「原片上的四类对象」）。

- **文本层的段**（说了什么，给分析）：每个原片一层，原片秒，作用于整个原片，允许重叠；字幕来源与手输来源同级、编辑方式一样。
  受保护 = 段本身被用户改过（文本、边界、拆分合并产物、切开后缩短的旧段、手输段：``edited``），或在任一条轨上有人工音素时间版本。
- **音效提示**（给人工拣选）：字幕里的（某某音效）行，也能手动新增；不进文本层、不做对齐、不带标签。
- **区段标签**（时间上的属性）：用户显式画的，原片 / 角色 / 资产三种作用域；说话人不在这里（是段的属性）。
- 复合操作（加段、拆分、合并、切开、新增音效提示、重新生成说话人）都拼成一个编辑批次：可撤销、原子。
  拆分与合并 = 删旧段、建新段（新段没有分析；旧段的分析随段软删，撤销即恢复）。
- 只读视图：原片页的段 / 提示 / 区段标签 / OP/ED / 派生采样，原片列表统计，准备清单。
时钟：段、提示、原片 / 角色作用域的区段标签都是原片秒；资产作用域的区段标签是资产局部秒。
"""

from __future__ import annotations

import sqlite3
from collections.abc import Callable, Iterable
from typing import Any

from ottosmasher.domain import subtitle_rules
from ottosmasher.domain.mapping import Mapping
from ottosmasher.domain.overlap import overlaps
from ottosmasher.store.db import transaction

from . import settings as settings_mod
from .edits import SEGMENT_MAX, ChangeSet, EditService, loads
from . import assets as assets_mod
from . import units
from .units import content_matches
from .errors import CoreError

SPEAKER_STATUS_MULTI = "speaker-status:\u591a\u4eba\u672a\u5206\u6bb5"
"""多人未分段（规格 06 §6.2.1，所有者 2026-10-05）"""


def speaker_tags(speakers: Iterable[str]) -> list[str]:
    """段的说话人 → 有效标签：一人 ``character:名``；多人每人 ``participants:名`` + ``speaker-status:多人未分段``。"""
    names = list(speakers)
    if not names:
        return []
    if len(names) == 1:
        return [f"character:{names[0]}"]
    return [*(f"participants:{n}" for n in names), SPEAKER_STATUS_MULTI]


def unit_prefix(segment_id: str) -> tuple[str, str]:
    """``seg:<段>@`` 开头的分析归属的区间（索引友好的前缀查询：'@' 之后是 'A'）。"""
    return f"seg:{segment_id}@", f"seg:{segment_id}A"


MANUAL_SQL = (
    "EXISTS (SELECT 1 FROM measure_run r WHERE r.owner_type = 'asset_text' AND r.kind = 'alignment'"
    " AND r.owner_id >= 'seg:' || {t}.id || '@' AND r.owner_id < 'seg:' || {t}.id || 'A' AND r.manual = 1)"
)
"""段在任一条轨上有人工音素时间版本（受保护的第二个标记）。"""


def protected_sql(t: str = "t") -> str:
    return f"({t}.edited = 1 OR {MANUAL_SQL.format(t=t)})"


USED_BY_SQL = (
    "(SELECT COUNT(*) FROM sample s JOIN sound_asset a ON a.id = s.asset_id"
    " WHERE a.source_id = {t}.source_id AND s.tag_judge_start < {t}.\"end\" AND s.tag_judge_end > {t}.start)"
)
"""读这一段的采样数（判定区间与段正长度交叠，P13：“这段被 N 个采样使用”）。"""


# ---------------------------------------------------------------- 只读视图


def _opeds(conn: sqlite3.Connection, source_id: str) -> list[dict[str, Any]]:
    return [dict(r) for r in conn.execute('SELECT id, version, kind, start, "end" FROM oped WHERE source_id=? AND deleted=0 ORDER BY start', (source_id,))]


def _analysis_states(conn: sqlite3.Connection, asset_id: str, segs: list[sqlite3.Row]) -> dict[str, str]:
    """段的音素状态（这条轨读的那一份：原素材上一份、回导来的另一份）：ok（有可用的）/ stale（段改过）/ failed（只有失败）/ none。
    这条轨不含人声 → 不给状态。"""
    out: dict[str, str] = {}
    a = assets_mod.get(conn, asset_id)
    if not units.voiced(a):
        return out
    base = units.base_of(a)
    for t in segs:
        rows = conn.execute(
            "SELECT status, seg_start, seg_end, seg_text FROM measure_run WHERE owner_type='asset_text' AND kind='alignment' AND owner_id=?",
            (units.unit_id(t["id"], base),),
        ).fetchall()
        oks = [r for r in rows if r["status"] == "ok"]
        if any(content_matches(r, t) for r in oks):
            out[t["id"]] = "ok"
        elif oks:
            out[t["id"]] = "stale"
        elif rows:
            out[t["id"]] = "failed"
        else:
            out[t["id"]] = "none"
    return out


def list_for_source(conn: sqlite3.Connection, source_id: str, asset_id: str | None = None) -> dict[str, Any]:
    if conn.execute("SELECT 1 FROM source WHERE id=?", (source_id,)).fetchone() is None:
        raise CoreError("source-not-found", id=source_id)
    opeds = _opeds(conn, source_id)

    def oped_of(a: float, b: float) -> str | None:
        hit = next((o for o in opeds if overlaps(a, b, o["start"], o["end"])), None)
        return hit["kind"] if hit else None

    segs = conn.execute(f"{_SEG_SQL} WHERE t.source_id=? AND t.deleted=0 ORDER BY t.start, t.\"end\", t.id", (source_id,)).fetchall()
    states = _analysis_states(conn, asset_id, segs) if asset_id else {}
    segments = [_segment_wire(t, i, oped_of(t["start"], t["end"]), states.get(t["id"])) for i, t in enumerate(segs, start=1)]
    hints = [
        {
            "id": h["id"], "version": h["version"], "start": h["start"], "end": h["end"], "text": h["text"], "origin": h["origin"],
            "edited": bool(h["edited"]), "protected": bool(h["edited"]) or h["origin"] == "manual", "oped": oped_of(h["start"], h["end"]),
        }
        for h in conn.execute('SELECT id, version, start, "end", text, origin, edited FROM sfx_hint WHERE source_id=? AND deleted=0 ORDER BY start, "end", id', (source_id,))
    ]
    tags = [
        {
            "id": r["id"], "version": r["version"], "scope": r["scope"], "scopeRole": r["scope_role"], "scopeAssetId": r["scope_asset_id"],
            "start": r["start"], "end": r["end"], "label": r["label"], "tags": loads(r["tags"]),
        }
        for r in conn.execute(
            'SELECT id, version, scope, scope_role, scope_asset_id, start, "end", label, tags FROM range_tag WHERE source_id=? AND deleted=0 ORDER BY start, rowid',
            (source_id,),
        )
    ]
    return {"segments": segments, "hints": hints, "tags": tags, "opeds": opeds, "derived": derived(conn, source_id)}


_SEG_SQL = (
    'SELECT t.id, t.version, t.source_id, t.start, t."end", t.text, t.speakers, t.origin, t.provenance, t.edited, t.speaker_edited,'
    " t.speakers_withheld,"
    f" {MANUAL_SQL.format(t='t')} AS manual, {USED_BY_SQL.format(t='t')} AS used_by FROM text_segment t"
)


def _segment_wire(t: sqlite3.Row, ordinal: int, oped: str | None, analysis: str | None) -> dict[str, Any]:
    prov = loads(t["provenance"]) if t["provenance"] else None
    return {
        "id": t["id"], "version": t["version"], "ordinal": ordinal, "start": t["start"], "end": t["end"], "text": t["text"],
        "speakers": loads(t["speakers"]), "origin": t["origin"], "edited": bool(t["edited"]), "speakerEdited": bool(t["speaker_edited"]),
        "speakersWithheld": bool(t["speakers_withheld"]) and not t["speaker_edited"],
        "manual": bool(t["manual"]), "protected": bool(t["edited"] or t["manual"]), "usedBy": int(t["used_by"]),
        "raw": (prov or {}).get("raw"), "oped": oped, "analysis": analysis,
    }


def get_segment(conn: sqlite3.Connection, segment_id: str) -> dict[str, Any]:
    """一段（舞台语音面板里「编辑这段…」用）：同 list 里的一行；序号按存活段的 (start, end, id) 排出来。"""
    t = conn.execute(f"{_SEG_SQL} WHERE t.id=? AND t.deleted=0", (segment_id,)).fetchone()
    if t is None:
        raise CoreError("segment-not-found", id=segment_id)
    ordinal = conn.execute(
        'SELECT COUNT(*) FROM text_segment WHERE source_id=? AND deleted=0 AND (start < ? OR (start = ? AND ("end" < ? OR ("end" = ? AND id <= ?))))',
        (t["source_id"], t["start"], t["start"], t["end"], t["end"], t["id"]),
    ).fetchone()[0]
    hit = next((o for o in _opeds(conn, t["source_id"]) if overlaps(t["start"], t["end"], o["start"], o["end"])), None)
    return _segment_wire(t, int(ordinal), hit["kind"] if hit else None, None)


def derived(conn: sqlite3.Connection, source_id: str) -> list[dict[str, Any]]:
    """原片页“采样”车道：这个原素材上的全部采样（所有音轨），按原素材起止（建采样时算好的原素材秒）。"""
    rows = conn.execute(
        'SELECT s.id, s.name, s.nature, s.asset_id, s.src_start, s.src_end FROM sample s JOIN sound_asset a ON a.id=s.asset_id'
        " WHERE a.source_id=? AND s.src_start IS NOT NULL ORDER BY s.src_start, s.src_end, s.rowid",
        (source_id,),
    )
    return [{"id": r["id"], "name": r["name"], "nature": r["nature"], "assetId": r["asset_id"], "start": r["src_start"], "end": r["src_end"]} for r in rows]


def counts(conn: sqlite3.Connection) -> dict[str, dict[str, Any]]:
    """每个原片：句数（不在 OP/ED 里的段）、有没有文本层或音效提示、OP/ED 数、采样数。"""
    opeds: dict[str, list[tuple[float, float]]] = {}
    for sid, a, b in conn.execute('SELECT source_id, start, "end" FROM oped WHERE deleted=0'):
        opeds.setdefault(sid, []).append((a, b))
    out: dict[str, dict[str, Any]] = {sid: {"lines": 0, "hasMarkers": False, "oped": len(opeds.get(sid, [])), "samples": 0} for (sid,) in conn.execute("SELECT id FROM source")}
    for sid, a, b in conn.execute('SELECT source_id, start, "end" FROM text_segment WHERE deleted=0'):
        if sid not in out:
            continue
        out[sid]["hasMarkers"] = True
        if not any(overlaps(a, b, x, y) for x, y in opeds.get(sid, [])):
            out[sid]["lines"] += 1
    for (sid,) in conn.execute("SELECT DISTINCT source_id FROM sfx_hint WHERE deleted=0"):
        if sid in out:
            out[sid]["hasMarkers"] = True
    for sid, n in conn.execute("SELECT a.source_id, COUNT(*) FROM sample s JOIN sound_asset a ON a.id=s.asset_id GROUP BY a.source_id"):
        if sid in out:
            out[sid]["samples"] = n
    return out


def prep(conn: sqlite3.Connection, source_id: str) -> dict[str, Any]:
    """准备清单的现状（UI_PLAN §4；没有顺序、不强制）。"""
    src = conn.execute("SELECT id, subtitle_path FROM source WHERE id=?", (source_id,)).fetchone()
    if src is None:
        raise CoreError("source-not-found", id=source_id)
    c = counts(conn).get(source_id, {"lines": 0, "oped": 0})
    markers = conn.execute("SELECT (SELECT COUNT(*) FROM text_segment WHERE source_id=? AND deleted=0) + (SELECT COUNT(*) FROM sfx_hint WHERE source_id=? AND deleted=0)",
                           (source_id, source_id)).fetchone()[0]
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
        "SELECT COUNT(*) FROM sample s JOIN sound_asset a ON a.id=s.asset_id WHERE a.source_id=? AND s.created_via='segment'", (source_id,)
    ).fetchone()[0]
    return {
        "subtitle": {"ok": markers > 0, "markers": markers, "associated": src["subtitle_path"] is not None},
        "separation": {"ok": vocal_sep is not None, "asset": label(vocal_sep[0]) if vocal_sep else None},
        "defaultVocal": {"ok": "vocal" in defaults, "asset": label(defaults.get("vocal"))},
        "defaultSfx": {"ok": "sfx" in defaults, "asset": label(defaults.get("sfx"))},
        "oped": {"ok": c["oped"] > 0, "count": c["oped"]},
        "lineSamples": {"ok": line_samples > 0, "count": line_samples},
    }


def promote_batch(
    conn: sqlite3.Connection, sample_id: str, tags: list[str], *, role: str | None = None, start: float | None = None, end: float | None = None
) -> dict[str, Any]:
    """本地标签提升为区段标签的编辑批次（R5.6）。返回 {batch, scope, role, assetId, start, end, roles}；不写库。
    作用域默认取资产的角色（一个角色 → 该角色；两个 → 必须选；没有 → 资产作用域，时间用资产局部秒）；时间默认 = 判定区间。"""
    s = conn.execute('SELECT id, asset_id, start, "end", tag_judge_start, tag_judge_end, version FROM sample WHERE id=?', (sample_id,)).fetchone()
    if s is None:
        raise CoreError("sample-not-found", id=sample_id)
    local = [r[0] for r in conn.execute("SELECT tag FROM sample_tag WHERE sample_id=? ORDER BY tag", (sample_id,))]
    tags = sorted({t.strip() for t in tags if t.strip()})
    if not tags or any(t not in local for t in tags):
        raise CoreError("promote-invalid", reason="not-local-tags")
    a = conn.execute("SELECT source_id, mapping FROM sound_asset WHERE id=?", (s["asset_id"],)).fetchone()
    roles = [r[0] for r in conn.execute("SELECT role FROM asset_role WHERE asset_id=? AND state='on' ORDER BY role", (s["asset_id"],))]
    m = Mapping.of(loads(a["mapping"]))
    js, je = (s["tag_judge_start"], s["tag_judge_end"]) if s["tag_judge_start"] is not None else (m.to_source(s["start"]), m.to_source(s["end"]))
    if not roles:
        scope, role = "asset", None
        a0, b0 = m.to_local(max(js, m.source_start)), m.to_local(min(je, m.source_end))
    else:
        if role is None:
            if len(roles) > 1:
                raise CoreError("promote-invalid", reason="role-required", roles=roles)
            role = roles[0]
        if role not in roles:
            raise CoreError("promote-invalid", reason="role-not-on-asset", role=role, roles=roles)
        scope = "role"
        a0, b0 = js, je
    start = a0 if start is None else float(start)
    end = b0 if end is None else float(end)
    fields: dict[str, Any] = {"source_id": a["source_id"], "scope": scope, "start": start, "end": end, "tags": tags}
    if scope == "role":
        fields["scope_role"] = role
    else:
        fields["scope_asset_id"] = s["asset_id"]
    batch = {
        "label": {"code": "tags-promote", "args": {"n": len(tags)}},
        "ops": [
            {"entity": "range_tag", "op": "create", "fields": fields},
            {"entity": "sample", "id": sample_id, "version": s["version"], "fields": {"local_tags": [t for t in local if t not in tags]}},
        ],
    }
    return {"batch": batch, "scope": scope, "role": role, "roles": roles, "assetId": s["asset_id"], "start": start, "end": end}


# ---------------------------------------------------------------- 复合操作（编辑批次）


def _merged_provenance(segs: list[sqlite3.Row]) -> dict[str, Any]:
    """合并出来的段的来源：由哪几段合成，以及各段的原文（按时间；``raw`` = 连起来，``raws`` = 逐段，手动加的段没有原文）。"""
    raws = [(loads(s["provenance"]) or {}).get("raw") if s["provenance"] else None for s in segs]
    out: dict[str, Any] = {"from": [s["id"] for s in segs]}
    if any(r is not None for r in raws):
        out |= {"raw": "\n".join(r for r in raws if r is not None), "raws": raws}
    return out


class TextLayer:
    def __init__(self, conn: sqlite3.Connection, edits: EditService, on_change: Callable[[ChangeSet], None] | None = None) -> None:
        self.conn = conn
        self.edits = edits
        self.on_change = on_change

    def _apply(self, batch: dict[str, Any]) -> tuple[str | None, ChangeSet]:
        with transaction(self.conn):
            edit_id, changes = self.edits.apply_within(batch)
        if self.on_change and changes.entities:
            self.on_change(changes)
        return edit_id, changes

    def _segment(self, segment_id: str) -> sqlite3.Row:
        r = self.conn.execute(
            'SELECT id, source_id, start, "end", text, speakers, origin, provenance, edited, version, deleted FROM text_segment WHERE id=?', (segment_id,)
        ).fetchone()
        if r is None or r["deleted"]:
            raise CoreError("segment-not-found", id=segment_id)
        return r

    def overlapping(self, source_id: str, start: float, end: float, exclude: Iterable[str] = ()) -> list[sqlite3.Row]:
        ex = set(exclude)
        return [
            r
            for r in self.conn.execute(
                'SELECT id, start, "end", text, version, edited FROM text_segment WHERE source_id=? AND deleted=0 AND start < ? AND "end" > ? AND start > ?'
                ' ORDER BY start, "end", id',
                (source_id, end, start, start - SEGMENT_MAX - 1e-6),
            )
            if r["id"] not in ex
        ]

    @staticmethod
    def _can_cut(start: float, end: float, rows: list[sqlite3.Row]) -> bool:
        """「切开」= 只改时间边界：每个重叠段都只从一侧伸进来（所有者 2026-10-09）。"""
        for r in rows:
            left = r["start"] < start < r["end"] <= end + 1e-9
            right = start - 1e-9 <= r["start"] < end < r["end"]
            if not (left or right):
                return False
        return True

    def check_add(self, source_id: str, start: float, end: float) -> dict[str, Any]:
        """加一段前看看与哪些段重叠、能不能切开（界面据此让用户选替换 / 切开 / 取消）。"""
        rows = self.overlapping(source_id, start, end)
        return {
            "conflicts": [{"id": r["id"], "start": r["start"], "end": r["end"], "text": r["text"]} for r in rows],
            "canCut": bool(rows) and self._can_cut(start, end, rows),
        }

    def add_segment(self, source_id: str, start: float, end: float, text: str, resolve: str | None = None) -> dict[str, Any]:
        """手输台词 = 在文本层加一段（手输段，算受保护）。与已有段重叠时必须给 ``resolve``：replace（删掉重叠段）/ cut（把重叠段缩到新段外面）。"""
        rows = self.overlapping(source_id, start, end)
        ops: list[dict[str, Any]] = []
        if rows:
            if resolve not in ("replace", "cut"):
                raise CoreError("segment-overlap", n=len(rows), canCut=self._can_cut(start, end, rows))
            if resolve == "cut" and not self._can_cut(start, end, rows):
                raise CoreError("segment-overlap", n=len(rows), canCut=False)
            for r in rows:
                if resolve == "replace":
                    ops.append({"entity": "segment", "id": r["id"], "version": r["version"], "fields": {"deleted": True}})
                elif r["start"] < start:
                    ops.append({"entity": "segment", "id": r["id"], "version": r["version"], "fields": {"end": start}})
                else:
                    ops.append({"entity": "segment", "id": r["id"], "version": r["version"], "fields": {"start": end}})
        ops.append({"entity": "segment", "op": "create", "fields": {
            "source_id": source_id, "start": start, "end": end, "text": text, "speakers": [], "origin": "typed", "edited": True}})
        edit_id, changes = self._apply({"label": {"code": "segment-add", "args": {}}, "ops": ops})
        new = [x for x in changes.entities.get("segment", set()) if x not in {r["id"] for r in rows}]
        return {"id": new[0] if new else None, "editId": edit_id}

    def split(self, segment_id: str, version: int, at: float, left: str, right: str) -> dict[str, Any]:
        """拆分 = 删旧段、建两个新段（受保护；新段没有分析）。``at`` 原片秒，必须在段内。"""
        t = self._segment(segment_id)
        if int(t["version"]) != int(version):
            raise CoreError("edit-conflict", entity="segment", id=segment_id, expected=version, actual=int(t["version"]))
        if not (t["start"] + 1e-3 < at < t["end"] - 1e-3):
            raise CoreError("segment-invalid", reason="split-outside")
        prov = (loads(t["provenance"]) if t["provenance"] else {}) | {"from": [segment_id]}
        base = {"source_id": t["source_id"], "speakers": loads(t["speakers"]), "origin": t["origin"], "provenance": prov, "edited": True}
        ops = [
            {"entity": "segment", "id": segment_id, "version": t["version"], "fields": {"deleted": True}},
            {"entity": "segment", "op": "create", "fields": base | {"start": t["start"], "end": at, "text": left}},
            {"entity": "segment", "op": "create", "fields": base | {"start": at, "end": t["end"], "text": right}},
        ]
        edit_id, changes = self._apply({"label": {"code": "segment-split", "args": {}}, "ops": ops})
        return {"ids": sorted(changes.entities.get("segment", set()) - {segment_id}), "editId": edit_id}

    def merge(self, ids: list[str], text: str | None = None) -> dict[str, Any]:
        """合并 = 删这些段、建一个新段（区间并起来，文本默认按时间用换行连接，说话人按出现顺序合并；受保护；新段没有分析）。"""
        segs = [self._segment(i) for i in dict.fromkeys(ids)]
        if len(segs) < 2 or len({s["source_id"] for s in segs}) != 1:
            raise CoreError("segment-invalid", reason="merge-needs-two")
        segs.sort(key=lambda s: (s["start"], s["end"]))
        names: list[str] = []
        for s in segs:
            names += [n for n in loads(s["speakers"]) if n not in names]
        ops: list[dict[str, Any]] = [{"entity": "segment", "id": s["id"], "version": s["version"], "fields": {"deleted": True}} for s in segs]
        ops.append({"entity": "segment", "op": "create", "fields": {
            "source_id": segs[0]["source_id"], "start": min(s["start"] for s in segs), "end": max(s["end"] for s in segs),
            "text": text if text is not None else "\n".join(s["text"] for s in segs), "speakers": names,
            "origin": "subtitle" if all(s["origin"] == "subtitle" for s in segs) else "typed",
            "provenance": _merged_provenance(segs), "edited": True}})
        edit_id, changes = self._apply({"label": {"code": "segment-merge", "args": {"n": len(segs)}}, "ops": ops})
        new = sorted(changes.entities.get("segment", set()) - {s["id"] for s in segs})
        return {"id": new[0] if new else None, "editId": edit_id}

    def add_hint(self, source_id: str, start: float, end: float, text: str) -> dict[str, Any]:
        """手动新增一条音效提示（所有者 2026-10-09：算受保护）。"""
        ops = [{"entity": "sfx_hint", "op": "create", "fields": {
            "source_id": source_id, "start": start, "end": end, "text": text, "origin": "manual", "edited": True}}]
        edit_id, changes = self._apply({"label": {"code": "hint-add", "args": {}}, "ops": ops})
        return {"id": next(iter(changes.entities.get("sfx_hint", {None}))), "editId": edit_id}

    def regenerate_speakers(self, source_id: str) -> dict[str, Any]:
        """按当前规则重新生成说话人：只动字幕来源、未受保护、说话人没被手改过的段（从来源记录里的原文重新提取）。"""
        return self.regenerate_speakers_many([source_id])

    def regenerate_speakers_many(self, source_ids: list[str]) -> dict[str, Any]:
        """多个原素材一起重新生成：整批一个编辑、一次撤销（所有者 2026-11-03）。"""
        rules = subtitle_rules.SubtitleRules.build(settings_mod.values(self.conn))
        ops: list[dict[str, Any]] = []
        for sid in dict.fromkeys(source_ids):
            ops.extend(self._speaker_ops(sid, rules))
        if not ops:
            return {"changed": 0, "editId": None}
        edit_id, _ = self._apply({"label": {"code": "speakers-regenerate", "args": {"n": len(ops)}}, "ops": ops})
        return {"changed": len(ops), "editId": edit_id}

    def _speaker_ops(self, source_id: str, rules: Any) -> list[dict[str, Any]]:
        rows = self.conn.execute(
            f'SELECT t.id, t.version, t.speakers, t.speakers_withheld, t.provenance FROM text_segment t WHERE t.source_id=? AND t.deleted=0 AND t.origin=\'subtitle\''
            f" AND t.speaker_edited=0 AND NOT {protected_sql('t')} ORDER BY t.start",
            (source_id,),
        ).fetchall()
        ops = []
        for r in rows:
            raw = (loads(r["provenance"]) or {}).get("raw") if r["provenance"] else None
            if raw is None:
                continue
            c = subtitle_rules.classify(raw, rules)
            names = list(c.speakers) if c.kind == "line" else []
            withheld = c.kind == "line" and c.withheld
            if names != loads(r["speakers"]) or withheld != bool(r["speakers_withheld"]):
                ops.append({"entity": "segment", "id": r["id"], "version": r["version"],
                            "fields": {"speakers": names, "speaker_edited": False, "speakers_withheld": withheld}})
        return ops
