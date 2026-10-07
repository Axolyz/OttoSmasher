"""测试用的伪 PyMSS Studio（只用标准库）：按 14 §14.6 的布局与事件格式模仿 0.0.18 的 worker.py。

- 安装目录 ``<tmp>/Fake Studio.app/Contents/Resources/python/worker.py``，``Info.plist`` 版本 9.9.9；
- 数据目录 ``<tmp>/data``：``runtime-envs/active-runtime.json``（pythonPath = 当前解释器）、``models/`` 下两个模型：
  ``fake_vocals``（声部 Vocals|Instrumental，别名 fake_vocals.ckpt）、``fake_3track``（speech|music|effects）；还有一个没下载完的模型；
- ``infer``：读 16/24 位 PCM WAV，按声部写浮点 WAV（Vocals = 原样，其余 = 半幅反相），输出布局 ``<output>/<输入名>/<输入名>_<stem>.wav``；
- 故障模式（数据目录里的 ``mode.txt``）：``short``（输出少 10 帧）、``missing``（少一个声部）、``error``（发 error 事件但退出码 0）、
  ``exit1``（退出码 1）、``slow``（推理中睡 60 秒，测取消）、``touch``（推理中改动模型文件 → 指纹前后不一致）、``outside``（输出路径在输出目录外）。
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

WORKER = r'''
import json, os, struct, sys, time, wave
from pathlib import Path

DATA = Path(os.environ["PYMSS_STUDIO_DATA_ROOT"])
MODE = (DATA / "mode.txt").read_text().strip() if (DATA / "mode.txt").exists() else "ok"
MODELS = Path(os.environ["PYMSS_MODEL_DIR"])


def emit(kind, payload=None, task=None):
    sys.stdout.write(json.dumps({"type": kind, "requestId": "r", "taskId": task, "timestamp": time.time(), "payload": payload or {}}) + "\n")
    sys.stdout.flush()


def models():
    return [
        {"name": "fake_vocals", "aliases": ["fake_vocals.ckpt"], "configInstruments": "Vocals|Instrumental", "downloaded": True,
         "modelPath": str(MODELS / "fake_vocals.ckpt"), "configPath": str(MODELS / "fake_vocals.yaml"), "auxiliaryPaths": []},
        {"name": "fake_3track", "aliases": [], "configInstruments": "speech|music|effects", "downloaded": True,
         "modelPath": str(MODELS / "fake_3track.ckpt"), "configPath": None},
        {"name": "half_downloaded", "aliases": [], "targetStem": "vocals", "downloaded": False},
        {"name": "unsupported", "aliases": [], "targetStem": "vocals", "downloaded": True, "supported": False},
    ]


def read_pcm(path):
    with wave.open(str(path), "rb") as w:
        ch, sw, sr, n = w.getnchannels(), w.getsampwidth(), w.getframerate(), w.getnframes()
        raw = w.readframes(n)
    vals = []
    for i in range(0, len(raw), sw):
        b = raw[i:i + sw]
        if sw == 2:
            v = struct.unpack("<h", b)[0] / 32768.0
        else:
            v = int.from_bytes(b + (b"\xff" if b[2] & 0x80 else b"\x00"), "little", signed=True) / 8388608.0
        vals.append(v)
    return vals, ch, sr


def write_float(path, vals, ch, sr):
    data = struct.pack("<%df" % len(vals), *vals)
    fmt = struct.pack("<HHIIHH", 3, ch, sr, sr * ch * 4, ch * 4, 32)
    with open(path, "wb") as f:
        f.write(b"RIFF" + struct.pack("<I", 4 + 8 + len(fmt) + 8 + len(data)) + b"WAVE")
        f.write(b"fmt " + struct.pack("<I", len(fmt)) + fmt + b"data" + struct.pack("<I", len(data)) + data)


cmd = sys.argv[1]
payload = json.loads(Path(sys.argv[sys.argv.index("--payload") + 1]).read_text(encoding="utf-8"))
if cmd == "list_models":
    emit("models", {"models": models()})
    sys.exit(0)
if cmd != "infer":
    sys.exit(2)
assert payload["download"] is False
model = next(m for m in models() if m["name"] == payload["model"] or payload["model"] in m["aliases"])
stems = payload.get("selectedStems") or model["configInstruments"].split("|")
if MODE == "exit1":
    sys.stderr.write("boom\n")
    sys.exit(1)
out_root = Path(payload["output"])
for task in payload["tasks"]:
    tid = task["taskId"]
    emit("task_started", {}, tid)
    if MODE == "error":
        emit("error", {"code": "INFERENCE_FAILED", "message": "fake failure", "recoverable": False}, tid)
        continue
    if MODE == "slow":
        (DATA / "studio-pid.txt").write_text(str(os.getpid()))
        time.sleep(60)
    vals, ch, sr = read_pcm(task["input"])
    emit("task_stage", {"stage": "separating"}, tid)
    stem_name = Path(task["input"]).stem
    d = out_root / stem_name if MODE != "outside" else out_root.parent / "elsewhere"
    d.mkdir(parents=True, exist_ok=True)
    outputs = []
    use = stems[:-1] if MODE == "missing" else stems
    for i, st in enumerate(use):
        emit("task_progress", {"stage": "separating", "done": i, "total": len(use)}, tid)
        x = vals if st.lower() in ("vocals", "speech") else [-0.5 * v for v in vals]
        if MODE == "short":
            x = x[: max(0, len(x) - 10 * ch)]
        p = d / f"{stem_name}_{st}.wav"
        write_float(p, x, ch, sr)
        outputs.append({"path": str(p), "stem": st})
    if MODE == "touch":
        with open(model["modelPath"], "ab") as f:
            f.write(b"changed")
    emit("task_done", {"files": [o["path"] for o in outputs], "outputs": outputs, "outputDir": str(d), "outputFormat": "wav"}, tid)
'''


def make_fake_studio(root: Path, mode: str = "ok") -> tuple[str, str]:
    app = root / "Fake Studio.app"
    res = app / "Contents" / "Resources"
    (res / "python").mkdir(parents=True, exist_ok=True)
    (res / "python" / "worker.py").write_text(WORKER, encoding="utf-8")
    (app / "Contents" / "Info.plist").write_text(
        '<?xml version="1.0" encoding="UTF-8"?><plist version="1.0"><dict><key>CFBundleShortVersionString</key><string>9.9.9</string></dict></plist>',
        encoding="utf-8",
    )
    data = root / "data"
    (data / "runtime-envs").mkdir(parents=True, exist_ok=True)
    (data / "runtime-envs" / "active-runtime.json").write_text(json.dumps({"backend": "fake", "pythonPath": sys.executable}), encoding="utf-8")
    models = data / "models"
    models.mkdir(exist_ok=True)
    for f in ("fake_vocals.ckpt", "fake_vocals.yaml", "fake_3track.ckpt"):
        (models / f).write_bytes(f.encode() * 100)
    (data / "mode.txt").write_text(mode)
    return str(app), str(data)
