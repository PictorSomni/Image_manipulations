# -*- coding: utf-8 -*-
"""
Réduit la qualité JPEG d'une série d'images (dossier ET sous-dossiers) sans
changer leur résolution. Pensé pour l'export web.

Corrige l'orientation EXIF via ``ImageOps.exif_transpose`` et sauvegarde
dans ``web/`` en reproduisant l'arborescence d'origine.

Variables d'environnement :
  FOLDER_PATH   — dossier source (défaut : répertoire du script).
  WEB_QUALITY   — qualité JPEG de sortie, 0-100 (défaut : CONSTANTS.WEB_QUALITY).

Dépendances : Pillow (PIL)
"""

__version__ = "3.0.5"

#############################################################
#                          IMPORTS                          #
#############################################################
import os
import sys
from pathlib import Path
from PIL import Image, ImageFile, ImageOps
sys.path.insert(0, str(Path(__file__).resolve().parent))
import CONSTANTS

#############################################################
#                           PATH                            #
#############################################################
PATH = Path(os.environ.get("FOLDER_PATH", str(Path(__file__).resolve().parent)))
os.chdir(PATH)

#############################################################
#                         CONTENT                           #
#############################################################
ImageFile.LOAD_TRUNCATED_IMAGES = True

try:
    QUALITY = int(os.environ.get("WEB_QUALITY", str(CONSTANTS.WEB_QUALITY)))
except ValueError:
    print("Erreur : La variable d'environnement WEB_QUALITY doit être un nombre.")
    sys.exit()

EXTENSION = (".jpg", ".jpeg", ".png", ".bmp", ".tiff", ".tif", ".webp")
OUTPUT_FOLDER_NAME = "web"

all_files = [
    file for file in sorted(PATH.rglob("*"))
    if file.is_file()
    and file.suffix.lower() in EXTENSION
    and OUTPUT_FOLDER_NAME not in file.relative_to(PATH).parts
]
TOTAL = len(all_files)

#############################################################
#                           MAIN                            #
#############################################################
if TOTAL == 0:
    print("Aucune image trouvée dans le dossier.")
    sys.exit()

for i, file in enumerate(all_files):
    print(f"{i+1}/{TOTAL}")

    output_dir = PATH / OUTPUT_FOLDER_NAME / file.parent.relative_to(PATH)
    output_dir.mkdir(parents=True, exist_ok=True)

    try:
        image = Image.open(file)
    except Exception as e:
        print(f"Erreur lors de l'ouverture : {e}")
        continue
    else:
        image = ImageOps.exif_transpose(image)
        image = image.convert("RGB")
        output_path = output_dir / f"{file.stem}.jpg"
        image.save(output_path, format="JPEG", quality=QUALITY)
        image.close()

print("Terminé !")
