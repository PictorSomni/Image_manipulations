# -*- coding: utf-8 -*-
"""
Réduit le bruit d'un lot d'images par l'algorithme Non-Local Means (NLM).

Utilise ``cv2.fastNlMeansDenoisingColored``, qui traite simultanément luminance
et chrominance. Les résultats sont sauvegardés dans un sous-dossier ``DENOISE/``
avec le même nom de base en JPEG qualité maximale.

Paramètres configurables dans CONSTANTS.py (section 12.1) :
  DENOISE_H               — force sur la luminance  (défaut 8)
  DENOISE_H_COLOR         — force sur la couleur    (défaut 8)
  DENOISE_TEMPLATE_WINDOW — fenêtre de comparaison  (défaut 7, impair)
  DENOISE_SEARCH_WINDOW   — fenêtre de recherche    (défaut 21, impair)

Variables d'environnement :
  FOLDER_PATH     — dossier source (défaut : répertoire du script).
  SELECTED_FILES  — liste de noms séparés par ``|`` (filtre optionnel).

Dépendances : OpenCV (cv2), Pillow (PIL)
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

output_folder = folder_path / "DENOISE"
output_folder.mkdir(exist_ok=True)

H               = CONSTANTS.DENOISE_H
H_COLOR         = CONSTANTS.DENOISE_H_COLOR
TEMPLATE_WINDOW = CONSTANTS.DENOISE_TEMPLATE_WINDOW
SEARCH_WINDOW   = CONSTANTS.DENOISE_SEARCH_WINDOW

#############################################################
#                           MAIN                            #
#############################################################
for index, file_name in enumerate(files_to_process):
    print(f"Image {index + 1} sur {total}")
    try:
        pil_img = Image.open(folder_path / file_name).convert("RGB")
    except Exception:
        continue

    bgr = cv2.cvtColor(np.array(pil_img), cv2.COLOR_RGB2BGR)
    denoised_bgr = cv2.fastNlMeansDenoisingColored(
        bgr,
        None,
        h=H,
        hColor=H_COLOR,
        templateWindowSize=TEMPLATE_WINDOW,
        searchWindowSize=SEARCH_WINDOW,
    )
    result = Image.fromarray(cv2.cvtColor(denoised_bgr, cv2.COLOR_BGR2RGB))
    stem = Path(file_name).stem
    result.save(str(output_folder / f"{stem}.jpg"), format="JPEG", subsampling=0, quality=100)

print("Terminé !")
