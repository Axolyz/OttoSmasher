"""Visual bindings follow the audio clock; media identity is never inferred from names."""

import json
import math
import re
import subprocess
import uuid
from pathlib import Path

from filelock import FileLock

from .asset_timeline import canonical, map_time
from .workspace import DATA, executable, identity, write_json


def editable(db, kind, oid):
    owner = "sample" if kind == "sample_visual" else "source"
    table = "materials" if owner == "sample" else "sources"
    if not db.execute(f"SELECT 1 FROM {table} WHERE id=?", (oid,)).fetchone():
        raise ValueError("画面归属对象不存在")
    row = db.execute(
        "SELECT payload FROM visual_bindings WHERE owner_type=? AND owner_id=?", (owner, oid)
    ).fetchone()
    data = json.loads(row[0]) if row else {}
    return {"mode": data.get("mode"), "path": data.get("path", "")}


def validate(value):
    if set(value) != {"mode", "path"}:
        raise ValueError("画面只接受 mode/path")
    if value["mode"] is None:
        if value["path"]:
            raise ValueError("恢复默认时 path 应为空")
        return value
    if value["mode"] not in {"sync", "image", "local_loop"}:
        raise ValueError("画面模式应为 sync/image/local_loop 或 null")
    path = Path(value["path"]).expanduser().resolve(strict=True)
    from .catalog import probe

    metadata = probe(str(path))
    streams = [s for s in metadata["streams"] if s["codec_type"] == "video"]
    if not streams:
        raise ValueError("画面文件没有可显示的视频或图片")
    duration = float(metadata.get("format", {}).get("duration") or streams[0].get("duration") or 0)
    if value["mode"] != "image" and (not math.isfinite(duration) or duration <= 0):
        raise ValueError("动画或同步视频必须有确定时长")
    if value["mode"] == "image" and path.suffix.lower() not in {
        ".png",
        ".jpg",
        ".jpeg",
        ".webp",
        ".bmp",
        ".tif",
        ".tiff",
        ".avif",
    }:
        raise ValueError("image 模式需要静态图片；动画请用 local_loop")
    return {"mode": value["mode"], "path": str(path)}


def write(db, kind, oid, value):
    owner = "sample" if kind == "sample_visual" else "source"
    if value["mode"] is None:
        db.execute("DELETE FROM visual_bindings WHERE owner_type=? AND owner_id=?", (owner, oid))
        return
    from .catalog import probe

    path = Path(value["path"])
    stat = path.stat()
    metadata = probe(str(path))
    video = next(s for s in metadata["streams"] if s["codec_type"] == "video")
    payload = {
        **value,
        "file_stat": [stat.st_size, stat.st_mtime_ns],
        "video_stream": video["index"],
        "duration": float(metadata.get("format", {}).get("duration") or video.get("duration") or 0),
    }
    db.execute(
        "INSERT INTO visual_bindings VALUES(?,?,?,1) ON CONFLICT(owner_type,owner_id) DO UPDATE SET payload=excluded.payload,revision=revision+1",
        (owner, oid, canonical(payload)),
    )


def effective(db, mid, role=None):
    sample = db.execute(
        "SELECT m.source_id,s.path,s.metadata FROM materials m JOIN sources s ON s.id=m.source_id WHERE m.id=?",
        (mid,),
    ).fetchone()
    if not sample:
        raise ValueError("采样不存在")
    for kind, oid in [("sample", mid), ("source", sample["source_id"])]:
        row = db.execute(
            "SELECT payload FROM visual_bindings WHERE owner_type=? AND owner_id=?", (kind, oid)
        ).fetchone()
        if row:
            result = json.loads(row[0])
            result["inherited"] = kind == "source"
            break
    else:
        metadata = json.loads(sample["metadata"])
        video = next(
            (
                s
                for s in metadata["streams"]
                if s["codec_type"] == "video" and not s.get("disposition", {}).get("attached_pic")
            ),
            None,
        )
        if not video:
            return None
        stat = Path(sample["path"]).stat()
        result = {
            "mode": "sync",
            "path": sample["path"],
            "file_stat": [stat.st_size, stat.st_mtime_ns],
            "video_stream": video["index"],
            "duration": float(metadata.get("format", {}).get("duration") or video.get("duration") or 0),
            "inherited": True,
            "is_default": True,
        }
    stat = Path(result["path"]).stat()
    if [stat.st_size, stat.st_mtime_ns] != result["file_stat"]:
        raise ValueError("绑定画面文件已改变，请重新保存画面绑定")
    from .sample_audio import resolve

    audio = resolve(db, mid, role)
    result["audio_duration"] = audio["end"] - audio["start"]
    result["root_knots"] = audio.get("root_knots")
    if result["mode"] == "sync":
        if not result["root_knots"]:
            raise ValueError("当前声音没有精确来源时间映射，不能同步视频")
        if result["duration"] and result["root_knots"][-1][1] > result["duration"] + 1e-5:
            raise ValueError("同步选区超出画面时长")
    return result


