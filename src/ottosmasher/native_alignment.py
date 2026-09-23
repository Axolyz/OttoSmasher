from .workspace import CODE_ROOT
"""Character/syllable alignment is a separate measured layer, never a phone backend."""

import json
import subprocess
from pathlib import Path

from .inference_runtime import python_path
from .workspace import DATA, ROOT, connect, identity, write_json

ADAPTER_VERSIONS = {"yohane": "official-time-lyrics-v2", "qwen3-aligner": "official-japanese-nagisa-v2"}

MODELS = {"yohane": "yohane · 原生音节", "qwen3-aligner": "Qwen3 · 日语词"}


def ensure(db):
    db.execute(
        "CREATE TABLE IF NOT EXISTS native_alignments(material_id TEXT,model TEXT,payload TEXT,PRIMARY KEY(material_id,model))"
    )


def model_revision(model):
    return identity(
        [
            (p.name, p.stat().st_size, p.stat().st_mtime_ns)
            for p in sorted((ROOT / "models" / model).glob("*"))
            if p.is_file()
        ]
    )


def listing(db, mid):
    ensure(db)
    results = [
        json.loads(r[0])
        for r in db.execute("SELECT payload FROM native_alignments WHERE material_id=?", (mid,))
    ]
    for r in results:
        asset = r.get("input", {}).get("asset", {})
        p = Path(asset.get("path", ""))
        r["stale"] = r.get("adapter_version") != ADAPTER_VERSIONS[r["model"]] or not p.is_file() or r.get("model_revision") != model_revision(r["model"])
        if p.is_file():
            r["stale"] |= r.get("input", {}).get("file_stat") != [p.stat().st_size, p.stat().st_mtime_ns]
    return {
        "models": [
            {"id": k, "name": v, "available": (ROOT / "models" / k / "model.safetensors").is_file()}
            for k, v in MODELS.items()
        ],
        "results": results,
    }


def play(db, mid, model, index, native=False):
    from .native_player import register
    from .sample_audio import pcm
    from .sound_assets import crop_asset

    result = next((r for r in listing(db, mid)["results"] if r["model"] == model), None)
    if not result or result["status"] != "ready" or result["stale"]:
        raise ValueError("结果缺失或已失效")
    if not isinstance(index, int) or not 0 <= index < len(result["segments"]):
        raise ValueError("无效字符/音节")
    seg = result["segments"][index]
    asset = crop_asset(result["input"]["asset"], seg["start"], seg["end"])
    if native:
        return register(
            asset["path"],
            asset["start"],
            asset["end"],
            asset,
            [{"index": asset["audio_stream"], "codec_type": "audio"}],
        )
    path = pcm(asset)
    return {"path": path}


def run(payload, jid):
    from . import materials, sample_audio
    from .source_vocals import ensure as vocals
    from .workspace import get_cue

    model = payload["model"]
    if model not in MODELS:
        raise ValueError("未知字符/音节对齐模型")
    folder = DATA / "native-alignments" / jid
    folder.mkdir(parents=True, exist_ok=True)
    items = []
    with connect() as db:
        ensure(db)
        for mid in payload["material_ids"]:
            r = materials.get(db, mid)
            if not r.get("cue_id"):
                raise ValueError("字符/音节对齐需要已有台词")
            cue = get_cue(db, r["cue_id"])
            if r["start"] > cue["start"] + 0.05 or r["end"] < cue["end"] - 0.05:
                raise ValueError("派生选段缺少独立正文；请在完整台词上运行字符/音节对齐")
            asset = sample_audio.resolve(db, mid)
            if asset["role"] != "vocals":
                db.commit()  # Separation writes its own progress/assets through another connection.
                vocals(cue, payload.get("vocal_model", "becruily_deux"))
                asset = sample_audio.resolve_range(db, r, r["start"], r["end"], "vocals")
            path = sample_audio.pcm(asset)
            item = {
                "material_id": mid,
                "path": str(path),
                "text": cue["spoken"],
                "asset": asset,
                "file_stat": [Path(asset["path"]).stat().st_size, Path(asset["path"]).stat().st_mtime_ns],
                "audio_identity": identity(asset),
                "output": str(folder / (mid + ".json")),
            }
            items.append(item)
    req = folder / "request.json"
    write_json(req, {"model": model, "model_revision": model_revision(model), "adapter_version": ADAPTER_VERSIONS[model], "items": items})
    subprocess.run(
        [str(python_path()), str(CODE_ROOT / "scripts/native_alignment_worker.py"), str(req)], check=True
    )
    rows = []
    with connect() as db:
        ensure(db)
        for item in items:
            result = json.loads(Path(item["output"]).read_text())
            db.execute(
                "INSERT OR REPLACE INTO native_alignments VALUES(?,?,?)",
                (item["material_id"], model, json.dumps(result)),
            )
            rows.append(
                {"material_id": item["material_id"], "status": result["status"], "error": result.get("error")}
            )
        db.commit()
    if rows and all(row["status"] != "ready" for row in rows):
        raise ValueError(
            "字符／音节对齐全部失败；原始结果已保留："
            + "; ".join(row.get("error") or "未知错误" for row in rows)
        )
    return {"type": "native-alignment", "model": model, "rows": rows}
