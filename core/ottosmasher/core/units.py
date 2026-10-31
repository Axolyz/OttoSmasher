"""音素属于原素材时间线（所有者 2026-10-12【基线变更】，docs/history/QUESTIONS.md「音素回到原素材时间线、去掉父采样」）。

- 一句台词（文本层的段）只有一份当前音素，原素材上的所有音轨都读它；唯一的例外是回导成品（外面改过的声音）：
  它和从它再加工出来的音轨读“段 + 这个回导成品”那一份。键 = ``seg:<段>@<原素材或回导成品>``（measure_head / measure_run 的归属类型 ``asset_text``）。
  版本、当前头、人工修音素时间都挂在这里；在哪条轨上测的只作记录（``measure_run.asset_id``）。
- 测量结果里的时间（音素、有效范围、窗口、目标、跨度）都存**原素材秒**；每条音轨读时按自己的映射换成本轨时间，
  越出这条轨覆盖范围的音素去掉、被裁掉一部分的非停顿音素标 clipped（◐）。
- 只在盖住整句的音轨上测（对齐要整句），所以没有“半句分析”。
- 不含人声的音轨不读音素（所有者 2026-10-12）：含人声 = 开着“人声”角色，或者一个角色都没开、又不是从分离声部来的（原混音以及从它截取 / 拉平 / 回导的）。
  按角色在读取时判断，不存。
- 每个分析版本记下分析时的段内容（``seg_start / seg_end / seg_text``）。段的文本或区间改了 → 这些版本停用，直到重新分析；撤销那次修改 → 立即恢复。
- **可用的音素**（一段在一个归属上）：内容与段现在一致的成功版本里，优先当前头，其次人工版本，再其次最新的。
- 采样只读取：读与判定区间正长度交叠的所有段的音素；任何一段没有可用音素 → 节奏不可用并写明缺哪段；
  音素裁到采样范围，被裁掉一部分的非停顿音素标 ◐；两段的非停顿音素在采样范围内交叠 → 冲突（不自动裁决）。
"""

from __future__ import annotations

import sqlite3
from collections.abc import Callable
from typing import Any

from ..domain.mapping import FULL_TRACK_TOLERANCE, Mapping
from .edits import SEGMENT_MAX, loads
from .errors import CoreError

OWNER = "asset_text"
EPS = 1e-6


def unit_id(segment: str, base: str) -> str:
    return f"seg:{segment}@{base}"


def parse(unit: str) -> tuple[str, str]:
    """``seg:<段>@<x>`` → (段, x)；x 是原素材、回导成品，或（界面按采样所在音轨拼的）某条音轨，用 ``normalize`` 换成归属。"""
    if not unit.startswith("seg:") or "@" not in unit:
        raise CoreError("speech-blocked", reason="not-a-unit")
    seg, rest = unit[len("seg:") :].split("@", 1)
    return seg, rest


def base_of(asset: Any) -> str:
    """音轨读哪一份音素：回导来的 = 那个回导成品；其余 = 原素材。"""
    return asset["reimport_id"] or asset["source_id"]


def base_sql(a: str = "a") -> str:
    return f"COALESCE({a}.reimport_id, {a}.source_id)"


def normalize(conn: sqlite3.Connection, unit: str) -> str:
    """把 ``seg:<段>@<音轨>`` 换成 ``seg:<段>@<归属>``；本来就是归属的原样返回。"""
    seg, x = parse(unit)
    r = conn.execute("SELECT source_id, reimport_id FROM sound_asset WHERE id=?", (x,)).fetchone()
    return unit_id(seg, base_of(r)) if r is not None else unit


def voiced(asset: Any) -> bool:
    """含人声：开着“人声”角色；或者一个角色都没开、又不是从分离声部来的（原混音以及从它截取 / 拉平 / 回导的）。"""
    roles = list(asset.get("roles") or [])
    return "vocal" in roles or (not roles and not asset.get("from_separation"))


def voiced_sql(a: str = "a") -> str:
    return (
        f"(EXISTS (SELECT 1 FROM asset_role vr WHERE vr.asset_id = {a}.id AND vr.role = 'vocal' AND vr.state = 'on')"
        f" OR ({a}.from_separation = 0 AND NOT EXISTS (SELECT 1 FROM asset_role vr WHERE vr.asset_id = {a}.id AND vr.state = 'on')))"
    )


