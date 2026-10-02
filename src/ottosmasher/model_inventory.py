"""Installed model assets, separate from runtime and actual inference verification."""

from pathlib import Path
from .workspace import ROOT, CODE_ROOT

MODELS = {
    "narabas": ["models/narabas/narabas-v0.onnx"],
    "phonetic": [
        "models/hubert/1218_hfa_model_new_dict/" + n
        for n in (
            "model.onnx",
            "config.json",
            "vocab.json",
            "VERSION",
            "japanese_dict_full.txt",
            "ds_cmudict-07b.txt",
            "ds-zh-pinyin-lite.txt",
        )
    ],
    "pydomino": ["models/pydomino/phoneme_transition_model.onnx"],
    "fcpe": ["models/features/fcpe.onnx"],
    "flatten": ["models/flatten/pc_nsf_hifigan.onnx", "models/flatten/config.json"],
    "tsqyomi": [
        "models/tsqyomi/model.onnx",
        "models/tsqyomi/tokenizer.json",
        "models/tsqyomi/metadata.json",
        "models/tsqyomi/preparation.json",
    ],
}


def model_path(relative):
    target = ROOT / relative
    if target.exists():
        return target
    if relative == MODELS["pydomino"][0]:
        legacy = ROOT / "vendor/pydomino/onnx_model/phoneme_transition_model.onnx"
        if legacy.exists():
            return legacy
    bundled = CODE_ROOT / "model-support" / relative
    return bundled if bundled.exists() else target


def inventory(config=None):
    from .inference_runtime import accelerator
    from .inference_evidence import read

    provider = (
        (accelerator() or "CPUExecutionProvider")
        if (config or {}).get("onnx_acceleration")
        else "CPUExecutionProvider"
    )
    result = []
    for name, files in MODELS.items():
        evidence = read(model_path(files[0]), provider)
        nodes = evidence.get("executed_nodes", {})
        state = "未实测"
        if evidence.get("status") == "failed":
            state = "实测失败：" + evidence.get("error", "")
        elif evidence.get("status") == "passed":
            state = "实测通过；节点执行：" + "、".join(
                k.replace("ExecutionProvider", "") + ":" + str(v) for k, v in nodes.items()
            )
            if provider != "CPUExecutionProvider" and not nodes.get(provider):
                state += "（本次没有加速节点）"
        result.append(
            {
                "id": name,
                "files": [{"path": str(model_path(p)), "present": model_path(p).is_file()} for p in files],
                "files_ready": all(model_path(p).is_file() for p in files),
                "inference_status": state,
                "evidence": evidence,
            }
        )
    return result


def install_support():
    import shutil

    support = CODE_ROOT / "model-support"
    if support.exists():
        for source in support.rglob("*"):
            if source.is_file() and (
                source.suffix in {".json", ".yaml", ".yml", ".txt"} or source.name == "VERSION"
            ):
                dest = ROOT / source.relative_to(support)
                if not dest.exists():
                    dest.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(source, dest)
