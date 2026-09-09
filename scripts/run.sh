#!/bin/sh
set -e
ROOT="$(CDPATH= cd -- "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

start_app() {
  if [ ! -f config.yaml ]; then
    cp config.example.yaml config.yaml
  fi
  exec "$1" -m app
}

# 반입본: 바깥에서 풀어 넣은 lib/ 가 있으면 venv·pip 없이 기동
if [ -d lib ]; then
  export PYTHONNOUSERSITE=1
  if command -v python3 >/dev/null 2>&1; then
    start_app python3
  else
    start_app python
  fi
fi

if [ ! -x .venv/bin/python ]; then
  python3 -m venv .venv
fi
.venv/bin/python -m pip install -r requirements.txt
start_app .venv/bin/python
