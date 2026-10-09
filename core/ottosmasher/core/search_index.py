"""三大搜索的索引（规格 09 §9.6.5、10 §10.2.5，ARCHITECTURE §4.6、§9；ROADMAP L24）。

- **语音检索索引**（``speech_index``，可清理的派生数据）：每采样一行 = 节奏分析（音块、停顿、语段、量化）+ 逐块属性 + 持续终点 + 角色，
  由「准备检索索引」任务构建（要解码音频算停顿，所以不在检索时现场做：检索不读波形）。失效键全部来自数据库（不探测文件），
  检索前对整个范围一次查询算出；改采样名称、星标、标签等不失效（R14.14）。
- **音高检索的覆盖**：音高索引就是 F0 测量（``Data/Measurements/f0``，不是缓存）。采样“已索引” = 它的范围所在的 F0 段都已测（当前声音身份）。
  身份只用数据库里的记录算（与 ``SpeechService.f0_identity`` 相同的结果，不探测文件）。
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
from collections.abc import Iterable, Sequence
from pathlib import Path
from typing import Any

import msgspec
import numpy as np

from ..algo import rhythm as rh
from ..algo import speech_search as ss
from ..algo import stretch as st
from ..domain.mapping import Mapping
from ..domain.overlap import overlaps
from ..models import f0store, fcpe
from . import settings as settings_mod
from . import units
from .clock import now_iso
from .edits import loads
from .errors import CoreError

KEY_VERSION = "speech-index-3"  # 3：分析属于“段 + 资产”，采样按判定区间读（所有者 2026-10-09）

# 资产存储的签名（范围、种类、文件快照；按固定顺序拼接）：文件被替换、存储变了 → 签名变（只用数据库，不探测文件）
STORAGE_SIG_SQL = (
    "(SELECT group_concat(v, '|') FROM (SELECT st.range_start || ':' || st.range_end || ':' || st.kind || ':' || COALESCE(mf.file_snapshot, '') AS v"
    " FROM asset_storage st JOIN media_file mf ON mf.id = st.media_file_id WHERE st.asset_id = {asset} ORDER BY st.kind, st.range_start, st.range_end, mf.id))"
)
_CHUNK = 900  # SQLite 参数个数上限以内


def _chunks(ids: Sequence[str]) -> Iterable[list[str]]:
    for i in range(0, len(ids), _CHUNK):
        yield list(ids[i : i + _CHUNK])


# ---------------------------------------------------------------- 语音检索索引：失效键


_KEY_SQL = """
SELECT s.id, s.asset_id, s.start, s."end", s.rhythm,
  {reads} AS reads,
  {storage} AS storage,
  src.file_snapshot AS src_snap,
  fr.result AS f0res, a.duration AS adur,
  a.source_id,
  (SELECT COUNT(*) || ':' || COALESCE(MAX(rt.updated_at), '') FROM range_tag rt WHERE rt.source_id = a.source_id AND rt.deleted = 0 AND rt.tags LIKE '%character:%') AS rtags,
  (SELECT group_concat(role || state, ',') FROM asset_role WHERE asset_id = s.asset_id) AS roles,
  (SELECT group_concat(tag, ',') FROM sample_tag WHERE sample_id = s.id AND tag LIKE 'character:%') AS chars,
  s.tag_judge_start, s.tag_judge_end
