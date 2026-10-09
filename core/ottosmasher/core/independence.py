"""采样独立化（规格 04 §4.8 刚需、§4.5；ARCHITECTURE §4.9；Q4；L32）。

- 声音：把采样绑定资产的 [start, end)（两端各留 1 帧余量，按原文件的样本对齐）解码成**无损 WAV 切片**——源是 16/24 位整数 PCM（含 FLAC 等无损）
  时用 24 位整数（16/24 位样本都原样保存），否则（MP3 正式音轨、浮点源）用 32 位浮点，与解码结果逐样本相同——作为该资产的
  ``asset_storage(kind=materialized_slice)``。采样的绑定（资产 + 区间）不变：测量（按资产）、固定结果、来源记录都照常有效。
  切片的快照里记着“它来自哪段存储”（原媒体 ID、快照、音频流、窗口），分析与 F0 的身份按原存储认（``assets.measured_as``），所以**读到的分析继续可读**（L32）。
- 画面：有效画面是原片自带的视频流时，按同步规则生成这段的视频片段（每帧取最近的源帧），作为采样的画面绑定（``materialized_clip``，偏移 = −片段起点的原片秒）。
  绑定的是外部图片 / 动画 / 视频文件时不复制（那些文件不随原片删除）。
- 位置：``Library/Independent/<作品 集数> [id8]/``。耗时（解码、编码视频）→ 轻量通道的任务「采样独立化」；登记在 Core 主线程、一个事务。
- 删除原片时可勾选要独立化的采样：任务完成后接着删除原片，原片记录保留为“媒体已释放”（``SourceService.delete(release=True)``）。
"""

from __future__ import annotations

import math
import shutil
import sqlite3
from pathlib import Path
from typing import Any

from ..domain import filename as fname
from ..domain.mapping import Mapping
from ..media import decode as dec
from ..media import probe as probe_mod
from ..media import video as video_mod
from ..media import wavfile
from ..store.db import transaction
from ..store.workspace import Workspace
from . import assets as assets_mod
from . import libdirs, visuals
from .clock import new_id, now_iso
from .edits import ChangeSet, dumps, loads
from .errors import CoreError

JOB_KIND = "samples.independ"
LOSSLESS = {"flac", "alac", "wavpack", "ape", "tta", "mlp", "truehd"}


def _int_lossless(codec: str | None, bits: int | None) -> bool:
    c = (codec or "").lower()
    return (c.startswith("pcm_s16") or c.startswith("pcm_s24") or c in LOSSLESS) and (bits or 16) in (16, 24)


