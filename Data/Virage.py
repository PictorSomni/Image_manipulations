# -*- coding: utf-8 -*-
"""
Vire un lot de photos vers un préréglage (sépia, jauni, N&B verdâtre...) :
conversion en noir et blanc puis colorisation HSL à teinte/saturation fixes
et luminosité par pixel — le même principe que "Teinte et saturation >
Coloriser" dans Photoshop/Affinity.

Utile pour uniformiser le jaunissement de photos anciennes scannées, dont la
teinte d'origine varie d'un scan à l'autre.

Préréglages configurables dans CONSTANTS.py (section 12.7, VIRAGE_PRESETS).

Variables d'environnement :
  FOLDER_PATH     — dossier source (défaut : répertoire du script).
  SELECTED_FILES  — liste de noms séparés par ``|`` (filtre optionnel).
  VIRAGE_PRESET   — nom du préréglage (défaut : CONSTANTS.VIRAGE_DEFAULT_PRESET).

Les résultats sont enregistrés dans un sous-dossier ``VIRAGE/`` ; le nom du
préréglage est ajouté au nom de fichier pour pouvoir comparer plusieurs
essais sur la même photo sans les écraser.

Dépendances : NumPy, Pillow (PIL)
"""

__version__ = "1.0.0"

#############################################################
#                          IMPORTS                          #
#############################################################
import colorsys
import os
import re
import unicodedata
from pathlib import Path
import numpy as np
from PIL import Image
import CONSTANTS

#############################################################
#                           PATH                            #
#############################################################
PATH = Path(os.environ.get("FOLDER_PATH", str(Path(__file__).resolve().parent)))

#############################################################
#                         CONTENT                           #
#############################################################
selected_files_str = os.environ.get("SELECTED_FILES", "")
selected_files_set = set(selected_files_str.split("|")) if selected_files_str else None

PRESET_NAME = os.environ.get("VIRAGE_PRESET", CONSTANTS.VIRAGE_DEFAULT_PRESET)
if PRESET_NAME not in CONSTANTS.VIRAGE_PRESETS:
    raise SystemExit(f"Préréglage inconnu : {PRESET_NAME}")
HUE_DEG, SATURATION_PCT = CONSTANTS.VIRAGE_PRESETS[PRESET_NAME]

EXTENSION = (".JPG", ".JPEG", ".PNG", ".BMP", ".GIF", ".TIFF")  # extensions d'image acceptées
all_files = [file.name for file in sorted(PATH.iterdir()) if file.is_file() and file.suffix.upper() in EXTENSION and file.name != "watermark.png"]
FOLDER = [f for f in all_files if f in selected_files_set] if selected_files_set else all_files
TOTAL = len(FOLDER)

output_folder = PATH / "VIRAGE"
output_folder.mkdir(exist_ok=True)

_ascii_name = unicodedata.normalize("NFKD", PRESET_NAME).encode(
    "ascii", "ignore").decode("ascii")


def colorize_hsl(pil_img, hue_deg, saturation_pct):
    """Convertit en niveaux de gris puis colorise en HSL à teinte/saturation
    fixes — la luminosité de chaque pixel reste celle du noir et blanc,
    exactement comme "Coloriser" dans Photoshop/Affinity (noir en L=0,
    blanc en L=1, teinte pleine au milieu)."""
    gray = np.asarray(pil_img.convert("L"), dtype=np.float64) / 255.0
    hue, sat = (hue_deg % 360) / 360.0, saturation_pct / 100.0
    # LUT de 256 entrées (une par niveau de gris possible) : colorsys ne
    # traite qu'un pixel à la fois, mais teinte/saturation étant fixes ici,
    # 256 appels suffisent au lieu d'un par pixel de l'image.
    lut = np.array(
        [colorsys.hls_to_rgb(hue, level / 255.0, sat) for level in range(256)],
        dtype=np.float32) * 255.0
    indices = np.clip(np.round(gray * 255), 0, 255).astype(np.uint8)
    return Image.fromarray(lut[indices].astype(np.uint8))


#############################################################
#                           MAIN                            #
#############################################################
for i, file in enumerate(FOLDER):
    print(f"Image {i + 1} sur {TOTAL} — {PRESET_NAME}")
    try:
        base_image = Image.open(PATH / file).convert("RGB")
    except Exception:
        continue
    result = colorize_hsl(base_image, HUE_DEG, SATURATION_PCT)
    stem = Path(file).stem
    result.save(str(output_folder / f"{stem}_{_ascii_name}.jpg"),
               format="JPEG", subsampling=0, quality=100)

print("Terminé !")
