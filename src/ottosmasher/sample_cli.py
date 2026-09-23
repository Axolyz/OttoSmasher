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
            "folder",
            "flatten",
            "batch-flatten",
            "export",
            "analyze",
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
        if action == "get":
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
        elif action == "folder":
            result = catalog.folder(db, data["name"], data.get("id"))
        elif action == "flatten":
            result = submit("flatten", {"material_id": mid, **data})
        elif action == "batch-flatten":
            result = ops.batch_flatten(db, **data)
        elif action == "export":
            result = ops.export(db, mid, **data)
        elif action == "analyze":
            result = ops.start_analysis(db, mid, **data)
    print(json.dumps(result, ensure_ascii=False, indent=2))
