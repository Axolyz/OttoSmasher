"""原片文件夹（阶段 3.13，所有者 2026-10-07）：第一层子文件夹 = 作品、扫描登记、认移动/改名、作品改名改文件夹、作品设置、字幕匹配放宽。"""

import os
import shutil
from pathlib import Path

import pytest

from ottosmasher.core import effective_tags
from ottosmasher.core.edits import EditService
from ottosmasher.core.errors import CoreError
from ottosmasher.core.roots import RootService, scan_roots
from ottosmasher.core.sources import SourceService, find_subtitle
from test_imports import Jobs
from test_sources import ff, media, needs_ffmpeg, wav  # noqa: F401 - fixture


def tree(base: Path) -> Path:
    root = base / "原片库"
    kf = root / "Kemono Friends"
    (kf / "Subs").mkdir(parents=True)
    (root / "Game" / "se").mkdir(parents=True)
    wav(kf / "[G] Kemono Friends [01].wav", 0.3)
    (kf / "[G] Kemono Friends [01].ja.srt").write_text("1\n00:00:00,000 --> 00:00:00,200\nあ\n", encoding="utf-8")
    wav(kf / "[G] Kemono Friends [02].wav", 0.3)
    (kf / "Subs" / "[G] Kemono Friends [02].srt").write_text("1\n00:00:00,000 --> 00:00:00,200\nい\n", encoding="utf-8")
    wav(root / "Game" / "se" / "hit.wav", 0.2)
    ff("-f", "lavfi", "-i", "testsrc=size=64x36:rate=1:duration=1", "-frames:v", "1", str(root / "Game" / "se" / "hit.png"))
    wav(root / "loose.wav", 0.2)
    return root


class Svc:
    def __init__(self, db, ws):
        self.events = []
        self.edits = EditService(db)
        self.sources = SourceService(db, workspace_root=ws.root)
        self.jobs = Jobs(ws.root / "Jobs")
        self.roots = RootService(db, ws, self.jobs, self.sources, on_change=None, emit=lambda n, d: self.events.append((n, d)))
        self.db, self.ws = db, ws

    def scan(self):
        roots = [{"id": r[0], "path": r[1]} for r in self.db.execute("SELECT id, path FROM source_root")]
        known = [r[0] for r in self.db.execute("SELECT path_key FROM source")]
        res = scan_roots(roots, known, self.ws.root / "Jobs" / "x" / "cache", lambda *_: None)
        self.roots._adopt_scan({"id": "x"}, res)
        return self.events[-1][1]

    def row(self, name):
        return self.db.execute("SELECT * FROM source WHERE path LIKE ?", (f"%{name}",)).fetchone()


@needs_ffmpeg
def test_scan_registers_by_folder(db, ws, tmp_path):
    root = tree(tmp_path)
    s = Svc(db, ws)
    out = s.roots.add(str(root))
    assert out["job"] is not None  # 加了就排一次扫描
    ev = s.scan()
    assert (ev["new"], ev["moved"], ev["missing"]) == (4, 0, 0)
    assert dict(ev["byWork"]) == {"Kemono Friends": 2, "Game": 1, "": 1}
    r1, r2, hit, loose = (s.row(n) for n in ("[01].wav", "[02].wav", "hit.wav", "loose.wav"))
    assert (r1["work"], r1["episode"], r1["rel_path"]) == ("Kemono Friends", "01", "Kemono Friends/[G] Kemono Friends [01].wav")
    assert (hit["work"], hit["rel_path"]) == ("Game", "Game/se/hit.wav")  # 第一层子文件夹 = 作品，更深的只是子目录
    assert (loose["work"], loose["rel_path"]) == ("", "loose.wav")
    # 字幕放宽：同名加语言后缀、Subs 子文件夹
    assert r1["subtitle_path"].endswith("[01].ja.srt") and "/Subs/" in r2["subtitle_path"]
    assert hit["visual_binding_id"] is not None  # 同名画面
    assert {r[0] for r in db.execute("SELECT name FROM work_folder")} == {"Kemono Friends", "Game"}
    # 再扫一遍：没有新的
    assert s.scan()["new"] == 0
    # 原片文件夹里的原片不能在编辑通道里改作品（要用作品改名）
    with pytest.raises(CoreError) as e:
        s.edits.apply({"ops": [{"entity": "source", "id": r1["id"], "version": r1["version"], "fields": {"work": "别的"}}]})
    assert e.value.args_["reason"] == "work-follows-folder"


