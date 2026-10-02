"""Independent ONNX and experiment-only torch runtime selection."""

import json
import os
import subprocess
import sys
import threading

from .workspace import ROOT


def python_path(name="onnx"):
    if name in ("inference", "torch"):
        from .editions import edition

        if edition() != "experiment":
            raise ValueError("standard 不提供 PyTorch 推理环境")
        name = "inference"
    base = (
        __import__("pathlib").Path(os.environ.get("OTTO_ONNX_ENV", ROOT / ".runtime/envs" / name))
        if name == "onnx"
        else ROOT / ".runtime/envs" / name
    )
    candidates = (
        [base / "Scripts/python.exe", base / "python.exe"] if os.name == "nt" else [base / "bin/python"]
    )
    return next((p for p in candidates if p.is_file()), candidates[0])


def settings():
    raw = os.environ.get("OTTO_INFERENCE_SETTINGS")
    if raw:
        return json.loads(raw)
    from .ui_catalog import settings as read
    from .workspace import connect

    with connect() as db:
        values = read(db)
    return {k: values[k] for k in ("inference_device", "cuda_device", "onnx_acceleration", "onnx_device_id")}


def torch_device(config=None):
    from .editions import edition

    if edition() != "experiment":
        raise ValueError("standard 不提供 PyTorch 推理")
    import torch

    config = config or settings()
    requested = config.get("inference_device", "auto")
    index = int(config.get("cuda_device", 0))
    cuda = torch.cuda.is_available() and index < torch.cuda.device_count()
    mps = hasattr(torch.backends, "mps") and torch.backends.mps.is_available()
    chosen = ("cuda" if cuda else "mps" if mps else "cpu") if requested == "auto" else requested
    if chosen == "cuda" and not cuda:
        raise RuntimeError(f"指定的 CUDA 设备 {index} 不可用；未回退到 CPU")
    if chosen == "mps" and not mps:
        raise RuntimeError("指定的 MPS 不可用；未回退到 CPU")
    if chosen not in ("cuda", "mps", "cpu"):
        raise ValueError("未知推理设备")
    return f"cuda:{index}" if chosen == "cuda" else chosen


def accelerator(platform=None):
    return {"win32": "DmlExecutionProvider", "darwin": "CoreMLExecutionProvider"}.get(
        platform or sys.platform
    )


def onnx_providers(config=None):
    import onnxruntime as ort

    config = settings() if config is None else config
    available = ort.get_available_providers()
    if "CPUExecutionProvider" not in available:
        raise RuntimeError("ONNX CPU 执行提供器不可用")
    if not config.get("onnx_acceleration", False):
        return ["CPUExecutionProvider"]
    provider = accelerator()
    if provider is None:
        return ["CPUExecutionProvider"]
    if provider not in available:
        raise RuntimeError("当前平台的 ONNX 加速后端不可用；未回退到 CPU")
    options = (
        {"device_id": int(config.get("onnx_device_id", 0))}
        if provider == "DmlExecutionProvider"
        else {"ModelFormat": "NeuralNetwork", "MLComputeUnits": "ALL"}
    )
    return [(provider, options), "CPUExecutionProvider"]


def check():
    from .model_inventory import inventory

    python = python_path()
    frozen = settings()
    base = {"python": str(python), "accelerator": accelerator(), "models": inventory(frozen)}
    if not python.is_file():
        return {**base, "ready": False, "error": "ONNX 推理环境尚未安装"}
    try:
        result = subprocess.run(
            [str(python), "-m", "ottosmasher.inference_runtime"],
            capture_output=True,
            text=True,
            timeout=45,
            check=False,
            env={**os.environ, "OTTO_INFERENCE_SETTINGS": json.dumps(frozen)},
        )
        if result.returncode:
            return {**base, "ready": False, "error": result.stderr[-6000:]}
        return {**base, "ready": True, **json.loads(result.stdout)}
    except (subprocess.TimeoutExpired, ValueError) as exc:
        return {**base, "ready": False, "error": str(exc)}


def separation_device(config=None):
    """pymss accepts a backend name plus device_ids, not a cuda:N string."""
    actual = torch_device(config)
    return {"device": actual.split(":")[0], "device_ids": [int(actual.split(":")[1]) if ":" in actual else 0]}


