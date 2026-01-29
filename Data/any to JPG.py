# -*- coding: utf-8 -*-

#############################################################
#                          IMPORTS                          #
#############################################################
from pathlib import Path
from wand.image import Image

#############################################################
#                           PATH                            #
#############################################################
PATH = Path(__file__).resolve().parent

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
print(f"Conversion en JPG")
print(f"Dossier de travail: {PATH}")
print(f"Fichiers trouvés: {TOTAL}")

if TOTAL == 0:
    print("Aucun fichier à convertir trouvé.")
else:
    for i, file in enumerate(FOLDER):
        file_name = file.stem
        file_extension = file.suffix.lower()
        print(f"Image {i+1} sur {TOTAL}: {file.name}")
        folder(f"{file_extension[1:]}")

        try:
            with Image(filename=str(file)) as actual_file:
                image = actual_file.convert('jpg')
                jpg_path = PATH / f"{file_name}.jpg"
                image.save(filename=str(jpg_path))
            dest_folder = PATH / f"{file_extension[1:]}"
            file.rename(dest_folder / file.name)
            print(f"  [OK] Converti: {file_name}.jpg")
        except Exception as e:
            print(f"  [X] Erreur pour {file.name}: {e}")

print("Terminé")