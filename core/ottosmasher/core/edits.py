"""统一编辑通道（ARCHITECTURE §5，规格 07 §7.6，16 R9）。

所有用户资料修改都表示成一个编辑批次：对象列表 + 字段级的新值 + 客户端看到的对象版本。

- 预览：计算逐字段对比，不写库。
- 应用：一个事务；任一对象版本不一致或校验失败 → 整批拒绝，错误指出第几个对象。
- 撤销：从最近一次开始，找第一个“所有对象当前状态仍等于该次修改后状态”的修改，用一次新的编辑恢复修改前的值；
  找不到就报“没有仍可安全撤销的资料修改”。撤销本身不能再被撤销（没有重做）。新建的标注被撤销 = 软删除。
"""

from __future__ import annotations

import sqlite3
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

import msgspec

from ..store.db import transaction
from . import settings as settings_mod
from .clock import new_id, now_iso
from .errors import CoreError

Validator = Callable[[Any], Any]

_json_enc = msgspec.json.Encoder()
_json_dec = msgspec.json.Decoder()


def dumps(v: Any) -> str:
    return _json_enc.encode(v).decode()


def loads(s: str | None) -> Any:
    return None if s is None else _json_dec.decode(s)


# ---------------------------------------------------------------- 校验器


class _Invalid(Exception):
    def __init__(self, reason: str, **args: Any) -> None:
        self.reason = reason
        self.args_ = args


def v_text(*, min_len: int = 0, max_len: int = 10_000, strip: bool = True) -> Validator:
    def check(v: Any) -> str:
        if not isinstance(v, str):
            raise _Invalid("not-text")
        s = v.strip() if strip else v
        if len(s) < min_len:
            raise _Invalid("too-short", min=min_len)
        if len(s) > max_len:
            raise _Invalid("too-long", max=max_len)
        return s

    return check


def v_bool(v: Any) -> bool:
    if not isinstance(v, bool):
        raise _Invalid("not-boolean")
    return v


def v_enum(*options: str) -> Validator:
    def check(v: Any) -> str:
        if v not in options:
            raise _Invalid("not-an-option", options=list(options))
        return v

    return check


def v_opt_int(lo: int, hi: int) -> Validator:
    def check(v: Any) -> int | None:
        if v is None:
            return None
        if isinstance(v, bool) or not isinstance(v, int) or not lo <= v <= hi:
            raise _Invalid("out-of-range", min=lo, max=hi)
        return v

    return check


def v_number(v: Any) -> float:
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        raise _Invalid("not-number")
    return float(v)


def v_tags(max_count: int) -> Validator:
    def check(v: Any) -> list[str]:
        if not isinstance(v, list) or not all(isinstance(t, str) for t in v):
            raise _Invalid("not-tag-list")
        out = sorted({t.strip() for t in v if t.strip()})
        if len(out) > max_count:
            raise _Invalid("too-many-tags", max=max_count)
        if any(len(t) > 200 for t in out):
            raise _Invalid("tag-too-long", max=200)
        return out

    return check


def v_json(v: Any) -> Any:
    return v


# ---------------------------------------------------------------- 对象类型


@dataclass(frozen=True)
class FieldSpec:
    validate: Validator
    column: str | None = None  # None = 同名列
    json: bool = False  # 列里存 JSON
    custom: str | None = None  # 非列字段，由 EntitySpec 的钩子读写


@dataclass(frozen=True)
class EntitySpec:
    name: str
    table: str
    fields: dict[str, FieldSpec]
    creatable: dict[str, FieldSpec] = field(default_factory=dict)  # 新建时可给的额外字段
    create_required: tuple[str, ...] = ()
    soft_delete_column: str | None = None  # 新建被撤销时置 1
    revision_table: bool = False  # annotation：每次编辑留版本


def _q(col: str) -> str:
    return f'"{col}"'


ENTITIES: dict[str, EntitySpec] = {}


def _register(spec: EntitySpec) -> None:
    ENTITIES[spec.name] = spec


