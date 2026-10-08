"""导入原片（规格 06 §6.6、05 §5.1；ARCHITECTURE §4.10；UI_PLAN §4、§8）。

所有者 2026-10-07：原片只有一种。原片页「＋」与采样库「导入」是同一个导入框，唯一的区别是“直接建立全长采样”勾不勾
（采样库进来默认勾，原片页进来默认不勾）；任何原片之后也能「建立全长采样…」（``whole_samples``）。

- 每个文件 = 一个原片（登记位置，不复制、不转码）；勾了全长采样就在默认音轨上建一个整段采样（名 = 文件名去扩展名，性质在框里选，不靠文件名或音高推断）。
- 作品：框里填了就用它（集数仍按文件名推断）；空着就按文件名推断作品与集数（同原片页登记）。
- 接受文件和整个文件夹（含子文件夹，跳过隐藏文件）。文件夹里导入音频和视频；与同文件夹某个音频同名的视频/图片是那个音频的画面，不单独导入。
- 再次导入已登记过的文件：原片不重复登记、属性不改；勾了全长采样就再建一个整段采样（显式操作一律新建）。
- **同名画面**：与音频同一文件夹、去掉扩展名后同名（NFC、不分大小写）的视频 / 动图 / 静态图，按 视频 > 动图 > 静态图 取第一个（同类按文件名），
  其余列为冲突；视频要真的有视频流。绑定方式：视频 = 同步画面，动图 = 循环，静态图 = 图片（规格 12 的画面绑定）。
- 两步：``import.scan`` 轻量任务在任务进程里探测、确切时长、生成波形峰值（写进任务目录，登记时移进缓存）、找同名画面 → 预览；
  用户确认后 ``commit`` 在 Core 主线程里逐个文件一个事务登记。
- 扫描结果只留在内存里（预览令牌 = 任务 ID）；重启后要重新扫描。
"""

from __future__ import annotations

import dataclasses
import os
import shutil
import unicodedata
from collections.abc import Callable, Iterable
from pathlib import Path
from typing import Any

from ottosmasher.domain import naming
from ottosmasher.media import probe as probe_mod
from ottosmasher.store.db import transaction

from . import effective_tags
from . import settings as settings_mod
from .clock import new_id, now_iso
from .edits import ChangeSet, dumps, loads
from .errors import CoreError
from .samples import NATURES
from .sources import path_key, prepare

AUDIO_EXT = frozenset({".wav", ".flac", ".mp3", ".m4a", ".aac", ".ogg", ".opus", ".aif", ".aiff", ".wma"})
VIDEO_EXT = frozenset({".mp4", ".mov", ".mkv", ".webm", ".m4v", ".avi"})
ANIM_EXT = frozenset({".gif"})
IMAGE_EXT = frozenset({".png", ".jpg", ".jpeg", ".webp", ".bmp"})
PICTURE_RANK = {"video": 0, "anim": 1, "image": 2}
BINDING_MODE = {"video": "sync", "anim": "loop", "image": "image"}
MAX_TEXT = 200


def picture_kind(ext: str) -> str | None:
    ext = ext.lower()
    return "video" if ext in VIDEO_EXT else "anim" if ext in ANIM_EXT else "image" if ext in IMAGE_EXT else None


def _stem_key(name: str) -> str:
    return unicodedata.normalize("NFC", Path(name).stem).casefold()


def collect(paths: Iterable[str]) -> list[tuple[str, str]]:
    """要导入的文件（绝对路径, 导入根文件夹），按输入顺序、文件夹内按路径排序，去重。"""
    out: list[tuple[str, str]] = []
    seen: set[str] = set()

    def add(f: str, root: str) -> None:
        if f not in seen:
            seen.add(f)
            out.append((f, root))

    for raw in paths:
        p = Path(os.path.abspath(raw))
        if p.is_dir():
            files = [f for f in sorted(p.rglob("*")) if f.is_file() and not any(x.startswith(".") for x in f.relative_to(p).parts)]
            audio_stems = {(str(f.parent), _stem_key(f.name)) for f in files if f.suffix.lower() in AUDIO_EXT}
            for f in files:
                ext = f.suffix.lower()
                if ext in AUDIO_EXT:
                    add(str(f), str(p))
                elif ext in VIDEO_EXT and (str(f.parent), _stem_key(f.name)) not in audio_stems:
                    add(str(f), str(p))  # 视频：没有同名音频的才单独导入；有的是那个音频的画面
        else:
            add(str(p), str(p.parent))  # 单独选的文件（含视频、找不到的）：都试着登记，读不了的列出来
    return out


