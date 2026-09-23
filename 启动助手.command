#!/bin/sh
OTTO_PROJECT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
cd "$OTTO_PROJECT_DIR" || exit 1
exec ./otto ui library
