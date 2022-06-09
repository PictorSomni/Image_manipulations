# -*- coding: utf-8 -*-
#############################################################
#                          IMPORTS                          #
#############################################################
import os
from pickle import FALSE
import sys
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

#############################################################
#                           PATH                            #
#############################################################
PATH = os.path.dirname(os.path.abspath(__file__))
os.chdir(PATH)

#############################################################
#                         CONTENT                           #
#############################################################
ImageFile.LOAD_TRUNCATED_IMAGES = True

EXTENSION = (".jpg", ".jpeg", ".png")
FOLDER = [file for file in sorted(os.listdir()) if file.lower().endswith(EXTENSION) and not file == "watermark.png"]
IMAGES = []
REQUIRED = ["recto", "verso", "duo"]
FORBIDDEN = ["10x15", "projet"]

#############################################################
#               CONVERT MM 300DPI TO PIXELS                 #
#############################################################
WIDTH_DPI = round((float(WIDTH) / 25.4) * DPI)
HEIGHT_DPI = round((float(HEIGHT) / 25.4) * DPI)

#############################################################
#                           MAIN                            #
#############################################################
os.system('cls' if os.name == 'nt' else 'clear')
print("Remerciements Funéraires")
print("#" * 30 + "\n")

new_image = Image.new('RGB', (WIDTH_DPI * 2, HEIGHT_DPI))

for file in FOLDER :
    file_name = re.search(r"([\w\s]+).\w+", file)
    if any(required_name in file_name.group(1).lower() for required_name in REQUIRED) == True and any(forbidden_name in file_name.group(1).lower() for forbidden_name in FORBIDDEN) == FALSE :
        IMAGES.append(file)

for image in IMAGES :
    base_image = Image.open(image)

    project = base_image.copy()
    project.thumbnail((MAXSIZE,MAXSIZE))
    watermark = Image.open("watermark.png")
    project.paste(watermark, watermark)
    project.convert("RGB").save(f"{PATH}\\Projet_{image}", format="JPEG", subsampling=0, quality=QUALITY)
    print(f"{image} : Projet OK")

    cropped_image = ImageOps.fit(base_image, (WIDTH_DPI, HEIGHT_DPI))
    new_image.paste(cropped_image, (0, 0))
    new_image.paste(cropped_image, (WIDTH_DPI, 0))
    new_image.save(f"{PATH}\\10x15_{image}", dpi=(DPI, DPI), format='JPEG', subsampling=0, quality=100)
    print(f"{image} : 2 en 1 OK")

print("Terminé !")
