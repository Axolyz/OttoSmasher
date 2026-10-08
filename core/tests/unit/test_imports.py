"""采样库导入：规格 06 §6.6、ARCHITECTURE §4.10（文件夹、同名画面 视频 > 动图 > 图片、读不了的列出、已登记跳过）。"""

import threading

import pytest
from pathlib import Path

from ottosmasher.core import effective_tags
from ottosmasher.core.errors import CoreError
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
    # 没有同名音频的视频：单独导入成原片（所有者 2026-10-07：文件夹导入兼顾视频）
    ff("-f", "lavfi", "-i", "testsrc=size=64x36:rate=24:duration=1", "-f", "lavfi", "-i", "sine=duration=1", "-c:v", "libx264", "-shortest", str(d / "se" / "clip.mp4"))
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
    # 隐藏文件、非媒体跳过；与音频同名的视频（B.mp4、c.mp4）是画面不单独导入；按路径排序
    assert names == ["a.wav", "b.ogg", "broken.wav", "c.wav", "clip.mp4", "coin.wav"]
    by = {Path(x["path"]).name: x for x in res["items"]}
    assert by["a.wav"]["picture"]["kind"] == "image"
    assert by["b.ogg"]["picture"]["kind"] == "video" and [Path(p).name for p in by["b.ogg"]["picture"]["conflicts"]] == ["b.gif"]
    assert by["c.wav"]["picture"] is None  # c.mp4 没有画面
    assert not by["broken.wav"]["ok"]
    imp._adopt_scan({"id": "job1"}, res)
    assert list((ws.data / "Cache" / "Peaks").glob("*.npz"))  # 峰值移进缓存

    pv = imp.preview("job1")
    assert by["clip.mp4"]["video"] and by["clip.mp4"]["picture"] is None
    assert (pv["total"], pv["importable"], pv["videos"], pv["existing"], pv["withPicture"], pv["withoutPicture"]) == (6, 5, 1, 0, 2, 3)
    assert [Path(x["path"]).name for x in pv["unreadable"]] == ["broken.wav"]
    assert [Path(x["path"]).name for x in pv["conflicts"]] == ["b.ogg"]

    out = imp.commit("job1", work="游戏 A", source_type="游戏", whole_sample=True, nature="unpitched", bind_pictures=True)
    assert (out["created"], out["existing"], out["failed"], len(out["sourceIds"]), len(out["sampleIds"])) == (5, 0, [], 5, 5)
    rows = db.execute(
        'SELECT s.name, s.nature, s.start, s."end", s.created_via, src.work, src.source_type, src.import_root, src.visual_binding_id'
        " FROM sample s JOIN sound_asset a ON a.id=s.asset_id JOIN source src ON src.id=a.source_id ORDER BY s.name"
    ).fetchall()
    assert [r["name"] for r in rows] == ["a", "b", "c", "clip", "coin"]
    assert all(r["nature"] == "unpitched" and r["start"] == 0 and r["created_via"] == "import" for r in rows)
    assert all(r["work"] == "游戏 A" and r["source_type"] == "游戏" and r["import_root"] == str(d) for r in rows)
    assert abs(rows[4]["end"] - 0.65) < 1e-6  # 整段（确切时长）
    assert [r["visual_binding_id"] is not None for r in rows] == [True, True, False, False, False]
    modes = [r[0] for r in db.execute("SELECT mode FROM visual_binding ORDER BY rowid")]
    assert modes == ["image", "sync"]
    # 继承标签 work:/type:（规格 05 §5.1）
    sid = out["sampleIds"][0]
    assert {t["tag"] for t in effective_tags.of_sample(db, sid)} >= {"work:游戏 A", "type:游戏"}

    # 同一文件夹再导入（所有者 2026-10-07 允许）：原片不重复登记、属性不改，勾了全长采样就再建整段采样
    imp._adopt_scan({"id": "job2"}, scan([str(d)], ws.root / "Jobs" / "job2" / "cache", lambda *_: None))
    assert imp.preview("job2")["existing"] == 5
    again = imp.commit("job2", work="别的", source_type="", whole_sample=True, nature="unclassified", bind_pictures=True)
    assert (again["created"], again["existing"], len(again["sampleIds"])) == (0, 5, 5)
    assert db.execute("SELECT COUNT(*) FROM sample").fetchone()[0] == 10
    assert db.execute("SELECT COUNT(*) FROM source").fetchone()[0] == 5
    assert {r[0] for r in db.execute("SELECT work FROM source")} == {"游戏 A"}

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
    out = imp.commit("j", work="", source_type="", whole_sample=True, nature="speech", bind_pictures=False)
    assert out["created"] == 1
    assert db.execute("SELECT COUNT(*) FROM visual_binding").fetchone()[0] == 0


