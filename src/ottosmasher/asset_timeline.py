"""Asset selections, exact clocks and immutable measurements.

No inference or file materialization occurs here. A persisted selection is never
moved by an annotation edit. Migration is explicit until all compatibility
writers have been switched; opening a workspace only installs empty tables.
"""

from __future__ import annotations

import bisect
import json
import math
import time
from dataclasses import asdict, dataclass
from itertools import pairwise

from .workspace import identity


def canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)


@dataclass(frozen=True)
class AssetSelection:
    asset_id: str
    start: float
    end: float

    def __post_init__(self):
        if (
            not self.asset_id
            or not all(math.isfinite(x) for x in (self.start, self.end))
            or not 0 <= self.start < self.end
        ):
            raise ValueError("资产选区必须是有限的半开区间 [start,end)")

    def json(self):
        return asdict(self)


def ensure(db):
    db.create_function("asset_descriptor", 3, descriptor_range, deterministic=True)
    # Do not use executescript: it commits an enclosing application transaction.
    statements = [
        """CREATE TABLE IF NOT EXISTS sound_assets(
          id TEXT PRIMARY KEY,source_id TEXT NOT NULL,descriptor TEXT NOT NULL,
          duration REAL NOT NULL CHECK(duration>0),mapping TEXT,content_key TEXT,
          created REAL NOT NULL)""",
        """CREATE TABLE IF NOT EXISTS asset_inputs(
          asset_id TEXT NOT NULL REFERENCES sound_assets(id),input_asset_id TEXT NOT NULL REFERENCES sound_assets(id),
          start REAL NOT NULL,end REAL NOT NULL,operation TEXT NOT NULL,parameters TEXT NOT NULL,
          PRIMARY KEY(asset_id,input_asset_id,start,end))""",
        """CREATE TABLE IF NOT EXISTS asset_samples(
          sample_id TEXT PRIMARY KEY REFERENCES materials(id),asset_id TEXT NOT NULL REFERENCES sound_assets(id),
          start REAL NOT NULL,end REAL NOT NULL,revision INTEGER NOT NULL DEFAULT 1,
          CHECK(start>=0 AND end>start))""",
        "CREATE INDEX IF NOT EXISTS sound_asset_content ON sound_assets(json_extract(descriptor,'$.path'),json_extract(descriptor,'$.sha256'))",
        "CREATE INDEX IF NOT EXISTS sound_asset_clip_parent ON sound_assets(json_extract(descriptor,'$.provenance.full_source_asset.path'),json_extract(descriptor,'$.provenance.full_source_asset.sha256'))",
        "CREATE INDEX IF NOT EXISTS asset_sample_range ON asset_samples(asset_id,start,end)",
        """CREATE TABLE IF NOT EXISTS asset_groups(
          asset_id TEXT NOT NULL REFERENCES sound_assets(id),group_name TEXT NOT NULL,
          PRIMARY KEY(asset_id,group_name))""",
        """CREATE TABLE IF NOT EXISTS timeline_annotations(
          id TEXT PRIMARY KEY,source_id TEXT NOT NULL,start REAL NOT NULL,end REAL NOT NULL,
          kind TEXT NOT NULL,text TEXT NOT NULL,tags TEXT NOT NULL,scope TEXT NOT NULL,
          revision INTEGER NOT NULL DEFAULT 1,deleted INTEGER NOT NULL DEFAULT 0,
          CHECK(start>=0 AND end>start))""",
        "CREATE INDEX IF NOT EXISTS timeline_source_range ON timeline_annotations(source_id,start,end)",
        """CREATE TABLE IF NOT EXISTS analysis_runs(
          id TEXT PRIMARY KEY,asset_id TEXT REFERENCES sound_assets(id),start REAL,end REAL,
          kind TEXT NOT NULL,signature TEXT NOT NULL,text_revision TEXT,payload TEXT NOT NULL,
          human INTEGER NOT NULL DEFAULT 0,parent_id TEXT REFERENCES analysis_runs(id),created REAL NOT NULL)""",
        "CREATE INDEX IF NOT EXISTS analysis_asset_range ON analysis_runs(asset_id,kind,start,end)",
        """CREATE TABLE IF NOT EXISTS analysis_references(
          owner_type TEXT NOT NULL,owner_id TEXT NOT NULL,kind TEXT NOT NULL,run_id TEXT NOT NULL REFERENCES analysis_runs(id),
          revision INTEGER NOT NULL DEFAULT 1,PRIMARY KEY(owner_type,owner_id,kind))""",
        "CREATE INDEX IF NOT EXISTS analysis_reference_run ON analysis_references(run_id,owner_type)",
        """CREATE TABLE IF NOT EXISTS analysis_history(
          owner_type TEXT NOT NULL,owner_id TEXT NOT NULL,kind TEXT NOT NULL,run_id TEXT NOT NULL REFERENCES analysis_runs(id),
          PRIMARY KEY(owner_type,owner_id,kind,run_id))""",
        """CREATE TABLE IF NOT EXISTS visual_bindings(
          owner_type TEXT NOT NULL,owner_id TEXT NOT NULL,payload TEXT NOT NULL,revision INTEGER NOT NULL DEFAULT 1,
          PRIMARY KEY(owner_type,owner_id))""",
        "CREATE TABLE IF NOT EXISTS asset_migrations(id TEXT PRIMARY KEY,payload TEXT NOT NULL,created REAL NOT NULL)",
    ]
    for statement in statements:
        db.execute(statement)
    for table in ("sound_assets", "asset_inputs", "analysis_runs"):
        for verb in ("UPDATE", "DELETE"):
            db.execute(
                f"CREATE TRIGGER IF NOT EXISTS immutable_{table}_{verb.lower()} BEFORE {verb} ON {table} BEGIN SELECT RAISE(ABORT,'immutable asset or analysis'); END"
            )