def _mapping(mapping: Any) -> Mapping:
    return mapping if isinstance(mapping, Mapping) else Mapping.of(loads(mapping) if isinstance(mapping, str) else mapping)


def seg_target(seg_start: float, seg_end: float, mapping: Any, duration: float) -> tuple[float, float] | None:
    """段在资产上的目标（资产局部秒）：段区间裁到资产覆盖的原片范围再换算；完全在覆盖范围外 → None。"""
    m = _mapping(mapping)
    lo, hi = m.source_start, m.source_end
    if not (seg_end > lo and seg_start < hi):
        return None
    try:
        la, lb = max(0.0, m.to_local(max(seg_start, lo))), min(duration, m.to_local(min(seg_end, hi)))
    except CoreError:
        return None
    return (la, lb) if lb > la else None


def covers(mapping: Any, seg_start: float, seg_end: float) -> bool:
    """音轨盖住整句（容差同默认轨的 20 ms）：只有这样的轨能拿来测这句的音素。"""
    m = _mapping(mapping)
    return m.source_start <= seg_start + FULL_TRACK_TOLERANCE and m.source_end >= seg_end - FULL_TRACK_TOLERANCE


def analysis_track(conn: sqlite3.Connection, source_id: str) -> str | None:
    """原片的分析音轨（采样详情 / 批量 / 原片页「语音分析」的默认、自动准备的整轨 F0）：默认人声轨；没有就是原混音（原片默认音频流的那条）。原片不可用 → None。"""
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
    """一段在一个归属上的可用版本：内容一致的成功版本里，当前头 > 人工 > 最新。``runs`` 按 created_at、rowid 降序。"""
    ok = [r for r in runs if r["status"] == "ok" and content_matches(r, seg)]
    if not ok:
        return None
    for r in ok:
        if r["id"] == head_run:
            return r
    manual = [r for r in ok if r["manual"]]
    return manual[0] if manual else ok[0]


# ---------------------------------------------------------------- 时间换算：测量音轨局部秒 → 原素材秒（采纳时）；原素材秒 → 读取方本轨（读取时）


def _shift(res: dict[str, Any], fn: Callable[[float], float]) -> dict[str, Any]:
    phones = []
    for p in res.get("phones") or []:
        q = dict(p) | {"start": round(fn(float(p["start"])), 6), "end": round(fn(float(p["end"])), 6)}
        if p.get("eff") is not None:
            q["eff"] = [round(fn(float(p["eff"][0])), 6), round(fn(float(p["eff"][1])), 6)]
        phones.append(q)
    out = dict(res) | {"phones": phones}
    if res.get("window") is not None:
        out["window"] = [round(fn(float(res["window"][0])), 6), round(fn(float(res["window"][1])), 6)]
    return out


def to_source(res: dict[str, Any], mapping: Any) -> dict[str, Any]:
    """测量结果（测量音轨局部秒）→ 原素材秒。"""
    m = _mapping(mapping)
    return _shift(res, lambda t: m.to_source(min(max(t, 0.0), m.duration)))


def to_reader(phones: list[dict[str, Any]], mapping: Any) -> list[dict[str, Any]]:
    """音素（原素材秒）→ 读取方本轨局部秒：完全在这条轨覆盖范围外的去掉，被裁掉一部分的非停顿音素标 clipped。
    每个输出音素记下它在原结果里的序号（``i``，人工修时间用）。"""
    m = _mapping(mapping)
    lo, hi = m.source_start, m.source_end
    out = []
    for i, p in enumerate(phones):
        s0, s1 = float(p["start"]), float(p["end"])
        if not (s1 > lo + EPS and s0 < hi - EPS) and not (s1 - s0 <= EPS and lo - EPS <= s0 <= hi + EPS):
            continue  # 不在这条轨覆盖的范围里（零长度的停顿在范围内照留）
        a, b = max(s0, lo), min(s1, hi)
        q = dict(p) | {"start": round(m.to_local(a), 6), "end": round(m.to_local(b), 6), "i": i}
        if p.get("eff") is not None:
            e0, e1 = max(float(p["eff"][0]), lo), min(float(p["eff"][1]), hi)
            if e1 > e0:
                q["eff"] = [round(m.to_local(e0), 6), round(m.to_local(e1), 6)]
            else:
                q.pop("eff")
        if p["label"] != "pau" and (a > s0 + EPS or b < s1 - EPS):
            q["clipped"] = True
        out.append(q)
    return out


