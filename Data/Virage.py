# -*- coding: utf-8 -*-
"""
Vire un lot de photos vers un préréglage (sépia, jauni, N&B verdâtre...) :
conversion en noir et blanc puis calque de couleur unie en mode Multiply
par-dessus — le même principe qu'un calque couleur uni + mode de fusion
"Multiplier" dans Affinity/Photoshop (résultat = gris × couleur). La teinte
reste visible jusque dans les hautes lumières, contrairement à "Teinte et
saturation > Coloriser" qui désature vers le blanc pur.

Utile pour uniformiser le jaunissement de photos anciennes scannées, dont la
teinte d'origine varie d'un scan à l'autre.

Préréglages configurables dans CONSTANTS.py (section 12.7, VIRAGE_PRESETS) :
chaque préréglage est le triplet HSL (teinte °, saturation %, luminosité %)
de la couleur du calque Multiply — mêmes chiffres que le sélecteur HSL
d'Affinity/Photoshop.

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
import image_ops

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
HUE_DEG, SATURATION_PCT, LIGHTNESS_PCT = CONSTANTS.VIRAGE_PRESETS[PRESET_NAME]

EXTENSION = (".JPG", ".JPEG", ".PNG", ".BMP", ".GIF", ".TIFF")  # extensions d'image acceptées
all_files = [file.name for file in sorted(PATH.iterdir()) if file.is_file() and file.suffix.upper() in EXTENSION and file.name != "watermark.png"]
FOLDER = [f for f in all_files if f in selected_files_set] if selected_files_set else all_files
TOTAL = len(FOLDER)

output_folder = PATH / "VIRAGE"
output_folder.mkdir(exist_ok=True)

_ascii_name = unicodedata.normalize("NFKD", PRESET_NAME).encode(
    "ascii", "ignore").decode("ascii")


def colorize_multiply(pil_img, hue_deg, saturation_pct, lightness_pct):
    """Convertit en niveaux de gris puis pose une couleur unie en mode
    Multiply par-dessus — exactement un calque couleur uni HSL + mode de
    fusion "Multiplier" dans Affinity/Photoshop (résultat = gris × couleur).

    Contrairement à "Coloriser" (substitution HSL), la teinte de la couleur
    reste visible jusque dans les hautes lumières : un gris à 255 (blanc)
    multiplié par la couleur redonne la couleur elle-même, jamais du blanc
    pur — un tirage papier ancien n'est jamais neutre, même dans ses zones
    les plus claires (retour user : hautes lumières "cramées" avec l'ancienne
    méthode, besoin de plus de contrôle sur la teinte obtenue)."""
    gray = np.asarray(pil_img.convert("L"), dtype=np.float64) / 255.0
    hue, light, sat = (hue_deg % 360) / 360.0, lightness_pct / 100.0, saturation_pct / 100.0
    color_rgb = np.array(colorsys.hls_to_rgb(hue, light, sat), dtype=np.float64)
    result = gray[:, :, np.newaxis] * color_rgb[np.newaxis, np.newaxis, :]
    return Image.fromarray(np.round(result * 255).astype(np.uint8))


#############################################################
#                           MAIN                            #
#############################################################
for i, file in enumerate(FOLDER):
    print(f"Image {i + 1} sur {TOTAL} — {PRESET_NAME}")
    try:
        base_image = image_ops.open_srgb(PATH / file)
    except Exception:
        continue
    result = colorize_multiply(base_image, HUE_DEG, SATURATION_PCT, LIGHTNESS_PCT)
    stem = Path(file).stem
    result.save(str(output_folder / f"{stem}_{_ascii_name}.jpg"),
               format="JPEG", subsampling=0, quality=100,
               icc_profile=image_ops._SRGB_ICC)

print("Terminé !")
