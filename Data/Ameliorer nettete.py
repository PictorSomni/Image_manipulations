# -*- coding: utf-8 -*-
"""
Améliore la netteté d'un lot d'images par filtre UnsharpMask en deux passes.

Applique ``ImageFilter.UnsharpMask`` (radius=4, percent=42) puis
(radius=2, percent=42) à chaque image et sauvegarde le résultat en JPEG
qualité maximale dans un sous-dossier ``NET/``.

Variables d'environnement :
  FOLDER_PATH     — dossier source (défaut : répertoire du script).
  SELECTED_FILES  — liste de noms séparés par ``|`` (filtre optionnel).

Dépendances : Pillow (PIL)
"""

__version__ = "1.7.6"

#############################################################
#                          IMPORTS                          #
#############################################################
import os
from pathlib import Path
from PIL import Image, ImageFilter

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

EXTENSION = (".JPG", ".JPEG", ".PNG")
all_files = [file.name for file in sorted(PATH.iterdir()) if file.is_file() and file.suffix.upper() in EXTENSION and file.name != "watermark.png"]
FOLDER = [f for f in all_files if f in selected_files_set] if selected_files_set else all_files
TOTAL = len(FOLDER)


def folder(folder) :
    """Crée le sous-dossier ``folder`` dans PATH s'il n'existe pas encore."""
    folder_path = PATH / folder
    folder_path.mkdir(exist_ok=True)

#############################################################
#                           MAIN                            #
#############################################################
for i, file in enumerate(FOLDER):
    folder("NET")
    print("Image {} sur {}".format(i+1, TOTAL))

    if file != "watermark.png":
        try:
            base_image = Image.open(PATH / file)
        except Exception:
            continue
        else:
            base_image.convert("RGB")
            # base_image = base_image.filter(ImageFilter.EDGE_ENHANCE)
            base_image = base_image.filter(ImageFilter.UnsharpMask(radius=4, percent=42, threshold=0))
            base_image = base_image.filter(ImageFilter.UnsharpMask(radius=2, percent=42, threshold=0))
            # base_image = base_image.filter(ImageFilter.SHARPEN)
            output_folder = PATH / "NET"
            output_folder.mkdir(exist_ok=True)
            base_image.save(str(output_folder / file), format="JPEG", subsampling=0, quality=100)

print("Terminé !")
