"""视频片段导出（规格 12 §12.5、16 R21.9、S7；UI_PLAN §8「导出视频片段…」；Q8：没有画面报错，不生成黑屏）。

- 画面来源按 12 §12.4 的有效画面（采样 > 原片 > 原片自带视频流）；同步视频取原片对应时间段（+ 偏移），图片生成静止视频，循环动画按“本地时间 mod 时长”。
- 版本：原声（画面原速）；卡拍有两种——**同映射变速**（每个输出帧按卡拍映射的逆找原片时间，音画同步）或**原速画面**
  （画面与卡拍音频时长不同：默认带原声，另存卡拍 WAV 与映射清单，推定 A24）。
- 取帧：每个输出帧取最近的源帧，不插帧；超出视频流的部分补黑帧并在完成提示里说明，不移动音频（推定 A24）。
- 帧率跟随画面（同步视频 = 原片视频的帧率；图片 / 循环且无原片视频 = 动画自身帧率，图片 30 fps）；分辨率跟随画面。
- 格式：默认 H.264 MP4 + AAC，设置「导出 → 视频编码」可选高质量中间编码（ProRes 422 HQ MOV + PCM）；可选不带声音。
- 命名与位置同 WAV 导出（扩展名不同）；按稳定键复用，被外部改过报错不覆盖；导出文件从不自动删除。
- 编码在“导出视频片段”任务里做（轻量通道，可取消）；完成后发 ``exports.videoDone``（文件、补黑帧数）。
时钟：输出秒 = 片段时间；原片秒经资产映射；画面文件秒 = 原片秒 + 偏移（同步）。
"""

from __future__ import annotations

import hashlib
import math
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Any

from ..domain import filename as fname
from ..domain.mapping import Mapping
from ..media import decode as dec
from ..media import video as video_mod
from ..media import wavfile
from ..store.workspace import Workspace
from . import assets as assets_mod
from . import settings as settings_mod
from . import visuals
from .clock import new_id, now_iso
from .edits import dumps, loads
from .errors import CoreError
from .exports import _sha256, processing_label, track_label

JOB_KIND = "export.video"
VERSIONS = ("original", "stretched")
PICTURES = ("synced", "original")  # 卡拍版的画面：同映射变速 / 原速画面
IMAGE_FPS = 30.0


