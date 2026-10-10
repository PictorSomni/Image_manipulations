#!/bin/bash
# Installation Linux/macOS — non interactive : environnement Python
# isolé (.venv) + dépendances. Appelé par setup.sh ou à la main.
set -e
cd "$(dirname "$0")"

if ! command -v python3 >/dev/null; then
    echo "[ERREUR] Python 3 introuvable. Lancez plutôt setup.sh."
    exit 1
fi
command -v magick >/dev/null || command -v convert >/dev/null \
    || echo "[AVERTISSEMENT] ImageMagick absent : conversions limitées."

# .venv : Debian, Raspberry Pi OS et Homebrew refusent pip hors venv.
[ -x .venv/bin/python ] || python3 -m venv .venv
PY=.venv/bin/python
"$PY" -m pip install --upgrade pip -q

if ! "$PY" -m pip install -r requirements.txt --upgrade; then
    echo "[INFO] Nouvel essai avec ONNX CPU (pas de GPU compatible)..."
    TMP_REQ="$(mktemp)"
    sed 's/^onnxruntime-gpu.*/onnxruntime>=1.16.0/' requirements.txt > "$TMP_REQ"
    "$PY" -m pip install -r "$TMP_REQ" --upgrade
    rm -f "$TMP_REQ"
fi

echo "[OK] Installation terminée. Lancer : ./run.sh"
