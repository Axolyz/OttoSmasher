#!/bin/sh
set -eu
cd "$(dirname "$0")"
exec ./otto ui library --edition experiment
