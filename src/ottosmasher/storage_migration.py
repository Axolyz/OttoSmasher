"""Explicit resumable migration of generated audio. Originals are never candidates."""

import json
from pathlib import Path

import soundfile as sf

from .materials import sha256
from .workspace import DATA, ROOT, identity, write_json


def preserve_feature_sidecars(mapping):
    """Carry whole-asset measurements across an explicitly authorized encoding migration.

    Cropped views have a different clock and must never become a parent sidecar.
    Existing target measurements take precedence; old measurements remain intact.
    """
    import os
    import shutil
    import tempfile

    copied = []
    for old, target in mapping.items():
        if target["source"] != old or target["offset"] != 0:
            continue
        source = Path(old).with_suffix(".features.json")
        audio = Path(target["path"])
        destination = audio.with_suffix(".features.json")
        if not source.is_file() or destination.exists():
            continue
        if not audio.is_file() or sha256(audio) != target["sha256"]:
            raise ValueError(f"迁移目标身份不匹配：{audio}")
        fd, temporary = tempfile.mkstemp(dir=destination.parent, suffix=".features.tmp")
        os.close(fd)
        try:
            shutil.copyfile(source, temporary)
            os.replace(temporary, destination)
        finally:
            Path(temporary).unlink(missing_ok=True)
        copied.append(str(destination))
    return copied


def plan(db):
    """Resolve proven legacy crop ancestry before selecting physical encodings."""
    from functools import lru_cache

    digest = lru_cache(maxsize=None)(sha256)
    assets = [json.loads(r[0]) for r in db.execute("SELECT descriptor FROM sound_assets")]
    recipes, retained = {}, set()
    for asset in assets:
        path = Path(asset.get("path", ""))
        if (
            not path.is_file()
            or not path.is_relative_to(DATA)
            or path.suffix.lower() not in (".wav", ".flac", ".mp3")
        ):
            continue
        lineage = asset.get("provenance", {})
        parent = lineage.get("full_source_asset", {})
        if (
            lineage.get("version") == "whole-vocal-clip-v1"
            and parent.get("path")
            and str(path) != parent["path"]
        ):
            source = Path(parent["path"])
            offset = (
                lineage["window_start"] - parent.get("root_knots", [[0, 0]])[0][1] + parent.get("start", 0)
            )
            if not source.is_file() or digest(source) != parent.get("sha256"):
                raise ValueError(f"裁切父轨无法验证：{source}")
            if digest(path) != asset.get("sha256"):
                raise ValueError(f"裁切音频已改变：{path}")
            duration = sf.info(path).duration
            if offset < 0 or offset + duration > sf.info(source).duration + 2 / 44100:
                raise ValueError(f"裁切范围超出父轨：{path}")
            recipes[str(path)] = {"source": str(source), "offset": offset, "duration": duration}
            retained.add(str(source))
        else:
            retained.add(str(path))
    # Explicitly saved processed assets are also owners, including unused alternate stems.
    from .cache_storage import references

    protected, _ = references(db, ROOT)
    # Only registered audio owners, not historical input paths, force a separate encoding.
    for row in db.execute("SELECT payload FROM processed_audio_assets"):
        doc = json.loads(row[0])
        path = Path(doc.get("asset", {}).get("path", ""))
        if (
            path in protected
            and path.is_file()
            and path.is_relative_to(DATA)
            and path.suffix.lower() in (".wav", ".flac", ".mp3")
        ):
            retained.add(str(path))
    for row in db.execute("SELECT payload FROM shared_sample_audio"):
        asset = json.loads(row[0])
        path = Path(asset.get("path", ""))
        if path.is_file() and path.is_relative_to(DATA) and path.suffix.lower() in (".wav", ".flac", ".mp3"):
            retained.add(str(path))
    for path in retained:
        recipes.setdefault(path, {"source": path, "offset": 0, "duration": sf.info(path).duration})
    return recipes


