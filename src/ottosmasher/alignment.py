from __future__ import annotations
from .workspace import CODE_ROOT

import hashlib
import json
import time

import numpy as np
from praatio import textgrid

from .analysis import acoustic_features
from .vocals import prepare_vocals, read_aligned_input
from .workspace import DATA, ROOT, command, connect, get_cue, identity, save_analysis, set_job, write_json

VERSION = "hubert-onnx-v2-vocals"
MODEL = ROOT / "models/hubert/1218_hfa_model_new_dict/model.onnx"



def prepare_hubert(limit=24):
    db = connect()
    # All subtitle events count as neighbors: stage directions may be audible too.
    rows = db.execute(
        """WITH ordered AS (
        SELECT c.*,lag(end) OVER(PARTITION BY source_id ORDER BY ordinal) AS prev_end,
          lead(start) OVER(PARTITION BY source_id ORDER BY ordinal) AS next_start,
          row_number() OVER(PARTITION BY source_id ORDER BY ordinal) AS pos
        FROM cues c)
        SELECT * FROM ordered c WHERE kind='dialogue' AND end-start BETWEEN 1 AND 7
        AND length(spoken) BETWEEN 5 AND 65 AND instr(spoken,char(10))=0
        AND (prev_end IS NULL OR start-prev_end>=1.0)
        AND (next_start IS NULL OR next_start-end>=1.0)
        AND NOT EXISTS (SELECT 1 FROM analyses a WHERE a.cue_id=c.id AND a.kind='phonetic' AND a.version=?)
        ORDER BY pos,source_id LIMIT ?""",
        (VERSION, limit),
    ).fetchall()
    if not rows:
        db.close()
        return None
    folder = DATA / "alignment" / identity(VERSION, [r["id"] for r in rows])
    folder.mkdir(parents=True, exist_ok=True)
    manifest = {
        "backend": "HubertFA",
        "version": VERSION,
        "verified": False,
        "cues": [],
        "model": str(MODEL),
        "model_sha256": hashlib.sha256(MODEL.read_bytes()).hexdigest(),
        "upstream": json.loads((CODE_ROOT / "dependencies/sources.lock.json").read_text()),
        "input_variant": "vocals",
        "selection": "1-7s single-line dialogue; >=1s subtitle gaps; pymss vocals separated with extra context",
    }
    cues = [get_cue(db, row["id"]) for row in rows]
    vocals = prepare_vocals(cues)
    for cue in cues:
        lineage = vocals[cue["id"]]
        start, end = lineage["window_start"], lineage["window_end"]
        from .workspace import executable

        command(
            [
                executable("ffmpeg"),
                "-v",
                "error",
                "-nostdin",
                "-y",
                "-i",
                lineage["audio_path"],
                "-ac",
                "1",
                "-ar",
                "16000",
                "-c:a",
                "pcm_s16le",
                folder / (cue["id"] + ".wav"),
            ]
        )
        manifest["cues"].append(
            {
                "id": cue["id"],
                "spoken": cue["spoken"],
                "window_start": start,
                "window_end": end,
                "source_fingerprint": cue["fingerprint"],
                "source_id": cue["source_id"],
                "subtitle_start": cue["start"],
                "subtitle_end": cue["end"],
                "input_variant": "vocals",
                "audio_lineage": lineage,
            }
        )
        set_job(db, identity(cue["id"], VERSION), cue["id"], VERSION, "prepared")
    write_json(folder / "source.json", manifest)
    db.close()
    return folder


