"""Events emitted during connection setup must follow the handshake."""

from ottosmasher.core import agent_link


def test_broadcast_during_hello_cannot_overtake_handshake(tmp_path):
    class Connection:
        def __init__(self):
            self.incoming = [agent_link.pack({"t": "hello", "actor": {"kind": "agent", "session": "test"}})]
            self.sent = []
            self.closed = False

        def recv_bytes(self):
            if self.incoming:
                return self.incoming.pop(0)
            raise EOFError

        def send_bytes(self, data):
            self.sent.append(agent_link.unpack(data))

        def close(self):
            self.closed = True

    conn = Connection()
    event = {"t": "evt", "e": "job.updated", "d": {"status": "running"}}
    link = agent_link.AgentLink(tmp_path, tmp_path, hello=lambda: {}, submit=lambda *_: None, on_peers=lambda: None)

    def hello():
        # Deterministically interleave a broadcast before the hello write.
        link.broadcast(event)
        return {"version": "test"}

    link._hello = hello
    link._on_peers = lambda: link.broadcast(event)
    link._serve_peer(conn)
    assert [m["t"] for m in conn.sent] == ["hello", "evt"]
    assert conn.sent[0]["ok"] and conn.sent[0]["r"]["version"] == "test"
    assert conn.closed and not link.sessions()


def test_permission_denial_explains_local_ipc_without_claiming_app_is_stopped(monkeypatch):
    from ottosmasher.core import agent_link
    from ottosmasher.core.errors import CoreError
    import pytest

    def denied(*args, **kwargs):
        raise PermissionError("access denied")

    monkeypatch.setattr(agent_link, "Client", denied)
    with pytest.raises(CoreError) as caught:
        agent_link.connect({"address": "local-endpoint", "family": "AF_PIPE", "key": "00"}, {"kind": "agent", "session": "test"})
    assert caught.value.code == "agent-link-failed"
    assert "sandbox/ACL" in caught.value.args_["reason"]
    assert "PermissionError" in caught.value.args_["reason"]
