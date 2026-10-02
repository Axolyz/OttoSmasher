"""Scoped interval labels; no inference and no dependence on saved cue samples."""

import bisect
import itertools
import json
from collections import OrderedDict

from .asset_timeline import canonical, map_time
from .workspace import identity


def subtitle_tags(payload):
    prefix = "character:" if payload.get("status") == "single" else "participants:"
    tags = [prefix + name for name in payload.get("names", [])]
    if payload.get("status") == "multiple_or_group":
        tags.append("speaker-status:多人未分段")
    return tags


def sync_cue(db, cue_id):
    """Insert only: reimporting subtitles must not overwrite an edited annotation."""
    row = db.execute("SELECT * FROM cues WHERE id=?", (cue_id,)).fetchone()
    if not row or row["start"] < 0 or row["end"] <= row["start"]:
        return
    from .subtitle_speakers import extract

    from .subtitle_import import classify, ensure

    ensure(db)
    if db.execute("SELECT 1 FROM timeline_annotations WHERE id=?", (cue_id,)).fetchone():
        return
    from .ui_catalog import settings

    parsed = classify(row["original"], settings(db))
    scope = {"type": "group", "ids": ["dialogue" if parsed["kind"] == "dialogue" else "effects"]}
    db.execute("INSERT OR IGNORE INTO subtitle_classifications VALUES(?,?)", (cue_id, canonical(parsed)))
    speakers = parsed["speakers"]
    tags = [("character:" if len(speakers) == 1 else "participants:") + n for n in speakers]
    db.execute(
        "INSERT OR IGNORE INTO timeline_annotations VALUES(?,?,?,?,?,?,?,?,1,0)",
        (
            row["id"],
            row["source_id"],
            row["start"],
            row["end"],
            parsed["kind"],
            row["original"],
            canonical(tags),
            canonical(scope),
        ),
    )


def migrate_labels(db):
    # Flatten the old "latest manual speaker wins" overlays into ordinary,
    # non-overlapping annotations. The new reader has no special speaker rules.
    sources = [r[0] for r in db.execute("SELECT DISTINCT source_id FROM speaker_annotations")]
    for sid in sources:
        rows = db.execute(
            "SELECT * FROM speaker_annotations WHERE source_id=? ORDER BY created DESC,id", (sid,)
        ).fetchall()
        cuts = sorted({r[k] for r in rows for k in ("start", "end")})
        for lo, hi in itertools.pairwise(cuts):
            chosen = next((r for r in rows if r["start"] < hi and r["end"] > lo), None)
            if chosen:
                db.execute(
                    "INSERT OR IGNORE INTO timeline_annotations VALUES(?,?,?,?,?,?,?,?,1,0)",
                    (
                        identity("legacy-speaker-span", sid, lo, hi, chosen["id"]),
                        sid,
                        lo,
                        hi,
                        "tag",
                        "",
                        canonical(["character:" + chosen["speaker"]]),
                        canonical({"type": "group", "ids": ["dialogue"]}),
                    ),
                )
    from .subtitle_speakers import extract

    for cue in db.execute("SELECT * FROM cues"):
        manual = db.execute(
            "SELECT 1 FROM speaker_annotations WHERE source_id=? AND start<? AND end>?",
            (cue["source_id"], cue["end"], cue["start"]),
        ).fetchone()
        tags = [] if manual or cue["kind"] != "dialogue" else subtitle_tags(extract(cue["original"]))
        db.execute(
            "UPDATE timeline_annotations SET tags=? WHERE id=? AND revision=1 AND tags='[]'",
            (canonical(tags), cue["id"]),
        )


class Intervals:
    def __init__(self, rows):
        self.rows = sorted(rows, key=lambda r: r["start"])
        self.starts = [r["start"] for r in self.rows]
        self.maximum_ends = list(itertools.accumulate((r["end"] for r in self.rows), max))

    def overlap(self, start, end):
        left = bisect.bisect_right(self.maximum_ends, start)
        right = bisect.bisect_left(self.starts, end)
        return (r for r in self.rows[left:right] if r["end"] > start)


