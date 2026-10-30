"""区间解码：规格 16 R20.2（只读需要的区间）、R21.1/R21.5（逐样本等于原信号、MP3 首样本不错位）。

信号：30 秒锯齿斜坡（相邻样本都不同，任何错位都会被发现）；立体声用 y 与 −y 检测声道交换（规格 16 第三部分）。
"""

import os
import shutil
import subprocess
from pathlib import Path

import numpy as np
import pytest

from ottosmasher.core.errors import CoreError
from ottosmasher.media import decode as dec
from ottosmasher.media.probe import probe

pytestmark = pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="ffmpeg not on PATH")
SR = 48000


@pytest.fixture(scope="module")
def ramp(tmp_path_factory) -> dict[str, Path]:
    d = tmp_path_factory.mktemp("ramp")
    n = SR * 30
    y = ((np.arange(n) % 40000) - 20000).astype(np.int16)
    stereo = np.stack([y, -y - 1], axis=1).astype(np.int16)  # 右声道 = −y（再错开 1，避免溢出）
    raw = d / "ramp.s16"
    stereo.tofile(raw)
    out = {}
    for ext, codec in [("wav", []), ("flac", []), ("mkv", ["-c:a", "flac"]), ("mp3", ["-c:a", "libmp3lame", "-q:a", "0"]),
                       ("m4a", ["-c:a", "aac", "-b:a", "256k"]),
                       ("opus.mkv", ["-c:a", "libopus"]),
                       ("opus10.mkv", ["-c:a", "libopus", "-frame_duration", "10"]),  # pre-skip（312）大于半帧
                       ("opus5.mkv", ["-c:a", "libopus", "-frame_duration", "5"])]:  # fmt: skip
        f = d / f"斜坡 [x] ♪.{ext}"
        subprocess.run(
            ["ffmpeg", "-v", "error", "-y", "-f", "s16le", "-ar", str(SR), "-ac", "2", "-i", str(raw), *codec, str(f)],
            check=True,
        )
        out[ext] = f
    return out


def ref_of(f: Path) -> dec.StreamRef:
    pr = probe(f)
    a = pr.audio[0]
    return dec.StreamRef(str(f), 0, a.sample_rate, a.channels, a.codec, pr.format_name)


@pytest.mark.parametrize(
    "ext,method", [("wav", "direct"), ("flac", "direct"), ("mkv", "indexed"), ("mp3", "preroll"), ("m4a", "indexed"), ("opus.mkv", "indexed"), ("opus10.mkv", "indexed"), ("opus5.mkv", "indexed")]
)
def test_range_equals_full_decode(ramp, tmp_path, ext, method):
    ref = ref_of(ramp[ext])
    assert ref.method == method
    full = dec.decode_all(ref)
    for start in [0.0, 0.123, 2.123, 7.77777, 13.0001, 21.5, 29.4]:
        end = min(start + 0.5, len(full) / SR)
        seg = dec.decode_range(ref, start, end, cache=tmp_path)
        a, b = round(start * SR), round(end * SR)
        assert seg.shape == (b - a, 2)
        assert np.array_equal(seg, full[a:b]), (ext, start)


def test_lossless_equals_original_signal(ramp, tmp_path):
    # R21.1：无损源上的区间 = 原信号对应样本（声道不交换）
    y = ((np.arange(SR * 30) % 40000) - 20000).astype(np.float32) / 32768
    for ext in ("wav", "flac", "mkv"):
        seg = dec.decode_range(ref_of(ramp[ext]), 0.123, 0.456, cache=tmp_path)
        a, b = round(0.123 * SR), round(0.456 * SR)
        assert np.array_equal(seg[:, 0], y[a:b])
        assert np.array_equal(seg[:, 1], (-(y[a:b] * 32768) - 1) / 32768)


def test_mp3_first_sample_not_shifted(ramp, tmp_path):
    # R21.5：起点 0.123 与 2.123 都对齐，首样本非零
    ref = ref_of(ramp["mp3"])
    full = dec.decode_all(ref)
    for start in (0.123, 2.123):
        seg = dec.decode_range(ref, start, start + 0.2, cache=tmp_path)
        assert seg[0, 0] != 0
        assert np.array_equal(seg, full[round(start * SR) : round((start + 0.2) * SR)])


@pytest.mark.parametrize("index_source", ["probe", "peaks"])
def test_opus_seek_through_exact_eof(ramp, tmp_path, index_source):
    """Opus seeks reapply pre-skip: the first decoded frame is shorter than its indexed frame.

    Reproduce the F0 last-chunk failure without models; exercise both index producers.
    """
    from ottosmasher.media import peaks

    ref = ref_of(ramp["opus.mkv"])
    full = dec.decode_all(ref)
    if index_source == "peaks":
        peaks.build(ref, tmp_path)
    else:
        dec.frame_index(ref, tmp_path)
    a = 25 * SR
    seg = dec.decode_frames(ref, a, len(full), cache=tmp_path)
    assert np.array_equal(seg, full[a:])
    with pytest.raises(CoreError) as ei:
        dec.decode_frames(ref, a, len(full) + 1, cache=tmp_path)
    assert ei.value.code == "range-invalid"


def test_index_is_cached_and_invalidated(ramp, tmp_path):
    f = tmp_path / "copy.mkv"
    shutil.copy(ramp["mkv"], f)
    ref = ref_of(f)
    dec.decode_range(ref, 1.0, 1.5, cache=tmp_path / "c")
    files = list((tmp_path / "c" / "FrameIndex").glob("*.npz"))
    assert len(files) == 1
    idx = dec.frame_index(ref, tmp_path / "c")
    assert idx.total == SR * 30
    os.utime(f, ns=(f.stat().st_atime_ns, f.stat().st_mtime_ns + 10**9))  # 修改时间变了 → 新键
    dec.decode_range(ref, 1.0, 1.5, cache=tmp_path / "c")
    assert len(list((tmp_path / "c" / "FrameIndex").glob("*.npz"))) == 2
    assert not list((tmp_path / "c" / "FrameIndex").glob("*.tmp*"))  # 不留临时文件


def test_out_of_range_is_an_error(ramp, tmp_path):
    for ext in ("wav", "mkv"):
        ref = ref_of(ramp[ext])
        with pytest.raises(CoreError) as ei:
            dec.decode_range(ref, 29.8, 30.5, cache=tmp_path)
        assert ei.value.code == "range-invalid"
    with pytest.raises(CoreError):
        dec.decode_frames(ref_of(ramp["wav"]), 10, 10, cache=tmp_path)
