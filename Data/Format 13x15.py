# -*- coding: utf-8 -*-

__version__ = "1.6.7"

#############################################################
#                          IMPORTS                          #
#############################################################
import os
from pathlib import Path
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

# Récupérer les fichiers sélectionnés depuis le Dashboard (si applicable)
selected_files_str = os.environ.get("SELECTED_FILES", "")
selected_files_set = set(selected_files_str.split("|")) if selected_files_str else None

EXTENSION = (".jpg", ".jpeg", ".png")
all_files = [file.name for file in sorted(PATH.iterdir()) if file.is_file() and file.suffix.lower() in EXTENSION and file.name != "watermark.png"]
FOLDER = [f for f in all_files if f in selected_files_set] if selected_files_set else all_files
TOTAL = len(FOLDER)

def mm_to_pixels(mm, dpi) :
    return round((float(mm) / 25.4) * dpi)

PRINT_SIZE = (127, 152)
CROP_SIZE = (102, 152)
PRINT_DPI = (mm_to_pixels(PRINT_SIZE[0], DPI)), (mm_to_pixels(PRINT_SIZE[1], DPI))
CROP_DPI = (mm_to_pixels(CROP_SIZE[0], DPI)), (mm_to_pixels(CROP_SIZE[1], DPI))


def folder(folder) :
    folder_path = PATH / folder
    folder_path.mkdir(exist_ok=True)


#############################################################
#                           MAIN                            #
#############################################################
for i, file in enumerate(FOLDER):
    print("Image {} sur {}".format(i+1, TOTAL))

    try:
        file_path = PATH / file
        base_image = Image.open(file_path)
    except Exception as e:
        print(e)
    else:
        folder("13x15")

        if base_image.width > base_image.height: # IF LANDSCAPE, ROTATE 90 DEGREES
            base_image = base_image.rotate(90, expand=True)

        result = ImageOps.fit(base_image, (CROP_DPI[0], CROP_DPI[1]), centering=(0.5, 0.5))
        result = result.convert("RGB")

        print_size = Image.new("RGB", (PRINT_DPI[0], PRINT_DPI[1]), (255, 255, 255))
        print_size.paste(result)

        filename = file_path.stem
        output_folder = PATH / "13x15"
        print_size.save(str(output_folder / f"{filename}.jpg"), dpi=(DPI, DPI), format='JPEG', subsampling=0, quality=100)
print("Terminé !")
# input("Terminé !\nAppuyez sur une touche pour fermer")
