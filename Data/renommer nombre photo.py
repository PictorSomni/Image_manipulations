# -*- coding: utf-8 -*-

__version__ = "1.6.4"

#############################################################
#                          IMPORTS                          #
#############################################################
import os
from pathlib import Path
import sys
import re

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

EXTENSION = (".JPG", ".JPEG", ".PNG", ".PSD", ".PSB", ".AF", ".NEF", ".CR2", ".ARW", ".DNG", ".TIFF", ".TIF")
all_files = [file.name for file in PATH.iterdir() if file.is_file() and file.suffix.upper() in EXTENSION and file.name != "watermark.png"]
FOLDER = [f for f in all_files if f in selected_files_set] if selected_files_set else all_files

#############################################################
#                           MAIN                            #
#############################################################
for i, file in enumerate(FOLDER):
    print(f"Image {i+1} sur {len(FOLDER)}")
    file_path = PATH / file
    filename = file_path.stem
    ext = file_path.suffix
    
    digits = re.findall(r"\d+", filename)
    
    if digits:
        # Concatène tous les groupes de chiffres
        number = "".join(digits)
        number = number[-4:]  # Limite aux 4 derniers chiffres
        file_path.rename(PATH / f"{number}{ext}")
    
sys.exit(1)