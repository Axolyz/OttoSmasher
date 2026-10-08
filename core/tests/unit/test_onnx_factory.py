"""统一 ONNX 会话工厂（规格 14 §14.7、16 R19.5；ROADMAP L6）：用伪 ONNX Runtime 控制可用 provider 与会话实际 provider。"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from ottosmasher.core.errors import CoreError
from ottosmasher.models.onnx import COREML, CPU, DML, Device, create_session, providers_for


class FakeOrt:
    """伪 ONNX Runtime：``available`` = 可用 provider；``active`` = 会话里实际生效的（None = 请求的全部）。"""

    class ExecutionMode:
        ORT_SEQUENTIAL = "sequential"

    def __init__(self, available, active=None, nodes=None, fail_run=False):
        self.available = list(available)
        self.active = active
        self.nodes = nodes or []
        self.fail_run = fail_run
        self.created = []

    def get_available_providers(self):
        return self.available

    def SessionOptions(self):  # noqa: N802 — 与 onnxruntime 同名
        return SimpleNamespace(enable_mem_pattern=True, execution_mode="parallel", enable_profiling=False, profile_file_prefix="", intra_op_num_threads=0)

    def InferenceSession(self, path, sess_options, providers):  # noqa: N802
        ort = self
        names = [p[0] if isinstance(p, tuple) else p for p in providers]

        class Sess:
            def __init__(self):
                self.options = sess_options
                self.providers = providers

            def get_providers(self):
                return ort.active if ort.active is not None else names

            def run(self, outputs, feeds):
                if ort.fail_run:
                    raise RuntimeError("boom")
                return ["out"]

            def end_profiling(self):
                p = Path(sess_options.profile_file_prefix + ".json")
                p.write_text(json.dumps(ort.nodes), encoding="utf-8")
                return str(p)

        s = Sess()
        self.created.append(s)
        return s


@pytest.fixture
def model(tmp_path: Path) -> tuple[Path, str]:
    p = tmp_path / "m.onnx"
    p.write_bytes(b"fake model bytes")
    return p, hashlib.sha256(b"fake model bytes").hexdigest()


def test_providers_follow_platform_and_setting():
    assert providers_for(Device(False), "darwin") == [CPU]
    assert providers_for(Device(True), "darwin") == [(COREML, {"ModelFormat": "NeuralNetwork", "MLComputeUnits": "ALL"}), CPU]
    assert providers_for(Device(True, 2), "win32") == [(DML, {"device_id": 2}), CPU]
    assert providers_for(Device(True), "linux") == [CPU]


def test_file_checks(tmp_path: Path, model):
    path, sha = model
    with pytest.raises(CoreError) as e:
        create_session("m", tmp_path / "nope.onnx", sha, Device(), ort=FakeOrt([CPU]))
    assert e.value.code == "model-file-missing"
    with pytest.raises(CoreError) as e:
        create_session("m", path, "0" * 64, Device(), ort=FakeOrt([CPU]))
    assert e.value.code == "model-sha-mismatch" and e.value.args_["got"] == sha


def test_cpu_default_and_probe_counts_nodes_per_ep(model):
    path, sha = model
    nodes = [
        {"cat": "Node", "name": "Conv_1_kernel_time", "args": {"provider": CPU}},
        {"cat": "Node", "name": "Conv_1_fence_before", "args": {"provider": CPU}},
        {"cat": "Node", "name": "Gemm_2_kernel_time", "args": {"provider": CPU}},
        {"cat": "Session", "name": "model_run"},
    ]
    ort = FakeOrt([COREML, CPU], nodes=nodes)
    s = create_session("m", path, sha, Device(False), ort=ort, platform="darwin")
    assert ort.created[0].providers == [CPU]
    assert ort.created[0].options.enable_profiling is True
    assert s.probe is None
    s.run(None, {})
    assert s.probe == {"model": "m", "device": {"accelerate": False, "directml_device": 0}, "file_sha": sha, "status": "passed", "nodes": {CPU: 2}, "error": None}
    s.run(None, {})  # 只记第一次
    assert s.probe["nodes"] == {CPU: 2}


def test_requested_ep_must_enter_the_session(model):
    path, sha = model
    # 运行库里根本没有 CoreML
    with pytest.raises(CoreError) as e:
        create_session("m", path, sha, Device(True), ort=FakeOrt([CPU]), platform="darwin")
    assert e.value.code == "onnx-ep-missing" and e.value.args_["provider"] == COREML
    # 有，但会话只拿到了 CPU：报错，不整模型静默回退
    with pytest.raises(CoreError) as e:
        create_session("m", path, sha, Device(True), ort=FakeOrt([COREML, CPU], active=[CPU]), platform="darwin")
    assert e.value.code == "onnx-ep-missing" and e.value.args_["active"] == CPU
    # 拿到了：个别算子落到 CPU 可以
    nodes = [{"cat": "Node", "name": "a_kernel_time", "args": {"provider": COREML}}, {"cat": "Node", "name": "b_kernel_time", "args": {"provider": CPU}}]
    s = create_session("m", path, sha, Device(True), ort=FakeOrt([COREML, CPU], nodes=nodes), platform="darwin")
    s.run(None, {})
    assert s.probe["status"] == "passed" and s.probe["nodes"] == {COREML: 1, CPU: 1}


def test_directml_turns_off_mem_pattern_and_runs_sequentially(model):
    path, sha = model
    ort = FakeOrt([DML, CPU])
    create_session("m", path, sha, Device(True, 1), ort=ort, platform="win32")
    opts = ort.created[0].options
    assert opts.enable_mem_pattern is False and opts.execution_mode == "sequential"
    assert ort.created[0].providers == [(DML, {"device_id": 1}), CPU]


def test_failed_first_inference_is_recorded(model):
    path, sha = model
    s = create_session("m", path, sha, Device(), ort=FakeOrt([CPU], fail_run=True))
    with pytest.raises(RuntimeError):
        s.run(None, {})
    assert s.probe["status"] == "failed" and "boom" in s.probe["error"]


def test_probe_records_are_kept_per_device_and_listed_for_the_current_one(tmp_path):
    from ottosmasher.core.server import Core

    srv = Core(tmp_path / "ws")
    srv.open()
    try:
        cpu = {"model": "fcpe", "device": {"accelerate": False, "directml_device": 0}, "file_sha": "x", "status": "passed", "nodes": {CPU: 120}, "error": None}
        acc = {"model": "fcpe", "device": {"accelerate": True, "directml_device": 0}, "file_sha": "x", "status": "failed", "nodes": None, "error": "onnx-ep-missing"}
        srv._adopt_probes({"id": "j"}, {"probes": [cpu, acc]})
        res = srv.dispatch({"id": 1, "m": "models.status", "p": {}})
        assert res["ok"], res
        assert [(p["model"], p["status"], p["nodes"]) for p in res["r"]["probes"]] == [("fcpe", "passed", {CPU: 120})]
        # 改成加速：列出加速设置下的记录
        srv.edits.apply({"ops": [{"entity": "setting", "id": "inference.accelerate", "version": 0, "fields": {"value": True}}]})
        res = srv.dispatch({"id": 2, "m": "models.status", "p": {}})
        assert [(p["status"], p["error"]) for p in res["r"]["probes"]] == [("failed", "onnx-ep-missing")]
        # 再实测一次覆盖同一（模型、设置）
        srv._adopt_probes({"id": "j2"}, {"probes": [{**acc, "status": "passed", "nodes": {COREML: 3, CPU: 4}, "error": None}]})
        res = srv.dispatch({"id": 3, "m": "models.status", "p": {}})
        assert res["r"]["probes"][0]["nodes"] == {COREML: 3, CPU: 4}
    finally:
        srv.close()
