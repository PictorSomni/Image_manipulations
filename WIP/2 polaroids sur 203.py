# -*- coding: utf-8 -*-
#############################################################
#                          IMPORTS                          #
#############################################################
import os
import sys
import re
from time import sleep
from PIL import Image, ImageOps , ImageFile

#############################################################
#                           SIZE                            #
#############################################################
DPI = 300      # DPI

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
FOLDER = [file for file in sorted(os.listdir()) if file.lower().endswith(EXTENSION)]
DOUBLE = False
IMAGE_NAME = ""
PRINT_SIZE = (2400, 1500)
POSITION = 1200
IMAGES = []
#############################################################
#                           MAIN                            #
#############################################################
index = 1
for file in FOLDER :
    file_name = re.search(r"([\w\s]+).\w+", file)
    if "POLA_" in file_name.group(1).upper() :
        IMAGES.append(file)
        print(file)

for index, image in enumerate(IMAGES):
    os.system('cls' if os.name == 'nt' else 'clear')
    print("2 pola sur 10x15")
    print("#" * 30)
    print(f"Image : {index + 1} sur {len(IMAGES)}")
    print("-" * 13)

    
    image1 = IMAGES.pop()
    if len(IMAGES) < 1:
        image2 = image1
    else:
        image2 = IMAGES.pop()

    images = map(Image.open, [image1, image2])
    offset = 0
    try:
        new_image = Image.new('RGB', PRINT_SIZE, color=(255, 255, 255))
    except Exception:
        pass
    else:
        for image in images:
            new_image.paste(image, (offset, 0))
            offset += POSITION


        if DOUBLE :
            new_image.save(f"{PATH}\\D_{IMAGE_NAME}", dpi=(DPI, DPI), format='JPEG', subsampling=0, quality=100)
            DOUBLE = False
        else :
            new_image.save(f"{PATH}\\D_{index:03}.jpg", dpi=(DPI, DPI), format='JPEG', subsampling=0, quality=100)

        index += 1

print("Terminé !")
