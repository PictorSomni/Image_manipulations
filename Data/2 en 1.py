# -*- coding: utf-8 -*-
"""
Assemble deux photos sur une seule image JPEG prête à imprimer.

Chaque paire d'images est recadrée au format ``WIDTH × HEIGHT`` mm à 300 DPI
puis collée sur une planche. Sans ``TWO_IN_ONE_SHEET``, la planche fait
exactement ``(WIDTH×2) × HEIGHT`` : les deux photos côte à côte, sans marge.

Avec ``TWO_IN_ONE_SHEET`` (ex. une feuille A4), la planche est imposée : les
photos sont pivotées et empilées si c'est la seule façon de les y faire tenir
à 100 %, et le bloc est centré. Deux 13×18 ne rentrent sur A4 ni côte à côte
(254 mm > 210) ni empilées en portrait (356 mm > 297), mais passent en
paysage empilées (178 × 254) — d'où la rotation automatique.

Si un nom de fichier contient un mot-clé "recto", "verso" ou "duo", les deux
faces sont issues de la même image (duplication).

Variables d'environnement :
  FOLDER_PATH       — dossier source des images (défaut : répertoire du script).
  SELECTED_FILES    — liste de noms séparés par ``|`` (filtre optionnel).
  TWO_IN_ONE_WIDTH  — largeur individuelle en mm (défaut : 76).
  TWO_IN_ONE_HEIGHT — hauteur individuelle en mm (défaut : 102).
  TWO_IN_ONE_SHEET  — planche de destination ``LxH`` en mm (ex. ``210x297``).
                      Vide = planche collée au plus juste (comportement
                      historique).

  Les fichiers dont le nom commence par ``NX_`` (ex. ``2X_photo.jpg``) sont
  répétés N fois dans la liste avant d'être appariés.

Dépendances : Pillow (PIL)
"""

__version__ = "3.1.0"

#############################################################
#                          IMPORTS                          #
#############################################################
from pathlib import Path
import os
import re
import sys
sys.path.insert(0, str(Path(__file__).resolve().parent))
import CONSTANTS
import image_ops
from PIL import Image, ImageOps, ImageFile

#############################################################
#                           SIZE                            #
#############################################################
#-------------- size of each individual image --------------#
WIDTH = int(os.environ.get("TWO_IN_ONE_WIDTH", 76))   # mm -> will be doubled !
HEIGHT = int(os.environ.get("TWO_IN_ONE_HEIGHT", 102)) # mm
DPI = CONSTANTS.DPI          # DPI
START = 1          # Start number to count, if needed

#------------- destination sheet (optional) ----------------#
_sheet_env = os.environ.get("TWO_IN_ONE_SHEET", "").strip()
SHEET = tuple(int(v) for v in _sheet_env.split("x")) if _sheet_env else None

#############################################################
#                           PATH                            #
#############################################################
PATH = Path(os.environ.get("FOLDER_PATH", str(Path(__file__).resolve().parent)))

#############################################################
#                         CONTENT                           #
#############################################################
ImageFile.LOAD_TRUNCATED_IMAGES = True

# Récupérer les fichiers sélectionnés depuis Hub (si applicable)
selected_files_str = os.environ.get("SELECTED_FILES", "")
selected_files_set = set(selected_files_str.split("|")) if selected_files_str else None

EXTENSION = (".jpg", ".jpeg", ".png")
all_files = [file.name for file in sorted(PATH.iterdir()) if file.is_file() and file.suffix.lower() in EXTENSION and file.name != "watermark.png" and not file.name.startswith("._")]
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

def plan_layout(photo_mm, sheet_mm):
    """Place deux photos de ``photo_mm`` sur une planche ``sheet_mm``.

    Renvoie ``(rotate, cols, rows)`` — ``rotate`` indiquant qu'il faut
    basculer les photos de 90° — ou ``None`` si la paire ne tient pas à
    100 % sur la planche, quelle que soit la disposition.

    Ordre d'essai : sans rotation d'abord, côte à côte avant empilé, pour
    que les formats qui marchaient déjà gardent exactement leur rendu.
    """
    pw, ph = photo_mm
    sw, sh = sheet_mm
    for rotate in (False, True):
        w, h = (ph, pw) if rotate else (pw, ph)
        for cols, rows in ((2, 1), (1, 2)):
            if w * cols <= sw and h * rows <= sh:
                return rotate, cols, rows
    return None


