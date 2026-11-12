"""分离（规格 05 §5.5、14 §14.6、13 §13.3.2；16 R18）——Core 侧：发现 Studio、模型列表、提交、登记结果。

- 模型列表：轻量任务 ``studio.models`` 跑 Studio 的 list_models，结果缓存在 ``Data/Cache/studio-models.json``（Studio 安装、环境或模型目录变了就失效）。
- 提交（模型通道任务 ``separate``）：输入 = 当前音源资产的选区（整片 = 整个资产），**提交时冻结**；可以一次给多段（``ranges``，所有者 2026-10-30）：
  各段放进同一个任务，worker 把它们拼成一个输入（段间 1 秒静音）分离一次再切回（Studio 按约 22 秒的块推理，短输入也按整块算；
  10 段 × 6 秒实测 31 秒 vs 分开约 100 秒；和单独分离一样接近“放在上下文里分离”的结果）；每段各登记一组声部；模型必须在 Studio 的可用列表里；
  选区分离可选任意模型，整片的“人声方式 / 三轨方式”按能力筛（界面负责，Core 只查模型存在且声部有效）；设备取设置。
- 不做自动复用（所有者 2026-10-30、2026-11-03，DECISIONS §9）：点一次分离就真的跑一次，多出来的音轨由用户删（assets.delete）。
- 登记（任务成功后在 Core 主线程）：每个声部一个新资产——MP3 移入 ``Library/Tracks/<原片>/``；映射 = 输入映射裁到所选区间；
  声部名保留 Studio 原样；记录模型身份（名称、指纹、Studio 版本、文件身份）与参数；按“声部名 → 角色”别名表预填角色（不继承输入角色）；
  **不设默认轨**；整轨分离不建采样，局部分离每个声部自动建一个采样（所有者 2026-10-13）。任何一步失败整次不登记（已移入的文件删掉）。
"""

from __future__ import annotations

import json
import shutil
import sqlite3
from collections.abc import Callable
from pathlib import Path
from typing import Any

from ottosmasher.domain.mapping import Mapping, check_range
from ottosmasher.media import probe as probe_mod
from ottosmasher.store.db import transaction
from ottosmasher.store.workspace import Workspace
from ottosmasher.studio import discovery, protocol

from . import assets as assets_mod
from . import effective_tags
from . import libdirs
from . import settings as settings_mod
from .clock import new_id, now_iso
from .edits import ChangeSet, dumps, loads
from .errors import CoreError
from .samples import checked_local_tags

DEVICES = ("auto", "cpu", "cuda", "mps")