def descriptor_range(encoded, start, end):
    descriptor = json.loads(encoded)
    duration = descriptor["end"] - descriptor["start"]
    if start == 0 and end == duration:
        return encoded
    knots = descriptor.get("root_knots")
    if knots:
        descriptor["root_knots"] = [
            [0, map_time(knots, start)],
            *[[x - start, y] for x, y in knots if start < x < end],
            [end - start, map_time(knots, end)],
        ]
    descriptor.update(start=descriptor["start"] + start, end=descriptor["start"] + end)
    return canonical(descriptor)


def validate_mapping(knots, duration, *, allow_partial=False):
    if knots is None:
        return None
    if len(knots) < 2:
        raise ValueError("时间映射至少需要两个点")
    result = [[float(x), float(y)] for x, y in knots]
    if any(not math.isfinite(n) for p in result for n in p):
        raise ValueError("时间映射必须为有限数")
    if abs(result[0][0]) > 1e-8 or (not allow_partial and abs(result[-1][0] - duration) > 1e-6):
        raise ValueError("时间映射必须覆盖完整资产")
    if result[0][1] < 0 or any(x1 >= x2 or y1 >= y2 for (x1, y1), (x2, y2) in pairwise(result)):
        raise ValueError("时间映射必须严格递增")
    return result


def map_time(knots, value, *, inverse=False):
    """Interpolate only within recorded coverage; never extrapolate/clamp silently."""
    points = [(y, x) if inverse else (x, y) for x, y in knots]
    x, y = zip(*points)
    if not math.isfinite(value) or not x[0] <= value <= x[-1]:
        raise ValueError("时间不在精确映射覆盖范围内")
    i = min(max(bisect.bisect_right(x, value) - 1, 0), len(x) - 2)
    return y[i] + (value - x[i]) * (y[i + 1] - y[i]) / (x[i + 1] - x[i])


