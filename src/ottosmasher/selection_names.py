"""One naming policy for source and sample selections, without inference."""

from .asset_timeline import map_time


def suggest(db, source_id, asset, start, end, *, record=None, selection=None):
    if record is None:
        import json

        from .analysis_scope import covering
        from .ui_catalog import settings

        for backend in settings(db)["phone_model_order"]:
            measured = covering(db, asset, backend)
            if measured:
                payload = json.loads(measured["payload"])
                original = json.loads(measured["descriptor"])
                offset = original["start"] - asset["start"]
                mora = payload.get("mora", {})
                words = mora.get("words", {}) if mora.get("original_matches") else {}
                record = {
                    "analysis": {
                        "mora": mora,
                        "phones": [
                            {
                                **p,
                                "start": p["start"] + offset,
                                "end": p["end"] + offset,
                                "word_locator": words.get(str(p.get("mora_index"))),
                            }
                            for p in payload["phones"]
                        ],
                    }
                }
                break
    knots = asset.get("root_knots")
    if not knots:
        source = db.execute("SELECT title FROM sources WHERE id=?", (source_id,)).fetchone()
        return f"{source[0]} {start:.3f}–{end:.3f}"
    covered_start, covered_end = max(start, knots[0][0]), min(end, knots[-1][0])
    if covered_end <= covered_start:
        source = db.execute("SELECT title FROM sources WHERE id=?", (source_id,)).fetchone()
        return f"{source[0]} · 资产局部 {start:.3f}–{end:.3f}"
    lo, hi = map_time(knots, covered_start), map_time(knots, covered_end)
    if selection is not None:
        from .asset_timeline import annotations_for

        captions = [
            r["text"]
            for r in annotations_for(db, selection, kinds={"dialogue", "event", "song"})
            if r["text"].strip()
        ]
    else:
        from .asset_compat import active

        if active(db):
            from .timeline_labels import text_context

            captions = [r["original"] for r in text_context(db, source_id, lo, hi) if r["original"].strip()]
        else:
            captions = [
                r[0]
                for r in db.execute(
                    "SELECT original FROM cues WHERE source_id=? AND start<? AND end>? ORDER BY start,ordinal",
                    (source_id, hi, lo),
                )
                if r[0].strip()
            ]
    text = " / ".join(dict.fromkeys(captions))
    if record:
        phones = [p for p in record["analysis"]["phones"] if p["start"] < end and p["end"] > start]
        words = list(dict.fromkeys(p["word_locator"]["word"] for p in phones if p.get("word_locator")))
        if words:
            text = "".join(words)
        sequence = record["analysis"].get("mora", {}).get("sequence", [])
        indices = sorted(
            {
                p["mora_index"]
                for p in phones
                if isinstance(p.get("mora_index"), int) and p["mora_index"] < len(sequence)
            }
        )
        labels = (
            "".join(sequence[i] for i in indices)
            if indices
            else " ".join(p["label"] for p in phones if p["label"] not in {"pau", "SP", "sil"})
        )
        if text and labels:
            return f"{text} — {labels}"
    if text:
        return text
    source = db.execute("SELECT title FROM sources WHERE id=?", (source_id,)).fetchone()
    return f"{source[0]} {lo:.3f}–{hi:.3f}"
