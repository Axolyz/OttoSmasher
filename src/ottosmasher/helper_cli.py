from .workspace import CODE_ROOT
"""Composable file/directory operations, without requiring a running GUI."""

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path

from .workspace import ROOT, connect


def handles(argv):
    return bool(argv) and (
        argv[0]
        in {
            "media",
            "library",
            "process",
            "jobs",
            "ui",
            "subtitles",
            "samples",
            "prepare",
        }
        or (argv[0] == "analyze" and len(argv) > 1 and argv[1] in {"phones", "features", "index"})
    )


def main(argv):
    if argv[0] == "prepare":
        from . import preparation_jobs
        from . import source_preparation as prep
        from .operation_jobs import submit

        parser = argparse.ArgumentParser(prog="otto prepare")
        parser.add_argument(
            "action", choices=["list", "register", "configure", "preview", "import", "analysis"]
        )
        parser.add_argument("--json")
        a = parser.parse_args(argv[1:])
        data = json.loads(sys.stdin.read() if a.json == "-" else Path(a.json).read_text()) if a.json else {}
        with connect() as db:
            if a.action == "list":
                out = prep.listing(db)
            elif a.action == "register":
                out = prep.register(db, data["paths"])
            elif a.action == "configure":
                out = prep.configure(db, **data)
            elif a.action == "preview":
                out = prep.preview(db, data["source_id"])
            elif a.action == "import":
                out = prep.ingest(db, data["source_id"], data["token"])
            else:
                out = preparation_jobs.inspect(
                    db,
                    **{
                        k: v
                        for k, v in data.items()
                        if k in ("source_ids", "material_ids", "backends", "vocal_model")
                    },
                )
                if data.get("run"):
                    out = submit("speech-prepare", out)
        print(json.dumps(out, ensure_ascii=False, indent=2))
        return

    if argv[0] == "samples":
        from .sample_cli import main as sample_main

        return sample_main(argv[1:])
    from . import (
        material_operations as ops,
    )
    from . import (
        materials as m,
    )
    from . import (
        media_operations as media,
    )
    from . import (
        operation_jobs as jobs,
    )

    p = argparse.ArgumentParser(prog="otto " + argv[0])
    cmd = argv[0]
    sub = p.add_subparsers(dest="action", required=True)
    if cmd == "ui":
        for action in ("library", "search", "cut", "browser"):
            sub.add_parser(action)
    elif cmd == "media":
        probe = sub.add_parser("probe")
        probe.add_argument("path")
        for action in ("cut", "waveform", "proxy"):
            a = sub.add_parser(action)
            a.add_argument("path")
            a.add_argument("--start", type=float, default=0)
            a.add_argument("--end", type=float)
            a.add_argument("--audio-stream", type=int)
            if action == "cut":
                a.add_argument("--output")
                a.add_argument("--video", action="store_true")
                a.add_argument("--register", action="store_true")
    elif cmd == "library":
        a = sub.add_parser("register")
        a.add_argument("path")
        a.add_argument("--copy", action="store_true")
        a.add_argument("--audio-stream", type=int)
        a = sub.add_parser("manifest")
        a.add_argument("path")
        sub.add_parser("sync")
        a = sub.add_parser("search")
        a.add_argument("text", nargs="?", default="")
        a.add_argument("--collection")
        a.add_argument("--tag", action="append", default=[])
        a.add_argument("--source-id")
        a.add_argument("--limit", type=int, default=50)
        a.add_argument("--offset", type=int, default=0)
        a = sub.add_parser("get")
        a.add_argument("material")
        a = sub.add_parser("edit")
        a.add_argument("material")
        a.add_argument("--json", required=True, help="JSON file, or - for stdin")
        a = sub.add_parser("collection")
        a.add_argument("name")
        a = sub.add_parser("add-to")
        a.add_argument("material")
        a.add_argument("collection")
        a.add_argument("--remove", action="store_true")
        a = sub.add_parser("range")
        a.add_argument("source_id")
        a.add_argument("start", type=float)
        a.add_argument("end", type=float)
        a.add_argument("--title", default="")
        a.add_argument("--audio-stream", type=int)
        a = sub.add_parser("version")
        a.add_argument("material")
        a.add_argument("path")
        a.add_argument("--parent")
        a.add_argument("--operation", default="external")
    elif cmd == "process":
        for action in ("plans", "preview", "reaper"):
            a = sub.add_parser(action)
            a.add_argument("material")
            a.add_argument("--json", required=True)
        a = sub.add_parser("export")
        a.add_argument("material")
        a.add_argument("--plan-id")
        a.add_argument("--version-id")
        a.add_argument("--analysis-kind", default="narabas")
        a.add_argument("--variant", choices=["raw", "vocals"], default="vocals")
        a.add_argument("--video", action="store_true")
        a = sub.add_parser("separate")
        a.add_argument("path", nargs="?")
        a.add_argument("--material-id")
        a.add_argument("--version-id")
        a.add_argument("--output")
        a.add_argument("--model", default="becruily_deux")
        a.add_argument("--device", default="auto")
        a.add_argument("--stem", action="append")
    elif cmd == "jobs":
        sub.add_parser("list")
        for action in ("log", "cancel", "retry"):
            a = sub.add_parser(action)
            a.add_argument("job")
        a = sub.add_parser("submit")
        a.add_argument("operation", choices=sorted(jobs.OPERATIONS))
        a.add_argument("--json", required=True)
    elif cmd == "subtitles":
        for action in ("prepare", "sub-align", "subplz", "all"):
            a = sub.add_parser(action)
            a.add_argument("--source-id")
    elif cmd == "analyze":
        for action in ("phones", "features", "index"):
            a = sub.add_parser(action)
            a.add_argument(
                "--json", required=True, help="Explicit source_ids/material_ids and model selection"
            )
    a = vars(p.parse_args(argv[1:]))
    action = a.pop("action")

    def payload():
        return json.load(sys.stdin) if a["json"] == "-" else json.loads(Path(a["json"]).read_text())

    if cmd == "ui":
        if action == "browser":
            subprocess.run([sys.executable, str(CODE_ROOT / "scripts/refresh_browser.py")], check=True)
            return
        electron = (
            ROOT
            / "desktop/node_modules/electron/dist"
            / (
                "Electron.app/Contents/MacOS/Electron"
                if sys.platform == "darwin"
                else "electron.exe"
                if os.name == "nt"
                else "electron"
            )
        )
        if not electron.exists():
            raise ValueError("请先运行 scripts/setup_desktop.sh")
        child = subprocess.Popen(
            [str(electron), str(CODE_ROOT / "desktop"), "--view=" + action], cwd=ROOT, start_new_session=True
        )
        result = {"pid": child.pid, "view": action}
    elif cmd == "media":
        if action == "probe":
            from .catalog import probe

            result = probe(a["path"])
        else:
            register = a.pop("register", False)
            result = getattr(media, action)(**a)
            if register:
                with connect() as db:
                    result["materials"] = ops.import_manifest(db, result["path"] + ".json")
    elif cmd == "library":
        with connect() as db:
            if action == "register":
                result = m.register_file(db, **a)
            elif action == "get":
                result = m.get(db, a["material"])
            elif action == "sync":
                m.sync_cues(db)
                result = {"synced": True}
            elif action == "search":
                a["tags"] = a.pop("tag")
                result = m.search(db, **a)
            elif action == "edit":
                result = m.edit(db, a["material"], **payload())
            elif action == "collection":
                result = m.collection(db, a["name"])
            elif action == "add-to":
                result = m.membership(db, a["material"], a["collection"], not a["remove"])
            elif action == "range":
                result = m.save_range(db, **a)
            elif action == "manifest":
                result = ops.import_manifest(db, a["path"])
            elif action == "version":
                result = m.add_version(
                    db, a["material"], a["path"], a["operation"], {"imported_external": True}, a["parent"]
                )
    elif cmd == "process":
        if action == "separate":
            a["stems"] = a.pop("stem")
            result = jobs.submit(action, a)
        else:
            with connect() as db:
                if action == "export":
                    mid = a.pop("material")
                    result = ops.export(db, mid, **a)
                else:
                    result = getattr(ops, action)(db, a["material"], payload())
    elif cmd == "jobs":
        if action == "list":
            result = jobs.listing()
        elif action == "submit":
            result = jobs.submit(a["operation"], payload())
        elif action == "log":
            result = {"text": jobs.read_log(a["job"])}
        else:
            result = getattr(jobs, action)(a["job"])
    elif cmd == "analyze":
        data = payload()
        if not data.get("source_ids") and not data.get("material_ids"):
            raise ValueError("请指定 source_ids 或 material_ids；不再运行固定测试语料")
        if action == "phones":
            from .preparation_jobs import inspect

            with connect() as db:
                report = inspect(db, **data)
            result = jobs.submit("speech-prepare", report)
        else:
            from .source_preparation import selected_materials

            with connect() as db:
                selected = selected_materials(db, data.get("source_ids"), data.get("material_ids"))
            result = jobs.submit(
                "acoustic-features" if action == "features" else "sample-prepare", {"material_ids": selected}
            )
    elif cmd == "subtitles":
        result = jobs.submit("subtitles", {"operation": action, **a})
    print(json.dumps(result, ensure_ascii=False, indent=2))
