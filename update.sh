#!/usr/bin/env bash
set -euo pipefail

EXPECTED_ORIGIN="https://github.com/PictorSomni/Image_manipulations.git"

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$SCRIPT_DIR"

if ! REPO_ROOT="$(git rev-parse --show-toplevel 2>/dev/null)"; then
	echo "[ERREUR] Ce dossier n'est pas un depot Git valide."
	echo "[INFO] Dossier courant: $SCRIPT_DIR"
	exit 1
fi

if [ "$REPO_ROOT" != "$SCRIPT_DIR" ]; then
	echo "[ERREUR] Chemin du repo invalide pour ce script."
	echo "[INFO] Racine Git detectee: $REPO_ROOT"
	echo "[INFO] Dossier du script:   $SCRIPT_DIR"
	exit 1
fi

if ! ORIGIN_URL="$(git remote get-url origin 2>/dev/null)"; then
	echo "[ERREUR] Remote 'origin' introuvable."
	exit 1
fi

if [ "$ORIGIN_URL" != "$EXPECTED_ORIGIN" ]; then
	echo "[ERREUR] Mauvais depot distant configure."
	echo "[INFO] Origin detecte:  $ORIGIN_URL"
	echo "[INFO] Origin attendu:  $EXPECTED_ORIGIN"
	exit 1
fi

echo "[INFO] Mise a jour du depot Git..."
git pull
echo "[OK] Depot mis a jour."