FROM sample s
JOIN sound_asset a ON a.id = s.asset_id
JOIN source src ON src.id = a.source_id
LEFT JOIN measure_head fh ON fh.owner_type = 'asset' AND fh.owner_id = s.asset_id AND fh.kind = 'f0'
LEFT JOIN measure_run fr ON fr.id = fh.run_id
WHERE s.id IN ({marks})
"""


def speech_keys(conn: sqlite3.Connection, sample_ids: Sequence[str]) -> dict[str, tuple[str, bool]]:
    """每个采样：（失效键, 有没有可用的语音分析）。没有分析的采样不需要索引（计入“缺少有效分析”）。"""
    penalty = settings_mod.values(conn)["analysis.penalty"]
    versions = [KEY_VERSION, rh.ALGO_VERSION, st.ALGO_VERSION, ss.ALGO_VERSION, ss.INDEX_VERSION, penalty]
    out: dict[str, tuple[str, bool]] = {}
    for part in _chunks(list(dict.fromkeys(sample_ids))):
        for r in conn.execute(_KEY_SQL.format(marks=",".join("?" * len(part)), storage=STORAGE_SIG_SQL.format(asset="s.asset_id"), reads=units.reads_sql("s", "a.source_id")), part):
            # 读到的段都有可用分析才需要索引（段改过、还没分析的计入“缺少有效分析”）；冲突的建索引时记为 none
            has = bool(r["reads"]) and all(not x.endswith("|-") for x in str(r["reads"]).split(","))
            # F0 只看采样范围所在的段（同一资产别处补测 F0 不让这条失效）
            f0 = loads(r["f0res"]) if r["f0res"] else {}
            need = f0store.chunks_for(float(r["start"]), float(r["end"]), float(r["adur"]))
            f0part = [f0.get("identity"), sorted(set(need) & set(f0.get("chunks") or []))]
            raw = [versions, f0part, *[r[k] for k in r.keys() if k not in ("f0res", "adur")]]
            out[r["id"]] = (hashlib.sha1(json.dumps(raw, default=str, ensure_ascii=False).encode("utf-8")).hexdigest(), has)
    return out


# ---------------------------------------------------------------- 语音检索索引：构建一行（任务进程里，只读）


def block_characters(conn: sqlite3.Connection, sample_id: str, blocks: Sequence[rh.Block], block_units: Sequence[str | None] = ()) -> list[str | None]:
    """块区间上的单一角色（09 §9.6.3）：采样本地的 ``character:`` 标签 + 产生这一块的那一段的说话人（一人才算；资产要带人声角色）
    + 与块区间交叠的区段标签里的 ``character:``（作用域规则同有效标签）；恰好一个才算，否则未知。"""
    s = conn.execute(
        "SELECT s.asset_id, a.mapping, a.source_id FROM sample s JOIN sound_asset a ON a.id = s.asset_id WHERE s.id = ?",
        (sample_id,),
    ).fetchone()
    if s is None:
        return [None] * len(blocks)
    local = {t for (t,) in conn.execute("SELECT tag FROM sample_tag WHERE sample_id = ? AND tag LIKE 'character:%'", (sample_id,))}
    roles = {r[0] for r in conn.execute("SELECT role FROM asset_role WHERE asset_id = ? AND state = 'on'", (s["asset_id"],))}
    try:
        m: Mapping | None = Mapping.of(loads(s["mapping"]))
    except CoreError:
        m = None
    tags = conn.execute(
        'SELECT scope, scope_role, scope_asset_id, start, "end", tags FROM range_tag WHERE source_id = ? AND deleted = 0 AND tags LIKE \'%character:%\'',
        (s["source_id"],),
    ).fetchall()
    speakers: dict[str, list[str]] = {}
    for u in {x for x in block_units if x}:
        seg_id = u[len("seg:") :].split("@", 1)[0]
        r = conn.execute("SELECT speakers FROM text_segment WHERE id = ?", (seg_id,)).fetchone()
        speakers[u] = loads(r[0]) if r else []
    out: list[str | None] = []
    for i, b in enumerate(blocks):
        found = set(local)
        u = block_units[i] if i < len(block_units) else None
        if u and "vocal" in roles:
            names = speakers.get(u) or []
            found |= {f"character:{names[0]}"} if len(names) == 1 else {f"participants:{n}" for n in names}
        src_win = None
        if m is not None:
            try:
                src_win = (m.to_source(b.onset), m.to_source(b.end))
            except CoreError:
                src_win = None
        for a in tags:
            if a["scope"] == "asset":
                if a["scope_asset_id"] != s["asset_id"] or not overlaps(b.onset, b.end, a["start"], a["end"]):
                    continue
            else:
                if src_win is None or not overlaps(src_win[0], src_win[1], a["start"], a["end"]):
                    continue
                if a["scope"] == "role" and a["scope_role"] not in roles:
                    continue
            found |= {t for t in loads(a["tags"]) if t.startswith("character:")}
        chars = {t for t in found if t.startswith("character:")}
        out.append(next(iter(chars)) if len(chars) == 1 and len(found) == 1 else None)
    return out


def build_row(rhythm: Any, conn: sqlite3.Connection, sample_id: str) -> tuple[str, str | None, bytes | None]:
    """一个采样的索引行：（status, reason, data）。``rhythm`` 是 ``RhythmService``（只读用）。"""
    try:
        an = rhythm.analysis(sample_id)
    except CoreError as e:
        return "none", e.code, None
    try:
        i0, frames, have = rhythm.speech.f0_frames(an.asset_id, *an.window)
        frames = np.asarray(frames, dtype=np.float64)
        have = np.asarray(have, dtype=bool)
    except CoreError:
        i0, frames, have = 0, np.zeros((0, 3)), np.zeros(0, dtype=bool)
    times = ((i0 + np.arange(len(frames))) * fcpe.HOP + fcpe.HOP / 2) / fcpe.SR
    energy = frames[:, 2] if len(frames) else np.zeros(0)
    measured = have & np.isfinite(energy) if len(frames) else have
    head = rhythm.speech.sample_view(sample_id)["head"]
    manual = bool(head and head.get("manual"))
    thr = ss.active_threshold(energy, measured)
    sustain = [ss.sustain_end(b, an.pauses, times, energy, measured, thr, manual) for b in an.blocks]
    chars = block_characters(conn, sample_id, an.blocks, [an.phone_units[b.members[0]] if b.members[0] < len(an.phone_units) else None for b in an.blocks])
    cells = list(an.raw.cells or [])
    idx = ss.build_index(
        sample_id, an.phones, an.blocks, an.pauses, an.seg, an.cuts, an.segments, an.dur, cells, an.window, an.sr, an.attrs, sustain, chars,
        an.manual_cells, an.penalty,
    )
    wire = ss.to_wire(idx, [b.members for b in an.blocks])
    return "ok", None, msgspec.msgpack.encode(wire)


class SpeechIndex:
    """Core 侧：范围的索引状态、采纳任务结果、给检索进程读。"""

    def __init__(self, conn: sqlite3.Connection) -> None:
        self.conn = conn

    def status(self, sample_ids: Sequence[str]) -> dict[str, list[str]]:
        """{"ready": 可检索, "none": 有分析但建不出（缺少有效分析）, "missing": 没有分析, "stale": 要准备}。"""
        keys = speech_keys(self.conn, sample_ids)
        have: dict[str, tuple[str, str]] = {}
        for part in _chunks(list(keys)):
            for sid, key, status in self.conn.execute(
                f"SELECT sample_id, input_key, status FROM speech_index WHERE sample_id IN ({','.join('?' * len(part))})", part
            ):
                have[sid] = (key, status)
        out: dict[str, list[str]] = {"ready": [], "none": [], "missing": [], "stale": []}
        for sid in sample_ids:
            k = keys.get(sid)
            if k is None:
                continue  # 采样已删除
            key, has = k
            if not has:
                out["missing"].append(sid)
                continue
            cur = have.get(sid)
            if cur is None or cur[0] != key:
                out["stale"].append(sid)
            elif cur[1] == "ok":
                out["ready"].append(sid)
            else:
                out["none"].append(sid)
        return out

    def adopt(self, rows: Iterable[tuple[str, str, str, str | None, bytes | None]]) -> int:
        """任务结果（采样, 构建时的键, status, reason, data）：键仍然等于现在的键才写（中途变了就丢掉，下次再准备）。"""
        rows = list(rows)
        now = speech_keys(self.conn, [r[0] for r in rows])
        n = 0
        ts = now_iso()
        for sid, key, status, reason, data in rows:
            cur = now.get(sid)
            if cur is None or cur[0] != key:
                continue
            self.conn.execute(
                "INSERT INTO speech_index(sample_id, input_key, status, reason, data, built_at) VALUES (?, ?, ?, ?, ?, ?)"
                " ON CONFLICT(sample_id) DO UPDATE SET input_key=excluded.input_key, status=excluded.status, reason=excluded.reason,"
                " data=excluded.data, built_at=excluded.built_at",
                (sid, key, status, reason, data, ts),
            )
            n += 1
        return n


def read_wires(conn: sqlite3.Connection, sample_ids: Sequence[str]) -> list[dict[str, Any]]:
    """检索进程：按给定顺序读出可检索的行（解码 msgpack；``key`` = 失效键，方案缓存用）。"""
    dec = msgspec.msgpack.Decoder()
    by: dict[str, dict[str, Any]] = {}
    for part in _chunks(list(sample_ids)):
        for sid, key, data in conn.execute(
            f"SELECT sample_id, input_key, data FROM speech_index WHERE status = 'ok' AND sample_id IN ({','.join('?' * len(part))})", part
        ):
            w = dec.decode(data)
            w["key"] = f"{sid}:{key}"
            by[sid] = w
    return [by[s] for s in sample_ids if s in by]


# ---------------------------------------------------------------- 音高检索：F0 身份与覆盖（只用数据库）


def f0_sha() -> str:
    from ..models import registry

    return next(f.sha256 for f in registry.spec(fcpe.MODEL_ID).files if f.rel_path == fcpe.MODEL_FILE)


def asset_identities(conn: sqlite3.Connection, ranges: dict[str, list[tuple[float, float]]], sha: str | None = None) -> dict[str, dict[str, Any]]:
    """每个资产：存放这些区间的那段存储上的 F0 身份（与 ``SpeechService.f0_identity`` 同一算法）、时长；
    区间跨了不同存储时按第一个区间（同一资产的采样几乎总在同一存储里；跨存储的区间单独记 ``mixed``）。"""
    sha = sha or f0_sha()
    out: dict[str, dict[str, Any]] = {}
    ids = list(ranges)
    for part in _chunks(ids):
        rows = conn.execute(
            f"SELECT a.id, a.origin, a.stream_ordinal, a.mapping, a.duration FROM sound_asset a WHERE a.id IN ({','.join('?' * len(part))})", part
        ).fetchall()
        storage: dict[str, list[sqlite3.Row]] = {}
        for r in conn.execute(
            "SELECT st.asset_id, st.range_start, st.range_end, st.kind, m.id AS mid, m.file_snapshot FROM asset_storage st"
            f" JOIN media_file m ON m.id = st.media_file_id WHERE st.asset_id IN ({','.join('?' * len(part))}) ORDER BY st.kind = 'primary' DESC",
            part,
        ):
            storage.setdefault(r["asset_id"], []).append(r)
        for a in rows:
            idents: dict[tuple[float, float], str | None] = {}
            for rg in ranges[a["id"]]:
                ident = None
                for s in storage.get(a["id"], []):
                    if s["range_start"] - 1e-6 <= rg[0] and rg[1] <= s["range_end"] + 1e-6:
                        snap = loads(s["file_snapshot"]) if s["file_snapshot"] else {}
                        audio = {
                            "asset": a["id"], "mapping": loads(a["mapping"]), "media": s["mid"],
                            "snapshot": {k: snap.get(k) for k in ("size", "mtime_ns")},
                            "ordinal": a["stream_ordinal"] if a["origin"] == "stream" else 0,
                            "storage": [s["range_start"], s["range_end"], 0.0],
                        }
                        ident = f0store.identity(audio, sha)
                        break
                idents[rg] = ident
            out[a["id"]] = {"duration": float(a["duration"]), "identities": idents}
    return out


def pitch_coverage(conn: sqlite3.Connection, f0_root: Path, samples: Sequence[tuple[str, str, float, float]]) -> dict[str, Any]:
    """采样（id, 资产, 起, 止）的覆盖：范围内的 F0 段是否都已测（当前身份）。返回 {"ready": [...], "pending": [...], "plan": {资产: {身份, 时长, 缺的段}}}。"""
    ranges: dict[str, list[tuple[float, float]]] = {}
    for _sid, aid, a, b in samples:
        ranges.setdefault(aid, []).append((a, b))
    idents = asset_identities(conn, ranges)
    present_cache: dict[tuple[str, str], set[int]] = {}
    ready, pending = [], []
    plan: dict[str, dict[str, Any]] = {}
    for sid, aid, a, b in samples:
        info = idents.get(aid)
        ident = info["identities"].get((a, b)) if info else None
        if ident is None:
            pending.append(sid)
            continue
        key = (aid, ident)
        if key not in present_cache:
            present_cache[key] = f0store.present(f0_root, aid, ident)
        need = set(f0store.chunks_for(a, b, info["duration"])) - present_cache[key]
        if need:
            pending.append(sid)
            p = plan.setdefault(f"{aid}|{ident}", {"asset": aid, "identity": ident, "duration": info["duration"], "chunks": set()})
            p["chunks"] |= need
        else:
            ready.append(sid)
    return {"ready": ready, "pending": pending, "plan": plan, "identities": idents}
