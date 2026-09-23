"""Lazy original-picture thumbnails, bounded decoding independent of speech models."""

import json
import subprocess
import threading
import uuid
from pathlib import Path

from .workspace import DATA, executable, identity

_DECODERS = threading.BoundedSemaphore(2)


def thumbnail(db, mid):
    row = db.execute(
        "SELECT m.start,m.end,s.path,s.fingerprint,s.metadata FROM materials m JOIN sources s ON s.id=m.source_id WHERE m.id=?",
        (mid,),
    ).fetchone()
    if not row:
        raise ValueError("采样不存在")
    videos = [
        v
        for v in json.loads(row["metadata"])["streams"]
        if v["codec_type"] == "video" and not v.get("disposition", {}).get("attached_pic")
    ]
    if not videos or not Path(row["path"]).is_file():
        return None
    start, end = row["start"], row["end"]
    stored = db.execute("SELECT payload FROM sample_assets WHERE material_id=?", (mid,)).fetchone()
    if stored:
        knots = json.loads(stored[0]).get("root_knots")
        if knots:
            start, end = knots[0][1], knots[-1][1]
    stamp = (start + end) / 2
    stat = Path(row["path"]).stat()
    key = identity("sample-thumb-v1", row["fingerprint"], stat.st_mtime_ns, stamp, videos[0]["index"])
    out = DATA / "cache/thumbnails" / (key + ".jpg")
    with _DECODERS:
        if not out.exists():
            out.parent.mkdir(parents=True, exist_ok=True)
            tmp = out.with_name(out.stem + "." + uuid.uuid4().hex + ".partial.jpg")
            try:
                subprocess.run(
                    [
                        executable("ffmpeg"),
                        "-v",
                        "error",
                        "-nostdin",
                        "-y",
                        "-ss",
                        str(stamp),
                        "-i",
                        row["path"],
                        "-map",
                        f"0:{videos[0]['index']}",
                        "-frames:v",
                        "1",
                        "-vf",
                        "scale=192:-2",
                        "-threads",
                        "1",
                        "-q:v",
                        "4",
                        str(tmp),
                    ],
                    check=True,
                    timeout=30,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.PIPE,
                )
                if not tmp.is_file() or not tmp.stat().st_size:
                    return None
                tmp.replace(out)
            finally:
                tmp.unlink(missing_ok=True)
    return out