class IndependenceService:
    def __init__(self, conn: sqlite3.Connection, ws: Workspace, jobs: Any, sources: Any, on_change: Any = None) -> None:
        self.conn = conn
        self.ws = ws
        self.jobs = jobs
        self.sources = sources
        self.on_change = on_change
        jobs.adopters[JOB_KIND] = self._adopt

    # ------------------------------------------------------------ 计划

    def plan(self, ids: list[str]) -> list[dict[str, Any]]:
        """每个采样：时长、切片大约多大、要不要生成画面片段、是否已独立化。"""
        out = []
        for sid in dict.fromkeys(ids):
            r = self.conn.execute('SELECT s.id, s.name, s.asset_id, s.start, s."end", s.independent FROM sample s WHERE s.id = ?', (sid,)).fetchone()
            if r is None:
                raise CoreError("sample-not-found", id=sid)
            asset = assets_mod.get(self.conn, r["asset_id"])
            try:
                ref, _win, _media = assets_mod.locate(self.conn, self.ws.root, asset, float(r["start"]), float(r["end"]))
                frames = (float(r["end"]) - float(r["start"])) * ref.sample_rate
                size = int(frames * ref.channels * (3 if _int_lossless(ref.codec, None) else 4))
            except CoreError:
                size = 0
            b = visuals.resolve(self.conn, sample_id=sid, root=self.ws.root)
            out.append({"id": sid, "name": r["name"], "duration": float(r["end"]) - float(r["start"]), "bytes": size,
                        "picture": bool(b and b["origin"] == "stream"), "independent": bool(r["independent"])})
        return out

    def submit(self, ids: list[str], delete_source: str | None = None) -> dict[str, Any]:
        items = []
        for sid in dict.fromkeys(ids):
            r = self.conn.execute('SELECT id, name, asset_id, start, "end", independent FROM sample WHERE id = ?', (sid,)).fetchone()
            if r is None:
                raise CoreError("sample-not-found", id=sid)
            if r["independent"]:
                continue
            asset = assets_mod.get(self.conn, r["asset_id"])
            if delete_source and asset["source_id"] != delete_source:
                raise CoreError("independ-invalid", reason="other-source", id=sid)
            start, end = float(r["start"]), float(r["end"])
            ref, win, media = assets_mod.locate(self.conn, self.ws.root, asset, start, end)
            assets_mod.check_media(media)
            sr = ref.sample_rate
            # 两端各留 1 帧余量，按原文件的样本对齐（切片里第 k 个样本 = 原文件第 a0 + k 个样本）
            a0 = max(round(win.to_file(win.local_start) * sr), round(win.to_file(start) * sr) - 1)
            b0 = min(round(win.to_file(win.local_end) * sr), round(win.to_file(end) * sr) + 1)
            fmt = "s24" if _int_lossless(ref.codec, _bits(self.conn, asset)) else "f32"
            item: dict[str, Any] = {
                "sample": sid, "asset": asset["id"], "source": asset["source_id"], "name": r["name"],
                "file": {"path": ref.path, "ordinal": ref.ordinal, "sample_rate": sr, "channels": ref.channels, "codec": ref.codec, "format": ref.format_name},
                "frames": [a0, b0], "local": [win.to_local(a0 / sr), win.to_local(b0 / sr)], "fmt": fmt,
                "from": {**assets_mod.measured_as(media, win), "media_file_id": assets_mod.measured_as(media, win)["media"]},
                "wav": str(self.ws.staging / f"{new_id()}.wav"),
            }
            b = visuals.resolve(self.conn, sample_id=sid, root=self.ws.root)
            if b is not None and b["origin"] == "stream":
                visuals.check_ok(b)
                mapping = Mapping.of(asset["mapping"])
                info = video_mod.info(b["path"], int(b["ordinal"]))
                s0 = mapping.to_source(start)
                n = video_mod.frame_count(end - start, info.fps)
                times = []
                for k in range(n):
                    t = min(k / info.fps, end - start)
                    times.append(round(mapping.to_source(min(start + t, mapping.duration)), 6))
                item["video"] = {"out": str(self.ws.staging / f"{new_id()}.mp4"), "frames": n, "fps": info.fps, "size": [info.width, info.height],
                                 "picture": {"kind": "video", "path": b["path"], "ordinal": int(b["ordinal"]), "start": info.start, "end": info.end},
                                 "times": times, "s0": s0, "duration": end - start}
            items.append(item)
        if not items and not delete_source:
            raise CoreError("independ-invalid", reason="nothing")
        self.ws.staging.mkdir(parents=True, exist_ok=True)
        affects = {"sample": [i["sample"] for i in items], "source": sorted({i["source"] for i in items} | ({delete_source} if delete_source else set()))}
        return self.jobs.submit(JOB_KIND, {"items": items, "deleteSource": delete_source, "cache": str(self.ws.data / "Cache")}, affects)

    # ------------------------------------------------------------ 登记

    def _adopt(self, job: dict[str, Any], result: dict[str, Any]) -> None:
        params = loads(job["params"])
        made: list[Path] = []
        cs = ChangeSet()
        try:
            with transaction(self.conn):
                for it in params["items"]:
                    cur = self.conn.execute('SELECT asset_id, independent FROM sample WHERE id = ?', (it["sample"],)).fetchone()
                    if cur is None or cur["independent"] or cur["asset_id"] != it["asset"]:
                        continue  # 期间被删或已独立化：不登记
                    d = libdirs.independent_dir(self.ws, self.conn, it["source"])
                    stem = fname.truncate_utf8(fname.portable(it["name"]), 100).strip(" .") or "sample"
                    wav = d / f"{stem}__{it['sample'][:12]}.wav"
                    shutil.move(it["wav"], wav)
                    made.append(wav)
                    pr = probe_mod.probe(wav)
                    snap = {**probe_mod.snapshot(wav, pr), "from": it["from"]}
                    mid, ts = new_id(), now_iso()
                    self.conn.execute(
                        "INSERT INTO media_file(id, path, location, file_snapshot, format, sample_rate, frames, created_at) VALUES (?, ?, 'library', ?, 'wav', ?, ?, ?)",
                        (mid, wav.relative_to(self.ws.root).as_posix(), dumps(snap), it["file"]["sample_rate"], it["frames"][1] - it["frames"][0], ts),
                    )
                    self.conn.execute(
                        "INSERT INTO asset_storage(asset_id, range_start, range_end, media_file_id, kind) VALUES (?, ?, ?, ?, 'materialized_slice')",
                        (it["asset"], it["local"][0], it["local"][1], mid),
                    )
                    vid = None
                    if it.get("video"):
                        mp4 = d / f"{stem}__{it['sample'][:12]}.mp4"
                        shutil.move(it["video"]["out"], mp4)
                        made.append(mp4)
                        vid = visuals.prepare(self.conn, "sample", it["sample"], str(mp4), mode="materialized_clip", offset=-float(it["video"]["s0"]),
                                              location="library", root=self.ws.root)
                    self.conn.execute(
                        "UPDATE sample SET independent = 1, visual_binding_id = COALESCE(?, visual_binding_id), updated_at = ? WHERE id = ?",
                        (vid, ts, it["sample"]),
                    )
                    cs.add("sample", it["sample"])
                    cs.add("asset", it["asset"])
        except Exception:
            for p in made:
                p.unlink(missing_ok=True)
            raise
        if self.on_change and cs.entities:
            self.on_change(cs)
        if params.get("deleteSource"):
            self.sources.delete(params["deleteSource"], release=True, skip_jobs=(job["id"],))  # 这个任务自己还算“运行中”


