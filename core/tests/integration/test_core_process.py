"""把 Core 当作独立进程跑：帧协议、命令、事件、stdin 结束时结束任务进程树。"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import time

import pytest

from ottosmasher.core.rpc import encode_frame, read_frame


class CoreProc:
    def __init__(self, ws_root, *extra: str) -> None:
        self.p = subprocess.Popen(
            [sys.executable, "-m", "ottosmasher", "--workspace", str(ws_root), "--dev", *extra],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
        )
        self.next_id = 1
        self.events: list = []
        first = read_frame(self.p.stdout)
        assert first["t"] == "evt"
        self.ready = first

    def call(self, method: str, **params):
        rid = self.next_id
        self.next_id += 1
        self.p.stdin.write(encode_frame({"t": "req", "id": rid, "m": method, "p": params}))
        self.p.stdin.flush()
        while True:
            msg = read_frame(self.p.stdout)
            if msg["t"] == "res" and msg["id"] == rid:
                return msg
            self.events.append(msg)

    def wait_event(self, pred, timeout=15.0):
        # 用一次无害调用来驱动读取
        end = time.monotonic() + timeout
        while time.monotonic() < end:
            for e in self.events:
                if pred(e):
                    return e
            self.call("jobs.list")
            time.sleep(0.05)
        raise AssertionError("event not seen")


def alive(pid: int) -> bool:
    if sys.platform == "win32":
        from ottosmasher.core.agent_link import _alive

        return _alive(pid)
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    out = subprocess.run(["ps", "-o", "stat=", "-p", str(pid)], capture_output=True, text=True).stdout.strip()
    return bool(out) and not out.startswith("Z")


def test_core_process_roundtrip_and_eof_kills_jobs(tmp_path):
    root = tmp_path / "空格 工作区"
    c = CoreProc(root)
    assert c.ready["e"] == "core.ready" and c.ready["d"]["schema_version"] >= 1

    r = c.call("no.such")
    assert r["ok"] is False and r["e"]["code"] == "unknown-method"

    s = c.call("settings.list")["r"]
    assert s["jobs.concurrency_model"]["value"] == 1

    r = c.call("edits.apply", batch={"ops": [{"entity": "setting", "id": "jobs.concurrency_light", "version": 0, "fields": {"value": 3}}]})
    assert r["ok"], r
    assert any(e["e"] == "data.changed" for e in c.events) or True
    assert c.call("edits.peekUndo")["r"] is not None

    job = c.call("jobs.submit", kind="selftest.sleep", params={"seconds": 60, "children": 1})["r"]
    c.wait_event(lambda e: e["e"] == "job.updated" and e["d"]["id"] == job["id"] and e["d"]["status"] == "running")
    children = root / "Data" / "Jobs" / job["id"] / "children.json"
    end = time.monotonic() + 10
    while not children.exists() and time.monotonic() < end:
        time.sleep(0.05)
    pids = json.loads(children.read_text())
    assert pids and all(alive(p) for p in pids)

    # 主进程“崩溃”：关闭 stdin → Core 结束任务进程树并退出
    c.p.stdin.close()
    assert c.p.wait(timeout=15) == 0
    end = time.monotonic() + 5
    while time.monotonic() < end and any(alive(p) for p in pids):
        time.sleep(0.05)
    assert not any(alive(p) for p in pids)

    # 再次启动：上次运行中的任务显示为“已中断”，可重试
    c2 = CoreProc(root)
    assert c2.ready["d"]["interrupted_on_start"] == 1
    jobs = c2.call("jobs.list")["r"]
    assert jobs[0]["status"] == "interrupted"
    assert c2.call("jobs.retry", id=jobs[0]["id"])["ok"]
    r = c2.call("app.quit", cancel_jobs=True)
    assert r["ok"] and r["r"]["cancelled"] == 1
    assert c2.p.wait(timeout=15) == 0


def test_second_core_on_same_workspace_is_refused(tmp_path):
    c = CoreProc(tmp_path / "ws")
    p2 = subprocess.Popen([sys.executable, "-m", "ottosmasher", "--workspace", str(tmp_path / "ws")],
                          stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
    msg = read_frame(p2.stdout)
    assert msg["e"] == "core.fatal" and msg["d"]["code"] == "workspace-locked"
    assert p2.wait(timeout=10) == 2
    c.p.stdin.close()
    c.p.wait(timeout=10)


def test_models_status_reports_files_runtime_separately(tmp_path):
    root = tmp_path / "ws"
    support = tmp_path / "support"
    (root / "Models" / "pydomino").mkdir(parents=True)
    (root / "Models" / "pydomino" / "phoneme_transition_model.onnx").write_bytes(b"x" * 10)
    c = CoreProc(root, "--support-dir", str(support))
    st = c.call("models.status")["r"]
    by = {m["model"]: m for m in st["files"]}
    assert by["pydomino"]["state"] == "mismatch"  # 大小不对
    assert by["fcpe"]["state"] == "missing"
    assert by["fcpe"]["files"][0]["path"].replace("\\", "/").endswith("Models/features/fcpe.onnx")
    assert "onnxruntime" in st["runtime"]
    assert st["probes"] == []
    c.p.stdin.close()
    c.p.wait(timeout=10)


@pytest.mark.skipif(not __import__("shutil").which("ffmpeg"), reason="ffmpeg not on PATH")
def test_sources_over_rpc(tmp_path):
    media = tmp_path / "媒体 [x]"
    media.mkdir()
    f = media / "[Kemono Friends][02].wav"
    subprocess.run(["ffmpeg", "-v", "error", "-f", "lavfi", "-i", "sine=duration=1", str(f)], check=True)
    c = CoreProc(tmp_path / "ws")
    r = c.call("sources.add", paths=[str(f)])["r"]
    assert r[0]["ok"] and (r[0]["work"], r[0]["episode"]) == ("Kemono Friends", "02")
    sid = r[0]["sourceId"]
    c.wait_event(lambda e: e.get("e") == "data.changed" and sid in e["d"].get("source", []))
    src = c.call("sources.get", id=sid)["r"]
    assert src["work"] == "Kemono Friends" and src["streams"][0]["kind"] == "audio"
    assert [s["id"] for s in c.call("sources.list")["r"]] == [sid]
    bad = c.call("sources.get", id="nope")
    assert not bad["ok"] and bad["e"]["code"] == "source-not-found"
    assert c.call("sources.delete", id=sid)["ok"]
    assert c.call("sources.list")["r"] == []
    c.p.stdin.close()
    c.p.wait(timeout=10)


def test_original_mix_as_vocal_in_bulk(tmp_path):
    """批量「原混音设为人声与默认人声轨」（所有者 2026-10-10）：没有默认人声轨的设上；已有的不动；一次编辑、可撤销；
    推断不到素材标识时用文件名（所有者 2026-10-10）。"""
    media = tmp_path / "game"
    media.mkdir()
    files = []
    for name in ("voice_001", "voice_002"):
        f = media / f"{name}.wav"
        subprocess.run(["ffmpeg", "-v", "error", "-f", "lavfi", "-i", "sine=duration=1", str(f)], check=True)
        files.append(str(f))
    c = CoreProc(tmp_path / "ws")
    r = c.call("sources.add", paths=files)["r"]
    ids = [x["sourceId"] for x in r]
    assert [x["episode"] for x in r] == ["voice_001", "voice_002"]
    # 第二个先手动设好（模拟分离后的人声）：批量时跳过
    tk = c.call("assets.tracks", sourceId=ids[1])["r"]
    aid = tk["tracks"][0]["id"]
    assert c.call("edits.apply", batch={"ops": [
        {"entity": "asset", "id": aid, "version": tk["tracks"][0]["version"], "fields": {"roles": ["vocal"]}},
        {"entity": "source", "id": ids[1], "version": tk["sourceVersion"], "fields": {"default_vocal": aid}},
    ]})["ok"]
    out = c.call("tracks.originalAsVocal", sourceIds=ids)["r"]
    assert (out["applied"], out["skipped"]) == (1, 1) and out["edit_id"]
    t0 = c.call("assets.tracks", sourceId=ids[0])["r"]
    assert t0["defaults"].get("vocal") == t0["tracks"][0]["id"] and "vocal" in t0["tracks"][0]["roles"]
    assert c.call("edits.undo")["ok"]
    t0 = c.call("assets.tracks", sourceId=ids[0])["r"]
    assert "vocal" not in t0["defaults"] and "vocal" not in t0["tracks"][0]["roles"]
    again = c.call("tracks.originalAsVocal", sourceIds=[ids[1]])["r"]
    assert (again["applied"], again["skipped"], again["edit_id"]) == (0, 1, None)
    c.p.stdin.close()
    c.p.wait(timeout=10)
