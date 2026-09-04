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
import random
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


def _rect_overlap_area(a, b):
    ax, ay, aw, ah = a
    bx, by, bw, bh = b
    iw = max(0, min(ax + aw, bx + bw) - max(ax, bx))
    ih = max(0, min(ay + ah, by + bh) - max(ay, by))
    return iw * ih


def test_split_weighted_tiles_exactly_no_gap_no_overlap(mod):
    """Le coeur de la garantie anti-vide/anti-chevauchement (retour user :
    "certaines images clairement plus petites et d'autres clairement plus
    grandes... qu'elles se repositionnent pour avoir le moins de vide
    possible") : l'union des rectangles renvoyés par _split_weighted doit
    couvrir EXACTEMENT le rectangle d'origine, sans le moindre trou ni
    chevauchement entre eux — quel que soit le nombre d'items ou l'écart
    de poids entre eux. Beaucoup de tirages aléatoires (comptes et poids
    variés) pour ne pas dépendre d'un seul cas favorable."""
    rng = random.Random(0)
    for trial in range(30):
        n = rng.randint(1, 15)
        items = [(rng.uniform(0.35, 5.0), f"k{i}") for i in range(n)]
        w, h = rng.randint(200, 4000), rng.randint(200, 3000)
        rects = mod._split_weighted(items, 0, 0, w, h)
        assert len(rects) == n
        total_area = sum(rw * rh for _, _, _, rw, rh in rects)
        assert total_area == w * h, (
            f"tirage {trial} : aire totale {total_area} != {w * h}")
        boxes = [(rx, ry, rw, rh) for _, rx, ry, rw, rh in rects]
        for i in range(len(boxes)):
            for j in range(i + 1, len(boxes)):
                assert _rect_overlap_area(boxes[i], boxes[j]) == 0, (
                    f"tirage {trial} : chevauchement entre "
                    f"{boxes[i]} et {boxes[j]}")
    print("  _split_weighted (aucun trou, aucun chevauchement, aire exacte) : OK")


def test_layout_covers_every_photo_and_stays_ordered(mod):
    keys = _keys(7)
    layout = mod.compute_layout(keys, 4000, 3000, size_variation=0,
                                rotation_variation=0, seed=1)
    assert len(layout) == 7
    for cx, cy, box_w, box_h, angle in layout:
        assert box_w > 0 and box_h > 0
        assert angle == 0
        assert 0 <= cx <= 4000 and 0 <= cy <= 3000
    print("  compute_layout (mosaïque régulière, sans variation) : OK")


def test_size_and_rotation_are_independent(mod):
    """Les 2 curseurs doivent agir chacun sur son propre aspect, sans
    faire bouger l'autre — c'est tout l'intérêt de les avoir séparés."""
    keys = _keys(12)

    only_size = mod.compute_layout(keys, 4000, 3000, size_variation=100,
                                   rotation_variation=0, seed=7)
    assert all(angle == 0 for *_, angle in only_size)
    areas = [w * h for _, _, w, h, _ in only_size]
    assert max(areas) / min(areas) > 2, (
        "size_variation=100 doit produire des tailles nettement différentes")

    only_rotation = mod.compute_layout(keys, 4000, 3000, size_variation=0,
                                       rotation_variation=100, seed=7)
    assert any(angle != 0 for *_, angle in only_rotation)
    # size_variation=0 -> poids tous égaux -> cases toutes de même aire
    # AVANT rétrécissement anti-rotation ; seul ce rétrécissement (qui
    # dépend de l'angle ET de l'aspect de CHAQUE tuile, cf.
    # _rotation_safe_scale) peut encore les faire un peu varier — need
    # beaucoup moins que l'écart volontaire de size_variation=100.
    areas_r = [w * h for _, _, w, h, _ in only_rotation]
    assert max(areas_r) / min(areas_r) < max(areas) / min(areas)
    print("  size_variation / rotation_variation indépendants : OK")


def test_rotation_never_overflows_its_own_cell(mod):
    """Une tuile pivotée doit toujours tenir dans sa case d'origine — donc
    ne jamais déborder sur une voisine ni recréer le "chevauchement
    total" observé quand la position pouvait déplacer une tuile entière
    (retour user, réglage désormais supprimé) : ici la case elle-même ne
    bouge jamais, seule la tuile PIVOTÉE à l'intérieur rétrécit."""
    keys = _keys(10)
    layout = mod.compute_layout(keys, 4000, 3000, size_variation=70,
                                rotation_variation=100, seed=4)
    # Les cases (sans rotation) tuilent exactement le canevas — aucune
    # tuile pivotée (rétrécie pour tenir dedans) ne peut donc chevaucher
    # sa voisine : on le revérifie ici en comparant à la version sans
    # rotation, mêmes poids (même seed), qui donne les cases d'origine.
    baseline = mod.compute_layout(keys, 4000, 3000, size_variation=70,
                                  rotation_variation=0, seed=4)
    for (cx, cy, w, h, angle), (_, _, cell_w, cell_h, _) in zip(layout, baseline):
        assert w <= cell_w + 1e-6 and h <= cell_h + 1e-6, (
            "une tuile pivotée ne doit jamais dépasser sa case d'origine")
    print("  rotation toujours contenue dans sa case (pas de chevauchement) : OK")


