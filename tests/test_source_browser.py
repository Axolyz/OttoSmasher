import json

import numpy as np
import pytest
import soundfile as sf
from test_samples import library as library  # noqa: PLC0414 - imported pytest fixture

from ottosmasher import materials, sample_analysis
from ottosmasher import sample_ops as ops
from ottosmasher import source_regions as regions


def test_source_browser_is_not_a_sample_and_cut_is(library):
    db, root, _ = library
    browser = ops.source_browser(db, root["source_id"])
    assert browser["id"] not in materials.query_ids(db)
    cut = ops.source_selection(db, root["id"], 0.15, 0.35, role="raw", nature="unpitched")
    assert cut["id"] in materials.query_ids(db)
    assert cut["start"] == pytest.approx(0.15)
    assert cut["nature"] == "unpitched"


def test_flatten_selection_registers_only_successful_result(library, monkeypatch, tmp_path):
    db, root, _y = library
    monkeypatch.setattr(ops, "DATA", tmp_path)

    def fake_run(args, **kw):
        from pathlib import Path

        p = Path(args[-1])
        req = json.loads(p.read_text())
        audio, sr = sf.read(req["path"])
        assert len(audio) == int(0.3 * 24000)
        output = tmp_path / "flattened.wav"
        sf.write(output, audio, sr, subtype="FLOAT")
        p.with_suffix(".result.json").write_text(
            json.dumps(
                {
                    "path": str(output),
                    "start": 0,
                    "end": 0.3,
                    "audio_stream": 0,
                    "role": "flattened",
                    "sha256": materials.sha256(output),
                    "target_note": {"name": "A3"},
                }
            )
        )

    monkeypatch.setattr("subprocess.run", fake_run)
    monkeypatch.setattr(sample_analysis, "prepare", lambda *a: None)
    before = db.execute("SELECT count(*) FROM materials").fetchone()[0]
    out = ops.flatten(db, root["id"], mode="all", start=0.2, end=0.5, role="raw")
    assert db.execute("SELECT count(*) FROM materials").fetchone()[0] == before + 1
    child = materials.get(db, out["material_id"])
    assert child["derivation"]["parent_id"] == root["id"]
    assert child["start"] == pytest.approx(0.2) and child["end"] == pytest.approx(0.5)
    assert child["audio_asset"]["root_knots"] == [[0, 0.2], [0.3, 0.5]]

    def fail(*a, **kw):
        raise RuntimeError("failed model")

    monkeypatch.setattr("subprocess.run", fail)
    with pytest.raises(RuntimeError):
        ops.flatten(db, root["id"], mode="all", start=0.3, end=0.5)
    assert db.execute("SELECT count(*) FROM materials").fetchone()[0] == before + 1


def test_reviewed_regions_block_auto_import_not_manual_cuts(library):
    db, root, _ = library
    # The same schema as subtitle import, with retained raw cue independent of library rows.
    db.execute(
        "INSERT INTO cues VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
        ("opening", root["source_id"], 1, 0.1, 0.4, "歌", "歌", "", "歌", "", "dialogue", "test"),
    )
    mark = regions.confirm(db, root["source_id"], 0.2, 0.8)
    materials.sync_cues(db)
    assert db.execute("SELECT 1 FROM cues WHERE id='opening'").fetchone()
    assert not db.execute("SELECT 1 FROM materials WHERE id='opening'").fetchone()
    assert regions.blocked(db, root["source_id"], 0.1, 0.3)
    assert not regions.blocked(db, root["source_id"], 0.8, 0.9)
    child = ops.source_selection(db, root["id"], 0.3, 0.5, role="raw")
    assert child["id"] in materials.query_ids(db)
    regions.remove(db, mark["id"])
    materials.sync_cues(db)
    assert "opening" in materials.query_ids(db)
    regions.confirm(db, root["source_id"], 0.2, 0.8)
    assert "opening" not in materials.query_ids(db)
    assert child["id"] in materials.query_ids(db)


def test_frame_scan_detects_position_and_rejects_uniform_reference(monkeypatch, tmp_path):
    from ottosmasher import opening_scan as scan

    rng = np.random.default_rng(7)
    ref = rng.random((54, 96, 3)).astype("float32")

    def frames(*args):
        yield 1.0, np.zeros((54, 96, 3), dtype="uint8")
        yield 2.0, (ref * 255).astype("uint8")
        yield 3.0, np.zeros((54, 96, 3), dtype="uint8")

    monkeypatch.setattr(scan, "frames", frames)
    hit = scan.match("unused", ref, 0, 10, 2, offset=0.1)[0]
    assert hit["start"] == pytest.approx(1.9) and hit["end"] == pytest.approx(3.9)
    assert hit["needs_review"] and hit["similarity"] > 0.99


def test_mark_before_subtitle_import_keeps_media_identity(library):
    from ottosmasher import catalog

    db, root, _ = library
    from pathlib import Path

    media = Path(root["path"])
    mark = regions.confirm(db, root["source_id"], 0.1, 0.8)
    fp = regions.media_fingerprint(db, root["source_id"])
    media.with_suffix(".srt").write_text("1\n00:00:00,200 --> 00:00:00,700\n歌詞\n")
    result = catalog.import_directory(media.parent)
    assert result["imported"] == 1 and not result["errors"]
    assert regions.media_fingerprint(db, root["source_id"]) == fp
    assert regions.blocked(db, root["source_id"], 0.2, 0.7)
    assert db.execute("SELECT count(*) FROM cues").fetchone()[0] == 1
    assert db.execute("SELECT count(*) FROM materials WHERE cue_id IS NOT NULL").fetchone()[0] == 0
    assert regions.listing(db)[0]["id"] == mark["id"]