# ---------------------------------------------------------------- SQL：采样读哪些段（列表状态、检索索引的失效键、固定结果的快照）


def _segs(s: str, a: str) -> str:
    return (
        f"t.source_id = {a}.source_id AND t.deleted = 0 AND t.start < {s}.tag_judge_end AND t.\"end\" > {s}.tag_judge_start"
        f" AND t.start > {s}.tag_judge_start - {SEGMENT_MAX + 1e-6}"
    )


def _runs(a: str, extra: str = "") -> str:
    return (
        f"FROM measure_run r WHERE r.owner_type = 'asset_text' AND r.kind = 'alignment' AND r.owner_id = 'seg:' || t.id || '@' || {base_sql(a)}{extra}"
    )


def _usable(a: str) -> str:
    return _runs(a, " AND r.status = 'ok' AND r.seg_text = t.text AND abs(r.seg_start - t.start) < 1e-6 AND abs(r.seg_end - t.\"end\") < 1e-6")


def state_sql(s: str = "s", a: str = "a") -> str:
    """语音分析状态（列表）：novoice（采样所在的轨不含人声）> stale（段改过待重新分析）> incomplete（读到的段有的还没分析）> failed > none
    > partial（◐）/ manual / ok。``a`` = 采样所在资产的别名。
    partial（◐）= 只读到某段的一部分：采样的原素材起止没有盖住读到的某一段。"""
    flags = (
        f"SELECT EXISTS (SELECT 1 {_usable(a)}) AS u,"
        f" EXISTS (SELECT 1 {_runs(a, ' AND r.status = ' + chr(39) + 'ok' + chr(39))}) AS ok,"
        f" EXISTS (SELECT 1 {_runs(a, ' AND r.status = ' + chr(39) + 'failed' + chr(39))}) AS fl,"
        f" EXISTS (SELECT 1 {_usable(a)} AND r.manual = 1) AS man,"
        f" ({s}.src_start > t.start + 1e-6 OR {s}.src_end < t.\"end\" - 1e-6) AS part"
        f" FROM text_segment t WHERE {_segs(s, a)}"
    )
    return (
        f"(CASE WHEN NOT {voiced_sql(a)} THEN 'novoice' ELSE (SELECT CASE WHEN COUNT(*) = 0 THEN 'none'"
        " WHEN SUM(u = 0 AND ok = 1) > 0 THEN 'stale'"
        " WHEN SUM(u) = COUNT(*) THEN (CASE WHEN MAX(part) = 1 THEN 'partial' WHEN MAX(man) = 1 THEN 'manual' ELSE 'ok' END)"
        " WHEN SUM(u) > 0 THEN 'incomplete'"
        " WHEN SUM(fl) > 0 THEN 'failed' ELSE 'none' END"
        f" FROM ({flags})) END)"
    )


def reads_sql(s: str = "s", a: str = "a") -> str:
    """采样读到的段与各段用的音素版本的签名（检索索引的失效键、固定结果的“分析变了”判断）：
    段的编号、区间、文本、说话人 + 可用版本（没有 = '-'）。没有读到段、或采样所在的轨不含人声 → NULL。"""
    pick = (
        f"(SELECT r.id || ':' || r.manual {_usable(a)}"
        " ORDER BY (r.id = (SELECT h.run_id FROM measure_head h WHERE h.owner_type = 'asset_text' AND h.owner_id = r.owner_id AND h.kind = 'alignment')) DESC,"
        " r.manual DESC, r.created_at DESC, r.rowid DESC LIMIT 1)"
    )
    return (
        f"(CASE WHEN {voiced_sql(a)} THEN (SELECT group_concat(x, ',') FROM (SELECT t.id || '|' || t.start || '|' || t.\"end\" || '|' || t.text || '|' || t.speakers || '|' || COALESCE("
        f"{pick}, '-') AS x FROM text_segment t WHERE {_segs(s, a)} ORDER BY t.start, t.\"end\", t.id)) END)"
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
    ``{"conflict": {a, b, start, end, units}}``（a、b 是序号，start–end 是交叠区间的读取方本轨局部秒；不自动裁决）。
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
