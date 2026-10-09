"""视频片段导出（规格 12 §12.5、16 R21.9、S7）：原声版时长与音频一致、画面 = 原片对应区间的最近帧；外部 MP4 视频晚开始 → 补黑帧并计数；
循环动画绑定按本地时间取模（S7.3）；没有画面报错（Q8）；同样的请求复用。"""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import numpy as np
import pytest

from ottosmasher.core import assets as assets_mod
from ottosmasher.core import visuals
from ottosmasher.core.edits import EditService
from ottosmasher.core.errors import CoreError
from ottosmasher.core.exports import ExportService
from ottosmasher.core.samples import SampleService
from ottosmasher.core.sources import SourceService
from ottosmasher.core.video_export import VideoExportService, run_job

pytestmark = pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="ffmpeg not on PATH")


class FakeJobs:
    def __init__(self) -> None:
        self.adopters: dict = {}
        self.submitted: list = []

    def submit(self, kind, params, affects=None):
        self.submitted.append((kind, params))
        return {"id": f"job{len(self.submitted)}", "kind": kind}


class Ctx:
    def progress(self, *a, **k):
        pass


def run(svc: VideoExportService, jobs: FakeJobs, started: dict) -> dict:
    """像调度器那样：任务进程里跑，再由 Core 登记。"""
    assert started["job"] is not None
    _kind, params = jobs.submitted[-1]
    res = run_job(params, Ctx())
    svc._adopt({"params": json.dumps(params)}, res)
    return {**params, **res}


def ffprobe(path: str) -> dict:
    out = subprocess.run(["ffprobe", "-v", "error", "-show_streams", "-show_format", "-of", "json", path], capture_output=True, check=True).stdout
    return json.loads(out)


def full(y: float) -> float:
    """有限范围的亮度（geq 写进去的 Y）→ 取出灰度图时的全范围值。"""
    return (y - 16) * 255 / 219


def frame(path: str, t: float, size=(64, 36)) -> np.ndarray:
    out = subprocess.run(["ffmpeg", "-v", "error", "-ss", f"{t:.4f}", "-i", path, "-frames:v", "1", "-vf", f"scale={size[0]}:{size[1]}", "-f", "rawvideo",
                          "-pix_fmt", "gray", "-"], capture_output=True, check=True).stdout
    return np.frombuffer(out, dtype=np.uint8).astype(np.float64)


@pytest.fixture
def env(db, ws, tmp_path):
    # 画面：每秒换一次灰度（0.5 秒处 = 第 0 秒的灰度），方便对帧；声音：正弦
    src = tmp_path / "Show 01.mkv"
    subprocess.run(["ffmpeg", "-v", "error", "-f", "lavfi", "-i", "color=c=black:s=64x36:r=24:d=6,geq=lum='min(255,floor(T)*40)':cb=128:cr=128",
                    "-f", "lavfi", "-i", "sine=f=330:sample_rate=48000:duration=6", "-c:v", "libx264", "-g", "1", "-c:a", "flac", str(src)], check=True)
    [r] = SourceService(db, workspace_root=ws.root).add([str(src)])
    aid = assets_mod.list_for_source(db, r["sourceId"])[0]["id"]
    jobs = FakeJobs()
    svc = VideoExportService(db, ws, ExportService(db, ws), handoff=None, jobs=jobs)
    return svc, jobs, aid, SampleService(db), r["sourceId"]


def test_original_clip_matches_source_and_reuses(env, db) -> None:
    svc, jobs, aid, samples, _src = env
    sid = samples.create(aid, 1.5, 4.0, name="やったー")["id"]
    started = svc.sample(sid, version="original", words={"video": "视频"})
    out = run(svc, jobs, started)
    assert out["black"] == 0 and out["frames"] == 60  # 2.5 秒 × 24 帧
    path = out["target"]
    assert path.endswith(".mp4") and "__视频" in Path(path).name or "视频" in Path(path).name
    info = ffprobe(path)
    kinds = {s["codec_type"]: s for s in info["streams"]}
    assert kinds["video"]["codec_name"] == "h264" and kinds["audio"]["codec_name"] == "aac"
    assert float(info["format"]["duration"]) == pytest.approx(2.5, abs=0.06)  # 时长 = 采样时长
    # 片段的第 0.6 秒 = 原片 2.1 秒（灰度 80），第 1.6 秒 = 原片 3.1 秒（灰度 120）
    assert frame(path, 0.6).mean() == pytest.approx(full(80), abs=4)
    assert frame(path, 1.6).mean() == pytest.approx(full(120), abs=4)
    # 同样的请求：复用，不再排任务
    again = svc.sample(sid, version="original", words={"video": "视频"})
    assert again["reused"] and again["path"] == path and len(jobs.submitted) == 1


