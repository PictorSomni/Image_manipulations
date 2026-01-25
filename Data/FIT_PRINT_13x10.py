# -*- coding: utf-8 -*-
#############################################################
#                          IMPORTS                          #
#############################################################
from pathlib import Path
from time import sleep
import os
from PIL import Image, ImageFile, ImageOps

DPI = 300
#############################################################
#                           PATH                            #
#############################################################
PATH = Path(__file__).resolve().parent

#############################################################
#                         CONTENT                           #
#############################################################
ImageFile.LOAD_TRUNCATED_IMAGES = True

EXTENSION = (".jpg", ".jpeg", ".png")
FOLDER = [file.name for file in sorted(PATH.iterdir()) if file.is_file() and file.suffix.lower() in EXTENSION and file.name != "watermark.png"]
TOTAL = len(FOLDER)

def mm_to_pixels(mm, dpi) :
    return round((float(mm) / 25.4) * dpi)

PRINT_SIZE = (127, 102)
CROP_SIZE = (102, 102)
PRINT_DPI = (mm_to_pixels(PRINT_SIZE[0], DPI)), (mm_to_pixels(PRINT_SIZE[1], DPI))
CROP_DPI = (mm_to_pixels(CROP_SIZE[0], DPI)), (mm_to_pixels(CROP_SIZE[1], DPI))


def folder(folder) :
    folder_path = PATH / folder
    folder_path.mkdir(exist_ok=True)


#############################################################
#                           MAIN                            #
#############################################################
for i, file in enumerate(FOLDER):
    os.system('cls' if os.name == 'nt' else 'clear')
    print("Image {} sur {}".format(i+1, TOTAL))

    try:
        file_path = PATH / file
        base_image = Image.open(file_path)
    except Exception:
        print(Exception)
    else:
        folder("13x10")

        if base_image.width > base_image.height: # IF LANDSCAPE, ROTATE 90 DEGREES
            base_image = base_image.rotate(90, expand=True)

        result = ImageOps.fit(base_image, (CROP_DPI[0], CROP_DPI[1]), centering=(0.5, 0.5))
        result = result.convert("RGB")

        print_size = Image.new("RGB", (PRINT_DPI[0], PRINT_DPI[1]), (255, 255, 255))
        print_size.paste(result)

        filename = file_path.stem
        output_folder = PATH / "13x10"
        print_size.save(str(output_folder / f"{filename}.jpg"), dpi=(DPI, DPI), format='JPEG', subsampling=0, quality=100)
print("Terminé !")
sleep(1)
# input("Terminé !\nAppuyez sur une touche pour fermer")
