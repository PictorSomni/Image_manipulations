<<<<<<< HEAD
# -*- coding: utf-8 -*-

__version__ = "1.7.0"

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
series_name = os.environ.get("SERIES_NAME", "").strip()

for index, file in enumerate(FOLDER) :
    print(f"{index +1} / {len(FOLDER)}")
    file_path = PATH / file
    filename = file_path.stem
    ext = file_path.suffix
    new_index = index + 1

    if series_name:
        new_name = f"{series_name}_{new_index:03}{ext}"
    else:
        new_name = f"{new_index:03}{ext}"

    file_path.rename(PATH / new_name)
=======
# -*- coding: utf-8 -*-

__version__ = "1.7.0"

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
>>>>>>> f6665681ce24b14a5eda40c125e857b0d94923cf
sys.exit(1)