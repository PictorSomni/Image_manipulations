# -*- coding: utf-8 -*-
"""
test_montage_collage.py — auto-contrôle de compute_layout / fit_and_rotate /
render_montage ("Montage collage.py", nom de fichier avec espace donc non
importable via `import` classique — chargé dynamiquement, comme
test_ui_changes.py le fait pour Retouche par lot.pyw).

Lancer :  python3 "Data/test_montage_collage.py"
"""

import importlib.machinery
import importlib.util
import math
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))


def _load_montage():
    path = Path(__file__).resolve().parent / "Montage collage.py"
    spec = importlib.util.spec_from_loader(
        "montage_collage",
        importlib.machinery.SourceFileLoader("montage_collage", str(path)))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _keys(n):
    return [f"photo{i}.jpg" for i in range(n)]


def test_layout_covers_every_photo_and_stays_ordered(mod):
    keys = _keys(7)
    layout = mod.compute_layout(keys, 4000, 3000, size_variation=0,
                                rotation_variation=0, position_variation=0,
                                max_overlap=15, seed=1)
    assert len(layout) == 7
    for cx, cy, box_w, box_h, angle in layout:
        assert box_w > 0 and box_h > 0
        assert angle == 0
        assert 0 <= cx <= 4000 and 0 <= cy <= 3000
    print("  compute_layout (grille sage, sans variation) : OK")


def test_sparse_last_row_stretches_to_fill_width(mod):
    """Retour user : avec peu de photos, count ne remplit pas forcément
    cols x rows pile (ex. 3 photos -> grille 2x2) — une largeur de cellule
    fixe laissait une cellule entière VIDE (fond transparent visible,
    "beaucoup de blanc/vide"). La ligne incomplète doit maintenant
    s'étaler sur toute la largeur utile plutôt que de laisser un trou."""
    keys = _keys(3)
    layout = mod.compute_layout(keys, 4000, 3000, size_variation=0,
                                rotation_variation=0, position_variation=0,
                                max_overlap=100, seed=1)
    widths = sorted(round(w) for _, _, w, h, _ in layout)
    # 2 photos se partagent la première ligne (2000 chacune), la 3e est
    # seule sur sa ligne et prend donc toute la largeur utile (4000).
    assert widths == [2000, 2000, 4000], (
        f"la ligne incomplète doit combler tout l'espace, obtenu {widths}")
    print("  ligne incomplète étalée sur toute la largeur (pas de trou) : OK")


def test_size_and_rotation_are_independent(mod):
    """Les curseurs doivent agir chacun sur son propre aspect, sans faire
    bouger les autres — c'est tout l'intérêt de les avoir séparés (retour
    user : un seul curseur "chaos" ne faisait pas assez varier les tailles
    à mi-course)."""
    keys = _keys(12)

    only_size = mod.compute_layout(keys, 4000, 3000, size_variation=100,
                                   rotation_variation=0,
                                   position_variation=0, max_overlap=100,
                                   seed=7)
    assert all(angle == 0 for *_, angle in only_size)
    widths = {round(w) for _, _, w, h, _ in only_size}
    assert len(widths) > 1, "size_variation=100 doit produire des tailles différentes"

    only_rotation = mod.compute_layout(keys, 4000, 3000, size_variation=0,
                                       rotation_variation=100,
                                       position_variation=0, max_overlap=100,
                                       seed=7)
    assert any(angle != 0 for *_, angle in only_rotation)
    base_w = only_rotation[0][2]
    assert all(abs(w - base_w) < 1e-6 for _, _, w, h, _ in only_rotation), (
        "size_variation=0 doit garder des tailles identiques quelle que "
        "soit la rotation")
    print("  size_variation / rotation_variation indépendants : OK")


def test_position_variation_is_independent(mod):
    """3e curseur (retour user) : grille bien rangée (0) à scatter "lâché"
    (100), sans faire bouger taille ni rotation."""
    keys = _keys(12)

    grid = mod.compute_layout(keys, 4000, 3000, size_variation=0,
                              rotation_variation=0, position_variation=0,
                              max_overlap=100, seed=9)
    scattered = mod.compute_layout(keys, 4000, 3000, size_variation=0,
                                   rotation_variation=0,
                                   position_variation=100, max_overlap=100,
                                   seed=9)
    # Rotation toujours nulle (rotation_variation=0) des deux côtés, et
    # même angle (0) qu'importe la position...
    assert all(a == 0 for *_, a in grid) and all(a == 0 for *_, a in scattered)
    # ...mais les boîtes grossissent TOUTES dans la même proportion à fort
    # position_variation (retour user : "il y a des trous" — le jitter de
    # position, sans grossir les boîtes en face, laissait du fond
    # transparent visible ; le grossissement compense, cf. `overlap` dans
    # compute_layout). size_variation=0 -> même overlap partout.
    ratios = {round(w1 / w0, 6) for (_, _, w0, *_), (_, _, w1, *_)
             in zip(grid, scattered)}
    assert len(ratios) == 1 and next(iter(ratios)) > 1, (
        "position_variation=100 doit agrandir toutes les boîtes pareil")
    # ...et des centres différents : le scatter doit s'écarter de la
    # position de grille pile centrée.
    moved = sum(1 for (cx0, cy0, *_), (cx1, cy1, *_) in zip(grid, scattered)
               if abs(cx0 - cx1) > 1 or abs(cy0 - cy1) > 1)
    assert moved > 0, "position_variation=100 doit décaler des centres"
    print("  position_variation indépendant (grille <-> scatter, sans trou) : OK")


