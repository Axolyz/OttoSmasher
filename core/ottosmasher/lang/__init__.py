"""采样语言的插拔点（规格 08 §8.9、04 §4.9；ARCHITECTURE §8）。

语言是数据属性（采样、字幕、对齐文本、测量输入都记语言，默认 ``ja``）；分析、检索、命名按语言取这里登记的实现。
本轮只登记日语；中文、英文的前端与对齐模型由所有者另行定型。
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from ..core.errors import CoreError

DEFAULT_LANGUAGE = "ja"


@dataclass(frozen=True)
class LanguageProfile:
    code: str
    normalize: Callable[[str], str]  # 逐码位替换，保持字符位置
    analyze: Callable[..., Any]  # (文本, g2p, versions) -> FrontendResult
    split_syllables: Callable[[str], list[str]]  # mora / 音节切分
    core_phonemes: frozenset[str]  # 音块核心（也是 mora 的核）
    aligner: str  # 对齐模型的身份（写进测量）


def _ja() -> LanguageProfile:
    from ..models import domino
    from .ja import frontend

    return LanguageProfile("ja", frontend.normalize, frontend.analyze, frontend.split_mora, frontend.CORE, domino.DECODER_VERSION)


_FACTORIES: dict[str, Callable[[], LanguageProfile]] = {"ja": _ja}
_cache: dict[str, LanguageProfile] = {}


def get(code: str | None) -> LanguageProfile:
    code = code or DEFAULT_LANGUAGE
    if code not in _cache:
        factory = _FACTORIES.get(code)
        if factory is None:
            raise CoreError("language-unsupported", language=code)
        _cache[code] = factory()
    return _cache[code]
