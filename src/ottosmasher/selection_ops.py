"""Production services on AssetSelection, independent of a parent sample's lifetime."""

import json
import time
from pathlib import Path

from . import asset_timeline as t
from .workspace import identity


def resolve(db, selection):
    selection = selection if isinstance(selection, t.AssetSelection) else t.AssetSelection(**selection)
    return selection, t.selection_asset(db, selection)


def from_source(db, mid, start, end, role="raw", audio_stream=None):
    from .materials import playback_record
    from .sample_audio import resolve_range

    sample = playback_record(db, mid)
    descriptor = resolve_range(db, sample, start, end, role, audio_stream)
    if role == "raw":
        whole = t.register_asset(
            db,
            sample["source_id"],
            resolve_range(db, sample, 0, sample["source_duration"], role, audio_stream),
        )
        return t.AssetSelection(whole.asset_id, start, end)
    # Reuse a known track only if content AND projected provenance agree.
    for row in db.execute(
        "SELECT * FROM sound_assets WHERE source_id=? AND json_extract(descriptor,'$.path')=? AND json_extract(descriptor,'$.sha256')=?",
        (sample["source_id"], descriptor.get("path"), descriptor.get("sha256")),
    ):
        candidate = json.loads(row["descriptor"])
        lo, hi = descriptor["start"] - candidate["start"], descriptor["end"] - candidate["start"]
        if (
            candidate.get("audio_stream", 0) != descriptor.get("audio_stream", 0)
            or not 0 <= lo < hi <= row["duration"]
        ):
            continue
        selection = t.AssetSelection(row["id"], lo, hi)
        try:
            projected = t.selection_asset(db, selection)
        except ValueError:
            continue
        if projected.get("root_knots") == descriptor.get("root_knots") and projected.get(
            "role"
        ) == descriptor.get("role"):
            return selection
    return t.register_asset(db, sample["source_id"], descriptor, legacy_mapping=True)


def from_sample(db, mid, start=None, end=None, role=None):
    from .sample_audio import resolve as audio_resolve

    row = db.execute("SELECT asset_id,start,end FROM asset_samples WHERE sample_id=?", (mid,)).fetchone()
    if row and role in (None, "selected"):
        whole = t.AssetSelection(**dict(row))
    else:
        sid = db.execute("SELECT source_id FROM materials WHERE id=?", (mid,)).fetchone()
        if not sid:
            raise ValueError("采样不存在")
        whole = t.register_asset(db, sid[0], audio_resolve(db, mid, role), legacy_mapping=True)
    lo = 0 if start is None else float(start)
    hi = whole.end - whole.start if end is None else float(end)
    if not 0 <= lo < hi <= whole.end - whole.start:
        raise ValueError("选区超出采样")
    return t.AssetSelection(whole.asset_id, whole.start + lo, whole.start + hi)


def save(db, selection, *, title=None, nature=None, tags=None, commit=True):
    from .asset_compat import active, bind
    from .materials import get
    from .selection_names import suggest

    selected, asset = resolve(db, selection)
    row = db.execute("SELECT source_id FROM sound_assets WHERE id=?", (selected.asset_id,)).fetchone()
    sid = row[0]
    if nature is None:
        from .track_roles import nature as track_nature

        nature = track_nature(db, selected.asset_id)
    if nature not in {"speech", "pitched", "unpitched", "unclassified"}:
        raise ValueError("未知采样性质")
    if tags is not None and (
        not isinstance(tags, list) or any(not isinstance(x, str) or not x.strip() for x in tags)
    ):
        raise ValueError("标签应为非空文本列表")
    name = (
        title
        if title is not None
        else suggest(db, sid, asset, 0, selected.end - selected.start, selection=selected)
    )
    if not isinstance(name, str) or not name.strip():
        raise ValueError("采样名称不能为空")
    knots = asset.get("root_knots")
    if not knots:
        raise ValueError("资产没有来源映射，请普通导入")
    mid = identity("saved-selection", selected.json(), time.time_ns())
    # The compatibility fields are a source-coordinate projection, not authority.
    db.execute(
        """INSERT INTO materials(id,source_id,start,end,audio_stream,title,created,nature,status,pool)
               VALUES(?,?,?,?,?,?,?,?,'confirmed','library')""",
        (
            mid,
            sid,
            knots[0][1],
            knots[-1][1],
            asset.get("audio_stream", 0),
            name,
            time.time(),
            nature,
        ),
    )
    if active(db):
        t.bind_sample(db, mid, selected)
    else:
        bind(db, mid, asset)
    db.executemany(
        "INSERT INTO material_tags VALUES(?,?,'manual')", [(mid, x) for x in sorted(set(tags or []))]
    )
    if commit:
        db.commit()
    return get(db, mid)


