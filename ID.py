# -*- coding: utf-8 -*-
#############################################################
#                          IMPORTS                          #
#############################################################
import os
import sys
import re
from time import sleep
from PIL import Image, ImageOps 

#############################################################
#                           SIZE                            #
#############################################################
WIDTH = 46         # mm
HEIGHT = 36         # mm

CANVA_WIDTH = 152   # mm
CANVA_HEIGHT = 102  # mm

H_SPACE = 34        # PIXELS !!!
V_SPACE = 89        # PIXELS !!!

DPI = 300

#############################################################
#                           PATH                            #
#############################################################
PATH = os.path.dirname(os.path.abspath(__file__))
os.chdir(PATH)

#############################################################
#                         CONTENT                           #
#############################################################
EXTENSION = (".jpg", ".jpeg", ".png", ".JPG", ".JPEG", ".PNG")
FOLDER = [file for file in sorted(os.listdir()) if file.endswith(EXTENSION) and not file == "watermark.png"]
TOTAL = len(FOLDER)
BG_COLOR = (200, 200, 200)

#############################################################
#               CONVERT MM 300DPI TO PIXELS                 #
#############################################################
def mm_to_pixels(mm, dpi) :
    return round((float(mm) / 25.4) * dpi)

WIDTH_DPI = mm_to_pixels(WIDTH, DPI)
HEIGHT_DPI = mm_to_pixels(HEIGHT, DPI)
CANVA_WIDTH_DPI = mm_to_pixels(CANVA_WIDTH, DPI)
CANVA_HEIGHT_DPI = mm_to_pixels(CANVA_HEIGHT, DPI)

#############################################################
#                           MAIN                            #
#############################################################
index = 1
save_it = False
x_offset = H_SPACE
counter = 0
canva = Image.new('RGB', (CANVA_WIDTH_DPI, CANVA_HEIGHT_DPI), BG_COLOR)
while len(FOLDER) > 0:
    os.system('cls' if os.name == 'nt' else 'clear')
    print("ID")
    print("#" * 30)
    print(f"image restantes {len(FOLDER)}")
    print("-" * 13)
    

    current_image = FOLDER.pop()
    image = Image.open(current_image)
    
    y_offset = V_SPACE

    if index % 3 == 0 or len(FOLDER) == 0 :
        save_it = True
        print("Enregistrement image\n")

    for i in range(2):
        if image.width < image.height:
            image = image.rotate(90, expand=True)

        result = ImageOps.fit(image, (WIDTH_DPI, HEIGHT_DPI))
        
        canva.paste(result, (x_offset, y_offset))
    
        y_offset += (HEIGHT_DPI + V_SPACE)    
    x_offset += (WIDTH_DPI + H_SPACE)

    if save_it == True :
        counter += 1
        canva.save(f"{PATH}\\ID_{counter:03}.jpg", dpi=(DPI, DPI), format='JPEG', subsampling=0, quality=100)
        # canva.show()
        save_it = False
        canva = Image.new('RGB', (CANVA_WIDTH_DPI, CANVA_HEIGHT_DPI), BG_COLOR)
        x_offset = H_SPACE

    index += 1

print("Terminé !")