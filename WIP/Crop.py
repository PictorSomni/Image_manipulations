# -*- coding: utf-8 -*-

#############################################################
#                          IMPORTS                          #
#############################################################
import os
import sys
import math
from PIL import Image, ImageOps, ImageFile

DPI = 300

#############################################################
#                           PATH                            #
#############################################################
PATH = os.path.dirname(os.path.abspath(__file__))
os.chdir(PATH)

#############################################################
#                         CONTENT                           #
#############################################################
ImageFile.LOAD_TRUNCATED_IMAGES = True

EXTENSION = (".jpg", ".jpeg", ".png")
FOLDER = [file for file in sorted(os.listdir()) if file.lower().endswith(EXTENSION) and not file == "watermark.png"]
TOTAL = len(FOLDER)


if not os.path.exists(f"{PATH}\\CROPPED") :
    os.makedirs(f"{PATH}\\CROPPED") # Save the copies in another folder, just in case...

#############################################################
#                           MAIN                            #
#############################################################
for i, file in enumerate(FOLDER) :
    os.system('cls' if os.name == 'nt' else 'clear')
    print(f"Crop images")
    print("#" * 32 + "\n")
    print("Image {} sur {}".format(i+1, TOTAL))

    try :
        image = Image.open(file)
        file = file.split(".")[0]
    except Exception :
        print(Exception)
    else :
        W, H = image.size
        AREA = (372, 0, W, H-303) # Left, Up, Right, Down

        result = image.crop(AREA)
        result = result.convert("RGB") # In case there are PNGs
        result = result.rotate(180, expand=True)
        result.save(f"{PATH}\\CROPPED\\{file}.jpg", dpi=(DPI, DPI), format='JPEG', subsampling=0, quality=100)

print("Terminé !")
# input("Terminé !\nAppuyez sur une touche pour fermer")