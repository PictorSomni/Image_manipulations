# -*- coding: utf-8 -*-
"""
Prépare un montage photo (grille bien rangée -> scrapbook "lâché") sur un
canevas à la taille finale demandée par le client, à partir de toutes les
images d'un dossier.

Répartit les photos sur une grille approximative puis fait varier position
(COLLAGE_POSITION_VARIATION, grille bien rangée à scatter "lâché"), taille
(COLLAGE_SIZE_VARIATION) et rotation (COLLAGE_ROTATION_VARIATION) de
chacune, indépendamment. Une marge de sécurité (COLLAGE_SAFE_MARGIN_CM)
tient la grille éloignée du bord réel du canevas, pour limiter le risque de
détail important coupé au massicot. Une photo peut être désignée comme
centrale (COLLAGE_CENTER_FILE, agrandie, posée au milieu, jamais pivotée) et
d'autres comme mises en avant (COLLAGE_FEATURED_FILES, agrandies).

Produit un aperçu à taille réelle (``Montage/apercu.png``, fond transparent)
et, si demandé, un fichier .psd avec chaque photo sur son propre calque déjà
placé — reste à retoucher les bords (flou, ombre) et poser le fond dans
Affinity.

Variables d'environnement :
  FOLDER_PATH              — dossier source (défaut : répertoire du script).
  SELECTED_FILES           — liste de noms séparés par ``|`` (filtre optionnel).
  COLLAGE_WIDTH_CM         — largeur du canevas final, en cm.
  COLLAGE_HEIGHT_CM        — hauteur du canevas final, en cm.
  COLLAGE_DPI              — résolution en ppp (défaut CONSTANTS.COLLAGE_DPI_DEFAULT).
  COLLAGE_POSITION_VARIATION — 0-100, grille bien rangée (0) à scatter "lâché" (100) (défaut CONSTANTS.COLLAGE_POSITION_VARIATION_DEFAULT).
  COLLAGE_SIZE_VARIATION   — 0-100, écart de taille entre photos (défaut CONSTANTS.COLLAGE_SIZE_VARIATION_DEFAULT).
  COLLAGE_ROTATION_VARIATION — 0-100, amplitude de rotation (défaut CONSTANTS.COLLAGE_ROTATION_VARIATION_DEFAULT).
  COLLAGE_SAFE_MARGIN_CM   — marge de sécurité près des bords, en cm (défaut CONSTANTS.COLLAGE_SAFE_MARGIN_CM_DEFAULT).
  COLLAGE_CENTER_FILE      — nom d'une photo à poser au centre, agrandie (optionnel).
  COLLAGE_FEATURED_FILES   — noms de photos à mettre en avant, séparés par ``|`` (optionnel).
  COLLAGE_PSD              — "1" pour écrire aussi un .psd calque par calque.
  COLLAGE_SEED             — graine aléatoire (optionnel, pour reproduire un tirage).

Dépendances : Pillow, numpy (déjà requis par image_ops).
  Optionnel (COLLAGE_PSD=1 uniquement) : pytoshop, six.
"""

__version__ = "2.0.0"

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

# Une photo mise en avant (mais pas centrale) ressort ~60% plus grande que
# la variation de taille normale ne le ferait déjà — assez pour se voir
# nettement dans le tas sans écraser le reste (pas exposé en réglage : un
# multiplicateur de plus n'apporterait rien que la case à cocher ne dise
# déjà, cf. retour user).
FEATURED_SCALE_BOOST = 1.6

#############################################################
#                          LAYOUT                            #
#############################################################

