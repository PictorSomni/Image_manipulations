# -*- coding: utf-8 -*-
"""
Copie les fichiers RAW/NEF correspondant aux photos commandées via kiosk_flet
dans un sous-dossier ``NEFs/`` du dossier SELECTION concerné.

Fonctionnement :
  1. Détecte (ou demande) le dossier source contenant les fichiers RAW.
  2. Détecte (ou demande) le dossier SELECTION à cibler.
  3. Parcourt récursivement SELECTION pour collecter les noms de base uniques
     des images commandées.
  4. Localise les fichiers RAW correspondants dans le dossier source.
  5. Copie ces RAW dans ``SELECTION/NEFs/``.

Lorsque lancé depuis le Dashboard, ``FOLDER_PATH`` doit pointer vers le dossier
de la session (celui qui contient à la fois les JPEGs et les fichiers RAW).
Si ``SELECTED_FILES`` contient le chemin d'un dossier ``SELECTION*``, il est
utilisé directement sans demande supplémentaire.

Variables d'environnement :
  FOLDER_PATH     — dossier source contenant les fichiers RAW.
  SELECTED_FILES  — chemin optionnel vers le dossier SELECTION ciblé.
"""

__version__ = "2.3.2"

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
# Extensions RAW reconnues (insensible à la casse)
RAW_EXTENSIONS = {
    ".nef", ".cr2", ".cr3", ".arw", ".dng",
    ".orf", ".rw2", ".raf", ".pef", ".srw",
    ".3fr", ".x3f", ".mrw", ".nrw",
}

# Nom du sous-dossier de destination dans SELECTION
NEF_SUBFOLDER_NAME = "NEFs"

# Nom du fichier de commande à ignorer lors du scan
COMMANDE_FILENAME = "commande.txt"

#############################################################
#                         HELPERS                           #
#############################################################

def _find_selection_folders(source: Path) -> list[Path]:
    """Retourne les dossiers SELECTION* triés (SELECTION < SELECTION_2 < …)."""
    candidates = sorted(
        (entry for entry in source.iterdir()
         if entry.is_dir() and entry.name.upper().startswith("SELECTION")),
        key=lambda p: (len(p.name), p.name),
    )
    return candidates


def _collect_stems_from_selection(selection: Path) -> set[str]:
    """
    Parcourt récursivement le dossier SELECTION et retourne l'ensemble des
    noms de base (sans extension, en minuscules) des fichiers image trouvés.
    """
    stems: set[str] = set()
    for entry in selection.rglob("*"):
        if entry.is_file() and entry.name.lower() != COMMANDE_FILENAME:
            stems.add(entry.stem.lower())
    return stems


def _find_raw_files(source: Path, stems: set[str]) -> list[Path]:
    """
    Retourne les fichiers RAW situés directement dans ``source`` dont le nom
    de base (en minuscules) figure dans ``stems``.
    """
    raw_files: list[Path] = []
    for entry in sorted(source.iterdir()):
        if entry.is_file() and entry.suffix.lower() in RAW_EXTENSIONS:
            if entry.stem.lower() in stems:
                raw_files.append(entry)
    return raw_files


def _copy_raws(raw_files: list[Path], destination: Path) -> tuple[int, list[str]]:
    """
    Copie ``raw_files`` dans ``destination``.
    Retourne (nombre_copiés, liste_erreurs).
    """
    destination.mkdir(parents=True, exist_ok=True)
    copied = 0
    errors: list[str] = []
    for raw_path in raw_files:
        dest_path = destination / raw_path.name
        if dest_path.exists():
            errors.append(f"Déjà présent, ignoré : {raw_path.name}")
            continue
        try:
            shutil.copy2(raw_path, dest_path)
            copied += 1
        except OSError as copy_error:
            errors.append(f"{raw_path.name} : {copy_error}")
    return copied, errors

#############################################################
#                        FLET MAIN                          #
#############################################################

