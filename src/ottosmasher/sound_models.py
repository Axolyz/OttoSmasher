from .workspace import CODE_ROOT
"""Model adapters, explicit availability and serial inference outside the service."""

import json
import os
import subprocess
from pathlib import Path

from .inference_runtime import python_path
from .workspace import DATA, ROOT, identity

MODELS = {"bandit-v2": {
    "env": "inference", "weights": ["bandit-v2/model.ckpt", "bandit-v2/config.yaml"],
    "name": "BandIt v2 · 多语言", "url": "https://github.com/kwatcharasupat/bandit-v2"}}
CINEMATIC = ("bandit-v2",)


def statuses():
    checks = ROOT / ".runtime/sound-model-validation.json"
    validated = json.loads(checks.read_text()) if checks.exists() else {}
    out = []
    for key, m in MODELS.items():
        missing = [
            str(ROOT / "models/sound-lab" / p)
            for p in m["weights"]
            if not (ROOT / "models/sound-lab" / p).is_file()
        ]
        ready = (
            python_path().is_file()
            and not missing
            and not m.get("blocked")
        )
        out.append(
            {
                "id": key,
                **m,
                "available": ready,
                "missing": missing,
                "validation": validated.get(key),
                "status": "ready" if ready else "unavailable",
                "reason": m.get("blocked")
                or (
                    "缺少模型文件"
                    if missing
                    else ""
                ),
            }
        )
    return out


def fingerprint(model):
    from .materials import sha256

    # Read weight digests once per file modification, persisted locally for large models.
    p = DATA / "model-fingerprints.json"
    cache = json.loads(p.read_text()) if p.exists() else {}
    digests = []
    for f in MODELS[model]["weights"]:
        path = ROOT / "models/sound-lab" / f
        if not path.exists():
            raise ValueError("缺少模型：" + str(path))
        k = str(path)
        stat = path.stat()
        signature = [stat.st_size, stat.st_mtime_ns]
        if cache.get(k, {}).get("stat") != signature:
            cache[k] = {"stat": signature, "sha256": sha256(path)}
        digests.append(cache[k]["sha256"])
    from .workspace import write_json

    write_json(p, cache)
    return identity(model, digests)


def infer(operation, paths, output, **params):
    model = operation
    if model not in MODELS:
        raise ValueError("已移除或未知的声音模型：" + model)
    status = next(x for x in statuses() if x["id"] == model)
    if not status["available"]:
        raise ValueError(
            status["name"] + " 不可运行：" + status["reason"] + " " + ", ".join(status["missing"])
        )
    output = Path(output)
    output.mkdir(parents=True, exist_ok=True)
    if model.startswith("bandit") and os.environ.get("OTTO_JOB_ID"):
        params["progress_path"] = str(DATA / "jobs" / (os.environ["OTTO_JOB_ID"] + "-progress.json"))
    req = {"operation": operation, "paths": list(map(str, paths)), "output": str(output), **params}
    request = output / "request.json"
    request.write_text(json.dumps(req))
    subprocess.run(
        [
            str(python_path()),
            str(CODE_ROOT / "scripts/sound_model_worker.py"),
            str(request),
        ],
        cwd=ROOT,
        check=True,
        env={
            **os.environ,
            "HF_HOME": str(ROOT / "models/huggingface"),
            "HF_HUB_OFFLINE": "1",
            "TRANSFORMERS_OFFLINE": "1",
        },
    )
    result = json.loads(request.with_suffix(".result.json").read_text())
    result["execution"] = {
        "adapter_version": "sound-adapter-2",
        "request_path": str(request),
        "model_fingerprint": fingerprint(model),
        "parameters": params,
        "seconds": result.get("seconds"),
        "peak_rss_bytes": result.get("peak_rss_bytes"),
        "bandit_options": {"tta": True, "batch_size": 1, "overlap": "fingerprinted config"}
        if model.startswith("bandit")
        else None,
    }
    return result
