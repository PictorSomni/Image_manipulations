# -*- coding: utf-8 -*-
"""
Application kiosque de sélection d'impressions photo — Version Flet.

Remplace la version Qt6 originale (main.py) avec :
  - Interface plein écran Flet, palette de couleurs de Dashboard.pyw.
  - Grille d'images avec sélection de format et compteur d'impressions par photo.
  - Prévisualisation N&B par image (toggle par bouton).
  - Calcul du prix total en temps réel.
  - Validation copie des fichiers sélectionnés dans un dossier SELECTION (SELECTION_2, … si déjà existant).

Dépendances : flet, Pillow (PIL)
"""

__version__ = "3.1.0"

import flet as ft
import os
import sys
import io
import json
import base64
import threading
import shutil
import thumb_cache

# ── Import des constantes spécifiques au kiosk ───────────────────────────────
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import CONSTANTS as KIOSK_CONSTANT

try:
    from PIL import Image as PILImage, ImageOps
    import image_ops
    HAS_PIL = True
except ImportError:
    PILImage = None  # type: ignore[assignment]
    ImageOps = None  # type: ignore[assignment]
    image_ops = None  # type: ignore[assignment]
    HAS_PIL = False

# ── Extensions acceptées ──────────────────────────────────────────────────────
KIOSK_EXTENSION = KIOSK_CONSTANT.EXTENSION

# ── Taille des miniatures ────────────────────────────────────────────────────
THUMBNAIL_SIZE = KIOSK_CONSTANT.THUMBNAIL_SIZE


# ─────────────────────────────────────────────────────────────────────────────
#  Utilitaire image
# ─────────────────────────────────────────────────────────────────────────────

