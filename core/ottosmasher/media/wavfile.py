"""24-bit PCM WAV 写入（规格 12 §12.1：PCM 24-bit，采样率与声道跟随源）。

float32 → 24 位整数：先夹到 [-1, 1 − 2⁻²³]，再乘 2²³ 四舍五入；16/24 位来源的样本都能原样还原（误差 0；一般误差 ≤ 2⁻²⁴）。
1–2 声道写普通 PCM 头，更多声道写 WAVE_FORMAT_EXTENSIBLE（不指定扬声器位置）。
"""

from __future__ import annotations

import struct
from pathlib import Path
from typing import BinaryIO

import numpy as np

_PCM = 1
_EXTENSIBLE = 0xFFFE
_KSDATAFORMAT_SUBTYPE_PCM = bytes.fromhex("0100000000001000800000aa00389b71")


def to_int24_bytes(pcm: np.ndarray) -> bytes:
    """(帧, 声道) float32 → 交错的小端 24 位字节。"""
    x = np.clip(pcm.astype(np.float64), -1.0, 1.0 - 2.0**-23)
    i = np.rint(x * (1 << 23)).astype("<i4")
    b = i.reshape(-1).view(np.uint8).reshape(-1, 4)[:, :3]
    return b.tobytes()


def _header(frames: int, channels: int, rate: int) -> bytes:
    block = channels * 3
    data_len = frames * block
    if channels <= 2:
        fmt = struct.pack("<HHIIHH", _PCM, channels, rate, rate * block, block, 24)
    else:
        fmt = struct.pack("<HHIIHHHHI", _EXTENSIBLE, channels, rate, rate * block, block, 24, 22, 24, 0)
        fmt += _KSDATAFORMAT_SUBTYPE_PCM
    if 4 + (8 + len(fmt)) + (8 + data_len) > 0xFFFFFFFF:
        raise ValueError("wav too large")
    riff_len = 4 + (8 + len(fmt)) + (8 + data_len) + (data_len & 1)
    return b"RIFF" + struct.pack("<I", riff_len) + b"WAVE" + b"fmt " + struct.pack("<I", len(fmt)) + fmt + b"data" + struct.pack("<I", data_len)


def write_wav24(fh: BinaryIO, pcm: np.ndarray, rate: int) -> None:
    if pcm.ndim != 2:
        raise ValueError("pcm must be (frames, channels)")
    frames, channels = pcm.shape
    fh.write(_header(frames, channels, rate))
    body = to_int24_bytes(pcm)
    fh.write(body)
    if len(body) & 1:
        fh.write(b"\x00")


def save_wav24(path: Path, pcm: np.ndarray, rate: int) -> None:
    with open(path, "wb") as fh:
        write_wav24(fh, pcm, rate)


def save_wav_f32(path: Path, pcm: np.ndarray, rate: int) -> None:
    """32 位浮点 WAV（加工的中间结果，例如拉平成品编码 MP3 之前：重合成的声音可能略超过 ±1，不在这里削波）。只写 1–2 声道。"""
    if pcm.ndim != 2 or pcm.shape[1] > 2:
        raise ValueError("pcm must be (frames, 1|2)")
    frames, channels = pcm.shape
    block = channels * 4
    data_len = frames * block
    fmt = struct.pack("<HHIIHH", 3, channels, rate, rate * block, block, 32)
    with open(path, "wb") as fh:
        fh.write(b"RIFF" + struct.pack("<I", 4 + 8 + len(fmt) + 8 + data_len) + b"WAVE" + b"fmt " + struct.pack("<I", len(fmt)) + fmt)
        fh.write(b"data" + struct.pack("<I", data_len))
        fh.write(np.ascontiguousarray(pcm, dtype="<f4").tobytes())


def load_wav_f32(path: Path) -> tuple[np.ndarray, int]:
    """读 32 位浮点 WAV（Rubber Band 等外部工具按输入格式写回的中间结果）：返回 ([帧, 声道] float32, 采样率)。
    只认 IEEE float 32 位（普通头或 EXTENSIBLE）；其他格式报错，不猜。"""
    data = Path(path).read_bytes()
    if data[:4] != b"RIFF" or data[8:12] != b"WAVE":
        raise ValueError("not a wav file")
    pos, fmt, body = 12, None, None
    while pos + 8 <= len(data):
        cid, size = data[pos : pos + 4], struct.unpack("<I", data[pos + 4 : pos + 8])[0]
        chunk = data[pos + 8 : pos + 8 + size]
        if cid == b"fmt ":
            fmt = chunk
        elif cid == b"data":
            body = chunk
        pos += 8 + size + (size & 1)
    if fmt is None or body is None:
        raise ValueError("wav without fmt/data")
    tag, channels, rate = struct.unpack("<HHI", fmt[:8])
    bits = struct.unpack("<H", fmt[14:16])[0]
    if tag == _EXTENSIBLE and len(fmt) >= 26:
        tag = struct.unpack("<H", fmt[24:26])[0]
    if tag != 3 or bits != 32:
        raise ValueError(f"unsupported wav format {tag}/{bits}")
    n = len(body) // (4 * channels)
    return np.frombuffer(body[: n * 4 * channels], dtype="<f4").reshape(n, channels).astype(np.float32), int(rate)
