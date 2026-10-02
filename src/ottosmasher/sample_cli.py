"""JSON-first composable interface to the same operations used by Electron."""

import argparse
import json
import sys
from pathlib import Path

from .workspace import connect


def main(argv):
    p = argparse.ArgumentParser(prog="otto samples")
    p.add_argument(
        "action",
        choices=[
            "get",
            "register",
            "select",
            "preferences",
            "prepare",
            "plans",
            "search",
            "review",
            "flatten",
            "batch-flatten",
            "export",
            "analyze",
            "reanalyse",
            "pitch-query",
            "pitch-index",
            "selection-save",
            "selection-external-import",
            "selection-resolve",
            "selection-descendants",
            "selection-separate",
            "selection-reanalyse",
            "selection-flatten",
            "phone-times-export",
            "phone-times-apply",
            "edit-new-annotation",
            "edit-promote-tags",
            "edit-export",
            "edit-preview",
            "edit-apply",
            "edit-undo",
            "migration-prepare",
            "migration-audit",
            "migration-activate",
        ],
    )
    p.add_argument("material", nargs="?")
    p.add_argument("--json", help="JSON file; - reads stdin")
    args = p.parse_args(argv)
    data = (
        json.loads(sys.stdin.read() if args.json == "-" else Path(args.json).read_text()) if args.json else {}
    )
    from . import materials
    from . import sample_analysis as analysis
    from . import sample_catalog as catalog
    from . import sample_ops as ops
    from . import sample_rhythm as rhythm
    from .operation_jobs import submit

    with connect() as db:
        action = args.action
        mid = args.material
        if action.startswith("selection-"):
            from . import selection_ops

            verb = action.removeprefix("selection-")
            if verb == "resolve":
                selected = (
                    selection_ops.from_source(
                        db, mid, data["start"], data["end"], data.get("role", "raw"), data.get("audio_stream")
                    )
                    if data.get("clock") == "source"
                    else selection_ops.from_sample(
                        db, mid, data.get("start"), data.get("end"), data.get("role")
                    )
                )
                result = selected.json()
            elif verb in {"separate", "flatten"}:
                result = submit(verb, data)
            elif verb == "reanalyse":
                from .reanalysis import submit_selection

                result = submit_selection(db, **data)
            else:
                result = getattr(selection_ops, verb.replace("-", "_"))(db, **data)
        elif action == "pitch-query":
            from .pitch_search import query

            result = query(db, data)
        elif action == "pitch-index":
            from .pitch_indexing import selection_scope

            result = submit("pitch-index", selection_scope(db, data))
        elif action == "phone-times-export":
            from .phone_timing import document

            result = document(db, mid, data.get("backend"))
        elif action == "phone-times-apply":
            from .phone_timing import apply

            result = apply(db, data)
        elif action == "reanalyse":
            from .reanalysis import submit as force_fa

            result = force_fa(db, data.get("ids", [mid] if mid else []), data.get("backend"))
        elif action.startswith("edit-"):
            from . import business_edits

            if action == "edit-promote-tags":
                result = business_edits.promote_tags(db, **data)
            elif action == "edit-new-annotation":
                result = business_edits.new_annotation(db, **data)
            elif action == "edit-export":
                result = business_edits.export(db, data["objects"])
            elif action == "edit-preview":
                result = business_edits.preview(db, data)
            elif action == "edit-apply":
                result = business_edits.apply(db, data)
            else:
                result = business_edits.undo(db, data.get("action_id"))
        elif action.startswith("migration-"):
            from .asset_migration import prepare, audit, activate

            result = (
                prepare(db, **data)
                if action == "migration-prepare"
                else activate(db)
                if action == "migration-activate"
                else audit(db)
            )
        elif action == "get":
            result = materials.get(db, mid)
        elif action == "register":
            result = ops.register(db, **data)
        elif action == "select":
            result = ops.select(db, mid, **data)
        elif action == "preferences":
            catalog.preferences(db, mid, **data)
            result = materials.get(db, mid)
        elif action == "prepare":
            result = analysis.prepare(db, mid)
        elif action == "plans":
            result = rhythm.plans(db, mid, **data)
        elif action == "search":
            from .speech_query import query

            result = query(db, data)
        elif action == "review":
            result = catalog.review(db, data["ids"], data.get("accept", True))
        elif action == "flatten":
            result = submit("flatten", {"material_id": mid, **data})
        elif action == "batch-flatten":
            result = ops.batch_flatten(db, **data)
        elif action == "export":
            result = ops.export(db, mid, **data)
        elif action == "analyze":
            result = ops.start_analysis(db, mid, **data)
    print(json.dumps(result, ensure_ascii=False, indent=2))
