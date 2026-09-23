import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest
import soundfile as sf
from test_samples import library as library  # noqa: PLC0414

from ottosmasher import job_worker, sample_acoustics, sample_audio, source_vocals, ui_catalog, vocals
from ottosmasher.materials import sha256

spec = importlib.util.spec_from_file_location(
    "separation_chunks", Path(__file__).parents[1] / "scripts/separation_chunks.py"
)
chunks = importlib.util.module_from_spec(spec)
spec.loader.exec_module(chunks)


@pytest.mark.parametrize("seconds", [0.25, 3, 3.25, 8.3])
def test_contextual_stitch_preserves_every_frame_and_emits_progress(tmp_path, seconds):
    sr = 1000
    audio = np.random.default_rng(20).normal(0, 0.1, (round(seconds * sr), 2)).astype("float32")
    path = tmp_path / "input.wav"
    sf.write(path, audio, sr, subtype="FLOAT")

    class Identity:
        config = SimpleNamespace(audio={"sample_rate": sr})

        def separate(self, y, **_):
            self.progress_callback(1, 2, "real inference")
            return {"vocals": y.T, "instrument": y.T * 0.5}

    progress = tmp_path / "progress.json"
    outputs = chunks.separate_file(
        Identity(), path, tmp_path / "out", ["vocals", "instrument"], 3, 1, progress
    )
    y, _ = sf.read(outputs["vocals"], dtype="float32")
    np.testing.assert_allclose(y, audio, atol=3e-8)
    assert json.loads(progress.read_text())["percent"] == 100
    assert not list(tmp_path.rglob("*.partial"))


def test_full_source_separates_once_before_clipping_and_is_reusable(library, tmp_path, monkeypatch):
    db, root, _ = library
    monkeypatch.setattr(source_vocals, "DATA", tmp_path / "data")
    monkeypatch.setattr(vocals, "model_identity", lambda m: {m: "fingerprint"})
    calls = []

    def separate(op, p, jid):
        calls.append((op, p))
        assert p["start"] == 0 and p["end"] == 1
        target = Path(p["output"]) / "vocals.wav"
        sf.write(target, np.ones(24000) * 0.1, 24000)
        a = {
            "path": str(target),
            "role": "vocals",
            "start": 0,
            "end": 1,
            "sha256": sha256(target),
            "root_knots": [[0, 0], [1, 1]],
            "audio_stream": 0,
            "provenance": {
                "source_id": root["source_id"],
                "model": p["model"],
                "source_audio_stream": 0,
                "source_fingerprint": root["fingerprint"],
                "model_fingerprints": {p["model"]: "fingerprint"},
            },
        }
        with source_vocals.connect() as conn:
            conn.execute(
                "INSERT INTO shared_sample_audio VALUES(?,?,?)", ("whole", root["source_id"], json.dumps(a))
            )

    monkeypatch.setattr(job_worker, "run", separate)
    cue = {**root, "id": "cue1", "start": 0.1, "end": 0.4}
    first = source_vocals.ensure(cue)
    second = source_vocals.ensure({**cue, "id": "cue2", "start": 0.5, "end": 0.7})
    assert first == second and len(calls) == 1
    assert sample_audio.resolve(db, root["id"], "vocals")["path"] == first["path"]
    assert db.execute("SELECT count(*) FROM analyses").fetchone()[0] == 0
    # Removing the lightweight manifest still reuses the registered full track.
    next((tmp_path / "data").rglob("source.json")).unlink()
    assert source_vocals.ensure(cue) == first and len(calls) == 1


def test_features_without_text_are_read_from_the_selected_audio(library):
    db, root, _ = library
    assert sample_acoustics.capabilities(db, root["id"])["default_role"] == "selected"
    assert sample_acoustics.cached(db, root["id"])["status"] == "missing"
    path = sample_audio.pcm(sample_audio.resolve(db, root["id"]))
    path.with_suffix(".features.json").write_text(
        json.dumps(
            {
                "times": [0.1, 0.5],
                "f0_hz": [200, None],
                "voiced": [True, False],
                "energy": [0.1, 0.2],
                "confidence": [0.9, 0],
            }
        )
    )
    result = sample_acoustics.cached(db, root["id"])
    assert result["frames"]["f0_hz"] == [200, None]
    assert db.execute("SELECT count(*) FROM analyses").fetchone()[0] == 0


def test_scheduler_limits_and_progress_setting(library):
    from ottosmasher.operation_jobs import resource_lane

    db, _, _ = library
    assert resource_lane("separate") == "model"
    assert resource_lane("cut") == "utility"
    assert (
        ui_catalog.settings(db, {"model_concurrency": 2, "separation_progress": False})["model_concurrency"]
        == 2
    )
    with pytest.raises(ValueError):
        ui_catalog.settings(db, {"model_concurrency": 0})


@pytest.mark.parametrize(
    "limit, operation, waits", [(1, "cut", False), (1, "separate", True), (2, "separate", False)]
)
def test_task_admission_uses_separate_lanes_and_configured_model_limit(
    library, monkeypatch, limit, operation, waits
):
    import os
    import time

    db, _, _ = library
    ui_catalog.settings(db, {"model_concurrency": limit})
    for jid, op, status in [("other", "separate", "running"), ("this", operation, "queued")]:
        db.execute(
            "INSERT INTO operation_jobs VALUES(?,?,?,?,?,?,?,?,?)",
            (jid, op, "{}", status, os.getpid(), None, None, time.time(), time.time()),
        )
    db.commit()
    slept = []

    def sleep(_):
        assert not slept, "task admission failed to observe a freed lane"
        slept.append(True)
        db.execute("UPDATE operation_jobs SET status='succeeded' WHERE id='other'")
        db.commit()

    monkeypatch.setenv("OTTO_JOB_ID", "before-test")
    monkeypatch.setattr(job_worker.time, "sleep", sleep)
    monkeypatch.setattr(job_worker, "run", lambda *_: {"completed": True})
    job_worker.main("this")
    assert bool(slept) == waits
    assert db.execute("SELECT status FROM operation_jobs WHERE id='this'").fetchone()[0] == "succeeded"
