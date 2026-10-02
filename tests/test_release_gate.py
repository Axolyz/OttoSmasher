import json
import runpy
from pathlib import Path
import pytest

validate=runpy.run_path(str(Path(__file__).resolve().parents[1]/'scripts/publish_release.py'))['validate']


def artifacts(tmp_path):
    for platform,arch,filename in [('darwin','arm64','mac-arm64'),('win32','x64','win-x64')]:
        folder=tmp_path/platform;folder.mkdir()
        (folder/f'OttoSmasher-1.0.0-{filename}.zip').write_bytes(b'archive')
        (folder/'packaged-smoke.json').write_text(json.dumps({'passed':True,'platform':platform,'arch':arch}))
    return tmp_path


def test_release_needs_both_platforms_and_strict_size_limit(tmp_path):
    root=artifacts(tmp_path)
    files=validate(root,'1.0.0');assert len(files)==2
    with files[0].open('r+b') as f:f.truncate(2_000_000_000)
    with pytest.raises(ValueError,match='2 GB'):validate(root,'1.0.0')
    files[0].unlink()
    with pytest.raises(ValueError,match='Both platform'):validate(root,'1.0.0')


def test_release_refuses_failed_smoke_and_extra_zip(tmp_path):
    root=artifacts(tmp_path)
    report=root/'darwin/packaged-smoke.json'
    report.write_text(json.dumps({'passed':False,'platform':'darwin','arch':'arm64'}))
    with pytest.raises(ValueError,match='smoke'):validate(root,'1.0.0')
    (root/'unexpected.zip').write_bytes(b'x')
    with pytest.raises(ValueError,match='unexpected'):validate(root,'1.0.0')


def test_runtime_audit_distinguishes_compatibility_adapter_from_torch(tmp_path):
    audit=runpy.run_path(str(Path(__file__).resolve().parents[1]/'scripts/stage_app.py'))['audit_runtime']
    (tmp_path/'lib/python3.11/site-packages/sklearn/externals/array_api_compat/torch').mkdir(parents=True)
    audit(tmp_path)
    (tmp_path/'lib/python3.11/site-packages/torch').mkdir()
    with pytest.raises(ValueError,match='PyTorch'):audit(tmp_path)
