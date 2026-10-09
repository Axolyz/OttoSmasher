"""采样独立化与删除原片（规格 04 §4.8、§4.5、16 S12；ARCHITECTURE §4.9；L32）：无损切片与原存储逐样本相同、读到的分析继续可读、
删除原片后原片保留为“媒体已释放”（段与标签留着）、切片外报“原片媒体已释放”、其他采样与库内整轨删掉、原片文件不碰。"""

from __future__ import annotations

import json
import shutil
import subprocess

import numpy as np
import pytest

from ottosmasher.core import assets as assets_mod
from ottosmasher.core import visuals
from ottosmasher.core.errors import CoreError
from ottosmasher.core.independence import IndependenceService, run_job
from ottosmasher.media import decode as dec
from test_rhythm_service import align, core, sample  # noqa: F401 — 同一组合成素材

pytestmark = pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="ffmpeg not on PATH")


class FakeJobs:
    def __init__(self) -> None:
        self.adopters: dict = {}
        self.submitted: list = []

    def submit(self, kind, params, affects=None):
        self.submitted.append(params)
        return {"id": f"job{len(self.submitted)}"}


class Ctx:
    def progress(self, *a, **k):
        pass


def independ(core, ids, delete_source=None):  # noqa: F811
    svc = IndependenceService(core.conn, core.ws, FakeJobs(), core.sources)
    svc.submit(ids, delete_source)
    params = svc.jobs.submitted[-1]
    run_job(params, Ctx())
    svc._adopt({"id": "job", "params": json.dumps(params)}, {"n": len(params["items"])})
    return svc


def pcm(core, aid, a, b):  # noqa: F811
    asset = assets_mod.get(core.conn, aid)
    ref, win, _m = assets_mod.locate(core.conn, core.ws.root, asset, a, b)
    sr = ref.sample_rate
    return dec.decode_frames(ref, round(win.to_file(a) * sr), round(win.to_file(b) * sr), cache=core.ws.data / "Cache")


def test_independ_then_release_keeps_analysis(core):  # noqa: F811
    keep = sample(core, 2.0, 5.6, name="残す")
    align(core, keep)
    other = sample(core, 7.0, 8.0, name="消す")
    before = pcm(core, core.aid, 2.5, 3.5)
    view0 = core.speech.sample_view(keep)
    assert view0["head"] is not None
    plan = IndependenceService(core.conn, core.ws, FakeJobs(), core.sources).plan([keep])
    assert plan[0]["bytes"] > 0 and not plan[0]["picture"]  # wav 原片没有画面
    independ(core, [keep])
    row = core.samples.get(keep)
    assert row["detail"]["independent"]
    # 切片与原存储逐样本相同；原片还在时按主存储读（主存储优先）
    st = core.conn.execute("SELECT kind, range_start, range_end FROM asset_storage WHERE asset_id=? ORDER BY kind", (core.aid,)).fetchall()
    assert [r[0] for r in st] == ["materialized_slice", "primary"]
    # 删除原片（媒体已释放）
    src = core.conn.execute("SELECT source_id, path FROM sound_asset a JOIN source s ON s.id=a.source_id WHERE a.id=?", (core.aid,)).fetchone()
    out = core.sources.delete(src[0], release=True)
    assert out["released"] and out["keptSamples"] == 1
    assert core.conn.execute("SELECT media_state FROM source WHERE id=?", (src[0],)).fetchone()[0] == "released"
    assert core.conn.execute("SELECT COUNT(*) FROM sample WHERE id=?", (other,)).fetchone()[0] == 0  # 其他采样删掉
    assert core.conn.execute("SELECT COUNT(*) FROM text_segment WHERE source_id=?", (src[0],)).fetchone()[0] == 1  # 段留着
    import os

    assert os.path.isfile(src[1])  # 原片文件不碰
    after = pcm(core, core.aid, 2.5, 3.5)
    assert np.array_equal(before, after)  # 切片逐样本相同
    view1 = core.speech.sample_view(keep)
    assert view1["head"] is not None and view1["head"]["runId"] == view0["head"]["runId"]  # 读到的分析继续可读（L32）
    assert core.rhythm.view(keep)["blocks"]  # 节奏照常（只解码采样范围，在切片里）
    from ottosmasher.core import playback as playback_mod

    h = playback_mod.resolve_asset(core.conn, core.ws.root, core.aid, 2.5, 3.0)
    assert "/Independent/" in h["path"] and h["fileStart"] == pytest.approx(2.5 - st[0][1], abs=1e-6)
    with pytest.raises(CoreError) as ei:
        pcm(core, core.aid, 6.0, 6.5)  # 切片之外
    assert ei.value.code == "media-released"
    assert core.samples.get(keep)["media_state"] == "released"
    # 媒体已释放的原片再删除 = 全部删除
    core.sources.delete(src[0], release=True)
    assert core.conn.execute("SELECT COUNT(*) FROM source WHERE id=?", (src[0],)).fetchone()[0] == 0


def test_picture_clip_materialized_for_video_sources(core, tmp_path):  # noqa: F811
    mkv = tmp_path / "v.mkv"
    subprocess.run(["ffmpeg", "-v", "error", "-f", "lavfi", "-i", "testsrc=size=64x36:rate=24:duration=4", "-f", "lavfi", "-i", "sine=sample_rate=16000:duration=4",
                    "-c:v", "libx264", "-c:a", "flac", str(mkv)], check=True)
    r = core.sources.add([str(mkv)])[0]
    aid = r["assets"][0]["assetId"]
    sid = core.samples.create(aid, 1.0, 2.0, name="画")["id"]
    assert IndependenceService(core.conn, core.ws, FakeJobs(), core.sources).plan([sid])[0]["picture"]
    independ(core, [sid], delete_source=r["sourceId"])  # 独立化后接着删除原片
    b = visuals.resolve(core.conn, sample_id=sid, root=core.ws.root)
    assert (b["origin"], b["mode"], b["state"]) == ("sample", "materialized_clip", "ok")
    assert visuals.picture_time(b, 1.5, 0.5) == pytest.approx(0.5)  # 片段时间 = 原片秒 − 片段起点
    assert "/Independent/" in b["path"] and b["path"].endswith(".mp4")
    assert core.conn.execute("SELECT media_state FROM source WHERE id=?", (r["sourceId"],)).fetchone()[0] == "released"
    # 声音切片是 24 位整数 WAV（FLAC 源 = 无损）
    mf = core.conn.execute("SELECT m.path FROM asset_storage s JOIN media_file m ON m.id=s.media_file_id WHERE s.asset_id=?", (aid,)).fetchone()[0]
    assert mf.endswith(".wav")
