"""任务种类与通道（规格 13 §13.1.1）。阶段 1 只有模型检测和自检任务；其余随各阶段登记。"""

from __future__ import annotations

# 种类 → 通道
KINDS: dict[str, str] = {
    "models.verify": "light",
    "models.download": "light",
    "models.import": "light",
    "models.probe": "model",
    "speech.analyze": "model",
    "dictionary.compile": "light",
    "dictionary.preview": "light",
    "studio.models": "light",
    "separate": "model",
    "flatten": "model",
    "import.scan": "light",
    "sources.scan": "light",
    "search.index": "light",
    "f0.measure": "model",
    "acoustic.measure": "model",
    "export.video": "light",
    "samples.independ": "light",
}

# 开发与测试用的自检任务（只在开发模式下可提交）
DEV_KINDS: dict[str, str] = {
    "selftest.sleep": "light",
    "selftest.sleep_model": "model",
    "selftest.fail": "light",
}


def channel_of(kind: str, *, dev: bool) -> str | None:
    if kind in KINDS:
        return KINDS[kind]
    if dev and kind in DEV_KINDS:
        return DEV_KINDS[kind]
    return None
