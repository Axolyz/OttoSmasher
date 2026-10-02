"""Workspace dictionary and shared front-end snapshots, without core ML imports."""

import json
import os
import subprocess
import uuid

from .workspace import CODE_ROOT, DATA, identity, write_json


def dictionary():
    path = DATA / "text-frontend/dictionary.json"
    return (
        json.loads(path.read_text())
        if path.is_file()
        else {"version": "empty", "text": "", "path": None, "entries": 0}
    )


def worker(payload):
    from .inference_runtime import python_path

    folder = DATA / "cache/text-frontend"
    folder.mkdir(parents=True, exist_ok=True)
    request = folder / (uuid.uuid4().hex + ".request.json")
    output = request.with_suffix(".result.json")
    write_json(request, payload)
    try:
        result = subprocess.run(
            [str(python_path()), str(CODE_ROOT / "scripts/g2p_worker.py"), str(request), str(output)],
            env={**os.environ, "PYTHONPATH": str(CODE_ROOT / "src")},
            capture_output=True,
            check=False,
            text=True,
            timeout=300,
        )
        if result.returncode:
            raise ValueError("文本前端失败：" + result.stderr[-3000:])
        return json.loads(output.read_text())
    finally:
        request.unlink(missing_ok=True)
        output.unlink(missing_ok=True)


def save_dictionary(text, base_version):
    from filelock import FileLock

    folder = DATA / "text-frontend"
    folder.mkdir(parents=True, exist_ok=True)
    if dictionary()["version"] != base_version:
        raise ValueError("辞典版本过期，请重新载入")
    compiled = worker({"operation": "compile", "text": text, "folder": str(folder / "dictionaries")})
    with FileLock(str(folder / "dictionary.lock")):
        if dictionary()["version"] != base_version:
            raise ValueError("编译期间辞典已改变，请重新载入")
        write_json(folder / "dictionary.json", compiled)
    return compiled


def batch(texts, frozen_dictionary=None):
    snapshot = dictionary() if frozen_dictionary is None else frozen_dictionary
    return worker({"texts": texts, "dictionary": snapshot["path"]})


def ensure_texts(db):
    db.execute(
        "CREATE TABLE IF NOT EXISTS alignment_texts(annotation_id TEXT PRIMARY KEY,text TEXT NOT NULL,revision INTEGER NOT NULL DEFAULT 1)"
    )


def alignment_text(db, cue):
    ensure_texts(db)
    row = db.execute(
        "SELECT text,revision FROM alignment_texts WHERE annotation_id=?", (cue["id"],)
    ).fetchone()
    original = cue["spoken"]
    from .asset_compat import active

    annotation = (
        db.execute(
            "SELECT text,revision FROM timeline_annotations WHERE id=? AND deleted=0", (cue["id"],)
        ).fetchone()
        if active(db)
        else None
    )
    if annotation:
        from .subtitle_speakers import spoken_text

        original = spoken_text(annotation["text"])
    text = row["text"] if row else original
    return {
        "text": text,
        "version": identity(cue["id"], text, row["revision"] if row else 0),
        "original_matches": text == cue["spoken"],
    }
