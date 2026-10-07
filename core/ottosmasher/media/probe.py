"""媒体探测（规格 05 §5.1、ARCHITECTURE §4.1）：ffprobe → 流列表 + 文件快照。

- 音频流按“第几条音频流”编号（``ordinal`` 从 0 起，与 ffmpeg ``-map 0:a:N`` 一致；mpv 的 ``aid`` = ordinal + 1）；
- 音频文件里的封面图（``disposition.attached_pic``）记为视频流但标 ``is_attached_pic``，不算视频；
- 流时长依次取 ``duration`` → ``duration_ts × time_base`` → Matroska 的 ``DURATION`` 标签 → 扫描该流的包时间戳（最后一包结束 − 第一包开始，
  只读容器、不解码；KF08 这类没有时长标签的片源）；都没有就是未知（None），不拿容器时长冒充；
- 文件快照（取代内容指纹，QUESTIONS D3）：大小 + 修改时间 + 流签名，不读内容、不算哈希。
"""

from __future__ import annotations

import json
import os
import re
import subprocess
from dataclasses import asdict, dataclass, replace
from fractions import Fraction
from pathlib import Path
from typing import Any

from ottosmasher.core.errors import CoreError

from . import tools

PROBE_TIMEOUT = 60.0


@dataclass(frozen=True)
class Stream:
    kind: str  # "audio" / "video"
    ordinal: int  # 同类流里的序号（从 0 起；封面图也占视频序号）
    container_index: int
    codec: str | None
    sample_rate: int | None
    channels: int | None
    bit_depth: int | None
    language: str | None
    title: str | None
    start_time: float | None
    duration: float | None
    is_attached_pic: bool = False


@dataclass(frozen=True)
class Probe:
    format_name: str | None
    format_duration: float | None
    streams: tuple[Stream, ...]

    @property
    def audio(self) -> list[Stream]:
        return [s for s in self.streams if s.kind == "audio"]

    @property
    def video(self) -> list[Stream]:
        """真正的视频流（不含封面图）。"""
        return [s for s in self.streams if s.kind == "video" and not s.is_attached_pic]


def _num(v: Any) -> float | None:
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    return f if f == f else None  # NaN → None


def _int(v: Any) -> int | None:
    try:
        i = int(v)
    except (TypeError, ValueError):
        return None
    return i if i > 0 else None


_HMS = re.compile(r"^(\d+):(\d{2}):(\d{2}(?:\.\d+)?)$")


def _stream_duration(s: dict[str, Any]) -> float | None:
    d = _num(s.get("duration"))
    if d is not None:
        return d
    ts, tb = s.get("duration_ts"), s.get("time_base")
    if ts is not None and tb:
        try:
            return float(int(ts) * Fraction(tb))
        except (ValueError, ZeroDivisionError):
            pass
    tags = {k.upper(): v for k, v in (s.get("tags") or {}).items()}
    m = _HMS.match(str(tags.get("DURATION", "")).strip())
    if m:
        return int(m.group(1)) * 3600 + int(m.group(2)) * 60 + float(m.group(3))
    return None


def parse(data: dict[str, Any]) -> Probe:
    counters = {"audio": 0, "video": 0}
    streams: list[Stream] = []
    for s in data.get("streams", []):
        kind = s.get("codec_type")
        if kind not in counters:
            continue
        tags = {k.lower(): v for k, v in (s.get("tags") or {}).items()}
        lang = tags.get("language")
        streams.append(
            Stream(
                kind=kind,
                ordinal=counters[kind],
                container_index=int(s.get("index", 0)),
                codec=s.get("codec_name"),
                sample_rate=_int(s.get("sample_rate")),
                channels=_int(s.get("channels")),
                bit_depth=_int(s.get("bits_per_raw_sample")) or _int(s.get("bits_per_sample")),
                language=None if lang in (None, "", "und") else str(lang),
                title=tags.get("title") or None,
                start_time=_num(s.get("start_time")),
                duration=_stream_duration(s),
                is_attached_pic=bool((s.get("disposition") or {}).get("attached_pic")),
            )
        )
        counters[kind] += 1
    fmt = data.get("format") or {}
    return Probe(fmt.get("format_name"), _num(fmt.get("duration")), tuple(streams))


