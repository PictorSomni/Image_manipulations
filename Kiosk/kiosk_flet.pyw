# -*- coding: utf-8 -*-
"""
Application kiosque de sélection d'impressions photo — Version Flet.

Remplace la version Qt6 originale (main.py) avec :
  - Interface plein écran Flet, palette de couleurs de Dashboard.pyw.
  - Grille d'images avec sélection de format et compteur d'impressions par photo.
  - Prévisualisation N&B par image (toggle par bouton).
  - Calcul du prix total en temps réel.
  - Validation et écriture d'un fichier commande.txt.

Dépendances : flet, Pillow (PIL)
"""

import flet as ft
import os
import sys
import io
import base64
import threading

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
    page.window.full_screen = True
    page.padding = 0
    page.update()

    # ── Tarifs et paramètres grille depuis Kiosk/CONSTANT.py ─────────────────
    SIZES: dict = KIOSK_CONSTANT.SIZES

    # ── État global ───────────────────────────────────────────────────────
    current_folder = {"path": ""}
    images_list: list[str] = []
    # prints_data[format][filename] = nombre de copies
    prints_data: dict[str, dict[str, int]] = {}
    current_size = {"value": list(SIZES.keys())[0]}
    total_price = {"value": 0.0}
    nb_state: dict[str, bool] = {}          # True = prévisualisation N&B active
    image_cards: dict[str, dict] = {}       # {filename: {card, count_text, image_ctrl, nb_button}}

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
        nb_state[filename] = not nb_state.get(filename, False)
        is_nb = nb_state[filename]
        card_data = image_cards[filename]

        # Feedback immédiat sur l'icône
        card_data["nb_button"].icon_color = C_VIOLET if is_nb else C_LIGHT_GREY
        card_data["nb_button"].update()

        file_path = os.path.join(current_folder["path"], filename)

        def _reload_thumbnail():
            b64 = _make_thumbnail_b64(file_path, grayscale=is_nb)
            if b64 is not None:
                card_data["image_ctrl"].src = f"data:image/jpeg;base64,{b64}"
            elif not is_nb:
                card_data["image_ctrl"].src = file_path

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
            "nb_active": nb_state.get(filename, False),
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
            b64 = _make_thumbnail_b64(
                _current_file_path(),
                grayscale=state["nb_active"],
                size=1024,
            )
            if b64 is not None:
                preview_img.src = f"data:image/jpeg;base64,{b64}"
            else:
                preview_img.src = _current_file_path()

            async def _apply():
                try:
                    page.update()
                except Exception:
                    pass

            page.run_task(_apply)

        def _navigate_to(new_filename: str) -> None:
            state["filename"] = new_filename
            state["nb_active"] = nb_state.get(new_filename, False)
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
            state["nb_active"] = nb_state.get(state["filename"], False)
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
    #  État de chargement des miniatures
    # ─────────────────────────────────────────────────────────────────────
    _loading_state: dict = {"total": 0, "loaded": 0}

    # ─────────────────────────────────────────────────────────────────────
    #  Construction d'une carte image
    # ─────────────────────────────────────────────────────────────────────

    def _build_image_card(filename: str) -> tuple[ft.Container, dict, object]:
        file_path = os.path.join(current_folder["path"], filename)

        _blank_gif = "data:image/gif;base64,R0lGODlhAQABAAD/ACwAAAAAAQABAAACADs="

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
            src=_blank_gif,
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

        # On ferme sur filename (valeur figée à chaque itération)
        nb_button.on_click = lambda e, f=filename: on_toggle_nb(f)

        # Chargement de la miniature en arrière-plan via PIL
        # NE PAS lancer le thread ici — il sera démarré par load_folder
        # après que les cartes aient été ajoutées à la page.
        def _load_thumb():
            b64 = _make_thumbnail_b64(file_path, grayscale=False)
            if b64 is not None:
                image_ctrl.src = f"data:image/jpeg;base64,{b64}"
            else:
                image_ctrl.src = file_path
            # Mise à jour de la barre de progression
            _loading_state["loaded"] += 1
            loaded = _loading_state["loaded"]
            total = _loading_state["total"]
            loading_label.value = f"Chargement {loaded} / {total}"
            if loaded >= total:
                loading_row.visible = False

            async def _apply():
                try:
                    page.update()
                except Exception:
                    pass

            page.run_task(_apply)

        # Nom affiché tronqué
        display_name = filename if len(filename) <= 18 else filename[:15] + "…"

        card = ft.Container(
            content=ft.Column([
                # Miniature cliquable
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
        return card, card_data, _load_thumb

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

        # Construction de la grille
        images_grid.controls.clear()
        images_grid.update()
        if images_list:
            _loading_state["total"] = len(images_list)
            _loading_state["loaded"] = 0
            loading_label.value = f"Chargement 0 / {len(images_list)}"
            loading_row.visible = True
            loading_row.update()
        thumb_loaders: list = []
        for entry_name in images_list:
            card, card_data, loader = _build_image_card(entry_name)
            image_cards[entry_name] = card_data
            images_grid.controls.append(card)
            thumb_loaders.append(loader)
        images_grid.update()  # cartes sur la page AVANT de lancer les threads
        for loader in thumb_loaders:
            threading.Thread(target=loader, daemon=True).start()

        _update_size_buttons()

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

        # Détermine quels fichiers ont au moins une copie dans n'importe quel format
        selected_files: set[str] = set()
        for format_name in SIZES:
            for filename, count in prints_data.get(format_name, {}).items():
                if count > 0:
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
        selection_dir = os.path.join(folder_path, "SELECTION")
        autres_dir = os.path.join(folder_path, "AUTRES")

        errors: list[str] = []
        try:
            os.makedirs(selection_dir, exist_ok=True)
            os.makedirs(autres_dir, exist_ok=True)
        except OSError as mkdir_error:
            page.show_dialog(ft.SnackBar(
                ft.Text(f"Erreur création dossiers : {mkdir_error}", color=C_RED),
                bgcolor=C_GREY,
                duration=4000,
                behavior=ft.SnackBarBehavior.FLOATING,
            ))
            return

        import shutil
        for filename in images_list:
            source_path = os.path.join(folder_path, filename)
            if not os.path.isfile(source_path):
                continue
            destination_dir = selection_dir if filename in selected_files else autres_dir
            destination_path = os.path.join(destination_dir, filename)
            # Évite d'écraser un fichier existant en ajoutant un suffixe
            if os.path.exists(destination_path):
                base, extension = os.path.splitext(filename)
                counter = 1
                while os.path.exists(destination_path):
                    destination_path = os.path.join(destination_dir, f"{base}_{counter}{extension}")
                    counter += 1
            try:
                shutil.move(source_path, destination_path)
            except OSError as move_error:
                errors.append(f"{filename}: {move_error}")

        if errors:
            print(f"[ERREUR] Déplacement fichiers :\n" + "\n".join(errors))

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

        moved_count = len(selected_files) - len(errors)
        page.show_dialog(ft.SnackBar(
            ft.Text(
                f"✓  {moved_count} image(s) déplacée(s) vers SELECTION.",
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
        ),
        bgcolor=C_DARK,
        padding=ft.Padding(10, 16, 10, 16),
        width=KIOSK_CONSTANT.LEFT_PANEL_WIDTH,
    )

    async def _close_window():
        """Ferme la fenêtre proprement depuis le thread UI."""
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
                    ft.Container(
                        content=images_grid,
                        expand=True,
                        bgcolor=C_BG,
                    ),
                ], expand=True, spacing=0),
            ], expand=True, spacing=0, vertical_alignment=ft.CrossAxisAlignment.START),
        ], expand=True, spacing=0)
    )


# ─────────────────────────────────────────────────────────────────────────────
#  Lancement
# ─────────────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    ft.run(main)
