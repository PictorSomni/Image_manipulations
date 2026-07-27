# -*- coding: utf-8 -*-
"""
Ajoute un grain argentique simulé à un lot d'images.

Le grain est pondéré par la luminance via une courbe parabolique centrée sur
les mi-tons (peak à luma ≈ 0,5) : il est minimal dans les ombres profondes et
les hautes lumières, et maximal dans les demi-teintes — ce qui évite l'effet
de bruit numérique dans les zones sombres tout en conservant le grain visible
là où l'œil le perçoit naturellement sur un film argentique.

La taille du grain est simulée en générant le bruit à une résolution réduite
puis en le réinterpolant, ce qui donne des grains de taille réaliste plutôt
qu'un simple bruit pixel-par-pixel.

Les résultats sont sauvegardés dans un sous-dossier ``GRAIN/``
avec le même nom de base en JPEG qualité maximale.

Paramètres configurables dans CONSTANTS.py (section 12.2) :
  GRAIN_AMOUNT       — intensité  (0.05 = ISO 100, 0.10 = ISO 400, 0.20 = ISO 1600)
  GRAIN_SIZE         — taille en % de la plus petite dimension (0.1 = fin, 0.3 = moyen, 0.6 = gros)
  GRAIN_COLOR_RATIO  — part de grain couleur (0.0 = mono pur, 0.3 = subtil, 1.0 = plein)
  GRAIN_SHADOW_BOOST — concentration sur les mi-tons (1.0 = large, 2.0 = centré, 3.0 = serré)

Variables d'environnement :
  FOLDER_PATH     — dossier source (défaut : répertoire du script).
  SELECTED_FILES  — liste de noms séparés par ``|`` (filtre optionnel).

Dépendances : OpenCV (cv2), NumPy, Pillow (PIL)
"""

__version__ = "3.1.0"

#############################################################
#                          IMPORTS                          #
#############################################################
import os
from pathlib import Path
import CONSTANTS
import image_ops

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

GRAIN_FLOOR  = float(os.environ.get("GRAIN_FLOOR",  CONSTANTS.GRAIN_FLOOR))
GRAIN2_FLOOR = float(os.environ.get("GRAIN2_FLOOR", CONSTANTS.GRAIN2_FLOOR))

CHROMA_SHIFT  = float(os.environ.get("GRAIN_CHROMA_SHIFT",  CONSTANTS.GRAIN_CHROMA_SHIFT))
CHROMA_SHIFT2 = float(os.environ.get("GRAIN2_CHROMA_SHIFT", CONSTANTS.GRAIN2_CHROMA_SHIFT))

GRAIN1_ENABLED     = os.environ.get("GRAIN1_ENABLED", "1") == "1"

HALATION_ENABLED   = os.environ.get("HALATION_ENABLED", "1") == "1"
HALATION_THRESHOLD = float(os.environ.get("HALATION_THRESHOLD", CONSTANTS.HALATION_THRESHOLD))
HALATION_RADIUS    = float(os.environ.get("HALATION_RADIUS",    CONSTANTS.HALATION_RADIUS))
HALATION_INTENSITY = float(os.environ.get("HALATION_INTENSITY", CONSTANTS.HALATION_INTENSITY))
HALATION_RED_SHIFT = float(os.environ.get("HALATION_RED_SHIFT", CONSTANTS.HALATION_RED_SHIFT))

BLOOM_ENABLED    = os.environ.get("BLOOM_ENABLED", "1") == "1"
BLOOM_RADIUS     = float(os.environ.get("BLOOM_RADIUS",    CONSTANTS.BLOOM_RADIUS))
BLOOM_INTENSITY  = float(os.environ.get("BLOOM_INTENSITY", CONSTANTS.BLOOM_INTENSITY))

