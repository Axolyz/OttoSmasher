"""Lazy original-picture thumbnails, bounded decoding independent of speech models."""

import json
import subprocess
import threading
import uuid
from pathlib import Path

from .workspace import DATA, executable, identity

_DECODERS = threading.BoundedSemaphore(2)


def thumbnail(db, mid):
    from .visual_media import effective,position
    binding=effective(db,mid)
    if not binding:return None
    stamp=position(binding,min(binding['audio_duration']/2,(binding.get('root_knots') or [[0,0],[binding['audio_duration'],0]])[-1][0]))
    key=identity('visual-thumb-v2',binding,stamp)
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
                        binding["path"],
                        "-map",
                        f"0:{binding['video_stream']}",
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
