"""Core 与 Electron 主进程之间的帧协议（ARCHITECTURE §2）。

每帧 = 4 字节大端长度 + msgpack 负载。消息三种：

- 请求 ``{"t": "req", "id": int, "m": 方法名, "p": 参数}``
- 响应 ``{"t": "res", "id": int, "ok": True, "r": 结果}`` 或 ``{"t": "res", "id": int, "ok": False, "e": {"code", "args"}}``
- 事件 ``{"t": "evt", "e": 事件名, "d": 数据}``
"""

from __future__ import annotations

import struct
import threading
from typing import Any, BinaryIO

import msgspec

MAX_FRAME = 64 * 1024 * 1024
_HEADER = struct.Struct(">I")

_encoder = msgspec.msgpack.Encoder()
_decoder = msgspec.msgpack.Decoder()


class FrameError(Exception):
    pass


def encode_frame(msg: Any) -> bytes:
    body = _encoder.encode(msg)
    if len(body) > MAX_FRAME:
        raise FrameError(f"frame too large: {len(body)}")
    return _HEADER.pack(len(body)) + body


def _read_exact(stream: BinaryIO, n: int) -> bytes | None:
    buf = bytearray()
    while len(buf) < n:
        chunk = stream.read(n - len(buf))
        if not chunk:
            if buf:
                raise FrameError("truncated frame")
            return None
        buf += chunk
    return bytes(buf)


def read_frame(stream: BinaryIO) -> Any | None:
    """读一帧；流结束返回 None。"""
    head = _read_exact(stream, _HEADER.size)
    if head is None:
        return None
    (length,) = _HEADER.unpack(head)
    if length > MAX_FRAME:
        raise FrameError(f"frame too large: {length}")
    body = _read_exact(stream, length)
    if body is None:
        raise FrameError("truncated frame")
    return _decoder.decode(body)


class FrameWriter:
    """线程安全的写端（任务监视线程也会发事件）。"""

    def __init__(self, stream: BinaryIO) -> None:
        self._stream = stream
        self._lock = threading.Lock()

    def send(self, msg: Any) -> None:
        data = encode_frame(msg)
        with self._lock:
            self._stream.write(data)
            self._stream.flush()

    def event(self, name: str, data: Any) -> None:
        self.send({"t": "evt", "e": name, "d": data})
