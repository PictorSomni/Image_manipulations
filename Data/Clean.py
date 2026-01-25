# -*- coding: utf-8 -*-
#############################################################
#                          IMPORTS                          #
#############################################################
from pathlib import Path
import os
from time import sleep
from PIL import Image

#############################################################
#                           PATH                            #
#############################################################
PATH = Path(__file__).resolve().parent

#############################################################
#                         CONTENT                           #
#############################################################
EXTENSION = (".JPG", ".JPEG", ".PNG", ".DNG")
FOLDER = [file.name for file in sorted(PATH.iterdir()) if file.is_file() and file.suffix.upper() in EXTENSION and file.name != "watermark.png"]
TOTAL = len(FOLDER)

#############################################################
#                           MAIN                            #
#############################################################
for i, file in enumerate(FOLDER):
    os.system('cls' if os.name == 'nt' else 'clear')
    print(f"Aurevoir EXIFS !")
    print("Image {} sur {}".format(i+1, TOTAL))

    filename = Path(file).stem
    try:
        base_image = Image.open(PATH / file)
    except Exception:
        continue
    else:
        base_image.convert("RGB").save(str(PATH / f"{filename}.jpg"), format="JPEG", subsampling=0, quality=100)

print("Terminé !")
sleep(1)