def compute_layout(photo_keys, canvas_w, canvas_h, size_variation,
                   rotation_variation, position_variation, seed=None,
                   margin_px=0, center_key=None, featured_keys=frozenset()):
    """Place chaque clé de `photo_keys` sur une grille approx. de la taille
    du canevas (moins `margin_px` de marge sur chaque bord), puis fait
    varier indépendamment position (`position_variation` — 0 = cellule de
    grille pile centrée, 100 = scatter façon scrapbook), taille
    (`size_variation`) et rotation (`rotation_variation`), chacune 0-100.

    `center_key`, si présent dans `photo_keys`, est retirée du tirage de
    grille et posée au milieu du canevas, agrandie, jamais pivotée. Les
    clés de `featured_keys` reçoivent un coup de pouce de taille en plus
    de la variation aléatoire normale.

    Renvoie une liste de (center_x, center_y, box_w, box_h, angle_deg)
    dans le MÊME ORDRE que `photo_keys` (donc aussi l'ordre d'empilement
    en cas de recouvrement, la centrale mise à part — toujours dessinée
    en dernier, cf. render_montage)."""
    rng = random.Random(seed)
    usable_w = max(1, canvas_w - 2 * margin_px)
    usable_h = max(1, canvas_h - 2 * margin_px)

    others = [k for k in photo_keys if k != center_key]
    count = len(others)
    cols = max(1, round(math.sqrt(max(count, 1) * usable_w / usable_h)))
    rows = math.ceil(count / cols) if count else 0
    cell_w = usable_w / cols
    cell_h = usable_h / rows if rows else usable_h

    cells = [(c, r) for r in range(rows) for c in range(cols)]
    rng.shuffle(cells)

    size_t = max(0.0, min(1.0, size_variation / 100)) ** 0.6
    rotation_t = max(0.0, min(1.0, rotation_variation / 100))
    position_t = max(0.0, min(1.0, position_variation / 100))
    # Grossit toutes les boîtes (centrale incluse, ci-dessous) dans la
    # même proportion pour compenser le jitter de position et fermer les
    # trous qu'il crée sinon (retour user).
    overlap = 1 + position_t * 0.7

    placed = {}
    for key, (c, r) in zip(others, cells):
        cx = margin_px + (c + 0.5) * cell_w
        cy = margin_px + (r + 0.5) * cell_h
        # Indépendant de size_variation (retour user) : un slider dédié
        # pour aller d'une grille bien rangée (0) à un scatter façon
        # scrapbook (100) — 0.6 de la cellule laisse largement déborder
        # sur les cellules voisines au maximum, sans perdre l'idée de
        # grille de départ qui garantit une couverture homogène du
        # canevas quel que soit le réglage.
        jitter = position_t * min(cell_w, cell_h) * 0.6
        cx += rng.uniform(-jitter, jitter)
        cy += rng.uniform(-jitter, jitter)
        # Asymétrique (-0.5 à +1.1) plutôt que centré sur 1 : quelques
        # photos nettement plus grandes que la moyenne, comme un vrai
        # scrapbook composé à la main plutôt qu'une grille uniformément
        # redimensionnée (retour user : les tailles restaient trop
        # semblables avec un écart symétrique étroit).
        scale = max(0.35, 1 + rng.uniform(-0.5, 1.1) * size_t)
        if key in featured_keys:
            scale *= FEATURED_SCALE_BOOST
        angle = rng.uniform(-28, 28) * rotation_t
        placed[key] = (cx, cy, cell_w * scale * overlap,
                      cell_h * scale * overlap, angle)

    # Le chevauchement qui referme les trous ci-dessus peut, à l'inverse,
    # faire disparaître une petite tuile complètement sous une plus
    # grande dessinée par-dessus (retour user : aucune photo ne doit être
    # totalement recouverte). Écarte chaque tuile plus grande dessinée
    # après elle dans `others` (donc au-dessus, cf. ordre de calque dans
    # render_montage) jusqu'à ce qu'un bord dépasse. Approximation par
    # cercle inscrit (rayon = plus petit demi-côté) qui ignore la
    # rotation exacte — suffisant pour garantir un morceau visible sans
    # viser une géométrie pixel-perfect ; une seule passe, ne rattrape
    # pas les conflits en chaîne (rare avec un nombre de photos usuel).
    for i, ki in enumerate(others):
        cxi, cyi, wi, hi, ai = placed[ki]
        ri = min(wi, hi) / 2
        for kj in others[i + 1:]:
            cxj, cyj, wj, hj, _ = placed[kj]
            rj = min(wj, hj) / 2
            if rj <= ri:
                continue
            dx, dy = cxi - cxj, cyi - cyj
            dist = math.hypot(dx, dy)
            min_dist = rj - ri + 0.15 * ri
            if dist >= min_dist:
                continue
            if dist < 1e-6:
                angle_push = rng.uniform(0, 2 * math.pi)
                dx, dy, dist = math.cos(angle_push), math.sin(angle_push), 1.0
            cxi = cxj + dx / dist * min_dist
            cyi = cyj + dy / dist * min_dist
            cxi = max(margin_px + wi / 2,
                      min(cxi, canvas_w - margin_px - wi / 2))
            cyi = max(margin_px + hi / 2,
                      min(cyi, canvas_h - margin_px - hi / 2))
        placed[ki] = (cxi, cyi, wi, hi, ai)

    if center_key is not None and center_key in photo_keys:
        box_w = min(usable_w * 0.9, cell_w * 2.2 * overlap)
        box_h = min(usable_h * 0.9, cell_h * 2.2 * overlap)
        placed[center_key] = (canvas_w / 2, canvas_h / 2, box_w, box_h, 0.0)

    return [placed[k] for k in photo_keys]


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


