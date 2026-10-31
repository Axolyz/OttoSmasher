"""（任务进程）原始能力（``core/primitives.py``）：只读文件、只算；逐条结果写进任务目录 ``items/<序号>.json``（音高另有 ``.npy``），不登记。"""

from __future__ import annotations

import json
import math
import traceback
from pathlib import Path
from typing import Any

from ..core.errors import CoreError
from ..domain.mapping import Mapping


def _wire(exc: BaseException) -> dict[str, Any]:
    return exc.to_wire() if isinstance(exc, CoreError) else {"code": "job-exception", "args": {"type": type(exc).__name__, "message": str(exc)}}


def _runtime(params: dict[str, Any], ctx: Any) -> Any:
    from ..lang.ja.runtime import JaRuntime
    from ..models.onnx import Device

    d = params["dictionary"]
    return JaRuntime(Path(params["models_dir"]), Path(params["support_dir"]), Device.of(ctx.device), Path(d["path"]) if d.get("path") else None, d["version"])


def _each(items: list[dict[str, Any]], ctx: Any, stage: str, code: str, fn: Any) -> dict[str, Any]:
    out_dir = ctx.job_dir / "items"
    out_dir.mkdir(exist_ok=True)
    ok = failed = 0
    for n, it in enumerate(items):
        ctx.progress(stage, n, len(items), code)
        try:
            res = fn(it, out_dir)
            (out_dir / f"{it['idx']}.json").write_text(json.dumps(res, ensure_ascii=False), encoding="utf-8")
            ctx.emit({"type": "item", "idx": it["idx"], "status": "ok", "ref": f"{it['idx']}.json"})
            ok += 1
        except Exception as exc:  # noqa: BLE001 — 一条出错不拖垮整批；原因写明
            if not isinstance(exc, CoreError):
                traceback.print_exc()
            ctx.emit({"type": "item", "idx": it["idx"], "status": "failed", "error": _wire(exc)})
            failed += 1
    ctx.progress(stage, len(items), len(items), code)
    return {"ok": ok, "failed": failed}


# ---------------------------------------------------------------- 读音分析


def text_analyze(params: dict[str, Any], ctx: Any) -> dict[str, Any]:
    rt = _runtime(params, ctx)

    def one(it: dict[str, Any], _d: Path) -> dict[str, Any]:
        r = rt.analyze(it["text"])
        return {"text": r.text, "normalized": r.normalized, "phonemes": r.phonemes, "morae": r.morae, "dictionary": params["dictionary"]["version"],
                "words": [{"text": w.text, "reading": w.reading, "start": w.start, "end": w.end, "morae": w.morae, "moraStart": w.mora_start, "mapped": w.mapped}
                          for w in r.words]}

    return _each(params["items"], ctx, "text", "text-analyzing", one)


# ---------------------------------------------------------------- 对齐


def speech_align(params: dict[str, Any], ctx: Any) -> dict[str, Any]:
    from ..models import domino, registry
    from ..models.onnx import Device, create_session
    from .speech import align_item

    rt = _runtime(params, ctx)
    path, sha = registry.locate(domino.MODEL_ID, domino.MODEL_FILE, Path(params["models_dir"]), Path(params["support_dir"]))
    if sha != params["versions"]["model"]["sha256"]:
        raise CoreError("model-sha-mismatch", model=domino.MODEL_ID, path=str(path), expected=params["versions"]["model"]["sha256"], got=sha)
    aligner = domino.Aligner(create_session(domino.MODEL_ID, path, sha, Device.of(ctx.device)))
    cache = ctx.job_dir / "cache"
    fronts: dict[str, Any] = {}

    def front(text: str) -> Any:
        if text not in fronts:
            fronts[text] = rt.analyze(text)
        return fronts[text]

    def one(it: dict[str, Any], _d: Path) -> dict[str, Any]:
        if it.get("lines"):
            fe, spans = join_lines(it["lines"], [front(t) for t in it["lines"]])
        else:
            fe, spans = front(it["text"]), None
        res = align_item(it, lambda _t: fe, aligner, cache=cache)
        return shape_alignment(it, fe, res, spans)

    return _each(params["items"], ctx, "align", "speech-aligning", one)


def join_lines(texts: list[str], fes: list[Any]) -> tuple[Any, list[tuple[str, int, int]]]:
    """几行的前端结果拼成一句：每行去掉首尾停顿，行与行之间一个 ``pau``（和 pydomino 的多句输入一样）；
    音拍、词的序号接着往下数。返回拼好的结果和每行在音素序列里的范围 ``(文字, 起, 止)``——拼好的序列首尾没有停顿，
    所以它和对齐结果的音素一一对应（不按音拍找：有的音素没有音拍序号，例如「イエ～イ」）。"""
    from dataclasses import replace

    from ..lang.ja.frontend import FrontendResult

    phonemes: list[str] = []
    pm: list[int | None] = []
    pw: list[int | None] = []
    words: list[Any] = []
    morae: list[str] = []
    mora_word: list[int] = []
    spans = []
    chars = 0
    for text, fe in zip(texts, fes):
        keep = list(range(len(fe.phonemes)))
        while keep and fe.phonemes[keep[0]] == "pau":
            keep.pop(0)
        while keep and fe.phonemes[keep[-1]] == "pau":
            keep.pop()
        if not keep:
            raise CoreError("frontend-failed", reason="no-phonemes", detail=text)
        if phonemes:
            phonemes.append("pau")
            pm.append(None)
            pw.append(None)
        m0, w0, p0 = len(morae), len(words), len(phonemes)
        for k in keep:
            phonemes.append(fe.phonemes[k])
            pm.append(None if fe.phoneme_mora[k] is None else fe.phoneme_mora[k] + m0)
            pw.append(None if fe.phoneme_word[k] is None else fe.phoneme_word[k] + w0)
        words += [replace(w, start=None if w.start is None else w.start + chars, end=None if w.end is None else w.end + chars, mora_start=w.mora_start + m0)
                  for w in fe.words]
        morae += fe.morae
        mora_word += [x + w0 for x in fe.mora_word]
        spans.append((text, p0, len(phonemes)))
        chars += len(text) + 1
    first = fes[0]
    joined = FrontendResult(text="\n".join(texts), normalized="\n".join(fe.normalized for fe in fes), phonemes=phonemes, phoneme_mora=pm,
                            phoneme_word=pw, words=words, morae=morae, mora_word=mora_word, versions=first.versions)
    return joined, spans


