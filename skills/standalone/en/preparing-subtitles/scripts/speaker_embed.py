# /// script
# requires-python = ">=3.10,<3.13"
# dependencies = ["anime-speaker-embedding==0.2.1", "numpy"]
# ///
"""Speaker embeddings (voiceprints) for time ranges of one audio file — for grouping lines by speaker.

An agent runs it in its own environment with `uv run speaker_embed.py ...` (uv installs the
dependencies into its own cache on first use; the first run also downloads PyTorch and the model, a few hundred MB).

Model: anime_speaker_embedding 0.2.1, variant "char" (ECAPA-TDNN trained on anime character voices,
https://huggingface.co/litagin/anime_speaker_embedding_ecapa_tdnn_groupnorm ; downloaded from Hugging Face on first use).
Use separated vocals, not the original mix.

Usage:
  uv run speaker_embed.py AUDIO RANGES.json OUT [--mapping EXPORT.json] [--device cpu]

  AUDIO        any file ffmpeg can read (separated vocals, a video's audio stream 0)
  RANGES.json  [{"id": ..., "start": seconds, "end": seconds}, ...]
               seconds are AUDIO file seconds; with --mapping they are source seconds instead
  --mapping    JSON with a [[file seconds, source seconds], ...] polyline (or {"mapping": [...]}), for audio cut from a longer source; ranges are converted back
  OUT          writes OUT.npy (N x 192 float32, L2-normalized, row order = RANGES.json) and OUT.json
               ([{"id", "start", "end", "seconds", "short"}], file seconds; short = under 0.5 s, unreliable)

Details that matter (and are easy to get wrong):
  - 16 kHz mono float in [-1, 1], decoded by ffmpeg (-ac 1 -ar 16000); one range per forward pass
    (the model rescales a batch by its overall peak, so batching ranges of different loudness changes the results).
  - Ranges shorter than 0.1 s are zero-padded to 0.1 s; under 0.5 s the embedding is much less reliable.
  - Cosine similarity of the normalized rows; on anime voices same-speaker pairs are only around 0.3-0.4 on average
    and different speakers around 0.2, so compare relatively (nearest groups, margins), not against a fixed 0.7.
"""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
from bisect import bisect_right
from pathlib import Path

import numpy as np

SR = 16000
MIN_SECONDS = 0.1
SHORT = 0.5


def decode(path: str, ffmpeg: str) -> np.ndarray:
    raw = subprocess.run([ffmpeg, "-v", "error", "-i", path, "-map", "0:a:0", "-ac", "1", "-ar", str(SR), "-f", "f32le", "-"],
                         capture_output=True, check=True).stdout
    return np.frombuffer(raw, dtype=np.float32)


def source_to_file(mapping: list[list[float]]):
    """Inverse of a mapping ([[file s, source s], ...], both strictly increasing): source seconds -> file seconds."""
    src = [float(p[1]) for p in mapping]
    fil = [float(p[0]) for p in mapping]

    def f(t: float) -> float:
        if not src[0] - 1e-6 <= t <= src[-1] + 1e-6:
            raise SystemExit(f"time {t} is outside the exported range {src[0]}..{src[-1]} (source seconds)")
        i = min(max(bisect_right(src, t) - 1, 0), len(src) - 2)
        return fil[i] + (t - src[i]) * (fil[i + 1] - fil[i]) / (src[i + 1] - src[i])

    return f


def load_ranges(path: str, mapping_path: str | None) -> list[dict]:
    ranges = json.loads(Path(path).read_text(encoding="utf-8"))
    if mapping_path:
        m = json.loads(Path(mapping_path).read_text(encoding="utf-8"))
        conv = source_to_file(m["mapping"] if isinstance(m, dict) else m)
        ranges = [{**r, "start": conv(float(r["start"])), "end": conv(float(r["end"]))} for r in ranges]
    for r in ranges:
        if not float(r["end"]) > float(r["start"]):
            raise SystemExit(f"range {r.get('id')}: end must be after start")
    return ranges


def cut(wave: np.ndarray, start: float, end: float) -> np.ndarray:
    x = np.array(wave[max(0, int(start * SR)):max(0, int(end * SR))], dtype=np.float32)  # a copy: decode() gives a read-only buffer, torch.from_numpy needs a writable one
    if len(x) < MIN_SECONDS * SR:
        x = np.pad(x, (0, int(MIN_SECONDS * SR) - len(x)))
    return x


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("audio")
    ap.add_argument("ranges")
    ap.add_argument("out")
    ap.add_argument("--mapping")
    ap.add_argument("--device", default="cpu")
    ap.add_argument("--ffmpeg", default=shutil.which("ffmpeg"))
    a = ap.parse_args(argv)
    if not a.ffmpeg:
        raise SystemExit("ffmpeg not found: install it or pass --ffmpeg /path/to/ffmpeg")
    ranges = load_ranges(a.ranges, a.mapping)
    wave = decode(a.audio, a.ffmpeg)

    import torch
    from anime_speaker_embedding import AnimeSpeakerEmbedding

    model = AnimeSpeakerEmbedding(variant="char", device=a.device)
    out = np.zeros((len(ranges), 192), np.float32)
    meta = []
    with torch.inference_mode():
        for n, r in enumerate(ranges):
            s, e = float(r["start"]), float(r["end"])
            v = model(torch.from_numpy(cut(wave, s, e))[None].to(a.device)).squeeze().float().cpu().numpy()
            out[n] = v / max(float(np.linalg.norm(v)), 1e-12)
            meta.append({"id": r.get("id", n), "start": s, "end": e, "seconds": round(e - s, 3), "short": e - s < SHORT})
            if n % 500 == 0:
                print(f"{n}/{len(ranges)}", file=sys.stderr, flush=True)
    np.save(f"{a.out}.npy", out)
    Path(f"{a.out}.json").write_text(json.dumps(meta, ensure_ascii=False), encoding="utf-8")
    print(json.dumps({"npy": f"{a.out}.npy", "json": f"{a.out}.json", "count": len(ranges), "short": sum(m["short"] for m in meta)}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
