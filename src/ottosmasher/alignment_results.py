"""Measured batch outputs, subtitle ownership and source-time projection."""

from __future__ import annotations

import hashlib
import json
import time
from functools import lru_cache
from pathlib import Path

import numpy as np
import soundfile as sf

from .backends import BACKENDS
from .rhythm_units import normalize_phone
from .workspace import DATA, command, connect, executable, get_cue, identity, save_analysis, write_json


@lru_cache(maxsize=1024)
def file_digest(path, size, modified):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def processing_provenance(item, kind, raw=None):
    from .workspace import ROOT

    references = {
        "phonetic": ["models/hubert/1218_hfa_model_new_dict/vocab.json"],
        "narabas": ["vendor/narabas/narabas/symbols.py"],
        "pydomino": ["vendor/pydomino/onnx_model/phoneme_transition_model.onnx"],
    }

    def digest(path):
        if not path.is_file():
            return None
        stat = path.stat()
        return file_digest(str(path), stat.st_size, stat.st_mtime_ns)

    sr = 16000
    input_path = Path(item[f"wav_{sr}"]) if item.get(f"wav_{sr}") else None
    return {
        "reference_files": {name: digest(ROOT / name) for name in references[kind]},
        "input_sample_rate": sr,
        "converted_audio_sha256": digest(input_path) if input_path else None,
        "audio_conversion": "FFmpeg mono PCM s16le resample from identical versioned pymss vocals",
        "phone_conversion": {
            "pydomino": "OpenJTalk phones; I/U to i/u; boundary pau; minimum 10 ms",
            "phonetic": "OpenJTalk I/U to i/u; omit cl/pau/sil; validate ja/ checkpoint vocabulary",
            "narabas": "OpenJTalk I/U to i/u; keep cl; pau between context cues; explicit BOS/EOS and CTC blank",
        }[kind],
    }


def target_phones(raw, item, kind):
    phones = raw["phones"]
    if kind == "pydomino":
        phones = [
            {
                **p,
                "raw_label": p["label"],
                "label": p["label"].lower() if p["label"] in {"I", "U"} else p["label"],
            }
            for p in phones
        ]
    expected = raw["phone_owners"]
    speech = [p for p in phones if p["label"] not in {"SP", "AP", "pau", "sil", "", "[BOS]", "[EOS]"}]
    if [p["label"] for p in speech] != [p["phone"] for p in expected]:
        raise ValueError("Output phone sequence differs from transcript; target ownership uncertain")
    owned = [
        {**p, "mora_index": e.get("mora_index"), "reading": e.get("reading")}
        for p, e in zip(speech, expected)
        if e["cue_id"] == item["id"]
    ]
    if not owned:
        raise ValueError("No target phones")
    # Retain measured silence inside the target, but not neighboring speech.
    return sorted(
        owned
        + [
            p
            for p in phones
            if p["label"] in {"SP", "AP", "pau", "sil", ""}
            and p["end"] > p["start"]
            and p["start"] >= owned[0]["start"]
            and p["end"] <= owned[-1]["end"]
        ],
        key=lambda p: p["start"],
    )


