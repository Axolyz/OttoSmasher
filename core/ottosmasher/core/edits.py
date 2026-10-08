"""统一编辑通道（ARCHITECTURE §5，规格 07 §7.6，16 R9）。

所有用户资料修改都表示成一个编辑批次：对象列表 + 字段级的新值 + 客户端看到的对象版本。

- 预览：计算逐字段对比，不写库。
- 应用：一个事务；任一对象版本不一致或校验失败 → 整批拒绝，错误指出第几个对象。
- 撤销：从最近一次开始，找第一个“所有对象当前状态仍等于该次修改后状态”的修改，用一次新的编辑恢复修改前的值；
  找不到就报“没有仍可安全撤销的资料修改”。撤销本身不能再被撤销（没有重做）。新建的标注被撤销 = 软删除。
"""

from __future__ import annotations

import os

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


def v_opt_path(v: Any) -> str | None:
    """文件路径或 None（清除）。存在性等在 _check_source 里查。"""
    if v is None:
        return None
    if not isinstance(v, str) or not v.strip():
        raise _Invalid("not-text")
    if len(v) > 4096:
        raise _Invalid("too-long", max=4096)
    return v


def v_opt_id(v: Any) -> str | None:
    if v is None:
        return None
    if not isinstance(v, str) or not 1 <= len(v) <= 64:
        raise _Invalid("not-text")
    return v


def v_opt_enum(*options: str) -> Validator:
    def check(v: Any) -> str | None:
        if v is not None and v not in options:
            raise _Invalid("not-an-option", options=list(options))
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


