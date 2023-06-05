# -*- coding: utf-8 -*-
#############################################################
#                          IMPORTS                          #
#############################################################
import os
from time import sleep
from PIL import Image, ImageOps, ImageFile

#############################################################
#                           SIZE                            #
#############################################################
#-------------- size of each individual image --------------#
WIDTH = 102        # mm -> will be doubled !
HEIGHT = 152       # mm
DPI = 300          # DPI
START = 1         # Start number to count, if needed

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
DUO = ["recto", "verso", "duo"]
DOUBLE = False
IMAGE_NAME = ""

#############################################################
#               CONVERT MM 300DPI TO PIXELS                 #
#############################################################
def mm_to_pixels(mm, dpi) :
    return round((float(mm) / 25.4) * dpi)

WIDTH_DPI = mm_to_pixels(WIDTH, DPI)
HEIGHT_DPI = mm_to_pixels(HEIGHT, DPI)

#############################################################
#                           MAIN                            #
#############################################################
index = 1
while len(FOLDER) > 0:
    os.system('cls' if os.name == 'nt' else 'clear')
    print("2 images sur 15x20")
    print("#" * 30)
    print(f"image {index} sur {TOTAL // 2}")
    print("-" * 13)

    
    image1 = FOLDER.pop()
    if any(key_name in image1.lower() for key_name in DUO) == True:
        IMAGE_NAME = image1
        image2 = image1
        DOUBLE = True
    else :
        if len(FOLDER) < 1:
            image2 = image1
        else:
            image2 = FOLDER.pop()

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

        if DOUBLE :
            new_image.save(f"{PATH}\\{WIDTH * 2}x{HEIGHT}_{IMAGE_NAME}", dpi=(DPI, DPI), format='JPEG', subsampling=0, quality=100)
            DOUBLE = False
        else :
            new_image.save(f"{PATH}\\{WIDTH * 2}x{HEIGHT}_{START:03}.jpg", dpi=(DPI, DPI), format='JPEG', subsampling=0, quality=100)

        index += 1
        START += 1

print("Terminé !")
