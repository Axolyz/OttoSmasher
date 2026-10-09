"""原片：登记、查询、重新定位、删除（规格 05 §5.1、04 §4.2.1、§4.5、§4.6；16 R1）。

- 登记不复制、不转码、不分析、不建采样、不要求字幕；同一路径重复登记返回已有原片并保留用户设置；
  没有音频流 → ``source-no-audio``；推断作品/集数（设置里的规则）；关联同名字幕（只关联，不导入；.srt 优先）；
  默认分析音轨 = 语言与首选采样语言相同的第一条，否则第一条。
- 重新定位只改位置引用（不校验内容和时长），并换成新文件的快照；资产、映射、测量、OP/ED 不变。
- 删除原片：级联删除它的采样、资产、标注、字幕版本、测量、OP/ED、角色、画面绑定；原片文件与导出保留；有相关任务时拒绝。
"""

from __future__ import annotations

import os
import sqlite3
from contextlib import nullcontext
import unicodedata
from collections.abc import Callable, Iterable
from dataclasses import replace
from pathlib import Path
from typing import Any

from ottosmasher.domain import naming
from ottosmasher.media import peaks as peaks_mod
from ottosmasher.media import probe as probe_mod
from ottosmasher.media.decode import StreamRef
from ottosmasher.store.db import transaction

from . import assets as assets_mod
from . import rootpaths
from . import settings as settings_mod
from .clock import new_id, now_iso
from .edits import ChangeSet, dumps, loads
from .errors import CoreError

SUBTITLE_EXTS = (".srt", ".ass")
"""同名字幕的查找顺序：两种都有时取 .srt（所有者 2026-10-07）。"""

LANG_ALIASES = {"ja": {"ja", "jpn"}, "zh": {"zh", "chi", "zho"}, "en": {"en", "eng"}}


def path_key(path: str | os.PathLike[str]) -> str:
    return os.path.normcase(unicodedata.normalize("NFC", os.path.abspath(os.fspath(path))))


def pick_default_audio(streams: list[probe_mod.Stream], preferred: str) -> int:
    langs = LANG_ALIASES.get(preferred, {preferred})
    for s in streams:
        if s.language and s.language.lower() in langs:
            return s.ordinal
    return streams[0].ordinal


def exact_durations(path: str, pr: probe_mod.Probe, cache: Path) -> probe_mod.Probe:
    """每条音频流从头解码一次，用确切样本数作时长（容器里的时长标签不精确：YY2-07-A 标 110.001 秒，
    实际 110.000167 秒，差 40 个样本，超出一帧容差）。这次解码顺带生成波形峰值缓存（写进 cache）。约 0.5 秒 / 24 分钟 FLAC。"""
    streams = []
    for s in pr.streams:
        if s.kind == "audio":
            if not s.sample_rate or not s.channels:
                raise CoreError("media-probe-failed", path=path, detail="unknown-audio-format")
            pk = peaks_mod.build(StreamRef(path, s.ordinal, s.sample_rate, s.channels, s.codec, pr.format_name), cache)
            s = replace(s, duration=pk.frames / s.sample_rate if pk.frames else None)
        streams.append(s)
    return probe_mod.Probe(pr.format_name, pr.format_duration, tuple(streams))


def prepare(path: str, cache: Path, *, probe: Callable[[str], probe_mod.Probe] = probe_mod.probe) -> probe_mod.Probe:
    """登记前的准备（不碰数据库，可以在任务进程里做）：探测 + 确切时长。没有音频流 → 报错。"""
    pr = probe(path)
    if not pr.audio:
        raise CoreError("source-no-audio", path=path)
    return exact_durations(path, pr, cache)


SUBTITLE_DIRS = ("subs", "sub", "subtitles", "subtitle", "\u5b57\u5e55")  # 最后一个是中文“字幕”
JA_TAGS = ("ja", "jp", "jpn", "jap", "japanese")


