"""采样：截取（新建）、列表、删除（规格 04 §4.2.6–§4.2.7、§4.5、§4.7；16 R7.1–R7.5、R8.9）。

- 显式保存一律新建：同一范围保存两次就是两个采样（R7.1）；新采样直接绑定资产选区，不复制音频、不跑模型（R7.2）。
- 建议名：对齐结果（阶段 4）→ 与选区正长度交叠的文本层的段与音效提示的文字（未删除，原片时间；A23）→ 原片名 起–止。
- 判定区间（所有者 2026-10-09）：没给的 = 选区（数据库触发器按资产映射补上）；从段 / 音效提示建的 = 段 / 提示的区间。
- 性质：调用方显式给的生效；没给就按资产角色预填（R2.6）。
- 采样之间没有父子关系（所有者 2026-10-12）：只记创建方式；同一原素材上原素材时间交叠的采样是“相关采样”（跨所有音轨），
  声音怎么做出来的看音轨的加工链（core/lineage.py）。
- 删除：采样本身、本地标签、画面覆盖、以它为归属的测量采用；固定结果里的成员保留采样 ID，界面据此显示“已删除”；
  交叠的采样、资产、音素（属于原素材时间线）、文本层、原片、导出文件都不动（P9）。
"""

from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Any

from ottosmasher.domain import naming
from ottosmasher.domain.mapping import EPS, Mapping, check_range
from ottosmasher.store.db import transaction

from . import assets as assets_mod
from . import effective_tags, lineage, sample_filter, units
from .clock import new_id, now_iso
from .edits import ChangeSet, dumps, loads
from .errors import CoreError

NATURES = sample_filter.NATURES
CREATED_VIA = ("manual", "segment", "hint", "hit", "processed", "import", "reimport")
SORTS = {
    "created": "s.created_at DESC, s.rowid DESC",
    "name": "s.name COLLATE NOCASE, s.rowid",
    "source": "src.work COLLATE NOCASE, src.episode COLLATE NOCASE, s.src_start, s.rowid",
    "duration": '(s."end" - s.start), s.rowid',
}


def source_display_name(work: str, episode: str, path: str) -> str:
    """原素材名：作品 + 素材标识；没有作品就用素材标识（默认就是文件名），再没有用文件名（不含扩展名）。界面用同一规则。"""
    if work and episode:
        return f"{work} {episode}"
    return work or episode or Path(path).stem


