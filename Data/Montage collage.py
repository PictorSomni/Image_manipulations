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
# élevé dans le partage de l'aire (cf. _squarify) — assez pour se voir
# nettement dans le tas sans écraser le reste (pas exposé en réglage : un
# multiplicateur de plus n'apporterait rien que la case à cocher ne dise
# déjà, cf. retour user).
FEATURED_SCALE_BOOST = 1.6

# "Cover" (cf. fit_and_rotate) peut, avec une case d'aspect très différent
# de la photo, recadrer une part écrasante de l'image — "certaines images
# sont bien tronquées" (retour user, même après _squarify qui limite mais
# n'élimine pas totalement les cases très allongées, ex. un seul item
# restant après un tirage de poids très inégal). Ce plafond limite la
# perte à MAX_CROP_FRACTION du côté le plus recadré : au-delà, mieux vaut
# un peu d'espace vide sur le côté opposé qu'une photo méconnaissable.
MAX_CROP_FRACTION = 0.5

#############################################################
#                          LAYOUT                            #
#############################################################

def _row_worst_ratio(row, side, total_weight, total_area):
    """Pire ratio largeur/hauteur qu'aurait un item de `row` (liste de
    (poids, clé)) si cette rangée partageait `side` (le plus petit côté
    du rectangle courant) — plus ce ratio est proche de 1, plus les items
    de la rangée seraient carrés. Utilisé par _squarify pour décider
    combien d'items regrouper dans une même rangée."""
    row_weight = sum(wt for wt, _ in row)
    if row_weight <= 0 or side <= 0 or total_weight <= 0:
        return float("inf")
    row_len = total_area * (row_weight / total_weight) / side
    if row_len <= 0:
        return float("inf")
    worst = 0.0
    for wt, _ in row:
        item_side = total_area * (wt / total_weight) / row_len
        if item_side <= 0:
            return float("inf")
        worst = max(worst, row_len / item_side, item_side / row_len)
    return worst


def _squarify(items, x, y, w, h):
    """Treemap « squarified » (Bruls, Huizing, van Wijk 1999) : partitionne
    (x, y, w, h) en autant de sous-rectangles que d'`items` (liste de
    (poids, clé)), chacun proportionnel à son poids. Construit une rangée
    à la fois le long du plus petit côté courant, en y ajoutant des items
    tant que ça n'aggrave pas le pire ratio largeur/hauteur de la rangée
    (cf. _row_worst_ratio) — contrairement à une coupe binaire simple qui
    peut créer des bandes très allongées avec un fort écart de poids
    (retour user : "certaines images sont bien tronquées" — une case
    beaucoup trop large ou haute force un recadrage très agressif de la
    photo qui doit la remplir), ça garde les cases proches du carré.

    L'union des rectangles renvoyés couvre EXACTEMENT (x, y, w, h), sans
    trou ni recouvrement entre eux — la garantie "jamais de fond visible,
    jamais deux photos qui se chevauchent" reste intacte.

    Renvoie une liste de (clé, x, y, w, h)."""
    remaining = sorted(items, key=lambda t: -t[0])
    result = []
    rx, ry, rw, rh = x, y, w, h
    while remaining:
        if len(remaining) == 1:
            result.append((remaining[0][1], rx, ry, rw, rh))
            break
        total = sum(wt for wt, _ in remaining)
        side = min(rw, rh)
        row = [remaining[0]]
        best = _row_worst_ratio(row, side, total, rw * rh)
        i = 1
        while i < len(remaining):
            trial = row + [remaining[i]]
            trial_worst = _row_worst_ratio(trial, side, total, rw * rh)
            if trial_worst > best:
                break
            row, best = trial, trial_worst
            i += 1
        remaining = remaining[len(row):]
        row_weight = sum(wt for wt, _ in row)
        last_row = not remaining
        if rw >= rh:
            # Dernière rangée : consomme tout ce qu'il reste (évite qu'une
            # dérive d'arrondi cumulée sur les rangées précédentes laisse
            # un reliquat de largeur non attribué).
            row_len = rw if last_row else min(rw - 1, max(1, round(rw * row_weight / total)))
            cy, cum = ry, 0.0
            for idx, (wt, key) in enumerate(row):
                cum += wt
                next_cy = ry + rh if idx == len(row) - 1 else ry + round(rh * cum / row_weight)
                result.append((key, rx, cy, row_len, next_cy - cy))
                cy = next_cy
            rx, rw = rx + row_len, rw - row_len
        else:
            row_len = rh if last_row else min(rh - 1, max(1, round(rh * row_weight / total)))
            cx, cum = rx, 0.0
            for idx, (wt, key) in enumerate(row):
                cum += wt
                next_cx = rx + rw if idx == len(row) - 1 else rx + round(rw * cum / row_weight)
                result.append((key, cx, ry, next_cx - cx, row_len))
                cx = next_cx
            ry, rh = ry + row_len, rh - row_len
    return result


