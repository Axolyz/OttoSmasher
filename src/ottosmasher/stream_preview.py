"""Seekable on-demand previews. Only requested 8-second segments are encoded.

This is a disposable playback adapter, never a sample/export time mapping.
"""

import json
import math
import os
import re
import threading
import uuid
from pathlib import Path

from .workspace import DATA, command, executable, identity, write_json

SEGMENT = 8
CACHE_BYTES = 512 * 1024 * 1024
_encode = threading.RLock()


def register(video, start, end, asset):
    p = Path(video)
    st = p.stat()
    spec = {
        "video": str(p),
        "fingerprint": [st.st_size, st.st_mtime_ns],
        "start": start,
        "end": end,
        "asset": asset,
        "segment": SEGMENT,
        "version": 1,
    }
    key = identity("stream-preview", spec)
    folder = DATA / "cache/streams" / key
    write_json(folder / "source.json", spec)
    return {
        "url": f"/api/helper/streams/{key}/index.m3u8",
        "origin": start,
        "duration": end - start,
        "audio_source": asset["role"],
        "streaming": True,
        "waveform_url": f"/api/helper/streams/{key}/waveform",
    }


def load(key):
    if not re.fullmatch("[a-f0-9]{24}", key):
        raise ValueError("无效播放标识")
    p = DATA / "cache/streams" / key / "source.json"
    spec = json.loads(p.read_text())
    st = Path(spec["video"]).stat()
    if [st.st_size, st.st_mtime_ns] != spec["fingerprint"]:
        raise ValueError("原片已改变，请重新打开")
    return spec


def playlist(key):
    s = load(key)
    duration = s["end"] - s["start"]
    lines = [
        "#EXTM3U",
        "#EXT-X-VERSION:3",
        f"#EXT-X-TARGETDURATION:{SEGMENT}",
        "#EXT-X-PLAYLIST-TYPE:VOD",
        "#EXT-X-MEDIA-SEQUENCE:0",
        "#EXT-X-INDEPENDENT-SEGMENTS",
    ]
    for i in range(math.ceil(duration / SEGMENT)):
        # Independent encodes have independent timestamp epochs and encoder delay.
        # Explicit discontinuities let the media engine rebase each segment.
        if i:
            lines.append("#EXT-X-DISCONTINUITY")
        lines += [f"#EXTINF:{min(SEGMENT, duration - i * SEGMENT):.6f},", f"{i}.ts"]
    return "\n".join(lines + ["#EXT-X-ENDLIST", ""])


def trim_cache(keep):
    files = []
    for p in (DATA / "cache/streams").glob("*/*.ts"):
        try:
            stat = p.stat()
            files.append((stat.st_mtime, stat.st_size, p))
        except FileNotFoundError:
            pass
    size = sum(x[1] for x in files)
    for _, n, p in sorted(files):
        if size <= CACHE_BYTES:
            break
        if p == keep:
            continue
        p.unlink(missing_ok=True)
        size -= n


def segment(key, index):
    s = load(key)
    offset = index * SEGMENT
    duration = s["end"] - s["start"]
    if index < 0 or offset >= duration:
        raise ValueError("播放分片超出范围")
    target = DATA / "cache/streams" / key / f"{index}.ts"
    with _encode:
        if target.is_file():
            os.utime(target, None)
            return target
        a = s["asset"]
        if "path" not in a:
            from .sample_audio import pcm

            a = {**a, "path": str(pcm(a)), "start": 0, "audio_stream": 0}
        args = [
            executable("ffmpeg"),
            "-v",
            "error",
            "-nostdin",
            "-y",
            "-ss",
            str(s["start"] + offset),
            "-i",
            s["video"],
            "-ss",
            str(a["start"] + offset),
            "-i",
            a["path"],
            "-t",
            str(min(SEGMENT, duration - offset)),
            "-map",
            "0:v:0",
            "-map",
            f"1:{a.get('audio_stream', 0)}",
            "-sn",
            "-dn",
            "-vf",
            "scale='min(960,iw)':-2,setpts=PTS-STARTPTS",
            "-af",
            "asetpts=PTS-STARTPTS",
            "-c:v",
            "libx264",
            "-preset",
            "ultrafast",
            "-crf",
            "26",
            "-threads",
            "2",
            "-pix_fmt",
            "yuv420p",
            "-c:a",
            "aac",
            "-b:a",
            "160k",
            "-muxdelay",
            "0",
            "-muxpreload",
            "0",
            "-f",
            "mpegts",
        ]
        temp = target.with_suffix(f".{uuid.uuid4().hex}.tmp")
        try:
            command(args + [str(temp)])
            temp.replace(target)
        finally:
            temp.unlink(missing_ok=True)
        trim_cache(target)
    return target


def waveform(key):
    from .media_operations import waveform as peaks

    s = load(key)
    a = s["asset"]
    if "path" not in a:
        from .sample_audio import pcm

        a = {**a, "path": str(pcm(a)), "start": 0, "end": s["end"] - s["start"], "audio_stream": 0}
    return peaks(a["path"], a["start"], a["end"], a.get("audio_stream", 0), bins=32000)


def segment_bytes(key, index):
    with _encode:
        return segment(key, index).read_bytes()
