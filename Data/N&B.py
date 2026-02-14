# -*- coding: utf-8 -*-

__version__ = "1.6.3"

#############################################################
#                          IMPORTS                          #
#############################################################
import os
from pathlib import Path
from PIL import Image

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

EXTENSION = (".JPG", ".JPEG", ".PNG", ".DNG")
all_files = [file.name for file in sorted(PATH.iterdir()) if file.is_file() and file.suffix.upper() in EXTENSION and file.name != "watermark.png"]
FOLDER = [f for f in all_files if f in selected_files_set] if selected_files_set else all_files
TOTAL = len(FOLDER)

def folder(folder) :
    folder_path = PATH / folder
    folder_path.mkdir(exist_ok=True)

#############################################################
#                           MAIN                            #
#############################################################
for i, file in enumerate(FOLDER):
    print("Image {} sur {}".format(i+1, TOTAL))
    folder("N&B")

    filename = Path(file).stem
    try:
        base_image = Image.open(PATH / file)
    except Exception:
        continue
    else:
        base_image.convert("L").save(str(PATH / "N&B" / f"{filename}.jpg"), format="JPEG", subsampling=0, quality=100)

print("Terminé !")