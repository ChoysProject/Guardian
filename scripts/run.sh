#!/bin/sh
set -e
ROOT="$(CDPATH= cd -- "$(dirname "$0")/.." && pwd)"
cd "$ROOT"
if [ ! -x .venv/bin/python ]; then
  python3 -m venv .venv
fi
.venv/bin/python -m pip install -r requirements.txt
if [ ! -f config.yaml ]; then
  cp config.example.yaml config.yaml
fi
exec .venv/bin/python -m app
