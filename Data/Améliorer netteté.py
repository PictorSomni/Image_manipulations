# -*- coding: utf-8 -*-
"""
Améliore la netteté d'un lot d'images par filtre UnsharpMask en deux passes.

Applique ``ImageFilter.UnsharpMask`` (radius=4, percent=42) puis
(radius=2, percent=42) à chaque image et sauvegarde le résultat en JPEG
qualité maximale dans un sous-dossier ``NETTES/``.

Variables d'environnement :
  FOLDER_PATH     — dossier source (défaut : répertoire du script).
  SELECTED_FILES  — liste de noms séparés par ``|`` (filtre optionnel).

Dépendances : Pillow (PIL)
"""

__version__ = "2.8.8"

#############################################################
#                          IMPORTS                          #
#############################################################
import os
from pathlib import Path
from PIL import Image, ImageFilter

#############################################################
#                           PATH                            #
#############################################################
folder_path = Path(os.environ.get("FOLDER_PATH", str(Path(__file__).resolve().parent)))

#############################################################
#                         CONTENT                           #
#############################################################
# Récupérer les fichiers sélectionnés depuis le Dashboard (si applicable)
selected_files_string = os.environ.get("SELECTED_FILES", "")
selected_files_set = set(selected_files_string.split("|")) if selected_files_string else None

image_extensions = (".JPG", ".JPEG", ".PNG")
all_files = [file.name for file in sorted(folder_path.iterdir()) if file.is_file() and file.suffix.upper() in image_extensions and file.name != "watermark.png"]
files_to_process = [file_name for file_name in all_files if file_name in selected_files_set] if selected_files_set else all_files
total_files_count = len(files_to_process)


def create_folder(folder_name):
    """Crée le sous-dossier ``folder_name`` dans folder_path s'il n'existe pas encore."""
    new_folder_path = folder_path / folder_name
    new_folder_path.mkdir(exist_ok=True)

#############################################################
#                           MAIN                            #
#############################################################
for index, file_name in enumerate(files_to_process):
    create_folder("NETTES")
    print(f"Image {index + 1} sur {total_files_count}")

    if file_name != "watermark.png":
        try:
            base_image = Image.open(folder_path / file_name)
        except Exception:
            continue
        else:
            base_image.convert("RGB")
            # base_image = base_image.filter(ImageFilter.EDGE_ENHANCE)
            base_image = base_image.filter(ImageFilter.UnsharpMask(radius=4, percent=42, threshold=0))
            base_image = base_image.filter(ImageFilter.UnsharpMask(radius=2, percent=42, threshold=0))
            # base_image = base_image.filter(ImageFilter.SHARPEN)
            output_folder = folder_path / "NETTES"
            output_folder.mkdir(exist_ok=True)
            base_image.save(str(output_folder / file_name), format="JPEG", subsampling=0, quality=100)

print("Terminé !")
