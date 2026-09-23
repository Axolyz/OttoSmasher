"""Explicit local-backend jobs for new text-bearing speech; no ASR fallback."""




def analyze(mid, retry=False, backends=None, vocal_model="becruily_deux"):
    from .alignment_batch import run

    row = run([mid], backends or ["narabas"], vocal_model)[0]
    if row.get("error"):
        raise ValueError(row["error"])
    return row["stages"]


def attach_text(db, mid, text):
    from .catalog import normalize, reading_text
    from .materials import get
    from .workspace import identity

    r = get(db, mid)
    text = text.strip()
    if not text:
        raise ValueError("台词文本不能为空")
    if r["cue_id"]:
        raise ValueError("该采样已有固定原句；不能覆盖原始文本版本")
    cid = identity("imported-transcript-v1", r["source_id"], r["start"], r["end"], text)
    ordinal = db.execute(
        "SELECT coalesce(max(ordinal),0)+1 FROM cues WHERE source_id=?", (r["source_id"],)
    ).fetchone()[0]
    db.execute(
        "INSERT OR IGNORE INTO cues VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
        (
            cid,
            r["source_id"],
            ordinal,
            r["start"],
            r["end"],
            text,
            text,
            normalize(text),
            reading_text(text),
            None,
            "speech",
            "[]",
        ),
    )
    db.execute("UPDATE materials SET cue_id=?,active_phone_backend='narabas' WHERE id=?", (cid, mid))
    db.commit()
