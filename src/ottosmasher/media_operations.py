"""File-first media operations. No GUI, HTTP or phone model required."""

from __future__ import annotations

import json
import math
import os
import re
import subprocess
import uuid
from pathlib import Path

import numpy as np

from .catalog import probe
from .workspace import DATA, command, executable, identity, write_json


def safe_title(title):
    return re.sub(r'[\\/:*?"<>|\x00-\x1f]', "_", title).strip(" .")[:90] or "sample"


def source_spec(path, start=0, end=None, audio_stream=None):
    path = Path(path).expanduser().resolve(strict=True)
    info = probe(path)
    duration = float(info["format"]["duration"])
    end = duration if end is None else end
    if not all(math.isfinite(v) for v in (start, end)) or not 0 <= start < end <= duration + 0.002:
        raise ValueError("无效媒体选区")
    tracks = [s for s in info["streams"] if s["codec_type"] == "audio"]
    if audio_stream is None:
        if len(tracks) != 1:
            raise ValueError(f"必须指定音轨：{[s['index'] for s in tracks]}")
        audio_stream = tracks[0]["index"]
    track = next((s for s in tracks if s["index"] == audio_stream), None)
    if track is None:
        raise ValueError("音轨不存在")
    stat = path.stat()
    return {
        "path": str(path),
        "start": start,
        "end": end,
        "audio_stream": audio_stream,
        "sample_rate": int(track["sample_rate"]),
        "channels": track.get("channels"),
        "fingerprint": identity(str(path), stat.st_size, stat.st_mtime_ns),
        "duration": duration,
        "streams": info["streams"],
    }


def cut(path, start=0, end=None, audio_stream=None, *, output=None, video=False, title=None):
    s = source_spec(path, start, end, audio_stream)
    sr = s["sample_rate"]
    first = round(start * sr)
    last = round(s["end"] * sr)
    if first >= last:
        raise ValueError("选区不足一个采样帧")
    key = identity("precise-media-v1", s, video)
    extension = ".mp4" if video else ".wav"
    target = (
        Path(output).expanduser().resolve()
        if output
        else DATA / "media" / "exports" / f"{safe_title(title or Path(path).stem)}__{key[:12]}{extension}"
    )
    manifest_path = target.with_suffix(target.suffix + ".json")
    manifest = {
        "version": "media-file-v1",
        "operation": "video_cut" if video else "audio_cut",
        "source": s,
        "source_start_frame": first,
        "source_end_frame": last,
        "source_sample_rate": sr,
        "source_start": first / sr,
        "source_end": last / sr,
        "audio_stream": s["audio_stream"],
        "time_mapping": {"source_origin": first / sr, "target_origin": 0, "rate": 1},
        "path": str(target),
        "key": key,
    }
    if target.exists():
        if manifest_path.exists() and json.loads(manifest_path.read_text()).get("key") == key:
            from .materials import sha256

            cached = json.loads(manifest_path.read_text())
            if cached.get("sha256") != sha256(target):
                raise ValueError("已有导出文件被修改，请选择新输出路径")
            return cached
        raise ValueError("输出文件已存在，不能覆盖")
    target.parent.mkdir(parents=True, exist_ok=True)
    temp = target.with_name(f".{target.stem}.{uuid.uuid4().hex}.tmp{extension}")
    args = [executable("ffmpeg"), "-v", "error", "-nostdin", "-ss", f"{first / sr:.12f}", "-i", s["path"]]
    if video:
        tracks = [
            t
            for t in s["streams"]
            if t["codec_type"] == "video" and not t.get("disposition", {}).get("attached_pic")
        ]
        if not tracks:
            raise ValueError("此素材没有视频轨道")
        args += [
            "-map",
            f"0:{tracks[0]['index']}",
            "-map",
            f"0:{s['audio_stream']}",
            "-t",
            f"{(last - first) / sr:.12f}",
            "-c:v",
            "libx264",
            "-preset",
            "fast",
            "-crf",
            "18",
            "-pix_fmt",
            "yuv420p",
            "-c:a",
            "aac",
            "-b:a",
            "256k",
            "-movflags",
            "+faststart",
        ]
        manifest["video_boundary"] = (
            "decoded source frames intersecting selection; audio sample clock retained"
        )
    else:
        args += [
            "-map",
            f"0:{s['audio_stream']}",
            "-vn",
            "-af",
            f"atrim=end_sample={last - first},asetpts=PTS-STARTPTS",
            "-c:a",
            "pcm_s24le",
        ]
    try:
        command(args + [str(temp)])
        # Link is an atomic no-overwrite promotion, even for simultaneous exports.
        os.link(temp, target)
    except FileExistsError:
        raise ValueError("另一任务已创建输出，请重新读取")
    finally:
        temp.unlink(missing_ok=True)
    from .materials import sha256

    manifest["sha256"] = sha256(target)
    write_json(manifest_path, manifest)
    return manifest