class _Pictures:
    """按文件夹缓存的同名画面候选。"""

    def __init__(self, probe: Callable[[str], probe_mod.Probe]) -> None:
        self.probe = probe
        self._dirs: dict[str, dict[str, list[tuple[str, str]]]] = {}
        self._video: dict[str, dict[str, Any] | None] = {}

    def _index(self, d: str) -> dict[str, list[tuple[str, str]]]:
        if d not in self._dirs:
            idx: dict[str, list[tuple[str, str]]] = {}
            try:
                names = sorted(os.listdir(d))
            except OSError:
                names = []
            for n in names:
                k = picture_kind(Path(n).suffix)
                if k and not n.startswith(".") and os.path.isfile(os.path.join(d, n)):
                    idx.setdefault(_stem_key(n), []).append((os.path.join(d, n), k))
            self._dirs[d] = idx
        return self._dirs[d]

    def _video_info(self, path: str) -> dict[str, Any] | None:
        if path not in self._video:
            try:
                pr = self.probe(path)
                v = pr.video
                self._video[path] = {"ordinal": v[0].ordinal, "duration": v[0].duration or pr.format_duration} if v else None
            except CoreError:
                self._video[path] = None
        return self._video[path]

    def find(self, audio: str) -> dict[str, Any] | None:
        cands = [c for c in self._index(os.path.dirname(audio)).get(_stem_key(audio), []) if c[0] != audio]
        cands.sort(key=lambda c: (PICTURE_RANK[c[1]], c[0]))
        usable = []
        for path, kind in cands:
            if kind == "video":
                info = self._video_info(path)
                if info is None:
                    continue  # 同名的视频文件里没有画面：不算候选
                usable.append({"path": path, "kind": kind, **info})
            else:
                usable.append({"path": path, "kind": kind, "ordinal": 0, "duration": None})
        if not usable:
            return None
        return usable[0] | {"conflicts": [u["path"] for u in usable[1:]]}


def scan(paths: list[str], cache: Path, progress: Callable[[int, int], None], *, probe: Callable[[str], probe_mod.Probe] = probe_mod.probe) -> dict[str, Any]:
    """任务进程里执行：不碰数据库。"""
    files = collect(paths)
    pics = _Pictures(probe)
    items = []
    for i, (f, root) in enumerate(files):
        progress(i, len(files))
        item: dict[str, Any] = {"path": f, "root": root}
        try:
            pr = prepare(f, cache, probe=probe)
            item |= {"ok": True, "probe": dataclasses.asdict(pr), "video": bool(pr.video)}
        except CoreError as e:
            item |= {"ok": False, "error": e.to_wire()}
        if item["ok"]:
            item["picture"] = None if item["video"] else pics.find(f)  # 自己有画面的视频不再找同名画面
        items.append(item)
    progress(len(files), len(files))
    return {"items": items}


def _probe_of(d: dict[str, Any]) -> probe_mod.Probe:
    return probe_mod.Probe(d["format_name"], d["format_duration"], tuple(probe_mod.Stream(**s) for s in d["streams"]))


