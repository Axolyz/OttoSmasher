"""统一的 ONNX 会话工厂（规格 14 §14.7、16 R19.5；ROADMAP L6）。

四类模型（pydomino、tsqyomi、FCPE、PC-NSF-HiFiGAN）都从这里建会话：
- 加载前校验文件 SHA-256（指纹不符明确报错）；
- 默认 CPU；“ONNX 硬件加速”打开时 macOS 用 CoreML（NeuralNetwork 格式、ALL 计算单元），Windows 用 DirectML（设备号可设、关内存模式、顺序执行），
  Linux 只用 CPU；provider 列表为 [加速 EP, CPU]，允许个别算子落到 CPU，但**请求的加速 EP 没进入会话就报错**（不整模型静默回退）；
- 实测证据：首次成功推理后用 profiling 统计各 EP 执行的节点数（“实测通过 + 节点分布”），失败记“实测失败 + 原因”。
  provider 可用 ≠ 实测通过。证据由任务进程随结果交回，Core 写进 ``model_probe``。
"""

from __future__ import annotations

import hashlib
import json
import os
import sys
import tempfile
import threading
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from ..core.errors import CoreError

COREML = "CoreMLExecutionProvider"
DML = "DmlExecutionProvider"
CPU = "CPUExecutionProvider"

_sha_memo: dict[tuple[str, int, int], str] = {}
_sha_lock = threading.Lock()


@dataclass(frozen=True)
class Device:
    """提交任务时冻结的设备设置（13 §13.1.2）。"""

    accelerate: bool = False
    directml_device: int = 0

    @classmethod
    def of(cls, d: dict[str, Any] | None) -> Device:
        d = d or {}
        return cls(bool(d.get("accelerate", False)), int(d.get("directml_device", 0)))

    def wire(self) -> dict[str, Any]:
        return {"accelerate": self.accelerate, "directml_device": self.directml_device}


def accel_provider(platform: str = sys.platform) -> str | None:
    if platform == "darwin":
        return COREML
    if platform == "win32":
        return DML
    return None


def providers_for(device: Device, platform: str = sys.platform) -> list[Any]:
    """会话的 provider 列表（带选项）。"""
    ep = accel_provider(platform) if device.accelerate else None
    if ep == COREML:
        return [(COREML, {"ModelFormat": "NeuralNetwork", "MLComputeUnits": "ALL"}), CPU]
    if ep == DML:
        return [(DML, {"device_id": device.directml_device}), CPU]
    return [CPU]


def file_sha256(path: Path) -> str:
    """文件 SHA-256（同一进程里按“路径 + 大小 + 修改时间”记住，换了文件就重算）。"""
    st = path.stat()
    key = (str(path), st.st_size, st.st_mtime_ns)
    with _sha_lock:
        hit = _sha_memo.get(key)
    if hit is not None:
        return hit
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    digest = h.hexdigest()
    with _sha_lock:
        _sha_memo[key] = digest
    return digest


def check_file(model: str, path: Path, sha256: str) -> None:
    if not path.is_file():
        raise CoreError("model-file-missing", model=model, path=str(path))
    got = file_sha256(path)
    if got != sha256:
        raise CoreError("model-sha-mismatch", model=model, path=str(path), expected=sha256, got=got)


