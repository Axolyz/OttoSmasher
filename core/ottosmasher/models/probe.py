"""实测（规格 14 §14.7、13 §13.4；ROADMAP L6）：在当前设备设置下给每个模型做一次最小推理，记“实测通过 + 节点分布”或“实测失败 + 原因”。

分析任务（阶段 4.5 起）在首次推理时也会交回同样的记录；设置页的「实测」只是不用等真正分析就能看到结果。
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Any

import numpy as np

from ..core.errors import CoreError
from . import registry
from .onnx import Device, Session, create_session

PROBE_SENTENCE = "\u4f55\u3092\u3057\u3066\u3044\u308b\u306e\u3002"  # 「何をしているの。」：含多读音字，一定会用到 tsqyomi（core 里不写 CJK 字面量）


def _record(model: str, device: Device, status: str, *, nodes: dict[str, int] | None = None, error: str | None = None, sha: str | None = None) -> dict[str, Any]:
    return {"model": model, "device": device.wire(), "file_sha": sha, "status": status, "nodes": nodes, "error": error}


def _run_pydomino(sess: Session, models_dir: Path, support_dir: Path) -> None:
    sess.run(["transition_logprobs", "blank_logprobs"], {"input_waveform": np.zeros((1, 16000), dtype=np.float32)})


def _run_tsqyomi(sess: Session, models_dir: Path, support_dir: Path) -> None:
    from ..lang.ja import openjtalk  # noqa: PLC0415

    openjtalk.install_tsqyomi(
        sess,
        registry.locate("tsqyomi", "tsqyomi/tokenizer.json", models_dir, support_dir),
        registry.locate("tsqyomi", "tsqyomi/metadata.json", models_dir, support_dir),
    )
    openjtalk.load().g2p_mapping(PROBE_SENTENCE, use_tsqyomi=True, normalize_mode="None")


def _run_fcpe(sess: Session, models_dir: Path, support_dir: Path) -> None:
    sess.run(["latent"], {"mel": np.zeros((1, 64, 128), dtype=np.float32)})


def _run_hifigan(sess: Session, models_dir: Path, support_dir: Path) -> None:
    sess.run(["audio"], {"mel": np.zeros((1, 128, 32), dtype=np.float32), "f0": np.full((1, 32), 220.0, dtype=np.float32)})


# 模型 → (权重文件, 最小推理)
RUNNERS: dict[str, tuple[str, Callable[[Session, Path, Path], None]]] = {
    "pydomino": ("pydomino/phoneme_transition_model.onnx", _run_pydomino),
    "tsqyomi": ("tsqyomi/model.onnx", _run_tsqyomi),
    "fcpe": ("features/fcpe.onnx", _run_fcpe),
    "pc_nsf_hifigan": ("flatten/pc_nsf_hifigan.onnx", _run_hifigan),
}


def probe_model(model: str, models_dir: Path, support_dir: Path, device: Device, *, ort: Any = None) -> dict[str, Any] | None:
    """一个模型的实测记录；权重文件不在就不实测（返回 None，界面照旧显示“缺少文件”）。"""
    rel, run = RUNNERS[model]
    path, sha = registry.locate(model, rel, models_dir, support_dir)
    if not path.is_file():
        return None
    try:
        sess = create_session(model, path, sha, device, ort=ort)
    except CoreError as exc:
        return _record(model, device, "failed", error=f"{exc.code}: {exc.args_}", sha=sha)
    try:
        run(sess, models_dir, support_dir)
    except CoreError as exc:
        return sess.probe or _record(model, device, "failed", error=f"{exc.code}: {exc.args_}", sha=sha)
    except Exception as exc:  # noqa: BLE001 — 实测失败要如实记下原因
        return sess.probe or _record(model, device, "failed", error=f"{type(exc).__name__}: {exc}", sha=sha)
    return sess.probe or _record(model, device, "failed", error="no-inference", sha=sha)


def probe_all(models_dir: Path, support_dir: Path, device: Device, progress: Callable[[int, int, str], None] | None = None) -> list[dict[str, Any]]:
    out = []
    names = list(RUNNERS)
    for i, m in enumerate(names):
        if progress:
            progress(i, len(names), m)
        r = probe_model(m, models_dir, support_dir, device)
        if r is not None:
            out.append(r)
    if progress:
        progress(len(names), len(names), "")
    return out