async def main(page: ft.Page) -> None:
    page.title = "Copier NEFs → SELECTION"
    page.theme_mode = ft.ThemeMode.DARK
    page.bgcolor = CONSTANTS.COLOR_DARK
    page.window.width = 600
    page.window.height = 400
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
    BLUE       = CONSTANTS.COLOR_BLUE

    # ── Récupération des chemins depuis l'environnement ───────────────────
    env_source      = os.environ.get("FOLDER_PATH", "").strip()
    env_selection   = os.environ.get("SELECTED_FILES", "").strip()

    source_path: Path | None = (
        Path(env_source) if env_source and os.path.isdir(env_source) else None
    )
    selection_path: Path | None = None

    # SELECTED_FILES peut pointer directement sur un dossier SELECTION*
    if env_selection:
        first_item = env_selection.split("|")[0].strip()
        if os.path.isdir(first_item) and Path(first_item).name.upper().startswith("SELECTION"):
            selection_path = Path(first_item)

    # Si pas fourni explicitement, tenter l'auto-détection depuis source
    if selection_path is None and source_path and source_path.is_dir():
        candidates = _find_selection_folders(source_path)
        if candidates:
            selection_path = candidates[-1]  # la plus récente

    # ── État ─────────────────────────────────────────────────────────────
    state = {
        "source":    source_path,
        "selection": selection_path,
    }

    # ── Widgets ───────────────────────────────────────────────────────────
    source_label = ft.Text(
        str(state["source"]) if state["source"] else "Aucun dossier sélectionné",
        size=12,
        color=GREEN if state["source"] else LIGHT_GREY,
        overflow=ft.TextOverflow.ELLIPSIS,
        max_lines=1,
    )
    selection_label = ft.Text(
        str(state["selection"]) if state["selection"] else "Aucun dossier SELECTION détecté",
        size=12,
        color=GREEN if state["selection"] else LIGHT_GREY,
        overflow=ft.TextOverflow.ELLIPSIS,
        max_lines=1,
    )
    status_label = ft.Text("", size=12, color=LIGHT_GREY, text_align=ft.TextAlign.CENTER)

    def _refresh_labels() -> None:
        source_label.value = str(state["source"]) if state["source"] else "Aucun dossier sélectionné"
        source_label.color = GREEN if state["source"] else LIGHT_GREY
        selection_label.value = str(state["selection"]) if state["selection"] else "Aucun dossier SELECTION détecté"
        selection_label.color = GREEN if state["selection"] else LIGHT_GREY
        page.update()

    async def pick_source(e) -> None:
        picked = await ft.FilePicker().get_directory_path(
            dialog_title="Dossier source (contenant les NEFs)",
            initial_directory=str(state["source"]) if state["source"] else None,
        )
        if picked:
            state["source"] = Path(picked)
            # Relancer l'auto-détection de SELECTION
            if state["selection"] is None:
                candidates = _find_selection_folders(state["source"])
                if candidates:
                    state["selection"] = candidates[-1]
            _refresh_labels()

    async def pick_selection(e) -> None:
        picked = await ft.FilePicker().get_directory_path(
            dialog_title="Dossier SELECTION ciblé",
            initial_directory=str(state["source"]) if state["source"] else None,
        )
        if picked:
            state["selection"] = Path(picked)
            _refresh_labels()

    def run_copy(e) -> None:
        if not state["source"] or not state["source"].is_dir():
            status_label.value = "Dossier source introuvable."
            status_label.color = RED
            page.update()
            return
        if not state["selection"] or not state["selection"].is_dir():
            status_label.value = "Dossier SELECTION introuvable."
            status_label.color = RED
            page.update()
            return

        stems = _collect_stems_from_selection(state["selection"])
        if not stems:
            status_label.value = "Aucune photo trouvée dans SELECTION."
            status_label.color = RED
            page.update()
            return

        raw_files = _find_raw_files(state["source"], stems)
        if not raw_files:
            status_label.value = f"Aucun fichier RAW correspondant trouvé ({len(stems)} photo(s) cherchée(s))."
            status_label.color = RED
            page.update()
            return

        destination = state["selection"] / NEF_SUBFOLDER_NAME
        copied, errors = _copy_raws(raw_files, destination)

        summary_parts = [f"{copied} NEF(s) copiés → {state['selection'].name}/NEFs/"]
        if errors:
            summary_parts.append(f"{len(errors)} ignoré(s) ou erreur(s).")
            for error_line in errors:
                print(f"[WARN] {error_line}")
        print(" ".join(summary_parts))

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
                    ft.Icon(ft.Icons.PHOTO_CAMERA, color=VIOLET, size=24),
                    ft.Text("Copier NEFs → SELECTION", size=16, color=WHITE, weight=ft.FontWeight.W_600),
                    ft.Container(expand=True),
                    ft.IconButton(
                        icon=ft.Icons.CLOSE, icon_color=RED, icon_size=18,
                        tooltip="Fermer",
                        on_click=lambda e: page.run_task(_close),
                        style=ft.ButtonStyle(padding=ft.Padding.all(4)),
                    ),
                ], spacing=10, vertical_alignment=ft.CrossAxisAlignment.CENTER),
                ft.Divider(color=GREY, height=16),
                # Source (NEFs)
                ft.Row([
                    ft.Icon(ft.Icons.FOLDER, color=BLUE, size=16),
                    ft.Text("Source (NEFs)", size=12, color=LIGHT_GREY, width=90),
                    ft.Container(content=source_label, expand=True),
                    ft.IconButton(
                        icon=ft.Icons.FOLDER_OPEN, icon_color=YELLOW,
                        tooltip="Choisir le dossier source",
                        on_click=pick_source,
                        style=ft.ButtonStyle(padding=ft.Padding.all(4)),
                    ),
                ], spacing=6, vertical_alignment=ft.CrossAxisAlignment.CENTER),
                # SELECTION
                ft.Row([
                    ft.Icon(ft.Icons.FOLDER_SPECIAL, color=VIOLET, size=16),
                    ft.Text("SELECTION", size=12, color=LIGHT_GREY, width=90),
                    ft.Container(content=selection_label, expand=True),
                    ft.IconButton(
                        icon=ft.Icons.FOLDER_OPEN, icon_color=YELLOW,
                        tooltip="Choisir le dossier SELECTION",
                        on_click=pick_selection,
                        style=ft.ButtonStyle(padding=ft.Padding.all(4)),
                    ),
                ], spacing=6, vertical_alignment=ft.CrossAxisAlignment.CENTER),
                status_label,
                ft.Container(height=4),
                ft.Row([
                    ft.Button(
                        "Copier les NEFs",
                        icon=ft.Icons.COPY,
                        bgcolor=VIOLET, color=DARK,
                        style=ft.ButtonStyle(shape=ft.RoundedRectangleBorder(radius=8)),
                        on_click=run_copy,
                    ),
                ], alignment=ft.MainAxisAlignment.CENTER),
            ], spacing=10, horizontal_alignment=ft.CrossAxisAlignment.STRETCH),
            bgcolor=DARK,
            border_radius=10,
            border=ft.Border.all(1, GREY),
            padding=ft.Padding(28, 24, 28, 24),
            width=540,
        )
    )

    # Lancement automatique si tout est connu
    if state["source"] and state["selection"]:
        run_copy(None)


ft.run(main)
