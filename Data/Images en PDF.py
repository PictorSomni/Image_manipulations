# -*- coding: utf-8 -*-

__version__ = "1.6.0"

#############################################################
#                          IMPORTS                          #
#############################################################
import os
import sys
from pathlib import Path
from PIL import Image, ImageFile

#############################################################
#                           PATH                            #
#############################################################
PATH = Path(__file__).resolve().parent

#############################################################
#                         CONTENT                           #
#############################################################
ImageFile.LOAD_TRUNCATED_IMAGES = True

# Récupérer les fichiers sélectionnés depuis le Dashboard (si applicable)
selected_files_str = os.environ.get("SELECTED_FILES", "")
selected_files_set = set(selected_files_str.split("|")) if selected_files_str else None

EXTENSION = (".jpg", ".jpeg", ".png")
all_files = [file for file in sorted(PATH.iterdir()) if file.is_file() and file.suffix in EXTENSION and file.name != "watermark.png"]
IMAGE_FILES = [f for f in all_files if f.name in selected_files_set] if selected_files_set else all_files
TOTAL = len(IMAGE_FILES)

# Le nom du PDF est le nom du dossier parent
PDF_NAME = PATH.name

#############################################################
#                           MAIN                            #
#############################################################
print(f"Création d'un PDF à partir de {TOTAL} images")
print("~" * 39)

if TOTAL == 0:
    print("Aucune image trouvée !")
    sys.exit(1)

# Charger toutes les images
images = []
for index, img_file in enumerate(IMAGE_FILES, start=1):
    print(f"Image {index}/{TOTAL}: {img_file.name}...")
    try:
        images.append(Image.open(img_file))
    except Exception as e:
        print(f"Erreur lors du chargement de {img_file.name}: {e}")

if len(images) == 0:
    print("Aucune image valide trouvée !")
    sys.exit(1)

# Convertir toutes les images en RGB (nécessaire pour PDF)
rgb_images = []
for img in images:
    if img.mode == "RGBA":
        # Créer un fond blanc pour les images avec transparence
        rgb_img = Image.new("RGB", img.size, (255, 255, 255))
        rgb_img.paste(img, mask=img.split()[3] if len(img.split()) == 4 else None)
        rgb_images.append(rgb_img)
    elif img.mode != "RGB":
        rgb_images.append(img.convert("RGB"))
    else:
        rgb_images.append(img)

# Sauvegarder le PDF
first = rgb_images[0]
pdf_path = PATH / f"{PDF_NAME}.pdf"

if len(rgb_images) > 1:
    first.save(str(pdf_path), "PDF", resolution=100.0, save_all=True, append_images=rgb_images[1:])
else:
    first.save(str(pdf_path), "PDF", resolution=100.0)

print(f"[OK] PDF créé avec succès: {PDF_NAME}.pdf")
