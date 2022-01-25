# -*- coding: utf-8 -*-
#############################################################
#                          IMPORTS                          #
#############################################################
import os
import sys
import re
from time import sleep
from PIL import Image, ImageFile

DPI = 300
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

features = re.search(r"FIT_PRINT_(\d+)\s?x\s?(\d+).py", sys.argv[0]) # width x height

if int(features.group(1)) < int(features.group(2)) :
    WIDTH = int(features.group(2))
    HEIGHT = int(features.group(1))
else :
    WIDTH = int(features.group(1))
    HEIGHT = int(features.group(2))

EXTENSION = (".jpg", ".jpeg", ".png", ".JPG", ".JPEG", ".PNG")
FOLDER = [file for file in sorted(os.listdir()) if file.endswith(EXTENSION) and not file == "watermark.png"]
TOTAL = len(FOLDER)

def correct_round(number) :
    if number  == 89 :
        number = 9
    
    elif number  == 127 :
        number = 13
    
    elif number  == 178 :
        number = 18

    else :
        number = int(number /10)

    return number


def mm_to_pixels(mm, dpi) :
    return round((float(mm) / 25.4) * dpi)

WIDTH_DPI = mm_to_pixels(WIDTH, DPI)
HEIGHT_DPI = mm_to_pixels(HEIGHT, DPI)

WIDTH = correct_round(WIDTH)
HEIGHT = correct_round(HEIGHT)

NAME_SIZE = f"{HEIGHT}x{WIDTH}"


def folder(folder) :
    if not os.path.exists(PATH + f"\\{folder}") :
        os.makedirs(PATH + f"\\{folder}")


#############################################################
#                           MAIN                            #
#############################################################
for i, file in enumerate(FOLDER):
    os.system('cls' if os.name == 'nt' else 'clear')
    print("Image {} sur {}".format(i+1, TOTAL))

    try:
        base_image = Image.open(file)
    except Exception:
        print(Exception)
    else:
        folder(NAME_SIZE)

        if base_image.width < base_image.height : # IF PORTRAIT, ROTATE 90 DEGREES
            base_image = base_image.rotate(90, expand=True)
            ROTATED = True
        else :
            ROTATED = False

        print_size = Image.new("RGB", (WIDTH_DPI, HEIGHT_DPI), (255, 255, 255))
        print_size.paste(base_image)

        if ROTATED == True :
            print_size = print_size.rotate(270, expand=True)
                            
        print_size.save(f"{PATH}\\{NAME_SIZE}\\{NAME_SIZE}_{file}", dpi=(DPI, DPI), format='JPEG', subsampling=0, quality=100)
print("Terminé !")
sleep(1)
# input("Terminé !\nAppuyez sur une touche pour fermer")
