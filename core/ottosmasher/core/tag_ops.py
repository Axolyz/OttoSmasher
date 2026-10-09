"""标签与资料的批量操作（规格 07 §7.4–§7.6、16 R8.5、R9；所有者 2026-10-09 的四类对象：说话人是段的属性，L33）。

全部只是**生成编辑批次**：预览不写库，界面把预览得到的批次（带对象版本）原样交给 ``edits.apply``——期间别处改过的对象版本不符，整批拒绝（R9.1）；
一次一个编辑记录，可撤销。

- 批量编辑资料（「编辑资料…」「添加标签…」「移除标签…」）：名称、性质、星标、评分、本地标签 + / −；没变化的采样不进批次。
- 所选采样的标签：每个标签“本地 n / 继承 m”（按采样计，同一采样多条继承路径只算一次），继承的给来源（区段标签 / 段 / 原片 / 资产）。
- 管理标签：全部在用的标签与计数；**全局改名 / 全局移除**作用于带该本地标签的采样、带该标签的区段标签、作品 / 类型匹配的原片、
  以及人物标签对应的**段的说话人**（改名 / 移除说话人，自动记“说话人改过”）。不允许全局添加。
  原片文件夹里的原片作品跟文件夹走（阶段 3.13）：这些原片不改，预览里单独列出数量，提示用「作品设置…」改文件夹名。
  ``speaker-status:多人未分段`` 由段的多人说话人派生，不能全局移除（预览里列出“改不了的继承”数量）。
"""

from __future__ import annotations

import sqlite3
from typing import Any

from .edits import EditService, facet_of, loads
from .errors import CoreError

PERSON = ("character:", "participants:")
DERIVED = "speaker-status:"
_CHUNK = 900


def _chunks(ids: list[str]) -> list[list[str]]:
    return [ids[i : i + _CHUNK] for i in range(0, len(ids), _CHUNK)]


def _check_tag(tag: Any, field: str = "tag") -> str:
    if not isinstance(tag, str) or not tag.strip():
        raise CoreError("sample-invalid", reason="too-short", field=field)
    tag = tag.strip()
    if len(tag) > 500:
        raise CoreError("sample-invalid", reason="too-long", field=field, max=500)
    return tag


