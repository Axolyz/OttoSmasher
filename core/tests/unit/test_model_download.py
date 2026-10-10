"""模型权重的显式下载与从文件导入（所有者 2026-10-10；规格 14 §14.1、15 §15.8）：
边下边算 SHA-256，一致才原子放到位置；不一致 / HTTP 错误 → 报下载失败（带网址与放置路径），不留半成品；
从文件导入按 SHA-256 认文件（文件名不对也认），别的文件不复制；“未校验”的已有文件不被下载替换。"""

from __future__ import annotations

import hashlib
import http.server
import threading
from pathlib import Path

import pytest

from ottosmasher.core.errors import CoreError
from ottosmasher.models import download, registry

GOOD = b"onnx-weights-" * 50_000  # 约 650 KB
SHA = hashlib.sha256(GOOD).hexdigest()


class Ctx:
    def __init__(self) -> None:
        self.events: list = []

    def progress(self, *a, **k):
        self.events.append(a)

    def log(self, text):
        pass


@pytest.fixture()
def server():
    files = {"/good.onnx": GOOD, "/bad.onnx": b"x" * len(GOOD)}

    class H(http.server.BaseHTTPRequestHandler):
        def do_GET(self):  # noqa: N802
            body = files.get(self.path)
            if body is None:
                self.send_error(404)
                return
            self.send_response(200)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *a):
            pass

    srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), H)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{srv.server_address[1]}"
    srv.shutdown()


@pytest.fixture()
def fake(monkeypatch, server):
    spec = registry.ModelSpec("demo", (registry.ModelFile("demo/w.onnx", "weight", SHA, len(GOOD)),), f"{server}/good.onnx", "MIT")
    monkeypatch.setattr(registry, "MODELS", (spec,))
    return spec


def test_plan_download_and_place(fake, tmp_path):
    models, support = tmp_path / "Models", tmp_path / "support"
    items = download.plan(models, support, {})
    assert [(i["model"], i["replace"], i["license"]) for i in items] == [("demo", False, "MIT")]
    ctx = Ctx()
    res = download.run_download({"item": items[0], "tag": "t1"}, ctx)
    dest = models / "demo" / "w.onnx"
    assert dest.read_bytes() == GOOD and res["hashes"][str(dest)]["sha256"] == SHA
    assert not list(dest.parent.glob("*.part-*")) and ctx.events
    # 写进 SHA 缓存之后就是“就绪”，不再列入下载
    h = res["hashes"][str(dest)]
    cache = {str(dest): (h["size"], h["mtime_ns"], h["sha256"])}
    assert registry.file_status(models, support, cache)[0]["state"] == "ready"
    assert download.plan(models, support, cache) == []


def test_unverified_file_is_not_replaced(fake, tmp_path):
    models = tmp_path / "Models"
    (models / "demo").mkdir(parents=True)
    (models / "demo" / "w.onnx").write_bytes(GOOD)  # 用户放好了、还没检测
    assert download.plan(models, tmp_path, {}) == []


def test_sha_mismatch_and_http_error_leave_nothing(fake, server, tmp_path):
    models = tmp_path / "Models"
    item = download.plan(models, tmp_path, {})[0]
    for url, reason in [(f"{server}/bad.onnx", "sha-mismatch"), (f"{server}/missing.onnx", "http")]:
        with pytest.raises(CoreError) as e:
            download.run_download({"item": {**item, "url": url}, "tag": "t"}, Ctx())
        assert e.value.code == "model-download-failed" and e.value.args_["reason"] == reason
        assert e.value.args_["url"] == url and e.value.args_["path"] == item["path"]  # 失败时给出网址与放置路径
        assert not Path(item["path"]).exists() and not list(Path(item["path"]).parent.glob("*.part-*"))
    # 大小不符的旧文件 → 列入下载并标明会替换
    Path(item["path"]).write_bytes(b"short")
    again = download.plan(models, tmp_path, {})
    assert again[0]["replace"]


def test_import_recognises_by_sha(fake, tmp_path):
    src = tmp_path / "下载 的文件"
    (src / "sub").mkdir(parents=True)
    (src / "sub" / "renamed.bin").write_bytes(GOOD)  # 文件名不对、大小对 → 认得出
    (src / "w.onnx").write_bytes(b"not the model")  # 名字对、内容不对 → 不复制
    (src / "other.txt").write_text("x")  # 既不同名也不同大小 → 不看
    models = tmp_path / "Models"
    res = download.run_import({"paths": [str(src)], "models_dir": str(models), "support_dir": str(tmp_path)}, Ctx())
    dest = models / "demo" / "w.onnx"
    assert dest.read_bytes() == GOOD and [x["model"] for x in res["imported"]] == ["demo"]
    assert [Path(x["file"]).name for x in res["skipped"]] == ["w.onnx"] and res["skipped"][0]["reason"] == "not-a-model"
    assert str(dest) in res["hashes"]
    assert (src / "sub" / "renamed.bin").exists()  # 原文件不动


def test_real_registry_lists_all_four_weights(tmp_path):
    """真实清单：四个权重都有大小、许可、固定修订的直链；空工作区要下载约 196 MB。"""
    items = download.plan(tmp_path / "Models", tmp_path / "support", {})
    assert sorted(i["model"] for i in items) == ["fcpe", "pc_nsf_hifigan", "pydomino", "tsqyomi"]
    assert all(i["size"] and i["license"] and i["url"].startswith("https://") for i in items)
    assert sum(i["size"] for i in items) == 196_021_366
    assert next(i for i in items if i["model"] == "pc_nsf_hifigan")["license"] == "CC-BY-NC-SA-4.0"
