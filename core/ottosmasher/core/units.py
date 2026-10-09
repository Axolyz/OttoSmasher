"""分析归属与采样读取（所有者 2026-10-09【基线变更】，docs/QUESTIONS.md「原片上的四类对象」C、D 节）。

- 分析结果归属于“文本层的段 + 具体那条声音资产”：``seg:<段>@<资产>``（measure_head / measure_run 的归属类型 ``asset_text``）。
  版本、当前头、人工修音素时间都挂在这里；同一段在不同的轨上各有一份。
  目标 = 段区间映射到资产（裁到覆盖范围），窗口 = 目标 ± 对齐容差，只送这段的文本。
- 每个分析版本记下分析时的段内容（``seg_start / seg_end / seg_text``）。段的文本或区间改了 → 这些版本停用（不可用），
  直到重新分析；撤销那次修改 → 内容又一致，立即恢复。
- **可用的分析**（一段在一条资产上）：内容与段现在一致的成功版本里，优先当前头，其次人工版本，再其次最新的；文件快照另在读取时核对。
- 采样只读取：读与判定区间正长度交叠的所有段在采样所在资产上的分析；任何一段没有可用分析 → 节奏不可用并写明缺哪段；
  音素裁到采样范围，被裁掉一部分的非停顿音素标 ◐；两段的非停顿音素在采样范围内交叠 → 冲突（不自动裁决）。
时钟：段与判定区间是原片秒；分析的目标、音素跨度、音素时间是资产局部秒。
"""

from __future__ import annotations

import sqlite3
from typing import Any

from ..domain.mapping import Mapping
from .edits import SEGMENT_MAX, loads
from .errors import CoreError

OWNER = "asset_text"
EPS = 1e-6


def unit_id(segment: str, asset: str) -> str:
    return f"seg:{segment}@{asset}"


def parse(unit: str) -> tuple[str, str]:
    if not unit.startswith("seg:") or "@" not in unit:
        raise CoreError("speech-blocked", reason="not-a-unit")
    seg, asset = unit[len("seg:") :].split("@", 1)
    return seg, asset


def seg_target(seg_start: float, seg_end: float, mapping: Any, duration: float) -> tuple[float, float] | None:
    """段在资产上的目标（资产局部秒）：段区间裁到资产覆盖的原片范围再换算；完全在覆盖范围外 → None。"""
    m = mapping if isinstance(mapping, Mapping) else Mapping.of(loads(mapping) if isinstance(mapping, str) else mapping)
    lo, hi = m.source_start, m.source_end
    if not (seg_end > lo and seg_start < hi):
        return None
    try:
        la, lb = max(0.0, m.to_local(max(seg_start, lo))), min(duration, m.to_local(min(seg_end, hi)))
    except CoreError:
        return None
    return (la, lb) if lb > la else None


def analysis_track(conn: sqlite3.Connection, source_id: str) -> str | None:
    """原片的分析音轨（原片页「语音分析」的默认、自动准备的整轨 F0）：默认人声轨；没有就是原混音（原片默认音频流的那条）。原片不可用 → None。"""
    row = conn.execute(
        "SELECT (SELECT asset_id FROM default_track WHERE source_id = src.id AND role = 'vocal') AS vox, src.default_audio_stream AS ord"
        " FROM source src WHERE src.id = ? AND src.media_state = 'available'",
        (source_id,),
    ).fetchone()
    if row is None:
        return None
    if row["vox"] is not None:
        return row["vox"]
    r = conn.execute(
        "SELECT id FROM sound_asset WHERE source_id = ? AND origin = 'stream' ORDER BY (stream_ordinal IS ?) DESC, stream_ordinal LIMIT 1",
        (source_id, row["ord"]),
    ).fetchone()
    return r[0] if r else None


def content_matches(run: Any, seg: Any) -> bool:
    return (
        run["seg_text"] is not None
        and run["seg_text"] == seg["text"]
        and run["seg_start"] is not None
        and abs(float(run["seg_start"]) - float(seg["start"])) < EPS
        and abs(float(run["seg_end"]) - float(seg["end"])) < EPS
    )


def pick_usable(runs: list[Any], seg: Any, head_run: str | None) -> Any | None:
    """一段在一条资产上的可用版本：内容一致的成功版本里，当前头 > 人工 > 最新。``runs`` 按 created_at、rowid 降序。"""
    ok = [r for r in runs if r["status"] == "ok" and content_matches(r, seg)]
    if not ok:
        return None
    for r in ok:
        if r["id"] == head_run:
            return r
    manual = [r for r in ok if r["manual"]]
    return manual[0] if manual else ok[0]


