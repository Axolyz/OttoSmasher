"""Active measurements may be shared by selections of the same physical sound."""

import json

from .asset_timeline import adopt_analysis
from .workspace import identity


def publish(db, run_id, annotation_id, *, automatic=False):
    run = db.execute("SELECT * FROM analysis_runs WHERE id=?", (run_id,)).fetchone()
    if not run or not run["asset_id"]:
        return None
    owner = identity("asset-text-analysis", run["asset_id"], run["start"], run["end"], annotation_id)
    return adopt_analysis(db, "asset_text", owner, run["kind"], run_id, automatic=automatic)


def covering(db, asset, kind):
    """Only current heads, exact content identity and complete input coverage.

    A matching source-time range alone is never evidence that processed sound
    was measured. Sharing uses file bytes, stream and compatible time mapping.
    """
    if not asset.get("sha256") or not asset.get("path"):
        return None
    from .source_locations import original_path

    lookup_path = original_path(db, asset["path"])
    rows = db.execute(
        """SELECT a.*,s.descriptor FROM sound_assets s
        CROSS JOIN analysis_runs a ON a.asset_id=s.id
        WHERE a.kind=?
        AND json_extract(s.descriptor,'$.path')=? AND json_extract(s.descriptor,'$.sha256')=?
        AND json_extract(s.descriptor,'$.start')+a.start <= ?
        AND json_extract(s.descriptor,'$.start')+a.end >= ?
        AND EXISTS (SELECT 1 FROM analysis_references r
                    WHERE r.run_id=a.id AND r.owner_type IN ('asset_text','annotation'))
        ORDER BY a.human DESC,a.created DESC""",
        (kind, lookup_path, asset["sha256"], asset["start"] + 1e-8, asset["end"] - 1e-8),
    )
    for row in rows:
        descriptor = json.loads(row["descriptor"])
        if descriptor.get("audio_stream", 0) != asset.get("audio_stream", 0):
            continue
        if (
            descriptor["start"] + row["start"] > asset["start"] + 1e-8
            or descriptor["start"] + row["end"] < asset["end"] - 1e-8
        ):
            continue
        # Verify root positions at every knot in the selected view. Equivalent
        # bytes with a different source mapping remain different provenance.
        from .asset_timeline import map_time

        try:
            if any(
                abs(map_time(descriptor["root_knots"], asset["start"] - descriptor["start"] + x) - y) > 1e-7
                for x, y in asset.get("root_knots", [])
            ):
                continue
        except (KeyError, ValueError):
            continue
        if json.loads(row["payload"]).get("clock") != "asset":
            continue
        return row
    return None


