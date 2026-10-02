"""Bounded approximate F0 retrieval; this module never loads an inference model."""

from __future__ import annotations

import json
import math
import time
from pathlib import Path

import numpy as np

from .pitch_values import midi
from .workspace import identity

VERSION = "pitch-grid-v1"
HOP = 0.01
COARSE = 5
CONFIDENCE = 0.5


def ensure(db):
    for sql in [
        "CREATE TABLE IF NOT EXISTS pitch_tracks(id TEXT PRIMARY KEY,signature TEXT NOT NULL,path TEXT NOT NULL,frames INTEGER NOT NULL,descriptor TEXT NOT NULL,created REAL NOT NULL)",
        "CREATE TABLE IF NOT EXISTS pitch_sample_ranges(sample_id TEXT PRIMARY KEY,track_id TEXT NOT NULL,start REAL NOT NULL,end REAL NOT NULL,asset_signature TEXT NOT NULL,source_id TEXT NOT NULL,role TEXT NOT NULL)",
        "CREATE TABLE IF NOT EXISTS pitch_asset_ranges(asset_id TEXT PRIMARY KEY,track_id TEXT NOT NULL,start REAL NOT NULL,end REAL NOT NULL,source_id TEXT NOT NULL,role TEXT NOT NULL)",
        "CREATE INDEX IF NOT EXISTS pitch_track_ranges ON pitch_sample_ranges(track_id,start,end)",
    ]:
        db.execute(sql)
    # These are cache invalidations, not a second business authority.
    binding_type = db.execute("SELECT type FROM sqlite_master WHERE name='sample_assets'").fetchone()[0]
    table, field = (
        ("asset_samples", "sample_id") if binding_type == "view" else ("sample_assets", "material_id")
    )
    for verb in ("INSERT", "UPDATE", "DELETE"):
        ref = "OLD" if verb == "DELETE" else "NEW"
        db.execute(
            f"CREATE TRIGGER IF NOT EXISTS invalidate_pitch_binding_{table}_{verb.lower()} AFTER {verb} ON {table} BEGIN DELETE FROM pitch_sample_ranges WHERE sample_id={ref}.{field}; END"
        )
    db.execute(
        "CREATE TRIGGER IF NOT EXISTS invalidate_pitch_deleted AFTER DELETE ON materials BEGIN DELETE FROM pitch_sample_ranges WHERE sample_id=OLD.id; END"
    )


def parse(text):
    rows = []
    for number, line in enumerate(text.splitlines(), 1):
        if not line.strip():
            continue
        try:
            duration, pitch = line.split()
            duration = float(duration)
            if not math.isfinite(duration) or duration < 0.1:
                raise ValueError("每行至少 100 ms")
            frames = math.floor(duration / HOP + 0.5)
            parts = pitch.split("..")
            if not 1 <= len(parts) <= 2:
                raise ValueError("音高范围格式为 C5..D5")
            lo, hi = midi(parts[0]), midi(parts[-1])
            if lo > hi:
                raise ValueError("音高范围上下限颠倒")
            rows.append({"frames": frames, "duration": frames * HOP, "low": lo, "high": hi})
        except (ValueError, TypeError) as e:
            raise ValueError(f"第 {number} 行：{e}") from e
    if not 1 <= len(rows) <= 16 or sum(r["frames"] for r in rows) > 1000:
        raise ValueError("需要 1–16 行，总长不超过 10 秒")
    return rows


def options(values=None):
    values = values or {}
    allowed = {"tolerance_cents", "coverage", "max_gap", "stability_cents", "energy_min", "energy_max"}
    if set(values) - allowed:
        raise ValueError("未知音高查询参数：" + ",".join(sorted(set(values) - allowed)))
    out = {
        "tolerance_cents": 50.0,
        "coverage": 0.8,
        "max_gap": 0.12,
        "stability_cents": None,
        "energy_min": None,
        "energy_max": None,
        **values,
    }
    limits = {
        "tolerance_cents": (0, 1200),
        "coverage": (0, 1),
        "max_gap": (0, 10),
        "stability_cents": (0, 12000),
        "energy_min": (0, 1e6),
        "energy_max": (0, 1e6),
    }
    for key, (lo, hi) in limits.items():
        value = out[key]
        if value is None and key in {"stability_cents", "energy_min", "energy_max"}:
            continue
        if (
            isinstance(value, bool)
            or not isinstance(value, (int, float))
            or not math.isfinite(value)
            or not lo <= value <= hi
        ):
            raise ValueError("无效音高查询参数：" + key)
    if (
        out["energy_min"] is not None
        and out["energy_max"] is not None
        and out["energy_min"] > out["energy_max"]
    ):
        raise ValueError("能量上下限颠倒")
    return out


