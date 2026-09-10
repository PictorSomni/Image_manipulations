"""Vérifie que la géométrie recalculée après un quart de tour (boutons
90° de Recadrage manuel.pyw) fait bien COUVRIR le canevas à zoom 1.00×
— sinon l'image reste baladable à 1.00× (retour user)."""
import math
import os
import sys

sys.path.insert(0, os.path.dirname(__file__))
import image_ops


def _cover_geometry(canvas_w, canvas_h, orig_w, orig_h, coarse_deg):
    """Réplique PhotoCropper._recompute_cover_for_coarse (mode cover)."""
    quarter = round(coarse_deg / 90.0) % 2 == 1
    seen_w = canvas_h if quarter else canvas_w
    seen_h = canvas_w if quarter else canvas_h
    base_scale = max(seen_w / orig_w, seen_h / orig_h)
    display_w = max(int(round(orig_w * base_scale)), math.ceil(seen_w) + 4)
    display_h = max(int(round(orig_h * base_scale)), math.ceil(seen_h) + 4)
    return base_scale, display_w, display_h


def _covers(canvas_w, canvas_h, orig_w, orig_h, coarse_deg):
    base_scale, dw, dh = _cover_geometry(
        canvas_w, canvas_h, orig_w, orig_h, coarse_deg)
    view = image_ops.CropView(
        canvas_w=canvas_w, canvas_h=canvas_h, base_scale=base_scale,
        offset_x=0.0, offset_y=0.0, scale=1.0, rotation=coarse_deg,
        original_width=orig_w, original_height=orig_h,
        display_w=dw, display_h=dh)
    bw, bh = image_ops.get_transformed_bounds(view)
    return bw >= canvas_w - 1 and bh >= canvas_h - 1


CASES = [
    # (canvas_w, canvas_h, orig_w, orig_h)
    (1000, 1500, 6000, 4000),   # canevas portrait, photo paysage
    (1500, 1000, 4000, 6000),   # canevas paysage, photo portrait
    (1000, 1500, 4000, 6000),   # mêmes orientations
    (1181, 1772, 5472, 3648),   # 10x15 @ 300ppp, photo 3:2
    (1000, 1000, 6000, 4000),   # canevas carré
]


def main():
    print("Vérifications :")
    ok = True
    for cw, ch, ow, oh in CASES:
        for coarse in (0.0, 90.0, -90.0, 180.0):
            covered = _covers(cw, ch, ow, oh, coarse)
            tag = f"canevas {cw}x{ch}, photo {ow}x{oh}, coarse {coarse:+.0f}°"
            print(f"  {tag} : {'OK' if covered else 'ÉCHEC'}")
            ok = ok and covered
    if not ok:
        raise SystemExit("Au moins un cas ne couvre pas le canevas.")
    print("Tout est passé.")


if __name__ == "__main__":
    main()
