"""时间映射与选区：规格 16 R3.1–R3.4、R3.6–R3.8，R2.1–R2.2 的判定部分，R21.4 的映射组合。"""

import pytest
from hypothesis import given
from hypothesis import strategies as st

from ottosmasher.core.errors import CoreError
from ottosmasher.domain.mapping import (
    FileWindow,
    Mapping,
    check_range,
    display_to_local,
    local_to_display,
)

approx = pytest.approx
FRAME = 1 / 48000


def pts(m: Mapping):
    return [approx(list(p)) for p in m.points]


# R3.1 整轨映射上裁切：首点原片时间 2.5，第二点 [0.2, 3]；越界换算报错
def test_crop_on_offset_mapping():
    m = Mapping.of([[0, 2], [0.4, 3], [1, 4]])
    c = m.crop(0.2, 0.7)
    assert c.to_list() == pts(Mapping.of([[0, 2.5], [0.2, 3], [0.5, 3.5]]))
    with pytest.raises(CoreError) as ei:
        m.to_source(1.2)
    assert ei.value.code == "time-out-of-range"
    with pytest.raises(CoreError):
        m.to_source(-0.01)
    with pytest.raises(CoreError):
        m.to_local(1.9)
    with pytest.raises(CoreError):
        c.to_source(0.6)


# R3.2 多级裁切按原帧组合：子 0.1–0.7，孙取子的 0.125–0.225 → 绝对 0.225–0.325
def test_nested_crop_composes():
    asset = Mapping.identity(1.0)
    child = asset.crop(0.1, 0.7)
    grand = child.crop(0.125, 0.225)
    assert grand.source_start == approx(0.225)
    assert grand.source_end == approx(0.325)
    assert grand.duration == approx(0.1)


# R3.3 非线性映射后再裁切按控制点换算（不是按比例）
def test_crop_nonlinear_uses_control_points():
    m = Mapping.of([[0, 0.1], [0.3, 0.2], [0.6, 0.7]])
    c = m.crop(0.3, 0.45)
    assert (c.source_start, c.source_end) == (approx(0.2), approx(0.45))


# R3.4 PCM 舍入允许一帧：终点 1 + 1/48000 接受并截为 1；1.01 拒绝
def test_one_frame_rounding():
    assert check_range(0.5, 1 + FRAME, 1.0, frame=FRAME) == (0.5, 1.0)
    assert check_range(-FRAME, 0.5, 1.0, frame=FRAME) == (0.0, 0.5)
    with pytest.raises(CoreError) as ei:
        check_range(0.5, 1.01, 1.0, frame=FRAME)
    assert ei.value.code == "range-invalid"
    assert ei.value.args_["reason"] == "out-of-bounds"
    with pytest.raises(CoreError):
        check_range(0.5, 0.5, 1.0, frame=FRAME)
    with pytest.raises(CoreError):
        check_range(0.6, 0.5, 1.0, frame=FRAME)
    with pytest.raises(CoreError):
        check_range(float("nan"), 0.5, 1.0, frame=FRAME)


# R3.6 共享整轨上的区间叠加文件偏移，不重复叠加：句窗 0.1–0.3 对应文件 0.5–0.7
def test_file_offset_applied_once():
    win = FileWindow(local_start=0.0, local_end=2.0, file_start=0.4)
    assert (win.to_file(0.1), win.to_file(0.3)) == (approx(0.5), approx(0.7))
    # 独立化切片：资产局部 [3, 5) 存在切片文件的 0 秒起
    sl = FileWindow(local_start=3.0, local_end=5.0)
    assert sl.to_file(3.5) == approx(0.5)
    assert sl.covers(3.2, 4.0) and not sl.covers(2.9, 4.0)
    with pytest.raises(CoreError):
        sl.to_file(5.5)


def test_display_coordinates():
    assert display_to_local(0.1, 0.4, 0.7) == approx(0.5)
    assert local_to_display(0.5, 0.4, 0.7) == approx(0.1)
    with pytest.raises(CoreError):
        display_to_local(0.4, 0.4, 0.7)


# R3.7 回导：选区 0.2–0.7
def test_reimport():
    asset = Mapping.identity(1.0)
    assert asset.reimport(0.2, 0.5, frame=FRAME).to_list() == pts(Mapping.of([[0, 0.2], [0.5, 0.7]]))
    m = asset.reimport(0.2, 24002 / 48000, frame=FRAME)
    assert m.duration == 24002 / 48000
    assert m.source_end == approx(0.2 + 24002 / 48000)
    with pytest.raises(CoreError):
        asset.reimport(0.2, 1.0, frame=FRAME)


