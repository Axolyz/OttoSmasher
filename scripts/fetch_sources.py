"""Fetch upstream source for inspection/adapters, recording exact local revisions."""

import json
import os
import shutil
import subprocess
from pathlib import Path

CODE_ROOT = Path(__file__).resolve().parents[1]
ROOT = Path(os.environ.get("OTTO_ROOT", CODE_ROOT)).resolve()
REPOS = {'HubertFA': 'https://github.com/wolfgitpr/HubertFA.git', 'pymss': 'https://github.com/pymss-project/pymss.git', 'narabas': 'https://github.com/darashi/narabas.git', 'yohane': 'https://github.com/Japan7/yohane.git', 'pydomino': 'https://github.com/DwangoMediaVillage/pydomino'}


def main():
    bundled = Path.home() / ".cache/codex-runtimes/codex-primary-runtime/dependencies/bin/fallback/git"
    local = ROOT / ".runtime/envs/core/bin/git"
    git = os.environ.get("OTTOSMASHER_GIT") or (
        str(local) if local.exists() else str(bundled) if bundled.exists() else shutil.which("git")
    )
    if not git:
        raise SystemExit("Set OTTOSMASHER_GIT to a working Git executable")
    lock_path = CODE_ROOT / "dependencies/sources.lock.json"
    pinned = json.loads(lock_path.read_text()) if lock_path.exists() else {}
    lock = {}
    for name, url in REPOS.items():
        target = ROOT / "vendor" / name
        if not target.exists():
            subprocess.run([git, "init", str(target)], check=True)
            subprocess.run([git, "-C", str(target), "remote", "add", "origin", url], check=True)
            ref = pinned.get(name, {}).get("commit", "HEAD")
            subprocess.run([git, "-C", str(target), "fetch", "--depth", "1", "origin", ref], check=True)
            subprocess.run([git, "-C", str(target), "checkout", "--detach", "FETCH_HEAD"], check=True)
        if name == "pydomino":
            subprocess.run(
                [git, "-C", str(target), "submodule", "update", "--init", "--recursive"], check=True
            )
        commit = subprocess.check_output([git, "-C", str(target), "rev-parse", "HEAD"], text=True).strip()
        if name in pinned and commit != pinned[name]["commit"]:
            raise SystemExit(
                f"{name}: checkout differs from source lock; inspect it before changing the lock"
            )
        lock[name] = {"url": url, "commit": commit}
        print(f"{name}: {commit}", flush=True)
    (ROOT / ".runtime").mkdir(exist_ok=True)
    (ROOT / ".runtime/sources.resolved.json").write_text(json.dumps(lock, indent=2) + "\n")


if __name__ == "__main__":
    main()
