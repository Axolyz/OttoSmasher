#!/usr/bin/env python3
"""Resume the source-pattern index without rerunning separation/alignment."""

import argparse
import json

from ottosmasher.rhythm_index import rebuild_index
from ottosmasher.workspace import ROOT, connect, write_json

parser = argparse.ArgumentParser()
parser.add_argument(
    "--models",
    nargs="+",
    choices=["narabas", "phonetic", "pydomino"],
    default=["narabas", "phonetic", "pydomino"],
)
args = parser.parse_args()
report = {}
with connect() as db:
    for kind in args.models:

        def progress(s, kind=kind):
            if s["cues"] % 25 == 0:
                print(
                    f"{kind}: {s['cues']} cues, {s['scopes']} scopes, {len(s['errors'])} errors", flush=True
                )

        report[kind] = rebuild_index(db, kind, progress)
        print(json.dumps({k: v for k, v in report[kind].items() if k != "errors"}), flush=True)
        write_json(ROOT / "outputs/validation/rhythm-index-v1.json", report)
