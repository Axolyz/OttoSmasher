"""Legacy persisted-reference validation; search allocation lives in rhythm_allocation."""

import json
import re

from .workspace import DATA, identity

VERSION = "retired-query-quantization"


def load_plan(plan_id, cue_id, analysis, view):
    if not re.fullmatch("[a-f0-9]{24}", plan_id):
        raise ValueError("Invalid plan id")
    path = DATA / "quantization-plans" / (plan_id + ".json")
    if not path.exists():
        raise ValueError("Plan missing; regenerate")
    plan = json.loads(path.read_text())
    if (
        plan.get("version") not in {"binary-reference-v5"}
        or plan["cue_id"] != cue_id
        or plan["analysis_id"] != identity(analysis)
        or plan["rhythm_id"] != identity(view)
    ):
        raise ValueError("Analysis or rhythm groups changed; regenerate strict plans")
    return plan
