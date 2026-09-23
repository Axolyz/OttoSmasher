from __future__ import annotations

import json
import time

import numpy as np
from scipy.signal import find_peaks

from .media import read_window
from .workspace import connect, get_cue, identity, save_analysis, set_job

VERSION = "acoustic-v1"


def acoustic_features(y, sr, start):
    """Mixed-audio energy candidates, explicitly not phone boundaries or vocal VAD."""
    hop, frame = round(sr * 0.01), round(sr * 0.025)
    if len(y) < frame:
        return {"anchors": [], "waveform": [], "flags": ["too_short"]}
    frames = np.lib.stride_tricks.sliding_window_view(y, frame)[::hop]
    rms = np.sqrt(np.mean(frames**2, axis=1) + 1e-12)
    log_energy = 20 * np.log10(rms + 1e-8)
    novelty = np.maximum(0, log_energy - np.roll(log_energy, 3))
    novelty[:3] = 0
    peaks, _ = find_peaks(novelty, distance=8, prominence=2.5, height=3)
    max_rms = max(float(np.max(rms)), 1e-6)
    anchors = [
        {
            "time": round(start + (int(i) * hop + frame / 2) / sr, 5),
            "strength": round(float(rms[i] / max_rms), 5),
            "kind": "mixed_audio_energy_rise",
            "phone": None,
            "pitch_midi": None,
            "duration": None,
        }
        for i in peaks
        if rms[i] >= max_rms * 0.04
    ]
    stride = max(1, len(rms) // 400)
    return {
        "anchors": anchors,
        "waveform": [round(float(x / max_rms), 4) for x in rms[::stride]],
        "waveform_step": stride * hop / sr,
        "waveform_start": start,
        "rms_db": round(float(20 * np.log10(np.sqrt(np.mean(y**2)) + 1e-8)), 3),
        "flags": ["mixed_audio_may_include_music", "not_phoneme_boundaries"],
    }


def run_acoustic(limit=None, source_id=None, progress=None):
    db = connect()
    condition, params = "", []
    if source_id:
        condition = " AND c.source_id=?"
        params.append(source_id)
    rows = db.execute(
        """SELECT c.id FROM cues c WHERE c.kind='dialogue' """
        + condition
        + """ AND NOT EXISTS (SELECT 1 FROM analyses a WHERE a.cue_id=c.id
                         AND a.kind='acoustic' AND a.version=?) ORDER BY c.source_id,c.ordinal""",
        (*params, VERSION),
    ).fetchall()
    if limit is not None:
        rows = rows[:limit]
    result = {"completed": 0, "failed": 0, "total": len(rows)}
    for row in rows:
        cue = get_cue(db, row[0])
        job = identity(cue["id"], VERSION)
        set_job(db, job, cue["id"], VERSION, "running")
        try:
            y, sr, start, end = read_window(cue)
            payload = acoustic_features(y, sr, start)
            payload.update(
                {
                    "version": VERSION,
                    "source_fingerprint": cue["fingerprint"],
                    "window_start": start,
                    "window_end": end,
                    "sample_rate": sr,
                    "verified": False,
                    "created": time.time(),
                }
            )
            save_analysis(db, cue["id"], "acoustic", VERSION, payload)
            set_job(db, job, cue["id"], VERSION, "done")
            result["completed"] += 1
        except Exception as exc:  # noqa: BLE001 - persist per-item failure, then continue batch
            set_job(db, job, cue["id"], VERSION, "failed", str(exc))
            result["failed"] += 1
        if progress and (result["completed"] + result["failed"]) % 100 == 0:
            progress(json.dumps(result))
    db.close()
    return result
