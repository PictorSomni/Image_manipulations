# -*- coding: utf-8 -*-
#############################################################
#                          IMPORTS                          #
#############################################################

import os
import sys
import re
from PIL import Image, ImageFile

#############################################################
#                           PATH                            #
#############################################################

PATH = os.path.dirname(os.path.abspath(__file__))
os.chdir(PATH)

#############################################################
#                         CONTENT                           #
#############################################################

ImageFile.LOAD_TRUNCATED_IMAGES = True

file_name = re.search(r"(\d+)\s?\w?.py", sys.argv[0])

try :
    MAXSIZE = (int(file_name.group(1)), int(file_name.group(1)))
except Exception :
    input("Erreur : Le nom de l'executable doit être un nombre.")
    sys.exit()
else :
    EXTENSION = (".jpg", ".jpeg", ".png", ".JPG", ".JPEG", ".PNG")
    FOLDER = [file for file in sorted(os.listdir()) if file.endswith(EXTENSION) and not file == "watermark.png"]
    TOTAL = len(FOLDER)

#############################################################
#                           MAIN                            #
#############################################################

if not os.path.exists(PATH + f"\\{MAXSIZE[0]}px") :
    os.makedirs(PATH + f"\\{MAXSIZE[0]}px")

for i, file in enumerate(FOLDER):
    os.system('cls' if os.name == 'nt' else 'clear')
    print(f"Conversion en {MAXSIZE[0]} px")
    print("Image {} sur {}".format(i+1, TOTAL))


    try:
        base_image = Image.open(file)
    except Exception:
        continue
    else:
        base_image.thumbnail(MAXSIZE, Image.ANTIALIAS)

        # base_image.save("{}\\{}px\\{:03}.jpg".format(PATH, MAXSIZE[0], i), format='JPEG', subsampling=0, quality=100)
        base_image.save("{}\\{}px\\{}".format(PATH, MAXSIZE[0], file), format='JPEG', subsampling=0, quality=100)

print("Terminé !")
# input("Terminé !\nAppuyez sur une touche pour fermer")