# -*- coding: utf-8 -*-

#############################################################
#                          IMPORTS                          #
#############################################################
import os
import sys
from PIL import Image, ImageOps, ImageFile

#############################################################
#                           PATH                            #
#############################################################
PATH = os.path.dirname(os.path.abspath(__file__))
os.chdir(PATH)

#############################################################
#                         CONTENT                           #
#############################################################
ImageFile.LOAD_TRUNCATED_IMAGES = True

EXTENSION = (".jpg", ".jpeg", ".png", ".JPG", ".JPEG", ".PNG")
FOLDER = [file for file in sorted(os.listdir()) if file.endswith(EXTENSION) and not file == "watermark.png"]
TOTAL = len(FOLDER)

#############################################################
#                           MAIN                            #
#############################################################
if not os.path.exists(PATH + "\\splitted") :
    os.makedirs(PATH + f"\\splitted")

for i, file in enumerate(FOLDER) :
    os.system('cls' if os.name == 'nt' else 'clear')
    print("Images coupées en 2")
    print("#" * 32 + "\n")
    print("Image {} sur {}".format(i+1, TOTAL))
    filename, file_extension = os.path.splitext(file)

    try :
        base_image = Image.open(file)
    except Exception :
        print(Exception)
    else :
        if base_image.width < base_image.height : # IF PORTRAIT, ROTATE 90 DEGREES
            base_image = base_image.rotate(-90, expand=True)

        half_width = base_image.width // 2

        for index in range(2) :
            print(f"Division : {index + 1} / 2")
            half_image = base_image.crop((half_width * index, 0, half_width * (index + 1), base_image.height))
            half_image = half_image.convert("RGB")
            half_image.save(f"{PATH}\\splitted\\{filename}_{index + 1}{file_extension}", format='JPEG', subsampling=0, quality=100)

print("Terminé !")
# input("Terminé !\nAppuyez sur une touche pour fermer")