_register(
    EntitySpec(
        "sample",
        "sample",
        {
            "name": FieldSpec(v_text(min_len=1, max_len=500)),
            "note": FieldSpec(v_text(max_len=10_000, strip=False)),
            "rating": FieldSpec(v_opt_int(1, 5)),
            "starred": FieldSpec(v_bool),
            "nature": FieldSpec(v_enum("speech", "pitched", "unpitched", "unclassified")),
            "local_tags": FieldSpec(v_tags(512), custom="local_tags"),
        },
    )
)
_register(
    EntitySpec(
        "source",
        "source",
        {
            "work": FieldSpec(v_text(max_len=200)),
            "episode": FieldSpec(v_text(max_len=200)),
            "source_type": FieldSpec(v_text(max_len=100)),
        },
    )
)
_register(
    EntitySpec(
        "annotation",
        "annotation",
        {
            "start": FieldSpec(v_number),
            "end": FieldSpec(v_number),
            "raw_text": FieldSpec(v_text(max_len=10_000, strip=False)),
            "clean_text": FieldSpec(v_text(max_len=10_000, strip=False)),
            "align_text_manual": FieldSpec(v_text(max_len=10_000, strip=False)),
            "tags": FieldSpec(v_tags(512), json=True),
            "deleted": FieldSpec(v_bool),
        },
        creatable={
            "source_id": FieldSpec(v_text(min_len=1, max_len=64)),
            "kind": FieldSpec(v_enum("line", "sfx", "song", "tag")),
            "scope": FieldSpec(v_enum("source", "role", "asset")),
            "scope_role": FieldSpec(v_enum("vocal", "sfx")),
            "scope_asset_id": FieldSpec(v_text(min_len=1, max_len=64)),
        },
        create_required=("source_id", "kind", "scope", "start", "end"),
        soft_delete_column="deleted",
        revision_table=True,
    )
)
_register(
    EntitySpec(
        "saved_filter",
        "saved_filter",
        {
            "name": FieldSpec(v_text(min_len=1, max_len=200)),
            "conditions": FieldSpec(v_json, json=True),
            "sort_order": FieldSpec(v_opt_int(0, 1_000_000)),
            "deleted": FieldSpec(v_bool),
        },
        create_required=("name", "conditions", "sort_order"),
        soft_delete_column="deleted",
    )
)
# 设置：键值对象，ID = 设置键，唯一字段 value；没存过的取默认值（版本 0）
_register(EntitySpec("setting", "setting", {"value": FieldSpec(v_json, json=True)}))

_BOOL_COLUMNS = {"starred", "deleted", "user_edited", "independent"}


# ---------------------------------------------------------------- 编辑服务


@dataclass
class ChangeSet:
    """一次写入影响的对象（推给界面，只用来提示“资料已更新”）。"""

    entities: dict[str, set[str]] = field(default_factory=dict)

    def add(self, entity: str, entity_id: str) -> None:
        self.entities.setdefault(entity, set()).add(entity_id)

    def to_wire(self) -> dict[str, list[str]]:
        return {k: sorted(v) for k, v in self.entities.items()}


