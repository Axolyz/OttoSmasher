"""三大搜索（规格 09 §9.6、10 §10.2、04 §4.2.10；ARCHITECTURE §2.2、§9）：Core 侧——范围、覆盖预检、准备任务、检索协调、固定结果。

覆盖预检：语音检索“n/m 已就绪”（有分析但索引没建或过期 → 「准备当前范围索引」）；音高检索“a/b 已索引”（F0 没测 → 「准备当前范围索引」）。
准备任务完成后只刷新覆盖数（事件 ``search.coverage``），**不重新搜索**（10 §10.2.5）。

检索：命令先在主线程校验查询、算出范围（快照），立即返回检索 ID；分片在常驻进程池里并行（``search_worker``），
后台线程等结果，回到主线程写固定结果（全部写入、不截断），发 ``search.finished``。被取消的检索不写固定结果。
固定结果：恢复与翻页不重搜、不重排；读取时只核对成员失效（已删除 / 绑定变化 / 分析或测量变化）。
时钟：语音命中的起止是资产局部秒；音高命中的帧是资产帧（10 ms），另给资产局部秒与原片秒（原片模式跳转用）。
"""

from __future__ import annotations

import sqlite3
import threading
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

import msgspec

from ..algo import pitch_search as ps
from ..algo import speech_search as ss
from ..domain.mapping import Mapping
from ..models import f0store
from ..store.db import transaction
from ..store.workspace import Workspace
from . import assets as assets_mod
from .clock import new_id, now_iso
from .edits import dumps, loads
from .errors import CoreError
from .probes import record_probes
from .search_index import SpeechIndex, asset_identities, pitch_coverage
from .search_worker import SearchPool, pitch_shard, shards_of, speech_shard

MODES = ("speech", "pitch", "pitchSources")
PITCH_MODES = ("samples", "sources")
PAGE_MAX = 100


