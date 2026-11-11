"""建采样 = 一个动作（所有者 2026-10-09【基线变更】，docs/history/QUESTIONS.md「原片上的四类对象」D 节）。

来源可以是选区、文本层的段、音效提示、检索命中、分离声部、整段原片，也可以批量；同一套默认规则、一律新建；
单条（动作条上的小面板）和批量（整页表格）是同一个动作，产物完全相同。

- 从段建：选区 = 段区间 ± 字幕采样扩展量（裁到音轨覆盖范围）；默认建在默认人声轨上，也可以选当前查看的轨；
  名称 = 段文本（换行用空格连接）；性质 = 语音；判定区间 = 段区间（裁到选区内）。
- 从音效提示建：单条默认在当前查看的轨上，批量默认在默认音效轨上；选区 = 提示区间 ± 扩展量；名称 = 提示文字（括号内容，多个用“ / ”连接）；
  性质默认非调谐单音；判定区间 = 提示区间。
- 缺默认轨：在弹窗里就地指定，不回退混音（R4.8）。候选状态：pending 待创建 / oped 与 OP/ED 交叠 / out-of-track 在音轨覆盖范围外 / no-name 没有文字。
- 其他来源（选区、命中、分离声部）：性质按资产角色预填（04 §4.2.7）；命名按 A23 用交叠的段与提示文字；判定区间 = 选区。
- 整段原片：原片默认音频流的整轨，名称 = 文件名，性质按该轨的角色。
- 文本快照（用于命名和显示）在建立时记下，之后改段不追改。
时钟：段、提示、判定区间是原片秒；采样的起止是资产局部秒。
"""

from __future__ import annotations

import hashlib
import sqlite3
import unicodedata
from collections.abc import Callable
from pathlib import Path
from typing import Any

from ottosmasher.domain import naming
from ottosmasher.domain.mapping import Mapping, check_range
from ottosmasher.domain.overlap import overlaps
from ottosmasher.store.db import transaction

from . import assets as assets_mod
from . import settings as settings_mod
from .edits import ChangeSet, dumps, loads
from .errors import CoreError

KINDS = ("selection", "segments", "hints", "stem", "whole")
ROLE_OF = {"segments": "vocal", "hints": "sfx"}


