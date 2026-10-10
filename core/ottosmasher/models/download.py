"""模型权重的准备（规格 14 §14.1、15 §15.1 / §15.8；所有者 2026-10-10：发布包不带模型权重，应用里要有地方让用户把模型下载下来）。

- **只在用户显式要求时下载**（设置 → 环境与模型「下载缺少的模型」）；普通操作从不触发下载（14 §14.1、15 §15.6）。
- 地址固定到 14 §14.1 的修订（``registry.MODELS``），**边下边算 SHA-256**，与清单一致才原子改名放到工作区 ``Models/`` 下的位置；
  不一致、网络错误、磁盘错误 → 删掉半成品，报“下载失败”并给出**网址与放置路径**（用户可以自己下载后放过去，或用「从文件导入」）。
- 「从文件导入」：用户用别的途径（浏览器、镜像、模型合集）拿到的文件，选文件或文件夹；按文件名或大小挑出候选，算 SHA-256，
  与清单里哪个权重一致就复制到哪里（文件名不对也认）；不一致的不复制，在结果里写明。
- 只处理**权重**；非权重的支持文件（tokenizer、metadata、声码器 config）随应用分发。
- 在任务进程里做，每个模型一个任务（轻量通道，可取消；取消时留下的 ``*.part-*`` 下次开始前清掉）。结果交回 Core 写进 SHA 缓存，面板直接显示“就绪”。
"""

from __future__ import annotations

import hashlib
import os
import shutil
import time
import urllib.error
import urllib.request
from collections.abc import Callable
from pathlib import Path
from typing import Any

from ..core.errors import CoreError
from . import registry

CHUNK = 1024 * 1024
TIMEOUT = 60  # 秒：连接与两次读之间的上限
USER_AGENT = "OttoSmasher-model-download"


def weights() -> list[tuple[registry.ModelSpec, registry.ModelFile]]:
    return [(m, f) for m in registry.MODELS for f in m.files if f.role == "weight"]


def plan(models_dir: Path, support_dir: Path, cached: dict[str, tuple[int, int, str]], models: list[str] | None = None) -> list[dict[str, Any]]:
    """要下载的权重：缺失、大小不符、SHA 不符的（“未校验”的不下载——那是用户放好了、还没检测的文件，先检测）。"""
    states = {m["model"]: m for m in registry.file_status(models_dir, support_dir, cached)}
    out = []
    for m, f in weights():
        if models is not None and m.id not in models:
            continue
        path = registry.file_path(f, models_dir, support_dir)
        st = next(x for x in states[m.id]["files"] if x["path"] == str(path))
        if st["state"] in ("ok", "unverified"):
            continue
        out.append({"model": m.id, "url": m.url_hint, "path": str(path), "sha256": f.sha256, "size": f.size, "replace": st["state"] != "missing",
                    "license": m.license})
    return out


def _clean_parts(directory: Path, name: str) -> None:
    for p in directory.glob(f"{name}.part-*"):
        p.unlink(missing_ok=True)


def _fail(item: dict[str, Any], reason: str, detail: str = "") -> CoreError:
    return CoreError("model-download-failed", model=item["model"], url=item["url"], path=item["path"], reason=reason, detail=detail[:300])


