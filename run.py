#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Lanceur universel pour Dashboard Image Manipulation
Compatible: Windows, macOS, Linux
"""

import sys
import os
import subprocess
from pathlib import Path

def check_dependencies():
    """Vérifie si les dépendances sont installées"""
    missing = []
    
    try:
        import flet
    except ImportError:
        missing.append("flet")
    
    try:
        import PIL
    except ImportError:
        missing.append("Pillow")
    
    try:
        import rich
    except ImportError:
        missing.append("rich")
    
    try:
        import wand
    except ImportError:
        missing.append("Wand")
    
    return missing

def main():
    print("=" * 50)
    print("Dashboard Image Manipulation")
    print("=" * 50)
    print()
    
    # Vérifier les dépendances
    missing = check_dependencies()
    
    if missing:
        print("❌ Dépendances manquantes:", ", ".join(missing))
        print()
        print("Installez-les avec:")
        if os.name == 'nt':  # Windows
            print("  install.bat")
        else:  # Linux/macOS
            print("  ./install.sh")
        print()
        print("ou manuellement:")
        print("  pip install -r requirements.txt")
        sys.exit(1)
    
    # Vérifier que Dashboard.py existe
    dashboard_path = Path(__file__).parent / "Dashboard.py"
    if not dashboard_path.exists():
        print("❌ Fichier Dashboard.py introuvable dans le dossier courant")
        sys.exit(1)
    
    # Vérifier que le dossier Data existe
    data_path = Path(__file__).parent / "Data"
    if not data_path.exists():
        print("⚠️  Dossier Data introuvable - certaines applications pourraient ne pas fonctionner")
    
    print("✓ Toutes les dépendances sont installées")
    print("✓ Lancement du Dashboard...")
    print()
    
    # Lancer Dashboard.py
    try:
        subprocess.run([sys.executable, str(dashboard_path)], check=True)
    except KeyboardInterrupt:
        print("\n✓ Dashboard fermé")
    except Exception as e:
        print(f"❌ Erreur lors du lancement: {e}")
        sys.exit(1)

if __name__ == "__main__":
    main()
