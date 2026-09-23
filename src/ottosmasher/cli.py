from __future__ import annotations

import argparse
import json
from pathlib import Path


def main():
    import sys

    from .helper_cli import handles
    from .helper_cli import main as helper_main

    if handles(sys.argv[1:]):
        try:
            return helper_main(sys.argv[1:])
        except (ValueError, OSError, RuntimeError) as exc:
            print(json.dumps({"error": str(exc)}, ensure_ascii=False), file=sys.stderr)
            raise SystemExit(1)
    parser = argparse.ArgumentParser(prog="otto", description="Local rhythm-aware Japanese dialogue helper")
    commands = parser.add_subparsers(dest="command", required=True)
    ingest = commands.add_parser("import")
    ingest.add_argument("directory", type=Path)
    ingest.add_argument("--audio-stream", type=int)
    commands.add_parser("stats")
    search = commands.add_parser("search")
    search.add_argument("text", nargs="?", default="")
    search.add_argument("--limit", type=int, default=30)
    analyze = commands.add_parser("analyze")
    analyze.add_argument("--limit", type=int)
    analyze.add_argument("--source-id")
    rhythm = commands.add_parser("rhythm")
    rhythm.add_argument("query", type=Path)
    export = commands.add_parser("export")
    export.add_argument("cue_id")
    export.add_argument("--factor", type=float, default=1)
    export.add_argument("--variant", choices=["raw", "vocals"], default="raw")
    serve = commands.add_parser("serve")
    serve.add_argument("--port", type=int, default=8765)
    args = parser.parse_args()
    from .workspace import connect, get_cue, get_speech_analysis, get_vocals_lineage

    if args.command == "import":
        from .catalog import import_directory

        result = import_directory(args.directory, args.audio_stream)
    elif args.command == "analyze":
        from .analysis import run_acoustic

        result = run_acoustic(args.limit, args.source_id, lambda s: print(s, flush=True))
    elif args.command == "serve":
        import uvicorn

        uvicorn.run("ottosmasher.api:app", host="127.0.0.1", port=args.port)
        return
    else:
        db = connect()
        try:
            if args.command == "stats":
                from .catalog import stats

                result = stats(db)
            elif args.command == "search":
                from .catalog import search_text

                result = search_text(db, args.text, limit=args.limit)
            elif args.command == "rhythm":
                from .speech_query import query

                result = query(db, json.loads(args.query.read_text()))
            elif args.command == "export":
                from .media import export_bundle

                result = export_bundle(
                    get_cue(db, args.cue_id),
                    get_speech_analysis(db, args.cue_id, "phonetic"),
                    args.factor,
                    variant=args.variant,
                    lineage=get_vocals_lineage(db, args.cue_id),
                )
        finally:
            db.close()
    print(json.dumps(result, ensure_ascii=False, indent=2))
    if isinstance(result, dict) and (result.get("errors") or result.get("failed")):
        raise SystemExit(1)


if __name__ == "__main__":
    main()