def import_hubert(folder):
    manifest = json.loads((folder / "prepared.json").read_text())
    if manifest.get("input_variant") != "vocals":
        raise ValueError("HubertFA production import requires separated vocals")
    db = connect()
    results = {"completed": 0, "failed": []}
    for item in manifest["cues"]:
        cue_id = item["id"]
        try:
            tg_path = folder / "TextGrid" / (cue_id + ".TextGrid")
            tg = textgrid.openTextgrid(str(tg_path), includeEmptyIntervals=False)
            origin = item["window_start"]
            phones = [
                {"start": origin + a, "end": origin + b, "label": label}
                for a, b, label in tg.getTier("phones").entries
            ]
            if not phones or any(p["end"] <= p["start"] for p in phones):
                raise ValueError("Empty or invalid phone intervals")
            cue = get_cue(db, cue_id)
            if cue["fingerprint"] != item["source_fingerprint"]:
                raise ValueError("Source changed since alignment preparation")
            y, sr, _, _ = read_aligned_input(item)
            energies = []
            anchors = []
            for p in phones:
                # Vowel starts are an explicit first anchor heuristic, not mora/P-center truth.
                if p["label"] not in {"a", "i", "u", "e", "o", "N"}:
                    continue
                a, b = round((p["start"] - origin) * sr), round((p["end"] - origin) * sr)
                energy = float(np.sqrt(np.mean(y[max(0, a) : min(len(y), b)] ** 2))) if b > a else 0
                energies.append(energy)
                anchors.append(
                    {
                        "time": p["start"],
                        "duration": p["end"] - p["start"],
                        "phone": p["label"],
                        "strength": energy,
                        "pitch_midi": None,
                        "kind": "aligned_vowel_start",
                    }
                )
            peak = max(energies, default=1) or 1
            for a in anchors:
                a["strength"] = a["strength"] / peak
            flags = [
                "unverified_alignment",
                "pymss_vocals",
                "separation_artifacts_possible",
                "vowel_start_is_anchor_heuristic",
                "automatic_reading",
            ]
            if item["g2p"].get("closure_not_separately_aligned"):
                flags.append("closure_not_separately_aligned")
            if any(p["end"] - p["start"] < 0.02 for p in phones if p["label"] not in {"SP", "AP"}):
                flags.append("very_short_phones")
            payload = {
                **item,
                "version": VERSION,
                "model_sha256": manifest["model_sha256"],
                "upstream": manifest["upstream"],
                "phones": phones,
                "anchors": anchors,
                "raw_textgrid": str(tg_path),
                "verified": False,
                "flags": flags,
                "postprocessing": "upstream fill_small_gaps/add_SP retained in raw TextGrid",
                "created": time.time(),
            }
            save_analysis(db, cue_id, "phonetic", VERSION, payload)
            energy = acoustic_features(y, sr, item["window_start"])
            energy.update(
                {
                    **item,
                    "version": "vocals-energy-v1",
                    "verified": False,
                    "flags": ["pymss_vocals", "not_phoneme_boundaries", "separation_artifacts_possible"],
                }
            )
            save_analysis(db, cue_id, "vocals_energy", "vocals-energy-v1", energy)
            set_job(db, identity(cue_id, VERSION), cue_id, VERSION, "done")
            results["completed"] += 1
        except Exception as exc:  # noqa: BLE001 - persist per-item failure, then continue batch
            results["failed"].append({"cue_id": cue_id, "error": str(exc)})
            set_job(db, identity(cue_id, VERSION), cue_id, VERSION, "failed", str(exc))
    db.close()
    return results


def run_hubert(limit=24):
    folder = prepare_hubert(limit)
    if folder is None:
        return {"completed": 0, "message": "No new isolated cues eligible"}
    try:
        output = command(
            [
                __import__("ottosmasher.inference_runtime", fromlist=["python_path"]).python_path(),
                CODE_ROOT / "scripts/hubert_worker.py",
                folder,
                "--model",
                MODEL,
            ],
            timeout=3600,
        )
        (folder / "run.log").write_text(output.stdout + "\n" + output.stderr)
    except Exception as exc:
        db = connect()
        for item in json.loads((folder / "source.json").read_text())["cues"]:
            set_job(db, identity(item["id"], VERSION), item["id"], VERSION, "failed", str(exc))
        db.close()
        raise
    return import_hubert(folder)
