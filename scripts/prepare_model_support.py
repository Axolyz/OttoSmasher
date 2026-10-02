"""Prepare pinned non-weight support files for standard builds (never called at runtime)."""

import hashlib
import io
import json
import urllib.request
import zipfile
from pathlib import Path

root = Path(__file__).resolve().parents[1]
manifest = json.loads((root / "dependencies/model-support.json").read_text())
archives = {}
for item in manifest["files"]:
    path = root / item["path"]
    if path.is_file() and hashlib.sha256(path.read_bytes()).hexdigest() == item["sha256"]:
        continue
    if item.get("member"):
        if item["url"] not in archives:
            archives[item["url"]] = zipfile.ZipFile(
                io.BytesIO(urllib.request.urlopen(item["url"], timeout=60).read())
            )
        data = archives[item["url"]].read(item["member"])
    else:
        data = urllib.request.urlopen(item["url"], timeout=60).read()
    if hashlib.sha256(data).hexdigest() != item["sha256"]:
        raise ValueError("Support checksum changed: " + item["path"])
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
(root / "models/tsqyomi/preparation.json").write_text(
    json.dumps(manifest["tsqyomi"], ensure_ascii=False, indent=2)
)
