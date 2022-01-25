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
WIDTH = 50     # mm
HEIGHT = 250   # mm
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

EXTENSION = (".jpg", ".jpeg", ".png", ".JPG", ".JPEG", ".PNG")
FOLDER = [file for file in sorted(os.listdir()) if file.endswith(EXTENSION) and not file == "watermark.png"]
TOTAL = len(FOLDER)
DUO = ["recto", "verso", "duo"]
DOUBLE = False
IMAGE_NAME = ""

#############################################################
#               CONVERT MM 300DPI TO PIXELS                 #
#############################################################
WIDTH_DPI = round((float(WIDTH) / 25.4) * DPI)
HEIGHT_DPI = round((float(HEIGHT) / 25.4) * DPI)

#############################################################
#                           MAIN                            #
#############################################################
if not os.path.exists(f"{PATH}\\2 en 1") :
    os.makedirs(f"{PATH}\\2 en 1")

index = 1
while len(FOLDER) > 0:
    os.system('cls' if os.name == 'nt' else 'clear')
    print("2 images sur 10x15")
    print("#" * 30)
    print(f"image {index} sur {TOTAL}")
    print("-" * 13)

    
    image1 = FOLDER.pop()
    if any(key_name in image1.lower() for key_name in DUO) == True:
        IMAGE_NAME = image1
        image2 = image1
        DOUBLE = True
    else :
        if len(FOLDER) < 1:
            image2 = image1
        else:
            image2 = FOLDER.pop()

    images = map(Image.open, [image1, image2])
    x_offset = 0
    try:
        new_image = Image.new('RGB', (WIDTH_DPI * 2, HEIGHT_DPI), color=(255, 255, 255, 255))
    except Exception:
        pass
    else:
        for image in images:
            if image.width > image.height:
                image = image.rotate(90, expand=True)

            hpercent = (HEIGHT_DPI/float(image.height))
            wsize = int((float(image.width)*float(hpercent)))
            cropped_image = image.resize((wsize, HEIGHT_DPI), Image.LANCZOS)
            
            new_image.paste(cropped_image, (x_offset, 0))
            x_offset += WIDTH_DPI


        if DOUBLE :
            new_image.save(f"{PATH}\\2 en 1\\2-en-1_{IMAGE_NAME}", dpi=(DPI, DPI), format='JPEG', subsampling=0, quality=100)
            DOUBLE = False
        else :
            new_image.save(f"{PATH}\\2 en 1\\2-en-1_{index:03}.jpg", dpi=(DPI, DPI), format='JPEG', subsampling=0, quality=100)

        index += 1

print("Terminé !")