def _subtitle_in(d: Path, stem: str) -> Path | None:
    """d 里与 stem 同名的字幕：完全同名 > 同名加一段后缀（stem.ja.srt，日语后缀优先）；同一层 .srt 优先于 .ass。"""
    try:
        files = [p for p in d.iterdir() if p.is_file()]
    except OSError:
        return None
    exact: list[tuple[int, Path]] = []
    tagged: list[tuple[int, int, str, Path]] = []
    for p in files:
        n = unicodedata.normalize("NFC", p.name).lower()
        for rank, ext in enumerate(SUBTITLE_EXTS):
            if not n.endswith(ext):
                continue
            base = n[: -len(ext)]
            if base == stem:
                exact.append((rank, p))
            elif base.startswith(stem + "."):
                tag = base[len(stem) + 1 :]
                if 0 < len(tag) <= 12 and "." not in tag:
                    tagged.append((0 if tag in JA_TAGS else 1, rank, tag, p))
    if exact:
        return min(exact)[1]
    if tagged:
        return min(tagged)[3]
    return None


def find_subtitle(path: Path) -> str | None:
    """自动关联的字幕（规格 05 §5.1：只关联不导入）。所有者 2026-10-07 放宽：同一文件夹里完全同名的 .srt/.ass，
    其次同名加语言等后缀（第01集.ja.srt），再其次同一文件夹的 Subs / 字幕 子文件夹里的同样两种。"""
    stem = unicodedata.normalize("NFC", path.stem).lower()
    hit = _subtitle_in(path.parent, stem)
    if hit is None:
        try:
            subdirs = sorted(p for p in path.parent.iterdir() if p.is_dir() and unicodedata.normalize("NFC", p.name).lower() in SUBTITLE_DIRS)
        except OSError:
            subdirs = []
        for d in subdirs:
            hit = _subtitle_in(d, stem)
            if hit is not None:
                break
    return str(hit) if hit is not None else None


def move_source(conn: sqlite3.Connection, source_id: str, path: str, snap: dict[str, Any] | None = None) -> None:
    """在调用方的事务里改原片位置（重新定位、扫描认出的移动/改名）：路径、原片文件夹位置；在原片文件夹里时作品跟着文件夹走；
    原片文件对应的 media_file 一起改；字幕文件不在了就按新位置重新找同名字幕。作品变了要重算派生采样的有效标签。"""
    path = os.path.abspath(path)
    cur = conn.execute("SELECT work, subtitle_path, file_snapshot FROM source WHERE id=?", (source_id,)).fetchone()
    snap_text = dumps(snap) if snap is not None else cur["file_snapshot"]
    where = rootpaths.locate(conn, path)
    work = where[2] if where is not None else cur["work"]
    sub = cur["subtitle_path"]
    if sub and not os.path.isfile(sub):
        sub = find_subtitle(Path(path))
    conn.execute(
        "UPDATE source SET path=?, path_key=?, file_snapshot=?, root_id=?, rel_path=?, work=?, subtitle_path=?, updated_at=?, version=version+1 WHERE id=?",
        (path, path_key(path), snap_text, where[0] if where else None, where[1] if where else None, work, sub, now_iso(), source_id),
    )
    for mid in assets_mod.source_media_files(conn, source_id):
        conn.execute("UPDATE media_file SET path=?, file_snapshot=? WHERE id=?", (path, snap_text, mid))
    if work != cur["work"]:
        from . import effective_tags  # 避免循环导入

        effective_tags.refresh(conn, [r[0] for r in conn.execute("SELECT s.id FROM sample s JOIN sound_asset a ON a.id=s.asset_id WHERE a.source_id=?", (source_id,))])


