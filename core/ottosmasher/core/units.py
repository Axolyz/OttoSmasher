"""文本单元（所有者 2026-10-08【基线变更，细化 D41】）：语音分析只挂在“声音资产 + 文本单元”上，不属于任何采样。

- 文本单元 = 一段有文本的音轨区间，两种来源：
  - 字幕的一行：``line:<标注>@<资产>``；目标 = 字幕区间 ± 字幕采样扩展量（设置 subtitle.pad_before / pad_after），裁到资产覆盖范围，
    换算成资产局部秒（默认情况下与默认字幕采样的选区完全一样）；文本 = 这一行的对齐文本（人工 > 自动）；
  - 用户给一段选区手输的台词：``typed:<资产>@<起>-<止>``；目标 = 输入时的那段选区（采样的手输台词、详情里的「选区标注 / 对齐」）。
  当前版本、历史版本、人工修正都属于这句（measure_head / measure_run 的归属类型 ``asset_text``）。
- 采样读取覆盖它的文本单元，只有两条规则：
  - 采样有自己的文本（字幕采样、手输过台词的采样）：只读自己那一句；
  - 没有自己的文本（普通截取，包括跨两句的合并截取）：读范围内所有文本单元（音素跨度与采样范围正长度交叠），
    只有一部分落在范围内的标 ◐（partial）；两句的音素在时间上冲突 → 节奏分析不可用并说明原因（不自动处理）。
- 节奏和检索照旧按采样计算（音素裁到采样范围）。
时钟：单元的目标、音素跨度、音素时间都是资产局部秒。
"""

from __future__ import annotations

import sqlite3
from typing import Any

from ..domain.mapping import Mapping
from .edits import loads
from .errors import CoreError

OWNER = "asset_text"
LINE, TYPED = "line", "typed"
EPS = 1e-6


def line_id(annotation: str, asset: str) -> str:
    return f"line:{annotation}@{asset}"


def typed_id(asset: str, start: float, end: float) -> str:
    return f"typed:{asset}@{start:.6f}-{end:.6f}"


def kind_of(unit: str) -> str:
    return LINE if unit.startswith("line:") else TYPED


def parse_line(unit: str) -> tuple[str, str]:
    ann, asset = unit[len("line:") :].split("@", 1)
    return ann, asset


def find_typed(conn: sqlite3.Connection, asset: str, start: float, end: float) -> str | None:
    """同一资产、同一选区已有的手输单元（按区间比较，不靠编号的格式）。"""
    r = conn.execute(
        "SELECT owner_id FROM measure_run WHERE owner_type = ? AND kind = 'alignment' AND owner_id LIKE 'typed:%' AND asset_id = ?"
        " AND abs(range_start - ?) < ? AND abs(range_end - ?) < ? ORDER BY created_at DESC, rowid DESC LIMIT 1",
        (OWNER, asset, start, EPS, end, EPS),
    ).fetchone()
    return r[0] if r else None


def typed_owner(conn: sqlite3.Connection, asset: str, start: float, end: float) -> str:
    return find_typed(conn, asset, start, end) or typed_id(asset, start, end)


def analysis_track(conn: sqlite3.Connection, source_id: str) -> str | None:
    """原片的分析音轨（原片页「语音分析」、自动准备的整轨 F0）：默认人声轨；没有就是原混音（原片默认音频流的那条）。原片不可用 → None。"""
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


def line_text(ann: sqlite3.Row | dict[str, Any]) -> tuple[str, str] | None:
    """字幕行的对齐文本：人工 > 自动；没有 → None。返回（文本, 来源）。"""
    manual = (ann["align_text_manual"] or "").strip()
    if manual:
        return manual, "line-manual"
    auto = (ann["align_text_auto"] or "").strip()
    return (auto, "line-auto") if auto else None


