# -*- coding: utf-8 -*-
"""
Renomme séquentiellement toutes les images d'un dossier (001.jpg, 002.jpg…).

Les fichiers sont triés alphabétiquement, puis renommés avec un index
à trois chiffres complété de zéros (``f"{index:03}{ext}"``). Un nom de série
optionnel peut être injecté via ``SERIES_NAME`` (préfixe : ``Serie_001.jpg``).

Variables d'environnement :
  FOLDER_PATH     — dossier source (défaut : répertoire du script).
  SELECTED_FILES  — liste de noms séparés par ``|`` (filtre optionnel).
  SERIES_NAME     — préfixe de série (optionnel).
  SERIES_CONTINUE — n° après lequel numéroter (vide = repartir à 001).
                    Nécessite SERIES_NAME. Les fichiers déjà nommés
                    « SERIES_NAME_NNN » restent en place.

Sécurité : si un nom cible existe déjà (et n'est pas lui-même renommé),
le script s'arrête AVANT de toucher au moindre fichier.

Dépendances : modules standard (os, re, pathlib)
"""

__version__ = "2.10.91"

#############################################################
#                          IMPORTS                          #
#############################################################
import os
import re
from pathlib import Path
import CONSTANTS

#############################################################
#                           PATH                            #
#############################################################
PATH = Path(os.environ.get("FOLDER_PATH", str(Path(__file__).resolve().parent)))
SERIES_NAME = os.environ.get("SERIES_NAME", "").strip()

#############################################################
#                         CONTENT                           #
#############################################################
# Récupérer les fichiers sélectionnés depuis Hub (si applicable)
selected_files_str = os.environ.get("SELECTED_FILES", "")
selected_files_list = selected_files_str.split("|") if selected_files_str else None

all_files = sorted([
    file.name
    for file in PATH.iterdir()
    if file.is_file()
    and not file.name.startswith(".")
    and file.name != "watermark.png"
])
if selected_files_list:
    all_files_set = set(all_files)
    FOLDER = [
        f for f in selected_files_list
        if f in all_files_set and not f.startswith(".")
    ]
else:
    FOLDER = all_files

# Continuer une série existante : SERIES_CONTINUE contient le n° après lequel
# numéroter (vide = repartir à 001). Les fichiers déjà nommés
# « SERIES_NAME_NNN » restent en place.
start = 1
raw = os.environ.get("SERIES_CONTINUE", "").strip()
if SERIES_NAME and raw.isdigit():
    start = int(raw) + 1
    pattern = re.compile(re.escape(SERIES_NAME) + r"_(\d{3,})$")
    FOLDER = [f for f in FOLDER if not pattern.match(Path(f).stem)]

#############################################################
#                         CIBLES                            #
#############################################################
# Calcul de tous les noms finaux avant de toucher au moindre fichier.
targets = []
for index, file in enumerate(FOLDER):
    ext = Path(file).suffix
    new_index = index + start
    if SERIES_NAME:
        targets.append(f"{SERIES_NAME}_{new_index:03}{ext}")
    else:
        targets.append(f"{new_index:03}{ext}")

# Une cible est en collision si elle existe déjà ET n'est pas elle-même
# un fichier qu'on s'apprête à renommer (la phase 1 le libère).
renamed = set(FOLDER)
collisions = [t for t in targets if (PATH / t).exists() and t not in renamed]
if collisions:
    raise SystemExit(
        "Collision, abandon sans rien renommer. Noms déjà pris : "
        + ", ".join(collisions[:5])
        + (" …" if len(collisions) > 5 else "")
    )

#############################################################
#                           MAIN                            #
#############################################################

# Phase 1 : noms temporaires pour éviter les collisions entre fichiers
# ponytail: deux passes, car Path.rename() écrase silencieusement la cible
temp_map = []
for index, file in enumerate(FOLDER):
    file_path = PATH / file
    ext = file_path.suffix
    temp = PATH / f"__seq_tmp_{index:06}{ext}"
    file_path.rename(temp)
    temp_map.append(temp)

# Phase 2 : noms finaux
for index, (temp, new_name) in enumerate(zip(temp_map, targets)):
    print(f"{index + 1} / {len(temp_map)}")
    temp.rename(PATH / new_name)