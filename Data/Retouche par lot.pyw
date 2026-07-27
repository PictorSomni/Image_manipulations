# -*- coding: utf-8 -*-
"""
Retouche par lot.pyw — aperçu live sur une image représentative, puis
application de la même pipeline (débruitage, réglages couleur, virage,
netteté, grain pellicule, copyright) en pleine résolution sur tout le
dossier/sélection.

Chaque étape est indépendamment activable et partage sa logique avec les
scripts autonomes du même nom (Débruiter.py, Virage.py, Grain pellicule.py,
Copyright.py, Améliorer netteté.py) via `image_ops.py` — mêmes fonctions,
mêmes réglages, aperçu et export identiques à la résolution près.

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
import os
import sys
import threading
import time
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import CONSTANTS
import image_ops
import flet as ft
from PIL import Image

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
    preset_name = CONSTANTS.VIRAGE_DEFAULT_PRESET
    preset = CONSTANTS.VIRAGE_PRESETS[preset_name]
    return {
        "enabled": False,
        "preset": preset_name,
        "mode": preset["mode"],
        "hue": preset["hue"],
        "sat": preset["sat"],
        "light": preset.get("light", 50),
    }


def default_params():
    """Nouvelle copie des réglages par défaut (jamais partagée entre deux
    exécutions — chaque appelant doit avoir son propre dict mutable)."""
    C = CONSTANTS
    return {
        "denoise": {
            "enabled": False,
            "h": C.DENOISE_H, "h_color": C.DENOISE_H_COLOR,
            "template_window": C.DENOISE_TEMPLATE_WINDOW,
            "search_window": C.DENOISE_SEARCH_WINDOW,
        },
        "couleur": {
            "enabled": False,
            "exposure": 0, "contrast": 0, "saturation": 0, "hue": 0,
            "white_balance": 0, "shadows": 0, "highlights": 0,
            "whites": 0, "blacks": 0,
        },
        "virage": _default_virage(),
        "nettete": {
            "enabled": True,
            "radius1": 4, "percent1": 42, "radius2": 2, "percent2": 42,
        },
        "grain": {
            "enabled": False,
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
            "curve": {"enabled": C.CURVE_ENABLED,
                     "shoulder_start": C.CURVE_SHOULDER_START,
                     "shoulder_strength": C.CURVE_SHOULDER_STRENGTH,
                     "toe_start": C.CURVE_TOE_START,
                     "toe_lift": C.CURVE_TOE_LIFT},
            "grain1": {"enabled": True, "amount": C.GRAIN_AMOUNT,
                      "size": C.GRAIN_SIZE, "color_ratio": C.GRAIN_COLOR_RATIO,
                      "shadow_boost": C.GRAIN_SHADOW_BOOST,
                      "floor": C.GRAIN_FLOOR,
                      "chroma_shift": C.GRAIN_CHROMA_SHIFT},
            "grain2": {"enabled": True, "amount": C.GRAIN2_AMOUNT,
                      "size": C.GRAIN2_SIZE,
                      "color_ratio": C.GRAIN2_COLOR_RATIO,
                      "shadow_boost": C.GRAIN2_SHADOW_BOOST,
                      "floor": C.GRAIN2_FLOOR,
                      "chroma_shift": C.GRAIN2_CHROMA_SHIFT},
        },
        "copyright": {"enabled": False, "mode": "date", "custom_text": ""},
    }


#############################################################
#              PIPELINE PURE (aperçu + batch)                #
#############################################################
def run_pipeline(image, params, *, date_label=None, filename_stem=""):
    """Applique les étapes activées, dans l'ordre : débruiter → couleur →
    virage → netteté → grain pellicule → copyright. Pure PIL/image_ops,
    aucun appel Flet — appelée identique sur le proxy réduit (aperçu) et
    sur le plein format (batch). Part toujours d'une copie : ne mute
    jamais `image` (qui peut être un proxy mis en cache entre deux
    appels)."""
    result = image.copy()

    d = params["denoise"]
    if d["enabled"]:
        result = image_ops.apply_denoise(
            result, h=d["h"], h_color=d["h_color"],
            template_window=d["template_window"],
            search_window=d["search_window"])

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
        if v["mode"] == "multiply":
            result = image_ops.colorize_multiply(
                result, v["hue"], v["sat"], v["light"])
        else:
            result = image_ops.colorize_hsl(result, v["hue"], v["sat"])

    n = params["nettete"]
    if n["enabled"]:
        result = image_ops.apply_sharpen(
            result, radius1=n["radius1"], percent1=n["percent1"],
            radius2=n["radius2"], percent2=n["percent2"])

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
        if g["curve"]["enabled"]:
            a = g["curve"]
            result = image_ops.add_filmic_curve(
                result, a["shoulder_start"], a["shoulder_strength"],
                a["toe_start"], a["toe_lift"])
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
#                           MAIN                             #
#############################################################
def main(page: ft.Page):
    page.title = "Retouche par lot"
    page.theme_mode = ft.ThemeMode.DARK
    page.window.maximized = True
    page.bgcolor = BG
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

    # ── Aperçu ────────────────────────────────────────────────────────
    # Pan/zoom natif Flet (même widget que le viewer plein écran de
    # Hub.pyw) : ft.InteractiveViewer a besoin d'un width/height explicite
    # (pas `expand`), sinon `constrained=True` le dimensionne sur le
    # rectangle CONTAIN de l'image au lieu du viewport voulu, et zoomer
    # agrandit l'image dans ce rectangle fixe au lieu du cadre disponible.
    _PREVIEW_W, _PREVIEW_H = 760, 560
    image_display = ft.Image(src=_BLANK_SRC, gapless_playback=True,
                             fit=ft.BoxFit.CONTAIN,
                             width=_PREVIEW_W, height=_PREVIEW_H)
    preview_viewer = ft.InteractiveViewer(
        content=image_display, min_scale=1.0, max_scale=6.0,
        pan_enabled=True, scale_enabled=True, constrained=True,
        width=_PREVIEW_W, height=_PREVIEW_H,
        clip_behavior=ft.ClipBehavior.HARD_EDGE)
    counter_text = ft.Text("", size=CONSTANTS.TEXT_SM, color=WHITE)

    def _live_preview_loop():
        while True:
            with state["live_lock"]:
                request_seen = state["live_req"]
            proxy = state["proxy"]
            params_copy = copy.deepcopy(state["params"])
            date_label = state["date_label"]
            stem = Path(file_names[state["index"]]).stem
            try:
                result = run_pipeline(proxy, params_copy,
                                      date_label=date_label,
                                      filename_stem=stem)
                buf = io.BytesIO()
                result.save(buf, format="JPEG", quality=70)
                src = ("data:image/jpeg;base64,"
                      + base64.b64encode(buf.getvalue()).decode())
            except Exception:
                src = None

            if src:
                async def _apply(src=src):
                    image_display.src = src
                    image_display.update()
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
        ratio = min(CONSTANTS.PREVIEW_MAX_PIXELS / img.width,
                   CONSTANTS.PREVIEW_MAX_PIXELS / img.height, 1.0)
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

    preview_column = ft.Column([
        ft.Container(content=preview_viewer,
                    width=_PREVIEW_W + 16, height=_PREVIEW_H + 16,
                    bgcolor=DARK, border_radius=8, padding=8,
                    alignment=ft.Alignment.CENTER),
        ft.Row([
            ft.IconButton(ft.Icons.CHEVRON_LEFT, on_click=_prev,
                         icon_color=WHITE),
            counter_text,
            ft.IconButton(ft.Icons.CHEVRON_RIGHT, on_click=_next,
                         icon_color=WHITE),
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

    def _slider_row(label, value, minv, maxv, on_change, *, divisions=None):
        """Slider cranté par pas entiers par défaut (un pas = une unité
        affichée) plutôt que des valeurs flottantes continues (retour
        user) — passer `divisions` explicitement pour un pas plus fin.
        Double-clic : revient à 0 (ou au minimum si 0 est hors plage,
        ex. rayons de netteté qui commencent à 1)."""
        if divisions is None:
            divisions = round(maxv - minv)
        reset_value = max(0, minv)
        text = ft.Text(f"{label} : {round(value)}", size=CONSTANTS.TEXT_SM,
                       color=WHITE)

        def _handle(e):
            snapped = round(e.control.value)
            text.value = f"{label} : {snapped}"
            on_change(snapped)
            text.update()
            live_preview_tick()
        slider = ft.Slider(min=minv, max=maxv, value=value,
                          divisions=divisions, on_change=_handle,
                          active_color=BLUE)

        def _reset(e):
            slider.value = reset_value
            on_change(reset_value)
            text.value = f"{label} : {round(reset_value)}"
            slider.update()
            text.update()
            live_preview_tick()
        slider_area = ft.GestureDetector(content=slider,
                                        on_double_tap=_reset)
        column = ft.Column([text, slider_area], spacing=0)
        column.data = slider
        return column

    # ── Débruiter ───────────────────────────────────────────────────
    dn = state["params"]["denoise"]
    section_denoise = _make_section("Débruiter", RED, dn, [
        _slider_row("Force luminance", dn["h"], 0, 25,
                   lambda v: dn.__setitem__("h", v)),
        _slider_row("Force couleur", dn["h_color"], 0, 25,
                   lambda v: dn.__setitem__("h_color", v)),
    ])

    # ── Réglages couleur ────────────────────────────────────────────
    co = state["params"]["couleur"]
    section_couleur = _make_section("Réglages couleur", BLUE, co, [
        _slider_row("Exposition", co["exposure"], -100, 100,
                   lambda v: co.__setitem__("exposure", v)),
        _slider_row("Contraste", co["contrast"], -100, 100,
                   lambda v: co.__setitem__("contrast", v)),
        _slider_row("Saturation", co["saturation"], -100, 100,
                   lambda v: co.__setitem__("saturation", v)),
        _slider_row("Teinte", co["hue"], -100, 100,
                   lambda v: co.__setitem__("hue", v)),
        _slider_row("Balance des blancs", co["white_balance"], -100, 100,
                   lambda v: co.__setitem__("white_balance", v)),
        _slider_row("Hautes lumières", co["highlights"], -100, 100,
                   lambda v: co.__setitem__("highlights", v)),
        _slider_row("Ombres", co["shadows"], -100, 100,
                   lambda v: co.__setitem__("shadows", v)),
        _slider_row("Blancs", co["whites"], -100, 100,
                   lambda v: co.__setitem__("whites", v)),
        _slider_row("Noirs", co["blacks"], -100, 100,
                   lambda v: co.__setitem__("blacks", v)),
    ])

    # ── Virage ──────────────────────────────────────────────────────
    vi = state["params"]["virage"]
    virage_hue_row = _slider_row("Teinte", vi["hue"], 0, 360,
                                 lambda v: vi.__setitem__("hue", v))
    virage_sat_row = _slider_row("Saturation", vi["sat"], 0, 100,
                                 lambda v: vi.__setitem__("sat", v))
    virage_light_row = _slider_row("Luminosité", vi["light"], 0, 100,
                                   lambda v: vi.__setitem__("light", v))

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
        _slider_row("Rayon — passe 1", ne["radius1"], 1, 8,
                   lambda v: ne.__setitem__("radius1", v)),
        _slider_row("Intensité — passe 1 (%)", ne["percent1"], 0, 150,
                   lambda v: ne.__setitem__("percent1", v)),
        _slider_row("Rayon — passe 2", ne["radius2"], 1, 8,
                   lambda v: ne.__setitem__("radius2", v)),
        _slider_row("Intensité — passe 2 (%)", ne["percent2"], 0, 150,
                   lambda v: ne.__setitem__("percent2", v)),
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
        return field

    def _grain_tile(label, color, sub, field_specs):
        sw = ft.Switch(value=sub["enabled"], active_color=color)

        def _on_sw(e):
            sub["enabled"] = sw.value
            live_preview_tick()
        sw.on_change = _on_sw
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
        _grain_tile("Courbe tonale", GREEN, ga["curve"], [
            ("shoulder_start", "Seuil épaulement"),
            ("shoulder_strength", "Force épaulement"),
            ("toe_start", "Seuil pied"),
            ("toe_lift", "Relèvement pied")]),
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
        icon=ft.Icons.PLAY_ARROW, on_click=_open_batch_dialog)

    # ── Mise en page ────────────────────────────────────────────────
    page.add(
        ft.Row([
            ft.Column([preview_column], expand=1,
                     alignment=ft.MainAxisAlignment.CENTER,
                     horizontal_alignment=ft.CrossAxisAlignment.CENTER),
            ft.Container(
                content=ft.Column(
                    [section_denoise, section_couleur, section_virage,
                     section_nettete, section_grain, section_copyright,
                     ft.Divider(color=GREY),
                     ft.Row([progress_bar, progress_text], spacing=12),
                     batch_button],
                    spacing=6, scroll=ft.ScrollMode.AUTO, expand=True),
                expand=1, padding=12, bgcolor=BG),
        ], expand=True, vertical_alignment=ft.CrossAxisAlignment.STRETCH)
    )

    load_representative(0)


if __name__ == "__main__":
    ft.run(main)
