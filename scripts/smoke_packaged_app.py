"""Run the actual unpacked Electron app in an empty workspace with Unicode paths."""
import json
import os
import platform
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
app = ROOT / ('dist/apps/win-unpacked/OttoSmasher.exe' if platform.system() == 'Windows'
              else 'dist/apps/mac-arm64/OttoSmasher.app/Contents/MacOS/OttoSmasher')
test = ROOT / 'build/验收 空目录'
report = ROOT / 'dist/packaged-smoke.json'
env = {**os.environ, 'OTTO_ROOT': str(test / 'workspace'), 'OTTO_APP_USER_DATA': str(test / 'profile'),
       'OTTO_SMOKE_REPORT': str(report), 'OTTO_DESKTOP_PORT': '18789'}
env.pop('ELECTRON_RUN_AS_NODE', None)
subprocess.run([str(app), '--packaged-smoke'], env=env, timeout=240, check=True)
result = json.loads(report.read_text())
assert result['passed'], result
print(json.dumps(result))