def line_target(ann_start: float, ann_end: float, mapping: Any, duration: float, pads: tuple[float, float]) -> tuple[float, float] | None:
    """字幕行在资产上的目标（资产局部秒）：字幕区间 ± 扩展量，裁到资产覆盖的原片范围；完全在覆盖范围外 → None。"""
    m = mapping if isinstance(mapping, Mapping) else Mapping.of(loads(mapping) if isinstance(mapping, str) else mapping)
    lo, hi = m.source_start, m.source_end
    if not (ann_end > lo and ann_start < hi):
        return None
    a, b = max(ann_start - pads[0], lo, 0.0), min(ann_end + pads[1], hi)
    try:
        la, lb = max(0.0, m.to_local(a)), min(duration, m.to_local(b))
    except CoreError:
        return None
    return (la, lb) if lb > la else None


# ---------------------------------------------------------------- SQL：采样读哪些句（列表状态、检索索引的失效键、固定结果的快照）


def _own_line(s: str) -> str:
    return (
        f"CASE WHEN TRIM(COALESCE({s}.align_text_manual, '')) = '' AND json_extract({s}.origin, '$.kind') = 'subtitle'"
        f" AND json_extract({s}.origin, '$.annotation') IS NOT NULL THEN 'line:' || json_extract({s}.origin, '$.annotation') || '@' || {s}.asset_id END"
    )


def _typed_match(s: str, r: str) -> str:
    return (
        f"{r}.owner_type = 'asset_text' AND {r}.kind = 'alignment' AND {r}.owner_id LIKE 'typed:%' AND {r}.asset_id = {s}.asset_id"
        f" AND abs({r}.range_start - {s}.start) < 1e-6 AND abs({r}.range_end - {s}.\"end\") < 1e-6"
    )


def _overlap(s: str, r: str) -> str:
    return (
        f"h.owner_type = 'asset_text' AND h.kind = 'alignment' AND {r}.asset_id = {s}.asset_id AND {r}.status = 'ok'"
        f" AND {r}.span_end > {s}.start AND {r}.span_start < {s}.\"end\""
    )


def _typed(s: str) -> str:
    return f"TRIM(COALESCE({s}.align_text_manual, '')) <> ''"


def state_sql(s: str = "s") -> str:
    """语音分析状态（列表“已分析”）：manual / ok / partial（◐，没有自己文本的采样只读到某句的一部分）/ failed（只有失败记录）/ none。"""
    own = _own_line(s)
    head = "CASE WHEN r.manual = 1 THEN 'manual' ELSE 'ok' END"
    return (
        f"(CASE WHEN {_typed(s)} THEN COALESCE("
        f"(SELECT {head} FROM measure_head h JOIN measure_run r ON r.id = h.run_id WHERE h.kind = 'alignment' AND {_typed_match(s, 'r')}),"
        f"(SELECT 'failed' FROM measure_run m WHERE {_typed_match(s, 'm')} AND m.status = 'failed' LIMIT 1), 'none')"
        f" WHEN ({own}) IS NOT NULL THEN COALESCE("
        f"(SELECT {head} FROM measure_head h JOIN measure_run r ON r.id = h.run_id WHERE h.owner_type = 'asset_text' AND h.owner_id = ({own}) AND h.kind = 'alignment'),"
        f"(SELECT 'failed' FROM measure_run m WHERE m.owner_type = 'asset_text' AND m.owner_id = ({own}) AND m.kind = 'alignment' AND m.status = 'failed' LIMIT 1), 'none')"
        f" ELSE COALESCE((SELECT CASE WHEN SUM(r.span_start < {s}.start - 1e-6 OR r.span_end > {s}.\"end\" + 1e-6) > 0 THEN 'partial' ELSE 'ok' END"
        f" FROM measure_head h JOIN measure_run r ON r.id = h.run_id WHERE {_overlap(s, 'r')} HAVING COUNT(*) > 0), 'none') END)"
    )


def reads_sql(s: str = "s") -> str:
    """采样读到的句与版本的签名（检索索引的失效键、固定结果的“分析变了”判断）；没有可读的 → NULL。"""
    own = _own_line(s)
    one = "h.owner_id || ':' || h.run_id || ':' || h.version"
    return (
        f"(CASE WHEN {_typed(s)} THEN (SELECT {one} FROM measure_head h JOIN measure_run r ON r.id = h.run_id WHERE h.kind = 'alignment' AND {_typed_match(s, 'r')})"
        f" WHEN ({own}) IS NOT NULL THEN (SELECT {one} FROM measure_head h WHERE h.owner_type = 'asset_text' AND h.owner_id = ({own}) AND h.kind = 'alignment')"
        f" ELSE (SELECT group_concat(x, ',') FROM (SELECT {one} || ':' || COALESCE(json_extract(r.inputs, '$.audio.snapshot'), '') AS x"
        f" FROM measure_head h JOIN measure_run r ON r.id = h.run_id WHERE {_overlap(s, 'r')} ORDER BY h.owner_id)) END)"
    )


