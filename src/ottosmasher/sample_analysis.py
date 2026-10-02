"""Material-local analysis projections. Inference is never part of retrieval."""

import copy
import itertools
import json
import zlib
from functools import lru_cache
from pathlib import Path

import numpy as np

from .source_locations import identity_descriptor
from .sample_catalog import BACKENDS
from .workspace import get_cue, get_speech_analysis, identity

VERSION = "sample-local-v5"


def words(cue, a):
    if (a.get("mora") or {}).get("source") == "openjtalk-plus-tsqyomi-v1":
        return (
            {int(k): v for k, v in a["mora"].get("words", {}).items()}
            if a["mora"].get("original_matches", True)
            else {}
        )
    import unicodedata

    from .catalog import SUDACHI, SplitMode

    text = cue["spoken"]
    tokens = list(SUDACHI.tokenize(text, SplitMode.C))

    def clean(s):
        s = unicodedata.normalize("NFKC", s)
        return "".join(
            chr(ord(c) + 96) if "ぁ" <= c <= "ゖ" else c
            for c in s
            if "ぁ" <= c <= "ゖ" or "ァ" <= c <= "ヺ" or c == "ー"
        )

    def canonical(s):
        groups = {
            "ア": "アァカガサザタダナハバパマヤャラワヮ",
            "イ": "イィキギシジチヂニヒビピミリヰ",
            "ウ": "ウゥクグスズツヅヌフブプムユュルヴ",
            "エ": "エェケゲセゼテデネヘベペメレヱ",
            "オ": "オォコゴソゾトドノホボポモヨョロヲ",
        }
        vowel = {c: v for v, chars in groups.items() for c in chars}
        out = []
        last = None
        for c in clean(s):
            if c == "ー" and last:
                c = last
            if c == "ウ" and last == "オ":
                c = "オ"
            if c == "イ" and last == "エ":
                c = "エ"
            out.append(c)
            last = vowel.get(c)
        return "".join(out)

    sequence = (a.get("mora") or {}).get("sequence", [])
    if canonical("".join(t.reading_form() for t in tokens)) != canonical("".join(sequence)):
        return {}

    mapping = {}
    offset = 0
    for token in tokens:
        stop = offset + len(clean(token.reading_form()))
        for i in range(len(sequence)):
            x = len(clean("".join(sequence[:i])))
            y = x + len(clean(sequence[i]))
            if offset <= x and y <= stop:
                mapping[i] = {
                    "word": token.surface(),
                    "text_range": [token.begin(), token.end()],
                    "reading": token.reading_form(),
                }
        offset = stop
    return mapping


def signature(r, asset, analysis, db=None):
    from .rhythm_index import index_version
    from .ui_catalog import settings

    penalty = settings(db)["large_number_penalty"] if db is not None else 1.0
    return identity(
        VERSION, "vowel-acoustic-bounds-v1", index_version(), asset, analysis, r["analysis_settings"], penalty
    )


