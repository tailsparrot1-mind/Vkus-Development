#!/usr/bin/env bash
set -e
cd "$(dirname "$0")"
export LANG="C.UTF-8"
export LC_ALL="C.UTF-8"
export PYTHONUTF8=1
python3 -m venv .venv 2>/dev/null || true
source .venv/bin/activate
python -m pip install -q -r requirements.txt
exec python3 main.py
