"""采样库导入：规格 06 §6.6、ARCHITECTURE §4.10（文件夹、同名画面 视频 > 动图 > 图片、读不了的列出、已登记跳过）。"""

import threading
from pathlib import Path

from ottosmasher.core import effective_tags
from ottosmasher.core.imports import ImportService, scan
from ottosmasher.core.sources import SourceService
from ottosmasher.core.thumbnails import ThumbnailService
from test_sources import ff, media, needs_ffmpeg, wav  # noqa: F401 - fixture


class Jobs:
    def __init__(self, d: Path):
        self.adopters = {}
        self.jobs_dir = d
        self.submitted = []

    def submit(self, kind, params, affects=None):
        self.submitted.append((kind, params))
        return {"id": "job1"}


def pictures(d: Path):
    ff("-f", "lavfi", "-i", "testsrc=size=64x36:rate=1:duration=1", "-frames:v", "1", str(d / "a.png"))
    ff("-f", "lavfi", "-i", "testsrc=size=64x36:rate=24:duration=1", "-c:v", "libx264", str(d / "B.mp4"))  # 大小写不同也算同名
    ff("-f", "lavfi", "-i", "testsrc=size=64x36:rate=5:duration=1", str(d / "b.gif"))
    ff("-f", "lavfi", "-i", "sine=duration=1", str(d / "c.mp4"))  # 只有声音的同名“视频”：不算画面


def folder(media: Path) -> Path:  # noqa: F811
    d = media / "游戏 A"
    (d / "se" / "ui").mkdir(parents=True)
    wav(d / "a.wav", 0.5)
    ff("-f", "lavfi", "-i", "sine=duration=0.3", "-c:a", "libopus", str(d / "b.ogg"))
    wav(d / "c.wav", 0.2)
    wav(d / "se" / "ui" / "coin.wav", 0.65)
    wav(d / ".hidden.wav", 0.1)
    (d / "broken.wav").write_bytes(b"RIFF\x00\x00")
    (d / "readme.txt").write_text("x")
    pictures(d)
    return d


def service(db, ws):
    svc = SourceService(db, workspace_root=ws.root)
    jobs = Jobs(ws.root / "Jobs")
    return ImportService(db, ws, jobs, svc), svc


@needs_ffmpeg
def test_scan_preview_commit(db, ws, media):  # noqa: F811
    d = folder(media)
    imp, svc = service(db, ws)
    assert imp.scan([str(d)])["id"] == "job1"
    res = scan([str(d)], ws.root / "Jobs" / "job1" / "cache", lambda *_: None)
    names = [Path(x["path"]).name for x in res["items"]]
    assert names == ["a.wav", "b.ogg", "broken.wav", "c.wav", "coin.wav"]  # 隐藏文件、非音频跳过；按路径排序
    by = {Path(x["path"]).name: x for x in res["items"]}
    assert by["a.wav"]["picture"]["kind"] == "image"
    assert by["b.ogg"]["picture"]["kind"] == "video" and [Path(p).name for p in by["b.ogg"]["picture"]["conflicts"]] == ["b.gif"]
    assert by["c.wav"]["picture"] is None  # c.mp4 没有画面
    assert not by["broken.wav"]["ok"]
    imp._adopt_scan({"id": "job1"}, res)
    assert list((ws.data / "Cache" / "Peaks").glob("*.npz"))  # 峰值移进缓存

    pv = imp.preview("job1")
    assert (pv["total"], pv["importable"], pv["existing"], pv["withPicture"], pv["withoutPicture"]) == (5, 4, 0, 2, 2)
    assert [Path(x["path"]).name for x in pv["unreadable"]] == ["broken.wav"]
    assert [Path(x["path"]).name for x in pv["conflicts"]] == ["b.ogg"]

    out = imp.commit("job1", work="游戏 A", source_type="游戏", nature="unpitched", bind_pictures=True)
    assert (out["created"], out["skipped"], out["failed"]) == (4, 0, [])
    rows = db.execute(
        'SELECT s.name, s.nature, s.start, s."end", s.created_via, src.work, src.source_type, src.import_root, src.visual_binding_id'
        " FROM sample s JOIN sound_asset a ON a.id=s.asset_id JOIN source src ON src.id=a.source_id ORDER BY s.name"
    ).fetchall()
    assert [r["name"] for r in rows] == ["a", "b", "c", "coin"]
    assert all(r["nature"] == "unpitched" and r["start"] == 0 and r["created_via"] == "import" for r in rows)
    assert all(r["work"] == "游戏 A" and r["source_type"] == "游戏" and r["import_root"] == str(d) for r in rows)
    assert abs(rows[3]["end"] - 0.65) < 1e-6  # 整段（确切时长）
    assert [r["visual_binding_id"] is not None for r in rows] == [True, True, False, False]
    modes = [r[0] for r in db.execute("SELECT mode FROM visual_binding ORDER BY rowid")]
    assert modes == ["image", "sync"]
    # 继承标签 work:/type:（规格 05 §5.1）
    sid = out["sampleIds"][0]
    assert {t["tag"] for t in effective_tags.of_sample(db, sid)} >= {"work:游戏 A", "type:游戏"}

    # 同一文件夹再导入：已登记的跳过，不重复建采样
    imp._adopt_scan({"id": "job2"}, scan([str(d)], ws.root / "Jobs" / "job2" / "cache", lambda *_: None))
    assert imp.preview("job2")["existing"] == 4
    assert imp.commit("job2", work="", source_type="", nature="unclassified", bind_pictures=True)["skipped"] == 4
    assert db.execute("SELECT COUNT(*) FROM sample").fetchone()[0] == 4

    # 绑定的画面给缩略图（图片、同步视频）；没有画面的纯音频没有
    ev = threading.Event()
    th = ThumbnailService(db, ws, post=lambda fn: fn(), emit=lambda n, d_: ev.set())
    srcs = {r[1]: r[0] for r in db.execute("SELECT s.id, s.path FROM source s")}
    items = [{"kind": "source", "id": srcs[str(d / n)]} for n in ("a.wav", "b.ogg", "c.wav")]
    assert [r["state"] for r in th.get(items)] == ["pending", "pending", "none"]
    for _ in range(40):
        if [r["state"] for r in th.get(items)] == ["ready", "ready", "none"]:
            break
        ev.wait(0.5)
        ev.clear()
    assert [r["state"] for r in th.get(items)] == ["ready", "ready", "none"]
    poster = th.get([items[0] | {"size": "poster"}])
    assert poster[0]["state"] in ("pending", "ready")
    th.shutdown()


@needs_ffmpeg
def test_single_files_and_no_binding(db, ws, media):  # noqa: F811
    d = folder(media)
    imp, _ = service(db, ws)
    res = scan([str(d / "a.wav"), str(d / "gone.wav")], ws.root / "Jobs" / "j" / "cache", lambda *_: None)
    assert [x["ok"] for x in res["items"]] == [True, False]
    assert res["items"][0]["root"] == str(d) and res["items"][0]["picture"]["kind"] == "image"  # 单选的文件也找同文件夹的同名画面
    imp._adopt_scan({"id": "j"}, res)
    out = imp.commit("j", work="", source_type="", nature="speech", bind_pictures=False)
    assert out["created"] == 1
    assert db.execute("SELECT COUNT(*) FROM visual_binding").fetchone()[0] == 0
