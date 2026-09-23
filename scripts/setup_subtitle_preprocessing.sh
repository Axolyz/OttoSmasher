#!/bin/sh
# Isolated local tools; upstream checkouts and models remain outside Git.
set -eu
OTTO_PROJECT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
cd "$OTTO_PROJECT_DIR"
.runtime/envs/core/bin/python - <<'PY'
import json,subprocess
from pathlib import Path
for spec in json.load(open('dependencies/subtitle-preprocessing.sources.json')).values():
    path=Path(spec['path'])
    if not path.exists():
        subprocess.run(['./scripts/git','clone','--depth','1',spec['url'],str(path)],check=True)
        subprocess.run(['./scripts/git','-C',str(path),'fetch','--depth','1','origin',spec['commit']],check=True)
        subprocess.run(['./scripts/git','-C',str(path),'checkout','--detach',spec['commit']],check=True)
    current=subprocess.check_output(['./scripts/git','-C',str(path),'rev-parse','HEAD'],text=True).strip()
    if current!=spec['commit']:
        raise SystemExit(f'Checkout changed: {path}; refusing to overwrite')
PY
for tool in sub-align subplz; do
  if [ ! -x ".runtime/envs/$tool/bin/python" ]; then
    .runtime/envs/core/bin/python -m venv ".runtime/envs/$tool"
  fi
  ".runtime/envs/$tool/bin/pip" install -r "dependencies/$tool.pip.lock.txt"
done
