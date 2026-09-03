# -*- coding: utf-8 -*-
"""
Retouche par lot.pyw — aperçu live sur une image représentative, puis
application de la même pipeline (débruitage, réglages couleur, virage,
LUT 3D, netteté, grain pellicule, copyright) en pleine résolution sur tout
le dossier/sélection.

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
            "auto_cast": C.RETOUCHE_LOT_COULEUR_AUTO_CAST,
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
        "lut": {
            "enabled": C.RETOUCHE_LOT_LUT_ENABLED,
            "name": C.RETOUCHE_LOT_LUT_NAME,
            "intensity": C.RETOUCHE_LOT_LUT_INTENSITY,
        },
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


#############################################################
#                   PRÉRÉGLAGES NOMMÉS                      #
#############################################################
# Un préréglage = un fichier .json de paramètres, même format que le
# retouche_params.json déposé par chaque lot — les deux sont donc
# interchangeables : on peut déposer le fichier d'un lot réussi dans
# PRESETS_DIR pour en faire un préréglage.
#
# ponytail: pas de bouton Supprimer. Tout est lancé depuis Hub.pyw, dont la
# surface Fichiers sait déjà supprimer un .json — dupliquer ça ici
# ajouterait un dialogue de confirmation pour une action déjà accessible.
PRESETS_DIR = Path(__file__).resolve().parent / "presets_retouche"

# Un nom de préréglage devient un nom de fichier : tout ce qui n'est pas
# lettre/chiffre/espace/tiret/underscore est écarté, ce qui neutralise au
# passage « ../ » et les séparateurs de chemin (le nom vient d'un champ
# libre). Accents conservés : les noms sont en français.
_PRESET_NAME_RE = re.compile(r"[^\w \-]", re.UNICODE)


def sanitize_preset_name(name):
    """Nom de préréglage -> nom de fichier sûr, ou "" si rien n'en reste."""
    cleaned = _PRESET_NAME_RE.sub("", (name or "").strip())
    # Points de tête exclus : ils produiraient un fichier caché, invisible
    # dans la liste comme dans Hub.
    return cleaned.strip(" .")[:60].strip()


def list_presets():
    """Noms des préréglages disponibles, triés alphabétiquement."""
    if not PRESETS_DIR.is_dir():
        return []
    return sorted(p.stem for p in PRESETS_DIR.glob("*.json"))


def load_preset(name):
    """Paramètres d'un préréglage. Lève si le nom est vide ou introuvable."""
    safe = sanitize_preset_name(name)
    if not safe:
        raise ValueError("Nom de préréglage invalide.")
    with open(PRESETS_DIR / f"{safe}.json", "r", encoding="utf-8") as f:
        return json.load(f)


