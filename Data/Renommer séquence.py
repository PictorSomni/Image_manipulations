# -*- coding: utf-8 -*-
"""
Renomme séquentiellement toutes les images d'un dossier (001.jpg, 002.jpg…).

Les fichiers sont triés alphabétiquement, puis renommés avec un index
à trois chiffres complété de zéros (``f"{index:03}{ext}"``). Un nom de série
optionnel peut être injecté via ``SERIES_NAME`` (non utilisé dans la version
actuelle du script, réservé pour usage futur).

Variables d'environnement :
  FOLDER_PATH     — dossier source (défaut : répertoire du script).
  SELECTED_FILES  — liste de noms séparés par ``|`` (filtre optionnel).
  SERIES_NAME     — préfixe de série (optionnel, non utilisé actuellement).

Dépendances : modules standard (os, pathlib, sys)
"""

__version__ = "3.0.6"

#############################################################
#                          IMPORTS                          #
#############################################################
import os
from pathlib import Path
import sys
import CONSTANTS

#############################################################
#                           PATH                            #
#############################################################
PATH = Path(os.environ.get("FOLDER_PATH", str(Path(__file__).resolve().parent)))
SERIES_NAME = os.environ.get("SERIES_NAME", "").strip()

#############################################################
#                         CONTENT                           #
#############################################################
# Récupérer les fichiers sélectionnés depuis le Dashboard (si applicable)
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
    temp_map.append((temp, ext))

# Phase 2 : noms finaux
for index, (temp, ext) in enumerate(temp_map):
    new_index = index + 1
    print(f"{new_index} / {len(temp_map)}")
    if SERIES_NAME:
        new_name = f"{SERIES_NAME}_{new_index:03}{ext}"
    else:
        new_name = f"{new_index:03}{ext}"
    temp.rename(PATH / new_name)

sys.exit(1)