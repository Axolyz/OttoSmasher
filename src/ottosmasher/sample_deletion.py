"""Explicit catalog removal. Original sources and media files are never deleted."""

import json


def remove(db, ids):
    ids = list(set(ids))
    db.execute("CREATE TABLE IF NOT EXISTS deleted_sample_cues(cue_id TEXT PRIMARY KEY)")
    db.execute("CREATE TEMP TABLE IF NOT EXISTS deleting_samples(id TEXT PRIMARY KEY)")
    db.execute("DELETE FROM deleting_samples")
    db.executemany("INSERT INTO deleting_samples VALUES(?)", [(x,) for x in ids])
    count = db.execute(
        "SELECT count(*) FROM materials WHERE id IN (SELECT id FROM deleting_samples)"
    ).fetchone()[0]
    db.execute(
        "INSERT OR IGNORE INTO deleted_sample_cues SELECT cue_id FROM materials WHERE id IN (SELECT id FROM deleting_samples) AND id=cue_id"
    )
    for edge in db.execute(
        "SELECT * FROM sample_edges WHERE parent_id IN (SELECT id FROM deleting_samples) AND child_id NOT IN (SELECT id FROM deleting_samples)"
    ).fetchall():
        payload = json.loads(edge["payload"])
        payload["deleted_parent"] = dict(
            db.execute("SELECT * FROM materials WHERE id=?", (edge["parent_id"],)).fetchone()
        )
        db.execute(
            "UPDATE sample_edges SET parent_id=NULL,payload=? WHERE child_id=?",
            (json.dumps(payload), edge["child_id"]),
        )
    db.execute("DELETE FROM sample_edges WHERE child_id IN (SELECT id FROM deleting_samples)")
    db.execute(
        "UPDATE material_versions SET parent_id=NULL WHERE parent_id IN (SELECT id FROM material_versions WHERE material_id IN (SELECT id FROM deleting_samples))"
    )
    # Ownership is explicit. Shared assets, annotations and measured runs survive
    # even when a table happens to contain a material_id provenance column.
    owned_tables = (
        "material_tags",
        "material_versions",
        "collection_members",
        "sample_assets",
        "sample_measurements",
        "sample_analysis_status",
        "sample_records",
        "tag_overrides",
        "feature_documents",
        "feature_scalars",
        "speech_unit_indices",
        "native_alignments",
    )
    tables = {r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    for table in owned_tables:
        if table in tables:
            db.execute(f'DELETE FROM "{table}" WHERE material_id IN (SELECT id FROM deleting_samples)')
    if "asset_samples" in tables:
        db.execute("DELETE FROM asset_samples WHERE sample_id IN (SELECT id FROM deleting_samples)")
    if "analysis_references" in tables:
        db.execute(
            "DELETE FROM analysis_references WHERE owner_type='sample' AND owner_id IN (SELECT id FROM deleting_samples)"
        )
    if "visual_bindings" in tables:
        db.execute(
            "DELETE FROM visual_bindings WHERE owner_type='sample' AND owner_id IN (SELECT id FROM deleting_samples)"
        )
    db.execute(
        "DELETE FROM sample_batch_items WHERE candidate_id IN (SELECT id FROM deleting_samples) OR accepted_id IN (SELECT id FROM deleting_samples)"
    )
    db.execute("DELETE FROM materials WHERE id IN (SELECT id FROM deleting_samples)")
    return count


def reset(db):
    if db.execute("SELECT 1 FROM operation_jobs WHERE status IN ('queued','running')").fetchone():
        raise ValueError("请先结束正在运行的任务")
    count = remove(db, [r[0] for r in db.execute("SELECT id FROM materials")])
    # Include never-registered cues: reset must not cause an implicit full import.
    db.execute("INSERT OR IGNORE INTO deleted_sample_cues SELECT id FROM cues")
    for table in (
        "collection_members",
        "collections",
        "sample_batches",
        "sample_batch_items",
        "saved_views",
        "query_results",
    ):
        if db.execute("SELECT 1 FROM sqlite_master WHERE name=?", (table,)).fetchone():
            db.execute(f"DELETE FROM {table}")
    return {"samples": count}