def fetch(item: dict[str, Any], tag: str, progress: Callable[[int, int | None], None], opener: Callable[..., Any] = urllib.request.urlopen) -> dict[str, Any]:
    """下载一个权重到它的位置：同目录的临时名 → 校验 → 原子改名。返回 SHA 缓存记录。"""
    dest = Path(item["path"])
    dest.parent.mkdir(parents=True, exist_ok=True)
    _clean_parts(dest.parent, dest.name)
    part = dest.parent / f"{dest.name}.part-{tag}"
    h = hashlib.sha256()
    done = 0
    try:
        req = urllib.request.Request(item["url"], headers={"User-Agent": USER_AGENT})
        with opener(req, timeout=TIMEOUT) as resp, open(part, "wb") as out:
            total = item.get("size") or int(resp.headers.get("Content-Length") or 0) or None
            last = 0.0
            while True:
                b = resp.read(CHUNK)
                if not b:
                    break
                out.write(b)
                h.update(b)
                done += len(b)
                now = time.monotonic()
                if now - last >= 0.25:
                    progress(done, total)
                    last = now
        progress(done, item.get("size") or done)
    except urllib.error.HTTPError as exc:
        part.unlink(missing_ok=True)
        raise _fail(item, "http", f"{exc.code} {exc.reason}") from None
    except (urllib.error.URLError, TimeoutError, ConnectionError) as exc:
        part.unlink(missing_ok=True)
        raise _fail(item, "network", str(getattr(exc, "reason", exc))) from None
    except OSError as exc:
        part.unlink(missing_ok=True)
        raise _fail(item, "disk", str(exc)) from None
    got = h.hexdigest()
    if got != item["sha256"]:
        part.unlink(missing_ok=True)
        raise _fail(item, "sha-mismatch", f"{done} bytes, sha256 {got}")
    os.replace(part, dest)
    st = dest.stat()
    return {"size": st.st_size, "mtime_ns": st.st_mtime_ns, "sha256": got}


def run_download(params: dict[str, Any], ctx: Any, opener: Callable[..., Any] = urllib.request.urlopen) -> dict[str, Any]:
    """（任务进程）下载一个权重（每个模型一个任务：一个失败不连累别的，下好的立即登记）。进度按 MB 报。"""
    it: dict[str, Any] = params["item"]
    tag = str(params.get("tag") or os.getpid())
    mb = 1024 * 1024

    def prog(done: int, total: int | None) -> None:
        ctx.progress("download", done // mb, max(1, (total or done) // mb), "models-downloading", model=it["model"])

    ctx.log(f"download {it['url']} -> {it['path']}")
    return {"hashes": {it["path"]: fetch(it, tag, prog, opener)}, "model": it["model"]}


def _candidates(paths: list[str]) -> list[Path]:
    names = {Path(f.rel_path).name for _m, f in weights()}
    sizes = {f.size for _m, f in weights() if f.size}
    out: list[Path] = []
    for raw in paths:
        p = Path(raw)
        files = [x for x in p.rglob("*") if x.is_file() and not x.is_symlink()] if p.is_dir() else [p] if p.is_file() else []
        for x in files:
            try:
                size = x.stat().st_size
            except OSError:
                continue
            if x.name in names or size in sizes:
                out.append(x)
    return out


def run_import(params: dict[str, Any], ctx: Any) -> dict[str, Any]:
    """（任务进程）从用户选的文件 / 文件夹里认出定型权重（按 SHA-256），复制到工作区 ``Models/`` 的位置。"""
    models_dir = Path(params["models_dir"])
    support_dir = Path(params["support_dir"])
    by_sha = {f.sha256: (m, f) for m, f in weights()}
    files = _candidates(params["paths"])
    hashes: dict[str, Any] = {}
    imported: list[dict[str, str]] = []
    skipped: list[dict[str, str]] = []
    for i, src in enumerate(files):
        ctx.progress("import", i, len(files), "models-importing", file=src.name)
        got = registry.sha256_file(src)
        hit = by_sha.get(got)
        if hit is None:
            skipped.append({"file": str(src), "reason": "not-a-model"})
            continue
        m, f = hit
        dest = registry.file_path(f, models_dir, support_dir)
        if dest.resolve() == src.resolve():
            skipped.append({"file": str(src), "reason": "already-in-place"})
            continue
        dest.parent.mkdir(parents=True, exist_ok=True)
        part = dest.parent / f"{dest.name}.part-import"
        shutil.copyfile(src, part)
        os.replace(part, dest)
        st = dest.stat()
        hashes[str(dest)] = {"size": st.st_size, "mtime_ns": st.st_mtime_ns, "sha256": got}
        imported.append({"model": m.id, "file": str(src), "path": str(dest)})
        ctx.log(f"import {src} -> {dest}")
    ctx.progress("import", len(files), len(files), "models-importing")
    return {"hashes": hashes, "imported": imported, "skipped": skipped}
