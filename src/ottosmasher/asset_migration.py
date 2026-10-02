"""Non-destructive, repeatable preparation of the unified catalog.

Legacy readers remain authoritative until compatibility writers are migrated.
This preparation deliberately does not set a cutover flag. It can be audited on
an SQLite backup without resolving missing media or running a model.
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
import time
from pathlib import Path

from . import asset_timeline as timeline

VERSION = "asset-catalog-v1-prepared"


def legacy_signature(db):
    digest = hashlib.sha256()
    for table in (
        "sources",
        "materials",
        "cues",
        "sample_assets",
        "sample_measurements",
        "analyses",
        "shared_sample_audio",
        "speaker_annotations",
    ):
        digest.update(table.encode())
        for row in db.execute(f"SELECT * FROM {table} ORDER BY rowid"):
            digest.update(json.dumps(tuple(row), ensure_ascii=False, separators=(",", ":")).encode())
    return digest.hexdigest()


def prepare(db, refresh=False):
    from .asset_compat import active, analysis_selection

    if active(db):
        raise ValueError("工作区已经切换，不能再次准备旧数据迁移")
    timeline.ensure(db)
    previous = db.execute("SELECT payload FROM asset_migrations WHERE id=?", (VERSION,)).fetchone()
    if previous and not refresh:
        return {**json.loads(previous[0]), "already_prepared": True}
    if db.execute("SELECT 1 FROM operation_jobs WHERE status IN ('queued','running')").fetchone():
        raise ValueError("迁移前必须结束排队和运行中的任务")
    if db.in_transaction:
        raise ValueError("迁移必须从没有未提交资料修改的连接启动")
    filename = db.execute("PRAGMA database_list").fetchone()[2]
    backup_path = None
    if filename:
        backup_path = Path(filename).parent / "backups" / f"pre-asset-catalog-{time.time_ns()}.sqlite3"
        backup_path.parent.mkdir(parents=True, exist_ok=True)
        with sqlite3.connect(backup_path) as backup:
            db.backup(backup)
    with db:
        db.execute("BEGIN IMMEDIATE")
        # Recheck under the same writer lock that blocks task submission.
        if db.execute("SELECT 1 FROM operation_jobs WHERE status IN ('queued','running')").fetchone():
            raise ValueError("迁移前必须结束排队和运行中的任务")
        if refresh:
            db.execute("DELETE FROM asset_migrations WHERE id=?", (VERSION,))
        protected = {
            (r["owner_type"], r["owner_id"], r["kind"])
            for r in db.execute(
                "SELECT r.*,a.human,a.payload FROM analysis_references r JOIN analysis_runs a ON a.id=r.run_id"
            )
            if r["human"] or json.loads(r["payload"]).get("clock") == "asset"
        }
        samples = [dict(r) for r in db.execute("SELECT * FROM materials")]
        sources = {r["id"]: dict(r) for r in db.execute("SELECT * FROM sources")}
        descriptors = {r[0]: json.loads(r[1]) for r in db.execute("SELECT * FROM sample_assets")}
        missing_binding = []
        selections = {}
        for sample in samples:
            descriptor = descriptors.get(sample["id"])
            # Unbound cue samples used dynamic vocals discovery. Freeze neither
            # guessed raw mix nor an arbitrary historical model's vocals.
            if not descriptor and sample["cue_id"]:
                missing_binding.append(sample["id"])
                continue
            if not descriptor:
                source = sources[sample["source_id"]]
                descriptor = {
                    "path": source["path"],
                    "start": sample["start"],
                    "end": sample["end"],
                    "audio_stream": sample["audio_stream"],
                    "sha256": source["fingerprint"],
                    "role": "raw",
                    "root_knots": [[0, sample["start"]], [sample["end"] - sample["start"], sample["end"]]],
                    "provenance": {"source_id": source["id"]},
                }
            sel = timeline.register_asset(db, sample["source_id"], descriptor, legacy_mapping=True)
            timeline.bind_sample(db, sample["id"], sel)
            selections[sample["id"]] = sel
            # Only explicit existing roles create groups; no acoustic classifier.
            if descriptor.get("role") == "vocals":
                db.execute("INSERT OR IGNORE INTO asset_groups VALUES(?,?)", (sel.asset_id, "dialogue"))
        for edge in db.execute("SELECT * FROM sample_edges"):
            child = selections.get(edge["child_id"])
            if not child:
                continue
            p = json.loads(edge["payload"])
            descriptor = p.get("parent_audio")
            if not descriptor:
                continue
            sid = db.execute("SELECT source_id FROM sound_assets WHERE id=?", (child.asset_id,)).fetchone()[0]
            parent = timeline.register_asset(db, sid, descriptor, legacy_mapping=True)
            lo, hi = p.get("parent_range", [0, parent.end])
            timeline.selection_asset(db, timeline.AssetSelection(parent.asset_id, lo, hi))
            db.execute(
                "INSERT OR IGNORE INTO asset_inputs VALUES(?,?,?,?,?,?)",
                (child.asset_id, parent.asset_id, lo, hi, edge["operation"], timeline.canonical(p)),
            )
        for cue in db.execute("SELECT * FROM cues"):
            if cue["end"] <= cue["start"] or cue["start"] < 0:
                continue
            scope = (
                {"type": "group", "ids": ["dialogue"]}
                if cue["kind"] == "dialogue"
                else {"type": "source", "ids": []}
            )
            db.execute(
                "INSERT OR IGNORE INTO timeline_annotations VALUES(?,?,?,?,?,?,?,?,1,0)",
                (
                    cue["id"],
                    cue["source_id"],
                    cue["start"],
                    cue["end"],
                    cue["kind"],
                    cue["original"],
                    "[]",
                    timeline.canonical(scope),
                ),
            )
        # Canonical JSON identity shares equal snapshots even with differing
        # whitespace/key order; distinct historical values always survive.
        known = {}
        for row in db.execute("SELECT * FROM analyses ORDER BY created"):
            payload = json.loads(row["payload"])
            rid = timeline.add_analysis(
                db,
                row["kind"],
                row["version"],
                payload,
                selection=analysis_selection(db, row["cue_id"], payload),
            )
            known[(row["kind"], timeline.canonical(payload))] = rid
            if ("annotation", row["cue_id"], row["kind"]) in protected:
                db.execute(
                    "INSERT OR IGNORE INTO analysis_history VALUES('annotation',?,?,?)",
                    (row["cue_id"], row["kind"], rid),
                )
            else:
                timeline.adopt_analysis(db, "annotation", row["cue_id"], row["kind"], rid, automatic=True)
        for row in db.execute("SELECT * FROM sample_measurements"):
            payload = json.loads(row["payload"])
            rid = known.get((row["backend"], timeline.canonical(payload)))
            if not rid:
                cue = db.execute("SELECT cue_id FROM materials WHERE id=?", (row["material_id"],)).fetchone()
                rid = timeline.add_analysis(
                    db,
                    row["backend"],
                    payload.get("version", "legacy-snapshot"),
                    payload,
                    selection=analysis_selection(db, cue[0], payload) if cue and cue[0] else None,
                )
            if ("sample", row["material_id"], row["backend"]) in protected:
                db.execute(
                    "INSERT OR IGNORE INTO analysis_history VALUES('sample',?,?,?)",
                    (row["material_id"], row["backend"], rid),
                )
            else:
                timeline.adopt_analysis(db, "sample", row["material_id"], row["backend"], rid, automatic=True)
        from .timeline_labels import migrate_labels

        migrate_labels(db)
        result = audit(db)
        result["legacy_signature"] = legacy_signature(db)
        result.update(
            {
                "version": VERSION,
                "backup": str(backup_path) if backup_path else None,
                "unresolved_sample_ids": missing_binding,
                "authority": "legacy",
                "prepared_only": True,
            }
        )
        if result["descriptor_mismatches"] or result["snapshot_mismatches"]:
            raise ValueError("资产迁移校验失败：" + timeline.canonical(result))
        db.execute(
            "INSERT INTO asset_migrations VALUES(?,?,?)", (VERSION, timeline.canonical(result), time.time())
        )
    return result


def audit(db):
    archived = bool(db.execute("SELECT 1 FROM sqlite_master WHERE name='legacy_sample_assets'").fetchone())
    descriptor_mismatches = []
    for row in db.execute("SELECT * FROM " + ("legacy_sample_assets" if archived else "sample_assets")):
        binding = db.execute("SELECT * FROM asset_samples WHERE sample_id=?", (row[0],)).fetchone()
        if not binding:
            descriptor_mismatches.append(row[0])
            continue
        restored = timeline.selection_asset(
            db, timeline.AssetSelection(binding["asset_id"], binding["start"], binding["end"])
        )
        original = json.loads(row[1])
        if restored != original:
            descriptor_mismatches.append(row[0])
    snapshot_mismatches = []
    for row in db.execute(
        "SELECT * FROM " + ("legacy_sample_measurements" if archived else "sample_measurements")
    ):
        new = db.execute(
            "SELECT 1 FROM analysis_history h JOIN analysis_runs a ON a.id=h.run_id WHERE owner_type='sample' AND owner_id=? AND h.kind=? AND a.payload=?",
            (row[0], row[1], timeline.canonical(json.loads(row[2]))),
        ).fetchone()
        if not new:
            snapshot_mismatches.append([row[0], row[1]])
    return {
        "samples": db.execute("SELECT count(*) FROM materials").fetchone()[0],
        "bindings": db.execute("SELECT count(*) FROM asset_samples").fetchone()[0],
        "assets": db.execute("SELECT count(*) FROM sound_assets").fetchone()[0],
        "annotations": db.execute("SELECT count(*) FROM timeline_annotations").fetchone()[0],
        "analysis_runs": db.execute("SELECT count(*) FROM analysis_runs").fetchone()[0],
        "analysis_references": db.execute("SELECT count(*) FROM analysis_references").fetchone()[0],
        "descriptor_mismatches": descriptor_mismatches,
        "snapshot_mismatches": snapshot_mismatches,
    }


def activate(db):
    """Switch the three compatibility relations in one transaction after audit."""
    from .asset_compat import ACTIVE, active

    if active(db):
        return {"active": True, "already_active": True}
    prepared = prepare(db)
    if db.in_transaction:
        raise ValueError("切换必须使用独立事务")
    with db:
        db.execute("BEGIN IMMEDIATE")
        if db.execute("SELECT 1 FROM operation_jobs WHERE status IN ('queued','running')").fetchone():
            raise ValueError("切换前必须结束任务")
        if prepared.get("legacy_signature") != legacy_signature(db):
            raise ValueError("迁移准备后旧资料已改变，请使用 migration-prepare 的 refresh=true 重新准备")
        checked = audit(db)
        if checked["descriptor_mismatches"] or checked["snapshot_mismatches"]:
            raise ValueError("准备后资料已改变，请重新校验迁移")
        unresolved = []
        from .sample_audio import resolve

        for sample in db.execute(
            "SELECT * FROM materials WHERE id NOT IN(SELECT sample_id FROM asset_samples)"
        ).fetchall():
            try:
                descriptor = resolve(db, sample["id"])
            except (ValueError, OSError) as exc:
                descriptor = {
                    "start": 0,
                    "end": sample["end"] - sample["start"],
                    "role": "vocals" if sample["cue_id"] else "raw",
                    "root_knots": [[0, sample["start"]], [sample["end"] - sample["start"], sample["end"]]],
                    "missing_reason": str(exc),
                    "provenance": {"source_id": sample["source_id"]},
                }
                unresolved.append(sample["id"])
            selection = timeline.register_asset(db, sample["source_id"], descriptor, legacy_mapping=True)
            timeline.bind_sample(db, sample["id"], selection)
        # Archive values without live foreign keys: deleting a sample must not
        # delete history or be blocked by its immutable archival row.
        for table in ("sample_assets", "sample_measurements", "analyses"):
            db.execute(f"CREATE TABLE legacy_{table} AS SELECT * FROM {table}")
            db.execute(f"DROP TABLE {table}")
            for verb in ("INSERT", "UPDATE", "DELETE"):
                db.execute(
                    f"CREATE TRIGGER legacy_{table}_{verb.lower()} BEFORE {verb} ON legacy_{table} BEGIN SELECT RAISE(ABORT,'legacy data is read-only'); END"
                )
        db.execute("""CREATE VIEW sample_assets AS SELECT s.sample_id AS material_id,
            asset_descriptor(a.descriptor,s.start,s.end) AS payload FROM asset_samples s JOIN sound_assets a ON a.id=s.asset_id""")
        db.execute("""CREATE VIEW sample_measurements AS SELECT r.owner_id AS material_id,r.kind AS backend,a.payload
            FROM analysis_references r JOIN analysis_runs a ON a.id=r.run_id WHERE r.owner_type='sample' """)
        db.execute("""CREATE VIEW analyses AS SELECT h.owner_id AS cue_id,h.kind AS kind,a.signature AS version,a.payload,a.created
            FROM analysis_history h JOIN analysis_runs a ON a.id=h.run_id WHERE h.owner_type='annotation' """)
        result = {
            "active": True,
            "unresolved_sample_ids": unresolved,
            "samples": checked["samples"],
            "legacy_read_only": True,
            "backup": prepared["backup"],
        }
        db.execute(
            "INSERT INTO asset_migrations VALUES(?,?,?)", (ACTIVE, timeline.canonical(result), time.time())
        )
    return result