def import_range(db, selection, path):
    import soundfile as sf
    selected, _ = resolve(db, selection)
    path = Path(path).expanduser().resolve(strict=True)
    info = sf.info(path)
    if info.frames <= 0:
        raise ValueError('回导文件为空')
    duration = db.execute('SELECT duration FROM sound_assets WHERE id=?', (selected.asset_id,)).fetchone()[0]
    end = selected.start + info.duration
    if end > duration + 1e-9:
        raise ValueError('回导文件从选区起点开始后超出当前资产边界')
    selected = t.AssetSelection(selected.asset_id, selected.start, min(end, duration))
    return selected, t.selection_asset(db, selected), path, info


def external_import(db, selection, path, **save_options):
    import soundfile as sf

    from .materials import sha256

    selected, parent, path, info = import_range(db, selection, path)
    knots = [list(x) for x in parent.get("root_knots", [])]
    if not knots:
        raise ValueError("输入选区没有精确来源映射")
    knots[-1][0] = info.duration
    descriptor = {
        "path": str(path),
        "sha256": sha256(path),
        "start": 0,
        "end": info.duration,
        "sample_rate": info.samplerate,
        "channels": info.channels,
        "audio_stream": 0,
        "role": "external-import",
        "root_knots": knots,
        "speech_analysis_eligible": False,
        "provenance": {
            "operation": "external-import",
            "internal_timing": "preserved",
            "input_selection": selected.json(),
        },
    }
    sid = db.execute("SELECT source_id FROM sound_assets WHERE id=?", (selected.asset_id,)).fetchone()[0]
    child = t.register_asset(db, sid, descriptor, input_selection=selected, operation="external-import")
    return save(db, child, **save_options)