def intersecting(db, selection, kind):
    """Display current runs over a viewport; do not combine them into a measurement."""
    from .asset_timeline import AssetSelection, selection_asset, map_time

    selected = AssetSelection(**selection)
    asset = selection_asset(db, selected)
    if not asset.get("path") or not asset.get("sha256"):
        return []
    from .source_locations import original_path

    lookup_path = original_path(db, asset["path"])
    select = """SELECT a.*,s.descriptor,
        (SELECT r.owner_id FROM analysis_references r WHERE r.run_id=a.id AND r.owner_type='annotation' LIMIT 1) annotation
        FROM sound_assets s CROSS JOIN analysis_runs a ON a.asset_id=s.id WHERE """
    current = """ AND a.kind=? AND EXISTS (SELECT 1 FROM analysis_references r WHERE r.run_id=a.id
        AND r.owner_type IN ('annotation','asset_text')) """
    rows = list(
        db.execute(
            select
            + "json_extract(s.descriptor,'$.path')=? AND json_extract(s.descriptor,'$.sha256')=? AND json_extract(s.descriptor,'$.start')+a.start < ? AND json_extract(s.descriptor,'$.start')+a.end > ?"
            + current,
            (lookup_path, asset["sha256"], asset["end"], asset["start"], kind),
        )
    )
    # The legacy whole-track clip recipe records the exact parent content. This
    # is a crop relationship, never an inference from coincident source times.
    rows += list(
        db.execute(
            select
            + """json_extract(s.descriptor,'$.provenance.full_source_asset.path')=?
        AND json_extract(s.descriptor,'$.provenance.full_source_asset.sha256')=?
        AND json_extract(s.descriptor,'$.provenance.version')='whole-vocal-clip-v1'
        AND json_extract(s.descriptor,'$.provenance.window_start') < ?
        AND json_extract(s.descriptor,'$.provenance.window_end') > ?"""
            + current,
            (lookup_path, asset["sha256"], asset["root_knots"][-1][1], asset["root_knots"][0][1], kind),
        )
    )
    rows.sort(key=lambda r: (r["human"], r["created"]), reverse=True)
    result, seen = [], set()
    for row in rows:
        original = json.loads(row["descriptor"])
        parent = original.get("provenance", {}).get("full_source_asset") or {}
        inherited_crop = (
            original.get("path") != lookup_path
            and parent.get("path") == lookup_path
            and parent.get("sha256") == asset["sha256"]
        )
        measured = parent if inherited_crop else original
        if measured.get("audio_stream", 0) != asset.get("audio_stream", 0):
            continue
        try:

            def file_time(value, clock):
                if clock == "asset" and not inherited_crop:
                    return original["start"] + value
                root = map_time(original["root_knots"], value) if clock == "asset" else value
                return measured["start"] + map_time(measured["root_knots"], root, inverse=True)

            lo = max(asset["start"], file_time(row["start"], "asset"))
            hi = min(asset["end"], file_time(row["end"], "asset"))
            if hi <= lo:
                continue
            # Legacy track duration can differ from its source by one PCM frame.
            tolerance = max(1e-7, 1 / measured.get("sample_rate", 192000)) if inherited_crop else 1e-7
            if any(
                abs(
                    map_time(measured["root_knots"], t - measured["start"])
                    - map_time(asset["root_knots"], t - asset["start"])
                )
                > tolerance
                for t in (lo, hi)
            ):
                continue
        except (KeyError, ValueError):
            continue
        payload = json.loads(row["payload"])
        annotation = payload.get("annotation_id") or row["annotation"] or row["id"]
        if annotation in seen:
            continue
        seen.add(annotation)
        for i, phone in enumerate(payload.get("phones", [])):
            try:
                start, end = (file_time(phone[k], payload.get("clock", "source")) for k in ("start", "end"))
            except (KeyError, ValueError):
                continue
            if start < hi and end > lo:
                result.append(
                    {
                        "id": f"phone-{row['id']}-{i}",
                        "run_id": row["id"],
                        "phone_index": i,
                        "annotation_id": annotation,
                        "human": bool(row["human"]),
                        "start": max(start, lo) - asset["start"],
                        "end": min(end, hi) - asset["start"],
                        "label": phone.get("phone", phone.get("label", "")),
                        "layer": "phones",
                    }
                )
    # Reuse asset-local energy facts; the viewport never dispatches inference.
    from pathlib import Path
    from .vowel_bounds import annotate
    import numpy as np

    feature_path = Path(asset["path"]).with_suffix(".features.json")
    try:
        if feature_path.is_file():
            frames = json.loads(feature_path.read_text())
            frames["times"] = np.asarray(frames["times"]) - asset["start"]
            annotate(result, frames)
        elif asset["end"] - asset["start"] <= 30 and asset.get("audio_stream", 0) == 0:
            from .boundaries import energy_frames

            times, rms, hop = energy_frames(asset["path"], 0, start=asset["start"], end=asset["end"])
            annotate(result, {"times": times + hop / 2, "energy": rms * rms})
    except (OSError, ValueError, RuntimeError):
        pass  # No valid energy evidence: keep the original FA range.
    return result
