"""日语文本前端（规格 08 §8.2；ARCHITECTURE §8 的 ja 插拔点）。基线规则，按规格逐条实现，不顺手优化。

- 规范化：逐码位替换、保持字符位置（三种波浪号 → 长音符；空白、标点、符号 → 停顿「、」）；
- 音素：pyopenjtalk-plus（tsqyomi 读音）的逐词结果拼接；停顿类标签统一为 ``pau``、连续的只留一个；重复元音、清音 I/U、N、cl 原样保留；
- mora：读音（片假名，去掉重音记号）切成 mora，小写的 ァィゥェォャュョヮ 并入前一个字、「ー」单独成拍；
  每个词只有“核心音素数 = 该词 mora 数 = 切出的 mora 数”时才建立音素 → mora 映射（辅音归它后面的核心音素所在的 mora），否则未知（不硬凑）；
- 每个 mora 记录所在的词（原文、字符范围、读音），用于命名与词定位；
- 词定位：只在长音等价时归一（「ー」= 前一拍的元音；o 段后的「ウ」= 「オ」、e 段后的「イ」= 「エ」）。

G2P 由调用方注入（``g2p(规范化文本) -> 逐词映射``），单元测试不用加载模型。
"""

from __future__ import annotations

import json
import unicodedata
from collections.abc import Callable, Sequence
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from ...core.errors import CoreError

FRONTEND_VERSION = "ja-frontend-1"
PAUSES = frozenset({"pau", "sil", "sp", "SP"})
# 核心音素：音块与 mora 的核（规格 08 §8.2.3；cl 也占一拍）
CORE = frozenset({"a", "i", "u", "e", "o", "A", "I", "U", "E", "O", "N", "cl"})

_K = json.loads((Path(__file__).with_name("kana.json")).read_text(encoding="utf-8"))
TILDES = frozenset(_K["tildes"])
LONG = _K["long_vowel"]
PAUSE = _K["pause"]
ACCENTS = frozenset(_K["accent_marks"])
SMALL = frozenset(_K["small_merge"])
VOWEL_OF = {ch: v for v, chars in _K["rows"].items() for ch in chars}
VOWEL_KANA = _K["vowel_kana"]

G2P = Callable[[str], Sequence[dict[str, Any]]]


# ---------------------------------------------------------------- 规范化


def normalize(text: str) -> str:
    """逐码位替换，长度不变。"""
    out = []
    for ch in text:
        if ch in TILDES:
            out.append(LONG)
            continue
        cat = unicodedata.category(ch)
        if ch != LONG and (ch.isspace() or cat[0] in "PSZ" or cat in ("Cc", "Cf")):
            out.append(PAUSE)
        else:
            out.append(ch)
    return "".join(out)


# ---------------------------------------------------------------- mora


def split_mora(reading: str) -> list[str]:
    morae: list[str] = []
    for ch in reading:
        if ch in SMALL and morae and morae[-1] != LONG:
            morae[-1] += ch
        else:
            morae.append(ch)
    return morae


def clean_reading(pron: str) -> str:
    return "".join(ch for ch in pron if ch not in ACCENTS)


def vowel_of(mora: str) -> str | None:
    return VOWEL_OF.get(mora[-1]) if mora else None


def long_vowel_keys(reading: str) -> list[str]:
    """词定位用的 mora 键：长音等价（「ー」= 前一拍的元音；o 段后的ウ = オ；e 段后的イ = エ）。"""
    keys: list[str] = []
    prev_vowel: str | None = None
    for m in split_mora(reading):
        if m == LONG and prev_vowel:
            k = VOWEL_KANA[prev_vowel]
        elif m == VOWEL_KANA["u"] and prev_vowel == "o":
            k = VOWEL_KANA["o"]
        elif m == VOWEL_KANA["i"] and prev_vowel == "e":
            k = VOWEL_KANA["e"]
        else:
            k = m
        keys.append(k)
        v = vowel_of(k)
        prev_vowel = v if v else (prev_vowel if m == LONG else None)
    return keys


# ---------------------------------------------------------------- 结果


@dataclass(frozen=True)
class Word:
    text: str  # 原文（未规范化），字符范围对不上时为表层形
    start: int | None  # 原文字符范围 [start, end)；数字展开等对不上时为 None
    end: int | None
    reading: str  # 片假名读音（去掉重音记号）
    morae: list[str]
    mora_start: int  # 这个词的第一个 mora 在整句里的序号
    mapped: bool  # 音素 → mora 映射是否建立