class SampleService:
    def __init__(self, conn: sqlite3.Connection, *, on_change: Any = None, reader: Any = None) -> None:
        self.conn = conn
        self.on_change = on_change
        self.reader = reader  # 文字搜索的读音（text_search.Reader）；没有 = 只按名称、备注与段原文
        self._memo: dict[Any, Any] = {}  # 一次查询里「返回原素材」的整轨（lineage.back_track）按资产记住

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
        partial = None
        if mapping is not None:
            s0, s1 = mapping.to_source(start), mapping.to_source(end)
            # 正长度交叠（端点相接不算，04 §4.3.3）；文本层的段与音效提示的文字（A23：不受角色限制；名称里的换行用空格连接）
            rows = self.conn.execute(
                'SELECT id, text, k FROM (SELECT id, start, "end", text, 0 AS k FROM text_segment WHERE source_id=? AND deleted=0'
                ' UNION ALL SELECT id, start, "end", text, 1 AS k FROM sfx_hint WHERE source_id=? AND deleted=0)'
                ' WHERE start < ? AND "end" > ? ORDER BY start, "end", k',
                (src["id"], src["id"], s1 - EPS, s0 + EPS),
            ).fetchall()
            texts = [str(r[1]).replace("\n", " ") for r in rows]
            if rows and all(r["k"] == 0 for r in rows) and units.voiced(asset):
                partial = self._partial_name([r["id"] for r in rows], units.base_of(asset), s0, s1)
        else:
            s0, s1 = start, end
        if partial:
            return {"name": partial, "nature": naming.nature_for_roles(asset["roles"]), "roles": asset["roles"], "start": start, "end": end}
        name = naming.suggest_sample_name(
            source_name=source_display_name(src["work"], src["episode"], src["path"]),
            start=s0,
            end=s1,
            mapped=mapping is not None,
            local_marker=local_marker,
            overlapping_texts=texts,
        )
        return {"name": name, "nature": naming.nature_for_roles(asset["roles"]), "roles": asset["roles"], "start": start, "end": end}

    def _partial_name(self, segment_ids: list[str], base: str, s0: float, s1: float) -> str | None:
        """局部命名（所有者 2026-10-12）：选区只碰到台词段（没碰到音效提示）、而且没有把每一句都完整盖住 →
        “选中部分（这几句，多句用 / 连接）”；完整盖住的句子在选中部分里写整句原文。任何一句还没有可用的音素就不用（照旧写整句）。
        音素与选区都是原素材秒。"""
        frags: list[str] = []
        texts: list[str] = []
        whole = True
        for sid in segment_ids:
            seg = self.conn.execute('SELECT id, start, "end", text FROM text_segment WHERE id=?', (sid,)).fetchone()
            uid = units.unit_id(sid, base)
            runs = self.conn.execute(
                "SELECT * FROM measure_run WHERE owner_type=? AND owner_id=? AND kind='alignment' ORDER BY created_at DESC, rowid DESC", (units.OWNER, uid)
            ).fetchall()
            head = self.conn.execute("SELECT run_id FROM measure_head WHERE owner_type=? AND owner_id=? AND kind='alignment'", (units.OWNER, uid)).fetchone()
            use = units.pick_usable(runs, seg, head[0] if head else None) if seg is not None else None
            if use is None:
                return None
            res = loads(use["result"]) or {}
            text = " ".join(str(seg["text"] or "").split())
            texts.append(text)
            got = naming.partial_fragment(res.get("phones") or [], res.get("words") or [], res.get("morae") or [], s0, s1)
            if got is None:
                continue  # 这句一个音都没选中（只碰到它前后的空白）：不算没盖住
            frag, full = got
            whole = whole and full
            frags.append(text if full else frag)
        frag = "".join(frags).strip()
        if whole or not frag:
            return None
        return naming.partial_name(frag, " / ".join(dict.fromkeys(texts)))

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
    ) -> dict[str, Any]:
        with transaction(self.conn):
            sid = self.insert_checked(asset_id, start, end, name=name, nature=nature, created_via=created_via)
        self._changed("sample", [sid])
        return self.get(sid)

    def insert_checked(
        self, asset_id: str, start: float, end: float, *, name: str, nature: str | None = None, created_via: str = "manual",
        origin: dict[str, Any] | None = None, snapshot: dict[str, Any] | None = None,
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
        sid, ts = new_id(), now_iso()
        js, je = (round(judge[0], 6), round(judge[1], 6)) if judge else (None, None)
        self.conn.execute(
            'INSERT INTO sample(id, asset_id, start, "end", name, nature, language, created_via,'
            " origin, text_snapshot, tag_judge_start, tag_judge_end, created_at, updated_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (sid, asset_id, start, end, name, nature, asset["language"], created_via,
             dumps(origin) if origin else None, dumps(snapshot) if snapshot else None, js, je, ts, ts),
        )
        effective_tags.refresh(self.conn, [sid])
        return sid

    # ------------------------------------------------------------ 查询

    _COLUMNS = (
        's.id, s.asset_id, s.start, s."end", s.name, s.nature, s.starred, s.rating, s.language, s.created_via,'
        " s.src_start AS source_start, s.src_end AS source_end, s.created_at, s.version, s.independent,"
        " a.source_id, a.mapping, a.origin AS asset_origin, a.stream_ordinal,"
        " src.work, src.episode, src.path AS source_path, src.media_state,"
        # 语音分析状态（所有者 2026-10-08：分析属于文本单元，采样按规则读取）：manual / ok / partial（◐）/ failed / none
        f" {units.state_sql('s', 'a')} AS analysis"
    )
    _FROM = " FROM sample s JOIN sound_asset a ON a.id = s.asset_id JOIN source src ON src.id = a.source_id"

    def _row(self, r: sqlite3.Row) -> dict[str, Any]:
        return self._row_dict(dict(r))

    def _row_dict(self, d: dict[str, Any]) -> dict[str, Any]:
        d.pop("mapping")
        d["back_asset_id"] = lineage.back_track(self.conn, d["asset_id"], self._memo)
        d["duration"] = d["end"] - d["start"]
        d["starred"] = bool(d["starred"])
        d["independent"] = bool(d["independent"])
        d["source_name"] = source_display_name(d["work"], d["episode"], d["source_path"])
        return d

    def get(self, sample_id: str) -> dict[str, Any]:
        self._memo = {}
        r = self.conn.execute(f"SELECT {self._COLUMNS}{self._FROM} WHERE s.id=?", (sample_id,)).fetchone()
        if r is None:
            raise CoreError("sample-not-found", id=sample_id)
        d = self._row(r)
        d["people"] = effective_tags.people(self.conn, [sample_id]).get(sample_id, [])
        d["tags"] = effective_tags.of_sample(self.conn, sample_id)
        d["detail"] = self.detail(sample_id)
        return d

    def detail(self, sample_id: str) -> dict[str, Any]:
        """详情区「资料与来源」（UI_PLAN §3）：备注、建立方式、加工链、技术详情。"""
        r = self.conn.execute(
            "SELECT s.note, s.asset_id, s.origin, s.independent, s.tag_judge_start, s.tag_judge_end, s.updated_at, a.stem_name"
            " FROM sample s JOIN sound_asset a ON a.id = s.asset_id WHERE s.id = ?",
            (sample_id,),
        ).fetchone()
        return {
            "note": r["note"],
            "origin": loads(r["origin"]) if r["origin"] else None,
            "independent": bool(r["independent"]),
            "judge": [r["tag_judge_start"], r["tag_judge_end"]] if r["tag_judge_start"] is not None else None,
            "stemName": r["stem_name"],
            "updatedAt": r["updated_at"],
            "chain": lineage.chain(self.conn, r["asset_id"]),
        }

    def related(self, sample_id: str, limit: int = 12) -> dict[str, Any]:
        """相关采样（所有者 2026-10-12）：同一原素材上、原素材时间正长度交叠（端点相接不算）的其他采样，跨所有音轨；
        按交叠长度从长到短，最多 ``limit`` 个 + 总数。"""
        self._memo = {}
        s = self.conn.execute(
            "SELECT s.src_start, s.src_end, a.source_id FROM sample s JOIN sound_asset a ON a.id = s.asset_id WHERE s.id=?", (sample_id,)
        ).fetchone()
        if s is None:
            raise CoreError("sample-not-found", id=sample_id)
        lo, hi = float(s["src_start"]), float(s["src_end"])
        cond = (" WHERE a.source_id = ? AND s.id <> ? AND s.src_start < ? - 1e-6 AND s.src_end > ? + 1e-6")
        args = [s["source_id"], sample_id, hi, lo]
        total = self.conn.execute(f"SELECT COUNT(*){self._FROM}{cond}", args).fetchone()[0]
        limit = max(1, min(int(limit), 200))
        rows = self.conn.execute(
            f"SELECT {self._COLUMNS}, (MIN(s.src_end, ?) - MAX(s.src_start, ?)) AS ov, a.stem_name, a.production{self._FROM}{cond}"
            " ORDER BY ov DESC, s.src_start, s.rowid LIMIT ?",
            [hi, lo, *args, limit],
        ).fetchall()
        out = []
        for r in rows:
            d = dict(r)
            ov, stem, prod = d.pop("ov"), d.pop("stem_name"), d.pop("production")
            out.append({"sample": self._row_dict(d), "overlap": round(float(ov), 6), "stemName": stem,
                        "model": (loads(prod) or {}).get("model") if prod else None})
        ppl = effective_tags.people(self.conn, [x["sample"]["id"] for x in out])
        for x in out:
            x["sample"]["people"] = ppl.get(x["sample"]["id"], [])
        return {"total": int(total), "rows": out}

    def rows(self, ids: list[str]) -> dict[str, dict[str, Any]]:
        """现有采样的列表行（固定结果翻页用；已删除的不在里面）。"""
        self._memo = {}
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

    def _where(self, f: dict[str, Any]) -> tuple[str, list[Any]]:
        return sample_filter.where(self.conn, f, self.reader)

    def list(self, *, offset: int = 0, limit: int = 100, sort: str = "created", **f: Any) -> dict[str, Any]:
        """一页摘要（不含分析资料，R8.9）+ 总数。条件见 ``sample_filter``：性质多选取并集，其余取交集。"""
        self._memo = {}
        cond, args = self._where(f)
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

    def rows(self, ids: list[str]) -> list[dict[str, Any]]:
        """这些采样的列表摘要（与 ``list`` 的行相同）：浏览列表就地更新状态用（P8：不插入、不重排）。找不到的（已删除）不返回。"""
        self._memo = {}
        ids = list(dict.fromkeys(ids))[:500]
        if not ids:
            return []
        marks = ",".join("?" * len(ids))
        out = [self._row(r) for r in self.conn.execute(f"SELECT {self._COLUMNS}{self._FROM} WHERE s.id IN ({marks})", ids)]
        ppl = effective_tags.people(self.conn, [r["id"] for r in out])
        for r in out:
            r["people"] = ppl.get(r["id"], [])
        return out

    def ids(self, **f: Any) -> list[str]:
        """“全选全部匹配”（跨页）与检索范围：返回全部 ID（R8.9），与页偏移无关。"""
        cond, args = self._where(f)
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
            x(f"DELETE FROM sample WHERE id IN ({marks})", ids)  # 本地标签、有效标签级联
        self._changed("sample", ids)
        return {"deleted": len(ids)}

    def _changed(self, entity: str, ids: list[str]) -> None:
        if self.on_change:
            cs = ChangeSet()
            for i in ids:
                cs.add(entity, i)
            self.on_change(cs)

