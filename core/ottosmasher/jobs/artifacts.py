"""Private files left by completed workers, and paged alignment results."""

import json
import logging
import os
import stat
from collections.abc import Iterable, Iterator
from pathlib import Path
from typing import Any
from zipfile import ZIP_DEFLATED, BadZipFile, ZipFile

import msgspec

log = logging.getLogger(__name__)

CACHE_JOBS = frozenset({
    "f0.measure", "speech.analyze", "speech.align", "f0.track", "acoustic.measure",
    "import.scan", "sources.scan", "flatten",
})
INTERMEDIATE_JOBS = CACHE_JOBS | {"separate"}
RESULTS_ARCHIVE = "alignment-results.zip"
RESULTS_PER_BLOCK = 32
_ALIGNMENT_BLOCK = msgspec.msgpack.Decoder(type=dict[int, bytes])


def _linked(path: Path) -> bool:
    return path.is_symlink() or path.is_junction()


def job_directory(root: Path, jid: str) -> Path | None:
    if not jid or jid.startswith(".") or Path(jid).name != jid or _linked(root):
        return None
    job = root / jid
    return None if _linked(job) else job


def regular_files(root: Path) -> Iterator[tuple[Path, int, float]]:
    if _linked(root):
        return
    for parent, dirs, names in os.walk(root, followlinks=False):
        dirs[:] = [d for d in dirs if not _linked(Path(parent) / d)]
        for name in names:
            p = Path(parent) / name
            try:
                info = p.lstat()
            except OSError:
                continue
            if stat.S_ISREG(info.st_mode):
                yield p, info.st_size, info.st_mtime


def adopted_f0(job: Path, root: Path, plan: Iterable[dict[str, Any]]) -> Iterator[tuple[Path, Path]]:
    """Find the formal chunk for a worker copy. The caller compares bytes before deleting."""
    chunks = job / "f0"
    if _linked(chunks) or _linked(root):
        return
    for entry in plan:
        asset = job_directory(root, entry["asset"])
        if asset is None:
            continue
        source = job_directory(chunks, entry["asset"])
        formal = job_directory(asset, entry["identity"])
        if source is None or formal is None or not source.is_dir():
            continue
        manifest = formal / "manifest.json"
        try:
            if _linked(manifest):
                continue
            recorded = json.loads(manifest.read_bytes())["chunks"]
        except (OSError, ValueError, KeyError, TypeError):
            continue
        if not isinstance(recorded, dict):
            continue
        for k in entry["chunks"]:
            k = str(int(k))
            if k not in recorded:
                continue
            worker, adopted = source / f"{k}.npy", formal / f"{k}.npy"
            if not _linked(worker) and not _linked(adopted) and worker.is_file() and adopted.is_file():
                yield worker, adopted


def intermediate_files(
    job: Path, kind: str, f0_root: Path, plan: Iterable[dict[str, Any]],
) -> Iterator[tuple[Path, int, float, Path | None]]:
    names = ("input", "out", "tracks") if kind == "separate" else ("cache",) if kind in CACHE_JOBS else ()
    for name in names:
        for p, size, mtime in regular_files(job / name):
            yield p, size, mtime, None
    if kind in ("f0.measure", "speech.analyze", "acoustic.measure"):
        for worker, formal in adopted_f0(job, f0_root, plan):
            try:
                st = worker.stat()
                if st.st_size == formal.stat().st_size:
                    yield worker, st.st_size, st.st_mtime, formal
            except FileNotFoundError:
                continue


def remove_intermediate(path: Path, formal: Path | None) -> bool:
    if _linked(path) or (formal is not None and (_linked(formal) or path.read_bytes() != formal.read_bytes())):
        return False
    path.unlink()
    return True


def cleanup_intermediates(jobs_dir: Path, jid: str, kind: str, f0_root: Path, plan: Iterable[dict[str, Any]]) -> None:
    """Call after the result is committed and the worker has exited."""
    job = job_directory(jobs_dir, jid)
    if job is None:
        return
    try:
        for p, _size, _mtime, formal in intermediate_files(job, kind, f0_root, plan):
            remove_intermediate(p, formal)
    except OSError:
        log.exception("Could not clean intermediates for %s", jid)


def alignment_items(job: Path, indices: Iterable[int]) -> dict[int, bytes]:
    """Read only the archive blocks that the requested page touches. Older jobs use JSON files."""
    wanted = set(indices)
    found: dict[int, bytes] = {}
    archive = job / RESULTS_ARCHIVE
    if wanted and archive.is_file():
        with ZipFile(archive) as z:
            for block in {i // RESULTS_PER_BLOCK for i in wanted}:
                try:
                    raw = z.read(str(block))
                except KeyError:
                    continue
                found.update((i, data) for i, data in _ALIGNMENT_BLOCK.decode(raw).items() if i in wanted)
    for i in wanted - found.keys():
        try:
            found[i] = (job / "items" / f"{i}.json").read_bytes()
        except FileNotFoundError:
            pass
    return found


def archive_alignment(job: Path, *, before: float | None = None) -> tuple[int, int]:
    """Publish an archive before retiring its byte-identical JSON files."""
    items = job / "items"
    archive = job / RESULTS_ARCHIVE
    if _linked(job) or _linked(items) or _linked(archive):
        return 0, 0
    paths = {}
    for path, size, mtime in regular_files(items):
        if path.parent != items or path.suffix != ".json" or not path.stem.isascii() or not path.stem.isdecimal():
            continue
        if before is not None and mtime > before:
            return 0, 0
        idx = int(path.stem)
        if path.stem == str(idx):
            paths[idx] = (path, size)
    if len(paths) < 2 and not archive.is_file():
        return 0, 0
    tmp = archive.with_suffix(".tmp")
    published = 0
    removed = 0
    freed = 0
    try:
        if not archive.is_file():
            blocks: dict[int, list[int]] = {}
            for i in sorted(paths):
                blocks.setdefault(i // RESULTS_PER_BLOCK, []).append(i)
            # A private exclusive temp file also prevents following a stray symlink.
            if _linked(tmp):
                return 0, 0
            tmp.unlink(missing_ok=True)
            with tmp.open("xb") as f, ZipFile(f, "w", compression=ZIP_DEFLATED, compresslevel=6) as z:
                for block, indices in blocks.items():
                    z.writestr(str(block), msgspec.msgpack.encode({i: paths[i][0].read_bytes() for i in indices}))
            published = tmp.stat().st_size
            if published >= sum(size for _, size in paths.values()):
                tmp.unlink()
                return 0, 0
            tmp.replace(archive)
        with ZipFile(archive) as z:
            for name in z.namelist():
                for i, data in _ALIGNMENT_BLOCK.decode(z.read(name)).items():
                    if i in paths:
                        path, size = paths[i]
                        if not _linked(path) and path.read_bytes() == data:
                            path.unlink()
                            removed += 1
                            freed += size
    except (OSError, ValueError, BadZipFile, msgspec.DecodeError):
        log.exception("Could not archive alignment results in %s", job)
    return removed, max(0, freed - published)
