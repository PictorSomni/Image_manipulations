# -*- coding: utf-8 -*-
#############################################################
#                          IMPORTS                          #
#############################################################
import os
import sys
import re
from PIL import Image, ImageOps, ImageFile

#############################################################
#                           SIZES                           #
#############################################################
DPI = 300       # DPI

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

#############################################################
#                           MAIN                            #
#############################################################
PRINT_SIZE = (980, 1205)
IMAGE_SIZE = 835
POSITION = 73

canvas = Image.new('RGB', PRINT_SIZE, color=(255, 255, 255))

for file in FOLDER :
    file_name = re.search(r"([\w\s]+).\w+", file)
    if not "POLA_" in file_name.group(1).upper() :
        IMAGES.append(file)
        print(file)

for index, image in enumerate(IMAGES) :
    os.system('cls' if os.name == 'nt' else 'clear')
    print(f"Image : {index + 1} sur {len(IMAGES)}")
    print("-" * 13)
    raw = Image.open(image)
    cropped = ImageOps.fit(raw, (IMAGE_SIZE, IMAGE_SIZE))
    canvas.paste(cropped, (POSITION, POSITION))
    canvas.convert("RGB").save(f"{PATH}\\POLA_{image}", dpi=(DPI, DPI), format='JPEG', subsampling=0, quality=100)

print("Terminé !")
