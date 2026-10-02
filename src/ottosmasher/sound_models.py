"""Continuous three-stem adapters backed exclusively by the selected provider."""

from . import studio
from .workspace import identity

ALIASES = {
    "speech": "dialog",
    "dialogue": "dialog",
    "dialog": "dialog",
    "music": "music",
    "effects": "effect",
    "effect": "effect",
    "sfx": "effect",
}
MODELS = {}  # Historical route identifiers remain readable in stored results.
CINEMATIC = ()


def statuses():
    try:
        return [
            {
                "id": m["name"],
                "name": m["name"],
                "available": True,
                "missing": [],
                "status": "ready",
                "reason": "",
                "provider": "studio",
            }
            for m in studio.models()
            if {ALIASES.get(s.lower()) for s in studio.stems(m)} >= {"dialog", "music", "effect"}
        ]
    except (ValueError, RuntimeError, OSError):
        return []


def fingerprint(model):
    return identity(studio.fingerprint(model))


def infer(operation, paths, output, **params):
    from .separation import separate

    if operation not in {m["id"] for m in statuses()}:
        raise ValueError("Studio 中没有已下载的对白/音乐/音效三轨模型；请先在 Studio 下载并选择模型")
    rows = separate(operation, paths, output, device=params.get("device", "auto"))
    return {
        "outputs": [
            {ALIASES[x["stem"].lower()]: x["path"] for x in group if x["stem"].lower() in ALIASES}
            for group in rows
        ],
        "execution": {
            "provider": "studio",
            "model_fingerprint": fingerprint(operation),
            "model": operation,
            "parameters": params,
        },
    }
