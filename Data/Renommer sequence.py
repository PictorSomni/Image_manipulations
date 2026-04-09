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

__version__ = "2.0.0"

#############################################################
#                          IMPORTS                          #
#############################################################
import os
from pathlib import Path
import sys

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
selected_files_set = set(selected_files_str.split("|")) if selected_files_str else None

EXTENSION = (".JPG", ".JPEG", ".PNG")
all_files = sorted([file.name for file in PATH.iterdir() if file.is_file() and file.suffix.upper() in EXTENSION and file.name != "watermark.png"])
FOLDER = sorted([f for f in all_files if f in selected_files_set]) if selected_files_set else all_files

#############################################################
#                           MAIN                            #
#############################################################

for index, file in enumerate(FOLDER) :
    print(f"{index +1} / {len(FOLDER)}")
    file_path = PATH / file
    filename = file_path.stem
    ext = file_path.suffix
    new_index = index + 1

    if SERIES_NAME:
        new_name = f"{SERIES_NAME}_{new_index:03}{ext}"
    else:
        new_name = f"{new_index:03}{ext}"

    file_path.rename(PATH / new_name)
sys.exit(1)