def effective(db, sample_ids, only_tags=None):
    """Bounded catalog pass; interval indices avoid scanning every subtitle per sample."""
    wanted = set(sample_ids)
    if not wanted:
        return {}
    sql = "SELECT s.sample_id,s.asset_id,s.start,s.end,a.source_id,a.mapping FROM asset_samples s JOIN sound_assets a ON a.id=s.asset_id"
    candidates = list(
        db.execute(
            sql
            + (" WHERE s.sample_id IN (" + ",".join("?" for _ in wanted) + ")" if len(wanted) <= 800 else ""),
            list(wanted) if len(wanted) <= 800 else [],
        )
    )
    sources = {row["source_id"] for row in candidates}
    groups = {}
    for row in db.execute("SELECT * FROM asset_groups"):
        groups.setdefault(row["asset_id"], set()).add(row["group_name"])
    rows_by_scope = {}
    for row in db.execute("SELECT * FROM timeline_annotations WHERE deleted=0 AND tags<>'[]'"):
        if row["source_id"] not in sources:
            continue
        item = dict(row)
        item["tags"] = json.loads(item["tags"])
        if only_tags is not None:
            item["tags"] = [tag for tag in item["tags"] if tag in only_tags]
        if not item["tags"]:
            continue
        scope = json.loads(item["scope"])
        for key in [item["source_id"]] if scope["type"] == "source" else scope["ids"]:
            rows_by_scope.setdefault((scope["type"], key, item["source_id"]), []).append(item)
    indices = {k: Intervals(v) for k, v in rows_by_scope.items()}
    if not indices:
        return {}
    result = {}
    mappings = {}
    range_cache = OrderedDict()
    for row in candidates:
        mid = row["sample_id"]
        if mid not in wanted:
            continue
        cache_key = (row["asset_id"], row["start"], row["end"])
        if cache_key in range_cache:
            result[mid] = range_cache[cache_key]
            range_cache.move_to_end(cache_key)
            continue
        keys = [("asset", row["asset_id"], row["start"], row["end"])]
        if row["mapping"]:
            if row["asset_id"] not in mappings:
                mappings[row["asset_id"]] = json.loads(row["mapping"])
            knots = mappings[row["asset_id"]]
            # Old mappings sometimes end a fraction of a frame early. Only
            # their recorded coverage contributes source labels; no extrapolation.
            lo, hi = max(row["start"], knots[0][0]), min(row["end"], knots[-1][0])
            if hi > lo:
                if len(knots) == 2:
                    (x0, y0), (x1, y1) = knots
                    scale = (y1 - y0) / (x1 - x0)
                    lo, hi = y0 + (lo - x0) * scale, y0 + (hi - x0) * scale
                else:
                    lo, hi = map_time(knots, lo), map_time(knots, hi)
                keys.append(("source", row["source_id"], lo, hi))
                keys.extend(("group", g, lo, hi) for g in groups.get(row["asset_id"], ()))
        found = {}
        for kind, key, lo, hi in keys:
            index = indices.get((kind, key, row["source_id"]))
            if index:
                for item in index.overlap(lo, hi):
                    for tag in item["tags"]:
                        found.setdefault(
                            tag,
                            {
                                "tag": tag,
                                "origin": "timeline",
                                "inherited": True,
                                "annotation_id": item["id"],
                            },
                        )
        result[mid] = list(found.values())
        range_cache[cache_key] = result[mid]
        if len(range_cache) > 4096:
            range_cache.popitem(last=False)
    return result


def text_context(db, source_id, start, end):
    """Source-wide subtitle layer, including asset-local annotations after mapping."""
    result = []
    for row in db.execute(
        "SELECT * FROM timeline_annotations WHERE source_id=? AND deleted=0 AND kind IN ('dialogue','event','song')",
        (source_id,),
    ):
        hidden = db.execute(
            "SELECT 1 FROM cue_subtitle_versions c JOIN subtitle_versions v ON v.id=c.version_id WHERE c.cue_id=? AND v.selected=0",
            (row["id"],),
        ).fetchone()
        if hidden:
            continue
        lo, hi = row["start"], row["end"]
        scope = json.loads(row["scope"])
        if scope["type"] == "asset":
            asset = db.execute("SELECT mapping FROM sound_assets WHERE id=?", (scope["ids"][0],)).fetchone()
            if not asset or not asset[0]:
                continue
            try:
                lo, hi = map_time(json.loads(asset[0]), lo), map_time(json.loads(asset[0]), hi)
            except ValueError:
                continue
        if lo < end and hi > start:
            result.append({"id": row["id"], "start": lo, "end": hi, "original": row["text"], "scope": scope})
    return sorted(result, key=lambda r: (r["start"], r["end"], r["id"]))
