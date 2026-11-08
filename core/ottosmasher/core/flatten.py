"""拉平（规格 11）：Core 侧——打开时冻结、缓存预估、提交（单个 / 批量都是一个任务、逐条 job_item）、登记成品、结果与只重跑失败项。

- 打开拉平台时冻结音源（声音资产）与外选区 [a, b) 和存放它的文件快照；提交时核对，变了就报“声音资产已改变，请重新打开”。
- 处理范围与定音方式都由用户选，默认值按入口（设置「拉平」组：采样详情 / 其他单个入口 / 批量）给出；改范围不自动改定音（Q6）。
  批量只有段内自动 / 交界自动（Q10【基线变更】：没有手动、没有内部拉平）。
- 仅元音 / 首元音起需要覆盖外选区的音素（所有者 2026-10-12：音素属于原素材时间线，拉平成品、局部声部上也读得到，所以拉平后还能再拉平）：
  从采样打开 = 采样读到的结果，否则 = 与选区交叠的段的音素换到这条轨上；没有就拒绝并说明（批量里该项单独失败）。
- 预估只读已缓存的测量（不跑模型）：输入资产的 F0 帧与对齐结果里存的有效范围；没有就“任务中分析确定”。
- 登记（任务成功后在主线程，一个事务）：每个成功条目一个新资产（origin=flatten，MP3 V0 放 Library/Tracks/<原片>/Flatten/，映射 = 输入映射裁到外选区，
  继承输入资产的角色，production 记目标音、范围、实际处理区间、定音方式与参考、内区与过渡、算法与模型身份、输入指纹）+ 成品 F0 测量 +
  **一个**调谐单音采样（有效标签 ``pitch:音名`` 由 effective_tags 按绑定资产的 production 实时求值）。
  相同输入 + 相同参数 + 相同模型的成品音频复用，但采样永远新建。取消 → 不登记；失败 → 不留任何登记。
时钟：资产区间是资产局部秒；送进任务的音素、内区是输入局部秒（外选区起点 = 0）。
"""

from __future__ import annotations

import hashlib
import json
import shutil
import sqlite3
from collections.abc import Callable
from pathlib import Path
from typing import Any

import numpy as np

from ..algo import flatten as fl
from ..domain.mapping import Mapping, check_range
from ..media import probe as probe_mod
from ..models import fcpe, hifigan, registry
from ..store.db import transaction
from ..store.workspace import Workspace
from . import assets as assets_mod
from . import libdirs
from . import effective_tags
from . import settings as settings_mod
from . import units
from .clock import new_id, now_iso
from .edits import ChangeSet, dumps, loads
from .errors import CoreError
from .probes import record_probes

JOB_KIND = "flatten"
ENTRIES = ("detail", "single", "batch")


