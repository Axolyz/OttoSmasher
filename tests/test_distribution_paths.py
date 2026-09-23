"""Read-only application resources must never become the writable catalog root."""
import json
import os
import subprocess
import sys
from pathlib import Path


def test_workspace_resources_and_media_runtime_are_separate(tmp_path):
    source = Path(__file__).resolve().parents[1]
    workspace = tmp_path / '中文 工作区'
    media = tmp_path / 'media-runtime'
    folder = media / ('Library/bin' if os.name == 'nt' else 'bin')
    folder.mkdir(parents=True)
    binary = folder / ('ffmpeg.exe' if os.name == 'nt' else 'ffmpeg')
    binary.touch()
    env = {**os.environ, 'PYTHONPATH': str(source / 'src'), 'OTTO_ROOT': str(workspace),
           'OTTO_CODE_ROOT': str(source), 'OTTO_CORE_ENV': str(media)}
    result = subprocess.check_output([sys.executable, '-c',
        'import json; from ottosmasher.workspace import ROOT,CODE_ROOT,DATA,connect,executable; '
        'db=connect(); db.close(); '
        'print(json.dumps([str(ROOT),str(CODE_ROOT),str(DATA),executable("ffmpeg")]))'], env=env, text=True)
    assert json.loads(result) == [str(workspace), str(source), str(workspace / 'data'), str(binary)]
    assert (workspace / 'data/catalog.sqlite3').is_file()
