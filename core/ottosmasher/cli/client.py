"""连到正在运行的应用的 Core（阶段 A）：命令行与测试共用。

一个连接一个读端：``call`` 一直读到自己那条响应，途中收到的事件放进缓冲，``next_event`` 先从缓冲取。
"""

from __future__ import annotations

import collections
import time
from pathlib import Path
from typing import Any

from ..core import agent_link
from ..core.errors import CoreError
from ..store.workspace import Workspace


class LinkClient:
    def __init__(self, workspace: Path, *, kind: str = "agent", session: str | None = None) -> None:
        self.workspace = Path(workspace)
        info = agent_link.read_endpoint(Workspace(self.workspace).data)
        if info is None:
            raise CoreError("app-not-running", workspace=str(self.workspace))
        self.conn, self.hello = agent_link.connect(info, {"kind": kind, "session": session})
        self.events: collections.deque[dict[str, Any]] = collections.deque()
        self._next = 1

    def close(self) -> None:
        try:
            self.conn.close()
        except OSError:
            pass

    def __enter__(self) -> LinkClient:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    def _recv(self, timeout: float | None) -> dict[str, Any] | None:
        if timeout is not None and not self.conn.poll(timeout):
            return None
        try:
            return agent_link.unpack(self.conn.recv_bytes())
        except (EOFError, OSError) as exc:
            raise CoreError("agent-link-failed", reason=f"connection closed: {exc!r}") from None

    def send(self, method: str, params: dict[str, Any] | None = None) -> int:
        rid = self._next
        self._next += 1
        self.conn.send_bytes(agent_link.pack({"t": "req", "id": rid, "m": method, "p": params or {}}))
        return rid

    def request(self, method: str, params: dict[str, Any] | None = None, *, timeout: float | None = None) -> dict[str, Any]:
        """原始响应 ``{"ok", "r"|"e"}``。timeout 秒内没有响应 → agent-link-failed。"""
        rid = self.send(method, params)
        end = None if timeout is None else time.monotonic() + timeout
        while True:
            left = None if end is None else max(0.0, end - time.monotonic())
            msg = self._recv(left)
            if msg is None:
                raise CoreError("agent-link-failed", reason=f"no response to {method} within {timeout} s")
            if msg.get("t") == "res" and msg.get("id") == rid:
                return msg
            if msg.get("t") == "evt":
                self.events.append(msg)

    def call(self, method: str, params: dict[str, Any] | None = None, *, timeout: float | None = None) -> Any:
        """结果；业务错误抛 CoreError。"""
        res = self.request(method, params, timeout=timeout)
        if res.get("ok"):
            return res.get("r")
        e = res.get("e") or {}
        raise CoreError(e.get("code", "internal-error"), **(e.get("args") or {}))

    def next_event(self, timeout: float | None = None) -> dict[str, Any] | None:
        """下一个事件（``{"e": 名称, "d": 数据}``）；timeout 秒内没有 → None。"""
        if self.events:
            return self.events.popleft()
        end = None if timeout is None else time.monotonic() + timeout
        while True:
            left = None if end is None else max(0.0, end - time.monotonic())
            msg = self._recv(left)
            if msg is None:
                return None
            if msg.get("t") == "evt":
                return msg
