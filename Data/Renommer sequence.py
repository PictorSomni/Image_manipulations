# -*- coding: utf-8 -*-

__version__ = "1.6.9"

#############################################################
#                          IMPORTS                          #
#############################################################
import os
from pathlib import Path
import sys

#############################################################
#                           PATH                            #
#############################################################
PATH = Path(__file__).resolve().parent

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

    new_name = f"{new_index:03}{ext}"

    file_path.rename(PATH / new_name)
sys.exit(1)