def save_preset(name, params):
    """Écrit un préréglage et renvoie le nom retenu (après nettoyage)."""
    safe = sanitize_preset_name(name)
    if not safe:
        raise ValueError("Nom de préréglage invalide.")
    PRESETS_DIR.mkdir(exist_ok=True)
    with open(PRESETS_DIR / f"{safe}.json", "w", encoding="utf-8") as f:
        json.dump(params, f, indent=2, ensure_ascii=False)
    return safe


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
    virage → LUT → netteté → grain pellicule → copyright. Pure PIL/image_ops,
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
        if c["auto_cast"] > 0:
            # Avant les autres réglages : neutralise la dominante d'abord,
            # exposition/contraste/etc. affinent ensuite sur une base
            # déjà rééquilibrée plutôt que de composer avec le virage.
            result = image_ops.apply_auto_color_cast(
                result, strength=c["auto_cast"])
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

    lu = params["lut"]
    if lu["enabled"]:
        result = image_ops.apply_cube_lut(
            result, lu["name"], lu["intensity"])

    n = params["nettete"]
    if n["enabled"]:
        result = image_ops.apply_sharpen(
            result, radius1=_scale_to_image(n["radius1"], image),
            percent1=n["percent1"],
            radius2=_scale_to_image(n["radius2"], image),
            percent2=n["percent2"])

    g = params["grain"]
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
    CONSTANTS.attach_error_copy_snackbar(
        page, ignore=("Codec failed to produce an image",))
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

    _ROW_SPACING = CONSTANTS.SPACE_LG

    def _proxy_max_px():
        """Résolution cible du proxy d'aperçu, calée sur la taille réelle du
        widget plutôt que sur une constante fixe (cf. image_ops)."""
        return image_ops.preview_max_px(
            max(state["preview_w"], state["preview_h"]),
            CONSTANTS.RETOUCHE_LOT_PREVIEW_MAX_PIXELS,
            CONSTANTS.RETOUCHE_LOT_PREVIEW_CEILING)

    def _rebuild_proxy():
        """Reconstruit le proxy depuis l'original si la cible a changé.

        Renvoie True si le proxy a été remplacé (l'appelant enchaîne alors
        sur live_preview_tick()).
        """
        img = state["source_image"]
        if img is None:
            return False
        target = _proxy_max_px()
        current = state.get("proxy_max_px")
        # Les micro-variations sont ignorées : page.on_resize se déclenche en
        # continu pendant le glissement d'un bord de fenêtre, et
        # ré-échantillonner l'original (plusieurs dizaines de mégapixels) à
        # chaque événement coûte bien plus cher que la boucle d'aperçu.
        if current and abs(target - current) <= 0.1 * current:
            return False
        ratio = min(target / img.width, target / img.height, 1.0)
        if ratio < 1.0:
            state["proxy"] = img.resize(
                (max(1, round(img.width * ratio)),
                 max(1, round(img.height * ratio))),
                Image.Resampling.BICUBIC)
        else:
            state["proxy"] = img.copy()
        state["proxy_max_px"] = target
        return True

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
        w = left_w - CONSTANTS.SPACE_LG  # padding intérieur (8x2) de
                                          # preview_container
        state["preview_w"], state["preview_h"] = w, h
        image_display.width, image_display.height = w, h
        preview_viewer.width, preview_viewer.height = w, h
        preview_container.width, preview_container.height = left_w, h + 16
        histogram_image.width = w
        controls_container.update()
        preview_container.update()
        histogram_image.update()
        # L'aperçu a changé de taille : le proxy doit suivre, sinon on
        # continue d'afficher une image rendue pour l'ancienne fenêtre.
        _rebuild_proxy()
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
        state["proxy_max_px"] = None  # force la reconstruction ci-dessous
        _rebuild_proxy()
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
        ], alignment=ft.MainAxisAlignment.CENTER,
           spacing=CONSTANTS.SPACE_XS),
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

    def _make_section(name, color, icon, param, body_controls):
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
                        ft.Icon(icon, color=color, size=CONSTANTS.ICON_SM),
                        ft.Text(name, color=color,
                               weight=ft.FontWeight.W_600,
                               size=CONSTANTS.TEXT_SM),
                    ], spacing=CONSTANTS.SPACE_SM),
                    on_click=_toggle_section(name), expand=True,
                    padding=ft.Padding(CONSTANTS.SPACE_XS, CONSTANTS.SPACE_SM,
                                      CONSTANTS.SPACE_XS, CONSTANTS.SPACE_SM),
                ),
                switch,
            ], alignment=ft.MainAxisAlignment.SPACE_BETWEEN),
            bgcolor=DARK, border_radius=6,
            padding=ft.Padding(CONSTANTS.SPACE_SM, 0, CONSTANTS.SPACE_SM, 0),
            border=ft.Border.all(1, color),
        )
        body = ft.Container(
            content=ft.Column(body_controls, spacing=CONSTANTS.SPACE_MD),
            visible=False,
            padding=ft.Padding(CONSTANTS.SPACE_LG, CONSTANTS.SPACE_MD,
                              CONSTANTS.SPACE_LG, CONSTANTS.SPACE_MD),
            bgcolor=BG, border_radius=6, border=ft.Border.all(1, color))
        sections[name] = {"body": body, "switch": switch}
        return ft.Column([header, body], spacing=CONSTANTS.SPACE_XS)

    def _slider_row(label, dct, key, minv, maxv, *, divisions=None):
        """Slider cranté par pas entiers par défaut (un pas = une unité
        affichée) plutôt que des valeurs flottantes continues (retour
        user) — passer `divisions` explicitement pour un pas plus fin.
        Double-clic : revient à 0 (ou au minimum si 0 est hors plage,
        ex. rayons de netteté qui commencent à 1). Auto-enregistré dans
        `reset_registry` pour le bouton Réinitialiser.

        Utilisable sans clavier ni souris : les boutons − / + permettent le
        pas à pas (au doigt, la main masque le curseur qu'elle déplace) et
        le ↺ s'active dès que la valeur s'écarte du défaut — le double-clic
        reste, mais il n'est plus le seul accès à la remise à zéro, ce qui
        le rendait introuvable sur écran tactile. Les trois boutons sont
        toujours présents (grisés plutôt que masqués) : une icône qui
        apparaît et disparaît ferait sauter la hauteur de la ligne, et donc
        tout le panneau, à chaque mouvement de curseur.

        `column.data` porte une fonction de rafraîchissement : elle relit
        `dct[key]` et remet curseur, libellé et icône ↺ d'accord entre eux.
        Utilisée par Réinitialiser, Charger des réglages et les préréglages
        de virage, qui écrivent dans les paramètres sans passer par l'UI.
        """
        value = dct[key]
        if divisions is None:
            divisions = round(maxv - minv)
        step = max(1, round((maxv - minv) / max(1, divisions)))
        reset_value = max(0, minv)
        text = ft.Text(f"{label} : {round(value)}", size=CONSTANTS.TEXT_SM,
                       color=WHITE)
        _touch = CONSTANTS.TOUCH_TARGET
        reset_btn = ft.IconButton(
            ft.Icons.RESTART_ALT, icon_size=CONSTANTS.ICON_SM,
            icon_color=BLUE, tooltip=f"Réinitialiser « {label} »",
            disabled=round(value) == reset_value,
            width=_touch, height=_touch)
        minus_btn = ft.IconButton(
            ft.Icons.REMOVE, icon_size=CONSTANTS.ICON_SM, icon_color=WHITE,
            tooltip=f"{label} − {step}", width=_touch, height=_touch)
        plus_btn = ft.IconButton(
            ft.Icons.ADD, icon_size=CONSTANTS.ICON_SM, icon_color=WHITE,
            tooltip=f"{label} + {step}", width=_touch, height=_touch)

        def _write(new_value, *, move_slider=True):
            """Point de passage unique : curseur, − / +, ↺ et chargement de
            réglages écrivent tous ici, donc l'affichage ne peut pas
            diverger de `dct[key]`."""
            snapped = max(minv, min(maxv, round(new_value)))
            dct[key] = snapped
            text.value = f"{label} : {snapped}"
            reset_btn.disabled = (snapped == reset_value)
            if move_slider:
                slider.value = snapped
                slider.update()
            text.update()
            reset_btn.update()

        def _handle(e):
            # Le curseur est déjà à la bonne position : le repousser
            # pendant le glissement le ferait sauter sous le doigt.
            _write(e.control.value, move_slider=False)
            live_preview_tick()

        slider = ft.Slider(min=minv, max=maxv, value=value, expand=True,
                          divisions=divisions, on_change=_handle,
                          active_color=BLUE)

        def _step(delta):
            def handler(e):
                _write(dct[key] + delta)
                live_preview_tick()
            return handler

        minus_btn.on_click = _step(-step)
        plus_btn.on_click = _step(step)

        def _reset(e):
            _write(reset_value)
            live_preview_tick()

        reset_btn.on_click = _reset
        slider_area = ft.GestureDetector(content=slider,
                                        on_double_tap=_reset, expand=True)

        def _refresh():
            """Resynchronise depuis dct[key] sans relancer l'aperçu :
            l'appelant groupe ses modifications puis déclenche un seul
            live_preview_tick()."""
            _write(dct[key])

        column = ft.Column([
            text,
            ft.Row([reset_btn, minus_btn, slider_area, plus_btn], spacing=0,
                  vertical_alignment=ft.CrossAxisAlignment.CENTER),
        ], spacing=0)
        column.data = _refresh
        reset_registry["sliders"].append((column, label, dct, key))
        return column

    # ── Débruiter ───────────────────────────────────────────────────
    dn = state["params"]["denoise"]
    section_denoise = _make_section(
        "Débruiter", RED, ft.Icons.BLUR_ON, dn, [
        _slider_row("Force luminance", dn, "h", 0, 25),
        _slider_row("Force couleur", dn, "h_color", 0, 25),
    ])

    # ── Réglages couleur ────────────────────────────────────────────
    co = state["params"]["couleur"]
    section_couleur = _make_section(
        "Réglages couleur", BLUE, ft.Icons.PALETTE, co, [
        _slider_row("Corriger la dominante (photos anciennes)",
                   co, "auto_cast", 0, 125),
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
        """Le préréglage a écrit dans `vi` : chaque ligne se resynchronise
        elle-même (curseur, libellé, état du ↺)."""
        virage_hue_row.data()
        virage_sat_row.data()
        virage_light_row.data()

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

    section_virage = _make_section(
        "Virage", YELLOW, ft.Icons.COLORIZE, vi, [
            virage_preset_dd, virage_mode_dd, virage_hue_row,
            virage_sat_row, virage_light_row,
        ])

    # ── LUT (Data/LUTs/*.cube) ──────────────────────────────────────
    lu = state["params"]["lut"]
    _cube_luts = image_ops.list_cube_luts()  # scan à la volée à l'ouverture

    def _on_lut_select(e):
        lu["name"] = lut_dd.value or ""
        live_preview_tick()

    lut_dd = ft.Dropdown(
        label="Fichier LUT", value=lu["name"] or None,
        options=[ft.dropdown.Option(name) for name in _cube_luts],
        bgcolor=DARK, border_color=GREY, color=WHITE,
        hint_text=("Aucun .cube dans Data/LUTs" if not _cube_luts
                  else None),
        on_select=_on_lut_select)
    lut_intensity_row = _slider_row("Intensité", lu, "intensity", 0, 100)

    section_lut = _make_section("LUT", VIOLET, ft.Icons.GRADIENT, lu, [
        lut_dd, lut_intensity_row,
    ])

    # ── Netteté ─────────────────────────────────────────────────────
    ne = state["params"]["nettete"]
    section_nettete = _make_section(
        "Netteté", GREEN, ft.Icons.DEBLUR, ne, [
        _slider_row("Rayon — passe 1", ne, "radius1", 1, 8),
        _slider_row("Intensité — passe 1 (%)", ne, "percent1", 0, 150),
        _slider_row("Rayon — passe 2", ne, "radius2", 1, 8),
        _slider_row("Intensité — passe 2 (%)", ne, "percent2", 0, 150),
    ])

    # ── Grain pellicule — remontées en sections de premier niveau (retour
    # user : à l'origine 6 apps séparées, un seul accordéon maître les
    # enterrait plutôt que de les rendre directement accessibles) ───────
    ga = state["params"]["grain"]

    def _num_field(sub, key, label):
        # expand=True dans une Row, pas dans la Column du corps de section
        # directement : un TextField ne s'étire pas tout seul comme un
        # Slider (retour user, champs Grain restés étroits).
        field = ft.TextField(
            label=label, value=str(sub[key]), bgcolor=DARK,
            border_color=GREY, color=WHITE, expand=True,
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
        return ft.Row([field])

    def _grain_section(label, color, icon, sub, field_specs):
        fields = [_num_field(sub, key, flabel) for key, flabel in field_specs]
        return _make_section(label, color, icon, sub, fields)

    section_ca = _grain_section(
        "Aberrations chromatiques", YELLOW, ft.Icons.BLUR_LINEAR, ga["ca"], [
            ("strength", "Intensité"), ("axial_ratio", "Ratio axial")])
    section_desat = _grain_section(
        "Désaturation des extrêmes", VIOLET, ft.Icons.CONTRAST, ga["desat"], [
            ("shadow_threshold", "Seuil ombres"),
            ("shadow_intensity", "Intensité ombres"),
            ("highlight_threshold", "Seuil HL"),
            ("highlight_intensity", "Intensité HL"),
            ("midtone_boost", "Boost mi-tons")])
    section_halation = _grain_section(
        "Halation", RED, ft.Icons.FLARE, ga["halation"], [
            ("threshold", "Seuil"), ("radius", "Rayon"),
            ("intensity", "Intensité"), ("red_shift", "Décalage rouge")])
    section_bloom = _grain_section(
        "Bloom (Soft Light)", BLUE, ft.Icons.WB_SUNNY, ga["bloom"], [
            ("radius", "Rayon"), ("intensity", "Intensité")])
    section_grain1 = _grain_section(
        "Grain — Couche 1", ORANGE, ft.Icons.GRAIN, ga["grain1"], [
            ("amount", "Intensité"), ("size", "Taille"),
            ("color_ratio", "Part couleur"),
            ("shadow_boost", "Concentration mi-tons"),
            ("chroma_shift", "Décalage inter-canal")])
    section_grain2 = _grain_section(
        "Grain — Couche 2", ORANGE, ft.Icons.GRAIN, ga["grain2"], [
            ("amount", "Intensité"), ("size", "Taille"),
            ("color_ratio", "Part couleur"),
            ("shadow_boost", "Concentration mi-tons"),
            ("chroma_shift", "Décalage inter-canal")])

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

    section_copyright = _make_section(
        "Copyright", WHITE, ft.Icons.COPYRIGHT, cp, [
            copyright_mode_dd, copyright_custom_field,
        ])

    # ── Batch final ─────────────────────────────────────────────────
    progress_bar = ft.ProgressBar(width=300, visible=False, color=BLUE)
    progress_text = ft.Text("", size=CONSTANTS.TEXT_SM, color=WHITE)

    # Armé par _stop_batch, testé en tête de boucle par batch_worker : le
    # lot tourne sur un thread daemon et la seule sortie était jusqu'ici de
    # quitter l'application (retour user).
    # ponytail: granularité = une image ; l'arrêt prend effet après l'image
    # en cours (quelques secondes sur un gros fichier + débruitage). Pour un
    # arrêt immédiat il faudrait rendre run_pipeline interruptible étape par
    # étape — inutile tant que le temps par image reste raisonnable.
    batch_stop = threading.Event()

    def _set_batch_running(running):
        """Le bouton du lot devient son propre bouton d'arrêt.

        Un seul contrôle, au même endroit, toujours à portée du pouce :
        rien de nouveau à chercher à l'écran une fois le lot lancé.
        """
        if running:
            batch_button.text = "Arrêter le traitement"
            batch_button.icon = ft.Icons.STOP
            batch_button.bgcolor = RED
            batch_button.on_click = _stop_batch
        else:
            batch_button.text = (
                f"Lancer le traitement complet ({len(file_names)} images)")
            batch_button.icon = ft.Icons.PLAY_ARROW
            batch_button.bgcolor = GREEN
            batch_button.on_click = _open_batch_dialog
        batch_button.disabled = False

    def _stop_batch(e):
        """Demande l'arrêt ; le bouton se désactive le temps que l'image en
        cours se termine, puis batch_worker rend la main."""
        batch_stop.set()
        batch_button.disabled = True
        progress_text.value = "Arrêt en cours…"
        page.update()

    def _update_progress(done, total):
        progress_bar.value = done / total
        progress_text.value = f"{done} / {total}"

    def batch_worker(params_snapshot):
        output_folder = folder_path / "RETOUCHE"
        output_folder.mkdir(exist_ok=True)
        # Réglages utilisés pour ce lot — rechargeables via "Charger des
        # réglages…" pour reprendre et ajuster un lot précédent.
        with open(folder_path / "retouche_params.json", "w",
                  encoding="utf-8") as f:
            json.dump(params_snapshot, f, indent=2, ensure_ascii=False)
        total = len(file_names)
        done = 0
        for i, name in enumerate(file_names):
            if batch_stop.is_set():
                break
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

            done = i + 1

            async def _tick(done=done, total=total):
                _update_progress(done, total)
                progress_bar.update()
                progress_text.update()
            page.run_task(_tick)

        stopped = batch_stop.is_set()
        if stopped:
            print(f"Traitement interrompu — {done} image(s) sur {total} "
                  f"traitées, conservées dans {output_folder}")
        else:
            print("Terminé !")
            print(f"NAVIGATE_TO:{output_folder}")

        async def _done(stopped=stopped, done=done, total=total):
            # Interruption : on reste dans l'app (les réglages sont encore
            # là, on peut relancer) ; fin normale : on ferme comme avant.
            if stopped:
                progress_text.value = (
                    f"Interrompu — {done} / {total} traitées, conservées "
                    f"dans RETOUCHE/.")
                _set_batch_running(False)
                page.update()
                return
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
        batch_stop.clear()
        _set_batch_running(True)
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
        height=CONSTANTS.TOUCH_TARGET,  # action principale : cible au doigt
        on_click=_open_batch_dialog)

    # « Enregistrer comme réglages par défaut » a été retiré : les
    # préréglages nommés couvrent cet usage sans réécrire CONSTANTS.py.

    # ── Resynchronisation de l'UI depuis state["params"] ────────────────
    def _sync_controls_from_params():
        """Reflète state["params"] (déjà à jour) sur tous les contrôles —
        partagé par Réinitialiser et Charger des réglages."""
        for switch, dct in reset_registry["switches"]:
            switch.value = dct["enabled"]
            switch.update()
        for column, label, dct, key in reset_registry["sliders"]:
            column.data()  # cf. _slider_row : rafraîchit depuis dct[key]
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

        lut_dd.value = lu["name"] or None
        lut_dd.update()

        copyright_mode_dd.value = {
            "date": "Date", "filename": "Nom de fichier",
            "custom": "Personnalisé"}[cp["mode"]]
        copyright_custom_field.value = cp["custom_text"]
        copyright_custom_field.visible = (cp["mode"] == "custom")
        copyright_mode_dd.update()
        copyright_custom_field.update()

        page.update()

    # ── Charger des réglages depuis un fichier retouche_params.json ────
    # (déposé par chaque lot, cf. batch_worker) — pour reprendre et
    # ajuster les réglages d'un lot précédent.
    load_params_status = ft.Text("", size=CONSTANTS.TEXT_SM, color=GREEN)

    async def _open_load_params_picker(e):
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
        icon=ft.Icons.FOLDER_OPEN_OUTLINED, on_click=_open_load_params_picker,
        style=ft.ButtonStyle(color=VIOLET, side=ft.BorderSide(1, VIOLET)))

    # ── Préréglages nommés ─────────────────────────────────────────────
    # Seule voie pour retrouver des réglages : un choix dans une liste, un
    # tap. Le retouche_params.json déposé par chaque lot a le même format,
    # donc reprendre les réglages d'un lot précédent = déposer son fichier
    # dans PRESETS_DIR.
    preset_status = ft.Text("", size=CONSTANTS.TEXT_SM, color=GREEN)

    def _preset_options():
        return [ft.dropdown.Option(n) for n in list_presets()]

    def _on_preset_select(e):
        name = preset_dd.value
        if not name:
            return
        try:
            _update_in_place(state["params"], load_preset(name))
        except Exception as exc:
            preset_status.value = f"Erreur : {exc}"
            preset_status.color = RED
            preset_status.update()
            return
        _sync_controls_from_params()
        preset_status.value = f"Préréglage « {name} » appliqué."
        preset_status.color = GREEN
        preset_status.update()
        live_preview_tick()

    preset_dd = ft.Dropdown(
        label="Préréglage", options=_preset_options(), expand=True,
        hint_text=("Aucun préréglage enregistré" if not list_presets()
                  else None),
        bgcolor=DARK, border_color=VIOLET, color=WHITE,
        on_select=_on_preset_select)

    preset_name_field = ft.TextField(
        label="Nom du préréglage", autofocus=True,
        bgcolor=DARK, border_color=VIOLET, color=WHITE,
        text_size=CONSTANTS.TEXT_SM)

    def _confirm_save_preset(e):
        try:
            saved = save_preset(preset_name_field.value, state["params"])
        except Exception as exc:
            preset_status.value = f"Erreur : {exc}"
            preset_status.color = RED
            preset_save_dlg.open = False
            page.update()
            return
        preset_save_dlg.open = False
        preset_dd.options = _preset_options()
        preset_dd.value = saved
        preset_status.value = f"Préréglage « {saved} » enregistré."
        preset_status.color = GREEN
        page.update()

    def _cancel_save_preset(e):
        preset_save_dlg.open = False
        page.update()

    preset_save_dlg = ft.AlertDialog(
        title=ft.Text("Enregistrer les réglages actuels",
                     size=CONSTANTS.TEXT_SM, color=WHITE),
        content=preset_name_field,
        actions=[ft.TextButton("Annuler", on_click=_cancel_save_preset),
                ft.TextButton("Enregistrer", on_click=_confirm_save_preset)],
    )

    def _open_save_preset_dialog(e):
        # Prérempli avec la sélection courante : réenregistrer un
        # préréglage après retouche est le cas le plus fréquent, et ça
        # évite de retaper un nom au clavier.
        preset_name_field.value = preset_dd.value or ""
        if preset_save_dlg not in page.overlay:
            page.overlay.append(preset_save_dlg)
        preset_save_dlg.open = True
        page.update()

    # ponytail: nommer un préréglage demande un clavier. Sur une borne
    # tactile sans clavier, la LECTURE de la liste suffit — c'est
    # l'opération quotidienne ; la création se fait au poste équipé.
    preset_row = ft.Row([
        preset_dd,
        ft.IconButton(ft.Icons.SAVE_OUTLINED, icon_color=VIOLET,
                     icon_size=CONSTANTS.ICON_SM,
                     tooltip="Enregistrer les réglages actuels comme "
                             "préréglage",
                     width=CONSTANTS.TOUCH_TARGET,
                     height=CONSTANTS.TOUCH_TARGET,
                     on_click=_open_save_preset_dialog),
    ], spacing=CONSTANTS.SPACE_MD,
       vertical_alignment=ft.CrossAxisAlignment.CENTER)

    # ── Mise en page ────────────────────────────────────────────────
    # Zone délimitée (fond sombre + bordure), comme le panneau gauche
    # d'Augmentation IA.pyw (retour user : l'ancien fond plat ne
    # distinguait pas cette colonne du reste de la fenêtre). Les réglages
    # défilent seuls (sous-Column scrollable) ; le bouton de lancement
    # reste fixe en bas de la colonne, toujours visible sans défiler.
    controls_container = ft.Container(
        content=ft.Column(
            [
                ft.Column(
                    [section_denoise, section_couleur, section_virage,
                     section_lut, section_nettete,
                     section_ca, section_desat, section_halation,
                     section_bloom, section_grain1, section_grain2,
                     section_copyright,
                     ft.Divider(color=GREY),
                     preset_row, preset_status,
                     ft.Divider(color=GREY),
                     load_params_button, load_params_status],
                    spacing=CONSTANTS.SPACE_SM, scroll=ft.ScrollMode.AUTO,
                    expand=True),
                ft.Divider(color=GREY),
                ft.Row([progress_bar, progress_text],
                      spacing=CONSTANTS.SPACE_MD),
                batch_button,
            ], spacing=CONSTANTS.SPACE_MD, expand=True),
        padding=CONSTANTS.SPACE_MD, bgcolor=DARK, border=ft.Border.all(1, GREY),
        border_radius=10)

    page.add(
        ft.Row([
            controls_container,
            ft.Column(
                [preview_column],
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
