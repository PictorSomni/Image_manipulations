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
                                rotation_variation=0, seed=1)
    assert len(layout) == 7
    for cx, cy, box_w, box_h, angle in layout:
        assert box_w > 0 and box_h > 0
        assert angle == 0
        assert 0 <= cx <= 4000 and 0 <= cy <= 3000
    print("  compute_layout (grille sage, sans variation) : OK")


def test_size_and_rotation_are_independent(mod):
    """Les deux curseurs doivent agir chacun sur son propre aspect, sans
    faire bouger l'autre — c'est tout l'intérêt de les avoir séparés
    (retour user : un seul curseur "chaos" ne faisait pas assez varier
    les tailles à mi-course)."""
    keys = _keys(12)

    only_size = mod.compute_layout(keys, 4000, 3000, size_variation=100,
                                   rotation_variation=0, seed=7)
    assert all(angle == 0 for *_, angle in only_size)
    widths = {round(w) for _, _, w, h, _ in only_size}
    assert len(widths) > 1, "size_variation=100 doit produire des tailles différentes"

    only_rotation = mod.compute_layout(keys, 4000, 3000, size_variation=0,
                                       rotation_variation=100, seed=7)
    assert any(angle != 0 for *_, angle in only_rotation)
    base_w = only_rotation[0][2]
    assert all(abs(w - base_w) < 1e-6 for _, _, w, h, _ in only_rotation), (
        "size_variation=0 doit garder des tailles identiques quelle que "
        "soit la rotation")
    print("  size_variation / rotation_variation indépendants : OK")


def test_safe_margin_keeps_grid_off_the_edge(mod):
    keys = _keys(6)
    margin = 200
    layout = mod.compute_layout(keys, 4000, 3000, size_variation=0,
                                rotation_variation=0, seed=3, margin_px=margin)
    for cx, cy, box_w, box_h, _ in layout:
        assert cx - box_w / 2 >= margin - 1e-6
        assert cy - box_h / 2 >= margin - 1e-6
        assert cx + box_w / 2 <= 4000 - margin + 1e-6
        assert cy + box_h / 2 <= 3000 - margin + 1e-6
    print("  marge de sécurité (grille tenue à distance du bord) : OK")


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
    featured_w = by_key["photo0.jpg"][2]
    other_avg = sum(w for k, (_, _, w, _, _) in by_key.items()
                    if k != "photo0.jpg") / (len(keys) - 1)
    assert featured_w > other_avg
    print("  photo mise en avant (boost de taille appliqué) : OK")


def test_fit_and_rotate_contains_without_cropping(mod):
    from PIL import Image
    source = Image.new("RGBA", (800, 400), (255, 0, 0, 255))
    tile = mod.fit_and_rotate(source, box_w=200, box_h=200, angle_deg=0)
    assert tile.width <= 200 and tile.height <= 200
    assert round(tile.width / tile.height) == round(800 / 400)

    rotated = mod.fit_and_rotate(source, box_w=200, box_h=200, angle_deg=45)
    assert rotated.width > tile.width and rotated.height > tile.height
    print("  fit_and_rotate (contain + expand) : OK")


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
        margin_px=margin, seed=13, load_source=lambda k: sources[k],
        log=lambda msg: None)
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
        margin_px=50, seed=2, load_source=lambda k: sources[k],
        log=lambda msg: None)
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
    test_size_and_rotation_are_independent(montage)
    test_safe_margin_keeps_grid_off_the_edge(montage)
    test_center_photo_is_centered_and_upright(montage)
    test_featured_photo_is_bigger_on_average(montage)
    test_fit_and_rotate_contains_without_cropping(montage)
    test_render_montage_respects_margin_even_when_oversized(montage)
    test_render_montage_composites_and_skips_missing(montage)
    print("Tout est passé.")