def test_safe_margin_keeps_mosaic_off_the_edge(mod):
    keys = _keys(6)
    margin = 200
    layout = mod.compute_layout(keys, 4000, 3000, size_variation=0,
                                rotation_variation=0, seed=3, margin_px=margin)
    for cx, cy, box_w, box_h, _ in layout:
        assert cx - box_w / 2 >= margin - 1e-6
        assert cy - box_h / 2 >= margin - 1e-6
        assert cx + box_w / 2 <= 4000 - margin + 1e-6
        assert cy + box_h / 2 <= 3000 - margin + 1e-6
    print("  marge de sécurité (mosaïque tenue à distance du bord) : OK")


def test_center_photo_is_centered_and_upright(mod):
    keys = _keys(9)
    layout = mod.compute_layout(keys, 4000, 3000, size_variation=100,
                                rotation_variation=100, seed=5,
                                center_key="photo3.jpg")
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
                                rotation_variation=0, seed=11,
                                featured_keys=frozenset({"photo0.jpg"}))
    by_key = dict(zip(keys, layout))
    featured_area = by_key["photo0.jpg"][2] * by_key["photo0.jpg"][3]
    other_avg = sum(w * h for k, (_, _, w, h, _) in by_key.items()
                    if k != "photo0.jpg") / (len(keys) - 1)
    assert featured_area > other_avg
    print("  photo mise en avant (poids renforcé -> case plus grande) : OK")


def test_fit_and_rotate_covers_the_box_without_gaps(mod):
    """Retour user : même une mosaïque sans le moindre trou laissait de
    grandes bandes transparentes DANS chaque tuile dès que l'aspect ratio
    de la photo ne collait pas à sa case — la tuile doit désormais
    REMPLIR exactement box_w x box_h (recadrée si besoin), jamais plus
    petite."""
    from PIL import Image
    source = Image.new("RGBA", (800, 400), (255, 0, 0, 255))
    tile = mod.fit_and_rotate(source, box_w=200, box_h=200, angle_deg=0)
    assert tile.size == (200, 200), (
        "la tuile doit remplir exactement la boîte, sans letterbox")

    rotated = mod.fit_and_rotate(source, box_w=200, box_h=200, angle_deg=45)
    assert rotated.width > tile.width and rotated.height > tile.height
    print("  fit_and_rotate (cover + recadrage centré, sans bande vide) : OK")


def test_render_montage_respects_margin(mod):
    """Les tuiles de la mosaïque (hors centrale) ne peuvent, par
    construction de compute_layout, jamais dépasser leur case — donc
    jamais déborder de la marge de sécurité non plus. Vérifié ici sur le
    rendu complet (pas seulement le layout), avec beaucoup de photos et
    fort écart de taille/rotation pour maximiser le risque."""
    from PIL import Image
    keys = _keys(10)
    sources = {k: Image.new("RGBA", (500, 500), (255, 255, 255, 255))
              for k in keys}
    canvas_w, canvas_h, margin = 1600, 1200, 150
    canvas, layers = mod.render_montage(
        keys, canvas_w, canvas_h, size_variation=100, rotation_variation=100,
        margin_px=margin, seed=13,
        load_source=lambda k: sources[k], log=lambda msg: None)
    assert len(layers) == len(keys)
    for _, tile, left, top in layers:
        tw, th = tile.size
        assert left >= margin - 1
        assert top >= margin - 1
        assert left + tw <= canvas_w - margin + 1
        assert top + th <= canvas_h - margin + 1
    print("  render_montage (mosaïque toujours dans la marge) : OK")


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
        margin_px=50, seed=2,
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
    test_split_weighted_tiles_exactly_no_gap_no_overlap(montage)
    test_layout_covers_every_photo_and_stays_ordered(montage)
    test_size_and_rotation_are_independent(montage)
    test_rotation_never_overflows_its_own_cell(montage)
    test_safe_margin_keeps_mosaic_off_the_edge(montage)
    test_center_photo_is_centered_and_upright(montage)
    test_featured_photo_is_bigger_on_average(montage)
    test_fit_and_rotate_covers_the_box_without_gaps(montage)
    test_render_montage_respects_margin(montage)
    test_render_montage_composites_and_skips_missing(montage)
    print("Tout est passé.")
