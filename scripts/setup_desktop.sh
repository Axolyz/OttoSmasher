#!/bin/sh
set -eu
TASK_ROOT=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
NODE_BIN=${OTTO_NODE:-"$TASK_ROOT/.runtime/envs/player/bin/node"}
if [ ! -x "$NODE_BIN" ]; then NODE_BIN=$(command -v node || true); fi
if [ -z "$NODE_BIN" ]; then
  echo "Install the project player runtime (scripts/setup_player.py) first." >&2; exit 1
fi
if [ ! -x "$NODE_BIN" ]; then
  echo 'Set OTTO_NODE to your Node.js 22+ executable.' >&2; exit 1
fi
export PATH="$(dirname -- "$NODE_BIN"):$PATH"
cd "$TASK_ROOT/desktop"
if [ ! -d node_modules ]; then
  npm install --ignore-scripts
fi
if [ ! -f node_modules/electron/path.txt ]; then "$NODE_BIN" node_modules/electron/install.js; fi
"$NODE_BIN" node_modules/typescript/bin/tsc --noEmit
"$NODE_BIN" node_modules/vite/bin/vite.js build
if [ "$(uname -s)" = Darwin ] && [ ! -f "$TASK_ROOT/.runtime/player.node" ]; then
  "$TASK_ROOT/.runtime/envs/core/bin/python" "$TASK_ROOT/scripts/setup_player.py"
fi
echo 'Ready: ./otto ui library (or search / cut)'
