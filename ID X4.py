# -*- coding: utf-8 -*-
#############################################################
#                          IMPORTS                          #
#############################################################
import os
from time import sleep
from PIL import Image, ImageOps 

#############################################################
#                           SIZE                            #
#############################################################
WIDTH = 46         # mm
HEIGHT = 36         # mm

CANVA_WIDTH = 127   # mm
CANVA_HEIGHT = 102  # mm

SPACE = 120        # PIXELS !!!

DPI = 300

#############################################################
#                           PATH                            #
#############################################################
PATH = os.path.dirname(os.path.abspath(__file__))
os.chdir(PATH)

#############################################################
#                         CONTENT                           #
#############################################################
EXTENSION = (".jpg", ".jpeg", ".png")
FOLDER = [file for file in sorted(os.listdir()) if file.lower().endswith(EXTENSION) and not file == "watermark.png"]
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

x_offset = SPACE
y_offset = SPACE
counter = 1

os.system('cls' if os.name == 'nt' else 'clear')
print("ID")
print("#" * 30)
print(f"image restantes {len(FOLDER)}")
print("-" * 13)

for file in FOLDER:
    canva = Image.new('RGB', (CANVA_WIDTH_DPI, CANVA_HEIGHT_DPI), BG_COLOR)
    print(f"Traitement de l'image {counter} sur {TOTAL} : {file}")
    
    current_image = FOLDER.pop()
    image = Image.open(current_image)

    for y in range(2):
        for i in range(2):            
            if image.width < image.height:
                image = image.rotate(90, expand=True)

            result = ImageOps.fit(image, (WIDTH_DPI, HEIGHT_DPI))
            
            canva.paste(result, (x_offset, y_offset))
        
            y_offset += (HEIGHT_DPI + SPACE)    
        x_offset += (WIDTH_DPI + SPACE)
        y_offset = SPACE

    canva.save(f"{PATH}\\ID_{counter:03}.jpg", dpi=(DPI, DPI), format='JPEG', subsampling=0, quality=100)
    x_offset = SPACE
    counter += 1

print("Terminé !")
sleep(1)