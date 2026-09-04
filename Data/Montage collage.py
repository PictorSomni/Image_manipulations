# -*- coding: utf-8 -*-
"""
Prépare un montage photo (mosaïque à tailles variables, façon scrapbook)
sur un canevas à la taille finale demandée par le client, à partir de
toutes les images d'un dossier.

Répartit les photos par un partage récursif de l'aire du canevas
proportionnel au poids (COLLAGE_SIZE_VARIATION) de chacune — garantit par
construction que les tuiles couvrent TOUT le canevas, sans trou ni
recouvrement entre elles (le seul chevauchement volontaire vient de la
photo centrale, cf. plus bas). Une légère rotation
(COLLAGE_ROTATION_VARIATION) peut ensuite être appliquée à chaque tuile,
rétrécie d'autant qu'il faut pour que sa boîte pivotée tienne quand même
dans sa case d'origine — elle ne déborde donc jamais sur une voisine. Une
marge de sécurité (COLLAGE_SAFE_MARGIN_CM) tient la mosaïque éloignée du
bord réel du canevas, pour limiter le risque de détail important coupé au
massicot. Une photo peut être désignée comme centrale (COLLAGE_CENTER_FILE,
agrandie, posée au milieu, jamais pivotée) et d'autres comme mises en
avant (COLLAGE_FEATURED_FILES, agrandies).

Produit un aperçu à taille réelle (``Montage/apercu.png``, fond transparent)
et, si demandé, un fichier .psd avec chaque photo sur son propre calque déjà
placé — reste à retoucher les bords (flou, ombre) et poser le fond dans
Affinity.

Variables d'environnement :
  FOLDER_PATH              — dossier source (défaut : répertoire du script).
  SELECTED_FILES           — liste de noms séparés par ``|`` (filtre optionnel).
  COLLAGE_WIDTH_CM         — largeur du canevas final, en cm.
  COLLAGE_HEIGHT_CM        — hauteur du canevas final, en cm.
  COLLAGE_DPI              — résolution en ppp (défaut CONSTANTS.DPI).
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

__version__ = "3.0.0"

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

# Une photo mise en avant (mais pas centrale) reçoit un poids ~60% plus
# élevé dans le partage de l'aire (cf. _split_weighted) — assez pour se
# voir nettement dans le tas sans écraser le reste (pas exposé en réglage :
# un multiplicateur de plus n'apporterait rien que la case à cocher ne
# dise déjà, cf. retour user).
FEATURED_SCALE_BOOST = 1.6

#############################################################
#                          LAYOUT                            #
#############################################################

def _split_weighted(items, x, y, w, h):
    """Partitionne récursivement le rectangle (x, y, w, h) en autant de
    sous-rectangles que d'`items` (liste de (poids, clé)), chacun
    proportionnel à son poids — coupe toujours le long du plus grand côté
    du rectangle courant (évite les bandes trop fines). L'union des
    rectangles renvoyés couvre EXACTEMENT (x, y, w, h), sans trou ni
    recouvrement entre eux : c'est ce qui garantit qu'un écart de taille
    marqué (poids très différents) ne laisse jamais de fond transparent
    visible ni ne fait chevaucher deux photos entre elles (retour user :
    "certaines images clairement plus petites et d'autres clairement plus
    grandes... qu'elles se repositionnent pour avoir le moins de vide
    possible" — la grille à jitter précédente ne pouvait pas garantir ça,
    ce partage récursif le garantit par construction).

    Renvoie une liste de (clé, x, y, w, h)."""
    if len(items) == 1:
        return [(items[0][1], x, y, w, h)]
    total = sum(wt for wt, _ in items)
    # Sépare en 2 groupes de poids aussi égal que possible (glouton sur
    # les poids triés décroissants — pas besoin de l'optimal, juste d'un
    # partage raisonnable pour que chaque moitié récursive reste
    # équilibrée).
    ordered = sorted(items, key=lambda t: -t[0])
    group_a, sum_a = [], 0.0
    for wt, k in ordered:
        if not group_a or sum_a < total / 2:
            group_a.append((wt, k))
            sum_a += wt
        else:
            break
    group_b = ordered[len(group_a):]
    if not group_b:
        # Poids extrêmement inégaux (ex. 1 item boosté qui dépasse déjà à
        # lui seul la moitié du total) : lui laisser sa propre part plutôt
        # que de forcer les autres à la partager avec lui.
        group_b = [group_a.pop()]
        sum_a -= group_b[0][0]
    frac_a = sum_a / total
    if w >= h:
        wa = min(w - 1, max(1, round(w * frac_a)))
        return (_split_weighted(group_a, x, y, wa, h)
               + _split_weighted(group_b, x + wa, y, w - wa, h))
    ha = min(h - 1, max(1, round(h * frac_a)))
    return (_split_weighted(group_a, x, y, w, ha)
           + _split_weighted(group_b, x, y + ha, w, h - ha))


def _rotation_safe_scale(box_w, box_h, angle_deg):
    """Facteur d'échelle (<=1) à appliquer à (box_w, box_h) pour que la
    boîte ENGLOBANTE une fois pivotée (expand=True, cf. fit_and_rotate)
    tienne quand même dans (box_w, box_h) d'origine. Sans ce
    rétrécissement, une tuile pivotée déborderait sur sa voisine — aucune
    des deux n'a de marge prévue pour ça, cf. _split_weighted qui les fait
    se toucher pile."""
    if abs(angle_deg) < 0.05:
        return 1.0
    rad = math.radians(angle_deg)
    c, s = abs(math.cos(rad)), abs(math.sin(rad))
    ext_w = box_w * c + box_h * s
    ext_h = box_w * s + box_h * c
    return min(box_w / ext_w, box_h / ext_h)


def compute_layout(photo_keys, canvas_w, canvas_h, size_variation,
                   rotation_variation, seed=None, margin_px=0,
                   center_key=None, featured_keys=frozenset()):
    """Place chaque clé de `photo_keys` sur le canevas (moins `margin_px`
    de marge sur chaque bord) par un partage récursif de l'aire disponible
    proportionnel au poids de chacune (cf. _split_weighted) — les tuiles
    couvrent ainsi TOUJOURS tout le canevas, sans trou ni recouvrement
    entre elles, quel que soit le nombre de photos. `size_variation`
    (0-100) pilote l'écart entre les poids : 0 = tous égaux (mosaïque
    régulière), 100 = certaines tuiles nettement plus grandes que
    d'autres. Une rotation (`rotation_variation`, 0-100) peut ensuite être
    appliquée à chaque tuile, rétrécie d'autant qu'il faut pour que sa
    boîte pivotée tienne quand même dans sa case d'origine (cf.
    _rotation_safe_scale) — jamais de débordement sur une voisine.

    `center_key`, si présent dans `photo_keys`, est retirée du partage et
    posée au milieu du canevas, agrandie, jamais pivotée, volontairement
    au-dessus du reste (mise en avant délibérée, cf. render_montage). Les
    clés de `featured_keys` reçoivent un poids plus élevé dans le partage
    — donc une case proportionnellement plus grande.

    Renvoie une liste de (center_x, center_y, box_w, box_h, angle_deg)
    dans le MÊME ORDRE que `photo_keys` (donc aussi l'ordre d'empilement,
    la centrale mise à part — toujours dessinée en dernier, cf.
    render_montage)."""
    rng = random.Random(seed)
    usable_w = max(1, canvas_w - 2 * margin_px)
    usable_h = max(1, canvas_h - 2 * margin_px)

    others = [k for k in photo_keys if k != center_key]
    size_t = max(0.0, min(1.0, size_variation / 100)) ** 0.6
    rotation_t = max(0.0, min(1.0, rotation_variation / 100))

    weights = []
    for key in others:
        # Asymétrique (-0.5 à +1.1) plutôt que centré sur 1 : quelques
        # photos nettement plus grandes que la moyenne, comme un vrai
        # scrapbook composé à la main plutôt qu'une mosaïque uniformément
        # redimensionnée (retour user : les tailles restaient trop
        # semblables avec un écart symétrique étroit).
        weight = max(0.35, 1 + rng.uniform(-0.5, 1.1) * size_t)
        if key in featured_keys:
            weight *= FEATURED_SCALE_BOOST
        weights.append((weight, key))
    # Mélange avant le partage récursif (qui trie par poids en interne) :
    # sans ça, deux photos consécutives dans `photo_keys` finiraient
    # presque toujours voisines sur le canevas.
    rng.shuffle(weights)

    placed = {}
    if others:
        for key, x, y, w, h in _split_weighted(weights, margin_px, margin_px,
                                               usable_w, usable_h):
            angle = rng.uniform(-28, 28) * rotation_t
            scale = _rotation_safe_scale(w, h, angle)
            placed[key] = (x + w / 2, y + h / 2, w * scale, h * scale, angle)

    if center_key is not None and center_key in photo_keys:
        # Taille "nominale" de référence : l'aire moyenne qu'aurait une
        # tuile si le canevas était partagé également entre toutes les
        # autres photos, à l'aspect ratio du canevas — sert juste à faire
        # ressortir la centrale nettement au-dessus de cette moyenne.
        count = max(1, len(others))
        nominal_w = usable_w / math.sqrt(count)
        nominal_h = usable_h / math.sqrt(count)
        box_w = min(usable_w * 0.9, nominal_w * 2.2)
        box_h = min(usable_h * 0.9, nominal_h * 2.2)
        placed[center_key] = (canvas_w / 2, canvas_h / 2, box_w, box_h, 0.0)

    return [placed[k] for k in photo_keys]


def fit_and_rotate(image, box_w, box_h, angle_deg):
    """Redimensionne `image` (RGBA) pour REMPLIR box_w x box_h (« cover » —
    recadre l'excédent au centre, jamais de bande transparente dans la
    tuile) puis pivote — expand=True agrandit le cadre pour ne rien couper
    aux coins. rotate() n'accepte pas LANCZOS (transform affine, cf.
    image_ops.py:488-492) : BICUBIC pour la rotation, LANCZOS pour le
    resize.

    Cover plutôt que contain (retour user) : même une mosaïque sans le
    moindre trou (cf. compute_layout) laissait de grandes bandes
    transparentes DANS chaque tuile dès que l'aspect ratio de la photo ne
    collait pas à celui de sa case — "les gens paient pour voir leurs
    photos, pas du vide". Recadre au centre : perd un peu des bords les
    plus longs, jamais le centre du sujet."""
    box_w, box_h = max(1, round(box_w)), max(1, round(box_h))
    ratio = max(box_w / image.width, box_h / image.height)
    new_size = (max(box_w, round(image.width * ratio)),
                max(box_h, round(image.height * ratio)))
    resized = image.resize(new_size, Image.Resampling.LANCZOS)
    left = (resized.width - box_w) // 2
    top = (resized.height - box_h) // 2
    cropped = resized.crop((left, top, left + box_w, top + box_h))
    if abs(angle_deg) < 0.05:
        return cropped
    return cropped.rotate(angle_deg, expand=True,
                          resample=Image.Resampling.BICUBIC)


def render_montage(photo_keys, canvas_w, canvas_h, size_variation,
                   rotation_variation, margin_px, seed, load_source, *,
                   center_key=None, featured_keys=frozenset(),
                   log=lambda msg: print(msg, flush=True)):
    """Calcule le placement (compute_layout) puis compose tout sur un
    canevas RGBA. `load_source(key)` doit renvoyer une image PIL RGBA (ou
    None pour l'ignorer) — c'est ce qui change entre le rendu final (pleine
    résolution, image_ops.open_srgb) et un aperçu rapide (miniatures
    thumb_cache côté Hub), le placement et le rendu restant identiques.

    Renvoie (canvas, layers) où layers est une liste de (nom, tuile RGBA
    visible, left, top) — pour l'écriture PSD, ou pour rien si non
    utilisée. La photo centrale (s'il y en a une) est dessinée en dernier,
    donc toujours au-dessus du reste."""
    order = photo_keys
    if center_key is not None and center_key in photo_keys:
        order = [k for k in photo_keys if k != center_key] + [center_key]
    layout = dict(zip(photo_keys, compute_layout(
        photo_keys, canvas_w, canvas_h, size_variation, rotation_variation,
        seed, margin_px, center_key, featured_keys)))

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
            # Recale (ne recadre pas) — filet de sécurité pour que la
            # marge tienne même si un futur réglage produisait une tuile
            # plus grande que sa case ; les tuiles de la mosaïque
            # (compute_layout) ne la dépassent normalement jamais.
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
    dpi       = env_float("COLLAGE_DPI", CONSTANTS.DPI)
    size_variation = max(0.0, min(100.0, env_float(
        "COLLAGE_SIZE_VARIATION", CONSTANTS.COLLAGE_SIZE_VARIATION_DEFAULT)))
    rotation_variation = max(0.0, min(100.0, env_float(
        "COLLAGE_ROTATION_VARIATION", CONSTANTS.COLLAGE_ROTATION_VARIATION_DEFAULT)))
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
          f"{len(photo_names)} photo(s), taille={size_variation:g} "
          f"rotation={rotation_variation:g} marge={safe_margin_cm:g}cm",
          flush=True)

    def load_source(name):
        return image_ops.open_srgb(PATH / name).convert("RGBA")

    canvas, psd_layers = render_montage(
        photo_names, canvas_w, canvas_h, size_variation, rotation_variation,
        margin_px, seed, load_source,
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
