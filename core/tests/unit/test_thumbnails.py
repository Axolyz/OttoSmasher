"""列表缩略图：规格 16 R22.11（中点帧经分段映射、缓存、无视频无缩略图）、ARCHITECTURE §10.2。"""

import threading

from conftest import make_sample
from ottosmasher.core.clock import new_id, now_iso
from ottosmasher.core.sources import SourceService
from ottosmasher.core.thumbnails import ThumbnailService
from test_sources import media, mp3_with_cover, needs_ffmpeg, two_audio_mkv, wav  # noqa: F401 - fixture

JPEG = b"\xff\xd8\xff"


class Events:
    def __init__(self):
        self.items = []
        self.cv = threading.Condition()

    def emit(self, name, data):
        assert name == "thumbs.ready"
        with self.cv:
            self.items.extend(data["items"])
            self.cv.notify_all()

    def wait(self, n):
        with self.cv:
            assert self.cv.wait_for(lambda: len(self.items) >= n, timeout=20)


def service(db, ws):
    ev = Events()
    return ThumbnailService(db, ws, post=lambda fn: fn(), emit=ev.emit), ev


def stream_asset(db, sid):
    return db.execute("SELECT id FROM sound_asset WHERE source_id=? AND origin='stream' ORDER BY stream_ordinal LIMIT 1", (sid,)).fetchone()[0]


@needs_ffmpeg
def test_source_and_sample_thumbs(db, ws, media):  # noqa: F811
    svc = SourceService(db, workspace_root=ws.root)
    res = svc.add([str(two_audio_mkv(media / "v [1].mkv")), str(mp3_with_cover(media / "c.mp3")), str(wav(media / "a.wav"))])
    vid, cover, audio = (r["sourceId"] for r in res)
    smp = make_sample(db, stream_asset(db, vid))
    th, ev = service(db, ws)
    items = [{"kind": "source", "id": vid}, {"kind": "sample", "id": smp}, {"kind": "source", "id": cover}, {"kind": "source", "id": audio}]
    first = th.get(items)
    # 封面图不算视频、纯音频没有缩略图（不生成占位图）
    assert [r["state"] for r in first] == ["pending", "pending", "none", "none"]
    ev.wait(2)
    second = th.get(items)
    assert [r["state"] for r in second] == ["ready", "ready", "none", "none"]
    assert all(r["data"].startswith(JPEG) for r in second[:2])
    assert len(list((ws.data / "Cache" / "Thumbs").rglob("*.jpg"))) == 2  # 缓存
    # 媒体已释放 → 没有缩略图
    db.execute("UPDATE source SET media_state='released' WHERE id=?", (vid,))
    assert th.get(items[:1])[0]["state"] == "none"
    th.shutdown()


@needs_ffmpeg
def test_failure_is_remembered(db, ws, media):  # noqa: F811
    svc = SourceService(db, workspace_root=ws.root)
    vid = svc.add([str(two_audio_mkv(media / "v.mkv"))])[0]["sourceId"]
    (media / "v.mkv").write_bytes(b"\x00" * 64)  # 文件坏了：取帧失败
    th, ev = service(db, ws)
    assert th.get([{"kind": "source", "id": vid}])[0]["state"] == "pending"
    ev.wait(1)
    assert th.get([{"kind": "source", "id": vid}])[0]["state"] == "failed"
    th.shutdown()


@needs_ffmpeg
def test_sample_time_goes_through_mapping(db, ws, media):  # noqa: F811
    svc = SourceService(db, workspace_root=ws.root)
    vid = svc.add([str(two_audio_mkv(media / "v.mkv", seconds=2.0))])[0]["sourceId"]
    # 变速资产：局部 0–1 秒对应原片 0.2–0.4 秒，局部 1–2 秒对应原片 0.4–1.8 秒
    aid = new_id()
    db.execute(
        "INSERT INTO sound_asset(id, source_id, origin, duration, mapping, created_at) VALUES (?, ?, 'flatten', 2.0, '[[0,0.2],[1,0.4],[2,1.8]]', ?)",
        (aid, vid, now_iso()),
    )
    smp = make_sample(db, aid)  # 局部 1.0–2.0，中点 1.5 → 原片 1.1
    th, _ = service(db, ws)
    assert abs(th._target("sample", smp)[2] - 1.1) < 1e-9
    assert abs(th._target("source", vid)[2] - 1.0) < 1e-9  # 整片中点
    th.shutdown()
