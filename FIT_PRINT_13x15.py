# -*- coding: utf-8 -*-
#############################################################
#                          IMPORTS                          #
#############################################################
import os
from time import sleep
from PIL import Image, ImageFile, ImageOps

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

def mm_to_pixels(mm, dpi) :
    return round((float(mm) / 25.4) * dpi)

PRINT_SIZE = (127, 152)
CROP_SIZE = (102, 152)
PRINT_DPI = (mm_to_pixels(PRINT_SIZE[0], DPI)), (mm_to_pixels(PRINT_SIZE[1], DPI))
CROP_DPI = (mm_to_pixels(CROP_SIZE[0], DPI)), (mm_to_pixels(CROP_SIZE[1], DPI))


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
        folder("13x15")

        if base_image.width > base_image.height : # IF LANDSCAPE, ROTATE 90 DEGREES
            base_image = base_image.rotate(90, expand=True)

        result = ImageOps.fit(base_image, (CROP_DPI[0], CROP_DPI[1]), centering=(0.5, 0.5))
        result = result.convert("RGB")

        print_size = Image.new("RGB", (PRINT_DPI[0], PRINT_DPI[1]), (255, 255, 255))
        print_size.paste(result)

        print_size.save(f"{PATH}\\13x15\\{file}", dpi=(DPI, DPI), format='JPEG', subsampling=0, quality=100)
print("Terminé !")
sleep(1)
# input("Terminé !\nAppuyez sur une touche pour fermer")
