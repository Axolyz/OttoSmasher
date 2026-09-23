from fastapi import APIRouter

from . import ui_catalog
from .cue_operations import database

router = APIRouter(prefix="/api/ui")


@router.get("/settings")
def settings():
    with database() as db:
        return ui_catalog.settings(db)


@router.post("/settings")
def save_settings(body: dict):
    with database() as db:
        before = ui_catalog.settings(db)
        result = ui_catalog.settings(db, body)
        if result["large_number_penalty"] != before["large_number_penalty"]:
            from .operation_jobs import submit

            tables = {r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
            ids = (
                [r[0] for r in db.execute("SELECT DISTINCT material_id FROM sample_records")]
                if "sample_records" in tables
                else []
            )
            for table in ("speech_unit_indices", "rhythm_index"):
                if table in tables:
                    db.execute("DELETE FROM " + table)
            db.commit()
            if ids:
                submit("sample-prepare", {"material_ids": ids})
        return result


@router.post("/catalog")
def catalog(body: dict):
    with database() as db:
        return ui_catalog.listing(db, body)


@router.post("/source-labels")
def labels(body: dict):
    with database() as db:
        ui_catalog.label_source(db, **body)
        return {"ok": True}


@router.post("/tag-rule")
def tag_rule(body: dict):
    with database() as db:
        ui_catalog.ensure(db)
        db.execute(
            "INSERT OR REPLACE INTO tag_rules VALUES(?,?)", (str(body["tag"]), int(bool(body.get("inherit"))))
        )
        db.commit()
        return {"ok": True}


@router.post("/tag-override")
def override(body: dict):
    if body["category"] not in ("work", "type", "character"):
        raise ValueError("未知标签分类")
    with database() as db:
        ui_catalog.ensure(db)
        if not db.execute("SELECT 1 FROM materials WHERE id=?", (body["material_id"],)).fetchone():
            raise ValueError("采样不存在")
        if body.get("reset"):
            db.execute(
                "DELETE FROM tag_overrides WHERE material_id=? AND category=?",
                (body["material_id"], body["category"]),
            )
        else:
            db.execute(
                "INSERT OR REPLACE INTO tag_overrides VALUES(?,?,?)",
                (body["material_id"], body["category"], body.get("value")),
            )
        db.commit()
        return {"ok": True}


@router.get("/storage")
def storage():
    from .cache_storage import status

    with database() as db:
        return status(db)


@router.post("/storage/clean")
def clean_storage():
    from .cache_storage import clean, status

    with database() as db:
        result = clean(db)
        return {**result, "storage": status(db)}
