"""Reference-aware maintenance of generated files; never a general file deleter.

Measurements, originals, saved assets and whole-source stems are durable data.
Only allowlisted generated roots are considered. Historical task logs are not
ownership roots, but live jobs block maintenance. No symlink is traversed.
"""

import json
import os
import time
from pathlib import Path

from filelock import FileLock

from .workspace import ROOT, write_json

GROUPS = {
    "playback": ("播放与可视化缓存", ["data/cache", "data/previews", "data/sound-previews"]),
    "pcm": ("临时解码音频", ["data/sample-cache", "data/audio"]),
    "processing": (
        "模型处理结果",
        [
            "data/media/plugin-output",
            "data/media/processed",
            "data/media/source-vocals",
            "data/vocals",
            "data/alignment",
        ],
    ),
    "derived": ("派生节奏缓存", ["data/sample-plans", "data/quantization-plans", "data/unit-features"]),
}
# These are caches/projections or historical execution records, not owners of audio.
NON_OWNERS = {
    "operation_jobs",
    "jobs",
    "processed_audio_assets",
    "rhythm_index",
    "speech_unit_indices",
    "sample_records",
}


def maintenance_lock(root=ROOT):
    p = root / "data/cache-maintenance.lock"
    p.parent.mkdir(parents=True, exist_ok=True)
    return FileLock(str(p), timeout=30)


def strings(value):
    if isinstance(value, str):
        if value[:1] in ("{", "["):
            try:
                yield from strings(json.loads(value))
                return
            except ValueError:
                pass
        yield value
    elif isinstance(value, dict):
        for v in value.values():
            yield from strings(v)
    elif isinstance(value, (list, tuple)):
        for v in value:
            yield from strings(v)


def files(folder):
    if folder.is_symlink() or folder.resolve() != folder.absolute() or not folder.is_dir():
        return
    for parent, dirs, names in os.walk(folder, followlinks=False):
        dirs[:] = [d for d in dirs if not (Path(parent) / d).is_symlink()]
        for name in names:
            p = Path(parent) / name
            if not p.is_symlink():
                yield p


