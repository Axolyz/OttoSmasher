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


def _models_download(params: dict[str, Any], ctx: Ctx) -> dict[str, Any]:
    from ..models.download import run_download

    return run_download(params, ctx)


def _models_import(params: dict[str, Any], ctx: Ctx) -> dict[str, Any]:
    from ..models.download import run_import

    return run_import(params, ctx)


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


JOIN_GAP = 1.0  # 多段拼接时段与段之间的静音（秒）：模型的上下文不把相邻段的声音带过来


def _separate(params: dict[str, Any], ctx: Ctx) -> dict[str, Any]:
    """分离（规格 05 §5.5、14 §14.6.4）：解码输入 → Studio infer → 校验输出 → MP3 V0（无缝校验）。登记由 Core 做。

    多段（``inputs``，2026-10-30）：Studio 按固定长度的块推理（实测约 22 秒一块，短输入也按整块算，一块约 6.5 秒），
    所以把各段**拼成一个输入**（段间 1 秒静音），分离一次，再按位置把每个声部切回各段。``items`` 与输入一一对应。"""
    import numpy as np

    from ..media import decode as dec
    from ..media import mp3, wavfile
    from ..media import probe as probe_mod
    from ..studio import protocol
    from ..studio.discovery import StudioEnv

    env = StudioEnv.of(params["env"])
    model = params["model"]
    stems: list[str] = params["stems"]
    ctx.progress("fingerprint", 0, 1, "sep-fingerprint")
    fp0 = protocol.fingerprint(env, model)

    # 输入：资产选区解码成 PCM（保持源采样率与声道）；多段时拼成一个
    inputs = params.get("inputs") or [params["input"]]
    in_dir = ctx.job_dir / "input"
    in_dir.mkdir(parents=True, exist_ok=True)
    parts: list[tuple[int, int]] = []  # 每段在拼接输入里的 (起点帧, 帧数)
    pcms = []
    rate = 0
    for k, inp in enumerate(inputs):
        ref = dec.StreamRef(**inp["ref"])
        ctx.progress("decoding", k, len(inputs), "sep-decoding")
        pcm = dec.decode_frames(ref, inp["a"], inp["b"], cache=Path(params["cache"]))
        rate = ref.sample_rate
        pcms.append(pcm)
    gap = np.zeros((round(JOIN_GAP * rate), pcms[0].shape[1]), dtype=np.float32)
    pos = 0
    chunks = []
    for k, pcm in enumerate(pcms):
        if k:
            chunks.append(gap)
            pos += gap.shape[0]
        parts.append((pos, int(pcm.shape[0])))
        chunks.append(pcm)
        pos += int(pcm.shape[0])
    joined = chunks[0] if len(chunks) == 1 else np.concatenate(chunks)
    del pcms, chunks
    in_path = in_dir / "input-0.wav"
    wavfile.save_wav24(in_path, joined, rate)
    in_frames = int(joined.shape[0])
    del joined

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
    seconds = in_frames / rate
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
        frames, out_rate, ch = mp3.wav_info(outputs[st])
        expect = round(in_frames * out_rate / rate)
        if abs(frames - expect) > 1:
            raise CoreError("sep-output-invalid", reason="length", stem=st, expected=expect, got=frames)
        infos[st] = (frames, out_rate, ch)
    if protocol.fingerprint(env, model) != fp0:
        raise CoreError("sep-model-changed", model=model["name"])

    tracks = ctx.job_dir / "tracks"
    tracks.mkdir(exist_ok=True)
    items: list[dict[str, Any]] = [{"stems": [], "inputFrames": n, "inputRate": rate} for _, n in parts]
    total, n_done = len(parts) * len(stems), 0
    for i, st in enumerate(stems):
        frames, out_rate, ch = infos[st]
        if len(parts) == 1:
            pieces = [(outputs[st], frames)]
        else:
            # 拼接输入的输出：按位置切回各段（输出采样率可能与输入不同，按比例换算），先写浮点 WAV 再编码
            pr = probe_mod.probe(outputs[st])
            a0 = pr.audio[0]
            full = dec.decode_all(dec.StreamRef(str(outputs[st]), 0, int(a0.sample_rate), int(a0.channels or ch), a0.codec, pr.format_name))
            scale = out_rate / rate
            pieces = []
            for k, (off, n) in enumerate(parts):
                a, m = round(off * scale), round(n * scale)
                seg = full[a : a + m]
                if seg.shape[0] < m:  # 末尾差一帧时补静音，不改长度
                    seg = np.concatenate([seg, np.zeros((m - seg.shape[0], seg.shape[1]), dtype=np.float32)])
                p = tracks / f"part-{k:03d}-{i:02d}.wav"
                wavfile.save_wav_f32(p, seg, out_rate)
                pieces.append((p, m))
            del full
        for k, (src, m) in enumerate(pieces):
            ctx.progress("encoding", n_done, total, "sep-encoding", stem=st)
            n_done += 1
            dst = tracks / f"{k:03d}-{i:02d}.mp3"
            manifest = mp3.encode_v0(src, dst, frames=m, rate=out_rate, channels=ch)
            items[k]["stems"].append({"stem": st, "mp3": str(dst), "frames": manifest["frames"], "rate": manifest["rate"], "channels": ch, "manifest": manifest})
    ctx.progress("encoding", total, total, "sep-encoding")
    return {"items": items, "fingerprint": fp0, "studioVersion": env.version}


