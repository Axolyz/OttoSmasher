import numpy as np
import pytest
import soundfile as sf

from ottosmasher import media_operations, media_visualization


@pytest.mark.parametrize("sr", [16000, 44100, 48000])
def test_spectrum_pcm_rounding_and_real_overflow(tmp_path, monkeypatch, sr):
    for m in (media_operations, media_visualization):
        monkeypatch.setattr(m, "DATA", tmp_path)
    path = tmp_path / "音.wav"
    sf.write(path, np.zeros(sr * 3), sr)
    start = 0.1234567
    end = 2.3924567
    spec = media_operations.source_spec(path, start, end, 0)
    key = media_visualization.register(spec)
    duration = (round(end * sr) - round(start * sr)) / sr
    detail = media_visualization.detail(key, 0, duration)
    assert detail["start"] == 0
    assert detail["end"] == pytest.approx(duration)
    with pytest.raises(ValueError, match="越界"):
        media_visualization.detail(key, 0, end - start + 2 / sr)
    with pytest.raises(ValueError, match="越界"):
        media_visualization.detail(key, -2 / sr, 1)


def test_required_rhythm_units_do_not_skip_or_return_other_occurrence():
    from test_quantized_match import note, pattern, query

    from ottosmasher.quantized_match import match_pattern

    p = pattern()
    for i in range(3):
        q = vars(query([note(0, 0.25)], required_unit_indices=[i]))
        result = match_pattern(p, q)
        assert result and result["matched_anchor_indices"] == [i]


def test_hit_version_and_range_rejected_before_actions(monkeypatch):
    from ottosmasher import sample_analysis, speech_query

    r = {"signature": "new", "asset": {"path": "bound.wav"}, "backend": "mfa"}
    monkeypatch.setattr(sample_analysis, "ready", lambda *args: r)
    with pytest.raises(ValueError, match="失效"):
        speech_query.validate_hit(
            None, {"material_id": "one", "revision": "old", "audio_identity": "old", "backend": "mfa"}
        )


def test_cancel_only_signals_owned_job_process_group(tmp_path, monkeypatch):
    import contextlib
    import os
    import sqlite3
    import subprocess
    import sys

    from ottosmasher import operation_jobs

    if os.name != "posix":
        pytest.skip("POSIX job groups")

    @contextlib.contextmanager
    def connection():
        db = sqlite3.connect(tmp_path / "jobs.sqlite3")
        db.row_factory = sqlite3.Row
        try:
            with db:
                yield db
        finally:
            db.close()

    monkeypatch.setattr(operation_jobs, "connect", connection)
    processes = [
        subprocess.Popen([sys.executable, "-c", "import time; time.sleep(30)"], start_new_session=True)
        for _ in range(2)
    ]
    try:
        with connection() as db:
            db.execute("CREATE TABLE operation_jobs(id TEXT,status TEXT,pid INTEGER,updated REAL)")
            db.executemany(
                "INSERT INTO operation_jobs VALUES(?,?,?,0)",
                [(str(i), "running", p.pid) for i, p in enumerate(processes)],
            )
        assert operation_jobs.cancel("0") == {"status": "cancelled"}
        assert processes[0].wait(timeout=3) < 0
        assert processes[1].poll() is None
        with connection() as db:
            assert db.execute("SELECT status FROM operation_jobs WHERE id='1'").fetchone()[0] == "running"
    finally:
        for process in processes:
            if process.poll() is None:
                process.terminate()
            process.wait(timeout=3)
