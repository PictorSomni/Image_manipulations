# -*- coding: utf-8 -*-
"""
Supprime les fichiers vieux de plus de 60 jours dans les dossiers
KIOSK GAUCHE, KIOSK DROITE et TEMP.

Chemins :
  Windows : \\\\Diskstation\\travaux en cours\\z2026\\kiosk\\KIOSK GAUCHE
            \\\\Diskstation\\travaux en cours\\z2026\\kiosk\\KIOSK DROITE
            \\\\diskstation\\travaux en cours\\Z2026\\TEMP
  macOS   : /Volumes/TRAVAUX EN COURS/Z2026/KIOSK/KIOSK GAUCHE
            /Volumes/TRAVAUX EN COURS/Z2026/KIOSK/KIOSK DROITE
            /Volumes/TRAVAUX EN COURS/Z2026/TEMP

Dépendances : modules standard (os, platform, pathlib, datetime)
"""

__version__ = "1.9.5"

#############################################################
#                          IMPORTS                          #
#############################################################
import platform
from pathlib import Path
from datetime import datetime, timedelta

#############################################################
#                         CONSTANTS                         #
#############################################################
DAYS = 60

if platform.system() == "Windows":
    FOLDERS = [
        Path("\\\\studioc-kiosk1\\kiosk-data\\it-HotFolder"),
        Path("\\\\studioc-kiosk2\\kiosk-data\\it-HotFolder"),
        Path("\\\\Diskstation\\travaux en cours\\z2026\\kiosk\\KIOSK GAUCHE"),
        Path("\\\\Diskstation\\travaux en cours\\z2026\\kiosk\\KIOSK DROITE"),
        Path("\\\\diskstation\\travaux en cours\\Z2026\\TEMP"),
    ]
else:
    FOLDERS = [
        Path("/Volumes/kiosk-data-1/it-HotFolder"),
        Path("/Volumes/kiosk-data-2/it-HotFolder"),
        Path("/Volumes/TRAVAUX EN COURS/Z2026/KIOSK/KIOSK GAUCHE"),
        Path("/Volumes/TRAVAUX EN COURS/Z2026/KIOSK/KIOSK DROITE"),
        Path("/Volumes/TRAVAUX EN COURS/Z2026/TEMP"),
    ]

#############################################################
#                           MAIN                            #
#############################################################
print(f"Nettoyage des fichiers de plus de {DAYS} jours...", flush=True)

limit = datetime.now() - timedelta(days=DAYS)
total_deleted = 0
total_size = 0

for folder in FOLDERS:
    print(f"\n{folder.name}", flush=True)
    print("=" * 40, flush=True)

    if not folder.exists():
        print(f"  [AVERTISSEMENT] Dossier inaccessible : {folder}", flush=True)
        continue

    deleted = 0
    size = 0

    for item in sorted(folder.rglob("*")):
        if item.is_file():
            try:
                mtime = datetime.fromtimestamp(item.stat().st_mtime)
                if mtime < limit:
                    file_size = item.stat().st_size
                    item.unlink()
                    print(f"  - {item.name}  ({mtime.strftime('%Y-%m-%d')})", flush=True)
                    deleted += 1
                    size += file_size
            except Exception as e:
                print(f"  [ERREUR] {item.name} : {e}", flush=True)

    # Supprimer les sous-dossiers vides après le nettoyage des fichiers
    # (sauf pour les HotFolders dont les sous-dossiers fixes doivent être conservés)
    if "HotFolder" not in str(folder):
        for subdir in sorted(folder.rglob("*"), key=lambda p: len(p.parts), reverse=True):
            if subdir.is_dir():
                try:
                    if not any(subdir.iterdir()):
                        subdir.rmdir()
                        print(f"  [Dossier vide supprimé] {subdir.name}", flush=True)
                except Exception:
                    pass

    if deleted == 0:
        print("  Aucun fichier a supprimer.", flush=True)
    else:
        print(f"\n  -> {deleted} fichier(s) supprimé(s) — {size / 1024 / 1024:.1f} Mo liberes", flush=True)

    total_deleted += deleted
    total_size += size

print(f"\n{'=' * 40}", flush=True)
if total_deleted == 0:
    print("Aucun fichier a supprimer.", flush=True)
else:
    print(f"Terminé : {total_deleted} fichier(s) supprimé(s) au total.", flush=True)
    print(f"Espace libéré : {total_size / 1024 / 1024:.1f} Mo", flush=True)