def v_roles(v: Any) -> list[str]:
    if not isinstance(v, list) or any(r not in ("vocal", "sfx") for r in v):
        raise _Invalid("not-an-option", options=["vocal", "sfx"])
    return sorted(set(v))


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
            # 「作品与输入设置」（规格 05 §5.2）：分析音轨 = 第几条音频流；字幕文件只关联不导入，可清除
            "default_audio_stream": FieldSpec(v_opt_int(0, 999)),
            "subtitle_path": FieldSpec(v_opt_path),
            # 当前字幕版本（规格 04 §4.2.2）：只由字幕导入改（切回旧版本 = 重新导入旧文件），撤销导入时恢复
            "current_subtitle_version_id": FieldSpec(v_opt_id),
            # 默认轨（规格 04 §4.2.3）：每个角色一条，从带该角色、完整覆盖且未变速的资产里选；None = 未指定
            "default_vocal": FieldSpec(v_opt_id, custom="default_track"),
            "default_sfx": FieldSpec(v_opt_id, custom="default_track"),
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
            # 种类：字幕来的台词/音效可以改成歌词（规格 04 §4.2.2：歌词只能由用户手动标）；作用域可改（04：标注可编辑时间、文字、标签、作用域）
            "kind": FieldSpec(v_enum("line", "sfx", "song", "tag")),
            "scope": FieldSpec(v_enum("source", "role", "asset")),
            "scope_role": FieldSpec(v_opt_enum("vocal", "sfx")),
            # 用户改过（字幕重新导入只补登、不改写用户改过的标注；编辑时自动置上，撤销时恢复）
            "user_edited": FieldSpec(v_bool),
        },
        creatable={
            "source_id": FieldSpec(v_text(min_len=1, max_len=64)),
            "scope_asset_id": FieldSpec(v_text(min_len=1, max_len=64)),
            # 字幕导入（规格 06 §6.1）：来自哪个字幕版本的哪一行、按当时规则得到的自动对齐文本
            "subtitle_version_id": FieldSpec(v_text(min_len=1, max_len=64)),
            "subtitle_line_id": FieldSpec(v_text(min_len=1, max_len=64)),
            "align_text_auto": FieldSpec(v_text(max_len=10_000, strip=False)),
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
# 作品文件夹（阶段 3.13）：作品级设置——来源类型（新文件沿用）、同名画面自动绑定；改名是文件操作，不走编辑通道（core/roots.py）
_register(
    EntitySpec(
        "work_folder",
        "work_folder",
        {"source_type": FieldSpec(v_text(max_len=100)), "bind_pictures": FieldSpec(v_bool)},
    )
)
# 声音资产：只有角色可改（规格 04 §4.2.3；用户移除的角色记为 removed_by_user，系统预填不再加回）
_register(EntitySpec("asset", "sound_asset", {"roles": FieldSpec(v_roles, custom="roles")}))
# OP/ED 区间（规格 05 §5.6）：字幕规则结果与人工标记/确认都经编辑通道新建（可撤销 = 软删除），删除也是软删除
_register(
    EntitySpec(
        "oped",
        "oped",
        {
            "kind": FieldSpec(v_enum("OP", "ED")),
            "start": FieldSpec(v_number),
            "end": FieldSpec(v_number),
            "deleted": FieldSpec(v_bool),
        },
        creatable={
            "source_id": FieldSpec(v_text(min_len=1, max_len=64)),
            "origin": FieldSpec(v_enum("subtitle_rule", "manual")),
            "evidence": FieldSpec(v_json, json=True),
        },
        create_required=("source_id", "kind", "start", "end", "origin"),
        soft_delete_column="deleted",
    )
)
# 设置：键值对象，ID = 设置键，唯一字段 value；没存过的取默认值（版本 0）
_register(EntitySpec("setting", "setting", {"value": FieldSpec(v_json, json=True)}))

_BOOL_COLUMNS = {"starred", "deleted", "user_edited", "independent", "bind_pictures"}


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
        self._pending_roles: dict[str, list[str]] = {}

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
            if f.custom == "roles":
                out[n] = [
                    r[0]
                    for r in self.conn.execute(
                        "SELECT role FROM asset_role WHERE asset_id=? AND state='on' ORDER BY role", (entity_id,)
                    )
                ]
            if f.custom == "default_track":
                r = self.conn.execute(
                    "SELECT asset_id FROM default_track WHERE source_id=? AND role=?", (entity_id, n.removeprefix("default_"))
                ).fetchone()
                out[n] = None if r is None else r[0]
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
        # 同一批次里先改角色、再设默认轨（「人声／音效与默认轨」里给原混音加人声角色并设为默认，一次撤销）
        self._pending_roles: dict[str, list[str]] = {}
        for op in ops:
            f = op.get("fields") if isinstance(op, dict) else None
            if isinstance(f, dict) and op.get("entity") == "asset" and isinstance(op.get("id"), str) and "roles" in f:
                try:
                    self._pending_roles[op["id"]] = v_roles(f["roles"])
                except _Invalid:
                    pass  # 下面逐项校验时会报出具体错误
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
            if spec.name == "annotation" and diffs and "user_edited" not in new:
                flag = self._read(spec, entity_id, ["user_edited"])
                if flag and not flag[0]["user_edited"]:
                    diffs["user_edited"] = (False, True)
            if spec.name in ("annotation", "oped") and ("start" in new or "end" in new):
                self._check_range(i, spec, entity_id, new)
            if spec.name == "annotation" and ({"scope", "scope_role"} & set(new)):
                self._check_scope(i, entity_id, new)
            if spec.name == "source":
                self._check_source(i, entity_id, new)
            plan.append(
                {"index": i, "entity": entity, "id": entity_id, "op": "update", "version": version, "diffs": diffs}
            )
        self._check_defaults_keep_roles(plan)
        return plan

    def _check_defaults_keep_roles(self, plan: list[dict[str, Any]]) -> None:
        """移除某资产的角色时，它若是该角色的默认轨，同一批次必须同时改掉那个默认轨（默认轨必须带该角色）。"""
        new_defaults = {
            (p["id"], n.removeprefix("default_")): d[1]
            for p in plan
            if p["entity"] == "source"
            for n, d in p["diffs"].items()
            if n.startswith("default_")
        }
        for p in plan:
            if p["entity"] != "asset" or "roles" not in p["diffs"]:
                continue
            roles = p["diffs"]["roles"][1]
            for src, role in self.conn.execute("SELECT source_id, role FROM default_track WHERE asset_id=?", (p["id"],)):
                if role not in roles and new_defaults.get((src, role), p["id"]) == p["id"]:
                    raise CoreError("edit-invalid", index=p["index"], entity="asset", field="roles", reason="still-default", role=role)

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

    def _check_source(self, i: int, source_id: str, new: dict[str, Any]) -> None:
        if "work" in new:
            r = self.conn.execute("SELECT root_id, work FROM source WHERE id=?", (source_id,)).fetchone()
            if r is not None and r["root_id"] is not None and new["work"] != r["work"]:
                # 原片文件夹里的原片：作品跟着文件夹走，改名用「作品设置…」（会改文件夹名，阶段 3.13）
                raise CoreError("edit-invalid", index=i, entity="source", field="work", reason="work-follows-folder")
        for role in ("vocal", "sfx"):
            aid = new.get(f"default_{role}")
            if aid is None:
                continue
            from . import assets as assets_mod  # 避免循环导入

            try:
                assets_mod.check_default_track(self.conn, source_id, aid, role, roles=self._pending_roles.get(aid))
            except CoreError as exc:
                raise CoreError("edit-invalid", index=i, entity="source", field=f"default_{role}", **exc.args_) from None
        vid = new.get("current_subtitle_version_id")
        if vid is not None and self.conn.execute(
            "SELECT 1 FROM subtitle_version WHERE id=? AND source_id=?", (vid, source_id)
        ).fetchone() is None:
            raise CoreError("edit-invalid", index=i, entity="source", field="current_subtitle_version_id", reason="other-source")
        if "default_audio_stream" in new:
            o = new["default_audio_stream"]
            if o is None or self.conn.execute(
                "SELECT 1 FROM source_stream WHERE source_id=? AND kind='audio' AND ordinal=?", (source_id, o)
            ).fetchone() is None:
                raise CoreError("edit-invalid", index=i, entity="source", field="default_audio_stream", reason="no-such-stream")
        p = new.get("subtitle_path")
        if p is not None:
            if not os.path.isfile(p):
                raise CoreError("edit-invalid", index=i, entity="source", field="subtitle_path", reason="file-missing")
            if os.path.splitext(p)[1].lower() not in (".srt", ".ass"):
                raise CoreError("edit-invalid", index=i, entity="source", field="subtitle_path", reason="not-subtitle")

    def _check_range(self, i: int, spec: EntitySpec, entity_id: str | None, new: dict[str, Any]) -> None:
        start, end = new.get("start"), new.get("end")
        if entity_id is not None and (start is None or end is None):
            cur = self._read(spec, entity_id, ["start", "end"])
            if cur:
                start = cur[0]["start"] if start is None else start
                end = cur[0]["end"] if end is None else end
        if start is not None and end is not None and not end > start:
            raise CoreError("edit-invalid", index=i, entity=spec.name, field="end", reason="end-not-after-start")
        # 不超出坐标范围（R4.3）：原片 / 角色作用域按原片时长，资产作用域按资产时长
        if entity_id is not None:
            row = self.conn.execute(f"SELECT * FROM {spec.table} WHERE id=?", (entity_id,)).fetchone()
            src, asset = row["source_id"], (row["scope_asset_id"] if spec.name == "annotation" and row["scope"] == "asset" else None)
        else:
            src = new.get("source_id")
            asset = new.get("scope_asset_id") if new.get("scope") == "asset" else None
        limit = None
        if asset is not None:
            r = self.conn.execute("SELECT duration FROM sound_asset WHERE id=?", (asset,)).fetchone()
            limit = r[0] if r else None
        elif src is not None:
            r = self.conn.execute("SELECT duration FROM source WHERE id=?", (src,)).fetchone()
            limit = r[0] if r else None
        if start is not None and start < -1e-9:
            raise CoreError("edit-invalid", index=i, entity=spec.name, field="start", reason="out-of-bounds")
        if end is not None and limit is not None and end > limit + 1e-6:
            raise CoreError("edit-invalid", index=i, entity=spec.name, field="end", reason="out-of-bounds")

    def _check_scope(self, i: int, entity_id: str | None, new: dict[str, Any]) -> None:
        """作用域与角色要配对：角色作用域必须给角色，其他作用域不能带角色。资产作用域只能在新建时定（时间坐标不同）。"""
        cur = {"scope": None, "scope_role": None}
        if entity_id is not None:
            r = self.conn.execute("SELECT scope, scope_role FROM annotation WHERE id=?", (entity_id,)).fetchone()
            cur = {"scope": r["scope"], "scope_role": r["scope_role"]}
            if ("scope" in new and new["scope"] != cur["scope"]) and "asset" in (new["scope"], cur["scope"]):
                raise CoreError("edit-invalid", index=i, entity="annotation", field="scope", reason="asset-scope-fixed")
        scope = new.get("scope", cur["scope"])
        role = new.get("scope_role", cur["scope_role"])
        if (scope == "role") != (role is not None):
            raise CoreError("edit-invalid", index=i, entity="annotation", field="scope_role", reason="scope-role-mismatch")

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
        if spec.name == "oped":
            self._check_range(i, spec, None, values)
        if spec.name == "annotation":
            self._check_range(i, spec, None, values)
            self._check_scope(i, None, values)
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

    def apply_within(self, batch: dict[str, Any]) -> tuple[str | None, ChangeSet]:
        """在调用方已开的写事务里应用一个编辑批次（与别的写入同一事务，例如字幕导入同时写入只读的字幕版本快照）。
        调用方提交后负责发出变更通知。"""
        label = batch.get("label") or {"code": "edit", "args": {}}
        plan = [p for p in self._plan(batch) if p["diffs"]]
        changes = ChangeSet()
        if not plan:
            return None, changes
        edit_id = self._write(plan, label, undo_of=None)
        for p in plan:
            changes.add(p["entity"], p["id"])
        return edit_id, changes

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
        # 有效标签索引在同一事务里跟着改（ARCHITECTURE §4、R8.8）
        from . import effective_tags  # 避免循环导入

        affected: list[str] = []
        for p in plan:
            affected += effective_tags.affected_by_change(self.conn, p["entity"], p["id"], p["diffs"].keys())
        effective_tags.refresh(self.conn, affected)
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
            elif spec.fields[n].custom == "roles":
                self._write_roles(entity_id, v)
            elif spec.fields[n].custom == "default_track":
                role = n.removeprefix("default_")
                self.conn.execute("DELETE FROM default_track WHERE source_id=? AND role=?", (entity_id, role))
                if v is not None:
                    self.conn.execute("INSERT INTO default_track(source_id, role, asset_id) VALUES (?, ?, ?)", (entity_id, role, v))
        return version + 1

    def _write_roles(self, asset_id: str, roles: list[str]) -> None:
        """开 → on；原来开着、现在关 → removed_by_user（系统预填不再加回）；从没有过的不写。"""
        cur = {r[0]: r[1] for r in self.conn.execute("SELECT role, state FROM asset_role WHERE asset_id=?", (asset_id,))}
        for role in ("vocal", "sfx"):
            if role in roles:
                self.conn.execute(
                    "INSERT INTO asset_role(asset_id, role, state) VALUES (?, ?, 'on')"
                    " ON CONFLICT(asset_id, role) DO UPDATE SET state='on', version=version+1",
                    (asset_id, role),
                )
            elif cur.get(role) == "on":
                self.conn.execute(
                    "UPDATE asset_role SET state='removed_by_user', version=version+1 WHERE asset_id=? AND role=?", (asset_id, role)
                )

    def _write_local_tags(self, sample_id: str, tags: list[str]) -> None:
        self.conn.execute("DELETE FROM sample_tag WHERE sample_id=?", (sample_id,))
        self.conn.executemany("INSERT INTO sample_tag(sample_id, tag) VALUES (?, ?)", [(sample_id, t) for t in tags])
        # 有效标签由 _write 末尾统一重算（effective_tags）

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
