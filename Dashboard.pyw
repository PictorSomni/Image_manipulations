# -*- coding: utf-8 -*-
"""
Tableau de bord principal de l'application Image Manipulations.

Ce module fournit une interface graphique Flet permettant de :
  - Sélectionner un dossier de travail et parcourir son contenu
    dans un panneau de prévisualisation avec chargement paresseux des miniatures.
  - Lancer les scripts de traitement d'images du répertoire ``Data/``
    en tant que sous-processus Python isolés, avec injection automatique des
    variables d'environnement requises (``FOLDER_PATH``, ``DATA_PATH``, etc.).
  - Afficher la sortie standard / erreur de chaque script dans un terminal
    intégré mis à jour en temps réel.
  - Effectuer des opérations sur fichiers : sélection par checkbox, copier/
    coller, suppression avec confirmation, création de dossier.

Raccourcis clavier :
  Ctrl/Cmd+C  — copier les fichiers sélectionnés dans le presse-papiers interne.
  Ctrl/Cmd+V  — coller dans le dossier actuel.
  Ctrl/Cmd+N  — créer un nouveau dossier.

Dépendances :
  flet >= 0.80, modules standard (os, subprocess, sys, platform, shutil,
  threading, re, zipfile, time).
"""

__version__ = "2.0.4"

#############################################################
#                          IMPORTS                          #
#############################################################
import flet as ft
import os
import subprocess
import sys
import platform
import shutil
import threading
import re
import zipfile
import json
import asyncio
import time
import hashlib
try:
    from PIL import Image as _PILImage
except ImportError:
    _PILImage = None

#############################################################
#                         CONSTANTS                         #
#############################################################
_IMAGE_VIEWER_EXTS = {".jpg", ".jpeg", ".png", ".gif", ".bmp", ".webp", ".ico", ".tiff", ".tif"}

_FILTER_CATEGORIES = {
    "images": {".jpg", ".jpeg", ".png", ".gif", ".bmp", ".webp", ".ico", ".tiff", ".tif", ".raw", ".cr2", ".nef", ".arw", ".dng"},
    "videos": {".mp4", ".mov", ".avi", ".mkv", ".mts", ".m2ts", ".wmv", ".mpg", ".mpeg"},
    "zip":    {".zip", ".rar", ".7z", ".tar", ".gz"},
    "docs":   {".pdf",".txt", ".md", ".log", ".csv", ".xml", ".json", ".odt", ".docx", ".xlsx", ".pptx", ".doc", ".xls", ".ppt"},
}

_OS_JUNK = {
    ".ds_store", "thumbs.db", "thumbs.db:encryptable",
    "ehthumbs.db", "ehthumbs_vista.db", "desktop.ini",
    ".directory", ".spotlight-v100", ".trashes",
}

def _is_os_junk(entry):
    """Retourne True si l'entrée est un fichier système à ignorer."""
    name_lower = entry.name.lower()
    return (
        name_lower in _OS_JUNK
        or name_lower.startswith("._")
        or entry.name == "$RECYCLE.BIN"
        or (entry.name.startswith(".Trash-") and entry.is_dir())
    )

#############################################################
#                           MAIN                            #
#############################################################
def main(page: ft.Page):
    """
    Point d'entrée Flet du Dashboard.

    Configure la fenêtre principale (titre, thème, dimensions, barre de titre
    personnalisée), initialise toutes les variables d'état, enregistre les
    canaux PubSub et construit l'interface avec trois zones :
      - Grille « Applications disponibles » (gauche).
      - Panneau de prévisualisation du contenu du dossier sélectionné (droite).
      - Terminal intégré affichant la sortie des scripts (bas).

    Parameters
    ----------
    page : ft.Page
        Objet page Flet injecté automatiquement par ``ft.run(main)``.

    ---
    PubSub (publish/subscribe) est un système de messagerie interne
    qui permet la communication thread-safe entre les threads de fond
    (scan, lecture de processus) et le thread UI de Flet :
    les threads publient des messages sur des "canaux" nommés
    (ex. "terminal", "refresh", "navigate"), et les callbacks abonnés les reçoivent
    et mettent à jour l'interface.
    ---
    """
# ===================== COLORS ===================== #
    DARK = "#222429"
    BG = "#373d4a"
    GREY = "#2C3038"
    LIGHT_GREY = "#9399A6"
    BLUE = "#45B8F5"
    VIOLET = "#B587FE"
    GREEN = "#49B76C"
    YELLOW = "#FBCD5F"
    HOVER_YELLOW = "#F9BA4E"
    ORANGE = "#FFA071"
    RED = "#F17171"
    WHITE = "#c7ccd8"