def descendants(db, selection, *, groups=None, max_depth=None, source=False):
    """Project saved descendants onto the selected asset's recorded source clock."""
    selected, _descriptor = resolve(db, selection)
    if max_depth is not None and (type(max_depth) is not int or not 0 <= max_depth <= 100):
        raise ValueError("max_depth 须为 0–100 整数或 null")
    if groups is not None and (not isinstance(groups, list) or any(not isinstance(g, str) for g in groups)):
        raise ValueError("groups 须为组名列表")
    ancestor = db.execute("SELECT * FROM sound_assets WHERE id=?", (selected.asset_id,)).fetchone()
    if not ancestor["mapping"]:
        return []
    mapping = json.loads(ancestor["mapping"])
    covered_start, covered_end = max(selected.start, mapping[0][0]), min(selected.end, mapping[-1][0])
    if covered_end <= covered_start:
        return []
    lo, hi = t.map_time(mapping, covered_start), t.map_time(mapping, covered_end)
    reachable = {selected.asset_id: 0}
    frontier = [selected.asset_id]
    while frontier:
        current = frontier.pop()
        for edge in db.execute("SELECT asset_id FROM asset_inputs WHERE input_asset_id=?", (current,)):
            depth = reachable[current] + 1
            if edge[0] not in reachable and (max_depth is None or depth <= max_depth):
                reachable[edge[0]] = depth
                frontier.append(edge[0])
    if source:
        parents = {}
        for edge in db.execute("SELECT asset_id,input_asset_id FROM asset_inputs"):
            parents.setdefault(edge[0], []).append(edge[1])
        depths = {}

        def level(aid, seen=None):
            if aid in depths:
                return depths[aid]
            seen = set() if seen is None else seen
            if aid in seen:
                raise ValueError("派生关系中存在环")
            depths[aid] = 1 + max((level(p, seen | {aid}) for p in parents.get(aid, [])), default=0)
            return depths[aid]

    result = []
    for row in db.execute(
        "SELECT s.*,m.title,m.pool,a.mapping FROM asset_samples s JOIN materials m ON m.id=s.sample_id JOIN sound_assets a ON a.id=s.asset_id WHERE a.source_id=?",
        (ancestor["source_id"],),
    ):
        if (not source and row["asset_id"] not in reachable) or not row["mapping"]:
            continue
        # The source browser's technical sample is not a user-created child,
        # even when viewing a different stem/asset of the same source.
        if row["pool"] == "source-browser":
            continue
        depth = level(row["asset_id"]) if source else reachable[row["asset_id"]]
        if max_depth is not None and depth > max_depth:
            continue
        if groups and not set(groups).intersection(
            r[0]
            for r in db.execute("SELECT group_name FROM asset_groups WHERE asset_id=?", (row["asset_id"],))
        ):
            continue
        if (
            row["asset_id"] == selected.asset_id
            and row["start"] <= selected.start
            and row["end"] >= selected.end
        ):
            continue
        childmap = json.loads(row["mapping"])
        child_start, child_end = max(row["start"], childmap[0][0]), min(row["end"], childmap[-1][0])
        if child_end <= child_start:
            continue
        a, b = t.map_time(childmap, child_start), t.map_time(childmap, child_end)
        if a >= hi or b <= lo:
            continue
        result.append(
            {
                "id": row["sample_id"],
                "title": row["title"],
                "asset_id": row["asset_id"],
                "depth": depth,
                "start": t.map_time(mapping, max(lo, a), inverse=True) - selected.start,
                "end": t.map_time(mapping, min(hi, b), inverse=True) - selected.start,
            }
        )
    return sorted(result, key=lambda x: (x["start"], x["end"], x["id"]))


def separation_snapshot(db, payload):
    if payload.get("clock") == "source":
        selected = from_source(
            db,
            payload["material_id"],
            float(payload["start"]),
            float(payload["end"]),
            payload.get("role", "raw"),
            payload.get("audio_stream"),
        )
        descriptor = t.selection_asset(db, selected)
    else:
        selected, descriptor = (
            resolve(db, payload["selection"])
            if payload.get("selection")
            else resolve(
                db,
                from_sample(
                    db, payload["material_id"], payload.get("start"), payload.get("end"), payload.get("role")
                ),
            )
        )
    from .selection_names import suggest
    from .ui_catalog import settings

    sid = db.execute("SELECT source_id FROM sound_assets WHERE id=?", (selected.asset_id,)).fetchone()[0]
    return {
        **payload,
        "model": payload.get("model") or settings(db)["vocal_model"],
        "selection": selected.json(),
        "input_asset": descriptor,
        "source_id": sid,
        "suggested_title": suggest(db, sid, descriptor, 0, selected.end - selected.start, selection=selected),
    }


