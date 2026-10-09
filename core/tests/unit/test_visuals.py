"""画面绑定（规格 12 §12.4、16 S7.3）：优先级、三种模式的画面时间、编辑通道挂上 / 撤销、文件改过报错、同名匹配。"""

from __future__ import annotations

import math
import os
import subprocess

import pytest

from conftest import make_source
from ottosmasher.core import visuals
from ottosmasher.core.edits import EditService
from ottosmasher.core.errors import CoreError
from ottosmasher.core.samples import SampleService
from test_tracks import asset


@pytest.fixture
def media(tmp_path):
    png = tmp_path / "ep.png"
    gif = tmp_path / "loop.gif"
    subprocess.run(["ffmpeg", "-v", "error", "-f", "lavfi", "-i", "color=c=red:s=64x36:d=0.1", "-frames:v", "1", str(png)], check=True)
    # 0.6 秒的循环动画（S7.3）
    subprocess.run(["ffmpeg", "-v", "error", "-f", "lavfi", "-i", "testsrc=s=64x36:r=10:d=0.6", str(gif)], check=True)
    return png, gif


def test_priority_modes_and_undo(db, media) -> None:
    png, gif = media
    src = make_source(db, path=str(png.with_name("ep.wav")))
    db.execute("UPDATE source SET duration=100.0 WHERE id=?", (src,))
    a = asset(db, src)
    svc, edits = SampleService(db), EditService(db)
    s1 = svc.create(a, 10, 12, name="一")["id"]
    assert visuals.resolve(db, sample_id=s1) is None  # 没有视频流也没有绑定：无画面
    # 原片绑定图片 → 采样继承；采样自己绑定循环动画 → 盖过原片
    vb = visuals.prepare(db, "source", src, str(png))
    edits.apply({"ops": [{"entity": "source", "id": src, "version": 1, "fields": {"visual_binding_id": vb}}]})
    b = visuals.resolve(db, sample_id=s1)
    assert (b["origin"], b["mode"], b["state"]) == ("source", "image", "ok")
    lb = visuals.prepare(db, "sample", s1, str(gif))
    v = db.execute("SELECT version FROM sample WHERE id=?", (s1,)).fetchone()[0]
    edits.apply({"label": {"code": "visual-bind", "args": {"name": "一"}}, "ops": [{"entity": "sample", "id": s1, "version": v, "fields": {"visual_binding_id": lb}}]})
    b = visuals.resolve(db, sample_id=s1)
    assert (b["origin"], b["mode"]) == ("sample", "loop") and b["duration"] == pytest.approx(0.6, abs=0.02)
    # S7.3：0.6 秒的循环，本地 1.45 秒 → 动画的 0.25 秒；图片永远第一帧；同步 = 原片秒 + 偏移
    assert visuals.picture_time(b, 11.45, 1.45) == pytest.approx(0.25)
    assert visuals.picture_time({"mode": "image"}, 5, 5) == 0.0
    assert visuals.picture_time({"mode": "sync", "offset": 0.125}, 12.5, 0.0) == pytest.approx(12.625)
    assert math.isnan(visuals.picture_time({"mode": "sync", "offset": 0}, None, 0.0))
    # 撤销 → 回到原片的图片
    edits.undo()
    assert visuals.resolve(db, sample_id=s1)["origin"] == "source"
    # 别的采样的绑定不能挂过来
    s2 = svc.create(a, 20, 21, name="二")["id"]
    with pytest.raises(CoreError):
        edits.apply({"ops": [{"entity": "sample", "id": s2, "version": 1, "fields": {"visual_binding_id": lb}}]})
    # 绑定文件改过 → 状态 changed（播放 / 导出报错，不换别的）
    os.utime(png, ns=(1, 1))
    assert visuals.resolve(db, sample_id=s1)["state"] == "changed"
    with pytest.raises(CoreError) as ei:
        visuals.check_ok(visuals.resolve(db, sample_id=s1))
    assert ei.value.code == "visual-changed"


def test_prepare_rejects_and_match_same_name(db, media, tmp_path) -> None:
    png, gif = media
    src = make_source(db, path=str(tmp_path / "ep.wav"))
    with pytest.raises(CoreError):
        visuals.prepare(db, "source", src, str(png), mode="loop")  # 图片不能循环
    with pytest.raises(CoreError):
        visuals.prepare(db, "source", src, str(tmp_path / "nope.png"))
    plan = visuals.match_plan(db, [src])
    assert plan[0]["picture"] == str(png) and plan[0]["kind"] == "image"
