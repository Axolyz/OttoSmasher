"""Continuous source stems; inference output never registers samples implicitly."""

import numpy as np

from . import sound_assets as assets
from . import sound_models as models
from .workspace import DATA


def register_input(db, spec):
    d = assets.source(db, spec)
    a = d["asset"]
    duration = a["end"] - a["start"]
    start = float(spec.get("start", 0))
    end = float(spec.get("end", duration))
    if spec.get("clock") == "source":
        x, y = np.asarray(a["root_knots"]).T
        if not y[0] <= start < end <= y[-1]:
            raise ValueError("原片选区超出所选音源")
        start, end = map(float, np.interp([start, end], y, x))
    d = {**d, "asset": assets.crop_asset(a, start, end)}
    return assets.put(db, d, "otto.source", "1", {"selection": spec})


def infer_assets(db, action, docs, folder, **kwargs):
    from .sample_audio import pcm

    return models.infer(action, [pcm(d["asset"]) for d in docs], folder, **kwargs)


def submit(db, action, payload):
    from .operation_jobs import submit as enqueue

    if action != "tracks":
        raise ValueError("此声音工具已移除；只支持原片三轨分离")
    if payload.get("routes", ["bandit-v2"]) != ["bandit-v2"]:
        raise ValueError("只保留 BandIt v2 多语言")
    return enqueue("source-separation", {"request": payload})


def run(db, payload, jid):
    from .sound_tracks import build

    assets.ensure(db)
    req = payload["request"]
    d = register_input(db, req["input"])
    duration = d["asset"]["end"] - d["asset"]["start"]
    folder = DATA / "media/source-separation" / jid
    folder.mkdir(parents=True, exist_ok=True)
    chunks = []
    for start in np.arange(0, duration, 60.0):
        lo, hi = max(0, float(start - 2)), min(duration, float(start + 62))
        chunk = assets.put(
            db, {**d, "asset": assets.crop_asset(d["asset"], lo, hi)}, "otto.source", "1", {"chunk": [lo, hi]}
        )
        chunks.append((lo, chunk))
    db.commit()  # Do not hold a catalog write lock throughout long model inference.
    result = infer_assets(
        db,
        "bandit-v2",
        [c[1] for c in chunks],
        folder,
        **({"device": req["device"]} if "device" in req else {}),
    )
    if len(result["outputs"]) != len(chunks):
        raise ValueError("分离没有返回全部窗口，不能登记完整参考轨")
    tracks = build(
        db,
        d,
        "bandit-v2",
        result["outputs"],
        [c[0] for c in chunks],
        folder,
        result.get("execution"),
        models.MODELS["bandit-v2"]["name"],
    )
    return {
        "type": "source-tracks",
        "source_id": d["source_id"],
        "reference_tracks": [doc["id"] for doc in tracks.values()],
    }
