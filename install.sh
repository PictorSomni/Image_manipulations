#!/bin/bash
# Script d'installation pour Linux/macOS
# Dashboard Image Manipulation

set -e

echo "======================================"
echo "Dashboard Image Manipulation Setup"
echo "======================================"
echo ""

# Vérifier si Python est installé
if ! command -v python3 &> /dev/null; then
    echo "[ERREUR] Python 3 n'est pas installé."
    echo "[INFO] Installez Python 3.8+ depuis https://www.python.org/downloads/"
    exit 1
fi

PYTHON_VERSION=$(python3 --version | cut -d' ' -f2 | cut -d'.' -f1,2)
echo "[OK] Python $PYTHON_VERSION détecté"

# Vérifier si pip est installé
if ! command -v pip3 &> /dev/null; then
    echo "[ERREUR] pip n'est pas installé."
    echo "[INFO] Installez pip: sudo apt install python3-pip (Linux) ou brew install python3 (macOS)"
    exit 1
fi

echo "[OK] pip détecté"
echo ""

# Utiliser le pip du Python detecte pour eviter les conflits d'environnement
PIP_CMD=(python3 -m pip)

echo "Mise a jour de pip..."
"${PIP_CMD[@]}" install --upgrade pip

# Installer ImageMagick (requis pour Wand) si pas présent
echo "Vérification d'ImageMagick (requis pour la conversion d'images)..."
if ! command -v convert &> /dev/null; then
    echo "!!!  ImageMagick n'est pas installé."
    echo ""
    echo "Pour installer ImageMagick :"
    echo "  - Linux (Debian/Ubuntu): sudo apt install imagemagick"
    echo "  - Linux (Fedora): sudo dnf install ImageMagick"
    echo "  - macOS: brew install imagemagick"
    echo ""
    read -p "Voulez-vous continuer sans ImageMagick ? (certaines fonctionnalités ne fonctionneront pas) [y/N] " -n 1 -r
    echo ""
    if [[ ! $REPLY =~ ^[Yy]$ ]]; then
        echo "Installation annulée."
        exit 1
    fi
else
    echo "[OK] ImageMagick détecté"
fi

echo ""
echo "Installation des dependances Python..."
if ! "${PIP_CMD[@]}" install -r requirements.txt --upgrade; then
    echo ""
    echo "[AVERTISSEMENT] Echec de l'installation standard des dependances."
    echo "[INFO] Nouvelle tentative avec fallback ONNX CPU (si backend GPU indisponible sur cette machine)..."

    TMP_REQ="$(mktemp)"
    awk '
        BEGIN { replaced = 0 }
        /^onnxruntime-gpu>=/ {
            print "onnxruntime>=1.16.0"
            replaced = 1
            next
        }
        { print }
        END {
            if (replaced == 0) {
                print "onnxruntime>=1.16.0"
            }
        }
    ' requirements.txt > "$TMP_REQ"

    if ! "${PIP_CMD[@]}" install -r "$TMP_REQ" --upgrade; then
        rm -f "$TMP_REQ"
        echo "[ERREUR] Installation des dependances impossible."
        exit 1
    fi

    rm -f "$TMP_REQ"
    echo "[OK] Installation terminee avec fallback ONNX CPU."
fi

echo ""
echo "Verification d'Ollama (IA locale)..."
_ollama_bin=""
for _p in \
    "$(command -v ollama 2>/dev/null)" \
    "/usr/local/bin/ollama" \
    "/opt/homebrew/bin/ollama" \
    "/opt/homebrew/sbin/ollama" \
    "$HOME/.local/bin/ollama"; do
    if [ -x "$_p" ]; then
        _ollama_bin="$_p"
        break
    fi
done

if [ -n "$_ollama_bin" ]; then
    echo "[OK] Ollama detecte ($_ollama_bin), mise a jour du modele..."
    "$_ollama_bin" pull llama3.2:3b || true
else
    echo "[INFO] Ollama non detecte. Installation en cours..."
    curl -fsSL https://ollama.com/install.sh | sh
    if command -v ollama &> /dev/null || [ -x "/usr/local/bin/ollama" ]; then
        echo "[OK] Ollama installe."
    else
        echo "[AVERTISSEMENT] Impossible d'installer Ollama automatiquement."
        echo "[INFO] Installez-le manuellement depuis https://ollama.com/download"
    fi
fi

echo ""
echo "======================================"
echo "[OK] Installation terminee !"
echo "======================================"
echo ""
echo "Pour lancer le Dashboard :"
echo "  ./run.sh"
echo "ou"
echo "  python3 Dashboard.pyw"
echo ""