def _import_scan(params: dict[str, Any], ctx: Ctx) -> dict[str, Any]:
    """采样库导入的扫描（06 §6.6）：探测、确切时长、峰值（写进任务目录的 cache，登记时移进工作区缓存）、同名画面。"""
    from ..core.imports import scan

    return scan(list(params["paths"]), ctx.job_dir / "cache", lambda done, total: ctx.progress("scan", done, total, "import-scanning"))


def _sources_scan(params: dict[str, Any], ctx: Ctx) -> dict[str, Any]:
    """原片文件夹扫描（阶段 3.13）：没登记过的音频/视频做准备，登记与认移动在 Core 里。"""
    from ..core.roots import scan_roots

    return scan_roots(list(params["roots"]), list(params["known"]), ctx.job_dir / "cache", lambda done, total: ctx.progress("scan", done, total, "sources-scanning"), list(params.get("linked") or ()))


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


def _speech_analyze(params: dict[str, Any], ctx: Ctx) -> dict[str, Any]:
    """批量语音分析（08 §8.4）：一个进程处理全部条目；模型只加载一次；同一句文本只跑一次前端；逐条结果写进任务目录并报告。"""
    from ..lang.ja.runtime import JaRuntime
    from ..models import domino, registry
    from ..models.onnx import Device, create_session
    from .speech import align_item

    device = Device.of(ctx.device)
    models, support = Path(params["models_dir"]), Path(params["support_dir"])
    d = params["dictionary"]
    rt = JaRuntime(models, support, device, Path(d["path"]) if d.get("path") else None, d["version"])
    path, sha = registry.locate(domino.MODEL_ID, domino.MODEL_FILE, models, support)
    if sha != params["versions"]["model"]["sha256"]:
        raise CoreError("model-sha-mismatch", model=domino.MODEL_ID, path=str(path), expected=params["versions"]["model"]["sha256"], got=sha)
    aligner = domino.Aligner(create_session(domino.MODEL_ID, path, sha, device))
    out_dir = ctx.job_dir / "items"
    out_dir.mkdir(exist_ok=True)
    cache = ctx.job_dir / "cache"
    fronts: dict[str, Any] = {}
    items = params["items"]
    ok = failed = 0
    for n, it in enumerate(items):
        ctx.progress("align", n, len(items), "speech-aligning")
        try:
            text = it["text"]
            if text not in fronts:
                try:
                    fronts[text] = rt.analyze(text)
                except CoreError as exc:
                    fronts[text] = exc
            f = fronts[text]
            if isinstance(f, CoreError):
                raise f
            res = align_item(it, lambda _t, f=f: f, aligner, cache=cache)
            name = f"{it['idx']}.json"
            (out_dir / name).write_text(json.dumps(res, ensure_ascii=False), encoding="utf-8")
            ctx.emit({"type": "item", "idx": it["idx"], "status": "ok", "ref": name})
            ok += 1
        except CoreError as exc:
            ctx.emit({"type": "item", "idx": it["idx"], "status": "failed", "error": exc.to_wire()})
            failed += 1
        except Exception as exc:  # noqa: BLE001 — 一条出错不拖垮整批；原因写明
            traceback.print_exc()
            ctx.emit({"type": "item", "idx": it["idx"], "status": "failed", "error": _wire(exc)})
            failed += 1
    ctx.progress("align", len(items), len(items), "speech-aligning")
    sessions = [rt.session, aligner.session]
    plan = params.get("f0") or []
    try:
        f0_done, f0_errors = _measure_f0(plan, ctx, models, support, device, sessions)
    except Exception as exc:  # noqa: BLE001 — 音高失败（缺 FCPE、会话建不起来……）不影响已经算好的对齐结果；原因写进结果（P6）
        traceback.print_exc()
        f0_done, f0_errors = [], [{"asset": None, "chunk": None, "error": _wire(exc)}]
    probes = [s.probe for s in sessions if s.probe]
    out = {"ok": ok, "failed": failed, "probes": probes, "f0": f0_done, "f0Errors": f0_errors}
    if f0_errors:
        total = sum(len(e["chunks"]) for e in plan)
        measured = sum(len(e["chunks"]) for e in f0_done)
        # 任务级提醒（码登记在错误码表，任务抽屉里显示；第一条原因代表全部）
        out["warnings"] = [{"code": "speech-f0-failed", "args": {"failed": total - measured, "total": total}, "cause": f0_errors[0]["error"]}]
    return out


def _wire(exc: BaseException) -> dict[str, Any]:
    if isinstance(exc, CoreError):
        return exc.to_wire()
    return {"code": "job-exception", "args": {"type": type(exc).__name__, "message": str(exc)}}


