# -*- coding: utf-8 -*-
"""
Prépare un montage photo (grille bien rangée -> scrapbook "lâché") sur un
canevas à la taille finale demandée par le client, à partir de toutes les
images d'un dossier.

Répartit les photos sur une grille approximative puis, selon COLLAGE_CHAOS
(0 = mosaïque, 100 = photos lâchées), fait varier la position, la taille et
la rotation de chacune. Produit un aperçu à taille réelle
(``Montage/apercu.png``, fond transparent) et, si demandé, un fichier .psd
avec chaque photo sur son propre calque déjà placé — reste à retoucher les
bords (flou, ombre) et poser le fond dans Affinity.

Variables d'environnement :
  FOLDER_PATH        — dossier source (défaut : répertoire du script).
  SELECTED_FILES     — liste de noms séparés par ``|`` (filtre optionnel).
  COLLAGE_WIDTH_CM   — largeur du canevas final, en cm.
  COLLAGE_HEIGHT_CM  — hauteur du canevas final, en cm.
  COLLAGE_DPI        — résolution en ppp (défaut CONSTANTS.COLLAGE_DPI_DEFAULT).
  COLLAGE_CHAOS      — 0-100 (défaut CONSTANTS.COLLAGE_CHAOS_DEFAULT).
  COLLAGE_PSD        — "1" pour écrire aussi un .psd calque par calque.
  COLLAGE_SEED       — graine aléatoire (optionnel, pour reproduire un tirage).

Dépendances : Pillow, numpy (déjà requis par image_ops).
  Optionnel (COLLAGE_PSD=1 uniquement) : pytoshop, six.
"""

__version__ = "1.0.0"

#############################################################
#                          IMPORTS                          #
#############################################################
import math
import os
import random
import sys
from pathlib import Path

from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parent))
import CONSTANTS
import image_ops

#############################################################
#                           PATH                            #
#############################################################
PATH = Path(os.environ.get("FOLDER_PATH", str(Path(__file__).resolve().parent)))

#############################################################
#                          LAYOUT                            #
#############################################################

def compute_layout(count, canvas_w, canvas_h, chaos, seed=None):
    """Place `count` photos sur une grille approx. de la taille du canevas,
    puis fait varier position/taille/rotation selon `chaos` (0-100).
    Renvoie une liste de (center_x, center_y, box_w, box_h, angle_deg),
    une par photo, dans l'ordre où elles doivent être dessinées (donc
    l'ordre d'empilement en cas de recouvrement)."""
    rng = random.Random(seed)
    cols = max(1, round(math.sqrt(count * canvas_w / canvas_h)))
    rows = math.ceil(count / cols)
    cell_w, cell_h = canvas_w / cols, canvas_h / rows
    cells = [(c, r) for r in range(rows) for c in range(cols)]
    rng.shuffle(cells)
    layout = []
    for c, r in cells[:count]:
        cx, cy = (c + 0.5) * cell_w, (r + 0.5) * cell_h
        jitter = (chaos / 100) * min(cell_w, cell_h) * 0.35
        cx += rng.uniform(-jitter, jitter)
        cy += rng.uniform(-jitter, jitter)
        scale = 1 + rng.uniform(-0.25, 0.45) * (chaos / 100)
        angle = rng.uniform(-22, 22) * (chaos / 100)
        layout.append((cx, cy, cell_w * scale, cell_h * scale, angle))
    return layout


def fit_and_rotate(image, box_w, box_h, angle_deg):
    """Redimensionne `image` (RGBA) pour tenir dans box_w x box_h (« contain »,
    sans recadrage) puis pivote — expand=True agrandit le cadre pour ne rien
    couper aux coins. rotate() n'accepte pas LANCZOS (transform affine, cf.
    image_ops.py:488-492) : BICUBIC pour la rotation, LANCZOS pour le resize."""
    ratio = min(box_w / image.width, box_h / image.height)
    new_size = (max(1, round(image.width * ratio)),
                max(1, round(image.height * ratio)))
    resized = image.resize(new_size, Image.Resampling.LANCZOS)
    if abs(angle_deg) < 0.05:
        return resized
    return resized.rotate(angle_deg, expand=True,
                          resample=Image.Resampling.BICUBIC)

#############################################################
#                           MAIN                            #
#############################################################

