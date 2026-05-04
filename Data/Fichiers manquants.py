# -*- coding: utf-8 -*-
"""
Compare deux répertoires et identifie les fichiers présents à la source mais absents
de la destination.

Lorsque lancé depuis le Dashboard, ``SELECTED_FILES`` doit contenir le chemin du
dossier de destination (passé en tant que sélection de dossier unique). Le script
affiche les fichiers manquants et les sélectionne automatiquement dans la preview
via le préfixe ``SELECTED_FILES:``.

Variables d'environnement :
  FOLDER_PATH     — dossier source (défaut : répertoire du script).
  SELECTED_FILES  — chemin du dossier de destination (fichier/dossier sélectionné).
"""

__version__ = "2.3.1"

ENV_SELECTED_FILES_KEY = "SELECTED_FILES"
OUTPUT_SELECTED_FILES_PREFIX = "SELECTED_FILES:"

#############################################################
#                          IMPORTS                          #
#############################################################
import sys
import flet as ft
from pathlib import Path
import os
import re
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import CONSTANTS

#############################################################
#                         HELPERS                           #
#############################################################
_COPIES_PREFIX_RE = re.compile(r'^\d+X_', re.IGNORECASE)

def strip_copies_prefix(name: str) -> str:
    """Supprime le préfixe de compteur d'impression (ex: '3X_') si présent."""
    return _COPIES_PREFIX_RE.sub('', name)

def _compare(source: Path, destination: Path) -> list[str]:
    """Retourne la liste des fichiers présents dans source mais absents de destination."""
    all_files = [file.name for file in sorted(source.iterdir()) if file.is_file()]
    dest_files = [file.name for file in sorted(destination.iterdir()) if file.is_file()]
    dest_basenames = {Path(strip_copies_prefix(f)).stem.lower() for f in dest_files}
    return [
        file for file in all_files
        if Path(file).stem.lower() not in dest_basenames
        and not file.startswith('.')
        and not file.endswith('.py')
    ]

#############################################################
#                        FLET MAIN                          #
#############################################################