@dataclass
class Session:
    """包装好的会话：``run`` 第一次成功后交出实测证据（``probe``）。"""

    model: str
    sha256: str
    device: Device
    inner: Any
    probing: bool
    probe: dict[str, Any] | None = None
    _lock: threading.Lock = field(default_factory=threading.Lock)

    def __getattr__(self, name: str) -> Any:
        # get_inputs / get_outputs / get_providers 等直接转给底层会话（tsqyomi 的推理引擎按 InferenceSession 的接口用它）
        if name.startswith("_") or name == "inner":
            raise AttributeError(name)
        return getattr(self.inner, name)

    def providers(self) -> list[str]:
        return list(self.inner.get_providers())

    def inputs(self) -> list[Any]:
        return list(self.inner.get_inputs())

    def run(self, outputs: list[str] | None, feeds: dict[str, Any]) -> list[Any]:
        # DirectML 不支持同一会话并行 Run：一律串行（别的 EP 也只是少一点并行，任务进程本来就一个一个跑）
        with self._lock:
            try:
                out = self.inner.run(outputs, feeds)
            except Exception as exc:
                if self.probe is None:
                    self.probe = self._probe_record("failed", error=f"{type(exc).__name__}: {exc}")
                raise
            if self.probing and self.probe is None:
                self.probe = self._probe_record("passed", nodes=_profile_nodes(self.inner))
                self.probing = False
            return out

    def _probe_record(self, status: str, *, nodes: dict[str, int] | None = None, error: str | None = None) -> dict[str, Any]:
        return {"model": self.model, "device": self.device.wire(), "file_sha": self.sha256, "status": status, "nodes": nodes, "error": error}


def _profile_nodes(sess: Any) -> dict[str, int] | None:
    """结束 profiling，统计每个 EP 执行的节点数（同名节点只算一次）。"""
    try:
        path = sess.end_profiling()
    except Exception:  # noqa: BLE001 — 拿不到证据就如实记“没有节点分布”，不当作推理失败
        return None
    try:
        events = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    finally:
        try:
            os.unlink(path)
        except OSError:
            pass
    seen: dict[str, str] = {}
    for ev in events if isinstance(events, list) else []:
        if ev.get("cat") != "Node":
            continue
        args = ev.get("args") or {}
        prov = args.get("provider")
        name = str(ev.get("name", "")).removesuffix("_kernel_time").removesuffix("_fence_before").removesuffix("_fence_after")
        if prov and name:
            seen.setdefault(name, prov)
    return dict(sorted(Counter(seen.values()).items()))


def create_session(
    model: str,
    path: Path,
    sha256: str,
    device: Device,
    *,
    intra_threads: int | None = None,
    probe: bool = True,
    ort: Any = None,
    platform: str = sys.platform,
) -> Session:
    """建会话。``probe``：首次成功推理后统计节点分布（每个任务进程每个模型一次）。``ort`` 只给测试替换。"""
    check_file(model, path, sha256)
    if ort is None:
        try:
            import onnxruntime as ort  # noqa: PLC0415 — 只有任务进程需要
        except ImportError as exc:
            raise CoreError("onnx-runtime-missing", detail=f"{type(exc).__name__}: {exc}") from None
    providers = providers_for(device, platform)
    wanted = providers[0][0] if isinstance(providers[0], tuple) else providers[0]
    so = ort.SessionOptions()
    if intra_threads:
        so.intra_op_num_threads = intra_threads
    if wanted == DML:
        so.enable_mem_pattern = False
        so.execution_mode = ort.ExecutionMode.ORT_SEQUENTIAL
    if probe:
        so.enable_profiling = True
        so.profile_file_prefix = str(Path(tempfile.gettempdir()) / f"otto-ort-{model}-{os.getpid()}")
    available = set(ort.get_available_providers())
    if wanted != CPU and wanted not in available:
        raise CoreError("onnx-ep-missing", model=model, provider=wanted, active=",".join(sorted(available)))
    try:
        inner = ort.InferenceSession(str(path), sess_options=so, providers=providers)
    except Exception as exc:  # noqa: BLE001 — 会话建不起来就是失败（不改用 CPU 重来）
        raise CoreError("onnx-session-failed", model=model, provider=wanted, detail=f"{type(exc).__name__}: {exc}") from None
    active = list(inner.get_providers())
    if wanted != CPU and wanted not in active:
        raise CoreError("onnx-ep-missing", model=model, provider=wanted, active=",".join(active))
    return Session(model, sha256, device, inner, probing=probe)
