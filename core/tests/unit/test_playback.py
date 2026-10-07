"""播放句柄：规格 16 R22.1–R22.3、R22.5。"""

import shutil

import pytest

from ottosmasher.core import assets as assets_mod
from ottosmasher.core import playback
from ottosmasher.core.errors import CoreError
from ottosmasher.core.sources import SourceService
from test_sources import two_audio_mkv, wav

pytestmark = pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="ffmpeg not on PATH")


@pytest.fixture
def mkv(db, ws, tmp_path):
    f = two_audio_mkv(tmp_path / "v [x].mkv")
    [r] = SourceService(db, workspace_root=ws.root).add([str(f)])
    return f, r["sourceId"]


# R22.2 内嵌音轨按“第几条音频流”选择（视频是容器流 0，音频是 1、2 → aid 1、2）
def test_source_handle_uses_audio_ordinal(db, mkv):
    f, sid = mkv
    h = playback.resolve_source(db, sid)
    assert h == {
        "path": str(f), "aid": 2, "duration": pytest.approx(2.5), "hasVideo": True,
        "audioFile": None, "audioDelay": 0.0, "coverage": [0.0, pytest.approx(2.5)],
    }  # 默认 = 日语那条 = 第 2 条；容器音轨没有外挂音轨  # fmt: skip
    assert playback.resolve_source(db, sid, 0)["aid"] == 1
    with pytest.raises(CoreError) as ei:
        playback.resolve_source(db, sid, 5)
    assert ei.value.code == "stream-not-found"


def test_source_handle_refuses_changed_or_missing_file(db, mkv):
    f, sid = mkv
    with open(f, "ab") as fh:
        fh.write(b"\x00")
    with pytest.raises(CoreError) as ei:
        playback.resolve_source(db, sid)
    assert ei.value.code == "source-changed"


# R22.3 / R22.5 试听直接读绑定的区间，终点以文件秒交给引擎；缺失报错不换轨
def test_asset_handle(db, ws, mkv, tmp_path):
    f, sid = mkv
    a = assets_mod.list_for_source(db, sid)[1]
    h = playback.resolve_asset(db, ws.root, a["id"], 0.5, 1.25)
    assert h == {"path": str(f), "aid": 2, "fileStart": 0.5, "fileEnd": 1.25, "localStart": 0.5, "localEnd": 1.25}
    with pytest.raises(CoreError):
        playback.resolve_asset(db, ws.root, a["id"], 2.0, 3.0)
    f.unlink()
    with pytest.raises(CoreError) as ei:
        playback.resolve_asset(db, ws.root, a["id"], 0.5, 1.0)
    assert ei.value.code == "asset-file-missing"


def test_audio_only_source_has_no_video(db, ws, tmp_path):
    [r] = SourceService(db, workspace_root=ws.root).add([str(wav(tmp_path / "a.wav"))])
    assert playback.resolve_source(db, r["sourceId"])["hasVideo"] is False


def test_hang_offset_and_external_stem(db, ws, tmp_path):
    """R22.1：外挂分离轨按偏移挂到原片（原片 103–123、声部局部 3–23 → 音频延迟 100）；变速的不能挂。"""
    assert playback.hang_offset([[3.0, 103.0], [23.0, 123.0]]) == 100.0
    assert playback.hang_offset([[0.0, 0.0], [10.0, 20.0]]) is None
