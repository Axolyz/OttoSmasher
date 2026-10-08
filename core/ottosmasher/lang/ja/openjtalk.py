"""pyopenjtalk-plus 0.4.1.post9 的加载（规格 14 §14.2）。

坑：这个版本 ``import pyopenjtalk`` 时会经 ``utils → yomi_model.nani_predict`` 在模块顶层建两个 ONNX 会话（旧的「何」读音模型）。
规格要求只加载 tsqyomi v4、不加载其他读音模型，所以导入前先放一个同名的空模块占位（我们总是用 ``use_tsqyomi=True``，
库在这时不会用「何」模型；万一被调用就报错，不静默改读音）。tsqyomi 的会话由应用的会话工厂创建后交给库（不让库自己建、也不让它下载）。
"""

from __future__ import annotations

import sys
import types
from pathlib import Path
from typing import Any

from ...core.errors import CoreError
from ...models.onnx import Session, check_file

PYOPENJTALK_VERSION = "0.4.1-post9"
TSQYOMI_REVISION = "680596dd2ad2bad59ee5db3741e197cfce79f9b4"
TSQYOMI_VERSION = f"tsqyomi-v4@{TSQYOMI_REVISION[:7]}"
_NANI = "pyopenjtalk.yomi_model.nani_predict"


def _nani_disabled(*_a: Any, **_k: Any) -> int:
    raise RuntimeError("pyopenjtalk nani model is disabled; use_tsqyomi=True must be used")


def load() -> types.ModuleType:
    """导入 pyopenjtalk（不建任何模型会话）。"""
    if "pyopenjtalk" in sys.modules:
        mod = sys.modules["pyopenjtalk"]
        nani = sys.modules.get(_NANI)
        if nani is None or getattr(nani, "predict", None) is not _nani_disabled:
            raise RuntimeError("pyopenjtalk was imported without the nani-model guard")
        return mod
    stub = types.ModuleType(_NANI)
    stub.predict = _nani_disabled  # type: ignore[attr-defined]
    stub.X_COLS = []  # type: ignore[attr-defined]
    sys.modules[_NANI] = stub
    import pyopenjtalk  # noqa: PLC0415
    from pyopenjtalk.tsqyomi import model as tsq  # noqa: PLC0415
    from pyopenjtalk.version import __version__  # noqa: PLC0415

    if __version__ != PYOPENJTALK_VERSION or tsq._MODEL_REVISION != TSQYOMI_REVISION:  # noqa: SLF001 — 固定版本的核对
        raise CoreError("frontend-failed", reason="library-version", detail=f"pyopenjtalk {__version__}, tsqyomi {tsq._MODEL_REVISION}")  # noqa: SLF001
    return pyopenjtalk


def install_tsqyomi(session: Session, tokenizer: tuple[Path, str], metadata: tuple[Path, str]) -> None:
    """把应用建好的 tsqyomi 会话交给库（核对支持文件的 SHA-256 与 ONNX 契约）。``tokenizer``/``metadata`` = (路径, SHA-256)。"""
    load()
    from pyopenjtalk.tsqyomi import model as tsq  # noqa: PLC0415
    from tokenizers import Tokenizer  # noqa: PLC0415

    check_file("tsqyomi", *tokenizer)
    check_file("tsqyomi", *metadata)
    meta = tsq.TsqyomiMetadata.load(metadata[0])
    tok = Tokenizer.from_file(str(tokenizer[0]))
    # 与库自己的加载一致：不截断、不补齐（推理时自己切窗口）
    tok.no_truncation()
    tok.no_padding()
    try:
        tsq.TsqyomiModel.validate_onnx_contract(session, meta)
    except ValueError as exc:
        raise CoreError("frontend-failed", reason="tsqyomi-contract", detail=str(exc)) from None
    with tsq._lifecycle_condition:  # noqa: SLF001 — 库没有“用现成会话”的公开接口
        tsq._loaded_model = tsq.TsqyomiModel(tok, session, meta)  # noqa: SLF001


def tsqyomi_loaded() -> bool:
    if "pyopenjtalk" not in sys.modules:
        return False
    from pyopenjtalk.tsqyomi import model as tsq  # noqa: PLC0415

    return bool(tsq.is_model_loaded())