def import_result(folder, item, kind, raw):
    db = connect()
    cue = get_cue(db, item["id"])
    version = BACKENDS[kind]["version"]
    raw_id = identity(raw)
    provenance = processing_provenance(item, kind, raw)
    existing = db.execute(
        "SELECT payload FROM analyses WHERE cue_id=? AND kind=? AND version=?", (cue["id"], kind, version)
    ).fetchone()
    prior = {}
    if existing:
        prior = json.loads(existing[0])
        if (
            prior.get("raw_id") == raw_id
            and prior.get("import_version") == "context-import-v4"
            and prior.get("alignment_input_lineage") == item.get("audio_lineage")
        ):
            if prior.get("processing_provenance") != provenance:
                prior["processing_provenance"] = provenance
                save_analysis(db, item["id"], kind, version, prior)
            db.close()
            return prior
        write_json(DATA / "analysis-history" / (identity(prior) + ".json"), prior)
    payload = {
        "version": version,
        "input_variant": "vocals",
        "verified": False,
        "flags": ["unverified_alignment", "pymss_vocals", "vowel_start_is_anchor_heuristic"],
        "cohort": folder.name,
        "source_fingerprint": cue["fingerprint"],
        "backend": kind,
        "raw_output": str(folder / kind / item["id"] / "result.json"),
        "phones": [],
        "anchors": [],
        "window_start": cue["start"] - 0.65,
        "window_end": cue["end"] + 0.65,
        "runtime_seconds": raw.get("runtime_seconds"),
        "model_sha256": raw.get("model_sha256"),
        "model_release": raw.get("model_release"),
        "adapter_recipe": raw.get("recipe"),
        "probabilities_preserved": raw.get("probabilities_preserved"),
        "alignment_dictionary_sha256": raw.get("alignment_dictionary_sha256"),
        "generated_pronunciations": raw.get("generated_pronunciations"),
        "g2p": raw.get("g2p"),
        "alignment_input_lineage": item.get("audio_lineage"),
        "mora": raw.get("mora", {}).get(item["id"]),
        "created": time.time(),
        "raw_id": raw_id,
        "import_version": "context-import-v4",
        "dictionary_sha256": raw.get("dictionary_sha256"),
        "processing_provenance": provenance,
        "upstream": json.loads((folder.parents[2] / "dependencies/sources.lock.json").read_text())
        if (folder.parents[2] / "dependencies/sources.lock.json").exists()
        else None,
    }
    try:
        if raw.get("error"):
            raise ValueError(raw["error"])
        if item["source_fingerprint"] != cue["fingerprint"]:
            raise ValueError("Source changed since cohort preparation")
        relative = target_phones(raw, item, kind)
        if any(p["end"] <= p["start"] for p in relative):
            raise ValueError("Non-positive phone interval")
        origin = item["window_start"]
        phones = [{**p, "start": p["start"] + origin, "end": p["end"] + origin} for p in relative]
        from .boundaries import acoustic_crop, estimate_ctc_coverage

        start, end, evidence = acoustic_crop(item, phones, raw)
        payload["crop_evidence"] = evidence
        if kind == "narabas":
            payload["emission_phones"] = phones
            phones = estimate_ctc_coverage(phones, evidence)
        if evidence["uncertain_start"] or evidence["uncertain_end"]:
            payload["flags"].append("crop_boundary_uncertain")
        lineage = {
            **item["audio_lineage"],
            "parent_audio_sha256": item["audio_lineage"]["audio_sha256"],
            "target_cue_id": cue["id"],
            "window_start": start,
            "window_end": end,
            "crop_backend": kind,
            "crop_version": version,
        }
        crop = folder / kind / item["id"] / f"target-vocals-{version}-context-import-v3.wav"
        command(
            [
                executable("ffmpeg"),
                "-v",
                "error",
                "-y",
                "-ss",
                start - origin,
                "-t",
                end - start,
                "-i",
                item["audio_lineage"]["audio_path"],
                "-c:a",
                "pcm_s24le",
                crop,
            ]
        )
        lineage.update(audio_path=str(crop), audio_sha256=hashlib.sha256(crop.read_bytes()).hexdigest())
        y, sr = sf.read(crop, always_2d=True)
        anchors = []
        for p in phones:
            base = normalize_phone(p["label"])
            if base not in {"a", "i", "u", "e", "o", "N"}:
                continue
            piece = y[max(0, round((p["start"] - start) * sr)) : round((p["end"] - start) * sr)]
            anchors.append(
                {
                    "time": p["start"],
                    "duration": p["end"] - p["start"],
                    "phone": base,
                    "strength": float(np.sqrt(np.mean(piece**2))) if len(piece) else 0,
                    "pitch_midi": None,
                }
            )
        peak = max((p["strength"] for p in anchors), default=1) or 1
        for p in anchors:
            p["strength"] /= peak
        payload.update(
            phones=phones,
            anchors=anchors,
            audio_lineage=lineage,
            window_start=start,
            window_end=end,
            waveform=[float(np.max(np.abs(chunk))) for chunk in np.array_split(y, min(180, len(y)))],
        )
        if any(p["end"] - p["start"] < 0.02 for p in phones if p["label"] not in {"SP", "pau", "AP"}):
            payload["flags"].append("very_short_phones")
        if any(p["label"] == "spn" for p in phones):
            payload["flags"].append("unknown_phone_spn")
    except Exception as exc:  # noqa: BLE001 - retain per-cue failures
        payload.update(error=str(exc), flags=["alignment_failed"], phones=[], anchors=[])
    if prior.get("reference_settings"):
        payload["reference_settings"] = prior["reference_settings"]
    if prior.get("manual_crop") and payload.get("phones"):
        from .manual_crop import apply_crop

        try:
            payload = apply_crop(payload, *prior["manual_crop"])
        except ValueError:
            payload["flags"].append("previous_manual_crop_needs_review")
    save_analysis(db, item["id"], kind, version, payload)
    db.close()
    return payload
