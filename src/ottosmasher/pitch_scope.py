"""Read-only source/annotation filtering in the physical file's F0 clock."""

import json
import math
from collections import defaultdict

from .asset_timeline import AssetSelection, annotations_for, map_time
from .pitch_search import HOP, valid_starts
from .tag_expression import from_tags, parse


def tag_ranges(db, row, duration, scope):
    descriptor = json.loads(row["descriptor"])
    lo, hi = descriptor["start"], descriptor["end"]
    scopes = [scope, *scope.get("intersections", [])]
    expressions = [
        parse(expression)
        for part in scopes
        for expression in (part.get("tag_expression", ""), from_tags(part.get("tags", [])), from_tags([part["single_tag"]] if part.get("single_tag") else []))
    ]
    if not any(part.get("tags") or part.get("tag_expression") or part.get("single_tag") for part in scopes):
        return [(lo, hi)]
    source = db.execute(
        "SELECT work,media_type FROM source_labels WHERE source_id=?", (row["source_id"],)
    ).fetchone()
    counts = defaultdict(int)
    if source:
        for key, prefix in [("work", "work:"), ("media_type", "type:")]:
            if source[key]:
                counts[prefix + source[key]] += 1
    events = defaultdict(list)
    knots = descriptor.get("root_knots")
    for annotation in annotations_for(db, AssetSelection(row["id"], 0, row["duration"])):
        if not annotation["tags"]:
            continue
        if annotation["scope"]["type"] == "asset":
            a, b = annotation["start"], annotation["end"]
        elif knots:
            a = map_time(knots, max(knots[0][1], annotation["start"]), inverse=True)
            b = map_time(knots, min(knots[-1][1], annotation["end"]), inverse=True)
        else:
            continue
        a += lo
        b += lo
        # Strict positive overlap for a complete query [t,t+duration).
        begin = math.floor((a - duration) / HOP + 1e-8) + 1
        end = math.ceil(b / HOP - 1e-8)
        for tag in annotation["tags"]:
            events[begin].append((tag, 1))
            events[end].append((tag, -1))
    start = math.ceil(lo / HOP - 1e-8)
    stop = math.floor((hi - duration) / HOP + 1e-8) + 1
    if stop <= start:
        return []
    for at, changes in events.items():
        if at < start:
            for tag, delta in changes:
                counts[tag] += delta
    result = []
    cursor = start
    events.setdefault(start, [])
    events.setdefault(stop, [])
    for at in sorted(t for t in events if start <= t <= stop):
        tags = {tag for tag, n in counts.items() if n > 0}
        if at > cursor and all(e.matches(tags) for e in expressions):
            result.append((cursor * HOP, (at - 1) * HOP + duration))
        for tag, delta in events[at]:
            counts[tag] += delta
        cursor = at
    return result


def validate_boundaries(condition):
    if condition is None:
        return
    if not isinstance(condition, dict) or set(condition) - {"start_tolerance", "end_tolerance"}:
        raise ValueError("句首尾条件只接受 start_tolerance/end_tolerance")
    for value in condition.values():
        if (
            isinstance(value, bool)
            or not isinstance(value, (int, float))
            or not math.isfinite(value)
            or not 0 <= value <= 5
        ):
            raise ValueError("句首尾容差为 0–5 秒")


def restrict_boundaries(ranges, annotations, descriptor, duration, condition):
    """Return legal-start ranges, requiring an independently known text boundary."""
    validate_boundaries(condition)
    if not condition:
        return ranges, False
    knots = descriptor.get("root_knots")
    if not knots or not annotations:
        return [], True
    allowed = valid_starts(ranges, round(duration / HOP)).tolist()
    for field, coordinate, shift in [("start_tolerance", "start", 0), ("end_tolerance", "end", duration)]:
        if field not in condition:
            continue
        tolerance = condition[field]
        near = []
        for a in annotations:
            value = a[coordinate]
            if a.get("scope", {}).get("type") == "asset":
                local = value
            elif knots[0][1] <= value <= knots[-1][1]:
                local = map_time(knots, value, inverse=True)
            else:
                continue
            t = descriptor["start"] + local - shift
            near.append((math.ceil((t - tolerance) / HOP - 1e-8), math.floor((t + tolerance) / HOP + 1e-8)))
        allowed = [(max(a, c), min(b, d)) for a, b in allowed for c, d in near if max(a, c) <= min(b, d)]
    return [(a * HOP, b * HOP + duration) for a, b in allowed], False


def source_assets(db, body):
    """Common source selection for offline preparation and read-only queries."""
    scope = body.get("scope") or {}
    scopes = [scope, *scope.get("intersections", [])]
    if any(
        part.get(k) for part in scopes for k in ("nature", "natures", "starred", "material_ids", "conditions")
    ):
        raise ValueError("原片音轨模式不接受采样性质/收藏/选中采样范围")
    for key in ("asset_ids", "roles"):
        if key in body and (
            not isinstance(body[key], list) or not all(isinstance(v, str) for v in body[key])
        ):
            raise ValueError(f"{key} 应为字符串列表")
    wanted = set(body.get("asset_ids") or [])
    roles = set(body.get("roles") or [])
    source_ids = {part["source_id"] for part in scopes if part.get("source_id")}
    for row in db.execute("SELECT a.*,s.title FROM sound_assets a JOIN sources s ON s.id=a.source_id"):
        if wanted and row["id"] not in wanted or any(row["source_id"] != sid for sid in source_ids):
            continue
        descriptor = json.loads(row["descriptor"])
        if roles and descriptor.get("role", "raw") not in roles:
            continue
        if any(
            part.get("text") and part["text"].casefold() not in row["title"].casefold() for part in scopes
        ):
            continue
        work = db.execute("SELECT work FROM source_labels WHERE source_id=?", (row["source_id"],)).fetchone()
        if any(part.get("work") and (not work or work[0] != part["work"]) for part in scopes):
            continue
        yield row


def source_subjects(db, body, duration):
    scope = body.get("scope") or {}
    subjects = defaultdict(list)
    unknown = 0
    eligible = 0
    indexed = 0
    associated = defaultdict(list)
    indexed_tracks = dict(db.execute("SELECT asset_id,track_id FROM pitch_asset_ranges"))
    for row in source_assets(db, body):
        descriptor = json.loads(row["descriptor"])
        eligible += 1
        track_id = indexed_tracks.get(row["id"])
        if not track_id:
            continue
        indexed += 1
        ranges = tag_ranges(db, row, duration, scope)
        annotations = (
            annotations_for(db, AssetSelection(row["id"], 0, row["duration"]), kinds={"dialogue", "song"})
            if body.get("boundaries")
            else []
        )
        ranges, missing = restrict_boundaries(
            ranges, annotations, descriptor, duration, body.get("boundaries")
        )
        unknown += int(missing)
        subjects[track_id].extend(ranges)
        associated[track_id].append(
            {
                "asset_id": row["id"],
                "source_id": row["source_id"],
                "start": descriptor["start"],
                "end": descriptor["end"],
                "allowed_ranges": ranges,
            }
        )
    return (
        subjects,
        associated,
        {"eligible_assets": eligible, "indexed_assets": indexed, "boundary_unknown_assets": unknown},
    )
