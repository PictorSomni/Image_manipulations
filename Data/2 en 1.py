# -*- coding: utf-8 -*-
"""
Assemble deux photos portrait côte à côte sur une seule image JPEG prête à imprimer.

Chaque paire d'images est recadrée au format ``WIDTH × HEIGHT`` mm à 300 DPI
puis collée horizontalement pour obtenir un tirage ``(WIDTH×2) × HEIGHT``.
Si un nom de fichier contient un mot-clé "recto", "verso" ou "duo", les deux
faces sont issues de la même image (duplication).

Variables d'environnement :
  FOLDER_PATH       — dossier source des images (défaut : répertoire du script).
  SELECTED_FILES    — liste de noms séparés par ``|`` (filtre optionnel).
  TWO_IN_ONE_WIDTH  — largeur individuelle en mm (défaut : 76).
  TWO_IN_ONE_HEIGHT — hauteur individuelle en mm (défaut : 102).

  Les fichiers dont le nom commence par ``NX_`` (ex. ``2X_photo.jpg``) sont
  répétés N fois dans la liste avant d'être appariés.

Dépendances : Pillow (PIL)
"""

__version__ = "2.2.3"

#############################################################
#                          IMPORTS                          #
#############################################################
from pathlib import Path
import os
import re
from PIL import Image, ImageOps, ImageFile

#############################################################
#                           SIZE                            #
#############################################################
#-------------- size of each individual image --------------#
WIDTH = int(os.environ.get("TWO_IN_ONE_WIDTH", 76))   # mm -> will be doubled !
HEIGHT = int(os.environ.get("TWO_IN_ONE_HEIGHT", 102)) # mm
DPI = 300          # DPI
START = 1          # Start number to count, if needed

#############################################################
#                           PATH                            #
#############################################################
PATH = Path(os.environ.get("FOLDER_PATH", str(Path(__file__).resolve().parent)))

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

# Expand files prefixed with NX_ (e.g. "2X_photo.jpg" → repeat the file 2 times)
_COPIES_RE = re.compile(r'^(\d+)X_', re.IGNORECASE)

def _expand_copies(file_list):
    """Répète chaque fichier selon son préfixe NX_ (ex: '3X_photo.jpg' → 3 fois)."""
    expanded = []
    for f in file_list:
        m = _COPIES_RE.match(f)
        count = int(m.group(1)) if m else 1
        expanded.extend([f] * count)
    return expanded

FOLDER = _expand_copies(FOLDER)
TOTAL = len(FOLDER)
DUO = ["recto", "verso", "duo"]
DOUBLE = False
IMAGE_NAME = ""

#############################################################
#               CONVERT MM 300DPI TO PIXELS                 #
#############################################################
def mm_to_pixels(mm, dpi) :
    """Convertit des millimètres en pixels entiers pour un DPI donné."""
    return round((float(mm) / 25.4) * dpi)

WIDTH_DPI = mm_to_pixels(WIDTH, DPI)
HEIGHT_DPI = mm_to_pixels(HEIGHT, DPI)

_FORMAT_FOLDER_NAMES = {
    (76, 102): "10x15",
    (102, 102): "10x20",
    (89, 127): "13x18",
    (102, 152): "15x20",
    (152, 203): "20x30",
}
FOLDER_NAME = _FORMAT_FOLDER_NAMES.get((WIDTH, HEIGHT), f"{WIDTH * 2}x{HEIGHT}")

def folder(folder_name):
    """Crée le sous-dossier ``folder_name`` dans PATH s'il n'existe pas encore."""
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

    folder(FOLDER_NAME)
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

    images = map(Image.open, [PATH / image1, PATH / image2])
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

        output_folder = PATH / FOLDER_NAME
        if DOUBLE:
            new_image.save(str(output_folder / IMAGE_NAME), dpi=(DPI, DPI), format='JPEG', subsampling=0, quality=100)
            DOUBLE = False
        else:
            new_image.save(str(output_folder / f"{START:03}.jpg"), dpi=(DPI, DPI), format='JPEG', subsampling=0, quality=100)

        index += 1
        START += 1

print("Terminé !")
