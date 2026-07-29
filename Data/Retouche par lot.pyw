# -*- coding: utf-8 -*-
"""
Retouche par lot.pyw — aperçu live sur une image représentative, puis
application de la même pipeline (débruitage, réglages couleur, virage,
netteté, grain pellicule, copyright) en pleine résolution sur tout le
dossier/sélection.

Chaque étape est indépendamment activable et partage sa logique, via
`image_ops.py`, avec les anciens scripts autonomes du même nom
(Débruiter.py, Virage.py, Copyright.py, Améliorer netteté.py, Grain
pellicule.py) — tous retirés, remplacés par cet outil unique (aperçu et
export identiques à la résolution près).

Variables d'environnement :
  FOLDER_PATH     — dossier source (défaut : répertoire du script).
  SELECTED_FILES  — liste de noms séparés par ``|`` (filtre optionnel).

Dépendances : Flet, Pillow (PIL), NumPy, OpenCV (cv2)
"""

__version__ = "1.0.0"

#############################################################
#                          IMPORTS                          #
#############################################################
import asyncio
import base64
import copy
import io
import json
import os
import re
import sys
import threading
import time
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import CONSTANTS
import image_ops
import flet as ft
import numpy as np
from PIL import Image, ImageDraw

DARK = CONSTANTS.COLOR_DARK
BG = CONSTANTS.COLOR_BACKGROUND
GREY = CONSTANTS.COLOR_GREY
BLUE = CONSTANTS.COLOR_BLUE
VIOLET = CONSTANTS.COLOR_VIOLET
GREEN = CONSTANTS.COLOR_GREEN
YELLOW = CONSTANTS.COLOR_YELLOW
ORANGE = CONSTANTS.COLOR_ORANGE
RED = CONSTANTS.COLOR_RED
WHITE = CONSTANTS.COLOR_WHITE

# Image 1x1 transparente — placeholder avant chargement du premier aperçu.
_BLANK_SRC = "data:image/gif;base64,R0lGODlhAQABAAD/ACwAAAAAAQABAAACADs="

EXTENSION = (".JPG", ".JPEG", ".PNG", ".BMP", ".TIFF", ".TIF", ".WEBP")


#############################################################
#                    RÉGLAGES PAR DÉFAUT                    #
#############################################################
def _default_virage():
    # Pas de remontée des ombres ici : gérée par la section "Réglages
    # couleur" (slider Ombres) — les deux se chevauchaient (retour user).
    # hue/sat/light/mode viennent de RETOUCHE_LOT_VIRAGE_* (dernier état
    # enregistré via "Enregistrer comme réglages par défaut"), pas du
    # préréglage : l'utilisateur peut avoir dévié du préréglage de départ.
    C = CONSTANTS
    return {
        "enabled": C.RETOUCHE_LOT_VIRAGE_ENABLED,
        "preset": C.VIRAGE_DEFAULT_PRESET,
        "mode": C.RETOUCHE_LOT_VIRAGE_MODE,
        "hue": C.RETOUCHE_LOT_VIRAGE_HUE,
        "sat": C.RETOUCHE_LOT_VIRAGE_SAT,
        "light": C.RETOUCHE_LOT_VIRAGE_LIGHT,
    }


def _update_in_place(dst, src):
    """Recopie récursivement `src` dans `dst` en conservant l'identité des
    dicts imbriqués (jamais `dst[k] = src[k]` sur un sous-dict) — les
    contrôles Flet capturent ces sous-dicts par référence à la
    construction de l'UI ; les remplacer désynchroniserait affichage et
    état. Utilisé par le bouton Réinitialiser."""
    for key, value in src.items():
        if isinstance(value, dict) and isinstance(dst.get(key), dict):
            _update_in_place(dst[key], value)
        else:
            dst[key] = value


def default_params():
    """Nouvelle copie des réglages par défaut (jamais partagée entre deux
    exécutions — chaque appelant doit avoir son propre dict mutable)."""
    C = CONSTANTS
    return {
        "denoise": {
            "enabled": C.RETOUCHE_LOT_DENOISE_ENABLED,
            "h": C.DENOISE_H, "h_color": C.DENOISE_H_COLOR,
            "template_window": C.DENOISE_TEMPLATE_WINDOW,
            "search_window": C.DENOISE_SEARCH_WINDOW,
        },
        "couleur": {
            "enabled": C.RETOUCHE_LOT_COULEUR_ENABLED,
            "exposure": C.RETOUCHE_LOT_COULEUR_EXPOSURE,
            "contrast": C.RETOUCHE_LOT_COULEUR_CONTRAST,
            "saturation": C.RETOUCHE_LOT_COULEUR_SATURATION,
            "hue": C.RETOUCHE_LOT_COULEUR_HUE,
            "white_balance": C.RETOUCHE_LOT_COULEUR_WHITE_BALANCE,
            "shadows": C.RETOUCHE_LOT_COULEUR_SHADOWS,
            "highlights": C.RETOUCHE_LOT_COULEUR_HIGHLIGHTS,
            "whites": C.RETOUCHE_LOT_COULEUR_WHITES,
            "blacks": C.RETOUCHE_LOT_COULEUR_BLACKS,
        },
        "virage": _default_virage(),
        "nettete": {
            "enabled": C.RETOUCHE_LOT_NETTETE_ENABLED,
            "radius1": C.RETOUCHE_LOT_NETTETE_RADIUS1,
            "percent1": C.RETOUCHE_LOT_NETTETE_PERCENT1,
            "radius2": C.RETOUCHE_LOT_NETTETE_RADIUS2,
            "percent2": C.RETOUCHE_LOT_NETTETE_PERCENT2,
        },
        "grain": {
            "enabled": C.RETOUCHE_LOT_GRAIN_ENABLED,
            "ca": {"enabled": C.CA_ENABLED, "strength": C.CA_STRENGTH,
                   "axial_ratio": C.CA_AXIAL_RATIO},
            "desat": {"enabled": C.DESAT_ENABLED,
                      "shadow_threshold": C.DESAT_SHADOW_THRESHOLD,
                      "shadow_intensity": C.DESAT_SHADOW_INTENSITY,
                      "highlight_threshold": C.DESAT_HIGHLIGHT_THRESHOLD,
                      "highlight_intensity": C.DESAT_HIGHLIGHT_INTENSITY,
                      "midtone_boost": C.DESAT_MIDTONE_BOOST},
            "halation": {"enabled": C.HALATION_ENABLED,
                        "threshold": C.HALATION_THRESHOLD,
                        "radius": C.HALATION_RADIUS,
                        "intensity": C.HALATION_INTENSITY,
                        "red_shift": C.HALATION_RED_SHIFT},
            "bloom": {"enabled": C.BLOOM_ENABLED, "radius": C.BLOOM_RADIUS,
                     "intensity": C.BLOOM_INTENSITY},
            "grain1": {"enabled": C.RETOUCHE_LOT_GRAIN1_ENABLED,
                      "amount": C.GRAIN_AMOUNT,
                      "size": C.GRAIN_SIZE, "color_ratio": C.GRAIN_COLOR_RATIO,
                      "shadow_boost": C.GRAIN_SHADOW_BOOST,
                      "floor": C.GRAIN_FLOOR,
                      "chroma_shift": C.GRAIN_CHROMA_SHIFT},
            "grain2": {"enabled": C.RETOUCHE_LOT_GRAIN2_ENABLED,
                      "amount": C.GRAIN2_AMOUNT,
                      "size": C.GRAIN2_SIZE,
                      "color_ratio": C.GRAIN2_COLOR_RATIO,
                      "shadow_boost": C.GRAIN2_SHADOW_BOOST,
                      "floor": C.GRAIN2_FLOOR,
                      "chroma_shift": C.GRAIN2_CHROMA_SHIFT},
        },
        "copyright": {
            "enabled": C.RETOUCHE_LOT_COPYRIGHT_ENABLED,
            "mode": C.RETOUCHE_LOT_COPYRIGHT_MODE,
            "custom_text": C.RETOUCHE_LOT_COPYRIGHT_CUSTOM_TEXT,
        },
    }


