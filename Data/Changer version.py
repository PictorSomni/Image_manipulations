# -*- coding: utf-8 -*-
"""
Met à jour __version__ dans Dashboard.pyw et tous les scripts de Data/.

Utilisation :
  1. Modifiez NEW_VERSION ci-dessous.
  2. Enregistrez le fichier.
  3. Lancez-le (python "Changer version.py").
"""

# ← MODIFIEZ ICI
NEW_VERSION = "2.0.4"

#############################################################
#                          IMPORTS                          #
#############################################################
import re
from pathlib import Path

#############################################################
#                           MAIN                            #
#############################################################
ROOT = Path(__file__).parent.parent

targets = [ROOT / "Dashboard.pyw"] + sorted((ROOT / "Data").glob("*.py")) + sorted((ROOT / "Data").glob("*.pyw"))

pattern = re.compile(r'^(__version__\s*=\s*")[^"]*(")', re.MULTILINE)

updated = 0
skipped = 0

print(f"Version cible : {NEW_VERSION}\n")

for path in targets:
    try:
        text = path.read_text(encoding="utf-8")
    except Exception as e:
        print(f"  [ERREUR lecture] {path.name} : {e}")
        continue

    match = pattern.search(text)
    if not match:
        print(f"  [IGNORÉ] {path.name}  — pas de __version__")
        skipped += 1
        continue

    current = match.group(0).split('"')[1]
    if current == NEW_VERSION:
        print(f"  [OK]      {path.name}  ({current})")
        skipped += 1
        continue

    new_text = pattern.sub(rf'\g<1>{NEW_VERSION}\g<2>', text)
    try:
        path.write_text(new_text, encoding="utf-8")
        print(f"  [MIS À JOUR] {path.name}  {current} → {NEW_VERSION}")
        updated += 1
    except Exception as e:
        print(f"  [ERREUR écriture] {path.name} : {e}")

print(f"\n{'=' * 40}")
print(f"{updated} fichier(s) mis à jour, {skipped} inchangé(s).")
