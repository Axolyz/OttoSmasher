"""Private separation intermediates, never published assets or diagnostic logs."""

import logging
import os
from pathlib import Path

log = logging.getLogger(__name__)


def separation_files(jobs_dir: Path, jid: str) -> list[tuple[Path, int, float]]:
    if not jid or Path(jid).name != jid or jid in (".", "..") or jobs_dir.is_symlink():
        return []
    job = jobs_dir / jid
    if job.is_symlink():
        return []
    files = []
    for name in ("input", "out", "tracks"):
        root = job / name
        if root.is_symlink() or not root.is_dir():
            continue
        for parent, dirs, names in os.walk(root, followlinks=False):
            dirs[:] = [d for d in dirs if not (Path(parent) / d).is_symlink()]
            for filename in names:
                p = Path(parent) / filename
                if p.is_symlink() or not p.is_file():
                    continue
                stat = p.stat()
                files.append((p, stat.st_size, stat.st_mtime))
    return files


def cleanup_separation(jobs_dir: Path, jid: str) -> None:
    """Only call after successful adoption and worker exit; keep failed-job evidence."""
    try:
        for p, _size, _mtime in separation_files(jobs_dir, jid):
            p.unlink(missing_ok=True)
    except OSError:
        # The result is already published. Leave leftovers visible/cleanable in storage.
        log.exception("Could not clean separation intermediates for %s", jid)
