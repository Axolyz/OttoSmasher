"""Bounded correspondence search with a continuous, renderable timing witness."""

from __future__ import annotations

import numpy as np


def map_time(t, mapping):
    if mapping.get("knots"):
        return float(np.interp(t, [k[0] for k in mapping["knots"]], [k[1] for k in mapping["knots"]]))
    value = (t - mapping["origin_seconds"]) * mapping["factor"] + mapping["offset_seconds"]
    for p in mapping["pauses"]:
        fraction = min(1.0, max(0.0, (t - p["start"]) / (p["end"] - p["start"])))
        value += fraction * (p["target_duration"] - (p["end"] - p["start"]) * mapping["factor"])
    return float(value)