# ===================== PROPERTIES ===================== #
    page.title = "Dashboard - Image Manipulations"
    page.theme_mode = ft.ThemeMode.DARK
    page.bgcolor = BG
    page.window.title_bar_hidden = True
    page.window.title_bar_buttons_hidden = True
    page.window.width = 1600
    page.window.height = 900
    selected_folder = {"path": None}
    current_browse_folder = {"path": None}
    cwd = os.path.dirname(os.path.abspath(__file__))
    selected_files = set()  # Ensemble des fichiers sélectionnés
    clipboard = {"files": [], "cut": False}  # Presse-papiers pour copier/coller/couper des fichiers

    # ── Dossiers récents ──────────────────────────────────────────────
    _recent_path = os.path.join(cwd, ".recent_folders.json")

    def _load_recent() -> list:
        try:
            with open(_recent_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            return [p for p in data if os.path.isdir(p)]
        except Exception:
            return []

    def _save_recent(folders: list) -> None:
        try:
            with open(_recent_path, "w", encoding="utf-8") as f:
                json.dump(folders[:10], f, ensure_ascii=False, indent=2)
        except Exception:
            pass

    def _add_to_recent(path: str) -> None:
        path = os.path.normpath(path)
        recent = _load_recent()
        if path in recent:
            recent.remove(path)
        recent.insert(0, path)
        _save_recent(recent[:10])

    # ── Dossiers favoris ──────────────────────────────────────────────
    _favorites_path = os.path.join(cwd, ".favorites.json")
    # ── Programmes "Ouvrir avec" ──────────────────────────────────────
    _open_with_config_path = os.path.join(cwd, "open_with.json")

    def _load_favorites() -> list:
        try:
            with open(_favorites_path, "r", encoding="utf-8") as f:
                return [p for p in json.load(f) if isinstance(p, str)]
        except Exception:
            return []

    def _save_favorites(folders: list) -> None:
        try:
            with open(_favorites_path, "w", encoding="utf-8") as f:
                json.dump(folders, f, ensure_ascii=False, indent=2)
        except Exception:
            pass

    # Configuration: nom du fichier -> True si l'app est locale (pas besoin de dossier sélectionné)
    apps = {
        "N&B.py": (False, WHITE),
        "Fichiers manquants.py": (False, ORANGE),
        "Transfert vers TEMP.py": (True, BLUE),
        "Ameliorer nettete.py": (False, WHITE),
        "Renommer sequence.py": (False, BLUE),
        "Conversion JPG.py": (False, BLUE),
        "Nettoyer metadonnees.py": (False, RED),
        "Remerciements.py": (False, VIOLET),
        "Recadrage.pyw": (False, BLUE),
        "Redimensionner filigrane.py": (False, WHITE),
        "Images en PDF.py": (False, GREEN),
        "Redimensionner.py": (False, WHITE),
        "Format 13x10.py": (False, WHITE),
        "Augmentation IA.py": (False, GREEN),
        "Format 13x15.py": (False, WHITE),
    }
    
    resize_size = {"value": "640"}  # Taille par défaut pour le redimensionnement
    resize_watermark_size = {"value": "640"}  # Taille par défaut pour le redimensionnement avec watermark
    sort_mode = {"value": 0}  # 0 = A→Z, 1 = Z→A, 2 = par date de modification
    filter_type = {"value": "all"}  # "all", "images", "videos", "zip", "docs", "other"
    _removable_drives = {"list": []}  # [(name, path), ...]
    lazy_images = []  # [(list_index, file_path, image_ctrl)] pour le chargement paresseux
    PAGE_SIZE = 100             # Nb d'éléments max par page dans la prévisualisation
    preview_page = {"value": 0}  # Page courante (0-indexé)
    all_entries_data = {"list": [], "error": ""}  # Données brutes du dernier scan
    _pending_selection = {"names": None}  # Noms à sélectionner après le prochain scan
    ITEM_HEIGHT = 44             # hauteur approx. d'un ListTile dense avec thumbnail 40px
    _refresh_token = {"v": 0}   # incrémenté à chaque refresh pour annuler les anciens threads

# ===================== UI ELEMENTS ===================== #
    folder_path = ft.TextField(
        label="Dossier sélectionné",
        hint_text="Cliquez sur Parcourir... ou collez un chemin",
        width=300,
        bgcolor=DARK,
        border_color=GREY,
    )
    recent_folders_btn = ft.PopupMenuButton(
        icon=ft.Icons.HISTORY,
        icon_color=LIGHT_GREY,
        tooltip="Dossiers récents",
        items=[],
    )
    apps_list = ft.Column(expand=True, spacing=8)
    preview_list = ft.ListView(expand=True, auto_scroll=False, spacing=4)
    preview_loading = ft.Container(
        content=ft.Row([
            ft.ProgressRing(width=16, height=16, stroke_width=2, color=BLUE),
            ft.Text("Chargement...", size=12, color=LIGHT_GREY),
        ], spacing=8, alignment=ft.MainAxisAlignment.CENTER),
        alignment=ft.Alignment(0, 0),
        expand=True,
        visible=False,
    )
    terminal_output = ft.ListView(expand=True, spacing=2, auto_scroll=True)
    file_count_text = ft.Text("", size=14, color=WHITE, text_align=ft.TextAlign.RIGHT)
    selection_count_text = ft.Text("", size=14, color=BLUE, text_align=ft.TextAlign.RIGHT)
    _select_toggle_btn = ft.IconButton(
        icon=ft.Icons.SELECT_ALL,
        icon_color=VIOLET,
        icon_size=22,
        tooltip="Tout sélectionner",
    )
    _invert_selection_btn = ft.IconButton(
        icon=ft.Icons.PUBLISHED_WITH_CHANGES,
        icon_color=VIOLET,
        icon_size=22,
        tooltip="Inverser la sélection",
    )
    sort_segment = ft.CupertinoSlidingSegmentedButton(
        selected_index=0,
        bgcolor=GREY,
        thumb_color=DARK,
        controls=[
            ft.Text("A→Z",  size=11, color=WHITE),
            ft.Text("Z→A",  size=11, color=WHITE),
            ft.Text("Date", size=11, color=WHITE),
        ],
        tooltip="Tri alphabétique (A→Z / Z→A) ou par date de modification",
    )
    prev_page_btn = ft.IconButton(
        icon=ft.Icons.CHEVRON_LEFT, icon_size=18, icon_color=DARK, bgcolor=YELLOW,
        tooltip="Page précédente", visible=False, hover_color=HOVER_YELLOW
    )
    next_page_btn = ft.IconButton(
        icon=ft.Icons.CHEVRON_RIGHT, icon_size=18, icon_color=DARK, bgcolor=YELLOW,
        tooltip="Page suivante", visible=False, hover_color=HOVER_YELLOW
    )
    page_indicator_text = ft.Text("", size=12, color=LIGHT_GREY)
    selected_files_prefix = "SELECTED_FILES:"

    # ── Champs de saisie Redimensionner ──────────────────────────────
    resize_input = ft.TextField(
        value="640",
        width=80,
        height=35,
        text_size=13,
        text_align=ft.TextAlign.CENTER,
        keyboard_type=ft.KeyboardType.NUMBER,
        border_color=BLUE,
        content_padding=ft.Padding(5, 5, 5, 5),
    )
    resize_watermark_input = ft.TextField(
        value="640",
        width=80,
        height=35,
        text_size=13,
        text_align=ft.TextAlign.CENTER,
        keyboard_type=ft.KeyboardType.NUMBER,
        border_color=ORANGE,
        content_padding=ft.Padding(5, 5, 5, 5),
    )
    # ── Filtre de types de fichiers ──────────────────────────────────
    _FILTER_LABELS = ["Tous", "Images", "ZIP", "Docs", "Autres"]
    _FILTER_KEYS   = ["all",  "images", "zip", "docs", "other"]
    filter_segment = ft.CupertinoSlidingSegmentedButton(
        selected_index=0,
        bgcolor=GREY,
        thumb_color=DARK,
        controls=[
            ft.Text(lbl, size=11, color=WHITE) for lbl in ["Tous", "Images", "ZIP", "Docs", "Autres"]
        ],
        tooltip="Filtrer les fichiers par type",
    )
    # ── Section favoris ──────────────────────────────────────────────
    _favorites_list_col = ft.ReorderableListView(expand=True, spacing=2, auto_scroll=False, padding=ft.Padding(12, 6, 12, 6), show_default_drag_handles=False)
    _favorites_container = ft.Container(
        content=ft.Column([
            ft.Row([
                ft.Icon(ft.Icons.STAR, size=14, color=BLUE),
                ft.Text("Favoris", size=14, color=BLUE, weight=ft.FontWeight.BOLD),
                ft.Container(expand=True),
                ft.Container(
                    content=ft.Icon(ft.Icons.ADD, size=13, color=DARK),
                    bgcolor=BLUE,
                    border_radius=10,
                    padding=ft.Padding(3, 1, 3, 1),
                    tooltip="Ajouter le dossier courant aux favoris",
                    on_click=lambda e: _add_favorite_current(),
                    ink=True,
                ),
            ], spacing=6, tight=True, vertical_alignment=ft.CrossAxisAlignment.CENTER),
            _favorites_list_col,
        ], spacing=4, expand=True),
        bgcolor=GREY,
        border=ft.Border.all(1, BLUE),
        border_radius=6,
        padding=ft.Padding(12, 6, 12, 6),
        expand=True,
    )
    # ── Section périphériques amovibles ──────────────────────────────
    _drives_column = ft.ReorderableListView(expand=True, spacing=4, auto_scroll=False, padding=ft.Padding(12, 6, 12, 6), show_default_drag_handles=False)
    _drives_container = ft.Container(
        content=ft.Column([
            ft.Row([
                ft.Icon(ft.Icons.USB, size=14, color=VIOLET),
                ft.Text("Périphériques détectés", size=14, color=VIOLET,
                        weight=ft.FontWeight.BOLD),
            ], spacing=6, tight=True),
            _drives_column,
        ], spacing=4, expand=True),
        bgcolor=GREY,
        border=ft.Border.all(1, VIOLET),
        border_radius=6,
        padding=ft.Padding(12, 6, 12, 6),
        expand=True,
        visible=False,
    )

# ===================== METHODS ===================== #
    # ================================================================ #
    #                    PUBSUB & ÉVÉNEMENTS                           #
    # ================================================================ #
    def on_terminal_message(topic, message):
        """Callback pour les messages pubsub"""
        try:
            msg, color = message
            terminal_output.controls.append(
                ft.Text(msg, size=13, color=color, font_family="monospace")
            )
            if len(terminal_output.controls) > 200:
                terminal_output.controls.pop(0)
            page.update()
        except Exception:
            # Ignore errors if page is closing or already destroyed
            pass
    
    # S'abonner au canal terminal
    page.pubsub.subscribe_topic("terminal", on_terminal_message)
    
    def on_refresh_preview(topic, message):
        """Callback pour rafraîchir la preview depuis un thread"""
        refresh_preview(reset_page=False)
    
    # S'abonner au canal refresh
    page.pubsub.subscribe_topic("refresh", on_refresh_preview)
    
    def on_navigate_request(topic, folder_path):
        """Callback pour naviguer vers un dossier depuis un thread"""
        if folder_path and os.path.isdir(folder_path):
            navigate_to_folder(folder_path)
    
    # S'abonner au canal navigate
    page.pubsub.subscribe_topic("navigate", on_navigate_request)

    def on_select_files_request(topic, selected_names_str):
        """Callback pour sélectionner des fichiers depuis la sortie d'un script"""
        apply_selected_files_by_name(selected_names_str)

    # S'abonner au canal select-files
    page.pubsub.subscribe_topic("select_files", on_select_files_request)

    def on_quit_request(topic, message):
        """Callback pour fermer la fenêtre depuis un thread de fond (thread-safe)"""
        page.window.close()

    # S'abonner au canal quit
    page.pubsub.subscribe_topic("quit", on_quit_request)

    def on_preview_ready(topic, payload):
        """Reçoit les données brutes du thread bg et déclenche le rendu de la page courante."""
        token, entries_data, new_file_count_text, error_text = payload
        if _refresh_token["v"] != token:
            return
        all_entries_data["list"] = entries_data
        all_entries_data["error"] = error_text
        file_count_text.value = new_file_count_text
        # Appliquer la sélection en attente si un script l'a demandé
        # (ex: Fichiers manquants). On le fait ICI avec les données fraîches
        # pour éviter tout race condition entre threads.
        if _pending_selection["names"] is not None:
            names_to_apply = _pending_selection["names"]
            _pending_selection["names"] = None
            apply_selected_files_by_name(names_to_apply)
        else:
            _render_current_page()

    # S'abonner au canal preview_ready
    page.pubsub.subscribe_topic("preview_ready", on_preview_ready)

    def request_quit():
        """Ferme la fenêtre principale de façon thread-safe via pubsub"""
        page.pubsub.send_all_on_topic("quit", None)

    def request_refresh():
        """Demande un rafraîchissement de la preview (thread-safe)"""
        page.pubsub.send_all_on_topic("refresh", None)
    
    def on_keyboard_event(e: ft.KeyboardEvent):
        """Gestionnaire des événements clavier pour les raccourcis"""
        # Détection de Ctrl (Windows/Linux) ou Cmd (macOS)
        ctrl_pressed = e.ctrl or e.meta
        
        if ctrl_pressed:
            if e.key == "C":
                copy_selected_files(None)
            elif e.key == "X":
                cut_selected_files(None)
            elif e.key == "V":
                paste_files(None)
            elif e.key == "N":
                create_new_folder(None)
    
    # Activer la gestion des événements clavier
    page.on_keyboard_event = on_keyboard_event

    # ================================================================ #
    #                          TERMINAL                                #
    # ================================================================ #
    def log_to_terminal(message, color=WHITE):
        """Ajoute un message au terminal intégré"""
        # Supprimer les codes ANSI d'échappement (clear screen, colors, etc.)
        ansi_escape = re.compile(r'\x1b\[[0-9;]*[a-zA-Z]|\x1b\[\?[0-9;]*[a-zA-Z]')
        clean_message = ansi_escape.sub('', message).strip()
        if clean_message:  # N'afficher que si le message n'est pas vide après nettoyage
            page.pubsub.send_all_on_topic("terminal", (clean_message, color))
    
    def clear_terminal(e):
        """Efface le contenu du terminal"""
        terminal_output.controls.clear()
        page.update()
    
    def copy_terminal_to_clipboard():
        """Copie tout le contenu du terminal dans le presse-papiers"""
        if not terminal_output.controls:
            return
        terminal_text = "\n".join([ctrl.value for ctrl in terminal_output.controls if hasattr(ctrl, 'value')])
        try:
            if platform.system() == "Darwin":
                process = subprocess.Popen(['pbcopy'], stdin=subprocess.PIPE)
                process.communicate(terminal_text.encode('utf-8'))
            elif platform.system() == "Windows":
                process = subprocess.Popen(['clip'], stdin=subprocess.PIPE)
                process.communicate(terminal_text.encode('utf-16'))
            else:
                try:
                    process = subprocess.Popen(['xclip', '-selection', 'clipboard'], stdin=subprocess.PIPE)
                    process.communicate(terminal_text.encode('utf-8'))
                except FileNotFoundError:
                    process = subprocess.Popen(['xsel', '--clipboard', '--input'], stdin=subprocess.PIPE)
                    process.communicate(terminal_text.encode('utf-8'))
            log_to_terminal("[OK] Terminal copié dans le presse-papiers", GREEN)
        except Exception as e:
            log_to_terminal(f"[ERREUR] Copie presse-papiers: {e}", RED)

    # ================================================================ #
    #                   NAVIGATION & FICHIERS                          #
    # ================================================================ #
    def on_folder_path_submit(e):
        """Charge un dossier collé/saisi manuellement dans le champ."""
        raw = (folder_path.value or "").strip().strip('"').strip("'")
        raw = raw.replace("\\", os.sep).replace("/", os.sep)
        if raw and os.path.isdir(raw):
            folder_path.error_text = None
            navigate_to_folder(raw)
        else:
            folder_path.error_text = "Dossier introuvable"
            folder_path.value = selected_folder.get("path", "") or ""
            folder_path.update()

    def on_folder_path_blur(e):
        """Restaure le chemin courant si le champ est laissé invalide."""
        folder_path.error_text = None
        folder_path.value = selected_folder.get("path", "") or ""
        folder_path.update()

    def _refresh_recent_btn():
        """Reconstruit les items du bouton dossiers récents."""
        recent = _load_recent()
        if not recent:
            recent_folders_btn.items = [
                ft.PopupMenuItem(content=ft.Text("Aucun dossier récent"))
            ]
        else:
            recent_folders_btn.items = [
                ft.PopupMenuItem(
                    content=ft.Row([
                        ft.Icon(ft.Icons.FOLDER, size=16),
                        ft.Text(os.path.basename(p) or p),
                    ], spacing=8, tight=True),
                    on_click=lambda e, folder=p: navigate_to_folder(folder),
                )
                for p in recent
            ]
        try:
            recent_folders_btn.update()
        except Exception:
            pass

    def open_in_file_explorer(folder_path):
        """Ouvre le dossier dans l'explorateur de fichiers natif"""
        if not folder_path or not os.path.isdir(folder_path):
            log_to_terminal("Aucun dossier sélectionné", RED)
            return
        
        try:
            if platform.system() == "Windows":
                subprocess.Popen(f'explorer "{folder_path}"')
            elif platform.system() == "Darwin":  # macOS
                subprocess.Popen(["open", folder_path])
            else:  # Linux
                subprocess.Popen(["xdg-open", folder_path])
            log_to_terminal(f"[OK] Ouverture du dossier: {os.path.basename(folder_path)}", GREEN)
        except Exception as e:
            log_to_terminal(f"[ERREUR] Erreur lors de l'ouverture de l'explorateur: {e}", RED)
    
    def open_file_with_default_app(file_path):
        """Ouvre un fichier avec l'application par défaut du système en premier plan"""
        if not file_path or not os.path.isfile(file_path):
            return
        
        try:
            if platform.system() == "Windows":
                # Utilise 'start' avec '' pour ouvrir en premier plan
                subprocess.Popen(f'start "" "{file_path}"', shell=True)
            elif platform.system() == "Darwin":  # macOS
                subprocess.Popen(["open", file_path])
            else:  # Linux
                subprocess.Popen(["xdg-open", file_path])
        except Exception as e:
            log_to_terminal(f"[ERREUR] Erreur lors de l'ouverture du fichier: {e}", RED)

    # ── Ouvrir avec (menu clic-droit) ─────────────────────────────────
    def _load_open_with_programs() -> list:
        """Charge la liste des programmes depuis open_with.json."""
        try:
            with open(_open_with_config_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            return [p for p in data if isinstance(p, dict) and "label" in p and "exe" in p]
        except Exception:
            return []

    def _open_files_with(prog: dict, files: list):
        """Ouvre une liste de fichiers avec le programme spécifié."""
        exe = prog.get("exe", "")
        if not exe:
            return
        try:
            if platform.system() == "Darwin":
                subprocess.Popen(["open", "-a", exe] + files)
            else:
                subprocess.Popen([exe] + files)
            names = ", ".join(os.path.basename(f) for f in files[:3])
            suffix = f" (+{len(files) - 3})" if len(files) > 3 else ""
            log_to_terminal(f"[OK] Ouvert avec {prog['label']}: {names}{suffix}", GREEN)
        except Exception as err:
            log_to_terminal(f"[ERREUR] {prog['label']}: {err}", RED)

    def _save_open_with_programs(programs: list):
        """Sauvegarde la liste des programmes dans open_with.json."""
        try:
            with open(_open_with_config_path, "w", encoding="utf-8") as f:
                json.dump(programs, f, ensure_ascii=False, indent=2)
        except Exception as err:
            log_to_terminal(f"[ERREUR] Sauvegarde open_with.json : {err}", RED)

    def _show_ctx_menu(files: list):
        """Affiche le dialog 'Ouvrir avec' pour les fichiers sélectionnés."""

        header_label = (
            os.path.basename(files[0]) if len(files) == 1
            else f"{len(files)} fichier(s) sélectionné(s)"
        )

        # Champs du formulaire d'ajout
        add_label_field = ft.TextField(
            hint_text="Nom affiché (ex : Affinity Photo)",
            border_color=BLUE, text_size=13, height=40,
            content_padding=ft.Padding(8, 4, 8, 4), expand=True,
        )
        add_exe_field = ft.TextField(
            hint_text="Chemin exe (ex : C:\\...\\Photo.exe)",
            border_color=BLUE, text_size=13, height=40,
            content_padding=ft.Padding(8, 4, 8, 4), expand=True,
        )
        add_form = ft.Container(
            content=ft.Column([
                ft.Divider(height=8, color=GREY),
                ft.Text("Ajouter un programme", size=12, color=LIGHT_GREY),
                ft.Row([add_label_field], tight=True),
                ft.Row([add_exe_field], tight=True),
            ], spacing=6, tight=True),
            visible=False,
        )

        items_rlv = ft.ReorderableListView(padding=0, show_default_drag_handles=False)
        dlg = ft.AlertDialog(
            title=ft.Row([
                ft.Text(header_label, size=13, color=LIGHT_GREY,
                        max_lines=1, overflow=ft.TextOverflow.ELLIPSIS, expand=True),
                ft.Container(
                    content=ft.Icon(ft.Icons.ADD, size=13, color=DARK),
                    bgcolor=BLUE, border_radius=10,
                    padding=ft.Padding(3, 1, 3, 1),
                    tooltip="Ajouter un programme",
                    ink=True,
                    on_click=lambda e: _toggle_add_form(),
                ),
            ], spacing=8, tight=True,
               vertical_alignment=ft.CrossAxisAlignment.CENTER),
            content=ft.Column([items_rlv, add_form],
                              spacing=0, tight=True, width=340),
            actions_alignment=ft.MainAxisAlignment.END,
        )

        def _rebuild_items():
            programs = _load_open_with_programs()
            items_rlv.controls.clear()
            if not programs:
                items_rlv.controls.append(ft.Container(
                    key="empty",
                    content=ft.Text(
                        "Aucun programme configuré — cliquez + pour en ajouter.",
                        size=12, color=LIGHT_GREY,
                    ),
                    padding=ft.Padding(0, 6, 0, 6),
                ))
            else:
                for i, prog in enumerate(programs):
                    def _make_open(p):
                        def _h(e):
                            dlg.open = False
                            page.update()
                            _open_files_with(p, files)
                        return _h
                    def _make_delete(p):
                        def _h(e):
                            progs = _load_open_with_programs()
                            progs = [x for x in progs if x != p]
                            _save_open_with_programs(progs)
                            _rebuild_items()
                            items_rlv.update()
                        return _h
                    items_rlv.controls.append(ft.ListTile(
                        key=str(i),
                        leading=ft.ReorderableDragHandle(
                            content=ft.Icon(ft.Icons.DRAG_HANDLE,
                                            color=LIGHT_GREY, size=18),
                        ),
                        title=ft.Text(prog["label"], size=13, color=WHITE),
                        trailing=ft.IconButton(
                            icon=ft.Icons.DELETE_OUTLINE, icon_size=16,
                            icon_color=RED, tooltip="Supprimer",
                            on_click=_make_delete(prog),
                            style=ft.ButtonStyle(padding=ft.Padding.all(4)),
                        ),
                        on_click=_make_open(prog),
                        hover_color=GREY, dense=True,
                        content_padding=ft.Padding(0, 0, 0, 0),
                    ))

        def _on_reorder(e: ft.OnReorderEvent):
            items_rlv.controls.insert(e.new_index, items_rlv.controls.pop(e.old_index))
            progs = _load_open_with_programs()
            progs.insert(e.new_index, progs.pop(e.old_index))
            _save_open_with_programs(progs)
            items_rlv.update()

        items_rlv.on_reorder = _on_reorder

        def _toggle_add_form():
            add_form.visible = not add_form.visible
            btn_ajouter.visible = add_form.visible
            if add_form.visible:
                add_label_field.value = ""
                add_exe_field.value = ""
            page.update()

        def _confirm_add(e):
            label = (add_label_field.value or "").strip()
            exe   = (add_exe_field.value or "").strip()
            if not label or not exe:
                add_label_field.error_text = "Requis" if not label else None
                add_exe_field.error_text   = "Requis" if not exe   else None
                page.update()
                return
            add_label_field.error_text = None
            add_exe_field.error_text   = None
            progs = _load_open_with_programs()
            progs.append({"label": label, "exe": exe})
            _save_open_with_programs(progs)
            add_form.visible = False
            btn_ajouter.visible = False
            _rebuild_items()
            page.update()

        def _close(e):
            dlg.open = False
            page.update()

        btn_ajouter = ft.TextButton("Ajouter", on_click=_confirm_add, visible=False)
        dlg.actions = [
            btn_ajouter,
            ft.TextButton("Fermer",  on_click=_close),
        ]

        _rebuild_items()
        page.overlay.append(dlg)
        dlg.open = True
        page.update()

    def navigate_to_folder(new_path):
        """Navigue vers un dossier dans la preview"""
        if not new_path:
            return
        current_browse_folder["path"] = new_path
        selected_folder["path"] = new_path
        folder_path.value = new_path
        selected_files.clear()
        selection_count_text.value = ""
        preview_page["value"] = 0
        _add_to_recent(new_path)
        _refresh_recent_btn()
        refresh_preview()
    
    def go_to_parent_folder(e):
        """Remonte au dossier parent"""
        if current_browse_folder["path"]:
            parent = os.path.dirname(current_browse_folder["path"])
            if parent and parent != current_browse_folder["path"]:
                navigate_to_folder(parent)
    
    def extract_zip(file_path):
        """Décompresse un .zip avec détection de dossier racine unique"""
        dest_dir = os.path.dirname(file_path)
        zip_name = os.path.splitext(os.path.basename(file_path))[0]
        
        try:
            with zipfile.ZipFile(file_path, 'r') as zf:
                names = zf.namelist()
                top_levels = {n.split('/')[0] for n in names if n}
                # Si tout le contenu est sous un seul dossier racine, extraire directement
                if len(top_levels) == 1 and any('/' in n for n in names):
                    extract_to = dest_dir
                else:
                    extract_to = os.path.join(dest_dir, zip_name)
                    os.makedirs(extract_to, exist_ok=True)

                zf.extractall(extract_to)
            log_to_terminal(f"[OK] Décompressé: {os.path.basename(file_path)}", GREEN)
            refresh_preview()
        except Exception as err:
            log_to_terminal(f"[ERREUR] Décompression: {err}", RED)

    def open_image_viewer(start_path):
        """Affiche un lecteur d'image plein écran avec navigation prev/next, zoom et déplacement (InteractiveViewer)."""
        entries = all_entries_data["list"]
        image_paths = [fp for (_, fp, is_d, is_img, _ext) in entries if is_img and not is_d]
        if not image_paths:
            image_paths = [start_path]
        try:
            current_idx = {"v": image_paths.index(start_path)}
        except ValueError:
            current_idx = {"v": 0}
            image_paths = [start_path]

        prev_kb = page.on_keyboard_event

        # ── Helpers ──────────────────────────────────────────────────────
        def _get_resolution(path):
            if _PILImage:
                try:
                    with _PILImage.open(path) as _im:
                        return f"{_im.width} × {_im.height}"
                except Exception:
                    pass
            return ""

        # ── Contrôles texte ───────────────────────────────────────────────
        filename_text = ft.Text(
            os.path.basename(image_paths[current_idx["v"]]),
            size=13,
            color=ft.Colors.WHITE,
            weight=ft.FontWeight.W_500,
            max_lines=1,
            overflow=ft.TextOverflow.ELLIPSIS,
        )
        counter_text = ft.Text(
            f"{current_idx['v'] + 1} / {len(image_paths)}",
            size=12,
            color=ft.Colors.WHITE70,
        )
        resolution_text = ft.Text(
            _get_resolution(image_paths[current_idx["v"]]),
            size=12,
            color=ft.Colors.WHITE54,
        )
        viewer_checkbox = ft.Checkbox(
            value=image_paths[current_idx["v"]] in selected_files,
            on_change=lambda e: on_checkbox_change(e, image_paths[current_idx["v"]]),
        )

        # ── InteractiveViewer ─────────────────────────────────────────────
        # On recrée l'InteractiveViewer à chaque changement d'image pour
        # remettre le zoom et le pan à zéro.
        _iv_key = {"n": 0}

        def _make_iv(path):
            _iv_key["n"] += 1
            vw = page.window.width or 1280
            vh = page.window.height or 800
            return ft.InteractiveViewer(
                key=str(_iv_key["n"]),
                content=ft.Image(
                    src=path,
                    width=vw,
                    height=vh,
                    fit=ft.BoxFit.CONTAIN,
                    error_content=ft.Icon(ft.Icons.BROKEN_IMAGE, color=ft.Colors.WHITE54),
                ),
                min_scale=0.5,
                max_scale=10.0,
                pan_enabled=True,
                scale_enabled=True,
                width=vw,
                height=vh,
                clip_behavior=ft.ClipBehavior.HARD_EDGE,
            )

        iv_container = ft.Container(
            content=_make_iv(image_paths[current_idx["v"]]),
            expand=True,
            alignment=ft.Alignment(0, 0),
        )

        # ── Navigation image ──────────────────────────────────────────────
        def _load_image(path):
            iv_container.content   = _make_iv(path)
            filename_text.value    = os.path.basename(path)
            counter_text.value     = f"{current_idx['v'] + 1} / {len(image_paths)}"
            resolution_text.value  = _get_resolution(path)
            viewer_checkbox.value  = path in selected_files
            page.update()

        def go_prev(e):
            if len(image_paths) > 1:
                current_idx["v"] = (current_idx["v"] - 1) % len(image_paths)
                _load_image(image_paths[current_idx["v"]])

        def go_next(e):
            if len(image_paths) > 1:
                current_idx["v"] = (current_idx["v"] + 1) % len(image_paths)
                _load_image(image_paths[current_idx["v"]])

        def close_viewer(e):
            page.on_keyboard_event = prev_kb
            page.theme = ft.Theme(
                page_transitions=ft.PageTransitionsTheme(
                    macos=ft.PageTransitionTheme.NONE,
                    windows=ft.PageTransitionTheme.NONE,
                    linux=ft.PageTransitionTheme.NONE,
                )
            )
            if len(page.views) > 1:
                page.views.pop()
            refresh_preview()
            page.update()

        def delete_current_image(e):
            path = image_paths[current_idx["v"]]
            fname = os.path.basename(path)

            def _confirm(e2):
                page.on_keyboard_event = on_key
                dlg.open = False
                page.update()
                try:
                    os.remove(path)
                    image_paths.pop(current_idx["v"])
                    log_to_terminal(f"[OK] Supprimé: {fname}", GREEN)
                except Exception as err:
                    log_to_terminal(f"[ERREUR] {err}", RED)
                    return
                if not image_paths:
                    close_viewer(None)
                    return
                current_idx["v"] = min(current_idx["v"], len(image_paths) - 1)
                _load_image(image_paths[current_idx["v"]])

            def _cancel(e2):
                page.on_keyboard_event = on_key
                dlg.open = False
                page.update()

            def _on_key_dialog(e2: ft.KeyboardEvent):
                if e2.key == "Escape":
                    _cancel(None)
                elif e2.key == "Enter":
                    _confirm(None)

            dlg = ft.AlertDialog(
                title=ft.Text("Supprimer l'image ?"),
                content=ft.Text(f"'{fname}' sera définitivement supprimé."),
                actions=[
                    ft.TextButton("Annuler", on_click=_cancel),
                    ft.TextButton("Supprimer", on_click=_confirm, style=ft.ButtonStyle(color=ft.Colors.RED)),
                ],
            )
            page.overlay.append(dlg)
            dlg.open = True
            page.on_keyboard_event = _on_key_dialog
            page.update()

        def on_key(e: ft.KeyboardEvent):
            if e.key in ("Arrow Right", "ArrowRight"):
                go_next(None)
            elif e.key in ("Arrow Left", "ArrowLeft"):
                go_prev(None)
            elif e.key == "Escape":
                close_viewer(None)
            elif e.key in ("Delete", "Backspace"):
                delete_current_image(None)

        page.on_keyboard_event = on_key

        page.theme = ft.Theme(
            page_transitions=ft.PageTransitionsTheme(
                macos=ft.PageTransitionTheme.OPEN_UPWARDS,
                windows=ft.PageTransitionTheme.OPEN_UPWARDS,
                linux=ft.PageTransitionTheme.OPEN_UPWARDS,
            )
        )

        btn_style = ft.ButtonStyle(
            overlay_color=ft.Colors.with_opacity(0.15, ft.Colors.WHITE),
        )

        bar_bg = ft.Colors.with_opacity(0.72, GREY)

        top_bar = ft.Row(
            [
                ft.Container(
                    content=ft.Column(
                        [
                            filename_text,
                            ft.Row(
                                [counter_text, ft.Text("·", size=12, color=ft.Colors.WHITE38), resolution_text],
                                alignment=ft.MainAxisAlignment.CENTER,
                                spacing=6,
                            ),
                        ],
                        horizontal_alignment=ft.CrossAxisAlignment.CENTER,
                        spacing=2,
                    ),
                    bgcolor=bar_bg,
                    padding=ft.Padding.symmetric(horizontal=24, vertical=10),
                    border_radius=16,
                    width=320,
                ),
            ],
            alignment=ft.MainAxisAlignment.CENTER,
            spacing=8,
        )

        # Bouton fermer — coin supérieur droit
        close_btn_top = ft.Container(
            content=ft.IconButton(
                icon=ft.Icons.CLOSE_ROUNDED,
                icon_color=ft.Colors.WHITE,
                icon_size=24,
                tooltip="Fermer (Échap)",
                on_click=close_viewer,
                style=btn_style,
            ),
            bgcolor=bar_bg,
            border_radius=20,
        )

        nav_bar = ft.Container(
            content=ft.Row(
                [
                    ft.IconButton(
                        icon=ft.Icons.ARROW_BACK_IOS_NEW_ROUNDED,
                        icon_color=ft.Colors.WHITE,
                        icon_size=26,
                        tooltip="Image précédente",
                        on_click=go_prev,
                        style=btn_style,
                    ),
                    ft.Container(
                        content=viewer_checkbox,
                        padding=ft.Padding.symmetric(horizontal=4, vertical=0),
                    ),
                    ft.IconButton(
                        icon=ft.Icons.DELETE_ROUNDED,
                        icon_color=ft.Colors.RED_300,
                        icon_size=22,
                        tooltip="Supprimer l'image (Suppr / ⌫)",
                        on_click=delete_current_image,
                        style=btn_style,
                    ),
                    ft.IconButton(
                        icon=ft.Icons.ARROW_FORWARD_IOS_ROUNDED,
                        icon_color=ft.Colors.WHITE,
                        icon_size=26,
                        tooltip="Image suivante",
                        on_click=go_next,
                        style=btn_style,
                    ),
                ],
                alignment=ft.MainAxisAlignment.CENTER,
                vertical_alignment=ft.CrossAxisAlignment.CENTER,
                tight=True,
            ),
            bgcolor=bar_bg,
            padding=ft.Padding.symmetric(horizontal=8, vertical=6),
            border_radius=16,
        )

        nav_bar_row = ft.Row(
            [nav_bar],
            alignment=ft.MainAxisAlignment.CENTER,
        )

        viewer_view = ft.View(
            route="/image_viewer",
            bgcolor="#3c3c3c",
            padding=0,
            controls=[
                ft.Stack(
                    [
                        iv_container,
                        # Barre supérieure — centrée
                        ft.Container(
                            content=top_bar,
                            top=12,
                            left=0,
                            right=0,
                            alignment=ft.Alignment(0, 0),
                        ),
                        # Bouton fermer — coin supérieur droit
                        ft.Container(
                            content=close_btn_top,
                            top=10,
                            right=12,
                        ),
                        # Barre de navigation inférieure
                        ft.Container(
                            content=nav_bar_row,
                            bottom=16,
                            left=0,
                            right=0,
                            alignment=ft.Alignment(0, 0),
                        ),
                    ],
                    expand=True,
                )
            ],
        )
        page.views.append(viewer_view)
        page.update()


    def on_file_click(file_path, is_dir):
        """Gère le clic sur un fichier ou dossier dans la preview"""
        if is_dir:
            navigate_to_folder(file_path)
        elif os.path.splitext(file_path)[1].lower() == ".zip":
            log_to_terminal(f"Extraction: {os.path.splitext(os.path.basename(file_path))[0]}", BLUE)
            extract_zip(file_path)
        elif os.path.splitext(file_path)[1].lower() in _IMAGE_VIEWER_EXTS:
            open_image_viewer(file_path)
        else:
            open_file_with_default_app(file_path)

    # ================================================================ #
    #                  OPÉRATIONS SUR FICHIERS                         #
    # ================================================================ #
    def _rename_item(file_path):
        """Renomme un fichier ou un dossier via une boîte de dialogue."""
        current_name = os.path.basename(file_path)
        parent_dir = os.path.dirname(file_path)
        stem, ext = os.path.splitext(current_name)

        name_input = ft.TextField(
            value=stem if ext else current_name,
            suffix=ft.Text(ext, color=LIGHT_GREY) if ext else None,
            autofocus=True,
            width=360,
            bgcolor=DARK,
            border_color=GREY,
            on_submit=lambda e: _do_rename(e),
        )

        def _do_rename(e):
            new_stem = name_input.value.strip() if name_input.value else ""
            if not new_stem:
                return
            new_name = new_stem + ext
            new_path = os.path.join(parent_dir, new_name)
            rename_dialog.open = False
            page.update()
            if new_name == current_name:
                return
            try:
                os.rename(file_path, new_path)
                log_to_terminal(f"[OK] Renommé: {current_name} → {new_name}", GREEN)
                refresh_preview(reset_page=False)
            except Exception as err:
                log_to_terminal(f"[ERREUR] Renommage: {err}", RED)

        def _cancel_rename(e):
            rename_dialog.open = False
            page.update()

        rename_dialog = ft.AlertDialog(
            title=ft.Text("Renommer"),
            content=name_input,
            actions=[
                ft.TextButton("Annuler", on_click=_cancel_rename),
                ft.TextButton("Renommer", on_click=_do_rename),
            ],
        )
        page.overlay.append(rename_dialog)
        rename_dialog.open = True
        page.update()

    def delete_item(file_path):
        """Supprime un fichier ou dossier avec confirmation"""
        def confirm_delete(e):
            """
            Exécute la suppression confirmée du fichier ou dossier.

            Appelée par le bouton « Supprimer » de la boîte de dialogue
            de confirmation. Ferme la dialog et rafraîchit la preview.
            """
            try:
                if os.path.isdir(file_path):
                    shutil.rmtree(file_path)
                else:
                    os.remove(file_path)
                dialog.open = False
                page.update()
                refresh_preview()
                log_to_terminal(f"[OK] Supprimé: {os.path.basename(file_path)}", GREEN)
            except Exception as err:
                log_to_terminal(f"[ERREUR] Erreur lors de la suppression: {err}", RED)
                dialog.open = False
                page.update()
        
        def cancel_delete(e):
            """Annule la suppression et ferme la boîte de dialogue."""
            dialog.open = False
            page.update()
        
        item_type = "dossier" if os.path.isdir(file_path) else "fichier"
        item_name = os.path.basename(file_path)
        
        dialog = ft.AlertDialog(
            title=ft.Text(f"Supprimer {item_type}?"),
            content=ft.Text(f"Voulez-vous vraiment supprimer '{item_name}'?"),
            actions=[
                ft.TextButton("Annuler", on_click=cancel_delete),
                ft.TextButton("Supprimer", on_click=confirm_delete, style=ft.ButtonStyle(color=ft.Colors.RED)),
            ],
        )
        page.overlay.append(dialog)
        dialog.open = True
        page.update()
        
    def create_new_folder(e):
        """Crée un nouveau dossier dans le dossier actuel"""
        target_folder = current_browse_folder["path"] or selected_folder["path"]
        if not target_folder:
            log_to_terminal("[ERREUR] Aucun dossier sélectionné", RED)
            return
        
        def confirm_create(e):
            """
            Valide la création du nouveau dossier.

            Lit le nom saisi, crée le dossier via ``os.makedirs``,
            ferme la dialog et rafraîchit la preview.
            """
            folder_name = folder_name_input.value.strip()
            if not folder_name:
                log_to_terminal("[ERREUR] Le nom du dossier ne peut pas être vide", RED)
                return
            
            new_folder_path = os.path.join(target_folder, folder_name)
            try:
                if os.path.exists(new_folder_path):
                    log_to_terminal(f"[ERREUR] Le dossier '{folder_name}' existe déjà", RED)
                    dialog.open = False
                    page.update()
                else:
                    os.makedirs(new_folder_path)
                    log_to_terminal(f"[OK] Dossier créé: {folder_name}", BLUE)
                    dialog.open = False
                    page.update()
                    refresh_preview()
            except Exception as err:
                log_to_terminal(f"[ERREUR] Erreur lors de la création du dossier: {err}", RED)
                dialog.open = False
                page.update()
        
        def cancel_create(e):
            """Annule la création du dossier et ferme la boîte de dialogue."""
            dialog.open = False
            page.update()
        
        folder_name_input = ft.TextField(
            label="Nom du dossier",
            autofocus=True,
            on_submit=confirm_create,
        )
        
        dialog = ft.AlertDialog(
            title=ft.Text("Créer un nouveau dossier"),
            content=folder_name_input,
            actions=[
                ft.TextButton("Annuler", on_click=cancel_create),
                ft.TextButton("Créer", on_click=confirm_create),
            ],
        )
        page.overlay.append(dialog)
        dialog.open = True
        page.update()
    
    def copy_selected_files(e):
        """Copie les fichiers sélectionnés dans le presse-papiers"""
        if not selected_files:
            log_to_terminal("[ATTENTION] Aucun fichier sélectionné", ORANGE)
            return
        clipboard["files"] = list(selected_files)
        clipboard["cut"] = False
        count = len(clipboard["files"])
        log_to_terminal(f"[OK] {count} élément(s) copié(s)", BLUE)

    def cut_selected_files(e):
        """Coupe les fichiers sélectionnés (déplacement à la destination)"""
        if not selected_files:
            log_to_terminal("[ATTENTION] Aucun fichier sélectionné", ORANGE)
            return
        clipboard["files"] = list(selected_files)
        clipboard["cut"] = True
        count = len(clipboard["files"])
        log_to_terminal(f"[OK] {count} élément(s) coupé(s) — collé avec Ctrl+V", ORANGE)

    def select_by_filter(e):
        """Sélectionne tous les fichiers correspondant au filtre actif dans la page courante."""
        entries = all_entries_data["list"]
        if filter_type["value"] != "all":
            entries = [en for en in entries if _match_filter(en)]
        added = 0
        for _name, fpath, is_dir, _is_img, _ext in entries:
            if not is_dir:
                selected_files.add(fpath)
                added += 1
        selection_count_text.value = _selection_label()
        _render_current_page()
        _sync_toggle_btn()
        if added:
            filt = filter_type["value"]
            label = filt if filt != "all" else "tous types"
            log_to_terminal(f"[OK] {added} fichier(s) sélectionné(s) — {label}", BLUE)
        else:
            log_to_terminal("[ATTENTION] Aucun fichier à sélectionner avec ce filtre", ORANGE)

    def _sync_toggle_btn():
        """Met à jour l'apparence du bouton sélectionner/désélectionner."""
        if selected_files:
            _select_toggle_btn.icon = ft.Icons.DESELECT
            _select_toggle_btn.icon_color = ORANGE
            _select_toggle_btn.tooltip = "Désélectionner tout"
        else:
            _select_toggle_btn.icon = ft.Icons.SELECT_ALL
            _select_toggle_btn.icon_color = VIOLET
            _select_toggle_btn.tooltip = "Tout sélectionner"
        try:
            _select_toggle_btn.update()
        except Exception:
            pass

    def toggle_select_all(e):
        """Sélectionne tout si rien sélectionné, sinon désélectionne tout."""
        if selected_files:
            clear_selection(e)
        else:
            select_by_filter(e)

    def invert_selection(e):
        """Inverse la sélection : sélectionne les non-sélectionnés, désélectionne les sélectionnés."""
        entries = all_entries_data["list"]
        if filter_type["value"] != "all":
            entries = [en for en in entries if _match_filter(en)]
        for _name, fpath, is_dir, _is_img, _ext in entries:
            if is_dir:
                continue
            if fpath in selected_files:
                selected_files.discard(fpath)
            else:
                selected_files.add(fpath)
        selection_count_text.value = _selection_label()
        _render_current_page()
        _sync_toggle_btn()
        log_to_terminal(f"[OK] Sélection inversée — {len(selected_files)} fichier(s) sélectionné(s)", BLUE)

    def paste_files(e):
        """Colle les fichiers du presse-papiers dans le dossier actuel"""
        target_folder = current_browse_folder["path"] or selected_folder["path"]
        if not target_folder:
            log_to_terminal("[ERREUR] Aucun dossier de destination sélectionné", RED)
            return
        
        if not clipboard["files"]:
            log_to_terminal("[ATTENTION] Presse-papiers vide", ORANGE)
            return
        
        copied_count = 0
        errors = []
        
        for source_path in clipboard["files"]:
            if not os.path.exists(source_path):
                errors.append(f"{os.path.basename(source_path)}: fichier source introuvable")
                continue
            
            dest_path = os.path.join(target_folder, os.path.basename(source_path))
            
            # Si le fichier existe déjà, ajouter un suffixe
            if os.path.exists(dest_path):
                base_name = os.path.basename(source_path)
                name, ext = os.path.splitext(base_name)
                counter = 1
                while os.path.exists(dest_path):
                    new_name = f"{name} ({counter}){ext}"
                    dest_path = os.path.join(target_folder, new_name)
                    counter += 1
            
            try:
                if os.path.isdir(source_path):
                    shutil.copytree(source_path, dest_path)
                else:
                    shutil.copy2(source_path, dest_path)
                copied_count += 1
                # Si mode couper : supprimer la source après copie réussie
                if clipboard["cut"]:
                    try:
                        if os.path.isdir(source_path):
                            shutil.rmtree(source_path)
                        else:
                            os.remove(source_path)
                        selected_files.discard(source_path)
                    except Exception as del_err:
                        errors.append(f"Suppression source {os.path.basename(source_path)}: {del_err}")
            except Exception as err:
                errors.append(f"{os.path.basename(source_path)}: {err}")
        
        if copied_count > 0:
            action = "déplacé" if clipboard["cut"] else "collé"
            log_to_terminal(f"[OK] {copied_count} élément(s) {action}(s)", BLUE)
            if clipboard["cut"]:
                clipboard["files"] = []
                clipboard["cut"] = False
                selection_count_text.value = _selection_label()
        
        if errors:
            for error in errors:
                log_to_terminal(f"[ERREUR] {error}", RED)
        
        refresh_preview()

    def _open_numpad(file_path):
        """Affiche un pavé numérique en sur-impression pour définir le nombre d'impressions."""
        basename = os.path.basename(file_path)
        m = re.match(r'^(\d+)X_', basename)
        numpad_value = {"text": m.group(1) if m else ""}

        display = ft.Text(
            numpad_value["text"] or "—",
            size=32, weight=ft.FontWeight.BOLD,
            color=YELLOW, text_align=ft.TextAlign.CENTER,
        )

        def _refresh_display():
            display.value = numpad_value["text"] or "—"
            display.update()

        def _press(d):
            if len(numpad_value["text"]) < 3:
                numpad_value["text"] += str(d)
            _refresh_display()

        def _backspace(e):
            numpad_value["text"] = numpad_value["text"][:-1]
            _refresh_display()

        def _confirm(e):
            val = numpad_value["text"]
            if not val or not val.isdigit() or int(val) < 1:
                log_to_terminal("[ERREUR] Nombre invalide", RED)
                return
            n = int(val)
            numpad_dialog.open = False
            page.update()
            folder = os.path.dirname(file_path)

            # Vérifier si le dossier ne contient aucun préfixe NX_ AVANT ce renommage
            # (on exclut le fichier courant lui-même)
            _print_prefix_re = re.compile(r'^\d+X_')
            others_have_prefix = any(
                _print_prefix_re.match(f)
                for f in os.listdir(folder)
                if f != basename and os.path.isfile(os.path.join(folder, f))
            )

            clean = re.sub(r'^\d+X_', '', basename)
            new_name = f"{n}X_{clean}"
            new_path = os.path.join(folder, new_name)
            if new_path != file_path:
                try:
                    os.rename(file_path, new_path)
                    log_to_terminal(f"[OK] {basename} → {new_name}", GREEN)
                    if file_path in selected_files:
                        selected_files.discard(file_path)
                        selected_files.add(new_path)
                except Exception as err:
                    log_to_terminal(f"[ERREUR] {err}", RED)

            # Si aucun autre fichier n'avait de préfixe, on ajoute "1X_" aux autres
            if not others_have_prefix:
                renamed_count = 0
                for fname in os.listdir(folder):
                    fpath = os.path.join(folder, fname)
                    if not os.path.isfile(fpath):
                        continue
                    if fname == new_name:
                        continue
                    if _print_prefix_re.match(fname):
                        continue
                    new_fname = f"1X_{fname}"
                    new_fpath = os.path.join(folder, new_fname)
                    try:
                        os.rename(fpath, new_fpath)
                        if fpath in selected_files:
                            selected_files.discard(fpath)
                            selected_files.add(new_fpath)
                        renamed_count += 1
                    except Exception as err:
                        log_to_terminal(f"[ERREUR] {fname}: {err}", RED)
                if renamed_count:
                    log_to_terminal(f"[OK] {renamed_count} fichier(s) renommé(s) avec le préfixe 1X_", GREEN)

            refresh_preview(reset_page=False)

        def _cancel(e):
            numpad_dialog.open = False
            page.update()

        def _btn(label, on_click, color=GREY, text_color=WHITE):
            return ft.Container(
                content=ft.Text(str(label), size=18, weight=ft.FontWeight.BOLD,
                                color=text_color, text_align=ft.TextAlign.CENTER),
                width=60, height=52,
                bgcolor=color, border_radius=6,
                alignment=ft.Alignment(0, 0),
                on_click=on_click, ink=True,
            )

        numpad_grid = ft.Column([
            ft.Container(
                content=display,
                bgcolor=DARK, border_radius=6,
                padding=ft.Padding(12, 8, 12, 8),
                alignment=ft.Alignment(0, 0),
                width=210,
            ),
            ft.Row([_btn(7, lambda e: _press(7)), _btn(8, lambda e: _press(8)), _btn(9, lambda e: _press(9))], spacing=6, tight=True),
            ft.Row([_btn(4, lambda e: _press(4)), _btn(5, lambda e: _press(5)), _btn(6, lambda e: _press(6))], spacing=6, tight=True),
            ft.Row([_btn(1, lambda e: _press(1)), _btn(2, lambda e: _press(2)), _btn(3, lambda e: _press(3))], spacing=6, tight=True),
            ft.Row([_btn("⌫", _backspace, GREY, ORANGE), _btn(0, lambda e: _press(0)), _btn("✓", _confirm, GREEN, DARK)], spacing=6, tight=True),
        ], spacing=6, tight=True, horizontal_alignment=ft.CrossAxisAlignment.CENTER)

        numpad_dialog = ft.AlertDialog(
            modal=True,
            title=ft.Text("Nombre d'impressions"),
            content=numpad_grid,
            actions=[ft.TextButton("Annuler", on_click=_cancel)],
            actions_alignment=ft.MainAxisAlignment.END,
        )
        page.overlay.append(numpad_dialog)
        numpad_dialog.open = True
        page.update()

    def _remove_print_prefix(file_path):
        """Retire le préfixe NX_ d'un fichier."""
        basename = os.path.basename(file_path)
        folder = os.path.dirname(file_path)
        clean = re.sub(r'^\d+X_', '', basename)
        if clean == basename:
            return
        new_path = os.path.join(folder, clean)
        try:
            os.rename(file_path, new_path)
            log_to_terminal(f"[OK] Compteur retiré : {clean}", GREEN)
            if file_path in selected_files:
                selected_files.discard(file_path)
                selected_files.add(new_path)
        except Exception as err:
            log_to_terminal(f"[ERREUR] {err}", RED)
        refresh_preview(reset_page=False)

    # ================================================================ #
    #                          SÉLECTION                               #
    # ================================================================ #
    def _selection_label():
        """Retourne le libellé de sélection affiché dans la barre d'état."""
        n = len(selected_files)
        if n == 0:
            return ""
        s = "s" if n > 1 else ""
        return f"{n} fichier{s} sélectionné{s}"

    def on_checkbox_change(e, file_path):
        """Gère le changement d'état d'une checkbox"""
        if e.control.value:
            selected_files.add(file_path)
        else:
            selected_files.discard(file_path)
        selection_count_text.value = _selection_label()
        _sync_toggle_btn()
        page.update()
    
    def clear_selection(e):
        """Désélectionne tous les fichiers et dossiers"""
        selected_files.clear()
        refresh_preview()
        selection_count_text.value = _selection_label()
        page.update()
        log_to_terminal("[OK] Sélection effacée", GREEN)
    
    def delete_selected_files(e):
        """Supprime tous les fichiers et dossiers sélectionnés avec confirmation"""
        if not selected_files:
            log_to_terminal("[ATTENTION] Aucun élément sélectionné", ORANGE)
            return
        
        def confirm_delete_multiple(e):
            """
            Supprime tous les éléments sélectionnés après confirmation.

            Itère sur ``selected_files``, supprime fichiers et dossiers,
            reporte le nombre de suppressions réussies dans le terminal.
            """
            deleted_files = 0
            deleted_folders = 0
            errors = []
            for item_path in list(selected_files):
                try:
                    if os.path.isdir(item_path):
                        shutil.rmtree(item_path)
                        deleted_folders += 1
                    elif os.path.isfile(item_path):
                        os.remove(item_path)
                        deleted_files += 1
                except Exception as err:
                    errors.append(f"{os.path.basename(item_path)}: {err}")
            
            selected_files.clear()
            dialog.open = False
            page.update()
            refresh_preview()
            
            if deleted_files > 0 or deleted_folders > 0:
                msg_parts = []
                if deleted_files > 0:
                    msg_parts.append(f"{deleted_files} fichier(s)")
                if deleted_folders > 0:
                    msg_parts.append(f"{deleted_folders} dossier(s)")
                log_to_terminal(f"[OK] Supprimé: {' et '.join(msg_parts)}", GREEN)
            if errors:
                for error in errors:
                    log_to_terminal(f"[ERREUR] {error}", RED)
        
        def cancel_delete_multiple(e):
            """Annule la suppression multiple et ferme la boîte de dialogue."""
            dialog.open = False
            page.update()
        
        item_count = len(selected_files)
        
        dialog = ft.AlertDialog(
            title=ft.Text(f"Supprimer {item_count} élément(s)?"),
            content=ft.Text(f"Voulez-vous vraiment supprimer les {item_count} élément(s) sélectionné(s)?"),
            actions=[
                ft.TextButton("Annuler", on_click=cancel_delete_multiple),
                ft.TextButton("Supprimer", on_click=confirm_delete_multiple, style=ft.ButtonStyle(color=ft.Colors.RED)),
            ],
        )
        page.overlay.append(dialog)
        dialog.open = True
        page.update()

    def apply_selected_files_by_name(selected_names_str):
        """Sélectionne dans la preview les éléments correspondant aux noms fournis"""
        folder_to_display = current_browse_folder["path"] or selected_folder["path"]
        if not folder_to_display or not os.path.isdir(folder_to_display):
            return

        names = [name for name in selected_names_str.split("|") if name]
        names_set = set(names)

        selected_files.clear()
        # Utilise all_entries_data pour garantir que les chemins dans selected_files
        # sont identiques (même objet str) à ceux utilisés par _render_current_page(),
        # évitant toute divergence de normalisation Unicode NFD/NFC sur macOS.
        entries = all_entries_data["list"]
        if names_set and entries:
            for file_name, file_path, is_dir, is_image, ext in entries:
                if file_name in names_set:
                    selected_files.add(file_path)
        elif names_set:
            # Fallback si entries pas encore peuplées
            for item_name in os.listdir(folder_to_display):
                if item_name in names_set:
                    selected_files.add(os.path.join(folder_to_display, item_name))

        selection_count_text.value = _selection_label()

        # Naviguer vers la première page contenant au moins un fichier sélectionné
        # (évite que les fichiers au-delà de PAGE_SIZE soient invisibles)
        if selected_files and entries:
            for idx, (file, file_path, is_dir, is_image, ext) in enumerate(entries):
                if file_path in selected_files:
                    preview_page["value"] = idx // PAGE_SIZE
                    break

        # Re-rendu immédiat sans nouveau scan (le script ne modifie aucun fichier)
        _render_current_page()

        if names_set and not selected_files:
            log_to_terminal("[ATTENTION] Aucun fichier correspondant trouvé dans la preview", ORANGE)

    # ================================================================ #
    #                    FILTRAGE & PÉRIPHÉRIQUES                      #
    # ================================================================ #
    def _match_filter(entry_tuple):
        """Retourne True si l'entrée correspond au filtre actif."""
        _name, _path, is_dir, is_image, ext = entry_tuple
        fval = filter_type["value"]
        if fval == "all":
            return True
        if is_dir:
            return True  # Dossiers toujours visibles pour la navigation
        if fval == "images":
            return is_image
        if fval in _FILTER_CATEGORIES:
            return ext in _FILTER_CATEGORIES[fval]
        if fval == "other":
            for cat_exts in _FILTER_CATEGORIES.values():
                if ext in cat_exts:
                    return False
            return True
        return True

    def _filter_chip_ctrl(label, key):
        pass  # remplacé par CupertinoSlidingSegmentedButton

    def _refresh_filter_chips():
        """Synchronise l'index du segment avec filter_type."""
        try:
            filter_segment.selected_index = _FILTER_KEYS.index(filter_type["value"])
            filter_segment.update()
        except Exception:
            pass

    def _set_filter(key):
        """Bascule le filtre actif et re-rend la page courante."""
        filter_type["value"] = key
        preview_page["value"] = 0
        _render_current_page()

    def on_filter_segment_change(e):
        """Callback du CupertinoSlidingSegmentedButton de filtre."""
        idx = e.control.selected_index
        _set_filter(_FILTER_KEYS[idx])

    def _get_removable_drives():
        """Détecte les périphériques amovibles (cross-platform, sans dépendance externe)."""
        drives = []
        try:
            if platform.system() == "Darwin":
                _sys_vols = {
                    "Macintosh HD", "Macintosh HD - Data",
                    "com.apple.TimeMachine.localsnapshots",
                    "Recovery", "Preboot", "VM", "Update",
                }
                for entry in os.scandir("/Volumes"):
                    if entry.is_dir() and entry.name not in _sys_vols and not entry.name.startswith("."):
                        drives.append((entry.name, entry.path))
            elif platform.system() == "Windows":
                import ctypes
                DRIVE_REMOVABLE, DRIVE_CDROM = 2, 5
                vol_buf = ctypes.create_unicode_buffer(261)
                for letter in "ABCDEFGHIJKLMNOPQRSTUVWXYZ":
                    path = f"{letter}:\\"
                    dtype = ctypes.windll.kernel32.GetDriveTypeW(path)
                    if dtype in (DRIVE_REMOVABLE, DRIVE_CDROM) and os.path.exists(path):
                        ctypes.windll.kernel32.GetVolumeInformationW(
                            path, vol_buf, 261, None, None, None, None, 0)
                        label = vol_buf.value or letter
                        drives.append((f"{label} ({letter}:)", path))
            else:  # Linux
                for base in ("/media", "/run/media"):
                    if not os.path.isdir(base):
                        continue
                    for entry in os.scandir(base):
                        if not entry.is_dir():
                            continue
                        if os.path.ismount(entry.path):
                            drives.append((entry.name, entry.path))
                        else:
                            try:
                                for sub in os.scandir(entry.path):
                                    if sub.is_dir() and os.path.ismount(sub.path):
                                        drives.append((sub.name, sub.path))
                            except PermissionError:
                                pass
        except Exception:
            pass
        return drives

    def _refresh_favorites_ui():
        """Reconstruit la liste des favoris dans le conteneur."""
        favs = _load_favorites()
        _favorites_list_col.controls.clear()
        if not favs:
            _favorites_list_col.controls.append(
                ft.Text("Aucun favori — cliquez sur + pour ajouter", size=10,
                        color=LIGHT_GREY, italic=True)
            )
        else:
            for p in favs:
                name = os.path.basename(p) or p
                def _nav(e, path=p):
                    if os.path.isdir(path):
                        navigate_to_folder(path)
                    else:
                        log_to_terminal(f"[ERREUR] Dossier introuvable : {path}", RED)
                def _remove(e, path=p):
                    favs2 = _load_favorites()
                    if path in favs2:
                        favs2.remove(path)
                    _save_favorites(favs2)
                    _refresh_favorites_ui()
                    try:
                        _favorites_list_col.update()
                    except Exception:
                        pass
                _favorites_list_col.controls.append(
                    ft.Row([
                        ft.ReorderableDragHandle(
                            content=ft.Icon(ft.Icons.DRAG_INDICATOR, size=16, color=LIGHT_GREY),
                            mouse_cursor=ft.MouseCursor.GRAB,
                        ),
                        ft.Icon(ft.Icons.FOLDER, size=16, color=BLUE),
                        ft.Container(
                            content=ft.Text(name, size=16, color=WHITE,
                                            overflow=ft.TextOverflow.ELLIPSIS, max_lines=1),
                            expand=True,
                            on_click=_nav,
                            tooltip=p,
                            ink=True,
                        ),
                        ft.Container(
                            content=ft.Icon(ft.Icons.CLOSE, size=16, color=LIGHT_GREY),
                            on_click=_remove,
                            tooltip="Retirer des favoris",
                            ink=True,
                            border_radius=8,
                            padding=ft.Padding(3, 2, 3, 2),
                        ),
                    ], spacing=4, tight=True, height=32, vertical_alignment=ft.CrossAxisAlignment.CENTER)
                )
        try:
            _favorites_list_col.update()
        except Exception:
            pass

    def _add_favorite_current():
        """Ajoute le dossier courant aux favoris."""
        path = current_browse_folder.get("path") or selected_folder.get("path")
        if not path or not os.path.isdir(path):
            log_to_terminal("[ATTENTION] Aucun dossier sélectionné à ajouter en favori", ORANGE)
            return
        path = os.path.normpath(path)
        favs = _load_favorites()
        if path not in favs:
            favs.append(path)
            _save_favorites(favs)
            _refresh_favorites_ui()
            log_to_terminal(f"[OK] Favori ajouté : {os.path.basename(path)}", YELLOW)
        else:
            log_to_terminal("[INFO] Ce dossier est déjà dans les favoris", LIGHT_GREY)

    def _eject_drive(path):
        """Démonte/éjecte un périphérique amovible selon le système d'exploitation."""
        try:
            sys_name = platform.system()
            if sys_name == "Windows":
                drive_letter = os.path.splitdrive(path)[0]  # ex: "E:"
                ps_cmd = (
                    f"(New-Object -comObject Shell.Application)"
                    f".Namespace(17).ParseName('{drive_letter}').InvokeVerb('Eject')"
                )
                subprocess.Popen(["powershell", "-Command", ps_cmd],
                                 creationflags=subprocess.CREATE_NO_WINDOW)
            elif sys_name == "Darwin":
                subprocess.Popen(["diskutil", "eject", path])
            else:  # Linux
                subprocess.Popen(["umount", path])
            log_to_terminal(f"[OK] Éjection demandée : {path}", VIOLET)
        except Exception as ex:
            log_to_terminal(f"[ERREUR] Éjection impossible : {ex}", RED)

    def _refresh_drives_ui(drives):
        """Met à jour la section périphériques (appelée depuis le callback pubsub)."""
        _drives_column.controls.clear()
        for name, path in drives:
            def _nav(e, p=path):
                if os.path.isdir(p):
                    navigate_to_folder(p)
                else:
                    log_to_terminal(f"[ERREUR] Périphérique introuvable : {p}", RED)
            def _eject(e, p=path):
                _eject_drive(p)
            _drives_column.controls.append(
                ft.Row([
                    ft.ReorderableDragHandle(
                        content=ft.Icon(ft.Icons.DRAG_INDICATOR, size=16, color=LIGHT_GREY),
                        mouse_cursor=ft.MouseCursor.GRAB,
                    ),
                    ft.Icon(ft.Icons.STORAGE, size=16, color=VIOLET),
                    ft.Container(
                        content=ft.Text(name, size=16, color=WHITE,
                                        overflow=ft.TextOverflow.ELLIPSIS, max_lines=1),
                        expand=True,
                        on_click=_nav,
                        tooltip=path,
                        ink=True,
                    ),
                    ft.Container(
                        content=ft.Icon(ft.Icons.EJECT, size=16, color=LIGHT_GREY),
                        on_click=_eject,
                        tooltip="Éjecter le périphérique",
                        ink=True,
                        border_radius=8,
                        padding=ft.Padding(3, 2, 3, 2),
                    ),
                ], spacing=4, tight=True, height=32, vertical_alignment=ft.CrossAxisAlignment.CENTER)
            )
        _drives_container.visible = bool(drives)
        try:
            _drives_container.update()
        except Exception:
            pass

    def _on_drives_changed(topic, drives):
        """Callback pubsub : met à jour l'UI périphériques depuis le thread de fond."""
        _refresh_drives_ui(drives)

    page.pubsub.subscribe_topic("drives_changed", _on_drives_changed)

    def _drives_polling_thread():
        """Thread de fond : détecte les changements de périphériques toutes les 3 s."""
        prev_drives = []
        while True:
            time.sleep(3)
            try:
                drives = _get_removable_drives()
                if drives != prev_drives:
                    prev_drives = drives
                    _removable_drives["list"] = drives
                    page.pubsub.send_all_on_topic("drives_changed", drives)
            except Exception:
                pass

    # ================================================================ #
    #                           PREVIEW                                #
    # ================================================================ #
    def _set_visible_images(scroll_pixels, viewport_height, do_update=True):
        """Applique src aux images dans la zone visible + buffer."""
        buffer_px = 3 * ITEM_HEIGHT
        for (list_idx, file_path, image_ctrl) in lazy_images:
            item_top = list_idx * ITEM_HEIGHT
            if item_top < scroll_pixels + viewport_height + buffer_px and (item_top + ITEM_HEIGHT) > scroll_pixels - buffer_px:
                if image_ctrl.src is None:
                    image_ctrl.src = file_path
                    if do_update:
                        image_ctrl.update()

    def on_preview_scroll(e):
        """Déclenche le chargement paresseux des miniatures lors du défilement de la liste."""
        _set_visible_images(e.pixels, e.viewport_dimension)

    def _render_current_page():
        """
        Construit et affiche les contrôles ListView pour la page courante.
        Appelée depuis on_preview_ready et go_to_page (thread UI uniquement).
        Toutes les miniatures de la page sont chargées immédiatement (pas de lazy loading).
        """
        try:
            entries = all_entries_data["list"]
            # Appliquer le filtre actif
            if filter_type["value"] != "all":
                entries = [e for e in entries if _match_filter(e)]
            total = len(entries)
            total_pages = max(1, (total + PAGE_SIZE - 1) // PAGE_SIZE)
            current_pg = min(preview_page["value"], total_pages - 1)
            preview_page["value"] = current_pg

            new_controls = []

            if all_entries_data["error"]:
                new_controls.append(ft.Text(all_entries_data["error"], color="red"))
            elif not entries:
                folder_to_display = current_browse_folder["path"] or selected_folder["path"]
                if folder_to_display:
                    new_controls.append(ft.Text("(dossier vide)", color=GREY))
            else:
                start = current_pg * PAGE_SIZE
                end = min(start + PAGE_SIZE, total)
                for list_idx, (file, file_path, is_dir, is_image, ext) in enumerate(entries[start:end]):
                    if is_dir:
                        icon = ft.Icons.FOLDER
                        icon_color = ft.Colors.AMBER_400
                    elif is_image:
                        icon = ft.Icons.IMAGE
                        icon_color = ft.Colors.GREEN_400
                    elif ext in [".pdf"]:
                        icon = ft.Icons.PICTURE_AS_PDF
                        icon_color = ft.Colors.RED_400
                    elif ext == ".zip":
                        icon = ft.Icons.FOLDER_ZIP
                        icon_color = ORANGE
                    elif ext in [".txt", ".md", ".log"]:
                        icon = ft.Icons.DESCRIPTION
                        icon_color = ft.Colors.BLUE_GREY_400
                    elif ext in [".af", ".afphoto", ".afdesign", ".afpub", ".psd", ".psb", ".svg", ".eps", ".ai"]:
                        icon = ft.Icons.ADOBE
                        icon_color = GREEN
                    else:
                        icon = ft.Icons.INSERT_DRIVE_FILE
                        icon_color = ft.Colors.BLUE_GREY_400

                    checkbox = ft.Checkbox(
                        border_side=ft.BorderSide(color=BLUE),
                        value=file_path in selected_files,
                        on_change=lambda e, path=file_path: on_checkbox_change(e, path),
                    )

                    if is_image:
                        visual = ft.Container(
                            content=ft.Image(src=file_path, fit=ft.BoxFit.COVER, error_content=ft.Icon(icon, color=icon_color, size=22)),
                            width=50, height=50,
                            border_radius=4, clip_behavior=ft.ClipBehavior.ANTI_ALIAS,
                        )
                    else:
                        visual = ft.Icon(icon, color=icon_color, size=22)

                    delete_btn = ft.IconButton(
                        icon=ft.Icons.DELETE_OUTLINE, icon_size=18,
                        icon_color=ft.Colors.RED_300, tooltip="Supprimer",
                        on_click=lambda e, path=file_path: delete_item(path),
                        style=ft.ButtonStyle(padding=ft.Padding.all(4)),
                    )
                    rename_btn = ft.IconButton(
                        icon=ft.Icons.EDIT_OUTLINED, icon_size=17,
                        icon_color=LIGHT_GREY, tooltip="Renommer",
                        on_click=lambda e, path=file_path: _rename_item(path),
                        style=ft.ButtonStyle(padding=ft.Padding.all(4)),
                    )
                    if is_dir:
                        trailing = ft.Row(
                            [rename_btn, delete_btn],
                            spacing=0, tight=True,
                            vertical_alignment=ft.CrossAxisAlignment.CENTER,
                        )
                    else:
                        pm = re.match(r'^(\d+)X_', file)
                        p_count = int(pm.group(1)) if pm else None
                        if p_count is not None:
                            count_chip = ft.Container(
                                content=ft.Text(f"{p_count}×", size=12,
                                                color=YELLOW, weight=ft.FontWeight.BOLD),
                                bgcolor=GREY, border_radius=4,
                                padding=ft.Padding(6, 3, 6, 3),
                                tooltip="Modifier le nombre d'impressions",
                                on_click=lambda e, p=file_path: _open_numpad(p),
                                ink=True,
                            )
                            remove_btn = ft.IconButton(
                                icon=ft.Icons.CLOSE, icon_size=15,
                                icon_color=LIGHT_GREY, tooltip="Retirer le compteur",
                                on_click=lambda e, p=file_path: _remove_print_prefix(p),
                                style=ft.ButtonStyle(padding=ft.Padding.all(4)),
                            )
                            trailing = ft.Row(
                                [count_chip, remove_btn, rename_btn, delete_btn],
                                spacing=0, tight=True,
                                vertical_alignment=ft.CrossAxisAlignment.CENTER,
                            )
                        else:
                            print_btn = ft.IconButton(
                                icon=ft.Icons.PRINT_OUTLINED, icon_size=17,
                                icon_color=LIGHT_GREY,
                                tooltip="Définir le nombre d'impressions",
                                on_click=lambda e, p=file_path: _open_numpad(p),
                                style=ft.ButtonStyle(padding=ft.Padding.all(4)),
                            )
                            trailing = ft.Row(
                                [print_btn, rename_btn, delete_btn],
                                spacing=0, tight=True,
                                vertical_alignment=ft.CrossAxisAlignment.CENTER,
                            )

                    def _make_ctx_handler(fp, d):
                        def _on_right_click(e):
                            if d:
                                return  # pas de menu pour les dossiers
                            if fp in selected_files and len(selected_files) > 1:
                                files_to_open = list(selected_files)
                            else:
                                files_to_open = [fp]
                            _show_ctx_menu(files_to_open)
                        return _on_right_click

                    new_controls.append(
                        ft.GestureDetector(
                            on_secondary_tap_up=_make_ctx_handler(file_path, is_dir),
                            content=ft.ListTile(
                                leading=ft.Row([checkbox, visual], spacing=8, tight=True),
                                title=ft.Text(file, size=13, color=WHITE),
                                trailing=trailing,
                                on_click=lambda e, path=file_path, d=is_dir: on_file_click(path, d),
                                hover_color=GREY, dense=False,
                                content_padding=ft.Padding(left=5, top=2, right=5, bottom=2),
                                min_leading_width=0,
                            ),
                        )
                    )

            preview_list.controls.clear()
            preview_list.controls.extend(new_controls)
            preview_list.on_scroll = None
            preview_loading.visible = False

            # Contrôles de pagination
            if total > PAGE_SIZE:
                prev_page_btn.visible = current_pg > 0
                next_page_btn.visible = current_pg < total_pages - 1
                page_indicator_text.value = f"{current_pg * PAGE_SIZE + 1}-{min((current_pg + 1) * PAGE_SIZE, total)}/{total}"
            else:
                prev_page_btn.visible = False
                next_page_btn.visible = False
                page_indicator_text.value = ""

            # Mettre à jour le compteur si un filtre est actif
            if filter_type["value"] != "all":
                n_files = sum(1 for e in entries if not e[2])
                n_total = sum(1 for e in all_entries_data["list"] if not e[2])
                file_count_text.value = f"({n_files}/{n_total})"

            _sync_toggle_btn()
            page.update()
        except Exception as ex:
            log_to_terminal(f"[ERREUR] Rendu preview: {ex}", RED)

    def refresh_preview(reset_page=True):
        """
        Déclenche un rafraîchissement asynchrone du panneau de prévisualisation.

        Incrémente le jeton de rafraîchissement (annulant tout rafraîchissement
        précédent en cours), vide la liste courante, affiche un indicateur de
        chargement, puis lance un thread de fond ``_bg()`` qui scanne le dossier
        courant et envoie les nouveaux contrôles via PubSub.

        Parameters
        ----------
        reset_page : bool
            Si True (défaut), revient à la page 0. Si False, conserve la page courante.
        """
        if reset_page:
            preview_page["value"] = 0
        _refresh_token["v"] += 1
        my_token = _refresh_token["v"]
        preview_list.on_scroll = None
        preview_list.controls.clear()
        lazy_images.clear()
        file_count_text.value = ""
        folder_to_display = current_browse_folder["path"] or selected_folder["path"]
        preview_loading.visible = bool(folder_to_display)
        page.update()

        def _bg():
            """
            Thread de fond : scanne le dossier et stocke des tuples de données brutes.

            Ne crée aucun widget Flet — la construction des contrôles est déléguée
            à _render_current_page() (thread UI), ce qui évite de sérialiser des
            centaines de widgets en un seul page.update().
            """
            entries_data = []
            new_file_count_text = ""
            error_text = ""

            if folder_to_display:
                try:
                    with os.scandir(folder_to_display) as it:
                        raw = [e for e in it if not _is_os_junk(e)]

                    file_count = sum(1 for e in raw if not e.name.startswith(".") and not e.is_dir())
                    new_file_count_text = f"({file_count} fichier{'s' if file_count > 1 else ''})"

                    if raw:
                        if sort_mode["value"] == 2:
                            sorted_entries = sorted(raw, key=lambda e: (not e.is_dir(), -e.stat().st_mtime))
                        elif sort_mode["value"] == 1:
                            sorted_entries = sorted(raw, key=lambda e: (not e.is_dir(), e.name.lower()), reverse=True)
                        else:
                            sorted_entries = sorted(raw, key=lambda e: (not e.is_dir(), e.name.lower()))

                        for entry in sorted_entries:
                            name = entry.name
                            path = entry.path
                            is_dir = entry.is_dir()
                            ext = os.path.splitext(name)[1].lower()
                            is_image = ext in [".jpg", ".jpeg", ".png", ".gif", ".bmp", ".webp", ".ico", ".tiff", ".tif"]
                            entries_data.append((name, path, is_dir, is_image, ext))

                except PermissionError:
                    error_text = "⚠️ Accès refusé à ce dossier"
                except Exception as ex:
                    error_text = f"⚠️ Erreur: {str(ex)}"

            # Envoyer tuples de données brutes — le rendu des widgets se fait sur le thread UI
            page.pubsub.send_all_on_topic("preview_ready", (my_token, entries_data, new_file_count_text, error_text))

        threading.Thread(target=_bg, daemon=True).start()
    
    def on_sort_change(e):
        """Change le mode de tri et rafraîchit la preview"""
        sort_mode["value"] = e.control.selected_index
        refresh_preview()

    def go_to_page(delta):
        """Navigue de ±1 page sans rescanner le dossier."""
        entries = all_entries_data["list"]
        total_pages = max(1, (len(entries) + PAGE_SIZE - 1) // PAGE_SIZE)
        new_pg = max(0, min(preview_page["value"] + delta, total_pages - 1))
        if new_pg == preview_page["value"]:
            return
        preview_page["value"] = new_pg
        _render_current_page()

    # ================================================================ #
    #                LANCEMENT D'APPLICATIONS                          #
    # ================================================================ #
    def launch_app(app_name, app_path, is_local, series_name=None):
        """
        Lance un script Data/ en tant que sous-processus Python avec les variables
        d'environnement appropriées.

        Pour certains scripts (``Renommer sequence.py``, ``Images en PDF.py``),
        affiche d'abord une boîte de dialogue pour recueillir un paramètre
        (nom de série / nom du PDF) avant de relancer la fonction.

        Pour les scripts « locaux » (is_local=True, ex. Kiosk, Transfert),
        lit stdout/stderr en temps réel, interprète les commandes spéciales
        ``NAVIGATE_TO:<path>`` et filtre les messages de fermeture Flet.
        Pour les scripts « dossier » (is_local=False), injecte ``FOLDER_PATH``,
        ``SELECTED_FILES``, ``RESIZE_SIZE``, etc. et rafraîchit la preview
        à la fin du processus.

        Parameters
        ----------
        app_name : str
            Nom du fichier script (ex. ``"Recadrage.pyw"``).
        app_path : str
            Chemin absolu vers le script.
        is_local : bool
            ``True`` si le script fonctionne sans dossier utilisateur sélectionné
            (ex. Kiosk, Transfert vers TEMP).
        series_name : str or None, optional
            Paramètre textuel à transmettre via ``SERIES_NAME`` ou ``PDF_NAME``
            (renseigné par le dialog affiché au premier appel).
        """
        # Pour Renommer sequence.py, demander le nom de la série avant de lancer
        if app_name == "Images en PDF.py" and series_name is None:
            pdf_name_input = ft.TextField(
                label="Nom du PDF",
                hint_text="Ex: Album_Mariage",
                autofocus=True,
                width=320,
                bgcolor=DARK,
                border_color=GREY,
            )

            def on_confirm_pdf(e):
                """Valide le nom du PDF et relance launch_app avec series_name renseigné."""
                name = pdf_name_input.value.strip() if pdf_name_input.value else ""
                pdf_dialog.open = False
                page.update()
                if name:
                    launch_app(app_name, app_path, is_local, series_name=name)

            def on_cancel_pdf(e):
                """Annule la saisie du nom du PDF et ferme la boîte de dialogue."""
                pdf_dialog.open = False
                page.update()

            pdf_name_input.on_submit = on_confirm_pdf

            pdf_dialog = ft.AlertDialog(
                modal=True,
                title=ft.Text("Nom du PDF"),
                content=pdf_name_input,
                actions=[
                    ft.TextButton("Annuler", on_click=on_cancel_pdf),
                    ft.TextButton("OK", on_click=on_confirm_pdf),
                ],
                actions_alignment=ft.MainAxisAlignment.END,
            )
            page.overlay.append(pdf_dialog)
            pdf_dialog.open = True
            page.update()
            return

        if app_name == "Renommer sequence.py" and series_name is None:
            series_input = ft.TextField(
                label="Nom de la série",
                hint_text="Ex: Mariage_Martin",
                autofocus=True,
                width=320,
                bgcolor=DARK,
                border_color=GREY,
            )

            def on_confirm_series(e):
                """Valide le nom de la série et relance launch_app avec series_name renseigné."""
                name = series_input.value.strip() if series_input.value else ""
                series_dialog.open = False
                page.update()
                launch_app(app_name, app_path, is_local, series_name=name)

            def on_cancel_series(e):
                """Annule la saisie du nom de la série et ferme la boîte de dialogue."""
                series_dialog.open = False
                page.update()

            series_input.on_submit = on_confirm_series

            series_dialog = ft.AlertDialog(
                modal=True,
                title=ft.Text("Renommer la série"),
                content=series_input,
                actions=[
                    ft.TextButton("Annuler", on_click=on_cancel_series),
                    ft.TextButton("OK", on_click=on_confirm_series),
                ],
                actions_alignment=ft.MainAxisAlignment.END,
            )
            page.overlay.append(series_dialog)
            series_dialog.open = True
            page.update()
            return

        if not is_local and not selected_folder["path"]:
            log_to_terminal("[ERREUR] Veuillez sélectionner un dossier avant de lancer cette application", RED)
            return

        try:
            display_name = app_name[:-4] if app_name.endswith(".pyw") else app_name[:-3]
            log_to_terminal(f"▶ Lancement de {display_name}...", BLUE)
            
            if is_local:
                # Préparer l'environnement pour les apps locales
                env = os.environ.copy()
                env["DATA_PATH"] = os.path.join(cwd, "Data")
                
                # Naviguer vers le PATH pour order_it gauche/droite
                if app_name == "Kiosk gauche.py":
                    if platform.system() == "Windows":
                        order_path = "\\\\Diskstation\\travaux en cours\\z2026\\kiosk\\KIOSK GAUCHE"
                    else:
                        order_path = "/Volumes/TRAVAUX EN COURS/Z2026/KIOSK/KIOSK GAUCHE"
                    if os.path.isdir(order_path):
                        navigate_to_folder(order_path)
                    else:
                        log_to_terminal(f"[AVERTISSEMENT] Le dossier {order_path} n'est pas accessible", ORANGE)
                
                elif app_name == "Kiosk droite.py":
                    if platform.system() == "Windows":
                        order_path = "\\\\Diskstation\\travaux en cours\\z2026\\kiosk\\KIOSK DROITE"
                    else:
                        order_path = "/Volumes/TRAVAUX EN COURS/Z2026/KIOSK/KIOSK DROITE"
                    if os.path.isdir(order_path):
                        navigate_to_folder(order_path)
                    else:
                        log_to_terminal(f"[AVERTISSEMENT] Le dossier {order_path} n'est pas accessible", ORANGE)
                
                # Ajouter le dossier destination pour Transfert vers TEMP.py
                if app_name == "Transfert vers TEMP.py":
                    if platform.system() == "Windows":
                        env["DEST_FOLDER"] = "\\\\diskstation\\travaux en cours\\Z2026\\TEMP"
                    else:
                        env["DEST_FOLDER"] = "/Volumes/TRAVAUX EN COURS/Z2026/TEMP"
                    env["LAUNCHED_FROM_DASHBOARD"] = "1"
                    if selected_files:
                        env["SOURCE_FILES"] = "|".join(str(f) for f in selected_files)
                
                process = subprocess.Popen(
                    [sys.executable, "-u", app_path],
                    env=env,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    text=True,
                    bufsize=1,
                    universal_newlines=True
                )
                if platform.system() == "Windows":
                    try:
                        import ctypes
                        ctypes.windll.user32.AllowSetForegroundWindow(process.pid)
                    except Exception:
                        pass
                
                # Lire la sortie en temps réel
                def read_output(pipe, color):
                    """
                    Lit en temps réel une pipe stdout ou stderr du sous-processus
                    local (Flet) et envoie chaque ligne non vide au terminal.

                    Filtre les messages de fermeture de session Flet et interprète
                    les commandes ``NAVIGATE_TO:<path>`` pour naviguer dans la preview.

                    Parameters
                    ----------
                    pipe : IO
                        Pipe stdout ou stderr du subprocess.
                    color : str
                        Couleur hexadécimale pour l'affichage dans le terminal.
                    """
                    try:
                        for line in iter(pipe.readline, ''):
                            if line:
                                line_stripped = line.rstrip()
                                # Ignorer les messages de fermeture de session Flet
                                if "Session closed" in line_stripped or "session" in line_stripped.lower() and "closed" in line_stripped.lower():
                                    continue
                                # Détecter la commande de navigation
                                if line_stripped.startswith("NAVIGATE_TO:"):
                                    folder_to_navigate = line_stripped[12:]  # Enlever "NAVIGATE_TO:"
                                    if os.path.isdir(folder_to_navigate):
                                        # Utiliser pubsub pour mettre à jour l'UI depuis un thread
                                        page.pubsub.send_all_on_topic("navigate", folder_to_navigate)
                                else:
                                    log_to_terminal(line_stripped, color)
                    except:
                        pass
                    finally:
                        pipe.close()
                
                threading.Thread(target=read_output, args=(process.stdout, WHITE), daemon=True).start()
                threading.Thread(target=read_output, args=(process.stderr, RED), daemon=True).start()
                
            else:
                # Préparer l'environnement avec le chemin du dossier Data
                env = os.environ.copy()
                env["DATA_PATH"] = os.path.join(cwd, "Data")
                env["FOLDER_PATH"] = selected_folder["path"]
                
                # Ajouter les chemins ImageMagick pour Wand (Homebrew sur macOS)
                if platform.system() == "Darwin":
                    # Chemins Homebrew pour Apple Silicon et Intel
                    homebrew_paths = ["/opt/homebrew", "/usr/local"]
                    for brew_path in homebrew_paths:
                        magick_lib = os.path.join(brew_path, "lib")
                        if os.path.exists(magick_lib):
                            env["MAGICK_HOME"] = brew_path
                            env["DYLD_LIBRARY_PATH"] = magick_lib + ":" + env.get("DYLD_LIBRARY_PATH", "")
                            env["PATH"] = os.path.join(brew_path, "bin") + ":" + env.get("PATH", "")
                            break
                
                # Ajouter la taille de redimensionnement pour Redimensionner.py
                if app_name == "Redimensionner.py":
                    env["RESIZE_SIZE"] = resize_size["value"]
                
                # Ajouter la taille de redimensionnement avec watermark pour Redimensionner filigrane.py
                if app_name == "Redimensionner filigrane.py":
                    env["RESIZE_WATERMARK_SIZE"] = resize_watermark_size["value"]
                
                # Ajouter le dossier destination pour Transfert vers TEMP.py
                if app_name == "Transfert vers TEMP.py":
                    if platform.system() == "Windows":
                        env["DEST_FOLDER"] = "Z:/temp"
                    else:
                        env["DEST_FOLDER"] = "/Volumes/TRAVAUX EN COURS/Z2026/TEMP"
                
                # Ajouter le nom de la série pour Renommer sequence.py
                if app_name == "Renommer sequence.py" and series_name:
                    env["SERIES_NAME"] = series_name

                # Ajouter le nom du PDF pour Images en PDF.py
                if app_name == "Images en PDF.py" and series_name:
                    env["PDF_NAME"] = series_name

                # Ajouter les fichiers sélectionnés (si aucun n'est sélectionné, la variable sera vide)
                if selected_files:
                    env["SELECTED_FILES"] = "|".join(os.path.basename(f) for f in selected_files)
                
                process = subprocess.Popen(
                    [sys.executable, "-u", app_path],
                    cwd=os.path.join(cwd, "Data"),
                    env=env,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    text=True,
                    encoding="utf-8",
                    errors="replace",
                    bufsize=1,
                )
                if platform.system() == "Windows":
                    try:
                        import ctypes
                        ctypes.windll.user32.AllowSetForegroundWindow(process.pid)
                    except Exception:
                        pass

                
                # Lire la sortie en temps réel
                def read_output(pipe, color):
                    """
                    Lit en temps réel une pipe stdout ou stderr du sous-processus
                    et envoie chaque ligne au terminal.

                    Détecte les lignes préfixées par ``SELECTED_FILES:`` pour
                    resélectionner des fichiers dans la preview après exécution
                    du script.

                    Parameters
                    ----------
                    pipe : IO
                        Pipe stdout ou stderr du subprocess.
                    color : str
                        Couleur hexadécimale pour l'affichage dans le terminal.
                    """
                    try:
                        for line in iter(pipe.readline, ''):
                            if line:
                                line_stripped = line.rstrip()
                                if line_stripped.startswith(selected_files_prefix):
                                    selected_names = line_stripped[len(selected_files_prefix):]
                                    # Stocker pour que on_preview_ready l'applique
                                    # avec les données fraîches du prochain scan.
                                    _pending_selection["names"] = selected_names
                                else:
                                    log_to_terminal(line_stripped, color)
                    except Exception as read_err:
                        log_to_terminal(f"[ERREUR] Lecture sortie script: {read_err}", RED)
                    finally:
                        pipe.close()
                
                t_stdout = threading.Thread(target=read_output, args=(process.stdout, WHITE), daemon=True)
                t_stderr = threading.Thread(target=read_output, args=(process.stderr, RED), daemon=True)
                t_stdout.start()
                t_stderr.start()
                
                # Attendre la fin et rafraîchir la preview
                def done():
                    """
                    Attend la fin du sous-processus ET la lecture complète des pipes,
                    puis journalise le résultat et demande un rafraîchissement de la preview.
                    On attend les threads de lecture pour s'assurer que SELECTED_FILES:
                    a bien été traité avant de déclencher le refresh.
                    """
                    t_stdout.join()
                    t_stderr.join()
                    process.wait()
                    log_to_terminal(f"[OK] {display_name} terminé", GREEN)
                    # Rafraîchir la preview pour afficher les nouveaux dossiers/fichiers créés
                    request_refresh()
                
                threading.Thread(target=done, daemon=True).start()
        except Exception as err:
            log_to_terminal(f"[ERREUR] Erreur lors du lancement: {err}", RED)

    # ── Handlers des champs Redimensionner ───────────────────────────
    def on_resize_input_change(e):
        """Met à jour la taille de redimensionnement cible en pixels."""
        resize_size["value"] = e.control.value

    def launch_resize(e):
        """Lance Redimensionner.py avec la taille saisie dans resize_input."""
        app_path = os.path.join(cwd, "Data", "Redimensionner.py")
        if os.path.exists(app_path):
            launch_app("Redimensionner.py", app_path, False)

    def on_resize_watermark_input_change(e):
        """Met à jour la taille de redimensionnement+filigrane cible en pixels."""
        resize_watermark_size["value"] = e.control.value

    def launch_resize_watermark(e):
        """Lance Redimensionner filigrane.py avec la taille saisie dans resize_watermark_input."""
        app_path = os.path.join(cwd, "Data", "Redimensionner filigrane.py")
        if os.path.exists(app_path):
            launch_app("Redimensionner filigrane.py", app_path, False)

    def refresh_apps():
        """
        Reconstruit la grille des applications disponibles.

        Filtre les scripts présents sur disque, crée des widgets spéciaux
        (champ numérique + bouton) pour ``Redimensionner.py`` et
        ``Redimensionner filigrane.py``, et des boutons simples pour les autres.
        """
        items = []

        for app_name, app_config in apps.items():
            is_local = app_config[0]
            app_color = app_config[1]
            app_path = os.path.join(cwd, "Data", app_name)
            if not os.path.exists(app_path):
                continue

            if app_name == "Redimensionner.py":
                items.append(
                    ft.Container(
                        content=ft.Column([
                            ft.Text("Redimensionner", size=13, color=app_color, weight=ft.FontWeight.W_500, text_align=ft.TextAlign.CENTER),
                            resize_input,
                            ft.Text("px", size=11, color=LIGHT_GREY, text_align=ft.TextAlign.CENTER),
                        ], horizontal_alignment=ft.CrossAxisAlignment.CENTER, alignment=ft.MainAxisAlignment.CENTER, spacing=3),
                        expand=True,
                        alignment=ft.Alignment(0, 0),
                        bgcolor=GREY,
                        border=ft.Border.all(1, app_color),
                        padding=ft.Padding(5, 8, 5, 8),
                        border_radius=4,
                        on_click=launch_resize,
                        ink=True,
                    )
                )
            elif app_name == "Redimensionner filigrane.py":
                items.append(
                    ft.Container(
                        content=ft.Column([
                            ft.Text("Redimensionner + filigrane", size=12, color=app_color, weight=ft.FontWeight.W_500, text_align=ft.TextAlign.CENTER),
                            resize_watermark_input,
                            ft.Text("px", size=11, color=LIGHT_GREY, text_align=ft.TextAlign.CENTER),
                        ], horizontal_alignment=ft.CrossAxisAlignment.CENTER, alignment=ft.MainAxisAlignment.CENTER, spacing=3),
                        expand=True,
                        alignment=ft.Alignment(0, 0),
                        bgcolor=GREY,
                        border=ft.Border.all(1, app_color),
                        padding=ft.Padding(5, 8, 5, 8),
                        border_radius=4,
                        on_click=launch_resize_watermark,
                        ink=True,
                    )
                )
            else:
                items.append(
                    ft.Container(
                        content=ft.Text(
                            app_name[:-4] if app_name.endswith(".pyw") else app_name[:-3],
                            size=14,
                            color=app_color,
                            text_align=ft.TextAlign.CENTER,
                            weight=ft.FontWeight.W_500,
                            max_lines=3,
                        ),
                        expand=True,
                        alignment=ft.Alignment(0, 0),
                        on_click=lambda e, name=app_name, path=app_path, local=is_local: launch_app(name, path, local),
                        bgcolor=GREY,
                        border=ft.Border.all(1, app_color),
                        padding=ft.Padding(10, 10, 10, 10),
                        border_radius=4,
                        ink=True,
                    )
                )

        # Grouper en rangées de 3 avec padding uniforme
        apps_list.controls.clear()
        for i in range(0, len(items), 3):
            row_items = items[i:i + 3]
            # Compléter la dernière rangée si incomplète
            while len(row_items) < 3:
                row_items.append(ft.Container(expand=True))
            apps_list.controls.append(
                ft.Row(controls=row_items, expand=True, spacing=8)
            )
        page.update()

    # ================================================================ #
    #                       ACTIONS FENÊTRE                            #
    # ================================================================ #
    async def pick_folder(e):
        """
        Ouvre le sélecteur de dossier natif et navigue vers le dossier choisi.

        Appelle ``ft.FilePicker.get_directory_path`` de façon asynchrone,
        normalise le chemin résultant et déclenche un rafraîchissement de la preview.
        """
        folder = await ft.FilePicker().get_directory_path(dialog_title="Sélectionner un dossier contenant des images")
        if folder:
            selected_folder["path"] = os.path.normpath(folder)
            current_browse_folder["path"] = selected_folder["path"]
            folder_path.value = selected_folder["path"]
            folder_path.update()
            selected_files.clear()
            preview_page["value"] = 0
            _add_to_recent(selected_folder["path"])
            _refresh_recent_btn()
            refresh_preview()
    
    async def close_window(e):
        """Ferme la fenêtre principale de l'application de façon asynchrone."""
        await page.window.close()

    def minimize_window(e):
        """Réduit la fenêtre dans la barre des tâches."""
        page.window.minimized = True

    def toggle_maximize_window(e):
        """Bascule entre fenêtre maximisée et taille normale."""
        page.window.maximized = not page.window.maximized
        page.update()

    def update_app(e):
        """Sauvegarde les fichiers utilisateur, git pull --rebase, vérifie les dépendances si requirements a changé, relance."""
        page.pubsub.send_all_on_topic("terminal", ("Mise à jour en cours…", YELLOW))
        def _run():
            def pub(msg, color=LIGHT_GREY):
                page.pubsub.send_all_on_topic("terminal", (msg, color))

            def run_git(*args):
                return subprocess.run(
                    ["git", *args],
                    cwd=cwd,
                    capture_output=True,
                    text=True,
                    encoding="utf-8",
                    errors="replace",
                )

            # ── Sauvegarde mémoire des fichiers utilisateur avant git ─
            _user_files = [".recent_folders.json", ".favorites.json", ".pip_cache.json"]
            _backups = {}
            for fname in _user_files:
                fpath = os.path.join(cwd, fname)
                if os.path.isfile(fpath):
                    try:
                        with open(fpath, "r", encoding="utf-8") as f:
                            _backups[fname] = f.read()
                    except Exception:
                        pass

            def _restore_user_files():
                for fname, content in _backups.items():
                    fpath = os.path.join(cwd, fname)
                    try:
                        with open(fpath, "w", encoding="utf-8") as f:
                            f.write(content)
                    except Exception:
                        pass

            try:
                # Stash les changements locaux s'il y en a
                stash_result = run_git("stash")
                stashed = "No local changes" not in stash_result.stdout

                # Pull --rebase
                result = run_git("pull", "--rebase", "origin")
                output = (result.stdout + result.stderr).strip()

                if result.returncode != 0:
                    if stashed:
                        run_git("rebase", "--abort")
                        run_git("stash", "pop")
                    _restore_user_files()
                    pub(f"[ERREUR] Erreur lors de la mise à jour.\n{output}", RED)
                    return

                # Supprimer le stash (changements de code locaux non désirés)
                if stashed:
                    run_git("stash", "drop")

                # Restaurer systématiquement les fichiers utilisateur
                _restore_user_files()

                if "Already up to date" in output or "Déjà à jour" in output or output == "":
                    pub("[OK] Déjà à jour.", GREEN)
                else:
                    pub(f"[OK] Code mis à jour.\n{output}", GREEN)

                # ── Dépendances : pip uniquement si requirements.txt a changé ──
                req_path = os.path.join(cwd, "requirements.txt")
                pip_cache_path = os.path.join(cwd, ".pip_cache.json")
                if not os.path.isfile(req_path):
                    pub("⚠ requirements.txt introuvable, installation ignorée.", YELLOW)
                else:
                    with open(req_path, "rb") as f:
                        req_hash = hashlib.sha256(f.read()).hexdigest()

                    cached_hash = None
                    try:
                        with open(pip_cache_path, "r", encoding="utf-8") as f:
                            cached_hash = json.load(f).get("req_hash")
                    except Exception:
                        pass

                    if cached_hash == req_hash:
                        pub("[OK] Dépendances inchangées, installation ignorée.", GREEN)
                    else:
                        pub("📦 Nouvelles dépendances détectées, installation en cours…", YELLOW)
                        pip_proc = subprocess.Popen(
                            [sys.executable, "-m", "pip", "install", "-r", req_path, "--upgrade"],
                            stdout=subprocess.PIPE,
                            stderr=subprocess.STDOUT,
                            text=True,
                            encoding="utf-8",
                            errors="replace",
                            cwd=cwd,
                        )
                        for line in pip_proc.stdout:
                            line = line.rstrip()
                            if line:
                                pub(line)
                        pip_proc.wait()
                        if pip_proc.returncode == 0:
                            pub("[OK] Dépendances installées.", GREEN)
                            try:
                                with open(pip_cache_path, "w", encoding="utf-8") as f:
                                    json.dump(
                                        {"req_hash": req_hash,
                                         "updated_at": time.strftime("%Y-%m-%d %H:%M")},
                                        f, ensure_ascii=False, indent=2,
                                    )
                            except Exception:
                                pass
                        else:
                            pub(f"pip a terminé avec le code {pip_proc.returncode}.", YELLOW)

                # ── Redémarrage automatique ───────────────────────────────
                pub("🔄 Redémarrage du Dashboard…", BLUE)
                script = os.path.abspath(__file__)
                subprocess.Popen(
                    [
                        sys.executable, "-c",
                        f"import time, subprocess, sys; time.sleep(2); "
                        f"subprocess.Popen([sys.executable, r'{script}'])",
                    ],
                    close_fds=True,
                )
                request_quit()

            except Exception as exc:
                _restore_user_files()
                page.pubsub.send_all_on_topic("terminal", (f"[ERREUR] {exc}", RED))

        threading.Thread(target=_run, daemon=True).start()

# ===================== UI WIRING ===================== #
    # ── Champ dossier ────────────────────────────────────────────────
    folder_path.on_submit = on_folder_path_submit
    folder_path.on_blur = on_folder_path_blur

    # ── Preview ───────────────────────────────────────────────────────
    sort_segment.on_change = on_sort_change
    filter_segment.on_change = on_filter_segment_change
    _select_toggle_btn.on_click = toggle_select_all
    _invert_selection_btn.on_click = invert_selection
    prev_page_btn.on_click = lambda e: go_to_page(-1)
    next_page_btn.on_click = lambda e: go_to_page(+1)

    # ── Redimensionnement ─────────────────────────────────────────────
    resize_input.on_change = on_resize_input_change
    resize_watermark_input.on_change = on_resize_watermark_input_change

    # ── Initialisation ────────────────────────────────────────────────
    _refresh_recent_btn()
    refresh_apps()
    _refresh_favorites_ui()
    _initial_drives = _get_removable_drives()
    if _initial_drives:
        _removable_drives["list"] = _initial_drives
        _refresh_drives_ui(_initial_drives)
    threading.Thread(target=_drives_polling_thread, daemon=True).start()

# ===================== FLET UI ===================== #
    page.add(
        ft.WindowDragArea(
            ft.Row([
                ft.Container(
                    ft.Text(f"DASHBOARD {__version__}", size=24, color=WHITE),
                    bgcolor=BG,
                    padding=10,
                ),
                ft.IconButton(
                    icon=ft.Icons.SYSTEM_UPDATE_ALT,
                    tooltip="Mettre à jour (git pull --rebase)",
                    on_click=update_app,
                    icon_color=LIGHT_GREY,
                    bgcolor=DARK,
                    icon_size=18,
                ),
                ft.Container(expand=True),
                folder_path,
                recent_folders_btn,
                ft.Button(
                    "Parcourir",
                    icon=ft.Icons.FOLDER_OPEN,
                    bgcolor=GREY,
                    color=RED,
                    on_click=pick_folder,
                ),
                ft.Button(
                    "Rafraîchir",
                    icon=ft.Icons.REFRESH,
                    bgcolor=GREY,
                    color=BLUE,
                    on_click=lambda e: refresh_preview(),
                ),
                ft.Button(
                    "Ouvrir l'explorateur",
                    icon=ft.Icons.FOLDER_OPEN,
                    on_click=lambda e: open_in_file_explorer(current_browse_folder["path"] or selected_folder["path"]),
                    bgcolor=GREY,
                    color=GREEN,
                    height=35,
                ),
                ft.Container(expand=True),
                ft.IconButton(
                    icon=ft.Icons.MINIMIZE, on_click=minimize_window,),
                ft.IconButton(
                    icon=ft.Icons.FULLSCREEN,
                    on_click=toggle_maximize_window,
                    tooltip="Maximiser / Restaurer",
                ),
                ft.IconButton(ft.Icons.CLOSE, on_click=close_window),
            ])
        ),
        ft.Column([
            ft.Divider(),
            ft.Row([
                ft.Column([
                    ft.Row([
                        ft.Container(
                            content=ft.Text("Applications disponibles", weight=ft.FontWeight.BOLD, size=14, color=WHITE),
                            margin=ft.Margin.only(top=10, bottom=10, left=10),
                        ),
                        ft.Container(width=48),  # Espacement entre le titre et les boutons
                        ft.IconButton(
                            icon=ft.Icons.KEYBOARD_DOUBLE_ARROW_LEFT_SHARP,
                            tooltip="Kiosk gauche",
                            on_click=lambda e: launch_app("Kiosk gauche.py", os.path.join(cwd, "Data", "Kiosk gauche.py"), True),
                            icon_color=VIOLET,
                            bgcolor=DARK,
                            icon_size=18,
                        ),
                        ft.IconButton(
                            icon=ft.Icons.KEYBOARD_DOUBLE_ARROW_RIGHT_SHARP,
                            tooltip="Kiosk droite",
                            on_click=lambda e: launch_app("Kiosk droite.py", os.path.join(cwd, "Data", "Kiosk droite.py"), True),
                            icon_color=VIOLET,
                            bgcolor=DARK,
                            icon_size=18,
                        ),
                        ft.IconButton(
                            icon=ft.Icons.AUTO_DELETE,
                            tooltip="Nettoyer anciens fichiers (> 60 jours)",
                            on_click=lambda e: launch_app("Nettoyer anciens fichiers.py", os.path.join(cwd, "Data", "Nettoyer anciens fichiers.py"), True),
                            icon_color=ORANGE,
                            bgcolor=GREY,
                            icon_size=18,
                        ),
                    ]),
                    ft.Container(
                        content=apps_list,
                        expand=True,
                        border=ft.Border.all(1, GREY),
                        border_radius=8,
                        bgcolor=DARK,
                        padding=8,
                    ),
                ], expand=True),
                ft.Column([
                    ft.Row([
                        ft.Text("Contenu du dossier", weight=ft.FontWeight.BOLD, size=14, color=WHITE, margin=ft.Margin.only(left=10)),
                        ft.IconButton(
                            icon=ft.Icons.ARROW_UPWARD,
                            tooltip="Dossier parent",
                            on_click=go_to_parent_folder,
                            icon_color=BLUE,
                            icon_size=20,
                        ),
                        _select_toggle_btn,
                        _invert_selection_btn,
                        ft.IconButton(
                            icon=ft.Icons.DELETE_SWEEP,
                            tooltip="Supprimer les fichiers sélectionnés",
                            on_click=delete_selected_files,
                            icon_color=RED,
                            icon_size=20,
                        ),
                        ft.Container(expand=True),
                        selection_count_text,
                        ft.Container(width=6),
                        file_count_text,
                        ft.Container(width=4),
                        prev_page_btn,
                        page_indicator_text,
                        next_page_btn,
                    ], spacing=5, vertical_alignment=ft.CrossAxisAlignment.CENTER, height=36),
                    ft.Row([
                        filter_segment,
                        ft.Container(expand=True),
                        ft.IconButton(
                            icon=ft.Icons.CONTENT_COPY,
                            tooltip="Copier les fichiers sélectionnés (Ctrl+C)",
                            on_click=copy_selected_files,
                            icon_color=BLUE,
                            icon_size=18,
                        ),
                        ft.IconButton(
                            icon=ft.Icons.CONTENT_CUT,
                            tooltip="Couper les fichiers sélectionnés (Ctrl+X)",
                            on_click=cut_selected_files,
                            icon_color=ORANGE,
                            icon_size=18,
                        ),
                        ft.IconButton(
                            icon=ft.Icons.CONTENT_PASTE,
                            tooltip="Coller les fichiers (Ctrl+V)",
                            on_click=paste_files,
                            icon_color=YELLOW,
                            icon_size=18,
                        ),
                        ft.IconButton(
                            icon=ft.Icons.CREATE_NEW_FOLDER,
                            tooltip="Créer un nouveau dossier (Ctrl+N)",
                            on_click=create_new_folder,
                            icon_color=GREEN,
                            icon_size=18,
                        ),
                        sort_segment
                    ], spacing=5, vertical_alignment=ft.CrossAxisAlignment.CENTER),
                    ft.Container(
                        content=ft.Stack([
                            preview_list,
                            preview_loading,
                        ]),
                        expand=True,
                        border=ft.Border.all(1, GREY),
                        border_radius=8,
                        bgcolor=DARK,
                    )
                ], expand=True)
            ], expand=True, spacing=8),
            ft.Container(
                content=ft.Row([
                    # ── Terminal (gauche) ────────────────────────────
                    ft.Column([
                        ft.Row([
                            ft.Container(width=8),
                            ft.Text("Terminal", weight=ft.FontWeight.BOLD, size=14, color=WHITE),
                            ft.IconButton(
                                icon=ft.Icons.COPY_ALL,
                                tooltip="Copier le terminal",
                                on_click=lambda e: copy_terminal_to_clipboard(),
                                icon_color=BLUE,
                                icon_size=18,
                            ),
                            ft.IconButton(
                                icon=ft.Icons.CLEAR_ALL,
                                tooltip="Effacer le terminal",
                                on_click=clear_terminal,
                                icon_color=RED,
                                icon_size=18,
                            ),
                        ], spacing=5, vertical_alignment=ft.CrossAxisAlignment.CENTER),
                        ft.Container(
                            content=terminal_output,
                            expand=True,
                            border=ft.Border.all(1, GREY),
                            border_radius=8,
                            bgcolor=DARK,
                            padding=5,
                        ),
                    ], expand=True, spacing=5),
                    # ── Favoris & Périphériques (droite) ─────────────
                    ft.Row([
                        _favorites_container,
                        _drives_container,
                    ], expand=True, spacing=8, vertical_alignment=ft.CrossAxisAlignment.STRETCH),
                ], spacing=8, expand=True),
                height=150,
            ),
        ], expand=True, spacing=8)
    )

    # ── Mettre la fenêtre en plein écran ────────────────────────────────────────────────
    async def _maximize():
        page.window.maximized = True
        page.update()

    page.run_task(_maximize)

#############################################################
#                            RUN                            #
#############################################################
# Neutralise l'erreur asyncio Windows "ConnectionResetError: [WinError 10054]"
# qui apparaît lors de la fermeture des pipes des sous-processus.
# C'est un bug connu de la boucle ProactorEventLoop sous Windows — sans impact fonctionnel.
if sys.platform == "win32":
    _original_exception_handler = None

    def _silence_proactor_pipe_errors(loop, context):
        exc = context.get("exception")
        if isinstance(exc, (ConnectionResetError, BrokenPipeError)):
            return
        if _original_exception_handler:
            _original_exception_handler(loop, context)
        else:
            loop.default_exception_handler(context)

    _loop = asyncio.new_event_loop()
    _original_exception_handler = _loop.get_exception_handler()
    _loop.set_exception_handler(_silence_proactor_pipe_errors)
    asyncio.set_event_loop(_loop)

ft.run(main)
