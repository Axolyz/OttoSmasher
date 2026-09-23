"""Reusable native-cadence RGB index. Frame times come from decoded PTS, never FPS division."""

import collections
import os
import queue
import re
import subprocess
import threading
import time
from pathlib import Path

import numpy as np
from PIL import Image

from .workspace import DATA, executable, identity

SIZE = (24, 14)
VERSION = "rgb-pts-v1"


def decoded(path, start, end, size=SIZE, hardware=False):
    cmd = [executable("ffmpeg"), "-hide_banner", "-v", "info", "-nostdin"]
    if hardware:
        cmd += ["-hwaccel", "videotoolbox"]
    cmd += [
        "-ss",
        str(start),
        "-i",
        str(path),
        "-t",
        str(end - start),
        "-an",
        "-sn",
        "-vf",
        f"scale={size[0]}:{size[1]},showinfo",
        "-fps_mode",
        "passthrough",
        "-pix_fmt",
        "rgb24",
        "-f",
        "rawvideo",
        "pipe:1",
    ]
    p = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    times = queue.Queue()
    errors = collections.deque(maxlen=12)

    def read_errors():
        for raw in p.stderr:
            line = raw.decode(errors="replace")
            m = re.search(r"\bn:\s*\d+\s+pts:\s*-?\d+\s+pts_time:([-\d.eE+]+)", line)
            if m:
                times.put(float(m[1]) + start)
            elif "showinfo" not in line:
                errors.append(line)
        times.put(None)

    thread = threading.Thread(target=read_errors, daemon=True)
    thread.start()
    n = size[0] * size[1] * 3
    try:
        while True:
            data = p.stdout.read(n)
            if not data:
                break
            if len(data) != n:
                raise ValueError("视频解码帧不完整")
            t = times.get(timeout=30)
            if t is None:
                raise ValueError("缺少解码时间戳")
            yield t, np.frombuffer(data, dtype=np.uint8).reshape(size[1], size[0], 3)
        if p.wait():
            raise ValueError("视频索引解码失败: " + "".join(errors)[-1200:])
    finally:
        if p.poll() is None:
            p.terminate()
            p.wait()
        thread.join(timeout=2)
        p.stdout.close()
        p.stderr.close()


def index(path, start, end):
    path = Path(path)
    st = path.stat()
    key = identity(VERSION, str(path.resolve()), st.st_size, st.st_mtime_ns, start, end)
    root = DATA / "cache" / "visual-index"
    root.mkdir(parents=True, exist_ok=True)
    target = root / (key + ".npz")
    began = time.perf_counter()
    if target.is_file():
        with np.load(target, allow_pickle=False) as f:
            return (
                f["times"],
                f["frames"],
                {"cached": True, "index_seconds": time.perf_counter() - began, "path": str(target)},
            )
    # Lock per range so separate queued requests cannot overwrite a partial index.
    from filelock import FileLock

    with FileLock(str(root / (key + ".lock"))):
        if target.is_file():
            with np.load(target, allow_pickle=False) as f:
                return (
                    f["times"],
                    f["frames"],
                    {"cached": True, "index_seconds": time.perf_counter() - began, "path": str(target)},
                )
        warnings = []
        for hardware in (True, False):
            times, frames = [], []
            try:
                for t, frame in decoded(path, start, end, hardware=hardware):
                    times.append(t)
                    frames.append(frame)
                if not times:
                    raise ValueError("范围没有可解码视频帧")
                break
            except (ValueError, subprocess.SubprocessError) as e:
                if not hardware:
                    raise
                warnings.append("VideoToolbox 不可用，改用 CPU：" + str(e))
                print(warnings[-1], flush=True)
        times = np.asarray(times, dtype=np.float64)
        frames = np.asarray(frames, dtype=np.uint8)
        temp = root / (key + f".{os.getpid()}.partial")
        try:
            with temp.open("wb") as f:
                np.savez_compressed(f, times=times, frames=frames)
            os.replace(temp, target)
        finally:
            temp.unlink(missing_ok=True)
        return (
            times,
            frames,
            {
                "cached": False,
                "index_seconds": time.perf_counter() - began,
                "path": str(target),
                "decoder": "videotoolbox" if hardware else "cpu",
                "warnings": warnings,
            },
        )


def scores(frames, ref):
    result = []
    b = ref.mean(axis=2).reshape(-1)
    b = b - b.mean()
    for start in range(0, len(frames), 512):
        x = frames[start : start + 512].astype(np.float32) / 255
        mse = ((x - ref) ** 2).mean(axis=(1, 2, 3))
        a = x.mean(axis=3).reshape(len(x), -1)
        a -= a.mean(axis=1, keepdims=True)
        corr = (a @ b) / np.maximum(np.linalg.norm(a, axis=1) * np.linalg.norm(b), 1e-8)
        result.extend(np.clip(0.55 * (1 - mse / 0.16) + 0.45 * corr, 0, 1))
    return np.asarray(result)


def match(path, ref, start, end, duration, offset):
    from .opening_scan import SIZE as FULL_SIZE
    from .opening_scan import score

    times, frames, stats = index(path, start, end)
    began = time.perf_counter()
    small = np.asarray(Image.fromarray((ref * 255).astype(np.uint8)).resize(SIZE), dtype=np.float32) / 255
    values = scores(frames, small)
    peaks = []
    # Refinement works on actual decoded frames, including one-frame references.
    for i in np.argsort(values)[::-1]:
        if values[i] < 0.58 or len(peaks) >= 8:
            break
        t = float(times[i])
        if any(abs(t - x) < max(1, duration * 0.65) for x in peaks):
            continue
        peaks.append(t)
    stats["query_seconds"] = time.perf_counter() - began
    began = time.perf_counter()
    hits = []
    for t in peaks:
        refined = max(
            (
                (at, score(f, ref))
                for at, f in decoded(path, max(start, t - 0.3), min(end, t + 0.3), FULL_SIZE)
            ),
            key=lambda x: x[1],
            default=(t, 0),
        )
        a = refined[0] - offset
        if refined[1] >= 0.60 and a >= 0:
            hits.append(
                {
                    "start": round(a, 4),
                    "end": round(a + duration, 4),
                    "reference_time": refined[0],
                    "similarity": refined[1],
                    "status": "proposal",
                    "needs_review": True,
                }
            )
    stats["refine_seconds"] = time.perf_counter() - began
    hits = sorted(hits, key=lambda h: -h["similarity"])[:3]
    return hits, stats
