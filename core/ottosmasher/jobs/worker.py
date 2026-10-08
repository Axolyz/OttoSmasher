"""任务进程入口：``python -m ottosmasher.jobs.worker <任务目录>``。

读 ``input.json``（种类、冻结的参数与设备设置），执行，向 stdout 逐行写 JSON 事件：
``{"type": "progress", ...}``、``{"type": "result", "result": ...}``、``{"type": "error", "code", "args"}``。
stderr 是日志。只写本任务目录；登记与否由 Core 决定（取消永远不会留下半成品登记）。
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import time
import traceback
from collections.abc import Callable
from pathlib import Path
from typing import Any

from ..core.errors import CoreError


class Ctx:
    def __init__(self, job_dir: Path, device: dict[str, Any]) -> None:
        self.job_dir = job_dir
        self.device = device

    def emit(self, msg: dict[str, Any]) -> None:
        sys.stdout.write(json.dumps(msg, ensure_ascii=False) + "\n")
        sys.stdout.flush()

    def progress(self, stage: str, done: int, total: int, code: str = "", **args: Any) -> None:
        self.emit({"type": "progress", "stage": stage, "done": done, "total": total, "code": code, "args": args})

    def log(self, text: str) -> None:
        sys.stderr.write(text + "\n")
        sys.stderr.flush()


def _models_verify(params: dict[str, Any], ctx: Ctx) -> dict[str, Any]:
    from ..models.registry import sha256_file

    paths: list[str] = params["paths"]
    out: dict[str, Any] = {}
    for i, p in enumerate(paths):
        ctx.progress("hashing", i, len(paths), "models-hashing", file=Path(p).name)
        path = Path(p)
        try:
            st = path.stat()
        except FileNotFoundError:
            continue
        out[p] = {"size": st.st_size, "mtime_ns": st.st_mtime_ns, "sha256": sha256_file(path)}
        ctx.log(f"sha256 {p} {out[p]['sha256']}")
    ctx.progress("hashing", len(paths), len(paths), "models-hashing")
    return {"hashes": out}


def _selftest_sleep(params: dict[str, Any], ctx: Ctx) -> dict[str, Any]:
    """睡一会儿；可以起若干子进程（同一进程组），用来验证取消会结束整棵树。"""
    children = []
    for _ in range(int(params.get("children", 0))):
        children.append(subprocess.Popen([sys.executable, "-c", "import time; time.sleep(600)"]))
    # 原子写入：别人（测试、诊断）随时可能来读，不能读到写了一半的文件
    tmp = ctx.job_dir / f"children.json.{os.getpid()}.tmp"
    tmp.write_text(json.dumps([c.pid for c in children]))
    os.replace(tmp, ctx.job_dir / "children.json")
    seconds = float(params.get("seconds", 1.0))
    steps = max(1, int(seconds / 0.05))
    for i in range(steps):
        ctx.progress("sleeping", i, steps, "selftest-sleeping")
        time.sleep(seconds / steps)
    for c in children:
        c.terminate()
        c.wait()
    return {"slept": seconds, "device": ctx.device}


def _selftest_fail(params: dict[str, Any], ctx: Ctx) -> dict[str, Any]:
    ctx.log("selftest: failing on purpose")
    raise CoreError("selftest-failed", reason=params.get("reason", "requested"))


def _studio_models(params: dict[str, Any], ctx: Ctx) -> dict[str, Any]:
    """列出 Studio 中已下载完整的模型（14 §14.6.3）。"""
    from ..studio import protocol
    from ..studio.discovery import StudioEnv

    env = StudioEnv.of(params["env"])
    ctx.progress("listing", 0, 1, "studio-listing")
    models = protocol.list_models(env, work_dir=ctx.job_dir, log_path=ctx.job_dir / "studio.log")
    return {"env": env.wire(), "models": models}


def _separate(params: dict[str, Any], ctx: Ctx) -> dict[str, Any]:
    """分离（规格 05 §5.5、14 §14.6.4）：解码输入 → Studio infer → 校验输出 → MP3 V0（无缝校验）。登记由 Core 做。"""
    from ..media import decode as dec
    from ..media import mp3, wavfile
    from ..studio import protocol
    from ..studio.discovery import StudioEnv

    env = StudioEnv.of(params["env"])
    model = params["model"]
    stems: list[str] = params["stems"]
    ctx.progress("fingerprint", 0, 1, "sep-fingerprint")
    fp0 = protocol.fingerprint(env, model)

    # 输入：资产选区解码成 PCM WAV（保持源采样率与声道）
    inp = params["input"]
    ref = dec.StreamRef(**inp["ref"])
    ctx.progress("decoding", 0, 1, "sep-decoding")
    pcm = dec.decode_frames(ref, inp["a"], inp["b"], cache=Path(params["cache"]))
    in_dir = ctx.job_dir / "input"
    in_dir.mkdir(parents=True, exist_ok=True)
    in_path = in_dir / "input.wav"
    wavfile.save_wav24(in_path, pcm, ref.sample_rate)
    in_frames = int(pcm.shape[0])
    del pcm

    out_dir = ctx.job_dir / "out"
    out_dir.mkdir(parents=True, exist_ok=True)
    done: dict[str, dict[str, Any]] = {}

    def on_event(ev: dict[str, Any]) -> None:
        t, p = ev.get("type"), ev.get("payload") or {}
        if t == "task_progress" and isinstance(p.get("total"), (int, float)) and p.get("total"):
            ctx.progress("separating", int(p.get("done") or 0), int(p["total"]), "sep-separating", step=str(p.get("stage") or ""))
        elif t == "task_stage":
            ctx.progress("separating", 0, 0, "sep-stage", step=str(p.get("stage") or ""))
        elif t == "task_log":
            ctx.log(f"[studio] {p}")
        elif t == "task_done":
            done[str(ev.get("taskId"))] = p

    device = params.get("device", "auto")
    payload: dict[str, Any] = {
        "model": model["name"],
        "tasks": [{"taskId": "input-0", "input": str(in_path)}],
        "output": str(out_dir),
        "outputFormat": "wav",
        "selectedStems": stems,
        "device": device,
        "modelDir": env.model_dir,
        "download": False,
    }
    if device == "cuda":
        payload["deviceIds"] = [int(params.get("deviceId", 0))]
    seconds = in_frames / ref.sample_rate
    protocol.run(
        env, "infer", payload, work_dir=ctx.job_dir, log_path=ctx.job_dir / "studio.log",
        timeout=max(600.0, seconds * 10 + 600.0), on_event=on_event,
    )  # fmt: skip

    # 只信任 task_done.outputs；所有输入都有 task_done；路径在输出目录内且存在；所选声部全部产出；时长一致（±1 帧）
    td = done.get("input-0")
    if td is None:
        raise CoreError("sep-output-invalid", reason="no-task-done")
    outputs = {}
    root = out_dir.resolve()
    for o in td.get("outputs") or []:
        if not isinstance(o, dict) or "path" not in o or "stem" not in o:
            continue
        path = Path(o["path"]).resolve()
        if root not in path.parents or not path.is_file():
            raise CoreError("sep-output-invalid", reason="outside-or-missing", path=str(path))
        outputs[str(o["stem"])] = path
    missing = [st for st in stems if st not in outputs]
    if missing:
        raise CoreError("sep-output-invalid", reason="missing-stem", stems=", ".join(missing))
    infos = {}
    for st in stems:
        frames, rate, ch = mp3.wav_info(outputs[st])
        expect = round(in_frames * rate / ref.sample_rate)
        if abs(frames - expect) > 1:
            raise CoreError("sep-output-invalid", reason="length", stem=st, expected=expect, got=frames)
        infos[st] = (frames, rate, ch)
    if protocol.fingerprint(env, model) != fp0:
        raise CoreError("sep-model-changed", model=model["name"])

    tracks = ctx.job_dir / "tracks"
    tracks.mkdir(exist_ok=True)
    result_stems = []
    for i, st in enumerate(stems):
        ctx.progress("encoding", i, len(stems), "sep-encoding", stem=st)
        frames, rate, ch = infos[st]
        dst = tracks / f"{i:02d}.mp3"
        manifest = mp3.encode_v0(outputs[st], dst, frames=frames, rate=rate, channels=ch)
        result_stems.append({"stem": st, "mp3": str(dst), "frames": manifest["frames"], "rate": manifest["rate"], "channels": ch, "manifest": manifest})
    ctx.progress("encoding", len(stems), len(stems), "sep-encoding")
    return {
        "stems": result_stems,
        "fingerprint": fp0,
        "studioVersion": env.version,
        "inputFrames": in_frames,
        "inputRate": ref.sample_rate,
    }


def _import_scan(params: dict[str, Any], ctx: Ctx) -> dict[str, Any]:
    """采样库导入的扫描（06 §6.6）：探测、确切时长、峰值（写进任务目录的 cache，登记时移进工作区缓存）、同名画面。"""
    from ..core.imports import scan

    return scan(list(params["paths"]), ctx.job_dir / "cache", lambda done, total: ctx.progress("scan", done, total, "import-scanning"))


def _sources_scan(params: dict[str, Any], ctx: Ctx) -> dict[str, Any]:
    """原片文件夹扫描（阶段 3.13）：没登记过的音频/视频做准备，登记与认移动在 Core 里。"""
    from ..core.roots import scan_roots

    return scan_roots(list(params["roots"]), list(params["known"]), ctx.job_dir / "cache", lambda done, total: ctx.progress("scan", done, total, "sources-scanning"))


def _models_probe(params: dict[str, Any], ctx: Ctx) -> dict[str, Any]:
    """在提交时冻结的设备设置下给每个模型做一次最小推理（ROADMAP L6）。"""
    from ..models.onnx import Device
    from ..models.probe import probe_all

    probes = probe_all(
        Path(params["models_dir"]), Path(params["support_dir"]), Device.of(ctx.device),
        lambda done, total, model: ctx.progress("probe", done, total, "models-probing", model=model),
    )
    return {"probes": probes}


def _dictionary_compile(params: dict[str, Any], ctx: Ctx) -> dict[str, Any]:
    """用户辞典：编译到任务目录并加载验证；启用由 Core 做（08 §8.2.4）。"""
    from ..lang.ja import dictionary

    out = ctx.job_dir / "user.dic"
    name = dictionary.compile_to(params["text"], out)
    return {"name": name, "path": str(out) if name else None, "entries": len(dictionary.check(params["text"]))}


def _dictionary_preview(params: dict[str, Any], ctx: Ctx) -> dict[str, Any]:
    """辞典预览：用草稿（或当前）辞典给一句话出音素与读音。"""
    from ..lang.ja import dictionary
    from ..lang.ja.runtime import JaRuntime
    from ..models.onnx import Device

    draft = params.get("text")
    if draft is not None:
        out = ctx.job_dir / "draft.dic"
        name = dictionary.compile_to(draft, out)
        path, version = (out if name else None), dictionary.version_of(name)
    else:
        path = Path(params["current"]) if params.get("current") else None
        version = dictionary.version_of(Path(params["current"]).name if params.get("current") else None)
    rt = JaRuntime(Path(params["models_dir"]), Path(params["support_dir"]), Device.of(ctx.device), path, version)
    r = rt.analyze(params["sentence"])
    return {
        "phonemes": r.phonemes,
        "words": [{"text": w.text, "reading": w.reading, "mapped": w.mapped} for w in r.words],
        "dictionary": version,
        "probes": [rt.session.probe] if rt.session.probe else [],
    }


HANDLERS: dict[str, Callable[[dict[str, Any], Ctx], dict[str, Any]]] = {
    "dictionary.compile": _dictionary_compile,
    "dictionary.preview": _dictionary_preview,
    "models.probe": _models_probe,
    "studio.models": _studio_models,
    "separate": _separate,
    "import.scan": _import_scan,
    "sources.scan": _sources_scan,
    "models.verify": _models_verify,
    "selftest.sleep": _selftest_sleep,
    "selftest.sleep_model": _selftest_sleep,
    "selftest.fail": _selftest_fail,
}


def main(argv: list[str]) -> int:
    job_dir = Path(argv[1])
    spec = json.loads((job_dir / "input.json").read_text(encoding="utf-8"))
    ctx = Ctx(job_dir, spec.get("device", {}))
    handler = HANDLERS.get(spec["kind"])
    if handler is None:
        ctx.emit({"type": "error", "code": "job-kind-unknown", "args": {"kind": spec["kind"]}})
        return 1
    try:
        result = handler(spec.get("params", {}), ctx)
    except CoreError as exc:
        ctx.emit({"type": "error", "code": exc.code, "args": exc.args_})
        return 1
    except Exception as exc:  # noqa: BLE001 — 任何异常都变成失败，并把栈写进日志
        traceback.print_exc()
        ctx.emit({"type": "error", "code": "job-exception", "args": {"type": type(exc).__name__, "message": str(exc)}})
        return 1
    ctx.emit({"type": "result", "result": result})
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
