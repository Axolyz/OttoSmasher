"""Exact music bracket rules over associated raw subtitle events, not spoken text."""

import re
from pathlib import Path

import pysubs2

from . import source_preparation, source_regions
from .materials import sha256


def marker(text):
    text = re.sub(r"\{[^}]*\}|<[^>]*>", "", text).replace("\\N", "").replace("\\n", "").replace("\\h", "")
    return re.sub(r"\s+", "", text).replace("〜", "～")


def detect(events, duration):
    opened = None
    pairs, errors = [], []
    for event in events:
        text = marker(event.text)
        if text == "♪～":
            if opened is not None:
                errors.append("重复开始标记")
            opened = event.start / 1000
        elif text == "～♪":
            if opened is None:
                errors.append("结束标记缺少开始")
                continue
            end = event.end / 1000
            if not 0 <= opened < end <= duration:
                errors.append("标记超出原片或时间倒置")
            else:
                pairs.append({"start": opened, "end": end})
            opened = None
    if opened is not None:
        errors.append("开始标记缺少结束")
    if len(pairs) > 2:
        errors.append("超过两个音乐区间，需要人工指定用途")
    for i, p in enumerate(pairs):
        p["kind"] = (
            ("op" if i == 0 else "ed")
            if len(pairs) == 2
            else ("op" if (p["start"] + p["end"]) / 2 < duration / 2 else "ed")
        )
    return {"pairs": pairs, "errors": errors, "automatic": bool(pairs) and not errors and len(pairs) <= 2}


def run(db, source_ids, apply=True):
    sources = {s["id"]: s for s in source_preparation.listing(db)}
    results = []
    for sid in dict.fromkeys(source_ids):
        if sid not in sources:
            raise ValueError("原片不存在")
        s = sources[sid]
        path = Path(s["preparation"].get("subtitle_path") or s.get("subtitle_path") or "")
        if not path.is_file():
            results.append(
                {
                    "source_id": sid,
                    "title": s["work"] or s["title"],
                    "pairs": [],
                    "errors": ["未关联字幕；可使用参考帧或手动标记"],
                    "automatic": False,
                }
            )
            continue
        r = detect(pysubs2.load(str(path), encoding="utf-8-sig"), s["duration"])
        r.update(source_id=sid, title=s["work"] or s["title"], applied=[])
        if apply and r["automatic"]:
            for p in r["pairs"]:
                overlap = [x for x in s["regions"] if x["start"] < p["end"] and x["end"] > p["start"]]
                if overlap:
                    continue  # Never replace existing/manual markers.
                evidence = {
                    "method": "subtitle-music-brackets-v1",
                    "subtitle_sha256": sha256(path),
                    "subtitle_path": str(path),
                    "verified": False,
                }
                saved = source_regions.confirm(db, sid, **p, evidence=evidence, origin="subtitle-rule")
                r["applied"].append(saved["id"])
            source_preparation.configure(db, sid, op_review="reviewed")
        results.append(r)
    return {"sources": results}
