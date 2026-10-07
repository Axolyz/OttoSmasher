"""资产局部时间 → 原片时间的映射（规格 04 §4.3.2、§4.4 #4；ARCHITECTURE §4.2）。

所有时钟换算只走这里（规格 17 §17.1 #1）：

- 原片时间 ↔ 资产局部时间：``Mapping``（控制点、分段线性、越界报错、不外推不夹取）；
- 资产局部时间 → 文件时间：``FileWindow``（资产存放在文件的哪一段，只叠加一次偏移，R3.6）；
- 采样显示坐标 → 资产局部时间：``display_to_local``（采样选区起点为 0）；
- 选区端点的 PCM 舍入：``check_range``（允许一帧，R3.4）。

浮点比较统一用 ``EPS``；``EPS`` 之内的越界视为浮点误差并贴到边界上，超过就报错。
"""

from __future__ import annotations

import math
from bisect import bisect_right
from collections.abc import Iterable, Sequence
from dataclasses import dataclass

from ottosmasher.core.errors import CoreError

EPS = 1e-9
"""秒。只吸收浮点误差，不是业务容差。"""

FULL_TRACK_TOLERANCE = 0.020
"""秒。默认轨“完整覆盖且未变速”的容差（规格 04 §4.2.3，R2.1）。"""

Point = tuple[float, float]


def _out_of_range(t: float, lo: float, hi: float, clock: str) -> CoreError:
    return CoreError("time-out-of-range", t=t, start=lo, end=hi, clock=clock)


def _interp(xs: Sequence[float], ys: Sequence[float], x: float) -> float:
    """在严格递增的 xs 上分段线性插值；调用方保证 xs[0] ≤ x ≤ xs[-1]。"""
    if x <= xs[0]:
        return ys[0]
    if x >= xs[-1]:
        return ys[-1]
    i = bisect_right(xs, x) - 1
    x0, x1, y0, y1 = xs[i], xs[i + 1], ys[i], ys[i + 1]
    return y0 + (x - x0) * (y1 - y0) / (x1 - x0)


@dataclass(frozen=True)
class Mapping:
    """控制点 ``[(局部秒, 原片秒), …]``：两列严格递增，首点局部 = 0，末点局部 = 资产时长。"""

    points: tuple[Point, ...]

    def __post_init__(self) -> None:
        pts = self.points
        if len(pts) < 2:
            raise CoreError("mapping-invalid", reason="too-few-points")
        for loc, src in pts:
            if not (math.isfinite(loc) and math.isfinite(src)):
                raise CoreError("mapping-invalid", reason="not-finite")
        if pts[0][0] != 0.0:
            raise CoreError("mapping-invalid", reason="first-local-not-zero")
        if pts[0][1] < 0.0:
            raise CoreError("mapping-invalid", reason="negative-source")
        for (l0, s0), (l1, s1) in zip(pts, pts[1:]):
            if not (l1 > l0 and s1 > s0):
                raise CoreError("mapping-invalid", reason="not-increasing")

    # ---- 构造 ----

    @classmethod
    def of(cls, points: Iterable[Sequence[float]]) -> Mapping:
        """从 JSON 形式 ``[[local, source], …]`` 构造并校验。"""
        return cls(tuple((float(p[0]), float(p[1])) for p in points))

    @classmethod
    def identity(cls, duration: float) -> Mapping:
        """原片自带音频流的整轨资产：局部时间就是原片时间。"""
        return cls(((0.0, 0.0), (float(duration), float(duration))))

    def to_list(self) -> list[list[float]]:
        return [[loc, src] for loc, src in self.points]

    # ---- 属性 ----

    @property
    def duration(self) -> float:
        """资产局部时长。"""
        return self.points[-1][0]

    @property
    def source_start(self) -> float:
        return self.points[0][1]

    @property
    def source_end(self) -> float:
        return self.points[-1][1]

    @property
    def _locals(self) -> tuple[float, ...]:
        return tuple(p[0] for p in self.points)

    @property
    def _sources(self) -> tuple[float, ...]:
        return tuple(p[1] for p in self.points)

    # ---- 换算 ----

    def to_source(self, t: float) -> float:
        """资产局部秒 → 原片秒；超出 [0, 时长] 报错。"""
        if t < -EPS or t > self.duration + EPS:
            raise _out_of_range(t, 0.0, self.duration, "local")
        return _interp(self._locals, self._sources, t)

    def to_local(self, s: float) -> float:
        """原片秒 → 资产局部秒；超出资产覆盖的原片范围报错。"""
        if s < self.source_start - EPS or s > self.source_end + EPS:
            raise _out_of_range(s, self.source_start, self.source_end, "source")
        return _interp(self._sources, self._locals, s)

    # ---- 组合 ----

    def crop(self, a: float, b: float) -> Mapping:
        """选区 [a, b) 的映射 = ``[(0, f(a)), …中间点平移 −a…, (b−a, f(b))]``（规格 04 §4.3.2）。"""
        if not b > a:
            raise CoreError("range-invalid", reason="empty", start=a, end=b, duration=self.duration)
        fa, fb = self.to_source(a), self.to_source(b)
        a, b = max(a, 0.0), min(b, self.duration)
        mid = [(loc - a, src) for loc, src in self.points if a + EPS < loc < b - EPS]
        return Mapping(((0.0, fa), *mid, (b - a, fb)))

    def compose(self, inner: Mapping) -> Mapping:
        """``inner`` 把新局部时间映射到本资产的局部时间（例如卡拍渲染的“目标时间 → 资产时间”），
        返回新局部时间 → 原片时间。``inner`` 的值域必须落在本资产 [0, 时长] 之内。"""
        if inner.source_start < -EPS or inner.source_end > self.duration + EPS:
            raise _out_of_range(
                inner.source_start if inner.source_start < -EPS else inner.source_end,
                0.0,
                self.duration,
                "local",
            )
        knots = set(inner._locals)
        for loc in self._locals:
            if inner.source_start + EPS < loc < inner.source_end - EPS:
                knots.add(inner.to_local(loc))
        out: list[Point] = []
        for t in sorted(knots):
            if out and t - out[-1][0] <= EPS:
                continue
            out.append((t, self.to_source(inner.to_source(t))))
        # 末点必须正好是新时长
        out[-1] = (inner.duration, out[-1][1])
        return Mapping(tuple(out))

    def reimport(self, start: float, file_duration: float, *, frame: float) -> Mapping:
        """回导：以选区起点为准、终点按文件时长（规格 04 §4.3.2、R3.7–R3.8）；
        越出本资产边界（超过一帧）拒绝。返回新资产的映射。"""
        if not file_duration > 0:
            raise CoreError("range-invalid", reason="empty", start=start, end=start, duration=self.duration)
        start, end = check_range(start, start + file_duration, self.duration, frame=frame)
        m = self.crop(start, end)
        # 新资产的时长就是文件时长（一帧之内的贴边与浮点误差都归到末点上）
        return Mapping((*m.points[:-1], (file_duration, m.points[-1][1])))

    # ---- 判定 ----

    def is_full_track(self, source_duration: float, tol: float = FULL_TRACK_TOLERANCE) -> bool:
        """完整覆盖原片且未变速（R2.1–R2.2）：每个控制点都满足 |原片秒 − 局部秒| ≤ 容差，且时长≈原片时长。"""
        if abs(self.duration - source_duration) > tol:
            return False
        return all(abs(src - loc) <= tol for loc, src in self.points)


