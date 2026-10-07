"""PyMSS Studio worker 协议（规格 14 §14.6.2–§14.6.5）。只用 ``list_models``、``infer``；``download`` 永远为 false。

- 每次调用起一个独立子进程：``<Studio python> <worker.py> <命令> --payload <请求 JSON>``；stdin 关闭；stdout 每行一个 JSON 事件（UTF-8）；
  stderr 写日志文件。子进程与调用方在同一进程组：任务取消结束整棵进程树时它一起结束（协议没有取消命令）。
- 失败：退出码非 0，或出现任何 ``error`` 事件（批处理里单个输入失败时 Studio 仍可能 0 退出）→ 整次调用失败。
- 模型：只保留 ``downloaded`` 为真且 ``supported`` 不为假的；声部 = ``configInstruments``，没有则 ``targetStem``，按 / | , 拆分，保留原样大小写。
- 能力：人声模型 = 声部（小写）含 vocals；三轨 = 声部归一后同时含 对白（speech/dialogue/dialog）、音乐（music）、音效（effects/effect/sfx）。
- 模型指纹：Studio 版本 + 活动环境 JSON + 模型权重/配置/辅助文件 SHA-256 + worker 脚本 SHA-256（推理前后各算一次，不一致 → 拒绝）。
"""

from __future__ import annotations

import hashlib
import json
import re
import subprocess
import threading
from collections.abc import Callable
from pathlib import Path
from typing import Any

from ottosmasher.core.errors import CoreError

from .discovery import StudioEnv, worker_env

LIST_TIMEOUT = 120.0
_SPLIT = re.compile(r"[/|,]")
_DIALOG = {"speech", "dialogue", "dialog"}
_MUSIC = {"music"}
_EFFECTS = {"effects", "effect", "sfx"}


def run(
    env: StudioEnv,
    command: str,
    payload: dict[str, Any],
    *,
    work_dir: Path,
    log_path: Path,
    timeout: float,
    on_event: Callable[[dict[str, Any]], None] | None = None,
) -> list[dict[str, Any]]:
    """跑一次 worker 命令，返回全部事件；失败抛 ``studio-failed``（附 Studio 的错误与日志路径）。"""
    if command == "infer":
        payload = {**payload, "download": False}  # 永远不下载（即使上层误传）
    work_dir.mkdir(parents=True, exist_ok=True)
    req = work_dir / f"studio-{command}-request.json"
    req.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    events: list[dict[str, Any]] = []
    with log_path.open("ab") as log:
        proc = subprocess.Popen(
            [env.python, env.worker, command, "--payload", str(req)],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=log,
            env=worker_env(env),
            cwd=str(work_dir),
        )
        hit = threading.Event()

        def _expire() -> None:
            hit.set()
            proc.kill()

        timer = threading.Timer(timeout, _expire)
        timer.start()
        try:
            assert proc.stdout is not None
            for raw in proc.stdout:
                line = raw.decode("utf-8", errors="replace").strip()
                if not line:
                    continue
                try:
                    ev = json.loads(line)
                except ValueError:
                    log.write(b"[stdout] " + raw)
                    continue
                if not isinstance(ev, dict):
                    continue
                events.append(ev)
                if on_event is not None:
                    on_event(ev)
            code = proc.wait()
        finally:
            timer.cancel()
        timed_out = hit.is_set()
    errors = [e.get("payload") or {} for e in events if e.get("type") == "error"]
    if timed_out:
        raise CoreError("studio-failed", reason="timeout", command=command, log=str(log_path))
    if code != 0 or errors:
        first = errors[0] if errors else {}
        raise CoreError(
            "studio-failed",
            reason="studio-error" if errors else "exit-code",
            command=command,
            studio_code=first.get("code"),
            message=first.get("message"),
            exit_code=code,
            log=str(log_path),
        )
    return events


def stems_of(model: dict[str, Any]) -> list[str]:
    raw = model.get("configInstruments") or model.get("targetStem") or ""
    if isinstance(raw, list):
        raw = "|".join(str(x) for x in raw)
    return [s.strip() for s in _SPLIT.split(str(raw)) if s.strip()]


def is_vocal(stems: list[str]) -> bool:
    return any("vocals" in s.lower() for s in stems)


def is_three_track(stems: list[str]) -> bool:
    low = {s.lower() for s in stems}
    return bool(low & _DIALOG and low & _MUSIC and low & _EFFECTS)


def list_models(env: StudioEnv, *, work_dir: Path, log_path: Path) -> list[dict[str, Any]]:
    events = run(env, "list_models", {"modelDir": env.model_dir}, work_dir=work_dir, log_path=log_path, timeout=LIST_TIMEOUT)
    raw: list[dict[str, Any]] = []
    for ev in events:
        if ev.get("type") == "models":
            raw = list((ev.get("payload") or {}).get("models") or [])
    out = []
    for m in raw:
        if not isinstance(m, dict) or not m.get("downloaded") or m.get("supported") is False or not m.get("name"):
            continue
        stems = stems_of(m)
        out.append(
            {
                "name": str(m["name"]),
                "aliases": [str(a) for a in (m.get("aliases") or [])],
                "stems": stems,
                "category": m.get("category"),
                "vocal": is_vocal(stems),
                "threeTrack": is_three_track(stems),
                "files": [str(p) for p in [m.get("modelPath"), m.get("configPath"), *(m.get("auxiliaryPaths") or [])] if p],
            }
        )
    return out


def find_model(models: list[dict[str, Any]], name: str) -> dict[str, Any]:
    for m in models:
        if m["name"] == name or name in m["aliases"]:
            return m
    raise CoreError("studio-model-missing", model=name)


def _sha(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def fingerprint(env: StudioEnv, model: dict[str, Any]) -> str:
    h = hashlib.sha256()
    h.update(f"version:{env.version}\n".encode())
    h.update(Path(env.runtime_file).read_bytes())
    h.update(f"worker:{_sha(Path(env.worker))}\n".encode())
    for p in sorted(model["files"]):
        path = Path(p)
        if path.is_file():  # 缺的跳过（14 §14.6.4）
            h.update(f"{path.name}:{_sha(path)}\n".encode())
    return h.hexdigest()


def stat_signature(model: dict[str, Any]) -> list[list[Any]]:
    """模型文件的廉价身份（大小 + 修改时间），复用判断用；真正的指纹在任务里算。"""
    out = []
    for p in sorted(model["files"]):
        try:
            st = Path(p).stat()
            out.append([Path(p).name, st.st_size, st.st_mtime_ns])
        except OSError:
            out.append([Path(p).name, None, None])
    return out


