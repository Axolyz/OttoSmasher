"""导出 WAV：规格 16 R21.1–R21.3、R21.6，12 §12.1。"""

import shutil
import subprocess
from pathlib import Path

import numpy as np
import pytest

from ottosmasher.core import assets as assets_mod
from ottosmasher.core import exports as exports_mod
from ottosmasher.core.errors import CoreError
from ottosmasher.core.exports import ExportService
from ottosmasher.core.sources import SourceService
from ottosmasher.media import wavfile

pytestmark = pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="ffmpeg not on PATH")
SR = 48000


def read_wav24(path: Path) -> tuple[np.ndarray, int, int]:
    raw = path.read_bytes()
    assert raw[:4] == b"RIFF" and raw[8:12] == b"WAVE"
    fmt_at = raw.index(b"fmt ")
    channels = int.from_bytes(raw[fmt_at + 10 : fmt_at + 12], "little")
    rate = int.from_bytes(raw[fmt_at + 12 : fmt_at + 16], "little")
    bits = int.from_bytes(raw[fmt_at + 22 : fmt_at + 24], "little")
    assert bits == 24
    d = raw.index(b"data")
    n = int.from_bytes(raw[d + 4 : d + 8], "little")
    b = np.frombuffer(raw[d + 8 : d + 8 + n], dtype=np.uint8).reshape(-1, 3)
    i = (b[:, 0].astype(np.int32) | (b[:, 1].astype(np.int32) << 8) | (b[:, 2].astype(np.int32) << 16))
    i = np.where(i >= 1 << 23, i - (1 << 24), i)
    return (i.astype(np.float64) / (1 << 23)).reshape(-1, channels), rate, channels


@pytest.fixture
def env(db, ws, tmp_path):
    n = SR * 3
    y = ((np.arange(n) % 40000) - 20000).astype(np.int16)
    raw = tmp_path / "r.s16"
    np.stack([y, -y - 1], axis=1).astype(np.int16).tofile(raw)
    src = tmp_path / "媒体 ♪" / "[Group] Title [05].mkv"
    src.parent.mkdir()
    subprocess.run(["ffmpeg", "-v", "error", "-f", "s16le", "-ar", str(SR), "-ac", "2", "-i", str(raw), "-c:a", "flac", str(src)], check=True)
    sources = SourceService(db, workspace_root=ws.root)
    [r] = sources.add([str(src)])
    asset = assets_mod.list_for_source(db, r["sourceId"])[0]
    return {"svc": ExportService(db, ws), "asset": asset["id"], "src": src, "y": y, "sources": sources, "sid": r["sourceId"]}


def export(env, start=0.123, end=0.456, **kw):
    return env["svc"].export_wav(env["asset"], start, end, content=kw.pop("content", "やったー · 片段"), track="原混音", **kw)


# R21.1 选区 0.123–0.456 → 24-bit WAV，等于原信号对应样本；在素材库导出目录；同请求复用同一文件；不新增采样/任务
def test_export_equals_original_and_reuses(env, db, ws):
    out = export(env)
    p = Path(out["path"])
    assert p.parent.parent == ws.library / "Exports"
    assert p.name.endswith(f"__{out['key'][:12]}.wav")
    assert "__原混音__[Group] Title [05]__" in p.name and "_00-00-00.123-00-00-00.456__" in p.name
    pcm, rate, ch = read_wav24(p)
    a, b = round(0.123 * SR), round(0.456 * SR)
    assert (rate, ch, len(pcm)) == (SR, 2, b - a)
    y = env["y"].astype(np.float64)
    assert np.max(np.abs(pcm[:, 0] - y[a:b] / 32768)) <= 2**-23
    assert np.max(np.abs(pcm[:, 1] - (-y[a:b] - 1) / 32768)) <= 2**-23
    again = export(env)
    assert again == {**out, "reused": True}
    assert db.execute("SELECT COUNT(*) FROM sample").fetchone()[0] == 0
    assert db.execute("SELECT COUNT(*) FROM job").fetchone()[0] == 0
    assert not list(ws.staging.iterdir())  # 暂存区不留东西
    assert not [f for f in p.parent.iterdir() if f.name.startswith(".")]  # 用户可见目录不留临时文件