async def main(page: ft.Page) -> None:
    page.title = "Fichiers manquants"
    page.theme_mode = ft.ThemeMode.DARK
    page.bgcolor = CONSTANTS.COLOR_DARK
    page.window.width = 580
    page.window.height = 360
    page.window.resizable = True
    page.window.title_bar_hidden = True
    page.window.title_bar_buttons_hidden = True
    page.horizontal_alignment = ft.CrossAxisAlignment.CENTER
    page.vertical_alignment = ft.MainAxisAlignment.CENTER

    DARK       = CONSTANTS.COLOR_DARK
    GREY       = CONSTANTS.COLOR_GREY
    LIGHT_GREY = CONSTANTS.COLOR_LIGHT_GREY
    VIOLET     = CONSTANTS.COLOR_VIOLET
    GREEN      = CONSTANTS.COLOR_GREEN
    RED        = CONSTANTS.COLOR_RED
    WHITE      = CONSTANTS.COLOR_WHITE
    YELLOW     = CONSTANTS.COLOR_YELLOW

    # ── Récupération des chemins depuis l'environnement ───────────────────
    env_source = os.environ.get("FOLDER_PATH", "").strip()
    env_dest   = os.environ.get("SELECTED_FILES", "").strip()

    source_path: Path | None = Path(env_source) if env_source and os.path.isdir(env_source) else None
    dest_path:   Path | None = None
    if env_dest:
        first_item = env_dest.split("|")[0]
        if os.path.isdir(first_item):
            dest_path = Path(first_item)
        elif source_path and os.path.isdir(source_path / first_item):
            dest_path = source_path / first_item

    # ── Widgets ───────────────────────────────────────────────────────────
    source_label = ft.Text(
        str(source_path) if source_path else "Aucun dossier sélectionné",
        size=12,
        color=GREEN if source_path else LIGHT_GREY,
        overflow=ft.TextOverflow.ELLIPSIS,
        max_lines=1,
    )
    dest_label = ft.Text(
        str(dest_path) if dest_path else "Aucun dossier sélectionné",
        size=12,
        color=GREEN if dest_path else LIGHT_GREY,
        overflow=ft.TextOverflow.ELLIPSIS,
        max_lines=1,
    )
    status_label = ft.Text("", size=12, color=LIGHT_GREY, text_align=ft.TextAlign.CENTER)

    async def pick_source(e) -> None:
        nonlocal source_path
        picked = await ft.FilePicker().get_directory_path(
            dialog_title="Sélectionner le dossier SOURCE",
            initial_directory=str(source_path) if source_path else None,
        )
        if picked:
            source_path = Path(picked)
            source_label.value = str(source_path)
            source_label.color = GREEN
            page.update()

    async def pick_dest(e) -> None:
        nonlocal dest_path
        picked = await ft.FilePicker().get_directory_path(
            dialog_title="Sélectionner le dossier DE COMPARAISON",
            initial_directory=str(source_path) if source_path else None,
        )
        if picked:
            dest_path = Path(picked)
            dest_label.value = str(dest_path)
            dest_label.color = GREEN
            page.update()

    def run_comparison(e) -> None:
        if not source_path or not source_path.is_dir():
            status_label.value = "Dossier source introuvable."
            status_label.color = RED
            page.update()
            return
        if not dest_path or not dest_path.is_dir():
            status_label.value = "Dossier de comparaison introuvable."
            status_label.color = RED
            page.update()
            return
        if source_path == dest_path:
            status_label.value = "Les deux dossiers doivent être différents."
            status_label.color = RED
            page.update()
            return

        missing_files = _compare(source_path, dest_path)
        missing_str = "|".join(missing_files)
        os.environ[ENV_SELECTED_FILES_KEY] = missing_str
        print(f"{len(missing_files)} fichier(s) manquant(s) dans {dest_path.name}.")
        print(f"{OUTPUT_SELECTED_FILES_PREFIX}{missing_str}")
        page.run_task(_close)

    async def _close() -> None:
        try:
            await page.window.close()
        except RuntimeError:
            pass

    page.add(
        ft.Container(
            content=ft.Column([
                ft.Row([
                    ft.Icon(ft.Icons.FIND_IN_PAGE, color=VIOLET, size=24),
                    ft.Text("Fichiers manquants", size=16, color=WHITE, weight=ft.FontWeight.W_600),
                    ft.Container(expand=True),
                    ft.IconButton(
                        icon=ft.Icons.CLOSE, icon_color=RED, icon_size=18,
                        tooltip="Fermer",
                        on_click=lambda e: page.run_task(_close),
                        style=ft.ButtonStyle(padding=ft.Padding.all(4)),
                    ),
                ], spacing=10, vertical_alignment=ft.CrossAxisAlignment.CENTER),
                ft.Divider(color=GREY, height=16),
                ft.Row([
                    ft.Container(content=source_label, expand=True),
                    ft.IconButton(
                        icon=ft.Icons.FOLDER_OPEN, icon_color=YELLOW,
                        tooltip="Dossier source",
                        on_click=pick_source,
                        style=ft.ButtonStyle(padding=ft.Padding.all(4)),
                    ),
                ], spacing=6, vertical_alignment=ft.CrossAxisAlignment.CENTER),
                ft.Row([
                    ft.Container(content=dest_label, expand=True),
                    ft.IconButton(
                        icon=ft.Icons.FOLDER_OPEN, icon_color=YELLOW,
                        tooltip="Dossier de comparaison",
                        on_click=pick_dest,
                        style=ft.ButtonStyle(padding=ft.Padding.all(4)),
                    ),
                ], spacing=6, vertical_alignment=ft.CrossAxisAlignment.CENTER),
                status_label,
                ft.Container(height=4),
                ft.Row([
                    ft.Button(
                        "Comparer",
                        icon=ft.Icons.COMPARE_ARROWS,
                        bgcolor=VIOLET, color=DARK,
                        style=ft.ButtonStyle(shape=ft.RoundedRectangleBorder(radius=8)),
                        on_click=run_comparison,
                    ),
                ], alignment=ft.MainAxisAlignment.CENTER),
            ], spacing=10, horizontal_alignment=ft.CrossAxisAlignment.STRETCH),
            bgcolor=DARK,
            border_radius=10,
            border=ft.Border.all(1, GREY),
            padding=ft.Padding(28, 24, 28, 24),
            width=520,
        )
    )

    # Démarrage auto selon ce qui est connu (lancé depuis Dashboard)
    if source_path and dest_path:
        run_comparison(None)
    elif source_path:
        async def _auto_pick_dest():
            await pick_dest(None)
        page.run_task(_auto_pick_dest)


ft.run(main)