def _bits(conn: sqlite3.Connection, asset: dict[str, Any]) -> int | None:
    if asset["origin"] != "stream":
        return None
    r = conn.execute("SELECT bit_depth FROM source_stream WHERE source_id = ? AND kind = 'audio' AND ordinal = ?", (asset["source_id"], asset["stream_ordinal"])).fetchone()
    return r[0] if r else None


def run_job(params: dict[str, Any], ctx: Any) -> dict[str, Any]:
    """（任务进程）解码切片写 WAV；需要时生成画面片段。不碰数据库。"""
    items = params["items"]
    cache = Path(params["cache"])
    for i, it in enumerate(items):
        ctx.progress("slice", i, len(items))
        f = it["file"]
        ref = dec.StreamRef(f["path"], int(f["ordinal"]), int(f["sample_rate"]), int(f["channels"]), f["codec"], f["format"])
        pcm = dec.decode_frames(ref, int(it["frames"][0]), int(it["frames"][1]), cache=cache)
        if it["fmt"] == "s24":
            wavfile.save_wav24(Path(it["wav"]), pcm, int(f["sample_rate"]))
        else:
            wavfile.save_wav_f32(Path(it["wav"]), pcm, int(f["sample_rate"]))
        v = it.get("video")
        if v:
            times = [math.nan if x is None else float(x) for x in v["times"]]
            video_mod.render(Path(v["out"]), frames=int(v["frames"]), fps=float(v["fps"]), size=(int(v["size"][0]), int(v["size"][1])),
                             picture=v["picture"], times=times, audio=None, duration=float(v["duration"]))
    ctx.progress("slice", len(items), len(items))
    return {"n": len(items)}