@needs_ffmpeg
def test_import_without_whole_sample_then_whole_samples(db, ws, media):  # noqa: F811
    """原片页的导入（默认不勾全长采样）只登记原片；之后「建立全长采样…」可以补（所有者 2026-10-07）。"""
    d = folder(media)
    imp, _ = service(db, ws)
    imp._adopt_scan({"id": "j"}, scan([str(d / "a.wav"), str(d / "c.wav")], ws.root / "Jobs" / "j" / "cache", lambda *_: None))
    out = imp.commit("j", work="", source_type="", whole_sample=False, nature="ignored", bind_pictures=True)
    assert (out["created"], out["sampleIds"]) == (2, [])
    assert db.execute("SELECT COUNT(*) FROM sample").fetchone()[0] == 0
    a, c = out["sourceIds"]
    # 角色预填：给 a 的默认音轨加人声角色 → 语音；c 没有角色 → 未分类
    aid = db.execute("SELECT id FROM sound_asset WHERE source_id=? AND origin='stream'", (a,)).fetchone()[0]
    db.execute("INSERT INTO asset_role(asset_id, role, state) VALUES (?, 'vocal', 'on')", (aid,))
    r = imp.whole_samples([a, c], None)
    got = {row[0]: (row[1], row[2], row[3]) for row in db.execute('SELECT a.source_id, s.nature, s.start, s.created_via FROM sample s JOIN sound_asset a ON a.id=s.asset_id')}
    assert (got[a][0], got[c][0], got[a][1], got[a][2]) == ("speech", "unclassified", 0.0, "manual")
    assert len(r["sampleIds"]) == 2
    imp.whole_samples([c], "pitched")  # 每次都新建
    assert db.execute("SELECT COUNT(*) FROM sample").fetchone()[0] == 3
    with pytest.raises(CoreError):
        imp.whole_samples([c, "nope"], None)  # 整批回滚
    assert db.execute("SELECT COUNT(*) FROM sample").fetchone()[0] == 3


@needs_ffmpeg
def test_work_modes_and_grouping_preview(db, ws, media):  # noqa: F811
    """作品二选一（所有者 2026-10-07）：统一设为（预填推断出的同一作品 / 文件夹名）或按文件名推断；预览给出分组。"""
    d = media / "番剧 文件夹"
    d.mkdir()
    for n in ("[G] Show X [01].wav", "[G] Show X [02].wav"):
        wav(d / n, 0.2)
    imp, _ = service(db, ws)
    imp._adopt_scan({"id": "a"}, scan([str(d)], ws.root / "Jobs" / "a" / "cache", lambda *_: None))
    pv = imp.preview("a")
    assert (pv["inferredGroups"], pv["suggestedWork"]) == ([["Show X", 2]], "Show X")  # 推断出同一个作品 → 预填它
    wav(d / "extra.wav", 0.2)
    imp._adopt_scan({"id": "b"}, scan([str(d)], ws.root / "Jobs" / "b" / "cache", lambda *_: None))
    pv = imp.preview("b")
    assert (pv["inferredGroups"], pv["suggestedWork"]) == ([["Show X", 2], ["", 1]], "番剧 文件夹")  # 不一致 → 文件夹名
    # 按文件名推断（work=None）：两组；集数照样推断
    imp.commit("b", work=None, source_type="", whole_sample=False, nature="unclassified", bind_pictures=True)
    got = sorted((r[0], r[1]) for r in db.execute("SELECT work, episode FROM source"))
    assert got == [("", ""), ("Show X", "01"), ("Show X", "02")]
    # 统一设为空 = 未指定作品（不再推断作品），集数仍推断
    db.execute("DELETE FROM sample")
    for t in ("default_track", "asset_storage", "asset_role", "sound_asset", "source_stream", "source"):
        db.execute(f"DELETE FROM {t}")
    imp._adopt_scan({"id": "c"}, scan([str(d)], ws.root / "Jobs" / "c" / "cache", lambda *_: None))
    imp.commit("c", work="", source_type="", whole_sample=False, nature="unclassified", bind_pictures=True)
    got = sorted((r[0], r[1]) for r in db.execute("SELECT work, episode FROM source"))
    assert got == [("", ""), ("", "01"), ("", "02")]
