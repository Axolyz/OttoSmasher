from .workspace import CODE_ROOT
"""Shared local-only alignment dispatch; no silent model replacement."""

from .backends import BACKENDS
from .workspace import ROOT


def worker_command(folder, backend, limit=200, retry=False, exclude_regions=True):
    if backend not in BACKENDS:
        raise ValueError(f"不可运行的对齐后端：{backend}")
    spec = BACKENDS[backend]
    from .inference_runtime import python_path
    python = python_path()
    if not python.is_file():
        raise ValueError(f"{spec['name']} 环境尚未安装")
    excluded = []
    if exclude_regions and (folder / "manifest.json").exists():
        import json

        from .source_regions import blocked
        from .workspace import connect, get_cue

        with connect() as db:
            for c in json.loads((folder / "manifest.json").read_text())["cues"][:limit]:
                row = get_cue(db, c["id"])
                if blocked(db, row["source_id"], row["start"], row["end"]):
                    excluded.append(row["id"])
    script = "compare_worker.py"
    return [
        str(python),
        str(CODE_ROOT / "scripts" / script),
        str(folder),
        backend,
        "--limit",
        str(limit),
        *(["--retry"] if retry else []),
        *(["--exclude-cues", ",".join(excluded)] if excluded else []),
    ]
