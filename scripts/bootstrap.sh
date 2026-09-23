#!/bin/sh
# Project-local Apple Silicon environments. No shell profile changes.
set -eu
OTTO_PROJECT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
cd "$OTTO_PROJECT_DIR"
if [ "$(uname -sm)" != "Darwin arm64" ]; then
  echo 'This bootstrap currently targets Apple Silicon macOS. See README for portability.' >&2
  exit 1
fi
mkdir -p .runtime/bin .runtime/downloads .runtime/logs models
if [ ! -x .runtime/bin/micromamba ]; then
  curl -fL --retry 1 https://micro.mamba.pm/api/micromamba/osx-arm64/latest -o .runtime/downloads/micromamba.tar.bz2
  tar -xjf .runtime/downloads/micromamba.tar.bz2 -C .runtime bin/micromamba
fi
if [ ! -x .runtime/envs/core/bin/python ]; then
  .runtime/bin/micromamba create -y -r .runtime/mamba -p .runtime/envs/core -f dependencies/core.conda-explicit.txt
fi
.runtime/envs/core/bin/python -m pip install -r dependencies/core.pip.lock.txt
.runtime/envs/core/bin/python -m pip install -e '.[dev]'
.runtime/envs/core/bin/python scripts/setup_rubberband.py
.runtime/envs/core/bin/python scripts/fetch_sources.py
.runtime/envs/core/bin/python scripts/setup_inference.py
.runtime/envs/core/bin/python scripts/prepare_models.py
.runtime/envs/core/bin/python scripts/verify_models.py
.runtime/envs/core/bin/python scripts/setup_player.py
./scripts/setup_desktop.sh
echo "Ready: ./otto ui library"