class ImportService:
    def __init__(self, conn: Any, ws: Any, jobs: Any, sources: Any, *, on_change: Callable[[ChangeSet], None] | None = None) -> None:
        self.conn = conn
        self.ws = ws
        self.jobs = jobs
        self.sources = sources
        self.on_change = on_change
        self._scans: dict[str, dict[str, Any]] = {}
        jobs.adopters["import.scan"] = self._adopt_scan

    def scan(self, paths: list[str]) -> dict[str, Any]:
        paths = [str(p) for p in paths if str(p)]
        if not paths:
            raise CoreError("import-empty")
        return self.jobs.submit("import.scan", {"paths": paths})

    def _adopt_scan(self, job: dict[str, Any], result: dict[str, Any]) -> None:
        # 任务目录里的波形峰值移进缓存（文件名是内容键，已有的不覆盖）
        src = self.jobs.jobs_dir / job["id"] / "cache" / "Peaks"
        if src.is_dir():
            dst = self.ws.data / "Cache" / "Peaks"
            dst.mkdir(parents=True, exist_ok=True)
            for f in src.iterdir():
                if not (dst / f.name).exists():
                    shutil.move(str(f), dst / f.name)
        self._scans[job["id"]] = result

    def _scan_of(self, job_id: str) -> dict[str, Any]:
        sc = self._scans.get(job_id)
        if sc is None:
            raise CoreError("import-expired", job=job_id)
        return sc

    def preview(self, job_id: str) -> dict[str, Any]:
        items = self._scan_of(job_id)["items"]
        ok = [x for x in items if x["ok"]]
        existing = {r[0] for r in self.conn.execute("SELECT path_key FROM source")}
        fresh = [x for x in ok if path_key(x["path"]) not in existing]
        return {
            "total": len(items),
            "importable": len(ok),
            "videos": sum(1 for x in ok if x.get("video")),
            "existing": len(ok) - len(fresh),
            "withPicture": sum(1 for x in fresh if x.get("picture")),
            "withoutPicture": sum(1 for x in fresh if not x.get("picture")),
            "unreadable": [{"path": x["path"], "error": x["error"]} for x in items if not x["ok"]],
            "conflicts": [
                {"path": x["path"], "picture": x["picture"]["path"], "others": x["picture"]["conflicts"]}
                for x in fresh
                if x.get("picture") and x["picture"]["conflicts"]
            ],
            "roots": sorted({x["root"] for x in items}),
        }

    def commit(self, job_id: str, *, work: str, source_type: str, whole_sample: bool, nature: str, bind_pictures: bool) -> dict[str, Any]:
        work, source_type = work.strip(), source_type.strip()
        for field, v in (("work", work), ("source_type", source_type)):
            if len(v) > MAX_TEXT:
                raise CoreError("edit-invalid", index=0, field=field, reason="too-long")
        if whole_sample and nature not in NATURES:
            raise CoreError("edit-invalid", index=0, field="nature", reason="not-an-option")
        items = self._scan_of(job_id)["items"]
        values = settings_mod.values(self.conn)
        rules, preferred = values["source.infer_rules"], values["source.sample_language"]
        cs = ChangeSet()
        created, existing, failed, sample_ids, source_ids = 0, 0, [], [], []
        for it in items:
            if not it["ok"]:
                continue
            row = self.conn.execute("SELECT id FROM source WHERE path_key=?", (path_key(it["path"]),)).fetchone()
            try:
                with transaction(self.conn):
                    if row is not None:
                        sid = row[0]  # 已登记：原片不动
                        existing += 1
                    else:
                        r = self.sources.insert(
                            it["path"], _probe_of(it["probe"]), rules, preferred, it["root"], cs, work=work, source_type=source_type, tx=False
                        )
                        sid = r["sourceId"]
                        pic = it.get("picture")
                        if bind_pictures and pic:
                            bind_picture(self.conn, sid, pic)
                        created += 1
                        source_ids.append(sid)
                    if whole_sample:
                        sample_ids.append(create_whole_sample(self.conn, sid, nature, created_via="import"))
            except CoreError as e:
                failed.append({"path": it["path"], "error": e.to_wire()})
        self._scans.pop(job_id, None)
        for sid in sample_ids:
            cs.add("sample", sid)
        if cs.entities and self.on_change:
            self.on_change(cs)
        return {"created": created, "existing": existing, "failed": failed, "sourceIds": source_ids, "sampleIds": sample_ids}

    def whole_samples(self, source_ids: list[str], nature: str | None) -> dict[str, Any]:
        """对已有原片「建立全长采样」（所有者 2026-10-07）：每个原片在默认音轨上建一个整段采样；一次事务，失败整批回滚。
        nature 为 None = 按默认音轨的角色预填（人声 → 语音、音效 → 非调谐单音、其他 → 未分类，04 §4.2.7）。"""
        if nature is not None and nature not in NATURES:
            raise CoreError("edit-invalid", index=0, field="nature", reason="not-an-option")
        if not source_ids:
            raise CoreError("edit-empty")
        with transaction(self.conn):
            ids = [create_whole_sample(self.conn, sid, nature, created_via="manual") for sid in source_ids]
        cs = ChangeSet()
        for sid in ids:
            cs.add("sample", sid)
        if self.on_change:
            self.on_change(cs)
        return {"sampleIds": ids}


