"""字幕导入 = 一次显式操作，四类一起进（所有者 2026-10-09【基线变更】，docs/QUESTIONS.md「原片上的四类对象」B 节）。

- 台词行 → 文本层的段；音效行 → 音效提示；说话人 → 段的属性；♪～ / ～♪ → OP/ED 区间。不建采样、不触发分析。
- 预览分四类（各自可关，默认全开），逐行给出状态：
  - ``new`` 新增（与已有对象没有正长度交叠）；``unchanged`` 无变化（区间到毫秒且文本相同）；
  - ``replace`` 替换（只与未受保护的导入对象交叠，且全局选项是“替换”——所有者定的默认）；
  - ``skip`` 跳过（碰到受保护对象 → ``protected``，哪怕只碰到一点；或全局选项是“保留原有” → ``keep``）；用户可以逐行强制替换；
  - ``excluded`` 不勾 / 这一类关掉；``invalid`` 无效范围或没有文字。
  匹配按类分开；先找“无变化”，再对剩下的已有对象算替换 / 跳过；不勾的行不替换任何东西。
- 受保护：段被用户改过或在任一条轨上有人工音素版本；音效提示被改过或手动新增；OP/ED 人工标记 / 确认或改过边界。
- OP/ED：规则无错 → 配对结果随导入登记（来源“字幕规则”）；有错 → 只登记用户在弹窗里逐对确认的（来源“人工确认”）。
- 整次导入一个编辑批次：原子提交、可撤销（整批撤销）。被替换的对象软删除（它们的分析随之不可达，撤销后恢复）。
- 取消字幕版本：文本层不分版本，重新导入就是一次批量编辑；来源记录（文件名、指纹、行号、原文、导入时间）存在段上。
"""

from __future__ import annotations

import hashlib
import sqlite3
from collections.abc import Callable, Iterable
from pathlib import Path
from typing import Any

from ottosmasher.domain import oped_rule, subtitle_rules, subtitles
from ottosmasher.domain.overlap import overlaps
from ottosmasher.store.db import transaction

from . import settings as settings_mod
from .clock import now_iso
from .edits import ChangeSet, EditService, dumps
from .errors import CoreError
from .text_layer import MANUAL_SQL, USED_BY_SQL

DURATION_EPS = 1e-6
SAME_EPS = 5e-4  # “区间到毫秒相同”
DEFAULTS: dict[str, Any] = {"segments": True, "hints": True, "speakers": True, "oped": True, "replace": True}


def _options(options: dict[str, Any] | None) -> dict[str, Any]:
    o = dict(DEFAULTS)
    o.update({k: v for k, v in (options or {}).items() if v is not None})
    o["exclude"] = {int(x) for x in o.get("exclude") or []}
    o["force"] = {int(x) for x in o.get("force") or []}
    o["opedForce"] = {int(x) for x in o.get("opedForce") or []}
    o["opedConfirm"] = {int(c["index"]): c["kind"] for c in o.get("opedConfirm") or [] if c.get("kind") in ("OP", "ED")}
    return o


