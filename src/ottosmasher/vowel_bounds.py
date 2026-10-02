"""Conservative acoustic selection bounds, never a replacement for FA measurements."""

import numpy as np

VERSION = "vowel-acoustic-bounds-v1"
VOWELS = {"a", "i", "u", "e", "o", "I", "U", "N"}


def bounds(start, end, times, energy, *, manual=False, hop=0.01):
    if manual:
        return [start, end]
    times, energy = np.asarray(times), np.asarray(energy)
    mask = (times >= start) & (times < end)
    if mask.sum() < 4:
        return [start, end]
    t, e = times[mask], energy[mask]
    peak = float(np.quantile(e, 0.85))
    if not np.isfinite(peak) or peak <= 1e-10:
        return [start, end]
    active = np.flatnonzero(e > max(1e-10, peak * 0.0064))
    if len(active) < 3:
        return [start, end]
    lo, hi = float(t[active[0]] - hop / 2), float(t[active[-1]] + hop / 2)
    # Require >=30 ms quiet at an edge, and retain a 10 ms guard.
    lo = max(start, lo - 0.01) if lo - start >= 0.03 else start
    hi = min(end, hi + 0.01) if end - hi >= 0.03 else end
    return [lo, hi] if hi - lo >= 0.03 else [start, end]


def annotate(phones, frames, *, manual=False):
    from .rhythm_units import normalize_phone

    for phone in phones:
        if normalize_phone(phone["label"]) not in VOWELS:
            continue
        lo, hi = bounds(
            phone["start"],
            phone["end"],
            frames["times"],
            frames["energy"],
            manual=manual or bool(phone.get("human")),
        )
        phone.update(effective_start=lo, effective_end=hi, effective_version=VERSION)
    return phones
