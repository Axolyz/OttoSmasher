import io
import json

import pytest

from ottosmasher import editions, inference_runtime, service_version


def test_standard_cannot_restore_torch_archive_or_resolve_torch(monkeypatch):
    monkeypatch.setenv("OTTO_EDITION", "standard")
    monkeypatch.setenv("OTTO_ARCHIVED", "native-alignment")
    with pytest.raises(ValueError, match="experiment"):
        editions.enabled()
    monkeypatch.setenv("OTTO_ARCHIVED", "")
    with pytest.raises(ValueError, match="standard"):
        inference_runtime.python_path("torch")
    with pytest.raises(ValueError, match="长期搁置"):
        editions.require_operation("native-alignment", {})


def test_experiment_requires_explicit_archive_selection(monkeypatch):
    monkeypatch.setenv("OTTO_EDITION", "experiment")
    monkeypatch.setenv("OTTO_ARCHIVED", "")
    with pytest.raises(ValueError):
        editions.require_operation("native-alignment", {})
    monkeypatch.setenv("OTTO_ARCHIVED", "native-alignment")
    editions.require_operation("native-alignment", {})
    assert inference_runtime.python_path("torch").parent.parent.name == "inference"
    assert inference_runtime.python_path().parent.parent.name == "onnx"


def test_edition_change_restarts_same_code_service(monkeypatch):
    monkeypatch.setenv("OTTO_EDITION", "experiment")
    monkeypatch.setenv("OTTO_ARCHIVED", "")
    info = {
        "root": str(service_version.ROOT),
        "code_signature": service_version.LOADED_SIGNATURE,
        "edition": "standard",
        "archived": [],
    }
    monkeypatch.setattr(
        service_version.urllib.request, "urlopen", lambda *a, **k: io.BytesIO(json.dumps(info).encode())
    )
    calls = []
    monkeypatch.setattr(service_version.subprocess, "run", lambda *a, **k: calls.append(a))
    service_version.ensure_current_service()
    assert len(calls) == 1


def test_switch_requires_all_jobs_finished(monkeypatch):
    from ottosmasher import operation_jobs

    monkeypatch.setattr(operation_jobs, "listing", lambda: [{"id": "job1", "status": "queued"}])
    with pytest.raises(RuntimeError, match="job1"):
        editions.assert_idle()
    monkeypatch.setattr(operation_jobs, "listing", lambda: [{"id": "job1", "status": "succeeded"}])
    editions.assert_idle()


def test_retry_cannot_bypass_edition(library, monkeypatch):
    from ottosmasher import operation_jobs

    db, _, _ = library
    monkeypatch.setenv("OTTO_EDITION", "standard")
    monkeypatch.setenv("OTTO_ARCHIVED", "")
    db.execute(
        "INSERT INTO operation_jobs VALUES(?,?,?,?,?,?,?,?,?)",
        ("archived", "native-alignment", "{}", "failed", None, None, None, 0, 0),
    )
    db.commit()
    monkeypatch.setattr(operation_jobs, "launch", lambda *a: pytest.fail("must not launch"))
    with pytest.raises(ValueError, match="长期搁置"):
        operation_jobs.retry("archived")


from test_samples import library as library  # noqa: PLC0414