class SubtitleImporter:
    def __init__(self, conn: sqlite3.Connection, edits: EditService, on_change: Callable[[ChangeSet], None] | None = None) -> None:
        self.conn = conn
        self.edits = edits
        self.on_change = on_change

    def _source(self, source_id: str) -> sqlite3.Row:
        row = self.conn.execute(
            "SELECT id, path, duration, subtitle_path, default_audio_stream, version FROM source WHERE id=?", (source_id,)
        ).fetchone()
        if row is None:
            raise CoreError("source-not-found", id=source_id)
        return row

    # ---------- 已有对象

    def _existing(self, source_id: str) -> dict[str, list[dict[str, Any]]]:
        segs = [
            dict(r) | {"protected": bool(r["edited"] or r["manual"]), "analyzed": bool(r["analyzed"])}
            for r in self.conn.execute(
                f'SELECT t.id, t.version, t.start, t."end", t.text, t.edited, {MANUAL_SQL.format(t="t")} AS manual, {USED_BY_SQL.format(t="t")} AS used_by,'
                " EXISTS (SELECT 1 FROM measure_run r WHERE r.owner_type = 'asset_text' AND r.kind = 'alignment' AND r.status = 'ok'"
                "   AND r.owner_id >= 'seg:' || t.id || '@' AND r.owner_id < 'seg:' || t.id || 'A') AS analyzed"
                " FROM text_segment t WHERE t.source_id=? AND t.deleted=0 ORDER BY t.start, t.\"end\", t.id",
                (source_id,),
            )
        ]
        hints = [
            dict(r) | {"protected": bool(r["edited"]) or r["origin"] == "manual", "analyzed": False, "manual": 0, "used_by": 0}
            for r in self.conn.execute('SELECT id, version, start, "end", text, edited, origin FROM sfx_hint WHERE source_id=? AND deleted=0 ORDER BY start, id', (source_id,))
        ]
        opeds = [
            dict(r) | {"protected": bool(r["edited"]) or r["origin"] == "manual", "analyzed": False, "manual": 0, "used_by": 0, "text": r["kind"]}
            for r in self.conn.execute('SELECT id, version, kind, start, "end", origin, edited FROM oped WHERE source_id=? AND deleted=0 ORDER BY start, id', (source_id,))
        ]
        return {"segments": segs, "hints": hints, "oped": opeds}

    @staticmethod
    def _conflict(e: dict[str, Any]) -> dict[str, Any]:
        return {
            "id": e["id"], "start": e["start"], "end": e["end"], "text": e["text"], "protected": e["protected"],
            "edited": bool(e.get("edited")), "manual": bool(e.get("manual")), "analyzed": e["analyzed"], "usedBy": int(e.get("used_by") or 0),
        }

    @staticmethod
    def _match(rows: list[dict[str, Any]], existing: list[dict[str, Any]], o: dict[str, Any], force: set[int], key: str = "no") -> set[str]:
        """按类匹配：先认领“无变化”，再对剩下的已有对象算替换 / 跳过。返回要删除的已有对象。"""
        claimed: set[str] = set()
        for r in rows:
            if r["status"] != "pending":
                continue
            same = next(
                (e for e in existing if e["id"] not in claimed and abs(e["start"] - r["start"]) < SAME_EPS and abs(e["end"] - r["end"]) < SAME_EPS
                 and e["text"] == r["text"]),
                None,
            )
            if same is not None:
                claimed.add(same["id"])
                r["status"], r["same"] = "unchanged", same["id"]
        doomed: set[str] = set()
        for r in rows:
            if r["status"] != "pending":
                continue
            ov = [e for e in existing if e["id"] not in claimed and overlaps(r["start"], r["end"], e["start"], e["end"])]
            r["conflicts"] = [SubtitleImporter._conflict(e) for e in ov]
            if not ov:
                r["status"] = "new"
                continue
            forced = r[key] in force
            if any(e["protected"] for e in ov) and not forced:
                r["status"], r["reason"] = "skip", "protected"
            elif not o["replace"] and not forced:
                r["status"], r["reason"] = "skip", "keep"
            else:
                r["status"], r["forced"] = "replace", forced
                doomed |= {e["id"] for e in ov}
        return doomed

    # ---------- 预览

    def preview(self, source_id: str, path: str | None = None, options: dict[str, Any] | None = None) -> dict[str, Any]:
        o = _options(options)
        src = self._source(source_id)
        sub_path = path or src["subtitle_path"]
        if not sub_path:
            raise CoreError("subtitle-not-associated", id=source_id)
        parsed = subtitles.read(sub_path)
        values = settings_mod.values(self.conn)
        rules = subtitle_rules.SubtitleRules.build(values)
        duration = float(src["duration"] or 0.0)
        existing = self._existing(source_id)

        seg_rows: list[dict[str, Any]] = []
        hint_rows: list[dict[str, Any]] = []
        for cue in parsed.cues:
            c = subtitle_rules.classify(cue.text, rules)
            is_line = c.kind == "line"
            row: dict[str, Any] = {
                "no": cue.order, "ref": cue.ref, "start": cue.start, "end": cue.end, "raw": cue.text,
                "text": c.align_text if is_line else c.name, "speakers": list(c.speakers) if is_line else [],
                "status": "pending", "reason": None, "conflicts": [], "forced": False,
            }
            reason = None
            if cue.start < 0:
                reason = "negative-start"
            elif not cue.end > cue.start:
                reason = "empty"
            elif cue.end > duration + DURATION_EPS:
                reason = "beyond-end"
            elif not row["text"].strip():
                reason = "no-text"
            if reason is not None:
                row["status"], row["reason"] = "invalid", reason
            elif not o["segments" if is_line else "hints"]:
                row["status"], row["reason"] = "excluded", "category-off"
            elif cue.order in o["exclude"]:
                row["status"], row["reason"] = "excluded", "unchecked"
            (seg_rows if is_line else hint_rows).append(row)
        doomed_segs = self._match(seg_rows, existing["segments"], o, o["force"])
        doomed_hints = self._match(hint_rows, existing["hints"], o, o["force"])

        # OP/ED：规则配对（读同一个字幕文件）；有错时只处理用户逐对确认的
        res = oped_rule.identify(parsed.cues, duration, values["subtitle.oped_start"], values["subtitle.oped_end"])
        pair_rows: list[dict[str, Any]] = []
        for i, p in enumerate(res.pairs):
            kind = o["opedConfirm"].get(i, p.suggest)
            row = {"index": i, "start": p.start, "end": p.end, "suggest": p.suggest, "kind": kind, "refs": [p.start_ref, p.end_ref],
                   "text": kind, "status": "pending", "reason": None, "conflicts": [], "forced": False}
            if not o["oped"]:
                row["status"], row["reason"] = "excluded", "category-off"
            elif res.errors and i not in o["opedConfirm"]:
                row["status"], row["reason"] = "excluded", "needs-confirm"
            pair_rows.append(row)
        doomed_oped = self._match(pair_rows, existing["oped"], o, o["opedForce"], key="index")

        def summary(rows: list[dict[str, Any]], doomed: set[str], ex: list[dict[str, Any]]) -> dict[str, Any]:
            c = {k: 0 for k in ("new", "unchanged", "replace", "skip", "excluded", "invalid")}
            for r in rows:
                c[r["status"]] += 1
            gone = [e for e in ex if e["id"] in doomed]
            c["removed"] = len(gone)
            c["removedAnalyzed"] = sum(1 for e in gone if e["analyzed"])
            c["removedProtected"] = sum(1 for e in gone if e["protected"])
            return c

        token = self._token(src, parsed.fingerprint, rules, values, existing)
        speakers: dict[str, int] = {}
        for r in seg_rows:
            if r["status"] in ("new", "replace"):
                for n in r["speakers"]:
                    speakers[n] = speakers.get(n, 0) + 1
        return {
            "sourceId": source_id,
            "path": str(sub_path),
            "fileName": Path(sub_path).name,
            "format": parsed.format,
            "fingerprint": parsed.fingerprint,
            "token": token,
            "options": {k: o[k] for k in DEFAULTS},
            "segments": seg_rows,
            "hints": hint_rows,
            "speakers": [{"name": n, "count": k} for n, k in sorted(speakers.items(), key=lambda x: (-x[1], x[0]))],
            "oped": {"pairs": pair_rows, "errors": list(res.errors)},
            "counts": {
                "segments": summary(seg_rows, doomed_segs, existing["segments"]),
                "hints": summary(hint_rows, doomed_hints, existing["hints"]),
                "oped": summary(pair_rows, doomed_oped, existing["oped"]),
            },
            "removed": {
                "segments": [self._conflict(e) for e in existing["segments"] if e["id"] in doomed_segs],
                "hints": [self._conflict(e) for e in existing["hints"] if e["id"] in doomed_hints],
                "oped": [self._conflict(e) for e in existing["oped"] if e["id"] in doomed_oped],
            },
            "problems": parsed.problems,
        }

    @staticmethod
    def _token(src: sqlite3.Row, fingerprint: str, rules: subtitle_rules.SubtitleRules, values: dict[str, Any], existing: dict[str, list[dict[str, Any]]]) -> str:
        basis = {
            "fp": fingerprint,
            "source": [src["version"], src["duration"], src["default_audio_stream"], src["subtitle_path"]],
            "rules": dict(rules.patterns),
            "markers": [values["subtitle.oped_start"], values["subtitle.oped_end"]],
            "existing": {k: [[e["id"], e["version"], bool(e["protected"])] for e in v] for k, v in existing.items()},
        }
        return hashlib.sha256(dumps(basis).encode()).hexdigest()[:32]

    # ---------- 导入

    def import_(self, source_id: str, token: str, options: dict[str, Any] | None = None, path: str | None = None) -> dict[str, Any]:
        o = _options(options)
        with transaction(self.conn):
            pv = self.preview(source_id, path, options)
            if pv["token"] != token:
                raise CoreError("subtitle-preview-stale", id=source_id)
            ts = now_iso()
            prov_base = {"file": pv["fileName"], "fingerprint": pv["fingerprint"], "importedAt": ts}
            ops: list[dict[str, Any]] = []
            existing = self._existing(source_id)
            ver = {k: {e["id"]: e["version"] for e in v} for k, v in existing.items()}
            for e in pv["removed"]["segments"]:
                ops.append({"entity": "segment", "id": e["id"], "version": ver["segments"][e["id"]], "fields": {"deleted": True}})
            for e in pv["removed"]["hints"]:
                ops.append({"entity": "sfx_hint", "id": e["id"], "version": ver["hints"][e["id"]], "fields": {"deleted": True}})
            for e in pv["removed"]["oped"]:
                ops.append({"entity": "oped", "id": e["id"], "version": ver["oped"][e["id"]], "fields": {"deleted": True}})
            created = {"segments": 0, "hints": 0, "oped": 0}
            for r in pv["segments"]:
                if r["status"] in ("new", "replace"):
                    ops.append({"entity": "segment", "op": "create", "fields": {
                        "source_id": source_id, "start": r["start"], "end": r["end"], "text": r["text"],
                        "speakers": r["speakers"] if o["speakers"] else [], "origin": "subtitle",
                        "provenance": prov_base | {"line": r["no"], "ref": r["ref"], "raw": r["raw"]}}})
                    created["segments"] += 1
            for r in pv["hints"]:
                if r["status"] in ("new", "replace"):
                    ops.append({"entity": "sfx_hint", "op": "create", "fields": {
                        "source_id": source_id, "start": r["start"], "end": r["end"], "text": r["text"], "origin": "subtitle",
                        "provenance": prov_base | {"line": r["no"], "ref": r["ref"], "raw": r["raw"]}}})
                    created["hints"] += 1
            errors = bool(pv["oped"]["errors"])
            for r in pv["oped"]["pairs"]:
                if r["status"] in ("new", "replace"):
                    evidence: dict[str, Any] = {"refs": r["refs"], "file": pv["fingerprint"][:16]}
                    if errors:
                        evidence["via"] = "confirm"
                    ops.append({"entity": "oped", "op": "create", "fields": {
                        "source_id": source_id, "kind": r["kind"], "start": r["start"], "end": r["end"],
                        "origin": "manual" if errors else "subtitle_rule", "evidence": evidence}})
                    created["oped"] += 1
            edit_id = None
            changes = ChangeSet()
            if ops:
                edit_id, changes = self.edits.apply_within(
                    {"label": {"code": "subtitle-import", "args": {"n": created["segments"] + created["hints"], "file": pv["fileName"]}}, "ops": ops}
                )
        if self.on_change and changes.entities:
            changes.add("source", source_id)
            self.on_change(changes)
        return {
            "sourceId": source_id,
            "editId": edit_id,
            "created": created,
            "counts": pv["counts"],
            "invalid": [{"no": r["no"], "ref": r["ref"], "reason": r["reason"]} for r in pv["segments"] + pv["hints"] if r["status"] == "invalid"],
            "opedErrors": len(pv["oped"]["errors"]),
            "problems": pv["problems"],
        }

    def import_default(self, source_id: str) -> dict[str, Any]:
        """一键「导入到文本层」：按默认选项直接导入（OP/ED 有错时不登记，结果里报告）。"""
        pv = self.preview(source_id)
        return self.import_(source_id, pv["token"])

    # ---------- 多原片批量（原片列表勾选 → 批量 ▾ → 导入字幕）

    def preview_many(self, source_ids: Iterable[str]) -> list[dict[str, Any]]:
        """每个原片一行摘要（默认选项）；没关联字幕的跳过并说明；读不了的给出错误（不影响其他原片）。"""
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
            out.append({k: pv[k] for k in ("sourceId", "fileName", "token", "counts")} | {"problems": len(pv["problems"]), "opedErrors": len(pv["oped"]["errors"])})
        return out

    def import_many(self, items: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
        """逐个原片按默认选项导入；每个原片各自原子，一个失败不影响其他（结果里写明）。"""
        out: list[dict[str, Any]] = []
        for it in items:
            try:
                out.append(self.import_(str(it["sourceId"]), str(it["token"])))
            except CoreError as e:
                out.append({"sourceId": it["sourceId"], "error": e.to_wire()})
        return out