def _py_literal(value):
    """Représentation Python valide à écrire telle quelle dans CONSTANTS.py."""
    if isinstance(value, bool):
        return "True" if value else "False"
    if isinstance(value, float):
        return repr(round(value, 6))
    if isinstance(value, int):
        return repr(value)
    return repr(str(value))


def _constants_mapping(params):
    """Nom de constante CONSTANTS.py -> valeur actuelle du panneau. Les
    champs sans équivalent partagé ailleurs vivent sous RETOUCHE_LOT_* ;
    les autres (débruitage, virage, grain — section 12 de CONSTANTS.py)
    n'ont plus d'autre consommateur : les scripts autonomes correspondants
    ont tous été retirés, remplacés par cet outil unique."""
    d, c, v, n, g = (params["denoise"], params["couleur"], params["virage"],
                     params["nettete"], params["grain"])
    ca, ds, ha, bl = g["ca"], g["desat"], g["halation"], g["bloom"]
    g1, g2, cp = g["grain1"], g["grain2"], params["copyright"]
    return {
        "RETOUCHE_LOT_DENOISE_ENABLED": d["enabled"],
        "DENOISE_H": d["h"], "DENOISE_H_COLOR": d["h_color"],

        "RETOUCHE_LOT_COULEUR_ENABLED": c["enabled"],
        "RETOUCHE_LOT_COULEUR_EXPOSURE": c["exposure"],
        "RETOUCHE_LOT_COULEUR_CONTRAST": c["contrast"],
        "RETOUCHE_LOT_COULEUR_SATURATION": c["saturation"],
        "RETOUCHE_LOT_COULEUR_HUE": c["hue"],
        "RETOUCHE_LOT_COULEUR_WHITE_BALANCE": c["white_balance"],
        "RETOUCHE_LOT_COULEUR_HIGHLIGHTS": c["highlights"],
        "RETOUCHE_LOT_COULEUR_SHADOWS": c["shadows"],
        "RETOUCHE_LOT_COULEUR_WHITES": c["whites"],
        "RETOUCHE_LOT_COULEUR_BLACKS": c["blacks"],

        "RETOUCHE_LOT_VIRAGE_ENABLED": v["enabled"],
        "RETOUCHE_LOT_VIRAGE_MODE": v["mode"],
        "RETOUCHE_LOT_VIRAGE_HUE": v["hue"],
        "RETOUCHE_LOT_VIRAGE_SAT": v["sat"],
        "RETOUCHE_LOT_VIRAGE_LIGHT": v["light"],

        "RETOUCHE_LOT_NETTETE_ENABLED": n["enabled"],
        "RETOUCHE_LOT_NETTETE_RADIUS1": n["radius1"],
        "RETOUCHE_LOT_NETTETE_PERCENT1": n["percent1"],
        "RETOUCHE_LOT_NETTETE_RADIUS2": n["radius2"],
        "RETOUCHE_LOT_NETTETE_PERCENT2": n["percent2"],

        "RETOUCHE_LOT_GRAIN_ENABLED": g["enabled"],
        "CA_ENABLED": ca["enabled"], "CA_STRENGTH": ca["strength"],
        "CA_AXIAL_RATIO": ca["axial_ratio"],
        "DESAT_ENABLED": ds["enabled"],
        "DESAT_SHADOW_THRESHOLD": ds["shadow_threshold"],
        "DESAT_SHADOW_INTENSITY": ds["shadow_intensity"],
        "DESAT_HIGHLIGHT_THRESHOLD": ds["highlight_threshold"],
        "DESAT_HIGHLIGHT_INTENSITY": ds["highlight_intensity"],
        "DESAT_MIDTONE_BOOST": ds["midtone_boost"],
        "HALATION_ENABLED": ha["enabled"],
        "HALATION_THRESHOLD": ha["threshold"], "HALATION_RADIUS": ha["radius"],
        "HALATION_INTENSITY": ha["intensity"],
        "HALATION_RED_SHIFT": ha["red_shift"],
        "BLOOM_ENABLED": bl["enabled"], "BLOOM_RADIUS": bl["radius"],
        "BLOOM_INTENSITY": bl["intensity"],
        "RETOUCHE_LOT_GRAIN1_ENABLED": g1["enabled"],
        "GRAIN_AMOUNT": g1["amount"], "GRAIN_SIZE": g1["size"],
        "GRAIN_COLOR_RATIO": g1["color_ratio"],
        "GRAIN_SHADOW_BOOST": g1["shadow_boost"], "GRAIN_FLOOR": g1["floor"],
        "GRAIN_CHROMA_SHIFT": g1["chroma_shift"],
        "RETOUCHE_LOT_GRAIN2_ENABLED": g2["enabled"],
        "GRAIN2_AMOUNT": g2["amount"], "GRAIN2_SIZE": g2["size"],
        "GRAIN2_COLOR_RATIO": g2["color_ratio"],
        "GRAIN2_SHADOW_BOOST": g2["shadow_boost"], "GRAIN2_FLOOR": g2["floor"],
        "GRAIN2_CHROMA_SHIFT": g2["chroma_shift"],

        "RETOUCHE_LOT_COPYRIGHT_ENABLED": cp["enabled"],
        "RETOUCHE_LOT_COPYRIGHT_MODE": cp["mode"],
        "RETOUCHE_LOT_COPYRIGHT_CUSTOM_TEXT": cp["custom_text"],
    }