def render_montage(photo_keys, canvas_w, canvas_h, size_variation,
                   rotation_variation, position_variation, margin_px, seed,
                   load_source, *, center_key=None,
                   featured_keys=frozenset(),
                   log=lambda msg: print(msg, flush=True)):
    """Calcule le placement (compute_layout) puis compose tout sur un
    canevas RGBA. `load_source(key)` doit renvoyer une image PIL RGBA (ou
    None pour l'ignorer) — c'est ce qui change entre le rendu final (pleine
    résolution, image_ops.open_srgb) et un aperçu rapide (miniatures
    thumb_cache côté Hub), le placement et le rendu restant identiques.

    Renvoie (canvas, layers) où layers est une liste de (nom, tuile RGBA
    visible, left, top) — pour l'écriture PSD, ou pour rien si non utilisée.
    La photo centrale (s'il y en a une) est dessinée en dernier, donc
    toujours au-dessus du reste, et n'est jamais recalée par la marge
    (les autres si, cf. boucle ci-dessous — compute_layout ne fait
    qu'ESPACER la grille de départ, sans garantir qu'une tuile agrandie
    par la variation de taille ne déborde pas jusqu'au bord réel)."""
    order = photo_keys
    if center_key is not None and center_key in photo_keys:
        order = [k for k in photo_keys if k != center_key] + [center_key]
    layout = dict(zip(photo_keys, compute_layout(
        photo_keys, canvas_w, canvas_h, size_variation, rotation_variation,
        position_variation, seed, margin_px, center_key, featured_keys)))

    canvas = Image.new("RGBA", (canvas_w, canvas_h), (0, 0, 0, 0))
    layers = []
    total = len(order)
    for index, key in enumerate(order, start=1):
        cx, cy, box_w, box_h, angle = layout[key]
        log(f"{index} / {total} — {key}")
        try:
            source = load_source(key)
        except Exception as exc:
            log(f"[WARN] {key} ignorée : {exc}")
            continue
        if source is None:
            continue
        tile = fit_and_rotate(source, box_w, box_h, angle)
        tw, th = tile.size
        left, top = round(cx - tw / 2), round(cy - th / 2)
        if key != center_key:
            # Recale (ne recadre pas) pour que la marge de sécurité tienne
            # même quand taille aléatoire + décalage auraient fait déborder
            # jusqu'au bord réel — la case "grille inset" seule n'y
            # suffisait pas dès qu'une photo grossissait beaucoup (retour
            # user). Si la tuile est plus grande que la zone utile, ancrée
            # côté marge plutôt que de dépasser des deux côtés à la fois.
            left = max(margin_px, min(left, canvas_w - margin_px - tw))
            top = max(margin_px, min(top, canvas_h - margin_px - th))
        clip_left, clip_top = max(left, 0), max(top, 0)
        clip_right = min(left + tw, canvas_w)
        clip_bottom = min(top + th, canvas_h)
        if clip_right <= clip_left or clip_bottom <= clip_top:
            log(f"[WARN] {key} entièrement hors cadre, ignorée.")
            continue
        visible = tile.crop((clip_left - left, clip_top - top,
                             clip_right - left, clip_bottom - top))
        canvas.alpha_composite(visible, (clip_left, clip_top))
        layers.append((Path(str(key)).stem, visible, clip_left, clip_top))
    return canvas, layers

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
    size_variation = max(0.0, min(100.0, env_float(
        "COLLAGE_SIZE_VARIATION", CONSTANTS.COLLAGE_SIZE_VARIATION_DEFAULT)))
    rotation_variation = max(0.0, min(100.0, env_float(
        "COLLAGE_ROTATION_VARIATION", CONSTANTS.COLLAGE_ROTATION_VARIATION_DEFAULT)))
    position_variation = max(0.0, min(100.0, env_float(
        "COLLAGE_POSITION_VARIATION", CONSTANTS.COLLAGE_POSITION_VARIATION_DEFAULT)))
    safe_margin_cm = env_float(
        "COLLAGE_SAFE_MARGIN_CM", CONSTANTS.COLLAGE_SAFE_MARGIN_CM_DEFAULT)
    write_psd = os.environ.get("COLLAGE_PSD", "0") == "1"
    seed = os.environ.get("COLLAGE_SEED") or None

    center_file = os.environ.get("COLLAGE_CENTER_FILE", "").strip() or None
    if center_file and center_file not in photo_names:
        center_file = None
    featured_str = os.environ.get("COLLAGE_FEATURED_FILES", "")
    featured_files = frozenset(
        f for f in featured_str.split("|") if f) & frozenset(photo_names)

    canvas_w = round(width_cm / 2.54 * dpi)
    canvas_h = round(height_cm / 2.54 * dpi)
    margin_px = round(safe_margin_cm / 2.54 * dpi)
    out_dir = PATH / "Montage"
    out_dir.mkdir(exist_ok=True)

    print(f"[INFO] Canevas {canvas_w}x{canvas_h}px "
          f"({width_cm:g}x{height_cm:g}cm @ {dpi:g}ppp), "
          f"{len(photo_names)} photo(s), position={position_variation:g} "
          f"taille={size_variation:g} rotation={rotation_variation:g} "
          f"marge={safe_margin_cm:g}cm", flush=True)

    def load_source(name):
        return image_ops.open_srgb(PATH / name).convert("RGBA")

    canvas, psd_layers = render_montage(
        photo_names, canvas_w, canvas_h, size_variation, rotation_variation,
        position_variation, margin_px, seed, load_source,
        center_key=center_file, featured_keys=featured_files)

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