class TagOps:
    def __init__(self, conn: sqlite3.Connection, edits: EditService) -> None:
        self.conn = conn
        self.edits = edits

    # ------------------------------------------------------------ 所选采样

    def _rows(self, ids: list[str]) -> list[sqlite3.Row]:
        out: list[sqlite3.Row] = []
        for part in _chunks(list(dict.fromkeys(ids))):
            out += self.conn.execute(
                f"SELECT id, name, nature, starred, rating, version FROM sample WHERE id IN ({','.join('?' * len(part))})", part
            ).fetchall()
        if len(out) != len(set(ids)):
            found = {r["id"] for r in out}
            raise CoreError("sample-not-found", id=next(i for i in ids if i not in found))
        order = {k: n for n, k in enumerate(dict.fromkeys(ids))}
        return sorted(out, key=lambda r: order[r["id"]])

    def _local(self, ids: list[str]) -> dict[str, list[str]]:
        out: dict[str, list[str]] = {i: [] for i in ids}
        for part in _chunks(ids):
            for sid, tag in self.conn.execute(f"SELECT sample_id, tag FROM sample_tag WHERE sample_id IN ({','.join('?' * len(part))}) ORDER BY rowid", part):
                out[sid].append(tag)
        return out

    def of_samples(self, ids: list[str]) -> list[dict[str, Any]]:
        """所选采样的标签：本地 n / 继承 m（按采样计）+ 继承来源（最多 5 个）。"""
        acc: dict[str, dict[str, Any]] = {}
        for part in _chunks(list(dict.fromkeys(ids))):
            for sid, tag, facet, prov, ref in self.conn.execute(
                f"SELECT sample_id, tag, facet, provenance, provenance_ref FROM sample_effective_tag WHERE sample_id IN ({','.join('?' * len(part))})",
                part,
            ):
                a = acc.setdefault(tag, {"tag": tag, "facet": facet, "local": set(), "inherited": set(), "sources": {}})
                if prov == "local":
                    a["local"].add(sid)
                else:
                    a["inherited"].add(sid)
                    if ref and len(a["sources"]) < 5:
                        a["sources"].setdefault((prov, ref), None)
        out = []
        for a in sorted(acc.values(), key=lambda x: (x["facet"], x["tag"])):
            out.append({
                "tag": a["tag"], "facet": a["facet"], "local": len(a["local"]), "inherited": len(a["inherited"]),
                "sources": [self._source_ref(p, r) for p, r in a["sources"]],
            })
        return out

    def _source_ref(self, prov: str, ref: str) -> dict[str, Any]:
        """继承标签的来源（界面“去来源”）：区段标签 / 段 → 原片与区间；原片 → 原片；自动 → 资产。"""
        if prov == "segment":
            for table, kind in (("range_tag", "rangeTag"), ("text_segment", "segment")):
                r = self.conn.execute(f'SELECT source_id, start, "end" FROM {table} WHERE id = ?', (ref,)).fetchone()
                if r is not None:
                    return {"kind": kind, "id": ref, "sourceId": r[0], "start": r[1], "end": r[2]}
        if prov == "source":
            return {"kind": "source", "id": ref, "sourceId": ref}
        r = self.conn.execute("SELECT source_id FROM sound_asset WHERE id = ?", (ref,)).fetchone()
        return {"kind": "asset", "id": ref, "sourceId": r[0] if r else None}

    def batch_edit(self, ids: list[str], fields: dict[str, Any], *, label: dict[str, Any] | None = None) -> dict[str, Any]:
        """生成并预览批量编辑：返回 ``{batch, preview, samples, unchanged}``；界面确认后把 ``batch`` 交给 ``edits.apply``。"""
        if not ids:
            raise CoreError("edit-empty")
        allowed = {"name", "nature", "starred", "rating", "addTags", "removeTags"}
        if not fields or set(fields) - allowed:
            raise CoreError("sample-invalid", reason="not-an-option", field=",".join(sorted(set(fields) - allowed)) or "fields")
        add = [_check_tag(x, "addTags") for x in fields.get("addTags") or []]
        rm = {_check_tag(x, "removeTags") for x in fields.get("removeTags") or []}
        rows = self._rows(ids)
        local = self._local([r["id"] for r in rows]) if (add or rm) else {}
        ops = []
        for r in rows:
            f: dict[str, Any] = {k: fields[k] for k in ("name", "nature", "starred", "rating") if k in fields}
            if f.get("rating") == 0:
                f["rating"] = None  # 0 = 不评分
            if add or rm:
                cur = local[r["id"]]
                nxt = [x for x in cur if x not in rm]
                nxt += [x for x in add if x not in nxt]
                if nxt != cur:
                    f["local_tags"] = nxt
            if f:
                ops.append({"entity": "sample", "id": r["id"], "version": r["version"], "fields": f})
        if label is None:
            label = {"code": "samples-edit", "args": {"n": len(rows)}}
        batch = {"label": label, "ops": ops}
        if not ops:
            return {"batch": batch, "preview": {"changes": []}, "samples": len(rows), "unchanged": len(rows), "names": {}}
        preview = self.edits.preview(batch)
        changed = [c for c in preview["changes"] if c["diffs"]]
        batch["ops"] = [op for op, c in zip(ops, preview["changes"], strict=True) if c["diffs"]]
        names = {r["id"]: r["name"] for r in rows}
        return {"batch": batch, "preview": {"changes": changed}, "samples": len(rows), "unchanged": len(rows) - len(changed),
                "names": {c["id"]: names[c["id"]] for c in changed}}

    # ------------------------------------------------------------ 管理标签

    def list_all(self) -> list[dict[str, Any]]:
        """全部在用的标签：采样数（有效标签，按采样计）、本地采样数、区段标签数、原片数、段数（人物）。"""
        acc: dict[str, dict[str, Any]] = {}

        def get(tag: str) -> dict[str, Any]:
            return acc.setdefault(tag, {"tag": tag, "facet": facet_of(tag), "samples": 0, "local": 0, "rangeTags": 0, "sources": 0, "segments": 0})

        for tag, n in self.conn.execute("SELECT tag, COUNT(DISTINCT sample_id) FROM sample_effective_tag GROUP BY tag"):
            get(tag)["samples"] = n
        for tag, n in self.conn.execute("SELECT tag, COUNT(*) FROM sample_tag GROUP BY tag"):
            get(tag)["local"] = n
        for (tags,) in self.conn.execute("SELECT tags FROM range_tag WHERE deleted = 0 AND tags != '[]'"):
            for tg in set(loads(tags)):
                get(tg)["rangeTags"] += 1
        for col, ns in (("work", "work:"), ("source_type", "type:")):
            for v, n in self.conn.execute(f"SELECT {col}, COUNT(*) FROM source WHERE {col} != '' GROUP BY {col}"):
                get(ns + v)["sources"] = n
        names: dict[str, int] = {}
        for (sp,) in self.conn.execute("SELECT speakers FROM text_segment WHERE deleted = 0 AND speakers != '[]'"):
            for nm in set(loads(sp)):
                names[nm] = names.get(nm, 0) + 1
        for nm, n in names.items():
            for ns in PERSON:
                if f"{ns}{nm}" in acc or ns == "character:":
                    get(f"{ns}{nm}")["segments"] = n
        return sorted(acc.values(), key=lambda x: (x["facet"], x["tag"]))

    def global_plan(self, op: str, tag: str, to: str | None = None) -> dict[str, Any]:
        """全局改名 / 移除的编辑批次与影响（预览，不写库）。"""
        if op not in ("rename", "remove"):
            raise CoreError("sample-invalid", reason="not-an-option", field="op")
        tag = _check_tag(tag)
        new = _check_tag(to, "to") if op == "rename" else None
        if new == tag:
            raise CoreError("sample-invalid", reason="same-tag", field="to")
        person = tag.startswith(PERSON)
        if person and new is not None and not new.startswith(PERSON):
            raise CoreError("sample-invalid", reason="person-rename-namespace", field="to")
        ops: list[dict[str, Any]] = []
        report = {"samples": 0, "rangeTags": 0, "sources": 0, "segments": 0, "folderSources": 0, "derived": 0}
        # 本地标签
        for (sid,) in self.conn.execute("SELECT DISTINCT sample_id FROM sample_tag WHERE tag = ?", (tag,)).fetchall():
            cur = [r[0] for r in self.conn.execute("SELECT tag FROM sample_tag WHERE sample_id = ? ORDER BY rowid", (sid,))]
            nxt: list[str] = []
            for x in cur:
                y = new if x == tag else x
                if y is not None and y not in nxt:
                    nxt.append(y)
            ver = self.conn.execute("SELECT version FROM sample WHERE id = ?", (sid,)).fetchone()[0]
            ops.append({"entity": "sample", "id": sid, "version": ver, "fields": {"local_tags": nxt}})
            report["samples"] += 1
        # 区段标签
        for rid, tags, ver in self.conn.execute("SELECT id, tags, version FROM range_tag WHERE deleted = 0 AND tags != '[]'").fetchall():
            cur = loads(tags)
            if tag not in cur:
                continue
            nxt = []
            for x in cur:
                y = new if x == tag else x
                if y is not None and y not in nxt:
                    nxt.append(y)
            ops.append({"entity": "range_tag", "id": rid, "version": ver, "fields": {"tags": nxt}})
            report["rangeTags"] += 1
        # 原片的作品 / 类型
        for ns, col, field in (("work:", "work", "work"), ("type:", "source_type", "source_type")):
            if not tag.startswith(ns):
                continue
            if new is not None and not new.startswith(ns):
                raise CoreError("sample-invalid", reason="source-rename-namespace", field="to")
            value = tag[len(ns) :]
            to_value = new[len(ns) :] if new is not None else ""
            for sid, ver, root in self.conn.execute(f"SELECT id, version, root_id FROM source WHERE {col} = ?", (value,)).fetchall():
                if col == "work" and root is not None:
                    report["folderSources"] += 1  # 作品跟着文件夹走：用「作品设置…」改文件夹名
                    continue
                ops.append({"entity": "source", "id": sid, "version": ver, "fields": {field: to_value}})
                report["sources"] += 1
        # 段的说话人（L33）：人物标签 = 说话人名字；改名 / 移除说话人
        if person:
            name = tag.split(":", 1)[1]
            new_name = new.split(":", 1)[1] if new is not None else None
            for gid, sp, ver in self.conn.execute("SELECT id, speakers, version FROM text_segment WHERE deleted = 0 AND speakers != '[]'").fetchall():
                cur = loads(sp)
                if name not in cur:
                    continue
                nxt = []
                for x in cur:
                    y = new_name if x == name else x
                    if y is not None and y not in nxt:
                        nxt.append(y)
                ops.append({"entity": "segment", "id": gid, "version": ver, "fields": {"speakers": nxt}})
                report["segments"] += 1
        if tag.startswith(DERIVED):
            report["derived"] = self.conn.execute(
                "SELECT COUNT(DISTINCT sample_id) FROM sample_effective_tag WHERE tag = ? AND provenance = 'segment'"
                " AND provenance_ref IN (SELECT id FROM text_segment)", (tag,)
            ).fetchone()[0]
        label = {"code": "tags-global-rename" if op == "rename" else "tags-global-remove", "args": {"tag": tag, "to": new or ""}}
        batch = {"label": label, "ops": ops}
        changes = self.edits.preview(batch)["changes"] if ops else []
        return {"batch": batch, "report": report, "changes": len(changes)}
