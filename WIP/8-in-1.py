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
SIZE = (25, 38)     # mm
CANVA_WIDTH = 152   # mm
CANVA_HEIGHT = 102  # mm
SPACE = 10           # mm
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
BG_COLOR = (255, 255, 255)

#############################################################
#               CONVERT MM 300DPI TO PIXELS                 #
#############################################################
def mm_to_pixels(mm, dpi) :
    return round((float(mm) / 25.4) * dpi)

X_DPI = mm_to_pixels(SIZE[0], DPI)
Y_DPI = mm_to_pixels(SIZE[1], DPI)
SPACE_DPI = mm_to_pixels(SPACE, DPI)
CANVA_WIDTH_DPI = mm_to_pixels(CANVA_WIDTH, DPI)
CANVA_HEIGHT_DPI = mm_to_pixels(CANVA_HEIGHT, DPI)

#############################################################
#                           MAIN                            #
#############################################################
index = 1
save_it = False
running = False
x_offset = 0 + SPACE_DPI
counter = 0
canva = Image.new('RGB', (CANVA_WIDTH_DPI, CANVA_HEIGHT_DPI), BG_COLOR)
while len(FOLDER) > 0:
    os.system('cls' if os.name == 'nt' else 'clear')
    print("ID")
    print("#" * 30)
    print(f"image restantes {len(FOLDER)}")
    print("-" * 13)

    running = True
    
    y_offset = 0 + SPACE_DPI

    if index % 4 == 0 or len(FOLDER) == 0 :
        save_it = True
        running = False
        print("Enregistrement image\n")

    for i in range(2):
        try :
            current_image = FOLDER.pop()
        except IndexError :
            print("Derniere image")
        else :
            image = Image.open(current_image)

        result = ImageOps.fit(image, (X_DPI, Y_DPI))
        
        canva.paste(result, (x_offset, y_offset))
    
        y_offset += (Y_DPI + SPACE_DPI)    
    x_offset += (X_DPI + SPACE_DPI)

    if save_it == True :
        counter += 1
        canva.save(f"{PATH}\\6-in-1_{counter:03}.jpg", dpi=(DPI, DPI), format='JPEG', subsampling=0, quality=100)
        # canva.show()
        save_it = False
        canva = Image.new('RGB', (CANVA_WIDTH_DPI, CANVA_HEIGHT_DPI), BG_COLOR)
        x_offset = 0 + SPACE_DPI

    index += 1
    
if save_it == False and running == True :
    canva.save(f"{PATH}\\6-in-1_{counter + 1:03}.jpg", dpi=(DPI, DPI), format='JPEG', subsampling=0, quality=100)

print("Terminé !")
sleep(1)