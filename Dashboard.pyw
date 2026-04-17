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

__version__ = "2.1.1"



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


# ===================== COULEURS ===================== #
    DARK = "#222429"
    BACKGROUND = "#373d4a"
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



# ===================== PROPRIÉTÉS ===================== #
    page.title = "Dashboard - Image Manipulations"
    page.theme_mode = ft.ThemeMode.DARK
    page.bgcolor = BACKGROUND
    page.window.title_bar_hidden = True
    page.window.title_bar_buttons_hidden = True
    page.window.width = 1400
    page.window.height = 840
    selected_folder = {"path": None}
    current_browse_folder = {"path": None}
    app_directory = os.path.dirname(os.path.abspath(__file__))
    selected_files = set()  # Ensemble des fichiers sélectionnés
    clipboard = {"files": [], "cut": False}  # Presse-papiers pour copier/coller/couper des fichiers



    # ── Dossiers récents ──────────────────────────────────────────────
    recent_folders_file_path = os.path.join(app_directory, ".recent_folders.json")

    def _load_recent() -> list:
        try:
            with open(recent_folders_file_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            return [p for p in data if os.path.isdir(p)]
        except Exception:
            return []



    def _save_recent(folders: list) -> None:
        try:
            with open(recent_folders_file_path, "w", encoding="utf-8") as f:
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
    favorites_file_path = os.path.join(app_directory, ".favorites.json")



    # ── Programmes "Ouvrir avec" ──────────────────────────────────────
    open_with_config_file_path = os.path.join(app_directory, "open_with.json")

    def _load_favorites() -> list:
        try:
            with open(favorites_file_path, "r", encoding="utf-8") as f:
                raw = json.load(f)
            result = []
            for item in raw:
                if isinstance(item, str):
                    result.append({"path": item, "label": ""})
                elif isinstance(item, dict) and "path" in item:
                    result.append({"path": item["path"], "label": item.get("label", "")})
            return result
        except Exception:
            return []



    def _save_favorites(folders: list) -> None:
        try:
            with open(favorites_file_path, "w", encoding="utf-8") as f:
                json.dump(folders, f, ensure_ascii=False, indent=2)
        except Exception:
            pass



    # Configuration: nom du fichier -> True si l'app est locale (pas besoin de dossier sélectionné)
    apps = {
        "Transfert vers TEMP.py": (True, BLUE),
        "Conversion JPG.py": (False, BLUE),
        "Renommer sequence.py": (False, BLUE),
        "Format 13x10.py": (False, HOVER_YELLOW),
        "Format 13x15.py": (False, HOVER_YELLOW),
        "Recadrage.pyw": (False, BLUE),
        "Redimensionner filigrane.py": (False, WHITE),
        "2 en 1.py": (False, HOVER_YELLOW),
        "Redimensionner.py": (False, WHITE),
    }



    resize_size = {"value": "640"}  # Taille par défaut pour le redimensionnement
    resize_watermark_size = {"value": "640"}  # Taille par défaut pour le redimensionnement avec watermark
    sort_mode = {"value": 0}  # 0 = A→Z, 1 = Z→A, 2 = par date de modification
    filter_type = {"value": "all"}  # "all", "images", "videos", "zip", "docs", "other"
    removable_drives_state = {"list": []}  # [(name, path), ...]
    lazy_images = []  # [(list_index, file_path, image_ctrl)] pour le chargement paresseux
    PAGE_SIZE = 100             # Nb d'éléments max par page dans la prévisualisation
    preview_page = {"value": 0}  # Page courante (0-indexé)
    all_entries_data = {"list": [], "error": ""}  # Données brutes du dernier scan
    pending_file_selection = {"names": None}  # Noms à sélectionner après le prochain scan
    preview_refresh_token = {"value": 0}   # incrémenté à chaque refresh pour annuler les anciens threads
    search_query = {"value": ""}  # Requête de recherche active dans la preview



# ===================== ÉLÉMENTS UI ===================== #
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
    quick_tools_col = ft.Column([], spacing=10, horizontal_alignment=ft.CrossAxisAlignment.CENTER)
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
    select_toggle_button = ft.IconButton(
        icon=ft.Icons.SELECT_ALL,
        icon_color=VIOLET,
        icon_size=22,
        tooltip="Tout sélectionner",
    )
    invert_selection_button = ft.IconButton(
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

    # ── Barre de recherche dans la preview ────────────────────────────
    search_field = ft.TextField(
        hint_text="Rechercher...",
        border_color=BLUE,
        text_size=13,
        height=32,
        width=180,
        content_padding=ft.Padding(8, 2, 8, 2),
        prefix_icon=ft.Icons.SEARCH,
        bgcolor=DARK,
    )
    search_close_btn = ft.IconButton(
        icon=ft.Icons.CLOSE,
        icon_color=LIGHT_GREY,
        icon_size=16,
        tooltip="Fermer la recherche",
        style=ft.ButtonStyle(padding=ft.Padding.all(4)),
    )
    search_active_row = ft.Row(
        [search_field, search_close_btn],
        spacing=0, tight=True,
        vertical_alignment=ft.CrossAxisAlignment.CENTER,
        visible=False,
    )
    search_icon_btn = ft.IconButton(
        icon=ft.Icons.SEARCH,
        icon_color=WHITE,
        icon_size=20,
        tooltip="Rechercher dans les fichiers",
    )



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
    FILTER_KEYS   = ["all",  "images", "zip", "docs", "other"]
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
    favorites_list_view = ft.ReorderableListView(expand=True, spacing=2, auto_scroll=False, padding=ft.Padding(12, 6, 12, 6), show_default_drag_handles=False)
    favorites_panel = ft.Container(
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
            favorites_list_view,
        ], spacing=4, expand=True),
        bgcolor=GREY,
        border=ft.Border.all(1, BLUE),
        border_radius=6,
        padding=ft.Padding(12, 6, 12, 6),
        expand=True,
    )



    # ── Section périphériques amovibles ──────────────────────────────
    drives_list_view = ft.ReorderableListView(expand=True, spacing=4, auto_scroll=False, padding=ft.Padding(12, 6, 12, 6), show_default_drag_handles=False)
    drives_panel = ft.Container(
        content=ft.Column([
            ft.Row([
                ft.Icon(ft.Icons.USB, size=14, color=VIOLET),
                ft.Text("Périphériques détectés", size=14, color=VIOLET,
                        weight=ft.FontWeight.BOLD),
            ], spacing=6, tight=True),
            drives_list_view,
        ], spacing=4, expand=True),
        bgcolor=GREY,
        border=ft.Border.all(1, VIOLET),
        border_radius=6,
        padding=ft.Padding(12, 6, 12, 6),
        expand=True,
        visible=False,
    )