class SearchService:
    def __init__(
        self, conn: sqlite3.Connection, ws: Workspace, jobs: Any, samples: Any, speech: Any, support_dir: Path,
        emit: Callable[[str, Any], None] | None = None, rhythm: Any = None, post: Callable[[Callable[[], None]], None] | None = None,
    ) -> None:
        self.conn = conn
        self.ws = ws
        self.jobs = jobs
        self.samples = samples
        self.speech = speech
        self.support_dir = support_dir
        self.emit = emit
        self.rhythm = rhythm
        self.post = post
        self.index = SpeechIndex(conn)
        self.pool: SearchPool | None = None
        self.inline = False  # 测试：分片在调用线程里跑、结果同步写入
        self._active: dict[str, dict[str, Any]] = {}
        self._done: dict[str, dict[str, Any]] = {}
        jobs.adopters["search.index"] = self._adopt_index
        jobs.adopters["f0.measure"] = self._adopt_f0

    # ------------------------------------------------------------ 范围

    def scope_ids(self, scope: dict[str, Any] | None) -> list[str]:
        """当前浏览范围（查找栏与范围行的条件）→ 采样 ID（与列表同一套条件）。"""
        sc = scope or {}
        return self.samples.ids(natures=sc.get("natures"), starred=bool(sc.get("starred")), text=str(sc.get("text") or ""), source_id=sc.get("sourceId"))

    def _sample_ranges(self, ids: list[str]) -> list[tuple[str, str, float, float]]:
        out = []
        for i in range(0, len(ids), 900):
            part = ids[i : i + 900]
            out += [
                (r[0], r[1], float(r[2]), float(r[3]))
                for r in self.conn.execute(f'SELECT id, asset_id, start, "end" FROM sample WHERE id IN ({",".join("?" * len(part))})', part)
            ]
        order = {s: k for k, s in enumerate(ids)}
        out.sort(key=lambda r: order[r[0]])
        return out

    # ------------------------------------------------------------ 覆盖预检

    def coverage(self, mode: str, scope: dict[str, Any] | None) -> dict[str, Any]:
        if mode not in MODES:
            raise CoreError("search-invalid", field="mode")
        if mode == "pitchSources":
            tracks, plan = self._track_plan(scope)
            return {"mode": mode, "total": len(tracks), "ready": len(tracks) - len(plan), "stale": len(plan), "noAnalysis": 0}
        ids = self.scope_ids(scope)
        if mode == "speech":
            s = self.index.status(ids)
            return {"mode": mode, "total": len(ids), "ready": len(s["ready"]), "stale": len(s["stale"]), "noAnalysis": len(s["missing"]) + len(s["none"])}
        cov = pitch_coverage(self.conn, self.ws.f0, self._sample_ranges(ids))
        return {"mode": mode, "total": len(ids), "ready": len(cov["ready"]), "stale": len(cov["pending"]), "noAnalysis": 0}

    # ------------------------------------------------------------ 准备当前范围索引

    def prepare(self, mode: str, scope: dict[str, Any] | None) -> dict[str, Any]:
        if mode not in MODES:
            raise CoreError("search-invalid", field="mode")
        if mode == "pitchSources":
            _tracks, tplan = self._track_plan(scope)
            plan = self._f0_plan({"plan": tplan})
            if not plan:
                raise CoreError("search-nothing-to-prepare")
            params = {"plan": plan, "models_dir": str(self.ws.models), "support_dir": str(self.support_dir)}
            return self.jobs.submit("f0.measure", params, {"asset": sorted({p["asset"] for p in plan})})
        ids = self.scope_ids(scope)
        if mode == "speech":
            stale = self.index.status(ids)["stale"]
            if not stale:
                raise CoreError("search-nothing-to-prepare")
            params = {"ids": stale, "db": str(self.ws.db_path), "workspace": str(self.ws.root), "support_dir": str(self.support_dir)}
            return self.jobs.submit("search.index", params, {"sample": stale})
        cov = pitch_coverage(self.conn, self.ws.f0, self._sample_ranges(ids))
        plan = self._f0_plan(cov)
        if not plan:
            raise CoreError("search-nothing-to-prepare")
        params = {"plan": plan, "models_dir": str(self.ws.models), "support_dir": str(self.support_dir)}
        return self.jobs.submit("f0.measure", params, {"asset": sorted({p["asset"] for p in plan})})

    def _f0_plan(self, cov: dict[str, Any]) -> list[dict[str, Any]]:
        """覆盖缺口 → F0 测量计划（与语音分析里测 F0 同一格式：资产、身份、时长、文件、存储窗口、段号）。"""
        out = []
        for p in cov["plan"].values():
            asset = assets_mod.get(self.conn, p["asset"])
            chunks = sorted(p["chunks"])
            # 用第一段所在的存储定位文件（身份已按同一存储算出）
            from ..models import f0store

            cp = f0store.chunk_plan(chunks[0], p["duration"])
            t0 = min(max(0.0, cp["decode"][0]), float(asset["duration"]))
            t1 = min(float(asset["duration"]), max(t0 + 1e-3, cp["decode"][1]))
            try:
                ref, win, media = assets_mod.locate(self.conn, self.ws.root, asset, t0, t1)
                assets_mod.check_media(media)
            except CoreError:
                continue  # 文件缺失或被改动：不测（覆盖里仍是“未就绪”）
            out.append({
                "asset": p["asset"], "identity": p["identity"], "duration": p["duration"], "chunks": chunks,
                "file": {"path": ref.path, "ordinal": ref.ordinal, "sample_rate": ref.sample_rate, "channels": ref.channels, "codec": ref.codec, "format": ref.format_name},
                "storage": [win.local_start, win.local_end, win.file_start],
            })
        return out

    # ------------------------------------------------------------ 采纳

    def _adopt_index(self, job: dict[str, Any], result: dict[str, Any]) -> None:
        rows = msgspec.msgpack.decode((self.jobs.jobs_dir / job["id"] / result["rows"]).read_bytes())
        with transaction(self.conn):
            n = self.index.adopt([tuple(r) for r in rows])
        if self.emit:
            self.emit("search.coverage", {"mode": "speech", "adopted": n})

    def _adopt_f0(self, job: dict[str, Any], result: dict[str, Any]) -> None:
        with transaction(self.conn):
            self.speech._adopt_f0(job["id"], result.get("f0") or [], now_iso())
        record_probes(self.conn, result.get("probes") or [])
        if self.emit:
            self.emit("search.coverage", {"mode": "pitch", "adopted": len(result.get("f0") or [])})

    # ------------------------------------------------------------ 检索协调

    def _pool(self) -> SearchPool:
        if self.pool is None:
            self.pool = SearchPool(self.ws.db_path, self.ws.f0, inline=self.inline)
        return self.pool

    def shutdown(self) -> None:
        if self.pool is not None:
            self.pool.shutdown()

    def _launch(self, kind: str, fn: Callable[..., dict[str, Any]], shards: list[tuple[Any, ...]], ctx: dict[str, Any]) -> dict[str, Any]:
        pool = self._pool()
        sid = new_id()
        slot = pool.acquire()
        self._active[sid] = {"slot": slot, "kind": kind, "t0": time.monotonic()}

        def work() -> None:
            err: BaseException | None = None
            res: list[dict[str, Any]] | None = None
            try:
                res = pool.run(fn, shards, slot)
            except BaseException as e:  # noqa: BLE001 — 失败写进事件，不拖垮 Core
                err = e
            done = lambda: self._finish(sid, res, err, ctx)  # noqa: E731
            if self.inline or self.post is None:
                done()
            else:
                self.post(done)

        if self.emit:
            self.emit("search.started", {"searchId": sid, "kind": kind})
        if self.inline:
            work()
        else:
            threading.Thread(target=work, name=f"search-{sid[:8]}", daemon=True).start()
        return {"searchId": sid}

    def status(self, search_id: str) -> dict[str, Any]:
        a = self._active.get(search_id)
        if a is not None:
            return {"searchId": search_id, "kind": a["kind"], "status": "running", "resultId": None, "stats": None, "error": None}
        done = self._done.get(search_id)
        if done is None:
            raise CoreError("search-not-found", id=search_id)
        return done

    def pitch_check(self, blocks: list[dict[str, Any]] | None, text: str | None) -> dict[str, Any]:
        """音高查询的就地提示（10 §10.2.1）：块或文本格式 → 问题列表、每块帧数、规范文本、（文本解析出的）块。"""
        problems: list[dict[str, Any]] = []
        items: list[dict[str, Any]] = list(blocks or [])
        if text is not None:
            items, line_errors = ps.text_to_blocks(text)
            problems += line_errors
        q, errs = ps.check_blocks(items)
        problems += errs
        frames = [b.frames for b in q.blocks] if q else []
        return {"ok": not problems, "problems": problems, "frames": frames, "text": ps.blocks_to_text(q) if q else None, "blocks": items}

    def cancel(self, search_id: str) -> dict[str, Any]:
        a = self._active.get(search_id)
        if a is not None and self.pool is not None:
            self.pool.cancel(a["slot"])
        return {"searchId": search_id, "cancelling": a is not None}

    def _finish(self, sid: str, res: list[dict[str, Any]] | None, err: BaseException | None, ctx: dict[str, Any]) -> None:
        a = self._active.pop(sid, None)
        if a is not None and self.pool is not None:
            self.pool.release(a["slot"])
        ms = int(round((time.monotonic() - (a["t0"] if a else time.monotonic())) * 1000))
        out: dict[str, Any] = {"searchId": sid, "kind": ctx["kind"], "status": "done", "resultId": None, "stats": None, "error": None}
        if err is not None:
            out["status"] = "failed"
            out["error"] = err.to_wire() if isinstance(err, CoreError) else {"code": "internal-error", "args": {"method": "search", "reason": repr(err)}}
        elif res is None:
            out["status"] = "cancelled"
        else:
            rid, stats = (self._write_speech if ctx["kind"] == "speech" else self._write_pitch)(res, ctx, ms)
            out["resultId"], out["stats"] = rid, stats
        self._done[sid] = out
        while len(self._done) > 64:
            self._done.pop(next(iter(self._done)))
        if self.emit:
            self.emit("search.finished", out)

    # ---- 语音检索

    def run_speech(self, query: dict[str, Any], scope: dict[str, Any] | None) -> dict[str, Any]:
        ss.parse_query(query)  # 先校验：查询不对立即报错
        bpm = self.rhythm.bpm() if self.rhythm is not None else None
        ids = self.scope_ids(scope)
        st = self.index.status(ids)
        ready = st["ready"]
        workers = self._pool().workers
        shards = [(sh, query, bpm) for sh in shards_of(ready, workers) if sh]
        ctx = {
            "kind": "speech", "query": query, "scope": scope or {}, "bpm": bpm,
            "pre": {"total": len(ids), "searched": len(ready), "noAnalysis": len(st["missing"]) + len(st["none"]), "stale": len(st["stale"])},
        }
        return self._launch("speech", speech_shard, shards, ctx)

    def _write_speech(self, res: list[dict[str, Any]], ctx: dict[str, Any], ms: int) -> tuple[str, dict[str, Any]]:
        by: dict[str, list[dict[str, Any]]] = {}
        windows = no_ev = 0
        for r in res:
            windows += r["windows"]
            no_ev += r["noEvidence"]
            for h in r["hits"]:
                by.setdefault(h.pop("sample"), []).append(h)
        groups = []
        for sid, hs in by.items():
            hs.sort(key=lambda h: (round(h["score"], 10), h["start"], h["first"]))
            groups.append((round(hs[0]["score"], 10), sid, hs))
        groups.sort(key=lambda g: (g[0], g[1]))
        snaps = self._speech_snapshots([g[1] for g in groups])
        stats = {
            **ctx["pre"], "samples": len(groups), "hits": sum(len(g[2]) for g in groups), "ms": ms, "windows": windows,
            "noEvidence": no_ev, "bpm": ctx["bpm"], "truncated": False, "unknownBounds": 0,
        }
        rid = self._write_set("speech", ctx["query"], {"scope": ctx["scope"], "bpm": ctx["bpm"]}, {"bpm": ctx["bpm"]}, stats,
                              [(sid, None, snaps.get(sid, {}), hs) for _, sid, hs in groups])
        return rid, stats

    def _speech_snapshots(self, ids: list[str]) -> dict[str, dict[str, Any]]:
        """成员的绑定快照：资产与范围 + 语音分析头（自己的，或投影的来源）。"""
        out: dict[str, dict[str, Any]] = {}
        for i in range(0, len(ids), 900):
            part = ids[i : i + 900]
            for r in self.conn.execute(
                'SELECT s.id, s.asset_id, s.start, s."end", h.run_id, h.version FROM sample s'
                " LEFT JOIN measure_head h ON h.owner_type = 'sample' AND h.owner_id = s.id AND h.kind = 'alignment'"
                f" WHERE s.id IN ({','.join('?' * len(part))})",
                part,
            ):
                out[r[0]] = {"assetId": r[1], "start": r[2], "end": r[3], "analysis": [r[4], r[5]]}
        return out

    # ---- 音高检索

    def run_pitch(self, blocks: list[dict[str, Any]], params: dict[str, Any] | None, mode: str, scope: dict[str, Any] | None) -> dict[str, Any]:
        if mode not in PITCH_MODES:
            raise CoreError("search-invalid", field="mode")
        prm = ps.check_params(params or {}, mode=mode)  # 参数非法时即使范围为空也报错（R15.7）
        q = ps.parse_query(blocks)
        if mode == "samples":
            ids = self.scope_ids(scope)
            cov = pitch_coverage(self.conn, self.ws.f0, self._sample_ranges(ids))
            ready = set(cov["ready"])
            entries: dict[str, dict[str, Any]] = {}
            for sid, aid, a, b in self._sample_ranges(ids):
                if sid not in ready:
                    continue
                ident = cov["identities"][aid]["identities"][(a, b)]
                e = entries.setdefault(f"{aid}|{ident}", {"asset": aid, "identity": ident, "duration": cov["identities"][aid]["duration"], "spans": [], "lines": None})
                e["spans"].append([int(-(-round(a / ps.FRAME, 6) // 1)), int(round(b / ps.FRAME, 6) // 1), sid])
            pre = {"total": len(ids), "searched": len(ready), "noAnalysis": 0, "stale": len(cov["pending"])}
        else:
            entries, pre = self._source_tracks(scope, prm)
        items = list(entries.values())
        workers = self._pool().workers
        shards = [(sh, blocks, params or {}, mode) for sh in shards_of(items, workers, weight=lambda e: sum(s[1] - s[0] for s in e["spans"])) if sh]
        ctx = {"kind": "pitch", "query": {"blocks": blocks, "params": params or {}, "mode": mode}, "scope": scope or {}, "mode": mode, "pre": pre,
               "frames": q.frames}
        return self._launch("pitch", pitch_shard, shards, ctx)

    def _track_plan(self, scope: dict[str, Any] | None) -> tuple[list[Any], dict[str, dict[str, Any]]]:
        """原片音轨模式的覆盖：范围里的整轨，以及没测完的（资产 → 身份、时长、缺的段）。"""
        tracks = self._list_tracks(scope)
        idents = asset_identities(self.conn, {r["id"]: [(0.0, float(r["duration"]))] for r, _ in tracks})
        plan: dict[str, dict[str, Any]] = {}
        for r, _m in tracks:
            dur = float(r["duration"])
            ident = idents[r["id"]]["identities"].get((0.0, dur))
            if ident is None:
                continue
            need = set(f0store.chunks_for(0.0, dur, dur)) - f0store.present(self.ws.f0, r["id"], ident)
            if need:
                plan[r["id"]] = {"asset": r["id"], "identity": ident, "duration": dur, "chunks": need}
        return tracks, plan

    def _list_tracks(self, scope: dict[str, Any] | None) -> list[Any]:
        """原片音轨模式（10 §10.2.3）：范围只保留原片、文字（原片名/作品/集数）、音轨角色；采样专用条件拒绝并说明。"""
        sc = dict(scope or {})
        for k in ("natures", "starred"):
            if sc.get(k):
                raise CoreError("search-invalid", field=k)
        where, args = ["1=1"], []
        if sc.get("sourceId"):
            where.append("src.id = ?")
            args.append(sc["sourceId"])
        text = str(sc.get("text") or "").strip()
        if text:
            needle = "%" + text.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"
            where.append("(src.path LIKE ? ESCAPE '\\' OR src.work LIKE ? ESCAPE '\\' OR src.episode LIKE ? ESCAPE '\\')")
            args += [needle] * 3
        roles = sc.get("roles")
        rows = self.conn.execute(
            f"SELECT a.id, a.mapping, a.duration, src.id AS sid, src.duration AS sdur, src.current_subtitle_version_id AS subver FROM sound_asset a"
            f" JOIN source src ON src.id = a.source_id WHERE {' AND '.join(where)} ORDER BY src.created_at, a.created_at",
            args,
        ).fetchall()
        tracks = []
        for r in rows:
            try:
                m = Mapping.of(loads(r["mapping"]))
            except CoreError:
                continue
            if r["sdur"] is None or not m.is_full_track(float(r["sdur"])):
                continue
            if roles:
                have = {x[0] for x in self.conn.execute("SELECT role FROM asset_role WHERE asset_id = ? AND state = 'on'", (r["id"],))}
                if not have & set(roles) and not ("mix" in roles and not have):
                    continue
            tracks.append((r, m))
        return tracks

    def _source_tracks(self, scope: dict[str, Any] | None, prm: dict[str, Any]) -> tuple[dict[str, dict[str, Any]], dict[str, Any]]:
        """原片音轨模式的检索输入：整轨都测完的才检索（没测完的计入“未就绪”）；句首/句尾条件要台词标注（按映射换成资产秒）。"""
        tracks = self._list_tracks(scope)
        idents = asset_identities(self.conn, {r["id"]: [(0.0, float(r["duration"]))] for r, _ in tracks})
        entries: dict[str, dict[str, Any]] = {}
        stale = 0
        need_lines = prm.get("headTolerance") is not None or prm.get("tailTolerance") is not None
        for r, m in tracks:
            dur = float(r["duration"])
            ident = idents[r["id"]]["identities"].get((0.0, dur))
            if ident is None or set(f0store.chunks_for(0.0, dur, dur)) - f0store.present(self.ws.f0, r["id"], ident):
                stale += 1
                continue
            lines = None
            if need_lines:
                ls = []
                for a, b in self.conn.execute(
                    'SELECT start, "end" FROM annotation WHERE source_id = ? AND kind = \'line\' AND deleted = 0'
                    " AND (subtitle_version_id IS NULL OR subtitle_version_id IS ?) AND scope != 'asset'",
                    (r["sid"], r["subver"]),
                ):
                    try:
                        ls.append([m.to_local(a), m.to_local(b)])
                    except CoreError:
                        continue
                lines = ls or None
            n = f0store.total_frames(dur)
            entries[r["id"]] = {"asset": r["id"], "identity": ident, "duration": dur, "spans": [[0, n, None]], "lines": lines}
        return entries, {"total": len(tracks), "searched": len(entries), "noAnalysis": 0, "stale": stale}

    def _write_pitch(self, res: list[dict[str, Any]], ctx: dict[str, Any], ms: int) -> tuple[str, dict[str, Any]]:
        hits = [h for r in res for h in r["hits"]]
        hits.sort(key=lambda h: (round(h["score"] / ps.SCORE_QUANTUM), h["asset"], h["start"], h["frames"]))
        windows = sum(r["windows"] for r in res)
        unknown = sum(r["unknownBounds"] for r in res)
        def wire(h: dict[str, Any]) -> dict[str, Any]:
            return {
                "start": h["start"] * ps.FRAME, "end": (h["start"] + h["frames"]) * ps.FRAME, "frames": h["frames"], "octave": h["octave"],
                "ratio": h["ratio"], "score": h["score"], "blocks": h["blocks"],
            }
        members: list[tuple[str | None, str | None, dict[str, Any], list[dict[str, Any]]]] = []
        if ctx["mode"] == "samples":
            by: dict[str, list[dict[str, Any]]] = {}
            for h in hits:
                for sid in h["samples"]:
                    by.setdefault(sid, []).append(wire(h))
            snaps = self._pitch_snapshots(list(by))
            order = sorted(by, key=lambda sid: (round(by[sid][0]["score"] / ps.SCORE_QUANTUM), sid))
            members = [(sid, None, snaps.get(sid, {}), by[sid]) for sid in order]
        else:
            byA: dict[str, list[dict[str, Any]]] = {}
            for h in hits:
                byA.setdefault(h["asset"], []).append(wire(h))
            maps = {r[0]: (r[1], r[2]) for r in self.conn.execute(
                f"SELECT id, mapping, source_id FROM sound_asset WHERE id IN ({','.join('?' * len(byA))})", list(byA))} if byA else {}
            for aid in sorted(byA, key=lambda a: (round(byA[a][0]["score"] / ps.SCORE_QUANTUM), a)):
                m = Mapping.of(loads(maps[aid][0]))
                for h in byA[aid]:
                    h["sourceStart"], h["sourceEnd"] = m.to_source(h["start"]), m.to_source(h["end"])
                members.append((None, aid, {"assetId": aid, "sourceId": maps[aid][1]}, byA[aid]))
        stats = {**ctx["pre"], "samples": len(members), "hits": len(hits), "ms": ms, "windows": windows, "noEvidence": 0, "bpm": None,
                 "truncated": False, "unknownBounds": unknown}
        rid = self._write_set("pitch", ctx["query"], {"scope": ctx["scope"]}, ctx["query"]["params"], stats, members)
        return rid, stats

    def _pitch_snapshots(self, ids: list[str]) -> dict[str, dict[str, Any]]:
        out: dict[str, dict[str, Any]] = {}
        rng = self._sample_ranges(ids)
        idents = asset_identities(self.conn, {aid: [(a, b)] for _sid, aid, a, b in rng}) if rng else {}
        for sid, aid, a, b in rng:
            out[sid] = {"assetId": aid, "start": a, "end": b, "f0": idents.get(aid, {}).get("identities", {}).get((a, b))}
        return out

    # ---- 固定结果（04 §4.2.10）

    def _write_set(self, kind: str, query: Any, scope: Any, params: Any, stats: dict[str, Any],
                   members: list[tuple[str | None, str | None, dict[str, Any], list[dict[str, Any]]]]) -> str:
        rid = new_id()
        with transaction(self.conn):
            self.conn.execute(
                "INSERT INTO result_set(id, kind, created_at, title, query, scope_snapshot, params, stats, ui_state, closed) VALUES (?, ?, ?, '', ?, ?, ?, ?, NULL, 0)",
                (rid, kind, now_iso(), dumps(query), dumps(scope), dumps(params), dumps(stats)),
            )
            self.conn.executemany(
                "INSERT INTO result_member(result_id, rank, sample_id, asset_id, binding_snapshot, hits) VALUES (?, ?, ?, ?, ?, ?)",
                ((rid, i, sid, aid, dumps(snap), dumps(hs)) for i, (sid, aid, snap, hs) in enumerate(members)),
            )
        return rid

    def _header(self, r: sqlite3.Row) -> dict[str, Any]:
        return {
            "id": r["id"], "kind": r["kind"], "createdAt": r["created_at"], "query": loads(r["query"]), "scope": loads(r["scope_snapshot"]),
            "params": loads(r["params"]), "stats": loads(r["stats"]), "uiState": loads(r["ui_state"]) if r["ui_state"] else None,
        }

    def results(self) -> list[dict[str, Any]]:
        return [self._header(r) for r in self.conn.execute("SELECT * FROM result_set WHERE closed = 0 ORDER BY created_at, rowid")]

    def page(self, result_id: str, offset: int = 0, limit: int = PAGE_MAX) -> dict[str, Any]:
        """一页成员（≤ 100）。只核对失效，不重算、不重排：已删除 / 绑定变化（音源已变化）/ 分析或测量变了（命中已失效）。"""
        r = self.conn.execute("SELECT * FROM result_set WHERE id = ?", (result_id,)).fetchone()
        if r is None:
            raise CoreError("result-not-found", id=result_id)
        limit = max(1, min(int(limit), PAGE_MAX))
        offset = max(0, int(offset))
        total = self.conn.execute("SELECT COUNT(*) FROM result_member WHERE result_id = ?", (result_id,)).fetchone()[0]
        rows = self.conn.execute(
            "SELECT rank, sample_id, asset_id, binding_snapshot, hits FROM result_member WHERE result_id = ? AND rank >= ? ORDER BY rank LIMIT ?",
            (result_id, offset, limit),
        ).fetchall()
        sids = [m["sample_id"] for m in rows if m["sample_id"]]
        cur = self.samples.rows(sids)
        now = self._speech_snapshots(sids) if r["kind"] == "speech" else self._pitch_snapshots([s for s in sids if s in cur])
        out = []
        for m in rows:
            snap = loads(m["binding_snapshot"])
            state, sample, asset = "ok", None, None
            if m["sample_id"]:
                sample = cur.get(m["sample_id"])
                n = now.get(m["sample_id"])
                if sample is None:
                    state = "deleted"
                elif n is None or (n["assetId"], n["start"], n["end"]) != (snap.get("assetId"), snap.get("start"), snap.get("end")):
                    state = "changed"
                elif (r["kind"] == "speech" and n.get("analysis") != snap.get("analysis")) or (r["kind"] == "pitch" and n.get("f0") != snap.get("f0")):
                    state = "stale"
            else:
                a = self.conn.execute(
                    "SELECT a.id, a.source_id, a.stem_name, a.origin, src.work, src.episode, src.path FROM sound_asset a JOIN source src ON src.id = a.source_id WHERE a.id = ?",
                    (m["asset_id"],),
                ).fetchone()
                if a is None:
                    state = "deleted"
                else:
                    asset = {"id": a["id"], "sourceId": a["source_id"], "stemName": a["stem_name"], "origin": a["origin"], "work": a["work"],
                             "episode": a["episode"], "path": a["path"]}
            out.append({"rank": m["rank"], "sampleId": m["sample_id"], "assetId": m["asset_id"], "sample": sample, "asset": asset, "state": state,
                        "hits": loads(m["hits"])})
        return {"result": self._header(r), "total": total, "offset": offset, "rows": out}

    def close(self, result_id: str) -> dict[str, Any]:
        """关闭固定结果：只删结果集合（不删采样）。"""
        with transaction(self.conn):
            n = self.conn.execute("DELETE FROM result_set WHERE id = ?", (result_id,)).rowcount
        if not n:
            raise CoreError("result-not-found", id=result_id)
        return {"id": result_id}

    def set_ui(self, result_id: str, state: Any) -> None:
        """界面状态（激活、页码、选中、滚动）：不是用户资料，不进撤销。"""
        self.conn.execute("UPDATE result_set SET ui_state = ? WHERE id = ?", (dumps(state), result_id))