def position(binding, local_time):
    if binding["mode"] == "image":
        return 0.0
    if binding["mode"] == "local_loop":
        return local_time % binding["duration"]
    return map_time(binding["root_knots"], local_time)


def register(binding):
    key = identity("visual-file-v1", binding)
    write_json(DATA / "cache/visuals" / (key + ".json"), binding)
    return key


def load(key):
    if not re.fullmatch("[a-f0-9]{24}", key):
        raise ValueError("无效画面标识")
    data = json.loads((DATA / "cache/visuals" / (key + ".json")).read_text())
    stat = Path(data["path"]).stat()
    if [stat.st_size, stat.st_mtime_ns] != data["file_stat"]:
        raise ValueError("画面文件已改变")
    return data


def browser_file(key):
    data = load(key)
    if data["mode"] == "image":
        target = DATA / "cache/visuals" / (key + ".png")
        with FileLock(str(target) + ".lock"):
            if not target.exists():
                tmp = target.with_name(key + "." + uuid.uuid4().hex + ".tmp.png")
                try:
                    subprocess.run(
                        [
                            executable("ffmpeg"),
                            "-v",
                            "error",
                            "-nostdin",
                            "-y",
                            "-i",
                            data["path"],
                            "-frames:v",
                            "1",
                            str(tmp),
                        ],
                        check=True,
                        stdout=subprocess.DEVNULL,
                        stderr=subprocess.PIPE,
                    )
                    tmp.replace(target)
                finally:
                    tmp.unlink(missing_ok=True)
        return target
    target = DATA / "cache/visuals" / (key + ".mp4")
    with FileLock(str(target) + ".lock"):
        if not target.exists():
            lo, hi = (
                (data["root_knots"][0][1], data["root_knots"][-1][1])
                if data["mode"] == "sync"
                else (0, data["duration"])
            )
            tmp = target.with_name(key + "." + uuid.uuid4().hex + ".tmp.mp4")
            try:
                subprocess.run(
                    [
                        executable("ffmpeg"),
                        "-v",
                        "error",
                        "-nostdin",
                        "-y",
                        "-ss",
                        str(lo),
                        "-t",
                        str(hi - lo),
                        "-i",
                        data["path"],
                        "-map",
                        f"0:{data['video_stream']}",
                        "-an",
                        "-vf",
                        "scale='min(960,iw)':-2",
                        "-c:v",
                        "libx264",
                        "-preset",
                        "ultrafast",
                        "-crf",
                        "25",
                        "-pix_fmt",
                        "yuv420p",
                        "-movflags",
                        "+faststart",
                        str(tmp),
                    ],
                    check=True,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.PIPE,
                )
                tmp.replace(target)
            finally:
                tmp.unlink(missing_ok=True)
    return target


def playback(db, mid, native=False, role=None):
    binding = effective(db, mid, role)
    if not binding:
        return None
    key = register(binding)
    native = native and binding["mode"] != "image"
    origin = binding["root_knots"][0][1] if binding["mode"] == "sync" and not native else 0
    return {
        **binding,
        "url": f"/api/samples/visual-native/{key}" if native else f"/api/samples/visual-file/{key}",
        "video_origin": origin,
    }


def export(db, mid):
    from .sample_audio import pcm, resolve

    binding = effective(db, mid)
    if not binding:
        raise ValueError("原片及采样均未绑定画面")
    audio = resolve(db, mid)
    path = pcm(audio)
    manifest = {
        "schema": "otto.pv/1",
        "sample_id": mid,
        "audio_file": str(path),
        "audio_asset": audio,
        "visual": binding,
        "clock": "sample-local",
        "visual_audio": "muted",
        "loop_rule": "sample_local_time % visual.duration" if binding["mode"] == "local_loop" else None,
    }
    target = DATA / "media/exports" / (identity(manifest) + ".pv.json")
    write_json(target, manifest)
    return {
        "material_id": mid,
        "path": str(target),
        "visual_file": binding["path"],
        "audio_file": str(path),
        "manifest": manifest,
    }