def separate(payload, jid):
    import soundfile as sf

    from .inference_runtime import settings
    from .materials import sha256
    from .sample_audio import pcm
    from .separation import separate as run_model
    from .workspace import DATA, connect

    if not payload.get("selection"):
        raise ValueError("分离任务缺少提交时的资产选区快照")
    selected = t.AssetSelection(**payload["selection"])
    parent = payload["input_asset"]
    source = pcm(parent)
    output = DATA / "media" / "processed" / jid
    output.mkdir(parents=True, exist_ok=True)
    outputs = run_model(
        payload.get("model", "becruily_deux"),
        [str(source)],
        output,
        payload.get("stems"),
        payload.get("device") or settings()["inference_device"],
    )[0]
    result = {"outputs": outputs, "assets": [], "samples": []}
    with connect() as db:
        for stem in outputs:
            info = sf.info(stem["path"])
            if abs(info.frames - (selected.end - selected.start) * info.samplerate) > 1 + 1e-6:
                raise ValueError("分离输出改变了长度，不能建立精确来源映射")
            knots = [list(x) for x in parent.get("root_knots", [])]
            knots[-1][0] = info.duration
            descriptor = {
                "path": stem["path"],
                "sha256": sha256(stem["path"]),
                "start": 0,
                "end": info.duration,
                "sample_rate": info.samplerate,
                "channels": info.channels,
                "audio_stream": 0,
                "role": stem["stem"],
                "root_knots": knots,
                "speech_analysis_eligible": False,
                "provenance": {**stem, "input_selection": selected.json(), "source_id": payload["source_id"]},
            }
            asset = t.register_asset(
                db,
                payload["source_id"],
                descriptor,
                input_selection=selected,
                operation="separation",
                parameters={"model": payload.get("model"), "stem": stem["stem"]},
            )
            stem["path"] = t.selection_asset(db, asset)["path"]
            result["assets"].append({"selection": asset.json(), "stem": stem["stem"]})
            if payload.get("save"):
                result["samples"].append(
                    save(
                        db,
                        asset,
                        title=payload.get("title") or payload["suggested_title"] + " · " + stem["stem"],
                        nature=payload.get("nature", "unclassified"),
                    )["id"]
                )
    return result


def flatten(payload, jid):
    """Render a selected asset and save exactly one final product."""
    import subprocess

    from .inference_runtime import python_path
    from .sample_audio import pcm
    from .workspace import CODE_ROOT, DATA, connect, write_json

    selected = t.AssetSelection(**payload["selection"])
    descriptor = payload["input_asset"]
    mode = payload.get("mode", "all")
    intervals = None
    preserve_boundaries = False
    with connect() as db:
        if mode in ('vowels', 'from_first_vowel'):
            from .flatten_pitch import phone_ranges
            intervals, preserve_boundaries = phone_ranges(db, descriptor, payload.get('backend'), payload.get('material_id'))
    request = DATA / "jobs" / (jid + "-flatten.json")
    params = {k: payload[k] for k in ("target", "inner", "transition", "pitch_strategy", "boundary_side") if k in payload}
    write_json(
        request,
        {
            "path": str(pcm(descriptor)),
            "mode": mode,
            "intervals": intervals,
            "preserve_boundaries": preserve_boundaries,
            **params,
        },
    )
    subprocess.run(
        [str(python_path()), str(CODE_ROOT / "scripts/sample_flatten_worker.py"), str(request)], check=True
    )
    output = json.loads(request.with_suffix(".result.json").read_text())
    output["root_knots"] = [list(p) for p in descriptor.get("root_knots", [])]
    if output["root_knots"]:
        import soundfile as sf

        rate = sf.info(output["path"]).samplerate
        if abs(output["end"] - output["start"] - (selected.end - selected.start)) > 1 / rate + 1e-8:
            raise ValueError("拉平输出改变了时长，不能建立精确来源映射")
        output["root_knots"][-1][0] = output["end"] - output["start"]
    with connect() as db:
        status = db.execute("SELECT status FROM operation_jobs WHERE id=?", (jid,)).fetchone()
        if status and status[0] == "cancelled":
            raise ValueError("任务已取消，未登记拉平采样")
        asset = t.register_asset(
            db,
            payload["source_id"],
            output,
            input_selection=selected,
            operation="flatten",
            parameters={"mode": mode, **params, **output.get("provenance", {}), "target_note": output["target_note"]},
        )
        output = t.selection_asset(db, asset)
        sample = save(
            db,
            asset,
            title=payload.get("title") or payload["suggested_title"],
            nature="pitched",
        )
    return {"material_id": sample["id"], "path": output["path"], "target_note": output["target_note"], "flatten_parameters": output.get("provenance", {})}
