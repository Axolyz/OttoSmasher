"""检索的准备在后台自动做（所有者 2026-10-08【基线变更】：原来要在检索浮层里点「准备当前范围索引」）。

资料变化（新采样、语音分析结果、节奏参数、台词标注、默认轨、惩罚度……）后合并 1.5 秒，再看哪些要补：
- **语音检索索引**：有语音分析、但索引没建或过期的采样 → 「准备检索索引」任务（每个最多 500 条）；
- **F0（音高检索）**：新采样的范围、每个原片的默认人声轨（没有就用原混音）整轨 → 「测音高」任务（每个最多 6 段 = 6 分钟音频，不会长时间挡住别的任务）。
都是**后台任务**：同一通道里排在用户提交的任务后面。正在排队或运行的不重复提交（按采样 / 按 F0 段记账，任务结束就清掉）。
启动时全量补一次。设置「语音分析 → 自动准备检索」可以关掉（关了以后检索浮层里仍有手动的「准备」）。

另有「改段后自动在后台重跑」（所有者 2026-10-09，默认关，单独的开关）：段的文本或边界改了、拆分 / 合并 / 切开之后，
在原段已有分析的资产上排后台语音分析（导入替换不触发）；正在排队或运行的不重复提交。
"""

from __future__ import annotations

import logging
import threading
from collections.abc import Callable
from typing import Any

from ..models import f0store
from . import settings as settings_mod
from .edits import loads
from .errors import CoreError
from .search_index import asset_identities, pitch_coverage
from .units import analysis_track

log = logging.getLogger(__name__)

DEBOUNCE = 1.5
INDEX_BATCH = 500
F0_CHUNKS_PER_JOB = 6