def rewrite(value, mapping):
    if isinstance(value, list):
        return [rewrite(v, mapping) for v in value]
    if not isinstance(value, dict):
        return mapping[value]["path"] if isinstance(value, str) and value in mapping else value
    out = {k: rewrite(v, mapping) for k, v in value.items()}
    path = value.get("path")
    if path in mapping:
        target = mapping[path]
        if "start" in value and "end" in value:
            out.update(start=value["start"] + target["offset"], end=value["end"] + target["offset"])
        if "sha256" in value:
            out["sha256"] = target["sha256"]
    path = value.get("audio_path")
    if path in mapping:
        target = mapping[path]
        first = value.get("audio_start", 0)
        last = value.get(
            "audio_end", first + value.get("window_end", target["duration"]) - value.get("window_start", 0)
        )
        out.update(
            audio_start=first + target["offset"],
            audio_end=last + target["offset"],
            audio_sha256=target["sha256"],
        )
    if isinstance(out.get("asset"), dict) and "file_stat" in out:
        path = Path(out["asset"].get("path", ""))
        if path.is_file():
            st = path.stat()
            out["file_stat"] = [st.st_size, st.st_mtime_ns]
    return out


def migrate(db, *, apply=False, progress=print, migration_id="compact-v1"):
    from .audio_storage import durable
    from .cache_storage import active_jobs, maintenance_lock
    from .materials import playback_record
    from .sample_analysis import decode_record, encode_record, measurement, signature
    from .sample_audio import resolve

    folder = DATA / "maintenance" / migration_id.replace("compact", "storage")
    folder.mkdir(parents=True, exist_ok=True)
    journal = folder / "migration.json"
    state = json.loads(journal.read_text()) if journal.exists() else {"phase": "planned", "mapping": {}}
    if state["phase"] == "complete":
        return state

    with maintenance_lock(ROOT):
        if active_jobs(db):
            raise ValueError("有运行中的任务，暂不迁移")
        if state["phase"] == "planned":
            recipes = plan(db)
            write_json(folder / "plan.json", recipes)
            if not apply:
                return {
                    "physical_files": len({x["source"] for x in recipes.values()}),
                    "range_views": sum(bool(x["offset"]) for x in recipes.values()),
                }
            physical = {}
            for i, source in enumerate(sorted({x["source"] for x in recipes.values()})):
                target = durable(source)
                physical[source] = {"path": str(target), "sha256": sha256(target)}
                progress(f"encode {i + 1}: {Path(source).name}", flush=True)
            state["mapping"] = {p: {**recipe, **physical[recipe["source"]]} for p, recipe in recipes.items()}
            # Model-specific cropped files are reproducible views of the same parent.
            for row in db.execute("SELECT payload FROM analysis_runs"):
                doc = json.loads(row[0])
                lineage = doc.get("audio_lineage") or {}
                p = lineage.get("audio_path")
                parent = lineage.get("full_source_asset") or {}
                if (
                    p
                    and p not in state["mapping"]
                    and parent.get("path") in physical
                    and lineage.get("crop_backend")
                ):
                    if Path(p).is_file():
                        state["mapping"][p] = {
                            **physical[parent["path"]],
                            "source": parent["path"],
                            "offset": lineage["window_start"],
                            "duration": lineage["window_end"] - lineage["window_start"],
                        }
            state["phase"] = "encoded"
            write_json(journal, state)
        mapping = state["mapping"]
        preserve_feature_sidecars(mapping)
        if (
            state["phase"] == "encoded"
            and db.execute("SELECT 1 FROM sqlite_master WHERE name='storage_migrations'").fetchone()
            and db.execute("SELECT 1 FROM storage_migrations WHERE id=?", (migration_id,)).fetchone()
        ):
            state["phase"] = "published"
        if state["phase"] == "encoded":
            # A single transaction publishes all pointers; files remain recoverable until verified.
            with db:
                db.execute("BEGIN IMMEDIATE")
                guards = list(
                    db.execute(
                        "SELECT name,sql FROM sqlite_master WHERE type='trigger' AND name IN ('immutable_sound_assets_update','immutable_asset_inputs_update','immutable_analysis_runs_update')"
                    )
                )
                for name, _ in guards:
                    db.execute(f'DROP TRIGGER "{name}"')
                tables = [
                    r[0]
                    for r in db.execute(
                        "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
                    )
                ]
                for table in tables:
                    if table.startswith("legacy_") or table in (
                        "sample_records",
                        "speech_search_index",
                        "search_session_rows",
                        "search_sessions",
                    ):
                        continue
                    columns = [
                        r[1]
                        for r in db.execute(f'PRAGMA table_info("{table}")')
                        if r[2].upper() in ("TEXT", "")
                    ]
                    if not columns:
                        continue
                    cursor = db.execute(
                        f'SELECT rowid,{",".join(chr(34) + c + chr(34) for c in columns)} FROM "{table}"'
                    )
                    for row in cursor:
                        changed = {}
                        for col, value in zip(columns, tuple(row)[1:]):
                            if not isinstance(value, str):
                                continue
                            if value[:1] in ("{", "["):
                                try:
                                    obj = json.loads(value)
                                    new = rewrite(obj, mapping)
                                except ValueError:
                                    continue
                                if new != obj:
                                    changed[col] = json.dumps(new, ensure_ascii=False, separators=(",", ":"))
                            elif value in mapping:
                                changed[col] = mapping[value]["path"]
                        if changed:
                            db.execute(
                                f'UPDATE "{table}" SET '
                                + ",".join('"' + c + '"=?' for c in changed)
                                + " WHERE rowid=?",
                                [*changed.values(), row[0]],
                            )
                for row in db.execute("SELECT id,descriptor FROM sound_assets").fetchall():
                    asset = json.loads(row["descriptor"])
                    db.execute(
                        "UPDATE sound_assets SET content_key=? WHERE id=?", (asset.get("sha256"), row["id"])
                    )
                # Keep measured features; update only derived projection identities.
                ids = list(db.execute("SELECT material_id,backend FROM sample_records"))
                for i, (mid, backend) in enumerate(ids):
                    row = db.execute(
                        "SELECT payload FROM sample_records WHERE material_id=? AND backend=?", (mid, backend)
                    ).fetchone()
                    original_record = decode_record(row[0])
                    record = rewrite(original_record, mapping)
                    sample = playback_record(db, mid)
                    sample["analysis_settings"] = (
                        json.loads(sample["analysis_settings"])
                        if isinstance(sample["analysis_settings"], str)
                        else sample["analysis_settings"]
                    )
                    asset = resolve(db, mid)
                    old_features = Path(original_record["cue"]["path"]).with_suffix(".features.json")
                    new_features = (
                        DATA / "sample-cache" / (identity("sample-pcm-v1", asset) + ".features.json")
                    )
                    if old_features.is_file() and not new_features.exists():
                        import shutil

                        new_features.parent.mkdir(parents=True, exist_ok=True)
                        shutil.copyfile(old_features, new_features)
                    if record == original_record and asset == record["asset"]:
                        continue
                    measured = measurement(db, sample, backend)
                    if measured:
                        sig = signature(sample, asset, measured, db)
                        record["signature"] = sig
                        record["asset"] = asset
                        for entry in [record, *record.get("entries", [])]:
                            entry["signature"] = sig
                            entry["asset"] = asset
                        db.execute(
                            "UPDATE sample_records SET signature=?,payload=? WHERE material_id=? AND backend=?",
                            (sig, encode_record(record), mid, backend),
                        )
                    if i % 1000 == 0:
                        progress(f"projection {i}/{len(ids)}", flush=True)
                db.execute("DELETE FROM speech_unit_indices")
                db.execute("DELETE FROM speech_search_index")
                db.execute("CREATE TABLE IF NOT EXISTS storage_migrations(id TEXT PRIMARY KEY)")
                db.execute("INSERT OR REPLACE INTO storage_migrations VALUES(?)", (migration_id,))
                for _, sql in guards:
                    db.execute(sql)
            state["phase"] = "published"
            write_json(journal, state)
        if state["phase"] == "published":
            # Manifests are metadata, not additional audio owners. Keep their recipes current.
            for root in (
                "vocals",
                "alignment",
                "media/source-vocals",
                "media/processed",
                "media/plugin-output",
            ):
                for path in (DATA / root).rglob("*.json"):
                    if path.is_symlink():
                        continue
                    try:
                        old = json.loads(path.read_text())
                        new = rewrite(old, mapping)
                        if new != old:
                            write_json(path, new)
                    except (ValueError, UnicodeError):
                        continue
            missing = [
                json.loads(r[0]).get("path")
                for r in db.execute("SELECT descriptor FROM sound_assets")
                if json.loads(r[0]).get("path") and not Path(json.loads(r[0])["path"]).is_file()
            ]
            if missing:
                raise ValueError(f"资产文件缺失，停止释放旧文件：{missing[:3]}")
            state["phase"] = "verified"
            write_json(journal, state)
        return state


