# -*- coding: utf-8 -*-
#############################################################
#                          IMPORTS                          #
#############################################################
import os
import sys
import re
from time import sleep
from PIL import Image

#############################################################
#                           PATH                            #
#############################################################
PATH = os.path.dirname(os.path.abspath(__file__))
os.chdir(PATH)

#############################################################
#                         CONTENT                           #
#############################################################
EXTENSION = (".JPG", ".JPEG", ".PNG", ".DNG")
FOLDER = [file for file in sorted(os.listdir()) if file.upper().endswith(EXTENSION) and not file == "watermark.png"]
TOTAL = len(FOLDER)

#############################################################
#                           MAIN                            #
#############################################################
for i, file in enumerate(FOLDER):
    os.system('cls' if os.name == 'nt' else 'clear')
    print(f"Aurevoir EXIFS !")
    print("Image {} sur {}".format(i+1, TOTAL))

    filename = file.split(".")[0]
    try:
        base_image = Image.open(file)
    except Exception:
        continue
    else:
        base_image.convert("RGB").save(f"{PATH}\\{filename}.jpg", format="JPEG", subsampling=0, quality=100)

print("Terminé !")
sleep(1)