class AutoPrepare:
    def __init__(self, conn: Any, search: Any, jobs: Any, post: Callable[[Callable[[], None]], None], delay: float = DEBOUNCE, speech: Any = None) -> None:
        self.conn = conn
        self.search = search
        self.speech = speech
        self._sources_speech: set[str] = set()
        self._rerun: set[str] = set()
        self.pending_units: dict[str, set[str]] = {}
        self.jobs = jobs
        self.post = post
        self.delay = delay
        self._samples: set[str] = set()
        self._sources: set[str] = set()
        self._all = False
        self._all_speech = False
        self._timer: threading.Timer | None = None
        self._lock = threading.Lock()
        self.pending_index: dict[str, set[str]] = {}
        self.pending_f0: dict[str, set[tuple[str, str, int]]] = {}
        jobs.finish_hooks.append(self._finished)

    # ------------------------------------------------------------ 触发

    def on_change(self, entities: dict[str, set[str]]) -> None:
        with self._lock:
            self._samples |= set(entities.get("sample", ())) | set(entities.get("measure", ()))
            self._sources |= set(entities.get("source", ()))
            self._rerun |= set(entities.get("segment_content", ()))
            if entities.keys() & {"setting", "asset"}:
                self._all_speech = True  # 惩罚度、资产角色 → 语音检索索引可能整体过期
            for ent, table in (("segment", "text_segment"), ("range_tag", "range_tag")):
                ids = list(entities.get(ent, ()))
                for i in range(0, len(ids), 900):
                    part = ids[i : i + 900]
                    self._sources_speech |= {r[0] for r in self.conn.execute(
                        f"SELECT DISTINCT source_id FROM {table} WHERE id IN ({','.join('?' * len(part))})", part)}
        self._schedule()

    def kick_all(self) -> None:
        with self._lock:
            self._all = True
        self._schedule()

    def _schedule(self) -> None:
        with self._lock:
            if self._timer is not None:
                self._timer.cancel()
            self._timer = threading.Timer(self.delay, lambda: self.post(self.run))
            self._timer.daemon = True
            self._timer.start()

    def shutdown(self) -> None:
        with self._lock:
            if self._timer is not None:
                self._timer.cancel()

    def _finished(self, jid: str, kind: str, status: str) -> None:
        self.pending_index.pop(jid, None)
        self.pending_f0.pop(jid, None)
        self.pending_units.pop(jid, None)

    # ------------------------------------------------------------ 补

    def run(self) -> None:
        with self._lock:
            samples, sources, full, full_speech = self._samples, self._sources, self._all, self._all_speech
            self._samples, self._sources, self._all, self._all_speech = set(), set(), False, False
            rerun, src_speech = self._rerun, self._sources_speech
            self._rerun, self._sources_speech = set(), set()
        values = settings_mod.values(self.conn)
        if rerun and values["analysis.auto_rerun_segments"]:
            try:
                self._rerun_segments(rerun)
            except Exception:  # noqa: BLE001 — 自动重跑出错不影响别的
                log.exception("auto rerun failed")
        if not values["analysis.auto_prepare"]:
            return
        try:
            all_ids = [r[0] for r in self.conn.execute("SELECT id FROM sample")] if (full or full_speech) else []
            ids = all_ids if full else [r[0] for r in self._existing(samples)]
            by_src: list[str] = []
            for sid in src_speech:
                by_src += [r[0] for r in self.conn.execute("SELECT s.id FROM sample s JOIN sound_asset a ON a.id = s.asset_id WHERE a.source_id = ?", (sid,))]
            self._speech(all_ids if (full or full_speech) else list(dict.fromkeys(ids + by_src)))
            self._sample_f0(ids)
            src = [r[0] for r in self.conn.execute("SELECT id FROM source WHERE media_state = 'available'")] if full else list(sources)
            if not full:
                src += [r[0] for r in self.conn.execute(
                    f"SELECT DISTINCT a.source_id FROM sample s JOIN sound_asset a ON a.id = s.asset_id WHERE s.id IN ({','.join('?' * len(ids))})", ids)] if ids else []
            self._track_f0(sorted(set(src)))
        except Exception:  # noqa: BLE001 — 自动准备出错不影响别的；下次变化再试
            log.exception("auto prepare failed")

    def _rerun_segments(self, ids: set[str]) -> None:
        """段内容变了之后：在原段（拆分 / 合并的产物看来源段）已有分析的资产上排后台语音分析。"""
        if self.speech is None:
            return
        busy = set().union(*self.pending_units.values()) if self.pending_units else set()
        unit_ids: list[str] = []
        for sid in ids:
            row = self.conn.execute("SELECT deleted, provenance FROM text_segment WHERE id=?", (sid,)).fetchone()
            if row is None or row["deleted"]:
                continue
            origins = [sid] + list((loads(row["provenance"]) or {}).get("from") or []) if row["provenance"] else [sid]
            assets: set[str] = set()
            for o in origins:
                assets |= {r[0] for r in self.conn.execute(
                    "SELECT DISTINCT asset_id FROM measure_run WHERE owner_type='asset_text' AND kind='alignment' AND owner_id >= ? AND owner_id < ?",
                    (f"seg:{o}@", f"seg:{o}A"))}
            unit_ids += [f"seg:{sid}@{a}" for a in sorted(assets) if f"seg:{sid}@{a}" not in busy]
        if not unit_ids:
            return
        try:
            job = self.speech.submit("units", unit_ids, False, background=True)
        except CoreError as e:
            if e.code == "speech-nothing-to-do":
                return
            raise
        self.pending_units[job["id"]] = set(unit_ids)

    def _existing(self, ids: set[str]) -> list[Any]:
        out: list[Any] = []
        lst = list(ids)
        for i in range(0, len(lst), 900):
            part = lst[i : i + 900]
            out += self.conn.execute(f"SELECT id FROM sample WHERE id IN ({','.join('?' * len(part))})", part).fetchall()
        return out

    def _speech(self, ids: list[str]) -> None:
        if not ids:
            return
        busy = set().union(*self.pending_index.values()) if self.pending_index else set()
        stale = [s for s in self.search.index.status(ids)["stale"] if s not in busy]
        ws, support = self.search.ws, self.search.support_dir
        for i in range(0, len(stale), INDEX_BATCH):
            part = stale[i : i + INDEX_BATCH]
            job = self.jobs.submit("search.index", {"ids": part, "db": str(ws.db_path), "workspace": str(ws.root), "support_dir": str(support)},
                                   {"sample": part}, background=True)
            self.pending_index[job["id"]] = set(part)

    def _busy_f0(self) -> set[tuple[str, str, int]]:
        return set().union(*self.pending_f0.values()) if self.pending_f0 else set()

    def _submit_f0(self, plan: dict[str, dict[str, Any]]) -> None:
        """plan：资产|身份 → {asset, identity, duration, chunks}；扣掉正在测的段，切成每个任务最多 6 段。"""
        busy = self._busy_f0()
        batches: list[list[tuple[dict[str, Any], int]]] = [[]]
        for p in plan.values():
            for k in sorted(p["chunks"]):
                if (p["asset"], p["identity"], k) in busy:
                    continue
                if len(batches[-1]) >= F0_CHUNKS_PER_JOB:
                    batches.append([])
                batches[-1].append((p, k))
        for b in batches:
            if not b:
                continue
            sub: dict[str, dict[str, Any]] = {}
            for p, k in b:
                e = sub.setdefault(f"{p['asset']}|{p['identity']}", {**{x: p[x] for x in ("asset", "identity", "duration")}, "chunks": set()})
                e["chunks"].add(k)
            entries = self.search._f0_plan({"plan": sub})
            if not entries:
                continue
            ws = self.search.ws
            job = self.jobs.submit("f0.measure", {"plan": entries, "models_dir": str(ws.models), "support_dir": str(self.search.support_dir)},
                                   {"asset": sorted({e["asset"] for e in entries})}, background=True)
            self.pending_f0[job["id"]] = {(e["asset"], e["identity"], int(k)) for e in entries for k in e["chunks"]}

    def _sample_f0(self, ids: list[str]) -> None:
        if not ids:
            return
        cov = pitch_coverage(self.conn, self.search.ws.f0, self.search._sample_ranges(ids))
        self._submit_f0(cov["plan"])

    def _track_f0(self, sources: list[str]) -> None:
        """每个原片的默认人声轨（没有就用原混音：原片默认音频流的那条）整轨测 F0（无字幕时原片音轨模式也能直接用）。"""
        assets: list[tuple[str, float]] = []
        for sid in sources:
            aid = analysis_track(self.conn, sid)
            if aid is None:
                continue
            dur = self.conn.execute("SELECT duration FROM sound_asset WHERE id = ?", (aid,)).fetchone()[0]
            assets.append((aid, float(dur)))
        if not assets:
            return
        idents = asset_identities(self.conn, {a: [(0.0, d)] for a, d in assets})
        plan: dict[str, dict[str, Any]] = {}
        for a, d in assets:
            ident = idents.get(a, {}).get("identities", {}).get((0.0, d))
            if ident is None:
                continue
            need = set(f0store.chunks_for(0.0, d, d)) - f0store.present(self.search.ws.f0, a, ident)
            if need:
                plan[f"{a}|{ident}"] = {"asset": a, "identity": ident, "duration": d, "chunks": need}
        self._submit_f0(plan)