def build(db, mid, kind):
    import soundfile as sf

    from .beat_reference import compile_reference
    from .materials import get, sha256
    from .rhythm_units import _view
    from .sample_audio import pcm, resolve
    from .sound_features import asset_path, project

    r = get(db, mid)
    if kind not in BACKENDS:
        raise ValueError("没有对应文本和可继承音素分析")
    a = measurement(db, r, kind)
    if not a or not a.get("phones"):
        raise ValueError("此模型尚无成功音素结果")
    asset = resolve(db, mid)
    if asset.get("speech_analysis_eligible") is False and not a.get("_measured_current_asset"):
        raise ValueError("声音内容经过分离处理，原句音素仅保留来源，不能当作当前声音的测量")
    sig = signature(r, asset, a, db)
    existing = db.execute(
        "SELECT * FROM sample_records WHERE material_id=? AND backend=?", (mid, kind)
    ).fetchone()
    if existing and existing["signature"] == sig:
        return decode_record(existing["payload"])
    path = pcm(asset)
    info = sf.info(path)
    duration = info.duration
    digest = sha256(path)
    knots = asset.get("root_knots") or [[0, r["start"]], [duration, r["end"]]]
    local, root = np.asarray(knots).T

    def to_local(t):
        return float(np.interp(t, root, local))

    annotation_id = r.get("cue_id") or a.get("annotation_id")
    if not annotation_id:
        raise ValueError("当前测量没有对应文字区段")
    try:
        source_cue = get_cue(db, annotation_id)
    except ValueError:
        annotation = db.execute(
            "SELECT * FROM timeline_annotations WHERE id=? AND deleted=0", (annotation_id,)
        ).fetchone()
        if not annotation:
            raise ValueError("对应文字区段不存在")
        source = dict(db.execute("SELECT * FROM sources WHERE id=?", (r["source_id"],)).fetchone())
        from .subtitle_speakers import spoken_text

        source_cue = {
            **source,
            **dict(annotation),
            "id": annotation_id,
            "original": annotation["text"],
            "spoken": spoken_text(annotation["text"]),
            "source_duration": source["duration"],
            "source_id": r["source_id"],
        }
    word_map = words(source_cue, a)
    phones = []
    for i, original in enumerate(a["phones"]):
        if original["end"] <= root[0] or original["start"] >= root[-1]:
            continue
        p = copy.deepcopy(original)
        p["root_phone_index"] = i
        p["root_phone_id"] = identity(annotation_id, kind, a["version"], identity(a["phones"]), i)
        p["root_interval"] = [p["start"], p["end"]]
        p["partial"] = bool(p["start"] < root[0] or p["end"] > root[-1])
        p["start"], p["end"] = to_local(p["start"]), to_local(p["end"])
        if p["end"] <= p["start"]:
            continue
        for field in ("emission_start", "emission_end"):
            if field in p:
                p["root_" + field] = p[field]
                p[field] = to_local(p[field])
        p["word_locator"] = word_map.get(p.get("mora_index"))
        p["onset_origin"] = "edit_boundary" if original["start"] < root[0] else "inherited_model"
        phones.append(p)
    if not phones:
        raise ValueError("选区没有可继承音素")
    la = copy.deepcopy(a)
    la.update(version=VERSION + "-" + sig, window_start=0, window_end=duration, phones=phones, backend=kind)
    la["anchors"] = [
        {**p, "time": to_local(p["time"]), "end": to_local(p.get("end", p["time"]))}
        for p in a.get("anchors", [])
        if root[0] <= p["time"] < root[-1]
    ]
    indices = [p.get("mora_index") for p in phones if isinstance(p.get("mora_index"), int)]
    if indices:
        first, last = min(indices), max(indices) + 1
        seq = la.get("mora", {}).get("sequence", [])[first:last]
        la["mora"] = {
            **la.get("mora", {}),
            "sequence": seq,
            "count": len(seq),
            "reading": "".join(seq),
            "parent_range": [first, last],
        }
        for p in phones:
            if isinstance(p.get("mora_index"), int):
                p["mora_index"] -= first
    cue = {
        **source_cue,
        "id": mid,
        "path": str(path),
        "fingerprint": digest,
        "audio_stream": 0,
        "start": 0,
        "end": duration,
        "source_duration": duration,
        "spoken": r["title"],
    }
    la["audio_selection"] = None
    la["audio_lineage"] = {
        "audio_path": str(path),
        "audio_sha256": digest,
        "source_fingerprint": digest,
        "window_start": 0,
        "window_end": duration,
        "target_cue_id": mid,
        "input_variant": "vocals",
        "source_variant": asset["role"],
        "processing_ancestry": asset.get("provenance"),
    }
    settings = {**r["analysis_settings"].get("backend_settings", {}).get(kind, {}), **r["analysis_settings"]}
    view = copy.deepcopy(
        _view(json.dumps(la), tuple(settings.get("split_before", [])), settings.get("pause_sensitivity", 1))
    )
    if not view["units"]:
        raise ValueError("此选区没有可量化的元音起点")
    scopes = []
    cuts = (
        [0]
        + [i for i, u in enumerate(view["units"]) if i and u["phrase"] != view["units"][i - 1]["phrase"]]
        + [len(view["units"])]
    )
    for lo, hi in itertools.pairwise(cuts):
        scopes.append({"parent_unit_indices": list(range(lo, hi))})
    frames = None
    feature_path = Path(asset["path"]).with_suffix(".features.json") if asset.get("path") else None
    if path.with_suffix(".features.json").exists():
        feature_path = path.with_suffix(".features.json")
    if feature_path and feature_path.exists():
        raw = json.loads(feature_path.read_text())
        frames = {k: np.asarray(raw[k]) for k in ("times", "f0_hz", "voiced", "energy", "confidence")}
        frames["times"] -= 0 if feature_path == path.with_suffix(".features.json") else asset["start"]
    elif asset["role"] == "vocals":
        fp = asset_path(a["audio_lineage"])
        if fp.exists():
            raw = json.loads(fp.read_text())
            frames = {k: np.asarray(raw[k]) for k in ("times", "f0_hz", "voiced", "energy", "confidence")}
            times = frames["times"] + raw["source_window_start"]
            mask = (times >= root[0]) & (times <= root[-1])
            frames = {k: v[mask] for k, v in frames.items()}
            frames["times"] = np.interp(times[mask], root, local)
    if frames is None:
        from .boundaries import energy_frames

        t, rms, _ = energy_frames(str(path), 0)
        frames = {
            "times": t,
            "energy": rms**2,
            "f0_hz": np.zeros(len(t)),
            "confidence": np.zeros(len(t)),
            "voiced": np.zeros(len(t), dtype=bool),
        }
    frame_mask = (frames["times"] >= 0) & (frames["times"] < duration)
    frames = {k: v[frame_mask] for k, v in frames.items()}
    from .vowel_bounds import annotate

    annotate(la["phones"], frames, manual=bool(a.get("human") or a.get("manual") or a.get("manual_timing")))
    features = project(
        view["units"],
        scopes,
        frames,
        0,
        view["pauses"],
        manual=bool(a.get("human") or a.get("manual_timing")),
    )
    from .ui_catalog import settings as global_settings

    penalty = global_settings(db)["large_number_penalty"]
    compiled = compile_reference(
        cue,
        la,
        view,
        settings.get("slots", {}),
        settings.get("auto_long_vowels", False),
        large_number_penalty=penalty,
    )
    from .rhythm_scopes import list_scopes, scope_context

    descriptors = list_scopes(cue, la, view, settings.get("segments", {}))
    record = {
        "cue": cue,
        "analysis": la,
        "view": view,
        "compiled": compiled,
        "scope": descriptors[0],
        "features": features,
        "frames": {k: v.tolist() for k, v in frames.items()},
        "signature": sig,
        "asset": asset,
        "root_cue": source_cue,
        "backend": kind,
    }
    entries = []
    for descriptor in descriptors[1:]:
        aa, vv = scope_context(cue, la, view, descriptor)
        indices = descriptor["parent_unit_indices"]
        overrides = {
            str(i): settings["slots"][str(j)]
            for i, j in enumerate(indices)
            if str(j) in settings.get("slots", {})
        }
        cc = compile_reference(
            cue, aa, vv, overrides, settings.get("auto_long_vowels", False), large_number_penalty=penalty
        )
        entries.append(
            {
                **{k: v for k, v in record.items() if k not in ("frames",)},
                "scope": descriptor,
                "analysis": aa,
                "view": vv,
                "compiled": cc,
                "overrides": overrides,
                "features": [features[i] for i in indices],
            }
        )
    record["entries"] = entries
    db.execute(
        "INSERT OR REPLACE INTO sample_records VALUES(?,?,?,?)",
        (mid, kind, sig, encode_record(record)),
    )
    db.commit()
    return record


