"""Project cached source acoustic frames onto each backend's current rhythm groups."""

from ottosmasher.rhythm_index import _rows, ensure_record
from ottosmasher.sound_features import record_features
from ottosmasher.workspace import connect

with connect() as db:
    for kind in ("narabas", "phonetic", "pydomino"):
        count = 0
        for row in _rows(db, kind):
            record, _ = ensure_record(db, row, kind)
            count += len(record_features(record))
        print(f"{kind}: {count} projected units", flush=True)
