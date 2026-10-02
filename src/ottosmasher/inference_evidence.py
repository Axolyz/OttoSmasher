"""Local execution evidence keyed by model file and frozen provider policy."""

import json
import os
import tempfile
from pathlib import Path
from .workspace import ROOT, identity


def key(path, provider):
    if isinstance(path, bytes):
        return None
    p = Path(path)
    if not p.is_file():
        return None
    st = p.stat()
    return identity(str(p.resolve()), st.st_size, st.st_mtime_ns, provider)


def record(path, provider, **data):
    token = key(path, provider)
    if not token:
        return
    folder = ROOT / "data/runtime-checks"
    folder.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(dir=folder)
    with os.fdopen(fd, "w") as stream:
        json.dump({"provider": provider, **data}, stream, ensure_ascii=False)
    os.replace(temporary, folder / (token + ".json"))


def read(path, provider):
    token = key(path, provider)
    p = ROOT / "data/runtime-checks" / (str(token) + ".json")
    return json.loads(p.read_text()) if token and p.exists() else {}
