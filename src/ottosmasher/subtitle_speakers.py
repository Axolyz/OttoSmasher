"""Subtitle assertions, kept separate from measured speaker boundaries."""

import json
import re
import unicodedata

VERSION = "subtitle-speakers-v1"
EVENT = re.compile(
    r"(?:音$|声$|息$|呼吸|足音|拍手|悲鳴|笑い|泣き|あくび|寝息|鳴き|せき|咳|ため息|ドア|扉|ナレーション)"
)


def annotations(text):
    plain = text.replace("（", "(").replace("）", ")")
    depth = 0
    start = None
    out = []
    for i, c in enumerate(plain):
        if c == "(":
            if depth == 0:
                start = i
            depth += 1
        elif c == ")" and depth:
            depth -= 1
            if depth == 0:
                out.append((start, i + 1, plain[start + 1 : i]))
    return out


def spoken_text(text):
    out = text
    for a, b, _ in reversed(annotations(text)):
        out = out[:a] + out[b:]
    return out.strip()


def extract(text):
    plain = re.sub(r"\{[^}]*\}|<[^>]*>", "", text.replace("\\N", "\n"))
    marks = annotations(plain)
    turns = []
    for i, (start, end, name) in enumerate(marks):
        name = unicodedata.normalize("NFKC", spoken_text(name)).strip()
        if not name or len(name) > 30 or EVENT.search(name):
            continue
        # Mid-sentence reading glosses are not speaker names.
        if i == 0 and plain[:start].strip():
            continue
        following = plain[end : marks[i + 1][0] if i + 1 < len(marks) else len(plain)].strip()
        if not spoken_text(following):
            continue
        names = [v.strip() for v in re.split(r"[・＆&、/／]", name) if v.strip()]
        group = any(
            v.endswith(("たち", "達", "一同", "全員")) or re.fullmatch(r"[0-9一二三四五六七八九十]+人", v)
            for v in names
        )
        turns.append(
            {
                "names": names,
                "text": following,
                "text_span": [
                    end,
                    end + len(plain[end : marks[i + 1][0] if i + 1 < len(marks) else len(plain)]),
                ],
                "group": group,
            }
        )
    names = list(dict.fromkeys(n for t in turns for n in t["names"]))
    status = (
        "single"
        if len(names) == 1 and not any(t["group"] for t in turns)
        else "multiple_or_group"
        if names
        else "none"
    )
    return {
        "version": VERSION,
        "names": names,
        "turns": turns,
        "status": status,
        "timing": "unknown",
        "confirmed": False,
        "source": "subtitle",
    }


def ensure(db):
    db.execute("CREATE TABLE IF NOT EXISTS subtitle_speakers(cue_id TEXT PRIMARY KEY,payload TEXT NOT NULL)")


def record(db, cue_id, text):
    ensure(db)
    doc = extract(text)
    db.execute(
        "INSERT OR REPLACE INTO subtitle_speakers VALUES(?,?)", (cue_id, json.dumps(doc, ensure_ascii=False))
    )
    return doc