class SamplePlanner:
    def __init__(self, conn: sqlite3.Connection, samples: Any, on_change: Callable[[ChangeSet], None] | None = None) -> None:
        self.conn = conn
        self.samples = samples
        self.on_change = on_change

    # ---------- 计划

    def plan(self, src: dict[str, Any]) -> dict[str, Any]:
        kind = src.get("kind")
        if kind not in KINDS:
            raise CoreError("sample-plan-invalid", field="kind")
        if kind == "selection":
            out = self._selection(src)
        elif kind == "stem":
            out = self._stem(src)
        elif kind == "whole":
            out = self._whole(src)
        elif src.get("sourceIds") is not None:
            out = self._ranges_many(kind, src)
        else:
            out = self._ranges(kind, src)
        out["kind"] = kind
        out["token"] = hashlib.sha256(dumps({"src": src, "items": out["items"], "track": out.get("track")}).encode()).hexdigest()[:32]
        return out

    def _roles(self, asset_id: str) -> list[str]:
        return [r[0] for r in self.conn.execute("SELECT role FROM asset_role WHERE asset_id=? AND state='on' ORDER BY role", (asset_id,))]

    def _texts(self, source_id: str, a: float, b: float) -> list[dict[str, Any]]:
        return [
            dict(r) for r in self.conn.execute(
                'SELECT id, text, k FROM (SELECT id, start, "end", text, \'segment\' AS k FROM text_segment WHERE source_id=? AND deleted=0'
                ' UNION ALL SELECT id, start, "end", text, \'hint\' AS k FROM sfx_hint WHERE source_id=? AND deleted=0)'
                ' WHERE start < ? AND "end" > ? ORDER BY start, "end", k',
                (source_id, source_id, b - 1e-9, a + 1e-9),
            )
        ]

    def _item(self, asset: dict[str, Any], start: float, end: float, *, name: str, nature: str, via: str, origin: dict[str, Any] | None,
              judge: tuple[float, float] | None, snapshot: dict[str, Any] | None, status: str = "pending", key: str | None = None) -> dict[str, Any]:
        return {
            "key": key or f"{asset['id']}@{start:.6f}-{end:.6f}", "assetId": asset["id"], "start": start, "end": end,
            "judgeStart": None if judge is None else round(judge[0], 6), "judgeEnd": None if judge is None else round(judge[1], 6),
            "name": name, "nature": nature, "createdVia": via, "origin": origin, "snapshot": snapshot, "status": status,
        }

    def _selection(self, src: dict[str, Any]) -> dict[str, Any]:
        """选区（截取、命中保存、详情区里截取）：命名（局部命名 + A23）、性质按角色、判定区间 = 选区。"""
        asset = assets_mod.get(self.conn, src["assetId"])
        start, end = check_range(float(src["start"]), float(src["end"]), float(asset["duration"]), frame=1.0 / assets_mod.rate_of(self.conn, asset))
        sug = self.samples.suggest(asset["id"], start, end, local_marker=src.get("localMarker") or "")
        via = src.get("via") or "manual"
        if via not in ("manual", "hit"):
            raise CoreError("sample-plan-invalid", field="via")
        m = Mapping.of(asset["mapping"])
        a, b = m.to_source(start), m.to_source(end)
        texts = self._texts(asset["source_id"], a, b)
        snap = {"text": " / ".join(dict.fromkeys(t["text"].replace("\n", " ") for t in texts)), "segments": [t["id"] for t in texts if t["k"] == "segment"],
                "hints": [t["id"] for t in texts if t["k"] == "hint"]} if texts else None
        item = self._item(asset, start, end, name=sug["name"], nature=sug["nature"], via=via, origin={"kind": via} if via == "hit" else None,
                          judge=(a, b), snapshot=snap)
        return {"items": [item], "track": {"assetId": asset["id"], "roles": asset["roles"]}, "missingDefault": None, "pads": None}

    def _stem(self, src: dict[str, Any]) -> dict[str, Any]:
        """分离声部（整条资产）：性质按角色（C2），名称 = 原片名 · 模型 · 声部。"""
        asset = assets_mod.get(self.conn, src["assetId"])
        s = self.conn.execute("SELECT path, work, episode FROM source WHERE id=?", (asset["source_id"],)).fetchone()
        from .samples import source_display_name

        prod = asset["production"] or {}
        parts = [source_display_name(s["work"], s["episode"], s["path"]), str(prod.get("model") or ""), str(asset.get("stem_name") or "")]
        name = " · ".join(p for p in parts if p)[:500]
        m = Mapping.of(asset["mapping"])
        item = self._item(asset, 0.0, float(asset["duration"]), name=name, nature=naming.nature_for_roles(asset["roles"]), via="manual", origin=None,
                          judge=(m.to_source(0.0), m.to_source(float(asset["duration"]))), snapshot=None)
        return {"items": [item], "track": {"assetId": asset["id"], "roles": asset["roles"]}, "missingDefault": None, "pads": None}

    def _whole(self, src: dict[str, Any]) -> dict[str, Any]:
        """整段原片：原片默认音频流的整轨，名称 = 文件名（去扩展名），性质按这条轨的角色。"""
        items = []
        for sid in dict.fromkeys(src.get("sourceIds") or []):
            r = self.conn.execute(
                "SELECT a.id, a.duration, s.path FROM sound_asset a JOIN source s ON s.id=a.source_id"
                " WHERE a.source_id=? AND a.origin='stream' AND a.stream_ordinal=s.default_audio_stream",
                (sid,),
            ).fetchone()
            if r is None:
                p = self.conn.execute("SELECT path FROM source WHERE id=?", (sid,)).fetchone()
                if p is None:
                    raise CoreError("source-not-found", id=sid)
                raise CoreError("source-no-audio", path=p[0])
            asset = assets_mod.get(self.conn, r["id"])
            name = unicodedata.normalize("NFC", Path(r["path"]).stem)[:500] or Path(r["path"]).name
            m = Mapping.of(asset["mapping"])
            items.append(self._item(asset, 0.0, float(r["duration"]), name=name, nature=naming.nature_for_roles(asset["roles"]), via="manual",
                                    origin=None, judge=(m.to_source(0.0), m.to_source(float(r["duration"]))), snapshot=None, key=sid))
        return {"items": items, "track": None, "missingDefault": None, "pads": None}

    def _ranges(self, kind: str, src: dict[str, Any]) -> dict[str, Any]:
        """从段 / 音效提示建（单条或批量）：同一套规则。"""
        source_id = src["sourceId"]
        if self.conn.execute("SELECT 1 FROM source WHERE id=?", (source_id,)).fetchone() is None:
            raise CoreError("source-not-found", id=source_id)
        role = ROLE_OF[kind]
        values = settings_mod.values(self.conn)
        pads = (float(values["subtitle.pad_before"]), float(values["subtitle.pad_after"]))
        track_choice = src.get("track") or "default"
        track_id: str | None
        if track_choice == "current":
            track_id = src.get("assetId")
            if not track_id or self.conn.execute("SELECT 1 FROM sound_asset WHERE id=? AND source_id=?", (track_id, source_id)).fetchone() is None:
                raise CoreError("sample-plan-invalid", field="assetId")
        else:
            r = self.conn.execute("SELECT asset_id FROM default_track WHERE source_id=? AND role=?", (source_id, role)).fetchone()
            track_id = r[0] if r else None
        asset = assets_mod.get(self.conn, track_id) if track_id else None
        m = Mapping.of(asset["mapping"]) if asset else None
        opeds = [(o[0], o[1]) for o in self.conn.execute('SELECT start, "end" FROM oped WHERE source_id=? AND deleted=0', (source_id,))]
        table = "text_segment" if kind == "segments" else "sfx_hint"
        ids = src.get("ids")
        q = f'SELECT id, start, "end", text{", speakers" if kind == "segments" else ""} FROM {table} WHERE source_id=? AND deleted=0'
        args: list[Any] = [source_id]
        if src.get("start") is not None:
            q += ' AND "end" > ?'
            args.append(float(src["start"]))
        if src.get("end") is not None:
            q += " AND start < ?"
            args.append(float(src["end"]))
        rows = self.conn.execute(q + ' ORDER BY start, "end", id', args).fetchall()
        if ids is not None:
            want = list(dict.fromkeys(ids))
            by = {r["id"]: r for r in rows}
            rows = [by[i] for i in want if i in by]
        items = []
        for r in rows:
            text = (r["text"] or "").strip()
            name = text.replace("\n", " ")
            status = "pending"
            sel: tuple[float, float] | None = None
            if not name:
                status = "no-name"
            elif any(overlaps(r["start"], r["end"], a, b) for a, b in opeds):
                status = "oped"
            elif m is not None:
                if not overlaps(r["start"], r["end"], m.source_start, m.source_end):
                    status = "out-of-track"
                else:
                    sel = (max(r["start"] - pads[0], m.source_start, 0.0), min(r["end"] + pads[1], m.source_end))
            if asset is not None and sel is not None:
                la, lb = m.to_local(sel[0]), m.to_local(sel[1])
                judge = (max(r["start"], sel[0]), min(r["end"], sel[1]))
            else:
                la, lb, judge = max(r["start"] - pads[0], 0.0), r["end"] + pads[1], (r["start"], r["end"])
            if kind == "segments":
                snap = {"text": r["text"], "speakers": loads(r["speakers"]), "start": r["start"], "end": r["end"]}
                origin = {"kind": "segment", "segment": r["id"]}
                nature, via = "speech", "segment"
            else:
                snap = {"text": r["text"], "start": r["start"], "end": r["end"]}
                origin = {"kind": "hint", "hint": r["id"]}
                nature, via = "unpitched", "hint"
            fake = asset or {"id": None}
            it = self._item(fake, la, lb, name=name, nature=nature, via=via, origin=origin, judge=judge, snapshot=snap, status=status, key=r["id"])
            it["sourceStart"], it["sourceEnd"] = r["start"], r["end"]
            it["speakers"] = loads(r["speakers"]) if kind == "segments" else []
            items.append(it)
        track = None if asset is None else {"assetId": asset["id"], "roles": asset["roles"]}
        return {"items": items, "track": track, "missingDefault": role if (track_choice != "current" and asset is None) else None, "pads": list(pads)}

    def _ranges_many(self, kind: str, src: dict[str, Any]) -> dict[str, Any]:
        """多个原素材一起建（所有者 2026-11-03）：各用各的默认轨，规则与单个相同；缺默认轨又有内容的不列，记在 missingSources 里。"""
        from .samples import source_display_name

        items: list[dict[str, Any]] = []
        missing: list[str] = []
        pads: list[float] | None = None
        for sid in dict.fromkeys(src["sourceIds"]):
            one = self._ranges(kind, {"sourceId": sid, "track": "default"})
            pads = one["pads"]
            if one["missingDefault"]:
                if one["items"]:
                    missing.append(sid)
                continue
            s = self.conn.execute("SELECT work, episode, path FROM source WHERE id=?", (sid,)).fetchone()
            name = source_display_name(s["work"], s["episode"], s["path"])
            for it in one["items"]:
                it["sourceId"], it["sourceName"] = sid, name
            items.extend(one["items"])
        return {"items": items, "track": None, "missingDefault": None, "pads": pads, "missingSources": missing}

    # ---------- 创建

    def create_selection(self, asset_id: str, start: float, end: float, *, name: str | None = None, nature: str | None = None,
                         via: str = "manual") -> str:
        """单条选区的快捷方式（脚本、agent、测试）：同一个计划、同一套默认规则；名称 / 性质给了就覆盖。"""
        src = {"kind": "selection", "assetId": asset_id, "start": start, "end": end, "via": via}
        pv = self.plan(src)
        key = pv["items"][0]["key"]
        over = {k: v for k, v in (("name", name), ("nature", nature)) if v}
        return self.create(src, pv["token"], [key], {key: over} if over else None)["ids"][0]

    def create(self, src: dict[str, Any], token: str, keys: list[str], overrides: dict[str, dict[str, Any]] | None = None,
               nature: str | None = None) -> dict[str, Any]:
        """按计划原子创建（任何一条失败则这批回滚）。``overrides``：条目 → {name, nature, localTags}；``nature`` 给了就作用于全部。"""
        overrides = overrides or {}
        with transaction(self.conn):
            pv = self.plan(src)
            if pv["token"] != token:
                raise CoreError("sample-plan-stale")
            if pv["missingDefault"]:
                raise CoreError("default-track-missing", role=pv["missingDefault"])
            by = {it["key"]: it for it in pv["items"]}
            created = []
            for k in dict.fromkeys(keys):
                it = by.get(k)
                if it is None or it["status"] != "pending":
                    raise CoreError("sample-plan-not-pending", key=k, status=None if it is None else it["status"])
                o = overrides.get(k) or {}
                judge = (it["judgeStart"], it["judgeEnd"]) if it["judgeStart"] is not None else None
                created.append(self.samples.insert_checked(
                    it["assetId"], it["start"], it["end"], name=o.get("name") or it["name"], nature=nature or o.get("nature") or it["nature"],
                    created_via=it["createdVia"], origin=it["origin"], snapshot=it["snapshot"], judge=judge,
                    local_tags=o.get("localTags"),
                ))
        if self.on_change and created:
            cs = ChangeSet()
            for sid in created:
                cs.add("sample", sid)
            self.on_change(cs)
        return {"created": len(created), "ids": created}
