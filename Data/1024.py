# -*- coding: utf-8 -*-
#############################################################
#                          IMPORTS                          #
#############################################################

import os
import sys
import re
from pathlib import Path
from PIL import Image, ImageFile, ImageOps

#############################################################
#                           PATH                            #
#############################################################
PATH = Path(__file__).resolve().parent
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
    EXTENSION = (".jpg", ".jpeg", ".png")
    FOLDER = [file for file in sorted(os.listdir()) if file.lower().endswith(EXTENSION) and not file == "watermark.png"]
    TOTAL = len(FOLDER)

#############################################################
#                           MAIN                            #
#############################################################

output_folder = PATH / f"{MAXSIZE[0]}px"
output_folder.mkdir(exist_ok=True)

for i, file in enumerate(FOLDER):
    print("Image {} sur {}".format(i+1, TOTAL))

    try:
        base_image = Image.open(file)
    except Exception:
        continue
    else:
        # Respect EXIF orientation first
        base_image = ImageOps.exif_transpose(base_image)
        base_image.thumbnail(MAXSIZE, Image.LANCZOS)
        base_image = base_image.convert("RGB")
        base_image.save(output_folder / file, format='JPEG', subsampling=0, quality=100)
        base_image.close()

print("Terminé !")
# input("Terminé !\nAppuyez sur une touche pour fermer")