# ---------------------------------------------------------------- 合并：采样读到的几句 → 一个头（裁到采样范围）


def _span(phones: list[dict[str, Any]]) -> tuple[float, float] | None:
    sp = [p for p in phones if p["label"] != "pau"]
    return (float(sp[0]["start"]), float(sp[-1]["end"])) if sp else None


def span_of(result: dict[str, Any] | None) -> tuple[float, float] | None:
    """一次成功结果的音素跨度（首个到末个非停顿音素）。"""
    return _span(result["phones"]) if result and result.get("phones") else None


def clip(phones: list[dict[str, Any]], start: float, end: float) -> list[dict[str, Any]]:
    return [p | {"start": max(float(p["start"]), start), "end": min(float(p["end"]), end)} for p in phones if p["end"] > start and p["start"] < end]


def merge(units: list[dict[str, Any]], start: float, end: float) -> dict[str, Any]:
    """几句（各自的当前头：``result`` 里有 phones / morae / words）合成一个头，音素裁到 [start, end)。

    按首个非停顿音素排序；相邻两句的非停顿音素正长度交叠 → ``{"conflict": {...}}``（不自动处理）。
    每句去掉首尾停顿，句间空隙补一个停顿；第一句前、最后一句后的停顿保留（裁到范围）。mora、词的序号按句依次平移。
    """
    parts = []
    for u in units:
        phones = list(u["result"]["phones"])
        sp = _span(phones)
        if sp is None:
            continue
        parts.append((sp, u, phones))
    parts.sort(key=lambda x: (x[0][0], x[0][1]))
    speech = [clip([p for p in ph if p["label"] != "pau"], start, end) for _, _, ph in parts]
    for i in range(len(parts)):
        for j in range(i + 1, len(parts)):
            clash = next(((x, y) for x in speech[i] for y in speech[j] if min(x["end"], y["end"]) - max(x["start"], y["start"]) > EPS), None)
            if clash is not None:
                ua, ub = parts[i][1], parts[j][1]
                at = max(clash[0]["start"], clash[1]["start"])
                return {"conflict": {"a": ua["name"], "b": ub["name"], "at": round(float(at), 6), "units": [ua["unitId"], ub["unitId"]]}}
    phones: list[dict[str, Any]] = []
    morae: list[str] = []
    words: list[Any] = []
    for i, (sp, u, ph) in enumerate(parts):
        res = u["result"]
        mo, wo = len(morae), len(words)
        lo = 0 if i == 0 else next(k for k, p in enumerate(ph) if p["label"] != "pau")
        hi = len(ph) if i == len(parts) - 1 else max(k for k, p in enumerate(ph) if p["label"] != "pau") + 1
        if i > 0 and phones and sp[0] > phones[-1]["end"] + EPS:
            phones.append({"label": "pau", "start": phones[-1]["end"], "end": sp[0], "mora": None, "word": None})
        for p in ph[lo:hi]:
            q = dict(p)
            if q.get("mora") is not None:
                q["mora"] = int(q["mora"]) + mo
            if q.get("word") is not None:
                q["word"] = int(q["word"]) + wo
            phones.append(q)
        morae += list(res.get("morae") or [])
        words += [w | {"moraStart": int(w["moraStart"]) + mo} if w.get("moraStart") is not None else w for w in res.get("words") or []]
    out_phones = clip(phones, start, end)
    if len(parts) == 1:  # 只读到一句：其余字段（前端、对齐器信息）照搬
        return parts[0][1]["result"] | {"phones": out_phones, "morae": morae, "words": words}
    return {"phones": out_phones, "morae": morae, "words": words, "frontend": {}}


def partial(span: tuple[float, float] | None, start: float, end: float) -> bool:
    return span is not None and (span[0] < start - EPS or span[1] > end + EPS)