@dataclass(frozen=True)
class FrontendResult:
    text: str
    normalized: str
    phonemes: list[str]
    phoneme_mora: list[int | None]  # 每个音素所属的 mora 序号（未知为 None）
    phoneme_word: list[int | None]  # 每个音素所属的词（停顿为 None）
    words: list[Word]
    morae: list[str]  # 整句的 mora（片假名）
    mora_word: list[int]  # 每个 mora 所属的词
    versions: dict[str, str] = field(default_factory=dict)

    def wire(self) -> dict[str, Any]:
        return asdict(self)


def analyze(text: str, g2p: G2P, versions: dict[str, str] | None = None) -> FrontendResult:
    norm = normalize(text)
    if not norm.replace(PAUSE, "").strip():
        raise CoreError("frontend-failed", reason="empty-text")
    try:
        entries = list(g2p(norm))
    except CoreError:
        raise
    except Exception as exc:  # noqa: BLE001 — 前端失败要写明原因，该项分析失败（不跳过前端硬对齐）
        raise CoreError("frontend-failed", reason="g2p", detail=f"{type(exc).__name__}: {exc}") from None
    phonemes: list[str] = []
    ph_mora: list[int | None] = []
    ph_word: list[int | None] = []
    words: list[Word] = []
    morae: list[str] = []
    mora_word: list[int] = []

    def push(p: str, mora: int | None, word: int | None) -> None:
        if p == "pau" and phonemes and phonemes[-1] == "pau":
            return
        phonemes.append(p)
        ph_mora.append(mora)
        ph_word.append(word)

    for e in entries:
        ph = ["pau" if p in PAUSES else p for p in e.get("phonemes") or []]
        if not ph:
            continue
        if all(p == "pau" for p in ph):
            push("pau", None, None)
            continue
        reading = clean_reading(str(e.get("pron") or ""))
        wm = split_mora(reading)
        widx = len(words)
        base = len(morae)
        core = [p for p in ph if p in CORE]
        mapped = len(core) == int(e.get("mora_count") or -1) == len(wm)
        morae += wm
        mora_word += [widx] * len(wm)
        assigned: list[int | None] = [None] * len(ph)
        if mapped:
            ci = 0
            pending: list[int] = []
            for k, p in enumerate(ph):
                if p in CORE:
                    idx = base + ci
                    ci += 1
                    for j in pending:
                        assigned[j] = idx
                    pending = []
                    assigned[k] = idx
                elif p != "pau":
                    pending.append(k)
        for k, p in enumerate(ph):
            push(p, assigned[k], None if p == "pau" else widx)
        a, b = (e.get("char_span") or (0, 0))
        located = (a, b) != (0, 0) and 0 <= a < b <= len(text)
        words.append(
            Word(
                text=text[a:b] if located else str(e.get("surface") or ""),
                start=a if located else None,
                end=b if located else None,
                reading=reading,
                morae=wm,
                mora_start=base,
                mapped=mapped,
            )
        )
    if not any(p != "pau" for p in phonemes):
        raise CoreError("frontend-failed", reason="no-phonemes")
    v = {"frontend": FRONTEND_VERSION, **(versions or {})}
    return FrontendResult(text, norm, phonemes, ph_mora, ph_word, words, morae, mora_word, v)


# ---------------------------------------------------------------- 词定位


def locate_words(words: Sequence[tuple[str, str]], reading: str) -> list[tuple[int, int] | None]:
    """把逐词的读音按顺序对到一整句的读音上（长音等价），返回每个词在 ``reading`` 里的字符范围；对不上的为 None。"""
    full = split_mora(reading)
    keys = long_vowel_keys(reading)
    starts: list[int] = []
    pos = 0
    for m in full:
        starts.append(pos)
        pos += len(m)
    starts.append(pos)
    out: list[tuple[int, int] | None] = []
    cur = 0
    for _surface, wr in words:
        wk = long_vowel_keys(wr)
        if wk and keys[cur : cur + len(wk)] == wk:
            out.append((starts[cur], starts[cur + len(wk)]))
            cur += len(wk)
        else:
            out.append(None)
    return out
