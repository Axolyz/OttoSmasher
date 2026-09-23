"""Bounded-memory contextual separation; emit real model progress, preserve sample count."""

import json
import math
import time
from pathlib import Path

import numpy as np
import soundfile as sf


def separate_file(sep, source, output, stems, chunk_seconds=60, overlap_seconds=6, progress_path=None):
    info = sf.info(source)
    sr = int(sep.config.audio.get("sample_rate", 44100))
    if info.samplerate != sr:
        raise ValueError(f"Separation input must be {sr} Hz; got {info.samplerate}")
    size, overlap = round(chunk_seconds * sr), round(overlap_seconds * sr)
    step = size - overlap
    if step <= 0:
        raise ValueError("Invalid overlap")
    total = max(1, math.ceil(max(0, info.frames - size) / step) + 1)
    files = {s: Path(output) / f"stem-{i}" / f"result_{s}.wav" for i, s in enumerate(stems)}
    writers, tails = {}, {}
    start_clock = time.monotonic()

    def publish(i, done, count, message):
        fraction = min(1, max(0, done / max(count, 1)))
        elapsed = time.monotonic() - start_clock
        value = {
            "stage": "separation",
            "window": i + 1,
            "windows": total,
            "window_percent": round(100 * fraction, 1),
            "percent": round(100 * (i + fraction) / total, 1),
            "elapsed": round(elapsed, 1),
            "message": message,
            "updated": time.time(),
        }
        if progress_path:
            path = Path(progress_path)
            path.parent.mkdir(parents=True, exist_ok=True)
            tmp = path.with_suffix(".tmp")
            tmp.write_text(json.dumps(value))
            tmp.replace(path)
        print(
            f"Window {i + 1}/{total} model {fraction * 100:.1f}% · {message} · elapsed {elapsed:.1f}s",
            flush=True,
        )

    try:
        for i in range(total):
            first, last = i * step, min(info.frames, i * step + size)
            print(f"Separation window {i + 1}/{total}: {first / sr:.2f}–{last / sr:.2f}s", flush=True)

            def progress(done, count, message="", index=i):
                publish(index, done, count, message)

            publish(i, 0, 1, "Running model")
            sep.progress_callback = progress
            audio, _ = sf.read(source, start=first, stop=last, dtype="float32", always_2d=True)
            separated = sep.separate(audio.T, pbar=False, stems=stems)
            for stem in stems:
                y = np.array(separated[stem], dtype=np.float32, copy=True)
                if y.ndim == 1:
                    y = y[:, None]
                if len(y) != last - first or not np.isfinite(y).all():
                    raise ValueError(f"{stem}: invalid separation length or samples")
                if stem not in writers:
                    files[stem].parent.mkdir(parents=True, exist_ok=True)
                    writers[stem] = sf.SoundFile(
                        str(files[stem]) + ".partial",
                        "w",
                        format="WAV",
                        samplerate=sr,
                        channels=y.shape[1],
                        subtype="FLOAT",
                    )
                if stem in tails:
                    n = len(tails[stem])
                    alpha = np.linspace(0, 1, n, dtype=np.float32)[:, None]
                    y[:n] = tails[stem] * (1 - alpha) + y[:n] * alpha
                if last < info.frames:
                    writers[stem].write(y[:-overlap])
                    tails[stem] = y[-overlap:].copy()
                else:
                    writers[stem].write(y)
                del y
            del audio, separated
            publish(i, 1, 1, "Window written")
        for stem, writer in writers.items():
            if writer.frames != info.frames:
                raise ValueError("Output length differs from source")
            writer.close()
            Path(str(files[stem]) + ".partial").replace(files[stem])
        print(
            f"Separation complete: {info.duration:.2f}s, elapsed {time.monotonic() - start_clock:.1f}s",
            flush=True,
        )
        return files
    finally:
        for writer in writers.values():
            writer.close()
