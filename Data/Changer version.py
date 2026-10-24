# -*- coding: utf-8 -*-
"""
Incrémente la version de l'application (fichier VERSION à la racine).

Utilisation :
  python "Changer version.py"          → 2.10.127 devient 2.10.128
  python "Changer version.py" 2.11.0   → version imposée
"""

import sys
from pathlib import Path

VERSION_FILE = Path(__file__).resolve().parent.parent / "VERSION"

current = VERSION_FILE.read_text(encoding="utf-8").strip()
if len(sys.argv) > 1:
    new = sys.argv[1].strip()
else:
    parts = current.split(".")
    parts[-1] = str(int(parts[-1]) + 1)
    new = ".".join(parts)
VERSION_FILE.write_text(new + "\n", encoding="utf-8")
print(f"Version : {current} → {new}")
