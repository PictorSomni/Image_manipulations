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
echo "Installation des dépendances Python..."
pip3 install -r requirements.txt --upgrade

echo ""
echo "======================================"
echo "[OK] Installation terminée !"
echo "======================================"
echo ""
echo "Pour lancer le Dashboard :"
echo "  ./run.sh"
echo "ou"
echo "  python3 Dashboard.py"
echo ""