def _sha(obj: Any) -> str:
    return hashlib.sha256(json.dumps(obj, sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode("utf-8")).hexdigest()


def defaults_for(values: dict[str, Any], entry: str) -> dict[str, str]:
    if entry not in ENTRIES:
        raise CoreError("flatten-invalid", reason="not-an-option", field="entry")
    return {"range": values[f"flatten.{entry}_range"], "target": values[f"flatten.{entry}_target"], "side": "left"}


class FlattenService:
    def __init__(self, conn: sqlite3.Connection, ws: Workspace, jobs: Any, support_dir: Path, speech: Any, samples: Any,
                 on_change: Callable[[ChangeSet], None] | None = None) -> None:  # fmt: skip
        self.conn = conn
        self.ws = ws
        self.jobs = jobs
        self.support_dir = support_dir
        self.speech = speech
        self.samples = samples
        self.on_change = on_change
        jobs.adopters[JOB_KIND] = self._adopt

    # ------------------------------------------------------------ 冻结

    def _freeze(self, asset_id: str, start: float, end: float) -> dict[str, Any]:
        asset = assets_mod.get(self.conn, asset_id)
        start, end = check_range(float(start), float(end), float(asset["duration"]), frame=1.0 / assets_mod.rate_of(self.conn, asset))
        ref, win, media = assets_mod.locate(self.conn, self.ws.root, asset, start, end)
        assets_mod.check_media(media)
        snap = {k: (media["snapshot"] or {}).get(k) for k in ("size", "mtime_ns")}
        # 界面拿着令牌：文件快照写成字符串指纹（mtime_ns 超过 2^53，经过 JS 会丢精度）
        return {"assetId": asset_id, "start": start, "end": end, "media": media["media_file_id"], "snapshot": _sha(snap)[:32], "_snap": snap}

    def _check_frozen(self, token: dict[str, Any]) -> tuple[dict[str, Any], Any, Any, dict[str, Any]]:
        """提交时核对冻结的资产与外选区：资产没了、存放文件换了或被改动 → “声音资产已改变”。"""
        try:
            asset = assets_mod.get(self.conn, token["assetId"])
            ref, win, media = assets_mod.locate(self.conn, self.ws.root, asset, float(token["start"]), float(token["end"]))
            assets_mod.check_media(media)
        except CoreError:
            raise CoreError("flatten-asset-changed") from None
        snap = {k: (media["snapshot"] or {}).get(k) for k in ("size", "mtime_ns")}
        if media["media_file_id"] != token.get("media") or _sha(snap)[:32] != token.get("snapshot"):
            raise CoreError("flatten-asset-changed")
        return asset, ref, win, media | {"snap": snap}

    # ------------------------------------------------------------ 对齐（音素属于原素材时间线）

    def _alignment(self, asset_id: str, start: float, end: float, snap: dict[str, Any], sample_id: str | None, issues: list[dict[str, Any]] | None = None) -> dict[str, Any] | None:
        """选区上的音素（所有者 2026-10-12：音素属于原素材时间线，拉平成品、局部声部也读得到）。从采样打开、选区就是这个采样 → 采样读到的结果；
        否则 → 与选区（换算成原片秒）正长度交叠的段的音素，换到这条轨上。读到的段的对齐窗口要连起来覆盖整个选区
        （覆盖不全 = 不可用，不静默少算元音）；这条轨不含人声、任何一段不可用或两段音素冲突 → 不可用。``snap`` 不再参与（音素不按文件指纹拦）。"""
        def unavailable(reason: str, **args: Any) -> None:
            if issues is not None:
                issues.append(CoreError("flatten-needs-alignment", reason=reason, **args).to_wire())
            return None

        asset = assets_mod.get(self.conn, asset_id)
        if not units.voiced(asset):
            return unavailable("track-without-vocal-role")
        try:
            m = Mapping.of(asset["mapping"])
            a, b = m.to_source(start), m.to_source(end)
        except CoreError:
            return unavailable("mapping-unavailable")
        if sample_id:
            s = self.conn.execute(f"SELECT {self.speech._SAMPLE_COLS} FROM sample WHERE id=?", (sample_id,)).fetchone()
            if s is not None and s["asset_id"] == asset_id and abs(s["start"] - start) < 1e-6 and abs(s["end"] - end) < 1e-6:
                rd = self.speech.reading(s)
                head = rd["head"]
                if head is None:
                    return unavailable("sample-analysis-unavailable", sampleId=sample_id, blocked=rd.get("blocked"), conflict=rd.get("conflict"))
                if not self._covers([v.get("windowSource") for v in rd["units"] if v["head"]], a, b):
                    return unavailable("analysis-window-incomplete")
                phones = [{"label": p.get("orig", p["label"]), "start": p["start"], "end": p["end"], "eff": p.get("eff")} for p in head["result"]["phones"]]
                return {"runId": head["runId"], "manual": bool(head["manual"]), "owner": ",".join(head.get("units") or []), "phones": phones}
        segs = self.speech.read_segments(asset["source_id"], a, b)
        if not segs:
            return unavailable("no-segments")
        ords = self.speech.ordinals(asset["source_id"], [t["id"] for t in segs])
        base = units.base_of(asset)
        parts = []
        for t in segs:
            uid = units.unit_id(t["id"], base)
            r = self.speech.usable_run(uid, t)
            if r is None:
                return unavailable("segment-analysis-unavailable", segmentId=t["id"])
            parts.append((uid, t["id"], r, loads(r["result"])))
        if not self._covers([res.get("window") or [r["range_start"], r["range_end"]] for _, _, r, res in parts], a, b):
            return unavailable("analysis-window-incomplete")
        merged = units.merge([{"unitId": uid, "ordinal": ords.get(sid, 0), "result": self.speech._local_result(res, m)} for uid, sid, _, res in parts], start, end)
        if "conflict" in merged:
            return unavailable("phoneme-conflict", conflict=merged["conflict"])
        phones = [{"label": p.get("orig", p["label"]), "start": p["start"], "end": p["end"], "eff": p.get("eff")} for p in merged["phones"]]
        return {"runId": "+".join(r["id"] for _, _, r, _ in parts), "manual": any(bool(r["manual"]) for _, _, r, _ in parts), "owner": ",".join(u for u, _, _, _ in parts),
                "phones": phones}

    @staticmethod
    def _covers(windows: list[Any], start: float, end: float) -> bool:
        reach = start
        for a, b in sorted(tuple(w) for w in windows if w):
            if a > reach + 1e-6:
                break
            reach = max(reach, b)
        return reach >= end - 1e-6

    @staticmethod
    def _local_phones(al: dict[str, Any], start: float) -> list[list[Any]]:
        return [[p["label"], round(p["start"] - start, 6), round(p["end"] - start, 6)] for p in al["phones"]]

    # ------------------------------------------------------------ 打开与预估

    def open(self, asset_id: str, start: float, end: float, entry: str, sample_id: str | None = None) -> dict[str, Any]:
        """拉平台打开时：冻结、默认值（按入口）、对齐是否可用、建议名、初始内区。"""
        values = settings_mod.values(self.conn)
        token = self._freeze(asset_id, start, end)
        snap = token.pop("_snap")
        a, b = token["start"], token["end"]
        issues: list[dict[str, Any]] = []
        al = self._alignment(asset_id, a, b, snap, sample_id, issues)
        name = None
        if sample_id:
            s = self.conn.execute('SELECT name, asset_id, start, "end" FROM sample WHERE id=?', (sample_id,)).fetchone()
            if s is not None and s["asset_id"] == asset_id and abs(s["start"] - a) < 1e-6 and abs(s["end"] - b) < 1e-6:
                name = s["name"]
        if name is None:
            name = self.samples.suggest(asset_id, a, b)["name"]
        d = b - a
        return {
            "token": token,
            "duration": d,
            "defaults": defaults_for(values, entry),
            "alignment": None if al is None else {"manual": al["manual"], "runId": al["runId"], "phones": [
                {"label": p["label"], "start": max(0.0, p["start"] - a), "end": min(d, p["end"] - a)} for p in al["phones"]]},
            "alignmentIssue": issues[0] if issues else None,
            "name": name,
            "inner": list(fl.default_inner(d)),
            "transition": fl.TRANSITION,
        }  # fmt: skip

    def _options(self, opts: dict[str, Any], *, batch: bool) -> dict[str, Any]:
        rng, tgt = opts.get("range"), opts.get("target")
        ranges = ("whole", "vowels", "first") if batch else fl.RANGES
        targets = ("auto", "edge") if batch else fl.TARGETS
        if rng not in ranges:
            raise CoreError("flatten-invalid", reason="not-an-option", field="range")
        if tgt not in targets:
            raise CoreError("flatten-invalid", reason="not-an-option", field="target")
        side = opts.get("side") or "left"
        if side not in fl.SIDES:
            raise CoreError("flatten-invalid", reason="not-an-option", field="side")
        out: dict[str, Any] = {"range": rng, "target": tgt, "side": side}
        if tgt == "manual":
            m = fl.parse_manual(opts.get("manual"))
            out["manual"] = str(opts.get("manual")).strip()
            out["manualName"] = m.name
        if rng == "inner":
            inner = opts.get("inner")
            if not (isinstance(inner, list) and len(inner) == 2):
                raise CoreError("flatten-inner-invalid", reason="number")
            trans = opts.get("transition")
            tr = (float(trans[0]), float(trans[1])) if isinstance(trans, list) and len(trans) == 2 else (fl.TRANSITION, fl.TRANSITION)
            out["inner"] = [float(inner[0]), float(inner[1])]
            out["trans"] = list(tr)
        return out

    def estimate(self, token: dict[str, Any], opts: dict[str, Any], sample_id: str | None = None) -> dict[str, Any]:
        """缓存预估（不跑模型）：已测的 F0 帧 + 对齐结果里存的有效范围。没有足够的缓存 → status=in-job。参数不合法照样报错。"""
        o = self._options(opts, batch=False)
        asset_id, a, b = token["assetId"], float(token["start"]), float(token["end"])
        d = b - a
        vowels = None
        if o["range"] in ("vowels", "first"):
            _, _, _, media = self._check_frozen(token)
            al = self._alignment(asset_id, a, b, media["snap"], sample_id)
            if al is None:
                raise CoreError("flatten-needs-alignment", reason="no-alignment")
            vowels = []
            for p in al["phones"]:
                if p["label"] not in fl.derive.EFFECTIVE_LABELS:
                    continue
                s0, s1 = (p["eff"] if p.get("eff") and not al["manual"] else (p["start"], p["end"]))
                s0, s1 = max(0.0, s0 - a), min(d, s1 - a)
                if s1 > s0 + 1e-9:
                    vowels.append((s0, s1))
        intervals = fl.processing_intervals(o["range"], d, vowels=vowels, inner=tuple(o["inner"]) if "inner" in o else None,  # type: ignore[arg-type]
                                            trans=tuple(o.get("trans") or (fl.TRANSITION, fl.TRANSITION)))  # type: ignore[arg-type]  # fmt: skip
        if o["target"] == "manual":
            return {"status": "ok", "target": fl.parse_manual(o["manual"]).wire(), "intervals": [list(x) for x in intervals]}
        i0, frames, have = self.speech.f0_frames(asset_id, a, b)
        times = (np.arange(len(frames)) + i0) * fcpe.HOP / fcpe.SR + fcpe.HOP / 2 / fcpe.SR - a
        if not have.any():
            return {"status": "in-job", "target": None, "intervals": [list(x) for x in intervals]}
        frames = np.where(have[:, None], frames, 0.0).astype(np.float32)
        try:
            t = fl.auto_target(frames, intervals, times) if o["target"] == "auto" else fl.edge_target(frames, intervals, o["side"], times)
        except CoreError as e:
            return {"status": "insufficient", "target": None, "intervals": [list(x) for x in intervals], "error": e.to_wire()}
        return {"status": "ok", "target": t.wire(), "intervals": [list(x) for x in intervals]}

    # ------------------------------------------------------------ 提交

    def _versions(self) -> dict[str, Any]:
        _, voc_sha = registry.locate(hifigan.MODEL_ID, hifigan.MODEL_FILE, self.ws.models, self.support_dir)
        _, fc_sha = registry.locate(fcpe.MODEL_ID, fcpe.MODEL_FILE, self.ws.models, self.support_dir)
        return {"algo": fl.ALGO_VERSION, "vocoder": {"id": hifigan.MODEL_ID, "sha256": voc_sha, "frontend": hifigan.FRONTEND_VERSION},
                "fcpe": {"id": fcpe.MODEL_ID, "sha256": fc_sha, "frontend": fcpe.FRONTEND_VERSION}}  # fmt: skip

    def _item(self, idx: int, token: dict[str, Any], o: dict[str, Any], name: str, sample_id: str | None, ver: dict[str, Any]) -> dict[str, Any]:
        asset, ref, win, media = self._check_frozen(token)
        a, b = float(token["start"]), float(token["end"])
        sr = ref.sample_rate
        fa, fb = round(win.to_file(a) * sr), round(win.to_file(b) * sr)
        it: dict[str, Any] = {
            "idx": idx, "sample": sample_id, "name": name, "asset": asset["id"], "start": a, "end": b,
            "file": {"path": ref.path, "ordinal": ref.ordinal, "sample_rate": sr, "channels": ref.channels, "codec": ref.codec, "format": ref.format_name},
            "frames": [fa, fb], "snapshot": media["snap"], "media": token["media"], "range": o["range"],
            "target": {"method": o["target"], "side": o["side"], "manual": o.get("manual")},
        }  # fmt: skip
        if o["range"] == "inner":
            it["inner"], it["trans"] = o["inner"], o["trans"]
            fl.check_inner(b - a, tuple(o["inner"]), tuple(o["trans"]))  # type: ignore[arg-type]
        if o["range"] in ("vowels", "first"):
            al = self._alignment(asset["id"], a, b, media["snap"], sample_id)
            if al is None:
                raise CoreError("flatten-needs-alignment", reason="no-alignment")
            it["phones"], it["manual"], it["alignmentRun"] = self._local_phones(al, a), al["manual"], al["runId"]
        key = {k: it.get(k) for k in ("asset", "media", "snapshot", "frames", "range", "target", "inner", "trans", "phones", "manual")}
        it["fingerprint"] = _sha({"input": key, "versions": ver})
        reuse = self._reusable(it["fingerprint"])
        if reuse:
            it["reuse"] = reuse
        return it

    def _reusable(self, fingerprint: str) -> str | None:
        """相同输入 + 相同参数 + 相同模型版本的成品音频（文件仍在且没被改动）。"""
        for r in self.conn.execute("SELECT id FROM sound_asset WHERE origin='flatten' AND production LIKE ?", (f'%"fingerprint":"{fingerprint}"%',)):
            try:
                asset = assets_mod.get(self.conn, r[0])
                _, _, media = assets_mod.locate(self.conn, self.ws.root, asset, 0.0, float(asset["duration"]))
                assets_mod.check_media(media)
            except CoreError:
                continue
            return str(r[0])
        return None

    def _submit(self, items: list[dict[str, Any]], ver: dict[str, Any], options: dict[str, Any], batch: bool) -> dict[str, Any]:
        params = {
            "items": items, "versions": ver, "options": options, "batch": batch,
            "models_dir": str(self.ws.models), "support_dir": str(self.support_dir),
        }  # fmt: skip
        affects = {"sample": [it["sample"] for it in items if it.get("sample")], "asset": sorted({it["asset"] for it in items if it.get("asset")})}
        job = self.jobs.submit(JOB_KIND, params, affects)
        self.jobs.add_items(job["id"], [(it.get("sample") or it.get("asset") or "", "queued") for it in items])
        return self.jobs.summary(job["id"])

    def submit(self, token: dict[str, Any], opts: dict[str, Any], name: str, sample_id: str | None = None) -> dict[str, Any]:
        """单个拉平（拉平台「开始拉平」）。"""
        name = (name or "").strip()
        if not name:
            raise CoreError("flatten-invalid", reason="too-short", field="name")
        if len(name) > 500:
            raise CoreError("flatten-invalid", reason="too-long", field="name", max=500)
        o = self._options(opts, batch=False)
        ver = self._versions()
        it = self._item(0, token, o, name, sample_id, ver)
        return self._submit([it], ver, o, False)

    def _batch_items(self, sample_ids: list[str], o: dict[str, Any], ver: dict[str, Any]) -> list[dict[str, Any]]:
        items = []
        for idx, sid in enumerate(dict.fromkeys(sample_ids)):
            s = self.conn.execute('SELECT id, asset_id, start, "end", name FROM sample WHERE id=?', (sid,)).fetchone()
            if s is None:
                raise CoreError("sample-not-found", id=sid)
            try:
                token = self._freeze(s["asset_id"], s["start"], s["end"])
                token.pop("_snap")
                items.append(self._item(idx, token, o, s["name"], sid, ver))
            except CoreError as e:
                # 这一项处理不了（没有对齐、文件缺失……）：单独失败并说明，不影响别的项
                items.append({"idx": idx, "sample": sid, "name": s["name"], "asset": s["asset_id"], "error": e.to_wire()})
        return items

    def submit_batch(self, sample_ids: list[str], opts: dict[str, Any]) -> dict[str, Any]:
        """批量拉平：每项按自己的范围与边界独立定音；只有自动定音（Q10）。"""
        if not sample_ids:
            raise CoreError("flatten-invalid", reason="too-short", field="ids")
        o = self._options(opts, batch=True)
        ver = self._versions()
        return self._submit(self._batch_items(sample_ids, o, ver), ver, o, True)

    def rerun_failed(self, job_id: str) -> dict[str, Any]:
        """只重跑失败项（同一组选项，输入在现在重新冻结）。"""
        job = self.conn.execute("SELECT kind, params FROM job WHERE id=?", (job_id,)).fetchone()
        if job is None or job["kind"] != JOB_KIND:
            raise CoreError("job-not-found", id=job_id)
        params = loads(job["params"])
        failed = {r[0] for r in self.conn.execute("SELECT idx FROM job_item WHERE job_id=? AND status='failed'", (job_id,))}
        items = [it for it in params["items"] if it["idx"] in failed]
        if not items:
            raise CoreError("flatten-invalid", reason="nothing-failed", field="job")
        ver = self._versions()
        o = params["options"]
        if not params.get("batch"):
            it = items[0]
            token = self._freeze(it["asset"], it["start"], it["end"])
            token.pop("_snap")
            return self._submit([self._item(0, token, o, it["name"], it.get("sample"), ver)], ver, o, False)
        sids = [it["sample"] for it in items if it.get("sample")]
        return self._submit(self._batch_items(sids, o, ver), ver, o, True)

    # ------------------------------------------------------------ 登记

    def _adopt(self, job: dict[str, Any], result: dict[str, Any]) -> None:
        params = loads(job["params"])
        items = {it["idx"]: it for it in params["items"]}
        rows = self.conn.execute("SELECT idx, result_ref FROM job_item WHERE job_id=? AND status='ok' ORDER BY idx", (job["id"],)).fetchall()
        item_dir = self.jobs.jobs_dir / job["id"] / "items"
        device = loads(job["device"])
        moved: list[Path] = []
        created_samples: list[str] = []
        created_assets: list[str] = []
        f0_pending: list[tuple[str, dict[int, Path]]] = []
        ts = now_iso()
        cs = ChangeSet()
        try:
            with transaction(self.conn):
                for r in rows:
                    it = items.get(r["idx"])
                    if it is None:
                        continue
                    res = json.loads((item_dir / r["result_ref"]).read_text(encoding="utf-8"))
                    if self.conn.execute("SELECT 1 FROM sound_asset WHERE id=?", (it["asset"],)).fetchone() is None:
                        continue  # 输入资产在任务期间被删了（原片被删）：不登记
                    if res.get("reuse"):
                        aid = res["reuse"]
                        if self.conn.execute("SELECT 1 FROM sound_asset WHERE id=?", (aid,)).fetchone() is None:
                            raise CoreError("flatten-asset-changed")
                    else:
                        aid = self._register_asset(job, params, it, res, ts, device, moved)
                        created_assets.append(aid)
                        f0_pending.append((aid, {int(k): item_dir / str(it["idx"]) / "f0" / f"{k}.npy" for k in res["f0Chunks"]}))
                    sid = self._register_sample(job["id"], it, aid, ts)
                    created_samples.append(sid)
                    cs.add("sample", sid)
                    cs.add("asset", aid)
                # 成品 F0（身份依赖实际文件的快照，所以在资产与文件都就位之后算）
                for aid, chunks in f0_pending:
                    a = assets_mod.get(self.conn, aid)
                    _, ident = self.speech.f0_identity(aid, 0.0, float(a["duration"]))
                    self.speech.record_f0(aid, ident, chunks, job["id"], ts)
        except Exception:
            for p in moved:
                p.unlink(missing_ok=True)
            raise
        record_probes(self.conn, result.get("probes") or [])
        shutil.rmtree(self.jobs.jobs_dir / job["id"] / "cache", ignore_errors=True)
        if self.on_change and cs.entities:
            self.on_change(cs)

    def _register_asset(self, job: dict[str, Any], params: dict[str, Any], it: dict[str, Any], res: dict[str, Any], ts: str,
                        device: Any, moved: list[Path]) -> str:  # fmt: skip
        inp = assets_mod.get(self.conn, it["asset"])
        mid, aid = new_id(), new_id()
        target_dir = libdirs.track_dir(self.ws, self.conn, inp["source_id"], "Flatten")  # L23
        target = target_dir / f"{aid}.mp3"
        shutil.move(res["mp3"], target)
        moved.append(target)
        pr = probe_mod.probe(target)
        rel = target.relative_to(self.ws.root).as_posix()
        self.conn.execute(
            "INSERT INTO media_file(id, path, location, file_snapshot, format, sample_rate, frames, encode_manifest, created_at)"
            " VALUES (?, ?, 'library', ?, 'mp3', ?, ?, ?, ?)",
            (mid, rel, dumps(probe_mod.snapshot(target, pr)), res["rate"], res["frames"], dumps(res["manifest"]), ts),
        )
        duration = res["frames"] / res["rate"]
        pts = Mapping.of(inp["mapping"]).crop(it["start"], it["end"]).to_list()
        pts[-1][0] = duration  # 输出时长与输入相差不超过一帧：局部终点按实际文件时长（原片时间不变）
        production = {
            "op": "flatten", "target": res["target"], "range": it["range"], "intervals": res["intervals"],
            "method": it["target"]["method"], "side": it["target"]["side"] if it["target"]["method"] == "edge" else None,
            "ref": res["target"].get("ref"), "inner": res.get("inner"), "trans": it.get("trans"),
            "alignmentRun": it.get("alignmentRun"), "manualAlignment": it.get("manual"),
            "versions": params["versions"], "fingerprint": it["fingerprint"], "inputFrames": res["inputFrames"], "inputRate": res["inputRate"],
            "device": device, "job": job["id"],
        }  # fmt: skip
        self.conn.execute(
            "INSERT INTO sound_asset(id, source_id, origin, media_file_id, duration, mapping, input_asset_id, input_start, input_end,"
            " production, language, created_at) VALUES (?, ?, 'flatten', ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (aid, inp["source_id"], mid, duration, dumps(pts), inp["id"], it["start"], it["end"], dumps(production), inp["language"], ts),
        )
        self.conn.execute(
            "INSERT INTO asset_storage(asset_id, range_start, range_end, media_file_id, kind) VALUES (?, 0, ?, ?, 'primary')", (aid, duration, mid)
        )
        assets_mod.prefill_roles(self.conn, aid, list(inp["roles"]))  # 成品继承输入资产的角色（04 §4.2.4）
        return aid

    def _register_sample(self, job_id: str, it: dict[str, Any], aid: str, ts: str) -> str:
        a = assets_mod.get(self.conn, aid)
        sid = new_id()
        origin = {"kind": "flatten", "job": job_id, "idx": it["idx"]}
        self.conn.execute(
            'INSERT INTO sample(id, asset_id, start, "end", name, nature, language, created_via, origin, created_at, updated_at)'
            " VALUES (?, ?, 0, ?, ?, 'pitched', ?, 'processed', ?, ?, ?)",
            (sid, aid, float(a["duration"]), it["name"], a["language"], dumps(origin), ts, ts),
        )
        effective_tags.refresh(self.conn, [sid])
        return sid

    # ------------------------------------------------------------ 结果

    def results(self, job_id: str) -> list[dict[str, Any]]:
        """逐条结果：输入采样、状态、失败原因、成品采样与目标音。"""
        job = self.conn.execute("SELECT kind, params FROM job WHERE id=?", (job_id,)).fetchone()
        if job is None or job["kind"] != JOB_KIND:
            raise CoreError("job-not-found", id=job_id)
        items = {it["idx"]: it for it in loads(job["params"])["items"]}
        products: dict[int, dict[str, Any]] = {}
        for r in self.conn.execute(
            "SELECT s.id, s.origin, a.production FROM sample s JOIN sound_asset a ON a.id=s.asset_id WHERE s.origin LIKE ?", (f'%"job":"{job_id}"%',)
        ):
            o = loads(r["origin"])
            if o.get("job") == job_id:
                prod = loads(r["production"]) if r["production"] else {}
                products[int(o["idx"])] = {"sampleId": r["id"], "target": (prod.get("target") or {}).get("name")}
        out = []
        for r in self.conn.execute("SELECT idx, target, status, error FROM job_item WHERE job_id=? ORDER BY idx", (job_id,)):
            it = items.get(r["idx"], {})
            exists = bool(it.get("sample")) and self.conn.execute("SELECT 1 FROM sample WHERE id=?", (it["sample"],)).fetchone() is not None
            p = products.get(r["idx"], {})
            out.append({
                "idx": r["idx"], "sampleId": it.get("sample"), "name": it.get("name"), "deleted": bool(it.get("sample")) and not exists,
                "status": r["status"], "error": loads(r["error"]) if r["error"] else None,
                "productId": p.get("sampleId"), "target": p.get("target"),
            })  # fmt: skip
        return out
