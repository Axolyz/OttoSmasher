import io
import json

import pytest

from ottosmasher import service_version as version


@pytest.mark.parametrize('reported,restarts', [(None, True), ('old', True), ('current', False)])
def test_source_launcher_restarts_only_stale_service(monkeypatch, reported, restarts):
    monkeypatch.setattr(version, 'LOADED_SIGNATURE', 'current')
    monkeypatch.setattr(version.urllib.request, 'urlopen', lambda *a, **kw: io.BytesIO(json.dumps(
        {'root': str(version.ROOT), 'code_signature': reported}).encode()))
    calls = []
    monkeypatch.setattr(version.subprocess, 'run', lambda *a, **kw: calls.append((a, kw)))
    version.ensure_current_service()
    assert bool(calls) == restarts
    if calls:
        assert '--no-build' in calls[0][0][0]


def test_source_launcher_leaves_other_workspace_alone(monkeypatch):
    monkeypatch.setattr(version.urllib.request, 'urlopen', lambda *a, **kw: io.BytesIO(b'{"root":"elsewhere"}'))
    monkeypatch.setattr(version.subprocess, 'run', lambda *a, **kw: pytest.fail('must not restart'))
    with pytest.raises(RuntimeError, match='其他工作区'):
        version.ensure_current_service()


def test_signature_detects_content_change_and_removal(tmp_path):
    p = tmp_path / 'src/ottosmasher/module.py'
    p.parent.mkdir(parents=True)
    p.write_text('before')
    before = version.signature(tmp_path)
    p.write_text('after')
    after = version.signature(tmp_path)
    p.unlink()
    assert len({before, after, version.signature(tmp_path)}) == 3
