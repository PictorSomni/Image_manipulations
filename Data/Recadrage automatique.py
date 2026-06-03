# -*- coding: utf-8 -*-
"""
Recadre des images au format cible (mm) en mode "automatique".

Deux modes :
  - Mode crop (defaut) : recadrage plein-format via ImageOps.fit (remplit exactement).
  - Mode fit 100%      : image entiere placee dans le canvas sans rognage.
    * Une seule image  : positionnee en (0, 0) (coin haut-gauche) sur fond blanc.
    * Plusieurs copies : tuilees et centrees sur le canvas.

Variables d'environnement :
  FOLDER_PATH         -- dossier source (defaut : repertoire du script)
  SELECTED_FILES      -- liste de noms separes par "|" (filtre optionnel)
  FORCE_CROP_SIZE     -- format cible "LxH" en mm (ex: "102x152")
  FORCE_CROP_WIDTH    -- largeur manuelle en mm (fallback)
  FORCE_CROP_HEIGHT   -- hauteur manuelle en mm (fallback)
  FORCE_CROP_SCOPE    -- "selected" ou "all" (defaut : selected)
  FORCE_CROP_FIT      -- "1" pour le mode fit 100% (defaut : 0 = crop)

Sortie :
  Un sous-dossier nomme d'apres la taille cible (ex: "10x15" ou "12x17").
"""

__version__ = "2.7.4"

#############################################################
#                          IMPORTS                          #
#############################################################
import os
import re
from pathlib import Path
import sys

from PIL import Image, ImageFile, ImageOps

sys.path.insert(0, str(Path(__file__).resolve().parent))
import CONSTANTS


#############################################################
#                           PATH                            #
#############################################################
PATH = Path(os.environ.get("FOLDER_PATH", str(Path(__file__).resolve().parent)))


#############################################################
#                         CONTENT                           #
#############################################################
ImageFile.LOAD_TRUNCATED_IMAGES = True
DPI = CONSTANTS.DPI
TILE_GAP_MM = CONSTANTS.RECADRAGE_FORCE_TILE_GAP_MM
_EXTS = (".jpg", ".jpeg", ".png", ".bmp", ".tiff", ".tif", ".webp")
_SIZE_RE = re.compile(r"^\s*(\d+)\s*x\s*(\d+)\s*$", re.IGNORECASE)


def mm_to_pixels(mm: int, dpi: int) -> int:
    """Convertit des millimetres en pixels pour un DPI donne."""
    return round((float(mm) / 25.4) * dpi)


def normalize_mm_for_folder(mm: int) -> int:
    """Normalise les mm pour les noms de dossiers historiques (ex: 102->10, 127->13)."""
    mapping = {
        89: 9,
        102: 10,
        127: 13,
        152: 15,
        178: 18,
        203: 20,
        240: 24,
        297: 30,
        305: 30,
        405: 40,
        505: 50,
        605: 60,
        705: 70,
        805: 80,
        905: 90,
        1005: 100,
    }
    if mm in mapping:
        return mapping[mm]
    return int(round(mm / 10.0))


def parse_target_size_mm() -> tuple[int, int]:
    """Lit la taille cible depuis les variables d'environnement."""
    size_str = os.environ.get("FORCE_CROP_SIZE", "").strip()
    if size_str:
        match = _SIZE_RE.match(size_str)
        if match:
            width = int(match.group(1))
            height = int(match.group(2))
            if width > 0 and height > 0:
                return width, height

    width_str = os.environ.get("FORCE_CROP_WIDTH", "").strip()
    height_str = os.environ.get("FORCE_CROP_HEIGHT", "").strip()
    try:
        width = int(width_str)
        height = int(height_str)
        if width > 0 and height > 0:
            return width, height
    except Exception:
        pass

    # Defaut historique base sur 102x152 force
    return 102, 152


def list_images(scope: str) -> list[str]:
    """Retourne la liste des images a traiter selon la portee demandee."""
    all_files = [
        f.name
        for f in sorted(PATH.iterdir())
        if f.is_file() and f.suffix.lower() in _EXTS and f.name.lower() != "watermark.png"
    ]

    selected_raw = os.environ.get("SELECTED_FILES", "")
    selected_set = {name for name in selected_raw.split("|") if name} if selected_raw else set()

    if scope == "selected" and selected_set:
        return [name for name in all_files if name in selected_set]
    return all_files


