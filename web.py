# -*- coding: utf-8 -*-

#############################################################
#                          IMPORTS                          #
#############################################################
import os
import sys
import re
import math
from PIL import Image, ImageOps, ImageFile

SIZE = 1080

#############################################################
#                           PATH                            #
#############################################################
PATH = os.path.dirname(os.path.abspath(__file__))
os.chdir(PATH)

#############################################################
#                         CONTENT                           #
#############################################################
ImageFile.LOAD_TRUNCATED_IMAGES = True

PATH = os.path.dirname(os.path.abspath(__file__))
os.chdir(PATH)

EXTENSION = (".jpg", ".jpeg", ".png", ".JPG", ".JPEG", ".PNG")
FOLDER = [file for file in sorted(os.listdir()) if file.endswith(EXTENSION) and not file == "watermark.png"]
TOTAL = len(FOLDER)

#############################################################
#                           MAIN                            #
#############################################################
if not os.path.exists(PATH + f"\\WEB") :
    os.makedirs(PATH + f"\\WEB")

for i, file in enumerate(FOLDER) :
    os.system('cls' if os.name == 'nt' else 'clear')
    print(f"Recadrage {SIZE} px")
    print("#" * 32 + "\n")
    print("Image {} sur {}".format(i+1, TOTAL))

    try :
        base_image = Image.open(file)
    except Exception :
        print(Exception)
    else :
        result = ImageOps.fit(base_image, (SIZE, SIZE))
        result = result.convert("RGB")
        result.save(f"{PATH}\\WEB\\{file}", dpi=(72, 72), format='JPEG', subsampling=0, quality=100)

print("Terminé !")
# input("Terminé !\nAppuyez sur une touche pour fermer")