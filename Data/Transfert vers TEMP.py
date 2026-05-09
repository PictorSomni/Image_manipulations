# -*- coding: utf-8 -*-
"""
Interface graphique Flet pour transférer des fichiers vers le dossier TEMP daté/séquentiel.

Copie les fichiers vers un sous-dossier ``DEST/YYYY-MM-DD/NN/`` (date du jour +
séquence automatique), puis supprime les fichiers sources après copie réussie.

Source :
  - Si lancé depuis le Dashboard avec ``SOURCE_FILES``, utilise ces fichiers/dossiers.
  - Sinon, utilise le dossier Téléchargements.

Destination : toujours ``CONSTANTS.TEMP_FOLDER`` (surchargeable via DEST_FOLDER).

Lorsque lancé depuis le Dashboard (``LAUNCHED_FROM_DASHBOARD=1``), la copie
démarre automatiquement et la fenêtre se ferme à la fin.

Variables d'environnement :
  DEST_FOLDER              — chemin du dossier destination (défaut : CONSTANTS.TEMP_FOLDER).
  LAUNCHED_FROM_DASHBOARD  — ``"1"`` si lancé via le Dashboard.
  SOURCE_FILES             — chemins complets séparés par | (fichiers ou dossiers).

Dépendances : flet >= 0.21, modules standard (pathlib, shutil, datetime)
"""

__version__ = "2.4.0"

#############################################################
#                          IMPORTS                          #
#############################################################
from pathlib import Path
from shutil import copy2
from datetime import datetime
import sys
import os
sys.path.insert(0, str(Path(__file__).resolve().parent))
import CONSTANTS
import flet as ft

#############################################################
#                         CONSTANTS                         #
#############################################################
DEFAULT_SOURCE = Path.home() / "Downloads"
DEFAULT_DEST   = Path(os.environ.get("DEST_FOLDER", CONSTANTS.TEMP_FOLDER))
LAUNCHED_FROM_DASHBOARD = os.environ.get("LAUNCHED_FROM_DASHBOARD") == "1"

# Fichiers/dossiers spécifiques passés par le Dashboard (chemins complets séparés par |)
_SOURCE_FILES_ENV = os.environ.get("SOURCE_FILES", "")
SOURCE_FILES_FROM_DASHBOARD: list = []
if _SOURCE_FILES_ENV:
    for _p in _SOURCE_FILES_ENV.split("|"):
        _path = Path(_p)
        if _path.is_dir():
            SOURCE_FILES_FROM_DASHBOARD.extend(f for f in _path.iterdir() if f.is_file())
        elif _path.is_file():
            SOURCE_FILES_FROM_DASHBOARD.append(_path)

# Colors
DARK       = CONSTANTS.COLOR_DARK
BG         = CONSTANTS.COLOR_BACKGROUND
LIGHT_GREY = CONSTANTS.COLOR_LIGHT_GREY
BLUE       = CONSTANTS.COLOR_BLUE
GREEN      = CONSTANTS.COLOR_GREEN
ORANGE     = CONSTANTS.COLOR_ORANGE
RED        = CONSTANTS.COLOR_RED
WHITE      = CONSTANTS.COLOR_WHITE