class SourceService:
    def __init__(
        self,
        conn: sqlite3.Connection,
        *,
        on_change: Callable[[ChangeSet], None] | None = None,
        workspace_root: Path,
        probe: Callable[[str], probe_mod.Probe] = probe_mod.probe,
    ) -> None:
        self.conn = conn
        self.workspace_root = workspace_root
        self.on_change = on_change
        self.probe = probe

    # ------------------------------------------------------------ 登记

    def add(self, paths: Iterable[str], *, import_root: str | None = None) -> list[dict[str, Any]]:
        """逐个登记；每个文件单独成败，结果按输入顺序返回。"""
        values = settings_mod.values(self.conn)
        rules, preferred = values["source.infer_rules"], values["source.sample_language"]
        cs = ChangeSet()
        out: list[dict[str, Any]] = []
        for raw in paths:
            try:
                out.append(self._add_one(str(raw), rules, preferred, import_root, cs))
            except CoreError as e:
                out.append({"path": str(raw), "ok": False, "error": e.to_wire()})
        if cs.entities and self.on_change:
            self.on_change(cs)
        return out

    def _add_one(self, raw: str, rules: list[str], preferred: str, import_root: str | None, cs: ChangeSet) -> dict[str, Any]:
        path = os.path.abspath(raw)
        row = self.conn.execute("SELECT id FROM source WHERE path_key=?", (path_key(path),)).fetchone()
        if row is not None:
            return {"path": path, "ok": True, "sourceId": row[0], "existing": True}
        pr = prepare(path, self.workspace_root / "Data" / "Cache", probe=self.probe)
        return self.insert(path, pr, rules, preferred, import_root, cs)

    def insert(
        self,
        path: str,
        pr: probe_mod.Probe,
        rules: list[str],
        preferred: str,
        import_root: str | None,
        cs: ChangeSet,
        *,
        work: str | None = None,
        source_type: str | None = None,
        tx: bool = True,
    ) -> dict[str, Any]:
        """登记一个已经 ``prepare`` 过的文件（不再探测）。work 为 None = 按文件名推断作品与集数；给了（含空串 = 未指定作品）= 作品用它、集数仍推断。source_type 给了就用。
        tx=False：在调用方的事务里写（采样库导入把原片、整段采样、画面绑定放进同一个事务）。"""
        key = path_key(path)
        audio = pr.audio
        default = pick_default_audio(audio, preferred)
        # 原片时间以默认音轨的音频时钟为准；探测不出时长就拒绝登记，不拿容器时长冒充（P7）
        duration = next(s.duration for s in audio if s.ordinal == default)
        if duration is None or duration <= 0:
            raise CoreError("media-probe-failed", path=path, detail="no-duration")
        inferred = naming.infer_work_episode(path, rules)
        where = rootpaths.locate(self.conn, path)
        if where is not None:
            # 在原片文件夹里（阶段 3.13）：作品 = 第一层子文件夹名（不管导入框怎么选）；来源类型没给就沿用作品文件夹的设置
            work = where[2]
            wf = rootpaths.work_folder(self.conn, where[0], where[2])
            if source_type is None and wf is not None:
                source_type = wf["source_type"]
        if work is not None:  # 导入框“统一设为”（空 = 未指定作品）：作品用它，集数仍按文件名推断
            inferred = naming.WorkEpisode(work, inferred.episode, inferred.rule, inferred.timed_out)
        snap = probe_mod.snapshot(path, pr)
        sid, ts = new_id(), now_iso()
        with transaction(self.conn) if tx else nullcontext(self.conn):
            self.conn.execute(
                "INSERT INTO source(id, path, path_key, import_root, file_snapshot, duration, work, episode, source_type, subtitle_path,"
                " default_audio_stream, root_id, rel_path, created_at, updated_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (
                    sid,
                    path,
                    key,
                    import_root,
                    dumps(snap),
                    duration,
                    inferred.work or "",
                    inferred.episode or "",
                    source_type or "",
                    find_subtitle(Path(path)),
                    default,
                    where[0] if where else None,
                    where[1] if where else None,
                    ts,
                    ts,
                ),
            )
            self.conn.executemany(
                "INSERT INTO source_stream(source_id, kind, ordinal, container_index, codec, sample_rate, channels, bit_depth,"
                " language, title, start_time, duration, is_attached_pic) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
                [
                    (
                        sid,
                        s.kind,
                        s.ordinal,
                        s.container_index,
                        s.codec,
                        s.sample_rate,
                        s.channels,
                        s.bit_depth,
                        s.language,
                        s.title,
                        s.start_time,
                        s.duration,
                        int(s.is_attached_pic),
                    )
                    for s in pr.streams
                ],
            )
            created = assets_mod.create_stream_assets(self.conn, sid, path, snap, pr)
        cs.add("source", sid)
        return {
            "path": path,
            "ok": True,
            "sourceId": sid,
            "existing": False,
            "work": inferred.work,
            "episode": inferred.episode,
            "inferRule": inferred.rule,
            "inferTimedOut": list(inferred.timed_out),
            "assets": created,
        }

    # ------------------------------------------------------------ 查询

    def get(self, source_id: str) -> dict[str, Any]:
        row = self.conn.execute("SELECT * FROM source WHERE id=?", (source_id,)).fetchone()
        if row is None:
            raise CoreError("source-not-found", id=source_id)
        d = dict(row)
        d["file_snapshot"] = loads(d["file_snapshot"]) if d["file_snapshot"] else None
        d["streams"] = [
            dict(r) | {"is_attached_pic": bool(r["is_attached_pic"])}
            for r in self.conn.execute(
                "SELECT * FROM source_stream WHERE source_id=? ORDER BY kind, ordinal", (source_id,)
            )
        ]
        return d

    def list(self) -> list[dict[str, Any]]:
        """原片列表（按登记时间倒序；分组与计数在界面阶段 2.7 补齐）。"""
        rows = self.conn.execute(
            "SELECT s.id, s.path, s.work, s.episode, s.source_type, s.duration, s.media_state, s.subtitle_path,"
            " s.default_audio_stream, s.created_at, s.version, s.import_root, s.root_id, s.rel_path, s.visual_binding_id IS NOT NULL AS has_picture,"
            " (SELECT COUNT(*) FROM source_stream t WHERE t.source_id=s.id AND t.kind='audio') AS audio_streams,"
            " EXISTS(SELECT 1 FROM source_stream t WHERE t.source_id=s.id AND t.kind='video' AND t.is_attached_pic=0) AS has_video"
            " FROM source s ORDER BY s.created_at DESC, s.rowid DESC"
        )
        # 文件找不到（只看在不在，不核对快照；媒体已释放的另算）：列表里标出来（原型 st-w “文件找不到”）
        return [
            dict(r) | {"has_video": bool(r["has_video"]), "has_picture": bool(r["has_picture"]), "missing": r["media_state"] == "available" and not os.path.exists(r["path"])}
            for r in rows
        ]

    def check_file(self, source_id: str) -> None:
        """播放、导出、处理前核对原片文件（缺失或被替换 → 报错，不回退）。"""
        row = self.conn.execute("SELECT path, file_snapshot FROM source WHERE id=?", (source_id,)).fetchone()
        if row is None:
            raise CoreError("source-not-found", id=source_id)
        probe_mod.check_unchanged(row[0], loads(row[1]) if row[1] else {})

    # ------------------------------------------------------------ 重新定位

    def relocate(self, source_id: str, new_path: str) -> dict[str, Any]:
        """只改位置（R1.3）：换成新文件的快照；流签名与原来不同时如实返回，让界面提示，但不拒绝。"""
        cur = self.get(source_id)
        path = os.path.abspath(new_path)
        key = path_key(path)
        other = self.conn.execute("SELECT id FROM source WHERE path_key=? AND id<>?", (key, source_id)).fetchone()
        if other is not None:
            raise CoreError("source-path-taken", path=path, other=other[0])
        pr = self.probe(path)
        snap = probe_mod.snapshot(path, pr)
        before = (cur["file_snapshot"] or {}).get("streams")
        with transaction(self.conn):
            move_source(self.conn, source_id, path, snap)
        cs = ChangeSet()
        cs.add("source", source_id)
        if self.on_change:
            self.on_change(cs)
        return {"sourceId": source_id, "path": path, "streamsChanged": before != snap["streams"]}

    # ------------------------------------------------------------ 删除

    def _owned(self, source_id: str) -> dict[str, list[str]]:
        q = self.conn.execute
        assets = [r[0] for r in q("SELECT id FROM sound_asset WHERE source_id=?", (source_id,))]
        marks = ",".join("?" * len(assets))
        samples = [r[0] for r in q(f"SELECT id FROM sample WHERE asset_id IN ({marks})", assets)] if assets else []
        return {"asset": assets, "sample": samples}

    def _active_jobs(self, source_id: str, owned: dict[str, list[str]]) -> list[str]:
        hits = []
        for jid, affects in self.conn.execute("SELECT id, affects FROM job WHERE status IN ('queued', 'running')"):
            a = loads(affects) if affects else {}
            if source_id in a.get("source", []) or any(set(a.get(k, [])) & set(v) for k, v in owned.items()):
                hits.append(jid)
        return hits

    def delete_preview(self, source_id: str) -> dict[str, Any]:
        """确认框列明影响（规格 04 §4.5）。"""
        src = self.get(source_id)
        owned = self._owned(source_id)
        q = self.conn.execute
        count = lambda sql, args: q(sql, args).fetchone()[0]  # noqa: E731
        independent = (
            count(
                f"SELECT COUNT(*) FROM sample WHERE independent=1 AND id IN ({','.join('?' * len(owned['sample']))})",
                owned["sample"],
            )
            if owned["sample"]
            else 0
        )
        return {
            "sourceId": source_id,
            "path": src["path"],
            "samples": len(owned["sample"]),
            "independentSamples": independent,
            "generatedAssets": count("SELECT COUNT(*) FROM sound_asset WHERE source_id=? AND origin<>'stream'", (source_id,)),
            "annotations": count("SELECT COUNT(*) FROM annotation WHERE source_id=?", (source_id,)),
            "subtitleVersions": count("SELECT COUNT(*) FROM subtitle_version WHERE source_id=?", (source_id,)),
            "oped": count("SELECT COUNT(*) FROM oped WHERE source_id=?", (source_id,)),
            "activeJobs": self._active_jobs(source_id, owned),
        }

    def delete(self, source_id: str) -> dict[str, Any]:
        preview = self.delete_preview(source_id)
        if preview["activeJobs"]:
            raise CoreError("source-has-active-jobs", id=source_id, jobs=",".join(preview["activeJobs"]))
        if preview["independentSamples"]:
            # 独立化（规格 04 §4.8）在阶段 9 实现：到时保留独立化采样、原片变为“媒体已释放”。现在不静默删掉它们。
            raise CoreError("source-has-independent-samples", id=source_id, n=preview["independentSamples"])
        owned = self._owned(source_id)
        assets, samples = owned["asset"], owned["sample"]
        am, sm = ",".join("?" * len(assets)), ",".join("?" * len(samples))
        library_files: list[str] = []
        with transaction(self.conn):
            x = self.conn.execute
            if samples:
                # 固定结果里的成员保留采样 ID，界面据此显示“已删除”（规格 04 §4.5）
                x(f"DELETE FROM visual_binding WHERE owner_type='sample' AND owner_id IN ({sm})", samples)
                x(f"DELETE FROM sample WHERE id IN ({sm})", samples)
            x("DELETE FROM visual_binding WHERE owner_type='source' AND owner_id=?", (source_id,))
            media: set[str] = set()
            if assets:
                media |= {r[0] for r in x(f"SELECT media_file_id FROM sound_asset WHERE id IN ({am}) AND media_file_id IS NOT NULL", assets)}
                media |= {r[0] for r in x(f"SELECT media_file_id FROM asset_storage WHERE asset_id IN ({am})", assets)}
                runs = [r[0] for r in x(f"SELECT id FROM measure_run WHERE asset_id IN ({am})", assets)]
                if runs:
                    rm = ",".join("?" * len(runs))
                    x(f"DELETE FROM measure_head WHERE run_id IN ({rm})", runs)
                    x(f"DELETE FROM measure_run WHERE id IN ({rm})", runs)
                x(f"DELETE FROM annotation WHERE scope_asset_id IN ({am})", assets)
                x(f"DELETE FROM default_track WHERE asset_id IN ({am})", assets)
                # 生成资产之间有“输入”引用（如分离声部上的拉平），先断开再整体删除
                x(f"UPDATE sound_asset SET input_asset_id=NULL WHERE id IN ({am})", assets)
                x(f"DELETE FROM sound_asset WHERE id IN ({am})", assets)
            x("DELETE FROM source WHERE id=?", (source_id,))
            # 不再被任何对象引用的媒体文件记录：库内文件（为它生成的音轨与成品）连同文件删除；外部文件只删记录
            for mid in media:
                still = x(
                    "SELECT (SELECT COUNT(*) FROM sound_asset WHERE media_file_id=?) + (SELECT COUNT(*) FROM asset_storage WHERE media_file_id=?)"
                    " + (SELECT COUNT(*) FROM visual_binding WHERE media_file_id=?)",
                    (mid, mid, mid),
                ).fetchone()[0]
                if still:
                    continue
                row = x("SELECT path, location FROM media_file WHERE id=?", (mid,)).fetchone()
                if row is not None and row[1] == "library":
                    library_files.append(row[0])
                x("DELETE FROM media_file WHERE id=?", (mid,))
        for rel in library_files:
            self._remove_library_file(rel)
        cs = ChangeSet()
        cs.add("source", source_id)
        for s in samples:
            cs.add("sample", s)
        if self.on_change:
            self.on_change(cs)
        return preview

    def _remove_library_file(self, rel: str) -> None:
        """只删工作区素材库里的文件；路径越出素材库一律不碰。"""
        lib = (self.workspace_root / "Library").resolve()
        p = (self.workspace_root / rel).resolve()
        if lib not in p.parents:
            return
        try:
            p.unlink()
        except FileNotFoundError:
            pass
