"""REAPER 交接的条目文本（规格 12 §12.3、16 R21.7）。纯函数，不做 IO。

剪贴板（REAPER 7.x macOS 实测格式）：类型 ``REAPERMedia``，UTF-8，各行以 NUL 分隔，末尾两个 NUL；内容是 ``<ITEM … >`` 块。
- 数值保留 12 位小数；文件路径加引号时从 ``"`` ``'`` `````` 里选一个路径里没有的；路径含 NUL/CR/LF → 拒绝；标记非单调 → 拒绝；
- 拉伸标记 ``SM 目标 源 0 0 目标/拍长 + …``：目标与源都严格递增（时间映射的节点 + 保护核心的锚点，每个起音都有）；
- ``.RTrackTemplate``（试验入口）：同样的 ITEM，换行分隔。
时间：条目内的秒（目标 = 卡拍后的条目时间，源 = 原声 WAV 文件的秒）。
"""

from __future__ import annotations

import uuid
from collections.abc import Callable, Sequence
from dataclasses import dataclass

from ..core.errors import CoreError

PLAYRATE = "PLAYRATE 1 1 0 -1 0 0.0025"
QUOTES = ('"', "'", "`")
MAX_CLIPBOARD_BYTES = 2 * 1024 * 1024


def f12(x: float) -> str:
    return f"{x:.12f}"


def quoted(text: str, field: str) -> str:
    if any(c in text for c in "\0\r\n"):
        raise CoreError("reaper-path-invalid", field=field)
    for q in QUOTES:
        if q not in text:
            return f"{q}{text}{q}"
    raise CoreError("reaper-path-invalid", field=field)


def _title(name: str) -> str:
    clean = "".join(" " if c in "\0\r\n" else c for c in name)
    if all(q in clean for q in QUOTES):
        clean = clean.replace('"', "'")
    return quoted(clean, "name")


@dataclass(frozen=True)
class Item:
    position: float  # 秒（相对第一条）
    snap: float  # 吸附偏移（秒，条目内）：首个起音，或 0 = 以条目开头为准
    length: float  # 条目长度（卡拍后，秒）
    beat: float  # 拍长（秒）
    name: str
    markers: Sequence[tuple[float, float]]  # (目标秒, 源秒)
    path: str


def check_markers(markers: Sequence[tuple[float, float]]) -> None:
    for (t0, s0), (t1, s1) in zip(markers, markers[1:]):
        if not (t1 > t0 and s1 > s0):
            raise CoreError("reaper-markers-not-monotonic", at=round(t1, 6))


def item_lines(it: Item, guid: Callable[[], str] | None = None) -> list[str]:
    g = guid or (lambda: "{" + str(uuid.uuid4()).upper() + "}")
    check_markers(it.markers)
    sm = " + ".join(f"{f12(t)} {f12(s)} 0 0 {f12(t / it.beat)}" for t, s in it.markers)
    return [
        "<ITEM",
        f"POSITION {f12(it.position)} {f12(it.position / it.beat)}",
        f"SNAPOFFS {f12(it.snap)} {f12(it.snap / it.beat)}",
        f"LENGTH {f12(it.length)} {f12(it.length / it.beat)}",
        "LOOP 0",
        "ALLTAKES 0",
        "FADEIN 1 0 0 1 0 0 0",
        "FADEOUT 1 0 0 1 0 0 0",
        "MUTE 0 0",
        "SEL 1",
        f"IGUID {g()}",
        f"NAME {_title(it.name)}",
        "VOLPAN 1 0 1 -1",
        "SOFFS 0",
        PLAYRATE,
        "CHANMODE 0",
        f"GUID {g()}",
        f"SM {sm}",
        "<SOURCE WAVE",
        f"FILE {quoted(it.path, 'path')}",
        ">",
        ">",
    ]


def clipboard(items: Sequence[Item], guid: Callable[[], str] | None = None) -> str:
    """剪贴板内容（字符串，各行 NUL 分隔、末尾两个 NUL）；超过约 2 MB 拒绝。"""
    lines = [ln for it in items for ln in item_lines(it, guid)]
    text = "\0".join(lines) + "\0\0"
    if len(text.encode("utf-8")) > MAX_CLIPBOARD_BYTES:
        raise CoreError("reaper-too-large", bytes=len(text.encode("utf-8")), max=MAX_CLIPBOARD_BYTES)
    return text


def template(items: Sequence[Item], guid: Callable[[], str] | None = None) -> str:
    """``.RTrackTemplate``（试验）：同样的 ITEM，换行分隔。"""
    return "\n".join(ln for it in items for ln in item_lines(it, guid)) + "\n"


def lay_out(lengths: Sequence[float], beats: Sequence[float], bar_beats: int = 4) -> list[float]:
    """批量依次排开（所有者 2026-10-08）：一条接一条，每条之间空一小节（按前一条的拍长）。"""
    pos, out = 0.0, []
    for i, L in enumerate(lengths):
        out.append(pos)
        pos += L + bar_beats * beats[i]
    return out