def write_index(folder, f0, confidence, energy):
    """Write a reusable binary track, independent of any sample or FA identity."""
    folder = Path(folder)
    folder.mkdir(parents=True, exist_ok=True)
    native = np.column_stack((f0, confidence, energy)).astype("float32")
    if (
        len(native) == 0
        or not np.isfinite(native).all()
        or np.any(native[:, 0] < 0)
        or np.any(native[:, 1] < 0)
        or np.any(native[:, 2] < 0)
    ):
        raise ValueError("F0 索引包含无效帧")
    np.save(folder / "native.npy", native, allow_pickle=False)
    count = math.ceil(len(native) / COARSE)
    padded = np.zeros((count * COARSE, 3), dtype="float32")
    padded[: len(native)] = native
    cells = padded.reshape(count, COARSE, 3)
    valid = (cells[:, :, 1] >= CONFIDENCE) & (cells[:, :, 0] > 0)
    pitches = 69 + 12 * np.log2(np.maximum(cells[:, :, 0], 1e-20) / 440)
    weights = valid.sum(axis=1)
    mean = (np.where(valid, pitches, 0).sum(axis=1) / np.maximum(weights, 1)).astype("float32")
    summary = np.column_stack((mean, weights / COARSE, cells[:, :, 2].mean(axis=1))).astype("float32")
    np.save(folder / "summary.npy", summary, allow_pickle=False)
    return len(native)


def valid_starts(ranges, frames):
    # Union allowable START ranges, never union adjacent sample waveforms.
    intervals = sorted(
        (max(0, math.ceil(lo / HOP - 1e-8)), math.floor(hi / HOP + 1e-8) - frames) for lo, hi in ranges
    )
    merged = []
    for lo, hi in intervals:
        if hi < lo:
            continue
        if merged and lo <= merged[-1][1] + 1:
            merged[-1][1] = max(hi, merged[-1][1])
        else:
            merged.append([lo, hi])
    return np.asarray(merged, dtype="int64").reshape(-1, 2)


def allowed_mask(starts, ranges):
    if not len(ranges):
        return np.zeros(len(starts), dtype=bool)
    at = np.searchsorted(ranges[:, 0], starts, side="right") - 1
    return (at >= 0) & (starts <= ranges[np.maximum(at, 0), 1])