# ─────────────────────────────────────────────────────────────────────────────
#  Point d'entrée Flet
# ─────────────────────────────────────────────────────────────────────────────
def main(page: ft.Page) -> None:

    # ── Couleurs (issues de Kiosk/CONSTANT.py) ─────────────────────────────
    C_DARK       = KIOSK_CONSTANT.COLOR_DARK
    C_BG         = KIOSK_CONSTANT.COLOR_BACKGROUND
    C_GREY       = KIOSK_CONSTANT.COLOR_GREY
    C_LIGHT_GREY = KIOSK_CONSTANT.COLOR_LIGHT_GREY
    C_BLUE       = KIOSK_CONSTANT.COLOR_BLUE
    C_VIOLET     = KIOSK_CONSTANT.COLOR_VIOLET
    C_GREEN      = KIOSK_CONSTANT.COLOR_GREEN
    C_RED        = KIOSK_CONSTANT.COLOR_RED
    C_WHITE      = KIOSK_CONSTANT.COLOR_WHITE
    C_YELLOW     = KIOSK_CONSTANT.COLOR_YELLOW

    def _border_all(width: int | float, color: str) -> ft.Border:
        """Compatibilité Flet: remplace border.all indisponible sur certaines versions."""
        side = ft.BorderSide(width, color)
        return ft.Border(top=side, right=side, bottom=side, left=side)

    def _cleanup_temp_dir() -> None:
        """Hook de nettoyage conservé pour compatibilité (ancien flux kiosque)."""
        return

    # ── Configuration de la fenêtre ───────────────────────────────────────
    page.title = "Kiosk Photo"
    page.theme_mode = ft.ThemeMode.DARK
    page.bgcolor = C_BG
    page.window.title_bar_hidden = True
    page.window.title_bar_buttons_hidden = True
    page.padding = 0
    page.update()

    async def _maximize_window() -> None:
        page.window.maximized = True
        page.update()

    page.run_task(_maximize_window)
    page.run_task(page.window.to_front)

    # ── Verrouillage kiosque (HUB_SPEC §9) ────────────────────────────────
    # Sélection curatée : Hub passe `SELECTED_FILES` (basenames séparés par
    # "|", même convention que les autres outils lancés depuis Hub, cf.
    # `_launch_tool`) avant de lancer le kiosque ; sans cette variable,
    # repli sur `os.listdir` (lancement direct hors Hub / développement).
    def _load_selection_manifest() -> list[str] | None:
        raw = os.environ.get("SELECTED_FILES", "")
        if not raw:
            return None
        return [name for name in raw.split("|") if name]

    KIOSK_LOCKED = bool(os.environ.get("SELECTED_FILES"))

    # ── Tarifs et paramètres grille depuis Kiosk/CONSTANT.py ─────────────────
    STUDIOS_TARIFF: dict[str, float]      = KIOSK_CONSTANT.STUDIOS
    PRINTS_TARIFF:  dict[str, list]       = KIOSK_CONSTANT.PRINTS
    active_tariff = {"value": os.environ.get("TARIFF_TYPE", "STUDIOS")}

    def _active_sizes() -> dict:
        return STUDIOS_TARIFF if active_tariff["value"] == "STUDIOS" else PRINTS_TARIFF

    def _get_unit_price(format_name: str, total_count: int) -> float:
        """Prix unitaire selon le tarif actif ; PRINTS utilise des tranches dégressives."""
        if active_tariff["value"] == "STUDIOS":
            return STUDIOS_TARIFF.get(format_name, 0.0)
        tiers = PRINTS_TARIFF.get(format_name)
        if tiers is None:
            return 0.0
        if total_count <= 10:  return tiers[0]
        if total_count <= 50:  return tiers[1]
        if total_count <= 100: return tiers[2]
        if total_count <= 200: return tiers[3]
        return tiers[4]

    # ── État global ───────────────────────────────────────────────────────
    current_folder = {"path": ""}
    images_list: list[str] = []
    # prints_data[format][filename] = nombre de copies
    prints_data: dict[str, dict[str, int]] = {}
    current_size = {"value": list(_active_sizes().keys())[0]}
    total_price = {"value": 0.0}
    nb_state: dict[tuple, bool] = {}        # (format_name, filename) → True = N&B actif pour ce format
    image_cards: dict[str, dict] = {}       # {filename: {card, count_text, image_ctrl, nb_button}}
    # filename -> chemin d'une copie recadrée (dossier _RECADRES), utilisée
    # à la place de l'original par validate_order si présente.
    crop_overrides: dict[str, str] = {}

    KIOSK_PAGE_SIZE  = 60               # nombre de cartes affichées par page
    kiosk_page       = {"value": 0}     # page courante (0-indexé)
    kiosk_page_token = {"value": 0}     # jeton d'annulation des threads miniatures

    # ─────────────────────────────────────────────────────────────────────
    #  Helpers d'état
    # ─────────────────────────────────────────────────────────────────────

    FRAIS_AMORCE = KIOSK_CONSTANT.ORDER_SETUP_FEE  # partagé avec Hub.pyw

    def _recalculate_total() -> None:
        total = 0.0
        has_prints = False
        for format_name in _active_sizes():
            counts = prints_data.get(format_name, {})
            total_count = sum(counts.values())
            if total_count == 0:
                continue
            has_prints = True
            total += total_count * _get_unit_price(format_name, total_count)
        if active_tariff["value"] == "PRINTS" and has_prints:
            total += FRAIS_AMORCE
        total_price["value"] = round(total, 2)
        price_text.value = f"{total_price['value']:.2f} €"
        price_text.update()

    def _apply_card_style(card_data: dict, count: int) -> None:
        """Met en évidence (vert) ou remet à l'état neutre une carte selon le nombre de copies."""
        card_data["count_text"].value = str(count)
        card_data["count_text"].color = C_GREEN if count > 0 else C_LIGHT_GREY
        card_data["count_text"].update()
        card_data["card"].border = _border_all(2, C_GREEN if count > 0 else C_GREY)
        card_data["card"].update()

    def _update_size_buttons() -> None:
        for format_name, button in size_buttons_map.items():
            is_selected = (format_name == current_size["value"])
            button.color = C_DARK if is_selected else C_BLUE
            button.bgcolor = C_BLUE if is_selected else C_GREY
            if button.page:
                button.update()

    def _refresh_counts_for_current_size() -> None:
        """Recharge les compteurs affichés après un changement de format sélectionné."""
        format_name = current_size["value"]
        for filename, card_data in image_cards.items():
            count = prints_data.get(format_name, {}).get(filename, 0)
            _apply_card_style(card_data, count)
            is_nb = nb_state.get((format_name, filename), False)
            card_data["nb_button"].icon_color = C_VIOLET if is_nb else C_LIGHT_GREY
            card_data["nb_button"].update()

    # ─────────────────────────────────────────────────────────────────────
    #  Gestionnaires d'événements
    # ─────────────────────────────────────────────────────────────────────

    def on_size_select(format_name: str) -> None:
        current_size["value"] = format_name
        _update_size_buttons()
        _refresh_counts_for_current_size()

    def on_change_count(filename: str, delta: int) -> None:
        format_name = current_size["value"]
        old_count = prints_data[format_name].get(filename, 0)
        new_count = max(0, old_count + delta)
        prints_data[format_name][filename] = new_count
        _recalculate_total()
        _apply_card_style(image_cards[filename], new_count)

    def on_toggle_nb(filename: str) -> None:
        key = (current_size["value"], filename)
        nb_state[key] = not nb_state.get(key, False)
        is_nb = nb_state[key]
        card_data = image_cards[filename]

        # Feedback immédiat sur l'icône
        card_data["nb_button"].icon_color = C_VIOLET if is_nb else C_LIGHT_GREY
        card_data["nb_button"].update()

        file_path = os.path.join(current_folder["path"], filename)
        stem = os.path.splitext(filename)[0]

        def _reload_thumbnail():
            b64 = thumb_cache.get_or_generate(file_path, grayscale=is_nb)
            card_data["image_ctrl"].src = b64 if b64 else b""

            async def _apply():
                try:
                    page.update()
                except Exception:
                    pass

            page.run_task(_apply)

        threading.Thread(target=_reload_thumbnail, daemon=True).start()

    # ── Recadrage client (HUB_SPEC §9 : le kiosque doit permettre de
    #  recadrer, contrairement à l'ancienne version) ─────────────────────
    _crop_dlg_state = {"path": None, "filename": None, "image": None,
                       "original_width": 0, "original_height": 0,
                       "scale": 1.0, "offset_x": 0.0, "offset_y": 0.0,
                       "canvas_w": 700.0, "canvas_h": 700.0, "base_scale": 1.0}

    def _open_crop_dialog(filename: str) -> None:
        if not HAS_PIL:
            return
        fmt = current_size["value"]
        if fmt not in KIOSK_CONSTANT.FORMATS:
            page.show_dialog(ft.SnackBar(
                ft.Text("Recadrage indisponible pour ce format.", color=C_WHITE),
                bgcolor=C_GREY, duration=3000,
                behavior=ft.SnackBarBehavior.FLOATING))
            return
        source_path = os.path.join(current_folder["path"], filename)
        try:
            with PILImage.open(source_path) as im:
                im = ImageOps.exif_transpose(im).convert("RGB")
                _crop_dlg_state["image"] = im.copy()
        except Exception:
            return
        w, h = _crop_dlg_state["image"].size
        _crop_dlg_state.update({
            "path": source_path, "filename": filename,
            "original_width": w, "original_height": h,
            "scale": 1.0, "offset_x": 0.0, "offset_y": 0.0,
            "base_scale": max(_crop_dlg_state["canvas_w"] / w,
                              _crop_dlg_state["canvas_h"] / h),
        })
        _crop_dlg_render()
        crop_client_dialog.open = True
        if crop_client_dialog not in page.overlay:
            page.overlay.append(crop_client_dialog)
        page.update()

    def _crop_dlg_view():
        s = _crop_dlg_state
        return image_ops.CropView(
            canvas_w=s["canvas_w"], canvas_h=s["canvas_h"],
            base_scale=s["base_scale"], offset_x=s["offset_x"],
            offset_y=s["offset_y"], scale=s["scale"], rotation=0.0,
            original_width=s["original_width"],
            original_height=s["original_height"],
            display_w=s["original_width"] * s["base_scale"],
            display_h=s["original_height"] * s["base_scale"],
        )

    def _crop_dlg_render() -> None:
        img = _crop_dlg_state["image"]
        if img is None:
            return
        clamped = image_ops.clamp_offsets(_crop_dlg_view(), is_fit_in=False)
        _crop_dlg_state["scale"] = clamped.scale
        _crop_dlg_state["offset_x"] = clamped.offset_x
        _crop_dlg_state["offset_y"] = clamped.offset_y
        fmt_w, fmt_h = KIOSK_CONSTANT.FORMATS[current_size["value"]]
        result = image_ops.compute_crop_for_format(
            img, fmt_w, fmt_h, True, clamped, dpi=96)
        buf = io.BytesIO()
        result.save(buf, "JPEG", quality=85)
        crop_client_image.src = buf.getvalue()
        page.update()

    def _crop_dlg_nudge(dx, dy):
        def _on_click(e):
            step = _crop_dlg_state["canvas_w"] * 0.06
            _crop_dlg_state["offset_x"] += dx * step
            _crop_dlg_state["offset_y"] += dy * step
            _crop_dlg_render()
        return _on_click

    def _crop_dlg_zoom_end(e) -> None:
        _crop_dlg_state["scale"] = max(1.0, e.control.value)
        _crop_dlg_render()

    def _crop_dlg_cancel(e=None) -> None:
        crop_client_dialog.open = False
        page.update()

    def _crop_dlg_validate(e=None) -> None:
        img = _crop_dlg_state["image"]
        if img is None:
            return
        clamped = image_ops.clamp_offsets(_crop_dlg_view(), is_fit_in=False)
        fmt_w, fmt_h = KIOSK_CONSTANT.FORMATS[current_size["value"]]
        result = image_ops.compute_crop_for_format(
            img, fmt_w, fmt_h, True, clamped, dpi=KIOSK_CONSTANT.DPI)
        folder = os.path.join(current_folder["path"], "_RECADRES")
        try:
            os.makedirs(folder, exist_ok=True)
            stem = os.path.splitext(_crop_dlg_state["filename"])[0]
            dest = os.path.join(folder, f"{stem}_recadre.jpg")
            result.save(dest, "JPEG", quality=100,
                        dpi=(KIOSK_CONSTANT.DPI, KIOSK_CONSTANT.DPI))
        except Exception:
            crop_client_dialog.open = False
            page.update()
            return
        crop_overrides[_crop_dlg_state["filename"]] = dest
        crop_client_dialog.open = False
        page.update()

    crop_client_image = ft.Image(
        src="data:image/gif;base64,R0lGODlhAQABAAD/ACwAAAAAAQABAAACADs=",
        fit=ft.BoxFit.CONTAIN, expand=True)
    crop_client_dialog = ft.AlertDialog(
        modal=True,
        title=ft.Text("Recadrer"),
        content=ft.Container(
            width=460, height=560,
            content=ft.Column([
                ft.Container(content=crop_client_image, height=380,
                            bgcolor=C_DARK, alignment=ft.Alignment(0, 0)),
                ft.Text("Zoom", size=12, color=C_LIGHT_GREY),
                ft.Slider(min=1, max=3, value=1, on_change_end=_crop_dlg_zoom_end),
                ft.Row([
                    ft.IconButton(ft.Icons.ARROW_UPWARD, icon_color=C_WHITE,
                                 on_click=_crop_dlg_nudge(0, -1)),
                    ft.IconButton(ft.Icons.ARROW_DOWNWARD, icon_color=C_WHITE,
                                 on_click=_crop_dlg_nudge(0, 1)),
                    ft.IconButton(ft.Icons.ARROW_BACK, icon_color=C_WHITE,
                                 on_click=_crop_dlg_nudge(-1, 0)),
                    ft.IconButton(ft.Icons.ARROW_FORWARD, icon_color=C_WHITE,
                                 on_click=_crop_dlg_nudge(1, 0)),
                ], spacing=2, tight=True, alignment=ft.MainAxisAlignment.CENTER),
            ], spacing=8, tight=True),
        ),
        actions=[
            ft.TextButton("Annuler", on_click=_crop_dlg_cancel),
            ft.ElevatedButton("Valider", icon=ft.Icons.CHECK,
                              on_click=_crop_dlg_validate),
        ],
    )

    def on_show_preview(filename: str) -> None:
        """Affiche la prévisualisation plein écran avec PageView pour swiper entre les images."""
        _blank_gif = "data:image/gif;base64,R0lGODlhAQABAAD/ACwAAAAAAQABAAACADs="

        initial_index = images_list.index(filename) if filename in images_list else 0
        state = {"index": initial_index}
        _prev_keyboard_handler = page.on_keyboard_event

        def _current_filename() -> str:
            return images_list[state["index"]] if images_list else ""

        def close_preview(e) -> None:
            page.on_keyboard_event = _prev_keyboard_handler
            if preview_overlay in page.overlay:
                page.overlay.remove(preview_overlay)
            page.update()

        # ── Contrôles partagés barre titre / barre inférieure ────────────────
        preview_title = ft.Text(
            filename,
            size=15,
            color=C_WHITE,
            weight=ft.FontWeight.W_500,
            max_lines=1,
            overflow=ft.TextOverflow.ELLIPSIS,
        )
        preview_count_text = ft.Text(
            str(prints_data[current_size["value"]].get(filename, 0)),
            size=26,
            color=C_WHITE,
            weight=ft.FontWeight.BOLD,
            width=56,
            text_align=ft.TextAlign.CENTER,
        )
        nb_preview_button = ft.IconButton(
            icon=ft.Icons.INVERT_COLORS,
            icon_color=C_VIOLET if nb_state.get((current_size["value"], filename), False) else C_LIGHT_GREY,
            icon_size=30,
            tooltip="Basculer N&B",
        )

        # ── Contrôles image par index (chargement lazy) ──────────────────────
        page_image_controls: dict[int, ft.Image] = {}
        pages_loaded: set[int] = set()

        def _build_page_containers() -> list[ft.Container]:
            containers = []
            for page_index in range(len(images_list)):
                img_ctrl = ft.Image(
                    src=b"",
                    fit=ft.BoxFit.CONTAIN,
                    expand=True,
                    gapless_playback=True,
                    error_content=ft.Container(
                        content=ft.Icon(ft.Icons.IMAGE_OUTLINED, color=C_GREY, size=64),
                        alignment=ft.Alignment(0, 0),
                    ),
                )
                page_image_controls[page_index] = img_ctrl
                containers.append(
                    ft.Container(
                        content=img_ctrl,
                        expand=True,
                        alignment=ft.Alignment(0, 0),
                        bgcolor=C_DARK,
                    )
                )
            return containers

        def _load_image_for_index(load_index: int) -> None:
            if load_index < 0 or load_index >= len(images_list):
                return
            if load_index in pages_loaded:
                return
            load_filename = images_list[load_index]
            is_nb = nb_state.get((current_size["value"], load_filename), False)
            load_file_path = os.path.join(current_folder["path"], load_filename)
            b64 = thumb_cache.get_or_generate(
                load_file_path,
                size_px=KIOSK_CONSTANT.PREVIEW_NB_SIZE,
                quality=80,
                grayscale=is_nb,
            )
            if load_index in page_image_controls:
                page_image_controls[load_index].src = b64 if b64 else b""
            pages_loaded.add(load_index)

            async def _apply():
                try:
                    page.update()
                except Exception:
                    pass

            page.run_task(_apply)

        def _load_pages_around(center_index: int) -> None:
            for offset in (0, 1, -1, 2, -2):
                target = center_index + offset
                if 0 <= target < len(images_list):
                    threading.Thread(
                        target=_load_image_for_index,
                        args=(target,),
                        daemon=True,
                    ).start()

        def _update_bottom_bar(new_index: int) -> None:
            state["index"] = new_index
            new_filename = images_list[new_index] if images_list else ""
            preview_title.value = new_filename
            preview_count_text.value = str(
                prints_data[current_size["value"]].get(new_filename, 0)
            )
            is_nb = nb_state.get((current_size["value"], new_filename), False)
            nb_preview_button.icon_color = C_VIOLET if is_nb else C_LIGHT_GREY
            page.update()

        def on_page_change(e) -> None:
            new_index = int(e.data)
            _update_bottom_bar(new_index)
            _load_pages_around(new_index)

        def preview_add(e) -> None:
            on_change_count(_current_filename(), +1)
            preview_count_text.value = str(
                prints_data[current_size["value"]].get(_current_filename(), 0)
            )
            page.update()

        def preview_remove(e) -> None:
            on_change_count(_current_filename(), -1)
            preview_count_text.value = str(
                prints_data[current_size["value"]].get(_current_filename(), 0)
            )
            page.update()

        _HAS_PAGE_VIEW = hasattr(ft, "PageView")

        async def navigate_prev(e) -> None:
            if not images_list or state["index"] <= 0:
                return
            if _HAS_PAGE_VIEW:
                await images_page_view.previous_page(  # type: ignore[union-attr]
                    animation_curve=ft.AnimationCurve.EASE_IN_OUT_CUBIC_EMPHASIZED,
                    animation_duration=ft.Duration(milliseconds=500),
                )
            else:
                _fb_navigate(state["index"] - 1)

        async def navigate_next(e) -> None:
            if not images_list or state["index"] >= len(images_list) - 1:
                return
            if _HAS_PAGE_VIEW:
                await images_page_view.next_page(  # type: ignore[union-attr]
                    animation_curve=ft.AnimationCurve.EASE_IN_OUT_CUBIC_EMPHASIZED,
                    animation_duration=ft.Duration(milliseconds=500),
                )
            else:
                _fb_navigate(state["index"] + 1)

        def preview_toggle_nb(e) -> None:
            current_fn = _current_filename()
            on_toggle_nb(current_fn)
            is_nb = nb_state.get((current_size["value"], current_fn), False)
            nb_preview_button.icon_color = C_VIOLET if is_nb else C_LIGHT_GREY
            # Réinitialise l'image courante pour forcer le rechargement N&B
            if state["index"] in page_image_controls:
                page_image_controls[state["index"]].src = b""
            pages_loaded.discard(state["index"])
            page.update()
            threading.Thread(
                target=_load_image_for_index,
                args=(state["index"],),
                daemon=True,
            ).start()

        nb_preview_button.on_click = preview_toggle_nb

        # ── Sélecteur de format dans la prévisualisation ────────────────────────
        format_selector_text = ft.Text(
            current_size["value"],
            size=13,
            color=C_LIGHT_GREY,
        )

        def _on_select_format_in_preview(selected_format: str) -> None:
            current_size["value"] = selected_format
            format_selector_text.value = selected_format
            _update_size_buttons()
            current_fn = _current_filename()
            preview_count_text.value = str(
                prints_data[current_size["value"]].get(current_fn, 0)
            )
            is_nb = nb_state.get((current_size["value"], current_fn), False)
            nb_preview_button.icon_color = C_VIOLET if is_nb else C_LIGHT_GREY
            page.update()

        format_popup_menu = ft.PopupMenuButton(
            content=ft.Container(
                content=ft.Row([
                    format_selector_text,
                    ft.Icon(ft.Icons.ARROW_DROP_DOWN, color=C_LIGHT_GREY, size=16),
                ], spacing=2, tight=True),
                padding=ft.Padding(8, 4, 8, 4),
                border_radius=6,
                bgcolor=C_GREY,
            ),
            items=[
                ft.PopupMenuItem(
                    content=fmt,
                    on_click=lambda e, fmt=fmt: _on_select_format_in_preview(fmt),
                )
                for fmt in _active_sizes()
            ],
        )

        if _HAS_PAGE_VIEW:
            images_page_view = ft.PageView(
                controls=_build_page_containers(),
                expand=True,
                horizontal=True,
                selected_index=initial_index,
                on_change=on_page_change,
            )
        else:
            # Fallback pour les versions de Flet sans PageView (ex : macOS ancienne install)
            _fb_img_ctrl = ft.Image(
                src=_blank_gif,
                fit=ft.BoxFit.CONTAIN,
                expand=True,
                gapless_playback=True,
                error_content=ft.Container(
                    content=ft.Icon(ft.Icons.BROKEN_IMAGE, color=C_LIGHT_GREY, size=64),
                    alignment=ft.Alignment(0, 0),
                ),
            )
            page_image_controls[initial_index] = _fb_img_ctrl
            images_page_view = ft.Container(
                content=_fb_img_ctrl,
                expand=True,
                alignment=ft.Alignment(0, 0),
                bgcolor=C_DARK,
            )

            def _fb_navigate(new_index: int) -> None:
                """Navigation image en mode fallback (sans PageView)."""
                old_index = state["index"]
                page_image_controls.clear()
                page_image_controls[new_index] = _fb_img_ctrl
                pages_loaded.discard(old_index)
                _update_bottom_bar(new_index)
                threading.Thread(
                    target=_load_image_for_index,
                    args=(new_index,),
                    daemon=True,
                ).start()

        bottom_bar = ft.Container(
            content=ft.Row([
                ft.IconButton(
                    icon=ft.Icons.CHEVRON_LEFT,
                    icon_color=C_WHITE,
                    icon_size=36,
                    tooltip="Image précédente",
                    on_click=navigate_prev,
                    style=ft.ButtonStyle(padding=ft.Padding.all(4)),
                ),
                ft.Container(width=8),
                format_popup_menu,
                ft.Container(width=12),
                ft.IconButton(
                    icon=ft.Icons.REMOVE_CIRCLE_OUTLINE,
                    icon_color=C_RED,
                    icon_size=36,
                    tooltip="Retirer une copie",
                    on_click=preview_remove,
                    style=ft.ButtonStyle(padding=ft.Padding.all(4)),
                ),
                preview_count_text,
                ft.IconButton(
                    icon=ft.Icons.ADD_CIRCLE_OUTLINE,
                    icon_color=C_GREEN,
                    icon_size=36,
                    tooltip="Ajouter une copie",
                    on_click=preview_add,
                    style=ft.ButtonStyle(padding=ft.Padding.all(4)),
                ),
                ft.Container(width=12),
                nb_preview_button,
                ft.IconButton(
                    icon=ft.Icons.CROP,
                    icon_color=C_LIGHT_GREY,
                    icon_size=28,
                    tooltip="Recadrer",
                    on_click=lambda e: _open_crop_dialog(_current_filename()),
                    style=ft.ButtonStyle(padding=ft.Padding.all(4)),
                ),
                ft.Container(width=8),
                ft.IconButton(
                    icon=ft.Icons.CHEVRON_RIGHT,
                    icon_color=C_WHITE,
                    icon_size=36,
                    tooltip="Image suivante",
                    on_click=navigate_next,
                    style=ft.ButtonStyle(padding=ft.Padding.all(4)),
                ),
            ], vertical_alignment=ft.CrossAxisAlignment.CENTER, tight=True),
            bgcolor=ft.Colors.with_opacity(0.72, C_GREY),
            border_radius=16,
            padding=ft.Padding(8, 6, 8, 6),
        )

        preview_overlay = ft.Container(
            content=ft.Stack([
                ft.Column([
                    # Barre supérieure
                    ft.Container(
                        content=ft.Row([
                            ft.Container(expand=True),
                            preview_title,
                            ft.Container(expand=True),
                            ft.IconButton(
                                icon=ft.Icons.CLOSE,
                                icon_color=C_RED,
                                icon_size=28,
                                tooltip="Fermer",
                                on_click=close_preview,
                                style=ft.ButtonStyle(bgcolor=C_DARK),
                            ),
                        ], vertical_alignment=ft.CrossAxisAlignment.CENTER),
                        bgcolor=C_DARK,
                        padding=ft.Padding(12, 4, 12, 4),
                        height=50,
                    ),
                    # PageView des images (swipe horizontal)
                    images_page_view,
                ], spacing=0, expand=True),
                # Barre inférieure flottante
                ft.Container(
                    content=ft.Row(
                        [bottom_bar],
                        alignment=ft.MainAxisAlignment.CENTER,
                    ),
                    bottom=16,
                    left=0,
                    right=0,
                ),
            ], expand=True),
            bgcolor=C_DARK,
            expand=True,
        )

        def on_preview_key(event: ft.KeyboardEvent) -> None:
            if event.key in ("Arrow Left", "ArrowLeft"):
                page.run_task(navigate_prev, event)
            elif event.key in ("Arrow Right", "ArrowRight"):
                page.run_task(navigate_next, event)
            elif event.key == "Escape":
                close_preview(None)

        page.on_keyboard_event = on_preview_key
        page.overlay.append(preview_overlay)
        page.update()

        # Chargement des images autour de l'index initial
        _load_pages_around(initial_index)

    # ─────────────────────────────────────────────────────────────────────
    #  Construction d'une carte image
    # ─────────────────────────────────────────────────────────────────────

    def _build_image_card(filename: str, b64: str = None) -> tuple[ft.Container, dict]:
        """Construit une carte image (b64 ou zone grise si miniature pas encore prête)."""
        count_text = ft.Text(
            "0",
            size=20,
            color=C_LIGHT_GREY,
            weight=ft.FontWeight.BOLD,
            text_align=ft.TextAlign.CENTER,
        )
        nb_button = ft.IconButton(
            icon=ft.Icons.INVERT_COLORS,
            icon_color=C_LIGHT_GREY,
            icon_size=20,
            tooltip="Prévisualiser en N&B",
        )
        image_ctrl = ft.Image(
            src=b64 if b64 else b"",
            width=THUMBNAIL_SIZE,
            height=THUMBNAIL_SIZE,
            fit=ft.BoxFit.CONTAIN,
            gapless_playback=True,
            error_content=ft.Container(
                bgcolor=C_GREY,
                width=THUMBNAIL_SIZE,
                height=THUMBNAIL_SIZE,
                border_radius=4,
            ),
        )

        nb_button.on_click = lambda e, f=filename: on_toggle_nb(f)

        # Nom affiché tronqué
        display_name = filename if len(filename) <= 18 else filename[:15] + "…"

        card = ft.Container(
            content=ft.Column([
                ft.Container(
                    content=image_ctrl,
                    on_click=lambda e, f=filename: on_show_preview(f),
                    ink=True,
                    border_radius=6,
                    clip_behavior=ft.ClipBehavior.ANTI_ALIAS,
                    tooltip="Cliquer pour prévisualiser",
                ),
                ft.Text(
                    display_name,
                    size=11,
                    color=C_LIGHT_GREY,
                    text_align=ft.TextAlign.CENTER,
                    max_lines=1,
                    overflow=ft.TextOverflow.ELLIPSIS,
                ),
                ft.Row([
                    ft.IconButton(
                        icon=ft.Icons.REMOVE_CIRCLE_OUTLINE,
                        icon_color=C_RED,
                        icon_size=24,
                        tooltip="Retirer une impression",
                        on_click=lambda e, f=filename: on_change_count(f, -1),
                        style=ft.ButtonStyle(padding=ft.Padding.all(2)),
                    ),
                    count_text,
                    ft.IconButton(
                        icon=ft.Icons.ADD_CIRCLE_OUTLINE,
                        icon_color=C_GREEN,
                        icon_size=24,
                        tooltip="Ajouter une impression",
                        on_click=lambda e, f=filename: on_change_count(f, 1),
                        style=ft.ButtonStyle(padding=ft.Padding.all(2)),
                    ),
                    nb_button,
                ], alignment=ft.MainAxisAlignment.CENTER, spacing=0, tight=True),
            ],
                horizontal_alignment=ft.CrossAxisAlignment.CENTER,
                spacing=6,
                tight=True,
            ),
            bgcolor=C_GREY,
            border=_border_all(2, C_GREY),
            border_radius=10,
            padding=8,
        )

        card_data = {
            "card": card,
            "count_text": count_text,
            "image_ctrl": image_ctrl,
            "nb_button": nb_button,
        }
        return card, card_data

    # ─────────────────────────────────────────────────────────────────────
    #  Lazy loading — rendu de la page courante de la grille
    # ─────────────────────────────────────────────────────────────────────

    def _render_image_page() -> None:
        """Affiche uniquement les cartes de la page courante.
        Les miniatures ont déjà été converties sur disque — affichage instantané."""
        total = len(images_list)
        if total == 0:
            image_cards.clear()
            images_grid.controls.clear()
            images_grid.update()
            pagination_row.visible = False
            pagination_row.update()
            return

        total_pages = max(1, (total + KIOSK_PAGE_SIZE - 1) // KIOSK_PAGE_SIZE)
        current_pg  = min(max(0, kiosk_page["value"]), total_pages - 1)
        kiosk_page["value"] = current_pg

        start       = current_pg * KIOSK_PAGE_SIZE
        end         = min(start + KIOSK_PAGE_SIZE, total)
        page_images = images_list[start:end]

        # Pagination UI
        prev_page_btn.visible     = current_pg > 0
        next_page_btn.visible     = current_pg < total_pages - 1
        page_indicator_text.value = f"Page {current_pg + 1} / {total_pages}"
        pagination_row.visible    = total > KIOSK_PAGE_SIZE
        pagination_row.update()

        # Reconstruction de la grille pour cette page uniquement
        image_cards.clear()
        images_grid.controls.clear()

        render_token = kiosk_page_token["value"]
        for entry_name in page_images:
            card, card_data = _build_image_card(entry_name)
            image_cards[entry_name] = card_data
            images_grid.controls.append(card)

        images_grid.update()

        # Chargement asynchrone des miniatures pour la page courante
        if page_images:
            page_images_snapshot = list(page_images)
            folder_snapshot = current_folder["path"]

            def _fill_page_thumbs():
                for filename in page_images_snapshot:
                    if kiosk_page_token["value"] != render_token:
                        return
                    file_path = os.path.join(folder_snapshot, filename)
                    b64 = thumb_cache.get_or_generate(file_path)
                    if b64 and filename in image_cards and kiosk_page_token["value"] == render_token:
                        image_cards[filename]["image_ctrl"].src = b64

                        async def _upd():
                            try:
                                page.update()
                            except Exception:
                                pass

                        page.run_task(_upd)

            threading.Thread(target=_fill_page_thumbs, daemon=True).start()

    def _go_to_page(page_num: int) -> None:
        """Change la page courante et déclenche le rendu."""
        kiosk_page["value"] = page_num
        _render_image_page()
        page.update()

    # ─────────────────────────────────────────────────────────────────────
    #  Chargement du dossier
    # ─────────────────────────────────────────────────────────────────────

    def load_folder(folder_path: str) -> None:
        # Réinitialisation
        images_list.clear()
        image_cards.clear()
        nb_state.clear()
        prints_data.clear()
        total_price["value"] = 0.0
        current_folder["path"] = folder_path

        # Incrémenter le jeton pour annuler toute conversion en cours
        kiosk_page_token["value"] += 1
        token = kiosk_page_token["value"]

        # Scan des images — sélection curatée (manifeste) si verrouillé,
        # sinon listing classique du dossier (lancement hors Hub / dev).
        manifest = _load_selection_manifest()
        try:
            if manifest is not None:
                existing = set(os.listdir(folder_path))
                for entry_name in manifest:
                    if (entry_name in existing
                            and entry_name.lower().endswith(KIOSK_EXTENSION)):
                        images_list.append(entry_name)
            else:
                for entry_name in sorted(os.listdir(folder_path)):
                    if entry_name.lower().endswith(KIOSK_EXTENSION):
                        images_list.append(entry_name)
        except PermissionError:
            pass

        # Initialisation des données d'impression pour tous les formats possibles
        for format_name in set(STUDIOS_TARIFF) | set(PRINTS_TARIFF):
            prints_data[format_name] = {f: 0 for f in images_list}

        # Mise à jour des labels d'en-tête
        folder_label.value = os.path.basename(folder_path) or folder_path
        folder_label.update()
        count_label.value = f"{len(images_list)} image(s)"
        count_label.update()
        price_text.value = "0.00 €"
        price_text.update()

        # Vider la grille pendant la conversion
        images_grid.controls.clear()
        images_grid.update()
        pagination_row.visible = False
        pagination_row.update()
        _update_size_buttons()

        loading_row.visible = False
        loading_row.update()

        if not images_list:
            return

        # Affichage immédiat de la grille avec chargement asynchrone des miniatures
        kiosk_page["value"] = 0
        _render_image_page()

        # Pré-chargement en arrière-plan des miniatures pour toutes les pages
        def _bg_preload():
            thumb_cache.preload_folder(
                folder_path,
                images_list,
                stop_token=kiosk_page_token,
                token_value=token,
            )
            # Pré-génère aussi la taille plein écran, sinon le premier clic
            # sur une image déclenche un décodage+resize complet à la volée.
            thumb_cache.preload_folder(
                folder_path,
                images_list,
                size_px=KIOSK_CONSTANT.PREVIEW_NB_SIZE,
                quality=80,
                stop_token=kiosk_page_token,
                token_value=token,
            )

        threading.Thread(target=_bg_preload, daemon=True).start()

    # ─────────────────────────────────────────────────────────────────────
    #  Ouverture d'un dossier
    # ─────────────────────────────────────────────────────────────────────

    async def open_folder_dialog(e) -> None:
        folder = await ft.FilePicker().get_directory_path(
            dialog_title="Choisissez votre dossier de photos",
        )
        if folder:
            load_folder(os.path.normpath(folder))
        page.update()

    # ─────────────────────────────────────────────────────────────────────
    #  Validation de commande
    # ─────────────────────────────────────────────────────────────────────

    def validate_order(e) -> None:
        if not current_folder["path"]:
            return

        # Construit format_selections[format_name] = {filename: count} pour count > 0
        format_selections: dict[str, dict[str, int]] = {}
        selected_files: set[str] = set()
        for format_name in _active_sizes():
            for filename, count in prints_data.get(format_name, {}).items():
                if count > 0:
                    format_selections.setdefault(format_name, {})[filename] = count
                    selected_files.add(filename)

        if not selected_files:
            page.show_dialog(ft.SnackBar(
                ft.Text("Aucune impression sélectionnée.", color=C_WHITE),
                bgcolor=C_GREY,
                duration=3000,
                behavior=ft.SnackBarBehavior.FLOATING,
            ))
            return

        folder_path = current_folder["path"]

        # ── Trouve un dossier SELECTION disponible ─────────────────────────
        selection_base = os.path.join(folder_path, "SELECTION")
        selection_dir = selection_base
        n = 2
        while os.path.exists(selection_dir):
            selection_dir = f"{selection_base}_{n}"
            n += 1
        selection_name = os.path.basename(selection_dir)

        errors: list[str] = []
        try:
            os.makedirs(selection_dir, exist_ok=True)
        except OSError as mkdir_error:
            page.show_dialog(ft.SnackBar(
                ft.Text(f"Erreur création dossier : {mkdir_error}", color=C_RED),
                bgcolor=C_GREY,
                duration=4000,
                behavior=ft.SnackBarBehavior.FLOATING,
            ))
            return

        import shutil

        # ── Copie les fichiers sélectionnés dans SELECTION/ avec nomenclature {count}X_{format}_{original} ──
        for format_name, file_counts in format_selections.items():
            for filename, count in file_counts.items():
                source_path = crop_overrides.get(
                    filename, os.path.join(folder_path, filename))
                if not os.path.isfile(source_path):
                    continue
                original_stem, file_extension = os.path.splitext(filename)
                new_stem = f"{count}X_{format_name}_{original_stem}"
                destination_path = os.path.join(selection_dir, new_stem + file_extension)
                if os.path.exists(destination_path):
                    counter = 1
                    while os.path.exists(destination_path):
                        destination_path = os.path.join(selection_dir, f"{new_stem} ({counter}){file_extension}")
                        counter += 1
                try:
                    if nb_state.get((format_name, filename), False) and HAS_PIL and PILImage is not None and ImageOps is not None:
                        ext = file_extension.lower()
                        fmt = "JPEG" if ext in (".jpg", ".jpeg") else "PNG"
                        save_kwargs: dict = {"quality": 100} if fmt == "JPEG" else {}
                        with PILImage.open(source_path) as img:
                            img = ImageOps.exif_transpose(img)
                            img = img.convert("L")
                            img.save(destination_path, format=fmt, **save_kwargs)
                    else:
                        shutil.copy2(source_path, destination_path)
                except Exception as copy_error:
                    errors.append(f"{filename}: {copy_error}")

        # ── Écrit / complète commande.txt ──────────────────────────────────
        commande_path = os.path.join(selection_dir, "commande.txt")
        file_exists = os.path.isfile(commande_path)
        try:
            # Réorganise par photo : stem → [(count, format_name, is_nb), ...]
            photo_orders: dict[str, list[tuple[int, str, bool]]] = {}
            for format_name, file_counts in format_selections.items():
                for filename, count in file_counts.items():
                    stem = os.path.splitext(filename)[0]
                    is_nb = nb_state.get((format_name, filename), False)
                    photo_orders.setdefault(stem, []).append((count, format_name, is_nb))
            for stem in photo_orders:
                photo_orders[stem].sort(key=lambda entry: entry[1])

            with open(commande_path, "a", encoding="utf-8") as f:
                if file_exists:
                    f.write("\n")
                f.write(f"=== {selection_name} ===\n\n")
                for stem, prints_list in sorted(photo_orders.items()):
                    f.write(f"{stem}\n")
                    for count, format_name, is_nb in prints_list:
                        nb_marker = " n&b" if is_nb else ""
                        f.write(f"    {count}X {format_name}{nb_marker}\n")
                    f.write("\n")
                if active_tariff["value"] == "PRINTS":
                    f.write(f"Frais d'amorce : {FRAIS_AMORCE:.2f} €\n")
                f.write(f"TOTAL : {total_price['value']:.2f} €\n")
        except OSError as write_error:
            errors.append(f"commande.txt: {write_error}")

        if errors:
            print(f"[ERREUR] Copie fichiers :\n" + "\n".join(errors))

        # ── Unifie avec le mode commande de Hub.pyw (même fichier .order.json,
        #  clé = chemin absolu de l'original) — la copie SELECTION/commande.txt
        #  reste par ailleurs le flux d'impression physique inchangé.
        try:
            order_path = os.path.join(
                os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                ".order.json")
            try:
                with open(order_path, "r", encoding="utf-8") as f:
                    shared_order = json.load(f)
            except (OSError, ValueError):
                shared_order = {}
            for format_name, file_counts in format_selections.items():
                for filename, count in file_counts.items():
                    abs_path = os.path.abspath(
                        os.path.join(folder_path, filename))
                    shared_order.setdefault(abs_path, {})[format_name] = count
            with open(order_path, "w", encoding="utf-8") as f:
                json.dump(shared_order, f, ensure_ascii=False, indent=2)
        except OSError:
            pass

        # Réinitialisation de l'interface
        images_grid.controls.clear()
        images_grid.update()
        images_list.clear()
        image_cards.clear()
        nb_state.clear()
        prints_data.clear()
        total_price["value"] = 0.0
        price_text.value = "0.00 €"
        price_text.update()
        folder_label.value = "Aucun dossier"
        folder_label.update()
        count_label.value = "0 image(s)"
        count_label.update()
        current_folder["path"] = ""

        _cleanup_temp_dir()
        page.show_dialog(ft.SnackBar(
            ft.Text(
                f"[OK]  Commande validée.",
                color=C_GREEN,
            ),
            bgcolor=C_GREY,
            duration=3000,
            behavior=ft.SnackBarBehavior.FLOATING,
        ))

    # ─────────────────────────────────────────────────────────────────────
    #  Éléments UI permanents
    # ─────────────────────────────────────────────────────────────────────

    price_text = ft.Text(
        "0.00 €",
        size=32,
        color=C_BLUE,
        weight=ft.FontWeight.BOLD,
        text_align=ft.TextAlign.CENTER,
    )
    folder_label = ft.Text(
        "Aucun dossier",
        size=12,
        color=C_LIGHT_GREY,
        text_align=ft.TextAlign.CENTER,
        max_lines=2,
        overflow=ft.TextOverflow.ELLIPSIS,
    )
    count_label = ft.Text(
        "",
        size=11,
        color=C_LIGHT_GREY,
        text_align=ft.TextAlign.CENTER,
    )

    # ── Boutons de format ─────────────────────────────────────────────────
    size_buttons_map: dict[str, ft.Button] = {}
    sizes_column = ft.Column(
        spacing=4,
        scroll=ft.ScrollMode.AUTO,
        expand=True,
    )

    for format_name in _active_sizes():
        is_first = (format_name == current_size["value"])
        _fmt_btn = ft.Button(
            format_name,
            color=C_DARK if is_first else C_BLUE,
            bgcolor=C_BLUE if is_first else C_GREY,
            width=KIOSK_CONSTANT.LEFT_PANEL_WIDTH - 32,
            height=KIOSK_CONSTANT.FORMAT_BUTTON_HEIGHT,
            on_click=lambda e, s=format_name: on_size_select(s),
        )
        size_buttons_map[format_name] = _fmt_btn
        sizes_column.controls.append(_fmt_btn)

    # ── Grille d'images ───────────────────────────────────────────────────
    images_grid = ft.GridView(
        expand=True,
        max_extent=KIOSK_CONSTANT.GRID_MAX_EXTENT,
        child_aspect_ratio=KIOSK_CONSTANT.GRID_ASPECT_RATIO,
        spacing=KIOSK_CONSTANT.GRID_SPACING,
        run_spacing=KIOSK_CONSTANT.GRID_SPACING,
        padding=ft.Padding(12, 12, 12, 12),
    )

    # ── Zone de chargement des miniatures ─────────────────────────────────
    loading_label = ft.Text(
        "",
        size=12,
        color=C_LIGHT_GREY,
        text_align=ft.TextAlign.CENTER,
    )
    loading_progress = ft.ProgressBar(
        value=None,
        bgcolor=C_GREY,
        color=C_BLUE,
        height=4,
    )
    loading_row = ft.Container(
        content=ft.Column([
            loading_progress,
            loading_label,
        ], horizontal_alignment=ft.CrossAxisAlignment.CENTER, spacing=4),
        visible=False,
        bgcolor=C_BG,
        padding=ft.Padding(16, 6, 16, 4),
    )

    # ── Contrôles de pagination ───────────────────────────────────────────
    prev_page_btn = ft.IconButton(
        icon=ft.Icons.CHEVRON_LEFT,
        icon_color=C_BLUE,
        icon_size=44,
        tooltip="Page précédente",
        on_click=lambda e: _go_to_page(kiosk_page["value"] - 1),
    )
    next_page_btn = ft.IconButton(
        icon=ft.Icons.CHEVRON_RIGHT,
        icon_color=C_BLUE,
        icon_size=44,
        tooltip="Page suivante",
        on_click=lambda e: _go_to_page(kiosk_page["value"] + 1),
    )
    page_indicator_text = ft.Text(
        "",
        size=13,
        color=C_LIGHT_GREY,
        text_align=ft.TextAlign.CENTER,
        width=120,
    )
    pagination_row = ft.Container(
        content=ft.Row(
            [prev_page_btn, page_indicator_text, next_page_btn],
            alignment=ft.MainAxisAlignment.CENTER,
            vertical_alignment=ft.CrossAxisAlignment.CENTER,
            spacing=4,
        ),
        visible=False,
        bgcolor=C_BG,
        padding=ft.Padding(8, 4, 8, 4),
    )

    # ── Panneau gauche ────────────────────────────────────────────────────
    # Verrouillé (manifeste fourni par Hub) : pas d'accès au système de
    # fichiers hors de la sélection curatée (HUB_SPEC §9) — le bouton
    # "OUVRIR" (FilePicker libre) n'est ni affiché ni cliquable.
    left_panel_top = [] if KIOSK_LOCKED else [
        ft.Button(
            "OUVRIR",
            icon=ft.Icons.FOLDER_OPEN,
            color=C_DARK,
            bgcolor=C_VIOLET,
            width=KIOSK_CONSTANT.LEFT_PANEL_WIDTH - 32,
            height=KIOSK_CONSTANT.ACTION_BUTTON_HEIGHT,
            on_click=open_folder_dialog,
        ),
    ]
    left_panel = ft.Container(
        content=ft.Column([
            *left_panel_top,
            folder_label,
            count_label,
            ft.Divider(color=C_GREY, height=8, thickness=1),
            ft.Text(
                "Format d'impression",
                size=12,
                color=C_LIGHT_GREY,
                text_align=ft.TextAlign.CENTER,
                weight=ft.FontWeight.W_500,
            ),
            sizes_column,
            ft.Divider(color=C_GREY, height=8, thickness=1),
            price_text,
            ft.Text(
                "Total commande",
                size=12,
                color=C_LIGHT_GREY,
                text_align=ft.TextAlign.CENTER,
            ),
            ft.Button(
                "VALIDER",
                icon=ft.Icons.CHECK_CIRCLE_OUTLINE,
                color=C_DARK,
                bgcolor=C_GREEN,
                width=KIOSK_CONSTANT.LEFT_PANEL_WIDTH - 32,
                height=KIOSK_CONSTANT.ACTION_BUTTON_HEIGHT,
                on_click=validate_order,
            ),
        ],
            horizontal_alignment=ft.CrossAxisAlignment.CENTER,
            spacing=10,
            expand=True,
        ),
        bgcolor=C_DARK,
        padding=ft.Padding(10, 16, 10, 16),
        width=KIOSK_CONSTANT.LEFT_PANEL_WIDTH,
    )

    # Sortie directe (pas de code) : usage en présentiel sur écran tactile,
    # l'opérateur studio est physiquement là pour fermer le kiosque —
    # HUB_SPEC §9 mis à jour en conséquence. `prevent_close` reste utile
    # pour garantir _cleanup_temp_dir() avant fermeture (Cmd+Q, Alt+F4…).
    def _do_exit(event=None) -> None:
        _cleanup_temp_dir()
        page.window.prevent_close = False
        try:
            page.window.close()
        except Exception:
            pass
        os._exit(0)

    def _on_window_event(event) -> None:
        if getattr(event, "data", "") == "close":
            _do_exit()

    page.window.prevent_close = True
    page.window.on_event = _on_window_event

    # ── Tableau des tarifs ────────────────────────────────────────────────
    def _show_price_table(e) -> None:
        tariff_name = active_tariff["value"]
        if tariff_name == "STUDIOS":
            rows = [
                ft.DataRow(cells=[
                    ft.DataCell(ft.Text(fmt, color=C_WHITE, size=13)),
                    ft.DataCell(ft.Text(f"{price:.2f} €" if price > 0 else "—", color=C_BLUE, size=13)),
                ])
                for fmt, price in STUDIOS_TARIFF.items()
            ]
            table = ft.DataTable(
                columns=[
                    ft.DataColumn(ft.Text("Format", color=C_LIGHT_GREY, weight=ft.FontWeight.W_600)),
                    ft.DataColumn(ft.Text("Prix unitaire", color=C_LIGHT_GREY, weight=ft.FontWeight.W_600), numeric=True),
                ],
                rows=rows,
                border=_border_all(1, C_GREY),
                border_radius=8,
                heading_row_color=C_GREY,
            )
        else:
            tier_labels = ["≤ 10", "11–50", "51–100", "101–200", "> 200"]
            rows = [
                ft.DataRow(cells=[
                    ft.DataCell(ft.Text(fmt, color=C_WHITE, size=13)),
                    *[ft.DataCell(ft.Text(f"{p:.2f} €", color=C_BLUE, size=13)) for p in tiers],
                ])
                for fmt, tiers in PRINTS_TARIFF.items()
            ]
            table = ft.DataTable(
                columns=[
                    ft.DataColumn(ft.Text("Format", color=C_LIGHT_GREY, weight=ft.FontWeight.W_600)),
                    *[ft.DataColumn(ft.Text(lbl, color=C_LIGHT_GREY, weight=ft.FontWeight.W_600), numeric=True) for lbl in tier_labels],
                ],
                rows=rows,
                border=_border_all(1, C_GREY),
                border_radius=8,
                heading_row_color=C_GREY,
            )
        amorce_note = ft.Text(
            f"+ Frais d'amorce : {FRAIS_AMORCE:.2f} € par commande",
            color=C_LIGHT_GREY,
            size=12,
            italic=True,
        ) if tariff_name == "PRINTS" else None
        dlg = ft.AlertDialog(
            modal=True,
            title=ft.Text(f"Tarifs — {tariff_name}", color=C_WHITE, weight=ft.FontWeight.BOLD),
            content=ft.Container(
                content=ft.Column(
                    [table] + ([amorce_note] if amorce_note else []),
                    scroll=ft.ScrollMode.AUTO, tight=True,
                ),
                bgcolor=C_DARK,
                border_radius=8,
                padding=8,
            ),
            bgcolor=C_GREY,
            actions=[
                ft.TextButton("Fermer", on_click=lambda e: page.pop_dialog(), style=ft.ButtonStyle(color=C_BLUE)),
            ],
            actions_alignment=ft.MainAxisAlignment.END,
        )
        page.show_dialog(dlg)

    # ── Barre de titre personnalisée ──────────────────────────────────────
    top_bar = ft.Container(
        content=ft.Row([
            ft.Container(
                content=ft.Text(
                    "KIOSK PHOTO",
                    size=16,
                    color=C_BLUE,
                    weight=ft.FontWeight.BOLD,
                    style=ft.TextStyle(letter_spacing=2),
                ),
                padding=ft.Padding(16, 0, 0, 0),
            ),
            ft.Container(expand=True),
            ft.Button(
                content=ft.Text("TARIFS", size=12, color=C_LIGHT_GREY),
                on_click=_show_price_table,
                bgcolor=ft.Colors.TRANSPARENT,
                style=ft.ButtonStyle(
                    side=ft.BorderSide(1, C_LIGHT_GREY),
                    shape=ft.RoundedRectangleBorder(radius=6),
                    padding=ft.Padding.symmetric(horizontal=10, vertical=4),
                ),
                height=30,
            ),
            ft.IconButton(
                icon=ft.Icons.CLOSE,
                icon_color=C_RED,
                icon_size=22,
                tooltip="Quitter",
                on_click=_do_exit,
                visible=True,
                style=ft.ButtonStyle(padding=ft.Padding.all(4)),
            ),
        ], vertical_alignment=ft.CrossAxisAlignment.CENTER),
        bgcolor=C_DARK,
        height=44,
        padding=ft.Padding(0, 0, 8, 0),
    )

    # ── Assemblage du layout principal ────────────────────────────────────
    page.add(
        ft.Column([
            top_bar,
            ft.Divider(height=1, thickness=1, color=C_GREY),
            ft.Row([
                left_panel,
                ft.VerticalDivider(width=1, thickness=1, color=C_GREY),
                ft.Column([
                    loading_row,
                    pagination_row,
                    ft.Container(
                        content=images_grid,
                        expand=True,
                        bgcolor=C_BG,
                    ),
                ], expand=True, spacing=0),
            ], expand=True, spacing=0, vertical_alignment=ft.CrossAxisAlignment.STRETCH),
        ], expand=True, spacing=0)
    )

    # ── Auto-ouverture du dossier passé par Dashboard ─────────────────────
    _initial_folder = os.environ.get("FOLDER_PATH", "")
    if _initial_folder and os.path.isdir(_initial_folder):
        load_folder(_initial_folder)


# ─────────────────────────────────────────────────────────────────────────────
#  Lancement
# ─────────────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    ft.run(main)
