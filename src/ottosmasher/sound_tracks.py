"""Continuous separated references; never library samples or detected events."""

import json
from pathlib import Path

import numpy as np
import soundfile as sf

from . import sound_assets as assets


def ensure(db):
    assets.ensure(db)
    db.execute("""CREATE TABLE IF NOT EXISTS sound_reference_tracks(
        artifact_id TEXT PRIMARY KEY, source_id TEXT NOT NULL, title TEXT NOT NULL,
        start REAL NOT NULL, end REAL NOT NULL, route TEXT NOT NULL)""")
    db.commit()


def register(db, doc, title):
    ensure(db)
    k = doc["asset"]["root_knots"]
    db.execute(
        "INSERT OR REPLACE INTO sound_reference_tracks VALUES(?,?,?,?,?,?)",
        (doc["id"], doc["source_id"], title, k[0][1], k[-1][1], doc["producer"]),
    )
    db.commit()


def listing(db, source_id=None):
    ensure(db)
    sql = "SELECT * FROM sound_reference_tracks"
    rows = [
        dict(r)
        for r in db.execute(
            sql + (" WHERE source_id=?" if source_id else "") + " ORDER BY title",
            (source_id,) if source_id else (),
        )
    ]
    # Shared vocal separations are selectable references, not extra library samples.
    for row in db.execute(
        "SELECT * FROM shared_sample_audio" + (" WHERE source_id=?" if source_id else ""),
        (source_id,) if source_id else (),
    ):
        payload = json.loads(row["payload"])
        k = payload.get("root_knots")
        if not k or not Path(payload.get("path", "")).is_file():
            continue
        provenance = payload.get("provenance", {})
        rows.append(
            {
                "artifact_id": "shared:" + row["id"],
                "source_id": row["source_id"],
                "title": provenance.get("model", "人声分离")
                + " · "
                + {"vocals": "人声", "residual": "去人声残差"}.get(payload["role"], payload["role"]),
                "start": k[0][1],
                "end": k[-1][1],
                "route": provenance.get("model"),
                "role": payload["role"],
            }
        )
    durations = dict(db.execute("SELECT id,duration FROM sources"))
    for r in rows:
        r["complete"] = r["start"] <= 0.02 and r["end"] >= durations.get(r["source_id"], float("inf")) - 0.02
    rows.sort(key=lambda r: (not r["complete"], r["title"], r["start"]))
    return rows


def resolve(db, aid, source_id, start, end):
    if aid.startswith("shared:"):
        row = db.execute("SELECT * FROM shared_sample_audio WHERE id=?", (aid[7:],)).fetchone()
        if not row:
            raise ValueError("参考音源不存在")
        asset = json.loads(row["payload"])
        d = {
            "asset": asset,
            "source_id": row["source_id"],
            "producer": asset.get("provenance", {}).get("model"),
            "version": asset.get("sha256"),
        }
    else:
        d = assets.get(db, aid)
    if d["source_id"] != source_id:
        raise ValueError("参考音轨与原片不一致")
    x, y = np.asarray(d["asset"]["root_knots"]).T
    if not np.allclose(np.diff(x), np.diff(y), atol=1e-5):
        raise ValueError("已变速音频不能直接挂到原片时间轴")
    if not y[0] - 1e-5 <= start < end <= y[-1] + 1e-5:
        raise ValueError(f"此音轨仅覆盖原片 {y[0]:.3f}–{y[-1]:.3f} 秒，请在覆盖范围内试听")
    a = assets.crop_asset(d["asset"], float(np.interp(start, y, x)), float(np.interp(end, y, x)))
    a["provenance"] = {
        **a.get("provenance", {}),
        "reference_artifact": aid,
        "source_id": source_id,
        "model": d["producer"],
        "model_version": d["version"],
    }
    return a


def stitch(parts, duration, target):
    """Blend contextual overlaps on the exact source sample clock, bounded memory."""
    info = [sf.info(path) for _, path in parts]
    sr, channels = info[0].samplerate, info[0].channels
    if any(i.samplerate != sr or i.channels != channels for i in info):
        raise ValueError("分离窗口输出规格不一致")
    n = round(duration * sr)
    target = Path(target)
    target.parent.mkdir(parents=True, exist_ok=True)
    temp = target.with_suffix(".partial.wav")
    try:
        with sf.SoundFile(temp, "w", samplerate=sr, channels=channels, subtype="FLOAT") as out:
            for first in range(0, n, sr * 10):
                last = min(n, first + sr * 10)
                z = np.zeros((last - first, channels), dtype=np.float64)
                weights = np.zeros(last - first)
                for (offset, path), meta in zip(parts, info):
                    origin = round(offset * sr)
                    lo, hi = max(first, origin), min(last, origin + meta.frames)
                    if lo >= hi:
                        continue
                    y, _ = sf.read(path, start=lo - origin, stop=hi - origin, always_2d=True)
                    at = np.arange(lo, hi)
                    w = np.ones(hi - lo)
                    if origin > 0:
                        w = np.minimum(w, (at - origin + 1) / (2 * sr))
                    if origin + meta.frames < n:
                        w = np.minimum(w, (origin + meta.frames - at) / (2 * sr))
                    z[lo - first : hi - first] += y * w[:, None]
                    weights[lo - first : hi - first] += w
                if np.any(weights <= 0):
                    raise ValueError("分离窗口有缺口，不能用静音冒充完整音轨")
                out.write(z / weights[:, None])
        temp.replace(target)
    finally:
        temp.unlink(missing_ok=True)
    return target


def build(db, source, route, outputs, offsets, folder, execution, title=None):
    from .sound_models import fingerprint

    version = (execution or {}).get("model_fingerprint") or fingerprint(route)
    duration = source["asset"]["end"] - source["asset"]["start"]
    docs = {}
    for stem in ("effect", "music", "dialog"):
        path = stitch(
            [(a, o[stem]) for a, o in zip(offsets, outputs)],
            duration,
            Path(folder) / ("continuous_" + stem + ".wav"),
        )
        d = assets.put(
            db,
            {
                **{k: source[k] for k in ("source_id", "material_id", "title")},
                "asset": {"path": str(path), "role": stem},
            },
            route,
            version,
            {
                "execution": execution,
                "assembly": "context-crossfade-v1",
                "parts": [{"offset": a, "path": o[stem]} for a, o in zip(offsets, outputs)],
            },
            source,
        )
        register(
            db, d, (title or route) + " · " + {"effect": "音效", "music": "音乐", "dialog": "对白"}[stem]
        )
        docs[stem] = d
    return docs
