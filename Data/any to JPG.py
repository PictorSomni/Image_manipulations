# -*- coding: utf-8 -*-

#############################################################
#                          IMPORTS                          #
#############################################################
import os
import shutil
from pathlib import Path
from wand.image import Image
 
#############################################################
#                           PATH                            #
#############################################################
PATH = Path(__file__).resolve().parent
os.chdir(PATH)

#############################################################
#                         CONTENT                           #
#############################################################
EXTENSIONS = (".avif",".heic", ".webp", ".png", ".tiff", ".jpeg")
FOLDER = [file for file in sorted(PATH.iterdir()) if file.is_file() and file.suffix.lower() in EXTENSIONS]
TOTAL = len(FOLDER)

def folder(folder_name):
    folder_path = PATH / folder_name
    folder_path.mkdir(exist_ok=True)

#############################################################
#                           MAIN                            #
#############################################################

for i, file in enumerate(FOLDER):
    file_name = file.stem
    file_extension = file.suffix

    os.system('cls' if os.name == 'nt' else 'clear')
    print(f"{file_extension} en JPG")
    print("#" * 32 + "\n")
    print(f"Image {i+1} sur {TOTAL}")
    folder(f"{file_extension[1:]}")

    try:
        actual_file = Image(filename=str(file))
    except Exception:
        print(Exception)
    else:
        image = actual_file.convert('jpg')
        jpg_path = PATH / f"{file_name}.jpg"
        image.save(filename=str(jpg_path))
        dest_folder = PATH / f"{file_extension[1:]}"
        shutil.move(str(file), str(dest_folder / file.name))

print("Terminé")