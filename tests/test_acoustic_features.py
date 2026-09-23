"""Read-only queries, provenance and interpretable DSP contracts."""

import numpy as np
import pytest
from fastapi.testclient import TestClient

from ottosmasher import sample_catalog, sample_scope
from ottosmasher import timbre_features as tf

pytest_plugins = ["test_samples"]


def count(db):
    return db.execute("SELECT count(*) FROM materials").fetchone()[0]


def test_spectral_ratios_gain_invariant_harmonics_and_unknown():
    sr = 24000
    t = np.arange(sr) / sr
    pure = np.sin(2 * np.pi * 440 * t)
    bright = pure + 0.6 * np.sin(2 * np.pi * 2640 * t)
    times = np.arange(0, 1, 0.01)
    frames = {
        "times": times,
        "f0_hz": np.full(len(times), 440),
        "confidence": np.ones(len(times)),
        "voiced": np.ones(len(times), dtype=bool),
    }
    a, b, c = (
        tf.describe(pure, sr, frames),
        tf.describe(bright, sr, frames),
        tf.describe(bright * 0.1, sr, frames),
    )
    assert b["values"]["harmonic.high"] > a["values"]["harmonic.high"] + 0.1
    assert b["values"]["harmonic.high"] == pytest.approx(c["values"]["harmonic.high"], abs=1e-8)
    assert b["values"]["spectrum.centroid"] == pytest.approx(c["values"]["spectrum.centroid"])
    assert c["values"]["sound.rms"] == pytest.approx(b["values"]["sound.rms"] - 20)
    assert tf.describe(bright, sr)["values"]["pitch.midi"] is None
    assert all(x is None for x in tf.describe(np.zeros(sr), sr)["values"].values())


def test_scope_folder_union_independent_star_and_pending(library):
    db, root, _ = library
    child = sample_catalog.derive(db, root["id"], start=0.1, end=0.7, folder_id="pitched")
    sample_catalog.preferences(db, root["id"], folder_id="speech", starred=True)
    assert set(sample_scope.ids(db, {"natures": ["speech", "pitched"]})) == {root["id"], child["id"]}
    assert sample_scope.ids(db, {"natures": ["speech", "pitched"], "starred": True}) == [root["id"]]


def test_shared_filter_keeps_producers_distinct_and_missing_unknown(library, monkeypatch):
    db, root, _ = library
    child = sample_catalog.derive(db, root["id"], start=0.1, end=0.7, folder_id="pitched")
    docs = {
        (root["id"], "one"): {"values": {"score": 0.8}},
        (root["id"], "two"): {"values": {"score": 0.2}},
        (child["id"], "one"): {"values": {"score": 0.8}},
    }
    monkeypatch.setattr(tf, "read", lambda db, mid, producer: docs.get((mid, producer)))
    conditions = [
        {"producer": "one", "name": "score", "min": 0.7},
        {"producer": "two", "name": "score", "max": 0.3},
    ]
    before = count(db)
    result = sample_scope.search(db, conditions=conditions)
    assert result["total"] == 1 and result["unknown"] == 1
    assert result["results"][0]["id"] == root["id"]
    assert count(db) == before


def test_http_rhythm_filter_does_not_dispatch_batch(library, monkeypatch):
    from ottosmasher import sample_ops, sample_rhythm
    from ottosmasher.api import app

    db, _, _ = library
    before = count(db)
    monkeypatch.setattr(sample_rhythm, "search", lambda *_: {"results": []})

    def forbidden(*_):
        pytest.fail("ordinary search must never create a batch")

    monkeypatch.setattr(sample_ops, "batch_search", forbidden)
    response = TestClient(app).post("/api/samples/rhythm", json={"bpm": 120})
    assert response.status_code == 200 and count(db) == before