# R3.8 回导沿用非线性映射：导入 0.5 秒 → 局部终点 0.7；导入 0.8 秒 → 恰到 1.0 允许
def test_reimport_nonlinear():
    asset = Mapping.of([[0, 0], [0.4, 0.6], [1, 1]])
    m = asset.reimport(0.2, 0.5, frame=FRAME)
    assert m.duration == 0.5
    assert asset.to_local(m.source_end) == approx(0.7)
    assert m.points[1] == (approx(0.2), approx(0.6))  # 保留中间控制点
    m2 = asset.reimport(0.2, 0.8, frame=FRAME)
    assert m2.source_end == approx(1.0)
    with pytest.raises(CoreError):
        asset.reimport(0.2, 0.81, frame=FRAME)


# R21.4 卡拍：渲染映射与资产映射组合 → 清单 [[0,10],[0.5,10.8],[1,11.4]]
def test_compose_with_render_mapping():
    asset = Mapping.of([[0, 10], [0.4, 10.8], [1, 11.4]])
    render = Mapping.of([[0, 0], [0.5, 0.4], [1, 1]])  # 目标时间 → 资产局部时间
    assert asset.compose(render).to_list() == pts(Mapping.of([[0, 10], [0.5, 10.8], [1, 11.4]]))
    # 父映射的控制点落在子段中间时也要成为新控制点
    render2 = Mapping.of([[0, 0], [2, 1]])  # 匀速放慢一倍
    out = asset.compose(render2)
    assert out.to_list() == pts(Mapping.of([[0, 10], [0.8, 10.8], [2, 11.4]]))
    with pytest.raises(CoreError):
        asset.compose(Mapping.of([[0, 0.5], [1, 1.5]]))


# R2.1–R2.2 整轨判定：完整覆盖且未变速（容差 20 ms）
def test_full_track():
    assert Mapping.identity(1440.0).is_full_track(1440.0)
    assert Mapping.of([[0, 0.01], [1440.0, 1440.015]]).is_full_track(1440.0)
    assert not Mapping.of([[0, 0.1], [0.4, 0.5]]).is_full_track(1.0)  # 逐句资产
    assert not Mapping.of([[0, 0], [0.5, 0.2], [1, 1]]).is_full_track(1.0)  # 变速
    assert not Mapping.identity(1400.0).is_full_track(1440.0)  # 没覆盖完


@pytest.mark.parametrize(
    "points,reason",
    [
        ([[0, 0]], "too-few-points"),
        ([[0.1, 0], [1, 1]], "first-local-not-zero"),
        ([[0, 0], [0.5, 0.5], [0.5, 0.6]], "not-increasing"),
        ([[0, 0], [0.5, 0.5], [1, 0.4]], "not-increasing"),  # 倒放不能表达
        ([[0, 0], [float("inf"), 1]], "not-finite"),
        ([[0, -1], [1, 0]], "negative-source"),
    ],
)
def test_invalid_mapping(points, reason):
    with pytest.raises(CoreError) as ei:
        Mapping.of(points)
    assert ei.value.code == "mapping-invalid"
    assert ei.value.args_["reason"] == reason


# ---- 性质测试：往返、裁切与组合一致 ----

steps = st.lists(st.floats(0.01, 5.0), min_size=1, max_size=6)


@st.composite
def mappings(draw):
    dl, ds = draw(steps), draw(st.lists(st.floats(0.01, 5.0), min_size=1, max_size=6))
    n = min(len(dl), len(ds))
    loc, src = 0.0, draw(st.floats(0, 100))
    out = [(loc, src)]
    for i in range(n):
        loc += dl[i]
        src += ds[i]
        out.append((loc, src))
    return Mapping(tuple(out))


@given(mappings(), st.floats(0, 1))
def test_roundtrip(m, u):
    t = u * m.duration
    assert m.to_local(m.to_source(t)) == approx(t, abs=1e-7)


@given(mappings(), st.floats(0, 1), st.floats(0, 1), st.floats(0, 1))
def test_crop_agrees_with_parent(m, u, v, w):
    a, b = sorted((u * m.duration, v * m.duration))
    if b - a < 1e-3:
        return
    c = m.crop(a, b)
    t = w * (b - a)
    assert c.to_source(t) == approx(m.to_source(a + t), abs=1e-7)
    assert c.duration == approx(b - a)


@given(mappings(), mappings(), st.floats(0, 1))
def test_compose_agrees(parent, inner_raw, w):
    # 把 inner 的值域缩放到 parent 的局部范围内
    lo, hi = inner_raw.source_start, inner_raw.source_end
    scale = parent.duration / (hi - lo + 1)
    inner = Mapping(tuple((loc, (src - lo) * scale) for loc, src in inner_raw.points))
    out = parent.compose(inner)
    t = w * inner.duration
    assert out.to_source(t) == approx(parent.to_source(inner.to_source(t)), abs=1e-6)
    assert out.duration == inner.duration
