# -*- coding: utf-8 -*-
"""
Renumérote les pages exportées par Affinity avec des zéros de tête.

Affinity exporte les pages d'un document multi-pages avec le minimum de
chiffres nécessaire (nom_1.jpg, nom_2.jpg, ..., nom_10.jpg) — le tri
alphabétique place alors nom_10.jpg avant nom_2.jpg. Cet outil détecte
les séries "prefixe_numéro.ext" du dossier et ajoute les zéros de tête
qui manquent (nom_01.jpg, nom_02.jpg, ..., nom_10.jpg), sans jamais
réduire un padding déjà plus large que nécessaire.

Variables d'environnement :
  FOLDER_PATH — dossier source contenant les fichiers à renuméroter.

Dépendances : flet >= 0.21, modules standard (pathlib, re)
"""

__version__ = "1.0.0"

#############################################################
#                          IMPORTS                          #
#############################################################
import os
import re
import sys
import flet as ft
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import CONSTANTS

#############################################################
#                        CONSTANTES                         #
#############################################################
# Capture tout ce qui précède le DERNIER "_<chiffres>" du nom (sans
# extension) — c'est toujours ce numéro final qu'Affinity ajoute pour
# la page, quel que soit le contenu du préfixe.
PAGE_SUFFIX_RE = re.compile(r'^(.*)_(\d+)$')
MIN_DIGITS = 3  # nom_001.jpg au minimum, même pour une courte série (retour user)

#############################################################
#                        FLET MAIN                          #
#############################################################

async def main(page: ft.Page) -> None:
    page.title = "Renommer pages Affinity"
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
    ORANGE     = CONSTANTS.COLOR_ORANGE
    BLUE       = CONSTANTS.COLOR_BLUE

    # ── Récupération du dossier depuis l'environnement ────────────────────
    environment_folder = os.environ.get("FOLDER_PATH", "").strip()

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

    def run_renumber(e) -> None:
        if not source_folder or not source_folder.is_dir():
            status_label.value = "Dossier source introuvable."
            status_label.color = RED
            page.update()
            return

        files = sorted(
            entry for entry in source_folder.iterdir()
            if entry.is_file() and entry.suffix.lower() in CONSTANTS.IMAGE_EXTS
        )

        # (préfixe, extension) -> [(numéro, nb_chiffres_actuel, chemin), ...]
        groups: dict[tuple[str, str], list[tuple[int, int, Path]]] = {}
        for file_path in files:
            match = PAGE_SUFFIX_RE.match(file_path.stem)
            if not match:
                continue
            prefix, digits = match.group(1), match.group(2)
            key = (prefix, file_path.suffix)
            groups.setdefault(key, []).append(
                (int(digits), len(digits), file_path))

        renamed_count = 0
        skipped_count = 0
        for (prefix, ext), pages in groups.items():
            if len(pages) < 2:
                continue  # rien à départager sur une page seule
            # Minimum 3 chiffres (retour user) ; jamais réduire un padding
            # déjà plus large (ex. série déjà en 0001, 0002...), et jamais
            # moins que nécessaire pour le plus grand numéro de la série.
            width = max(
                MIN_DIGITS,
                len(str(max(number for number, _, _ in pages))),
                max(existing_width for _, existing_width, _ in pages),
            )
            for number, _existing_width, file_path in pages:
                new_name = f"{prefix}_{number:0{width}d}{file_path.suffix}"
                if new_name == file_path.name:
                    continue
                new_path = file_path.parent / new_name
                if new_path.exists():
                    skipped_count += 1
                    print(f"Ignoré (déjà existant) : {new_name}",
                         file=sys.stderr, flush=True)
                    continue
                file_path.rename(new_path)
                renamed_count += 1

        if renamed_count == 0 and skipped_count == 0:
            result_message = "Aucune série de pages à renuméroter."
            result_color = ORANGE
        else:
            parts = []
            if renamed_count:
                parts.append(f"{renamed_count} fichier(s) renommé(s)")
            if skipped_count:
                parts.append(f"{skipped_count} ignoré(s) (conflit)")
            result_message = " · ".join(parts)
            result_color = GREEN if renamed_count else ORANGE

        print(result_message, flush=True)
        status_label.value = result_message
        status_label.color = result_color
        page.update()

        page.run_task(_close)

    page.add(
        ft.Container(
            content=ft.Column([
                ft.Row([
                    ft.Icon(ft.Icons.FORMAT_LIST_NUMBERED, color=BLUE, size=24),
                    ft.Text(
                        "Renommer pages Affinity",
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
                        "Renuméroter",
                        icon=ft.Icons.FORMAT_LIST_NUMBERED,
                        bgcolor=BLUE, color=DARK,
                        style=ft.ButtonStyle(shape=ft.RoundedRectangleBorder(radius=8)),
                        on_click=run_renumber,
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
        run_renumber(None)


ft.run(main)