def process_fit(img: Image.Image, canvas_w: int, canvas_h: int) -> Image.Image:
    """
    Place img a sa taille reelle (100%) dans le canvas (canvas_w x canvas_h) :
    - pas d'agrandissement : une petite image reste a sa taille physique.
    - downscale uniquement si l'image est plus grande que le canvas.
    - si une seule copie tient : placee en (0, 0) sur fond blanc.
    - si plusieurs copies tiennent : tuilees et centrees sur le canvas.
    Retourne toujours une image de taille exacte (canvas_w x canvas_h).
    """
    # Ratio : jamais > 1.0 (on ne grandit pas l'image)
    ratio = min(canvas_w / img.width, canvas_h / img.height, 1.0)
    fit_w = round(img.width * ratio)
    fit_h = round(img.height * ratio)
    if ratio < 1.0:
        img_resized = img.resize((fit_w, fit_h), Image.Resampling.LANCZOS)
    else:
        img_resized = img  # taille native, pas de resampling

    # Combien de copies tiennent sur le canvas avec un espace mini configurable ?
    # n*tile + (n-1)*gap <= canvas  =>  n <= (canvas + gap) / (tile + gap)
    gap_px = mm_to_pixels(TILE_GAP_MM, DPI)
    cols = (canvas_w + gap_px) // (fit_w + gap_px)
    rows = (canvas_h + gap_px) // (fit_h + gap_px)
    if cols < 1:
        cols = 1
    if rows < 1:
        rows = 1

    canvas = Image.new("RGB", (canvas_w, canvas_h), (255, 255, 255))

    if cols == 1 and rows == 1:
        # Une seule image : coin (0, 0)
        canvas.paste(img_resized, (0, 0))
    else:
        # Plusieurs copies : centrees, avec interstice minimum configure
        total_w = cols * fit_w + (cols - 1) * gap_px
        total_h = rows * fit_h + (rows - 1) * gap_px
        offset_x = (canvas_w - total_w) // 2
        offset_y = (canvas_h - total_h) // 2
        for row in range(rows):
            for col in range(cols):
                x = offset_x + col * (fit_w + gap_px)
                y = offset_y + row * (fit_h + gap_px)
                canvas.paste(img_resized, (x, y))

    return canvas


#############################################################
#                           MAIN                            #
#############################################################
if not PATH.is_dir():
    print(f"[ERREUR] Dossier introuvable : {PATH}")
    sys.exit(1)

scope = os.environ.get("FORCE_CROP_SCOPE", "selected").strip().lower()
if scope not in {"selected", "all"}:
    scope = "selected"

fit_mode = os.environ.get("FORCE_CROP_FIT", "0").strip() == "1"

width_mm, height_mm = parse_target_size_mm()
images = list_images(scope)
total = len(images)

if total == 0:
    if scope == "selected":
        print("[INFO] Aucune image selectionnee. Rien a traiter.")
    else:
        print("[INFO] Aucune image trouvee dans le dossier.")
    sys.exit(0)

# Conserver la logique historique: orienter le format avec largeur >= hauteur
if width_mm < height_mm:
    width_mm, height_mm = height_mm, width_mm

width_px = mm_to_pixels(width_mm, DPI)
height_px = mm_to_pixels(height_mm, DPI)

folder_name = f"{normalize_mm_for_folder(height_mm)}x{normalize_mm_for_folder(width_mm)}"
output_folder = PATH / folder_name
output_folder.mkdir(exist_ok=True)

mode_label = "fit 100%" if fit_mode else "crop"
print(f"Format cible : {width_mm}x{height_mm} mm ({width_px}x{height_px} px @ {DPI} DPI)")
print(f"Mode        : {mode_label}")
print(f"Portee      : {'selection' if scope == 'selected' else 'tout le dossier'}")
print(f"Sortie      : {output_folder}")
print("#" * 40)

ok_count = 0
err_count = 0

for index, filename in enumerate(images, start=1):
    source_path = PATH / filename
    print(f"[{index}/{total}] {filename}")

    try:
        with Image.open(source_path) as img:
            img = ImageOps.exif_transpose(img)

            if fit_mode:
                # Mode fit : image entiere dans le canvas, sans rognage
                # On oriente l'image comme le canvas (paysage > paysage)
                canvas_w, canvas_h = width_px, height_px
                if (img.width < img.height) != (canvas_w < canvas_h):
                    img = img.rotate(90, expand=True)
                result = process_fit(img, canvas_w, canvas_h)
            else:
                # Mode crop : remplissage exact (comportement historique)
                rotated_back = False
                if img.width < img.height:
                    img = img.rotate(90, expand=True)
                    rotated_back = True
                result = ImageOps.fit(img, (width_px, height_px), method=Image.Resampling.LANCZOS)
                if rotated_back:
                    result = result.rotate(270, expand=True)

            result = result.convert("RGB")
            stem = source_path.stem
            out_path = output_folder / f"{folder_name}_{stem}.jpg"
            result.save(out_path, dpi=(DPI, DPI), format="JPEG", subsampling=0, quality=100)

        ok_count += 1
    except Exception as exc:
        err_count += 1
        print(f"[ERREUR] {filename} : {exc}")

print("#" * 40)
print(f"Termine ! {ok_count} image(s) traitee(s), {err_count} erreur(s).")