class EditService:
    def __init__(self, conn: sqlite3.Connection, on_change: Callable[[ChangeSet], None] | None = None) -> None:
        self.conn = conn
        self.on_change = on_change

    # ---------- 读

    def _read(self, spec: EntitySpec, entity_id: str, names: list[str]) -> tuple[dict[str, Any], int] | None:
        """读对象的若干字段与版本；对象不存在返回 None（设置例外：不存在 = 默认值、版本 0）。"""
        if spec.name == "setting":
            s = settings_mod.spec(entity_id)
            row = self.conn.execute("SELECT value, version FROM setting WHERE key=?", (entity_id,)).fetchone()
            if row is None:
                return {"value": s.default}, 0
            return {"value": loads(row["value"])}, int(row["version"])
        cols = [spec.fields[n] if n in spec.fields else spec.creatable[n] for n in names]
        plain = [(n, f) for n, f in zip(names, cols, strict=True) if f.custom is None]
        sel = ", ".join(_q(f.column or n) for n, f in plain) or "1"
        row = self.conn.execute(f"SELECT {sel}, version FROM {spec.table} WHERE id=?", (entity_id,)).fetchone()
        if row is None:
            return None
        out: dict[str, Any] = {}
        for i, (n, f) in enumerate(plain):
            v = row[i]
            if f.json:
                v = loads(v)
            elif (f.column or n) in _BOOL_COLUMNS:
                v = bool(v)
            out[n] = v
        for n, f in zip(names, cols, strict=True):
            if f.custom == "local_tags":
                out[n] = [
                    r[0]
                    for r in self.conn.execute(
                        "SELECT tag FROM sample_tag WHERE sample_id=? ORDER BY tag", (entity_id,)
                    )
                ]
        return out, int(row["version"])

    # ---------- 校验与对比（预览、应用共用）

    def _plan(self, batch: dict[str, Any]) -> list[dict[str, Any]]:
        ops = batch.get("ops")
        if not isinstance(ops, list) or not ops:
            raise CoreError("edit-empty")
        plan: list[dict[str, Any]] = []
        seen: set[tuple[str, str]] = set()
        for i, op in enumerate(ops):
            entity = op.get("entity")
            spec = ENTITIES.get(entity)  # type: ignore[arg-type]
            if spec is None:
                raise CoreError("edit-unknown-entity", index=i, entity=entity)
            kind = op.get("op", "update")
            fields = op.get("fields")
            if not isinstance(fields, dict) or not fields:
                raise CoreError("edit-invalid", index=i, entity=entity, field=None, reason="no-fields")
            if kind == "create":
                plan.append(self._plan_create(i, spec, fields))
                continue
            if kind != "update":
                raise CoreError("edit-invalid", index=i, entity=entity, field=None, reason="bad-op")
            entity_id = op.get("id")
            if not isinstance(entity_id, str):
                raise CoreError("edit-invalid", index=i, entity=entity, field=None, reason="no-id")
            if (entity, entity_id) in seen:
                raise CoreError("edit-duplicate-object", index=i, entity=entity, id=entity_id)
            seen.add((entity, entity_id))
            new: dict[str, Any] = {}
            for name, value in fields.items():
                fspec = spec.fields.get(name)
                if fspec is None:
                    raise CoreError("edit-unknown-field", index=i, entity=entity, field=name)
                new[name] = self._validate(i, spec, entity_id, name, fspec, value)
            try:
                cur = self._read(spec, entity_id, list(new))
            except CoreError as exc:
                raise CoreError("edit-not-found", index=i, entity=entity, id=entity_id) from exc
            if cur is None:
                raise CoreError("edit-not-found", index=i, entity=entity, id=entity_id)
            before, version = cur
            expected = op.get("version")
            if expected != version:
                raise CoreError("edit-conflict", index=i, entity=entity, id=entity_id, expected=expected, actual=version)
            diffs = {n: (before[n], v) for n, v in new.items() if before[n] != v}
            if spec.name == "annotation" and ("start" in new or "end" in new):
                self._check_range(i, spec, entity_id, new)
            plan.append(
                {"index": i, "entity": entity, "id": entity_id, "op": "update", "version": version, "diffs": diffs}
            )
        return plan

    def _validate(self, i: int, spec: EntitySpec, entity_id: str | None, name: str, fspec: FieldSpec, value: Any) -> Any:
        try:
            if spec.name == "setting":
                try:
                    return settings_mod.spec(entity_id or "").validate(value)
                except CoreError as exc:
                    if exc.code == "setting-unknown":
                        raise CoreError("edit-not-found", index=i, entity="setting", id=entity_id) from None
                    raise _Invalid(exc.args_.get("reason", exc.code), **{k: v for k, v in exc.args_.items() if k != "reason"}) from None
            return fspec.validate(value)
        except _Invalid as bad:
            raise CoreError("edit-invalid", index=i, entity=spec.name, field=name, reason=bad.reason, **bad.args_) from None

    def _check_range(self, i: int, spec: EntitySpec, entity_id: str | None, new: dict[str, Any]) -> None:
        start, end = new.get("start"), new.get("end")
        if entity_id is not None and (start is None or end is None):
            cur = self._read(spec, entity_id, ["start", "end"])
            if cur:
                start = cur[0]["start"] if start is None else start
                end = cur[0]["end"] if end is None else end
        if start is not None and end is not None and not end > start:
            raise CoreError("edit-invalid", index=i, entity=spec.name, field="end", reason="end-not-after-start")

    def _plan_create(self, i: int, spec: EntitySpec, fields: dict[str, Any]) -> dict[str, Any]:
        if spec.soft_delete_column is None:
            raise CoreError("edit-invalid", index=i, entity=spec.name, field=None, reason="not-creatable")
        values: dict[str, Any] = {}
        for name, value in fields.items():
            fspec = spec.fields.get(name) or spec.creatable.get(name)
            if fspec is None or name == spec.soft_delete_column:
                raise CoreError("edit-unknown-field", index=i, entity=spec.name, field=name)
            values[name] = self._validate(i, spec, None, name, fspec, value)
        for req in spec.create_required:
            if req not in values:
                raise CoreError("edit-invalid", index=i, entity=spec.name, field=req, reason="required")
        if spec.name == "annotation":
            self._check_range(i, spec, None, values)
            exists = self.conn.execute("SELECT 1 FROM source WHERE id=?", (values["source_id"],)).fetchone()
            if exists is None:
                raise CoreError("edit-invalid", index=i, entity="annotation", field="source_id", reason="no-such-source")
        values[spec.soft_delete_column] = False
        return {
            "index": i,
            "entity": spec.name,
            "id": new_id(),
            "op": "create",
            "version": None,
            "diffs": {n: (None, v) for n, v in values.items()},
        }

    # ---------- 公开接口

    def preview(self, batch: dict[str, Any]) -> dict[str, Any]:
        plan = self._plan(batch)
        return {"changes": [_wire(p) for p in plan]}

    def apply(self, batch: dict[str, Any]) -> dict[str, Any]:
        label = batch.get("label") or {"code": "edit", "args": {}}
        with transaction(self.conn):
            plan = self._plan(batch)  # 在写事务里重新校验，避免预览与应用之间被改
            real = [p for p in plan if p["diffs"]]
            if not real:
                return {"edit_id": None, "changes": []}
            edit_id = self._write(real, label, undo_of=None)
        changes = ChangeSet()
        for p in real:
            changes.add(p["entity"], p["id"])
        if self.on_change:
            self.on_change(changes)
        return {"edit_id": edit_id, "changes": [_wire(p) for p in real]}

    def _write(self, plan: list[dict[str, Any]], label: dict[str, Any], undo_of: str | None) -> str:
        edit_id = new_id()
        seq = (self.conn.execute("SELECT COALESCE(MAX(seq), 0) FROM edit").fetchone()[0] or 0) + 1
        ts = now_iso()
        self.conn.execute(
            "INSERT INTO edit(id, seq, created_at, label_code, label_args, undo_of) VALUES (?, ?, ?, ?, ?, ?)",
            (edit_id, seq, ts, label.get("code", "edit"), dumps(label.get("args", {})), undo_of),
        )
        for idx, p in enumerate(plan):
            spec = ENTITIES[p["entity"]]
            after = {n: d[1] for n, d in p["diffs"].items()}
            if p["op"] == "create":
                version_after = self._insert(spec, p["id"], after, ts)
                before = None
            else:
                before = {n: d[0] for n, d in p["diffs"].items()}
                version_after = self._update(spec, p["id"], after, p["version"], ts)
            if spec.revision_table:
                self._snapshot_revision(spec, p["id"], version_after, edit_id)
            self.conn.execute(
                "INSERT INTO edit_change(edit_id, idx, entity, entity_id, op, before, after, version_before, version_after)"
                " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    edit_id,
                    idx,
                    p["entity"],
                    p["id"],
                    p["op"],
                    None if before is None else dumps(before),
                    dumps(after),
                    p["version"],
                    version_after,
                ),
            )
        if undo_of is not None:
            self.conn.execute("UPDATE edit SET undone_by=? WHERE id=?", (edit_id, undo_of))
        return edit_id

    def _encode_col(self, spec: EntitySpec, name: str, value: Any) -> Any:
        f = spec.fields.get(name) or spec.creatable[name]
        if f.json:
            return dumps(value)
        if isinstance(value, bool):
            return int(value)
        return value

    def _insert(self, spec: EntitySpec, entity_id: str, values: dict[str, Any], ts: str) -> int:
        cols = {
            (spec.fields.get(n) or spec.creatable[n]).column or n: self._encode_col(spec, n, v)
            for n, v in values.items()
        }
        cols.update({"id": entity_id, "created_at": ts, "updated_at": ts, "version": 1})
        names = ", ".join(_q(c) for c in cols)
        marks = ", ".join("?" for _ in cols)
        self.conn.execute(f"INSERT INTO {spec.table}({names}) VALUES ({marks})", tuple(cols.values()))
        return 1

    def _update(self, spec: EntitySpec, entity_id: str, values: dict[str, Any], version: int, ts: str) -> int:
        if spec.name == "setting":
            if version == 0:
                self.conn.execute(
                    "INSERT INTO setting(key, value, version, updated_at) VALUES (?, ?, 1, ?)",
                    (entity_id, dumps(values["value"]), ts),
                )
                return 1
            cur = self.conn.execute(
                "UPDATE setting SET value=?, version=version+1, updated_at=? WHERE key=? AND version=?",
                (dumps(values["value"]), ts, entity_id, version),
            )
            if cur.rowcount != 1:
                raise CoreError("edit-conflict", entity="setting", id=entity_id)
            return version + 1
        plain = {n: v for n, v in values.items() if spec.fields[n].custom is None}
        sets = [f"{_q(spec.fields[n].column or n)}=?" for n in plain]
        params = [self._encode_col(spec, n, v) for n, v in plain.items()]
        sets += ["updated_at=?", "version=version+1"]
        cur = self.conn.execute(
            f"UPDATE {spec.table} SET {', '.join(sets)} WHERE id=? AND version=?",
            (*params, ts, entity_id, version),
        )
        if cur.rowcount != 1:
            raise CoreError("edit-conflict", entity=spec.name, id=entity_id)
        for n, v in values.items():
            if spec.fields[n].custom == "local_tags":
                self._write_local_tags(entity_id, v)
        return version + 1

    def _write_local_tags(self, sample_id: str, tags: list[str]) -> None:
        self.conn.execute("DELETE FROM sample_tag WHERE sample_id=?", (sample_id,))
        self.conn.executemany("INSERT INTO sample_tag(sample_id, tag) VALUES (?, ?)", [(sample_id, t) for t in tags])
        # 有效标签索引里的本地部分同步更新（其余来源由各自的写入维护，规格 16 R8.8）
        self.conn.execute("DELETE FROM sample_effective_tag WHERE sample_id=? AND provenance='local'", (sample_id,))
        self.conn.executemany(
            "INSERT INTO sample_effective_tag(sample_id, tag, facet, provenance) VALUES (?, ?, ?, 'local')",
            [(sample_id, t, facet_of(t)) for t in tags],
        )

    def _snapshot_revision(self, spec: EntitySpec, entity_id: str, version: int, edit_id: str) -> None:
        row = self.conn.execute(f"SELECT * FROM {spec.table} WHERE id=?", (entity_id,)).fetchone()
        snap = {k: row[k] for k in row.keys()}
        self.conn.execute(
            "INSERT INTO annotation_revision(annotation_id, version, snapshot, edit_id) VALUES (?, ?, ?, ?)",
            (entity_id, version, dumps(snap), edit_id),
        )

    # ---------- 撤销

    def _undo_candidate(self) -> tuple[sqlite3.Row, list[sqlite3.Row]] | None:
        edits = self.conn.execute(
            "SELECT * FROM edit WHERE undo_of IS NULL AND undone_by IS NULL ORDER BY seq DESC"
        ).fetchall()
        for e in edits:
            changes = self.conn.execute("SELECT * FROM edit_change WHERE edit_id=? ORDER BY idx", (e["id"],)).fetchall()
            if all(self._still_after(c) for c in changes):
                return e, changes
        return None

    def _still_after(self, c: sqlite3.Row) -> bool:
        spec = ENTITIES[c["entity"]]
        after = loads(c["after"])
        try:
            cur = self._read(spec, c["entity_id"], list(after))
        except CoreError:
            return False
        if cur is None:
            return False
        return cur[0] == after

    def peek_undo(self) -> dict[str, Any] | None:
        cand = self._undo_candidate()
        if cand is None:
            return None
        e, _ = cand
        return {"edit_id": e["id"], "label": {"code": e["label_code"], "args": loads(e["label_args"])}}

    def undo(self) -> dict[str, Any]:
        with transaction(self.conn):
            cand = self._undo_candidate()
            if cand is None:
                raise CoreError("undo-nothing-safe")
            e, changes = cand
            plan: list[dict[str, Any]] = []
            for c in changes:
                spec = ENTITIES[c["entity"]]
                after = loads(c["after"])
                cur = self._read(spec, c["entity_id"], list(after))
                assert cur is not None
                _, version = cur
                if c["op"] == "create":
                    col = spec.soft_delete_column
                    assert col is not None
                    diffs = {col: (False, True)}
                else:
                    before = loads(c["before"])
                    diffs = {n: (after[n], before[n]) for n in before}
                plan.append({"index": c["idx"], "entity": c["entity"], "id": c["entity_id"], "op": "update", "version": version, "diffs": diffs})
            label = {"code": "undo", "args": {"of": e["label_code"], "of_args": loads(e["label_args"])}}
            edit_id = self._write(plan, label, undo_of=e["id"])
        changes_set = ChangeSet()
        for p in plan:
            changes_set.add(p["entity"], p["id"])
        if self.on_change:
            self.on_change(changes_set)
        return {"edit_id": edit_id, "undone": e["id"], "label": label, "changes": [_wire(p) for p in plan]}


def facet_of(tag: str) -> str:
    """标签所属分面（规格 04 §4.2.8）：work / type / person / pitch / other。"""
    ns = tag.split(":", 1)[0] if ":" in tag else ""
    return {"work": "work", "type": "type", "character": "person", "participants": "person", "pitch": "pitch"}.get(ns, "other")


def _wire(p: dict[str, Any]) -> dict[str, Any]:
    return {
        "index": p["index"],
        "entity": p["entity"],
        "id": p["id"],
        "op": p["op"],
        "diffs": [{"field": n, "before": d[0], "after": d[1]} for n, d in p["diffs"].items()],
    }
