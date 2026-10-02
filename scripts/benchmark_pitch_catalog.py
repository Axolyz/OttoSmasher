"""100k-row HTTP/database benchmark over synthetic F0, never a real audio quality claim."""

import time

BEGAN = time.perf_counter()
import argparse
import hashlib
import json
import os
import subprocess
import sys
import threading
from pathlib import Path

p = argparse.ArgumentParser()
p.add_argument("--workspace", type=Path, required=True)
p.add_argument("--indices", type=Path, required=True)
p.add_argument("--prepare", action="store_true")
p.add_argument("--case", choices=["single", "multi", "none", "common", "overlap", "tags"], default="single")
p.add_argument("--repeat", type=int, default=6)
a = p.parse_args()
root = a.workspace.resolve()
root.mkdir(parents=True, exist_ok=True)
os.environ["OTTO_ROOT"] = str(root)
os.environ["OTTO_CODE_ROOT"] = str(Path(__file__).resolve().parents[1])
from ottosmasher.workspace import connect, identity, write_json
from ottosmasher import asset_timeline as timeline
from ottosmasher.asset_migration import activate
from ottosmasher.pitch_search import VERSION, ensure
from ottosmasher.sound_features import model_info

if a.prepare:
    if (root / "data/catalog.sqlite3").exists():
        raise SystemExit("Refusing to replace an existing workspace")
    tracks = json.loads((a.indices / "tracks.json").read_text())
    with connect() as db:
        activate(db)
        ensure(db)
        db.execute("INSERT INTO sample_folders VALUES('bench','基准',NULL)")
        now = time.time()
        for i, track in enumerate(tracks):
            # The file is only a stat/content identity fixture. No decoder or
            # model is run, and it must never be presented as 50h real media.
            path = root / f"identity-{i:03}.fixture"
            path.write_bytes(f"synthetic-track-{i}".encode())
            digest = hashlib.sha256(path.read_bytes()).hexdigest()
            stat = path.stat()
            sid = f"source-{i}"
            descriptor = {
                "path": str(path),
                "sha256": digest,
                "start": 0,
                "end": 3600,
                "audio_stream": 0,
                "role": "vocals",
                "root_knots": [[0, 0], [3600, 3600]],
            }
            db.execute(
                "INSERT INTO sources VALUES(?,?,?,?,?,?,?,?)",
                (sid, str(path), None, digest, sid, 3600, 0, '{"streams":[]}'),
            )
            db.execute("INSERT INTO source_labels VALUES(?,?,?,?,?)", (sid, "benchmark", "", "", now))
            selected = timeline.register_asset(db, sid, descriptor)
            signature = identity(VERSION, digest, 0, model_info()["sha256"])
            folder = Path(track["path"]).resolve()
            manifest = {
                "signature": signature,
                "file_stat": [stat.st_size, stat.st_mtime_ns],
                "frames": track["frames"],
            }
            write_json(folder / "manifest.json", manifest)
            indexed = {**descriptor, "file_stat": manifest["file_stat"]}
            db.execute(
                "INSERT INTO pitch_tracks VALUES(?,?,?,?,?,?)",
                (signature, signature, str(folder), track["frames"], json.dumps(indexed), now),
            )
            db.execute(
                "INSERT INTO pitch_asset_ranges VALUES(?,?,?,?,?,?)",
                (selected.asset_id, signature, 0, 3600, sid, "vocals"),
            )
            samples = []
            bindings = []
            ranges = []
            tags = []
            for j, (lo, hi) in enumerate(track["ranges"]):
                mid = f"{sid}-sample-{j}"
                samples.append((mid, sid, lo, hi, 0, mid, now, "bench"))
                bindings.append((mid, selected.asset_id, lo, hi))
                ranges.append((mid, signature, lo, hi, "fixture", sid, "vocals"))
                if j % 2 == 0:
                    tags.append((mid, "review:keep", "manual"))
                if j % 7 == 0:
                    tags.append((mid, "skip", "manual"))
            db.executemany(
                "INSERT INTO materials(id,source_id,start,end,audio_stream,title,created,folder_id) VALUES(?,?,?,?,?,?,?,?)",
                samples,
            )
            db.executemany(
                "INSERT INTO asset_samples(sample_id,asset_id,start,end) VALUES(?,?,?,?)", bindings
            )
            db.executemany("INSERT INTO pitch_sample_ranges VALUES(?,?,?,?,?,?,?)", ranges)
            db.executemany("INSERT INTO material_tags VALUES(?,?,?)", tags)
            for j in range(0, 3600, 30):
                db.execute(
                    "INSERT INTO timeline_annotations VALUES(?,?,?,?,?,?,?,?,1,0)",
                    (
                        f"{sid}-annotation-{j}",
                        sid,
                        j,
                        j + 10,
                        "tag",
                        "",
                        '["character:测试"]',
                        '{"type":"group","ids":["dialogue"]}',
                    ),
                )
    write_json(
        root / "benchmark-fixture.json", {"samples": 100000, "synthetic_f0_hours": 50, "real_audio_hours": 0}
    )
    print("Prepared synthetic database benchmark")
    raise SystemExit()
if not (root / "benchmark-fixture.json").exists():
    raise SystemExit("Not a benchmark workspace")
from fastapi.testclient import TestClient
from ottosmasher.api import app
import numpy as np
import psutil

query = {
    "single": ".4 A4",
    "multi": ".3 C4\n.3 E4\n.3 G4",
    "none": "1 C1",
    "common": ".1 C4..C5",
    "overlap": ".5 C4",
    "tags": ".4 A4",
}[a.case]
body = {"text": query, "scope": {}}
if a.case == "tags":
    body["scope"]["tag_expression"] = "(character:测试 OR review:keep) AND NOT skip"
if a.case == "overlap":
    with connect() as db:
        db.execute("CREATE TEMP TABLE overlap_ranges AS SELECT * FROM pitch_sample_ranges")
        db.execute("UPDATE asset_samples SET start=0,end=3599")
        db.execute("UPDATE materials SET start=0,end=3599")
        db.execute(
            "INSERT INTO pitch_sample_ranges SELECT sample_id,track_id,0,3599,asset_signature,source_id,role FROM overlap_ranges"
        )
process = psutil.Process()
baseline = process.memory_info().rss
peaks = [baseline]
done = threading.Event()


def sample():
    while not done.wait(0.005):
        peaks.append(process.memory_info().rss)


thread = threading.Thread(target=sample, daemon=True)
thread.start()
elapsed = []
with TestClient(app) as client:
    for i in range(a.repeat):
        began = time.perf_counter()
        response = client.post("/api/samples/pitch-query", json=body)
        elapsed.append(time.perf_counter() - began)
        if response.status_code != 200:
            raise RuntimeError(f"{response.status_code}: {response.text}")
        if i == 0:
            cold_app = time.perf_counter() - BEGAN
        result = response.json()
done.set()
thread.join()
report = {
    "case": a.case,
    "synthetic": True,
    "real_audio_hours": 0,
    "samples": 100000,
    "unique_f0_hours": 50,
    "http_times": elapsed,
    "cold_app_to_first_result_seconds": cold_app,
    "warm_p95_seconds": float(np.percentile(elapsed[1:], 95)),
    "query_peak_extra_mib": (max(peaks) - baseline) / 2**20,
    "matches": len(result["results"]),
    "coverage": result["coverage"],
    "truncated": result["truncated"],
}
print(json.dumps(report, indent=2, ensure_ascii=False))
