"""采样：截取（新建）、列表、删除（规格 04 §4.2.6–§4.2.7、§4.5、§4.7；16 R7.1–R7.5、R8.9）。

- 显式保存一律新建：同一范围保存两次就是两个采样（R7.1）；新采样直接绑定资产选区，不复制音频、不跑模型（R7.2）。
- 建议名：对齐结果（阶段 4）→ 与选区正长度交叠的文本层的段与音效提示的文字（未删除，原片时间；A23）→ 原片名 起–止。
- 判定区间（所有者 2026-10-09）：没给的 = 选区（数据库触发器按资产映射补上）；从段 / 音效提示建的 = 段 / 提示的区间。
- 性质：调用方显式给的生效；没给就按资产角色预填（R2.6）。
- 删除：采样本身、本地标签、画面覆盖、以它为归属的测量采用；子采样保留“已删除的父采样”来源（parent_label 在创建时就记下）；
  固定结果里的成员保留采样 ID，界面据此显示“已删除”；资产、分析（属于段 + 资产）、文本层、原片、导出文件都不动（P9）。
"""

from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Any

from ottosmasher.domain import naming
from ottosmasher.domain.mapping import EPS, Mapping, check_range
from ottosmasher.store.db import transaction

from . import assets as assets_mod
from . import effective_tags, units
from .clock import new_id, now_iso
from .edits import ChangeSet, dumps, loads
from .errors import CoreError

NATURES = ("speech", "pitched", "unpitched", "unclassified")
CREATED_VIA = ("manual", "segment", "hint", "hit", "processed", "import", "reimport")
SORTS = {
    "created": "s.created_at DESC, s.rowid DESC",
    "name": "s.name COLLATE NOCASE, s.rowid",
    "source": "src.work COLLATE NOCASE, src.episode COLLATE NOCASE, s.start, s.rowid",
    "duration": '(s."end" - s.start), s.rowid',
}


def source_display_name(work: str, episode: str, path: str) -> str:
    """原片名：作品 + 集数；没有就用文件名（不含扩展名）。界面用同一规则。"""
    if work and episode:
        return f"{work} {episode}"
    return work or Path(path).stem


