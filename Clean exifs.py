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
EXTENSION = (".JPG", ".JPEG", ".PNG")
FOLDER = [file for file in sorted(os.listdir()) if file.upper().endswith(EXTENSION) and not file == "watermark.png"]
TOTAL = len(FOLDER)


def folder(folder) :
    if not os.path.exists(PATH + f"\\{folder}") :
        os.makedirs(PATH + f"\\{folder}")


#############################################################
#                           MAIN                            #
#############################################################
for i, file in enumerate(FOLDER):
    folder("CLEAN")
    os.system('cls' if os.name == 'nt' else 'clear')
    print(f"Aurevoir EXIFS !")
    print("Image {} sur {}".format(i+1, TOTAL))

    if file != "watermark.png":
        try:
            base_image = Image.open(file)
        except Exception:
            continue
        else:
            base_image.convert("RGB")
            base_image.save(f"{PATH}\\CLEAN\\{file}", format="JPEG", subsampling=0, quality=100)

print("Terminé !")
sleep(1)
# input("Terminé !\nAppuyez sur une touche pour fermer")
