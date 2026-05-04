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

import flet as ft
import os
import sys
import io
import base64
import threading
import tempfile
import shutil
import platform

# ── Import des constantes spécifiques au kiosk ───────────────────────────────
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import CONSTANT as KIOSK_CONSTANT

try:
    from PIL import Image as PILImage, ImageOps
    HAS_PIL = True
except ImportError:
    PILImage = None  # type: ignore[assignment]
    ImageOps = None  # type: ignore[assignment]
    HAS_PIL = False

# ── Extensions acceptées ──────────────────────────────────────────────────────
KIOSK_EXTENSION = KIOSK_CONSTANT.EXTENSION

# ── Taille des miniatures ────────────────────────────────────────────────────
THUMBNAIL_SIZE = KIOSK_CONSTANT.THUMBNAIL_SIZE


# ─────────────────────────────────────────────────────────────────────────────
#  Utilitaire image
# ─────────────────────────────────────────────────────────────────────────────

def _make_thumbnail_b64(file_path: str, grayscale: bool = False, size: int = THUMBNAIL_SIZE) -> str | None:
    """
    Génère une miniature JPEG encodée en base64.

    Applique automatiquement la correction d'orientation EXIF.
    Retourne None si PIL n'est pas disponible ou en cas d'erreur.
    """
    if not HAS_PIL or PILImage is None or ImageOps is None:
        return None
    try:
        with PILImage.open(file_path) as img:
            img = ImageOps.exif_transpose(img)
            if grayscale:
                img = img.convert("L").convert("RGB")
            else:
                img = img.convert("RGB")
            img.thumbnail((size, size), PILImage.LANCZOS)
            buffer = io.BytesIO()
            img.save(buffer, format="JPEG", quality=80)
            return base64.b64encode(buffer.getvalue()).decode("utf-8")
    except Exception:
        return None