def waveform(path, start=0, end=None, audio_stream=None, bins=4000):
    s = source_spec(path, start, end, audio_stream)
    bins = max(64, min(32000, int(bins)))
    key = identity("peak-pyramid-v1", s)
    target = DATA / "cache" / "waveforms" / f"{key}.json"
    def selected(result):
        levels = result["peak_levels"]
        result["peaks"] = [next((v for v in levels if len(v) >= bins), levels[-1])]
        return result
    if target.exists():
        return selected(json.loads(target.read_text()))
    width = max(1, math.ceil((s["end"] - start) * 8000 / 32000))
    p = subprocess.Popen(
        [
            executable("ffmpeg"),
            "-v",
            "error",
            "-nostdin",
            "-ss",
            str(start),
            "-t",
            str(s["end"] - start),
            "-i",
            s["path"],
            "-map",
            f"0:{s['audio_stream']}",
            "-vn",
            "-ac",
            "1",
            "-ar",
            "8000",
            "-f",
            "f32le",
            "pipe:1",
        ],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    values = []
    while chunk := p.stdout.read(width * 4):
        values.append(float(np.max(np.abs(np.frombuffer(chunk, dtype="<f4")))))
    error = p.stderr.read().decode()
    p.wait()
    if p.returncode:
        raise ValueError(error[-2000:])
    from .media_visualization import register

    levels = []
    for count in (512,2048,8192,32000):
        step = max(1, math.ceil(len(values)/count))
        level = [max(values[i:i+step]) for i in range(0,len(values),step)]
        if not levels or len(level)!=len(levels[-1]): levels.append(level)
    result = {
        "peaks": [values],
        "peak_levels": levels,
        "duration": s["end"] - start,
        "origin": start,
        "key": key,
        "visualization_key": register(s),
    }
    write_json(target, result)
    return selected(result)


def proxy(path, start=0, end=None, audio_stream=None):
    s = source_spec(path, start, end, audio_stream)
    key = identity("preview-proxy-v1", s)
    target = DATA / "cache" / "proxies" / f"{key}.mp4"
    if not target.exists():
        target.parent.mkdir(parents=True, exist_ok=True)
        temp = target.with_name(f".{key}.{uuid.uuid4().hex}.mp4")
        try:
            command(
                [
                    executable("ffmpeg"),
                    "-v",
                    "error",
                    "-nostdin",
                    "-ss",
                    str(start),
                    "-t",
                    str(s["end"] - start),
                    "-i",
                    s["path"],
                    "-map",
                    "0:v:0",
                    "-map",
                    f"0:{s['audio_stream']}",
                    "-vf",
                    "scale='min(960,iw)':-2",
                    "-c:v",
                    "libx264",
                    "-preset",
                    "ultrafast",
                    "-crf",
                    "26",
                    "-pix_fmt",
                    "yuv420p",
                    "-c:a",
                    "aac",
                    "-movflags",
                    "+faststart",
                    str(temp),
                ]
            )
            os.replace(temp, target)
        finally:
            temp.unlink(missing_ok=True)
    return {
        "key": key,
        "path": str(target),
        "origin": start,
        "duration": s["end"] - start,
        "preview_only": True,
    }