def register_asset(
    db,
    source_id,
    descriptor,
    *,
    input_selection=None,
    operation="import",
    parameters=None,
    legacy_mapping=False,
):
    """A descriptor's file range becomes an asset-local clock starting at zero.

    Conservatively share only identical descriptors AND mappings. Content-based
    index reuse is independent; equal bytes are not sufficient lineage identity.
    """
    descriptor = json.loads(canonical(descriptor))
    from .source_locations import original_path

    if descriptor.get("path"):
        descriptor["path"] = original_path(db, descriptor["path"])
    from pathlib import Path
    from .workspace import DATA

    path = Path(descriptor.get("path", ""))
    if (
        path.is_file()
        and path.is_relative_to(DATA / "media")
        and not path.is_relative_to(DATA / "media/exports")
        and path.suffix.lower() in (".wav", ".flac")
        and (
            operation in ("flatten", "separation", "external-import", "quantized")
            or descriptor.get("role") in ("flattened", "warped")
        )
    ):
        from .audio_storage import durable
        from .materials import sha256
        import shutil

        compact = durable(path, data_root=DATA)
        features = path.with_suffix(".features.json")
        if features.is_file() and not compact.with_suffix(".features.json").exists():
            shutil.copyfile(features, compact.with_suffix(".features.json"))
        descriptor.update(path=str(compact), sha256=sha256(compact))
    duration = float(descriptor["end"]) - float(descriptor["start"])
    AssetSelection("validation", 0, duration)
    knots = validate_mapping(descriptor.get("root_knots"), duration, allow_partial=legacy_mapping)
    aid = identity(
        "sound-asset-v1",
        source_id,
        descriptor,
        input_selection.json() if input_selection else None,
        operation,
        parameters or {},
    )
    inserted = db.execute(
        "INSERT OR IGNORE INTO sound_assets VALUES(?,?,?,?,?,?,?)",
        (
            aid,
            source_id,
            canonical(descriptor),
            duration,
            canonical(knots) if knots else None,
            descriptor.get("sha256"),
            time.time(),
        ),
    )
    if input_selection:
        selection_asset(db, input_selection)
        if input_selection.asset_id == aid:
            raise ValueError("资产不能来自自身")
        db.execute(
            "INSERT OR IGNORE INTO asset_inputs VALUES(?,?,?,?,?,?)",
            (
                aid,
                input_selection.asset_id,
                input_selection.start,
                input_selection.end,
                operation,
                canonical(parameters or {}),
            ),
        )
        if inserted.rowcount and operation in {"flatten", "external-import", "quantized"}:
            db.execute(
                "INSERT OR IGNORE INTO asset_groups SELECT ?,group_name FROM asset_groups WHERE asset_id=?",
                (aid, input_selection.asset_id),
            )
    if inserted.rowcount and str(descriptor.get("role", "")).casefold() == "vocals":
        db.execute("INSERT OR IGNORE INTO asset_groups VALUES(?,'dialogue')", (aid,))
    return AssetSelection(aid, 0, duration)


def selection_asset(db, selection: AssetSelection):
    row = db.execute("SELECT * FROM sound_assets WHERE id=?", (selection.asset_id,)).fetchone()
    if not row:
        raise ValueError("声音资产不存在")
    if selection.end > row["duration"]:
        raise ValueError("选区超出资产范围")
    from .source_locations import resolve_descriptor

    descriptor = resolve_descriptor(db, row["source_id"], json.loads(row["descriptor"]))
    if selection.start == 0 and selection.end == row["duration"]:
        return descriptor
    knots = json.loads(row["mapping"]) if row["mapping"] else None
    if knots:
        cropped = [
            [selection.start, map_time(knots, selection.start)],
            *[p for p in knots if selection.start < p[0] < selection.end],
            [selection.end, map_time(knots, selection.end)],
        ]
        descriptor["root_knots"] = [[x - selection.start, y] for x, y in cropped]
    return {
        **descriptor,
        "start": descriptor["start"] + selection.start,
        "end": descriptor["start"] + selection.end,
    }


def bind_sample(db, sample_id, selection):
    selection_asset(db, selection)
    db.execute(
        """INSERT INTO asset_samples(sample_id,asset_id,start,end) VALUES(?,?,?,?)
      ON CONFLICT(sample_id) DO UPDATE SET asset_id=excluded.asset_id,start=excluded.start,end=excluded.end,revision=revision+1""",
        (sample_id, selection.asset_id, selection.start, selection.end),
    )


def sample_selection(db, sample_id):
    row = db.execute(
        "SELECT asset_id,start,end FROM asset_samples WHERE sample_id=?", (sample_id,)
    ).fetchone()
    if not row:
        raise ValueError("采样尚未迁移到统一资产")
    return AssetSelection(**dict(row))