def _save_thumbnail(file_path: str, out_path: str, grayscale: bool = False, size: int = THUMBNAIL_SIZE) -> bool:
    """
    Génère une miniature JPEG et la sauvegarde sur disque.
    Retourne True en cas de succès, False sinon.
    """
    if not HAS_PIL or PILImage is None or ImageOps is None:
        return False
    try:
        with PILImage.open(file_path) as img:
            img = ImageOps.exif_transpose(img)
            if grayscale:
                img = img.convert("L").convert("RGB")
            else:
                img = img.convert("RGB")
            img.thumbnail((size, size), PILImage.LANCZOS)
            img.save(out_path, format="JPEG", quality=80)
        return True
    except Exception:
        return False


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

    # ── Configuration de la fenêtre ───────────────────────────────────────
    page.title = "Kiosk Photo"
    page.theme_mode = ft.ThemeMode.DARK
    page.bgcolor = C_BG
    page.window.title_bar_hidden = True
    page.window.title_bar_buttons_hidden = True
    page.padding = 0
    page.update()

    async def _maximize_window() -> None:
        if platform.system() == "Darwin":
            page.window.full_screen = True
        else:
            page.window.maximized = True
        page.update()

    page.run_task(_maximize_window)

    # ── Tarifs et paramètres grille depuis Kiosk/CONSTANT.py ─────────────────
    SIZES: dict = KIOSK_CONSTANT.SIZES

    # ── État global ───────────────────────────────────────────────────────
    current_folder = {"path": ""}
    images_list: list[str] = []
    # prints_data[format][filename] = nombre de copies
    prints_data: dict[str, dict[str, int]] = {}
    current_size = {"value": list(SIZES.keys())[0]}
    total_price = {"value": 0.0}
    nb_state: dict[tuple, bool] = {}        # (format_name, filename) → True = N&B actif pour ce format
    image_cards: dict[str, dict] = {}       # {filename: {card, count_text, image_ctrl, nb_button}}

    KIOSK_PAGE_SIZE  = 60               # nombre de cartes affichées par page
    kiosk_page       = {"value": 0}     # page courante (0-indexé)
    kiosk_page_token = {"value": 0}     # jeton d'annulation des threads miniatures

    # ─────────────────────────────────────────────────────────────────────
    #  Helpers d'état
    # ─────────────────────────────────────────────────────────────────────

    def _recalculate_total() -> None:
        total = 0.0
        for format_name, price_per_unit in SIZES.items():
            for filename, count in prints_data.get(format_name, {}).items():
                total += count * price_per_unit
        total_price["value"] = round(total, 2)
        price_text.value = f"{total_price['value']:.2f} €"
        price_text.update()

    def _apply_card_style(card_data: dict, count: int) -> None:
        """Met en évidence (vert) ou remet à l'état neutre une carte selon le nombre de copies."""
        card_data["count_text"].value = str(count)
        card_data["count_text"].color = C_GREEN if count > 0 else C_LIGHT_GREY
        card_data["count_text"].update()
        card_data["card"].border = ft.Border.all(2, C_GREEN if count > 0 else C_GREY)
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
            temp_dir = _get_temp_dir()
            if is_nb:
                thumb_path = os.path.join(temp_dir, f"{stem}_nb.jpg")
                if not os.path.exists(thumb_path):
                    ok = _save_thumbnail(file_path, thumb_path, grayscale=True)
                    if not ok:
                        thumb_path = os.path.join(temp_dir, f"{stem}_thumb.jpg")
            else:
                thumb_path = os.path.join(temp_dir, f"{stem}_thumb.jpg")
                if not os.path.exists(thumb_path):
                    ok = _save_thumbnail(file_path, thumb_path, grayscale=False)
                    if not ok:
                        thumb_path = file_path
            card_data["image_ctrl"].src = thumb_path

            async def _apply():
                try:
                    page.update()
                except Exception:
                    pass

            page.run_task(_apply)

        threading.Thread(target=_reload_thumbnail, daemon=True).start()

    def on_show_preview(filename: str) -> None:
        """Affiche la prévisualisation plein écran de l'image."""
        _blank_gif = "data:image/gif;base64,R0lGODlhAQABAAD/ACwAAAAAAQABAAACADs="

        # État mutable de la prévisualisation (navigation)
        state = {
            "index": images_list.index(filename) if filename in images_list else 0,
            "filename": filename,
            "nb_active": nb_state.get((current_size["value"], filename), False),
        }

        def _current_file_path() -> str:
            return os.path.join(current_folder["path"], state["filename"])

        def close_preview(e) -> None:
            if preview_overlay in page.overlay:
                page.overlay.remove(preview_overlay)
            page.update()

        preview_img = ft.Image(
            src=_blank_gif,
            fit=ft.BoxFit.CONTAIN,
            expand=True,
            gapless_playback=True,
            error_content=ft.Container(
                content=ft.Icon(ft.Icons.BROKEN_IMAGE, color=C_LIGHT_GREY, size=64),
                alignment=ft.Alignment(0, 0),
            ),
        )
        preview_title = ft.Text(
            filename,
            size=15,
            color=C_WHITE,
            weight=ft.FontWeight.W_500,
            max_lines=1,
            overflow=ft.TextOverflow.ELLIPSIS,
        )

        # ── Barre inférieure : compteur + N&B ─────────────────────────────
        preview_count_text = ft.Text(
            str(prints_data[current_size["value"]].get(filename, 0)),
            size=26,
            color=C_WHITE,
            weight=ft.FontWeight.BOLD,
            width=56,
            text_align=ft.TextAlign.CENTER,
        )

        def _refresh_preview_count() -> None:
            preview_count_text.value = str(
                prints_data[current_size["value"]].get(state["filename"], 0)
            )
            page.update()

        def preview_add(e) -> None:
            on_change_count(state["filename"], +1)
            _refresh_preview_count()

        def preview_remove(e) -> None:
            on_change_count(state["filename"], -1)
            _refresh_preview_count()

        nb_preview_button = ft.IconButton(
            icon=ft.Icons.INVERT_COLORS,
            icon_color=C_VIOLET if state["nb_active"] else C_LIGHT_GREY,
            icon_size=30,
            tooltip="Basculer N&B",
        )

        def _reload_preview_image() -> None:
            temp_dir = _get_temp_dir()
            stem = os.path.splitext(state["filename"])[0]
            suffix = "_preview_nb" if state["nb_active"] else "_preview"
            preview_path = os.path.join(temp_dir, f"{stem}{suffix}.jpg")
            if not os.path.exists(preview_path):
                ok = _save_thumbnail(
                    _current_file_path(),
                    preview_path,
                    grayscale=state["nb_active"],
                    size=1024,
                )
                if not ok:
                    preview_path = _current_file_path()
            preview_img.src = preview_path

            async def _apply():
                try:
                    page.update()
                except Exception:
                    pass

            page.run_task(_apply)

        def _navigate_to(new_filename: str) -> None:
            state["filename"] = new_filename
            state["nb_active"] = nb_state.get((current_size["value"], new_filename), False)
            preview_img.src = _blank_gif
            preview_title.value = new_filename
            preview_count_text.value = str(
                prints_data[current_size["value"]].get(new_filename, 0)
            )
            nb_preview_button.icon_color = C_VIOLET if state["nb_active"] else C_LIGHT_GREY
            page.update()
            threading.Thread(target=_reload_preview_image, daemon=True).start()

        def navigate_prev(e) -> None:
            if not images_list:
                return
            state["index"] = (state["index"] - 1) % len(images_list)
            _navigate_to(images_list[state["index"]])

        def navigate_next(e) -> None:
            if not images_list:
                return
            state["index"] = (state["index"] + 1) % len(images_list)
            _navigate_to(images_list[state["index"]])

        def preview_toggle_nb(e) -> None:
            on_toggle_nb(state["filename"])
            state["nb_active"] = nb_state.get((current_size["value"], state["filename"]), False)
            nb_preview_button.icon_color = C_VIOLET if state["nb_active"] else C_LIGHT_GREY
            preview_img.src = _blank_gif
            page.update()
            threading.Thread(target=_reload_preview_image, daemon=True).start()

        nb_preview_button.on_click = preview_toggle_nb

        bottom_bar = ft.Container(
            content=ft.Row([
                ft.Container(expand=True),
                ft.Text(
                    current_size["value"],
                    size=13,
                    color=C_LIGHT_GREY,
                ),
                ft.Container(expand=True),
                ft.IconButton(
                    icon=ft.Icons.CHEVRON_LEFT,
                    icon_color=C_WHITE,
                    icon_size=36,
                    tooltip="Image précédente",
                    on_click=navigate_prev,
                    style=ft.ButtonStyle(padding=ft.Padding.all(4)),
                ),
                ft.Container(width=8),
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
                ft.Container(width=8),
                ft.IconButton(
                    icon=ft.Icons.CHEVRON_RIGHT,
                    icon_color=C_WHITE,
                    icon_size=36,
                    tooltip="Image suivante",
                    on_click=navigate_next,
                    style=ft.ButtonStyle(padding=ft.Padding.all(4)),
                ),
                ft.Container(width=20),
                nb_preview_button,
                ft.Container(expand=True),
            ], vertical_alignment=ft.CrossAxisAlignment.CENTER),
            bgcolor=C_DARK,
            height=64,
            padding=ft.Padding(12, 4, 12, 4),
        )

        preview_overlay = ft.Container(
            content=ft.Column([
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
                # Zone image
                ft.Container(
                    content=preview_img,
                    expand=True,
                    alignment=ft.Alignment(0, 0),
                    bgcolor=C_DARK,
                ),
                # Barre inférieure
                ft.Divider(height=1, thickness=1, color=C_GREY),
                bottom_bar,
            ], spacing=0, expand=True),
            bgcolor=C_DARK,
            expand=True,
        )

        page.overlay.append(preview_overlay)
        page.update()

        # ── Chargement de l'image en haute résolution en arrière-plan
        threading.Thread(target=_reload_preview_image, daemon=True).start()

    # ─────────────────────────────────────────────────────────────────────
    #  Dossier temporaire pour les miniatures
    # ─────────────────────────────────────────────────────────────────────
    _temp_dir: dict = {"path": ""}

    def _get_temp_dir() -> str:
        """Crée le dossier temporaire si nécessaire et retourne son chemin."""
        if not _temp_dir["path"] or not os.path.isdir(_temp_dir["path"]):
            _temp_dir["path"] = tempfile.mkdtemp(prefix="kiosk_")
        return _temp_dir["path"]

    def _cleanup_temp_dir() -> None:
        """Supprime le dossier temporaire et tout son contenu."""
        if _temp_dir["path"] and os.path.isdir(_temp_dir["path"]):
            shutil.rmtree(_temp_dir["path"], ignore_errors=True)
        _temp_dir["path"] = ""

    # ─────────────────────────────────────────────────────────────────────
    #  Construction d'une carte image
    # ─────────────────────────────────────────────────────────────────────

    def _build_image_card(filename: str, thumb_path: str) -> tuple[ft.Container, dict]:
        """Construit une carte image en utilisant la miniature déjà convertie sur disque."""
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
            src=thumb_path,
            width=THUMBNAIL_SIZE,
            height=THUMBNAIL_SIZE,
            fit=ft.BoxFit.CONTAIN,
            gapless_playback=True,
            error_content=ft.Container(
                content=ft.Icon(ft.Icons.BROKEN_IMAGE, color=C_LIGHT_GREY, size=40),
                width=THUMBNAIL_SIZE,
                height=THUMBNAIL_SIZE,
                alignment=ft.Alignment(0, 0),
                bgcolor=C_GREY,
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
            border=ft.Border.all(2, C_GREY),
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

        temp_dir = _get_temp_dir()
        for entry_name in page_images:
            stem       = os.path.splitext(entry_name)[0]
            thumb_path = os.path.join(temp_dir, f"{stem}_thumb.jpg")
            card, card_data = _build_image_card(entry_name, thumb_path)
            image_cards[entry_name] = card_data
            images_grid.controls.append(card)

        images_grid.update()

    def _go_to_page(page_num: int) -> None:
        """Change la page courante et déclenche le rendu."""
        kiosk_page["value"] = page_num
        _render_image_page()
        page.update()

    # ─────────────────────────────────────────────────────────────────────
    #  Chargement du dossier
    # ─────────────────────────────────────────────────────────────────────

    def load_folder(folder_path: str) -> None:
        _cleanup_temp_dir()
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

        # Scan des images
        try:
            for entry_name in sorted(os.listdir(folder_path)):
                if entry_name.lower().endswith(KIOSK_EXTENSION):
                    images_list.append(entry_name)
        except PermissionError:
            pass

        # Initialisation des données d'impression pour chaque format
        for format_name in SIZES:
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

        if not images_list:
            loading_row.visible = False
            loading_row.update()
            return

        # ── Phase 1 : conversion de toutes les miniatures (1024 px) ──────
        total = len(images_list)
        loading_label.value    = f"Conversion 0 / {total}"
        loading_progress.value = 0.0
        loading_row.visible    = True
        loading_row.update()

        def _convert_all():
            temp_dir = _get_temp_dir()
            for i, filename in enumerate(images_list):
                if kiosk_page_token["value"] != token:
                    return  # dossier changé entre-temps
                file_path  = os.path.join(folder_path, filename)
                stem       = os.path.splitext(filename)[0]
                thumb_path = os.path.join(temp_dir, f"{stem}_thumb.jpg")
                if not os.path.exists(thumb_path):
                    _save_thumbnail(file_path, thumb_path, grayscale=False, size=1024)
                loaded = i + 1
                loading_label.value    = f"Conversion {loaded} / {total}"
                loading_progress.value = loaded / total

                async def _upd():
                    try:
                        page.update()
                    except Exception:
                        pass

                page.run_task(_upd)

            if kiosk_page_token["value"] != token:
                return

            # ── Phase 2 : affichage paginé ───────────────────────────────
            async def _show_grid():
                loading_row.visible = False
                kiosk_page["value"] = 0
                _render_image_page()
                page.update()

            page.run_task(_show_grid)

        threading.Thread(target=_convert_all, daemon=True).start()

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
        for format_name in SIZES:
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

        # ── Copie les fichiers sélectionnés dans SELECTION/<format>/<count>x/ ──
        for format_name, file_counts in format_selections.items():
            for filename, count in file_counts.items():
                source_path = os.path.join(folder_path, filename)
                if not os.path.isfile(source_path):
                    continue
                count_subfolder = os.path.join(selection_dir, format_name, f"{count}x")
                try:
                    os.makedirs(count_subfolder, exist_ok=True)
                except OSError as mk_err:
                    errors.append(f"{filename}: {mk_err}")
                    continue
                destination_path = os.path.join(count_subfolder, filename)
                if os.path.exists(destination_path):
                    base, extension = os.path.splitext(filename)
                    counter = 1
                    while os.path.exists(destination_path):
                        destination_path = os.path.join(count_subfolder, f"{base}_{counter}{extension}")
                        counter += 1
                try:
                    if nb_state.get((format_name, filename), False) and HAS_PIL and PILImage is not None and ImageOps is not None:
                        ext = os.path.splitext(filename)[1].lower()
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
                f.write(f"TOTAL : {total_price['value']:.2f} €\n")
        except OSError as write_error:
            errors.append(f"commande.txt: {write_error}")

        if errors:
            print(f"[ERREUR] Copie fichiers :\n" + "\n".join(errors))

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

        copied_count = len(selected_files) - len(errors)
        _cleanup_temp_dir()
        page.show_dialog(ft.SnackBar(
            ft.Text(
                f"✓  {copied_count} image(s) copiée(s) vers {selection_name}.",
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
    for format_name in SIZES:
        is_first = (format_name == current_size["value"])
        format_button = ft.Button(
            format_name,
            color=C_DARK if is_first else C_BLUE,
            bgcolor=C_BLUE if is_first else C_GREY,
            width=KIOSK_CONSTANT.LEFT_PANEL_WIDTH - 32,
            height=KIOSK_CONSTANT.FORMAT_BUTTON_HEIGHT,
            on_click=lambda e, s=format_name: on_size_select(s),
        )
        size_buttons_map[format_name] = format_button
        sizes_column.controls.append(format_button)

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
        icon_size=28,
        tooltip="Page précédente",
        on_click=lambda e: _go_to_page(kiosk_page["value"] - 1),
    )
    next_page_btn = ft.IconButton(
        icon=ft.Icons.CHEVRON_RIGHT,
        icon_color=C_BLUE,
        icon_size=28,
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
    left_panel = ft.Container(
        content=ft.Column([
            ft.Button(
                "OUVRIR",
                icon=ft.Icons.FOLDER_OPEN,
                color=C_DARK,
                bgcolor=C_VIOLET,
                width=KIOSK_CONSTANT.LEFT_PANEL_WIDTH - 32,
                height=KIOSK_CONSTANT.ACTION_BUTTON_HEIGHT,
                on_click=open_folder_dialog,
            ),
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

    async def _close_window():
        """Ferme la fenêtre proprement depuis le thread UI."""
        _cleanup_temp_dir()
        try:
            await page.window.close()
        except RuntimeError:
            pass

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
            ft.IconButton(
                icon=ft.Icons.CLOSE,
                icon_color=C_RED,
                icon_size=22,
                tooltip="Quitter",
                on_click=lambda e: page.run_task(_close_window),
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