def encode_record(record):
    return zlib.compress(
        json.dumps(record, ensure_ascii=False, allow_nan=False, separators=(",", ":")).encode(), 3
    )


def decode_record(payload):
    return json.loads(zlib.decompress(payload) if isinstance(payload, bytes) else payload)


@lru_cache(maxsize=24)
def _decoded_record(payload):
    return decode_record(payload)


def ready(db, mid, kind=None, *, materialize=True):
    from .materials import playback_record

    r = playback_record(db, mid)
    if isinstance(r["analysis_settings"], str):
        r["analysis_settings"] = json.loads(r["analysis_settings"])
    kind = kind or r["active_phone_backend"]
    row = db.execute(
        "SELECT payload FROM sample_records WHERE material_id=? AND backend=?", (mid, kind)
    ).fetchone()
    if not row:
        raise ValueError("该采样的局部分析尚未准备，请先重建分析")
    record = copy.deepcopy(_decoded_record(row[0]))
    a = measurement(db, r, kind)
    from .sample_audio import resolve

    if not a or record["signature"] != signature(r, resolve(db, mid), a, db):
        raise ValueError("局部分析已过期，请重建")
    if materialize:
        from .sample_audio import pcm

        bind_pcm(record, pcm(record["asset"]))
    return record


def bind_pcm(record, path):
    """Bind disposable playback input without changing stored measurement identity."""
    from .materials import sha256
    from .rhythm_scopes import SELECTION_VERSION

    digest = sha256(path)
    for entry in [record, *record.get("entries", [])]:
        entry["cue"].update(path=str(path), fingerprint=digest, audio_stream=0)
        lineage = entry["analysis"]["audio_lineage"]
        lineage.update(
            audio_path=str(path),
            audio_sha256=digest,
            source_fingerprint=digest,
            audio_start=0,
            audio_end=lineage["window_end"] - lineage["window_start"],
        )
        selection = entry["analysis"].get("audio_selection")
        if selection:
            selection.update(source_fingerprint=digest, audio_sha256=digest)
            selection["selection_id"] = identity(
                SELECTION_VERSION, {k: v for k, v in selection.items() if k != "selection_id"}
            )