def coarse(summary, native_count, rows, opts, allowed):
    total = sum(r["frames"] for r in rows)
    starts = np.arange(max(0, (native_count - total) // COARSE + 1), dtype="int64")
    valid = allowed_mask(starts * COARSE, allowed)
    scores = np.zeros(len(starts), dtype="float32")
    offset = 0
    for row in rows:
        lo = math.floor(offset / COARSE)
        hi = math.ceil((offset + row["frames"]) / COARSE)
        n = max(1, hi - lo)
        band = (summary[:, 0] >= row["low"] - opts["tolerance_cents"] / 100 - 1) & (
            summary[:, 0] <= row["high"] + opts["tolerance_cents"] / 100 + 1
        )
        prefix = np.concatenate(([0.0], np.cumsum(summary[:, 1] * band, dtype="float64")))
        right = np.minimum(starts + hi, len(summary))
        left = np.minimum(starts + lo, len(summary))
        coverage = (prefix[right] - prefix[left]) / n
        valid &= coverage >= max(0, opts["coverage"] - 0.15)
        scores += 1 - coverage
        offset += row["frames"]
    indices = np.flatnonzero(valid)
    return starts[indices] * COARSE, scores[indices]


def longest_gap(good):
    bad = ~good
    positions = np.flatnonzero(np.diff(np.r_[False, bad, False].astype("int8")))
    return int(np.max(positions[1::2] - positions[::2], initial=0))


def refine(native, start, rows, opts):
    entire = native[start : start + sum(r["frames"] for r in rows)]
    reliable = (entire[:, 1] >= CONFIDENCE) & (entire[:, 0] > 0) & np.isfinite(entire).all(axis=1)
    if longest_gap(reliable) * HOP > opts["max_gap"] + 1e-9:
        return None
    offset = start
    errors = []
    coverage = []
    for row in rows:
        frames = native[offset : offset + row["frames"]]
        offset += row["frames"]
        if len(frames) != row["frames"]:
            return None
        reliable = (frames[:, 1] >= CONFIDENCE) & (frames[:, 0] > 0) & np.isfinite(frames).all(axis=1)
        pitches = 69 + 12 * np.log2(np.maximum(frames[:, 0], 1e-20) / 440)
        distance = np.maximum(np.maximum(row["low"] - pitches, pitches - row["high"]), 0) * 100
        good = reliable & (distance <= opts["tolerance_cents"] + 1e-4)
        ratio = float(good.mean())
        if ratio + 1e-9 < opts["coverage"] or longest_gap(reliable) * HOP > opts["max_gap"] + 1e-9:
            return None
        if not np.any(reliable):
            return None
        if (
            opts["stability_cents"] is not None
            and np.ptp(np.percentile(pitches[reliable], [10, 90])) * 100 > opts["stability_cents"]
        ):
            return None
        energy = float(frames[:, 2].mean())
        if opts["energy_min"] is not None and energy < opts["energy_min"]:
            return None
        if opts["energy_max"] is not None and energy > opts["energy_max"]:
            return None
        errors.append(float(distance[reliable].mean()))
        coverage.append(ratio)
    return {"score": float(np.mean(errors)), "coverage": coverage}


def gap_rows(reliable):
    positions = np.arange(reliable.shape[1])
    last = np.maximum.accumulate(np.where(reliable, positions, -1), axis=1)
    return np.max(positions - last, axis=1)


def refine_many(native, starts, rows, opts):
    """Bounded batches, with exactly the same predicates as scalar refine."""
    total = sum(r["frames"] for r in rows)
    found = []
    for base in range(0, len(starts), 256):
        batch = np.asarray(starts[base : base + 256], dtype="int64")
        frames = native[batch[:, None] + np.arange(total)]
        reliable = (frames[:, :, 1] >= CONFIDENCE) & (frames[:, :, 0] > 0) & np.isfinite(frames).all(axis=2)
        keep = gap_rows(reliable) * HOP <= opts["max_gap"] + 1e-9
        pitches = 69 + 12 * np.log2(np.maximum(frames[:, :, 0], 1e-20) / 440)
        scores = []
        coverages = []
        offset = 0
        for row in rows:
            end = offset + row["frames"]
            valid = reliable[:, offset:end]
            pitch = pitches[:, offset:end]
            distance = np.maximum(np.maximum(row["low"] - pitch, pitch - row["high"]), 0) * 100
            good = valid & (distance <= opts["tolerance_cents"] + 1e-4)
            coverage = good.mean(axis=1)
            counts = valid.sum(axis=1)
            keep &= (coverage + 1e-9 >= opts["coverage"]) & (counts > 0)
            if opts["stability_cents"] is not None:
                # Ignore missing F0, including rows already rejected as unvoiced.
                present = np.flatnonzero(counts)
                stable = np.zeros(len(batch), dtype=bool)
                bounds = np.nanpercentile(np.where(valid[present], pitch[present], np.nan), [10, 90], axis=1)
                stable[present] = (bounds[1] - bounds[0]) * 100 <= opts["stability_cents"]
                keep &= stable
            energy = frames[:, offset:end, 2].mean(axis=1)
            if opts["energy_min"] is not None:
                keep &= energy >= opts["energy_min"]
            if opts["energy_max"] is not None:
                keep &= energy <= opts["energy_max"]
            scores.append(np.where(valid, distance, 0).sum(axis=1) / np.maximum(counts, 1))
            coverages.append(coverage)
            offset = end
        score = np.mean(scores, axis=0)
        for i in np.flatnonzero(keep):
            found.append(
                (int(batch[i]), {"score": float(score[i]), "coverage": [float(c[i]) for c in coverages]})
            )
    return found


def search_tracks(tracks, text, parameters=None, *, candidate_limit=2000, result_limit=100):
    """tracks contain index folders and already filtered single-sample ranges."""
    began = time.perf_counter()
    rows = parse(text)
    opts = options(parameters)
    duration = sum(r["frames"] for r in rows)
    groups = []
    seen_candidates = 0
    coverage_frames = 0
    for track in tracks:
        summary = np.load(Path(track["path"]) / "summary.npy", mmap_mode="r", allow_pickle=False)
        allowed = valid_starts(track["ranges"], duration)
        positions, scores = coarse(summary, track["frames"], rows, opts, allowed)
        seen_candidates += len(positions)
        coverage_frames += track["frames"]
        # One coarse basin is one event candidate, not hundreds of 10ms hits.
        for indexes in np.split(np.arange(len(positions)), np.flatnonzero(np.diff(positions) > COARSE) + 1):
            if not len(indexes): continue
            ranked = indexes[np.lexsort((positions[indexes], scores[indexes]))[:candidate_limit]]
            groups.append((float(scores[ranked[0]]), track, positions[ranked], allowed))
    groups.sort(key=lambda x:(x[0], x[1]["id"], int(x[2][0])))
    group_count = len(groups)
    groups = groups[:candidate_limit]
    candidates = []
    depth = 0
    # Round robin: every distinct basin gets an opportunity before retries.
    while len(candidates) < candidate_limit:
        added = False
        for group_id, (_,track,positions,allowed) in enumerate(groups):
            if depth < len(positions):
                candidates.append((group_id,track,int(positions[depth]),allowed));added=True
                if len(candidates) == candidate_limit: break
        if not added: break
        depth += 1
    pending, subjects, membership = {}, {}, {}
    for gid, track, pos, allowed in candidates:
        tid=track["id"];subjects[tid]=track
        starts=np.arange(max(0,pos-5),min(track["frames"]-duration,pos+5)+1,dtype="int64")
        starts=starts[allowed_mask(starts,allowed)]
        pending.setdefault(tid,set()).update(starts.tolist())
        for start in starts:membership.setdefault((tid,int(start)),set()).add(gid)
    best = {}
    for tid, starts in pending.items():
        native=np.load(Path(subjects[tid]["path"])/"native.npy",mmap_mode="r",allow_pickle=False)
        for start,match in refine_many(native,sorted(starts),rows,opts):
            hit={"asset_id":tid,"start":start*HOP,"end":(start+duration)*HOP,**match}
            for gid in membership[(tid,start)]:
                previous=best.get(gid)
                if previous is None or (hit['score'],hit['start']) < (previous['score'],previous['start']):best[gid]=hit
    unique={(h['asset_id'],h['start']):h for h in best.values()}
    results=sorted(unique.values(),key=lambda h:(h['score'],h['asset_id'],h['start']))
    if result_limit is not None: results=results[:result_limit]
    return {
        "results": results,
        "query": rows,
        "parameters": opts,
        "approximate": True,
        "coarse_grid_seconds": 0.05,
        "refine_grid_seconds": 0.01,
        "candidate_limit": candidate_limit,
        "candidates_seen": seen_candidates,
        "candidate_groups": group_count,
        "candidates_refined": len(candidates),
        "truncated": seen_candidates > candidate_limit,
        "indexed_seconds": coverage_frames * HOP,
        "elapsed_seconds": time.perf_counter() - began,
    }


def query(db, body, *, coverage_only=False):
    began = time.perf_counter()
    from .pitch_scope import validate_boundaries
    from .sample_scope import ids

    ensure(db)
    if set(body) - {"text", "mode", "scope", "roles", "boundaries", "parameters", "asset_ids"}:
        raise ValueError("未知音高查询字段")
    validate_boundaries(body.get("boundaries"))
    for key in ("roles", "asset_ids"):
        if key in body and (
            not isinstance(body[key], list) or any(not isinstance(x, str) for x in body[key])
        ):
            raise ValueError(f"{key} 应为文本列表")
    mode = body.get("mode", "samples")
    if mode not in {"samples", "sources"}:
        raise ValueError("音高检索模式应为 samples/sources")
    duration = sum(r["duration"] for r in parse(body["text"]))
    tracks = {}
    associations = {}
    indexed = set()
    source_associations = {}
    coverage = {}
    unknown = 0
    eligible = set(ids(db, body.get("scope"))) if mode == "samples" else set()
    if mode == "sources":
        from .pitch_scope import source_subjects

        tracks, source_associations, coverage = source_subjects(db, body, duration)
    else:
        for row in db.execute("SELECT * FROM pitch_sample_ranges"):
            if row["sample_id"] not in eligible:
                continue
            if body.get("roles") and row["role"] not in body["roles"]:
                continue
            indexed.add(row["sample_id"])
            ranges = [(row["start"], row["end"])]
            if body.get("boundaries"):
                from .asset_timeline import annotations_for, sample_selection
                from .pitch_scope import restrict_boundaries
                from .sample_audio import resolve

                descriptor = resolve(db, row["sample_id"])
                try:
                    annotations = annotations_for(
                        db, sample_selection(db, row["sample_id"]), kinds={"dialogue", "song"}
                    )
                except ValueError:
                    annotations = [
                        dict(c)
                        for c in db.execute(
                            "SELECT start,end FROM cues WHERE source_id=? AND kind IN ('dialogue','song')",
                            (row["source_id"],),
                        )
                    ]
                ranges, missing = restrict_boundaries(
                    ranges, annotations, descriptor, duration, body["boundaries"]
                )
                unknown += int(missing)
            tracks.setdefault(row["track_id"], []).extend(ranges)
            associations.setdefault(row["track_id"], []).append((row["sample_id"], row["start"], row["end"]))
    subjects = []
    stale = []
    for row in db.execute("SELECT * FROM pitch_tracks"):
        if row["id"] not in tracks:
            continue
        try:
            validate_track(row)
        except (ValueError, OSError) as exc:
            stale.append({"track_id": row["id"], "reason": str(exc)})
            continue
        subjects.append({**dict(row), "ranges": tracks[row["id"]]})
    result = ({"results":[]} if coverage_only else search_tracks(subjects, body["text"], body.get("parameters"), result_limit=None))
    for hit in result["results"]:
        hit["sample_ids"] = [
            mid
            for mid, lo, hi in associations.get(hit["asset_id"], [])
            if lo <= hit["start"] + 1e-8 and hit["end"] <= hi + 1e-8
        ]
        if mode == "sources":
            hit["source_assets"] = [
                {k: v for k, v in a.items() if k != "allowed_ranges"}
                for a in source_associations[hit["asset_id"]]
                if any(
                    lo <= hit["start"] + 1e-8 and hit["end"] <= hi + 1e-8 for lo, hi in a["allowed_ranges"]
                )
            ]
    valid = {s["id"] for s in subjects}
    indexed = {mid for tid, items in associations.items() if tid in valid for mid, _, _ in items}
    if mode == "sources":
        coverage["indexed_assets"] = sum(
            len(items) for tid, items in source_associations.items() if tid in valid
        )
    result["mode"] = mode
    result["coverage"] = {
        **coverage,
        "eligible_samples": len(eligible),
        "indexed_samples": len(indexed),
        "boundary_unknown_samples": unknown,
        "stale_tracks": stale,
    }
    result['elapsed_seconds']=time.perf_counter()-began
    if coverage_only:return result
    result['index_versions']={s['id']:s['signature'] for s in subjects}
    result['grouped_results']=group_results(db,result['results'][:100],mode,associations)
    result['results']=result['results'][:100]
    result['elapsed_seconds']=time.perf_counter()-began
    return result


def group_results(db,hits,mode,associations):
    grouped={}
    for hit in hits:
        if mode=='samples':
            for mid,lo,hi in associations.get(hit['asset_id'],[]):
                if not lo<=hit['start']+1e-8 or not hit['end']<=hi+1e-8:continue
                if mid not in grouped:
                    if len(grouped)>=100:continue
                    r=db.execute('SELECT m.id,m.title,m.source_id,m.start,m.end,m.nature,m.starred FROM materials m WHERE m.id=?',(mid,)).fetchone()
                    if not r:continue
                    grouped[mid]={**dict(r),'material_id':mid,'sample_title':r['title'],'duration':hi-lo,'hits':[],'tags':[]}
                grouped[mid]['hits'].append({**{k:v for k,v in hit.items() if k not in ('sample_ids','source_assets')},'kind':'pitch','id':identity('pitch-hit',hit['asset_id'],hit['start'],mid),
                    'material_id':mid,'file_start':hit['start'],'file_end':hit['end'],'start':hit['start']-lo,'end':hit['end']-lo})
        else:
            for asset in hit.get('source_assets',[]):
                aid=asset['asset_id'];r=db.execute('SELECT s.id,s.title,a.descriptor FROM sound_assets a JOIN sources s ON s.id=a.source_id WHERE a.id=?',(aid,)).fetchone()
                if not r:continue
                if aid not in grouped and len(grouped)>=100:continue
                item=grouped.setdefault(aid,{'id':aid,'source_result':True,'source_id':r['id'],'title':r['title'], 'sample_title':r['title'],'hits':[],'tags':[]})
                descriptor=json.loads(r['descriptor'])
                from .asset_timeline import map_time
                source_range=[map_time(descriptor['root_knots'],hit[k]-descriptor['start']) for k in ('start','end')]
                item['hits'].append({**{k:v for k,v in hit.items() if k not in ('sample_ids','source_assets')},'kind':'pitch','id':identity('pitch-hit',aid,hit['start']),
                    'source_range':source_range,'source_role':descriptor.get('role','raw'),'source_asset_id':aid,'file_start':hit['start'],'file_end':hit['end'],'source_id':r['id']})
    if mode=='samples':
        from .ui_catalog import effective_all
        labels=effective_all(db,list(grouped))
        for mid,item in grouped.items():item['tags']=labels.get(mid,[])
    return list(grouped.values())[:100]


def validate_track(row):
    """Cheap query-time identity checks. Hash verification belongs to index jobs."""
    from .sound_features import model_info

    descriptor = json.loads(row["descriptor"])
    stat = Path(descriptor["path"]).stat()
    if [stat.st_size, stat.st_mtime_ns] != descriptor["file_stat"]:
        raise ValueError("声音文件已改变，请重建索引")
    signature = identity(
        VERSION, descriptor["sha256"], descriptor.get("audio_stream", 0), model_info()["sha256"]
    )
    if signature != row["signature"]:
        raise ValueError("F0 算法或模型版本已改变，请重建索引")
    folder = Path(row["path"])
    manifest = json.loads((folder / "manifest.json").read_text())
    if manifest["signature"] != signature or manifest["frames"] != row["frames"]:
        raise ValueError("索引代次不匹配")
    for name, count in (("native.npy", row["frames"]), ("summary.npy", math.ceil(row["frames"] / COARSE))):
        values = np.load(folder / name, mmap_mode="r", allow_pickle=False)
        if values.shape != (count, 3) or values.dtype != np.float32:
            raise ValueError("索引帧结构不匹配，请重建索引")
    return descriptor


def hit_selection(db, asset_id, start, end, *, sample_id=None, source_asset_id=None):
    """Resolve file-clock hits to an explicit provenance, without saving a sample."""
    from .asset_timeline import AssetSelection, selection_asset
    from .selection_ops import from_sample

    if bool(sample_id) == bool(source_asset_id):
        raise ValueError("请选择一个关联采样或原片声音资产")
    track = db.execute("SELECT * FROM pitch_tracks WHERE id=?", (asset_id,)).fetchone()
    if not track:
        raise ValueError("音高索引不存在")
    indexed = validate_track(track)
    if sample_id:
        whole = from_sample(db, sample_id)
    else:
        row = db.execute("SELECT duration FROM sound_assets WHERE id=?", (source_asset_id,)).fetchone()
        if not row:
            raise ValueError("声音资产不存在")
        whole = AssetSelection(source_asset_id, 0, row[0])
    descriptor = selection_asset(db, whole)
    if any(descriptor.get(k, 0) != indexed.get(k, 0) for k in ("path", "sha256", "audio_stream")):
        raise ValueError("关联音源已改变，请重新搜索")
    if (
        not all(math.isfinite(x) for x in (start, end))
        or not descriptor["start"] <= start < end <= descriptor["end"]
    ):
        raise ValueError("命中未完整落在关联选区内")
    return AssetSelection(
        whole.asset_id, whole.start + start - descriptor["start"], whole.start + end - descriptor["start"]
    )