def probe(path: str | Path) -> Probe:
    p = Path(path)
    if not p.is_file():
        raise CoreError("file-missing", path=str(p))
    cmd = [tools.find("ffprobe"), "-v", "error", "-print_format", "json", "-show_format", "-show_streams", "-i", str(p)]
    try:
        out = subprocess.run(cmd, capture_output=True, timeout=PROBE_TIMEOUT, stdin=subprocess.DEVNULL)
    except subprocess.TimeoutExpired:
        raise CoreError("media-probe-failed", path=str(p), detail="timeout") from None
    if out.returncode != 0:
        detail = out.stderr.decode("utf-8", "replace").strip().splitlines()
        raise CoreError("media-probe-failed", path=str(p), detail=detail[-1] if detail else f"exit {out.returncode}")
    try:
        pr = parse(json.loads(out.stdout.decode("utf-8", "replace")))
    except (json.JSONDecodeError, TypeError) as e:
        raise CoreError("media-probe-failed", path=str(p), detail=str(e)) from None
    if any(s.duration is None and not s.is_attached_pic for s in pr.streams):
        pr = Probe(
            pr.format_name,
            pr.format_duration,
            tuple(
                replace(s, duration=packet_duration(p, s)) if s.duration is None and not s.is_attached_pic else s
                for s in pr.streams
            ),
        )
    return pr


def packet_duration(path: Path, s: Stream) -> float | None:
    """扫描一条流的包时间戳得到时长（最后一包结束 − 第一包开始）；读不出就是未知。"""
    sel = f"{'a' if s.kind == 'audio' else 'v'}:{s.ordinal}"
    cmd = [
        tools.find("ffprobe"), "-v", "error", "-select_streams", sel,
        "-show_entries", "packet=pts_time,duration_time", "-of", "csv=p=0", "-i", str(path),
    ]  # fmt: skip
    try:
        out = subprocess.run(cmd, capture_output=True, timeout=PROBE_TIMEOUT, stdin=subprocess.DEVNULL)
    except subprocess.TimeoutExpired:
        return None
    if out.returncode != 0:
        return None
    first: float | None = None
    end: float | None = None
    for line in out.stdout.decode("ascii", "replace").splitlines():
        parts = line.strip().split(",")
        pts = _num(parts[0]) if parts else None
        if pts is None:
            continue
        dur = _num(parts[1]) if len(parts) > 1 else None
        first = pts if first is None else min(first, pts)
        e = pts + (dur or 0.0)
        end = e if end is None else max(end, e)
    if first is None or end is None or end <= first:
        return None
    return end - first


# ---------------------------------------------------------------- 文件快照


def stream_signature(pr: Probe) -> list[list[Any]]:
    """各音频/视频流的编解码、采样率、声道、时长（毫秒取整，避免浮点噪声）。"""
    return [
        [s.kind, s.codec, s.sample_rate, s.channels, None if s.duration is None else round(s.duration * 1000)]
        for s in pr.streams
        if not s.is_attached_pic
    ]


def snapshot(path: str | Path, pr: Probe) -> dict[str, Any]:
    st = os.stat(path)
    return {"size": st.st_size, "mtime_ns": st.st_mtime_ns, "streams": stream_signature(pr)}


def check_unchanged(path: str | Path, snap: dict[str, Any]) -> None:
    """播放、导出、处理、测量前核对：文件缺失或大小/修改时间变了 → 报错（不替换、不回退）。

    只看 stat（不重新探测）；流签名用于重新定位时向用户说明差异。
    """
    try:
        st = os.stat(path)
    except FileNotFoundError:
        raise CoreError("file-missing", path=str(path)) from None
    changed = [k for k, v in (("size", st.st_size), ("mtime_ns", st.st_mtime_ns)) if snap.get(k) != v]
    if changed:
        raise CoreError("source-changed", path=str(path), what=",".join(changed))


def stream_dict(s: Stream) -> dict[str, Any]:
    return asdict(s)