def save_params_as_defaults(params):
    """Réécrit CONSTANTS.py : chaque constante de `_constants_mapping` est
    mise à jour en place (regex sur `NOM = ancienne_valeur`, commentaire de
    fin de ligne préservé) ; les rares constantes qui n'existeraient pas
    encore dans le fichier sont ajoutées à la fin."""
    const_path = Path(__file__).resolve().parent / "CONSTANTS.py"
    text = const_path.read_text(encoding="utf-8")
    missing = []
    for name, value in _constants_mapping(params).items():
        literal = _py_literal(value)
        pattern = re.compile(rf"^{name}([ \t]*=[ \t]*)[^#\n]*?([ \t]*)(#.*)?$",
                             re.MULTILINE)

        def _replace(m, name=name, literal=literal):
            comment = f"  {m.group(3)}" if m.group(3) else ""
            return f"{name}{m.group(1)}{literal}{comment}"
        new_text, count = pattern.subn(_replace, text, count=1)
        if count:
            text = new_text
        else:
            missing.append(f"{name} = {literal}")
    if missing:
        text = (text.rstrip("\n") + "\n\n\n"
               "# ── Retouche par lot — ajouts automatiques ──\n"
               + "\n".join(missing) + "\n")
    const_path.write_text(text, encoding="utf-8")


#############################################################
#              PIPELINE PURE (aperçu + batch)                #
#############################################################
def _scale_to_image(value_px, image):
    """Met à l'échelle une valeur calibrée à RETOUCHE_LOT_REFERENCE_PX vers
    la résolution réelle de `image` (côté le plus petit) — un même réglage
    produit un effet proportionnellement identique sur le proxy d'aperçu
    et sur l'export plein format, quelle que soit leur résolution."""
    return value_px * min(image.size) / CONSTANTS.RETOUCHE_LOT_REFERENCE_PX


def _round_odd(value, minimum=3):
    v = max(minimum, round(value))
    return v if v % 2 == 1 else v + 1


def run_pipeline(image, params, *, date_label=None, filename_stem=""):
    """Applique les étapes activées, dans l'ordre : débruiter → couleur →
    virage → netteté → grain pellicule → copyright. Pure PIL/image_ops,
    aucun appel Flet — appelée identique sur le proxy réduit (aperçu) et
    sur le plein format (batch). Part toujours d'une copie : ne mute
    jamais `image` (qui peut être un proxy mis en cache entre deux
    appels).

    Rayon de netteté et fenêtres de débruitage sont calibrés pour une
    image de RETOUCHE_LOT_REFERENCE_PX (côté le plus petit) puis mis à
    l'échelle vers la résolution réelle de `image` — sans ça, un même
    réglage de netteté paraît beaucoup plus fort sur le proxy d'aperçu
    (petit) que sur l'export plein format (retour user)."""
    result = image.copy()

    d = params["denoise"]
    if d["enabled"]:
        template_window = _round_odd(_scale_to_image(d["template_window"], image))
        search_window = _round_odd(_scale_to_image(d["search_window"], image),
                                   minimum=template_window + 2)
        result = image_ops.apply_denoise(
            result, h=d["h"], h_color=d["h_color"],
            template_window=template_window,
            search_window=search_window)

    c = params["couleur"]
    if c["enabled"]:
        result = image_ops.apply_adjustments(
            result, exposure=c["exposure"], contrast=c["contrast"],
            saturation=c["saturation"], hue=c["hue"],
            white_balance=c["white_balance"])
        result = image_ops.apply_highlights(result, c["highlights"])
        result = image_ops.apply_shadows(result, c["shadows"])
        result = image_ops.apply_whites(result, c["whites"])
        result = image_ops.apply_blacks(result, c["blacks"])

    v = params["virage"]
    if v["enabled"]:
        # colorize_hsl/colorize_multiply repartent d'un gris pur (toute
        # trace de couleur de la photo d'origine est perdue) : le slider
        # Saturation de "Réglages couleur" n'avait donc aucun effet une
        # fois le virage actif (retour user). On le réutilise comme
        # multiplicateur sur l'intensité du virage lui-même — +100 double
        # la saturation de la teinte, -100 la ramène à 0 — plutôt que de
        # laisser ce slider sans effet visible dans ce cas.
        sat_scale = max(0.0, 1 + c["saturation"] / 100) if c["enabled"] else 1.0
        virage_sat = min(100, v["sat"] * sat_scale)
        if v["mode"] == "multiply":
            result = image_ops.colorize_multiply(
                result, v["hue"], virage_sat, v["light"])
        else:
            result = image_ops.colorize_hsl(result, v["hue"], virage_sat)

    n = params["nettete"]
    if n["enabled"]:
        result = image_ops.apply_sharpen(
            result, radius1=_scale_to_image(n["radius1"], image),
            percent1=n["percent1"],
            radius2=_scale_to_image(n["radius2"], image),
            percent2=n["percent2"])

    g = params["grain"]
    if g["enabled"]:
        if g["ca"]["enabled"]:
            a = g["ca"]
            result = image_ops.add_chromatic_aberration(
                result, a["strength"], a["axial_ratio"])
        if g["desat"]["enabled"]:
            a = g["desat"]
            result = image_ops.add_desaturate_extremes(
                result, a["shadow_threshold"], a["shadow_intensity"],
                a["highlight_threshold"], a["highlight_intensity"],
                a["midtone_boost"])
        if g["halation"]["enabled"]:
            a = g["halation"]
            result = image_ops.add_halation(
                result, a["threshold"], a["radius"], a["intensity"],
                a["red_shift"])
        if g["bloom"]["enabled"]:
            a = g["bloom"]
            result = image_ops.add_bloom(result, a["radius"], a["intensity"])
        if g["grain1"]["enabled"]:
            a = g["grain1"]
            result = image_ops.add_film_grain(
                result, a["amount"], a["size"], a["color_ratio"],
                a["shadow_boost"], a["floor"], a["chroma_shift"])
        if g["grain2"]["enabled"]:
            a = g["grain2"]
            result = image_ops.add_film_grain(
                result, a["amount"], a["size"], a["color_ratio"],
                a["shadow_boost"], a["floor"], a["chroma_shift"])

    cp = params["copyright"]
    if cp["enabled"]:
        if cp["mode"] == "custom" and cp["custom_text"]:
            label = cp["custom_text"]
        elif cp["mode"] == "filename":
            label = filename_stem
        else:
            label = date_label or filename_stem
        result = image_ops.add_copyright(result, label)

    return result.convert("RGB")