def main():
    extensions = (".jpg", ".jpeg", ".png", ".bmp", ".tiff", ".tif", ".webp")
    selected_files_str = os.environ.get("SELECTED_FILES", "")
    selected_files_set = (set(selected_files_str.split("|"))
                          if selected_files_str else None)
    if selected_files_set:
        photo_names = sorted(f for f in selected_files_set
                             if (PATH / f).is_file()
                             and Path(f).suffix.lower() in extensions)
    else:
        photo_names = sorted(f.name for f in PATH.iterdir()
                             if f.is_file() and f.suffix.lower() in extensions)
    if not photo_names:
        print("[x] Aucune photo trouvée.", flush=True)
        return

    def env_float(key, default):
        try:
            return float(os.environ.get(key, str(default)))
        except ValueError:
            return default

    width_cm  = env_float("COLLAGE_WIDTH_CM", CONSTANTS.COLLAGE_WIDTH_CM_DEFAULT)
    height_cm = env_float("COLLAGE_HEIGHT_CM", CONSTANTS.COLLAGE_HEIGHT_CM_DEFAULT)
    dpi       = env_float("COLLAGE_DPI", CONSTANTS.COLLAGE_DPI_DEFAULT)
    chaos     = max(0.0, min(100.0, env_float(
        "COLLAGE_CHAOS", CONSTANTS.COLLAGE_CHAOS_DEFAULT)))
    write_psd = os.environ.get("COLLAGE_PSD", "0") == "1"
    seed = os.environ.get("COLLAGE_SEED") or None

    canvas_w = round(width_cm / 2.54 * dpi)
    canvas_h = round(height_cm / 2.54 * dpi)
    out_dir = PATH / "Montage"
    out_dir.mkdir(exist_ok=True)

    print(f"[INFO] Canevas {canvas_w}x{canvas_h}px "
          f"({width_cm:g}x{height_cm:g}cm @ {dpi:g}ppp), "
          f"{len(photo_names)} photo(s), chaos={chaos:g}", flush=True)

    layout = compute_layout(len(photo_names), canvas_w, canvas_h, chaos, seed)
    canvas = Image.new("RGBA", (canvas_w, canvas_h), (0, 0, 0, 0))
    psd_layers = []  # (nom, tuile RGBA visible, left, top) — si write_psd

    for index, (name, (cx, cy, box_w, box_h, angle)) in enumerate(
            zip(photo_names, layout), start=1):
        print(f"{index} / {len(photo_names)} — {name}", flush=True)
        try:
            source = image_ops.open_srgb(PATH / name).convert("RGBA")
        except Exception as exc:
            print(f"[WARN] {name} ignorée : {exc}", flush=True)
            continue
        tile = fit_and_rotate(source, box_w, box_h, angle)
        tw, th = tile.size
        left, top = round(cx - tw / 2), round(cy - th / 2)
        clip_left, clip_top = max(left, 0), max(top, 0)
        clip_right = min(left + tw, canvas_w)
        clip_bottom = min(top + th, canvas_h)
        if clip_right <= clip_left or clip_bottom <= clip_top:
            print(f"[WARN] {name} entièrement hors cadre, ignorée.", flush=True)
            continue
        visible = tile.crop((clip_left - left, clip_top - top,
                             clip_right - left, clip_bottom - top))
        canvas.alpha_composite(visible, (clip_left, clip_top))
        if write_psd:
            psd_layers.append((Path(name).stem, visible, clip_left, clip_top))

    preview_path = out_dir / "apercu.png"
    canvas.save(preview_path)
    print(f"[ok] Aperçu → {preview_path.name} ({canvas_w}x{canvas_h}px)",
          flush=True)

    if write_psd:
        write_psd_file(out_dir / "Montage.psd", canvas, psd_layers,
                       canvas_w, canvas_h)

    print("[ok] Terminé.", flush=True)


def write_psd_file(psd_path, canvas, psd_layers, canvas_w, canvas_h):
    """Écrit un .psd avec un calque par photo (pixels déjà mis à l'échelle
    et pivotés, position déjà posée) + l'image composite requise par le
    format PSD (sans elle, Pillow/certains lecteurs affichent une page
    blanche — cf. test manuel avant intégration)."""
    try:
        import numpy as np
        import pytoshop
        from pytoshop import layers as psd_layer_mod
        from pytoshop.enums import ColorMode, Compression
        from pytoshop.image_data import ImageData
    except ImportError:
        print("[WARN] pytoshop introuvable (pip install pytoshop six) — "
              ".psd non généré, l'aperçu PNG reste disponible.", flush=True)
        return

    records = []
    for layer_name, tile_img, left, top in psd_layers:
        arr = np.array(tile_img)
        channels = {
            0: psd_layer_mod.ChannelImageData(image=arr[..., 0], compression=Compression.raw),
            1: psd_layer_mod.ChannelImageData(image=arr[..., 1], compression=Compression.raw),
            2: psd_layer_mod.ChannelImageData(image=arr[..., 2], compression=Compression.raw),
            -1: psd_layer_mod.ChannelImageData(image=arr[..., 3], compression=Compression.raw),
        }
        records.append(psd_layer_mod.LayerRecord(
            channels=channels, top=top, left=left,
            bottom=top + arr.shape[0], right=left + arr.shape[1],
            name=layer_name, opacity=255))

    psd = pytoshop.core.PsdFile(num_channels=4, height=canvas_h,
                                width=canvas_w, color_mode=ColorMode.rgb)
    psd.layer_and_mask_info.layer_info = psd_layer_mod.LayerInfo(
        layer_records=records)
    comp = np.array(canvas)
    psd.image_data = ImageData(
        channels=np.stack([comp[..., i] for i in range(4)], axis=0),
        compression=Compression.raw)
    with open(psd_path, "wb") as f:
        psd.write(f)
    print(f"[ok] PSD → {psd_path.name} ({len(records)} calque(s))", flush=True)


if __name__ == "__main__":
    main()