@needs_ffmpeg
def test_work_settings_and_rename(db, ws, tmp_path):
    root = tree(tmp_path)
    s = Svc(db, ws)
    s.roots.add(str(root))
    s.scan()
    kf = next(w for w in s.roots.works() if w["name"] == "Kemono Friends")
    assert (kf["sources"], kf["sourceType"], kf["bindPictures"]) == (2, "", True)
    # 作品设置：来源类型整组一起设（一次编辑、可撤销），新文件沿用
    s.edits.apply(s.roots.settings_batch(kf["id"], "动画", True))
    assert {r[0] for r in db.execute("SELECT source_type FROM source WHERE work='Kemono Friends'")} == {"动画"}
    wav(root / "Kemono Friends" / "[G] Kemono Friends [03].wav", 0.3)
    assert s.scan()["new"] == 1
    assert s.row("[03].wav")["source_type"] == "动画"
    s.edits.undo()  # 撤销作品设置不影响后来扫进来的新原片
    assert s.row("[01].wav")["source_type"] == ""

    # 作品改名 = 改磁盘上的文件夹名；路径、字幕、作品名、派生采样的 work: 标签一起改
    r1 = s.row("[01].wav")
    aid = db.execute("SELECT id FROM sound_asset WHERE source_id=?", (r1["id"],)).fetchone()[0]
    from conftest import make_sample

    smp = make_sample(db, aid)
    db.execute('UPDATE sample SET "end"=0.2, start=0.0 WHERE id=?', (smp,))
    effective_tags.refresh(db, [smp])
    s.roots.rename(kf["id"], "けものフレンズ")
    assert (root / "けものフレンズ").is_dir() and not (root / "Kemono Friends").exists()
    r1 = db.execute("SELECT * FROM source WHERE id=?", (r1["id"],)).fetchone()
    assert r1["work"] == "けものフレンズ" and os.path.isfile(r1["path"]) and os.path.isfile(r1["subtitle_path"])
    assert r1["rel_path"].startswith("けものフレンズ/")
    assert "work:けものフレンズ" in {t["tag"] for t in effective_tags.of_sample(db, smp)}
    # 不行的名字、已有的作品名 → 报错、什么都不动
    for bad in ("", "a/b", ".hidden"):
        with pytest.raises(CoreError):
            s.roots.rename(kf["id"], bad)
    with pytest.raises(CoreError) as e:
        s.roots.rename(kf["id"], "Game")
    assert e.value.code == "work-folder-exists"
    assert (root / "けものフレンズ").is_dir()


@needs_ffmpeg
def test_finder_rename_and_root_relocate(db, ws, tmp_path):
    root = tree(tmp_path)
    s = Svc(db, ws)
    s.roots.add(str(root))
    s.scan()
    hit_id = s.row("hit.wav")["id"]
    # 在 Finder 里改了文件夹名：重新扫描认出是同一个原片（不重复登记）
    os.rename(root / "Game", root / "Game 2")
    ev = s.scan()
    assert (ev["new"], ev["moved"]) == (0, 1)
    hit = db.execute("SELECT work, rel_path, path FROM source WHERE id=?", (hit_id,)).fetchone()
    assert (hit["work"], hit["rel_path"]) == ("Game 2", "Game 2/se/hit.wav") and os.path.isfile(hit["path"])
    # 文件删掉：不删原片，只是找不到
    os.remove(root / "loose.wav")
    assert s.scan()["missing"] == 1
    assert s.row("loose.wav") is not None
    # 整个原片文件夹搬家：改设置里的位置，全部找回
    rid = db.execute("SELECT id FROM source_root").fetchone()[0]
    moved = tmp_path / "外置盘" / "原片库"
    moved.parent.mkdir()
    shutil.move(str(root), str(moved))
    out = s.roots.relocate(rid, str(moved))
    assert out["moved"] == 4
    assert all(os.path.isfile(r[0]) for r in db.execute("SELECT path FROM source WHERE work<>''"))
    # 不再当原片文件夹：原片照旧，作品可以在应用里改了
    s.roots.remove(rid)
    r = s.row("hit.wav")
    assert r["root_id"] is None and r["work"] == "Game 2"
    s.edits.apply({"ops": [{"entity": "source", "id": r["id"], "version": r["version"], "fields": {"work": "别的"}}]})


def test_root_overlap_refused(db, ws, tmp_path):
    (tmp_path / "a" / "b").mkdir(parents=True)
    s = Svc(db, ws)
    s.roots.add(str(tmp_path / "a"))
    for p in (tmp_path / "a" / "b", tmp_path / "a", tmp_path):
        with pytest.raises(CoreError):
            s.roots.add(str(p))


def test_find_subtitle_priority(tmp_path):
    v = tmp_path / "Ep 01.mkv"
    v.write_bytes(b"")
    (tmp_path / "Ep 01.en.srt").write_text("x")
    (tmp_path / "Ep 01.ja.ass").write_text("x")
    assert find_subtitle(v).endswith("Ep 01.ja.ass")  # 日语后缀优先
    (tmp_path / "Ep 01.ass").write_text("x")
    assert find_subtitle(v).endswith("Ep 01.ass")  # 完全同名优先
    (tmp_path / "Ep 01.srt").write_text("x")
    assert find_subtitle(v).endswith("Ep 01.srt")  # 同一层 .srt 优先
    assert find_subtitle(tmp_path / "Other.mkv") is None
