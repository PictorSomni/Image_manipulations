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

__version__ = "2.3.0"

#############################################################
#                          IMPORTS                          #
#############################################################
import sys
import shutil
import platform
from pathlib import Path
from datetime import datetime, timedelta
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import CONSTANTS

#############################################################
#                         CONSTANTS                         #
#############################################################
DAYS = CONSTANTS.CLEAN_DAYS

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
    deleted_dirs = 0

    # 1. Supprimer les sous-dossiers anciens (et tout leur contenu) avec shutil.rmtree
    # (sauf pour les HotFolders dont les sous-dossiers fixes doivent être conservés)
    if "HotFolder" not in str(folder):
        dirs_to_delete = []
        for item in sorted(folder.rglob("*"), key=lambda p: len(p.parts)):
            if item.is_dir() and item.exists():
                try:
                    stat = item.stat()
                    # st_birthtime sur macOS, st_ctime (création) sur Windows
                    ctime = datetime.fromtimestamp(getattr(stat, "st_birthtime", stat.st_ctime))
                    if ctime < limit:
                        # Ne pas ajouter si un dossier parent est déjà dans la liste
                        if not any(item.is_relative_to(d) for d, _ in dirs_to_delete):
                            dirs_to_delete.append((item, ctime))
                except Exception:
                    pass

        for item, _ in dirs_to_delete:
            if not item.exists():
                continue
            try:
                # Comptabiliser les fichiers contenus
                for f in item.rglob("*"):
                    if f.is_file():
                        try:
                            size += f.stat().st_size
                            deleted += 1
                        except Exception:
                            pass
                shutil.rmtree(item)
                print(f"  [Dossier supprimé] {item.name}", flush=True)
                deleted_dirs += 1
            except Exception as e:
                print(f"  [ERREUR dossier] {item.name} : {e}", flush=True)

    # 2. Supprimer les fichiers anciens restants (non couverts par un dossier supprimé)
    to_delete = []
    for item in sorted(folder.rglob("*")):
        if item.is_file() and item.exists():
            try:
                mtime = datetime.fromtimestamp(item.stat().st_mtime)
                if mtime < limit:
                    to_delete.append((item, mtime))
            except Exception:
                pass

    total_to_delete = len(to_delete)
    for i, (item, mtime) in enumerate(to_delete, 1):
        try:
            file_size = item.stat().st_size
            item.unlink()
            print(f"\r  {i}/{total_to_delete}", end="", flush=True)
            deleted += 1
            size += file_size
        except Exception as e:
            print(f"\n  [ERREUR] {item.name} : {e}".encode(sys.stdout.encoding or 'utf-8', errors='replace').decode(sys.stdout.encoding or 'utf-8'), flush=True)
    if total_to_delete > 0:
        print(flush=True)  # saut de ligne après la progression

    if deleted == 0 and deleted_dirs == 0:
        print("  Aucun fichier a supprimer.", flush=True)
    else:
        if deleted > 0:
            print(f"\n  -> {deleted} fichier(s) supprimé(s) — {size / 1024 / 1024:.1f} Mo liberes", flush=True)
        if deleted_dirs > 0:
            print(f"  -> {deleted_dirs} dossier(s) vide(s) supprimé(s)", flush=True)

    total_deleted += deleted
    total_size += size

print(f"\n{'=' * 40}", flush=True)
if total_deleted == 0:
    print("Aucun fichier a supprimer.", flush=True)
else:
    print(f"Terminé : {total_deleted} fichier(s) supprimé(s) au total.", flush=True)
    print(f"Espace libéré : {total_size / 1024 / 1024:.1f} Mo", flush=True)