def shape_alignment(it: dict[str, Any], fe: Any, res: dict[str, Any], lines: list[tuple[str, int, int]] | None = None) -> dict[str, Any]:
    """align_item 的结果 → 对外的形状：音素、音拍与词的起止、整句起止、窗口两端的空白、最长音素；音轨输入再给原片秒。
    ``lines``（多行输入）：每行在音素序列里的范围 → 每行的起止。"""
    m = Mapping.of(it["mapping"]) if it.get("mapping") else None

    def span(text: str, s: float, e: float) -> dict[str, Any]:
        d = {"text": text, "start": round(s, 6), "end": round(e, 6)}
        if m is not None:
            d |= {"sourceStart": round(m.to_source(s), 6), "sourceEnd": round(m.to_source(e), 6)}
        return d

    phones = []
    for p in res["phones"]:
        d = {"label": p["label"], "start": p["start"], "end": p["end"], "mora": p.get("mora"), "word": p.get("word")}
        if m is not None:
            d |= {"sourceStart": round(m.to_source(p["start"]), 6), "sourceEnd": round(m.to_source(p["end"]), 6)}
        phones.append(d)

    def group(key: str, names: list[str]) -> list[dict[str, Any]]:
        out = []
        for k, name in enumerate(names):
            ps = [p for p in res["phones"] if p.get(key) == k]
            if ps:
                out.append(span(name, ps[0]["start"], ps[-1]["end"]))
        return out

    w0, w1 = it["window"]
    first, last = res["phones"][0], res["phones"][-1]
    longest = max(res["phones"], key=lambda p: p["end"] - p["start"])
    out = {
        "text": it["text"], "clock": it["clock"], "window": [round(w0, 6), round(w1, 6)], "phones": phones,
        "morae": group("mora", list(fe.morae)), "words": group("word", [w.text for w in fe.words]),
        "speech": span(it["text"], first["start"], last["end"]),
        "edges": {"lead": round(first["start"] - w0, 6), "tail": round(w1 - last["end"], 6)},
        "longestPhone": {"label": longest["label"], "seconds": round(longest["end"] - longest["start"], 6)},
    }
    if lines is not None:
        out["lines"] = []
        for text, a, b in lines:
            out["lines"].append(span(text, res["phones"][a]["start"], res["phones"][b - 1]["end"]))
    return out


# ---------------------------------------------------------------- 测音高


def f0_track(params: dict[str, Any], ctx: Any) -> dict[str, Any]:
    import numpy as np

    from ..media import decode as dec
    from ..models import fcpe, registry
    from ..models.onnx import Device, create_session

    path, sha = registry.locate(fcpe.MODEL_ID, fcpe.MODEL_FILE, Path(params["models_dir"]), Path(params["support_dir"]))
    session = create_session(fcpe.MODEL_ID, path, sha, Device.of(ctx.device))
    seg, context = fcpe.SEGMENT_FRAMES, fcpe.CONTEXT_FRAMES
    step = fcpe.HOP / fcpe.SR

    def one(it: dict[str, Any], d: Path) -> dict[str, Any]:
        f = it["file"]
        ref = dec.StreamRef(f["path"], int(f["ordinal"]), int(f["sample_rate"]), int(f["channels"]), f.get("codec"), f.get("format"))
        sr = ref.sample_rate
        a, b = (int(x) for x in it["frames"])
        n = max(1, math.ceil((b - a) / sr / step))
        out = np.zeros((n, 3), dtype=np.float32)
        hop = round(step * sr)  # 一帧的样本数（10 ms）
        for k in range(0, n, seg):
            frames = min(seg, n - k)
            ctx_frames = min(context, k)  # 区间开头之前不取上下文：只测给定的这一段
            s0 = a + (k - ctx_frames) * hop
            s1 = min(b, a + (k + frames + context) * hop)
            pcm = dec.decode_frames(ref, s0, s1, cache=ctx.job_dir / "cache")
            out[k : k + frames] = fcpe.measure_chunk(session, pcm, sr, ctx_frames, frames)
        np.save(d / f"{it['idx']}.npy", out)
        conf = out[:, 1]
        voiced = out[conf >= fcpe.RELIABLE_CONF, 0]
        med = float(np.median(voiced)) if voiced.size else None
        return {"clock": it["clock"], "t0": round(it["window"][0], 6), "step": step, "count": n,
                "summary": {"voicedRatio": round(float(voiced.size) / n, 4), "medianHz": round(med, 3) if med else None,
                            "medianNote": _note(med) if med else None}}

    return _each(params["items"], ctx, "f0", "speech-f0", one)


def _note(hz: float) -> str:
    midi = 69 + 12 * math.log2(hz / 440.0)
    k = round(midi)
    names = ("C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B")
    return f"{names[k % 12]}{k // 12 - 1}{int(round((midi - k) * 100)):+d}c"
