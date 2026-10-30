"""pydomino 对齐（规格 14 §14.3、08 §8.3）：ONNX 推理走统一会话工厂，tokenizer 与 Viterbi 用上游 C++（本机扩展 ``_domino``）。

- 输入音频：16 kHz、单声道、float32（调用方从资产解码并多相重采样）；
- 模型：输入 ``input_waveform`` [1, N]，输出 ``transition_logprobs`` [1, T, K] 与 ``blank_logprobs`` [1, T]，T 为 10 ms 帧数；
- 每个音素最少帧数默认 1；``最少帧数 × (转移数 − 1) + 1 > 帧数`` 时自动降到 ``(帧数 − 1) / (转移数 − 1)``（与上游同一判断）；
  降到 0（帧数 < 转移数）就报 ``align-audio-too-short``——上游解码在最少帧数 0 时越界写；
- 输出相邻接续的区间：第 i 个的结束 = ``帧号 / 100`` 秒，最后一个持续到 ``采样数 / 16000``。
"""

from __future__ import annotations

import importlib.machinery
import importlib.util
import os
import platform
import sys
from dataclasses import dataclass
from pathlib import Path
from types import ModuleType
from typing import Any

import numpy as np

from ..core.errors import CoreError
from .onnx import Session

SAMPLE_RATE = 16000
FRAME_SECONDS = 0.01
MODEL_ID = "pydomino"
MODEL_FILE = "pydomino/phoneme_transition_model.onnx"
REVISION = "4930396642fdd85618884c7a209218a628fd3c34"
DECODER_VERSION = f"pydomino@{REVISION[:7]}"
PAUSES = frozenset({"pau", "sil", "sp", "SP"})

_native: ModuleType | None = None


def platform_tag() -> str:
    machine = platform.machine().lower()
    machine = {"x86_64": "x64", "amd64": "x64", "aarch64": "arm64"}.get(machine, machine)
    return f"{sys.platform}-{machine}"


def native_dir() -> Path:
    env = os.environ.get("OTTO_NATIVE_DIR")
    if env:
        return Path(env)
    from .. import resources

    return resources.root() / "third_party" / "native" / platform_tag()


def native() -> ModuleType:
    """加载本机扩展（tools/build_domino.py 的产物）；没有就明确报错，不改用别的实现。"""
    global _native
    if _native is not None:
        return _native
    d = native_dir()
    found = sorted(d.glob("_domino*")) if d.is_dir() else []
    if not found:
        raise CoreError("native-missing", name="_domino", path=str(d))
    loader = importlib.machinery.ExtensionFileLoader("_domino", str(found[0]))
    spec = importlib.util.spec_from_file_location("_domino", found[0], loader=loader)
    assert spec is not None
    mod = importlib.util.module_from_spec(spec)
    loader.exec_module(mod)
    _native = mod
    return mod


def prepare_sequence(sentences: list[list[str]]) -> list[str]:
    """送进上游 tokenizer 之前的音素序列（14 §14.3）：清音 I/U → i/u、停顿类记为 pau、每句后加 pau、最前面加 pau、合并相邻 pau。
    重复元音不合并。"""
    out = ["pau"]
    for sent in sentences:
        for p in sent:
            q = "pau" if p in PAUSES else {"I": "i", "U": "u"}.get(p, p)
            out.append(q)
        out.append("pau")
    merged: list[str] = []
    for p in out:
        if p == "pau" and merged and merged[-1] == "pau":
            continue
        merged.append(p)
    return merged


@dataclass(frozen=True)
class Alignment:
    """``intervals``：(开始秒, 结束秒, 上游标签)，窗口局部秒，连续覆盖整个窗口（含首尾 pau）。"""

    intervals: list[tuple[float, float, str]]
    frames: int
    min_frames: int


class Aligner:
    def __init__(self, session: Session, mod: ModuleType | None = None) -> None:
        self.session = session
        self.mod = mod or native()

    def align(self, wave: np.ndarray, sequence: list[str], min_frames: int = 1) -> Alignment:
        if not sequence or all(p == "pau" for p in sequence):
            raise CoreError("align-empty")
        try:
            ids: list[int] = self.mod.tokenize(" ".join(sequence))
        except ValueError as exc:
            raise CoreError("align-unsupported", detail=str(exc)) from None
        x = np.ascontiguousarray(wave, dtype=np.float32).reshape(1, -1)
        trans, blank = self.session.run(["transition_logprobs", "blank_logprobs"], {"input_waveform": x})
        trans = np.ascontiguousarray(np.asarray(trans, dtype=np.float32)[0])
        blank = np.ascontiguousarray(np.asarray(blank, dtype=np.float32)[0])
        frames, vocab = int(trans.shape[0]), int(trans.shape[1])
        if frames < 2:
            raise CoreError("align-audio-too-short", frames=frames)
        n = len(ids)
        mf = int(min_frames)
        if n > 1 and mf * (n - 1) + 1 > frames:
            mf = (frames - 1) // (n - 1)
        if mf < 1:
            # 帧数不够每个音素占一帧：上游 Viterbi 在最少帧数 0 时会写到缓冲区之前（堆损坏），所以报太短
            raise CoreError("align-audio-too-short", frames=frames)
        times: list[int] = self.mod.solve(trans.tobytes(), blank.tobytes(), frames, vocab, mf, ids)
        labels: list[str] = self.mod.to_phonemes(ids)
        out: list[tuple[float, float, str]] = []
        begin = 0.0
        for i in range(n):
            end = times[i] * FRAME_SECONDS
            out.append((begin, end, labels[i]))
            begin = end
        out.append((begin, x.shape[1] / SAMPLE_RATE, labels[n]))
        return Alignment(out, frames, mf)


def run_dummy(session: Session) -> Any:
    """实测用的一次最小推理（1 秒静音）。"""
    return session.run(["transition_logprobs", "blank_logprobs"], {"input_waveform": np.zeros((1, SAMPLE_RATE), dtype=np.float32)})