def _measure_f0(plan: list[dict[str, Any]], ctx: Ctx, models: Path, support: Path, device: Any, sessions: list[Any]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """FCPE 音高与能量帧（10 §10.1）：按资产分段（60 秒 + 两侧 1 秒上下文）只测缺的段；失败不影响对齐结果，原因写进结果。"""
    import numpy as np

    from ..media import decode as dec
    from ..models import f0store, fcpe, registry
    from ..models.onnx import create_session

    if not plan:
        return [], []
    path, sha = registry.locate(fcpe.MODEL_ID, fcpe.MODEL_FILE, models, support)
    session = create_session(fcpe.MODEL_ID, path, sha, device)
    sessions.append(session)
    done: list[dict[str, Any]] = []
    errors: list[dict[str, Any]] = []
    total = sum(len(e["chunks"]) for e in plan)
    n = 0
    for e in plan:
        f = e["file"]
        ref = dec.StreamRef(f["path"], int(f["ordinal"]), int(f["sample_rate"]), int(f["channels"]), f.get("codec"), f.get("format"))
        local_start, _local_end, file_start = e["storage"]
        out = ctx.job_dir / "f0" / e["asset"]
        out.mkdir(parents=True, exist_ok=True)
        ok: list[int] = []
        for k in e["chunks"]:
            ctx.progress("f0", n, total, "speech-f0")
            n += 1
            try:
                cp = f0store.chunk_plan(int(k), float(e["duration"]))
                d0, d1 = cp["decode"]
                sr = ref.sample_rate
                a = round((file_start + d0 - local_start) * sr)
                b = round((file_start + d1 - local_start) * sr)
                pcm = dec.decode_frames(ref, a, b, cache=ctx.job_dir / "cache")
                frames = fcpe.measure_chunk(session, pcm, sr, cp["skip"], cp["frames"])
                np.save(out / f"{k}.npy", frames)
                ok.append(int(k))
            except CoreError as exc:
                errors.append({"asset": e["asset"], "chunk": k, "error": exc.to_wire()})
        if ok:
            done.append({"asset": e["asset"], "identity": e["identity"], "chunks": ok})
    ctx.progress("f0", total, total, "speech-f0")  # 每块之前报一次，最后补上“全部完成”（不然成功的任务停在 (n-1)/n）
    return done, errors


def _flatten(params: dict[str, Any], ctx: Ctx) -> dict[str, Any]:
    """拉平（规格 11 §11.3）：一个进程处理全部条目；登记由 Core 做。"""
    from .flatten import run

    return run(params, ctx)


def _search_index(params: dict[str, Any], ctx: Ctx) -> dict[str, Any]:
    """语音检索索引（09 §9.6.5）：只读构建，登记由 Core 做。"""
    from .search import index

    return index(params, ctx)


def _f0_measure(params: dict[str, Any], ctx: Ctx) -> dict[str, Any]:
    """音高检索覆盖（10 §10.2.5）：测缺的 F0 段。"""
    from .search import f0

    return f0(params, ctx)


def _acoustic_measure(params: dict[str, Any], ctx: Ctx) -> dict[str, Any]:
    """单音声学指标（10 §10.3）。"""
    from .search import acoustic

    return acoustic(params, ctx)


def _export_video(params: dict[str, Any], ctx: Ctx) -> dict[str, Any]:
    """视频片段（12 §12.5）：逐帧取最近的源帧并编码；发布与登记由 Core 做。"""
    from ..core.video_export import run_job

    return run_job(params, ctx)


def _samples_independ(params: dict[str, Any], ctx: Ctx) -> dict[str, Any]:
    """采样独立化（04 §4.8）：解码无损切片、生成画面片段；登记由 Core 做。"""
    from ..core.independence import run_job

    return run_job(params, ctx)


def _primitive(name: str) -> Callable[[dict[str, Any], Ctx], dict[str, Any]]:
    def run(params: dict[str, Any], ctx: Ctx) -> dict[str, Any]:
        from . import primitives

        return getattr(primitives, name)(params, ctx)

    return run


HANDLERS: dict[str, Callable[[dict[str, Any], Ctx], dict[str, Any]]] = {
    "speech.align": _primitive("speech_align"),
    "text.analyze": _primitive("text_analyze"),
    "f0.track": _primitive("f0_track"),
    "export.video": _export_video,
    "samples.independ": _samples_independ,
    "acoustic.measure": _acoustic_measure,
    "search.index": _search_index,
    "f0.measure": _f0_measure,
    "speech.analyze": _speech_analyze,
    "dictionary.compile": _dictionary_compile,
    "dictionary.preview": _dictionary_preview,
    "models.probe": _models_probe,
    "studio.models": _studio_models,
    "separate": _separate,
    "flatten": _flatten,
    "import.scan": _import_scan,
    "sources.scan": _sources_scan,
    "models.verify": _models_verify,
    "models.download": _models_download,
    "models.import": _models_import,
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
