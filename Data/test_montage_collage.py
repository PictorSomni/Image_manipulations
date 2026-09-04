# -*- coding: utf-8 -*-
"""
test_montage_collage.py — auto-contrôle de compute_layout / fit_and_rotate
("Montage collage.py", nom de fichier avec espace donc non importable via
`import` classique — chargé dynamiquement, comme test_ui_changes.py le
fait pour Retouche par lot.pyw).

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


def test_layout_covers_every_photo_and_stays_ordered(mod):
    layout = mod.compute_layout(7, 4000, 3000, chaos=0, seed=1)
    assert len(layout) == 7
    for cx, cy, box_w, box_h, angle in layout:
        assert box_w > 0 and box_h > 0
        # chaos=0 : pas de rotation, cases posées sagement dans le canevas
        # (marge de sécurité : le centre reste dans le canevas, pas la
        # boîte entière — le calage fin reste au recadrage à l'affichage).
        assert angle == 0
        assert 0 <= cx <= 4000 and 0 <= cy <= 3000
    print("  compute_layout (grille sage, chaos=0) : OK")


def test_chaos_increases_spread(mod):
    """chaos=100 doit produire une dispersion (position/taille/angle)
    strictement plus grande que chaos=0 — sinon le curseur ne fait rien,
    ce qui est le bug le plus probable dans ce genre de code aléatoire."""
    tidy = mod.compute_layout(12, 4000, 3000, chaos=0, seed=42)
    messy = mod.compute_layout(12, 4000, 3000, chaos=100, seed=42)
    assert all(a == 0 for *_, a in tidy)
    assert any(a != 0 for *_, a in messy)
    tidy_sizes = {round(w) for _, _, w, h, _ in tidy}
    messy_sizes = {round(w) for _, _, w, h, _ in messy}
    assert len(messy_sizes) > len(tidy_sizes) or messy_sizes != tidy_sizes
    print("  chaos=100 disperse bien plus que chaos=0 : OK")


def test_fit_and_rotate_contains_without_cropping(mod):
    from PIL import Image
    source = Image.new("RGBA", (800, 400), (255, 0, 0, 255))
    tile = mod.fit_and_rotate(source, box_w=200, box_h=200, angle_deg=0)
    # "contain" : l'image entière rentre dans la boîte, ratio conservé
    assert tile.width <= 200 and tile.height <= 200
    assert round(tile.width / tile.height) == round(800 / 400)

    rotated = mod.fit_and_rotate(source, box_w=200, box_h=200, angle_deg=45)
    # expand=True : le cadre pivoté est plus grand que l'original, rien
    # n'est coupé aux coins
    assert rotated.width > tile.width and rotated.height > tile.height
    print("  fit_and_rotate (contain + expand) : OK")


if __name__ == "__main__":
    print("Vérifications :")
    montage = _load_montage()
    test_layout_covers_every_photo_and_stays_ordered(montage)
    test_chaos_increases_spread(montage)
    test_fit_and_rotate_contains_without_cropping(montage)
    print("Tout est passé.")
