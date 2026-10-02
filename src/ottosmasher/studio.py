"""External PyMSS Studio worker protocol. No imports or installs into its runtime."""

from __future__ import annotations

import hashlib
import json
import os
import plistlib
import subprocess
import time
from functools import lru_cache
from pathlib import Path

from .workspace import DATA, write_json


def resources_for(app):
    app = Path(app)
    if app.suffix.lower() == ".exe":
        app = app.parent
    candidates = [app / "Contents/Resources", app / "resources", app]
    return next((p for p in candidates if (p / "python/worker.py").is_file()), candidates[-1])


def detect_app(explicit=None):
    if explicit:
        return Path(explicit).expanduser()
    if os.name == "nt":
        bases = [
            Path(os.environ.get(k, ""))
            for k in ("LOCALAPPDATA", "ProgramFiles", "ProgramFiles(x86)")
            if os.environ.get(k)
        ]
        candidates = [
            base / sub
            for base in bases
            for sub in ("Programs/Pymss Studio", "Programs/pymss-studio", "Pymss Studio", "pymss-studio")
        ]
    else:
        candidates = [Path("/Applications/Pymss Studio.app"), Path.home() / "Applications/Pymss Studio.app"]
    return next(
        (p for p in candidates if (resources_for(p) / "python/worker.py").is_file()),
        candidates[0] if candidates else Path("Pymss Studio"),
    )


def configuration():
    from .ui_catalog import settings
    from .workspace import connect

    with connect() as db:
        s = settings(db)
    app = detect_app(s.get("studio_app"))
    root = Path(s.get("studio_data") or Path.home() / ".pymss-studio").expanduser()
    resources = resources_for(app)
    worker = resources / "python/worker.py"
    if not worker.is_file():
        raise ValueError("未找到 PyMSS Studio worker；请在设置中指定安装目录")
    states = [
        root / "runtime-envs/active-runtime.json",
        resources / "python-runtime/runtime-envs/active-runtime.json",
    ]
    state_file = next((p for p in states if p.is_file()), None)
    if not state_file:
        raise ValueError("Studio 没有活动推理环境；请先在 Studio 中完成环境安装")
    state = json.loads(state_file.read_text())
    python = Path(state.get("pythonPath", ""))
    if not python.is_absolute():
        python = (state_file.parent / python).resolve()
    if not python.is_file():
        raise ValueError("Studio 活动 Python 不存在：" + str(python))
    app_settings = root / "settings/app.json"
    stored = json.loads(app_settings.read_text()) if app_settings.exists() else {}
    models = Path(stored.get("modelDir") or root / "models").expanduser()
    version = "unknown"
    if (app / "Contents/Info.plist").exists():
        version = plistlib.loads((app / "Contents/Info.plist").read_bytes())["CFBundleShortVersionString"]
    env = {
        **os.environ,
        "PYMSS_STUDIO_DATA_ROOT": str(root),
        "PYMSS_MODEL_DIR": str(models),
        "PYMSS_STUDIO_RUNTIME_ENVS_DIR": str(state_file.parent),
        "PYMSS_STUDIO_ACTIVE_RUNTIME_FILE": str(state_file),
        "PYTHONNOUSERSITE": "1",
        "PYTHONUTF8": "1",
    }
    # Never leak Otto's import paths into the external interpreter.
    env.pop("PYTHONPATH", None)
    env.pop("PYTHONHOME", None)
    return {
        "app": str(app),
        "data": str(root),
        "python": str(python),
        "worker": str(worker),
        "models": str(models),
        "version": version,
        "runtime": state,
        "env": env,
    }


def call(command, payload, folder=None, timeout=120, progress_path=None):
    if command not in {"health", "env_info", "list_models", "infer"}:
        raise ValueError("Unsupported Studio command")
    c = configuration()
    payload = {**payload, "modelDir": c["models"]}
    if command == "infer":
        payload["download"] = False
    folder = Path(folder or DATA / "studio-probes")
    folder.mkdir(parents=True, exist_ok=True)
    import uuid

    token = uuid.uuid4().hex
    request = folder / (command + "-" + token + ".json")
    write_json(request, payload)
    log = folder / (command + "-" + token + ".log")
    events = []
    with log.open("w") as stderr:
        child = subprocess.Popen(
            [c["python"], c["worker"], command, "--payload", str(request)],
            cwd=folder,
            env=c["env"],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=stderr,
            text=True,
        )
        # Inherit the job's process group so cancellation kills only our own descendants.
        import queue
        import threading

        lines = queue.Queue()

        def drain():
            try:
                for line in child.stdout:
                    lines.put(line)
            finally:
                lines.put(None)

        threading.Thread(target=drain, daemon=True).start()
        deadline = time.monotonic() + timeout
        try:
            while True:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise TimeoutError("Studio worker 超时；日志：" + str(log))
                try:
                    line = lines.get(timeout=min(remaining, 1))
                except queue.Empty:
                    continue
                if line is None:
                    break
                try:
                    event = json.loads(line)
                except ValueError:
                    stderr.write(line)
                    continue
                if not isinstance(event, dict) or "type" not in event:
                    continue
                events.append(event)
                if event["type"].startswith("task_"):
                    p = event.get("payload", {})
                    if progress_path:
                        write_json(
                            Path(progress_path),
                            {
                                **p,
                                "provider": "studio",
                                "updated": time.time(),
                                "percent": round(100 * p.get("done", 0) / max(1, p.get("total", 1)), 1)
                                if event["type"] == "task_progress"
                                else None,
                            },
                        )
                    if event["type"] in ("task_stage", "task_done"):
                        print("Studio " + event["type"] + ": " + str(p.get("message", "")), flush=True)
            code = child.wait(timeout=max(1, deadline - time.monotonic()))
        except BaseException:
            child.terminate()
            try:
                child.wait(timeout=10)
            except subprocess.TimeoutExpired:
                child.kill()
                child.wait()
            raise
        finally:
            child.stdout.close()
    errors = [x["payload"] for x in events if x["type"] == "error"]
    if code or errors:
        raise RuntimeError(f"Studio {command} 失败：{errors or log.read_text()[-2000:]}；日志：{log}")
    return events


