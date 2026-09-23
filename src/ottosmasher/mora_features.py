"""Text mora correspondence; never a timing measurement."""
from itertools import pairwise


def mora_features(analysis, units, reading=""):
    data = analysis.get("mora")
    if not data:
        seq = []
        for c in reading:
            if c in "ゃゅょぁぃぅぇぉゎャュョァィゥェォヮ" and seq:
                seq[-1] += c
            elif "\u3041" <= c <= "\u3096" or "\u30a1" <= c <= "\u30fa" or c == "ー":
                seq.append(c)
        data = {
            "reading": reading,
            "sequence": seq,
            "count": len(seq),
            "source": "catalog reading; no measured mora times",
            "phone_mapping": "unavailable",
        }
    counts = []
    first_indices = []
    for u in units:
        indices = {m.get("mora_index") for m in u.get("members", []) if m.get("mora_index") is not None}
        counts.append(len(indices) if indices else None)
        first_indices.append(min(indices) if indices else None)
    interval_counts = [
        b - a if a is not None and b is not None and b > a else None for a, b in pairwise(first_indices)
    ]
    return {
        **data,
        "unit_counts": counts,
        "interval_mora_counts": interval_counts,
        "used_as": "weak prior only; long vowels remain grouped",
    }
