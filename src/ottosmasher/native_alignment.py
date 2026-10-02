"""Character/syllable alignment is a separate measured layer, never a phone backend."""

import json
from pathlib import Path

from .workspace import ROOT, identity

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
    from .editions import enabled

    ensure(db)
    results = [
        json.loads(r[0])
        for r in db.execute("SELECT payload FROM native_alignments WHERE material_id=?", (mid,))
    ]
    for r in results:
        asset = r.get("input", {}).get("asset", {})
        p = Path(asset.get("path", ""))
        r["stale"] = (
            r.get("adapter_version") != ADAPTER_VERSIONS[r["model"]]
            or not p.is_file()
            or r.get("model_revision") != model_revision(r["model"])
        )
        if p.is_file():
            r["stale"] |= r.get("input", {}).get("file_stat") != [p.stat().st_size, p.stat().st_mtime_ns]
    return {
        "models": [
            {
                "id": k,
                "name": v,
                "available": "native-alignment" in enabled()
                and (ROOT / "models" / k / "model.safetensors").is_file(),
            }
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
    from .editions import archived_module

    return archived_module("native-alignment").run(payload, jid)