#############################################################
#                           MAIN                            #
#############################################################
def main(page: ft.Page):
    page.title = "Transfert vers TEMP"
    page.theme_mode = ft.ThemeMode.DARK
    page.bgcolor = BG
    page.window.title_bar_hidden = True
    page.window.title_bar_buttons_hidden = True
    page.window.width = 560
    page.window.height = 260
    page.window.resizable = False
    page.horizontal_alignment = ft.CrossAxisAlignment.CENTER
    page.vertical_alignment = ft.MainAxisAlignment.START

    source_label = ft.Text(str(DEFAULT_SOURCE), color=GREEN, size=12)
    dest_label   = ft.Text(
        str(DEFAULT_DEST),
        color=GREEN if DEFAULT_DEST.exists() else RED,
        size=12,
    )
    status_text  = ft.Text(
        "Copie en cours..." if LAUNCHED_FROM_DASHBOARD else "",
        color=BLUE, size=14,
    )
    progress_bar = ft.ProgressBar(
        width=400, color=ORANGE, bgcolor=LIGHT_GREY,
        visible=LAUNCHED_FROM_DASHBOARD,
    )
    launch_button = ft.Button(
        "Lancer la copie",
        icon=ft.Icons.COPY,
        color=DARK, bgcolor=BLUE,
        style=ft.ButtonStyle(
            padding=20,
            text_style=ft.TextStyle(size=18, weight=ft.FontWeight.BOLD),
        ),
        height=60, width=250,
        visible=not LAUNCHED_FROM_DASHBOARD,
    )

    def get_next_sequence_folder(base_path):
        today = datetime.now().strftime("%Y-%m-%d")
        date_folder = Path(base_path) / today
        date_folder.mkdir(parents=True, exist_ok=True)
        sequence_number = 1
        while True:
            sequence_folder = date_folder / f"{sequence_number:02d}"
            if not sequence_folder.exists():
                sequence_folder.mkdir(parents=True, exist_ok=True)
                return sequence_folder
            sequence_number += 1

    async def run_copy(e):
        try:
            launch_button.disabled = True
            launch_button.update()

            status_text.value = "Analyse du dossier source..."
            status_text.color = BLUE
            status_text.update()

            source_files = (
                SOURCE_FILES_FROM_DASHBOARD
                if SOURCE_FILES_FROM_DASHBOARD
                else [f for f in DEFAULT_SOURCE.iterdir() if f.is_file()]
            )

            if not source_files:
                status_text.value = "Aucun fichier à copier."
                status_text.color = RED
                status_text.update()
                launch_button.disabled = False
                launch_button.update()
                return

            dest_folder = get_next_sequence_folder(DEFAULT_DEST)
            progress_bar.visible = True
            progress_bar.value = 0
            progress_bar.update()

            total = len(source_files)
            for index, source_file in enumerate(source_files):
                copy2(source_file, dest_folder / source_file.name)
                progress_bar.value = (index + 1) / total
                status_text.value = f"Copie : {index + 1}/{total} — {source_file.name}"
                progress_bar.update()
                status_text.update()

            progress_bar.visible = False
            progress_bar.update()

            for source_file in source_files:
                source_file.unlink()

            print(f"[ok] {total} fichier(s) copiés vers {dest_folder}", flush=True)
            print(f"NAVIGATE_TO:{dest_folder}", flush=True)
            status_text.value = f"Terminé — {total} fichier(s) transféré(s)"
            status_text.color = GREEN
            status_text.update()

            if LAUNCHED_FROM_DASHBOARD:
                await page.window.close()

        except Exception as error:
            progress_bar.visible = False
            progress_bar.update()
            print(f"[x] Erreur : {error}", flush=True)
            status_text.value = f"Erreur : {error}"
            status_text.color = RED
            status_text.update()

        finally:
            launch_button.disabled = False
            launch_button.update()

    launch_button.on_click = run_copy

    async def close_window(e):
        await page.window.close()

    if LAUNCHED_FROM_DASHBOARD:
        page.run_task(run_copy, None)

    page.add(
        ft.WindowDragArea(
            ft.Row([
                ft.Container(ft.Text("Transfert vers TEMP", color=WHITE), bgcolor=BG, padding=10),
                ft.Container(expand=True),
                ft.IconButton(ft.Icons.CLOSE, on_click=close_window),
            ])
        ),
        ft.Container(
            content=ft.Column([
                ft.Row([
                    ft.Text("Source :", color=LIGHT_GREY, size=12, width=80),
                    source_label,
                ]),
                ft.Row([
                    ft.Text("Destination :", color=LIGHT_GREY, size=12, width=80),
                    dest_label,
                ]),
                ft.Container(
                    content=ft.Row([launch_button], alignment=ft.MainAxisAlignment.CENTER),
                    alignment=ft.Alignment.CENTER,
                    padding=ft.Padding.symmetric(vertical=6),
                ),
                ft.Container(content=progress_bar, alignment=ft.Alignment.CENTER),
                ft.Container(content=status_text, alignment=ft.Alignment.CENTER),
            ], spacing=8),
            padding=20,
        ),
    )


ft.run(main)

