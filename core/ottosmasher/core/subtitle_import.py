"""字幕标记导入（规格 06 §6.1、04 §4.2.2；16 R4.1–R4.3、S1.4、S11.2–S11.4）。

- 预览：读字幕 → 按**当前**字幕规则分类 → 每行一个状态：
  ``importable`` 可导入；``oped`` 与已确认 OP/ED 正长度交叠（仍可导入，取样与批量分析时跳过；``opedPartial`` = 跨边界）；
  ``invalid`` 无效范围（开始 < 0、结束 ≤ 开始、超出原片时长；不可勾选，导入时跳过并报告）；
  ``registered`` 这个字幕版本里已经登记过（只补登未登记的行）。默认勾选 importable + oped。
- 预览令牌：字幕内容指纹、原片（含分析音轨、时长、关联字幕）的版本、OP/ED 区间、字幕规则——任何一项变了，导入时要求重新预览。
- 导入：一个写事务。字幕版本按**文件内容**区分（同一原片同一指纹 = 同一版本）；新内容 → 新版本快照（全部行）并成为当前版本；
  已有内容 → 只补登并设为当前（切回旧版本的方法）。标注经统一编辑通道新建（可撤销：撤销 = 软删除这批标注并恢复原来的当前版本）。
  只插入不覆盖：已登记（未删除）的行不再导入，用户改过的标记不会被改写。不建任何采样、不触发分析。
- 说话人：一人 → ``character:名``；多人 → 每人 ``participants:名`` + ``speaker-status:多人未分段``；作用域“人声”角色（规格 06 §6.2.1）。
  音效行作用域为原片、没有说话人。
"""

from __future__ import annotations

import hashlib
import sqlite3
from collections.abc import Callable, Iterable
from pathlib import Path
from typing import Any

from ottosmasher.domain import subtitle_rules, subtitles
from ottosmasher.domain.overlap import contains, overlaps
from ottosmasher.store.db import transaction

from . import settings as settings_mod
from .clock import new_id, now_iso
from .edits import ChangeSet, EditService, dumps
from .errors import CoreError

SPEAKER_STATUS_MULTI = "speaker-status:\u591a\u4eba\u672a\u5206\u6bb5"
"""多人未分段（规格 06 §6.2.1，所有者 2026-10-05）"""

DURATION_EPS = 1e-6


def speaker_tags(speakers: Iterable[str]) -> list[str]:
    names = list(speakers)
    if not names:
        return []
    if len(names) == 1:
        return [f"character:{names[0]}"]
    return [*(f"participants:{n}" for n in names), SPEAKER_STATUS_MULTI]


