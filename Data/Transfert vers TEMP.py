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

Dépendances : flet >= 0.84, modules standard (pathlib, shutil, datetime)
"""

__version__ = "3.0.0"

#############################################################
#                          IMPORTS                          #
#############################################################
from pathlib import Path
from shutil import copy2
from datetime import datetime
import sys
import os
import subprocess
sys.path.insert(0, str(Path(__file__).resolve().parent))
import CONSTANTS
import flet as ft

#############################################################
#                         CONSTANTS                         #
#############################################################
def _resolve_volume_path(p: Path) -> Path:
    """Sur macOS, résout le point de montage réel d'un volume réseau en lisant
    la table des montages (commande `mount`) — sans jamais accéder au filesystem,
    ce qui évite de déclencher la dialog d'authentification macOS.
    Gère le suffixe -1, -2… ajouté par macOS lors d'un double montage."""
    if sys.platform != "darwin":
        return p
    p_str = str(p)
    if not p_str.startswith("/Volumes/"):
        return p
    rest = p_str[len("/Volumes/"):]
    vol_name = rest.split("/")[0]
    sub_path = rest[len(vol_name):]
    try:
        import re as _re
        mount_out = subprocess.run(
            ["mount"], capture_output=True, text=True, timeout=3
        ).stdout
        for line in mount_out.splitlines():
            # Ligne type : //user@host/share on /Volumes/NOM (smbfs, ...)
            match = _re.match(r'^\S+\s+on\s+(/Volumes/[^(]+?)\s*\(', line)
            if not match:
                continue
            mount_point = match.group(1).rstrip()
            mp_vol = mount_point[len("/Volumes/"):]
            if mp_vol == vol_name or _re.match(
                rf'^{_re.escape(vol_name)}-\d+$', mp_vol
            ):
                return Path(mount_point + sub_path)
    except Exception:
        pass
    return p

DEFAULT_SOURCE = Path.home() / "Downloads"
DEFAULT_DEST   = _resolve_volume_path(Path(os.environ.get("DEST_FOLDER", CONSTANTS.TEMP_FOLDER)))
LAUNCHED_FROM_DASHBOARD = os.environ.get("LAUNCHED_FROM_DASHBOARD") == "1"
DELETE_AFTER_TRANSFER = os.environ.get("DELETE_AFTER_TRANSFER", "").strip() == "1"

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

# Le dialog de suppression est maintenant dans le Dashboard
# Pas de confirmation ici : supprimer silencieusement si DELETE_AFTER_TRANSFER=1

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
#                    SÉQUENCE DOSSIERS                      #
#############################################################
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
    page.run_task(page.window.to_front)


    source_label = ft.Text(str(DEFAULT_SOURCE), color=GREEN, size=12)
    # Sur macOS, ne pas appeler .exists() ici — déclenche la dialog auth sur les partages réseau.
    # La couleur sera mise à jour au moment de la copie.
    _dest_color = LIGHT_GREY if sys.platform == "darwin" else (GREEN if DEFAULT_DEST.exists() else RED)
    dest_label   = ft.Text(
        str(DEFAULT_DEST),
        color=_dest_color,
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

    def _next_sequence_path(base_path):
        """Détermine le prochain chemin de séquence sans le créer (lecture seule)."""
        today = datetime.now().strftime("%Y-%m-%d")
        date_folder = Path(base_path) / today
        seq = 1
        while (date_folder / f"{seq:02d}").exists():
            seq += 1
        return date_folder / f"{seq:02d}"

    async def run_copy(e):
        try:
            launch_button.disabled = True
            launch_button.update()

            # Re-résoudre le chemin destination au moment de la copie
            # (le volume macOS peut avoir été remonté avec un suffixe "-1" depuis le démarrage)
            dest = _resolve_volume_path(DEFAULT_DEST)
            if str(dest) != str(DEFAULT_DEST):
                dest_label.value = str(dest)
                dest_label.color = GREEN
                dest_label.update()

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

            progress_bar.visible = True
            progress_bar.value = 0
            progress_bar.update()

            total = len(source_files)
            try:
                dest_folder = get_next_sequence_folder(dest)
                for index, source_file in enumerate(source_files):
                    copy2(source_file, dest_folder / source_file.name)
                    progress_bar.value = (index + 1) / total
                    status_text.value = f"Copie : {index + 1}/{total} — {source_file.name}"
                    progress_bar.update()
                    status_text.update()
            except PermissionError:
                if sys.platform != "darwin":
                    raise
                status_text.value = "Droits insuffisants — authentification requise..."
                status_text.color = ORANGE
                status_text.update()
                dest_folder = _next_sequence_path(dest)
                def _q(p):
                    return "'" + str(p).replace("'", "'\\''")+"'"
                shell_script = " && ".join(
                    [f"mkdir -p {_q(dest_folder)}"] +
                    [f"cp {_q(f)} {_q(dest_folder / f.name)}" for f in source_files]
                )
                as_script = shell_script.replace("\\", "\\\\").replace('"', '\\"')
                proc = subprocess.run(
                    ["osascript", "-e",
                     f'do shell script "{as_script}" with administrator privileges'],
                    capture_output=True, text=True,
                )
                if proc.returncode != 0:
                    raise PermissionError(proc.stderr.strip() or "Accès refusé au dossier TEMP")
                progress_bar.value = 1.0
                progress_bar.update()

            progress_bar.visible = False
            progress_bar.update()

            # Suppression silencieuse si DELETE_AFTER_TRANSFER=1 (confirmé au Dashboard)
            # OU si aucun fichier n'était sélectionné au départ (on vide alors Downloads par défaut)
            if DELETE_AFTER_TRANSFER or not SOURCE_FILES_FROM_DASHBOARD:
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

    async def close_window(event):
        await page.window.close()
        os._exit(0)


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


if LAUNCHED_FROM_DASHBOARD:
    try:
        dest = _resolve_volume_path(DEFAULT_DEST)
        source_files = (
            SOURCE_FILES_FROM_DASHBOARD
            if SOURCE_FILES_FROM_DASHBOARD
            else [f for f in DEFAULT_SOURCE.iterdir() if f.is_file()]
        )
        if not source_files:
            print("[info] Aucun fichier à copier.", flush=True)
            sys.exit(0)
        dest_folder = get_next_sequence_folder(dest)
        for idx, f in enumerate(source_files, 1):
            copy2(f, dest_folder / f.name)
            print(f"Copie : {idx}/{len(source_files)} \u2014 {f.name}", flush=True)
        # Même logique de suppression pour le mode Dashboard direct
        if DELETE_AFTER_TRANSFER or not SOURCE_FILES_FROM_DASHBOARD:
            for f in source_files:
                f.unlink()
        print(f"[ok] {len(source_files)} fichier(s) copiés vers {dest_folder}", flush=True)
        print(f"NAVIGATE_TO:{dest_folder}", flush=True)
    except Exception as _e:
        print(f"[x] Erreur : {_e}", flush=True)
        sys.exit(1)
    sys.exit(0)

ft.run(main)