"""Explicit bounded production jobs; no fixed evaluation corpus dependency."""

import json
import time

from .backends import BACKENDS
from .workspace import connect


def inspect(db, source_ids=None, material_ids=None, backends=None, vocal_model="becruily_deux"):
    from .source_preparation import selected_materials
    from .vocals import VOCAL_MODELS, model_identity

    selected = list(dict.fromkeys(backends or ["narabas"]))
    if not selected or any(k not in BACKENDS for k in selected) or vocal_model not in VOCAL_MODELS:
        raise ValueError("未知对齐或人声模型")
    mids = selected_materials(db, source_ids, material_ids)
    dependencies = []
    for key, env in [
        ("separation", "separation"),
        ("features", "features"),
        *[(b, BACKENDS[b]["env"]) for b in selected],
    ]:
        from .inference_runtime import python_path
        p = python_path()
        dependencies.append(
            {
                "name": key,
                "label": {"separation": "人声分离 · pymss", "features": "音高与能量 · FCPE"}.get(
                    key, BACKENDS.get(key, {}).get("name", key)
                ),
                "path": str(p),
                "ready": p.is_file(),
                "check": "interpreter",
            }
        )
    try:
        model_identity(vocal_model)
    except (ValueError, RuntimeError) as e:
        dependencies.append({"name": vocal_model, "ready": False, "error": str(e)})
    coverage = {b: 0 for b in selected}
    for mid in mids:
        for b in selected:
            row = db.execute(
                "SELECT 1 FROM analyses a JOIN materials m ON m.cue_id=a.cue_id WHERE m.id=? AND a.kind=? AND json_array_length(a.payload,'$.phones')>0 LIMIT 1",
                (mid, b),
            ).fetchone()
            coverage[b] += bool(row)
    return {
        "material_ids": mids,
        "total": len(mids),
        "backends": selected,
        "vocal_model": vocal_model,
        "dependencies": dependencies,
        "coverage": coverage,
    }


def run(p, jid):
    from .alignment_batch import run as batch

    def update(rows):
        progress = {"type": "preparation", "rows": rows, "stage_revision": time.time_ns(), "completed": sum(r["status"] in ("ready", "failed", "excluded") for r in rows), "total": len(p["material_ids"])}
        with connect() as db:
            db.execute("UPDATE operation_jobs SET result=?,updated=? WHERE id=?", (json.dumps(progress), time.time(), jid))
    rows = batch(p["material_ids"], p.get("backends") or ["narabas"], p.get("vocal_model", "becruily_deux"), update, p.get("switch_backend"))
    return {"type": "preparation", "rows": rows, "completed": len(rows), "total": len(p["material_ids"])}