class SeparationService:
    def __init__(self, conn: sqlite3.Connection, ws: Workspace, jobs: Any, on_change: Callable[[ChangeSet], None] | None = None, samples: Any = None) -> None:
        self.samples = samples  # 局部分离自动建采样用（SampleService）
        self.conn = conn
        self.ws = ws
        self.jobs = jobs
        self.on_change = on_change
        jobs.adopters["studio.models"] = self._adopt_models
        jobs.adopters["separate"] = self._adopt_separation

    # ---------- Studio 与模型

    def env(self) -> discovery.StudioEnv:
        v = settings_mod.values(self.conn)
        return discovery.discover(v["studio.app_path"], v["studio.data_dir"])

    @property
    def _cache(self) -> Path:
        return self.ws.data / "Cache" / "studio-models.json"

    @staticmethod
    def _key(env: discovery.StudioEnv) -> list[Any]:
        def stat(p: str) -> list[Any]:
            try:
                st = Path(p).stat()
                return [st.st_size, st.st_mtime_ns]
            except OSError:
                return [None, None]

        return [env.worker, stat(env.worker), env.runtime_file, stat(env.runtime_file), env.model_dir, stat(env.model_dir), env.version,
                sorted([str(p.relative_to(env.model_dir)), *stat(str(p))] for p in Path(env.model_dir).rglob("*") if p.is_file())]

    def status(self, refresh: bool = False) -> dict[str, Any]:
        """设置页与分离确认框用：Studio 在不在、环境、模型列表（缓存；没有或过期就提交一次列模型任务）。"""
        try:
            env = self.env()
        except CoreError as e:
            return {"ok": False, "error": e.to_wire()}
        models = None
        try:
            cached = json.loads(self._cache.read_text(encoding="utf-8"))
            if not refresh and cached.get("key") == self._key(env):
                models = cached["models"]
        except (OSError, ValueError, KeyError):
            pass
        job = None
        if models is None:
            running = self.conn.execute("SELECT id FROM job WHERE kind='studio.models' AND status IN ('queued','running')").fetchone()
            job = running[0] if running else self.jobs.submit("studio.models", {"env": env.wire()})["id"]
        return {"ok": True, "env": env.wire(), "models": models, "listingJob": job}

    def _adopt_models(self, job: dict[str, Any], result: dict[str, Any]) -> None:
        env = discovery.StudioEnv.of(result["env"])
        self._cache.parent.mkdir(parents=True, exist_ok=True)
        tmp = self._cache.with_suffix(".tmp")
        tmp.write_text(json.dumps({"key": self._key(env), "models": result["models"]}, ensure_ascii=False), encoding="utf-8")
        tmp.replace(self._cache)

    def _models(self, env: discovery.StudioEnv) -> list[dict[str, Any]]:
        try:
            cached = json.loads(self._cache.read_text(encoding="utf-8"))
            if cached.get("key") == self._key(env):
                return list(cached["models"])
        except (OSError, ValueError, KeyError):
            pass
        raise CoreError("studio-models-unknown")

    # ---------- 提交

    def submit(self, asset_id: str, start: float | None, end: float | None, model_name: str, stems: list[str] | None,
               ranges: list[list[float]] | None = None, *, local_tags: list[str] | None = None) -> dict[str, Any]:
        asset = assets_mod.get(self.conn, asset_id)
        frame = 1.0 / assets_mod.rate_of(self.conn, asset)
        if ranges is not None and (start is not None or end is not None):
            raise CoreError("range-invalid", reason="ranges-and-start-end", start=start, end=end, duration=asset["duration"])
        if ranges is not None and not ranges:
            raise CoreError("range-invalid", reason="empty", start=None, end=None, duration=asset["duration"])
        wanted = [(r[0], r[1]) for r in ranges] if ranges is not None else [(0.0 if start is None else start, asset["duration"] if end is None else end)]
        spans = [check_range(float(a), float(b), asset["duration"], frame=frame) for a, b in wanted]
        env = self.env()
        model = protocol.find_model(self._models(env), model_name)
        chosen = list(stems) if stems else list(model["stems"])
        bad = [st for st in chosen if st not in model["stems"]]
        if bad or not chosen:
            raise CoreError("sep-stems-invalid", stems=", ".join(bad), model=model["name"])
        inputs: list[dict[str, Any]] = []
        for s0, s1 in dict.fromkeys(spans):  # 同一段给了两次只算一次
            ref, win, media = assets_mod.locate(self.conn, self.ws.root, asset, s0, s1)
            assets_mod.check_media(media)
            sr = ref.sample_rate
            inputs.append({
                "assetId": asset_id,
                "start": s0,
                "end": s1,
                "ref": {k: getattr(ref, k) for k in ("path", "ordinal", "sample_rate", "channels", "codec", "format_name")},
                "a": round(win.to_file(s0) * sr),
                "b": round(win.to_file(s1) * sr),
                "snapshot": media["snapshot"],
            })
        if len({(i["ref"]["sample_rate"], i["ref"]["channels"]) for i in inputs}) > 1:
            # 多段要拼成一个输入：存放在采样率或声道不同的文件里的段（回导拼起来的音轨）分开提交
            raise CoreError("range-invalid", reason="ranges-differ-in-format", start=None, end=None, duration=asset["duration"])
        values = settings_mod.values(self.conn)
        params = {
            "env": env.wire(),
            "model": model,
            "modelStat": protocol.stat_signature(model),
            "stems": chosen,
            "device": values["studio.device"],
            "deviceId": values["studio.device_id"],
            "cache": str(self.ws.data / "Cache"),
            "inputs": inputs,
            "localTags": checked_local_tags(local_tags),
        }
        job = self.jobs.submit("separate", params, {"source": [asset["source_id"]], "asset": [asset_id]})
        return {"job": job}

    # ---------- 登记

    def _adopt_separation(self, job: dict[str, Any], result: dict[str, Any]) -> None:
        params = loads(job["params"])
        inputs = params.get("inputs") or [params["input"]]  # 多段（2026-10-30）；之前的任务只有一段
        items = result.get("items") or [{"stems": result["stems"]}]
        if len(items) != len(inputs):
            raise CoreError("sep-output-invalid", reason="item-count", expected=len(inputs), got=len(items))
        asset = assets_mod.get(self.conn, inputs[0]["assetId"])
        tracks_dir = libdirs.track_dir(self.ws, self.conn, asset["source_id"], "Separation")  # L23：Library/Tracks/<作品 集数> [id8]/Separation/
        aliases = settings_mod.values(self.conn)["separation.role_aliases"]
        moved: list[Path] = []
        created: list[str] = []
        new_samples: list[str] = []
        src_dur = self.conn.execute("SELECT duration FROM source WHERE id=?", (asset["source_id"],)).fetchone()[0]
        try:
            with transaction(self.conn):
                for inp, item in zip(inputs, items, strict=True):
                    self._adopt_one(job, params, result, asset, inp, item["stems"], src_dur, tracks_dir, aliases, moved, created, new_samples)
        except Exception:
            for p in moved:
                p.unlink(missing_ok=True)
            raise
        if self.on_change and created:
            cs = ChangeSet()
            for a in created:
                cs.add("asset", a)
            for sid in new_samples:
                cs.add("sample", sid)
            cs.add("source", asset["source_id"])
            self.on_change(cs)

    def _adopt_one(self, job: dict[str, Any], params: dict[str, Any], result: dict[str, Any], asset: dict[str, Any], inp: dict[str, Any],
                   stems: list[dict[str, Any]], src_dur: float | None, tracks_dir: Path, aliases: Any,
                   moved: list[Path], created: list[str], new_samples: list[str]) -> None:
        """一段输入的各声部：在调用方的事务里登记（任何一段失败整个任务都不登记）。"""
        mapping = Mapping.of(asset["mapping"]).crop(inp["start"], inp["end"])
        partial = src_dur is None or not mapping.is_full_track(float(src_dur))
        for st in stems:
            mid, aid, ts = new_id(), new_id(), now_iso()
            target = tracks_dir / f"{aid}.mp3"
            shutil.move(st["mp3"], target)
            moved.append(target)
            pr = probe_mod.probe(target)
            rel = target.relative_to(self.ws.root).as_posix()
            self.conn.execute(
                "INSERT INTO media_file(id, path, location, file_snapshot, format, sample_rate, frames, encode_manifest, created_at)"
                " VALUES (?, ?, 'library', ?, 'mp3', ?, ?, ?, ?)",
                (mid, rel, dumps(probe_mod.snapshot(target, pr)), st["rate"], st["frames"], dumps(st["manifest"]), ts),
            )
            duration = st["frames"] / st["rate"]
            production = {
                "op": "separate",
                "model": params["model"]["name"],
                "modelStat": params["modelStat"],
                "fingerprint": result["fingerprint"],
                "studioVersion": result["studioVersion"],
                "stems": params["stems"],
                "device": params["device"],
                "job": job["id"],
            }
            self.conn.execute(
                "INSERT INTO sound_asset(id, source_id, origin, media_file_id, duration, mapping, input_asset_id, input_start, input_end,"
                " stem_name, production, language, created_at) VALUES (?, ?, 'separation', ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    aid, asset["source_id"], mid, duration, dumps(_fit(mapping, duration).to_list()), inp["assetId"],
                    inp["start"], inp["end"], st["stem"], dumps(production), asset["language"], ts,
                ),
            )  # fmt: skip
            self.conn.execute(
                "INSERT INTO asset_storage(asset_id, range_start, range_end, media_file_id, kind) VALUES (?, 0, ?, ?, 'primary')",
                (aid, duration, mid),
            )
            assets_mod.prefill_roles(self.conn, aid, assets_mod.roles_for_stem(st["stem"], aliases))
            created.append(aid)
            # 局部分离（对选区）= 某一段的另一个版本，属于采样那一侧：和拉平、回导一样自动建一个采样（所有者 2026-10-13）；
            # 整轨分离是原素材的音轨，不建采样。名称 = 这段的建议名 · 声部，性质按声部角色
            if partial and self.samples is not None:
                name = self.samples.suggest(aid, 0.0, duration)["name"]
                sid = self.samples.insert_checked(aid, 0.0, duration, name=f"{name} \u00b7 {st['stem']}"[:500], created_via="processed",
                                                  local_tags=params.get("localTags"), origin={"kind": "separation", "job": job["id"], "stem": st["stem"]})
                effective_tags.refresh(self.conn, [sid])
                new_samples.append(sid)

    def results(self, job_id: str) -> list[dict[str, Any]]:
        """任务抽屉「打开结果」：这个分离任务登记的声音资产。"""
        rows = self.conn.execute("SELECT id FROM sound_asset WHERE origin='separation' AND production LIKE ?", (f'%"job":"{job_id}"%',))
        return [assets_mod.get(self.conn, r[0]) for r in rows]


def _fit(mapping: Mapping, duration: float) -> Mapping:
    """输出时长与输入相差不超过一帧：映射的局部终点按实际文件时长对齐（原片时间不变）。"""
    pts = mapping.to_list()
    pts[-1][0] = duration
    return Mapping.of(pts)


def validate_device(v: Any) -> str:
    if v not in DEVICES:
        raise CoreError("setting-invalid", reason="not-an-option")
    return str(v)
