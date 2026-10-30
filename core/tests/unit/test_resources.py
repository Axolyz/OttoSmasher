"""发布版的随包文件（阶段 10，2026-10-30）：OTTO_RESOURCES 指向 .app 的 Resources 时，权重先找工作区 Models/、没有就用随包的，随包的直接算已核对；
默认工作区换成 ~/Documents/OttoSmasher Workspace。没设 OTTO_RESOURCES = 源码运行，仍是仓库。"""

from __future__ import annotations

from pathlib import Path

from ottosmasher import resources
from ottosmasher.models import registry


def _weight():
    return next(f for m in registry.MODELS for f in m.files if f.role == "weight" and f.size)


def test_source_run_uses_repo(monkeypatch):
    monkeypatch.delenv("OTTO_RESOURCES", raising=False)
    assert resources.root() == resources.REPO and resources.default_workspace() == resources.REPO / "dev-workspace"
    assert resources.bundled_models() is None


def test_packaged_bundled_weights_and_workspace(monkeypatch, tmp_path):
    res = tmp_path / "Resources"
    f = _weight()
    bundled = res / "models" / f.rel_path
    bundled.parent.mkdir(parents=True)
    with open(bundled, "wb") as fh:  # 稀疏文件：大小对就行
        fh.truncate(f.size)
    monkeypatch.setenv("OTTO_RESOURCES", str(res))
    assert resources.default_workspace() == Path.home() / "Documents" / "OttoSmasher Workspace"
    ws_models = tmp_path / "ws" / "Models"
    assert registry.file_path(f, ws_models, res / "third_party" / "model-support") == bundled
    st = {x["path"]: x["state"] for m in registry.file_status(ws_models, res / "third_party" / "model-support", {}) for x in m["files"]}
    assert st[str(bundled)] == "ok"
    # 工作区里有（导入的替换版本）就用工作区的
    mine = ws_models / f.rel_path
    mine.parent.mkdir(parents=True)
    mine.write_bytes(b"x")
    assert registry.file_path(f, ws_models, res / "third_party" / "model-support") == mine
