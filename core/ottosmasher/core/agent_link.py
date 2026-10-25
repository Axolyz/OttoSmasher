"""本机 agent 端点（阶段 A，ARCHITECTURE §15）：应用开着时，命令行 ``otto`` 经这里调用与界面同一组命令。

- 标准库 ``multiprocessing.connection``：macOS / Linux 用 AF_UNIX（套接字放系统临时目录，避开 104 字节路径上限），
  Windows 用命名管道（AF_PIPE，未实测，ROADMAP L47）；``authkey`` 每次启动随机生成，连同地址写进 ``Data/agent-endpoint.json``（0600），
  只有能读这个文件的本机用户连得上。只用 ``send_bytes`` / ``recv_bytes`` 传 msgpack（与 stdio 同样的消息），不用 pickle。
- 握手：客户端第一条消息 ``{"t": "hello", "actor": {"kind": "agent"|"script", "session": …}}``；这个连接上的所有请求都按它记来源，
  消息里再带 ``actor`` 也不理（不能冒充用户）。
- 请求放进 Core 主线程的同一个队列串行处理；响应写回这个连接；事件广播给所有连接（``Core.emit``）。
- 作用类别 ui / app / dev 的命令不对外；危险命令（登记时 ``danger``）先发 ``agent.confirm`` 等所有者在应用里确认（``agent.confirmReply``）。
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import secrets
import sys
import tempfile
import threading
import time
from collections.abc import Callable
from multiprocessing.connection import Client, Connection, Listener
from pathlib import Path
from typing import Any

import msgspec

from .clock import new_id, now_iso
from .errors import CoreError
from . import actor as actor_mod

log = logging.getLogger(__name__)

ENDPOINT_FILE = "agent-endpoint.json"
CONFIRM_SECONDS = 120.0  # 0 = 不限时。所有者 2026-10-24 先改不限时、后定回限时 + 错过的请求留在操作历史里 + 放行时核对
MISSED_MAX = 50
EXTERNAL_KINDS = ("agent", "script")

_enc = msgspec.msgpack.Encoder()
_dec = msgspec.msgpack.Decoder()


def address_for(workspace: Path) -> tuple[str, str]:
    """(family, address)：同一工作区每次相同，不同工作区不同。"""
    tag = hashlib.sha256(str(workspace.resolve()).encode("utf-8")).hexdigest()[:10]
    if sys.platform == "win32":
        return "AF_PIPE", rf"\\.\pipe\ottosmasher-{tag}"
    return "AF_UNIX", str(Path(tempfile.gettempdir()) / f"otto-{tag}.sock")


def endpoint_path(data_dir: Path) -> Path:
    return data_dir / ENDPOINT_FILE


def read_endpoint(data_dir: Path) -> dict[str, Any] | None:
    """读端点文件；不在或写端进程已不在 → None。"""
    try:
        info = json.loads(endpoint_path(data_dir).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    pid = info.get("pid")
    if not isinstance(pid, int) or not _alive(pid):
        return None
    return info


def _alive(pid: int) -> bool:
    if sys.platform == "win32":
        import ctypes

        h = ctypes.windll.kernel32.OpenProcess(0x1000, False, pid)  # PROCESS_QUERY_LIMITED_INFORMATION
        if not h:
            return False
        ctypes.windll.kernel32.CloseHandle(h)
        return True
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def connect(info: dict[str, Any], actor: dict[str, Any]) -> tuple[Connection, dict[str, Any]]:
    """客户端：连上并握手，返回 (连接, Core 的 hello)。失败抛 CoreError(agent-link-failed)。"""
    try:
        conn = Client(info["address"], family=info["family"], authkey=bytes.fromhex(info["key"]))
    except Exception as exc:  # noqa: BLE001 — 连接、认证失败都归到一个码
        raise CoreError("agent-link-failed", reason=repr(exc)) from None
    conn.send_bytes(_enc.encode({"t": "hello", "actor": actor}))
    reply = _dec.decode(conn.recv_bytes())
    if not reply.get("ok"):
        conn.close()
        err = reply.get("e") or {}
        raise CoreError(err.get("code", "agent-link-failed"), **(err.get("args") or {}))
    return conn, reply["r"]


def pack(msg: Any) -> bytes:
    return _enc.encode(msg)


def unpack(data: bytes) -> Any:
    return _dec.decode(data)


class Peer:
    """一条外部连接。写端加锁（主线程回响应，任务线程发事件）。"""

    def __init__(self, conn: Connection, pid: str, kind: str, session: str | None) -> None:
        self.conn = conn
        self.id = pid
        self.kind = kind
        self.session = session
        self.connected_at = now_iso()
        self.open = True
        self._lock = threading.Lock()

    def send(self, msg: Any) -> None:
        if not self.open:
            return
        data = _enc.encode(msg)
        with self._lock:
            try:
                self.conn.send_bytes(data)
            except (OSError, EOFError, ValueError):
                self.open = False

    def info(self) -> dict[str, Any]:
        return {"id": self.id, "kind": self.kind, "session": self.session, "connectedAt": self.connected_at}


class AgentLink:
    """监听线程 + 每个连接一个读线程。请求经 ``submit(peer, msg)`` 交给 Core 主线程。"""

    def __init__(self, workspace: Path, data_dir: Path, *, hello: Callable[[], dict[str, Any]],
                 submit: Callable[[Peer, dict[str, Any]], None], on_peers: Callable[[], None]) -> None:
        self.workspace = workspace
        self.data_dir = data_dir
        self._hello = hello
        self._submit = submit
        self._on_peers = on_peers
        self.peers: dict[str, Peer] = {}
        self._peers_lock = threading.Lock()
        self._listener: Listener | None = None
        self._closing = False

    # ---------- 生命周期

    def start(self) -> None:
        family, address = address_for(self.workspace)
        if family == "AF_UNIX":
            try:
                os.unlink(address)  # 上次崩溃留下的套接字文件（工作区锁保证不会是别的活着的 Core）
            except FileNotFoundError:
                pass
        key = secrets.token_bytes(32)
        self._listener = Listener(address, family=family, authkey=key)
        if family == "AF_UNIX":
            os.chmod(address, 0o600)
        info = {"family": family, "address": address, "key": key.hex(), "pid": os.getpid(), "workspace": str(self.workspace)}
        path = endpoint_path(self.data_dir)
        tmp = path.with_suffix(".tmp")
        fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(info, fh)
        os.replace(tmp, path)
        threading.Thread(target=self._accept_loop, name="agent-accept", daemon=True).start()

    def close(self) -> None:
        self._closing = True
        try:
            endpoint_path(self.data_dir).unlink()
        except FileNotFoundError:
            pass
        if self._listener is not None:
            try:
                self._listener.close()  # AF_UNIX 时顺带删掉套接字文件
            except OSError:
                pass
        with self._peers_lock:
            peers = list(self.peers.values())
        for p in peers:
            p.open = False
            try:
                p.conn.close()
            except OSError:
                pass

    # ---------- 连接

    def _accept_loop(self) -> None:
        assert self._listener is not None
        while not self._closing:
            try:
                conn = self._listener.accept()
            except Exception:  # noqa: BLE001 — 认证失败或关闭；关闭时退出，否则接着等
                if self._closing:
                    return
                log.info("agent link: a connection failed authentication", exc_info=True)
                continue
            threading.Thread(target=self._serve_peer, args=(conn,), name="agent-peer", daemon=True).start()

    def _serve_peer(self, conn: Connection) -> None:
        peer: Peer | None = None
        try:
            first = _dec.decode(conn.recv_bytes())
            actor = first.get("actor") if isinstance(first, dict) and first.get("t") == "hello" else None
            try:
                kind, session = actor_mod.parse(actor or {"kind": "agent"})
                if kind not in EXTERNAL_KINDS:
                    raise ValueError(f"actor.kind must be one of {EXTERNAL_KINDS}")
            except ValueError as exc:
                conn.send_bytes(_enc.encode({"t": "hello", "ok": False, "e": {"code": "agent-link-failed", "args": {"reason": str(exc)}}}))
                conn.close()
                return
            peer = Peer(conn, new_id(), kind, session)
            # Do not expose this connection to broadcasts until hello is written:
            # the client must receive its handshake before any event.
            peer.send({"t": "hello", "ok": True, "r": {**self._hello(), "peer": peer.id}})
            with self._peers_lock:
                self.peers[peer.id] = peer
            self._on_peers()
            while True:
                msg = _dec.decode(conn.recv_bytes())
                if isinstance(msg, dict) and msg.get("t") == "req":
                    self._submit(peer, msg)
        except (EOFError, OSError):
            pass
        except Exception:  # noqa: BLE001
            log.exception("agent link: peer failed")
        finally:
            if peer is not None:
                peer.open = False
                with self._peers_lock:
                    self.peers.pop(peer.id, None)
                self._on_peers()
            try:
                conn.close()
            except OSError:
                pass

    def broadcast(self, msg: dict[str, Any]) -> None:
        with self._peers_lock:
            peers = list(self.peers.values())
        for p in peers:
            p.send(msg)

    def sessions(self) -> list[dict[str, Any]]:
        with self._peers_lock:
            return [p.info() for p in self.peers.values()]


class Confirmations:
    """危险命令的确认：主线程登记、发 ``agent.confirm``；所有者回答或超时后在主线程执行 / 回错误。

    超时或提问的连接断了 → 记进“错过的请求”（本次运行内，事件 ``agent.missed``），所有者回来能看到 agent 想做什么。
    ``state`` 是提问时的资料指纹（影响预览 + 对象版本）：放行时重算，不一样就不执行、带新预览重新问。
    """

    def __init__(self, *, emit: Callable[[str, Any], None], post: Callable[[Callable[[], None]], None],
                 seconds: float = CONFIRM_SECONDS) -> None:
        self._emit = emit
        self._post = post
        self.seconds = seconds
        self.pending: dict[str, dict[str, Any]] = {}
        self.missed: list[dict[str, Any]] = []

    def ask(self, peer: Peer, msg: dict[str, Any], *, preview: Any = None, state: Any = None) -> str:
        cid = new_id()
        self.pending[cid] = {"peer": peer, "msg": msg, "at": time.monotonic(), "preview": preview, "state": state}
        if self.seconds > 0:
            t = threading.Timer(self.seconds, lambda: self._post(lambda: self.expire(cid)))
            t.daemon = True
            t.start()
        self._emit("agent.confirm", {
            "id": cid, "method": msg.get("m"), "params": msg.get("p") or {}, "preview": preview,
            "actor": {"kind": peer.kind, "session": peer.session}, "seconds": int(self.seconds),
        })
        return cid

    def take(self, cid: str) -> dict[str, Any]:
        item = self.pending.pop(cid, None)
        if item is None:
            raise CoreError("agent-confirm-unknown", id=cid)
        self._emit("agent.confirmClosed", {"id": cid})
        return item

    def _miss(self, cid: str, item: dict[str, Any], reason: str) -> None:
        msg, peer = item["msg"], item["peer"]
        self.missed.insert(0, {"id": cid, "method": msg.get("m"), "params": msg.get("p") or {}, "preview": item.get("preview"),
                               "actor": {"kind": peer.kind, "session": peer.session}, "at": now_iso(), "reason": reason})
        del self.missed[MISSED_MAX:]
        self._emit("agent.missed", self.missed)

    def dismiss(self, ids: list[str] | None) -> None:
        self.missed = [] if ids is None else [m for m in self.missed if m["id"] not in set(ids)]
        self._emit("agent.missed", self.missed)

    def expire(self, cid: str) -> None:
        item = self.pending.pop(cid, None)
        if item is None:
            return
        self._emit("agent.confirmClosed", {"id": cid})
        self._miss(cid, item, "timeout")
        msg = item["msg"]
        item["peer"].send({"t": "res", "id": msg.get("id"), "ok": False,
                           "e": CoreError("agent-confirm-timeout", method=msg.get("m"), seconds=int(self.seconds)).to_wire()})

    def drop_peer(self, peer_id: str) -> None:
        """连接断了：它等着的确认作废（不在提问的人走了之后再执行危险操作），记进错过的请求。"""
        for cid in [c for c, v in self.pending.items() if v["peer"].id == peer_id]:
            item = self.pending.pop(cid)
            self._emit("agent.confirmClosed", {"id": cid})
            self._miss(cid, item, "closed")
