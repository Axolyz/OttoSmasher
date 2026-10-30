"""定型模型清单与文件检测（规格 14 §14.1、13 §13.4、16 R19.7）。

三种状态分开报告（P12）：
- 文件是否就位（缺失时给出期望路径；SHA-256 与清单比对）；
- 运行库是否能加载（只代表能加载，不代表推理通过）；
- 在当前设备设置下的实测状态（未实测 / 失败：原因 / 通过：加速节点数）。

权重放在工作区 ``Models/``（用户放置）；非权重支持文件随应用分发，放在支持文件目录。
SHA-256 由任务进程计算（大文件不在 Core 主线程里读），结果按“路径 + 大小 + 修改时间”缓存。
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class ModelFile:
    rel_path: str
    role: str  # "weight"：工作区 Models/ 下，用户放置；"support"：随应用分发
    sha256: str
    size: int | None = None


@dataclass(frozen=True)
class ModelSpec:
    id: str
    files: tuple[ModelFile, ...]
    url_hint: str  # 权重的下载直链（固定到规格 14 §14.1 的修订；每个模型只有一个权重文件）
    license: str = ""  # 权重的上游许可（用户下载前在界面上看到；权重不随应用分发，规格 15 §15.9）


MODELS: tuple[ModelSpec, ...] = (
    ModelSpec(
        "pydomino",
        (
            ModelFile(
                "pydomino/phoneme_transition_model.onnx",
                "weight",
                "ce3f5d7cb39e4fec08ed0380338f10193d5e00b9d032277485fa862075191710",
                21_937_113,
            ),
        ),
        "https://raw.githubusercontent.com/DwangoMediaVillage/pydomino/4930396642fdd85618884c7a209218a628fd3c34/onnx_model/phoneme_transition_model.onnx",
        "MIT",
    ),
    ModelSpec(
        "tsqyomi",
        (
            ModelFile("tsqyomi/model.onnx", "weight", "ea7e4f229a4ccb8e6bc0f7037b4dba1452ca794808eabc88b421aa7d62d5b9c8", 74_154_263),
            ModelFile("tsqyomi/tokenizer.json", "support", "6a0734cf21c802169defaffe719bc2ef12bb9d0be37e54b61ed27aa89394723d"),
            ModelFile("tsqyomi/metadata.json", "support", "829c60584ba33ca6a10fe3697ab62b0210398c93266f743e79b32d85497c9cd6"),
        ),
        "https://huggingface.co/tsukumijima/tsqyomi-models/resolve/680596dd2ad2bad59ee5db3741e197cfce79f9b4/v4/model.onnx",
        "MIT",
    ),
    ModelSpec(
        "fcpe",
        (ModelFile("features/fcpe.onnx", "weight", "013b507acd406de122b61ee497300ac6be082511101bc2136b886e48d9737e5d", 43_340_548),),
        "https://raw.githubusercontent.com/ARounder-183/HiFiShifter/6432687173ae343ef0f2f824695650e877739ee0/backend/src-tauri/resources/models/fcpe/fcpe.onnx",
        "MIT",
    ),
    ModelSpec(
        "pc_nsf_hifigan",
        (
            ModelFile("flatten/pc_nsf_hifigan.onnx", "weight", "c0d5d05b6cfe12e254c82adeed6e52a31449a2d1398e05e1d7234f7dbfd720bb", 56_589_442),
            ModelFile("flatten/config.json", "support", "c3c56efaa5abdf1862224ae8396b17680c78d0b95ab009a31ef5d2f873cf07c2"),
        ),
        "https://raw.githubusercontent.com/ARounder-183/HiFiShifter/6432687173ae343ef0f2f824695650e877739ee0/backend/src-tauri/resources/models/nsf_hifigan/pc_nsf_hifigan.onnx",
        "CC-BY-NC-SA-4.0",  # OpenVPI 预训练声码器：署名、非商业、相同方式共享
    ),
)


def spec(model_id: str) -> ModelSpec:
    for m in MODELS:
        if m.id == model_id:
            return m
    raise KeyError(model_id)


def locate(model_id: str, rel_path: str, models_dir: Path, support_dir: Path) -> tuple[Path, str]:
    """某个模型文件的实际路径与清单里的 SHA-256。"""
    for f in spec(model_id).files:
        if f.rel_path == rel_path:
            return file_path(f, models_dir, support_dir), f.sha256
    raise KeyError(rel_path)


def file_path(f: ModelFile, models_dir: Path, support_dir: Path) -> Path:
    """权重：工作区 Models/ 里有就用它（导入的替换版本），否则用随包的（发布版，2026-10-30 所有者：除 PyMSS 外模型随包）。"""
    if f.role != "weight":
        return support_dir / f.rel_path
    p = models_dir / f.rel_path
    if not p.exists():
        from .. import resources

        bundled = resources.bundled_models()
        if bundled is not None and (bundled / f.rel_path).is_file():
            return bundled / f.rel_path
    return p


def snapshot(path: Path) -> tuple[int, int] | None:
    try:
        st = path.stat()
    except FileNotFoundError:
        return None
    return st.st_size, st.st_mtime_ns


def all_files(models_dir: Path, support_dir: Path) -> list[Path]:
    return [file_path(f, models_dir, support_dir) for m in MODELS for f in m.files]


def file_status(
    models_dir: Path,
    support_dir: Path,
    cached_sha: dict[str, tuple[int, int, str]],
) -> list[dict[str, Any]]:
    """每个模型的文件状态。``cached_sha``：路径 → (大小, 修改时间 ns, sha256)。"""
    from .. import resources

    bundled_root = resources.root().resolve() if resources.packaged() else None
    out: list[dict[str, Any]] = []
    for m in MODELS:
        files = []
        for f in m.files:
            p = file_path(f, models_dir, support_dir)
            snap = snapshot(p)
            if snap is None:
                state = "missing"
            elif f.size is not None and snap[0] != f.size:
                state = "size-mismatch"
            elif bundled_root is not None and bundled_root in p.resolve().parents:
                state = "ok"  # 随包的文件：构建时按 SHA-256 核对过，.app 有签名、程序目录只读，不在每个工作区再算一遍
            else:
                c = cached_sha.get(str(p))
                if c is None or (c[0], c[1]) != snap:
                    state = "unverified"
                else:
                    state = "ok" if c[2] == f.sha256 else "sha-mismatch"
            files.append({"path": str(p), "role": f.role, "state": state})
        states = {x["state"] for x in files}
        if states == {"ok"}:
            overall = "ready"
        elif "missing" in states:
            overall = "missing"
        elif states & {"sha-mismatch", "size-mismatch"}:
            overall = "mismatch"
        else:
            overall = "unverified"
        out.append({"model": m.id, "state": overall, "files": files, "url": m.url_hint, "license": m.license,
                    "bytes": sum(f.size or 0 for f in m.files if f.role == "weight")})
    return out


def runtime_status() -> dict[str, Any]:
    """运行库能否加载（不做推理）。单独报告，失败不影响文件状态。"""
    try:
        import onnxruntime as ort  # noqa: PLC0415

        return {"onnxruntime": {"loadable": True, "version": ort.__version__, "providers": ort.get_available_providers()}}
    except Exception as exc:  # 运行库缺失或损坏
        return {"onnxruntime": {"loadable": False, "error": f"{type(exc).__name__}: {exc}"}}


def sha256_file(path: Path, chunk: int = 4 * 1024 * 1024) -> str:
    import hashlib

    h = hashlib.sha256()
    with open(path, "rb") as fh:
        while True:
            b = fh.read(chunk)
            if not b:
                break
            h.update(b)
    return h.hexdigest()


def default_support_dir() -> Path:
    """开发期支持文件目录 = 仓库内 third_party/model-support（由 tools/fetch_model_support.py 准备）。"""
    env = os.environ.get("OTTO_MODEL_SUPPORT_DIR")
    if env:
        return Path(env)
    from .. import resources

    return resources.root() / "third_party" / "model-support"
