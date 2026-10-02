from .source_locations import identity_descriptor

"""Timestamp-only manual versions: labels, order and mora IDs are immutable."""

import copy
import json
import math

from . import asset_timeline as timeline
from .workspace import identity


def export(db, mid, backend=None):
    from .materials import get
    from .sample_analysis import measurement
    from .sample_audio import resolve

    sample = get(db, mid)
    backend = backend or sample["active_phone_backend"]
    raw = measurement(db, sample, backend)
    if not raw or not raw.get("phones"):
        raise ValueError("没有可编辑的音素结果，请先完成 FA")
    asset = resolve(db, mid)
    head = db.execute(
        "SELECT a.*,r.revision FROM analysis_references r JOIN analysis_runs a ON a.id=r.run_id WHERE owner_type='sample' AND owner_id=? AND r.kind=?",
        (mid, backend),
    ).fetchone()
    if head and json.loads(head["payload"]).get("input_descriptor_signature") == identity(
        identity_descriptor(db, asset)
    ):
        raw = json.loads(head["payload"])
    else:
        head = None
    clock = raw.get("clock", "source")
    if clock == "asset":
        s = raw["input_selection"]
        bounds = [s["start"], s["end"]]
    else:
        bounds = [
            max(0, raw.get("window_start", min(p["start"] for p in raw["phones"]))),
            raw.get("window_end", max(p["end"] for p in raw["phones"])),
        ]
    revision = identity(
        "phone-times-v1", raw, identity(identity_descriptor(db, asset)), head["revision"] if head else 0
    )
    return {
        "schema": "otto.phone-times/1",
        "material_id": mid,
        "backend": backend,
        "base_version": revision,
        "clock": clock,
        "range": bounds,
        "text": "\n".join(f"{p['start']:.9f}\t{p['end']:.9f}\t{p['label']}" for p in raw["phones"]),
        "_raw": raw,
        "_head": dict(head) if head else None,
        "_asset_signature": identity(identity_descriptor(db, asset)),
    }


def document(db, mid, backend=None):
    return {k: v for k, v in export(db, mid, backend).items() if not k.startswith("_")}


def apply(db, doc):
    if (
        set(doc) != {"schema", "material_id", "backend", "base_version", "clock", "range", "text"}
        or doc["schema"] != "otto.phone-times/1"
    ):
        raise ValueError("无效音素时间文档")
    if db.in_transaction:
        raise ValueError("音素修订必须使用独立事务")
    with db:
        db.execute("BEGIN IMMEDIATE")
        current = export(db, doc["material_id"], doc["backend"])
        if any(doc[k] != current[k] for k in ("base_version", "clock", "range")):
            raise ValueError("音素版本或坐标已改变，请重新载入")
        lines = [line.split() for line in doc["text"].splitlines() if line.strip()]
        phones = copy.deepcopy(current["_raw"]["phones"])
        if len(lines) != len(phones):
            raise ValueError("仅允许修改时间，不允许增删音素")
        prior_end = current["range"][0]
        for i, (parts, phone) in enumerate(zip(lines, phones), 1):
            if len(parts) != 3 or parts[2] != phone["label"]:
                raise ValueError(f"第 {i} 行：音素标签和顺序不能改变")
            try:
                lo, hi = float(parts[0]), float(parts[1])
            except ValueError as e:
                raise ValueError(f"第 {i} 行：需要秒数") from e
            if (
                not all(math.isfinite(t) for t in (lo, hi))
                or not prior_end <= lo < hi <= current["range"][1] + 1e-8
            ):
                raise ValueError(f"第 {i} 行：时间越界、重叠或顺序错误")
            phone.update(start=lo, end=hi)
            prior_end = hi
        measured = {
            **current["_raw"],
            "phones": phones,
            "input_descriptor_signature": current["_asset_signature"],
            "manual_timing": True,
            "version": identity("manual-phone-times", current["base_version"], phones),
        }
        # Derived rhythm is recomputed from edited phones, never stale anchors.
        measured.pop("anchors", None)
        head = current["_head"]
        parent_id = (
            head["id"]
            if head
            else timeline.add_analysis(db, doc["backend"], identity(current["_raw"]), current["_raw"])
        )
        db.execute(
            "INSERT OR IGNORE INTO analysis_history VALUES('sample',?,?,?)",
            (doc["material_id"], doc["backend"], parent_id),
        )
        selection = (
            timeline.AssetSelection(**measured["input_selection"])
            if measured.get("clock") == "asset"
            else None
        )
        rid = timeline.add_analysis(
            db,
            doc["backend"],
            identity(measured),
            measured,
            selection=selection,
            human=True,
            parent_id=parent_id,
        )
        adopted = timeline.adopt_analysis(db, "sample", doc["material_id"], doc["backend"], rid)
        from .analysis_scope import publish

        cue = db.execute("SELECT cue_id FROM materials WHERE id=?", (doc["material_id"],)).fetchone()
        publish(db, rid, cue[0] if cue else None)
        db.execute(
            "DELETE FROM sample_records WHERE material_id=? AND backend=?",
            (doc["material_id"], doc["backend"]),
        )
    return {"run_id": rid, **adopted}


def versions(db, mid, backend):
    return [
        dict(r)
        for r in db.execute(
            "SELECT a.id,a.human,a.created,a.parent_id,(r.run_id=a.id) AS active FROM analysis_history h JOIN analysis_runs a ON a.id=h.run_id LEFT JOIN analysis_references r ON r.owner_type=h.owner_type AND r.owner_id=h.owner_id AND r.kind=h.kind WHERE h.owner_type='sample' AND h.owner_id=? AND h.kind=? ORDER BY a.created DESC",
            (mid, backend),
        )
    ]


def choose(db, mid, backend, run_id, base_revision):
    if not db.execute(
        "SELECT 1 FROM analysis_history WHERE owner_type='sample' AND owner_id=? AND kind=? AND run_id=?",
        (mid, backend, run_id),
    ).fetchone():
        raise ValueError("此分析版本不属于当前采样")
    from .sample_audio import resolve

    asset = resolve(db, mid)
    payload = json.loads(db.execute("SELECT payload FROM analysis_runs WHERE id=?", (run_id,)).fetchone()[0])
    signature = payload.get("input_descriptor_signature")
    if signature and signature != identity(identity_descriptor(db, asset)):
        raise ValueError("此版本使用了不同音源，只能作为来源参考")
    if not signature and asset.get("speech_analysis_eligible") is False:
        raise ValueError("旧版本没有当前处理后声音的测量身份，不能采用")
    with db:
        result = timeline.adopt_analysis(db, "sample", mid, backend, run_id, expected_revision=base_revision)
        if result["adopted"]:
            from .analysis_scope import publish

            cue = db.execute("SELECT cue_id FROM materials WHERE id=?", (mid,)).fetchone()
            publish(db, run_id, payload.get("annotation_id") or (cue[0] if cue else None))
            db.execute("DELETE FROM sample_records WHERE material_id=? AND backend=?", (mid, backend))
    return result
