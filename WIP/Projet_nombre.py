# -*- coding: utf-8 -*-
#############################################################
#                          IMPORTS                          #
#############################################################

import os
import sys
import re
from PIL import Image

PROJECT = False
WATERMARK = False
MAXSIZE = 480

#############################################################
#                           PATH                            #
#############################################################

PATH = os.path.dirname(os.path.abspath(__file__))
os.chdir(PATH)

#############################################################
#                         CONTENT                           #
#############################################################

EXTENSION = (".jpg", ".jpeg", ".png", ".JPG", ".JPEG", ".PNG")
FOLDER = [file for file in sorted(os.listdir()) if file.endswith(EXTENSION) and not file == "watermark.png"]
TOTAL = len(FOLDER)

file_name = re.search(r"([\w\s]+).py", sys.argv[0])
if "PROJET" in file_name.group(1).upper() :
    PROJECT = True

if "watermark.png" in os.listdir() :
    WATERMARK = True

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
            name = re.search(r"_(\d+).", file)
            save_name = name.group(1)
            base_image.thumbnail((MAXSIZE,MAXSIZE), Image.LANCZOS)

            if WATERMARK:
                watermark = Image.open("watermark.png")
                base_image.paste(watermark, watermark)

            if PROJECT :
                base_image.save("{}/{}.jpg".format(PATH, save_name))
            else :        
                base_image.save("{}/{}_{:03}.jpg".format(PATH, file_name.group(1), i))

print("Terminé !")
# input("Terminé !\nAppuyez sur une touche pour fermer")
