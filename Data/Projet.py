# -*- coding: utf-8 -*-

__version__ = "1.6.8"

#############################################################
#                          IMPORTS                          #
#############################################################
from pathlib import Path
import os
from PIL import Image

PROJECT = False
WATERMARK = False
MAXSIZE = 640
QUALITY = 80
ALPHA = 0.35

#############################################################
#                           PATH                            #
#############################################################
PATH = Path(__file__).resolve().parent

# Récupère le chemin du dossier Data depuis l'environnement (si lancé via Dashboard)
# Sinon utilise le dossier parent du script
DATA_PATH = Path(os.environ.get("DATA_PATH", PATH))

#############################################################
#                         CONTENT                           #
#############################################################
# Récupérer les fichiers sélectionnés depuis le Dashboard (si applicable)
selected_files_str = os.environ.get("SELECTED_FILES", "")
selected_files_set = set(selected_files_str.split("|")) if selected_files_str else None

EXTENSION = (".JPG", ".JPEG", ".PNG", ".GIF")
all_files = [file.name for file in sorted(PATH.iterdir()) if file.is_file() and file.suffix.upper() in EXTENSION and file.name != "watermark.png"]
FOLDER = [f for f in all_files if f in selected_files_set] if selected_files_set else all_files
WATERMARK = str(DATA_PATH / "watermark.png")
TOTAL = len(FOLDER)
EXCEPTIONS = ("projet", "fogra29")

def folder(folder) :
    folder_path = PATH / folder
    folder_path.mkdir(exist_ok=True)

#############################################################
#                           MAIN                            #
#############################################################
folder("Projet")
for i, file in enumerate(FOLDER):
    print(f"Image {i+1} sur {TOTAL}")
    if any(exception_name in file.lower() for exception_name in EXCEPTIONS):
        print("Image ignorée (exception)")
        continue

    try:
        base_image = Image.open(file)
    except Exception:
        continue
    else:
        base_image.thumbnail((MAXSIZE,MAXSIZE), Image.Resampling.LANCZOS)

    try:
        watermark = Image.open(WATERMARK)
        if watermark.mode != "RGBA":
            watermark = watermark.convert("RGBA")

        r, g, b, a = watermark.split()
        a = a.point(lambda i: i * ALPHA)
        watermark = Image.merge("RGBA", (r, g, b, a))
    except Exception:
        watermark = Image.open("watermark.png")
        continue
    else :
        base_image.paste(watermark, watermark)
        filename = Path(file).stem
        output_folder = PATH / "Projet"
        output_folder.mkdir(exist_ok=True)
        base_image.convert("RGB").save(str(output_folder / f"{filename}.jpg"), format="JPEG", subsampling=0, quality=QUALITY)

print("Terminé !")