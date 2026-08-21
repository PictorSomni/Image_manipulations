# -*- coding: utf-8 -*-
"""
Recadre des images au format cible (mm) en mode "automatique".

Deux modes :
  - Mode crop (defaut) : recadrage plein-format via ImageOps.fit (remplit exactement).
  - Mode fit 100%      : image entiere placee dans le canvas sans rognage.
    * Une seule image  : positionnee en (0, 0) (coin haut-gauche) sur fond blanc.
    * Plusieurs copies : tuilees et centrees sur le canvas.

Nomenclature des fichiers :
  - Le nom de sortie ne répète pas le format cible : le fichier est déjà
    dans le sous-dossier nommé d'après le format (ex: "10x15/").
  - Préfixe NX_ (ex: "2X_photo.jpg", "3x_maphoto.png") = nombre d'impressions
    demandé. Il est TOUJOURS respecté, dans les deux modes :
    * Mode crop : une image recadrée, le préfixe est reporté tel quel sur le
      fichier de sortie ("3X_photo.jpg" -> "3X_photo.jpg").
    * Mode fit  : N copies tuilées sur le canvas. Si elles n'y tiennent pas
      toutes, on génère autant de canvas que nécessaire — le dernier reste
      partiellement blanc plutôt que d'être complété par des copies en trop.
      Le nombre de copies effectivement présentes sur chaque canevas est
      toujours reporté en préfixe (y compris quand toutes les copies
      tiennent sur un seul canevas).
  - Sans préfixe : mode automatique (le canvas est rempli au maximum en mode
    fit, une image en mode crop), et aucun préfixe en sortie.

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

__version__ = "3.1.0"

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
import image_ops


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
_COPY_COUNT_RE = re.compile(r"^(\d+)X_", re.IGNORECASE)  # Correction : IGNORECASE ajouté pour supporter "3x_"


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


def parse_crop_count() -> int:
    """Lit le nombre d'impressions (copies) par image depuis les variables d'environnement."""
    count_str = os.environ.get("FORCE_CROP_COUNT", "").strip()
    if count_str:
        try:
            count = int(count_str)
            if count > 0:
                return count
        except Exception:
            pass
    return 1


def extract_copy_count_from_filename(filename: str) -> tuple[int | None, str]:
    """
    Extrait le nombre de copies depuis le préfixe NX_ du nom de fichier.
    Retourne (count, clean_filename).
    
    Exemple : "2X_photo.jpg" -> (2, "photo.jpg")         # force 2 copies
              "1x_photo.jpg" -> (1, "photo.jpg")         # force 1 copie
              "photo.jpg"    -> (None, "photo.jpg")      # mode automatique (autant que possible)
    """
    match = _COPY_COUNT_RE.match(filename)
    if match:
        count = int(match.group(1))
        clean = filename[match.end():]
        return count, clean
    return None, filename


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


def resize_to_fit(img: Image.Image, canvas_w: int, canvas_h: int) -> tuple[Image.Image, int, int]:
    """
    Redimensionne img a sa taille reelle (100%) sans agrandir.
    - pas d'agrandissement : une petite image reste a sa taille physique.
    - downscale uniquement si l'image est plus grande que le canvas.
    
    Retourne (image_resized, fit_w, fit_h)
    """
    ratio = min(canvas_w / img.width, canvas_h / img.height, 1.0)
    fit_w = round(img.width * ratio)
    fit_h = round(img.height * ratio)
    if ratio < 1.0:
        img_resized = img.resize((fit_w, fit_h), Image.Resampling.LANCZOS)
    else:
        img_resized = img.copy()  # taille native, pas de resampling
    return img_resized, fit_w, fit_h


def calculate_tile_grid(tile_w: int, tile_h: int, canvas_w: int, canvas_h: int) -> tuple[int, int]:
    """
    Calcule le nombre de colonnes et rangees de tuiles (tile_w x tile_h)
    qui tiennent dans le canvas (canvas_w x canvas_h) avec ecart configurable.
    
    Retourne (cols, rows).
    """
    gap_px = mm_to_pixels(TILE_GAP_MM, DPI)
    
    if tile_w <= 0 or tile_h <= 0:
        return 1, 1
    
    # Formule : n*tile + (n-1)*gap <= canvas
    #          n*(tile + gap) <= canvas + gap
    #          n <= (canvas + gap) / (tile + gap)
    cols = max(1, (canvas_w + gap_px) // (tile_w + gap_px))
    rows = max(1, (canvas_h + gap_px) // (tile_h + gap_px))
    
    return cols, rows


def pack_tiles_into_canvases(tiles_list: list, canvas_w: int, canvas_h: int,
                              *, center_single: bool = False) -> list:
    """
    Pack une liste de tuiles (tile_dict avec 'image', 'width', 'height', 'count')
    dans des canvases (canvas_w x canvas_h), en remplissant au maximum.

    Si une tuile a forced_count=N, elle doit avoir exactement N copies (pouvant être
    repartie sur plusieurs canevas). Sinon, mettre le max possible.

    `center_single` : quand une seule tuile rentre dans le canevas, la
    centrer au lieu de la caler en haut-gauche (0, 0) — défaut : coin.

    Retourne une liste de canvases remplis (canvas_image, list_of_tuiles_placees).
    """
    if not tiles_list:
        return []
    
    gap_px = mm_to_pixels(TILE_GAP_MM, DPI)
    canvases = []
    remaining_tiles = []
    
    # Créer une liste de tuiles individuelles a placer
    for tile_dict in tiles_list:
        tile_image = tile_dict['image']
        tile_count = tile_dict['count']  # 1 si auto, ou N si forcé
        for _ in range(tile_count):
            remaining_tiles.append({
                'image': tile_image,
                'width': tile_dict['width'],
                'height': tile_dict['height'],
                'source_name': tile_dict['source_name']
            })
    
    while remaining_tiles:
        # Créer un nouveau canvas
        canvas = Image.new("RGB", (canvas_w, canvas_h), (255, 255, 255))
        canvas_tiles = []
        
        # Calculer combien de tuiles rentrent
        if remaining_tiles:
            first_tile_w = remaining_tiles[0]['width']
            first_tile_h = remaining_tiles[0]['height']
            cols, rows = calculate_tile_grid(first_tile_w, first_tile_h, canvas_w, canvas_h)
            max_tiles_in_canvas = cols * rows
        else:
            max_tiles_in_canvas = 0
        
        if max_tiles_in_canvas == 0:
            break
        
        # Placer les tuiles
        tiles_to_place = min(len(remaining_tiles), max_tiles_in_canvas)
        tiles_for_canvas = remaining_tiles[:tiles_to_place]
        remaining_tiles = remaining_tiles[tiles_to_place:]
        
        if not tiles_for_canvas:
            break
        
        # Redimensionner et placer les tuiles
        resized_tiles = []
        for tile_dict in tiles_for_canvas:
            img_resized, fit_w, fit_h = resize_to_fit(tile_dict['image'], canvas_w, canvas_h)
            resized_tiles.append({
                'image': img_resized,
                'width': fit_w,
                'height': fit_h,
                'source_name': tile_dict['source_name']
            })
        
        # Gérer le positionnement : haut-gauche si une seule tuile peut rentrer, centré sinon
        first_tile = resized_tiles[0]
        cols, rows = calculate_tile_grid(first_tile['width'], first_tile['height'], canvas_w, canvas_h)
        
        if cols == 1 and rows == 1 and not center_single:
            # Une seule image rentre dans le format : on la cale en haut à gauche (0, 0)
            offset_x = 0
            offset_y = 0
        else:
            # Plusieurs tuiles rentrent : on centre la grille de tuiles sur le canvas
            total_w = cols * first_tile['width'] + max(0, (cols - 1)) * gap_px
            total_h = rows * first_tile['height'] + max(0, (rows - 1)) * gap_px
            offset_x = (canvas_w - total_w) // 2
            offset_y = (canvas_h - total_h) // 2
        
        # Placer les tuiles en grille.
        #
        # Les places restantes du dernier canevas sont laissées BLANCHES.
        # Elles étaient auparavant comblées par des copies de la dernière
        # tuile : demander 3 tirages avec 2 par planche en sortait 4 (2 + 2
        # au lieu de 2 + 1). Le nombre d'impressions prime sur le
        # remplissage du papier — quitte à finir sur une planche partielle,
        # comme le fait « 2 en 1.py » (retour user).
        tile_index = 0
        for row in range(rows):
            for col in range(cols):
                if tile_index >= len(resized_tiles):
                    break
                tile = resized_tiles[tile_index]
                # Position calculee d'apres la dimension de chaque tuile
                x = offset_x + col * (tile['width'] + gap_px)
                y = offset_y + row * (tile['height'] + gap_px)
                canvas.paste(tile['image'], (x, y))
                canvas_tiles.append((tile['source_name'], x, y))
                tile_index += 1
        
        canvases.append((canvas, canvas_tiles))
    
    return canvases


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
center_single = os.environ.get("FORCE_CROP_CENTER", "0").strip() == "1"
white_border_mode = os.environ.get("FORCE_CROP_WHITE_BORDER", "0").strip() == "1"

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

if fit_mode:
    # ==== MODE FIT 100% : BATCH PACKING ====
    tiles_list = []
    
    # Étape 1 : Charger toutes les images et extraire les tuiles
    for index, filename in enumerate(images, start=1):
        source_path = PATH / filename
        print(f"[Lecture {index}/{total}] {filename}")
        
        try:
            copy_count, clean_filename = extract_copy_count_from_filename(filename)
            
            img = image_ops.open_srgb(source_path)

            # Orienter l'image comme le canvas (paysage > paysage)
            if (img.width < img.height) != (width_px < height_px):
                img = img.rotate(90, expand=True)

            img_rgb = img

            # Ajouter à la liste des tuiles
            # Si copy_count est None, mettre 1 par défaut (on ajustera pour les non-forcés après)
            tile_count = copy_count if copy_count is not None else 1

            tiles_list.append({
                'image': img_rgb.copy(),
                'width': img_rgb.width,
                'height': img_rgb.height,
                'count': tile_count,
                'source_name': Path(clean_filename).stem,
                'forced': copy_count is not None
            })
        except Exception as exc:
            print(f"[ERREUR] {filename} : {exc}")
    
    print("#" * 40)
    
    # Étape 2 : Séparer et Packer les tuiles de manière intelligente
    if tiles_list:
        all_canvases = []  # Liste finale de tuples : (canvas, canvas_tiles, suggested_stem)
        
        # 1. Traiter d'abord les images avec nombre d'impressions forcé (ex: 2X_photo.jpg)
        # On les regroupe ensemble pour optimiser l'espace
        prefixed_tiles = [t for t in tiles_list if t['forced']]
        if prefixed_tiles:
            prefixed_canvases = pack_tiles_into_canvases(
                prefixed_tiles, width_px, height_px, center_single=center_single)
            for canvas, canvas_tiles in prefixed_canvases:
                # Si toutes les tuiles de ce canevas viennent du même fichier, on prend son nom
                # Sinon, on utilise le mot-clé historique "combined"
                unique_sources = list({name for name, x, y in canvas_tiles})
                suggested_stem = unique_sources[0] if len(unique_sources) == 1 else "combined"
                all_canvases.append((canvas, canvas_tiles, suggested_stem))
        
        # 2. Traiter les images SANS préfixe (mode automatique)
        # Chaque image a droit à son propre canevas rempli au maximum de copies d'elle-même
        non_prefixed_tiles = [t for t in tiles_list if not t['forced']]
        for tile in non_prefixed_tiles:
            # Calculer dynamiquement combien de copies de cette image rentrent dans le canevas
            img_resized, fit_w, fit_h = resize_to_fit(tile['image'], width_px, height_px)
            cols, rows = calculate_tile_grid(fit_w, fit_h, width_px, height_px)
            max_tiles = cols * rows
            
            # On force la quantité à ce maximum pour remplir entièrement la grille
            tile['count'] = max_tiles
            
            # On génère le canevas pour cette image unique
            single_canvases = pack_tiles_into_canvases(
                [tile], width_px, height_px, center_single=center_single)
            for canvas, canvas_tiles in single_canvases:
                all_canvases.append((canvas, canvas_tiles, tile['source_name']))
        
        # Étape 3 : Sauvegarder les canvases avec gestion propre des doublons de noms
        # Compter d'abord combien de fois chaque nom de fichier va être généré
        stem_counts = {}
        for _, _, stem in all_canvases:
            stem_counts[stem] = stem_counts.get(stem, 0) + 1

        # Exception single-fit : si une image avec préfixe NX_ ne tient qu'une seule
        # fois dans le canvas (cols=1, rows=1), on reporte le N sur le nom de fichier
        # exporté et on ne génère qu'un seul canvas au lieu de N identiques.
        single_fit_stems = {
            stem
            for stem, count in stem_counts.items()
            if count > 1 and all(
                len(ct) == 1
                for _, ct, s in all_canvases
                if s == stem
            )
        }

        # Stems dont le nombre de copies a été forcé via préfixe NX_ (à
        # distinguer du mode automatique, qui ne porte pas de nombre à
        # reporter).
        forced_stems = {t['source_name'] for t in tiles_list if t['forced']}

        # Le nom du format n'est plus préfixé au nom de fichier : le
        # fichier est déjà dans le sous-dossier nommé d'après le format
        # (output_folder), le répéter ne fait qu'alourdir le nom. En
        # revanche le préfixe NX_ (nombre d'exemplaires) doit toujours
        # être conservé quand il est connu — y compris quand toutes les
        # copies forcées tiennent sur un seul canevas, cas où il était
        # perdu auparavant (retour user).
        saved_count = 0
        name_counts = {}
        already_saved = set()
        for canvas, canvas_tiles, stem in all_canvases:
            unique_sources = {name for name, x, y in canvas_tiles}
            if stem in single_fit_stems:
                if stem in already_saved:
                    continue
                already_saved.add(stem)
                prefix = f"{stem_counts[stem]}X_"
            elif len(unique_sources) == 1 and stem in forced_stems:
                prefix = f"{len(canvas_tiles)}X_"
            else:
                prefix = ""

            base_name = f"{prefix}{stem}"
            idx = name_counts.get(base_name, 0)
            name_counts[base_name] = idx + 1
            out_filename = (f"{base_name}.jpg" if idx == 0
                             else f"{base_name}_{idx + 1}.jpg")

            canvas_rgb = canvas.convert("RGB")
            out_path = output_folder / out_filename
            canvas_rgb.save(out_path, dpi=(DPI, DPI), format="JPEG",
                            subsampling=0, quality=100,
                            icc_profile=image_ops._SRGB_ICC)
            saved_count += 1

            print(f"✓ {out_filename} ({len(canvas_tiles)} tuile(s))")
            for source_name, x, y in canvas_tiles:
                print(f"   - {source_name}")

        ok_count = saved_count
    else:
        ok_count = 0
        err_count = len(images)
else:
    # ==== MODE CROP : TRAITEMENT PAR IMAGE ====
    ok_count = 0
    err_count = 0
    
    for index, filename in enumerate(images, start=1):
        source_path = PATH / filename
        print(f"[{index}/{total}] {filename}")

        try:
            copy_count, clean_filename = extract_copy_count_from_filename(filename)
            
            img = image_ops.open_srgb(source_path)

            # Mode crop : remplissage exact (comportement historique)
            rotated_back = False
            if img.width < img.height:
                img = img.rotate(90, expand=True)
                rotated_back = True
            if white_border_mode:
                border_px = mm_to_pixels(5, DPI)
                inner_w = width_px - 2 * border_px
                inner_h = height_px - 2 * border_px
                ratio = min(inner_w / img.width, inner_h / img.height)
                new_w = round(img.width * ratio)
                new_h = round(img.height * ratio)
                fitted = img.resize((new_w, new_h), Image.Resampling.LANCZOS)
                result = Image.new("RGB", (width_px, height_px), (255, 255, 255))
                result.paste(fitted, ((width_px - new_w) // 2, (height_px - new_h) // 2))
            else:
                result = ImageOps.fit(img, (width_px, height_px), method=Image.Resampling.LANCZOS)
            if rotated_back:
                result = result.rotate(270, expand=True)

            # Déterminer le nom de sortie. Le préfixe NX_ est REPORTÉ sur
            # le fichier recadré : sans lui, le nombre d'impressions était
            # perdu au recadrage et la photo disparaissait de commande.txt,
            # qui ne compte que les fichiers préfixés (retour user). Le nom
            # du format n'est plus répété dans le nom de fichier : le
            # fichier est déjà dans le sous-dossier nommé d'après le
            # format (retour user).
            stem = Path(clean_filename).stem
            prefix = f"{copy_count}X_" if copy_count is not None else ""
            out_path = output_folder / f"{prefix}{stem}.jpg"

            result.save(out_path, dpi=(DPI, DPI), format="JPEG",
                       subsampling=0, quality=100,
                       icc_profile=image_ops._SRGB_ICC)

            ok_count += 1
        except Exception as exc:
            err_count += 1
            print(f"[ERREUR] {filename} : {exc}")

print("#" * 40)
if fit_mode:
    print(f"Termine ! {ok_count} canvas genere(e)s.")