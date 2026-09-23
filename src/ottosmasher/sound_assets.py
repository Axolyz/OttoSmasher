"""Persistent processed source audio, with explicit source time mappings."""

import json
from pathlib import Path

import numpy as np

from .workspace import identity


def subject_key(s):
    return identity({"artifact_id": s["artifact_id"], "start": float(s["start"]), "end": float(s["end"])})


def ensure(db):
    existing = {r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    if 'workflow_artifacts' in existing and 'processed_audio_assets' not in existing:
        db.execute('ALTER TABLE workflow_artifacts RENAME TO processed_audio_assets')
    schema = """
    CREATE TABLE IF NOT EXISTS processed_audio_assets(id TEXT PRIMARY KEY, payload TEXT NOT NULL);
    """
    for statement in schema.split(";"):
        if statement.strip():
            db.execute(statement)


def source(db, spec):
    from . import materials, sample_audio

    if spec.get("artifact_id"):
        return get(db, spec["artifact_id"])
    if spec.get("material_id"):
        m = materials.get(db, spec["material_id"])
        if spec.get("clock") == "source" and "start" in spec and "end" in spec:
            a = sample_audio.resolve_range(
                db,
                m,
                float(spec["start"]),
                float(spec["end"]),
                spec.get("role", "raw"),
                spec.get("audio_stream"),
            )
            parent = m["id"] if m["start"] <= spec["start"] < spec["end"] <= m["end"] else None
        else:
            a = sample_audio.resolve(db, m["id"], spec.get("role", "selected"))
            parent = m["id"]
        return {"source_id": m["source_id"], "material_id": parent, "title": m["title"], "asset": a}
    sid = spec.get("source_id")
    if spec.get("path"):
        from .catalog import probe

        path = Path(spec["path"]).expanduser().resolve(strict=True)
        r = db.execute("SELECT id FROM sources WHERE path=?", (str(path),)).fetchone()
        if r:
            sid = r[0]
        else:
            info = probe(path)
            tracks = [s["index"] for s in info["streams"] if s["codec_type"] == "audio"]
            stream = spec.get("audio_stream", tracks[0] if len(tracks) == 1 else None)
            if stream not in tracks:
                raise ValueError("请选择有效音轨：" + str(tracks))
            sid = identity(str(path))
            db.execute(
                "INSERT INTO sources VALUES(?,?,?,?,?,?,?,?)",
                (
                    sid,
                    str(path),
                    "",
                    materials.sha256(path),
                    path.stem,
                    float(info["format"]["duration"]),
                    stream,
                    json.dumps(info),
                ),
            )
            db.commit()
    r = db.execute("SELECT * FROM sources WHERE id=?", (sid,)).fetchone()
    if not r:
        raise ValueError("请选择原片或采样")
    if not Path(r["path"]).is_file():
        raise ValueError("原片文件缺失")
    stream = spec.get("audio_stream", r["audio_stream"])
    metadata = json.loads(r["metadata"])
    if stream not in [x["index"] for x in metadata["streams"] if x["codec_type"] == "audio"]:
        raise ValueError("无效音轨")
    a = {
        "path": r["path"],
        "start": 0,
        "end": r["duration"],
        "audio_stream": stream,
        "sha256": r["fingerprint"],
        "role": "raw",
        "root_knots": [[0, 0], [r["duration"], r["duration"]]],
        "provenance": {"source_id": sid},
    }
    return {"source_id": sid, "material_id": None, "title": r["title"], "asset": a}


def crop_asset(asset, start, end):
    duration = asset["end"] - asset["start"]
    if not np.isfinite([start, end]).all() or not 0 <= start < end <= duration + 1 / 8000:
        raise ValueError("选区超出音源")
    x, y = np.asarray(asset["root_knots"]).T
    return {
        **asset,
        "start": asset["start"] + start,
        "end": asset["start"] + end,
        "root_knots": [
            [0, float(np.interp(start, x, y))],
            *[[a - start, b] for a, b in asset["root_knots"] if start < a < end],
            [end - start, float(np.interp(end, x, y))],
        ],
    }


def put(db, descriptor, producer, version, parameters, input_ref=None, commit=True):
    import soundfile as sf

    from .materials import sha256

    ensure(db)
    a = descriptor["asset"]
    if "residual_of" in a:
        import shutil

        from .sample_audio import pcm
        from .workspace import DATA

        generated = pcm(a)
        target = DATA / "media/processing-input" / (identity(a) + ".wav")
        target.parent.mkdir(parents=True, exist_ok=True)
        if not target.exists():
            shutil.copyfile(generated, target)
        a = {
            **a,
            "path": str(target),
            "sha256": sha256(target),
            "start": 0,
            "end": a["end"] - a["start"],
            "audio_stream": 0,
        }
        a.pop("residual_of", None)
        a.pop("raw", None)
    p = Path(a["path"]).resolve(strict=True)
    if input_ref:
        info = sf.info(p)
        expected = input_ref["asset"]["end"] - input_ref["asset"]["start"]
        if abs(info.duration - expected) > max(2 / info.samplerate, 0.01):
            raise ValueError("处理结果长度不一致，不能伪造时间映射")
        a = {
            **a,
            "sha256": sha256(p),
            "start": 0,
            "end": info.duration,
            "audio_stream": 0,
            "sample_rate": info.samplerate,
            "speech_analysis_eligible": False,
            "root_knots": input_ref["asset"]["root_knots"],
        }
    aid = identity("processed-audio-v1", a, producer, version, parameters)
    stat = p.stat()
    doc = {
        **descriptor,
        "file_stat": [stat.st_size, stat.st_mtime_ns],
        "id": aid,
        "asset": a,
        "producer": producer,
        "version": version,
        "parameters": parameters,
        "input": input_ref,
    }
    db.execute("INSERT OR IGNORE INTO processed_audio_assets VALUES(?,?)", (aid, json.dumps(doc)))
    if commit:
        db.commit()
    return doc


def get(db, aid):
    ensure(db)
    r = db.execute("SELECT payload FROM processed_audio_assets WHERE id=?", (aid,)).fetchone()
    if not r:
        raise ValueError("处理音源不存在")
    d = json.loads(r[0])
    p = Path(d["asset"]["path"])
    if not p.is_file():
        raise ValueError("处理文件缺失")
    stat = p.stat()
    if d.get("file_stat") and d["file_stat"] != [stat.st_size, stat.st_mtime_ns]:
        raise ValueError("音源文件已改变，请重新分析")
    return d
