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

__version__ = "2.8.2"

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

AMOUNT       = CONSTANTS.GRAIN_AMOUNT
SIZE         = CONSTANTS.GRAIN_SIZE
COLOR_RATIO  = CONSTANTS.GRAIN_COLOR_RATIO
SHADOW_BOOST = CONSTANTS.GRAIN_SHADOW_BOOST


def add_film_grain(pil_img: Image.Image) -> Image.Image:
    """Applique un grain argentique simulé à une image PIL RGB."""
    img = np.array(pil_img, dtype=np.float32) / 255.0
    h, w = img.shape[:2]

    # Grain généré à résolution réduite → interpolé → grains de taille SIZE pixels
    grain_h = max(1, round(h / SIZE))
    grain_w = max(1, round(w / SIZE))

    rng = np.random.default_rng()
    # Grain monochrome (même valeur sur les 3 canaux) + grain couleur (indépendant par canal)
    # COLOR_RATIO contrôle la part de variation chromatique : 0.0 = mono pur, 1.0 = couleur pleine
    grain_mono  = rng.normal(0.0, AMOUNT, (grain_h, grain_w, 1)).astype(np.float32)
    grain_color = rng.normal(0.0, AMOUNT, (grain_h, grain_w, 3)).astype(np.float32)
    grain_small = np.repeat(grain_mono, 3, axis=2) * (1.0 - COLOR_RATIO) + grain_color * COLOR_RATIO

    # Réinterpolation bicubique pour un grain à taille réaliste
    grain = cv2.resize(grain_small, (w, h), interpolation=cv2.INTER_CUBIC)

    # Masque de luminance : pondère le grain (fort dans les ombres, faible dans les lumières)
    luma = (0.299 * img[:, :, 0] + 0.587 * img[:, :, 1] + 0.114 * img[:, :, 2])
    # Courbe non linéaire : maximum vers luma ~0.2, quasi nul à 1.0
    shadow_weight = (1.0 - luma ** 1.2) ** SHADOW_BOOST
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

    result = add_film_grain(pil_img)
    stem = Path(file_name).stem
    result.save(str(output_folder / f"{stem}.jpg"), format="JPEG", subsampling=0, quality=100)

print("Terminé !")