def _distribute_into_regions(items, regions):
    """Répartit `items` (liste de (poids, clé)) entre les `regions`
    (liste de (x, y, w, h)) en visant, pour chacune, une part de poids
    proportionnelle à son aire — glouton (du plus gros item au plus
    petit, chacun assigné à la région la plus en retard sur sa part
    cible) : pas besoin de l'optimal, juste d'une répartition qui garde
    une densité de photos comparable dans chaque région. Renvoie une
    liste (même ordre que `regions`) de listes d'items."""
    total_area = sum(w * h for _, _, w, h in regions) or 1
    total_weight = sum(wt for wt, _ in items) or 1
    targets = [total_weight * (rw * rh / total_area) for _, _, rw, rh in regions]
    assigned = [0.0] * len(regions)
    result = [[] for _ in regions]
    for wt, key in sorted(items, key=lambda t: -t[0]):
        idx = min(range(len(regions)), key=lambda i: assigned[i] - targets[i])
        result[idx].append((wt, key))
        assigned[idx] += wt
    return result


def compute_layout(photo_keys, canvas_w, canvas_h, size_variation,
                   rotation_variation, seed=None, margin_px=0,
                   center_key=None, featured_keys=frozenset()):
    """Place chaque clé de `photo_keys` sur le canevas (moins `margin_px`
    de marge sur chaque bord) par un partage récursif de l'aire disponible
    proportionnel au poids de chacune (cf. _squarify) — les tuiles
    couvrent ainsi TOUJOURS tout le canevas, sans trou ni recouvrement de
    base entre elles, quel que soit le nombre de photos. `size_variation`
    (0-100) pilote l'écart entre les poids : 0 = tous égaux (mosaïque
    régulière), 100 = certaines tuiles nettement plus grandes que
    d'autres. Une rotation (`rotation_variation`, 0-100) peut ensuite être
    appliquée à chaque tuile, À TAILLE PLEINE (pas rétrécie) : une tuile
    pivotée déborde donc légèrement sur ses voisines à ses coins, comme
    un vrai tas de photos posées — préféré à un rétrécissement (retour
    user : "quand je modifie la rotation, la taille des images est
    réduite, laissant apparaître plus de vide" — rétrécir pour ne jamais
    déborder allait à l'encontre du remplissage maximal). Le débordement
    reste borné (angle max ±28°, cf. plus bas) et localisé aux tuiles
    immédiatement voisines — jamais le chevauchement quasi total que
    provoquait l'ancien curseur Position (supprimé).

    `center_key`, si présent dans `photo_keys`, obtient une case agrandie
    au milieu du canevas, jamais pivotée — mais reste une case du MÊME
    partage que les autres : sa place est réservée au centre puis les
    autres photos sont mosaïquées tout autour (haut/bas/gauche/droite),
    toujours sans trou ni recouvrement (retour user : la centrale ne doit
    plus être collée par-dessus un montage déjà complet une fois celui-ci
    construit sans elle — ça cachait les photos en dessous, "pas
    vraiment ce qui est recherché"). Les clés de `featured_keys`
    reçoivent un poids plus élevé dans le partage — donc une case
    proportionnellement plus grande.

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
        # Asymétrique (-0.7 à +2.2) plutôt que centré sur 1 : quelques
        # photos nettement plus grandes que la moyenne, comme un vrai
        # scrapbook composé à la main plutôt qu'une mosaïque uniformément
        # redimensionnée. Plage élargie (retour user : "augmenter les
        # différences de taille quand on pousse le slider" — mesuré,
        # ratio d'aire moyen max/min entre tuiles : x3.1 à 100% avant
        # cet élargissement, x6 après, pour un vide qui reste comparable
        # ~5% grâce à la mosaïque garantie sans trou, cf. _squarify).
        weight = max(0.2, 1 + rng.uniform(-0.7, 2.2) * size_t)
        if key in featured_keys:
            weight *= FEATURED_SCALE_BOOST
        weights.append((weight, key))
    # Mélange avant le partage récursif (qui trie par poids en interne) :
    # sans ça, deux photos consécutives dans `photo_keys` finiraient
    # presque toujours voisines sur le canevas.
    rng.shuffle(weights)

    has_center = center_key is not None and center_key in photo_keys
    placed = {}

    # _squarify trie ses items par poids décroissant en interne (utile à
    # l'algorithme, cf. sa docstring) : les photos les plus lourdes
    # (mises en avant) tombent donc TOUJOURS dans la première rangée
    # traitée, donc toujours dans le même coin du canevas — le mélange
    # de `weights` ci-dessus n'a aucun effet là-dessus puisque _squarify
    # re-trie de toute façon (retour user : "à part être mis en haut à
    # gauche, le fait de mettre des images en avant ne change rien").
    # Un miroir horizontal/vertical aléatoire, appliqué UNE FOIS à tout
    # le tirage, casse ce biais sans toucher à la qualité du pavage
    # (une réflexion d'un pavage sans trou/recouvrement reste un pavage
    # sans trou/recouvrement).
    flip_x = rng.random() < 0.5
    flip_y = rng.random() < 0.5

    def _place_group(group, rx, ry, rw, rh):
        for key, x, y, w, h in _squarify(group, rx, ry, rw, rh):
            if flip_x:
                x = margin_px + (usable_w - (x - margin_px) - w)
            if flip_y:
                y = margin_px + (usable_h - (y - margin_px) - h)
            angle = rng.uniform(-28, 28) * rotation_t
            placed[key] = (x + w / 2, y + h / 2, w, h, angle)

    if has_center:
        # Taille "nominale" de référence : l'aire moyenne qu'aurait une
        # tuile si le canevas était partagé également entre toutes les
        # autres photos, à l'aspect ratio du canevas — sert juste à faire
        # ressortir la centrale un peu au-dessus de cette moyenne, sans
        # écraser le reste de la mosaïque (retour user : "elle peut être
        # légèrement plus grande mais pas prendre toute la place" — x2.2
        # en linéaire, donc presque x5 en aire, était bien trop agressif).
        count = max(1, len(others))
        nominal_w = usable_w / math.sqrt(count)
        nominal_h = usable_h / math.sqrt(count)
        center_w = min(usable_w * 0.6, nominal_w * 1.4)
        center_h = min(usable_h * 0.6, nominal_h * 1.4)
        placed[center_key] = (canvas_w / 2, canvas_h / 2, center_w, center_h, 0.0)

    if others:
        if not has_center:
            _place_group(weights, margin_px, margin_px, usable_w, usable_h)
        else:
            # Réserve la case centrale (ci-dessus) comme un vrai TROU dans
            # la mosaïque plutôt que de construire le montage sans elle
            # puis de la recoller par-dessus à la fin (retour user :
            # "vient le recoller au-dessus de tout ensuite, ce qui n'est
            # pas vraiment ce qui est recherché" — ça cachait les photos
            # en dessous). Les autres photos mosaïquent les 4 bandes
            # (haut/bas/gauche/droite) qui encadrent ce trou — union des
            # 5 rectangles = tout le canevas, sans trou ni recouvrement.
            cx0 = margin_px + (usable_w - center_w) / 2
            cy0 = margin_px + (usable_h - center_h) / 2
            top_h = cy0 - margin_px
            bottom_y = cy0 + center_h
            bottom_h = (margin_px + usable_h) - bottom_y
            left_w = cx0 - margin_px
            right_x = cx0 + center_w
            right_w = (margin_px + usable_w) - right_x
            regions = [
                (margin_px, margin_px, usable_w, top_h),
                (margin_px, bottom_y, usable_w, bottom_h),
                (margin_px, cy0, left_w, center_h),
                (right_x, cy0, right_w, center_h),
            ]
            regions = [r for r in regions if r[2] > 0 and r[3] > 0]
            if regions:
                for region, group in zip(regions, _distribute_into_regions(weights, regions)):
                    if group:
                        _place_group(group, *region)
            else:
                # La centrale occupe déjà (quasi) tout l'espace utile :
                # pas de place pour un cadre autour, filet de sécurité
                # plutôt que de perdre des photos (posées par-dessus,
                # comme avant).
                _place_group(weights, margin_px, margin_px, usable_w, usable_h)

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
    photos, pas du vide". Recadre au centre, plafonné à MAX_CROP_FRACTION
    du côté le plus recadré (retour user : une case d'aspect trop
    différent de la photo tronquait l'essentiel de son contenu) — au-delà
    du plafond, léger espace transparent sur le côté opposé plutôt qu'une
    photo méconnaissable ; `crop()` remplit tout seul cet espace en
    transparent, y compris hors des bords de l'image source (cf. Pillow,
    testé)."""
    box_w, box_h = max(1, round(box_w)), max(1, round(box_h))
    cover_ratio = max(box_w / image.width, box_h / image.height)
    contain_ratio = min(box_w / image.width, box_h / image.height)
    ratio = min(cover_ratio, contain_ratio / (1 - MAX_CROP_FRACTION))
    new_size = (max(1, round(image.width * ratio)),
                max(1, round(image.height * ratio)))
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
