# -*- coding: utf-8 -*-

__version__ = "1.6.7"

#############################################################
#                          IMPORTS                          #
#############################################################
from pathlib import Path
import os
from PIL import Image, ImageOps, ImageFile

#############################################################
#                           SIZE                            #
#############################################################
#-------------- size of each individual image --------------#
WIDTH = 76         # mm -> will be doubled !
HEIGHT = 102       # mm
DPI = 300          # DPI
START = 1          # Start number to count, if needed

#############################################################
#                           PATH                            #
#############################################################
PATH = Path(__file__).resolve().parent

#############################################################
#                         CONTENT                           #
#############################################################
ImageFile.LOAD_TRUNCATED_IMAGES = True

# Récupérer les fichiers sélectionnés depuis le Dashboard (si applicable)
selected_files_str = os.environ.get("SELECTED_FILES", "")
selected_files_set = set(selected_files_str.split("|")) if selected_files_str else None

EXTENSION = (".jpg", ".jpeg", ".png")
all_files = [file.name for file in sorted(PATH.iterdir()) if file.is_file() and file.suffix.lower() in EXTENSION and file.name != "watermark.png"]
FOLDER = [f for f in all_files if f in selected_files_set] if selected_files_set else all_files
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

def folder(folder_name):
    folder_path = PATH / folder_name
    folder_path.mkdir(exist_ok=True)

#############################################################
#                           MAIN                            #
#############################################################
index = 1
print(f"2 images sur {WIDTH * 2}x{HEIGHT}")
print("#" * 30)

while len(FOLDER) > 0:
    print(f"image {index} sur {TOTAL // 2}") if TOTAL % 2 == 0 else print(f"image {index} sur {(TOTAL // 2) + 1}")
    print("-" * 13)

    folder(f"{WIDTH * 2}x{HEIGHT}")
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

        output_folder = PATH / f"{WIDTH * 2}x{HEIGHT}"
        if DOUBLE:
            new_image.save(str(output_folder / IMAGE_NAME), dpi=(DPI, DPI), format='JPEG', subsampling=0, quality=100)
            DOUBLE = False
        else:
            new_image.save(str(output_folder / f"{START:03}.jpg"), dpi=(DPI, DPI), format='JPEG', subsampling=0, quality=100)

        index += 1
        START += 1

print("Terminé !")