# ---------------------------------------------------------------- SQL：采样读哪些段（列表状态、检索索引的失效键、固定结果的快照）


def _segs(s: str, src: str) -> str:
    return (
        f"t.source_id = {src} AND t.deleted = 0 AND t.start < {s}.tag_judge_end AND t.\"end\" > {s}.tag_judge_start"
        f" AND t.start > {s}.tag_judge_start - {SEGMENT_MAX + 1e-6}"
    )


def _runs(s: str, extra: str = "") -> str:
    return (
        f"FROM measure_run r WHERE r.owner_type = 'asset_text' AND r.kind = 'alignment' AND r.owner_id = 'seg:' || t.id || '@' || {s}.asset_id{extra}"
    )


def _usable(s: str) -> str:
    return _runs(s, " AND r.status = 'ok' AND r.seg_text = t.text AND abs(r.seg_start - t.start) < 1e-6 AND abs(r.seg_end - t.\"end\") < 1e-6")


def state_sql(s: str = "s", src: str = "a.source_id") -> str:
    """语音分析状态（列表）：stale（段改过待重新分析）> incomplete（读到的段有的还没分析）> failed > none > partial（◐）/ manual / ok。
    partial（◐）= 只读到某段的一部分：采样范围没有盖住读到的某一段的目标区间（可用版本的 range = 段映射到资产、裁到覆盖）。
    对齐器把段前后的空白吸进首尾音素、伸出采样范围的不算（那些音素在合成结果里单独标 clipped）。"""
    flags = (
        f"SELECT EXISTS (SELECT 1 {_usable(s)}) AS u,"
        f" EXISTS (SELECT 1 {_runs(s, ' AND r.status = ' + chr(39) + 'ok' + chr(39))}) AS ok,"
        f" EXISTS (SELECT 1 {_runs(s, ' AND r.status = ' + chr(39) + 'failed' + chr(39))}) AS fl,"
        f" EXISTS (SELECT 1 {_usable(s)} AND r.manual = 1) AS man,"
        f" EXISTS (SELECT 1 {_usable(s)} AND (r.range_start < {s}.start - 1e-6 OR r.range_end > {s}.\"end\" + 1e-6)) AS part"
        f" FROM text_segment t WHERE {_segs(s, src)}"
    )
    return (
        "(SELECT CASE WHEN COUNT(*) = 0 THEN 'none'"
        " WHEN SUM(u = 0 AND ok = 1) > 0 THEN 'stale'"
        " WHEN SUM(u) = COUNT(*) THEN (CASE WHEN MAX(part) = 1 THEN 'partial' WHEN MAX(man) = 1 THEN 'manual' ELSE 'ok' END)"
        " WHEN SUM(u) > 0 THEN 'incomplete'"
        " WHEN SUM(fl) > 0 THEN 'failed' ELSE 'none' END"
        f" FROM ({flags}))"
    )


def reads_sql(s: str = "s", src: str = "a.source_id") -> str:
    """采样读到的段与各段用的分析版本的签名（检索索引的失效键、固定结果的“分析变了”判断）：
    段的编号、区间、文本、说话人 + 可用版本（没有 = '-'）+ 它的文件快照。没有读到段 → NULL。"""
    pick = (
        f"(SELECT r.id || ':' || r.manual || ':' || COALESCE(json_extract(r.inputs, '$.audio.snapshot'), '') {_usable(s)}"
        " ORDER BY (r.id = (SELECT h.run_id FROM measure_head h WHERE h.owner_type = 'asset_text' AND h.owner_id = r.owner_id AND h.kind = 'alignment')) DESC,"
        " r.manual DESC, r.created_at DESC, r.rowid DESC LIMIT 1)"
    )
    return (
        "(SELECT group_concat(x, ',') FROM (SELECT t.id || '|' || t.start || '|' || t.\"end\" || '|' || t.text || '|' || t.speakers || '|' || COALESCE("
        f"{pick}, '-') AS x FROM text_segment t WHERE {_segs(s, src)} ORDER BY t.start, t.\"end\", t.id))"
    )


# ---------------------------------------------------------------- 合并：采样读到的几段 → 一个结果（裁到采样范围）