# ===================== MÉTHODES ===================== #
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
            # Ignorer les erreurs si la page est en cours de fermeture ou déjà détruite
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


    def on_restore_window(topic, message):
        """Restaure la fenêtre Dashboard quand Selecteur se ferme."""
        page.window.minimized = False
        page.update()

    page.pubsub.subscribe_topic("restore_window", on_restore_window)


    def _launch_selecteur(extra_env: dict = None):
        """Lance Selecteur, minimise Dashboard, puis le restaure à la fermeture de Selecteur."""
        env = {
            **os.environ,
            "SELECTEUR_INITIAL_FOLDER": (
                current_browse_folder["path"] or selected_folder["path"] or ""
            ),
        }
        if extra_env:
            env.update(extra_env)
        proc = subprocess.Popen(
            [sys.executable, os.path.join(app_directory, "Selecteur.pyw")],
            env=env,
        )
        page.window.minimized = True
        page.update()

        def _watch():
            proc.wait()
            page.pubsub.send_all_on_topic("restore_window", None)

        threading.Thread(target=_watch, daemon=True).start()



    def on_preview_ready(topic, payload):
        """Reçoit les données brutes du thread bg et déclenche le rendu de la page courante."""
        token, entries_data, new_file_count_text, error_text = payload
        if preview_refresh_token["value"] != token:
            return
        all_entries_data["list"] = entries_data
        all_entries_data["error"] = error_text
        file_count_text.value = new_file_count_text
        # Appliquer la sélection en attente si un script l'a demandé
        # (ex: Fichiers manquants). On le fait ICI avec les données fraîches
        # pour éviter tout race condition entre threads.
        if pending_file_selection["names"] is not None:
            names_to_apply = pending_file_selection["names"]
            pending_file_selection["names"] = None
            apply_selected_files_by_name(names_to_apply)
        else:
            _render_preview_page()

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



    def _rebuild_recent_folders_menu():
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
            with open(open_with_config_file_path, "r", encoding="utf-8") as f:
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
            with open(open_with_config_file_path, "w", encoding="utf-8") as f:
                json.dump(programs, f, ensure_ascii=False, indent=2)
        except Exception as err:
            log_to_terminal(f"[ERREUR] Sauvegarde open_with.json : {err}", RED)



    def _show_open_with_menu(files: list):
        """Affiche le dialog 'Ouvrir avec' pour les fichiers sélectionnés."""

        header_label = (
            os.path.basename(files[0]) if len(files) == 1
            else f"{len(files)} fichier(s) sélectionné(s)"
        )

        # Champs du formulaire d'ajout
        add_label_field = ft.TextField(
            hint_text="Nom affiché (ex : Affinity)",
            border_color=BLUE, text_size=13, height=40,
            content_padding=ft.Padding(8, 4, 8, 4), expand=True,
        )
        add_exe_field = ft.TextField(
            hint_text="Chemin exe (ex : C:\\...\\Affinity.exe)",
            border_color=BLUE, text_size=13, height=40,
            content_padding=ft.Padding(8, 4, 8, 4), expand=True,
        )

        async def _browse_exe(e):
            result = await ft.FilePicker().pick_files(
                dialog_title="Choisir l'exécutable",
                allow_multiple=False,
            )
            if result:
                add_exe_field.value = result[0].path
                add_exe_field.update()

        browse_exe_btn = ft.IconButton(
            icon=ft.Icons.FOLDER_OPEN,
            icon_color=BLUE,
            icon_size=20,
            tooltip="Parcourir…",
            on_click=_browse_exe,
            style=ft.ButtonStyle(padding=ft.Padding.all(4)),
        )

        add_form = ft.Container(
            content=ft.Column([
                ft.Divider(height=8, color=GREY),
                ft.Text("Ajouter un programme", size=12, color=LIGHT_GREY),
                ft.Row([add_label_field], tight=True),
                ft.Row([add_exe_field, browse_exe_btn], tight=True),
            ], spacing=6, tight=True),
            visible=False,
        )

        programs_list_view = ft.ReorderableListView(padding=0, show_default_drag_handles=False)
        open_with_dialog = ft.AlertDialog(
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
            content=ft.Column([programs_list_view, add_form],
                              spacing=0, tight=True, width=340),
            actions_alignment=ft.MainAxisAlignment.END,
        )

        def _rebuild_items():
            programs = _load_open_with_programs()
            programs_list_view.controls.clear()
            if not programs:
                programs_list_view.controls.append(ft.Container(
                    key="empty",
                    content=ft.Text(
                        "Aucun programme configuré — cliquez + pour en ajouter.",
                        size=12, color=LIGHT_GREY,
                    ),
                    padding=ft.Padding(0, 6, 0, 6),
                ))
            else:
                for i, prog in enumerate(programs):
                    def _create_open_handler(p):
                        def _open_with_clicked(e):
                            open_with_dialog.open = False
                            page.update()
                            _open_files_with(p, files)
                        return _open_with_clicked
                    def _create_delete_handler(p):
                        def _delete_program_clicked(e):
                            programs = _load_open_with_programs()
                            programs = [x for x in programs if x != p]
                            _save_open_with_programs(programs)
                            _rebuild_items()
                            programs_list_view.update()
                        return _delete_program_clicked
                    programs_list_view.controls.append(ft.ListTile(
                        key=str(i),
                        leading=ft.ReorderableDragHandle(
                            content=ft.Icon(ft.Icons.DRAG_HANDLE,
                                            color=LIGHT_GREY, size=18),
                        ),
                        title=ft.Text(prog["label"], size=13, color=WHITE),
                        trailing=ft.IconButton(
                            icon=ft.Icons.CLOSE, icon_size=16,
                            icon_color=LIGHT_GREY, tooltip="Supprimer",
                            on_click=_create_delete_handler(prog),
                            style=ft.ButtonStyle(padding=ft.Padding.all(4)),
                        ),
                        on_click=_create_open_handler(prog),
                        hover_color=GREY, dense=True,
                        content_padding=ft.Padding(0, 0, 0, 0),
                    ))

        def _on_reorder(e: ft.OnReorderEvent):
            programs_list_view.controls.insert(e.new_index, programs_list_view.controls.pop(e.old_index))
            programs = _load_open_with_programs()
            programs.insert(e.new_index, programs.pop(e.old_index))
            _save_open_with_programs(programs)
            programs_list_view.update()

        programs_list_view.on_reorder = _on_reorder

        def _toggle_add_form():
            add_form.visible = not add_form.visible
            add_program_button.visible = add_form.visible
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
            programs = _load_open_with_programs()
            programs.append({"label": label, "exe": exe})
            _save_open_with_programs(programs)
            add_form.visible = False
            add_program_button.visible = False
            _rebuild_items()
            page.update()

        def _close(e):
            open_with_dialog.open = False
            page.update()

        add_program_button = ft.TextButton("Ajouter", on_click=_confirm_add, visible=False)
        open_with_dialog.actions = [
            add_program_button,
            ft.TextButton("Fermer",  on_click=_close),
        ]

        _rebuild_items()
        page.overlay.append(open_with_dialog)
        open_with_dialog.open = True
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
        _rebuild_recent_folders_menu()
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
            current_image_index = {"value": image_paths.index(start_path)}
        except ValueError:
            current_image_index = {"value": 0}
            image_paths = [start_path]

        previous_keyboard_handler = page.on_keyboard_event



        # ── Helpers ──────────────────────────────────────────────────────
        def _get_resolution(path):
            if _PILImage:
                try:
                    with _PILImage.open(path) as opened_image:
                        return f"{opened_image.width} × {opened_image.height}"
                except Exception:
                    pass
            return ""



        # ── Contrôles texte ───────────────────────────────────────────────
        filename_text = ft.Text(
            os.path.basename(image_paths[current_image_index["value"]]),
            size=13,
            color=ft.Colors.WHITE,
            weight=ft.FontWeight.W_500,
            max_lines=1,
            overflow=ft.TextOverflow.ELLIPSIS,
        )
        counter_text = ft.Text(
            f"{current_image_index['value'] + 1} / {len(image_paths)}",
            size=12,
            color=ft.Colors.WHITE70,
        )
        resolution_text = ft.Text(
            _get_resolution(image_paths[current_image_index["value"]]),
            size=12,
            color=ft.Colors.WHITE54,
        )
        viewer_checkbox = ft.Checkbox(
            value=image_paths[current_image_index["value"]] in selected_files,
            on_change=lambda e: on_checkbox_change(e, image_paths[current_image_index["value"]]),
        )



        # ── InteractiveViewer ─────────────────────────────────────────────
        # On recrée l'InteractiveViewer à chaque changement d'image pour
        # remettre le zoom et le pan à zéro.
        viewer_key_counter = {"count": 0}

        def _create_interactive_viewer(path):
            viewer_key_counter["count"] += 1
            window_width = page.window.width or 1280
            window_height = page.window.height or 800
            return ft.InteractiveViewer(
                key=str(viewer_key_counter["count"]),
                content=ft.Image(
                    src=path,
                    width=window_width,
                    height=window_height,
                    fit=ft.BoxFit.CONTAIN,
                    error_content=ft.Icon(ft.Icons.BROKEN_IMAGE, color=ft.Colors.WHITE54),
                ),
                min_scale=0.5,
                max_scale=10.0,
                pan_enabled=True,
                scale_enabled=True,
                width=window_width,
                height=window_height,
                clip_behavior=ft.ClipBehavior.HARD_EDGE,
            )

        viewer_container = ft.Container(
            content=_create_interactive_viewer(image_paths[current_image_index["value"]]),
            expand=True,
            alignment=ft.Alignment(0, 0),
        )



        # ── Navigation image ──────────────────────────────────────────────
        def _load_image(path):
            viewer_container.content   = _create_interactive_viewer(path)
            filename_text.value    = os.path.basename(path)
            counter_text.value     = f"{current_image_index['value'] + 1} / {len(image_paths)}"
            resolution_text.value  = _get_resolution(path)
            viewer_checkbox.value  = path in selected_files
            page.update()

        def go_prev(e):
            if len(image_paths) > 1:
                current_image_index["value"] = (current_image_index["value"] - 1) % len(image_paths)
                _load_image(image_paths[current_image_index["value"]])

        def go_next(e):
            if len(image_paths) > 1:
                current_image_index["value"] = (current_image_index["value"] + 1) % len(image_paths)
                _load_image(image_paths[current_image_index["value"]])

        def close_viewer(e):
            page.on_keyboard_event = previous_keyboard_handler
            page.theme = ft.Theme(
                page_transitions=ft.PageTransitionsTheme(
                    macos=ft.PageTransitionTheme.NONE,
                    windows=ft.PageTransitionTheme.NONE,
                    linux=ft.PageTransitionTheme.NONE,
                )
            )
            if len(page.views) > 1:
                page.views.pop()
            # Restaurer la page de la preview_list sur celle contenant la dernière image visionnée
            current_path = image_paths[current_image_index["value"]]
            all_entry_paths = [entry_path for (_name, entry_path, _is_dir, _is_img, _ext) in all_entries_data["list"]]
            try:
                entry_index = all_entry_paths.index(current_path)
                preview_page["value"] = entry_index // PAGE_SIZE
            except ValueError:
                pass
            refresh_preview(reset_page=False)
            page.update()

        def delete_current_image(e):
            path = image_paths[current_image_index["value"]]
            fname = os.path.basename(path)

            def _confirm(e2):
                page.on_keyboard_event = on_key
                delete_confirmation_dialog.open = False
                page.update()
                try:
                    os.remove(path)
                    image_paths.pop(current_image_index["value"])
                    log_to_terminal(f"[OK] Supprimé: {fname}", GREEN)
                except Exception as err:
                    log_to_terminal(f"[ERREUR] {err}", RED)
                    return
                if not image_paths:
                    close_viewer(None)
                    return
                current_image_index["value"] = min(current_image_index["value"], len(image_paths) - 1)
                _load_image(image_paths[current_image_index["value"]])

            def _cancel(e2):
                page.on_keyboard_event = on_key
                delete_confirmation_dialog.open = False
                page.update()

            def _on_key_dialog(e2: ft.KeyboardEvent):
                if e2.key == "Escape":
                    _cancel(None)
                elif e2.key == "Enter":
                    _confirm(None)

            delete_confirmation_dialog = ft.AlertDialog(
                title=ft.Text("Supprimer l'image ?"),
                content=ft.Text(f"'{fname}' sera définitivement supprimé."),
                actions=[
                    ft.TextButton("Annuler", on_click=_cancel),
                    ft.TextButton("Supprimer", on_click=_confirm, style=ft.ButtonStyle(color=ft.Colors.RED)),
                ],
            )
            page.overlay.append(delete_confirmation_dialog)
            delete_confirmation_dialog.open = True
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

        button_style = ft.ButtonStyle(
            overlay_color=ft.Colors.with_opacity(0.15, ft.Colors.WHITE),
        )

        overlay_bar_color = ft.Colors.with_opacity(0.72, GREY)

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
                    bgcolor=overlay_bar_color,
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
                style=button_style,
            ),
            bgcolor=overlay_bar_color,
            border_radius=20,
        )

        navigation_bar = ft.Container(
            content=ft.Row(
                [
                    ft.IconButton(
                        icon=ft.Icons.ARROW_BACK_IOS_NEW_ROUNDED,
                        icon_color=ft.Colors.WHITE,
                        icon_size=26,
                        tooltip="Image précédente",
                        on_click=go_prev,
                        style=button_style,
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
                        style=button_style,
                    ),
                    ft.IconButton(
                        icon=ft.Icons.ARROW_FORWARD_IOS_ROUNDED,
                        icon_color=ft.Colors.WHITE,
                        icon_size=26,
                        tooltip="Image suivante",
                        on_click=go_next,
                        style=button_style,
                    ),
                ],
                alignment=ft.MainAxisAlignment.CENTER,
                vertical_alignment=ft.CrossAxisAlignment.CENTER,
                tight=True,
            ),
            bgcolor=overlay_bar_color,
            padding=ft.Padding.symmetric(horizontal=8, vertical=6),
            border_radius=16,
        )

        navigation_bar_row = ft.Row(
            [navigation_bar],
            alignment=ft.MainAxisAlignment.CENTER,
        )

        viewer_view = ft.View(
            route="/image_viewer",
            bgcolor="#3c3c3c",
            padding=0,
            controls=[
                ft.Stack(
                    [
                        viewer_container,
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
                            content=navigation_bar_row,
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



    def _open_json_in_selecteur(file_path):
        """Lance le Sélecteur avec le fichier JSON pré-chargé dans l'onglet Liste."""
        log_to_terminal(
            f"[OK] Ouverture dans Sélecteur → Liste : {os.path.basename(file_path)}",
            VIOLET,
        )
        _launch_selecteur({"SELECTEUR_JSON_PATH": file_path})

    def on_file_click(file_path, is_dir):
        """Gère le clic sur un fichier ou dossier dans la preview"""
        if is_dir:
            navigate_to_folder(file_path)
        elif os.path.splitext(file_path)[1].lower() == ".zip":
            log_to_terminal(f"Extraction: {os.path.splitext(os.path.basename(file_path))[0]}", BLUE)
            extract_zip(file_path)
        elif os.path.splitext(file_path)[1].lower() in _IMAGE_VIEWER_EXTS:
            open_image_viewer(file_path)
        elif os.path.splitext(file_path)[1].lower() == ".json":
            _open_json_in_selecteur(file_path)
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
        _render_preview_page()
        _update_select_toggle_button()
        if added:
            filt = filter_type["value"]
            label = filt if filt != "all" else "tous types"
            log_to_terminal(f"[OK] {added} fichier(s) sélectionné(s) — {label}", BLUE)
        else:
            log_to_terminal("[ATTENTION] Aucun fichier à sélectionner avec ce filtre", ORANGE)



    def _update_select_toggle_button():
        """Met à jour l'apparence du bouton sélectionner/désélectionner."""
        if selected_files:
            select_toggle_button.icon = ft.Icons.DESELECT
            select_toggle_button.icon_color = ORANGE
            select_toggle_button.tooltip = "Désélectionner tout"
        else:
            select_toggle_button.icon = ft.Icons.SELECT_ALL
            select_toggle_button.icon_color = VIOLET
            select_toggle_button.tooltip = "Tout sélectionner"
        try:
            select_toggle_button.update()
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
        _render_preview_page()
        _update_select_toggle_button()
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

        # Snapshot du presse-papiers avant de lancer le thread
        files_to_paste = list(clipboard["files"])
        is_cut = clipboard["cut"]
        count = len(files_to_paste)
        action_label = "déplacement" if is_cut else "copie"
        log_to_terminal(f"[...] {action_label.capitalize()} de {count} élément(s) en cours…", ORANGE)

        def _do_paste():
            copied_count = 0
            errors = []

            for source_path in files_to_paste:
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
                    if is_cut:
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
                action = "déplacé" if is_cut else "collé"
                log_to_terminal(f"[OK] {copied_count} élément(s) {action}(s)", BLUE)
                if is_cut:
                    clipboard["files"] = []
                    clipboard["cut"] = False
                    selection_count_text.value = _selection_label()

            if errors:
                for error in errors:
                    log_to_terminal(f"[ERREUR] {error}", RED)

            refresh_preview()

        threading.Thread(target=_do_paste, daemon=True).start()



    def _show_print_count_numpad(file_path):
        """Affiche un pavé numérique en sur-impression pour définir le nombre d'impressions."""
        basename = os.path.basename(file_path)
        print_prefix_match = re.match(r'^(\d+)X_', basename)
        numpad_value = {"text": print_prefix_match.group(1) if print_prefix_match else ""}

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
            print_copies_count = int(val)
            numpad_dialog.open = False
            page.update()
            folder = os.path.dirname(file_path)



            # Vérifier si le dossier ne contient aucun préfixe NX_ AVANT ce renommage
            # (on exclut le fichier courant lui-même)
            print_prefix_pattern = re.compile(r'^\d+X_')
            others_have_prefix = any(
                print_prefix_pattern.match(f)
                for f in os.listdir(folder)
                if f != basename and os.path.isfile(os.path.join(folder, f))
            )

            clean = re.sub(r'^\d+X_', '', basename)
            new_name = f"{print_copies_count}X_{clean}"
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
                    if print_prefix_pattern.match(fname):
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

        def _make_numpad_button(label, on_click, color=GREY, text_color=WHITE):
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
            ft.Row([_make_numpad_button(7, lambda e: _press(7)), _make_numpad_button(8, lambda e: _press(8)), _make_numpad_button(9, lambda e: _press(9))], spacing=6, tight=True),
            ft.Row([_make_numpad_button(4, lambda e: _press(4)), _make_numpad_button(5, lambda e: _press(5)), _make_numpad_button(6, lambda e: _press(6))], spacing=6, tight=True),
            ft.Row([_make_numpad_button(1, lambda e: _press(1)), _make_numpad_button(2, lambda e: _press(2)), _make_numpad_button(3, lambda e: _press(3))], spacing=6, tight=True),
            ft.Row([_make_numpad_button("⌫", _backspace, GREY, ORANGE), _make_numpad_button(0, lambda e: _press(0)), _make_numpad_button("✓", _confirm, GREEN, DARK)], spacing=6, tight=True),
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



    def _remove_print_count_prefix(file_path):
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
        selected_count = len(selected_files)
        if selected_count == 0:
            return ""
        plural_suffix = "s" if selected_count > 1 else ""
        return f"{selected_count} fichier{plural_suffix} sélectionné{plural_suffix}"



    def on_checkbox_change(e, file_path):
        """Gère le changement d'état d'une checkbox"""
        if e.control.value:
            selected_files.add(file_path)
        else:
            selected_files.discard(file_path)
        selection_count_text.value = _selection_label()
        _update_select_toggle_button()
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
        names_to_select = set(names)

        selected_files.clear()



        # Utilise all_entries_data pour garantir que les chemins dans selected_files
        # sont identiques (même objet str) à ceux utilisés par _render_current_page(),
        # évitant toute divergence de normalisation Unicode NFD/NFC sur macOS.
        entries = all_entries_data["list"]
        if names_to_select and entries:
            for file_name, file_path, is_dir, is_image, ext in entries:
                if file_name in names_to_select:
                    selected_files.add(file_path)
        elif names_to_select:
            # Fallback si entries pas encore peuplées
            for item_name in os.listdir(folder_to_display):
                if item_name in names_to_select:
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
        _render_preview_page()

        if names_to_select and not selected_files:
            log_to_terminal("[ATTENTION] Aucun fichier correspondant trouvé dans la preview", ORANGE)



    # ================================================================ #
    #                    FILTRAGE & PÉRIPHÉRIQUES                      #
    # ================================================================ #
    def _match_filter(entry_tuple):
        """Retourne True si l'entrée correspond au filtre actif."""
        _name, _path, is_dir, is_image, ext = entry_tuple
        active_filter = filter_type["value"]
        if active_filter == "all":
            return True
        if is_dir:
            return True  # Dossiers toujours visibles pour la navigation
        if active_filter == "images":
            return is_image
        if active_filter in _FILTER_CATEGORIES:
            return ext in _FILTER_CATEGORIES[active_filter]
        if active_filter == "other":
            for cat_exts in _FILTER_CATEGORIES.values():
                if ext in cat_exts:
                    return False
            return True
        return True



    def _set_filter(key):
        """Bascule le filtre actif et re-rend la page courante."""
        filter_type["value"] = key
        preview_page["value"] = 0
        _render_preview_page()



    def on_filter_segment_change(e):
        """Callback du CupertinoSlidingSegmentedButton de filtre."""
        idx = e.control.selected_index
        _set_filter(FILTER_KEYS[idx])



    # ── Recherche dans la preview ──────────────────────────────────────
    def _on_search_change(e):
        """Met à jour la requête de recherche et re-rend la preview.
        Si le champ est vidé, referme la barre et restaure l'icône seule."""
        typed_text = (search_field.value or "").strip()
        if not typed_text:
            _clear_search(e)
            return
        search_query["value"] = typed_text
        preview_page["value"] = 0
        _render_preview_page()

    def _open_search(e):
        """Affiche la barre de recherche et masque le bouton icône."""
        search_icon_btn.visible = False
        search_active_row.visible = True
        page.update()
        search_field.focus()
        page.update()

    def _clear_search(e):
        """Efface la recherche, masque la barre et restaure tous les fichiers."""
        search_query["value"] = ""
        search_field.value = ""
        search_active_row.visible = False
        search_icon_btn.visible = True
        _render_preview_page()
        page.update()



    def _get_removable_drives():
        """Détecte les périphériques amovibles (cross-platform, sans dépendance externe)."""
        drives = []
        try:
            if platform.system() == "Darwin":
                macos_system_volumes = {
                    "Macintosh HD", "Macintosh HD - Data",
                    "com.apple.TimeMachine.localsnapshots",
                    "Recovery", "Preboot", "VM", "Update",
                }
                for entry in os.scandir("/Volumes"):
                    if entry.is_dir() and entry.name not in macos_system_volumes and not entry.name.startswith("."):
                        drives.append((entry.name, entry.path))

            elif platform.system() == "Windows":
                import ctypes
                DRIVE_TYPE_REMOVABLE, DRIVE_TYPE_CDROM = 2, 5
                volume_label_buffer = ctypes.create_unicode_buffer(261)
                for letter in "ABCDEFGHIJKLMNOPQRSTUVWXYZ":
                    path = f"{letter}:\\"
                    drive_type = ctypes.windll.kernel32.GetDriveTypeW(path)
                    if drive_type in (DRIVE_TYPE_REMOVABLE, DRIVE_TYPE_CDROM) and os.path.exists(path):
                        ctypes.windll.kernel32.GetVolumeInformationW(
                            path, volume_label_buffer, 261, None, None, None, None, 0)
                        label = volume_label_buffer.value or letter
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



    def _rebuild_favorites_panel():
        """Reconstruit la liste des favoris dans le conteneur."""
        favorites_list = _load_favorites()
        favorites_list_view.controls.clear()
        if not favorites_list:
            favorites_list_view.controls.append(
                ft.Text("Aucun favori — cliquez sur + pour ajouter", size=10,
                        color=LIGHT_GREY, italic=True)
            )
        else:
            for i, fav in enumerate(favorites_list):
                p = fav["path"]
                display_name = fav["label"] or os.path.basename(p) or p
                def _nav(e, path=p):
                    if os.path.isdir(path):
                        navigate_to_folder(path)
                    else:
                        log_to_terminal(f"[ERREUR] Dossier introuvable : {path}", RED)
                def _remove(e, path=p):
                    updated_favorites = _load_favorites()
                    updated_favorites = [f for f in updated_favorites if f["path"] != path]
                    _save_favorites(updated_favorites)
                    _rebuild_favorites_panel()
                    try:
                        favorites_list_view.update()
                    except Exception:
                        pass
                def _rename(e, path=p, current_label=fav["label"]):
                    _show_rename_favorite_dialog(path, current_label)
                favorites_list_view.controls.append(
                    ft.Row([
                        ft.ReorderableDragHandle(
                            content=ft.Icon(ft.Icons.DRAG_INDICATOR, size=16, color=LIGHT_GREY),
                            mouse_cursor=ft.MouseCursor.GRAB,
                        ),
                        ft.Icon(ft.Icons.FOLDER, size=16, color=BLUE),
                        ft.Container(
                            content=ft.Text(display_name, size=16, color=WHITE,
                                            overflow=ft.TextOverflow.ELLIPSIS, max_lines=1),
                            expand=True,
                            on_click=_nav,
                            tooltip=p,
                            ink=True,
                        ),
                        ft.Container(
                            content=ft.Icon(ft.Icons.EDIT_OUTLINED, size=15, color=LIGHT_GREY),
                            on_click=_rename,
                            tooltip="Renommer le raccourci",
                            ink=True,
                            border_radius=8,
                            padding=ft.Padding(3, 2, 3, 2),
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
            favorites_list_view.update()
        except Exception:
            pass



    def _show_rename_favorite_dialog(path: str, current_label: str):
        """Ouvre un dialog pour renommer le raccourci d'un favori."""
        label_field = ft.TextField(
            value=current_label or os.path.basename(path),
            hint_text=os.path.basename(path),
            border_color=BLUE, text_size=13, height=40,
            content_padding=ft.Padding(8, 4, 8, 4),
            autofocus=True,
        )
        dlg = ft.AlertDialog(
            title=ft.Text("Renommer le raccourci", size=13, color=WHITE),
            content=ft.Column([
                ft.Text(path, size=10, color=LIGHT_GREY,
                        overflow=ft.TextOverflow.ELLIPSIS, max_lines=1),
                label_field,
            ], spacing=6, tight=True, width=280),
            actions_alignment=ft.MainAxisAlignment.END,
        )

        def _confirm(e):
            new_label = (label_field.value or "").strip()
            favorites = _load_favorites()
            for fav in favorites:
                if fav["path"] == path:
                    fav["label"] = new_label
                    break
            _save_favorites(favorites)
            dlg.open = False
            page.update()
            _rebuild_favorites_panel()

        def _cancel(e):
            dlg.open = False
            page.update()

        dlg.actions = [
            ft.TextButton("OK", on_click=_confirm),
            ft.TextButton("Annuler", on_click=_cancel),
        ]
        page.overlay.append(dlg)
        dlg.open = True
        page.update()



    def _add_favorite_current():
        """Ajoute le dossier courant aux favoris (avec choix du nom du raccourci)."""
        path = current_browse_folder.get("path") or selected_folder.get("path")
        if not path or not os.path.isdir(path):
            log_to_terminal("[ATTENTION] Aucun dossier sélectionné à ajouter en favori", ORANGE)
            return
        path = os.path.normpath(path)
        favorites_list = _load_favorites()
        if any(f["path"] == path for f in favorites_list):
            log_to_terminal("[INFO] Ce dossier est déjà dans les favoris", LIGHT_GREY)
            return

        default_name = os.path.basename(path)
        label_field = ft.TextField(
            value=default_name,
            hint_text=default_name,
            border_color=BLUE, text_size=13, height=40,
            content_padding=ft.Padding(8, 4, 8, 4),
            autofocus=True,
        )
        dlg = ft.AlertDialog(
            title=ft.Text("Ajouter aux favoris", size=13, color=WHITE),
            content=ft.Column([
                ft.Text("Nom du raccourci :", size=11, color=LIGHT_GREY),
                label_field,
            ], spacing=6, tight=True, width=280),
            actions_alignment=ft.MainAxisAlignment.END,
        )

        def _confirm(e):
            label = (label_field.value or "").strip()
            dlg.open = False
            page.update()
            favorites_list = _load_favorites()
            if not any(f["path"] == path for f in favorites_list):
                favorites_list.append({"path": path, "label": label})
                _save_favorites(favorites_list)
                _rebuild_favorites_panel()
                log_to_terminal(f"[OK] Favori ajouté : {label or default_name}", YELLOW)

        def _cancel(e):
            dlg.open = False
            page.update()

        dlg.actions = [
            ft.TextButton("Ajouter", on_click=_confirm),
            ft.TextButton("Annuler", on_click=_cancel),
        ]
        page.overlay.append(dlg)
        dlg.open = True
        page.update()



    def _eject_drive(path):
        """Démonte/éjecte un périphérique amovible selon le système d'exploitation."""
        try:
            sys_name = platform.system()
            if sys_name == "Windows":
                drive_letter = os.path.splitdrive(path)[0]  # ex: "E:"
                powershell_eject_command = (
                    f"(New-Object -comObject Shell.Application)"
                    f".Namespace(17).ParseName('{drive_letter}').InvokeVerb('Eject')"
                )
                subprocess.Popen(["powershell", "-Command", powershell_eject_command],
                                 creationflags=subprocess.CREATE_NO_WINDOW)
            elif sys_name == "Darwin":
                subprocess.Popen(["diskutil", "eject", path])
            else:  # Linux
                subprocess.Popen(["umount", path])
            log_to_terminal(f"[OK] Éjection demandée : {path}", VIOLET)
        except Exception as ex:
            log_to_terminal(f"[ERREUR] Éjection impossible : {ex}", RED)



    def _rebuild_drives_panel(drives):
        """Met à jour la section périphériques (appelée depuis le callback pubsub)."""
        drives_list_view.controls.clear()
        for name, path in drives:
            def _nav(e, p=path):
                if os.path.isdir(p):
                    navigate_to_folder(p)
                else:
                    log_to_terminal(f"[ERREUR] Périphérique introuvable : {p}", RED)
            def _eject(e, p=path):
                _eject_drive(p)
            drives_list_view.controls.append(
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
        drives_panel.visible = bool(drives)
        try:
            drives_panel.update()
        except Exception:
            pass



    def _on_drives_changed(topic, drives):
        """Callback pubsub : met à jour l'UI périphériques depuis le thread de fond."""
        _rebuild_drives_panel(drives)

    page.pubsub.subscribe_topic("drives_changed", _on_drives_changed)



    def _poll_removable_drives():
        """Thread de fond : détecte les changements de périphériques toutes les 3 s."""
        prev_drives = []
        while True:
            time.sleep(3)
            try:
                drives = _get_removable_drives()
                if drives != prev_drives:
                    prev_drives = drives
                    removable_drives_state["list"] = drives
                    page.pubsub.send_all_on_topic("drives_changed", drives)
            except Exception:
                pass



    # ================================================================ #
    #                           PREVIEW                                #
    # ================================================================ #
    def _render_preview_page():
        """
        Construit et affiche les contrôles ListView pour la page courante.
        Appelée depuis on_preview_ready et go_to_page (thread UI uniquement).
        Toutes les miniatures de la page sont chargées immédiatement (pas de lazy loading).
        """
        try:
            entries = all_entries_data["list"]
            # Appliquer le filtre actif
            if filter_type["value"] != "all":
                entries = [entry for entry in entries if _match_filter(entry)]
            # Appliquer la recherche textuelle
            if search_query["value"]:
                query_lower = search_query["value"].lower()
                entries = [entry for entry in entries if query_lower in entry[0].lower()]
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

                    delete_button = ft.IconButton(
                        icon=ft.Icons.DELETE_OUTLINE, icon_size=18,
                        icon_color=ft.Colors.RED_300, tooltip="Supprimer",
                        on_click=lambda e, path=file_path: delete_item(path),
                        style=ft.ButtonStyle(padding=ft.Padding.all(4)),
                    )
                    rename_button = ft.IconButton(
                        icon=ft.Icons.EDIT_OUTLINED, icon_size=17,
                        icon_color=LIGHT_GREY, tooltip="Renommer",
                        on_click=lambda e, path=file_path: _rename_item(path),
                        style=ft.ButtonStyle(padding=ft.Padding.all(4)),
                    )
                    if is_dir:
                        trailing = ft.Row(
                            [rename_button, delete_button],
                            spacing=0, tight=True,
                            vertical_alignment=ft.CrossAxisAlignment.CENTER,
                        )
                    else:
                        print_prefix_match = re.match(r'^(\d+)X_', file)
                        print_count = int(print_prefix_match.group(1)) if print_prefix_match else None
                        if print_count is not None:
                            print_count_badge = ft.Container(
                                content=ft.Text(f"{print_count}×", size=12,
                                                color=YELLOW, weight=ft.FontWeight.BOLD),
                                bgcolor=GREY, border_radius=4,
                                padding=ft.Padding(6, 3, 6, 3),
                                tooltip="Modifier le nombre d'impressions",
                                on_click=lambda e, p=file_path: _show_print_count_numpad(p),
                                ink=True,
                            )
                            remove_prefix_button = ft.IconButton(
                                icon=ft.Icons.CLOSE, icon_size=15,
                                icon_color=LIGHT_GREY, tooltip="Retirer le compteur",
                                on_click=lambda e, p=file_path: _remove_print_count_prefix(p),
                                style=ft.ButtonStyle(padding=ft.Padding.all(4)),
                            )
                            trailing = ft.Row(
                                [print_count_badge, remove_prefix_button, rename_button, delete_button],
                                spacing=0, tight=True,
                                vertical_alignment=ft.CrossAxisAlignment.CENTER,
                            )
                        else:
                            set_print_count_button = ft.IconButton(
                                icon=ft.Icons.PRINT_OUTLINED, icon_size=17,
                                icon_color=LIGHT_GREY,
                                tooltip="Définir le nombre d'impressions",
                                on_click=lambda e, p=file_path: _show_print_count_numpad(p),
                                style=ft.ButtonStyle(padding=ft.Padding.all(4)),
                            )
                            trailing = ft.Row(
                                [set_print_count_button, rename_button, delete_button],
                                spacing=0, tight=True,
                                vertical_alignment=ft.CrossAxisAlignment.CENTER,
                            )

                    def _create_right_click_handler(fp, d):
                        def _on_right_click(e):
                            if d:
                                return  # pas de menu pour les dossiers
                            if fp in selected_files and len(selected_files) > 1:
                                files_to_open = list(selected_files)
                            else:
                                files_to_open = [fp]
                            _show_open_with_menu(files_to_open)
                        return _on_right_click

                    new_controls.append(
                        ft.GestureDetector(
                            on_secondary_tap_up=_create_right_click_handler(file_path, is_dir),
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

            _update_select_toggle_button()
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
        preview_refresh_token["value"] += 1
        current_refresh_token = preview_refresh_token["value"]
        preview_list.on_scroll = None
        preview_list.controls.clear()
        lazy_images.clear()
        file_count_text.value = ""
        folder_to_display = current_browse_folder["path"] or selected_folder["path"]
        preview_loading.visible = bool(folder_to_display)
        page.update()

        def _background_folder_scan():
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
            page.pubsub.send_all_on_topic("preview_ready", (current_refresh_token, entries_data, new_file_count_text, error_text))

        threading.Thread(target=_background_folder_scan, daemon=True).start()
    


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
        _render_preview_page()



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

        if app_name == "2 en 1.py" and series_name is None:
            _TWO_IN_ONE_FORMATS = [
                ("2 sur 10×15  (76 × 102 mm)",  "76x102"),
                ("2 sur 13×18  (89 × 127 mm)",  "89x127"),
                ("2 sur 15×20  (102 × 152 mm)", "102x152"),
                ("2 sur 20×30  (152 × 203 mm)", "152x203"),
            ]
            two_in_one_dropdown = ft.Dropdown(
                label="Format",
                value=_TWO_IN_ONE_FORMATS[0][1],
                autofocus=True,
                width=280,
                bgcolor=DARK,
                border_color=GREY,
                options=[
                    ft.dropdown.Option(key=val, text=label)
                    for label, val in _TWO_IN_ONE_FORMATS
                ],
            )

            def on_confirm_two_in_one(e):
                val = two_in_one_dropdown.value or _TWO_IN_ONE_FORMATS[0][1]
                two_in_one_dialog.open = False
                page.update()
                launch_app(app_name, app_path, is_local, series_name=val)

            def on_cancel_two_in_one(e):
                two_in_one_dialog.open = False
                page.update()

            two_in_one_dropdown.on_change = on_confirm_two_in_one

            two_in_one_dialog = ft.AlertDialog(
                modal=True,
                title=ft.Text("Format 2 en 1"),
                content=two_in_one_dropdown,
                actions=[
                    ft.TextButton("Annuler", on_click=on_cancel_two_in_one),
                    ft.TextButton("OK", on_click=on_confirm_two_in_one),
                ],
                actions_alignment=ft.MainAxisAlignment.END,
            )
            page.overlay.append(two_in_one_dialog)
            two_in_one_dialog.open = True
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
                env["DATA_PATH"] = os.path.join(app_directory, "Data")
                
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

                # Minimise Dashboard pour laisser la place à l'app lancée
                if app_path.endswith(".pyw"):
                    page.window.minimized = True
                    page.update()

                    def _watch_local(proc=process):
                        proc.wait()
                        page.pubsub.send_all_on_topic("restore_window", None)

                    threading.Thread(target=_watch_local, daemon=True).start()



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
                env["DATA_PATH"] = os.path.join(app_directory, "Data")
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



                # Ajouter les dimensions pour 2 en 1.py
                if app_name == "2 en 1.py" and series_name:
                    parts = series_name.split("x")
                    if len(parts) == 2:
                        env["TWO_IN_ONE_WIDTH"] = parts[0]
                        env["TWO_IN_ONE_HEIGHT"] = parts[1]



                # Ajouter les fichiers sélectionnés (si aucun n'est sélectionné, la variable sera vide)
                if selected_files:
                    env["SELECTED_FILES"] = "|".join(os.path.basename(f) for f in selected_files)
                
                process = subprocess.Popen(
                    [sys.executable, "-u", app_path],
                    cwd=os.path.join(app_directory, "Data"),
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
                                    pending_file_selection["names"] = selected_names
                                else:
                                    log_to_terminal(line_stripped, color)
                    except Exception as read_err:
                        log_to_terminal(f"[ERREUR] Lecture sortie script: {read_err}", RED)
                    finally:
                        pipe.close()
                
                stdout_reader_thread = threading.Thread(target=read_output, args=(process.stdout, WHITE), daemon=True)
                stderr_reader_thread = threading.Thread(target=read_output, args=(process.stderr, RED), daemon=True)
                stdout_reader_thread.start()
                stderr_reader_thread.start()



                # Attendre la fin et rafraîchir la preview
                def done():
                    """
                    Attend la fin du sous-processus ET la lecture complète des pipes,
                    puis journalise le résultat et demande un rafraîchissement de la preview.
                    On attend les threads de lecture pour s'assurer que SELECTED_FILES:
                    a bien été traité avant de déclencher le refresh.
                    """
                    stdout_reader_thread.join()
                    stderr_reader_thread.join()
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
        app_path = os.path.join(app_directory, "Data", "Redimensionner.py")
        if os.path.exists(app_path):
            launch_app("Redimensionner.py", app_path, False)



    def on_resize_watermark_input_change(e):
        """Met à jour la taille de redimensionnement+filigrane cible en pixels."""
        resize_watermark_size["value"] = e.control.value



    def launch_resize_watermark(e):
        """Lance Redimensionner filigrane.py avec la taille saisie dans resize_watermark_input."""
        app_path = os.path.join(app_directory, "Data", "Redimensionner filigrane.py")
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
            app_path = os.path.join(app_directory, "Data", app_name)
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



    def _build_quick_tools():
        """Construit la colonne d'icônes rondes (outils rapides)."""
        two_in_one_path = os.path.join(app_directory, "Data", "2 en 1.py")
        selecteur_path = os.path.join(app_directory, "Selecteur.pyw")
        fichiers_manquants_path = os.path.join(app_directory, "Data", "Fichiers manquants.py")

        def _round_button(icon, color, tooltip, on_click):
            return ft.Container(
                content=ft.Icon(icon, color=color, size=22),
                bgcolor=GREY,
                border=ft.Border.all(1, color),
                border_radius=50,
                width=44,
                height=44,
                alignment=ft.Alignment(0, 0),
                tooltip=tooltip,
                on_click=on_click,
                ink=True,
            )

        noir_et_blanc_path        = os.path.join(app_directory, "Data", "N&B.py")
        ameliorer_nettete_path    = os.path.join(app_directory, "Data", "Ameliorer nettete.py")
        nettoyer_metadonnees_path = os.path.join(app_directory, "Data", "Nettoyer metadonnees.py")
        images_en_pdf_path        = os.path.join(app_directory, "Data", "Images en PDF.py")
        remerciements_path        = os.path.join(app_directory, "Data", "Remerciements.py")

        quick_tools_col.controls = [
            _round_button(
                ft.Icons.VERTICAL_SPLIT,
                YELLOW,
                "Ouvrir le Sélecteur (demi-écran)",
                lambda e: _launch_selecteur(),
            ),
            _round_button(
                ft.Icons.FIND_IN_PAGE,
                ORANGE,
                "Fichiers manquants",
                lambda e: launch_app("Fichiers manquants.py", fichiers_manquants_path, False),
            ),
            _round_button(
                ft.Icons.MONOCHROME_PHOTOS,
                WHITE,
                "N&B",
                lambda e: launch_app("N&B.py", noir_et_blanc_path, False),
            ),
            _round_button(
                ft.Icons.AUTO_GRAPH,
                WHITE,
                "Améliorer netteté",
                lambda e: launch_app("Ameliorer nettete.py", ameliorer_nettete_path, False),
            ),
            _round_button(
                ft.Icons.CLEANING_SERVICES,
                RED,
                "Nettoyer métadonnées",
                lambda e: launch_app("Nettoyer metadonnees.py", nettoyer_metadonnees_path, False),
            ),
            _round_button(
                ft.Icons.PICTURE_AS_PDF,
                BLUE,
                "Images en PDF",
                lambda e: launch_app("Images en PDF.py", images_en_pdf_path, False),
            ),
            _round_button(
                ft.CupertinoIcons.BIN_XMARK_FILL,
                VIOLET,
                "Remerciements",
                lambda e: launch_app("Remerciements.py", remerciements_path, False),
            ),
            _round_button(
                ft.Icons.AUTO_FIX_HIGH,
                GREEN,
                "Augmentation IA",
                lambda e: launch_app("Augmentation IA.py", os.path.join(app_directory, "Data", "Augmentation IA.py"), False),
            ),
        ]



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
            _rebuild_recent_folders_menu()
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
        def _run_update():
            def publish_to_terminal(msg, color=LIGHT_GREY):
                page.pubsub.send_all_on_topic("terminal", (msg, color))



            def run_git_command(*args):
                return subprocess.run(
                    ["git", *args],
                    cwd=app_directory,
                    capture_output=True,
                    text=True,
                    encoding="utf-8",
                    errors="replace",
                )



            # ── Sauvegarde mémoire des fichiers utilisateur avant git ─
            user_data_filenames = [".recent_folders.json", ".favorites.json", ".pip_cache.json"]
            user_data_backups = {}
            for fname in user_data_filenames:
                fpath = os.path.join(app_directory, fname)
                if os.path.isfile(fpath):
                    try:
                        with open(fpath, "r", encoding="utf-8") as f:
                            user_data_backups[fname] = f.read()
                    except Exception:
                        pass



            def _restore_user_data_files():
                for fname, content in user_data_backups.items():
                    fpath = os.path.join(app_directory, fname)
                    try:
                        with open(fpath, "w", encoding="utf-8") as f:
                            f.write(content)
                    except Exception:
                        pass

            try:
                # Stash les changements locaux s'il y en a
                stash_result = run_git_command("stash")
                had_local_changes = "No local changes" not in stash_result.stdout

                # Pull --rebase
                git_pull_result = run_git_command("pull", "--rebase", "origin")
                git_command_output = (git_pull_result.stdout + git_pull_result.stderr).strip()

                if git_pull_result.returncode != 0:
                    if had_local_changes:
                        run_git_command("rebase", "--abort")
                        run_git_command("stash", "pop")
                    _restore_user_data_files()
                    publish_to_terminal(f"[ERREUR] Erreur lors de la mise à jour.\n{git_command_output}", RED)
                    return



                # Supprimer le stash (changements de code locaux non désirés)
                if had_local_changes:
                    run_git_command("stash", "drop")



                # Restaurer systématiquement les fichiers utilisateur
                _restore_user_data_files()

                if "Already up to date" in git_command_output or "Déjà à jour" in git_command_output or git_command_output == "":
                    publish_to_terminal("[OK] Déjà à jour.", GREEN)
                else:
                    publish_to_terminal(f"[OK] Code mis à jour.\n{git_command_output}", GREEN)



                # ── Dépendances : pip uniquement si requirements.txt a changé ──
                requirements_file_path = os.path.join(app_directory, "requirements.txt")
                pip_cache_file_path = os.path.join(app_directory, ".pip_cache.json")
                if not os.path.isfile(requirements_file_path):
                    publish_to_terminal("⚠ requirements.txt introuvable, installation ignorée.", YELLOW)
                else:
                    with open(requirements_file_path, "rb") as f:
                        requirements_checksum = hashlib.sha256(f.read()).hexdigest()

                    cached_checksum = None
                    try:
                        with open(pip_cache_file_path, "r", encoding="utf-8") as f:
                            cached_checksum = json.load(f).get("req_hash")
                    except Exception:
                        pass

                    if cached_checksum == requirements_checksum:
                        publish_to_terminal("[OK] Dépendances inchangées, installation ignorée.", GREEN)
                    else:
                        publish_to_terminal("📦 Nouvelles dépendances détectées, installation en cours…", YELLOW)
                        pip_install_process = subprocess.Popen(
                            [sys.executable, "-m", "pip", "install", "-r", requirements_file_path, "--upgrade"],
                            stdout=subprocess.PIPE,
                            stderr=subprocess.STDOUT,
                            text=True,
                            encoding="utf-8",
                            errors="replace",
                            cwd=app_directory,
                        )
                        for line in pip_install_process.stdout:
                            line = line.rstrip()
                            if line:
                                publish_to_terminal(line)
                        pip_install_process.wait()
                        if pip_install_process.returncode == 0:
                            publish_to_terminal("[OK] Dépendances installées.", GREEN)
                            try:
                                with open(pip_cache_file_path, "w", encoding="utf-8") as f:
                                    json.dump(
                                        {"req_hash": requirements_checksum,
                                         "updated_at": time.strftime("%Y-%m-%d %H:%M")},
                                        f, ensure_ascii=False, indent=2,
                                    )
                            except Exception:
                                pass
                        else:
                            publish_to_terminal(f"pip a terminé avec le code {pip_install_process.returncode}.", YELLOW)



                # ── Redémarrage automatique ───────────────────────────────
                publish_to_terminal("🔄 Redémarrage du Dashboard…", BLUE)
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
                _restore_user_data_files()
                page.pubsub.send_all_on_topic("terminal", (f"[ERREUR] {exc}", RED))

        threading.Thread(target=_run_update, daemon=True).start()



# ===================== CONNEXIONS UI ===================== #
    # ── Champ dossier ────────────────────────────────────────────────
    folder_path.on_submit = on_folder_path_submit
    folder_path.on_blur = on_folder_path_blur



    # ── Preview ───────────────────────────────────────────────────────
    sort_segment.on_change = on_sort_change
    filter_segment.on_change = on_filter_segment_change
    select_toggle_button.on_click = toggle_select_all
    invert_selection_button.on_click = invert_selection
    prev_page_btn.on_click = lambda e: go_to_page(-1)
    next_page_btn.on_click = lambda e: go_to_page(+1)



    # ── Recherche preview ─────────────────────────────────────────────
    search_icon_btn.on_click = _open_search
    search_field.on_change = _on_search_change
    search_field.on_submit = _on_search_change
    search_close_btn.on_click = _clear_search



    # ── Redimensionnement ─────────────────────────────────────────────
    resize_input.on_change = on_resize_input_change
    resize_watermark_input.on_change = on_resize_watermark_input_change



    # ── Initialisation ────────────────────────────────────────────────
    _rebuild_recent_folders_menu()
    refresh_apps()
    _build_quick_tools()
    _rebuild_favorites_panel()
    _initial_drives = _get_removable_drives()
    if _initial_drives:
        removable_drives_state["list"] = _initial_drives
        _rebuild_drives_panel(_initial_drives)
    threading.Thread(target=_poll_removable_drives, daemon=True).start()



# ===================== INTERFACE FLET ===================== #
    page.add(
        ft.WindowDragArea(
            ft.Row([
                ft.Container(
                    ft.Text(f"DASHBOARD {__version__}", size=24, color=WHITE),
                    bgcolor=BACKGROUND,
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
                        ft.Container(width=32),  # Espacement entre le titre et les boutons
                        ft.IconButton(
                            icon=ft.Icons.KEYBOARD_DOUBLE_ARROW_LEFT_SHARP,
                            tooltip="Kiosk gauche",
                            on_click=lambda e: launch_app("Kiosk gauche.py", os.path.join(app_directory, "Data", "Kiosk gauche.py"), True),
                            icon_color=VIOLET,
                            bgcolor=DARK,
                            icon_size=18,
                        ),
                        ft.IconButton(
                            icon=ft.Icons.KEYBOARD_DOUBLE_ARROW_RIGHT_SHARP,
                            tooltip="Kiosk droite",
                            on_click=lambda e: launch_app("Kiosk droite.py", os.path.join(app_directory, "Data", "Kiosk droite.py"), True),
                            icon_color=VIOLET,
                            bgcolor=DARK,
                            icon_size=18,
                        ),
                        ft.IconButton(
                            icon=ft.Icons.AUTO_DELETE,
                            tooltip="Nettoyer anciens fichiers (> 60 jours)",
                            on_click=lambda e: launch_app("Nettoyer anciens fichiers.py", os.path.join(app_directory, "Data", "Nettoyer anciens fichiers.py"), True),
                            icon_color=ORANGE,
                            bgcolor=GREY,
                            icon_size=18,
                        ),
                    ]),
                    ft.Row([
                        ft.Container(
                            content=apps_list,
                            expand=True,
                            border=ft.Border.all(1, GREY),
                            border_radius=8,
                            bgcolor=DARK,
                            padding=8,
                        ),
                        ft.Container(
                            content=quick_tools_col,
                            bgcolor=DARK,
                            border=ft.Border.all(1, GREY),
                            border_radius=8,
                            padding=ft.Padding.symmetric(vertical=8, horizontal=4),
                            width=56,
                        ),
                    ], expand=True, spacing=8),
                ], expand=6),
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
                        select_toggle_button,
                        invert_selection_button,
                        ft.IconButton(
                            icon=ft.Icons.DELETE_SWEEP,
                            tooltip="Supprimer les fichiers sélectionnés",
                            on_click=delete_selected_files,
                            icon_color=RED,
                            icon_size=20,
                        ),
                        search_icon_btn,
                        search_active_row,
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
                ], expand=9)
            ], expand=True, spacing=8),
            ft.Container(
                content=ft.Row([

                    # ── Terminal (gauche) ────────────────────────────
                    ft.Container(
                        content=terminal_output,
                        expand=True,
                        border=ft.Border.all(1, GREEN),
                        border_radius=8,
                        bgcolor=DARK,
                        padding=5,
                    ),

                    # ── Boutons ronds (milieu) ────────────────────────
                    ft.Column([
                        ft.IconButton(
                            icon=ft.Icons.COPY_ALL,
                            tooltip="Copier le terminal",
                            on_click=lambda e: copy_terminal_to_clipboard(),
                            icon_color=BLUE,
                            icon_size=18,
                            bgcolor=GREY,
                            style=ft.ButtonStyle(shape=ft.CircleBorder(), side=ft.BorderSide(1, BLUE)),
                        ),
                        ft.IconButton(
                            icon=ft.Icons.CLEAR_ALL,
                            tooltip="Effacer le terminal",
                            on_click=clear_terminal,
                            icon_color=RED,
                            icon_size=18,
                            bgcolor=GREY,
                            style=ft.ButtonStyle(shape=ft.CircleBorder(), side=ft.BorderSide(1, RED)),
                        ),
                    ], alignment=ft.MainAxisAlignment.CENTER, spacing=4),

                    # ── Favoris & Périphériques (droite) ─────────────
                    ft.Row([
                        favorites_panel,
                        drives_panel,
                    ], expand=True, spacing=8, vertical_alignment=ft.CrossAxisAlignment.STRETCH),
                ], spacing=8, expand=True),
                height=190,
            ),
        ], expand=True, spacing=8)
    )



#############################################################
#                         DÉMARRAGE                         #
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
