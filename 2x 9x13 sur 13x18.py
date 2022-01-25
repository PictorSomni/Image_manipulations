# -*- coding: utf-8 -*-
#############################################################
#                          IMPORTS                          #
#############################################################
import os
import sys
import re
from PIL import Image, ImageOps, ImageFile

#############################################################
#                           SIZE                            #
#############################################################
WIDTH = 89      # mm
HEIGHT = 127    # mm
DPI = 300       # DPI

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
IMAGE_NAME = ""

#############################################################
#               CONVERT MM 300DPI TO PIXELS                 #
#############################################################
WIDTH_DPI = round((float(WIDTH) / 25.4) * DPI)
HEIGHT_DPI = round((float(HEIGHT) / 25.4) * DPI)

#############################################################
#                           MAIN                            #
#############################################################
os.system('cls' if os.name == 'nt' else 'clear')

index = 1
while len(FOLDER) > 0:
    print(f"images restantes : {len(FOLDER)}")
    print("-" * 13)
    
    image1 = FOLDER.pop()
    IMAGE_NAME = image1
    image2 = image1
    
    images = map(Image.open, [image1, image2])
    x_offset = 0
    try:
        new_image = Image.new('RGB', (WIDTH_DPI * 2, HEIGHT_DPI))
    except Exception:
        pass
    else:
        for image in images:
            # widths, heights = zip(*(i.size for i in images))
            if image.width > image.height:
                image = image.rotate(90, expand=True)

            cropped_image = ImageOps.fit(image, (WIDTH_DPI, HEIGHT_DPI))

            new_image.paste(cropped_image, (x_offset, 0))
            x_offset += WIDTH_DPI

            new_image.save('9x13_{}'.format(IMAGE_NAME), dpi=(DPI, DPI), format='JPEG', subsampling=0, quality=100)

print("Terminé !")