_FORMAT_FOLDER_NAMES = {
    (76, 102): "10x15",
    (102, 102): "10x20",
    (89, 127): "13x18",
    (102, 152): "15x20",
    (152, 203): "20x30",
}

if SHEET:
    LAYOUT = plan_layout((WIDTH, HEIGHT), SHEET)
    if LAYOUT is None:
        print(f"Deux photos de {WIDTH}x{HEIGHT} mm ne tiennent pas à 100 % "
              f"sur une planche de {SHEET[0]}x{SHEET[1]} mm, "
              "même en les pivotant.")
        sys.exit(1)
    # _FORMAT_FOLDER_NAMES ne sert pas ici : il associe une photo à la
    # planche JUSTE de deux photos (76x102 -> "10x15"), pas à son propre
    # format. CONSTANTS.FORMATS donne bien 127x178 -> "13x18".
    _NAMES = {v: k for k, v in CONSTANTS.FORMATS.items()}
    _sheet_label = _NAMES.get(SHEET, f"{SHEET[0]}x{SHEET[1]}")
    _photo_label = _NAMES.get((WIDTH, HEIGHT), f"{WIDTH}x{HEIGHT}")
    FOLDER_NAME = f"{_photo_label} sur {_sheet_label}"
    SHEET_DPI = (mm_to_pixels(SHEET[0], DPI), mm_to_pixels(SHEET[1], DPI))
else:
    # Planche collée au plus juste : deux photos côte à côte, zéro marge.
    LAYOUT = (False, 2, 1)
    FOLDER_NAME = _FORMAT_FOLDER_NAMES.get((WIDTH, HEIGHT),
                                           f"{WIDTH * 2}x{HEIGHT}")
    SHEET_DPI = (WIDTH_DPI * 2, HEIGHT_DPI)

ROTATE, COLS, ROWS = LAYOUT
# Dimensions d'une case, après l'éventuelle bascule des photos.
CELL_DPI = (HEIGHT_DPI, WIDTH_DPI) if ROTATE else (WIDTH_DPI, HEIGHT_DPI)
# Bloc des deux photos centré sur la planche (marges égales de chaque côté).
MARGIN_X = (SHEET_DPI[0] - CELL_DPI[0] * COLS) // 2
MARGIN_Y = (SHEET_DPI[1] - CELL_DPI[1] * ROWS) // 2

def folder(folder_name):
    """Crée le sous-dossier ``folder_name`` dans PATH s'il n'existe pas encore."""
    folder_path = PATH / folder_name
    folder_path.mkdir(exist_ok=True)

#############################################################
#                           MAIN                            #
#############################################################
index = 1
print(f"2 images de {WIDTH}x{HEIGHT} mm sur {FOLDER_NAME}"
      + (" (photos pivotées à 90°)" if ROTATE else ""))
print("#" * 30)

while len(FOLDER) > 0:
    print(f"{index} / {TOTAL // 2}") if TOTAL % 2 == 0 else print(f"{index} / {(TOTAL // 2) + 1}")

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

    images = map(image_ops.open_srgb, [PATH / image1, PATH / image2])
    try:
        # Fond BLANC : avec une planche plus grande que le bloc de photos,
        # les marges sont visibles — un fond noir (défaut de Image.new)
        # noierait la feuille d'encre.
        new_image = Image.new('RGB', SHEET_DPI, (255, 255, 255))
    except Exception:
        pass
    else:
        for slot, image in enumerate(images):
            # Chaque photo est amenée dans l'orientation de sa case : le
            # recadrage ImageOps.fit rognerait sinon dans le mauvais sens.
            if (image.width > image.height) != (CELL_DPI[0] > CELL_DPI[1]):
                image = image.rotate(90, expand=True)

            cropped_image = ImageOps.fit(image, CELL_DPI)

            new_image.paste(cropped_image, (
                MARGIN_X + (slot % COLS) * CELL_DPI[0],
                MARGIN_Y + (slot // COLS) * CELL_DPI[1]))

        output_folder = PATH / FOLDER_NAME
        if DOUBLE:
            new_image.save(str(output_folder / IMAGE_NAME), dpi=(DPI, DPI),
                          format='JPEG', subsampling=0, quality=100,
                          icc_profile=image_ops._SRGB_ICC)
            DOUBLE = False
        else:
            new_image.save(str(output_folder / f"{START:03}.jpg"), dpi=(DPI, DPI),
                          format='JPEG', subsampling=0, quality=100,
                          icc_profile=image_ops._SRGB_ICC)

        index += 1
        START += 1

print("Terminé !")
