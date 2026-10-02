"""One provider boundary for every production separation route."""

import os

from .workspace import DATA


def provider():
    from .editions import require

    name = os.environ.get("OTTO_SEPARATION_PROVIDER", "studio")
    if name == "builtin":
        require("builtin-separation")
    elif name != "studio":
        raise ValueError("未知分离提供者")
    return name


def adapter():
    if provider() == "builtin":
        from .editions import archived_module

        return archived_module("builtin-separation")
    from . import studio

    return studio


def model_identity(name):
    from .inference_runtime import settings

    return {**adapter().fingerprint(name), "requested_device": settings()["inference_device"]}


def model_names(required="vocals"):
    backend = adapter()
    return [m["name"] for m in backend.models() if required in [s.lower() for s in backend.stems(m)]]


def separate(name, paths, output, stems=None, device=None):
    from .inference_runtime import settings

    device = device or settings()["inference_device"]
    jid = os.environ.get("OTTO_JOB_ID")
    progress = DATA / "jobs" / (jid + "-progress.json") if jid else None
    return adapter().separate_many(name, paths, output, stems, device, progress)