def test_no_picture_is_an_error(db, ws, tmp_path) -> None:
    wav = tmp_path / "a.wav"
    subprocess.run(["ffmpeg", "-v", "error", "-f", "lavfi", "-i", "sine=d=2", str(wav)], check=True)
    [r] = SourceService(db, workspace_root=ws.root).add([str(wav)])
    aid = assets_mod.list_for_source(db, r["sourceId"])[0]["id"]
    sid = SampleService(db).create(aid, 0, 1, name="x")["id"]
    svc = VideoExportService(db, ws, ExportService(db, ws), handoff=None, jobs=FakeJobs())
    with pytest.raises(CoreError) as ei:
        svc.sample(sid)
    assert ei.value.code == "visual-none"  # Q8：不生成黑屏


def test_late_video_start_pads_black(db, ws, tmp_path) -> None:
    """S7.4 的模式：外部 MP4 视频从 0.125 秒开始、音频从 0 开始 → 以音频为主时钟，开头补黑帧并计数。"""
    mp4 = tmp_path / "late.mp4"
    subprocess.run(["ffmpeg", "-v", "error", "-f", "lavfi", "-i", "color=c=white:s=64x36:r=24:d=3", "-f", "lavfi", "-i", "sine=sample_rate=48000:d=3",
                    "-c:v", "libx264", "-c:a", "aac", str(mp4)], check=True)
    # 把视频流整体推后 0.125 秒（音频不动）
    late = tmp_path / "late2.mp4"
    subprocess.run(["ffmpeg", "-v", "error", "-itsoffset", "0.125", "-i", str(mp4), "-i", str(mp4), "-map", "0:v", "-map", "1:a", "-c", "copy", str(late)], check=True)
    [r] = SourceService(db, workspace_root=ws.root).add([str(late)])
    aid = assets_mod.list_for_source(db, r["sourceId"])[0]["id"]
    sid = SampleService(db).create(aid, 0.0, 1.0, name="千鹤")["id"]
    jobs = FakeJobs()
    svc = VideoExportService(db, ws, ExportService(db, ws), handoff=None, jobs=jobs)
    out = run(svc, jobs, svc.sample(sid))
    assert out["black"] in (3, 4)  # 0.125 秒 × 24 fps ≈ 3 帧
    assert frame(out["target"], 0.02).mean() < 20 and frame(out["target"], 0.5).mean() > 200


def test_loop_binding_takes_local_time_mod_duration(env, db, tmp_path) -> None:
    """S7.3：0.6 秒的循环动画，本地 1.45 秒 → 动画的 0.25 秒。"""
    svc, jobs, aid, samples, _src = env
    gif = tmp_path / "loop.mp4"
    # 0.6 秒：每 0.1 秒一个灰度（0.25 秒处 = 第 2 格 = 灰度 60）
    subprocess.run(["ffmpeg", "-v", "error", "-f", "lavfi", "-i", "color=c=black:s=64x36:r=10:d=0.6,geq=lum='floor(T*10+0.001)*30':cb=128:cr=128",
                    "-c:v", "libx264", "-g", "1", str(gif)], check=True)
    sid = samples.create(aid, 1.0, 3.0, name="ループ")["id"]
    vb = visuals.prepare(db, "sample", sid, str(gif), mode="loop")
    v = db.execute("SELECT version FROM sample WHERE id=?", (sid,)).fetchone()[0]
    EditService(db).apply({"ops": [{"entity": "sample", "id": sid, "version": v, "fields": {"visual_binding_id": vb}}]})
    out = run(svc, jobs, svc.sample(sid, audio=False))
    assert out["fps"] == pytest.approx(10)
    info = ffprobe(out["target"])
    assert [s["codec_type"] for s in info["streams"]] == ["video"]  # 不带声音
    # 输出 10 fps：第 14 帧（本地 1.4 秒）→ 1.4 mod 0.6 = 0.2 → 第 2 格（灰度 60）；1.45 秒本身落在两帧之间，按规则见 test_visuals
    assert frame(out["target"], 1.4).mean() == pytest.approx(full(60), abs=4)
    assert frame(out["target"], 0.5).mean() == pytest.approx(full(150), abs=4)