class LockedSession:
    """Serialize runs, including providers whose session Run is not thread safe."""

    def __init__(self, session, path=None, provider=None):
        self.session = session
        self.path, self.provider, self.profiled = path, provider, False
        self.lock = threading.Lock()

    def __getattr__(self, name):
        return getattr(self.session, name)

    def run(self, *args, **kwargs):
        with self.lock:
            from .inference_evidence import record

            try:
                result = self.session.run(*args, **kwargs)
            except Exception as exc:
                if self.path is not None:
                    record(self.path, self.provider, status="failed", error=str(exc))
                raise
            if not self.profiled and self.path is not None:
                self.profiled = True
                from pathlib import Path

                profile = self.session.end_profiling()
                counts = {}
                if profile:
                    report = Path(profile)
                    try:
                        for event in json.loads(report.read_text()):
                            ep = event.get("args", {}).get("provider")
                            if ep:
                                counts[ep] = counts.get(ep, 0) + 1
                    finally:
                        report.unlink(missing_ok=True)
                record(self.path, self.provider, status="passed", executed_nodes=counts)
            return result


def onnx_session(path, options=None, config=None):
    import onnxruntime as ort
    from .model_inventory import install_support

    install_support()
    config = settings() if config is None else config
    providers = onnx_providers(config)
    options = options or ort.SessionOptions()
    requested = providers[0][0] if isinstance(providers[0], tuple) else providers[0]
    if requested == "DmlExecutionProvider":
        options.enable_mem_pattern = False
        options.execution_mode = ort.ExecutionMode.ORT_SEQUENTIAL
    if not isinstance(path, bytes):
        import tempfile

        options.enable_profiling = True
        options.profile_file_prefix = os.path.join(tempfile.gettempdir(), "otto-onnx-" + str(os.getpid()))
    try:
        session = ort.InferenceSession(
            path if isinstance(path, bytes) else str(path), options, providers=providers
        )
    except Exception as exc:
        from .inference_evidence import record

        if not isinstance(path, bytes):
            record(path, requested, status="failed", error=str(exc))
        raise
    session.disable_fallback()
    if requested not in session.get_providers():
        error = f"指定的 {requested} 初始化失败；未回退到 CPU"
        if not isinstance(path, bytes):
            from .inference_evidence import record

            record(path, requested, status="failed", error=error)
        raise RuntimeError(error)
    print(
        f"ONNX: {requested}; active={session.get_providers()}; CPU 算子分配允许，模型加速效果须实测",
        file=sys.stderr,
    )
    return LockedSession(session, path if not isinstance(path, bytes) else None, requested)


def probe():
    import importlib.util
    import onnxruntime as ort
    from .model_inventory import inventory

    result = {
        "runtime": "onnx",
        "onnx_providers": ort.get_available_providers(),
        "torch_installed": importlib.util.find_spec("torch") is not None,
        "accelerator": accelerator(),
        "models": inventory(settings()),
        "probe_passed": False,
    }
    result["components"] = {
        name: importlib.util.find_spec(name) is not None
        for name in ("otto_domino_decoder", "pyopenjtalk", "tokenizers", "numpy", "soundfile", "librosa")
    }
    try:
        if not all(result["components"].values()):
            raise RuntimeError(
                "运行环境组件缺失：" + str([k for k, v in result["components"].items() if not v])
            )
        import pyopenjtalk

        from pathlib import Path

        if not Path(os.fsdecode(pyopenjtalk.OPEN_JTALK_DICT_DIR)).is_dir():
            raise RuntimeError("Open JTalk 辞典缺失；检测不会自动下载")
        # Probe the dictionary only; legacy yomi weights are not part of standard.
        pyopenjtalk.g2p("あ", kana=False, use_sudachi_kanji_yomi=False, predict_nani=False)
        # Tiny bundled protobuf exercises session creation and actual execution, without model weights.
        from .runtime_probe import MODEL
        import numpy as np

        session = onnx_session(MODEL)
        value = session.run(None, {"x": np.ones((1, 2), dtype=np.float32)})[0]
        if not np.array_equal(value, np.full((1, 2), 2, dtype=np.float32)):
            raise ValueError("运行库探测结果错误")
        result.update(probe_passed=True, active_providers=session.get_providers())
    except Exception as exc:
        result["probe_error"] = str(exc)
    return result


if __name__ == "__main__":
    print(json.dumps(probe()))
