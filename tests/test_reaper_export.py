import json
from pathlib import Path

import numpy as np
import pytest
import soundfile as sf
import test_vocals
from test_quantization import fixture_analysis

from ottosmasher import beat_reference, quantization, strict_audio
from ottosmasher.reaper_export import export_reaper, media_payload, quoted
from ottosmasher.rhythm_units import rhythm_view

separated_cue = test_vocals.separated_cue


def test_clipboard_records_and_quote_integrity(tmp_path):
    audio = tmp_path / '日语 "test".wav'
    audio.touch()
    payload = media_payload(audio, 2, [(0, 0), (0.2, 0.3), (2, 1.5)], 0.2, 0.5, "test")
    assert payload.startswith(b"<ITEM\0") and payload.endswith(b"\0\0")
    records = payload.decode().split("\0")
    assert "PLAYRATE 1 1 0 -1 0 0.0025" in records
    assert any(
        r.startswith("SM ") and "0.200000000000 0.300000000000 0 0 0.400000000000" in r for r in records
    )
    assert any(r.startswith("FILE '") for r in records)
    with pytest.raises(ValueError):
        quoted("a\nb")
    with pytest.raises(ValueError):
        media_payload(audio, 2, [(0, 0), (0, 1)], 0, 0.5, "bad")


def test_real_source_not_baked_and_all_onsets_exported(separated_cue, monkeypatch):
    _, cue, lineage = separated_cue
    root = Path(lineage["audio_path"]).parent
    for module in (beat_reference, quantization, strict_audio):
        monkeypatch.setattr(module, "DATA", root / "data")
    a = fixture_analysis(lineage)
    v = rhythm_view(a)
    plan = beat_reference.generate_references(cue, a, v, strategy="acoustic", density=2)["plans"][0]
    result = export_reaper(cue, a, plan, directory=str(root / "persistent"), copy=False)
    original, sr = sf.read(result["audio"])
    assert len(original) == 3 * sr
    assert result["duration"] != pytest.approx(3)
    assert result["snap_offset"] > 0
    for p in plan["unit_targets"]:
        assert any(
            abs(source - p["source_seconds"]) <= 1 / sr
            and abs(dest - result["snap_offset"] - p["target_beat"] * plan["beat_seconds"]) <= 1 / sr
            for dest, source in result["markers"]
        )
    assert json.loads(Path(result["manifest"]).read_text())["plan_id"] == plan["plan_id"]
    assert sf.info(result["audio"]).duration == 3


def test_elastic_gap_preserves_nonzero_low_level_audio(separated_cue, monkeypatch):
    _, cue, lineage = separated_cue
    root = Path(lineage["audio_path"]).parent
    for module in (beat_reference, strict_audio):
        monkeypatch.setattr(module, "DATA", root / "data")
    y, sr = sf.read(lineage["audio_path"])
    y[round(1.2 * sr) : round(2.5 * sr)] *= 0.01
    sf.write(lineage["audio_path"], y, sr)
    import hashlib

    lineage["audio_sha256"] = hashlib.sha256(Path(lineage["audio_path"]).read_bytes()).hexdigest()
    a = fixture_analysis(lineage)
    v = rhythm_view(a)
    assert v["pauses"]
    p = beat_reference.generate_references(cue, a, v, strategy="acoustic", density=8)["plans"][0]
    path, meta = strict_audio.render_strict(cue, a, p)
    result, _ = sf.read(path, always_2d=True)
    gaps = [s for s in meta["segments"] if s["kind"] == "elastic_gap"]
    assert gaps
    assert all(np.any(abs(result[s["target_frames"][0] : s["target_frames"][1]]) > 0) for s in gaps)