@lru_cache(maxsize=8)
def _models_cached(signature):
    events = call("list_models", {})
    response = next((x["payload"] for x in events if x["type"] == "models"), None)
    if response is None:
        raise RuntimeError("Studio worker 协议不兼容：缺少 models 事件")
    return response["models"]


def models(refresh=False):
    c = configuration()
    if refresh:
        _models_cached.cache_clear()
    # A short TTL detects completed downloads, deletions and Studio upgrades.
    signature = (
        c["worker"],
        Path(c["worker"]).stat().st_mtime_ns,
        c["python"],
        c["models"],
        int(time.time() // 30),
    )
    return [x for x in _models_cached(signature) if x.get("downloaded") and x.get("supported", True)]


def stems(model):
    value = model.get("configInstruments") or model.get("targetStem", "")
    if isinstance(value, list):
        return value
    return [s.strip() for s in str(value).replace("/", ",").replace("|", ",").split(",") if s.strip()]


def select(name, required=None):
    model = next((m for m in models() if name == m["name"] or name in m.get("aliases", [])), None)
    if model is None:
        raise ValueError("Studio 中没有已下载完整的模型：" + name)
    if required and not set(required).issubset({x.lower() for x in stems(model)}):
        raise ValueError("模型不提供所需声部：" + ", ".join(required))
    return model


@lru_cache(maxsize=128)
def file_digest(path, size, modified):
    with Path(path).open("rb") as f:
        return hashlib.file_digest(f, "sha256").hexdigest()


def fingerprint(name):
    c = configuration()
    model = select(name)
    paths = [model["modelPath"], model.get("configPath"), *model.get("auxiliaryPaths", [])]
    files = {}
    for value in filter(None, paths):
        p = Path(value)
        st = p.stat()
        files[str(p)] = file_digest(str(p), st.st_size, st.st_mtime_ns)
    worker = Path(c["worker"])
    st = worker.stat()
    return {
        "provider": "studio",
        "studio_version": c["version"],
        "runtime": c["runtime"],
        "model": model["name"],
        "files": files,
        "worker_sha256": file_digest(str(worker), st.st_size, st.st_mtime_ns),
        "adapter": "studio-worker-v1",
    }


def status():
    try:
        c = configuration()
        return {
            "ready": True,
            **{k: c[k] for k in ("app", "data", "python", "version", "models")},
            "available_models": [{**m, "stems": stems(m)} for m in models(refresh=True)],
        }
    except (ValueError, OSError, RuntimeError) as exc:
        return {"ready": False, "error": str(exc), "available_models": []}


def separate_many(name, inputs, output, selected_stems=None, device="auto", progress_path=None):
    import soundfile as sf

    model = select(name)
    fingerprint_before = fingerprint(name)
    supported = stems(model)
    if selected_stems and not {s.lower() for s in selected_stems}.issubset({s.lower() for s in supported}):
        raise ValueError(f"请选择模型实际声部：{supported}")
    output = Path(output).resolve()
    output.mkdir(parents=True, exist_ok=True)
    tasks = [{"taskId": f"input-{i}", "input": str(Path(p).resolve())} for i, p in enumerate(inputs)]
    payload = {
        "model": model["name"],
        "tasks": tasks,
        "output": str(output),
        "outputFormat": "wav",
        "selectedStems": selected_stems or supported,
        "device": device,
        "download": False,
    }
    events = call("infer", payload, output, timeout=7200, progress_path=progress_path)
    completed = {x.get("taskId"): x["payload"] for x in events if x["type"] == "task_done"}
    if fingerprint(name) != fingerprint_before:
        raise RuntimeError("Studio 模型或运行时在任务期间发生变化；未登记输出")
    results = []
    for task in tasks:
        done = completed.get(task["taskId"])
        if not done:
            raise RuntimeError("Studio 未完成全部输入；未登记残缺结果")
        original = sf.info(task["input"])
        produced = []
        for item in done.get("outputs", []):
            path = Path(item["path"]).resolve()
            if not path.is_relative_to(output) or not path.is_file():
                raise ValueError("Studio 返回无效输出路径")
            info = sf.info(path)
            if abs(info.duration - original.duration) > 0.02:
                raise ValueError("分离输出时长与输入不一致")
            produced.append(
                {
                    "path": str(path),
                    "stem": item["stem"],
                    "model": name,
                    "provider": "studio",
                    "model_fingerprints": {**fingerprint_before, "requested_device": device},
                    "source_path": task["input"],
                    "source_sha256": file_digest(
                        task["input"],
                        Path(task["input"]).stat().st_size,
                        Path(task["input"]).stat().st_mtime_ns,
                    ),
                    "parameters": payload,
                    "verified": False,
                }
            )
        if not produced or not {s.lower() for s in (selected_stems or supported)}.issubset(
            {p["stem"].lower() for p in produced}
        ):
            raise RuntimeError("Studio 返回声部不完整")
        results.append(produced)
    write_json(output / "manifest.json", {"outputs": results})
    return results
