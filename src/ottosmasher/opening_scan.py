"""Bounded-memory visual reference matching; proposals require source review."""

import base64
import io
import json
import subprocess

import numpy as np
from PIL import Image

from .workspace import DATA, executable, identity, write_json

SIZE = (96, 54)


def reference(data):
    if not isinstance(data, str) or len(data) > 12_000_000:
        raise ValueError("参考图片过大（上限约 8 MB）")
    try:
        raw = base64.b64decode(data.split(",")[-1], validate=True)
        with Image.open(io.BytesIO(raw)) as im:
            if im.width * im.height > 24_000_000:
                raise ValueError("图片分辨率过大")
            im.load()
            a = np.array(im.convert("RGB").resize(SIZE), dtype=np.float32) / 255
    except Exception as e:
        raise ValueError("不能读取参考图片") from e
    if float(a.std()) < 0.045:
        raise ValueError("参考帧过于单色，无法可靠定位；请选择可辨识画面，并填写其距 OP/ED 开始的偏移")
    key = identity(raw.hex())
    path = DATA / "opening-references" / (key + ".png")
    path.parent.mkdir(parents=True, exist_ok=True)
    Image.fromarray((a * 255).astype(np.uint8)).save(path)
    return path


def score(frame, ref):
    # RGB appearance plus normalized luminance tolerates moderate compression changes.
    x = frame.astype(np.float32) / 255
    mse = float(np.mean((x - ref) ** 2))
    a = x.mean(axis=2).ravel()
    b = ref.mean(axis=2).ravel()
    a -= a.mean()
    b -= b.mean()
    corr = float(np.dot(a, b) / max(np.linalg.norm(a) * np.linalg.norm(b), 1e-8))
    return max(0.0, min(1.0, 0.55 * (1 - mse / 0.16) + 0.45 * corr))


def frames(path, start, end, fps=8):
    cmd = [
        executable("ffmpeg"),
        "-v",
        "error",
        "-nostdin",
        "-ss",
        str(start),
        "-i",
        str(path),
        "-t",
        str(end - start),
        "-an",
        "-sn",
        "-vf",
        f"fps={fps},scale={SIZE[0]}:{SIZE[1]}",
        "-pix_fmt",
        "rgb24",
        "-f",
        "rawvideo",
        "pipe:1",
    ]
    p = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    n = SIZE[0] * SIZE[1] * 3
    try:
        i = 0
        while True:
            b = p.stdout.read(n)
            if not b:
                break
            if len(b) != n:
                raise ValueError("视频解码帧不完整")
            yield start + i / fps, np.frombuffer(b, dtype=np.uint8).reshape(SIZE[1], SIZE[0], 3)
            i += 1
        error = p.stderr.read().decode(errors="replace")
        if p.wait():
            raise ValueError("视频解码失败：" + error[-500:])
    finally:
        if p.poll() is None:
            p.terminate()
            p.wait()
        p.stdout.close()
        p.stderr.close()


def match(path, ref, start, end, duration, offset=0, scan_fps=24):
    # Preserve native frame cadence: the reference can last only one frame.
    # Refine strong peaks; proposals still need review (VFR/edits/compression).
    peaks = []
    for t, f in frames(path, start, end, scan_fps):
        q = score(f, ref)
        if q < 0.60:
            continue
        if peaks and t - peaks[-1][0] < 1:
            if q > peaks[-1][1]:
                peaks[-1] = (t, q)
        else:
            peaks.append((t, q))
    chosen = []
    for t, q in sorted(peaks, key=lambda v: -v[1]):
        if any(abs(t - v[0]) < max(2, duration * 0.8) for v in chosen):
            continue
        chosen.append((t, q))
        if len(chosen) >= 3:
            break
    out = []
    for t, q in chosen:
        refined = max(
            ((at, score(f, ref)) for at, f in frames(path, max(start, t - 0.25), min(end, t + 0.25), 60)),
            key=lambda v: v[1],
            default=(t, q),
        )
        a = refined[0] - offset
        if a < 0:
            continue
        out.append(
            {
                "start": round(a, 4),
                "end": round(a + duration, 4),
                "reference_time": refined[0],
                "similarity": refined[1],
                "status": "proposal",
                "needs_review": True,
            }
        )
    return out


def run(db, p, jid):
    from .source_regions import media_fingerprint

    ref = np.array(Image.open(p["reference_path"]).convert("RGB"), dtype=np.float32) / 255
    duration = float(p["duration"])
    offset = float(p.get("reference_offset", 0))
    if not 0 < duration <= 900 or not 0 <= offset < duration:
        raise ValueError("OP/ED 长度或参考帧偏移无效")
    results = []
    failures = []
    timings = []
    for sid in dict.fromkeys(p["source_ids"]):
        s = db.execute("SELECT * FROM sources WHERE id=?", (sid,)).fetchone()
        if not s:
            raise ValueError("原片不存在")
        print("搜索参考帧：" + s["title"], flush=True)
        try:
            a = max(0, float(p.get("scan_start", 0)))
            b = min(s["duration"], float(p.get("scan_end") or s["duration"]))
            if a >= b:
                raise ValueError("扫描范围为空")
            video = next(
                (v for v in json.loads(s["metadata"])["streams"] if v["codec_type"] == "video"), None
            )
            if video is None:
                raise ValueError("此来源没有视频轨")
            rate = video.get("avg_frame_rate", "24/1").split("/")
            fps = float(rate[0]) / max(1, float(rate[1])) if len(rate) == 2 else float(rate[0])
            fps = fps if 0 < fps <= 120 else 24
            from .visual_index import match as indexed_match
            hits, timing = indexed_match(s["path"], ref, a, b, duration, offset)
            timings.append({"source_id": sid, **timing})
            results.extend(
                {
                    **h,
                    "source_id": sid,
                    "title": s["title"],
                    "source_fingerprint": media_fingerprint(db, sid),
                    "kind": p.get("kind", "op"),
                }
                for h in hits
                if h["end"] <= s["duration"]
            )
            if not hits:
                failures.append(
                    {"source_id": sid, "title": s["title"], "reason": "没有足够相似的帧；不自动标记"}
                )
        except Exception as e:  # noqa: BLE001 - preserve per-source failure in scan report
            failures.append({"source_id": sid, "title": s["title"], "reason": str(e)})
    result = {
        "id": jid,
        "type": "opening-proposals",
        "candidates": results,
        "failures": failures,
        "parameters": p,
        "timings": timings,
    }
    write_json(DATA / "opening-scans" / (jid + ".json"), result)
    return result
