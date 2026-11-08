"""单音 · 音色 / 单音 · 瞬态（规格 10 §10.3、03 §3.4.3，16 R16）：Core 侧——指标的有效性、准备任务、即时筛选的条件。

- 指标按采样存（``acoustic_metric``），有效 = 资产、范围、存储签名、算法版本都等于现在的（SQL 里核对，筛选可以直接分页）；
- 「后台准备当前范围指标」= 模型通道任务：先补测范围里缺的 F0（采样自己的音高测量，A16），再解码采样音频算指标；
- 筛选是即时浏览（不是固定结果）：条件进采样列表的查询；缺少所选指标的采样不命中，按指标单独计数。
"""

from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Any

from ..algo import acoustic as ac
from ..models import fcpe
from ..store.db import transaction
from ..store.workspace import Workspace
from . import assets as assets_mod
from .clock import now_iso
from .edits import dumps
from .errors import CoreError
from .probes import record_probes
from .search_index import STORAGE_SIG_SQL, f0_sha, pitch_coverage

JOB_KIND = "acoustic.measure"


def algo_tag() -> str:
    """算法版本 + F0 模型与前端（F0 换了模型，音高类指标就不同）。"""
    return f"{ac.ALGO_VERSION}|{f0_sha()[:12]}|{fcpe.FRONTEND_VERSION}"


def valid_clause(alias: str = "s") -> str:
    """“这个采样有有效指标行 m”的 SQL 条件（m 是 acoustic_metric 的别名）；参数：算法版本。"""
    return (
        f"m.sample_id = {alias}.id AND m.asset_id = {alias}.asset_id AND m.start = {alias}.start AND m.\"end\" = {alias}.\"end\""
        f" AND m.algo = ? AND m.storage_sig = {STORAGE_SIG_SQL.format(asset=alias + '.asset_id')}"
    )


def filter_sql(conds: list[tuple[str, float | None, float | None]], alias: str = "s") -> tuple[str, list[Any]]:
    """采样列表的附加条件：有有效指标且每个所选指标都在范围内（未知 = null → 不命中）。"""
    parts, args = [valid_clause(alias)], [algo_tag()]
    for name, lo, hi in conds:
        if lo is not None:
            parts.append(f"json_extract(m.metrics, '$.{name}') >= ?")
            args.append(lo)
        if hi is not None:
            parts.append(f"json_extract(m.metrics, '$.{name}') <= ?")
            args.append(hi)
        parts.append(f"json_extract(m.metrics, '$.{name}') IS NOT NULL")
    return f"EXISTS (SELECT 1 FROM acoustic_metric m WHERE {' AND '.join(parts)})", args