def display_ready(db, mid):
    """Rebuild a missing disposable projection from existing measurements only."""
    try:
        return ready(db, mid, materialize=False)
    except ValueError as error:
        if str(error) not in ("该采样的局部分析尚未准备，请先重建分析", "局部分析已过期，请重建"):
            raise
        from .materials import playback_record

        build(db, mid, playback_record(db, mid)["active_phone_backend"])
        return ready(db, mid, materialize=False)


def prepare(db, mid):
    result = {}
    for kind in BACKENDS:
        try:
            result[kind] = {"status": "ready", "signature": build(db, mid, kind)["signature"]}
        except (ValueError, OSError, KeyError) as e:
            result[kind] = {
                "status": "missing" if str(e) == "此模型尚无成功音素结果" else "failed",
                "error": str(e),
            }
            db.execute("DELETE FROM sample_records WHERE material_id=? AND backend=?", (mid, kind))
        db.execute(
            "INSERT OR REPLACE INTO sample_analysis_status VALUES(?,?,?,?)",
            (mid, kind, result[kind]["status"], result[kind].get("error")),
        )
        db.commit()
    return result


def measurement(db, sample, kind):
    current = db.execute(
        "SELECT a.* FROM analysis_references r JOIN analysis_runs a ON a.id=r.run_id WHERE r.owner_type='sample' AND r.owner_id=? AND r.kind=?",
        (sample["id"], kind),
    ).fetchone()
    if current:
        from .reanalysis import compatible_payload
        from .sample_audio import resolve

        raw = json.loads(current["payload"])
        if raw.get("input_descriptor_signature") == identity(
            identity_descriptor(db, resolve(db, sample["id"]))
        ):
            return compatible_payload(db, current)
    from .analysis_scope import covering
    from .sample_audio import resolve
    from .reanalysis import compatible_payload

    try:
        shared = covering(db, resolve(db, sample["id"]), kind)
    except (ValueError, OSError):
        shared = None
    if shared:
        return compatible_payload(db, shared)
    row = db.execute(
        "SELECT payload FROM sample_measurements WHERE material_id=? AND backend=?", (sample["id"], kind)
    ).fetchone()
    if row:
        value = json.loads(row[0])
        if not value.get("input_descriptor_signature") or value["input_descriptor_signature"] == identity(
            identity_descriptor(db, resolve(db, sample["id"]))
        ):
            return value
    if not sample.get("cue_id"):
        return None
    raw = get_speech_analysis(db, sample["cue_id"], kind)
    return raw
