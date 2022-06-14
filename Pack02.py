# -*- coding: utf-8 -*-
#############################################################
#                          IMPORTS                          #
#############################################################
from math import ceil
import os
import sys
import re
from PIL import Image, ImageOps, ImageFile

#############################################################
#                           SIZES                           #
#############################################################
PRINT_SIZE = (305, 203)
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
FORBIDDEN = ["10x15", "projet", "p1", "p2"]

#############################################################
#               CONVERT MM 300DPI TO PIXELS                 #
#############################################################
def pixel_size(size) :
    return (ceil((float(size) / 25.4) * DPI))

#############################################################
#                           MAIN                            #
#############################################################
PRINT_DPI = (pixel_size(PRINT_SIZE[0]), pixel_size(PRINT_SIZE[1]))
IMAGE_DPI = (pixel_size(PRINT_SIZE[0] //2), pixel_size(PRINT_SIZE[1]))
canvas = Image.new('RGB', PRINT_DPI, color=(255, 255, 255))

offset = 0
for file in FOLDER :
    file_name = re.search(r"([\w\s]+).\w+", file)
    if not any(forbidden_name in file_name.group(1).lower() for forbidden_name in FORBIDDEN) == True :
        IMAGES.append(file)

for index, image in enumerate(IMAGES) :
    os.system('cls' if os.name == 'nt' else 'clear')
    print(f"Image : {index + 1} sur {len(IMAGES)}")
    print("-" * 13)

    raw = Image.open(image)
    if raw.width < raw.height :
        landcape = raw.rotate(90, expand=True)
        portrait = raw

    else:
        landcape = raw
        portrait = raw.rotate(90, expand=True)

    big = ImageOps.fit(landcape, (PRINT_DPI)) # Full size (20x30cm)
    big.convert("RGB").save(f"{PATH}/P2_BIG_{image}", dpi=(DPI, DPI), format='JPEG', subsampling=0, quality=100)

    cropped = ImageOps.fit(portrait, (IMAGE_DPI)) # 2 side-by-side inside 20x30cm
    for instance in range(2) :
        canvas.paste(cropped, (offset, 0))
        offset += IMAGE_DPI[0]

    canvas.convert("RGB").save(f"{PATH}/P2_{image}", dpi=(DPI, DPI), format='JPEG', subsampling=0, quality=100)

print("Terminé !")