#############################################################
#                        HISTOGRAMME                         #
#############################################################
_HISTOGRAM_HEIGHT = 90
_HISTOGRAM_CHANNEL_COLORS = ((235, 70, 70), (70, 220, 100), (80, 150, 255))


def _remap_counts(counts_256, width):
    """Reprojette 256 bins sur `width` colonnes sans interpolation continue
    (même logique que Recadrage manuel.pyw)."""
    if width < 256:
        counts = np.zeros(width, dtype=np.float32)
        mapped_x = np.clip((np.arange(256, dtype=np.int32) * width) // 256,
                           0, width - 1)
        np.add.at(counts, mapped_x, counts_256)
    elif width > 256:
        mapped_x = np.round(np.linspace(0, 255, width)).astype(np.int32)
        counts = counts_256[mapped_x]
    else:
        counts = counts_256.copy()
    return counts


def render_histogram(pil_image, width, height=_HISTOGRAM_HEIGHT):
    """Histogramme RVB superposé (canaux semi-transparents), pour visualiser
    l'effet des réglages couleur/virage en temps réel."""
    arr = np.asarray(pil_image.convert("RGB"), dtype=np.uint8)
    base = Image.new("RGBA", (width, height), (20, 20, 26, 255))
    baseline = height - 1
    for ch, color in enumerate(_HISTOGRAM_CHANNEL_COLORS):
        counts_256 = np.bincount(
            arr[:, :, ch].ravel(), minlength=256)[:256].astype(np.float32)
        counts = _remap_counts(counts_256, width)
        peak = max(float(np.percentile(counts, 99.9)), 1.0)
        heights = np.clip((counts / peak) * (height - 1), 0, height - 1)
        layer = Image.new("RGBA", (width, height), (0, 0, 0, 0))
        draw = ImageDraw.Draw(layer)
        for x in range(width):
            if counts[x] <= 0 or heights[x] < 1:
                continue
            top_y = max(0, baseline - int(round(float(heights[x]))))
            draw.line([(x, baseline), (x, top_y)], fill=(*color, 140))
        base = Image.alpha_composite(base, layer)
    return base.convert("RGB")


