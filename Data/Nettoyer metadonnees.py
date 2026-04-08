# -*- coding: utf-8 -*-
"""
Supprime les métadonnées EXIF des images en les re-sauvegardant via Pillow.

Ouvre chaque image, la convertit en RGB (ce qui efface les métadonnées), puis
l'écrase sur place au format JPEG qualité maximale. Aucun sous-dossier n'est créé.

Variables d'environnement :
  FOLDER_PATH     — dossier source (défaut : répertoire du script).
  SELECTED_FILES  — liste de noms séparés par ``|`` (filtre optionnel).

Dépendances : Pillow (PIL)
"""

__version__ = "1.9.8"

#############################################################
#                          IMPORTS                          #
#############################################################
import os
from pathlib import Path
from PIL import Image

#############################################################
#                           PATH                            #
#############################################################
PATH = Path(os.environ.get("FOLDER_PATH", str(Path(__file__).resolve().parent)))

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

#############################################################
#                           MAIN                            #
#############################################################
for i, file in enumerate(FOLDER):
    print("Image {} sur {}".format(i+1, TOTAL))

    filename = Path(file).stem
    try:
        base_image = Image.open(PATH / file)
    except Exception:
        continue
    else:
        base_image.convert("RGB").save(str(PATH / f"{filename}.jpg"), format="JPEG", subsampling=0, quality=100)

print("Terminé !")