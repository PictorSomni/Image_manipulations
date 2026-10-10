# -*- coding: utf-8 -*-
"""
Sépare les fichiers RAW et JPG d'un dossier dans des sous-dossiers dédiés.

Déplace tous les fichiers RAW dans ``DOSSIER/RAW/`` et tous les JPG/JPEG
dans ``DOSSIER/JPG/``. Les autres fichiers sont ignorés.

Variables d'environnement :
  FOLDER_PATH     — dossier source contenant les fichiers à séparer.
  SELECTED_FILES  — noms de fichiers (basenames) séparés par | (optionnel).

Dépendances : flet >= 0.21, modules standard (pathlib, shutil)
"""

__version__ = "2.8.6"

#############################################################
#                          IMPORTS                          #
#############################################################
import sys
import os
import shutil
import flet as ft
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import CONSTANTS

#############################################################
#                        CONSTANTES                         #
#############################################################
RAW_EXTENSIONS = {
    ".nef", ".cr2", ".cr3", ".arw", ".dng",
    ".orf", ".rw2", ".raf", ".pef", ".srw",
    ".3fr", ".x3f", ".mrw", ".nrw",
}
JPG_EXTENSIONS = {".jpg", ".jpeg"}

RAW_SUBFOLDER_NAME = "RAW"
JPG_SUBFOLDER_NAME = "JPG"

#############################################################
#                        FLET MAIN                          #
#############################################################

async def main(page: ft.Page) -> None:
    page.title = "Séparer RAW et JPG"
    page.theme_mode = ft.ThemeMode.DARK
    page.bgcolor = CONSTANTS.COLOR_DARK
    page.window.width = 560
    page.window.height = 240
    page.window.resizable = False
    page.window.title_bar_hidden = True
    page.window.title_bar_buttons_hidden = True
    page.horizontal_alignment = ft.CrossAxisAlignment.CENTER
    page.vertical_alignment = ft.MainAxisAlignment.CENTER

    DARK       = CONSTANTS.COLOR_DARK
    GREY       = CONSTANTS.COLOR_GREY
    LIGHT_GREY = CONSTANTS.COLOR_LIGHT_GREY
    GREEN      = CONSTANTS.COLOR_GREEN
    RED        = CONSTANTS.COLOR_RED
    WHITE      = CONSTANTS.COLOR_WHITE
    YELLOW     = CONSTANTS.COLOR_YELLOW
    BLUE       = CONSTANTS.COLOR_BLUE
    ORANGE     = CONSTANTS.COLOR_ORANGE

    # ── Récupération des chemins depuis l'environnement ───────────────────
    environment_folder         = os.environ.get("FOLDER_PATH", "").strip()
    environment_selected_files = os.environ.get("SELECTED_FILES", "").strip()

    source_folder: Path | None = (
        Path(environment_folder)
        if environment_folder and os.path.isdir(environment_folder)
        else None
    )

    # ── Widgets ───────────────────────────────────────────────────────────
    folder_label = ft.Text(
        str(source_folder) if source_folder else "Aucun dossier fourni",
        size=11,
        color=GREEN if source_folder else RED,
        overflow=ft.TextOverflow.ELLIPSIS,
        max_lines=1,
    )
    status_label = ft.Text(
        "", size=13, color=LIGHT_GREY, text_align=ft.TextAlign.CENTER
    )

    async def _close() -> None:
        try:
            await page.window.close()
        except RuntimeError:
            pass

    def run_separation(e) -> None:
        if not source_folder or not source_folder.is_dir():
            status_label.value = "Dossier source introuvable."
            status_label.color = RED
            page.update()
            return

        # Collecter les fichiers à traiter
        if environment_selected_files:
            files_to_process = [
                source_folder / filename
                for filename in environment_selected_files.split("|")
                if filename.strip() and (source_folder / filename.strip()).is_file()
            ]
        else:
            files_to_process = sorted(
                entry for entry in source_folder.iterdir() if entry.is_file()
            )

        if not files_to_process:
            status_label.value = "Aucun fichier à traiter."
            status_label.color = ORANGE
            page.update()
            return

        raw_destination = source_folder / RAW_SUBFOLDER_NAME
        jpg_destination = source_folder / JPG_SUBFOLDER_NAME

        raw_count    = 0
        jpg_count    = 0
        skipped_count = 0

        for file_path in files_to_process:
            extension = file_path.suffix.lower()
            if extension in RAW_EXTENSIONS:
                raw_destination.mkdir(parents=True, exist_ok=True)
                shutil.move(str(file_path), raw_destination / file_path.name)
                raw_count += 1
            elif extension in JPG_EXTENSIONS:
                jpg_destination.mkdir(parents=True, exist_ok=True)
                shutil.move(str(file_path), jpg_destination / file_path.name)
                jpg_count += 1
            else:
                skipped_count += 1

        summary_parts = []
        if raw_count:
            summary_parts.append(f"{raw_count} RAW → {RAW_SUBFOLDER_NAME}/")
        if jpg_count:
            summary_parts.append(f"{jpg_count} JPG → {JPG_SUBFOLDER_NAME}/")
        if skipped_count:
            summary_parts.append(f"{skipped_count} ignoré(s)")

        result_message = " · ".join(summary_parts) if summary_parts else "Aucun fichier RAW ou JPG trouvé."
        result_color   = GREEN if (raw_count or jpg_count) else ORANGE

        print(result_message, flush=True)
        status_label.value = result_message
        status_label.color = result_color
        page.update()

        page.run_task(_close)

    page.add(
        ft.Container(
            content=ft.Column([
                ft.Row([
                    ft.Icon(ft.Icons.DRIVE_FILE_MOVE, color=YELLOW, size=24),
                    ft.Text(
                        "Séparer RAW et JPG",
                        size=16, color=WHITE, weight=ft.FontWeight.W_600,
                    ),
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
                    ft.Icon(ft.Icons.FOLDER, color=BLUE, size=14),
                    ft.Container(content=folder_label, expand=True),
                ], spacing=6, vertical_alignment=ft.CrossAxisAlignment.CENTER),
                ft.Container(height=8),
                ft.Row([
                    ft.Button(
                        "Séparer",
                        icon=ft.Icons.DRIVE_FILE_MOVE,
                        bgcolor=YELLOW, color=DARK,
                        style=ft.ButtonStyle(shape=ft.RoundedRectangleBorder(radius=8)),
                        on_click=run_separation,
                    ),
                ], alignment=ft.MainAxisAlignment.CENTER),
                ft.Container(height=4),
                ft.Container(content=status_label, alignment=ft.Alignment.CENTER),
            ], spacing=6, horizontal_alignment=ft.CrossAxisAlignment.STRETCH),
            bgcolor=DARK,
            border_radius=10,
            border=ft.Border.all(1, GREY),
            padding=ft.Padding(28, 24, 28, 24),
            width=500,
        )
    )

    # Lancement automatique si le dossier est connu
    if source_folder:
        run_separation(None)


ft.run(main)
