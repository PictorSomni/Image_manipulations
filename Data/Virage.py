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
import os
import re
import unicodedata
from pathlib import Path
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
        result = image_ops.colorize_multiply(base_image, HUE_DEG, SATURATION_PCT,
                                             LIGHTNESS_PCT, SHADOW_LIFT_PCT)
    else:
        result = image_ops.colorize_hsl(base_image, HUE_DEG, SATURATION_PCT,
                                        SHADOW_LIFT_PCT)
    stem = Path(file).stem
    result.save(str(output_folder / f"{stem}_{_ascii_name}.jpg"),
               format="JPEG", subsampling=0, quality=100,
               icc_profile=image_ops._SRGB_ICC)

print("Terminé !")