def _bbox(cx, cy, w, h, angle_deg):
    """Boîte englobante axis-aligned (même formule que _rotated_half_diag),
    pour mesurer le recouvrement RÉEL entre deux tuiles — le critère du
    cercle circonscrit utilisé pour piloter compute_layout est volontai-
    rement conservateur (2 rectangles adjacents sans le moindre
    recouvrement violent déjà ce critère), donc inadapté à un test."""
    rad = math.radians(angle_deg)
    ext_w = abs(w * math.cos(rad)) + abs(h * math.sin(rad))
    ext_h = abs(w * math.sin(rad)) + abs(h * math.cos(rad))
    return (cx - ext_w / 2, cy - ext_h / 2, cx + ext_w / 2, cy + ext_h / 2)


def _overlap_fraction(box_a, box_b):
    ax0, ay0, ax1, ay1 = box_a
    bx0, by0, bx1, by1 = box_b
    iw = max(0, min(ax1, bx1) - max(ax0, bx0))
    ih = max(0, min(ay1, by1) - max(ay0, by0))
    inter = iw * ih
    area_a, area_b = (ax1 - ax0) * (ay1 - ay0), (bx1 - bx0) * (by1 - by0)
    smaller = min(area_a, area_b)
    return inter / smaller if smaller > 0 else 0


def test_max_overlap_reduces_heavy_overlaps(mod):
    """Retour user (seuil généralisé, pas juste "pas d'avalement total") :
    à faible max_overlap, il doit y avoir nettement moins de paires
    lourdement recouvertes (>50% de la plus petite tuile cachée) qu'à
    max_overlap=100 (libre) — c'est la garantie concrète contre les
    visages cachés, mesurée sur le recouvrement réel des boîtes (pas le
    cercle circonscrit, trop conservateur pour un seuil exact). Plusieurs
    seeds + réglages costauds (beaucoup de photos, tailles variées) pour
    ne pas dépendre d'un seul tirage chanceux."""
    keys = _keys(12)

    def heavy_overlap_count(max_overlap, seed):
        layout = mod.compute_layout(keys, 4000, 3000, size_variation=50,
                                    rotation_variation=50,
                                    position_variation=50,
                                    max_overlap=max_overlap, seed=seed)
        boxes = [_bbox(*tile) for tile in layout]
        return sum(1 for i in range(len(boxes))
                  for j in range(i + 1, len(boxes))
                  if _overlap_fraction(boxes[i], boxes[j]) > 0.5)

    tight_total = sum(heavy_overlap_count(15, seed) for seed in range(10))
    free_total = sum(heavy_overlap_count(100, seed) for seed in range(10))
    assert tight_total < free_total, (
        "max_overlap=15 doit produire nettement moins de recouvrements "
        f"lourds que max_overlap=100 (obtenu : {tight_total} vs {free_total})")
    print(f"  max_overlap réduit les recouvrements lourds "
         f"({tight_total} à 15 vs {free_total} à 100) : OK")


def test_safe_margin_keeps_grid_off_the_edge(mod):
    keys = _keys(6)
    margin = 200
    layout = mod.compute_layout(keys, 4000, 3000, size_variation=0,
                                rotation_variation=0, position_variation=0,
                                max_overlap=100, seed=3, margin_px=margin)
    for cx, cy, box_w, box_h, _ in layout:
        assert cx - box_w / 2 >= margin - 1e-6
        assert cy - box_h / 2 >= margin - 1e-6
        assert cx + box_w / 2 <= 4000 - margin + 1e-6
        assert cy + box_h / 2 <= 3000 - margin + 1e-6
    print("  marge de sécurité (grille tenue à distance du bord) : OK")


def test_center_photo_is_centered_and_upright(mod):
    keys = _keys(9)
    layout = mod.compute_layout(keys, 4000, 3000, size_variation=100,
                                rotation_variation=100,
                                position_variation=100, max_overlap=100,
                                seed=5, center_key="photo3.jpg")
    by_key = dict(zip(keys, layout))
    cx, cy, box_w, box_h, angle = by_key["photo3.jpg"]
    assert cx == 2000 and cy == 1500
    assert angle == 0, "la photo centrale reste toujours droite"
    others_w = [w for k, (_, _, w, _, _) in by_key.items() if k != "photo3.jpg"]
    assert box_w > sum(others_w) / len(others_w), (
        "la photo centrale doit ressortir plus grande que la moyenne")
    print("  photo centrale (centrée, agrandie, jamais pivotée) : OK")