def references(db, root):
    tables = {r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    values = set()
    for table in tables - NON_OWNERS:
        if table.startswith("sqlite_"):
            continue
        for row in db.execute('SELECT * FROM "' + table.replace('"', '""') + '"'):
            values.update(strings(tuple(row)))
    assets = (
        dict(db.execute("SELECT id,payload FROM processed_audio_assets"))
        if "processed_audio_assets" in tables
        else {}
    )
    values.update(s.removeprefix("artifact:") for s in list(values) if s.startswith("artifact:"))
    keep = set()
    while True:
        added = []
        for aid, payload in assets.items():
            if aid in keep:
                continue
            obj = json.loads(payload)
            if aid in values or obj.get("asset", {}).get("path") in values:
                keep.add(aid)
                added.extend(strings(obj))
        if not added:
            break
        values.update(added)
    paths = set()
    for s in values:
        if s.startswith((str(root) + os.sep, "data/", "outputs/")):
            p = Path(s) if Path(s).is_absolute() else root / s
            # Only concrete files, not broad historical output directories.
            if p.is_file():
                paths.add(p.absolute())
            elif p.is_dir() and (p / "manifest.json").is_file():
                paths.add(p / "manifest.json")
    # Retain sidecars and any inputs needed to interpret durable raw results.
    pending = list(paths)
    seen = set()
    while pending:
        p = pending.pop()
        if p in seen:
            continue
        seen.add(p)
        candidates = [p.with_suffix(".features.json"), p.with_suffix(".json")]
        if p.suffix == ".json" and p.stat().st_size < 20_000_000:
            try:
                for s in strings(json.loads(p.read_text())):
                    if s.startswith(str(root) + os.sep):
                        q = Path(s)
                        if q.is_file():
                            candidates.append(q)
                        elif q.is_dir() and (q / "manifest.json").is_file():
                            candidates.append(q / "manifest.json")
            except (OSError, ValueError):
                pass
        for q in candidates:
            if q.is_file() and q not in paths:
                paths.add(q)
                pending.append(q)
    # An aligned sample projection's local PCM is inexpensive but some saved
    # plans still address it directly. Keep it until those plans are rebuilt.
    if "sample_records" in tables:
        for row in db.execute("SELECT payload FROM sample_records"):
            for s in strings(row[0]):
                if s.startswith(str(root) + os.sep):
                    p = Path(s)
                    if p.is_file():
                        paths.add(p)
    return paths, set(assets) - keep


def active_jobs(db):
    tables = {r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    if "operation_jobs" not in tables:
        return False
    return bool(
        db.execute("SELECT 1 FROM operation_jobs WHERE status IN ('running','queued') LIMIT 1").fetchone()
    )


def inventory(db, root=ROOT, *, now=None):
    now = time.time() if now is None else now
    protected, orphan_ids = references(db, root)
    rows, candidates = [], []
    for key, (title, roots) in GROUPS.items():
        row = {
            "key": key,
            "title": title,
            "total_bytes": 0,
            "reclaimable_bytes": 0,
            "protected_bytes": 0,
            "recent_bytes": 0,
            "files": 0,
        }
        for sub in roots:
            for p in files(root / sub):
                st = p.stat()
                row["files"] += 1
                row["total_bytes"] += st.st_size
                # Features cost model inference. Keep all measurements, even if
                # their adjacent decoded WAV can be regenerated cheaply.
                owned = p in protected or p.name.endswith(".features.json") or "native-player" in p.parts
                if owned:
                    row["protected_bytes"] += st.st_size
                elif now - st.st_mtime < 900 or p.suffix in (".lock", ".part", ".tmp"):
                    row["recent_bytes"] += st.st_size
                else:
                    row["reclaimable_bytes"] += st.st_size
                    candidates.append((p, st.st_size, st.st_mtime_ns))
        rows.append(row)
    return (
        {
            "categories": rows,
            "total_bytes": sum(r["total_bytes"] for r in rows),
            "reclaimable_bytes": sum(r["reclaimable_bytes"] for r in rows),
            "active_jobs": active_jobs(db),
        },
        candidates,
        orphan_ids,
    )


def status(db, root=ROOT):
    return inventory(db, root)[0]


def clean(db, root=ROOT, *, automatic=False, now=None):
    with maintenance_lock(root):
        # Freeze registration changes while taking the reference snapshot and deleting.
        if not db.in_transaction:
            db.execute("BEGIN IMMEDIATE")
        if active_jobs(db):
            raise ValueError("有排队或运行中的任务，请任务结束后清理缓存")
        report, candidates, orphan_ids = inventory(db, root, now=now)
        now = time.time() if now is None else now
        cheap = lambda p: any(
            p.is_relative_to(root / sub) for key in ("playback", "pcm", "derived") for sub in GROUPS[key][1]
        )
        total = sum(size for p, size, _ in candidates if not automatic or cheap(p))
        removed, skipped, freed = [], [], 0
        for p, size, stamp in sorted(candidates, key=lambda item: item[2]):
            # Automatic policy only evicts cheap caches, never model outputs.
            if automatic:
                if not cheap(p):
                    continue
                if now - stamp / 1e9 < 7 * 86400 and total - freed <= 2 * 1024**3:
                    continue
            try:
                if p.is_symlink() or p.stat().st_mtime_ns != stamp:
                    skipped.append(str(p))
                    continue
                p.unlink()
                freed += size
                removed.append(str(p.relative_to(root)))
            except OSError:
                skipped.append(str(p))
        if not automatic and orphan_ids:
            db.executemany("DELETE FROM processed_audio_assets WHERE id=?", [(x,) for x in orphan_ids])
        db.commit()
        # Remove empty generated directories only; never follow links.
        for _, roots in GROUPS.values():
            for sub in roots:
                base = root / sub
                for parent, dirs, _ in os.walk(base, topdown=False, followlinks=False):
                    for d in dirs:
                        try:
                            (Path(parent) / d).rmdir()
                        except OSError:
                            pass
        result = {
            "freed_bytes": freed,
            "removed_files": len(removed),
            "skipped_files": len(skipped),
            "automatic": automatic,
        }
        out = root / "data/maintenance" / f"cache-clean-{time.time_ns()}.json"
        write_json(out, {**result, "removed": removed, "skipped": skipped, "before": report})
        return result


def automatic_maintenance():
    """Called only after the local API has been idle; no model computation."""
    from .ui_catalog import settings
    from .workspace import connect

    with connect() as db:
        if not settings(db).get("cache_auto_trim", True) or active_jobs(db):
            return
        clean(db, automatic=True)
