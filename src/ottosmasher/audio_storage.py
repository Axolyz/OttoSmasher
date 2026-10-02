"""Shared audio ranges, bounded disposable PCM, and LAME V0 durable storage."""

import contextlib
import hashlib
import json
import os
import subprocess
import time
from pathlib import Path

import numpy as np
import soundfile as sf
from filelock import FileLock

from .workspace import DATA, executable, identity, write_json


def read(path, start=0, end=None, *, rate=None, channels=None, stream=0):
    """Decode only a range. Times are file-local; never assume a crop is a file."""
    path = Path(path)
    try:
        if stream != 0:
            raise RuntimeError("stream selection requires FFmpeg")
        info = sf.info(path)
        lo = round(start * info.samplerate)
        hi = min(info.frames, round(end * info.samplerate)) if end is not None else info.frames
        if lo < 0 or hi <= lo:
            raise ValueError("音频选区越界")
        y, sr = sf.read(path, start=lo, stop=hi, dtype="float32", always_2d=True)
        if rate and sr != rate:
            from math import gcd

            from scipy.signal import resample_poly

            g = gcd(sr, rate)
            y = resample_poly(y, rate // g, sr // g, axis=0)
            sr = rate
        if channels == 1:
            y = y.mean(axis=1, keepdims=True)
        return y, sr
    except (sf.LibsndfileError, RuntimeError):
        pass
    sr, count = rate or 48000, channels or 2
    args = [executable("ffmpeg"), "-v", "error", "-i", str(path), "-ss", str(start)]
    if end is not None:
        args += ["-t", str(end - start)]
    args += ["-map", f"0:{stream}", "-ar", str(sr), "-ac", str(count), "-f", "f32le", "pipe:1"]
    raw = subprocess.run(args, capture_output=True, check=True).stdout
    return np.frombuffer(raw, dtype="<f4").reshape(-1, count), sr


def lineage_audio(lineage):
    start = lineage.get("audio_start", 0)
    end = lineage.get("audio_end")
    if end is None and "window_end" in lineage:
        end = start + lineage["window_end"] - lineage.get("window_start", 0)
    return lineage["audio_path"], start, end


def durable(path, *, data_root=None):
    """Publish one compact encoding; input ownership/deletion stays with caller."""
    path = Path(path)
    if path.suffix.lower() == ".mp3":
        return path
    info = sf.info(path)
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    folder = (data_root or DATA) / "media/compact"
    folder.mkdir(parents=True, exist_ok=True)
    target = folder / (digest + ".mp3")
    with FileLock(str(target) + ".lock"):
        if not target.exists():
            temp = target.with_suffix(".part.mp3")
            args = [
                executable("ffmpeg"),
                "-v",
                "error",
                "-y",
                "-i",
                str(path),
                "-c:a",
                "libmp3lame",
                "-q:a",
                "0",
                "-compression_level",
                "0",
                "-write_xing",
                "1",
            ]
            if info.samplerate not in (32000, 44100, 48000):
                args += ["-ar", "48000"]
            if info.channels > 2:
                raise ValueError("多声道资产需要明确选择声道后才能压缩")
            try:
                subprocess.run([*args, str(temp)], capture_output=True, check=True)
                decoded = sf.info(temp)
                expected_frames = round(info.duration * decoded.samplerate)
                # Some short LAME streams expose a partial padding frame. Asset
                # selections retain the original length, excluding that tail.
                if not 0 <= decoded.frames - expected_frames <= 1152:
                    raise ValueError("MP3 编码长度校验失败，原文件保留")
                temp.replace(target)
                write_json(
                    target.with_suffix(".json"),
                    {
                        "version": "lame-v0-1",
                        "original_path": str(path),
                        "original_sha256": digest,
                        "original_frames": info.frames,
                        "original_rate": info.samplerate,
                        "frames": decoded.frames,
                        "trim_end_frames": decoded.frames - expected_frames,
                        "sample_rate": decoded.samplerate,
                        "channels": decoded.channels,
                    },
                )
            finally:
                temp.unlink(missing_ok=True)
    return target


@contextlib.contextmanager
def leased(path):
    """A cleanup process can acquire this lock only after the reader releases it."""
    with FileLock(str(path) + ".use"):
        if Path(path).exists():
            os.utime(path, None)
        yield Path(path)


@contextlib.contextmanager
def model_input(lineage, rate):
    path, start, end = lineage_audio(lineage)
    stream = lineage.get("file_audio_stream", 0)
    key = identity("model-pcm-1", path, Path(path).stat().st_mtime_ns, start, end, rate, stream)
    target = DATA / "cache/model-inputs" / (key + ".wav")
    target.parent.mkdir(parents=True, exist_ok=True)
    with leased(target):
        if not target.exists():
            y, sr = read(path, start, end, rate=rate, channels=1, stream=stream)
            temporary = target.with_suffix(".tmp.wav")
            sf.write(temporary, y, sr, subtype="PCM_16")
            temporary.replace(target)
        yield target
    trim_pcm()


def trim_pcm(limit=512 * 1024**2, low=384 * 1024**2):
    """Only disposable decoding files, never adjacent measurements or manifests."""
    from filelock import Timeout

    roots = [DATA / "cache/model-inputs", DATA / "sample-cache"]
    items = [
        (p.stat().st_mtime, p.stat().st_size, p)
        for root in roots
        if root.exists()
        for p in root.glob("*.wav")
        if not p.is_symlink()
    ]
    total = sum(x[1] for x in items)
    target = low if total > limit else limit
    now = time.time()
    for stamp, size, p in sorted(items):
        if total <= target and now - stamp < 86400:
            continue
        # Old consumers without an explicit lease receive a short grace window.
        if "model-inputs" not in p.parts and now - stamp < 900:
            continue
        try:
            with FileLock(str(p) + ".use", timeout=0):
                if p.exists() and p.stat().st_mtime == stamp:
                    p.unlink()
                    total -= size
        except (Timeout, FileNotFoundError):
            pass


def audio_owners(db):
    """Physical audio ownership, excluding historical job inputs and recipes."""
    tables = {r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    owners = set()
    for table, column in [
        ("sound_assets", "descriptor"),
        ("shared_sample_audio", "payload"),
        ("processed_audio_assets", "payload"),
    ]:
        if table not in tables:
            continue
        for row in db.execute(f"SELECT {column} FROM {table}"):
            doc = json.loads(row[0])
            asset = doc.get("asset", doc)
            if asset.get("path"):
                owners.add(Path(asset["path"]))
    for table in ("sources", "material_versions"):
        if table in tables:
            owners.update(Path(r[0]) for r in db.execute(f"SELECT path FROM {table}"))
    return owners


def retire_encoded_outputs(db):
    """A committed replacement is required before its own generated master is released."""
    owners = audio_owners(db)
    for manifest in (DATA / "media/compact").glob("*.json"):
        if manifest.name.endswith(".features.json"):
            continue
        doc = json.loads(manifest.read_text())
        old = Path(doc.get("original_path", ""))
        target = manifest.with_suffix(".mp3")
        if (
            target in owners
            and old not in owners
            and old.is_file()
            and not old.is_symlink()
            and old.is_relative_to(DATA / "media")
            and not old.is_relative_to(DATA / "media/exports")
        ):
            if hashlib.sha256(old.read_bytes()).hexdigest() == doc["original_sha256"]:
                old.unlink()