def finalize(db, *, progress=print, migration_id="compact-v1"):
    """Verify live owners, rebind reusable F0 indices, then retire generated intermediates."""
    from .audio_storage import audio_owners
    from .cache_storage import active_jobs, maintenance_lock
    from .sample_audio import resolve

    folder = DATA / "maintenance" / migration_id.replace("compact", "storage")
    journal = folder / "migration.json"
    state = json.loads(journal.read_text())
    if state["phase"] not in ("verified", "complete"):
        raise ValueError("引用尚未验证，不能释放旧音频")
    if state["phase"] == "complete":
        return state
    with maintenance_lock(ROOT):
        if active_jobs(db):
            raise ValueError("仍有活动任务")
        from .pitch_search import VERSION
        from .sound_features import model_info

        for track in db.execute("SELECT * FROM pitch_tracks").fetchall():
            descriptor = json.loads(track["descriptor"])
            path = Path(descriptor["path"])
            stat = path.stat()
            signature = identity(
                VERSION, descriptor["sha256"], descriptor.get("audio_stream", 0), model_info()["sha256"]
            )
            descriptor.update(file_stat=[stat.st_size, stat.st_mtime_ns], signature=signature, id=signature)
            manifest_path = Path(track["path"]) / "manifest.json"
            manifest = json.loads(manifest_path.read_text())
            manifest.update(signature=signature, file_stat=descriptor["file_stat"])
            write_json(manifest_path, manifest)
            with db:
                db.execute(
                    "UPDATE pitch_tracks SET id=?,signature=?,descriptor=? WHERE id=?",
                    (signature, signature, json.dumps(descriptor), track["id"]),
                )
                for table in ("pitch_sample_ranges", "pitch_asset_ranges"):
                    db.execute(f"UPDATE {table} SET track_id=? WHERE track_id=?", (signature, track["id"]))
        with db:
            for row in db.execute("SELECT sample_id FROM pitch_sample_ranges").fetchall():
                asset = resolve(db, row[0])
                db.execute(
                    "UPDATE pitch_sample_ranges SET asset_signature=? WHERE sample_id=?",
                    (identity(asset), row[0]),
                )
        owners = audio_owners(db)
        # Retain any genuinely referenced file, even if it resembles an intermediate.
        missing = [str(p) for p in owners if not p.is_file()]
        if missing:
            raise ValueError(f"保留的声音文件缺失：{missing[:3]}")
        candidates = set(Path(p) for p in state["mapping"])
        for root in (
            "alignment",
            "sample-cache",
            "audio",
            "media/source-vocals",
            "media/processed",
            "media/plugin-output",
        ):
            candidates.update(p for p in (DATA / root).rglob("*.wav") if not p.is_symlink())
        removed, kept, freed = [], [], 0
        for p in sorted(candidates):
            if not p.is_file() or p.is_symlink() or not p.is_relative_to(DATA):
                continue
            if p in owners:
                kept.append(str(p))
                continue
            # Restrict retirement to generated roots/verified replacement files.
            size = p.stat().st_size
            p.unlink()
            freed += size
            removed.append(str(p))
        db.commit()
        db.execute("VACUUM")
        state.update(
            phase="complete", freed_bytes=freed, removed_files=len(removed), retained_generated_files=kept
        )
        write_json(folder / "retired-files.json", {"removed": removed, "retained": kept})
        write_json(journal, state)
        progress(f"retired {len(removed)} files, {freed / 1e9:.3f} GB", flush=True)
        return state
