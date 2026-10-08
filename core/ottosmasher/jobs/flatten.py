"""（任务进程）拉平（规格 11 §11.3）：一个任务处理全部条目，模型只加载一次；只读文件、只算，登记由 Core 做。

每条：解码冻结的输入（资产选区，保持采样率与声道）→ 各声道平均后重新测量 F0（FCPE，10 §10.1）→ 处理区间（仅元音 / 首元音起用本次输入的能量收紧，
人工版本不收紧）→ 定音 → mel 帧 F0 → PC-NSF-HiFiGAN 逐声道重合成 → 采样域掩码拼接（区间外逐样本复制）→ 非有限值与长度校验 →
MP3 V0（无缝校验）→ 对成品**重新测量 F0**（按 60 秒分段存，供音高检索、单音指标、波形 F0 线；``pitch:`` 标签不依赖它）。
时间：条目里的音素与内区都是**输入局部秒**（外选区起点 = 0）。
"""

from __future__ import annotations

import json
import traceback
from pathlib import Path
from typing import Any

import numpy as np

from ..algo import flatten as fl
from ..core.errors import CoreError
from ..media import decode as dec
from ..media import mp3, wavfile
from ..models import f0store, fcpe, hifigan, registry
from ..models.onnx import Device, Session, create_session


def _session(model_id: str, rel: str, params: dict[str, Any], device: Device) -> Session:
    path, sha = registry.locate(model_id, rel, Path(params["models_dir"]), Path(params["support_dir"]))
    if not path.is_file():
        raise CoreError("model-file-missing", model=model_id, path=str(path))
    return create_session(model_id, path, sha, device)


def _target(it: dict[str, Any], frames: np.ndarray, intervals: list[tuple[float, float]]) -> fl.Target:
    t = it["target"]
    if t["method"] == "auto":
        return fl.auto_target(frames, intervals)
    if t["method"] == "edge":
        return fl.edge_target(frames, intervals, t["side"])
    return fl.parse_manual(t["manual"])


