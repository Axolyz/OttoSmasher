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
for key in ('PYTHONPATH', 'PYTHONHOME', 'CONDA_PREFIX', 'CONDA_DEFAULT_ENV', 'VIRTUAL_ENV'):
    env.pop(key, None)
if platform.system() == 'Windows':
    system = Path(env.get('SystemRoot', r'C:\Windows'))
    env['PATH'] = os.pathsep.join(map(str, [system / 'System32', system]))
else:
    env['PATH'] = '/usr/bin:/bin:/usr/sbin:/sbin'
report.unlink(missing_ok=True)
startup_log = Path(str(report) + '.startup.log')
startup_log.unlink(missing_ok=True)
try:
    completed = subprocess.run([str(app), '--packaged-smoke'], env=env, timeout=240)
finally:
    if startup_log.exists():
        print(startup_log.read_text(encoding='utf-8'), flush=True)
    if report.exists():
        print(report.read_text(encoding='utf-8'), flush=True)
    log = test / 'workspace/data/logs/desktop-service.log'
    if log.exists():
        print(log.read_text(encoding='utf-8', errors='replace')[-6000:], flush=True)
completed.check_returncode()
result = json.loads(report.read_text(encoding='utf-8'))
assert result['passed'], result
print(json.dumps(result))