DESAT_ENABLED             = os.environ.get("DESAT_ENABLED", "1") == "1"
DESAT_SHADOW_THRESHOLD    = float(os.environ.get("DESAT_SHADOW_THRESHOLD",    CONSTANTS.DESAT_SHADOW_THRESHOLD))
DESAT_SHADOW_INTENSITY    = float(os.environ.get("DESAT_SHADOW_INTENSITY",    CONSTANTS.DESAT_SHADOW_INTENSITY))
DESAT_HIGHLIGHT_THRESHOLD = float(os.environ.get("DESAT_HIGHLIGHT_THRESHOLD", CONSTANTS.DESAT_HIGHLIGHT_THRESHOLD))
DESAT_HIGHLIGHT_INTENSITY = float(os.environ.get("DESAT_HIGHLIGHT_INTENSITY", CONSTANTS.DESAT_HIGHLIGHT_INTENSITY))
DESAT_MIDTONE_BOOST       = float(os.environ.get("DESAT_MIDTONE_BOOST",       CONSTANTS.DESAT_MIDTONE_BOOST))

CURVE_ENABLED           = os.environ.get("CURVE_ENABLED", "1") == "1"
CURVE_SHOULDER_START    = float(os.environ.get("CURVE_SHOULDER_START",    CONSTANTS.CURVE_SHOULDER_START))
CURVE_SHOULDER_STRENGTH = float(os.environ.get("CURVE_SHOULDER_STRENGTH", CONSTANTS.CURVE_SHOULDER_STRENGTH))
CURVE_TOE_START         = float(os.environ.get("CURVE_TOE_START",         CONSTANTS.CURVE_TOE_START))
CURVE_TOE_LIFT          = float(os.environ.get("CURVE_TOE_LIFT",          CONSTANTS.CURVE_TOE_LIFT))

CA_ENABLED     = os.environ.get("CA_ENABLED", "1") == "1"
CA_STRENGTH    = float(os.environ.get("CA_STRENGTH",    CONSTANTS.CA_STRENGTH))
CA_AXIAL_RATIO = float(os.environ.get("CA_AXIAL_RATIO", CONSTANTS.CA_AXIAL_RATIO))


#############################################################
#                           MAIN                            #
#############################################################
for index, file_name in enumerate(files_to_process):
    print(f"Image {index + 1} sur {total}")
    try:
        pil_img = image_ops.open_srgb(folder_path / file_name)
    except Exception:
        continue

    result = pil_img
    if CA_ENABLED:
        print("  → Aberrations chromatiques...")
        result = image_ops.add_chromatic_aberration(result, CA_STRENGTH, CA_AXIAL_RATIO)
    if DESAT_ENABLED:
        print("  → Désaturation des extrêmes...")
        result = image_ops.add_desaturate_extremes(
            result, DESAT_SHADOW_THRESHOLD, DESAT_SHADOW_INTENSITY,
            DESAT_HIGHLIGHT_THRESHOLD, DESAT_HIGHLIGHT_INTENSITY,
            DESAT_MIDTONE_BOOST)
    if HALATION_ENABLED:
        print("  → Halation...")
        result = image_ops.add_halation(result, HALATION_THRESHOLD, HALATION_RADIUS,
                                        HALATION_INTENSITY, HALATION_RED_SHIFT)
    if BLOOM_ENABLED:
        print("  → Bloom...")
        result = image_ops.add_bloom(result, BLOOM_RADIUS, BLOOM_INTENSITY)
    if CURVE_ENABLED:
        print("  → Courbe tonale...")
        result = image_ops.add_filmic_curve(result, CURVE_SHOULDER_START, CURVE_SHOULDER_STRENGTH,
                                            CURVE_TOE_START, CURVE_TOE_LIFT)
    if GRAIN1_ENABLED:
        print("  → Grain 1...")
        result = image_ops.add_film_grain(result, AMOUNT, SIZE, COLOR_RATIO,
                                          SHADOW_BOOST, GRAIN_FLOOR, CHROMA_SHIFT)
    if GRAIN2_ENABLED:
        print("  → Grain 2...")
        result = image_ops.add_film_grain(result, AMOUNT2, SIZE2, COLOR_RATIO2,
                                          SHADOW_BOOST2, GRAIN2_FLOOR, CHROMA_SHIFT2)
    stem = Path(file_name).stem
    result.save(str(output_folder / f"{stem}.jpg"), format="JPEG",
               subsampling=0, quality=100, icc_profile=image_ops._SRGB_ICC)

print("Terminé !")
