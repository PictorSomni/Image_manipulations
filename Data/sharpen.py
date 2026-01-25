# -*- coding: utf-8 -*-
#############################################################
#                          IMPORTS                          #
#############################################################
from pathlib import Path
import sys
import re
from time import sleep
from PIL import Image, ImageFilter



#############################################################
#                           PATH                            #
#############################################################
PATH = Path(__file__).resolve().parent

#############################################################
#                         CONTENT                           #
#############################################################
EXTENSION = (".JPG", ".JPEG", ".PNG")
FOLDER = [file.name for file in sorted(PATH.iterdir()) if file.is_file() and file.suffix.upper() in EXTENSION and file.name != "watermark.png"]
TOTAL = len(FOLDER)


def folder(folder) :
    folder_path = PATH / folder
    folder_path.mkdir(exist_ok=True)


#############################################################
#                           MAIN                            #
#############################################################
for i, file in enumerate(FOLDER):
    folder("NET")
    os.system('cls' if os.name == 'nt' else 'clear')
    print(f"Renforcement netteté")
    print("Image {} sur {}".format(i+1, TOTAL))

    if file != "watermark.png":
        try:
            base_image = Image.open(file)
        except Exception:
            continue
        else:
            base_image.convert("RGB")
            # base_image = base_image.filter(ImageFilter.EDGE_ENHANCE)
            base_image = base_image.filter(ImageFilter.UnsharpMask(radius=4, percent=42, threshold=0))
            base_image = base_image.filter(ImageFilter.UnsharpMask(radius=2, percent=42, threshold=0))
            # base_image = base_image.filter(ImageFilter.SHARPEN)
            output_folder = PATH / "NET"
            output_folder.mkdir(exist_ok=True)
            base_image.save(str(output_folder / file), format="JPEG", subsampling=0, quality=100)

print("Terminé !")
sleep(1)
# input("Terminé !\nAppuyez sur une touche pour fermer")