def add_analysis(
    db, kind, signature, payload, *, selection=None, text_revision=None, human=False, parent_id=None
):
    if selection:
        selection_asset(db, selection)
    rid = identity(
        "analysis-run-v1",
        kind,
        signature,
        payload,
        selection.json() if selection else None,
        text_revision,
        human,
        parent_id,
    )
    db.execute(
        "INSERT OR IGNORE INTO analysis_runs VALUES(?,?,?,?,?,?,?,?,?,?,?)",
        (
            rid,
            selection.asset_id if selection else None,
            selection.start if selection else None,
            selection.end if selection else None,
            kind,
            signature,
            text_revision,
            canonical(payload),
            int(human),
            parent_id,
            time.time(),
        ),
    )
    return rid


def adopt_analysis(db, owner_type, owner_id, kind, run_id, *, expected_revision=None, automatic=False):
    run = db.execute("SELECT kind FROM analysis_runs WHERE id=?", (run_id,)).fetchone()
    if not run or run[0] != kind:
        raise ValueError("分析版本与模型不匹配")
    current = db.execute(
        """SELECT r.revision,a.human FROM analysis_references r JOIN analysis_runs a ON a.id=r.run_id
        WHERE owner_type=? AND owner_id=? AND r.kind=?""",
        (owner_type, owner_id, kind),
    ).fetchone()
    db.execute("INSERT OR IGNORE INTO analysis_history VALUES(?,?,?,?)", (owner_type, owner_id, kind, run_id))
    revision = current["revision"] if current else 0
    if expected_revision is not None and expected_revision != revision:
        return {"adopted": False, "reason": "stale", "revision": revision}
    if automatic and current and current["human"]:
        return {"adopted": False, "reason": "human_timing", "revision": revision}
    db.execute(
        """INSERT INTO analysis_references VALUES(?,?,?,?,1) ON CONFLICT(owner_type,owner_id,kind)
      DO UPDATE SET run_id=excluded.run_id,revision=revision+1""",
        (owner_type, owner_id, kind, run_id),
    )
    return {"adopted": True, "revision": revision + 1}


def validate_scope(scope):
    if not isinstance(scope, dict) or set(scope) - {"type", "ids"}:
        raise ValueError("标注范围只接受 type 和 ids")
    if scope.get("type") not in {"source", "group", "asset"}:
        raise ValueError("标注范围应为 source/group/asset")
    ids = scope.get("ids", [])
    if (
        not isinstance(ids, list)
        or any(not isinstance(x, str) or not x for x in ids)
        or (scope["type"] != "source" and not ids)
    ):
        raise ValueError("轨道组或资产范围必须明确给出 ids")
    if scope["type"] == "source" and ids:
        raise ValueError("原片全范围不接受 ids")
    return {"type": scope["type"], "ids": sorted(set(ids))}


def annotations_for(db, selection, *, kinds=None):
    asset = db.execute("SELECT * FROM sound_assets WHERE id=?", (selection.asset_id,)).fetchone()
    selection_asset(db, selection)
    groups = {
        r[0]
        for r in db.execute("SELECT group_name FROM asset_groups WHERE asset_id=?", (selection.asset_id,))
    }
    knots = json.loads(asset["mapping"]) if asset["mapping"] else None
    result = []
    for row in db.execute(
        "SELECT * FROM timeline_annotations WHERE source_id=? AND deleted=0", (asset["source_id"],)
    ):
        a = dict(row)
        scope = json.loads(a["scope"])
        if kinds and a["kind"] not in kinds:
            continue
        if scope["type"] == "asset":
            if selection.asset_id not in scope["ids"]:
                continue
            lo, hi = selection.start, selection.end
        else:
            if not knots or (scope["type"] == "group" and not groups.intersection(scope["ids"])):
                continue
            # Some legacy descriptors include a rounding tail beyond their
            # recorded mapping. Only the known portion can inherit tags.
            start, end = max(selection.start, knots[0][0]), min(selection.end, knots[-1][0])
            if end <= start:
                continue
            lo, hi = map_time(knots, start), map_time(knots, end)
        if a["start"] < hi and a["end"] > lo:
            a["scope"] = scope
            a["tags"] = json.loads(a["tags"])
            result.append(a)
    return sorted(result, key=lambda a: (a["start"], a["end"], a["id"]))
