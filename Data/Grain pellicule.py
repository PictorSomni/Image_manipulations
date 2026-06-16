# -*- coding: utf-8 -*-
"""
Ajoute un grain argentique simulé à un lot d'images.

Le grain est pondéré par la luminance : il est plus présent dans les ombres
et les mi-tons, et presque absent dans les hautes lumières — ce qui reproduit
le comportement du grain des films argentiques (ISO 400-3200).

La taille du grain est simulée en générant le bruit à une résolution réduite
puis en le réinterpolant, ce qui donne des grains de taille réaliste plutôt
qu'un simple bruit pixel-par-pixel.

Les résultats sont sauvegardés dans un sous-dossier ``GRAIN/``
avec le même nom de base en JPEG qualité maximale.

Paramètres configurables dans CONSTANTS.py (section 12.2) :
  GRAIN_AMOUNT       — intensité  (0.05 = ISO 100, 0.10 = ISO 400, 0.20 = ISO 1600)
  GRAIN_SIZE         — taille en pixels (1.0 = grain fin, 2.0-3.0 = gros grain)
  GRAIN_COLOR_RATIO  — part de grain couleur (0.0 = mono pur, 0.3 = subtil, 1.0 = plein)
  GRAIN_SHADOW_BOOST — renforcement dans les ombres (1.0 = uniforme, 2.0 = ombres renforcées)

Variables d'environnement :
  FOLDER_PATH     — dossier source (défaut : répertoire du script).
  SELECTED_FILES  — liste de noms séparés par ``|`` (filtre optionnel).

Dépendances : OpenCV (cv2), NumPy, Pillow (PIL)
"""

__version__ = "2.8.3"

#############################################################
#                          IMPORTS                          #
#############################################################
import os
from pathlib import Path
import cv2
import numpy as np
from PIL import Image
import CONSTANTS

#############################################################
#                           PATH                            #
#############################################################
folder_path = Path(os.environ.get("FOLDER_PATH", str(Path(__file__).resolve().parent)))

#############################################################
#                         CONTENT                           #
#############################################################
selected_files_str = os.environ.get("SELECTED_FILES", "")
selected_files_set = set(selected_files_str.split("|")) if selected_files_str else None

image_extensions = (".JPG", ".JPEG", ".PNG", ".BMP", ".TIFF", ".TIF", ".WEBP")
all_files = [
    f.name for f in sorted(folder_path.iterdir())
    if f.is_file() and f.suffix.upper() in image_extensions and f.name != "watermark.png"
]
files_to_process = [f for f in all_files if f in selected_files_set] if selected_files_set else all_files
total = len(files_to_process)

output_folder = folder_path / "GRAIN"
output_folder.mkdir(exist_ok=True)

AMOUNT       = float(os.environ.get("GRAIN_AMOUNT",       CONSTANTS.GRAIN_AMOUNT))
SIZE         = float(os.environ.get("GRAIN_SIZE",         CONSTANTS.GRAIN_SIZE))
COLOR_RATIO  = float(os.environ.get("GRAIN_COLOR_RATIO",  CONSTANTS.GRAIN_COLOR_RATIO))
SHADOW_BOOST = float(os.environ.get("GRAIN_SHADOW_BOOST", CONSTANTS.GRAIN_SHADOW_BOOST))

_GRAIN2_AMOUNT_RAW = os.environ.get("GRAIN2_AMOUNT")
GRAIN2_ENABLED = _GRAIN2_AMOUNT_RAW is not None
AMOUNT2       = float(_GRAIN2_AMOUNT_RAW or CONSTANTS.GRAIN2_AMOUNT)
SIZE2         = float(os.environ.get("GRAIN2_SIZE",         CONSTANTS.GRAIN2_SIZE))
COLOR_RATIO2  = float(os.environ.get("GRAIN2_COLOR_RATIO",  CONSTANTS.GRAIN2_COLOR_RATIO))
SHADOW_BOOST2 = float(os.environ.get("GRAIN2_SHADOW_BOOST", CONSTANTS.GRAIN2_SHADOW_BOOST))


def add_film_grain(
    pil_img: Image.Image,
    amount: float,
    size: float,
    color_ratio: float,
    shadow_boost: float,
) -> Image.Image:
    """Applique un grain argentique simulé à une image PIL RGB."""
    img = np.array(pil_img, dtype=np.float32) / 255.0
    h, w = img.shape[:2]

    grain_h = max(1, round(h / size))
    grain_w = max(1, round(w / size))

    rng = np.random.default_rng()
    grain_mono  = rng.normal(0.0, amount, (grain_h, grain_w, 1)).astype(np.float32)
    grain_color = rng.normal(0.0, amount, (grain_h, grain_w, 3)).astype(np.float32)
    grain_small = np.repeat(grain_mono, 3, axis=2) * (1.0 - color_ratio) + grain_color * color_ratio

    grain = cv2.resize(grain_small, (w, h), interpolation=cv2.INTER_CUBIC)

    luma = (0.299 * img[:, :, 0] + 0.587 * img[:, :, 1] + 0.114 * img[:, :, 2])
    shadow_weight = (1.0 - luma ** 1.2) ** shadow_boost
    shadow_weight = np.clip(shadow_weight, 0.0, 1.0)[:, :, np.newaxis]

    result = np.clip(img + grain * shadow_weight, 0.0, 1.0)
    return Image.fromarray((result * 255).astype(np.uint8))


#############################################################
#                           MAIN                            #
#############################################################
for index, file_name in enumerate(files_to_process):
    print(f"Image {index + 1} sur {total}")
    try:
        pil_img = Image.open(folder_path / file_name).convert("RGB")
    except Exception:
        continue

    result = add_film_grain(pil_img, AMOUNT, SIZE, COLOR_RATIO, SHADOW_BOOST)
    if GRAIN2_ENABLED:
        result = add_film_grain(result, AMOUNT2, SIZE2, COLOR_RATIO2, SHADOW_BOOST2)
    stem = Path(file_name).stem
    result.save(str(output_folder / f"{stem}.jpg"), format="JPEG", subsampling=0, quality=100)

print("Terminé !")
