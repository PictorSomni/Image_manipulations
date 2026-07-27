# -*- coding: utf-8 -*-
"""
Vire un lot de photos vers un préréglage (sépia, jauni, N&B verdâtre...) via
l'un de deux modes de colorisation (retour user : chacun rend mieux selon
l'effet visé — cf. CONSTANTS.py section 12.7 pour le détail) :

  "colorize" : substitution HSL, comme "Teinte et saturation > Coloriser"
               dans Photoshop/Affinity (noir en L=0, blanc en L=1, teinte
               pleine au milieu).
  "multiply" : calque couleur unie HSL + mode de fusion "Multiplier"
               (résultat = gris × couleur) — la teinte reste visible jusque
               dans les hautes lumières, contrairement à "colorize" qui
               désature vers le blanc pur.

Utile pour uniformiser le jaunissement de photos anciennes scannées, dont la
teinte d'origine varie d'un scan à l'autre.

Préréglages configurables dans CONSTANTS.py (section 12.7, VIRAGE_PRESETS) :
chaque préréglage fixe son propre mode + ses valeurs HSL.

Variables d'environnement :
  FOLDER_PATH     — dossier source (défaut : répertoire du script).
  SELECTED_FILES  — liste de noms séparés par ``|`` (filtre optionnel).
  VIRAGE_PRESET   — nom du préréglage (défaut : CONSTANTS.VIRAGE_DEFAULT_PRESET).
  VIRAGE_MODE     — force "colorize" ou "multiply" à la place du mode du
                    préréglage (défaut : mode du préréglage).
  VIRAGE_SHADOW_LIFT — remonte le point noir avant colorisation, % 0-100
                    (défaut : shadow_lift du préréglage, ou 0).

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
_preset = CONSTANTS.VIRAGE_PRESETS[PRESET_NAME]
MODE = os.environ.get("VIRAGE_MODE", _preset["mode"])
HUE_DEG = _preset["hue"]
SATURATION_PCT = _preset["sat"]
LIGHTNESS_PCT = _preset.get("light", 50)  # ignoré en mode "colorize"
SHADOW_LIFT_PCT = float(os.environ.get(
    "VIRAGE_SHADOW_LIFT", _preset.get("shadow_lift", 0)))

EXTENSION = (".JPG", ".JPEG", ".PNG", ".BMP", ".GIF", ".TIFF")  # extensions d'image acceptées
all_files = [file.name for file in sorted(PATH.iterdir()) if file.is_file() and file.suffix.upper() in EXTENSION and file.name != "watermark.png"]
FOLDER = [f for f in all_files if f in selected_files_set] if selected_files_set else all_files
TOTAL = len(FOLDER)

output_folder = PATH / "VIRAGE"
output_folder.mkdir(exist_ok=True)

_ascii_name = unicodedata.normalize("NFKD", PRESET_NAME).encode(
    "ascii", "ignore").decode("ascii")
if MODE != _preset["mode"]:
    # Mode forcé différent du préréglage : suffixe le nom de fichier pour
    # comparer les deux rendus sans que l'un écrase l'autre.
    _ascii_name += f"_{MODE}"
if SHADOW_LIFT_PCT != _preset.get("shadow_lift", 0):
    _ascii_name += f"_lift{round(SHADOW_LIFT_PCT)}"


def lift_shadows(gray, lift_pct):
    """Remonte le point noir avant colorisation, sans toucher le blanc :
    gray=0 -> lift_pct/100, gray=1 -> inchangé (pied de courbe argentique).
    Éclaircit l'image dans le fichier plutôt qu'en réduisant la densité à
    l'impression, ce qui délaverait aussi les hautes lumières colorées
    (retour user)."""
    if lift_pct <= 0:
        return gray
    lift = lift_pct / 100.0
    return lift + (1.0 - lift) * gray


def colorize_hsl(pil_img, hue_deg, saturation_pct, shadow_lift_pct=0):
    """Convertit en niveaux de gris puis colorise en HSL à teinte/saturation
    fixes — la luminosité de chaque pixel reste celle du noir et blanc,
    exactement comme "Coloriser" dans Photoshop/Affinity (noir en L=0,
    blanc en L=1, teinte pleine au milieu)."""
    gray = np.asarray(pil_img.convert("L"), dtype=np.float64) / 255.0
    gray = lift_shadows(gray, shadow_lift_pct)
    hue, sat = (hue_deg % 360) / 360.0, saturation_pct / 100.0
    # LUT de 256 entrées (une par niveau de gris possible) : colorsys ne
    # traite qu'un pixel à la fois, mais teinte/saturation étant fixes ici,
    # 256 appels suffisent au lieu d'un par pixel de l'image.
    lut = np.array(
        [colorsys.hls_to_rgb(hue, level / 255.0, sat) for level in range(256)],
        dtype=np.float32) * 255.0
    indices = np.clip(np.round(gray * 255), 0, 255).astype(np.uint8)
    return Image.fromarray(lut[indices].astype(np.uint8))


def colorize_multiply(pil_img, hue_deg, saturation_pct, lightness_pct,
                      shadow_lift_pct=0):
    """Convertit en niveaux de gris puis pose une couleur unie en mode
    Multiply par-dessus — exactement un calque couleur uni HSL + mode de
    fusion "Multiplier" dans Affinity/Photoshop (résultat = gris × couleur).

    Contrairement à "Coloriser" (substitution HSL), la teinte de la couleur
    reste visible jusque dans les hautes lumières : un gris à 255 (blanc)
    multiplié par la couleur redonne la couleur elle-même, jamais du blanc
    pur — un tirage papier ancien n'est jamais neutre, même dans ses zones
    les plus claires (retour user : hautes lumières "cramées" avec l'ancienne
    méthode, besoin de plus de contrôle sur la teinte obtenue).

    Multiply ne peut qu'assombrir (résultat <= gris) : shadow_lift_pct
    remonte le point noir en amont pour compenser une image trop sombre
    (retour user), sans toucher le blanc donc sans affecter la couleur des
    hautes lumières."""
    gray = np.asarray(pil_img.convert("L"), dtype=np.float64) / 255.0
    gray = lift_shadows(gray, shadow_lift_pct)
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
    if MODE == "multiply":
        result = colorize_multiply(base_image, HUE_DEG, SATURATION_PCT,
                                   LIGHTNESS_PCT, SHADOW_LIFT_PCT)
    else:
        result = colorize_hsl(base_image, HUE_DEG, SATURATION_PCT, SHADOW_LIFT_PCT)
    stem = Path(file).stem
    result.save(str(output_folder / f"{stem}_{_ascii_name}.jpg"),
               format="JPEG", subsampling=0, quality=100,
               icc_profile=image_ops._SRGB_ICC)

print("Terminé !")
