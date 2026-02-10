# -*- coding: utf-8 -*-
#############################################################
#                          IMPORTS                          #
#############################################################
from pathlib import Path
import os
import re
from PIL import Image, ImageOps, ImageFile
#############################################################
#                           SIZE                            #
#############################################################
WIDTH = 76      # mm
HEIGHT = 102    # mm
DPI = 300       # DPI
MAXSIZE = 512
QUALITY = 75
ALPHA = 0.42

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
ImageFile.LOAD_TRUNCATED_IMAGES = True

EXTENSION = (".jpg", ".jpeg", ".png")
FOLDER = [file.name for file in sorted(PATH.iterdir()) if file.is_file() and file.suffix.lower() in EXTENSION and file.name != "watermark.png"]
WATERMARK = str(DATA_PATH / "watermark.png")
REQUIRED = ["recto", "verso", "duo", "_1", "_2"]
BIG = ["int", "ext"]
FORBIDDEN = ["10x15", "13x18", "projet"]
duo = True

#############################################################
#               CONVERT MM 300DPI TO PIXELS                 #
#############################################################
WIDTH_DPI = round((float(WIDTH) / 25.4) * DPI)
HEIGHT_DPI = round((float(HEIGHT) / 25.4) * DPI)

#############################################################
#                           MAIN                            #
#############################################################
IMAGES = []  # Initialiser la liste des images
new_image = Image.new('RGB', (WIDTH_DPI * 2, HEIGHT_DPI))

for i, file in enumerate(FOLDER) :
    file_name = re.search(r"([\w\s]+).\w+", file)

    if any(required_name in file_name.group(1).lower() for required_name in REQUIRED) == True and not any(forbidden_name in file_name.group(1).lower() for forbidden_name in FORBIDDEN) == True :
        IMAGES.append(file)

    elif any(big_name in file_name.group(1).lower() for big_name in BIG) == True and not any(forbidden_name in file_name.group(1).lower() for forbidden_name in FORBIDDEN) == True :
        duo = False
        IMAGES.append(file)

for image in IMAGES :
    base_image = Image.open(image)
    print(f"{image} : Trouvée")
    if "_1" in image.lower() or "_2" in image.lower() :
        image = image.replace("_1", "_recto").replace("_2", "_verso")
    project = base_image.copy()
    project.thumbnail((MAXSIZE,MAXSIZE))
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
        project.paste(watermark, watermark)
        project.convert("RGB").save(PATH / f"Projet_{image}", format="JPEG", subsampling=0, quality=QUALITY)
        print(f"{image} : Projet OK")

    if duo == True :
        if base_image.width > base_image.height:
            base_image = base_image.rotate(90, expand=True)

        cropped_image = ImageOps.fit(base_image, (WIDTH_DPI, HEIGHT_DPI))
        new_image.paste(cropped_image, (0, 0))
        new_image.paste(cropped_image, (WIDTH_DPI, 0))
        new_image.convert("RGB").save(PATH / f"10x15_{image}", dpi=(DPI, DPI), format='JPEG', subsampling=0, quality=100)
        print(f"{image} : 2 en 1 OK")

print("Terminé !")