def create_whole_sample(conn: Any, source_id: str, nature: str | None, *, created_via: str) -> str:
    """在调用方的事务里：原片默认音轨上建一个整段采样（名 = 文件名去扩展名），并算有效标签。nature None = 按音轨角色预填。"""
    a = conn.execute(
        "SELECT a.id, a.duration, a.language, s.path FROM sound_asset a JOIN source s ON s.id=a.source_id"
        " WHERE a.source_id=? AND a.origin='stream' AND a.stream_ordinal=s.default_audio_stream",
        (source_id,),
    ).fetchone()
    if a is None:
        src = conn.execute("SELECT path FROM source WHERE id=?", (source_id,)).fetchone()
        if src is None:
            raise CoreError("source-not-found", id=source_id)
        raise CoreError("source-no-audio", path=src[0])
    if nature is None:
        roles = [r[0] for r in conn.execute("SELECT role FROM asset_role WHERE asset_id=? AND state='on'", (a["id"],))]
        nature = naming.nature_for_roles(roles)
    smp, ts = new_id(), now_iso()
    name = unicodedata.normalize("NFC", Path(a["path"]).stem)[:500] or Path(a["path"]).name
    conn.execute(
        'INSERT INTO sample(id, asset_id, start, "end", name, nature, language, created_via, created_at, updated_at)'
        " VALUES (?, ?, 0, ?, ?, ?, ?, ?, ?, ?)",
        (smp, a["id"], a["duration"], name, nature, a["language"], created_via, ts, ts),
    )
    effective_tags.refresh(conn, [smp])
    return smp


def bind_picture(conn: Any, source_id: str, pic: dict[str, Any]) -> str:
    """在调用方的事务里把画面文件绑定为原片的画面（规格 12：视频 = 同步，动图 = 循环，图片 = 静态）。"""
    st = os.stat(pic["path"])
    mid, vid, ts = new_id(), new_id(), now_iso()
    snap = {"size": st.st_size, "mtime_ns": st.st_mtime_ns, "videoOrdinal": pic.get("ordinal", 0), "duration": pic.get("duration")}
    conn.execute(
        "INSERT INTO media_file(id, path, location, file_snapshot, format, created_at) VALUES (?, ?, 'external', ?, ?, ?)",
        (mid, pic["path"], dumps(snap), pic["kind"], ts),
    )
    conn.execute(
        "INSERT INTO visual_binding(id, owner_type, owner_id, mode, media_file_id, clip_offset, created_at, updated_at)"
        " VALUES (?, 'source', ?, ?, ?, ?, ?, ?)",
        (vid, source_id, BINDING_MODE[pic["kind"]], mid, 0.0 if pic["kind"] == "video" else None, ts, ts),
    )
    conn.execute("UPDATE source SET visual_binding_id=? WHERE id=?", (vid, source_id))
    return vid


def binding_of(conn: Any, source_id: str) -> dict[str, Any] | None:
    """原片的画面绑定（没有 → None）：mode、文件路径、视频流序号、时长、种类。"""
    r = conn.execute(
        "SELECT v.mode, m.path, m.file_snapshot, m.format FROM source s JOIN visual_binding v ON v.id=s.visual_binding_id"
        " JOIN media_file m ON m.id=v.media_file_id WHERE s.id=?",
        (source_id,),
    ).fetchone()
    if r is None:
        return None
    snap = loads(r["file_snapshot"]) if r["file_snapshot"] else {}
    return {"mode": r["mode"], "path": r["path"], "kind": r["format"], "ordinal": snap.get("videoOrdinal", 0), "duration": snap.get("duration")}
