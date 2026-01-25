# -*- coding: utf-8 -*-
#############################################################
#                          IMPORTS                          #
#############################################################

import os
import sys
from PIL import Image, ImageFile, ImageOps

#############################################################
#                           PATH                            #
#############################################################
PATH = Path(__file__).resolve().parent
os.chdir(PATH)

#############################################################
#                         CONTENT                           #
#############################################################

ImageFile.LOAD_TRUNCATED_IMAGES = True

# Récupérer la taille depuis la variable d'environnement
try:
    MAXSIZE_VALUE = int(os.environ.get("RESIZE_SIZE", "640"))
    MAXSIZE = (MAXSIZE_VALUE, MAXSIZE_VALUE)
except ValueError:
    print("Erreur : La variable d'environnement RESIZE_SIZE doit être un nombre.")
    sys.exit()

EXTENSION = (".jpg", ".jpeg", ".png", ".bmp", ".tiff", ".tif", ".webp")
FOLDER = [file for file in sorted(os.listdir()) if file.lower().endswith(EXTENSION) and not file == "watermark.png"]
TOTAL = len(FOLDER)

#############################################################
#                           MAIN                            #
#############################################################

if TOTAL == 0:
    print("Aucune image trouvée dans le dossier.")
    sys.exit()

output_folder = PATH / f"{MAXSIZE[0]}px"
output_folder.mkdir(exist_ok=True)

for i, file in enumerate(FOLDER):
    print(f"Image {i+1} sur {TOTAL}")

    try:
        base_image = Image.open(file)
    except Exception as e:
        print(f"Erreur lors de l'ouverture : {e}")
        continue
    else:
        # Respect EXIF orientation first
        base_image = ImageOps.exif_transpose(base_image)
        original_size = base_image.size
        
        # Thumbnail maintient le ratio et réduit uniquement si nécessaire
        base_image.thumbnail(MAXSIZE, Image.Resampling.LANCZOS)
        new_size = base_image.size
        filename, _ = os.path.splitext(file)
        base_image = base_image.convert("RGB")
        output_path = output_folder / f"{filename}.jpg"
        base_image.save(output_path, format='JPEG', subsampling=0, quality=100)
        base_image.close()
        
print("✓ Terminé !")
