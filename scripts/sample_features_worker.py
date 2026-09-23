"""Batch-local FCPE lifetime. Existing sound fingerprints retain reusable features."""
import json
import sys
import time
from pathlib import Path

import soundfile as sf

from ottosmasher.sound_features import FCPE, model_info
from ottosmasher.workspace import write_json

batch = sys.argv[1] == "--batch"
items = json.loads(Path(sys.argv[2]).read_text()) if batch else [{"path": sys.argv[1]}]
engine = None
for item in items:
    path = Path(item["path"])
    target = path.with_suffix(".features.json")
    if batch and target.exists(): continue
    try:
        if engine is None:
            start = time.monotonic(); engine = FCPE()
            print(f"Stage FCPE initialization: {time.monotonic()-start:.3f}s", flush=True)
        start = time.monotonic()
        audio, sr = sf.read(path, dtype="float32", always_2d=True)
        write_json(target, {**engine.infer(audio.mean(axis=1), sr), "model": model_info()})
        print(f"Stage FCPE inference {path.name}: {time.monotonic()-start:.3f}s", flush=True)
    except Exception as e:
        print(f"FCPE failed {path}: {e}", flush=True)
        if not batch: raise
