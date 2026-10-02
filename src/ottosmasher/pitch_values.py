"""Shared human pitch notation for flattening and F0 queries."""

import math
import re


def midi(value):
    if isinstance(value, str):
        match = re.fullmatch(r"([A-Ga-g])([#♯b♭]?)(-?\d+)", value.strip())
        if not match:
            raise ValueError("音高应为音符（如 F#5）或 MIDI 数值")
        name, accidental, octave = match.groups()
        value = (
            (int(octave) + 1) * 12
            + {"C": 0, "D": 2, "E": 4, "F": 5, "G": 7, "A": 9, "B": 11}[name.upper()]
            + {"": 0, "#": 1, "♯": 1, "b": -1, "♭": -1}[accidental]
        )
    if (
        isinstance(value, bool)
        or not isinstance(value, (int, float))
        or not math.isfinite(value)
        or not 0 <= value <= 127
    ):
        raise ValueError("MIDI 音高须为 0–127 的有限数")
    return float(value)


def note(value):
    value = midi(value)
    rounded = math.floor(value + 0.5)
    names = ("C", "C♯", "D", "D♯", "E", "F", "F♯", "G", "G♯", "A", "A♯", "B")
    cents = round((value - rounded) * 100)
    return {
        "midi": value,
        "hz": 440 * 2 ** ((value - 69) / 12),
        "name": names[rounded % 12] + str(rounded // 12 - 1) + (f"{cents:+d}c" if cents else ""),
    }