def _span(phones: list[dict[str, Any]]) -> tuple[float, float] | None:
    sp = [p for p in phones if p["label"] != "pau"]
    return (float(sp[0]["start"]), float(sp[-1]["end"])) if sp else None


def span_of(result: dict[str, Any] | None) -> tuple[float, float] | None:
    """一次成功结果的音素跨度（首个到末个非停顿音素）。"""
    return _span(result["phones"]) if result and result.get("phones") else None


def clip(phones: list[dict[str, Any]], start: float, end: float) -> list[dict[str, Any]]:
    """裁到 [start, end)；被裁掉一部分的非停顿音素标 ``clipped``（◐）。"""
    out = []
    for p in phones:
        if not (p["end"] > start and p["start"] < end):
            continue
        a, b = max(float(p["start"]), start), min(float(p["end"]), end)
        q = p | {"start": a, "end": b}
        if p["label"] != "pau" and (a > float(p["start"]) + EPS or b < float(p["end"]) - EPS):
            q["clipped"] = True
        out.append(q)
    return out


def merge(units: list[dict[str, Any]], start: float, end: float) -> dict[str, Any]:
    """几段（各自的可用分析：``result`` 里有 phones / morae / words）合成一个结果，音素裁到 [start, end)。

    每个输入带 ``unitId``、``ordinal``（段在文本层里的序号）。按首个非停顿音素排序；两段的非停顿音素在范围内正长度交叠 →
    ``{"conflict": {a, b, start, end, units}}``（a、b 是序号，start–end 是交叠区间的资产局部秒；不自动裁决）。
    每段去掉首尾停顿，段间空隙补一个停顿；第一段前、最后一段后的停顿保留。mora、词的序号按段依次平移；每个音素记下来自第几个输入（``seg``）。
    """
    parts = []
    for i, u in enumerate(units):
        phones = list(u["result"]["phones"])
        sp = _span(phones)
        if sp is None:
            continue
        parts.append((sp, i, u, phones))
    parts.sort(key=lambda x: (x[0][0], x[0][1]))
    speech = [clip([p for p in ph if p["label"] != "pau"], start, end) for _, _, _, ph in parts]
    for i in range(len(parts)):
        for j in range(i + 1, len(parts)):
            for x in speech[i]:
                for y in speech[j]:
                    a, b = max(x["start"], y["start"]), min(x["end"], y["end"])
                    if b - a > EPS:
                        ua, ub = parts[i][2], parts[j][2]
                        oa, ob = sorted((ua.get("ordinal") or 0, ub.get("ordinal") or 0))
                        return {"conflict": {"a": oa, "b": ob, "start": round(float(a), 6), "end": round(float(b), 6), "units": [ua["unitId"], ub["unitId"]]}}
    phones: list[dict[str, Any]] = []
    morae: list[str] = []
    words: list[Any] = []
    for k, (sp, idx, u, ph) in enumerate(parts):
        res = u["result"]
        mo, wo = len(morae), len(words)
        lo = 0 if k == 0 else next(n for n, p in enumerate(ph) if p["label"] != "pau")
        hi = len(ph) if k == len(parts) - 1 else max(n for n, p in enumerate(ph) if p["label"] != "pau") + 1
        if k > 0 and phones and sp[0] > phones[-1]["end"] + EPS:
            phones.append({"label": "pau", "start": phones[-1]["end"], "end": sp[0], "mora": None, "word": None, "seg": idx})
        for p in ph[lo:hi]:
            q = dict(p)
            if q.get("mora") is not None:
                q["mora"] = int(q["mora"]) + mo
            if q.get("word") is not None:
                q["word"] = int(q["word"]) + wo
            q["seg"] = idx
            phones.append(q)
        morae += list(res.get("morae") or [])
        words += [w | {"moraStart": int(w["moraStart"]) + mo} if w.get("moraStart") is not None else w for w in res.get("words") or []]
    out_phones = clip(phones, start, end)
    if len(parts) == 1:  # 只读到一段：其余字段（前端、对齐器信息）照搬
        return parts[0][2]["result"] | {"phones": out_phones, "morae": morae, "words": words}
    return {"phones": out_phones, "morae": morae, "words": words, "frontend": {}}


def partial(span: tuple[float, float] | None, start: float, end: float) -> bool:
    return span is not None and (span[0] < start - EPS or span[1] > end + EPS)
