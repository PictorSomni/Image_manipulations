# -*- coding: utf-8 -*-

#############################################################
#                          IMPORTS                          #
#############################################################
import os
import sys
import re
import math
from PIL import Image, ImageOps, ImageFile

DPI = 300

BORDER_WHITE = 3
BORDER_BLACK = 1
BORDERS = BORDER_WHITE + BORDER_BLACK

WIDTH = 144
HEIGHT = 94

WIDTH_DPI = 0
HEIGHT_DPI = 0
BORDER_BORDER_WHITE_DPI = 0
BORDER_BORDER_BLACK_DPI = 0
BORDERS_DPI = 0

ROTATED = False

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


def mm_to_pixels(mm, dpi) :
    return round((float(mm) / 25.4) * dpi)


WIDTH_DPI = mm_to_pixels(WIDTH, DPI)
HEIGHT_DPI = mm_to_pixels(HEIGHT, DPI)
BORDER_BORDER_WHITE_DPI = mm_to_pixels(BORDER_WHITE, DPI) * 2
BORDER_BORDER_BLACK_DPI = mm_to_pixels(BORDER_BLACK, DPI) * 2
BORDERS_DPI = BORDER_BORDER_WHITE_DPI + BORDER_BORDER_BLACK_DPI

#############################################################
#                           MAIN                            #
#############################################################
for i, file in enumerate(FOLDER) :
    os.system('cls' if os.name == 'nt' else 'clear')
    print(f"Van Zuylenisation")
    print("#" * 32 + "\n")
    print("Image {} sur {}".format(i+1, TOTAL))

    try :
        base_image = Image.open(file)
        file = file.split(".")[0]
    except Exception :
        print(Exception)
    else :
        result = Image.new('RGB', (WIDTH_DPI, HEIGHT_DPI), (255, 255, 255, 255))
        cropped_image = base_image.resize((WIDTH_DPI - BORDERS_DPI, HEIGHT_DPI - BORDERS_DPI), Image.LANCZOS)
        result = ImageOps.fit(base_image, (WIDTH_DPI, HEIGHT_DPI))

        result = ImageOps.expand(result, border=BORDER_BORDER_BLACK_DPI // 2, fill="black")
        result = ImageOps.expand(result, border=BORDER_BORDER_WHITE_DPI // 2, fill="white")

        result = result.convert("RGB")
        result.save(f"{PATH}\\VZ_{file}.jpg", dpi=(DPI, DPI), format='JPEG', subsampling=0, quality=100)

print("Terminé !")
# input("Terminé !\nAppuyez sur une touche pour fermer")