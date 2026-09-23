"""Verify installed model assets against the recorded first working environment."""

import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def main():
    lock = json.loads((ROOT / "dependencies/models.lock.json").read_text())
    checked = 0
    for relative, entry in lock.items():
        path = ROOT / relative
        if not path.exists() and relative.startswith("models/separation/"):
            print(f"Optional separation asset not downloaded: {relative}")
            continue
        if not path.exists() or hashlib.sha256(path.read_bytes()).hexdigest() != entry["sha256"]:
            raise SystemExit(f"Model missing or differs from lock: {relative}")
        checked += 1
    print(f"Verified {checked} model assets")


if __name__ == "__main__":
    main()
