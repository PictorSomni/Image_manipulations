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
SIZES = [[127, 178], [89, 127], [89, 127], [35, 45], [35, 45]]
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
    return (round((float(size) / 25.4) * DPI))

#############################################################
#                           MAIN                            #
#############################################################
PRINT_DPI = (pixel_size(PRINT_SIZE[0]), pixel_size(PRINT_SIZE[1]))
canvas = Image.new('RGB', PRINT_DPI, color=(255, 255, 255))

for file in FOLDER :
    file_name = re.search(r"([\w\s]+).\w+", file)
    if not any(forbidden_name in file_name.group(1).lower() for forbidden_name in FORBIDDEN) == True :
        IMAGES.append(file)

for index, image in enumerate(IMAGES) :
    os.system('cls' if os.name == 'nt' else 'clear')
    print(f"Image : {index + 1} sur {len(IMAGES)}")
    print("-" * 13)
    POSITIONS = [[0.0, 0.0], [0.417, 0.0], [0.417, 0.439], [0.834, 0.0], [0.834, 0.173]]

    raw = Image.open(image)
    size_dpi = (0,0)

    for size in SIZES :
        if size == SIZES[0] :
            if raw.width > raw.height :
                raw = raw.rotate(90, expand=True)

            size_dpi = (pixel_size(size[0]), pixel_size(size[1]))

        else :
            if raw.width < raw.height :
                raw = raw.rotate(90, expand=True)

            size_dpi = (pixel_size(size[1]), pixel_size(size[0]))
        
        cropped = ImageOps.fit(raw, (size_dpi))
        position = POSITIONS.pop(0)
        canvas.paste(cropped, (round(canvas.width * position[0]), round(canvas.height * position[1])))

    canvas.convert("RGB").save(f"{PATH}/P1_{image}", dpi=(DPI, DPI), format='JPEG', subsampling=0, quality=100)

print("Terminé !")