#############################################################
#                           MAIN                             #
#############################################################
def main(page: ft.Page):
    page.title = "Retouche par lot"
    page.theme_mode = ft.ThemeMode.DARK
    page.bgcolor = BG
    page.padding = 0
    page.run_task(page.window.to_front)

    folder_path = Path(os.environ.get(
        "FOLDER_PATH", str(Path(__file__).resolve().parent)))
    selected_files_str = os.environ.get("SELECTED_FILES", "")
    selected_files_set = (set(selected_files_str.split("|"))
                          if selected_files_str else None)
    all_files = sorted(
        f.name for f in folder_path.iterdir()
        if f.is_file() and f.suffix.upper() in EXTENSION
        and f.name != "watermark.png")
    file_names = ([f for f in all_files if f in selected_files_set]
                  if selected_files_set else all_files)

    if not file_names:
        page.add(ft.Text("Aucune image trouvée dans ce dossier.",
                         color=RED, size=CONSTANTS.TEXT_LG))
        return

    state = {
        "index": 0,
        "source_image": None,
        "proxy": None,
        "date_label": None,
        "live_req": 0,
        "live_lock": threading.Lock(),
        "live_running": False,
        "params": default_params(),
    }

    # Contrôles à resynchroniser quand le bouton Réinitialiser recharge
    # state["params"] depuis CONSTANTS.py — alimenté par _make_section,
    # _slider_row, _num_field et _grain_tile au fil de la construction de
    # l'UI ci-dessous.
    reset_registry = {"switches": [], "sliders": [], "fields": []}

    # ── Aperçu ────────────────────────────────────────────────────────
    # Pan/zoom natif Flet (même widget que le viewer plein écran de
    # Hub.pyw) : ft.InteractiveViewer a besoin d'un width/height explicite
    # (pas `expand`), sinon `constrained=True` le dimensionne sur le
    # rectangle CONTAIN de l'image au lieu du viewport voulu, et zoomer
    # agrandit l'image dans ce rectangle fixe au lieu du cadre disponible.
    # Taille de départ raisonnable ; recalculée d'après la résolution de
    # la fenêtre dans _apply_preview_size (page.on_resize).
    state["preview_w"], state["preview_h"] = 760, 560
    image_display = ft.Image(src=_BLANK_SRC, gapless_playback=True,
                             fit=ft.BoxFit.CONTAIN,
                             width=state["preview_w"], height=state["preview_h"])
    preview_viewer = ft.InteractiveViewer(
        content=image_display, min_scale=1.0, max_scale=6.0,
        pan_enabled=True, scale_enabled=True, constrained=True,
        width=state["preview_w"], height=state["preview_h"],
        clip_behavior=ft.ClipBehavior.HARD_EDGE)
    preview_container = ft.Container(
        content=preview_viewer,
        width=state["preview_w"] + 16, height=state["preview_h"] + 16,
        bgcolor=DARK, border_radius=8, padding=8,
        alignment=ft.Alignment.CENTER)
    histogram_image = ft.Image(src=_BLANK_SRC, gapless_playback=True,
                               fit=ft.BoxFit.FILL,
                               width=state["preview_w"], height=_HISTOGRAM_HEIGHT)
    counter_text = ft.Text("", size=CONSTANTS.TEXT_SM, color=WHITE)

    _ROW_SPACING = 16

    def _apply_preview_size(e=None):
        """Colonne outils (gauche) = 40 % de la largeur de fenêtre en
        pixels fixes ; la colonne aperçu (droite) prend tout le reste (pas
        une fraction devinée : largeur de fenêtre moins colonne outils
        moins l'espacement du Row, page.padding étant à 0)."""
        page_w = int(getattr(e, "width", None) or page.width or 1400)
        page_h = int(getattr(e, "height", None) or page.height or 900)
        right_w = max(320, int(page_w * 0.40))
        controls_container.width = right_w
        left_w = max(480, page_w - right_w - _ROW_SPACING)
        h = max(360, int(page_h * 0.60))
        w = left_w - 16  # 16 = padding intérieur (8x2) de preview_container
        state["preview_w"], state["preview_h"] = w, h
        image_display.width, image_display.height = w, h
        preview_viewer.width, preview_viewer.height = w, h
        preview_container.width, preview_container.height = left_w, h + 16
        histogram_image.width = w
        controls_container.update()
        preview_container.update()
        histogram_image.update()
        live_preview_tick()

    page.on_resize = _apply_preview_size

    def _live_preview_loop():
        while True:
            with state["live_lock"]:
                request_seen = state["live_req"]
            proxy = state["proxy"]
            params_copy = copy.deepcopy(state["params"])
            date_label = state["date_label"]
            stem = Path(file_names[state["index"]]).stem
            try:
                if state.get("show_original"):
                    result = proxy.convert("RGB")
                else:
                    result = run_pipeline(proxy, params_copy,
                                          date_label=date_label,
                                          filename_stem=stem)
                buf = io.BytesIO()
                result.save(buf, format="JPEG", quality=85)
                src = ("data:image/jpeg;base64,"
                      + base64.b64encode(buf.getvalue()).decode())
                hist_img = render_histogram(result, state["preview_w"])
                hbuf = io.BytesIO()
                hist_img.save(hbuf, format="PNG")
                hist_src = ("data:image/png;base64,"
                           + base64.b64encode(hbuf.getvalue()).decode())
            except Exception:
                src = None
                hist_src = None

            if src:
                async def _apply(src=src, hist_src=hist_src):
                    image_display.src = src
                    image_display.update()
                    if hist_src:
                        histogram_image.src = hist_src
                        histogram_image.update()
                page.run_task(_apply)

            with state["live_lock"]:
                if state["live_req"] == request_seen:
                    state["live_running"] = False
                    return
            time.sleep(0.03)

    def live_preview_tick():
        with state["live_lock"]:
            state["live_req"] += 1
            if state["live_running"]:
                return
            state["live_running"] = True
        threading.Thread(target=_live_preview_loop, daemon=True).start()

    def load_representative(idx):
        idx = max(0, min(idx, len(file_names) - 1))
        name = file_names[idx]
        path = folder_path / name
        try:
            raw = Image.open(path)
            state["date_label"] = image_ops.get_date_taken(raw)
            img = image_ops.open_srgb(path)
        except Exception as exc:
            counter_text.value = f"Erreur : {exc}"
            page.update()
            return
        state["index"] = idx
        state["source_image"] = img
        max_px = CONSTANTS.RETOUCHE_LOT_PREVIEW_MAX_PIXELS
        ratio = min(max_px / img.width, max_px / img.height, 1.0)
        if ratio < 1.0:
            proxy = img.resize(
                (max(1, round(img.width * ratio)),
                 max(1, round(img.height * ratio))),
                Image.Resampling.BICUBIC)
        else:
            proxy = img.copy()
        state["proxy"] = proxy
        counter_text.value = f"{idx + 1} / {len(file_names)} — {name}"
        page.update()
        live_preview_tick()

    def _prev(e):
        load_representative(state["index"] - 1)

    def _next(e):
        load_representative(state["index"] + 1)

    state["show_original"] = False

    def _toggle_compare(e):
        state["show_original"] = not state["show_original"]
        compare_btn.icon_color = BLUE if state["show_original"] else WHITE
        compare_btn.update()
        live_preview_tick()

    compare_btn = ft.IconButton(
        ft.Icons.COMPARE, icon_color=WHITE, on_click=_toggle_compare,
        tooltip="Avant / Après (comparer avec l'original)")

    preview_column = ft.Column([
        preview_container,
        histogram_image,
        ft.Row([
            ft.IconButton(ft.Icons.CHEVRON_LEFT, on_click=_prev,
                         icon_color=WHITE),
            counter_text,
            ft.IconButton(ft.Icons.CHEVRON_RIGHT, on_click=_next,
                         icon_color=WHITE),
            compare_btn,
        ], alignment=ft.MainAxisAlignment.CENTER, spacing=4),
    ], horizontal_alignment=ft.CrossAxisAlignment.CENTER)

    # ── Panneaux repliables (un seul ouvert à la fois) ─────────────────
    sections = {}

    def _toggle_section(name):
        def handler(e):
            opening = not sections[name]["body"].visible
            for other_name, sec in sections.items():
                sec["body"].visible = (other_name == name and opening)
            page.update()
        return handler

    def _make_section(name, color, param, body_controls):
        switch = ft.Switch(value=param["enabled"], active_color=color)

        def _on_switch(e):
            param["enabled"] = switch.value
            live_preview_tick()
        switch.on_change = _on_switch
        reset_registry["switches"].append((switch, param))

        header = ft.Container(
            content=ft.Row([
                ft.Container(
                    content=ft.Row([
                        ft.Text(name, color=color,
                               weight=ft.FontWeight.W_600,
                               size=CONSTANTS.TEXT_SM),
                    ]),
                    on_click=_toggle_section(name), expand=True,
                    padding=ft.Padding(4, 8, 4, 8),
                ),
                switch,
            ], alignment=ft.MainAxisAlignment.SPACE_BETWEEN),
            bgcolor=DARK, border_radius=6, padding=ft.Padding(8, 0, 8, 0),
        )
        body = ft.Container(
            content=ft.Column(body_controls, spacing=10),
            visible=False, padding=ft.Padding(16, 10, 16, 14),
            bgcolor=BG, border_radius=6)
        sections[name] = {"body": body, "switch": switch}
        return ft.Column([header, body], spacing=2)

    def _slider_row(label, dct, key, minv, maxv, *, divisions=None):
        """Slider cranté par pas entiers par défaut (un pas = une unité
        affichée) plutôt que des valeurs flottantes continues (retour
        user) — passer `divisions` explicitement pour un pas plus fin.
        Double-clic : revient à 0 (ou au minimum si 0 est hors plage,
        ex. rayons de netteté qui commencent à 1). Auto-enregistré dans
        `reset_registry` pour le bouton Réinitialiser."""
        value = dct[key]
        if divisions is None:
            divisions = round(maxv - minv)
        reset_value = max(0, minv)
        text = ft.Text(f"{label} : {round(value)}", size=CONSTANTS.TEXT_SM,
                       color=WHITE)

        def _handle(e):
            snapped = round(e.control.value)
            text.value = f"{label} : {snapped}"
            dct[key] = snapped
            text.update()
            live_preview_tick()
        slider = ft.Slider(min=minv, max=maxv, value=value,
                          divisions=divisions, on_change=_handle,
                          active_color=BLUE)

        def _reset(e):
            slider.value = reset_value
            dct[key] = reset_value
            text.value = f"{label} : {round(reset_value)}"
            slider.update()
            text.update()
            live_preview_tick()
        slider_area = ft.GestureDetector(content=slider,
                                        on_double_tap=_reset)
        column = ft.Column([text, slider_area], spacing=0)
        column.data = slider
        reset_registry["sliders"].append((column, label, dct, key))
        return column

    # ── Débruiter ───────────────────────────────────────────────────
    dn = state["params"]["denoise"]
    section_denoise = _make_section("Débruiter", RED, dn, [
        _slider_row("Force luminance", dn, "h", 0, 25),
        _slider_row("Force couleur", dn, "h_color", 0, 25),
    ])

    # ── Réglages couleur ────────────────────────────────────────────
    co = state["params"]["couleur"]
    section_couleur = _make_section("Réglages couleur", BLUE, co, [
        _slider_row("Exposition", co, "exposure", -100, 100),
        _slider_row("Contraste", co, "contrast", -100, 100),
        _slider_row("Saturation", co, "saturation", -100, 100),
        _slider_row("Teinte", co, "hue", -100, 100),
        _slider_row("Balance des blancs", co, "white_balance", -100, 100),
        _slider_row("Hautes lumières", co, "highlights", -100, 100),
        _slider_row("Ombres", co, "shadows", -100, 100),
        _slider_row("Blancs", co, "whites", -100, 100),
        _slider_row("Noirs", co, "blacks", -100, 100),
    ])

    # ── Virage ──────────────────────────────────────────────────────
    vi = state["params"]["virage"]
    virage_hue_row = _slider_row("Teinte", vi, "hue", 0, 360)
    virage_sat_row = _slider_row("Saturation", vi, "sat", 0, 100)
    virage_light_row = _slider_row("Luminosité", vi, "light", 0, 100)

    def _reseed_virage_controls():
        virage_hue_row.data.value = vi["hue"]
        virage_hue_row.controls[0].value = f"Teinte : {round(vi['hue'])}"
        virage_sat_row.data.value = vi["sat"]
        virage_sat_row.controls[0].value = f"Saturation : {round(vi['sat'])}"
        virage_light_row.data.value = vi["light"]
        virage_light_row.controls[0].value = (
            f"Luminosité : {round(vi['light'])}")

    def _on_virage_preset(e):
        preset_name = virage_preset_dd.value
        preset = CONSTANTS.VIRAGE_PRESETS[preset_name]
        vi["preset"] = preset_name
        vi["mode"] = preset["mode"]
        vi["hue"] = preset["hue"]
        vi["sat"] = preset["sat"]
        vi["light"] = preset.get("light", 50)
        virage_mode_dd.value = "Auto (préréglage)"
        _reseed_virage_controls()
        page.update()
        live_preview_tick()

    virage_preset_dd = ft.Dropdown(
        label="Préréglage", value=vi["preset"],
        options=[ft.dropdown.Option(name)
                for name in CONSTANTS.VIRAGE_PRESETS],
        bgcolor=DARK, border_color=GREY, color=WHITE,
        on_select=_on_virage_preset)

    _mode_labels = {"colorize": "Coloriser", "multiply": "Multiplier"}

    def _on_virage_mode(e):
        choice = virage_mode_dd.value
        if choice == "Auto (préréglage)":
            vi["mode"] = CONSTANTS.VIRAGE_PRESETS[vi["preset"]]["mode"]
        elif choice == "Coloriser":
            vi["mode"] = "colorize"
        else:
            vi["mode"] = "multiply"
        live_preview_tick()

    virage_mode_dd = ft.Dropdown(
        label="Mode", value="Auto (préréglage)",
        options=[ft.dropdown.Option("Auto (préréglage)"),
                ft.dropdown.Option("Coloriser"),
                ft.dropdown.Option("Multiplier")],
        bgcolor=DARK, border_color=GREY, color=WHITE,
        on_select=_on_virage_mode)

    section_virage = _make_section("Virage", YELLOW, vi, [
        virage_preset_dd, virage_mode_dd, virage_hue_row, virage_sat_row,
        virage_light_row,
    ])

    # ── Netteté ─────────────────────────────────────────────────────
    ne = state["params"]["nettete"]
    section_nettete = _make_section("Netteté", GREEN, ne, [
        _slider_row("Rayon — passe 1", ne, "radius1", 1, 8),
        _slider_row("Intensité — passe 1 (%)", ne, "percent1", 0, 150),
        _slider_row("Rayon — passe 2", ne, "radius2", 1, 8),
        _slider_row("Intensité — passe 2 (%)", ne, "percent2", 0, 150),
    ])

    # ── Grain pellicule (sous-panneaux imbriqués, comme Hub.pyw) ───────
    ga = state["params"]["grain"]

    def _num_field(sub, key, label, width=140):
        field = ft.TextField(
            label=label, value=str(sub[key]), width=width, bgcolor=DARK,
            border_color=GREY, color=WHITE,
            keyboard_type=ft.KeyboardType.NUMBER)

        def _handle(e):
            try:
                sub[key] = float(field.value)
            except ValueError:
                return
            live_preview_tick()
        field.on_blur = _handle
        field.on_submit = _handle
        reset_registry["fields"].append((field, sub, key))
        return field

    def _grain_tile(label, color, sub, field_specs):
        sw = ft.Switch(value=sub["enabled"], active_color=color)

        def _on_sw(e):
            sub["enabled"] = sw.value
            live_preview_tick()
        sw.on_change = _on_sw
        reset_registry["switches"].append((sw, sub))
        fields = [_num_field(sub, key, flabel) for key, flabel in field_specs]
        return ft.ExpansionTile(
            title=ft.Text(label, color=color, weight=ft.FontWeight.W_600,
                         size=CONSTANTS.TEXT_SM),
            leading=sw,
            controls=[ft.Container(
                content=ft.Column(fields, spacing=8),
                padding=ft.Padding(16, 4, 16, 12))],
        )

    grain_tiles = [
        _grain_tile("Aberrations chromatiques", YELLOW, ga["ca"], [
            ("strength", "Intensité"), ("axial_ratio", "Ratio axial")]),
        _grain_tile("Désaturation des extrêmes", VIOLET, ga["desat"], [
            ("shadow_threshold", "Seuil ombres"),
            ("shadow_intensity", "Intensité ombres"),
            ("highlight_threshold", "Seuil HL"),
            ("highlight_intensity", "Intensité HL"),
            ("midtone_boost", "Boost mi-tons")]),
        _grain_tile("Halation", RED, ga["halation"], [
            ("threshold", "Seuil"), ("radius", "Rayon"),
            ("intensity", "Intensité"), ("red_shift", "Décalage rouge")]),
        _grain_tile("Bloom (Soft Light)", BLUE, ga["bloom"], [
            ("radius", "Rayon"), ("intensity", "Intensité")]),
        _grain_tile("Grain — Couche 1", ORANGE, ga["grain1"], [
            ("amount", "Intensité"), ("size", "Taille"),
            ("color_ratio", "Part couleur"),
            ("shadow_boost", "Concentration mi-tons"),
            ("chroma_shift", "Décalage inter-canal")]),
        _grain_tile("Grain — Couche 2", ORANGE, ga["grain2"], [
            ("amount", "Intensité"), ("size", "Taille"),
            ("color_ratio", "Part couleur"),
            ("shadow_boost", "Concentration mi-tons"),
            ("chroma_shift", "Décalage inter-canal")]),
    ]
    section_grain = _make_section("Grain pellicule", ORANGE, ga, grain_tiles)

    # ── Copyright ───────────────────────────────────────────────────
    cp = state["params"]["copyright"]
    copyright_custom_field = ft.TextField(
        label="Texte personnalisé", value=cp["custom_text"], width=280,
        bgcolor=DARK, border_color=GREY, color=WHITE,
        visible=(cp["mode"] == "custom"))

    def _on_copyright_text(e):
        cp["custom_text"] = copyright_custom_field.value
        live_preview_tick()
    copyright_custom_field.on_blur = _on_copyright_text
    copyright_custom_field.on_submit = _on_copyright_text

    def _on_copyright_mode(e):
        mode_map = {"Date": "date", "Nom de fichier": "filename",
                   "Personnalisé": "custom"}
        cp["mode"] = mode_map[copyright_mode_dd.value]
        copyright_custom_field.visible = (cp["mode"] == "custom")
        page.update()
        live_preview_tick()

    copyright_mode_dd = ft.Dropdown(
        label="Mode", value="Date",
        options=[ft.dropdown.Option("Date"),
                ft.dropdown.Option("Nom de fichier"),
                ft.dropdown.Option("Personnalisé")],
        bgcolor=DARK, border_color=GREY, color=WHITE,
        on_select=_on_copyright_mode)

    section_copyright = _make_section("Copyright", WHITE, cp, [
        copyright_mode_dd, copyright_custom_field,
    ])

    # ── Batch final ─────────────────────────────────────────────────
    progress_bar = ft.ProgressBar(width=300, visible=False, color=BLUE)
    progress_text = ft.Text("", size=CONSTANTS.TEXT_SM, color=WHITE)

    def _update_progress(done, total):
        progress_bar.value = done / total
        progress_text.value = f"{done} / {total}"

    def batch_worker(params_snapshot):
        output_folder = folder_path / "RETOUCHE"
        output_folder.mkdir(exist_ok=True)
        # Réglages utilisés pour ce lot — rechargeables via "Charger des
        # réglages…" pour reprendre et ajuster un lot précédent.
        with open(output_folder / "retouche_params.json", "w",
                  encoding="utf-8") as f:
            json.dump(params_snapshot, f, indent=2, ensure_ascii=False)
        total = len(file_names)
        for i, name in enumerate(file_names):
            print(f"Image {i + 1} sur {total}")
            try:
                raw = Image.open(folder_path / name)
                date_label = image_ops.get_date_taken(raw)
                img = image_ops.open_srgb(folder_path / name)
            except Exception:
                continue
            stem = Path(name).stem
            result = run_pipeline(img, params_snapshot,
                                  date_label=date_label, filename_stem=stem)
            result.save(str(output_folder / f"{stem}.jpg"), format="JPEG",
                       subsampling=0, quality=100,
                       icc_profile=image_ops._SRGB_ICC)

            async def _tick(done=i + 1, total=total):
                _update_progress(done, total)
                progress_bar.update()
                progress_text.update()
            page.run_task(_tick)
        print("Terminé !")
        print(f"NAVIGATE_TO:{output_folder}")

        async def _done():
            progress_text.value = "Terminé !"
            progress_text.update()
            await asyncio.sleep(1)
            try:
                await page.window.destroy()
            except Exception:
                pass
        page.run_task(_done)

    def _confirm_batch(e):
        dlg.open = False
        page.update()
        params_snapshot = copy.deepcopy(state["params"])
        batch_button.disabled = True
        progress_bar.visible = True
        progress_bar.value = 0
        progress_text.value = f"0 / {len(file_names)}"
        page.update()
        threading.Thread(target=batch_worker, args=(params_snapshot,),
                         daemon=True).start()

    def _cancel_batch(e):
        dlg.open = False
        page.update()

    dlg = ft.AlertDialog(
        title=ft.Text("Lancer le traitement complet ?",
                     size=CONSTANTS.TEXT_SM, color=WHITE),
        content=ft.Text(f"{len(file_names)} image(s) seront traitées avec "
                        "les réglages actuels, dans RETOUCHE/.",
                        size=CONSTANTS.TEXT_SM, color=WHITE),
        actions=[ft.TextButton("Annuler", on_click=_cancel_batch),
                ft.TextButton("Lancer", on_click=_confirm_batch)],
    )

    def _open_batch_dialog(e):
        page.overlay.append(dlg)
        dlg.open = True
        page.update()

    batch_button = ft.FilledButton(
        f"Lancer le traitement complet ({len(file_names)} images)",
        icon=ft.Icons.PLAY_ARROW, bgcolor=GREEN, color=DARK,
        on_click=_open_batch_dialog)

    # ── Enregistrer comme réglages par défaut ──────────────────────────
    save_defaults_status = ft.Text("", size=CONSTANTS.TEXT_SM, color=GREEN)

    def _confirm_save_defaults(e):
        save_defaults_dlg.open = False
        try:
            save_params_as_defaults(state["params"])
            save_defaults_status.value = "Réglages enregistrés par défaut."
            save_defaults_status.color = GREEN
        except Exception as exc:
            save_defaults_status.value = f"Erreur : {exc}"
            save_defaults_status.color = RED
        page.update()

    def _cancel_save_defaults(e):
        save_defaults_dlg.open = False
        page.update()

    save_defaults_dlg = ft.AlertDialog(
        title=ft.Text("Enregistrer comme réglages par défaut ?",
                     size=CONSTANTS.TEXT_SM, color=WHITE),
        content=ft.Text("Les réglages actuels remplaceront les valeurs par "
                        "défaut dans CONSTANTS.py, pour ce dossier comme "
                        "pour les prochains lancements de l'outil.",
                        size=CONSTANTS.TEXT_SM, color=WHITE),
        actions=[ft.TextButton("Annuler", on_click=_cancel_save_defaults),
                ft.TextButton("Enregistrer", on_click=_confirm_save_defaults)],
    )

    def _open_save_defaults_dialog(e):
        save_defaults_status.value = ""
        page.overlay.append(save_defaults_dlg)
        save_defaults_dlg.open = True
        page.update()

    save_defaults_button = ft.OutlinedButton(
        "Enregistrer comme réglages par défaut",
        icon=ft.Icons.SAVE_OUTLINED, on_click=_open_save_defaults_dialog,
        style=ft.ButtonStyle(color=BLUE, side=ft.BorderSide(1, BLUE)))

    # ── Resynchronisation de l'UI depuis state["params"] ────────────────
    def _sync_controls_from_params():
        """Reflète state["params"] (déjà à jour) sur tous les contrôles —
        partagé par Réinitialiser et Charger des réglages."""
        for switch, dct in reset_registry["switches"]:
            switch.value = dct["enabled"]
            switch.update()
        for column, label, dct, key in reset_registry["sliders"]:
            value = dct[key]
            column.data.value = value
            column.controls[0].value = f"{label} : {round(value)}"
            column.data.update()
            column.controls[0].update()
        for field, dct, key in reset_registry["fields"]:
            field.value = str(dct[key])
            field.update()

        virage_preset_dd.value = vi["preset"]
        # "Auto" si le mode courant correspond à celui du préréglage (cas
        # le plus fréquent après un chargement), sinon le mode explicite
        # (retour user : un fichier chargé avec un mode dévié du
        # préréglage ne doit pas être affiché comme "Auto").
        preset_mode = CONSTANTS.VIRAGE_PRESETS.get(vi["preset"], {}).get("mode")
        virage_mode_dd.value = (
            "Auto (préréglage)" if vi["mode"] == preset_mode
            else _mode_labels.get(vi["mode"], "Auto (préréglage)"))
        virage_preset_dd.update()
        virage_mode_dd.update()

        copyright_mode_dd.value = {
            "date": "Date", "filename": "Nom de fichier",
            "custom": "Personnalisé"}[cp["mode"]]
        copyright_custom_field.value = cp["custom_text"]
        copyright_custom_field.visible = (cp["mode"] == "custom")
        copyright_mode_dd.update()
        copyright_custom_field.update()

        page.update()

    # ── Réinitialiser les réglages par défaut ──────────────────────────
    def _confirm_reset(e):
        reset_dlg.open = False
        _update_in_place(state["params"], default_params())
        _sync_controls_from_params()
        live_preview_tick()

    def _cancel_reset(e):
        reset_dlg.open = False
        page.update()

    reset_dlg = ft.AlertDialog(
        title=ft.Text("Réinitialiser les réglages par défaut ?",
                     size=CONSTANTS.TEXT_SM, color=WHITE),
        content=ft.Text("Tous les réglages actuels seront remplacés par "
                        "les valeurs par défaut de CONSTANTS.py.",
                        size=CONSTANTS.TEXT_SM, color=WHITE),
        actions=[ft.TextButton("Annuler", on_click=_cancel_reset),
                ft.TextButton("Réinitialiser", on_click=_confirm_reset)],
    )

    def _open_reset_dialog(e):
        page.overlay.append(reset_dlg)
        reset_dlg.open = True
        page.update()

    reset_button = ft.OutlinedButton(
        "Réinitialiser les réglages par défaut",
        icon=ft.Icons.RESTART_ALT, on_click=_open_reset_dialog,
        style=ft.ButtonStyle(color=RED, side=ft.BorderSide(1, RED)))

    # ── Charger des réglages depuis un fichier retouche_params.json ────
    # (déposé par chaque batch, cf. batch_worker) — pour reprendre et
    # ajuster les réglages d'un lot précédent.
    load_params_status = ft.Text("", size=CONSTANTS.TEXT_SM, color=GREEN)

    async def _load_params_file(e):
        files = await ft.FilePicker().pick_files(
            dialog_title="Charger des réglages retouche",
            initial_directory=str(folder_path),
            file_type=ft.FilePickerFileType.CUSTOM,
            allowed_extensions=["json"], allow_multiple=False)
        if not files or not files[0].path:
            return
        try:
            with open(files[0].path, "r", encoding="utf-8") as f:
                loaded = json.load(f)
            _update_in_place(state["params"], loaded)
        except Exception as exc:
            load_params_status.value = f"Erreur : {exc}"
            load_params_status.color = RED
            load_params_status.update()
            return
        _sync_controls_from_params()
        load_params_status.value = f"Réglages chargés depuis {files[0].name}."
        load_params_status.color = GREEN
        load_params_status.update()
        live_preview_tick()

    load_params_button = ft.OutlinedButton(
        "Charger des réglages…",
        icon=ft.Icons.FOLDER_OPEN_OUTLINED, on_click=_load_params_file,
        style=ft.ButtonStyle(color=VIOLET, side=ft.BorderSide(1, VIOLET)))

    # ── Mise en page ────────────────────────────────────────────────
    controls_container = ft.Container(
        content=ft.Column(
            [section_denoise, section_couleur, section_virage,
             section_nettete, section_grain, section_copyright,
             ft.Divider(color=GREY),
             save_defaults_button, reset_button, save_defaults_status,
             load_params_button, load_params_status],
            spacing=6, scroll=ft.ScrollMode.AUTO, expand=True),
        padding=12, bgcolor=BG)

    page.add(
        ft.Row([
            controls_container,
            ft.Column(
                [preview_column,
                 ft.Divider(color=GREY),
                 ft.Row([progress_bar, progress_text], spacing=12),
                 batch_button],
                expand=True, alignment=ft.MainAxisAlignment.CENTER,
                horizontal_alignment=ft.CrossAxisAlignment.STRETCH),
        ], expand=True, spacing=_ROW_SPACING,
           vertical_alignment=ft.CrossAxisAlignment.STRETCH)
    )

    async def _startup():
        # page.window.maximized est appliqué de façon asynchrone par
        # Flutter : lire page.width tout de suite après renvoie encore la
        # taille de fenêtre par défaut (~800px), ce qui sous-dimensionnait
        # l'aperçu (retour user). On attend que la largeur bouge (comme
        # Augmentation IA.py) avant le premier calcul.
        pre_w = page.window.width or 0
        page.window.maximized = True
        page.update()
        for _ in range(40):
            await asyncio.sleep(0.1)
            if (page.window.width or 0) != pre_w:
                break
        await asyncio.sleep(0.2)
        _apply_preview_size()
        load_representative(0)

    page.run_task(_startup)


if __name__ == "__main__":
    ft.run(main)