class VideoExportService:
    def __init__(self, conn: sqlite3.Connection, ws: Workspace, exports: Any, handoff: Any, jobs: Any, emit: Any = None) -> None:
        self.conn = conn
        self.ws = ws
        self.exports = exports
        self.handoff = handoff
        self.jobs = jobs
        self.emit = emit
        jobs.adopters[JOB_KIND] = self._adopt

    # ------------------------------------------------------------ 计划

    def _picture(self, b: dict[str, Any]) -> tuple[dict[str, Any], float, tuple[int, int]]:
        visuals.check_ok(b)
        info = video_mod.info(b["path"], int(b["ordinal"]))
        if b["mode"] == "image":
            fps = IMAGE_FPS
            pic = {"kind": "image", "path": b["path"], "ordinal": 0, "start": 0.0, "end": 0.0}
        elif b["mode"] == "loop":
            fps = info.fps
            pic = {"kind": "loop", "path": b["path"], "ordinal": int(b["ordinal"]), "start": info.start, "end": info.end}
        else:
            fps = info.fps
            pic = {"kind": "video", "path": b["path"], "ordinal": int(b["ordinal"]), "start": info.start, "end": info.end}
        return pic, fps, (info.width, info.height)

    def sample(self, sample_id: str, *, version: str = "original", picture: str = "synced", audio: bool = True, words: dict[str, str] | None = None,
               plan: str = "near_fast", mora: bool = False, long_vowel: bool = False) -> dict[str, Any]:
        """整个采样导出视频片段：返回 ``{reused: true, path}``（同样的请求已导出过）或排队的任务摘要 ``{job}``。"""
        words = words or {}
        if version not in VERSIONS or picture not in PICTURES:
            raise CoreError("video-export-invalid", reason="not-an-option")
        row = self.conn.execute('SELECT id, asset_id, start, "end", name FROM sample WHERE id = ?', (sample_id,)).fetchone()
        if row is None:
            raise CoreError("sample-not-found", id=sample_id)
        b = visuals.resolve(self.conn, sample_id=sample_id, root=self.ws.root)
        if b is None:
            raise CoreError("visual-none", id=sample_id)  # Q8：不生成黑屏，界面给「画面绑定…」
        stretched = None
        if version == "stretched":
            start = float(row["start"])
            an, s, cells, pcm, sr = self.handoff.rhythm.stretched_pcm(sample_id, plan, mora, long_vowel)
            m = s.map
            stretched = {
                "pcm": pcm, "sr": sr, "bpm": s.bpm, "key": [an.identity, plan, s.density, s.bpm, cells],
                "inner": Mapping.of([[0.0, start]] + [[t / m.sr, start + src / m.sr] for src, t in m.knots[1:]]),
                "wav": lambda: self.handoff.export_stretched(sample_id, words, plan, mora, long_vowel)["path"],
            }
        return self._plan(row["asset_id"], float(row["start"]), float(row["end"]), b, content=row["name"], version=version, picture=picture,
                          audio=audio, words=words, sample_id=sample_id, stretched=stretched)

    def range(self, asset_id: str, start: float, end: float, content: str, *, audio: bool = True, words: dict[str, str] | None = None,
              sample_id: str | None = None, version: str = "original", picture: str = "synced", stretched: dict[str, Any] | None = None) -> dict[str, Any]:
        """资产的一段（原片页选区、检索命中）：画面按有效画面（命中所在的采样 > 原片绑定 > 原片视频流）。
        卡拍版只有命中有（``stretched`` = 命中证据所选方案的渲染与映射，见 ``HitService.stretched_video``）。"""
        if version not in VERSIONS or picture not in PICTURES or (version == "stretched") != (stretched is not None):
            raise CoreError("video-export-invalid", reason="not-an-option")
        asset = assets_mod.get(self.conn, asset_id)
        b = visuals.resolve(self.conn, sample_id=sample_id, root=self.ws.root) if sample_id else visuals.resolve(self.conn, source_id=asset["source_id"], root=self.ws.root)
        if b is None:
            raise CoreError("visual-none", id=sample_id or asset["source_id"])
        return self._plan(asset_id, start, end, b, content=content, version=version, picture=picture, audio=audio, words=words or {},
                          range_sample=sample_id, stretched=stretched)

    def _plan(self, asset_id: str, start: float, end: float, b: dict[str, Any], *, content: str, version: str, picture: str, audio: bool,
              words: dict[str, str], sample_id: str | None = None, range_sample: str | None = None, stretched: dict[str, Any] | None = None) -> dict[str, Any]:
        """``stretched``（卡拍版）：``pcm``/``sr`` 卡拍音频、``inner`` 输出秒 → 资产局部秒的映射、``bpm``、``key`` 稳定键里的方案部分、
        ``wav()`` 另存卡拍 WAV（原速画面用）。"""
        asset = assets_mod.get(self.conn, asset_id)
        mapping = Mapping.of(asset["mapping"])
        pic, fps, size = self._picture(b)
        codec = str(settings_mod.values(self.conn)["export.video_codec"])
        ext = "mov" if codec == "prores" else "mp4"
        processing = processing_label(asset, words)
        extra: dict[str, Any] = {}
        # 输出秒 → 原片秒（帧取哪一刻）与输出秒 → 采样本地秒（循环动画）
        if version == "stretched":
            if stretched is None:
                raise CoreError("video-export-invalid", reason="stretched-needs-sample")
            stretch = f"{words.get('stretch', 'stretch')}-{_bpm(stretched['bpm'])}BPM"
            processing = "_".join(x for x in (processing, stretch) if x)
            ver_key: list[Any] = ["stretched", *stretched["key"], picture]
            if picture == "synced":
                duration = len(stretched["pcm"]) / stretched["sr"]
                to_local = stretched["inner"].to_source  # 输出秒 → 资产局部秒
                audio_pcm, audio_sr = stretched["pcm"], stretched["sr"]
            else:
                # 原速画面：画面与原声同长，默认带原声；卡拍 WAV 与映射清单另存（12 §12.5）
                duration = end - start
                to_local = lambda t: start + t  # noqa: E731
                audio_pcm, audio_sr = None, None
                processing = "_".join(x for x in (processing, words.get("originalSpeed", "orig-speed")) if x)
                extra["stretchedWav"] = stretched["wav"]()
        else:
            duration = end - start
            to_local = lambda t: start + t  # noqa: E731
            audio_pcm, audio_sr = None, None
            ver_key = ["original"]
        frames = video_mod.frame_count(duration, fps)
        times: list[float] = []
        for k in range(frames):
            t = min(k / fps, duration)
            local = to_local(t)
            try:
                src = mapping.to_source(min(max(local, 0.0), mapping.duration))
            except CoreError:
                src = None
            times.append(visuals.picture_time(b, src, local - start))
        ref, win, media = assets_mod.locate(self.conn, self.ws.root, asset, start, end)
        assets_mod.check_media(media)
        snap = _stat_key(b["path"])
        key = hashlib.sha256(dumps([
            "video", asset_id, media["media_file_id"], media["snapshot"], round(start, 6), round(end, 6), *ver_key, b["mode"], b["path"], snap,
            b["offset"], audio, codec, content, ext,
        ]).encode()).hexdigest()
        src_row = self.conn.execute("SELECT id, path FROM source WHERE id = ?", (asset["source_id"],)).fetchone()
        name = fname.export_filename(fname.ExportNameParts(
            content=content, track=track_label(asset, words), source_name=Path(src_row[1]).stem, source_id=src_row[0],
            start=mapping.to_source(start), end=mapping.to_source(end), export_key=key,
            processing="_".join(x for x in (processing, words.get("video", "video")) if x), ext=ext,
        ))
        target_dir = self.ws.library / "Exports" / datetime.now().strftime("%Y-%m-%d")
        reuse = self.conn.execute("SELECT path, size, mtime_ns FROM export_file WHERE stable_key = ?", (key,)).fetchone()
        if reuse is not None and Path(reuse[0]).is_file():
            st = Path(reuse[0]).stat()
            if (st.st_size, st.st_mtime_ns) != (reuse[1], reuse[2]):
                raise CoreError("export-modified", path=reuse[0])
            return {"reused": True, "path": reuse[0], "job": None, **extra}
        target = target_dir / name
        if target.exists():
            raise CoreError("export-exists", path=str(target))
        # 声音：同 WAV 导出的内容（原声 = 资产区间的真实样本；卡拍 = 渲染结果），写进暂存目录交给任务
        audio_path = None
        if audio:
            self.ws.staging.mkdir(parents=True, exist_ok=True)
            audio_path = self.ws.staging / f"{new_id()}.wav"
            if audio_pcm is None:
                sr = ref.sample_rate
                a, bb = round(win.to_file(start) * sr), round(win.to_file(end) * sr)
                audio_pcm, audio_sr = dec.decode_frames(ref, a, bb, cache=self.ws.data / "Cache"), sr
            wavfile.save_wav24(audio_path, audio_pcm, int(audio_sr))
        params = {
            "out": str(self.ws.staging / f"{new_id()}.{ext}"), "target": str(target), "key": key, "frames": frames, "fps": fps, "size": list(size),
            "picture": pic, "times": [None if not math.isfinite(x) else round(x, 6) for x in times], "audio": str(audio_path) if audio_path else None,
            "codec": codec, "duration": duration, "content": content,
            "manifest": {"kind": "video", "asset": asset_id, "range": [start, end], "version": version, "picture": picture, "binding": {k: b[k] for k in ("origin", "mode", "path", "offset")},
                         "fps": fps, "frames": frames, "sample": sample_id},
        }
        owner = sample_id or range_sample
        job = self.jobs.submit(JOB_KIND, params, {"sample": [owner] if owner else [], "source": [asset["source_id"]]})
        return {"reused": False, "path": None, "job": job, **extra}

    # ------------------------------------------------------------ 登记

    def _adopt(self, job: dict[str, Any], result: dict[str, Any]) -> None:
        params = loads(job["params"])
        staged = Path(params["out"])
        target = Path(params["target"])
        try:
            target.parent.mkdir(parents=True, exist_ok=True)
            self.exports._publish(staged, target)
        finally:
            staged.unlink(missing_ok=True)
            if params.get("audio"):
                Path(params["audio"]).unlink(missing_ok=True)
        st = target.stat()
        kind = "video"
        self.conn.execute(
            "INSERT OR REPLACE INTO export_file(stable_key, path, kind, size, mtime_ns, sha256, created_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (params["key"], str(target), kind, st.st_size, st.st_mtime_ns, _sha256(target), now_iso()),
        )
        d = self.ws.data / "Manifests"
        d.mkdir(parents=True, exist_ok=True)
        (d / f"{params['key'][:24]}.json").write_text(dumps({**params["manifest"], "file": str(target), "black": result.get("black", 0),
                                                             "createdAt": now_iso()}), encoding="utf-8")
        if self.emit:
            self.emit("exports.videoDone", {"path": str(target), "black": int(result.get("black", 0)), "fps": params["fps"], "content": params["content"]})


def _bpm(v: float) -> str:
    from .handoff import bpm_text

    return bpm_text(v)


def _stat_key(path: str) -> list[int]:
    try:
        st = Path(path).stat()
    except OSError:
        return [0, 0]
    return [st.st_size, st.st_mtime_ns]


def run_job(params: dict[str, Any], ctx: Any) -> dict[str, Any]:
    """（任务进程）按计划逐帧写视频。"""
    times = [math.nan if x is None else float(x) for x in params["times"]]
    res = video_mod.render(
        Path(params["out"]), frames=int(params["frames"]), fps=float(params["fps"]), size=(int(params["size"][0]), int(params["size"][1])),
        picture=params["picture"], times=times, audio=params.get("audio"), codec=params["codec"], duration=float(params["duration"]),
        progress=lambda d, n: ctx.progress("encode", d, n),
    )
    ctx.progress("encode", int(params["frames"]), int(params["frames"]))
    return {"black": res["black"]}