def flatten_one(it: dict[str, Any], fc: Session, voc: Session, out: Path, cache: Path) -> dict[str, Any]:
    f = it["file"]
    ref = dec.StreamRef(f["path"], int(f["ordinal"]), int(f["sample_rate"]), int(f["channels"]), f.get("codec"), f.get("format"))
    a, b = it["frames"]
    pcm = dec.decode_frames(ref, int(a), int(b), cache=cache)
    sr = ref.sample_rate
    n, ch = pcm.shape
    if ch > 2:
        raise CoreError("mp3-encode-failed", reason="too-many-channels", channels=ch)
    d = n / sr
    frames = fcpe.measure(fc, pcm, sr)
    mode = it["range"]
    vowels = None
    if mode in ("vowels", "first") and it.get("phones") is not None:
        vowels = fl.vowel_intervals([(p[0], p[1], p[2]) for p in it["phones"]], d, audio=pcm, sr=sr, manual=bool(it.get("manual")))
    inner = tuple(it["inner"]) if mode == "inner" else None
    trans = tuple(it.get("trans") or (fl.TRANSITION, fl.TRANSITION))
    intervals = fl.processing_intervals(mode, d, vowels=vowels, inner=inner, trans=trans)  # type: ignore[arg-type]
    if mode == "inner":
        inner = intervals[0]
    target = _target(it, frames, intervals)
    n44 = round(n * hifigan.SR / sr)
    t = hifigan.frame_count(n44)
    f0m = fl.assign_f0(hifigan.mel_times(t), frames, intervals, target.midi, inner=inner, trans=trans)  # type: ignore[arg-type]
    rendered = hifigan.render(voc, pcm, sr, f0m)
    mask = fl.splice_mask(n, sr, intervals, fade=mode != "whole")
    result = fl.splice(pcm, rendered, mask)
    out.mkdir(parents=True, exist_ok=True)
    wav = out / "out.wav"
    wavfile.save_wav_f32(wav, result, sr)
    manifest = mp3.encode_v0(wav, out / "out.mp3", frames=n, rate=sr, channels=ch)
    wav.unlink(missing_ok=True)
    # 成品重新测量 F0：解码实际的 MP3 文件（新测量以实际文件为准，13 §13.3.2），按 f0store 的 60 秒分段存
    rate = int(manifest["rate"])
    dur = manifest["frames"] / rate
    got = dec.decode_frames(dec.StreamRef(str(out / "out.mp3"), 0, rate, ch, "mp3", "mp3"), 0, int(manifest["frames"]), cache=cache)
    fr2 = fcpe.measure(fc, got, rate)
    total = f0store.total_frames(dur)
    if len(fr2) != total:
        raise CoreError("flatten-output-invalid", reason="frames", expected=total, got=len(fr2))
    chunks = []
    (out / "f0").mkdir(exist_ok=True)
    for k in range(0, max(1, -(-total // f0store.CHUNK_FRAMES))):
        np.save(out / "f0" / f"{k}.npy", fr2[k * f0store.CHUNK_FRAMES : (k + 1) * f0store.CHUNK_FRAMES].astype(np.float32))
        chunks.append(k)
    return {
        "mp3": str(out / "out.mp3"),
        "frames": int(manifest["frames"]),
        "rate": rate,
        "channels": ch,
        "manifest": manifest,
        "duration": dur,
        "inputFrames": n,
        "inputRate": sr,
        "target": target.wire(),
        "intervals": [[round(x, 6), round(y, 6)] for x, y in intervals],
        "inner": list(inner) if inner else None,
        "f0Chunks": chunks,
    }


def run(params: dict[str, Any], ctx: Any) -> dict[str, Any]:
    device = Device.of(ctx.device)
    items = params["items"]
    todo = [it for it in items if not it.get("error") and not it.get("reuse")]
    fc = voc = None
    if todo:
        fc = _session(fcpe.MODEL_ID, fcpe.MODEL_FILE, params, device)
        voc = _session(hifigan.MODEL_ID, hifigan.MODEL_FILE, params, device)
    out_dir = ctx.job_dir / "items"
    out_dir.mkdir(exist_ok=True)
    cache = ctx.job_dir / "cache"
    ok = failed = 0
    last_error: CoreError | None = None
    for i, it in enumerate(items):
        ctx.progress("flatten", i, len(items), "flatten-running")
        try:
            if it.get("error"):
                raise CoreError(it["error"]["code"], **it["error"].get("args", {}))
            if it.get("reuse"):
                res: dict[str, Any] = {"reuse": it["reuse"]}
            else:
                res = flatten_one(it, fc, voc, out_dir / str(it["idx"]), cache)  # type: ignore[arg-type]
            name = f"{it['idx']}.json"
            (out_dir / name).write_text(json.dumps(res, ensure_ascii=False), encoding="utf-8")
            ctx.emit({"type": "item", "idx": it["idx"], "status": "ok", "ref": name})
            ok += 1
        except CoreError as exc:
            last_error = exc
            ctx.emit({"type": "item", "idx": it["idx"], "status": "failed", "error": exc.to_wire()})
            failed += 1
        except Exception as exc:  # noqa: BLE001 — 一条出错不拖垮整批；原因写明
            traceback.print_exc()
            last_error = CoreError("job-exception", type=type(exc).__name__, message=str(exc))
            ctx.emit({"type": "item", "idx": it["idx"], "status": "failed", "error": last_error.to_wire()})
            failed += 1
    ctx.progress("flatten", len(items), len(items), "flatten-running")
    if len(items) == 1 and failed and last_error is not None:
        raise last_error  # 单个拉平：失败就是任务失败（不留任何登记）
    probes = [s.probe for s in (fc, voc) if s is not None and s.probe]
    return {"ok": ok, "failed": failed, "probes": probes}