class AcousticService:
    def __init__(self, conn: sqlite3.Connection, ws: Workspace, jobs: Any, search: Any, speech: Any, support_dir: Path, emit: Any = None) -> None:
        self.conn = conn
        self.ws = ws
        self.jobs = jobs
        self.search = search
        self.speech = speech
        self.support_dir = support_dir
        self.emit = emit
        jobs.adopters[JOB_KIND] = self._adopt

    def status(self, scope: dict[str, Any] | None, metrics: list[str]) -> dict[str, Any]:
        """范围里：已准备（有有效指标行）的数量、未准备的数量、每个指标缺失（未准备或未知）的数量。"""
        ids = self.search.scope_ids(scope)
        ready: dict[str, dict[str, Any]] = {}
        from .edits import loads

        tag = algo_tag()
        for i in range(0, len(ids), 900):
            part = ids[i : i + 900]
            for sid, js in self.conn.execute(
                f"SELECT s.id, m.metrics FROM sample s JOIN acoustic_metric m ON {valid_clause('s')} WHERE s.id IN ({','.join('?' * len(part))})",
                [tag, *part],
            ):
                ready[sid] = loads(js)
        missing = {k: sum(1 for sid in ids if (ready.get(sid) or {}).get(k) is None) for k in metrics}
        return {"total": len(ids), "ready": len(ready), "stale": len(ids) - len(ready), "missing": missing}

    def read(self, ids: list[str]) -> list[dict[str, Any]]:
        from .edits import loads

        out = []
        tag = algo_tag()
        for sid in dict.fromkeys(ids):
            if self.conn.execute("SELECT 1 FROM sample WHERE id=?", (sid,)).fetchone() is None:
                raise CoreError("sample-not-found", id=sid)
            row = self.conn.execute(
                f"SELECT m.metrics FROM sample s JOIN acoustic_metric m ON {valid_clause('s')} WHERE s.id=?", (tag, sid)
            ).fetchone()
            exists = self.conn.execute("SELECT 1 FROM acoustic_metric WHERE sample_id=?", (sid,)).fetchone()
            out.append({"id": sid, "state": "ready" if row else "stale" if exists else "missing", "metrics": loads(row[0]) if row else None})
        return out

    def prepare(self, scope: dict[str, Any] | None) -> dict[str, Any]:
        ids = self.search.scope_ids(scope)
        tag = algo_tag()
        have = set()
        for i in range(0, len(ids), 900):
            part = ids[i : i + 900]
            have |= {r[0] for r in self.conn.execute(
                f"SELECT s.id FROM sample s JOIN acoustic_metric m ON {valid_clause('s')} WHERE s.id IN ({','.join('?' * len(part))})", [tag, *part])}
        todo = [r for r in self.search._sample_ranges(ids) if r[0] not in have]
        if not todo:
            raise CoreError("search-nothing-to-prepare")
        cov = pitch_coverage(self.conn, self.ws.f0, todo)
        plan = self.search._f0_plan(cov)
        items = []
        for sid, aid, a, b in todo:
            ident = cov["identities"].get(aid, {}).get("identities", {}).get((a, b))
            asset = assets_mod.get(self.conn, aid)
            try:
                ref, win, media = assets_mod.locate(self.conn, self.ws.root, asset, a, b)
                assets_mod.check_media(media)
            except CoreError:
                continue
            sig = self.conn.execute(f"SELECT {STORAGE_SIG_SQL.format(asset='?')}", (aid,)).fetchone()[0]
            items.append({
                "sample": sid, "asset": aid, "start": a, "end": b, "identity": ident, "duration": float(asset["duration"]), "sig": sig,
                "file": {"path": ref.path, "ordinal": ref.ordinal, "sample_rate": ref.sample_rate, "channels": ref.channels, "codec": ref.codec, "format": ref.format_name},
                "storage": [win.local_start, win.local_end, win.file_start],
            })
        if not items:
            raise CoreError("search-nothing-to-prepare")
        params = {"items": items, "plan": plan, "algo": tag, "f0root": str(self.ws.f0), "models_dir": str(self.ws.models), "support_dir": str(self.support_dir)}
        return self.jobs.submit(JOB_KIND, params, {"sample": [it["sample"] for it in items]})

    def _adopt(self, job: dict[str, Any], result: dict[str, Any]) -> None:
        ts = now_iso()
        n = 0
        with transaction(self.conn):
            self.speech._adopt_f0(job["id"], result.get("f0") or [], ts)
            import json

            rows = json.loads((self.jobs.jobs_dir / job["id"] / result["rows"]).read_text(encoding="utf-8")) if result.get("rows") else []
            for row in rows:
                cur = self.conn.execute(
                    f'SELECT s.asset_id, s.start, s."end", {STORAGE_SIG_SQL.format(asset="s.asset_id")} FROM sample s WHERE s.id = ?', (row["sample"],)
                ).fetchone()
                if cur is None or (cur[0], cur[1], cur[2], cur[3]) != (row["asset"], row["start"], row["end"], row["sig"]) or row["algo"] != algo_tag():
                    continue  # 任务期间采样变了：不登记，下次再准备
                self.conn.execute(
                    'INSERT INTO acoustic_metric(sample_id, asset_id, start, "end", storage_sig, algo, metrics, built_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)'
                    ' ON CONFLICT(sample_id) DO UPDATE SET asset_id=excluded.asset_id, start=excluded.start, "end"=excluded."end",'
                    " storage_sig=excluded.storage_sig, algo=excluded.algo, metrics=excluded.metrics, built_at=excluded.built_at",
                    (row["sample"], row["asset"], row["start"], row["end"], row["sig"], row["algo"], dumps(row["metrics"]), ts),
                )
                n += 1
        record_probes(self.conn, result.get("probes") or [])
        if self.emit:
            self.emit("search.coverage", {"mode": "metrics", "adopted": n})