class SubtitleImporter:
    def __init__(self, conn: sqlite3.Connection, edits: EditService, on_change: Callable[[ChangeSet], None] | None = None) -> None:
        self.conn = conn
        self.edits = edits
        self.on_change = on_change

    # ---------- 预览

    def _source(self, source_id: str) -> sqlite3.Row:
        row = self.conn.execute(
            "SELECT id, path, duration, subtitle_path, default_audio_stream, current_subtitle_version_id, version FROM source WHERE id=?",
            (source_id,),
        ).fetchone()
        if row is None:
            raise CoreError("source-not-found", id=source_id)
        return row

    def _opeds(self, source_id: str) -> list[sqlite3.Row]:
        return list(
            self.conn.execute(
                'SELECT id, kind, start, "end", version FROM oped WHERE source_id=? AND deleted=0 ORDER BY start', (source_id,)
            )
        )

    def preview(self, source_id: str, path: str | None = None) -> dict[str, Any]:
        src = self._source(source_id)
        sub_path = path or src["subtitle_path"]
        if not sub_path:
            raise CoreError("subtitle-not-associated", id=source_id)
        parsed = subtitles.read(sub_path)
        values = settings_mod.values(self.conn)
        rules = subtitle_rules.SubtitleRules.build(values)
        opeds = self._opeds(source_id)
        duration = float(src["duration"] or 0.0)

        existing = self.conn.execute(
            "SELECT id FROM subtitle_version WHERE source_id=? AND content_hash=?", (source_id, parsed.fingerprint)
        ).fetchone()
        registered: set[int] = set()
        if existing is not None:
            registered = {
                r[0]
                for r in self.conn.execute(
                    "SELECT l.line_no FROM subtitle_line l JOIN annotation a ON a.subtitle_line_id = l.id"
                    " WHERE l.version_id=? AND a.deleted=0",
                    (existing[0],),
                )
            }
        version_state = "new" if existing is None else ("current" if existing[0] == src["current_subtitle_version_id"] else "switch")

        lines: list[dict[str, Any]] = []
        counts = {"importable": 0, "oped": 0, "invalid": 0, "registered": 0}
        for cue in parsed.cues:
            c = subtitle_rules.classify(cue.text, rules)
            row: dict[str, Any] = {
                "no": cue.order,
                "ref": cue.ref,
                "start": cue.start,
                "end": cue.end,
                "text": cue.text,
                **c.wire(),
            }
            reason = None
            if cue.start < 0:
                reason = "negative-start"
            elif not cue.end > cue.start:
                reason = "empty"
            elif cue.end > duration + DURATION_EPS:
                reason = "beyond-end"
            if reason is not None:
                row["status"], row["reason"] = "invalid", reason
            elif cue.order in registered:
                row["status"] = "registered"
            else:
                hit = [o for o in opeds if overlaps(cue.start, cue.end, o["start"], o["end"])]
                if hit:
                    row["status"] = "oped"
                    row["oped"] = hit[0]["kind"]
                    row["opedPartial"] = not any(contains(o["start"], o["end"], cue.start, cue.end) for o in hit)
                else:
                    row["status"] = "importable"
            counts[row["status"]] += 1
            lines.append(row)

        token = self._token(src, parsed.fingerprint, opeds, rules)
        return {
            "sourceId": source_id,
            "path": str(sub_path),
            "fileName": Path(sub_path).name,
            "format": parsed.format,
            "fingerprint": parsed.fingerprint,
            "token": token,
            "versionState": version_state,
            "lines": lines,
            "counts": counts,
            "problems": parsed.problems,
        }

    @staticmethod
    def _token(src: sqlite3.Row, fingerprint: str, opeds: list[sqlite3.Row], rules: subtitle_rules.SubtitleRules) -> str:
        basis = {
            "fp": fingerprint,
            "source": [src["version"], src["duration"], src["default_audio_stream"], src["subtitle_path"]],
            "oped": [[o["id"], o["start"], o["end"], o["version"]] for o in opeds],
            "rules": dict(rules.patterns),
        }
        return hashlib.sha256(dumps(basis).encode()).hexdigest()[:32]

    # ---------- 导入

    def import_(self, source_id: str, token: str, line_nos: Iterable[int] | None = None, path: str | None = None) -> dict[str, Any]:
        """``line_nos`` 为 None = 默认勾选（可导入 + OP/ED 区间）。"""
        with transaction(self.conn):
            pv = self.preview(source_id, path)
            if pv["token"] != token:
                raise CoreError("subtitle-preview-stale", id=source_id)
            by_no = {ln["no"]: ln for ln in pv["lines"]}
            if line_nos is None:
                chosen = [ln for ln in pv["lines"] if ln["status"] in ("importable", "oped")]
            else:
                chosen = []
                for n in sorted(set(int(x) for x in line_nos)):
                    ln = by_no.get(n)
                    if ln is None or ln["status"] not in ("importable", "oped"):
                        raise CoreError("subtitle-line-not-importable", line=n, status=None if ln is None else ln["status"])
                    chosen.append(ln)

            src = self._source(source_id)
            version_id, created = self._ensure_version(source_id, pv)
            line_ids = {
                r[0]: r[1] for r in self.conn.execute("SELECT line_no, id FROM subtitle_line WHERE version_id=?", (version_id,))
            }
            ops: list[dict[str, Any]] = []
            for ln in chosen:
                is_line = ln["kind"] == "line"
                fields: dict[str, Any] = {
                    "source_id": source_id,
                    "kind": ln["kind"],
                    "scope": "role" if is_line else "source",
                    "start": ln["start"],
                    "end": ln["end"],
                    "raw_text": ln["text"],
                    "clean_text": ln["name"],
                    "tags": speaker_tags(ln["speakers"]),
                    "subtitle_version_id": version_id,
                    "subtitle_line_id": line_ids[ln["no"]],
                }
                if is_line:
                    fields["scope_role"] = "vocal"
                    fields["align_text_auto"] = ln["alignText"]
                ops.append({"entity": "annotation", "op": "create", "fields": fields})
            if src["current_subtitle_version_id"] != version_id:
                ops.append(
                    {"entity": "source", "id": source_id, "version": src["version"], "fields": {"current_subtitle_version_id": version_id}}
                )
            changes = ChangeSet()
            edit_id = None
            if ops:
                edit_id, changes = self.edits.apply_within(
                    {"label": {"code": "subtitle-import", "args": {"n": len(chosen), "file": pv["fileName"]}}, "ops": ops}
                )
        if self.on_change and (changes.entities or created):
            changes.add("source", source_id)
            self.on_change(changes)
        return {
            "sourceId": source_id,
            "editId": edit_id,
            "imported": len(chosen),
            "versionId": version_id,
            "newVersion": created,
            "switched": src["current_subtitle_version_id"] != version_id,
            "skipped": {"invalid": pv["counts"]["invalid"], "registered": pv["counts"]["registered"]},
            "invalid": [{"no": ln["no"], "ref": ln["ref"], "reason": ln["reason"]} for ln in pv["lines"] if ln["status"] == "invalid"],
            "problems": pv["problems"],
        }

    def _ensure_version(self, source_id: str, pv: dict[str, Any]) -> tuple[str, bool]:
        row = self.conn.execute(
            "SELECT id FROM subtitle_version WHERE source_id=? AND content_hash=?", (source_id, pv["fingerprint"])
        ).fetchone()
        if row is not None:
            return row[0], False
        vid = new_id()
        rules = {k: settings_mod.values(self.conn)[k] for k in subtitle_rules.KEYS}
        self.conn.execute(
            "INSERT INTO subtitle_version(id, source_id, content_hash, file_name, language, rules_snapshot, imported_at)"
            " VALUES (?, ?, ?, ?, NULL, ?, ?)",
            (vid, source_id, pv["fingerprint"], pv["fileName"], dumps(rules), now_iso()),
        )
        self.conn.executemany(
            'INSERT INTO subtitle_line(id, version_id, line_no, start, "end", raw_text) VALUES (?, ?, ?, ?, ?, ?)',
            [(new_id(), vid, ln["no"], ln["start"], ln["end"], ln["text"]) for ln in pv["lines"]],
        )
        return vid, True

    # ---------- 多原片批量（原片列表勾选 → 批量 ▾ → 导入字幕标记）

    def preview_many(self, source_ids: Iterable[str]) -> list[dict[str, Any]]:
        """每个原片一行摘要；没关联字幕的跳过并说明；读不了的给出错误（不影响其他原片）。"""
        out: list[dict[str, Any]] = []
        for sid in source_ids:
            src = self._source(sid)
            if not src["subtitle_path"]:
                out.append({"sourceId": sid, "skipped": "no-subtitle"})
                continue
            try:
                pv = self.preview(sid)
            except CoreError as e:
                out.append({"sourceId": sid, "error": e.to_wire()})
                continue
            out.append({k: pv[k] for k in ("sourceId", "fileName", "token", "versionState", "counts")} | {"problems": len(pv["problems"])})
        return out

    def import_many(self, items: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
        """逐个原片导入默认勾选的行；每个原片各自原子，一个失败不影响其他（结果里写明）。"""
        out: list[dict[str, Any]] = []
        for it in items:
            try:
                out.append(self.import_(str(it["sourceId"]), str(it["token"])))
            except CoreError as e:
                out.append({"sourceId": it["sourceId"], "error": e.to_wire()})
        return out