class SampleService:
    def __init__(self, conn: sqlite3.Connection, *, on_change: Any = None) -> None:
        self.conn = conn
        self.on_change = on_change

    # ------------------------------------------------------------ 建议

    def _source_of(self, asset: dict[str, Any]) -> sqlite3.Row:
        return self.conn.execute(
            "SELECT id, path, work, episode, duration FROM source WHERE id=?", (asset["source_id"],)
        ).fetchone()

    def suggest(self, asset_id: str, start: float, end: float, *, local_marker: str = "") -> dict[str, Any]:
        asset = assets_mod.get(self.conn, asset_id)
        start, end = check_range(start, end, asset["duration"], frame=1.0 / assets_mod.rate_of(self.conn, asset))
        src = self._source_of(asset)
        mapping = Mapping.of(asset["mapping"]) if asset["mapping"] else None
        texts: list[str] = []
        if mapping is not None:
            s0, s1 = mapping.to_source(start), mapping.to_source(end)
            # 正长度交叠（端点相接不算，04 §4.3.3）；文本层的段与音效提示的文字（A23：不受角色限制；名称里的换行用空格连接）
            rows = self.conn.execute(
                'SELECT text FROM (SELECT start, "end", text, 0 AS k FROM text_segment WHERE source_id=? AND deleted=0'
                ' UNION ALL SELECT start, "end", text, 1 AS k FROM sfx_hint WHERE source_id=? AND deleted=0)'
                ' WHERE start < ? AND "end" > ? ORDER BY start, "end", k',
                (src["id"], src["id"], s1 - EPS, s0 + EPS),
            ).fetchall()
            texts = [str(r[0]).replace("\n", " ") for r in rows]
        else:
            s0, s1 = start, end
        name = naming.suggest_sample_name(
            source_name=source_display_name(src["work"], src["episode"], src["path"]),
            start=s0,
            end=s1,
            mapped=mapping is not None,
            local_marker=local_marker,
            overlapping_texts=texts,
        )
        return {"name": name, "nature": naming.nature_for_roles(asset["roles"]), "roles": asset["roles"], "start": start, "end": end}

    # ------------------------------------------------------------ 新建

    def create(
        self,
        asset_id: str,
        start: float,
        end: float,
        *,
        name: str,
        nature: str | None = None,
        created_via: str = "manual",
        parent_sample_id: str | None = None,
    ) -> dict[str, Any]:
        with transaction(self.conn):
            sid = self.insert_checked(asset_id, start, end, name=name, nature=nature, created_via=created_via, parent_sample_id=parent_sample_id)
        self._changed("sample", [sid])
        return self.get(sid)

    def insert_checked(
        self, asset_id: str, start: float, end: float, *, name: str, nature: str | None = None, created_via: str = "manual",
        parent_sample_id: str | None = None, origin: dict[str, Any] | None = None, snapshot: dict[str, Any] | None = None,
        judge: tuple[float, float] | None = None,
    ) -> str:
        """校验并新建一个采样，在调用方的写事务里（批量新建整批原子）。判定区间没给 = 选区。"""
        asset = assets_mod.get(self.conn, asset_id)
        start, end = check_range(start, end, asset["duration"], frame=1.0 / assets_mod.rate_of(self.conn, asset))
        name = (name or "").strip()
        if not name:
            raise CoreError("sample-invalid", reason="too-short", field="name")
        if len(name) > 500:
            raise CoreError("sample-invalid", reason="too-long", field="name", max=500)
        if nature is None:
            nature = naming.nature_for_roles(asset["roles"])
        if nature not in NATURES:
            raise CoreError("sample-invalid", reason="not-an-option", field="nature")
        if created_via not in CREATED_VIA:
            raise CoreError("sample-invalid", reason="not-an-option", field="created_via")
        parent_label = None
        if parent_sample_id is not None:
            p = self.conn.execute("SELECT name FROM sample WHERE id=?", (parent_sample_id,)).fetchone()
            if p is None:
                raise CoreError("sample-not-found", id=parent_sample_id)
            parent_label = p[0]
        sid, ts = new_id(), now_iso()
        js, je = (round(judge[0], 6), round(judge[1], 6)) if judge else (None, None)
        self.conn.execute(
            'INSERT INTO sample(id, asset_id, start, "end", name, nature, language, created_via, parent_sample_id, parent_label,'
            " origin, text_snapshot, tag_judge_start, tag_judge_end, created_at, updated_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (sid, asset_id, start, end, name, nature, asset["language"], created_via, parent_sample_id, parent_label,
             dumps(origin) if origin else None, dumps(snapshot) if snapshot else None, js, je, ts, ts),
        )
        effective_tags.refresh(self.conn, [sid])
        return sid

    # ------------------------------------------------------------ 查询

    _COLUMNS = (
        's.id, s.asset_id, s.start, s."end", s.name, s.nature, s.starred, s.rating, s.language, s.created_via,'
        " s.parent_sample_id, s.parent_label, s.created_at, s.version,"
        " a.source_id, a.mapping, a.origin AS asset_origin, a.stream_ordinal,"
        " src.work, src.episode, src.path AS source_path, src.media_state,"
        # 语音分析状态（所有者 2026-10-08：分析属于文本单元，采样按规则读取）：manual / ok / partial（◐）/ failed / none
        f" {units.state_sql('s')} AS analysis"
    )
    _FROM = " FROM sample s JOIN sound_asset a ON a.id = s.asset_id JOIN source src ON src.id = a.source_id"

    def _row(self, r: sqlite3.Row) -> dict[str, Any]:
        d = dict(r)
        mapping = d.pop("mapping")
        try:
            d["source_start"] = Mapping.of(loads(mapping)).to_source(d["start"]) if mapping else None
        except CoreError:
            d["source_start"] = None
        d["duration"] = d["end"] - d["start"]
        d["starred"] = bool(d["starred"])
        d["source_name"] = source_display_name(d["work"], d["episode"], d["source_path"])
        return d

    def get(self, sample_id: str) -> dict[str, Any]:
        r = self.conn.execute(f"SELECT {self._COLUMNS}{self._FROM} WHERE s.id=?", (sample_id,)).fetchone()
        if r is None:
            raise CoreError("sample-not-found", id=sample_id)
        d = self._row(r)
        d["people"] = effective_tags.people(self.conn, [sample_id]).get(sample_id, [])
        d["tags"] = effective_tags.of_sample(self.conn, sample_id)
        return d

    def rows(self, ids: list[str]) -> dict[str, dict[str, Any]]:
        """现有采样的列表行（固定结果翻页用；已删除的不在里面）。"""
        out: dict[str, dict[str, Any]] = {}
        for i in range(0, len(ids), 900):
            part = ids[i : i + 900]
            for r in self.conn.execute(f"SELECT {self._COLUMNS}{self._FROM} WHERE s.id IN ({','.join('?' * len(part))})", part):
                d = self._row(r)
                out[d["id"]] = d
        ppl = effective_tags.people(self.conn, list(out))
        for k, d in out.items():
            d["people"] = ppl.get(k, [])
        return out

    @staticmethod
    def _where(natures: list[str] | None, starred: bool, text: str, source_id: str | None, metrics: dict[str, Any] | None = None) -> tuple[str, list[Any]]:
        where, args = ["1=1"], []
        if metrics:
            # 单音 · 音色 / 瞬态的即时筛选（10 §10.3）：缺少所选指标的不命中
            from ..algo import acoustic as ac
            from .acoustic import filter_sql

            conds = ac.check_conditions(metrics.get("conditions") or [], str(metrics.get("mode")))
            if conds:
                clause, extra = filter_sql(conds)
                where.append(clause)
                args += extra
        if natures:
            if any(n not in NATURES for n in natures):
                raise CoreError("sample-invalid", reason="not-an-option", field="nature")
            where.append(f"s.nature IN ({','.join('?' * len(natures))})")
            args += natures
        if starred:
            where.append("s.starred=1")
        if text.strip():
            where.append("(s.name LIKE ? ESCAPE '\\' OR s.note LIKE ? ESCAPE '\\')")
            needle = "%" + text.strip().replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"
            args += [needle, needle]
        if source_id:
            where.append("a.source_id=?")
            args.append(source_id)
        return " WHERE " + " AND ".join(where), args

    def list(
        self,
        *,
        offset: int = 0,
        limit: int = 100,
        natures: list[str] | None = None,
        starred: bool = False,
        text: str = "",
        source_id: str | None = None,
        sort: str = "created",
        metrics: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """一页摘要（不含分析资料，R8.9）+ 总数。性质多选取并集；星标、文字、原片、单音指标取交集。"""
        cond, args = self._where(natures, starred, text, source_id, metrics)
        order = SORTS.get(sort)
        if order is None:
            raise CoreError("sample-invalid", reason="not-an-option", field="sort")
        total = self.conn.execute(f"SELECT COUNT(*){self._FROM}{cond}", args).fetchone()[0]
        limit = max(1, min(int(limit), 500))
        rows = self.conn.execute(
            f"SELECT {self._COLUMNS}{self._FROM}{cond} ORDER BY {order} LIMIT ? OFFSET ?", [*args, limit, max(0, int(offset))]
        ).fetchall()
        out = [self._row(r) for r in rows]
        ppl = effective_tags.people(self.conn, [r["id"] for r in out])
        for r in out:
            r["people"] = ppl.get(r["id"], [])
        return {"total": total, "offset": offset, "rows": out}

    def ids(self, *, natures: list[str] | None = None, starred: bool = False, text: str = "", source_id: str | None = None,
            metrics: dict[str, Any] | None = None) -> list[str]:
        """“全选全部匹配”（跨页）：返回全部 ID（R8.9）。"""
        cond, args = self._where(natures, starred, text, source_id, metrics)
        return [r[0] for r in self.conn.execute(f"SELECT s.id{self._FROM}{cond} ORDER BY s.created_at DESC, s.rowid DESC", args)]

    # ------------------------------------------------------------ 删除

    def delete(self, ids: list[str]) -> dict[str, Any]:
        ids = list(dict.fromkeys(ids))
        if not ids:
            return {"deleted": 0}
        marks = ",".join("?" * len(ids))
        found = [r[0] for r in self.conn.execute(f"SELECT id FROM sample WHERE id IN ({marks})", ids)]
        if len(found) != len(ids):
            raise CoreError("sample-not-found", id=next(i for i in ids if i not in found))
        active = []
        for jid, affects in self.conn.execute("SELECT id, affects FROM job WHERE status IN ('queued', 'running')"):
            if set(loads(affects).get("sample", []) if affects else []) & set(ids):
                active.append(jid)
        if active:
            raise CoreError("sample-has-active-jobs", jobs=",".join(active))
        with transaction(self.conn):
            x = self.conn.execute
            # 语音分析属于文本单元（所有者 2026-10-08），删采样不删分析（P9）
            x(f"DELETE FROM visual_binding WHERE owner_type='sample' AND owner_id IN ({marks})", ids)
            x(f"DELETE FROM sample WHERE id IN ({marks})", ids)  # 本地标签、有效标签级联；子采样 parent_sample_id 置空，parent_label 保留
        self._changed("sample", ids)
        return {"deleted": len(ids)}

    def _changed(self, entity: str, ids: list[str]) -> None:
        if self.on_change:
            cs = ChangeSet()
            for i in ids:
                cs.add(entity, i)
            self.on_change(cs)

