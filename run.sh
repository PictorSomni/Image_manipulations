#!/bin/bash
# Lanceur Linux/macOS (utilise .venv s'il existe)
cd "$(dirname "$0")"
PY=python3
[ -x .venv/bin/python ] && PY=.venv/bin/python
"$PY" run.py
