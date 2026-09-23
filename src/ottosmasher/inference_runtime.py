"""One inference environment and explicit device policy, snapshotted per task."""

import json
import os
import subprocess

from .workspace import ROOT


def python_path(name="inference"):
    base = ROOT / ".runtime/envs" / name
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
    return {k: values[k] for k in ("inference_device", "cuda_device")}


def torch_device(config=None):
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


def onnx_providers(config=None):
    import onnxruntime as ort

    config = config or settings()
    requested = config.get("inference_device", "auto")
    available = ort.get_available_providers()
    if requested == "mps":
        raise RuntimeError("ONNX Runtime 不支持 MPS；请将执行设备设为自动或 CPU")
    cuda_selected = requested == "cuda"
    if requested == "auto" and "CUDAExecutionProvider" in available:
        cuda_selected = torch_device(config).startswith("cuda")
    if cuda_selected:
        torch_device({**config, "inference_device": "cuda"})
        if "CUDAExecutionProvider" not in available:
            raise RuntimeError("缺少 ONNX CUDA 执行提供器；未回退到 CPU")
        return [("CUDAExecutionProvider", {"device_id": int(config.get("cuda_device", 0))})]
    return ["CPUExecutionProvider"]


def check():
    python = python_path()
    if not python.is_file():
        return {"ready": False, "python": str(python), "error": "统一推理环境尚未安装"}
    try:
        result = subprocess.run(
            [str(python), "-m", "ottosmasher.inference_runtime"],
            capture_output=True,
            text=True,
            timeout=45,
            check=False,
            env={**os.environ, "OTTO_INFERENCE_SETTINGS": json.dumps(settings())},
        )
        if result.returncode:
            return {"ready": False, "python": str(python), "error": result.stderr[-6000:]}
        return {"ready": True, "python": str(python), **json.loads(result.stdout)}
    except (subprocess.TimeoutExpired, ValueError) as exc:
        return {"ready": False, "python": str(python), "error": str(exc)}


if __name__ == "__main__":
    from importlib.metadata import version

    import onnxruntime as ort

    print(
        json.dumps(
            {
                "torch_device": torch_device(),
                "onnx_providers": onnx_providers(),
                "available_onnx_providers": ort.get_available_providers(),
                "versions": {k: version(k) for k in ("torch", "numpy", "librosa", "transformers", "pymss")},
            }
        )
    )


def separation_device(config=None):
    """pymss accepts a backend name plus device_ids, not a cuda:N string."""
    actual = torch_device(config)
    return {"device": actual.split(":")[0], "device_ids": [int(actual.split(":")[1]) if ":" in actual else 0]}


def onnx_session(path, options=None):
    import onnxruntime as ort

    config = settings()
    providers = onnx_providers(config)
    if providers[0][0] == "CUDAExecutionProvider" and hasattr(ort, "preload_dlls"):
        ort.preload_dlls()  # Reuse the CUDA/cuDNN runtime installed with PyTorch on Windows.
    options = options or ort.SessionOptions()
    if config.get("inference_device") == "cuda":
        options.add_session_config_entry("session.disable_cpu_ep_fallback", "1")
    session = ort.InferenceSession(str(path), options, providers=providers)
    if config.get("inference_device") == "cuda" and "CUDAExecutionProvider" not in session.get_providers():
        raise RuntimeError("ONNX CUDA 初始化失败；未接受 CPU 替代")
    session.disable_fallback()
    return session
