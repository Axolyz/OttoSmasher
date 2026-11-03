"""Core 与 Electron 主进程之间的帧协议（ARCHITECTURE §2）。

每帧 = 4 字节大端长度 + msgpack 负载。消息三种：

- 请求 ``{"t": "req", "id": int, "m": 方法名, "p": 参数}``
- 响应 ``{"t": "res", "id": int, "ok": True, "r": 结果}`` 或 ``{"t": "res", "id": int, "ok": False, "e": {"code", "args"}}``
- 事件 ``{"t": "evt", "e": 事件名, "d": 数据}``
"""

from __future__ import annotations

import os
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


def detach_stdio() -> tuple[BinaryIO, BinaryIO]:
    """把帧通道换到私有的描述符上，返回（读端, 写端）；标准输入改成空设备，标准输出改指 stderr。

    Windows：读线程阻塞在同步管道上时，别的进程查询同一个管道句柄会一直卡住。没指定标准句柄就启动的子进程（检索的
    spawn 进程池）启动时要查询继承来的 stdin，于是永远起不来，界面一直“正在检索”。os.dup 得到的描述符不被子进程继承。
    顺带：C 库意外写 stdout 也不会混进帧里。
    """
    in_fd, out_fd = os.dup(0), os.dup(1)
    nul = os.open(os.devnull, os.O_RDWR)
    os.dup2(nul, 0)
    try:
        os.dup2(2, 1)
    except OSError:  # 没有 stderr（GUI 启动）
        os.dup2(nul, 1)
    os.close(nul)
    # 读端无缓冲、不随对象关闭：读线程阻塞在 read 时退出解释器，不会因为缓冲区锁而中止
    return open(in_fd, "rb", buffering=0, closefd=False), open(out_fd, "wb")  # noqa: SIM115 — 进程结束才关


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

    def event(self, name: str, data: Any, req: Any = None) -> None:
        msg = {"t": "evt", "e": name, "d": data}
        if req is not None:
            msg["req"] = req  # 由哪个请求引起（界面据此区分“自己的操作”与别处 / 任务的改动，P8）
        self.send(msg)
