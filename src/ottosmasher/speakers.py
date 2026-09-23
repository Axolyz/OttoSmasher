import itertools
import re


def single_speaker(name):
    return name if name and not re.search(r"[･・＆&、,／/]|一同|全員|[０-９0-9]+人", name) else None


def labels_for_units(db, cue, units):
    rows = db.execute(
        "SELECT * FROM speaker_annotations WHERE source_id=? ORDER BY created DESC", (cue["source_id"],)
    ).fetchall()
    result = []
    for unit in units:
        a, b = unit["time"], unit.get("end", unit["time"])
        cuts = sorted({a, b, *[max(a, min(b, r[k])) for r in rows for k in ("start", "end")]})
        parts = []
        for lo, hi in itertools.pairwise(cuts):
            if hi <= lo:
                continue
            mid = (lo + hi) / 2
            row = next((r for r in rows if r["start"] <= mid < r["end"]), None)
            parts.append(
                (row["speaker"], "manual") if row else (single_speaker(cue.get("speaker")), "subtitle")
            )
        names = {p[0] for p in parts}
        name = next(iter(names)) if len(names) == 1 else None
        result.append(
            {
                "speaker": name,
                "speaker_source": "manual"
                if name and any(p[1] == "manual" for p in parts)
                else "subtitle"
                if name
                else "unknown",
            }
        )
    return result