def test_featured_photo_is_bigger_on_average(mod):
    keys = _keys(20)
    layout = mod.compute_layout(keys, 4000, 3000, size_variation=50,
                                rotation_variation=0, position_variation=50,
                                max_overlap=100, seed=11,
                                featured_keys=frozenset({"photo0.jpg"}))
    by_key = dict(zip(keys, layout))
    featured_w = by_key["photo0.jpg"][2]
    other_avg = sum(w for k, (_, _, w, _, _) in by_key.items()
                    if k != "photo0.jpg") / (len(keys) - 1)
    assert featured_w > other_avg
    print("  photo mise en avant (boost de taille appliqué) : OK")


def test_fit_and_rotate_covers_the_box_without_gaps(mod):
    """Retour user : même une grille sans cellule vide laissait de grandes
    bandes transparentes DANS chaque tuile dès que l'aspect ratio de la
    photo ne collait pas à sa case — la tuile doit désormais REMPLIR
    exactement box_w x box_h (recadrée si besoin), jamais plus petite."""
    from PIL import Image
    source = Image.new("RGBA", (800, 400), (255, 0, 0, 255))
    tile = mod.fit_and_rotate(source, box_w=200, box_h=200, angle_deg=0)
    assert tile.size == (200, 200), (
        "la tuile doit remplir exactement la boîte, sans letterbox")

    rotated = mod.fit_and_rotate(source, box_w=200, box_h=200, angle_deg=45)
    assert rotated.width > tile.width and rotated.height > tile.height
    print("  fit_and_rotate (cover + recadrage centré, sans bande vide) : OK")


def test_render_montage_respects_margin_even_when_oversized(mod):
    """compute_layout espace juste la grille de départ ; c'est
    render_montage qui doit garantir la marge pour de vrai (retour user :
    une grosse variation de taille faisait quand même toucher le bord réel
    malgré la grille inset). Grandes sources carrées + fort écart de
    taille pour maximiser le risque de débordement."""
    from PIL import Image
    keys = _keys(6)
    sources = {k: Image.new("RGBA", (500, 500), (255, 255, 255, 255))
              for k in keys}
    canvas_w, canvas_h, margin = 1600, 1200, 150
    canvas, layers = mod.render_montage(
        keys, canvas_w, canvas_h, size_variation=100, rotation_variation=0,
        position_variation=100, max_overlap=100, margin_px=margin, seed=13,
        load_source=lambda k: sources[k], log=lambda msg: None)
    assert len(layers) == len(keys)
    for _, tile, left, top in layers:
        tw, th = tile.size
        assert left >= margin - 1
        assert top >= margin - 1
        # Une tuile plus grande que la zone utile est ancrée à la marge
        # (pas forcément tenue de l'autre côté) — seule garantie sûre.
        if tw <= canvas_w - 2 * margin:
            assert left + tw <= canvas_w - margin + 1
        if th <= canvas_h - 2 * margin:
            assert top + th <= canvas_h - margin + 1
    print("  render_montage (marge tenue même pour une grosse tuile) : OK")


def test_render_montage_composites_and_skips_missing(mod):
    from PIL import Image
    keys = _keys(4)
    sources = {
        "photo0.jpg": Image.new("RGBA", (400, 300), (255, 0, 0, 255)),
        "photo1.jpg": Image.new("RGBA", (300, 400), (0, 255, 0, 255)),
        "photo2.jpg": None,  # source manquante -> doit être ignorée sans planter
        "photo3.jpg": Image.new("RGBA", (300, 300), (0, 0, 255, 255)),
    }
    canvas, layers = mod.render_montage(
        keys, 1000, 800, size_variation=30, rotation_variation=30,
        position_variation=30, max_overlap=15, margin_px=50, seed=2,
        load_source=lambda k: sources[k], log=lambda msg: None)
    assert canvas.size == (1000, 800)
    assert canvas.mode == "RGBA"
    # 3 sources valides posées ; la 4e (None) n'a pas dû produire de calque
    assert len(layers) == 3
    assert {name for name, *_ in layers} == {"photo0", "photo1", "photo3"}
    print("  render_montage (composite + source manquante ignorée) : OK")


if __name__ == "__main__":
    print("Vérifications :")
    montage = _load_montage()
    test_layout_covers_every_photo_and_stays_ordered(montage)
    test_sparse_last_row_stretches_to_fill_width(montage)
    test_size_and_rotation_are_independent(montage)
    test_position_variation_is_independent(montage)
    test_max_overlap_reduces_heavy_overlaps(montage)
    test_safe_margin_keeps_grid_off_the_edge(montage)
    test_center_photo_is_centered_and_upright(montage)
    test_featured_photo_is_bigger_on_average(montage)
    test_fit_and_rotate_covers_the_box_without_gaps(montage)
    test_render_montage_respects_margin_even_when_oversized(montage)
    test_render_montage_composites_and_skips_missing(montage)
    print("Tout est passé.")
