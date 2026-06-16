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
  GRAIN_SIZE         — taille en pixels (1.0 = grain fin, 2.0-3.0 = gros grain)
  GRAIN_COLOR_RATIO  — part de grain couleur (0.0 = mono pur, 0.3 = subtil, 1.0 = plein)
  GRAIN_SHADOW_BOOST — concentration sur les mi-tons (1.0 = large, 2.0 = centré, 3.0 = serré)

Variables d'environnement :
  FOLDER_PATH     — dossier source (défaut : répertoire du script).
  SELECTED_FILES  — liste de noms séparés par ``|`` (filtre optionnel).

Dépendances : OpenCV (cv2), NumPy, Pillow (PIL)
"""

__version__ = "2.8.4"

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


def add_filmic_curve(
    pil_img: Image.Image,
    shoulder_start: float,
    shoulder_strength: float,
    toe_start: float,
    toe_lift: float,
) -> Image.Image:
    """Courbe tonale argentique : épaulement dans les HL + pied dans les ombres.

    Applique une courbe non-linéaire inspirée de la caractéristique des films argentiques :
    les hautes lumières sont compressées (évite l'écrêtage brutal) et les noirs
    sont légèrement relevés (densité minimale du film).

    shoulder_start    : seuil au-dessus duquel les HL sont compressées (ex. 0.80)
    shoulder_strength : force de la compression (0 = linéaire, 0.5 = standard, 1.5 = forte)
    toe_start         : seuil en dessous duquel les ombres sont relevées (ex. 0.06)
    toe_lift          : amplitude du relèvement des noirs (0 = aucun, 0.1 = subtil)
    """
    img = np.array(pil_img, dtype=np.float32) / 255.0
    result = img.copy()

    # Épaulement : spline de Hermite cubique C¹ — pente = 1 au seuil (raccord lisse
    # avec la zone linéaire), pente = (1 - s) à 1.0 (compression douce au sommet).
    # f(t) = -s·t³ + s·t² + t   →   f'(0) = 1, f'(1) = 1-s, f(0)=0, f(1)=1.
    # Remplace t^(1+s) qui créait un genou brusque (pente 1 → 0 instantané au seuil).
    if shoulder_strength > 0:
        t = np.clip((img - shoulder_start) / max(1e-6, 1.0 - shoulder_start), 0.0, 1.0)
        f = -shoulder_strength * t**3 + shoulder_strength * t**2 + t
        compressed = shoulder_start + (1.0 - shoulder_start) * f
        result = np.where(img > shoulder_start, compressed, result)

    # Pied : relèvement linéaire des pixels très sombres (densité minimale film)
    if toe_lift > 0 and toe_start > 0:
        t_toe = np.clip(1.0 - result / max(1e-6, toe_start), 0.0, 1.0)
        result = result + t_toe * toe_lift * toe_start

    return Image.fromarray((np.clip(result, 0.0, 1.0) * 255).astype(np.uint8))


def add_desaturate_extremes(
    pil_img: Image.Image,
    shadow_threshold: float,
    shadow_intensity: float,
    highlight_threshold: float,
    highlight_intensity: float,
    midtone_boost: float = 0.0,
) -> Image.Image:
    """Désature les ombres/HL et booste optionnellement la saturation des mi-tons.

    shadow_threshold    : luma en dessous duquel les ombres sont désaturées (ex. 0.25)
    shadow_intensity    : force de la désaturation dans les ombres (0.0–1.0)
    highlight_threshold : luma au-dessus duquel les hautes lumières sont désaturées (ex. 0.85)
    highlight_intensity : force de la désaturation dans les hautes lumières (0.0–1.0)
    midtone_boost       : saturation supplémentaire en mi-tons (0 = aucun, 0.3 = prononcé)
    """
    img = np.array(pil_img, dtype=np.float32) / 255.0
    luma = 0.299 * img[:, :, 0] + 0.587 * img[:, :, 1] + 0.114 * img[:, :, 2]
    gray = np.stack([luma, luma, luma], axis=-1)

    # Masque doux pour les ombres : 1.0 en luma=0, 0.0 au seuil
    shadow_mask = np.clip(1.0 - luma / max(1e-6, shadow_threshold), 0.0, 1.0)[:, :, np.newaxis]
    # Masque doux pour les hautes lumières : 0.0 au seuil, 1.0 en luma=1
    highlight_mask = np.clip(
        (luma - highlight_threshold) / max(1e-6, 1.0 - highlight_threshold), 0.0, 1.0
    )[:, :, np.newaxis]

    result = img + (gray - img) * shadow_mask * shadow_intensity
    result = result + (gray - result) * highlight_mask * highlight_intensity

    if midtone_boost > 0:
        # Masque mi-tons = (1 - shadow_mask) × (1 - highlight_mask) :
        # vaut 1 entre les deux seuils, retombe à 0 aux extrêmes.
        midtone_mask = (1.0 - shadow_mask) * (1.0 - highlight_mask)
        result = result + (result - gray) * midtone_mask * midtone_boost

    return Image.fromarray((np.clip(result, 0.0, 1.0) * 255).astype(np.uint8))


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
    # Parabole centrée sur les mi-tons avec plancher : peak à luma=0.5 (×1.0),
    # ombres/hautes lumières à 30 % — grain présent partout mais atténué aux extrêmes
    weight = 0.3 + 0.7 * np.clip(4.0 * luma * (1.0 - luma), 0.0, 1.0) ** shadow_boost
    weight = weight[:, :, np.newaxis]

    result = np.clip(img + grain * weight, 0.0, 1.0)
    return Image.fromarray((result * 255).astype(np.uint8))


def add_halation(
    pil_img: Image.Image,
    threshold: float,
    radius: float,
    intensity: float,
    red_shift: float,
) -> Image.Image:
    """Halo rougeâtre autour des hautes lumières (rebond de lumière sur la base du film).

    radius est exprimé en % de la plus petite dimension de l'image (ex. 5 = 5 %).
    Blend mode Screen : img + h - img·h — jamais de clipping sur les HL déjà proches de 1.0.
    """
    img = np.array(pil_img, dtype=np.float32) / 255.0
    h, w = img.shape[:2]
    luma = 0.299 * img[:, :, 0] + 0.587 * img[:, :, 1] + 0.114 * img[:, :, 2]

    # Masque doux au-dessus du seuil
    mask = np.clip((luma - threshold) / max(1e-6, 1.0 - threshold), 0.0, 1.0)

    # Layer de halo basé sur le masque seul (pas img*mask) : la lumière réfléchie
    # par la base du film est indépendante des pixels sombres environnants.
    halo = np.stack([
        np.clip(mask * (1.0 + red_shift), 0.0, 1.0),         # canal R boosté
        mask * max(0.0, 1.0 - red_shift * 0.2),              # canal G légèrement réduit
        mask * max(0.0, 1.0 - red_shift * 0.6),              # canal B atténué
    ], axis=-1).astype(np.float32)

    # Sigma en pixels (radius = % de la plus petite dim).
    # On floute à résolution réduite (effet basse fréquence) pour la vitesse :
    # on cible sigma ~20px dans l'espace réduit, puis on remonte.
    sigma = max(1.0, radius / 100.0 * min(h, w))
    scale = min(1.0, 20.0 / sigma)
    if scale < 1.0:
        sh, sw = max(1, int(h * scale)), max(1, int(w * scale))
        halo_s = cv2.resize(halo, (sw, sh), interpolation=cv2.INTER_AREA)
        halo_s = cv2.GaussianBlur(halo_s, (0, 0), sigmaX=sigma * scale, sigmaY=sigma * scale)
        blurred = cv2.resize(halo_s, (w, h), interpolation=cv2.INTER_LINEAR).astype(np.float32)
    else:
        blurred = cv2.GaussianBlur(halo, (0, 0), sigmaX=sigma, sigmaY=sigma)

    # Screen : img + h - img·h  (jamais de clipping — pixel à 0.95 avec halo 0.15
    # donne 0.9575 au lieu de 1.10 en additif ; sur luma=0 le halo s'exprime pleinement)
    halo = blurred * intensity
    result = np.clip(img + halo - img * halo, 0.0, 1.0)
    return Image.fromarray((result * 255).astype(np.uint8))


def add_bloom(
    pil_img: Image.Image,
    radius: float,
    intensity: float,
) -> Image.Image:
    """Glow général par superposition de l'image floutée en mode Soft Light.

    radius est exprimé en % de la plus petite dimension de l'image (ex. 6 = 6 %).
    Soft Light renforce le contraste et la saturation perçue — effect argentique prononcé.
    La courbe (shoulder) permet d'atténuer a posteriori quand l'effet est trop marqué.
    """
    img = np.array(pil_img, dtype=np.float32) / 255.0
    h, w = img.shape[:2]
    sigma = max(1.0, radius / 100.0 * min(h, w))
    scale = min(1.0, 20.0 / sigma)
    if scale < 1.0:
        sh, sw = max(1, int(h * scale)), max(1, int(w * scale))
        img_s = cv2.resize(img, (sw, sh), interpolation=cv2.INTER_AREA)
        img_s = cv2.GaussianBlur(img_s, (0, 0), sigmaX=sigma * scale, sigmaY=sigma * scale)
        blurred = cv2.resize(img_s, (w, h), interpolation=cv2.INTER_LINEAR).astype(np.float32)
    else:
        blurred = cv2.GaussianBlur(img, (0, 0), sigmaX=sigma, sigmaY=sigma).astype(np.float32)
    # Soft Light (Photoshop)
    D = np.where(img <= 0.25,
                 ((16.0 * img - 12.0) * img + 4.0) * img,
                 np.sqrt(np.clip(img, 0.0, 1.0)))
    soft = np.where(blurred <= 0.5,
                    img - (1.0 - 2.0 * blurred) * img * (1.0 - img),
                    img + (2.0 * blurred - 1.0) * (D - img))
    result = img * (1.0 - intensity) + np.clip(soft, 0.0, 1.0) * intensity
    return Image.fromarray((np.clip(result, 0.0, 1.0) * 255).astype(np.uint8))


#############################################################
#                           MAIN                            #
#############################################################
for index, file_name in enumerate(files_to_process):
    print(f"Image {index + 1} sur {total}")
    try:
        pil_img = Image.open(folder_path / file_name).convert("RGB")
    except Exception:
        continue

    result = pil_img
    if DESAT_ENABLED:
        print("  → Désaturation des extrêmes...")
        result = add_desaturate_extremes(result, DESAT_SHADOW_THRESHOLD, DESAT_SHADOW_INTENSITY,
                                         DESAT_HIGHLIGHT_THRESHOLD, DESAT_HIGHLIGHT_INTENSITY,
                                         DESAT_MIDTONE_BOOST)
    if HALATION_ENABLED:
        print("  → Halation...")
        result = add_halation(result, HALATION_THRESHOLD, HALATION_RADIUS, HALATION_INTENSITY, HALATION_RED_SHIFT)
    if BLOOM_ENABLED:
        print("  → Bloom...")
        result = add_bloom(result, BLOOM_RADIUS, BLOOM_INTENSITY)
    if CURVE_ENABLED:
        print("  → Courbe tonale...")
        result = add_filmic_curve(result, CURVE_SHOULDER_START, CURVE_SHOULDER_STRENGTH,
                                  CURVE_TOE_START, CURVE_TOE_LIFT)
    if GRAIN1_ENABLED:
        print("  → Grain 1...")
        result = add_film_grain(result, AMOUNT, SIZE, COLOR_RATIO, SHADOW_BOOST)
    if GRAIN2_ENABLED:
        print("  → Grain 2...")
        result = add_film_grain(result, AMOUNT2, SIZE2, COLOR_RATIO2, SHADOW_BOOST2)
    stem = Path(file_name).stem
    result.save(str(output_folder / f"{stem}.jpg"), format="JPEG", subsampling=0, quality=100)

print("Terminé !")