# R21.2 已导出文件被改动后不复用（报“修改”）；越界或原片缺失报错
def test_modified_export_and_missing_source(env):
    p = Path(export(env)["path"])
    with open(p, "ab") as fh:
        fh.write(b"\x00")
    with pytest.raises(CoreError) as ei:
        export(env)
    assert ei.value.code == "export-modified"
    with pytest.raises(CoreError) as ei:
        export(env, 2.9, 3.1)
    assert ei.value.code == "range-invalid"
    env["src"].unlink()
    with pytest.raises(CoreError) as ei:
        export(env, 1.0, 1.5)
    assert ei.value.code == "asset-file-missing"


def test_one_frame_tolerance_at_end(env):
    out = export(env, 2.5, 3 + 1 / SR)
    pcm, _, _ = read_wav24(Path(out["path"]))
    assert len(pcm) == round(0.5 * SR)


# R21.6 显式导出目录优先，不覆盖已有同名文件
def test_explicit_directory_never_overwrites(env, tmp_path):
    d = tmp_path / "导出 [mine]"
    out = export(env, directory=str(d))
    assert Path(out["path"]).parent == d
    other = export(env, 1.0, 1.2, directory=str(d))
    name = Path(other["path"]).name
    # 别人放的同名文件（没有本应用记录）：报错，原样保留
    Path(other["path"]).unlink()
    env["svc"].conn.execute("DELETE FROM export_file WHERE stable_key=?", (other["key"],))
    (d / name).write_bytes(b"not ours")
    with pytest.raises(CoreError) as ei:
        export(env, 1.0, 1.2, directory=str(d))
    assert ei.value.code == "export-exists"
    assert (d / name).read_bytes() == b"not ours"


def test_source_changed_during_generation(env, monkeypatch):
    orig = exports_mod.dec.decode_frames

    def touch_then_decode(*a, **kw):
        with open(env["src"], "ab") as fh:
            fh.write(b"\x00")
        return orig(*a, **kw)

    monkeypatch.setattr(exports_mod.dec, "decode_frames", touch_then_decode)
    with pytest.raises(CoreError) as ei:
        export(env)
    assert ei.value.code == "source-changed"


def test_multichannel_header(tmp_path):
    pcm = (np.arange(30, dtype=np.float32).reshape(10, 3) - 15) / 16
    f = tmp_path / "m.wav"
    wavfile.save_wav24(f, pcm, 44100)
    back, rate, ch = read_wav24(f)
    assert (rate, ch) == (44100, 3) and np.array_equal(back, pcm)
    probe = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "stream=channels,bits_per_sample,codec_name", "-of", "csv=p=0", str(f)],
                           capture_output=True, text=True, check=True).stdout.strip()  # fmt: skip
    assert probe == "pcm_s24le,3,24"


def test_track_label():
    from ottosmasher.core.exports import track_label

    w = {"original": "原混音", "vocal": "人声", "sfx": "音效", "flatten": "拉平", "reimport": "回导"}
    assert track_label({"origin": "stream", "roles": []}, w) == "原混音"
    assert track_label({"origin": "stream", "roles": ["vocal"]}, w) == "人声"
    assert track_label({"origin": "separation", "roles": [], "stem_name": "Vocals"}, w) == "Vocals"  # 旧版缺陷：写成“音频”
    assert track_label({"origin": "separation", "roles": ["sfx"], "stem_name": "effects"}, w) == "音效"
    assert track_label({"origin": "separation", "roles": ["vocal", "sfx"]}, w) == "人声+音效"
    assert track_label({"origin": "flatten", "roles": ["vocal"]}, w) == "拉平"


def test_export_samples_reuses(env, db):
    from ottosmasher.core.exports import export_samples
    from ottosmasher.core.samples import SampleService

    smp = SampleService(db)
    a = smp.create(env["asset"], 0.5, 1.0, name="やったー")
    b = smp.create(env["asset"], 1.0, 1.25, name="えっ")
    w = {"original": "原混音"}
    paths = export_samples(env["svc"], [a["id"], b["id"], a["id"]], w)
    assert len(paths) == 2 and Path(paths[0]).name.startswith("やったー__原混音__")
    assert export_samples(env["svc"], [a["id"]], w) == paths[:1]  # 同请求复用
