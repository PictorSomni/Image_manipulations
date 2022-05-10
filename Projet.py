# -*- coding: utf-8 -*-

#############################################################
#                          IMPORTS                          #
#############################################################

import os
import sys
import re
from time import sleep
from PIL import Image

PROJECT = False
WATERMARK = False
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

EXTENSION = (".JPG", ".JPEG", ".PNG", "GIF")
FOLDER = [file for file in sorted(os.listdir()) if file.upper().endswith(EXTENSION) and not file == "watermark.png"]
TOTAL = len(FOLDER)

file_name = re.search(r"([\w\s]+).py", sys.argv[0])
if "PROJET" in file_name.group(1).upper() :
    PROJECT = True

if "watermark.png" in os.listdir() :
    WATERMARK = True


def folder(folder) :
    if not os.path.exists(PATH + f"\\{folder}") :
        os.makedirs(PATH + f"\\{folder}")


#############################################################
#                           MAIN                            #
#############################################################

for i, file in enumerate(FOLDER):
    os.system('cls' if os.name == 'nt' else 'clear')
    print(f"Conversion en {MAXSIZE}px + renommage ({file_name.group(1)}) + filigrane")
    print("Image {} sur {}".format(i+1, TOTAL))

    if file != "watermark.png":
        try:
            base_image = Image.open(file)
        except Exception:
            continue
        else:
            base_image.thumbnail((MAXSIZE,MAXSIZE), Image.LANCZOS)
            folder("projet")

            if WATERMARK:
                watermark = Image.open("watermark.png")
                base_image.paste(watermark, watermark)

            if PROJECT :
                base_image.convert("RGB").save(f"{PATH}\\projet\\Projet_{file}", format="JPEG", subsampling=0, quality=QUALITY)
            else :
                base_image.convert("RGB").save("{PATH}\\projet\\{file_name.group(1)}_{i:03}.jpg", format="JPEG", subsampling=0, quality=QUALITY)

print("Terminé !")
sleep(1)
# input("Terminé !\nAppuyez sur une touche pour fermer")