def check_range(start: float, end: float, duration: float, *, frame: float) -> tuple[float, float]:
    """校验资产选区 ``0 ≤ start < end ≤ 时长``，端点越界一帧之内贴到边界，超过报错（R3.4）。

    ``frame`` 是一个采样周期（1 / 采样率）。
    """
    tol = frame + EPS
    if not (math.isfinite(start) and math.isfinite(end)) or not end > start:
        raise CoreError("range-invalid", reason="empty", start=start, end=end, duration=duration)
    if start < -tol or end > duration + tol:
        raise CoreError("range-invalid", reason="out-of-bounds", start=start, end=end, duration=duration)
    start, end = max(start, 0.0), min(end, duration)
    if not end > start:
        raise CoreError("range-invalid", reason="empty", start=start, end=end, duration=duration)
    return start, end


def display_to_local(t: float, selection_start: float, selection_end: float) -> float:
    """采样显示坐标（选区起点为 0）→ 资产局部秒。"""
    length = selection_end - selection_start
    if t < -EPS or t > length + EPS:
        raise _out_of_range(t, 0.0, length, "display")
    return selection_start + min(max(t, 0.0), length)


def local_to_display(t: float, selection_start: float, selection_end: float) -> float:
    """资产局部秒 → 采样显示坐标。"""
    if t < selection_start - EPS or t > selection_end + EPS:
        raise _out_of_range(t, selection_start, selection_end, "local")
    return min(max(t, selection_start), selection_end) - selection_start


@dataclass(frozen=True)
class FileWindow:
    """资产局部区间 [local_start, local_end) 存放在文件的 file_start 秒起（ARCHITECTURE §4.2 ``asset_storage``）。

    普通资产：local_start = 0、file_start = 0；独立化的切片：local_start = 切片起点、file_start = 0；
    共享整轨文件上的一段：file_start = 该段在文件里的起点。
    """

    local_start: float
    local_end: float
    file_start: float = 0.0

    def to_file(self, t: float) -> float:
        """资产局部秒 → 文件秒（只叠加一次偏移，R3.6）。"""
        if t < self.local_start - EPS or t > self.local_end + EPS:
            raise _out_of_range(t, self.local_start, self.local_end, "local")
        t = min(max(t, self.local_start), self.local_end)
        return self.file_start + (t - self.local_start)

    def covers(self, start: float, end: float) -> bool:
        return start >= self.local_start - EPS and end <= self.local_end + EPS
