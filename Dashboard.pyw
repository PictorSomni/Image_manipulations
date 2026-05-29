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
  Ctrl/Cmd+A  — sélectionner tout / désélectionner tout.
  Ctrl/Cmd+C  — copier les fichiers sélectionnés dans le presse-papiers interne.
  Ctrl/Cmd+↓ — basculer entre Terminal/Favoris et IA+Notes.
  Ctrl/Cmd+I  — inverser la sélection.
  Ctrl/Cmd+N  — créer un nouveau dossier.
  Ctrl/Cmd+V  — coller dans le dossier actuel.
  Ctrl/Cmd+↑ — agrandir/réduire le terminal.
  Ctrl/Cmd+← — Bloc-notes en plein écran (quand IA+Notes ouvert).
  Ctrl/Cmd+→ — IA en plein écran (quand IA+Notes ouvert).

Dépendances :
  flet >= 0.80, modules standard (os, subprocess, sys, platform, shutil,
  threading, re, zipfile, time).
"""

__version__ = "2.6.9"

# ==============================================================================
# TABLE DES MATIÈRES — Dashboard.pyw
# ==============================================================================
# 1. IMPORTS & CONFIGURATION ....................................... ~L 55
# 2. CONSTANTES .................................................... ~L 110
# 3. INTERFACE PRINCIPALE main() .................................. ~L 128
#    3.1  COULEURS ................................................. ~L 155
#    3.2  PROPRIÉTÉS & ÉTAT ....................................... ~L 171
#    3.3  ÉLÉMENTS UI ............................................. ~L 358
#    3.4  MÉTHODES ................................................ ~L 727
#    3.5  CONNEXIONS UI ........................................... ~L 7399
#    3.6  STRIP MODE (bandeau tactile) ............................. ~L 7806
#    3.7  INTERFACE FLET .......................................... ~L 7848
# ==============================================================================



#############################################################
#                          IMPORTS                          #
#############################################################
import flet as ft
import os
import subprocess
import sys
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "Data"))
import CONSTANTS
import platform
import shutil
import threading
import re
import zipfile
import json
import asyncio
import datetime
import concurrent.futures
import time
import hashlib
import urllib.request
import base64

try:
    from PIL import Image as _PILImage
except ImportError:
    _PILImage = None


from ai_tools import (
    _fetch_url_content, _web_search, _ollama_chat_once, _ollama_chat_stream,
    _ollama_chat_stream_with_tools, _gemini_chat_stream_with_tools,
    _parse_text_tool_calls, _strip_text_tool_calls,
    _format_ai_conversation, _folder_tool_definitions, _gemini_tool_definitions, _folder_list_contents,
    _folder_read_file, _folder_create_file, _encode_image_for_analysis, _analyze_images_batched,
    _gemini_generate_image,
    _WEB_TOOLS, _TERMINAL_TOOLS, _MEMORY_TOOLS, _run_terminal_command,
    _update_memory_file, _build_system_content,
    _voice_record_audio, _voice_transcribe, _gemini_tts, _gemini_tts_stream, _voice_play_audio,
)
import thumb_cache
#############################################################
#                         CONSTANTS                         #
#############################################################
_IMAGE_VIEWER_EXTS = CONSTANTS.IMAGE_EXTS
_NOTEPAD_EXTS      = CONSTANTS.NOTEPAD_EXTS
_ANSI_ESCAPE       = re.compile(r'\x1b\[[0-9;]*[a-zA-Z]|\x1b\[\?[0-9;]*[a-zA-Z]')

_OS_JUNK = {
    ".ds_store", "thumbs.db", "thumbs.db:encryptable",
    "ehthumbs.db", "ehthumbs_vista.db", "desktop.ini",
    ".directory", ".spotlight-v100", ".trashes",
    ".thumbcache.db",
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
#                        -={MAIN}=-                         #
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
    DARK        = CONSTANTS.COLOR_DARK
    BACKGROUND  = CONSTANTS.COLOR_BACKGROUND
    GREY        = CONSTANTS.COLOR_GREY
    LIGHT_GREY  = CONSTANTS.COLOR_LIGHT_GREY
    BLUE        = CONSTANTS.COLOR_BLUE
    VIOLET      = CONSTANTS.COLOR_VIOLET
    GREEN       = CONSTANTS.COLOR_GREEN
    YELLOW      = CONSTANTS.COLOR_YELLOW
    HOVER_YELLOW = CONSTANTS.COLOR_HOVER_YELLOW
    ORANGE      = CONSTANTS.COLOR_ORANGE
    RED         = CONSTANTS.COLOR_RED
    WHITE       = CONSTANTS.COLOR_WHITE



# ===================== PROPRIÉTÉS ===================== #
    page.title = "Dashboard - Image Manipulations"
    page.theme_mode = ft.ThemeMode.DARK
    page.bgcolor = BACKGROUND
    page.window.title_bar_hidden = True
    page.window.title_bar_buttons_hidden = True
    page.window.width = CONSTANTS.WINDOW_WIDTH
    page.window.height = CONSTANTS.WINDOW_HEIGHT
    page.window.maximized = CONSTANTS.MAXIMIZED
    page.window.icon = "assets/icon.png"

    async def on_window_event(event):
        if event.data == "close":
            proc = ollama_process["proc"]
            if proc is not None and proc.poll() is None:
                try:
                    proc.terminate()
                except Exception:
                    pass
        elif event.data in ("resize", "maximize", "unmaximize"):
            if overlay_fullscreen["mode"] in ("ai", "notepad"):
                win_w = page.window.width or CONSTANTS.WINDOW_WIDTH
                bottom_panel_container.width = int((win_w - 8) * 6 / 15 + 4)
                try:
                    bottom_panel_container.update()
                except Exception:
                    pass

    page.window.on_event = on_window_event
    selected_folder = {"path": None}
    current_browse_folder = {"path": None}
    kiosk_tariff = {"value": "PRINTS"}  # Tarif kiosk actif : "STUDIOS" ou "PRINTS"
    app_directory = os.path.dirname(os.path.abspath(__file__))
    selected_files = []  # Liste des fichiers sélectionnés (ordre de clic préservé)

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


    def _resolve_favorite_path(p: str) -> str:
        """Sur macOS, résout /Volumes/NOM vers /Volumes/NOM-1 si nécessaire.
        Cas 1 : NOM n'existe pas → cherche NOM-1, -2…
        Cas 2 : NOM existe mais NOM-1 aussi → NOM est un stub, préférer NOM-1."""
        if sys.platform != "darwin":
            return p
        if not p.startswith("/Volumes/"):
            return p
        rest = p[len("/Volumes/"):]
        vol_name = rest.split("/")[0]
        sub_path = rest[len(vol_name):]
        # Cherche le variant -N avec le numéro le plus élevé qui existe
        for suffix in ["-1", "-2", "-3", "-4"]:
            candidate_vol = f"/Volumes/{vol_name}{suffix}"
            candidate = f"{candidate_vol}{sub_path}"
            if os.path.isdir(candidate_vol):
                return candidate
        # Aucun variant -N : retourne le chemin original (existant ou non)
        return p



    # Configuration: nom du fichier -> True si l'app est locale (pas besoin de dossier sélectionné)
    apps = {
        "Transfert vers TEMP.py": (True, BLUE),
        "Conversion JPG.py": (False, BLUE),
        "Renommer sequence.py": (False, BLUE),
        "Format 13x15.py": (False, HOVER_YELLOW),
        "Fit 203.py": (False, HOVER_YELLOW),
        "Recadrage.pyw": (False, BLUE),
        "Redimensionner filigrane.py": (False, WHITE),
        "2 en 1.py": (False, HOVER_YELLOW),
        "Redimensionner.py": (False, WHITE),
        "Augmentation IA.py": (False, VIOLET),
        "Copyright.py": (False, VIOLET),
        "Comparaison.pyw": (False, VIOLET, os.path.join(os.path.dirname(os.path.abspath(__file__)), "Data", "Comparaison.pyw")),
    }


    # ===================== Valeurs par défaut ===================== #

    resize_size = {"value": str(CONSTANTS.RESIZE_DEFAULT)}  # Taille par défaut pour le redimensionnement
    resize_watermark_size = {"value": str(CONSTANTS.RESIZE_DEFAULT)}  # Taille par défaut pour le redimensionnement avec watermark
    sort_mode = {"value": 2}  # 0 = A→Z, 1 = Z→A, 2 = par date de modification
    show_only_selection = {"value": False}  # True = afficher uniquement les fichiers sélectionnés
    removable_drives_state = {"list": []}  # [(name, path), ...]
    _image_cache_busters = {}  # {normpath: temp_path_unique} pour invalider le cache navigateur
    _image_last_mtime = {}     # {normpath: mtime} pour détecter les modifications externes
    _checkbox_refs = {}        # {file_path: ft.Checkbox} — refs aux checkboxes rendues (mise à jour in-place)
    _thumb_cache = {}          # {normpath: b64_string} — miniatures PIL générées (chargement asynchrone)
    _pending_thumb_refs = {}   # {normpath: (ft.Container, file_path, icon, icon_color)} — widgets en attente
    PAGE_SIZE = 100             # Nb d'éléments max par page dans la prévisualisation
    preview_page = {"value": 0}  # Page courante (0-indexé)
    all_entries_data = {"list": [], "error": ""}  # Données brutes du dernier scan
    pending_file_selection = {"names": None}  # Noms à sélectionner après le prochain scan
    preview_refresh_token = {"value": 0}   # incrémenté à chaque refresh pour annuler les anciens threads
    search_query = {"value": ""}  # Requête de recherche active dans la preview
    command_history = []           # Historique des commandes du terminal
    history_index = {"value": -1}  # -1 = nouvelle saisie en cours
    history_draft = {"value": ""}  # Saisie en cours avant navigation dans l'historique
    terminal_input_focused = {"value": False}
    _solo_left_state   = {"container": None}   # Référence au conteneur solo (mode pleine hauteur)
    ai_mode            = {"value": False}
    ai_conversation    = []              # Historique de conversation [{role, content}]
    ai_streaming       = {"value": False}
    ollama_process     = {"proc": None}  # Process ollama serve lancé par nous
    ai_pending_images  = []              # Images jointes en attente [{path, b64}]
    ai_pending_files   = []              # Documents/audio joints en attente [{path, type}]
    _live_print_counts = {}     # {file_path: int} — cache local/live des nombres d'impressions avant renommage disque
    _print_rename_timers = {}   # {file_path: threading.Timer} — timers pour débouncer le renommage disque
    _print_count_text_refs = {} # {file_path: ft.Text}
    _print_minus_btn_refs = {}  # {file_path: ft.Container}



    def _generate_thumbnail(file_path):
        """
        Génère une miniature via le cache persistant thumb_cache.
        Retourne une chaîne base64, ou None en cas d'échec.
        """
        return thumb_cache.get_or_generate(file_path)



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
    app_progress_bar = ft.ProgressBar(value=None, visible=False, color=GREEN, height=2)
    terminal_cmd_input = ft.TextField(
        hint_text="> Terminal",#  (tapez /note pour ouvrir le bloc-notes)",
        border_color=GREEN,
        text_style=ft.TextStyle(font_family="monospace", size=CONSTANTS.TERMINAL_FONT_SIZE),
        dense=True,
        expand=True,
        color=GREEN,
        on_submit=lambda e: on_terminal_command_submit(e),
        on_focus=lambda e: terminal_input_focused.update({"value": True}),
        on_blur=lambda e: terminal_input_focused.update({"value": False}),
    )
    terminal_cmd_row = ft.Row([terminal_cmd_input])

    # ── Bloc-notes ────────────────────────────────────────────────────
    notes_file_path      = os.path.join(app_directory, ".notes.md")
    constants_file_path  = os.path.join(app_directory, "Data", "CONSTANTS.py")
    ai_history_file_path = os.path.join(app_directory, ".ai_conversation.json")
    note_mode            = {"value": False}
    note_target_file     = {"path": notes_file_path}

    notepad_field = ft.TextField(
        multiline=True,
        expand=True,
        min_lines=4,
        text_style=ft.TextStyle(font_family="monospace", size=CONSTANTS.TERMINAL_FONT_SIZE),
        color=WHITE,
        border_color=ft.Colors.TRANSPARENT,
        border_radius=6,
        bgcolor=DARK,
        filled=True,
        hint_text="Écrivez vos notes ici…",
        hint_style=ft.TextStyle(color=LIGHT_GREY, italic=True),
    )
    notepad_is_preview       = {"value": False}
    notepad_markdown_preview = ft.Markdown(
        "",
        selectable=True,
        extension_set=ft.MarkdownExtensionSet.GITHUB_WEB,
        code_theme=ft.MarkdownCodeTheme.ATOM_ONE_DARK,
        expand=True,
    )
    notepad_preview_scroll = ft.ListView(
        controls=[notepad_markdown_preview],
        expand=True,
        visible=False,
    )

    notepad_header_icon  = ft.Icon(ft.Icons.EDIT_NOTE, color=VIOLET, size=16)
    notepad_header_title = ft.Text("Notes", color=VIOLET, size=12, weight=ft.FontWeight.BOLD)

    expand_button_terminal = ft.IconButton(
        icon=ft.Icons.EXPAND_LESS,
        tooltip="Agrandir  (Ctrl+↑)",
        icon_color=LIGHT_GREY,
        icon_size=16,
        on_click=lambda e: toggle_terminal_overlay(),
    )
    expand_button_overlay = ft.IconButton(
        icon=ft.Icons.EXPAND_LESS,
        tooltip="Agrandir  (Ctrl+↑)",
        icon_color=LIGHT_GREY,
        icon_size=16,
        on_click=lambda e: toggle_terminal_overlay(),
    )
    expand_button_notepad = ft.IconButton(
        icon=ft.Icons.EXPAND_LESS,
        tooltip="Agrandir  (Ctrl+↑)",
        icon_color=LIGHT_GREY,
        icon_size=16,
        on_click=lambda e: toggle_terminal_overlay(),
    )

    notepad_container = ft.Container(
        content=ft.Column([
            notepad_field,
            notepad_preview_scroll,
        ], spacing=4, expand=True),
        expand=True,
        visible=True,
        bgcolor=DARK,
    )



    # ── Conversation IA ───────────────────────────────────────────────
    ai_chat_view = ft.ListView(expand=True, spacing=4, auto_scroll=True)
    ai_input_field = ft.TextField(
        hint_text="Posez votre question… (Entrée pour envoyer)",
        border_color=BLUE,
        text_style=ft.TextStyle(font_family="monospace", size=CONSTANTS.TERMINAL_FONT_SIZE),
        dense=True,
        expand=True,
        color=WHITE,
        bgcolor=DARK,
        shift_enter=True,
        on_submit=lambda e: _on_ai_submit(),
    )
    ai_model_dropdown = ft.Dropdown(
        value=CONSTANTS.AI_MODEL_TEXT,
        options=[ft.dropdown.Option(model) for model in CONSTANTS.AI_DROPDOWN_MODELS],
        text_size=11,
        dense=True,
        color=LIGHT_GREY,
        bgcolor=DARK,
        border_color=GREY,
        content_padding=ft.Padding.symmetric(horizontal=6, vertical=0),
        width=150,
    )
    ai_status_text    = ft.Text("", color=LIGHT_GREY, size=11, italic=True)
    ai_progress_bar  = ft.ProgressBar(value=None, visible=False, color=BLUE, height=2)
    ai_stop_button   = ft.IconButton(
        icon=ft.Icons.STOP_CIRCLE,
        icon_color=LIGHT_GREY,
        icon_size=16,
        tooltip="Libérer le modèle (ollama stop)",
        on_click=lambda e: _ai_stop_model(),
    )
    ai_attach_row    = ft.Row([], spacing=4, visible=False, wrap=True)
    ai_send_button   = ft.IconButton(
        icon=ft.Icons.SEND,
        icon_color=BLUE,
        icon_size=18,
        tooltip="Envoyer",
        on_click=lambda e: _on_ai_submit(),
    )
    ai_attach_button = ft.IconButton(
        icon=ft.Icons.ATTACH_FILE,
        icon_color=LIGHT_GREY,
        icon_size=18,
        tooltip="Joindre une image, un document ou un fichier audio",
        on_click=lambda e: page.run_task(_ai_pick_any),
    )
    ai_mic_button = ft.IconButton(
        icon=ft.Icons.MIC,
        icon_color=LIGHT_GREY,
        icon_size=18,
        tooltip=f"Enregistrer {CONSTANTS.AI_VOICE_RECORDING_SECONDS} s puis envoyer",
        visible=CONSTANTS.AI_VOICE_ENABLED,
        on_click=lambda e: _on_voice_input(),
    )
    ai_tts_enabled = {"value": CONSTANTS.AI_VOICE_TTS_ENABLED}
    ai_speaker_button = ft.IconButton(
        icon=ft.Icons.VOLUME_UP if CONSTANTS.AI_VOICE_TTS_ENABLED else ft.Icons.VOLUME_OFF,
        icon_color=CONSTANTS.COLOR_BLUE if CONSTANTS.AI_VOICE_TTS_ENABLED else CONSTANTS.COLOR_LIGHT_GREY,
        icon_size=18,
        tooltip="Désactiver la lecture vocale" if CONSTANTS.AI_VOICE_TTS_ENABLED else "Activer la lecture vocale",
        visible=CONSTANTS.AI_VOICE_ENABLED or CONSTANTS.AI_VOICE_TTS_BTN_VISIBLE,
        on_click=lambda e: _toggle_tts(),
    )

    ai_container = ft.Container(
        content=ft.Column([
            ai_chat_view,
            ai_attach_row,
            ai_progress_bar,
            ft.Row(
                [ai_attach_button, ai_mic_button, ai_input_field, ai_send_button],
                spacing=4,
                vertical_alignment=ft.CrossAxisAlignment.CENTER,
            ),
        ], spacing=4, expand=True),
        expand=True,
        visible=True,
        bgcolor=DARK,
    )


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



    select_same_date_button = ft.IconButton(
        icon=ft.Icons.EVENT,
        icon_color=VIOLET,
        icon_size=22,
        tooltip="Sélectionner même date",
    )



    filter_sel_btn = ft.IconButton(
        icon=ft.Icons.FILTER_LIST,
        icon_color=LIGHT_GREY,
        icon_size=22,
        tooltip="Afficher uniquement la sélection",
    )



    sort_segment = ft.CupertinoSlidingSegmentedButton(
        selected_index=2,
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
        height=45,
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
    )



    # ── Champs de saisie Redimensionner ──────────────────────────────
    resize_input = ft.TextField(
        value=str(CONSTANTS.RESIZE_DEFAULT),
        width=80,
        height=35,
        text_size=13,
        text_align=ft.TextAlign.CENTER,
        keyboard_type=ft.KeyboardType.NUMBER,
        border_color=BLUE,
        content_padding=ft.Padding(5, 5, 5, 5),
    )
    resize_watermark_input = ft.TextField(
        value=str(CONSTANTS.RESIZE_DEFAULT),
        width=80,
        height=35,
        text_size=13,
        text_align=ft.TextAlign.CENTER,
        keyboard_type=ft.KeyboardType.NUMBER,
        border_color=ORANGE,
        content_padding=ft.Padding(5, 5, 5, 5),
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
    # (terminal géré directement dans log_to_terminal)



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
        """Restaure la fenêtre Dashboard quand Side Panel se ferme."""
        page.window.minimized = False
        page.window.maximized = True
        page.update()

    page.pubsub.subscribe_topic("restore_window", on_restore_window)


    def on_deselect_request(topic, message):
        """Callback pour désélectionner tous les fichiers depuis un thread de fond."""
        selected_files.clear()
        if show_only_selection["value"]:
            show_only_selection["value"] = False
            _update_filter_sel_btn()
            _render_preview_page()
        else:
            _update_visible_checkboxes()

    # S'abonner au canal deselect
    page.pubsub.subscribe_topic("deselect", on_deselect_request)


    def _launch_side_panel(extra_env: dict = None):
        """Lance Side Panel, minimise Dashboard, puis le restaure à la fermeture de Side Panel."""
        env = {
            **os.environ,
            "SELECTEUR_INITIAL_FOLDER": (
                current_browse_folder["path"] or selected_folder["path"] or ""
            ),
        }
        if extra_env:
            env.update(extra_env)
        proc = subprocess.Popen(
            [sys.executable, os.path.join(app_directory, "Data", "SidePanel.pyw")],
            env=env,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        page.window.minimized = True
        page.update()

        def _watch():
            proc.wait()
            page.window.minimized = False
            page.run_task(page.window.to_front)
            page.update()

        threading.Thread(target=_watch, daemon=True).start()



    def _launch_comparaison(second_folder: str = ""):
        """Lance Comparaison.pyw, minimise Dashboard, puis le restaure à la fermeture."""
        browse = current_browse_folder["path"] or ""
        base   = selected_folder["path"] or ""

        # Dossier 1 : dossier courant de navigation (ou le dossier sélectionné)
        folder1 = browse or base
        if not folder1:
            log_to_terminal("[ERREUR] Veuillez sélectionner un dossier avant de lancer la Comparaison", RED)
            return

        # Dossier 2 : si browse et base sont distincts, utiliser base comme dossier 2
        if browse and base and os.path.normpath(browse) != os.path.normpath(base):
            folder2 = base
        else:
            folder2 = second_folder

        def _do_launch(f2: str):
            env = {**os.environ, "FOLDER_PATH": folder1}
            if f2:
                env["SECOND_FOLDER"] = f2
            # Si des fichiers sont sélectionnés dans folder1, les transmettre pour filtrer la comparaison
            files_in_folder1 = [
                f for f in selected_files
                if os.path.isfile(f) and os.path.normpath(os.path.dirname(f)) == os.path.normpath(folder1)
            ]
            if files_in_folder1:
                env["SELECTED_FILES"] = "|".join(os.path.basename(f) for f in files_in_folder1)
            comparaison_path = os.path.join(app_directory, "Data", "Comparaison.pyw")
            proc = subprocess.Popen([sys.executable, comparaison_path], env=env)
            page.window.minimized = True
            page.update()

            def _watch():
                proc.wait()
                page.window.minimized = False
                page.window.maximized = True
                page.update()

            threading.Thread(target=_watch, daemon=True).start()

        # Si le second dossier est déjà connu, lancer directement
        if folder2:
            _do_launch(folder2)
            return
        # Sinon, ouvrir un sélecteur de dossier dans Dashboard pour choisir le second dossier
        async def _pick_and_launch(e=None):
            picked = await ft.FilePicker().get_directory_path(
                dialog_title="Sélectionner le second dossier à comparer",
                initial_directory=folder1)
            if picked:
                _do_launch(os.path.normpath(picked))
            else:
                log_to_terminal("[INFO] Comparaison annulée (pas de second dossier sélectionné)", LIGHT_GREY)

        page.run_task(_pick_and_launch)



    def _launch_kiosk_flet():
        """Lance kiosk_flet.pyw, minimise Dashboard, puis le restaure à la fermeture."""
        folder = current_browse_folder["path"] or selected_folder["path"] or ""
        env = {**os.environ}
        if folder:
            env["FOLDER_PATH"] = folder
        env["TARIFF_TYPE"] = kiosk_tariff["value"]
        kiosk_path = os.path.join(app_directory, "Data", "kiosk_flet.pyw")
        proc = subprocess.Popen([sys.executable, kiosk_path], env=env,
                                  stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        page.window.minimized = True
        page.update()

        def _watch():
            proc.wait()
            page.window.minimized = False
            page.window.maximized = True
            page.update()
            refresh_preview(reset_page=False)

        threading.Thread(target=_watch, daemon=True).start()

    _kiosk_tariff_label = ft.Text("PRINTS", size=12, color=DARK)
    kiosk_tariff_btn = ft.Button(
        content=_kiosk_tariff_label,
        bgcolor=GREEN,
        style=ft.ButtonStyle(
            padding=ft.Padding.symmetric(horizontal=10, vertical=2),
            shape=ft.StadiumBorder(),
        ),
        height=40,
        width=76,
        tooltip="Tarif kiosk actif — cliquer pour changer (STUDIOS / PRINTS)",
    )

    def _toggle_kiosk_tariff(e) -> None:
        kiosk_tariff["value"] = "PRINTS" if kiosk_tariff["value"] == "STUDIOS" else "STUDIOS"
        if kiosk_tariff["value"] == "STUDIOS":
            _kiosk_tariff_label.value = "STUDIOS"
            kiosk_tariff_btn.bgcolor = YELLOW
        else:
            _kiosk_tariff_label.value = "PRINTS"
            kiosk_tariff_btn.bgcolor = GREEN
        kiosk_tariff_btn.update()

    kiosk_tariff_btn.on_click = _toggle_kiosk_tariff


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



    def _start_thumb_loader():
        """Lance un thread qui génère les miniatures PIL pour la page courante."""
        pending_snapshot = list(_pending_thumb_refs.items())
        load_token = preview_refresh_token["value"]

        def _load():
            _ts = CONSTANTS.DASHBOARD_THUMB_SIZE
            for norm_path, (img_ref, file_path, icon, icon_color) in pending_snapshot:
                if preview_refresh_token["value"] != load_token:
                    return  # Navigation survenue, annuler
                thumb = _generate_thumbnail(file_path)
                if thumb and preview_refresh_token["value"] == load_token:
                    _thumb_cache[norm_path] = thumb
                    img_ref.bgcolor = None
                    img_ref.content = ft.Image(
                        src=thumb,
                        width=_ts, height=_ts,
                        fit=ft.BoxFit.COVER,
                        border_radius=ft.BorderRadius.all(4),
                    )

                    async def _apply():
                        try:
                            page.update()
                        except Exception:
                            pass

                    page.run_task(_apply)

        threading.Thread(target=_load, daemon=True).start()



    def request_quit():
        """Ferme la fenêtre principale de façon thread-safe via pubsub"""
        page.pubsub.send_all_on_topic("quit", None)



    def request_refresh():
        """Demande un rafraîchissement de la preview (thread-safe)"""
        page.pubsub.send_all_on_topic("refresh", None)



    def on_keyboard_event(e: ft.KeyboardEvent):
        """Gestionnaire des événements clavier pour les raccourcis"""
        ctrl_pressed = e.ctrl or e.meta

        # Ctrl+↑ / Ctrl+↓ sont globaux : fonctionnent quelle que soit la zone active
        if ctrl_pressed and e.key in ("Arrow Up", "ArrowUp"):
            toggle_terminal_overlay()
            return

        if ctrl_pressed and e.key in ("Arrow Down", "ArrowDown"):
            if ai_mode["value"]:
                switch_to_terminal_mode()
            else:
                switch_to_ai_mode()
            return

        if ctrl_pressed and (ai_mode["value"] or note_mode["value"]):
            if e.key in ("Arrow Left", "ArrowLeft"):
                toggle_ai_fullscreen()
                return
            if e.key in ("Arrow Right", "ArrowRight"):
                toggle_notepad_fullscreen()
                return

        if terminal_input_focused["value"]:
            if e.key in ("Arrow Up", "ArrowUp"):
                if command_history:
                    if history_index["value"] == -1:
                        history_draft["value"] = terminal_cmd_input.value or ""
                    history_index["value"] = min(history_index["value"] + 1, len(command_history) - 1)
                    terminal_cmd_input.value = command_history[history_index["value"]]
                    terminal_cmd_input.update()
                return
            elif e.key in ("Arrow Down", "ArrowDown"):
                if history_index["value"] >= 0:
                    history_index["value"] -= 1
                    terminal_cmd_input.value = (
                        history_draft["value"] if history_index["value"] == -1
                        else command_history[history_index["value"]]
                    )
                    terminal_cmd_input.update()
                return
            elif e.key == "Enter":
                on_terminal_command_submit(e)
                return

        if e.key == "Escape" and (note_mode["value"] or ai_mode["value"]):
            switch_to_terminal_mode()
            return

        # Ne pas intercepter les raccourcis clavier si le bloc-notes ou l'IA est actif
        # (laisser le TextField gérer ses propres Ctrl+A, Ctrl+C, etc.)
        if note_mode["value"] or ai_mode["value"]:
            return

        if ctrl_pressed:
            if e.key == "A":
                toggle_select_all(None)
            elif e.key == "C":
                copy_selected_files(None)
            elif e.key == "I":
                invert_selection(None)
            elif e.key == "N":
                create_new_folder(None)
            elif e.key == "R":
                refresh_preview(force_reload=True)
            elif e.key == "V":
                paste_files(None)
            elif e.key == "X":
                cut_selected_files(None)
        elif e.key in ("Delete", "Backspace"):
            delete_selected_files(None)

    # Activer la gestion des événements clavier
    page.on_keyboard_event = on_keyboard_event



    # ================================================================ #
    #                          TERMINAL                                #
    # ================================================================ #
    _terminal_update_timer = {"timer": None}
    _terminal_update_lock  = threading.Lock()

    def log_to_terminal(message, color=WHITE):
        """Ajoute un message au terminal intégré"""
        clean_message = _ANSI_ESCAPE.sub('', message).strip()
        if not clean_message:
            return
        try:
            terminal_output.controls.append(
                ft.Text(clean_message, size=CONSTANTS.TERMINAL_FONT_SIZE, color=color, font_family="monospace")
            )
            if len(terminal_output.controls) > 1000:
                terminal_output.controls.pop(0)
            with _terminal_update_lock:
                if _terminal_update_timer["timer"] is not None:
                    _terminal_update_timer["timer"].cancel()
                def _do_update():
                    page.update()
                    async def _scroll():
                        try:
                            await terminal_output.scroll_to(offset=-1)
                        except Exception:
                            pass
                    page.run_task(_scroll)
                t = threading.Timer(0.05, _do_update)
                _terminal_update_timer["timer"] = t
                t.start()
        except Exception:
            pass



    def clear_terminal(e):
        """Efface le contenu du terminal"""
        terminal_output.controls.clear()
        page.update()

        async def _refocus_after_clear():
            try:
                await terminal_cmd_input.focus()
            except Exception:
                pass

        page.run_task(_refocus_after_clear)



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



    # ── Bloc-notes : fonctions ──────────────────────────────────────────
    async def _notepad_save_as():
        """Exporte le contenu du bloc-notes dans un fichier choisi par l'utilisateur."""
        result = await ft.FilePicker().save_file(
            dialog_title="Enregistrer le bloc-notes sous…",
            file_name="notes.md",
            allowed_extensions=["txt", "md"],
        )
        if not result:
            return
        target_path = result if isinstance(result, str) else getattr(result, "path", None)
        if not target_path:
            return
        try:
            with open(target_path, "w", encoding="utf-8") as exported_file:
                exported_file.write(notepad_field.value or "")
            log_to_terminal(f"[OK] Bloc-notes exporté → {target_path}", GREEN)
        except Exception as export_error:
            log_to_terminal(f"[ERREUR] Export bloc-notes : {export_error}", RED)

    def _notepad_clear():
        """Efface tout le contenu du bloc-notes (sans sauvegarder)."""
        notepad_field.value = ""
        if notepad_is_preview["value"]:
            notepad_is_preview["value"] = False
            notepad_field.visible = True
            notepad_preview_scroll.visible = False
        try:
            page.update()
        except Exception:
            pass

    def _prepare_notepad_markdown(text: str) -> str:
        """Prépare le texte brut pour l'affichage Markdown en préservant les sauts
        de ligne : deux espaces en fin de ligne non vide (force <br>), et &nbsp;
        pour les lignes vides afin de conserver l'espacement vertical."""
        processed_lines = []
        for line in text.split("\n"):
            if line.strip() == "":
                processed_lines.append("&nbsp;")
            else:
                processed_lines.append(line + "  ")
        return "\n".join(processed_lines)

    def _notepad_toggle_preview():
        """Bascule entre édition et prévisualisation Markdown du bloc-notes."""
        notepad_is_preview["value"] = not notepad_is_preview["value"]
        is_preview = notepad_is_preview["value"]
        if is_preview:
            save_notes()
            notepad_markdown_preview.value = _prepare_notepad_markdown(notepad_field.value or "")
            notepad_preview_scroll.visible = True
            notepad_field.visible = False
        else:
            notepad_field.visible = True
            notepad_preview_scroll.visible = False
        try:
            page.update()
        except Exception:
            pass

    def save_notes():
        """Sauvegarde le contenu du bloc-notes dans le fichier cible."""
        is_constants = (note_target_file["path"] == constants_file_path)
        try:
            with open(note_target_file["path"], "w", encoding="utf-8") as _f:
                _f.write(notepad_field.value or "")
            label = os.path.basename(note_target_file["path"])
            log_to_terminal(f"[OK] {label} sauvegardé", GREEN)
        except Exception as _err:
            log_to_terminal(f"[ERREUR] Sauvegarde : {_err}", RED)
            return
        if is_constants:
            log_to_terminal("[INFO] Redémarrage pour appliquer les nouvelles constantes…", ORANGE)
            dashboard_path = os.path.abspath(__file__)
            async def _restart_async():
                import time as _time
                _time.sleep(0.4)
                subprocess.Popen([sys.executable, dashboard_path])
                _time.sleep(0.2)
                try:
                    await page.window.close()
                except Exception:
                    pass
                os._exit(0)
            page.run_task(_restart_async)

    def load_notes():
        """Charge le contenu du bloc-notes depuis le fichier cible."""
        # Toujours revenir en mode édition lors du chargement d'un nouveau fichier
        if notepad_is_preview["value"]:
            notepad_is_preview["value"] = False
            notepad_field.visible = True
            notepad_preview_scroll.visible = False
        try:
            if os.path.exists(note_target_file["path"]):
                with open(note_target_file["path"], "r", encoding="utf-8") as _f:
                    content = _f.read()
            else:
                content = ""
        except Exception:
            content = ""
        notepad_field.value = content
        if notepad_is_preview["value"]:
            notepad_markdown_preview.value = content
            notepad_preview_scroll.visible = True
            notepad_field.visible = False

    def _open_notepad_ui(title, icon, color, hint):
        """Affiche la zone bloc-notes (+ IA) avec le titre et la couleur donnés."""
        notepad_header_icon.name  = icon
        notepad_header_icon.color = color
        notepad_header_title.value = title
        notepad_header_title.color = color
        notepad_field.hint_text   = hint
        load_notes()
        note_mode["value"] = True
        ai_mode["value"]   = True
        terminal_output.visible  = False
        terminal_cmd_row.visible = False
        update_overlay_visibility()
        try:
            page.update()
        except Exception:
            pass

        async def _focus_note():
            try:
                await notepad_field.focus()
            except Exception:
                pass
        page.run_task(_focus_note)

    def switch_to_note():
        """Bascule la zone bas en mode bloc-notes (fichier .notes.md)."""
        note_target_file["path"] = notes_file_path
        _open_notepad_ui("Notes", ft.Icons.EDIT_NOTE, VIOLET, "Écrivez vos notes ici…")

    def switch_to_options():
        """Bascule la zone bas en mode édition CONSTANTS.py."""
        note_target_file["path"] = constants_file_path
        _open_notepad_ui("CONSTANTS.py", ft.Icons.TUNE, ORANGE, "Modifiez les constantes ici…")
        return

    def open_file_in_notepad(file_path):
        """Ouvre un fichier texte dans le bloc-notes intégré et affiche le panneau."""
        note_target_file["path"] = file_path
        title = os.path.basename(file_path)
        _open_notepad_ui(title, ft.Icons.DESCRIPTION, VIOLET, "")

    def _create_and_open_info_txt(e=None):
        """Crée INFO.txt dans le dossier courant (si inexistant) et l'ouvre dans le bloc-notes."""
        folder = current_browse_folder["path"] or selected_folder.get("path")
        if not folder or not os.path.isdir(folder):
            log_to_terminal("[INFO] Aucun dossier sélectionné", LIGHT_GREY)
            return
        file_path = os.path.join(folder, "INFO.txt")
        if not os.path.exists(file_path):
            try:
                with open(file_path, "w", encoding="utf-8") as _f:
                    pass
            except Exception as err:
                log_to_terminal(f"[ERREUR] Création INFO.txt : {err}", RED)
                return
            refresh_preview(reset_page=False)
        open_file_in_notepad(file_path)

    # ── Intelligence artificielle ──────────────────────────────────────
    def switch_to_ai_mode():
        """Bascule la zone bas en mode conversation IA + notes."""
        note_target_file["path"] = notes_file_path
        load_notes()
        note_mode["value"] = True
        ai_mode["value"] = True
        terminal_output.visible  = False
        terminal_cmd_row.visible = False
        update_overlay_visibility()
        terminal_output.update()
        terminal_cmd_row.update()
        try:
            page.update()
        except Exception:
            pass

        # Pré-démarrer Ollama en silence pendant que l'utilisateur tape
        def _silent_prestart():
            try:
                urllib.request.urlopen(f"{CONSTANTS.AI_OLLAMA_URL}/api/tags", timeout=3).close()
            except Exception:
                try:
                    ollama_process["proc"] = subprocess.Popen(
                        ["ollama", "serve"],
                        stdout=subprocess.DEVNULL,
                        stderr=subprocess.DEVNULL,
                    )
                except Exception:
                    pass
        threading.Thread(target=_silent_prestart, daemon=True).start()

        async def _focus_ai():
            try:
                await ai_input_field.focus()
            except Exception:
                pass
        page.run_task(_focus_ai)

    def _clear_ai_conversation():
        """Efface l'historique de la conversation IA et supprime le fichier .ai_conversation.json."""
        ai_conversation.clear()
        ai_chat_view.controls.clear()
        ai_status_text.value = ""
        try:
            if os.path.isfile(ai_history_file_path):
                os.remove(ai_history_file_path)
        except Exception:
            pass
        try:
            page.update()
        except Exception:
            pass

    def _ai_save_history():
        """Sauvegarde ai_conversation dans .ai_conversation.json."""
        try:
            # Ne sauvegarder que role + content (pas les images base64)
            serializable = [
                {"role": message["role"], "content": message["content"]}
                for message in ai_conversation
                if message.get("role") in ("user", "assistant")
            ]
            with open(ai_history_file_path, "w", encoding="utf-8") as history_file:
                json.dump(serializable, history_file, ensure_ascii=False, indent=2)
        except Exception:
            pass

    def _ai_load_history():
        """Charge .ai_conversation.json dans ai_conversation et reconstruit ai_chat_view."""
        if not os.path.isfile(ai_history_file_path):
            return
        try:
            with open(ai_history_file_path, "r", encoding="utf-8") as history_file:
                saved_messages = json.load(history_file)
            for message in saved_messages:
                role = message.get("role")
                content = message.get("content", "")
                if role not in ("user", "assistant"):
                    continue
                ai_conversation.append({"role": role, "content": content})
                is_user = role == "user"
                if is_user:
                    bubble_text = ft.Text(
                        content,
                        size=CONSTANTS.TERMINAL_FONT_SIZE,
                        color=BLUE,
                        font_family="monospace",
                        selectable=True,
                        no_wrap=False,
                    )
                else:
                    bubble_text = ft.Markdown(
                        content,
                        selectable=True,
                        extension_set=ft.MarkdownExtensionSet.GITHUB_WEB,
                        code_theme=ft.MarkdownCodeTheme.ATOM_ONE_DARK,
                        expand=True,
                    )
                bubble = ft.Container(
                    content=bubble_text,
                    bgcolor=DARK if is_user else GREY,
                    border_radius=6,
                    padding=ft.Padding(8, 4, 8, 4),
                    expand=True,
                )
                ai_chat_view.controls.append(
                    ft.Row(
                        [bubble],
                        alignment=ft.MainAxisAlignment.END if is_user else ft.MainAxisAlignment.START,
                    )
                )
        except Exception:
            pass

    def _export_ai_conversation(to_notepad=False, event=None):
        """Copie la conversation IA dans le presse-papiers, et la transfère dans le bloc-notes si demandé."""
        if not ai_conversation:
            log_to_terminal("[IA] Aucune conversation à exporter", LIGHT_GREY)
            return
        text = _format_ai_conversation(ai_conversation, CONSTANTS.AI_USER_NAME, CONSTANTS.AI_SEPARATOR_WIDTH)
        async def _copy():
            try:
                await ft.Clipboard().set(text)
                log_to_terminal("[IA] Conversation copiée dans le presse-papiers", BLUE)
            except Exception as copy_error:
                log_to_terminal(f"[ERREUR] Copie IA : {copy_error}", RED)
        page.run_task(_copy)
        if to_notepad:
            switch_to_note()
            existing = notepad_field.value or ""
            sep = "\n\n" + "#" * CONSTANTS.AI_SEPARATOR_WIDTH + "\n\n" if existing.strip() else ""
            notepad_field.value = existing + sep + text
            try:
                notepad_field.update()
            except Exception:
                pass

    def _ai_stop_model():
        """Libère le modèle chargé en RAM via `ollama stop`."""
        def _run_stop():
            try:
                current_model = ai_model_dropdown.value or CONSTANTS.AI_MODEL_TEXT
                if not (current_model or "").startswith("gemini"):
                    subprocess.run(["ollama", "stop", CONSTANTS.AI_MODEL_VISION], timeout=10)
                    subprocess.run(["ollama", "stop", CONSTANTS.AI_MODEL_TEXT],   timeout=10)
            except Exception:
                pass
            ai_stop_button.visible = False
            ai_stop_button.icon_color = LIGHT_GREY
            ai_status_text.value = ""
            try:
                page.update()
            except Exception:
                pass
        threading.Thread(target=_run_stop, daemon=True).start()

    # ── Gestion des images jointes ────────────────────────────────────
    def _ai_refresh_attach_row():
        """Reconstruit la barre de pièces jointes visuellement."""
        ai_attach_row.controls.clear()
        for image_entry in ai_pending_images:
            name = os.path.basename(image_entry["path"])
            # Copie locale pour la lambda
            entry_ref = image_entry
            ai_attach_row.controls.append(
                ft.Container(
                    content=ft.Row([
                        ft.Icon(ft.Icons.IMAGE, size=13, color=ORANGE),
                        ft.Text(name, size=11, color=ORANGE),
                        ft.IconButton(
                            icon=ft.Icons.CLOSE,
                            icon_color=RED,
                            icon_size=12,
                            tooltip="Retirer",
                            style=ft.ButtonStyle(padding=ft.Padding.all(2)),
                            on_click=lambda e, ref=entry_ref: _ai_remove_image(ref),
                        ),
                    ], spacing=2, tight=True),
                    bgcolor=GREY,
                    border_radius=4,
                    padding=ft.Padding(4, 2, 4, 2),
                )
            )
        for file_entry in ai_pending_files:
            name = os.path.basename(file_entry["path"])
            file_type = file_entry["type"]
            icon_name = ft.Icons.AUDIO_FILE if file_type == "audio" else ft.Icons.DESCRIPTION
            entry_ref = file_entry
            ai_attach_row.controls.append(
                ft.Container(
                    content=ft.Row([
                        ft.Icon(icon_name, size=13, color=YELLOW),
                        ft.Text(name, size=11, color=YELLOW),
                        ft.IconButton(
                            icon=ft.Icons.CLOSE,
                            icon_color=RED,
                            icon_size=12,
                            tooltip="Retirer",
                            style=ft.ButtonStyle(padding=ft.Padding.all(2)),
                            on_click=lambda e, ref=entry_ref: _ai_remove_file(ref),
                        ),
                    ], spacing=2, tight=True),
                    bgcolor=GREY,
                    border_radius=4,
                    padding=ft.Padding(4, 2, 4, 2),
                )
            )
        ai_attach_row.visible = bool(ai_pending_images) or bool(ai_pending_files)
        try:
            page.update()
        except Exception:
            pass

    def _ai_attach_image(image_path):
        """Encode une image en base64 (redimensionnée à 1024px max) et l'ajoute aux pièces jointes."""
        # Vérifier si déjà jointe
        if any(entry["path"] == image_path for entry in ai_pending_images):
            return
        try:
            from PIL import Image as PilImage
            import io as _io
            with PilImage.open(image_path) as pil_img:
                pil_img = pil_img.convert("RGB")
                max_side = 1024
                width, height = pil_img.size
                if width > max_side or height > max_side:
                    ratio = min(max_side / width, max_side / height)
                    new_size = (int(width * ratio), int(height * ratio))
                    pil_img = pil_img.resize(new_size, PilImage.LANCZOS)
                buffer = _io.BytesIO()
                pil_img.save(buffer, format="JPEG", quality=85)
                b64_data = base64.b64encode(buffer.getvalue()).decode("utf-8")
        except Exception:
            # Fallback : lecture brute si Pillow échoue
            try:
                with open(image_path, "rb") as image_file:
                    b64_data = base64.b64encode(image_file.read()).decode("utf-8")
            except Exception as exc:
                _ai_add_bubble("assistant", f"[ERREUR] Impossible de lire l'image : {exc}")
                return
        ai_pending_images.append({"path": image_path, "b64": b64_data})
        _ai_refresh_attach_row()
        # Avertir si le modèle vision configuré ne supporte pas réellement la vision
        vision_model = CONSTANTS.AI_MODEL_VISION
        is_vision = any(
            vision_model == entry[1] or vision_model.startswith(entry[1] + ":")
            for entry in CONSTANTS.AI_AVAILABLE_MODELS
            if entry[2]
        )
        if not is_vision:
            _ai_add_bubble(
                "assistant",
                f"⚠️ Le modèle vision configuré ({vision_model}) n'est pas reconnu comme modèle vision.\n"
                "Vérifiez AI_MODEL_VISION dans CONSTANTS.py.",
            )

    def _ai_remove_image(image_entry):
        """Retire une image des pièces jointes en attente."""
        if image_entry in ai_pending_images:
            ai_pending_images.remove(image_entry)
        _ai_refresh_attach_row()

    # ── Extensions reconnues comme documents ou fichiers audio ────────
    _AI_DOCUMENT_EXTS = CONSTANTS.AI_DOCUMENT_EXTS
    _AI_AUDIO_EXTS     = CONSTANTS.AI_AUDIO_EXTS

    def _ai_attach_document_file(file_path):
        """Ajoute un document ou fichier audio aux pièces jointes en attente."""
        if any(entry["path"] == file_path for entry in ai_pending_files):
            return
        ext = os.path.splitext(file_path)[1].lower()
        file_type = "audio" if ext in _AI_AUDIO_EXTS else "document"
        ai_pending_files.append({"path": file_path, "type": file_type})
        _ai_refresh_attach_row()

    def _ai_remove_file(file_entry):
        """Retire un document/audio des pièces jointes en attente."""
        if file_entry in ai_pending_files:
            ai_pending_files.remove(file_entry)
        _ai_refresh_attach_row()

    def _ai_extract_file_content(file_entry):
        """
        Extrait le contenu textuel d'un document ou transcrit un fichier audio.
        Retourne (nom_affiché, texte_extrait).
        Lève une exception si l'extraction échoue.
        """
        file_path = file_entry["path"]
        file_type = file_entry["type"]
        ext = os.path.splitext(file_path)[1].lower()
        name = os.path.basename(file_path)

        if file_type == "audio":
            try:
                import whisper as _whisper
            except ImportError:
                raise ImportError(
                    "openai-whisper n'est pas installé.\n"
                    "Installez-le avec : pip install openai-whisper"
                )
            import shutil as _shutil
            if not _shutil.which("ffmpeg"):
                _system = platform.system()
                if _system == "Darwin":
                    _ffmpeg_hint = "brew install ffmpeg"
                elif _system == "Windows":
                    _ffmpeg_hint = "winget install ffmpeg  (ou https://ffmpeg.org/download.html)"
                else:
                    _ffmpeg_hint = "sudo apt install ffmpeg  (ou le gestionnaire de paquets de votre distro)"
                raise RuntimeError(
                    f"ffmpeg est requis pour transcrire les fichiers audio mais n'est pas installé.\n"
                    f"Installez-le avec : {_ffmpeg_hint}"
                )
            whisper_model = _whisper.load_model("base")
            try:
                result = whisper_model.transcribe(file_path)
            except Exception as whisper_error:
                raise RuntimeError(f"Échec de la transcription : {whisper_error}")
            transcribed_text = (result.get("text") or "").strip()
            if not transcribed_text:
                raise RuntimeError("La transcription est vide — vérifiez que le fichier audio contient de la parole.")
            return name, transcribed_text

        # ── Documents ────────────────────────────────────────────────
        if ext == ".pdf":
            try:
                import fitz as _fitz
                pdf_doc = _fitz.open(file_path)
                text = "\n".join(pdf_page.get_text("text") for pdf_page in pdf_doc)
                pdf_doc.close()
                return name, text
            except ImportError:
                raise ImportError("PyMuPDF non disponible pour lire les PDF.")

        if ext in (".docx", ".doc"):
            try:
                import docx as _docx
                word_doc = _docx.Document(file_path)
                text = "\n".join(para.text for para in word_doc.paragraphs)
                return name, text
            except ImportError:
                raise ImportError(
                    "python-docx non installé. Installez-le avec : pip install python-docx"
                )

        # Fichier texte brut (tous les autres formats)
        with open(file_path, "r", encoding="utf-8", errors="replace") as text_file:
            return name, text_file.read()

    async def _ai_pick_any():
        """Ouvre un sélecteur de fichier pour joindre une image, un document ou un fichier audio."""
        _image_exts_pick = {"jpg", "jpeg", "png", "gif", "bmp", "webp"}
        result = await ft.FilePicker().pick_files(
            dialog_title="Joindre une image, un document ou un fichier audio",
            allowed_extensions=[
                "jpg", "jpeg", "png", "gif", "bmp", "webp",
                "txt", "md", "py", "js", "ts", "json", "csv", "xml",
                "html", "htm", "yaml", "yml", "toml", "ini", "cfg", "log",
                "rst", "pdf", "docx", "doc", "rtf",
                "mp3", "wav", "m4a", "ogg", "flac", "aac", "opus",
            ],
            allow_multiple=True,
        )
        if result:
            for picked_file in result:
                if picked_file.path:
                    ext = os.path.splitext(picked_file.path)[1].lstrip(".").lower()
                    if ext in _image_exts_pick:
                        _ai_attach_image(picked_file.path)
                    else:
                        _ai_attach_document_file(picked_file.path)

    def ai_send_selected_images(e=None):
        """Joint les fichiers image, document et audio sélectionnés dans la preview à la conversation IA."""
        image_exts = CONSTANTS.IMAGE_EXTS
        image_paths = [
            file_path for file_path in selected_files
            if os.path.splitext(file_path)[1].lower() in image_exts
        ]
        file_paths = [
            file_path for file_path in selected_files
            if os.path.splitext(file_path)[1].lower() in (_AI_DOCUMENT_EXTS | _AI_AUDIO_EXTS)
        ]
        if not image_paths and not file_paths:
            log_to_terminal("[IA] Aucun fichier compatible sélectionné dans la preview", LIGHT_GREY)
            return
        switch_to_ai_mode()
        for image_path in image_paths:
            _ai_attach_image(image_path)
        for file_path in file_paths:
            _ai_attach_document_file(file_path)
        total = len(image_paths) + len(file_paths)
        log_to_terminal(f"[IA] {total} fichier(s) joint(s)", BLUE)

    def _ensure_ollama_ready(model_name=None):
        """
        Vérifie qu'Ollama est lancé et que le modèle est disponible.
        Lance le serveur et/ou télécharge le modèle si nécessaire.
        Retourne True si tout est prêt, False en cas d'erreur bloquante.
        Doit être appelé depuis un thread secondaire (bloquant).
        """        
        if model_name is None:
            model_name = CONSTANTS.AI_MODEL_TEXT
        # Les modèles Gemini n'ont pas besoin d'Ollama
        if (model_name or "").startswith("gemini"):
            return True
        def _is_ollama_up():
            try:
                with urllib.request.urlopen(
                    f"{CONSTANTS.AI_OLLAMA_URL}/api/tags", timeout=3
                ) as resp:
                    return resp.status == 200
            except Exception:
                return False

        # ── 1. Démarrer Ollama si nécessaire ──────────────────────────
        if not _is_ollama_up():
            _ai_add_bubble("assistant", "⚙️ Démarrage d'Ollama en arrière-plan…")
            try:
                ollama_process["proc"] = subprocess.Popen(
                    ["ollama", "serve"],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                )
            except FileNotFoundError:
                _ai_add_bubble(
                    "assistant",
                    "[ERREUR] Ollama n'est pas installé sur cette machine.\n"
                    "Téléchargez-le sur https://ollama.com",
                )
                return False
            # Attendre jusqu'à 20 s que le serveur réponde
            for _ in range(40):
                time.sleep(0.5)
                if _is_ollama_up():
                    break
            else:
                _ai_add_bubble(
                    "assistant",
                    "[ERREUR] Ollama n'a pas démarré dans les délais impartis.",
                )
                return False

        # ── 2. Vérifier si le modèle est présent ──────────────────────
        try:
            with urllib.request.urlopen(
                f"{CONSTANTS.AI_OLLAMA_URL}/api/tags", timeout=5
            ) as resp:
                available_names = [
                    model.get("name", "")
                    for model in json.loads(resp.read().decode("utf-8")).get("models", [])
                ]
            model_present = any(
                name == model_name or name.startswith(model_name + ":")
                for name in available_names
            )
        except Exception:
            model_present = False

        if not model_present:
            pull_status_ctrl = _ai_add_bubble(
                "assistant",
                f"⬇️ Téléchargement de {model_name}…\n"
                "(première utilisation — peut prendre quelques minutes)",
            )
            try:
                pull_payload = json.dumps(
                    {"name": model_name, "stream": True}
                ).encode("utf-8")
                pull_request = urllib.request.Request(
                    f"{CONSTANTS.AI_OLLAMA_URL}/api/pull",
                    data=pull_payload,
                    headers={"Content-Type": "application/json"},
                    method="POST",
                )
                with urllib.request.urlopen(pull_request, timeout=3600) as pull_resp:
                    for raw_line in pull_resp:
                        chunk = json.loads(raw_line.decode("utf-8"))
                        status = chunk.get("status", "")
                        completed = chunk.get("completed", 0)
                        total = chunk.get("total", 0)
                        if total:
                            pct = int(completed / total * 100)
                            pull_status_ctrl.value = (
                                f"⬇️ {model_name} — {status} {pct}%"
                            )
                        elif status:
                            pull_status_ctrl.value = (
                                f"⬇️ {model_name} — {status}"
                            )
                        try:
                            page.update()
                        except Exception:
                            pass
                pull_status_ctrl.value = f"✅ {model_name} téléchargé et prêt !"
                try:
                    page.update()
                except Exception:
                    pass
            except Exception as exc:
                _ai_add_bubble("assistant", f"[ERREUR] Téléchargement du modèle : {exc}")
                return False

        return True

    def _clean_file_content(raw_content):
        """
        Retire les artefacts de raisonnement inline de Gemma (chain-of-thought)
        qui s'immiscent parfois dans les arguments de create_file.
        Stratégie :
          - Retire les tokens spéciaux Gemma (<channel|>, <|tool_call>…)
          - Dès qu'une ligne de "thinking" est détectée (Wait,/Hmm,/I see…),
            tronque tout le reste (le contenu qui suit est invalide).
          - Retire les lignes de méta-commentaire isolées.
        """
        import re as _re_cfc
        # Tokens spéciaux Gemma et balises tool_call résiduelles
        content = _re_cfc.sub(r'<channel\|>', '', raw_content)
        content = _re_cfc.sub(r'<\|[^|>]+\|>', '', content)
        content = _re_cfc.sub(r'<\|tool_call>.*?(?:<tool_call\|>|$)', '', content, flags=_re_cfc.DOTALL)

        lines = content.split('\n')
        clean_lines = []

        # Patterns de TRONCATURE : dès qu'une de ces lignes apparaît, tout ce qui suit
        # est du raisonnement Gemma — on coupe ici.
        _TRUNCATE_RE = _re_cfc.compile(
            r'^\s*(?:Wait[,\s—]|Hmm[,\s.]|Actually[,\s—]|I see a discrepancy|'
            r'I notice that|Let me reconsider|Let me re-|I need to re-|'
            r'OK so[,\s]|OK, so[,\s]|I will re-run|I should re-)',
            _re_cfc.IGNORECASE,
        )
        # Patterns de lignes individuelles à ignorer (sans tronquer le reste)
        _SKIP_RE = _re_cfc.compile(
            r'^\s*(?:'
            r'\((?:Note|Wait|Self-correction|Correction|Assuming|Final attempt|'
            r'I will|Since the|The prompt|This was|Using the|Given that|'
            r'Final output|OK,? I|Let me re)'
            r'|(?:Actual list from|Final list based|Listing all files and|'
            r'File List:|Assuming the file|I will generate|I will use the|'
            r'I will stop|I will provide|I will list|I will present|'
            r'Since the prompt|The file list has been|I will assume)'
            r')',
            _re_cfc.IGNORECASE,
        )
        for line in lines:
            # Troncature : début du raisonnement Gemma → arrêt immédiat
            if _TRUNCATE_RE.match(line):
                break
            if _SKIP_RE.match(line):
                continue
            # Retire les parenthèses de raisonnement en fin de ligne
            # ex: "fichier.jpg  (Note: Correction: ...)" → "fichier.jpg"
            line = _re_cfc.sub(
                r'\s*\((?:Note|Wait|Self-correction|Correction):.*',
                '', line, flags=_re_cfc.IGNORECASE,
            )
            clean_lines.append(line)
        # Supprime les blocs de 3+ lignes vides consécutives
        result = _re_cfc.sub(r'\n{3,}', '\n\n', '\n'.join(clean_lines))
        return result.strip()

    def _md_dark(text: str) -> str:
        """Remplace les blockquotes Markdown (fond bleu clair de Flutter)
        par un équivalent lisible sur thème sombre."""
        lines = text.split("\n")
        result = []
        for line in lines:
            if line.startswith("> "):
                result.append("**›** " + line[2:])
            elif line == ">":
                result.append("")
            else:
                result.append(line)
        return "\n".join(result)

    def _speak_bubble(text):
        """Lit un texte via Gemini TTS en streaming (appelé dans un thread)."""
        _gemini_tts_stream(
            text,
            voice_name=CONSTANTS.AI_VOICE_TTS_VOICE,
            tts_model=CONSTANTS.AI_VOICE_TTS_MODEL,
            sample_rate=CONSTANTS.AI_VOICE_TTS_SAMPLE_RATE,
            language_code=CONSTANTS.AI_VOICE_TTS_LANGUAGE,
        )

    def _ai_add_bubble(role, text):
        """Ajoute un message dans le panneau IA et retourne le contrôle (pour le streaming)."""
        is_user  = role == "user"
        is_think = role == "think"
        if is_user:
            bubble_text = ft.Text(
                text,
                size=CONSTANTS.TERMINAL_FONT_SIZE,
                color=BLUE,
                font_family="monospace",
                selectable=True,
                no_wrap=False,
            )
        elif is_think:
            bubble_text = ft.Text(
                f"💭 {text}",
                size=CONSTANTS.TERMINAL_FONT_SIZE - 1,
                color=LIGHT_GREY,
                italic=True,
                selectable=True,
                no_wrap=False,
            )
        else:
            bubble_text = ft.Markdown(
                _md_dark(text),
                selectable=True,
                extension_set=ft.MarkdownExtensionSet.GITHUB_WEB,
                code_theme=ft.MarkdownCodeTheme.ATOM_ONE_DARK,
                md_style_sheet=ft.MarkdownStyleSheet(
                    p_text_style=ft.TextStyle(size=CONSTANTS.TERMINAL_FONT_SIZE),
                ),
                expand=True,
            )
        bubble = ft.Container(
            content=bubble_text,
            bgcolor="#1a1c20" if is_think else (DARK if is_user else GREY),
            border=ft.Border.all(1, LIGHT_GREY) if is_think else None,
            border_radius=6,
            padding=ft.Padding(8, 4, 8, 4),
            expand=True,
        )
        if not is_user and not is_think:
            raw_text = text
            speak_btn = ft.IconButton(
                icon=ft.Icons.VOLUME_UP,
                icon_color=LIGHT_GREY,
                icon_size=14,
                tooltip="Lire cette réponse",
                on_click=lambda e, t=raw_text: threading.Thread(
                    target=_speak_bubble, args=(t,), daemon=True
                ).start(),
            )
            row = ft.Row(
                [bubble, speak_btn],
                alignment=ft.MainAxisAlignment.START,
                vertical_alignment=ft.CrossAxisAlignment.START,
            )
        else:
            row = ft.Row(
                [bubble],
                alignment=ft.MainAxisAlignment.END if is_user else ft.MainAxisAlignment.START,
            )
        ai_chat_view.controls.append(row)
        async def _update_and_scroll():
            try:
                page.update()
                await asyncio.sleep(0)
                await ai_chat_view.scroll_to(offset=-1)
            except Exception:
                pass
        page.run_task(_update_and_scroll)
        return bubble_text

    def _ai_add_image_bubble(image_path):
        """Affiche une image générée par Nano Banana 2 dans le chat IA."""
        img_widget = ft.Image(
            src=image_path,
            width=400,
            border_radius=8,
            fit=ft.BoxFit.CONTAIN,
        )
        row = ft.Row(
            [ft.Container(img_widget, border_radius=8)],
            alignment=ft.MainAxisAlignment.START,
        )
        ai_chat_view.controls.append(row)
        async def _upd():
            try:
                page.update()
                await asyncio.sleep(0)
                await ai_chat_view.scroll_to(offset=-1)
            except Exception:
                pass
        page.run_task(_upd)

    def _send_ai_message(message_text):
        """Envoie un message à Ollama et streame la réponse dans le panneau IA."""
        if ai_streaming["value"]:
            return
        if not message_text.strip() and not ai_pending_images and not ai_pending_files:
            return
        ai_streaming["value"] = True
        ai_stop_button.icon_color = RED
        ai_status_text.value = "⏳ En cours…"
        try:
            page.update()
        except Exception:
            pass

        # Capturer et vider les images jointes avant le thread
        images_b64   = [entry["b64"]  for entry in ai_pending_images]
        images_paths = [entry["path"] for entry in ai_pending_images]
        ai_pending_images.clear()
        _ai_refresh_attach_row()

        # Capturer et vider les documents/audio joints avant le thread
        files_to_inject = list(ai_pending_files)
        ai_pending_files.clear()
        _ai_refresh_attach_row()

        # Choisir le modèle sélectionné par l'utilisateur
        active_model = ai_model_dropdown.value or CONSTANTS.AI_MODEL_TEXT

        enriched_text = message_text
        # Détecter les URLs dans le message et injecter leur contenu
        url_pattern = re.compile(r'https?://[^\s<>"\)\]]+', re.IGNORECASE)
        found_urls = url_pattern.findall(message_text)
        if found_urls:
            url_blocks = []
            for url in found_urls:
                page_content = _fetch_url_content(url, max_chars=CONSTANTS.AI_URL_MAX_CHARS)
                url_blocks.append(f"--- Contenu de {url} ---\n{page_content}\n--- Fin ---")
            enriched_text = enriched_text + "\n\n" + "\n\n".join(url_blocks)

        # Injecter le nom des fichiers image joints pour que l'IA les identifie
        if images_paths:
            filenames_info = ", ".join(os.path.basename(path) for path in images_paths)
            enriched_text = enriched_text + f"\n[Image(s) jointe(s) : {filenames_info}]"

        # Construire l'entrée utilisateur (avec images si présent)
        user_message = {"role": "user", "content": enriched_text}
        if images_b64:
            user_message["images"] = images_b64
        ai_conversation.append(user_message)

        # Afficher la bulle utilisateur avec indicateur image/fichier
        display_text = message_text
        if images_b64:
            display_text = f"🖼️ ({len(images_b64)} image(s))  {message_text}" if message_text else f"🖼️ {len(images_b64)} image(s) jointe(s)"
        if files_to_inject:
            files_label = "  ".join(
                ("🎵" if entry["type"] == "audio" else "📄") + " " + os.path.basename(entry["path"])
                for entry in files_to_inject
            )
            display_text = (display_text + "  " if display_text else "") + files_label
        _ai_add_bubble("user", display_text)

        def _run():
            full_response = ""
            response_text_ctrl = None
            try:
                # S'assurer qu'Ollama est prêt (serveur + modèle)
                if not _ensure_ollama_ready(active_model):
                    return

                # Indiquer que le modèle est en cours de chargement
                loading_ctrl = _ai_add_bubble("assistant", "⏳ Réflexion en cours…")

                def _remove_loading():
                    nonlocal loading_ctrl
                    if loading_ctrl is not None:
                        try:
                            ai_chat_view.controls = [
                                row for row in ai_chat_view.controls
                                if not (
                                    hasattr(row, "controls") and row.controls
                                    and hasattr(row.controls[0], "content")
                                    and row.controls[0].content is loading_ctrl
                                )
                            ]
                            loading_ctrl = None
                        except Exception:
                            pass

                # Extraire et injecter le contenu des documents/audio joints
                if files_to_inject:
                    injected_blocks = []
                    for file_entry in files_to_inject:
                        file_name = os.path.basename(file_entry["path"])
                        try:
                            if file_entry["type"] == "audio":
                                ai_status_text.value = f"⏳ Transcription : {file_name}…"
                                try:
                                    page.update()
                                except Exception:
                                    pass
                            label, content = _ai_extract_file_content(file_entry)
                            type_label = "Transcription audio" if file_entry["type"] == "audio" else "Document"
                            injected_blocks.append(
                                f"--- {type_label} : {label} ---\n{content[:50000]}\n--- Fin ---"
                            )
                        except Exception as extraction_exc:
                            _ai_add_bubble("assistant", f"[ERREUR] {file_name} : {extraction_exc}")
                    if injected_blocks:
                        ai_conversation[-1]["content"] += "\n\n" + "\n\n".join(injected_blocks)
                    ai_status_text.value = "⏳ En cours…"
                    try:
                        page.update()
                    except Exception:
                        pass

                # ── Outils dossier (disponibles si un dossier est ouvert) ─────
                _folder_path_for_tools = current_browse_folder["path"] or selected_folder["path"]
                _FOLDER_TOOLS = _folder_tool_definitions(_folder_path_for_tools)
                if (active_model or "").startswith("gemini"):
                    _ALL_TOOLS = _gemini_tool_definitions(_folder_path_for_tools)
                else:
                    _ALL_TOOLS = _WEB_TOOLS + _TERMINAL_TOOLS + _MEMORY_TOOLS + _FOLDER_TOOLS

                today = datetime.date.today().strftime("%d %B %Y")
                _system_content = _build_system_content(
                    CONSTANTS.AI_SYSTEM_PROMPT, _folder_path_for_tools, today
                )
                # Limiter l'historique aux 10 derniers messages pour éviter
                # que les petits modèles locaux perdent de vue la question courante
                _history = ai_conversation[-10:] if len(ai_conversation) > 10 else ai_conversation
                messages = [
                    {"role": "system", "content": _system_content},
                    *[{k: v for k, v in m.items() if k != "events"} for m in _history],
                ]

                # ── Debug log ───────────────────────────────────────────────
                import json as _json_debug, datetime as _dt_debug
                _DEBUG_LOG = "/tmp/ai_dashboard_debug.log"
                def _dbg(label: str, data) -> None:
                    try:
                        with open(_DEBUG_LOG, "a", encoding="utf-8") as _df:
                            ts = _dt_debug.datetime.now().strftime("%H:%M:%S")
                            _df.write(f"\n{'='*60}\n[{ts}] {label}\n")
                            if isinstance(data, (dict, list)):
                                _df.write(_json_debug.dumps(data, ensure_ascii=False, indent=2))
                            else:
                                _df.write(str(data))
                            _df.write("\n")
                    except Exception:
                        pass
                _dbg("INIT_MESSAGES", messages)

                # Capturer la demande originale de l'utilisateur (avant tout tour d'outil)
                # pour la réinjecter dans les rounds suivants et éviter que Gemma l'oublie.
                _original_user_request = next(
                    (m["content"] for m in reversed(messages) if m["role"] == "user"),
                    "",
                )
                if len(_original_user_request) > 400:
                    _original_user_request = _original_user_request[:400] + "…"

                # Résultat list_folder_contents conservé entre les rounds pour
                # l'auto-création si Gemma répond en texte sans appeler create_file.
                _last_folder_listing = None
                _text_response_retry_done = False
                _create_file_done = False  # True dès que create_file a été exécuté
                _read_file_done = False    # True dès que read_file_content a été exécuté
                _turn_events = []          # Événements d'outils du tour courant (pour export)

                # ── Boucle agentique (max 6 tours d'outils) ─────────────────────
                for _tool_round in range(12):
                    # Streaming avec thinking natif Ollama et capture des tool_calls
                    _streamed = ""
                    _thinking = ""
                    _stream_tool_calls = []
                    _text_parsed_tools = False  # True si tool_calls viennent du parseur texte
                    thinking_ctrl = None
                    _dbg(f"ROUND_{_tool_round}_START_messages_count={len(messages)}", messages)
                    _stream_token_count = 0
                    _STREAM_UPDATE_EVERY = 5

                    async def _scroll_and_update():
                        try:
                            page.update()
                            await asyncio.sleep(0)
                            await ai_chat_view.scroll_to(offset=-1)
                        except Exception:
                            pass

                    for _evt, _dat in (
                        _gemini_chat_stream_with_tools(
                            active_model, messages,
                            tools=_ALL_TOOLS,
                            temperature=CONSTANTS.AI_TEMPERATURE,
                        )
                        if (active_model or "").startswith("gemini") else
                        _ollama_chat_stream_with_tools(
                            CONSTANTS.AI_OLLAMA_URL, active_model, messages,
                            tools=_ALL_TOOLS,
                            temperature=CONSTANTS.AI_TEMPERATURE,
                        )
                    ):
                        if _evt == "tool_calls":
                            _stream_tool_calls.extend(_dat)
                        elif _evt == "thinking":
                            _thinking += _dat
                            if thinking_ctrl is None:
                                _remove_loading()
                                thinking_ctrl = _ai_add_bubble("think", _dat)
                            else:
                                thinking_ctrl.value = f"💭 {_thinking}"
                                page.run_task(_scroll_and_update)
                        else:  # "token"
                            _streamed += _dat
                            _stream_token_count += 1
                            if response_text_ctrl is None:
                                _remove_loading()
                                response_text_ctrl = _ai_add_bubble("assistant", _dat)
                            elif _stream_token_count % _STREAM_UPDATE_EVERY == 0:
                                response_text_ctrl.value = _md_dark(_streamed)
                                page.run_task(_scroll_and_update)

                    tool_calls = _stream_tool_calls
                    _dbg(f"ROUND_{_tool_round}_AFTER_STREAM", {
                        "_streamed_raw": _streamed,
                        "_stream_tool_calls_native": _stream_tool_calls,
                    })
                    if not _streamed and not _stream_tool_calls:
                        if not (active_model or "").startswith("gemini"):
                            _fallback = _ollama_chat_once(
                                CONSTANTS.AI_OLLAMA_URL, active_model, messages,
                                tools=_ALL_TOOLS,
                                temperature=CONSTANTS.AI_TEMPERATURE,
                            )
                            tool_calls = _fallback.get("tool_calls") or []
                            _streamed = _fallback.get("content", "")
                            _thinking = _fallback.get("thinking", "")
                    if not tool_calls:
                        text_calls = _parse_text_tool_calls(_streamed)
                        if text_calls:
                            tool_calls = text_calls
                            _text_parsed_tools = True
                            _streamed_for_history = _streamed  # Garder <tool_code> pour l'historique Gemma
                            _streamed = _strip_text_tool_calls(_streamed)
                    _dbg(f"ROUND_{_tool_round}_AFTER_PARSE", {
                        "_text_parsed_tools": _text_parsed_tools,
                        "tool_calls": tool_calls,
                        "_streamed_after_strip": _streamed[:600] if _streamed else "",
                    })

                    if not tool_calls:
                        full_response = _strip_text_tool_calls(_streamed)
                        # Fallback XML <think> si pas de thinking natif (modèles non supportés)
                        if not _thinking and "<think>" in full_response:
                            _think_match = re.search(r'<think>(.*?)</think>', full_response, re.DOTALL)
                            if _think_match:
                                _thinking = _think_match.group(1).strip()
                                full_response = re.sub(r'<think>.*?</think>', '', full_response, flags=re.DOTALL).strip()
                                if response_text_ctrl is not None:
                                    response_text_ctrl.value = _md_dark(full_response)
                                    try:
                                        page.update()
                                    except Exception:
                                        pass
                        if _thinking and thinking_ctrl is None:
                            _ai_add_bubble("think", _thinking)
                        if response_text_ctrl is not None and full_response:
                            response_text_ctrl.value = _md_dark(full_response)
                            try:
                                page.update()
                            except Exception:
                                pass
                        elif full_response:
                            _remove_loading()
                            response_text_ctrl = _ai_add_bubble("assistant", full_response)
                        break

                    # Tour d'outils — finaliser le texte préliminaire streamé si présent
                    if response_text_ctrl is not None:
                        if _streamed:
                            response_text_ctrl.value = _md_dark(_streamed)
                            try:
                                page.update()
                            except Exception:
                                pass
                        response_text_ctrl = None

                    # ── Exécuter les appels d'outils ──────────────────────────────
                    if _text_parsed_tools:
                        # Gemma : conserver le <tool_code> dans l'assistant message pour que
                        # Gemma reconnaisse sa propre syntaxe et continue d'appeler des outils.
                        messages.append({"role": "assistant", "content": _streamed_for_history})
                    else:
                        # Modèle avec tool_calls natifs : content vide pour éviter HTTP 500.
                        messages.append({"role": "assistant", "content": "", "tool_calls": tool_calls})
                    # Afficher tous les indicateurs, collecter les tâches
                    _tool_tasks = []
                    _folder_tool_results = []  # traités séquentiellement avant le pool
                    for tc in tool_calls:
                        fn      = tc.get("function", {})
                        fn_name = fn.get("name", "")
                        fn_args = fn.get("arguments") or {}
                        if fn_name == "web_search":
                            query   = fn_args.get("query", "")
                            short_q = (query[:45] + "…") if len(query) > 45 else query
                            ai_status_text.value = f"🔍 {short_q}"
                            if loading_ctrl is not None:
                                loading_ctrl.value = f"🔍 {short_q}"
                            _ai_add_bubble("assistant", f"🔍 Recherche : {query}")
                            _turn_events.append(f"🔍 Recherche : {query}")
                            _tool_tasks.append((fn_name, fn_args))
                        elif fn_name == "fetch_url":
                            url     = fn_args.get("url", "")
                            short_u = (url[:45] + "…") if len(url) > 45 else url
                            ai_status_text.value = f"🌐 {short_u}"
                            if loading_ctrl is not None:
                                loading_ctrl.value = f"🌐 {short_u}"
                            _ai_add_bubble("assistant", f"🌐 Lecture : {url}")
                            _turn_events.append(f"🌐 Lecture : {url}")
                            _tool_tasks.append((fn_name, fn_args))
                        elif fn_name == "list_folder_contents":
                            _folder_display = os.path.basename(_folder_path_for_tools) if _folder_path_for_tools else "?"
                            ai_status_text.value = "📂 Lecture du dossier…"
                            _ai_add_bubble("assistant", f"📂 Lecture du dossier « {_folder_display} »")
                            _turn_events.append(f"📂 Lecture du dossier « {_folder_display} »")
                            try:
                                page.update()
                            except Exception:
                                pass
                            _folder_tool_results.append((fn_name, _folder_list_contents(_folder_path_for_tools)))
                        elif fn_name == "read_file_content":
                            _read_filename = fn_args.get("filename", "")
                            ai_status_text.value = f"📄 Lecture : {_read_filename}…"
                            _ai_add_bubble("assistant", f"📄 Lecture : {_read_filename}")
                            _turn_events.append(f"📄 Lecture : {_read_filename}")
                            try:
                                page.update()
                            except Exception:
                                pass
                            _folder_tool_results.append((fn_name, _folder_read_file(
                                _folder_path_for_tools, _read_filename,
                                document_exts=CONSTANTS.AI_DOCUMENT_EXTS,
                            )))
                            _read_file_done = True
                        elif fn_name == "organize_files":
                            _org_actions = fn_args.get("actions", [])
                            _org_summary = fn_args.get("summary", "")
                            if not _org_actions:
                                _folder_tool_results.append((fn_name, "Aucune action à exécuter."))
                            elif not _folder_path_for_tools:
                                _folder_tool_results.append((fn_name, "Aucun dossier ouvert."))
                            else:
                                _org_confirmed = True
                                if CONSTANTS.AI_ORGANIZE_CONFIRM:
                                    ai_status_text.value = "📂 Organisation — en attente de confirmation…"
                                    try:
                                        page.update()
                                    except Exception:
                                        pass
                                    _confirm_event  = threading.Event()
                                    _confirm_result = {"confirmed": False}

                                    def _on_org_confirm(event=None):
                                        _confirm_result["confirmed"] = True
                                        _organize_dlg.open = False
                                        page.update()
                                        _confirm_event.set()

                                    def _on_org_cancel(event=None):
                                        _organize_dlg.open = False
                                        page.update()
                                        _confirm_event.set()

                                    _action_rows = [
                                        ft.Text(
                                            f"• {_act.get('filename', '?')}  →  "
                                            f"{_act.get('destination_subfolder', '?')}/",
                                            size=12, color=WHITE,
                                        )
                                        for _act in _org_actions[:40]
                                    ]
                                    if len(_org_actions) > 40:
                                        _action_rows.append(
                                            ft.Text(f"… et {len(_org_actions) - 40} autres", size=12, color=LIGHT_GREY)
                                        )
                                    _organize_dlg = ft.AlertDialog(
                                        modal=True,
                                        title=ft.Text("📂 Organiser les fichiers"),
                                        content=ft.Column(
                                            [
                                                ft.Text(
                                                    _org_summary or "Organisation proposée par l'IA :",
                                                    size=13, color=WHITE,
                                                ),
                                                ft.Container(height=6),
                                                ft.Column(
                                                    _action_rows,
                                                    scroll=ft.ScrollMode.AUTO,
                                                    height=min(320, len(_action_rows) * 24),
                                                ),
                                            ],
                                            tight=True,
                                            width=500,
                                        ),
                                        actions=[
                                            ft.TextButton("Annuler", on_click=_on_org_cancel),
                                            ft.Button(
                                                "Exécuter",
                                                bgcolor=BLUE,
                                                color=WHITE,
                                                on_click=_on_org_confirm,
                                            ),
                                        ],
                                        actions_alignment=ft.MainAxisAlignment.END,
                                    )
                                    page.overlay.append(_organize_dlg)
                                    _organize_dlg.open = True
                                    try:
                                        page.update()
                                    except Exception:
                                        pass
                                    _confirm_event.wait(timeout=300)
                                    _org_confirmed = _confirm_result["confirmed"]
                                if not _org_confirmed:
                                    _folder_tool_results.append((fn_name, "Organisation annulée par l'utilisateur."))
                                else:
                                    _executed_moves = []
                                    _move_errors    = []
                                    for _org_action in _org_actions:
                                        _org_filename  = os.path.basename(_org_action.get("filename", ""))
                                        _org_subfolder = _org_action.get("destination_subfolder", "").strip("/\\")
                                        if not _org_filename or not _org_subfolder:
                                            continue
                                        _org_source   = os.path.join(_folder_path_for_tools, _org_filename)
                                        _org_dest_dir = os.path.join(_folder_path_for_tools, _org_subfolder)
                                        _org_dest     = os.path.join(_org_dest_dir, _org_filename)
                                        if not os.path.isfile(_org_source):
                                            _move_errors.append(f"Introuvable : {_org_filename}")
                                            continue
                                        try:
                                            os.makedirs(_org_dest_dir, exist_ok=True)
                                            shutil.move(_org_source, _org_dest)
                                            _executed_moves.append(f"✓ {_org_filename} → {_org_subfolder}/")
                                        except Exception as _move_exc:
                                            _move_errors.append(f"✗ {_org_filename} : {_move_exc}")
                                    page.pubsub.send_all_on_topic("refresh", None)
                                    _org_result_lines = [f"{len(_executed_moves)} fichier(s) déplacé(s)."] + _executed_moves
                                    if _move_errors:
                                        _org_result_lines += ["Erreurs :"] + _move_errors
                                    _folder_tool_results.append((fn_name, "\n".join(_org_result_lines)))
                        elif fn_name == "analyze_images":
                            _analyze_filenames = fn_args.get("filenames", [])
                            _analyze_question  = fn_args.get("question", "")
                            # Résoudre la liste d'images à analyser
                            if not _analyze_filenames:
                                _analyze_candidates = sorted([
                                    entry.name for entry in os.scandir(_folder_path_for_tools)
                                    if entry.is_file()
                                    and os.path.splitext(entry.name)[1].lower() in CONSTANTS.IMAGE_EXTS
                                ])
                            else:
                                _analyze_candidates = [
                                    os.path.basename(fname) for fname in _analyze_filenames
                                    if os.path.isfile(
                                        os.path.join(_folder_path_for_tools, os.path.basename(fname))
                                    )
                                ]
                            if not _analyze_candidates:
                                _folder_tool_results.append((fn_name, "Aucune image trouvée."))
                            else:
                                _analyze_total   = len(_analyze_candidates)
                                _analyze_model   = ai_model_dropdown.value or CONSTANTS.AI_MODEL_VISION
                                _analyze_batch_n = (
                                    CONSTANTS.AI_GEMINI_FOLDER_BATCH_SIZE
                                    if (_analyze_model or "").startswith("gemini")
                                    else CONSTANTS.AI_FOLDER_SELECT_BATCH_SIZE
                                )
                                _analyze_batches = (_analyze_total + _analyze_batch_n - 1) // _analyze_batch_n
                                _analysis_progress_ctrl = _ai_add_bubble(
                                    "assistant",
                                    f"📸 Analyse de {_analyze_total} image(s) — lot 1/{_analyze_batches}…",
                                )
                                _turn_events.append(f"📸 Analyse de {_analyze_total} image(s)")
                                def _on_analyze_progress(batch_num, total_batches):
                                    ai_status_text.value = f"📸 Analyse lot {batch_num}/{total_batches}…"
                                    if _analysis_progress_ctrl:
                                        _analysis_progress_ctrl.value = _md_dark(
                                            f"📸 Analyse — lot {batch_num}/{total_batches}…"
                                        )
                                    try:
                                        page.update()
                                    except Exception:
                                        pass
                                _analyze_results = _analyze_images_batched(
                                    CONSTANTS.AI_OLLAMA_URL,
                                    _analyze_model,
                                    _folder_path_for_tools,
                                    _analyze_candidates,
                                    _analyze_question,
                                    batch_size=_analyze_batch_n,
                                    image_exts=CONSTANTS.IMAGE_EXTS,
                                    max_size=CONSTANTS.AI_FOLDER_SELECT_IMAGE_SIZE,
                                    quality=CONSTANTS.AI_FOLDER_SELECT_QUALITY,
                                    on_progress=_on_analyze_progress,
                                    is_running=lambda: ai_streaming["value"],
                                )
                                if _analysis_progress_ctrl:
                                    _analysis_progress_ctrl.value = _md_dark(
                                        f"📸 {len(_analyze_candidates)} image(s) analysée(s)."
                                    )
                                try:
                                    page.update()
                                except Exception:
                                    pass
                                _folder_tool_results.append(
                                    (fn_name, "\n\n".join(_analyze_results) or "Aucun résultat.")
                                )
                        elif fn_name in ("generate_image", "edit_image"):
                            import datetime as _dt_gi
                            _gi_prompt     = fn_args.get("prompt", "")
                            _gi_aspect     = fn_args.get("aspect_ratio", "1:1")
                            _gi_resolution = fn_args.get("resolution", "1K")
                            # Fichier de sortie
                            if fn_name == "generate_image":
                                _gi_out_filename = (
                                    fn_args.get("filename", "").strip()
                                    or f"generated_{_dt_gi.datetime.now():%Y%m%d_%H%M%S}.png"
                                )
                                _gi_src_bytes = None
                                _gi_label = _gi_prompt[:60] + ("…" if len(_gi_prompt) > 60 else "")
                                _ai_add_bubble("assistant", f"🎨 Génération : {_gi_label}")
                                _turn_events.append(f"🎨 Génération : {_gi_label}")
                            else:  # edit_image
                                _gi_src_name = fn_args.get("source_filename", "").strip()
                                _gi_out_filename = (
                                    fn_args.get("output_filename", "").strip()
                                    or f"edited_{_dt_gi.datetime.now():%Y%m%d_%H%M%S}.png"
                                )
                                _gi_src_bytes = None
                                if _gi_src_name and _folder_path_for_tools:
                                    _gi_src_path = os.path.join(
                                        _folder_path_for_tools, os.path.basename(_gi_src_name)
                                    )
                                    if os.path.isfile(_gi_src_path):
                                        with open(_gi_src_path, "rb") as _f:
                                            _gi_src_bytes = _f.read()
                                _ai_add_bubble("assistant", f"🎨 Édition : {_gi_src_name} → {_gi_out_filename}")
                                _turn_events.append(f"🎨 Édition : {_gi_src_name} → {_gi_out_filename}")
                            ai_status_text.value = "🎨 Nano Banana 2 en cours…"
                            ai_progress_bar.visible = True
                            try:
                                page.update()
                            except Exception:
                                pass
                            _gi_text, _gi_bytes = _gemini_generate_image(
                                _gi_prompt,
                                input_image_bytes=_gi_src_bytes,
                                aspect_ratio=_gi_aspect,
                                resolution=_gi_resolution,
                            )
                            ai_progress_bar.visible = False
                            if _gi_bytes:
                                _gi_dest_folder = _folder_path_for_tools or os.path.join(app_directory, "Generated")
                                os.makedirs(_gi_dest_folder, exist_ok=True)
                                _gi_save_path = os.path.join(_gi_dest_folder, _gi_out_filename)
                                with open(_gi_save_path, "wb") as _fout:
                                    _fout.write(_gi_bytes)
                                _ai_add_image_bubble(_gi_save_path)
                                if _folder_path_for_tools:
                                    page.pubsub.send_all_on_topic("refresh", None)
                                _gi_result = f"Image sauvegardée : {_gi_save_path}"
                                if _gi_text:
                                    _gi_result = _gi_text + f"\n\nFichier : {_gi_save_path}"
                            else:
                                _gi_result = _gi_text or "[ERREUR] Aucune image générée."
                            _folder_tool_results.append((fn_name, _gi_result))
                        elif fn_name == "create_file":
                            import datetime as _dt_cf
                            _create_filename = fn_args.get("filename", "").strip()
                            if not _create_filename:
                                _create_filename = f"fichier_{_dt_cf.datetime.now():%Y%m%d_%H%M%S}.txt"
                            # Si un listage de dossier est disponible ET qu'on n'est pas
                            # dans un workflow d'édition (read_file_content déjà exécuté),
                            # utiliser les données réelles plutôt que le contenu généré par Gemma.
                            if _last_folder_listing and not _read_file_done:
                                _create_content = _last_folder_listing
                            else:
                                _create_content = _clean_file_content(fn_args.get("content", ""))
                            ai_status_text.value = f"📝 Création : {_create_filename}…"
                            _ai_add_bubble("assistant", f"📝 Création du fichier : {_create_filename}")
                            _turn_events.append(f"📝 Création du fichier : {_create_filename}")
                            try:
                                page.update()
                            except Exception:
                                pass
                            _create_result = _folder_create_file(
                                _folder_path_for_tools, _create_filename, _create_content
                            )
                            page.pubsub.send_all_on_topic("refresh", None)
                            _create_file_done = True
                            _folder_tool_results.append((fn_name, _create_result))
                        elif fn_name == "run_terminal_command":
                            _cmd      = fn_args.get("command", "")
                            _cmd_desc = fn_args.get("description", _cmd)
                            _cwd = _folder_path_for_tools if _folder_path_for_tools else None
                            if CONSTANTS.AI_TERMINAL_CONFIRM:
                                _cmd_confirm_event  = threading.Event()
                                _cmd_confirm_result = {"confirmed": False}

                                def _on_cmd_confirm(event=None):
                                    _cmd_confirm_result["confirmed"] = True
                                    _cmd_dlg.open = False
                                    page.update()
                                    _cmd_confirm_event.set()

                                def _on_cmd_cancel(event=None):
                                    _cmd_dlg.open = False
                                    page.update()
                                    _cmd_confirm_event.set()

                                _cmd_dlg = ft.AlertDialog(
                                    modal=True,
                                    title=ft.Text("💻 Exécuter une commande"),
                                    content=ft.Column(
                                        [
                                            ft.Text(_cmd_desc, size=13, color=WHITE),
                                            ft.Container(height=8),
                                            ft.Container(
                                                ft.Text(_cmd, size=12, font_family="monospace", color=YELLOW),
                                                bgcolor=DARK,
                                                padding=10,
                                                border_radius=6,
                                            ),
                                        ],
                                        tight=True,
                                        width=500,
                                    ),
                                    actions=[
                                        ft.TextButton("Annuler", on_click=_on_cmd_cancel),
                                        ft.Button(
                                            "Exécuter",
                                            bgcolor=BLUE,
                                            color=WHITE,
                                            on_click=_on_cmd_confirm,
                                        ),
                                    ],
                                    actions_alignment=ft.MainAxisAlignment.END,
                                )
                                page.overlay.append(_cmd_dlg)
                                _cmd_dlg.open = True
                                try:
                                    page.update()
                                except Exception:
                                    pass
                                _cmd_confirm_event.wait(timeout=300)
                                if not _cmd_confirm_result["confirmed"]:
                                    _folder_tool_results.append((fn_name, "Commande annulée par l'utilisateur."))
                                    continue
                            ai_status_text.value = "💻 Exécution en cours…"
                            _turn_events.append(f"💻 Commande : {_cmd}")
                            try:
                                page.update()
                            except Exception:
                                pass
                            _folder_tool_results.append(
                                (fn_name, _run_terminal_command(_cmd, cwd=_cwd))
                            )
                        elif fn_name == "update_memory_file":
                            _mem_target  = fn_args.get("target", "")
                            _mem_action  = fn_args.get("action", "")
                            _mem_content = fn_args.get("content", "")
                            _mem_old     = fn_args.get("old_text", "")
                            ai_status_text.value = f"🧠 Mise à jour mémoire ({_mem_target})…"
                            _turn_events.append(f"🧠 Mémoire : {_mem_action} → {_mem_target}")
                            try:
                                page.update()
                            except Exception:
                                pass
                            _folder_tool_results.append(
                                (fn_name, _update_memory_file(_mem_target, _mem_action, _mem_content, _mem_old))
                            )
                    try:
                        page.update()
                    except Exception:
                        pass
                    # ── Injecter les résultats d'outils dans l'historique ────────────────
                    # Exécuter les outils web/URL en parallèle
                    def _run_tool(task):
                        name, args = task
                        if name == "web_search":
                            return _web_search(args.get("query", ""))
                        elif name == "fetch_url":
                            return _fetch_url_content(args.get("url", ""), max_chars=CONSTANTS.AI_URL_MAX_CHARS)
                        return ""
                    with concurrent.futures.ThreadPoolExecutor() as _pool:
                        _web_tool_results = list(_pool.map(_run_tool, _tool_tasks))
                    _all_tool_results = _folder_tool_results + [
                        (_t_name, _result)
                        for (_t_name, _), _result in zip(_tool_tasks, _web_tool_results)
                    ]
                    # Mémoriser le dernier résultat list_folder_contents pour
                    # l'auto-création si Gemma refuse d'appeler create_file.
                    for _t_name, _t_result in _all_tool_results:
                        if _t_name == "list_folder_contents":
                            _last_folder_listing = _t_result
                    if _text_parsed_tools:
                        # Gemma ne supporte pas role="tool" — injecter les résultats
                        # comme message user pour éviter HTTP 500 au deuxième appel.
                        _results_lines = [f"[{_tn}]: {_tr}" for _tn, _tr in _all_tool_results]
                        _injected_msg = "Résultats des outils :\n" + "\n\n".join(_results_lines)
                        # Ajouter la directive pour que Gemma continue (et appelle l'outil suivant
                        # si nécessaire) au lieu de répondre en texte avec les données.
                        _create_file_just_done_tp = any(
                            name == "create_file" for name, _ in _all_tool_results
                        )
                        if _create_file_just_done_tp:
                            _injected_msg += (
                                "\n\nLe fichier a été créé avec succès. "
                                "La tâche est terminée — réponds à l'utilisateur "
                                "pour confirmer ce qui a été fait, sans appeler d'autres outils."
                            )
                        else:
                            _injected_msg += (
                                f"\n\nDemande à accomplir : \u00ab {_original_user_request} \u00bb\n"
                                "Les résultats des outils sont disponibles ci-dessus. "
                                "Si la tâche n'est pas encore terminée, appelle l'outil suivant "
                                "(ex. create_file si tu dois créer un fichier). "
                                "N'écris pas la réponse finale avant d'avoir utilisé tous les outils nécessaires."
                            )
                        messages.append({"role": "user", "content": _injected_msg})
                        _dbg(f"ROUND_{_tool_round}_RESULTS_INJECTED", {
                            "assistant_msg_appended": messages[-2],
                            "user_results_msg": _injected_msg[:1000],
                        })
                    else:
                        # Stratégie hybride pour Gemma 4 via Ollama :
                        # Round 0 → tool_responses dans le message assistant
                        #            (maintient Gemma en mode outil pour forcer le chaînage)
                        # Round 1+ → role:tool standard
                        #            (évite HTTP 500 causé par tool_responses multiples en historique)
                        if _tool_round == 0:
                            _last_assistant_idx = None
                            for _msg_idx in range(len(messages) - 1, -1, -1):
                                if messages[_msg_idx].get("role") == "assistant":
                                    _last_assistant_idx = _msg_idx
                                    break
                            if _last_assistant_idx is not None:
                                messages[_last_assistant_idx]["tool_responses"] = [
                                    {"name": _t_name, "response": _t_result}
                                    for _t_name, _t_result in _all_tool_results
                                ]
                        else:
                            # Rounds suivants : role:tool standard (évite HTTP 500)
                            for _t_name, _t_result in _all_tool_results:
                                messages.append({"role": "tool", "content": _t_result})
                        # Message user avec données réelles explicites + directive
                        # (garantit que Gemma voit les vraies données dans tous les cas)
                        _create_file_just_done = any(
                            name == "create_file" for name, _ in _all_tool_results
                        )
                        if _create_file_just_done:
                            messages.append({"role": "user", "content": (
                                "Le fichier a été créé avec succès. "
                                "La tâche est terminée — réponds à l'utilisateur "
                                "pour confirmer ce qui a été fait, sans appeler d'autres outils."
                            )})
                        else:
                            _results_lines = [f"[{_tn}]:\n{_tr}" for _tn, _tr in _all_tool_results]
                            messages.append({"role": "user", "content": (
                                "Résultats des outils :\n\n"
                                + "\n\n".join(_results_lines)
                                + f"\n\nDemande à accomplir : \u00ab {_original_user_request} \u00bb\n"
                                "Appelle maintenant l'outil suivant en utilisant EXACTEMENT "
                                "les données ci-dessus (ne pas les inventer ni les modifier). "
                                "Si la tâche est de créer un fichier, appelle create_file avec "
                                "le contenu recopié mot pour mot depuis les résultats."
                            )})
                    _remove_loading()

                if full_response:
                    _entry = {"role": "assistant", "content": full_response}
                    if _thinking:
                        _entry["thinking"] = _thinking
                    if _turn_events:
                        _entry["events"] = _turn_events
                    ai_conversation.append(_entry)
                    _ai_save_history()
                else:
                    if _turn_events:
                        ai_conversation.append({"role": "assistant", "content": "[Aucune réponse reçue]", "events": _turn_events})
                        _ai_save_history()
                    _ai_add_bubble("assistant", "[Aucune réponse reçue]")
            except Exception as exc:
                _ai_add_bubble("assistant", f"[ERREUR] {exc}")
                full_response = ""
            finally:
                ai_streaming["value"] = False
                ai_stop_button.icon_color = LIGHT_GREY
                ai_status_text.value = ""
                try:
                    page.update()
                except Exception:
                    pass
                if full_response and ai_tts_enabled["value"]:
                    threading.Thread(target=_speak_bubble, args=(full_response,), daemon=True).start()
                async def _refocus_after_response():
                    try:
                        await ai_input_field.focus()
                    except Exception:
                        pass
                page.run_task(_refocus_after_response)

        threading.Thread(target=_run, daemon=True).start()

    # ── Sélection IA du dossier ───────────────────────────────────────────────

    def _copy_to_selection_folder(folder_path, filenames):
        """
        Copie les fichiers dans un dossier SELECTION (SELECTION_2, … si déjà existant).
        Retourne (selection_dir, copied_count, errors).
        """
        selection_base = os.path.join(folder_path, "SELECTION")
        selection_dir  = selection_base
        counter = 2
        while os.path.exists(selection_dir):
            selection_dir = f"{selection_base}_{counter}"
            counter += 1
        os.makedirs(selection_dir, exist_ok=True)
        copied_count = 0
        errors = []
        for filename in filenames:
            source_path      = os.path.join(folder_path, filename)
            destination_path = os.path.join(selection_dir, filename)
            if not os.path.isfile(source_path):
                errors.append(f"Introuvable : {filename}")
                continue
            try:
                shutil.copy2(source_path, destination_path)
                copied_count += 1
            except Exception as copy_exc:
                errors.append(f"{filename} : {copy_exc}")
        return selection_dir, copied_count, errors

    def _ai_analyze_folder_for_selection():
        """Affiche la boîte de dialogue de critères et lance la sélection IA du dossier."""
        if ai_streaming["value"]:
            return
        folder_path = current_browse_folder["path"] or selected_folder["path"]
        if not folder_path or not os.path.isdir(folder_path):
            _ai_add_bubble("assistant", "⚠️ Aucun dossier sélectionné.")
            return

        criteria_field = ft.TextField(
            hint_text=(
                "Ex 1 : Mariage civil — reportage de 4h. Priorité aux portraits des mariés et aux "
                "interactions avec la famille. Sourires, regards complices, moments spontanés.\n"
                "Ex 2 : Reportage commandé par la commune — sélection générale des meilleurs moments, "
                "mais aussi et surtout les photos où les élus interagissent avec les citoyens."
            ),
            border_color=BLUE,
            color=WHITE,
            bgcolor=DARK,
            multiline=True,
            min_lines=3,
            max_lines=8,
            expand=True,
        )

        def _do_analyze(event=None):
            criteria_dlg.open = False
            page.update()
            criteria_text = criteria_field.value.strip()
            threading.Thread(
                target=_ai_folder_select_run,
                args=(folder_path, criteria_text),
                daemon=True,
            ).start()

        criteria_dlg = ft.AlertDialog(
            modal=True,
            title=ft.Text("✨ Sélection IA"),
            content=ft.Column([
                ft.Text(
                    f"Dossier : {os.path.basename(folder_path)}",
                    color=LIGHT_GREY, size=12,
                ),
                ft.Container(height=8),
                ft.Text("Contexte de l'événement et critères spécifiques :", size=13, color=WHITE),
                ft.Container(height=4),
                criteria_field,
                ft.Container(height=6),
                ft.Text(
                    "Les critères de qualité de base (flou, exposition, yeux fermés…) "
                    "sont appliqués automatiquement.",
                    color=LIGHT_GREY, size=11, italic=True,
                ),
            ], tight=True, width=520),
            actions=[
                ft.TextButton("Annuler", on_click=lambda e: (
                    setattr(criteria_dlg, "open", False) or page.update()
                )),
                ft.Button(
                    "Analyser",
                    bgcolor=BLUE,
                    color=WHITE,
                    on_click=_do_analyze,
                ),
            ],
            actions_alignment=ft.MainAxisAlignment.END,
        )
        page.overlay.append(criteria_dlg)
        criteria_dlg.open = True
        page.update()

        async def _focus_criteria():
            await asyncio.sleep(0.15)
            await criteria_field.focus()
        page.run_task(_focus_criteria)

    def _ai_folder_select_run(folder_path, criteria_text):
        """Thread : traite toutes les images par lots, mise à jour live de la bulle de progression."""
        ai_streaming["value"] = True
        ai_stop_button.icon_color = RED
        ai_status_text.value = "⏳ Sélection IA…"
        try:
            page.update()
        except Exception:
            pass

        try:
            # ── Collecter les images du dossier ───────────────────────────────
            image_extensions = CONSTANTS.IMAGE_EXTS
            all_images = sorted([
                entry.name for entry in os.scandir(folder_path)
                if entry.is_file()
                and os.path.splitext(entry.name)[1].lower() in image_extensions
            ])
            if not all_images:
                _ai_add_bubble(
                    "assistant",
                    f"⚠️ Aucune image trouvée dans « {os.path.basename(folder_path)} ».",
                )
                return

            active_model  = ai_model_dropdown.value or CONSTANTS.AI_MODEL_VISION
            batch_size    = (
                CONSTANTS.AI_GEMINI_FOLDER_BATCH_SIZE
                if (active_model or "").startswith("gemini")
                else CONSTANTS.AI_FOLDER_SELECT_BATCH_SIZE
            )
            total_images  = len(all_images)
            total_batches = (total_images + batch_size - 1) // batch_size

            criteria_display  = criteria_text or "(critères généraux)"
            user_bubble_text  = (
                f"✨ **Sélection IA** — {os.path.basename(folder_path)}\n"
                f"{criteria_display}\n\n"
                f"_{total_images} image(s) — {total_batches} lot(s) de {batch_size} max_"
            )
            _ai_add_bubble("user", user_bubble_text)
            ai_conversation.append({"role": "user", "content": user_bubble_text})

            # ── Bulle de progression live (mise à jour après chaque lot) ─────
            progress_lines = [
                f"**Analyse IA en cours** — {os.path.basename(folder_path)}",
                f"_{total_images} photo(s) / {total_batches} lot(s) de {batch_size} max_",
                "",
            ]
            progress_ctrl = _ai_add_bubble("assistant", "\n".join(progress_lines))
            # Entrée assistant dans ai_conversation — maintenue synchronisée par _refresh_progress
            ai_conversation.append({"role": "assistant", "content": ""})

            async def _async_update():
                try:
                    page.update()
                    await asyncio.sleep(0)
                except Exception:
                    pass

            def _refresh_progress():
                try:
                    content = "\n".join(progress_lines)
                    progress_ctrl.value = _md_dark(content)
                    # Garder ai_conversation synchronisé pour que l'export fonctionne
                    if ai_conversation and ai_conversation[-1].get("role") == "assistant":
                        ai_conversation[-1]["content"] = content
                    page.run_task(_async_update)
                except Exception:
                    pass

            # ── Définition de l'outil ─────────────────────────────────────────
            select_photos_tool = {
                "type": "function",
                "function": {
                    "name": "select_photos",
                    "description": (
                        "Sélectionne les meilleures photos du groupe courant. "
                        "Appelle cette fonction avec la liste des noms de fichiers retenus."
                    ),
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "selected_files": {
                                "type": "array",
                                "items": {"type": "string"},
                                "description": "Noms de fichiers JPG à conserver dans ce groupe",
                            },
                            "reason": {
                                "type": "string",
                                "description": "Justification concise des choix pour ce groupe",
                            },
                        },
                        "required": ["selected_files", "reason"],
                    },
                },
            }

            # ── System prompt : critères universels + contexte utilisateur ────
            system_content = CONSTANTS.AI_FOLDER_SELECT_SYSTEM_PROMPT
            if criteria_text:
                system_content += (
                    f"\n\nCONTEXTE ET CRITÈRES SPÉCIFIQUES DU REPORTAGE :\n{criteria_text}"
                )

            if not _ensure_ollama_ready(active_model):
                return

            # ── Boucle de lots ────────────────────────────────────────────────
            all_selected_files = []
            lot_errors         = []

            for batch_index, batch_start in enumerate(range(0, total_images, batch_size)):
                if not ai_streaming["value"]:
                    break

                batch_number = batch_index + 1
                batch_images = all_images[batch_start : batch_start + batch_size]
                batch_end    = batch_start + len(batch_images)

                # ── Encodage ──────────────────────────────────────────────────
                progress_lines.append(
                    f"⏳ **Lot {batch_number}/{total_batches}** — "
                    f"encodage (photos {batch_start + 1}–{batch_end} / {total_images})…"
                )
                ai_status_text.value = (
                    f"⏳ Lot {batch_number}/{total_batches} — "
                    f"encodage ({batch_start + 1}–{batch_end}/{total_images})…"
                )
                _refresh_progress()

                images_b64    = []
                encoded_names = []
                for filename in batch_images:
                    b64 = _encode_image_for_analysis(
                        os.path.join(folder_path, filename),
                        max_size=CONSTANTS.AI_FOLDER_SELECT_IMAGE_SIZE,
                        quality=CONSTANTS.AI_FOLDER_SELECT_QUALITY,
                    )
                    if b64:
                        images_b64.append(b64)
                        encoded_names.append(filename)

                if not images_b64:
                    progress_lines[-1] = (
                        f"⚠️ **Lot {batch_number}/{total_batches}** "
                        f"(photos {batch_start + 1}–{batch_end}) — aucune image encodable"
                    )
                    lot_errors.append(f"Lot {batch_number} : aucune image encodable")
                    progress_lines.append("")
                    _refresh_progress()
                    continue

                # ── Appel IA (streaming avec pensée en direct) ───────────────
                progress_lines[-1] = (
                    f"⏳ **Lot {batch_number}/{total_batches}** — "
                    f"analyse IA (photos {batch_start + 1}–{batch_end} / {total_images})…"
                )
                ai_status_text.value = (
                    f"⏳ Lot {batch_number}/{total_batches} — "
                    f"analyse IA ({batch_start + 1}–{batch_end}/{total_images})…"
                )
                status_line_idx   = len(progress_lines) - 1  # ligne de statut à remplacer par le résultat
                progress_lines.append("")                      # placeholder pour la pensée en direct
                live_thinking_idx = len(progress_lines) - 1
                _refresh_progress()

                user_prompt = (
                    f"Groupe {batch_number} sur {total_batches} "
                    f"(photos {batch_start + 1} à {batch_end} sur {total_images} au total).\n"
                    f"Fichiers de ce groupe : {', '.join(encoded_names)}.\n\n"
                    "Analyse chaque photo de ce groupe et appelle obligatoirement l'outil "
                    "select_photos avec les fichiers retenus et une justification brève."
                )
                messages = [
                    {"role": "system", "content": system_content},
                    {"role": "user",   "content": user_prompt, "images": images_b64},
                ]

                tool_calls    = []
                text_content  = ""
                thinking_text = ""
                token_counter = 0
                try:
                    for event_type, event_data in (
                        _gemini_chat_stream_with_tools(
                            active_model, messages,
                            tools=[select_photos_tool],
                            temperature=0.3,
                        )
                        if (active_model or "").startswith("gemini") else
                        _ollama_chat_stream_with_tools(
                            CONSTANTS.AI_OLLAMA_URL, active_model, messages,
                            tools=[select_photos_tool],
                            temperature=0.3,
                            timeout=600,
                        )
                    ):
                        if not ai_streaming["value"]:
                            break
                        if event_type == "thinking":
                            thinking_text += event_data
                            token_counter += 1
                            if token_counter % 15 == 0:
                                progress_lines[live_thinking_idx] = f"💭 {thinking_text}"
                                _refresh_progress()
                        elif event_type == "token":
                            text_content += event_data
                        elif event_type == "tool_calls":
                            tool_calls.extend(event_data)
                except Exception as call_exc:
                    progress_lines[status_line_idx] = (
                        f"❌ **Lot {batch_number}/{total_batches}** "
                        f"(photos {batch_start + 1}–{batch_end}) — erreur : {call_exc}"
                    )
                    progress_lines[live_thinking_idx] = ""
                    lot_errors.append(f"Lot {batch_number} : {call_exc}")
                    progress_lines.append("")
                    _refresh_progress()
                    continue

                thinking_text = thinking_text.strip()

                # Repli 1 : format texte Gemma natif
                if not tool_calls and text_content:
                    text_calls = _parse_text_tool_calls(text_content)
                    if text_calls:
                        tool_calls   = text_calls
                        text_content = _strip_text_tool_calls(text_content)

                # Repli 2 : liste JSON brute dans le texte
                if not tool_calls and text_content:
                    json_match = re.search(
                        r'\[\s*"[^"]*\.jpe?g"(?:\s*,\s*"[^"]*\.jpe?g")*\s*\]',
                        text_content, re.IGNORECASE,
                    )
                    if json_match:
                        try:
                            parsed_list = json.loads(json_match.group(0))
                            if isinstance(parsed_list, list):
                                tool_calls = [{
                                    "function": {
                                        "name": "select_photos",
                                        "arguments": {
                                            "selected_files": parsed_list,
                                            "reason": "(extrait du texte)",
                                        },
                                    }
                                }]
                        except Exception:
                            pass

                # Repli 3 : noms de fichiers mentionnés en prose libre
                # (tolérant jpg/jpeg — l'IA peut écrire .jpg pour un fichier .jpeg)
                if not tool_calls and text_content:
                    stem_to_actual = {}
                    for actual_name in encoded_names:
                        stem = re.sub(r'\.jpe?g$', '', actual_name, flags=re.IGNORECASE).lower()
                        stem_to_actual[stem] = actual_name
                    mentioned_stems = re.findall(r'\b([\w\-]+)\.jpe?g\b', text_content, re.IGNORECASE)
                    found_in_batch = []
                    seen_names = set()
                    for mentioned_stem in mentioned_stems:
                        actual_name = stem_to_actual.get(mentioned_stem.lower())
                        if actual_name and actual_name not in seen_names:
                            found_in_batch.append(actual_name)
                            seen_names.add(actual_name)
                    if found_in_batch:
                        tool_calls = [{
                            "function": {
                                "name": "select_photos",
                                "arguments": {
                                    "selected_files": found_in_batch,
                                    "reason": "(noms extraits du texte libre)",
                                },
                            }
                        }]

                # ── Extraire la sélection du lot ──────────────────────────────
                # Index stem → nom réel : tolère la confusion .jpg/.jpeg du modèle
                stem_to_encoded = {}
                for actual_name in encoded_names:
                    stem = re.sub(r'\.jpe?g$', '', actual_name, flags=re.IGNORECASE).lower()
                    stem_to_encoded[stem] = actual_name

                def _resolve_filename(file_name):
                    """Résout un nom de fichier (avec ou sans extension, .jpg ou .jpeg) vers le nom réel."""
                    if not isinstance(file_name, str):
                        return None
                    file_name = file_name.strip().strip('"\'() ')
                    if file_name in encoded_names:
                        return file_name
                    stem = re.sub(r'\.jpe?g$', '', file_name, flags=re.IGNORECASE).lower()
                    return stem_to_encoded.get(stem)

                def _extract_filenames_from_text(text):
                    """Extrait les noms de fichiers mentionnés dans un texte libre (avec extension)."""
                    found = []
                    seen = set()
                    for mentioned_stem in re.findall(r'\b([\w\-]+)\.jpe?g\b', text, re.IGNORECASE):
                        actual_name = stem_to_encoded.get(mentioned_stem.lower())
                        if actual_name and actual_name not in seen:
                            found.append(actual_name)
                            seen.add(actual_name)
                    return found

                batch_selected = []
                batch_reason   = ""
                for tool_call in tool_calls:
                    fn = tool_call.get("function", {})
                    if fn.get("name") != "select_photos":
                        continue
                    args = fn.get("arguments", {})
                    # Certains modèles retournent arguments comme chaîne JSON
                    if isinstance(args, str):
                        try:
                            args = json.loads(args)
                        except Exception:
                            args = {}
                    if not isinstance(args, dict):
                        args = {}
                    raw_files = args.get("selected_files", [])
                    # Certains modèles retournent selected_files comme chaîne séparée par des virgules
                    if isinstance(raw_files, str):
                        raw_files = [f for f in re.split(r'[,\n;]+', raw_files) if f.strip()]
                    resolved = []
                    seen_resolved = set()
                    for entry in raw_files:
                        # Certains modèles retournent une liste de dicts {"name": "..."}
                        if isinstance(entry, dict):
                            entry = entry.get("name") or entry.get("filename") or ""
                        actual_name = _resolve_filename(entry)
                        if actual_name and actual_name not in seen_resolved:
                            resolved.append(actual_name)
                            seen_resolved.add(actual_name)
                    batch_selected = resolved
                    batch_reason   = args.get("reason", "") or ""

                # Repli 4 : noms de fichiers dans le champ reason du tool call
                # (modèle a listé les fichiers dans reason plutôt que dans selected_files)
                if not batch_selected and batch_reason:
                    found_in_reason = _extract_filenames_from_text(batch_reason)
                    if found_in_reason:
                        batch_selected = found_in_reason

                # Repli 5 : stems sans extension dans le champ reason
                # (modèle a écrit "NZ6_0450" sans ".jpeg" dans la justification)
                if not batch_selected and batch_reason:
                    found_stems = []
                    seen_stems = set()
                    for stem_candidate in re.findall(r'\b([\w\-]+)\b', batch_reason):
                        actual_name = stem_to_encoded.get(stem_candidate.lower())
                        if actual_name and actual_name not in seen_stems:
                            found_stems.append(actual_name)
                            seen_stems.add(actual_name)
                    if found_stems:
                        batch_selected = found_stems

                # ── Mettre à jour la bulle avec le résultat du lot ────────────
                if batch_selected:
                    progress_lines[status_line_idx] = (
                        f"✅ **Lot {batch_number}/{total_batches}** "
                        f"(photos {batch_start + 1}–{batch_end} / {total_images})"
                    )
                    shown_files = batch_selected[:5]
                    suffix = (
                        f" _+{len(batch_selected) - 5} autres_"
                        if len(batch_selected) > 5 else ""
                    )
                    progress_lines.append(
                        "— `" + "` `".join(shown_files) + f"`{suffix}"
                    )
                else:
                    _claims_selection = bool(batch_reason) and any(
                        keyword in batch_reason.lower()
                        for keyword in ("sélectionné", "selectionné", "retenu", "choisi", "conservé", "gardé")
                    )
                    if _claims_selection:
                        progress_lines[status_line_idx] = (
                            f"⚠️ **Lot {batch_number}/{total_batches}** "
                            f"(photos {batch_start + 1}–{batch_end}) — "
                            f"_aucun fichier identifiable (le modèle a sélectionné sans nommer les fichiers)_"
                        )
                    else:
                        progress_lines[status_line_idx] = (
                            f"— **Lot {batch_number}/{total_batches}** "
                            f"(photos {batch_start + 1}–{batch_end}) — _aucune retenue_"
                        )

                if batch_reason:
                    progress_lines.append(f"— _{batch_reason[:200]}_")

                if batch_selected:
                    progress_lines.append(f"— **{len(batch_selected)} retenue(s)**")

                # Vider le placeholder de pensée live (déjà affiché en direct)
                progress_lines[live_thinking_idx] = ""

                progress_lines.append("")  # ligne vide entre les lots
                all_selected_files.extend(batch_selected)
                _refresh_progress()

            # ── Résumé final ──────────────────────────────────────────────────
            was_stopped = not ai_streaming["value"]

            if not all_selected_files:
                stop_note = " _(analyse interrompue)_" if was_stopped else ""
                progress_lines.append(f"ℹ️ **Aucune photo sélectionnée.**{stop_note}")
                _refresh_progress()
                return

            selection_dir, copied_count, copy_errors = _copy_to_selection_folder(
                folder_path, all_selected_files
            )
            selection_name = os.path.basename(selection_dir)

            progress_lines.append("---")
            progress_lines.append(
                f"### ✅ {copied_count} photo(s) sélectionnée(s) sur {total_images}"
            )
            progress_lines.append(f"Copiées dans `{selection_name}/`")
            if was_stopped:
                progress_lines.append("_⚠️ Analyse interrompue — sélection partielle._")
            if lot_errors:
                progress_lines.append(f"⚠️ Lots en erreur : {'; '.join(lot_errors)}")
            if copy_errors:
                progress_lines.append(f"❌ Erreurs de copie : {'; '.join(copy_errors[:5])}")
            progress_lines.append(f"📂 `{selection_dir}`")
            _refresh_progress()

            page.pubsub.send_all_on_topic("refresh", None)

        except Exception as exc:
            _ai_add_bubble("assistant", f"[ERREUR sélection IA] {exc}")
        finally:
            ai_streaming["value"] = False
            ai_stop_button.icon_color = LIGHT_GREY
            ai_status_text.value = ""
            try:
                page.update()
            except Exception:
                pass

    def _on_ai_submit():
        """Récupère le texte saisi, vide le champ et envoie le message à l'IA."""
        message_text = ai_input_field.value.strip()
        # Autoriser l'envoi sans texte si des images ou fichiers sont joints
        if not message_text and not ai_pending_images and not ai_pending_files:
            return
        ai_input_field.value = ""
        ai_input_field.update()

        async def _refocus_ai():
            try:
                await ai_input_field.focus()
            except Exception:
                pass
        page.run_task(_refocus_ai)
        _send_ai_message(message_text)

    def _toggle_tts():
        """Active ou désactive la lecture vocale des réponses IA."""
        ai_tts_enabled["value"] = not ai_tts_enabled["value"]
        enabled = ai_tts_enabled["value"]
        ai_speaker_button.icon = ft.Icons.VOLUME_UP if enabled else ft.Icons.VOLUME_OFF
        ai_speaker_button.icon_color = BLUE if enabled else LIGHT_GREY
        ai_speaker_button.tooltip = "Désactiver la lecture vocale" if enabled else "Activer la lecture vocale"
        try:
            ai_speaker_button.update()
        except Exception:
            pass

    def _on_voice_input():
        """Enregistre le micro, transcrit via Whisper et envoie le texte à l'IA."""
        if ai_streaming["value"]:
            return
        # Active le TTS automatiquement si pas encore activé
        if not ai_tts_enabled["value"]:
            _toggle_tts()
        ai_mic_button.icon_color = CONSTANTS.COLOR_RED
        ai_mic_button.disabled = True
        ai_status_text.value = f"🎙 Enregistrement ({CONSTANTS.AI_VOICE_RECORDING_SECONDS} s)…"
        try:
            ai_mic_button.update()
            ai_status_text.update()
        except Exception:
            pass

        def _record_and_submit():
            try:
                audio_data = _voice_record_audio(
                    duration_seconds=CONSTANTS.AI_VOICE_RECORDING_SECONDS,
                    sample_rate=CONSTANTS.AI_VOICE_SAMPLE_RATE,
                )
                ai_status_text.value = "🔄 Transcription…"
                try:
                    ai_status_text.update()
                except Exception:
                    pass
                transcribed_text = _voice_transcribe(
                    audio_data,
                    sample_rate=CONSTANTS.AI_VOICE_SAMPLE_RATE,
                    stt_model=CONSTANTS.AI_VOICE_STT_MODEL,
                )
                if transcribed_text:
                    ai_input_field.value = transcribed_text
                    try:
                        ai_input_field.update()
                    except Exception:
                        pass
                    _on_ai_submit()
                else:
                    ai_status_text.value = "Aucun son détecté."
                    try:
                        ai_status_text.update()
                    except Exception:
                        pass
            except Exception as voice_exc:
                _ai_add_bubble("assistant", f"[Erreur micro] {voice_exc}")
            finally:
                ai_mic_button.icon_color = CONSTANTS.COLOR_LIGHT_GREY
                ai_mic_button.disabled = False
                try:
                    ai_mic_button.update()
                except Exception:
                    pass

        threading.Thread(target=_record_and_submit, daemon=True).start()

    def switch_to_terminal_mode():
        """Sauvegarde les notes/quitte l'IA et revient au terminal."""
        if note_mode["value"]:
            save_notes()
        note_mode["value"] = False
        ai_mode["value"]   = False
        terminal_output.visible   = True
        terminal_cmd_row.visible  = True
        update_overlay_visibility()
        terminal_output.update()
        terminal_cmd_row.update()

        async def _focus_term():
            try:
                await terminal_cmd_input.focus()
            except Exception:
                pass
        page.run_task(_focus_term)



    def on_terminal_command_submit(e):
        """Exécute la commande saisie dans le terminal intégré."""
        command_text = terminal_cmd_input.value.strip()
        if not command_text:
            return

        # ── Commandes internes (slash-commands) ───────────────────────
        if command_text.lower() == "/option":
            terminal_cmd_input.value = ""
            terminal_cmd_input.update()
            switch_to_options()
            return

        if not command_history or command_history[0] != command_text:
            command_history.insert(0, command_text)
        history_index["value"] = -1
        history_draft["value"] = ""
        terminal_cmd_input.value = ""
        terminal_cmd_input.update()

        async def _refocus():
            try:
                await terminal_cmd_input.focus()
            except Exception:
                pass

        page.run_task(_refocus)

        # Capturer le cwd maintenant, avant le lancement du thread,
        # pour éviter qu'une navigation simultanée ne le modifie.
        cwd = current_browse_folder["path"] or selected_folder.get("path") or app_directory
        log_to_terminal(f"> {command_text}", YELLOW)

        def _run():
            try:
                system = platform.system()
                if system == "Windows":
                    # PowerShell est plus capable que cmd.exe (ls, cat, pipeline…)
                    popen_kwargs = dict(
                        args=["powershell", "-NoProfile", "-NonInteractive", "-Command", command_text],
                        shell=False,
                    )
                else:
                    # zsh avec fallback bash si zsh n'est pas installé
                    shell_exe = "/bin/zsh" if os.path.exists("/bin/zsh") else "/bin/bash"
                    popen_kwargs = dict(
                        args=command_text,
                        shell=True,
                        executable=shell_exe,
                    )
                proc = subprocess.Popen(
                    **popen_kwargs,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.STDOUT,
                    text=True,
                    encoding="utf-8",
                    errors="replace",
                    cwd=cwd,
                )
                killed_by_timeout = [False]

                def _kill_on_timeout():
                    if proc.poll() is None:
                        killed_by_timeout[0] = True
                        proc.kill()
                        log_to_terminal("[ERREUR] Commande interrompue (délai dépassé 30s)", RED)

                watchdog = threading.Timer(30.0, _kill_on_timeout)
                watchdog.daemon = True
                watchdog.start()
                try:
                    had_output = False
                    for line in iter(proc.stdout.readline, ""):
                        stripped = line.rstrip()
                        if stripped:
                            log_to_terminal(stripped)
                            had_output = True
                    proc.wait()
                    if not killed_by_timeout[0]:
                        if proc.returncode != 0:
                            log_to_terminal(f"[code retour {proc.returncode}]", RED)
                        elif not had_output:
                            log_to_terminal("[aucun résultat]", LIGHT_GREY)
                finally:
                    watchdog.cancel()
            except FileNotFoundError:
                log_to_terminal(f"[ERREUR] Dossier introuvable : {cwd}", RED)
            except Exception as error:
                log_to_terminal(f"[ERREUR] {error}", RED)

        threading.Thread(target=_run, daemon=True).start()



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
                        ft.Text(os.path.basename(recent_path) or recent_path),
                    ], spacing=8, tight=True),
                    on_click=lambda e, folder=recent_path: navigate_to_folder(folder),
                )
                for recent_path in recent
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
            return [program for program in data if isinstance(program, dict) and "label" in program and "exe" in program]
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
            display_names = ", ".join(os.path.basename(file_path) for file_path in files[:3])
            overflow_suffix = f" (+{len(files) - 3})" if len(files) > 3 else ""
            log_to_terminal(f"[OK] Ouvert avec {prog['label']}: {display_names}{overflow_suffix}", GREEN)
            return True
        except Exception as err:
            log_to_terminal(f"[ERREUR] {prog['label']}: {err}", RED)
            return False



    def _save_open_with_programs(programs: list):
        """Sauvegarde la liste des programmes dans open_with.json."""
        try:
            with open(open_with_config_file_path, "w", encoding="utf-8") as f:
                json.dump(programs, f, ensure_ascii=False, indent=2)
        except Exception as err:
            log_to_terminal(f"[ERREUR] Sauvegarde open_with.json : {err}", RED)



    _ROTATABLE_EXTS = CONSTANTS.ROTATABLE_EXTS



    def _zip_selection(items: list, zip_name: str):
        """Zippe la liste de fichiers et/ou dossiers dans le dossier courant sous zip_name."""
        if not items:
            return
        folder = os.path.dirname(items[0])
        base = zip_name if zip_name else "selection"
        if not base.lower().endswith(".zip"):
            base += ".zip"
        candidate = os.path.join(folder, base)
        archive_stem, archive_ext = os.path.splitext(candidate)
        name_counter = 1
        while os.path.exists(candidate):
            candidate = f"{archive_stem}_{name_counter}{archive_ext}"
            name_counter += 1
        try:
            with zipfile.ZipFile(candidate, "w", zipfile.ZIP_DEFLATED) as zip_archive:
                for item_path in items:
                    if os.path.isdir(item_path):
                        dir_name = os.path.basename(item_path)
                        for root, _dirs, files in os.walk(item_path):
                            for file_name in files:
                                full_path = os.path.join(root, file_name)
                                arcname = os.path.join(dir_name, os.path.relpath(full_path, item_path))
                                zip_archive.write(full_path, arcname=arcname)
                    else:
                        zip_archive.write(item_path, arcname=os.path.basename(item_path))
            log_to_terminal(f"[OK] Archive créée : {os.path.basename(candidate)}", YELLOW)
            refresh_preview()
        except Exception as ex:
            log_to_terminal(f"[ERREUR] Zip : {ex}", RED)



    def _prompt_and_zip_selection(e):
        """Affiche le dialog de nom puis zippe les éléments sélectionnés (fichiers et dossiers)."""
        items = list(selected_files)
        if not items:
            log_to_terminal("[ATTENTION] Aucun élément sélectionné à zipper", ORANGE)
            return
        default_name = ""
        if len(items) == 1 and os.path.isdir(items[0]):
            default_name = os.path.basename(items[0])
        zip_name_input = ft.TextField(
            label="Nom de l'archive",
            hint_text="Ex: selection",
            value=default_name,
            autofocus=True,
            width=320,
            bgcolor=DARK,
            border_color=GREY,
        )



        def _on_confirm_zip(ev):
            name = (zip_name_input.value or "").strip() or default_name or "selection"
            zip_dlg.open = False
            page.update()
            log_to_terminal(f"[ZIP] Création de {name}.zip en cours…", YELLOW)
            threading.Thread(target=_zip_selection, args=(items, name), daemon=True).start()

        def _on_cancel_zip(ev):
            zip_dlg.open = False
            page.update()

        zip_name_input.on_submit = _on_confirm_zip
        zip_dlg = ft.AlertDialog(
            modal=True,
            title=ft.Text("Nom de l'archive ZIP"),
            content=zip_name_input,
            actions=[
                ft.TextButton("Annuler", on_click=_on_cancel_zip),
                ft.TextButton("OK", on_click=_on_confirm_zip),
            ],
            actions_alignment=ft.MainAxisAlignment.END,
        )
        page.overlay.append(zip_dlg)
        zip_dlg.open = True
        page.update()



    def _rotate_files(files, direction, clear_sel=False):
        """Pivote les images de 90° à gauche ou à droite en utilisant Pillow."""
        if _PILImage is None:
            log_to_terminal("[ERREUR] Pillow non installé — rotation impossible", RED)
            return
        rotated = 0
        timestamp = str(int(time.time() * 1000))
        for file_path in files:
            ext = os.path.splitext(file_path)[1].lower()
            if ext not in _ROTATABLE_EXTS:
                continue
            try:
                with _PILImage.open(file_path) as img:
                    img_converted = img.copy()
                    if direction == "left":
                        result = img_converted.rotate(90, expand=True)
                    else:
                        result = img_converted.rotate(-90, expand=True)
                    save_kwargs = {}
                    image_format = "JPEG" if ext in (".jpg", ".jpeg") else "PNG"
                    if image_format == "JPEG":
                        save_kwargs["quality"] = 95
                        save_kwargs["subsampling"] = 0
                    # Sauvegarder le fichier original
                    result.save(file_path, **save_kwargs)
                    # Mettre à jour le cache base64 pour bypasser l'ancienne miniature
                    normalized_path = os.path.normpath(file_path)
                    _thumb_cache.pop(normalized_path, None)
                    new_b64 = thumb_cache.get_or_generate(file_path)
                    if new_b64:
                        _image_cache_busters[normalized_path] = new_b64
                        _thumb_cache[normalized_path] = new_b64
                    try:
                        _image_last_mtime[normalized_path] = os.stat(file_path).st_mtime
                    except OSError:
                        pass
                rotated += 1
            except Exception as ex:
                log_to_terminal(f"[ERREUR] Rotation {os.path.basename(file_path)}: {ex}", RED)
        if rotated:
            label = "gauche" if direction == "left" else "droite"
            log_to_terminal(f"[OK] {rotated} image(s) pivotée(s) vers {label}", YELLOW)
            if clear_sel:
                selected_files.clear()
                _update_select_toggle_button()
            refresh_preview(reset_page=False, force_reload=True)



    def _show_file_context_menu(files: list):
        """Menu contextuel clic-droit : rotation + liste Ouvrir avec intégrée."""
        image_files = [f for f in files if os.path.splitext(f)[1].lower() in _ROTATABLE_EXTS]
        has_images = bool(image_files)
        doc_audio_files = [
            f for f in files
            if os.path.splitext(f)[1].lower() in (_AI_DOCUMENT_EXTS | _AI_AUDIO_EXTS)
        ]
        has_doc_audio = bool(doc_audio_files)

        header_label = (
            os.path.basename(files[0]) if len(files) == 1
            else f"{len(files)} fichier(s) sélectionné(s)"
        )

        # ── Formulaire d'ajout de programme ──────────────────────────────
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
            icon=ft.Icons.FOLDER_OPEN, icon_color=BLUE, icon_size=20,
            tooltip="Parcourir…", on_click=_browse_exe,
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
            ], spacing=8, tight=True, vertical_alignment=ft.CrossAxisAlignment.CENTER),
            content_padding=ft.Padding(12, 0, 12, 8),
        )



        def _close(e=None):
            dlg.open = False
            page.update()



        def _do_rotate(direction):
            _close()
            threading.Thread(target=_rotate_files, args=(image_files, direction, True), daemon=True).start()



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
                for program_index, prog in enumerate(programs):
                    def _create_open_handler(program):
                        def _open_with_clicked(e):
                            if platform.system() == "Windows":
                                try:
                                    import ctypes
                                    hwnd = ctypes.windll.user32.GetForegroundWindow()
                                    if hwnd:
                                        ctypes.windll.user32.ShowWindow(hwnd, 6)  # SW_MINIMIZE
                                except Exception:
                                    pass
                            _close()
                            if _open_files_with(program, files):
                                clear_selection(None)
                        return _open_with_clicked
                    def _create_delete_handler(program):
                        def _delete_program_clicked(e):
                            current_programs = _load_open_with_programs()
                            current_programs = [entry for entry in current_programs if entry != program]
                            _save_open_with_programs(current_programs)
                            _rebuild_items()
                            programs_list_view.update()
                        return _delete_program_clicked
                    programs_list_view.controls.append(ft.ListTile(
                        key=str(program_index),
                        leading=ft.ReorderableDragHandle(
                            content=ft.Icon(ft.Icons.DRAG_HANDLE, color=LIGHT_GREY, size=18),
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
            progs = _load_open_with_programs()
            progs.append({"label": label, "exe": exe})
            _save_open_with_programs(progs)
            add_form.visible = False
            add_program_button.visible = False
            _rebuild_items()
            page.update()

        # ── Assemblage du contenu ─────────────────────────────────────────
        content_rows = []
        if has_images:
            def _send_images_to_ai(e=None):
                _close()
                for image_path in image_files:
                    _ai_attach_image(image_path)
                switch_to_ai_mode()
                clear_selection(None)

            def _show_exif_data(e=None):
                _close()
                exif_path = image_files[0]
                rows = []
                try:
                    if _PILImage is None:
                        raise ImportError("PIL non disponible")
                    from PIL.ExifTags import TAGS
                    with _PILImage.open(exif_path) as img:
                        width, height = img.size
                        raw = img.getexif()
                    rows.append(
                        ft.Text(f"Résolution : {width} × {height} px", size=12, color=BLUE, selectable=True)
                    )
                    if raw:
                        for tag_id, value in raw.items():
                            tag_name = TAGS.get(tag_id, f"Tag {tag_id}")
                            if isinstance(value, bytes):
                                continue
                            rows.append(
                                ft.Text(f"{tag_name}: {value}", size=12, color=WHITE, selectable=True)
                            )
                    else:
                        rows.append(ft.Text("Aucune donnée EXIF.", size=12, color=LIGHT_GREY))
                except Exception as ex:
                    rows.append(ft.Text(f"Erreur : {ex}", size=12, color=RED))

                exif_dlg = ft.AlertDialog(
                    title=ft.Text(os.path.basename(exif_path), size=13, color=LIGHT_GREY),
                    content=ft.Column(
                        rows, spacing=2,
                        scroll=ft.ScrollMode.AUTO,
                        width=400, height=400,
                    ),
                )

                def _close_exif(e=None):
                    exif_dlg.open = False
                    page.update()

                exif_dlg.actions = [ft.TextButton("Fermer", on_click=_close_exif)]
                exif_dlg.actions_alignment = ft.MainAxisAlignment.END
                page.overlay.append(exif_dlg)
                exif_dlg.open = True
                page.update()

            icon_btns = [
                ft.IconButton(
                    icon=ft.Icons.SMART_TOY, icon_color=BLUE, icon_size=22,
                    tooltip=f"Envoyer à l'IA ({len(image_files)} image{'s' if len(image_files) > 1 else ''})",
                    on_click=_send_images_to_ai,
                ),
                ft.IconButton(
                    icon=ft.Icons.ROTATE_LEFT, icon_color=HOVER_YELLOW, icon_size=22,
                    tooltip="Rotation gauche (−90°)",
                    on_click=lambda e: _do_rotate("left"),
                ),
                ft.IconButton(
                    icon=ft.Icons.ROTATE_RIGHT, icon_color=YELLOW, icon_size=22,
                    tooltip="Rotation droite (+90°)",
                    on_click=lambda e: _do_rotate("right"),
                ),
            ]
            if len(image_files) == 1:
                icon_btns.append(ft.IconButton(
                    icon=ft.Icons.INFO_OUTLINE, icon_color=LIGHT_GREY, icon_size=22,
                    tooltip="Voir les EXIF",
                    on_click=_show_exif_data,
                ))
            content_rows.append(ft.Row(icon_btns, spacing=0, alignment=ft.MainAxisAlignment.CENTER))
            content_rows.append(ft.Divider(height=8, color=GREY))
        if has_doc_audio:
            def _send_docs_to_ai(e=None):
                _close()
                for doc_path in doc_audio_files:
                    _ai_attach_document_file(doc_path)
                switch_to_ai_mode()
                clear_selection(None)

            doc_label = (
                f"{len(doc_audio_files)} fichier{'s' if len(doc_audio_files) > 1 else ''}"
            )
            content_rows.append(ft.Row([
                ft.IconButton(
                    icon=ft.Icons.SMART_TOY, icon_color=VIOLET, icon_size=22,
                    tooltip=f"Envoyer à l'IA ({doc_label})",
                    on_click=_send_docs_to_ai,
                ),
            ], spacing=0, tight=True))
            content_rows.append(ft.Divider(height=8, color=GREY))
        content_rows.append(programs_list_view)
        content_rows.append(add_form)

        dlg.content = ft.Column(content_rows, spacing=0, tight=True, width=340)

        add_program_button = ft.TextButton("Ajouter", on_click=_confirm_add, visible=False)
        dlg.actions = [add_program_button, ft.TextButton("Fermer", on_click=_close)]
        dlg.actions_alignment = ft.MainAxisAlignment.END

        _rebuild_items()
        page.overlay.append(dlg)
        dlg.open = True
        page.update()



    def navigate_to_folder(new_path):
        """Navigue vers un dossier dans la preview"""
        if not new_path:
            return
        new_path = _resolve_favorite_path(new_path)
        current_browse_folder["path"] = new_path
        selected_folder["path"] = new_path
        folder_path.value = new_path
        selected_files.clear()
        selection_count_text.value = ""
        search_query["value"] = ""
        search_field.value = ""
        if show_only_selection["value"]:
            show_only_selection["value"] = False
            _update_filter_sel_btn()
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
            if CONSTANTS.DELETE_ZIP_AFTER_EXTRACT:
                try:
                    os.remove(file_path)
                    log_to_terminal(f"[OK] ZIP supprimé: {os.path.basename(file_path)}", GREEN)
                except Exception as _ze:
                    log_to_terminal(f"[ERREUR] Suppression ZIP: {_ze}", RED)
                refresh_preview()
            else:
                def _confirm_del_zip(ev):
                    dlg_del_zip.open = False
                    page.update()
                    try:
                        os.remove(file_path)
                        log_to_terminal(f"[OK] ZIP supprimé: {os.path.basename(file_path)}", GREEN)
                        refresh_preview()
                    except Exception as _ze:
                        log_to_terminal(f"[ERREUR] Suppression ZIP: {_ze}", RED)
                def _cancel_del_zip(ev):
                    dlg_del_zip.open = False
                    page.update()
                dlg_del_zip = ft.AlertDialog(
                    title=ft.Text("Supprimer le fichier ZIP ?"),
                    content=ft.Text(f"Voulez-vous supprimer '{os.path.basename(file_path)}' ?"),
                    actions=[
                        ft.TextButton("Conserver", on_click=_cancel_del_zip),
                        ft.TextButton("Supprimer", on_click=_confirm_del_zip,
                                      style=ft.ButtonStyle(color=ft.Colors.RED)),
                    ],
                )
                page.overlay.append(dlg_del_zip)
                dlg_del_zip.open = True
                page.update()
                refresh_preview()
        except Exception as err:
            log_to_terminal(f"[ERREUR] Décompression: {err}", RED)



    def open_image_viewer(start_path):
        """Affiche un lecteur d'image avec PageView swipeable (support écran tactile)."""
        _blank_gif = "data:image/gif;base64,R0lGODlhAQABAAD/ACwAAAAAAQABAAACADs="

        entries = all_entries_data["list"]
        image_paths = [entry_path for (_, entry_path, is_directory, is_image_file, _ext) in entries if is_image_file and not is_directory]
        if not image_paths:
            image_paths = [start_path]
        try:
            initial_index = image_paths.index(start_path)
        except ValueError:
            initial_index = 0
            image_paths = [start_path]

        state = {"index": initial_index}
        previous_keyboard_handler = page.on_keyboard_event

        def _current_path() -> str:
            return image_paths[state["index"]] if image_paths else ""



        # ── Helpers ──────────────────────────────────────────────────────
        def _get_resolution(path):
            if _PILImage:
                try:
                    with _PILImage.open(path) as opened_image:
                        return f"{opened_image.width} × {opened_image.height}"
                except Exception:
                    pass
            return ""



        # ── Contrôles barre titre ─────────────────────────────────────────
        filename_text = ft.Text(
            os.path.basename(_current_path()),
            size=13,
            color=ft.Colors.WHITE,
            weight=ft.FontWeight.W_500,
            max_lines=1,
            overflow=ft.TextOverflow.ELLIPSIS,
        )
        counter_text = ft.Text(
            f"{state['index'] + 1} / {len(image_paths)}",
            size=12,
            color=ft.Colors.WHITE70,
        )
        resolution_text = ft.Text(
            "",
            size=12,
            color=ft.Colors.WHITE54,
        )
        viewer_checkbox = ft.Checkbox(
            value=_current_path() in selected_files,
            on_change=lambda e: on_checkbox_change(e, _current_path()),
        )



        # ── Chargement lazy des images ────────────────────────────────────
        page_image_controls: dict = {}
        pages_loaded: set = set()

        def _build_page_containers():
            containers = []
            win_w = page.window.width or 1280
            win_h = page.window.height or 800
            for idx in range(len(image_paths)):
                img_ctrl = ft.Image(
                    src=_blank_gif,
                    width=win_w,
                    height=win_h,
                    fit=ft.BoxFit.CONTAIN,
                    gapless_playback=True,
                    error_content=ft.Container(
                        content=ft.Icon(ft.Icons.BROKEN_IMAGE, color=ft.Colors.WHITE54, size=64),
                        alignment=ft.Alignment(0, 0),
                    ),
                )
                page_image_controls[idx] = img_ctrl
                # InteractiveViewer à l'intérieur de chaque page :
                # - Pinch-to-zoom / molette souris pour zoomer
                # - Swipe horizontal disponible quand zoom = 1× (PageView reprend la main)
                # - Pan disponible quand zoom > 1×
                viewer = ft.InteractiveViewer(
                    key=f"iv_{idx}",
                    content=img_ctrl,
                    min_scale=0.5,
                    max_scale=10.0,
                    pan_enabled=True,
                    scale_enabled=True,
                    width=win_w,
                    height=win_h,
                    clip_behavior=ft.ClipBehavior.HARD_EDGE,
                )
                containers.append(
                    ft.Container(
                        content=viewer,
                        expand=True,
                        alignment=ft.Alignment(0, 0),
                        bgcolor="#1a1a1a",
                    )
                )
            return containers

        def _load_image_for_index(load_index: int) -> None:
            if load_index < 0 or load_index >= len(image_paths):
                return
            if load_index in pages_loaded:
                return
            path = image_paths[load_index]
            normalized = os.path.normpath(path)
            cached = _image_cache_busters.get(normalized)
            src = cached if cached else path
            if load_index in page_image_controls:
                page_image_controls[load_index].src = src
            pages_loaded.add(load_index)

            async def _apply():
                try:
                    page.update()
                except Exception:
                    pass

            page.run_task(_apply)

        def _load_pages_around(center: int) -> None:
            for offset in (0, 1, -1, 2, -2):
                target = center + offset
                if 0 <= target < len(image_paths):
                    threading.Thread(
                        target=_load_image_for_index,
                        args=(target,),
                        daemon=True,
                    ).start()



        # ── Mise à jour de la barre titre ─────────────────────────────────
        def _update_overlay_bar(new_index: int) -> None:
            state["index"] = new_index
            path = image_paths[new_index] if image_paths else ""
            filename_text.value = os.path.basename(path)
            counter_text.value = f"{new_index + 1} / {len(image_paths)}"
            viewer_checkbox.value = path in selected_files
            resolution_text.value = ""

            def _load_res():
                resolution_text.value = _get_resolution(path)
                try:
                    page.update()
                except Exception:
                    pass

            threading.Thread(target=_load_res, daemon=True).start()
            page.update()

        def on_page_change(e) -> None:
            new_index = int(e.data)
            _update_overlay_bar(new_index)
            _load_pages_around(new_index)



        # ── Viewer principal ──────────────────────────────────────────────
        _HAS_PAGE_VIEW = hasattr(ft, "PageView")
        if _HAS_PAGE_VIEW:
            images_page_view = ft.PageView(
                controls=_build_page_containers(),
                expand=True,
                horizontal=True,
                selected_index=initial_index,
                on_change=on_page_change,
            )
        else:
            # Fallback : une seule image visible à la fois (navigation par boutons/clavier)
            _fb_win_w = page.window.width or 1280
            _fb_win_h = page.window.height or 800
            _fb_img_ctrl = ft.Image(
                src=_blank_gif,
                width=_fb_win_w,
                height=_fb_win_h,
                fit=ft.BoxFit.CONTAIN,
                gapless_playback=True,
                error_content=ft.Container(
                    content=ft.Icon(ft.Icons.BROKEN_IMAGE, color=ft.Colors.WHITE54, size=64),
                    alignment=ft.Alignment(0, 0),
                ),
            )
            page_image_controls[initial_index] = _fb_img_ctrl
            _fb_iv = ft.InteractiveViewer(
                key="iv_fb",
                content=_fb_img_ctrl,
                min_scale=0.5,
                max_scale=10.0,
                pan_enabled=True,
                scale_enabled=True,
                width=_fb_win_w,
                height=_fb_win_h,
                clip_behavior=ft.ClipBehavior.HARD_EDGE,
            )
            images_page_view = ft.Container(
                content=_fb_iv,
                expand=True,
                alignment=ft.Alignment(0, 0),
                bgcolor="#1a1a1a",
            )

            def _fb_navigate(new_idx: int) -> None:
                """Met à jour l'image affichée en mode fallback (sans PageView)."""
                old_idx = state["index"]
                path = image_paths[new_idx] if image_paths else ""
                normalized = os.path.normpath(path) if path else ""
                cached = _image_cache_busters.get(normalized) if normalized else None
                _fb_img_ctrl.src = cached if cached else path
                page_image_controls.clear()
                page_image_controls[new_idx] = _fb_img_ctrl
                pages_loaded.discard(old_idx)
                pages_loaded.add(new_idx)



        # ── Navigation ────────────────────────────────────────────────────
        async def navigate_prev(e) -> None:
            if not image_paths or state["index"] <= 0:
                return
            if _HAS_PAGE_VIEW:
                await images_page_view.previous_page(  # type: ignore[union-attr]
                    animation_curve=ft.AnimationCurve.EASE_IN_OUT_CUBIC_EMPHASIZED,
                    animation_duration=ft.Duration(milliseconds=300),
                )
            else:
                new_idx = state["index"] - 1
                _fb_navigate(new_idx)
                _update_overlay_bar(new_idx)

        async def navigate_next(e) -> None:
            if not image_paths or state["index"] >= len(image_paths) - 1:
                return
            if _HAS_PAGE_VIEW:
                await images_page_view.next_page(  # type: ignore[union-attr]
                    animation_curve=ft.AnimationCurve.EASE_IN_OUT_CUBIC_EMPHASIZED,
                    animation_duration=ft.Duration(milliseconds=300),
                )
            else:
                new_idx = state["index"] + 1
                _fb_navigate(new_idx)
                _update_overlay_bar(new_idx)



        # ── Fermeture ─────────────────────────────────────────────────────
        def close_viewer(e) -> None:
            page.on_keyboard_event = previous_keyboard_handler
            if preview_overlay in page.overlay:
                page.overlay.remove(preview_overlay)
            # Restaurer la page preview sur l'image courante
            current_path = _current_path()
            all_entry_paths = [ep for (_, ep, _d, _i, _e) in all_entries_data["list"]]
            try:
                entry_index = all_entry_paths.index(current_path)
                preview_page["value"] = entry_index // PAGE_SIZE
            except ValueError:
                pass
            refresh_preview(reset_page=False)
            page.update()



        # ── Suppression ───────────────────────────────────────────────────
        def delete_current_image(e) -> None:
            path = _current_path()
            fname = os.path.basename(path)

            def _confirm(e2):
                page.on_keyboard_event = on_key
                delete_confirmation_dialog.open = False
                page.update()
                try:
                    os.remove(path)
                    log_to_terminal(f"[OK] Supprimé: {fname}", GREEN)
                except Exception as err:
                    log_to_terminal(f"[ERREUR] {err}", RED)
                    return

                # Retirer de la sélection si présent
                if path in selected_files:
                    selected_files.remove(path)
                    selection_count_text.value = _selection_label()
                    selection_count_text.update()
                # Retirer l'entrée de all_entries_data pour cohérence
                all_entries_data["list"] = [
                    e for e in all_entries_data["list"] if e[1] != path
                ]

                cur_idx = state["index"]
                image_paths.pop(cur_idx)
                if _HAS_PAGE_VIEW:
                    images_page_view.controls.pop(cur_idx)
                page_image_controls.pop(cur_idx, None)

                if not image_paths:
                    close_viewer(None)
                    return

                # Décaler les clés de page_image_controls après cur_idx
                shifted = {}
                for k, v in page_image_controls.items():
                    shifted[k if k < cur_idx else k - 1] = v
                page_image_controls.clear()
                page_image_controls.update(shifted)

                # Vider pages_loaded pour forcer le rechargement propre de tout
                pages_loaded.clear()

                new_idx = min(cur_idx, len(image_paths) - 1)

                if _HAS_PAGE_VIEW:
                    images_page_view.selected_index = new_idx
                else:
                    _fb_navigate(new_idx)

                _update_overlay_bar(new_idx)
                _load_pages_around(new_idx)
                page.update()

                # Rafraîchir la grille en arrière-plan sans changer de page
                threading.Thread(
                    target=lambda: refresh_preview(reset_page=False),
                    daemon=True,
                ).start()

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



        # ── Rotation ──────────────────────────────────────────────────────
        def _rotate_current(direction: str) -> None:
            path = _current_path()
            if not path:
                return
            if os.path.splitext(path)[1].lower() not in _ROTATABLE_EXTS:
                return

            def _do_rotate():
                _rotate_files([path], direction)
                normalized = os.path.normpath(path)
                cached = _image_cache_busters.get(normalized)
                src = cached if cached else path
                cur_idx = state["index"]
                if cur_idx in page_image_controls:
                    page_image_controls[cur_idx].src = src
                    pages_loaded.discard(cur_idx)
                try:
                    page.update()
                except Exception:
                    pass

            threading.Thread(target=_do_rotate, daemon=True).start()



        # ── Clavier ───────────────────────────────────────────────────────
        def on_key(e: ft.KeyboardEvent) -> None:
            if e.key in ("Arrow Left", "ArrowLeft"):
                page.run_task(navigate_prev, e)
            elif e.key in ("Arrow Right", "ArrowRight"):
                page.run_task(navigate_next, e)
            elif e.key == "Escape":
                close_viewer(None)
            elif e.key in ("Delete", "Backspace"):
                delete_current_image(None)
            elif e.key == "[":
                _rotate_current("left")
            elif e.key == "]":
                _rotate_current("right")

        page.on_keyboard_event = on_key



        # ── UI ────────────────────────────────────────────────────────────
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
                        on_click=navigate_prev,
                        style=button_style,
                    ),
                    ft.Container(
                        content=viewer_checkbox,
                        padding=ft.Padding.symmetric(horizontal=4, vertical=0),
                    ),
                    ft.IconButton(
                        icon=ft.Icons.ROTATE_LEFT,
                        icon_color=ft.Colors.WHITE70,
                        icon_size=22,
                        tooltip="Pivoter à gauche ([)",
                        on_click=lambda e: _rotate_current("left"),
                        style=button_style,
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
                        icon=ft.Icons.ROTATE_RIGHT,
                        icon_color=ft.Colors.WHITE70,
                        icon_size=22,
                        tooltip="Pivoter à droite (])",
                        on_click=lambda e: _rotate_current("right"),
                        style=button_style,
                    ),
                    ft.IconButton(
                        icon=ft.Icons.ARROW_FORWARD_IOS_ROUNDED,
                        icon_color=ft.Colors.WHITE,
                        icon_size=26,
                        tooltip="Image suivante",
                        on_click=navigate_next,
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

        preview_overlay = ft.Stack([
            # Viewer principal (fond plein)
            images_page_view,
            # Titre/compteur centré en haut
            ft.Container(
                content=top_bar,
                top=8,
                left=0,
                right=0,
                alignment=ft.Alignment(0, 0),
            ),
            # Bouton fermer en haut à droite
            ft.Container(
                content=close_btn_top,
                top=8,
                right=8,
            ),
            # Barre de navigation inférieure flottante
            ft.Container(
                content=ft.Row(
                    [navigation_bar],
                    alignment=ft.MainAxisAlignment.CENTER,
                ),
                bottom=16,
                left=0,
                right=0,
            ),
        ], expand=True)
        page.overlay.append(preview_overlay)
        page.update()

        # Résolution initiale en arrière-plan
        def _load_initial_res():
            resolution_text.value = _get_resolution(_current_path())
            try:
                page.update()
            except Exception:
                pass

        threading.Thread(target=_load_initial_res, daemon=True).start()

        # Chargement des images autour de l'index initial
        _load_pages_around(initial_index)



    def _open_json_in_side_panel(file_path):
        """Lance Side Panel avec le fichier JSON pré-chargé dans l'onglet Liste."""
        log_to_terminal(
            f"[OK] Ouverture dans Side Panel → Liste : {os.path.basename(file_path)}",
            VIOLET,
        )
        _launch_side_panel({"SELECTEUR_JSON_PATH": file_path})

    def on_file_click(file_path, is_dir):
        """
        Gère le clic sur un élément de la preview.

        - Dossier      → navigation
        - ZIP          → extraction
        - Image        → visionneuse plein écran
        - JSON         → ouverture dans Side Panel
        - Autre        → application par défaut du système
        """
        if is_dir:
            navigate_to_folder(file_path)
        elif os.path.splitext(file_path)[1].lower() == ".zip":
            log_to_terminal(f"Extraction: {os.path.splitext(os.path.basename(file_path))[0]}", YELLOW)
            extract_zip(file_path)
        elif os.path.splitext(file_path)[1].lower() in _NOTEPAD_EXTS:
            open_file_in_notepad(file_path)
        elif os.path.splitext(file_path)[1].lower() in _IMAGE_VIEWER_EXTS:
            open_image_viewer(file_path)
        elif os.path.splitext(file_path)[1].lower() == ".json":
            _open_json_in_side_panel(file_path)
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
                # Retirer de la sélection si présent
                if file_path in selected_files:
                    selected_files.remove(file_path)
                    selection_count_text.value = _selection_label()
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
                    navigate_to_folder(new_folder_path)
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
        clear_selection(None)



    def cut_selected_files(e):
        """Coupe les fichiers sélectionnés (déplacement à la destination)"""
        if not selected_files:
            log_to_terminal("[ATTENTION] Aucun fichier sélectionné", ORANGE)
            return
        clipboard["files"] = list(selected_files)
        clipboard["cut"] = True
        count = len(clipboard["files"])
        log_to_terminal(f"[OK] {count} élément(s) coupé(s) — collé avec Ctrl+V", ORANGE)
        clear_selection(None)



    def select_by_filter(e):
        """Sélectionne tous les fichiers visibles (en tenant compte de la recherche active)."""
        entries = all_entries_data["list"]
        if search_query["value"]:
            query_lower = search_query["value"].lower()
            entries = [entry for entry in entries if query_lower in entry[0].lower()]
        added = 0
        for _name, fpath, is_dir, _is_img, _ext in entries:
            if not is_dir and fpath not in selected_files:
                selected_files.append(fpath)
                added += 1
        if show_only_selection["value"]:
            _render_preview_page()
        else:
            _update_visible_checkboxes()
        if added:
            log_to_terminal(f"[OK] {added} fichier(s) sélectionné(s)", BLUE)
        else:
            log_to_terminal("[ATTENTION] Aucun fichier à sélectionner", ORANGE)



    def _update_select_toggle_button():
        """Met à jour l'apparence du bouton sélectionner/désélectionner."""
        if search_query["value"]:
            query_lower = search_query["value"].lower()
            filtered_paths = {
                fpath for (_name, fpath, is_dir, _is_img, _ext) in all_entries_data["list"]
                if not is_dir and query_lower in _name.lower()
            }
            all_filtered_selected = bool(filtered_paths) and filtered_paths.issubset(set(selected_files))
        else:
            all_filtered_selected = bool(selected_files)

        if all_filtered_selected:
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



    def _update_filter_sel_btn():
        """Met à jour l'apparence du bouton 'afficher uniquement la sélection'."""
        if show_only_selection["value"]:
            filter_sel_btn.icon_color = BLUE
            filter_sel_btn.tooltip = "Afficher tous les fichiers"
        else:
            filter_sel_btn.icon_color = LIGHT_GREY
            filter_sel_btn.tooltip = "Afficher uniquement la sélection"
        try:
            filter_sel_btn.update()
        except Exception:
            pass



    def _toggle_show_only_selection(e):
        """Active/désactive le filtre 'uniquement la sélection'."""
        show_only_selection["value"] = not show_only_selection["value"]
        _update_filter_sel_btn()
        _render_preview_page()



    def toggle_select_all(e):
        """Sélectionne tout si rien sélectionné, sinon désélectionne tout.
        Si une recherche est active : sélectionne d'abord les fichiers filtrés,
        puis désélectionne tout au second appui."""
        if search_query["value"]:
            query_lower = search_query["value"].lower()
            filtered_paths = {
                fpath for (_name, fpath, is_dir, _is_img, _ext) in all_entries_data["list"]
                if not is_dir and query_lower in _name.lower()
            }
            if not filtered_paths.issubset(set(selected_files)):
                # Premier appuis : sélectionner les fichiers filtrés
                select_by_filter(e)
            else:
                # Deuxième appui : tout désélectionner
                clear_selection(e)
        else:
            if selected_files:
                clear_selection(e)
            else:
                select_by_filter(e)



    def invert_selection(e):
        """Inverse la sélection : sélectionne les non-sélectionnés, désélectionne les sélectionnés."""
        entries = all_entries_data["list"]
        if search_query["value"]:
            query_lower = search_query["value"].lower()
            entries = [entry for entry in entries if query_lower in entry[0].lower()]
        for _name, fpath, is_dir, _is_img, _ext in entries:
            if is_dir:
                continue
            if fpath in selected_files:
                selected_files.remove(fpath)
            else:
                selected_files.append(fpath)
        if show_only_selection["value"]:
            _render_preview_page()
        else:
            _update_visible_checkboxes()
        log_to_terminal(f"[OK] Sélection inversée — {len(selected_files)} fichier(s) sélectionné(s)", BLUE)



    def select_same_date(e):
        """Sélectionne tous les fichiers du dossier pris à la même date (jour) que le fichier sélectionné."""
        if not selected_files:
            log_to_terminal("[ATTENTION] Aucun fichier sélectionné comme référence", ORANGE)
            return
        ref_path = selected_files[-1]
        try:
            ref_mtime = os.path.getmtime(ref_path)
        except OSError:
            log_to_terminal("[ERREUR] Impossible de lire la date du fichier de référence", RED)
            return
        ref_date = datetime.date.fromtimestamp(ref_mtime)
        added = 0
        for _name, fpath, is_dir, _is_img, _ext in all_entries_data["list"]:
            if is_dir:
                continue
            try:
                fdate = datetime.date.fromtimestamp(os.path.getmtime(fpath))
            except OSError:
                continue
            if fdate == ref_date and fpath not in selected_files:
                selected_files.append(fpath)
                added += 1
        if show_only_selection["value"]:
            _render_preview_page()
        else:
            _update_visible_checkboxes()
        _update_select_toggle_button()
        log_to_terminal(f"[OK] {len(selected_files)} fichier(s) du {ref_date.strftime('%d/%m/%Y')} sélectionné(s) (+{added} ajouté(s))", BLUE)



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
                            if source_path in selected_files:
                                selected_files.remove(source_path)
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

            app_progress_bar.visible = False
            try:
                page.update()
            except Exception:
                pass
            refresh_preview()

        app_progress_bar.visible = True
        try:
            page.update()
        except Exception:
            pass
        threading.Thread(target=_do_paste, daemon=True).start()



    def _apply_print_rename(file_path, new_count):
        basename = os.path.basename(file_path)
        folder = os.path.dirname(file_path)
        
        if not os.path.exists(file_path):
            return
            
        print_prefix_match = re.match(r'^(\d+)X_', basename)
        print_prefix_pattern = re.compile(r'^\d+X_')
        if print_prefix_match:
            current_count = int(print_prefix_match.group(1))
            clean_basename = re.sub(r'^\d+X_', '', basename)
        else:
            current_count = 0
            clean_basename = basename
            
        if new_count > 0:
            new_name = f"{new_count}X_{clean_basename}"
        else:
            new_name = clean_basename
            
        new_path = os.path.join(folder, new_name)
        if new_path != file_path:
            try:
                os.rename(file_path, new_path)
                log_to_terminal(f"[Impressions] {basename} → {new_name}", GREEN)
                
                # Mettre à jour dans selected_files
                if file_path in selected_files:
                    selected_files[selected_files.index(file_path)] = new_path
                    
                # Mettre à jour le dictionnaire de live counts avec la nouvelle clé de fichier
                _live_print_counts[new_path] = new_count
                _live_print_counts.pop(file_path, None)
                
                # Mettre à jour les références UI refs si elles existent
                if file_path in _print_count_text_refs:
                    _print_count_text_refs[new_path] = _print_count_text_refs.pop(file_path)
                if file_path in _print_minus_btn_refs:
                    _print_minus_btn_refs[new_path] = _print_minus_btn_refs.pop(file_path)
                
                # Déclencher un refresh en arrière-plan pour rescanner proprement
                page.pubsub.send_all_on_topic("refresh", None)
            except Exception as err:
                log_to_terminal(f"[ERREUR] {err}", RED)
                return
                
        # 1. Si le fichier est repassé à 0, on remet TOUS les autres fichiers du dossier à 0 aussi
        if new_count <= 0:
            renamed_count = 0
            for file_name in os.listdir(folder):
                # Ignorer les fichiers cachés et fichiers système/junk
                if file_name.startswith(".") or file_name.lower() in _OS_JUNK:
                    continue
                entry_path = os.path.join(folder, file_name)
                if not os.path.isfile(entry_path) or entry_path == new_path:
                    continue
                if not print_prefix_pattern.match(file_name):
                    continue
                clean_other_basename = re.sub(r'^\d+X_', '', file_name)
                clean_entry_path = os.path.join(folder, clean_other_basename)
                try:
                    os.rename(entry_path, clean_entry_path)
                    if entry_path in selected_files:
                        selected_files[selected_files.index(entry_path)] = clean_entry_path
                    # Mettre à jour live counts et UI instantanément pour les autres fichiers
                    _live_print_counts[clean_entry_path] = 0
                    _live_print_counts.pop(entry_path, None)
                    
                    if entry_path in _print_count_text_refs:
                        txt_ref = _print_count_text_refs[entry_path]
                        txt_ref.value = "·"
                        txt_ref.color = LIGHT_GREY
                        txt_ref.update()
                        _print_count_text_refs[clean_entry_path] = _print_count_text_refs.pop(entry_path)
                    if entry_path in _print_minus_btn_refs:
                        minus_ref = _print_minus_btn_refs[entry_path]
                        minus_ref.content.color = LIGHT_GREY
                        minus_ref.bgcolor = GREY
                        minus_ref.on_click = None
                        minus_ref.ink = False
                        minus_ref.update()
                        _print_minus_btn_refs[clean_entry_path] = _print_minus_btn_refs.pop(entry_path)
                        
                    renamed_count += 1
                except Exception as err:
                    log_to_terminal(f"[ERREUR] {file_name}: {err}", RED)
            if renamed_count:
                log_to_terminal(f"[OK] Préfixe retiré de {renamed_count} fichier(s)", GREEN)
                page.pubsub.send_all_on_topic("refresh", None)
                
        # 2. Gérer l'auto-préfixe 1X_ si besoin (uniquement sur fichiers non-cachés et non-junk)
        elif current_count == 0 and new_count > 0:
            others_have_prefix = any(
                print_prefix_pattern.match(file_name)
                for file_name in os.listdir(folder)
                if file_name != new_name and os.path.isfile(os.path.join(folder, file_name)) and not file_name.startswith(".") and file_name.lower() not in _OS_JUNK
            )
            if not others_have_prefix:
                renamed_count = 0
                for file_name in os.listdir(folder):
                    # Ignorer les fichiers cachés et fichiers système/junk
                    if file_name.startswith(".") or file_name.lower() in _OS_JUNK:
                        continue
                    entry_path = os.path.join(folder, file_name)
                    if not os.path.isfile(entry_path) or entry_path == new_path:
                        continue
                    if print_prefix_pattern.match(file_name):
                        continue
                    new_file_name = f"1X_{file_name}"
                    new_entry_path = os.path.join(folder, new_file_name)
                    try:
                        os.rename(entry_path, new_entry_path)
                        if entry_path in selected_files:
                            selected_files[selected_files.index(entry_path)] = new_entry_path
                        # Mettre à jour live counts et UI instantanément
                        _live_print_counts[new_entry_path] = 1
                        _live_print_counts.pop(entry_path, None)
                        
                        if entry_path in _print_count_text_refs:
                            txt_ref = _print_count_text_refs[entry_path]
                            txt_ref.value = "1"
                            txt_ref.color = YELLOW
                            txt_ref.update()
                            _print_count_text_refs[new_entry_path] = _print_count_text_refs.pop(entry_path)
                        if entry_path in _print_minus_btn_refs:
                            minus_ref = _print_minus_btn_refs[entry_path]
                            minus_ref.content.color = DARK
                            minus_ref.bgcolor = ORANGE
                            minus_ref.on_click = lambda e, p=new_entry_path: _decrement_print_count(p)
                            minus_ref.ink = True
                            minus_ref.update()
                            _print_minus_btn_refs[new_entry_path] = _print_minus_btn_refs.pop(entry_path)
                            
                        renamed_count += 1
                    except Exception as err:
                        log_to_terminal(f"[ERREUR] {file_name}: {err}", RED)
                if renamed_count:
                    log_to_terminal(f"[OK] {renamed_count} fichier(s) renommé(s) avec le préfixe 1X_", GREEN)
                    page.pubsub.send_all_on_topic("refresh", None)

    def _increment_print_count(file_path):
        """Incrémente le compteur d'impressions de façon réactive et débouncée."""
        if file_path in _live_print_counts:
            current_count = _live_print_counts[file_path]
        else:
            basename = os.path.basename(file_path)
            print_prefix_match = re.match(r'^(\d+)X_', basename)
            current_count = int(print_prefix_match.group(1)) if print_prefix_match else 0
            _live_print_counts[file_path] = current_count
            
        new_count = current_count + 1
        _live_print_counts[file_path] = new_count
        
        # Mettre à jour l'UI instantanément
        if file_path in _print_count_text_refs:
            txt_ref = _print_count_text_refs[file_path]
            txt_ref.value = str(new_count) if new_count > 0 else "·"
            txt_ref.color = YELLOW if new_count > 0 else LIGHT_GREY
            txt_ref.update()
            
        if file_path in _print_minus_btn_refs:
            minus_ref = _print_minus_btn_refs[file_path]
            minus_ref.content.color = DARK if new_count > 0 else LIGHT_GREY
            minus_ref.bgcolor = ORANGE if new_count > 0 else GREY
            minus_ref.on_click = (lambda e, p=file_path: _decrement_print_count(p)) if new_count > 0 else None
            minus_ref.ink = (new_count > 0)
            minus_ref.update()
            
        # Annuler l'ancien timer et démarrer le nouveau
        if file_path in _print_rename_timers:
            _print_rename_timers[file_path].cancel()
            
        timer = threading.Timer(1.5, _apply_print_rename, args=(file_path, new_count))
        _print_rename_timers[file_path] = timer
        timer.start()

    def _decrement_print_count(file_path):
        """Décrémente le compteur d'impressions de façon réactive et débouncée."""
        if file_path in _live_print_counts:
            current_count = _live_print_counts[file_path]
        else:
            basename = os.path.basename(file_path)
            print_prefix_match = re.match(r'^(\d+)X_', basename)
            current_count = int(print_prefix_match.group(1)) if print_prefix_match else 0
            _live_print_counts[file_path] = current_count
            
        if current_count <= 0:
            return
            
        new_count = current_count - 1
        _live_print_counts[file_path] = new_count
        
        # Mettre à jour l'UI instantanément
        if file_path in _print_count_text_refs:
            txt_ref = _print_count_text_refs[file_path]
            txt_ref.value = str(new_count) if new_count > 0 else "·"
            txt_ref.color = YELLOW if new_count > 0 else LIGHT_GREY
            txt_ref.update()
            
        if file_path in _print_minus_btn_refs:
            minus_ref = _print_minus_btn_refs[file_path]
            minus_ref.content.color = DARK if new_count > 0 else LIGHT_GREY
            minus_ref.bgcolor = ORANGE if new_count > 0 else GREY
            minus_ref.on_click = (lambda e, p=file_path: _decrement_print_count(p)) if new_count > 0 else None
            minus_ref.ink = (new_count > 0)
            minus_ref.update()
            
        # Annuler l'ancien timer et démarrer le nouveau
        if file_path in _print_rename_timers:
            _print_rename_timers[file_path].cancel()
            
        timer = threading.Timer(1.5, _apply_print_rename, args=(file_path, new_count))
        _print_rename_timers[file_path] = timer
        timer.start()



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
            if file_path not in selected_files:
                selected_files.append(file_path)
        else:
            if file_path in selected_files:
                selected_files.remove(file_path)
        selection_count_text.value = _selection_label()
        _update_select_toggle_button()
        selection_count_text.update()


    def _update_visible_checkboxes():
        """Met à jour les cases à cocher en place sans reconstruire les widgets image."""
        for file_path, checkbox_widget in _checkbox_refs.items():
            checkbox_widget.value = file_path in selected_files
        selection_count_text.value = _selection_label()
        _update_select_toggle_button()
        page.update()



    def clear_selection(e):
        """Désélectionne tous les fichiers et rafraîchit la preview."""
        selected_files.clear()
        if show_only_selection["value"]:
            show_only_selection["value"] = False
            _update_filter_sel_btn()
            _render_preview_page()  # la liste filtrée change, re-rendu nécessaire
        else:
            _update_visible_checkboxes()  # seulement les cases à cocher changent
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
            selection_count_text.value = _selection_label()
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

        names_ordered = [name for name in selected_names_str.split("|") if name]
        names_to_select = set(names_ordered)

        selected_files.clear()



        # Utilise all_entries_data pour garantir que les chemins dans selected_files
        # sont identiques (même objet str) à ceux utilisés par _render_current_page(),
        # évitant toute divergence de normalisation Unicode NFD/NFC sur macOS.
        entries = all_entries_data["list"]
        if names_to_select and entries:
            name_to_path = {file_name: file_path for file_name, file_path, is_dir, is_image, ext in entries if file_name in names_to_select}
            for name in names_ordered:
                if name in name_to_path:
                    selected_files.append(name_to_path[name])
        elif names_to_select:
            # Fallback si entries pas encore peuplées
            existing = {item_name: os.path.join(folder_to_display, item_name) for item_name in os.listdir(folder_to_display)}
            for name in names_ordered:
                if name in existing:
                    selected_files.append(existing[name])

        selection_count_text.value = _selection_label()



        # Naviguer vers la première page contenant au moins un fichier sélectionné
        # (évite que les fichiers au-delà de PAGE_SIZE soient invisibles)
        if selected_files and entries:
            for entry_index, (file_name, file_path, is_dir, is_image, ext) in enumerate(entries):
                if file_path in selected_files:
                    preview_page["value"] = entry_index // PAGE_SIZE
                    break



        # Re-rendu immédiat sans nouveau scan (le script ne modifie aucun fichier)
        _render_preview_page()

        if names_to_select and not selected_files:
            log_to_terminal("[ATTENTION] Aucun fichier correspondant trouvé dans la preview", ORANGE)



    # ================================================================ #
    #                    FILTRAGE & PÉRIPHÉRIQUES                      #
    # ================================================================ #
    # ── Recherche dans la preview ──────────────────────────────────────
    def _on_search_change(e):
        """Met à jour la requête de recherche et re-rend la preview.
        Si le champ est vidé, referme la barre et restaure l'icône seule."""
        typed_text = (search_field.value or "").strip()
        if not typed_text:
            _clear_search(e)
            return
        if show_only_selection["value"]:
            show_only_selection["value"] = False
            _update_filter_sel_btn()
        search_query["value"] = typed_text
        preview_page["value"] = 0
        _render_preview_page()

    def _clear_search(e):
        """Efface la recherche et restaure tous les fichiers."""
        search_query["value"] = ""
        search_field.value = ""
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
                    if entry.is_dir() and os.path.ismount(entry.path) and entry.name not in macos_system_volumes and not entry.name.startswith("."):
                        drives.append((entry.name, entry.path))
                # macOS crée parfois NAME et NAME-1 simultanément (stub APFS + nouveau montage).
                # Dans ce cas, NAME est le stub vide et NAME-1 est le vrai volume :
                # on garde l'entrée NAME mais on la fait pointer vers NAME-1.
                _sfx_re = re.compile(r'^(.*?)-(\d+)$')
                _drive_names = {n for n, _ in drives}
                _replacements = {}
                for _dn, _dp in drives:
                    _m = _sfx_re.match(_dn)
                    if _m:
                        _base, _n = _m.group(1), int(_m.group(2))
                        if _base in _drive_names:
                            _prev = _replacements.get(_base)
                            if _prev is None or _n > _prev[0]:
                                _replacements[_base] = (_n, _dp)
                if _replacements:
                    _skip = {_dn for _dn, _ in drives
                             if _sfx_re.match(_dn) and _sfx_re.match(_dn).group(1) in _replacements}
                    drives = [(_dn, _replacements[_dn][1]) if _dn in _replacements else (_dn, _dp)
                              for _dn, _dp in drives if _dn not in _skip]

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
                    resolved = _resolve_favorite_path(path)
                    if os.path.isdir(resolved):
                        navigate_to_folder(resolved)
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
        if any(favorite["path"] == path for favorite in favorites_list):
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
            if not any(favorite["path"] == path for favorite in favorites_list):
                favorites_list.insert(0, {"path": path, "label": label})
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
        """Démonte/éjecte un périphérique amovible selon le système d'exploitation.
        Réessaie automatiquement jusqu'à 3 fois si l'éjection n'est pas confirmée."""
        log_to_terminal(f"[...] Éjection en cours : {path}", VIOLET)

        def _run():
            sys_name = platform.system()
            max_attempts = 3
            for attempt in range(1, max_attempts + 1):
                try:
                    if sys_name == "Windows":
                        drive_letter = os.path.splitdrive(path)[0]  # ex: "E:"
                        powershell_eject_command = (
                            f"(New-Object -comObject Shell.Application)"
                            f".Namespace(17).ParseName('{drive_letter}').InvokeVerb('Eject')"
                        )
                        subprocess.run(["powershell", "-Command", powershell_eject_command],
                                       creationflags=subprocess.CREATE_NO_WINDOW,
                                       timeout=10)
                        # InvokeVerb est asynchrone : on attend que le lecteur disparaisse
                        time.sleep(1.5)
                        if not os.path.exists(path):
                            log_to_terminal(f"[OK] Éjecté : {path}", VIOLET)
                            return
                    elif sys_name == "Darwin":
                        result = subprocess.run(
                            ["diskutil", "eject", path],
                            capture_output=True, text=True, timeout=10,
                        )
                        if result.returncode == 0:
                            log_to_terminal(f"[OK] Éjecté : {path}", VIOLET)
                            return
                    else:  # Linux
                        result = subprocess.run(
                            ["umount", path],
                            capture_output=True, text=True, timeout=10,
                        )
                        if result.returncode == 0:
                            log_to_terminal(f"[OK] Éjecté : {path}", VIOLET)
                            return
                except subprocess.TimeoutExpired:
                    pass
                except Exception as ex:
                    log_to_terminal(f"[ERREUR] Éjection impossible : {ex}", RED)
                    return

                if attempt < max_attempts:
                    log_to_terminal(f"[...] Tentative {attempt}/{max_attempts} échouée — nouvel essai…", ORANGE)
                    time.sleep(1)

            log_to_terminal(f"[ATTENTION] Éjection non confirmée après {max_attempts} tentatives : {path}", ORANGE)

        threading.Thread(target=_run, daemon=True).start()



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
        ordered_drives = []
        while True:
            time.sleep(3)
            try:
                drives = _get_removable_drives()
                if drives != prev_drives:
                    new_drives = [drive for drive in drives if drive not in prev_drives]
                    existing_drives = [drive for drive in ordered_drives if drive in drives]
                    ordered_drives = new_drives + existing_drives
                    prev_drives = drives
                    removable_drives_state["list"] = ordered_drives
                    page.pubsub.send_all_on_topic("drives_changed", ordered_drives)
            except Exception:
                pass



    # ================================================================ #
    #                           PREVIEW                                #
    # ================================================================ #
    def _render_preview_page():
        """
        Construit et affiche les contrôles ListView pour la page courante.
        Appelée depuis on_preview_ready et go_to_page (thread UI uniquement).
        Les images sont affichées d'abord avec une icône placeholder, puis les miniatures
        sont générées en arrière-plan et mises à jour sans bloquer l'UI.
        """
        try:
            _checkbox_refs.clear()
            _pending_thumb_refs.clear()
            entries = all_entries_data["list"]
            # Appliquer la recherche textuelle
            if search_query["value"]:
                query_lower = search_query["value"].lower()
                entries = [entry for entry in entries if query_lower in entry[0].lower()]
            # Afficher uniquement la sélection si actif
            if show_only_selection["value"]:
                entries = [entry for entry in entries if entry[1] in selected_files]
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
                    _checkbox_refs[file_path] = checkbox

                    if is_image:
                        norm_path = os.path.normpath(file_path)
                        cached_b64 = _thumb_cache.get(norm_path) or _image_cache_busters.get(norm_path)
                        _ts = CONSTANTS.DASHBOARD_THUMB_SIZE
                        if cached_b64:
                            visual = ft.Image(
                                src=cached_b64,
                                width=_ts, height=_ts,
                                fit=ft.BoxFit.COVER,
                                border_radius=ft.BorderRadius.all(4),
                            )
                        else:
                            img_ref = ft.Container(
                                bgcolor=GREY,
                                width=_ts, height=_ts,
                                border_radius=ft.BorderRadius.all(4),
                            )
                            visual = img_ref
                            _pending_thumb_refs[norm_path] = (img_ref, file_path, icon, icon_color)
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
                        if file_path in _live_print_counts:
                            print_count = _live_print_counts[file_path]
                        else:
                            print_prefix_match = re.match(r'^(\d+)X_', file)
                            print_count = int(print_prefix_match.group(1)) if print_prefix_match else 0
                            _live_print_counts[file_path] = print_count

                        minus_btn = ft.Container(
                            content=ft.Text("−", size=13, color=DARK if print_count > 0 else LIGHT_GREY,
                                            text_align=ft.TextAlign.CENTER, weight=ft.FontWeight.BOLD),
                            width=26, height=26,
                            bgcolor=ORANGE if print_count > 0 else GREY,
                            border_radius=ft.BorderRadius(4, 0, 0, 4),
                            alignment=ft.Alignment(0, 0),
                            on_click=(lambda e, p=file_path: _decrement_print_count(p)) if print_count > 0 else None,
                            ink=print_count > 0,
                            tooltip="Réduire les impressions" if print_count > 0 else "",
                        )
                        _print_minus_btn_refs[file_path] = minus_btn

                        count_text_widget = ft.Text(
                            str(print_count) if print_count > 0 else "·",
                            size=11, color=YELLOW if print_count > 0 else LIGHT_GREY,
                            text_align=ft.TextAlign.CENTER, weight=ft.FontWeight.BOLD,
                        )
                        _print_count_text_refs[file_path] = count_text_widget

                        count_display = ft.Container(
                            content=count_text_widget,
                            width=22, height=26,
                            bgcolor=DARK,
                            alignment=ft.Alignment(0, 0),
                        )
                        plus_btn = ft.Container(
                            content=ft.Text("+", size=13, color=DARK,
                                            text_align=ft.TextAlign.CENTER, weight=ft.FontWeight.BOLD),
                            width=26, height=26,
                            bgcolor=GREEN,
                            border_radius=ft.BorderRadius(0, 4, 4, 0),
                            alignment=ft.Alignment(0, 0),
                            on_click=lambda e, p=file_path: _increment_print_count(p),
                            ink=True,
                            tooltip="Augmenter les impressions",
                        )
                        print_controls = ft.Row(
                            [minus_btn, count_display, plus_btn],
                            spacing=0, tight=True,
                        )
                        trailing = ft.Row(
                            [print_controls, rename_button, delete_button],
                            spacing=4, tight=True,
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
                            _show_file_context_menu(files_to_open)
                        return _on_right_click

                    new_controls.append(
                        ft.GestureDetector(
                            on_secondary_tap_up=_create_right_click_handler(file_path, is_dir),
                            content=ft.ListTile(
                                leading=checkbox,
                                title=ft.Row(
                                    [visual, ft.Text(file, size=16, color=WHITE, expand=True)],
                                    spacing=12,
                                    vertical_alignment=ft.CrossAxisAlignment.CENTER,
                                ),
                                trailing=trailing,
                                on_click=lambda e, path=file_path, d=is_dir: on_file_click(path, d),
                                hover_color=GREY, dense=False,
                                content_padding=ft.Padding(left=8, top=2, right=8, bottom=2),
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



            _update_select_toggle_button()
            page.update()
            # Lancer le chargement des miniatures en arrière-plan après le rendu initial
            if _pending_thumb_refs:
                _start_thumb_loader()
        except Exception as ex:
            log_to_terminal(f"[ERREUR] Rendu preview: {ex}", RED)



    def refresh_preview(reset_page=True, force_reload=False):
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
        force_reload : bool
            Si True, vérifie les mtimes et régénère les caches miniatures depuis le disque.
            Ne passer True que sur le bouton Rafraîchir explicite ou après une rotation.
        """
        if reset_page:
            preview_page["value"] = 0
        preview_refresh_token["value"] += 1
        current_refresh_token = preview_refresh_token["value"]
        preview_list.on_scroll = None
        preview_list.controls.clear()
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
                    with os.scandir(folder_to_display) as directory_scanner:
                        raw_entries = [dir_entry for dir_entry in directory_scanner if not _is_os_junk(dir_entry)]

                    file_count = sum(1 for dir_entry in raw_entries if not dir_entry.name.startswith(".") and not dir_entry.is_dir())
                    new_file_count_text = f"({file_count} fichier{'s' if file_count > 1 else ''})"

                    if raw_entries:
                        if sort_mode["value"] == 2:
                            sorted_entries = sorted(raw_entries, key=lambda entry: (not entry.is_dir(), -entry.stat().st_mtime))
                        elif sort_mode["value"] == 1:
                            sorted_entries = sorted(raw_entries, key=lambda entry: (not entry.is_dir(), entry.name.lower()), reverse=True)
                        else:
                            sorted_entries = sorted(raw_entries, key=lambda entry: (not entry.is_dir(), entry.name.lower()))

                        for entry in sorted_entries:
                            name = entry.name
                            path = entry.path
                            is_dir = entry.is_dir()
                            ext = os.path.splitext(name)[1].lower()
                            is_image = ext in [".jpg", ".jpeg", ".png", ".gif", ".bmp", ".webp", ".ico", ".tiff", ".tif"]
                            entries_data.append((name, path, is_dir, is_image, ext))

                            # Mémoriser le mtime à chaque scan pour détecter les modifications externes.
                            # Sur rafraîchissement explicite (force_reload), invalider le cache si le fichier a changé.
                            if is_image and not is_dir:
                                normalized_path = os.path.normpath(path)
                                try:
                                    current_mtime = entry.stat().st_mtime
                                except OSError:
                                    continue
                                stored_mtime = _image_last_mtime.get(normalized_path)
                                if force_reload and stored_mtime is not None and current_mtime != stored_mtime:
                                    # Invalider le cache et régénérer la miniature
                                    _thumb_cache.pop(normalized_path, None)
                                    new_b64 = thumb_cache.get_or_generate(path)
                                    if new_b64:
                                        _image_cache_busters[normalized_path] = new_b64
                                        _thumb_cache[normalized_path] = new_b64
                                _image_last_mtime[normalized_path] = current_mtime

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
        """Navigue de ±1 page dans la preview sans rescanner le dossier."""
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
    def _ask_text_before_launch(dialog_title: str, field_label: str, field_hint: str,
                                app_name: str, app_path: str, is_local: bool):
        """Affiche un dialog de saisie texte, puis relance launch_app avec le texte saisi.

        Utilisé pour recueillir un paramètre (nom de série, nom de PDF) avant
        de lancer un script qui en a besoin.
        """
        text_input = ft.TextField(
            label=field_label,
            hint_text=field_hint,
            autofocus=True,
            width=320,
            bgcolor=DARK,
            border_color=GREY,
        )

        def _on_confirm(e):
            name = text_input.value.strip() if text_input.value else ""
            param_dialog.open = False
            page.update()
            launch_app(app_name, app_path, is_local, series_name=name)

        def _on_cancel(e):
            param_dialog.open = False
            page.update()

        text_input.on_submit = _on_confirm
        param_dialog = ft.AlertDialog(
            modal=True,
            title=ft.Text(dialog_title),
            content=text_input,
            actions=[
                ft.TextButton("Annuler", on_click=_on_cancel),
                ft.TextButton("OK", on_click=_on_confirm),
            ],
            actions_alignment=ft.MainAxisAlignment.END,
        )
        page.overlay.append(param_dialog)
        param_dialog.open = True
        page.update()



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
        if app_name == "Copyright.py" and series_name is None:
            copyright_custom_field = ft.TextField(
                prefix="© ",
                border_color=BLUE,
                text_size=13,
                height=40,
                content_padding=ft.Padding(8, 4, 8, 4),
                expand=True,
                visible=False,
            )
            copyright_custom_row = ft.AnimatedSwitcher(
                content=ft.Container(height=0),
                duration=150,
            )

            selected_copyright_mode = {"value": None}

            def _make_copyright_option(mode, icon, label, description):
                def _on_click(e):
                    selected_copyright_mode["value"] = mode
                    copyright_custom_field.visible = (mode == "custom")
                    # Highlight sélectionné
                    for btn in copyright_options_row.controls:
                        btn.border = ft.Border.all(2, BLUE if btn.data == mode else GREY)
                    page.update()
                btn = ft.Container(
                    data=mode,
                    content=ft.Column([
                        ft.Icon(icon, size=22, color=BLUE),
                        ft.Text(label, size=12, color=WHITE, text_align=ft.TextAlign.CENTER, weight=ft.FontWeight.BOLD),
                        ft.Text(description, size=10, color=LIGHT_GREY, text_align=ft.TextAlign.CENTER),
                    ], horizontal_alignment=ft.CrossAxisAlignment.CENTER, spacing=4, tight=True),
                    bgcolor=DARK,
                    border=ft.Border.all(2, GREY),
                    border_radius=8,
                    padding=ft.Padding(10, 10, 10, 10),
                    width=105,
                    height=100,
                    on_click=_on_click,
                    ink=True,
                )
                return btn

            copyright_options_row = ft.Row(
                [
                    _make_copyright_option("date",   ft.Icons.CALENDAR_TODAY,    "Date",          "de prise de vue"),
                    _make_copyright_option("filename", ft.Icons.INSERT_DRIVE_FILE, "Nom du fichier",   ""),
                    _make_copyright_option("custom",  ft.Icons.EDIT,              "Personnalisé",  "© Votre nom"),
                ],
                spacing=8,
                alignment=ft.MainAxisAlignment.CENTER,
            )

            def _on_confirm_copyright(e):
                mode = selected_copyright_mode["value"]
                if mode is None:
                    return
                custom_text = copyright_custom_field.value.strip() if mode == "custom" else ""
                if mode == "custom" and not custom_text:
                    copyright_custom_field.error_text = "Requis"
                    page.update()
                    return
                copyright_dlg.open = False
                page.update()
                launch_app(app_name, app_path, is_local, series_name=f"{mode}:© {custom_text}")

            def _on_cancel_copyright(e):
                copyright_dlg.open = False
                page.update()

            copyright_dlg = ft.AlertDialog(
                modal=True,
                title=ft.Text("Ajouter Copyright"),
                content=ft.Column([
                    ft.Text("Quel texte afficher sur les images ?", size=13, color=LIGHT_GREY),
                    ft.Container(height=4),
                    copyright_options_row,
                    ft.Container(height=4),
                    copyright_custom_field,
                ], tight=True, spacing=4, width=350),
                actions=[
                    ft.TextButton("Annuler", on_click=_on_cancel_copyright),
                    ft.TextButton("Appliquer", on_click=_on_confirm_copyright),
                ],
                actions_alignment=ft.MainAxisAlignment.END,
            )
            page.overlay.append(copyright_dlg)
            copyright_dlg.open = True
            page.update()
            return

        if app_name == "Images en PDF.py" and series_name is None:
            _ask_text_before_launch("Nom du PDF", "Nom du PDF", "Ex: Album_Mariage",
                                    app_name, app_path, is_local)
            return

        if app_name == "2 en 1.py" and series_name is None:
            _TWO_IN_ONE_FORMATS = CONSTANTS.TWO_IN_ONE_FORMATS
            two_in_one_dialog = ft.AlertDialog(
                modal=True,
                title=ft.Text("Format 2 en 1"),
                content=None,
            )

            def _pick_two_in_one(val):
                two_in_one_dialog.open = False
                page.update()
                launch_app(app_name, app_path, is_local, series_name=val)

            def on_cancel_two_in_one(e):
                two_in_one_dialog.open = False
                page.update()

            two_in_one_buttons = ft.Column(
                controls=[
                    ft.Container(
                        content=ft.Text(label, size=14, color=HOVER_YELLOW, text_align=ft.TextAlign.CENTER),
                        bgcolor=GREY,
                        border=ft.Border.all(1, HOVER_YELLOW),
                        border_radius=4,
                        padding=ft.Padding(12, 10, 12, 10),
                        width=280,
                        alignment=ft.Alignment(0, 0),
                        ink=True,
                        on_click=lambda e, v=val: _pick_two_in_one(v),
                    )
                    for label, val in _TWO_IN_ONE_FORMATS
                ],
                spacing=6,
                tight=True,
            )
            two_in_one_dialog.content = two_in_one_buttons
            two_in_one_dialog.actions = [ft.TextButton("Annuler", on_click=on_cancel_two_in_one)]
            two_in_one_dialog.actions_alignment = ft.MainAxisAlignment.END
            page.overlay.append(two_in_one_dialog)
            two_in_one_dialog.open = True
            page.update()
            return
        
        if app_name == "Fit 203.py" and series_name is None:
            _FIT_203_FORMATS = CONSTANTS.FIT_203_FORMATS
            fit_203_dialog = ft.AlertDialog(
                modal=True,
                title=ft.Text("Format Fit 203"),
                content=None,
            )

            def _pick_fit_203(val):
                fit_203_dialog.open = False
                page.update()
                launch_app(app_name, app_path, is_local, series_name=val)

            def on_cancel_fit_203(e):
                fit_203_dialog.open = False
                page.update()

            fit_203_buttons = ft.Column(
                controls=[
                    ft.Container(
                        content=ft.Text(label, size=14, color=HOVER_YELLOW, text_align=ft.TextAlign.CENTER),
                        bgcolor=GREY,
                        border=ft.Border.all(1, HOVER_YELLOW),
                        border_radius=4,
                        padding=ft.Padding(12, 10, 12, 10),
                        width=280,
                        alignment=ft.Alignment(0, 0),
                        ink=True,
                        on_click=lambda e, v=f"{crop}|{canvas}|{label.split(' sur ')[-1].replace('×', 'x')}": _pick_fit_203(v),
                    )
                    for label, crop, canvas in _FIT_203_FORMATS
                ],
                spacing=6,
                tight=True,
            )
            fit_203_dialog.content = fit_203_buttons
            fit_203_dialog.actions = [ft.TextButton("Annuler", on_click=on_cancel_fit_203)]
            fit_203_dialog.actions_alignment = ft.MainAxisAlignment.END
            page.overlay.append(fit_203_dialog)
            fit_203_dialog.open = True
            page.update()
            return

        if app_name == "Renommer sequence.py" and series_name is None:
            _ask_text_before_launch("Renommer la série", "Nom de la série", "Ex: Mariage_Martin",
                                    app_name, app_path, is_local)
            return

        if not is_local and not (current_browse_folder["path"] or selected_folder["path"]):
            log_to_terminal("[ERREUR] Veuillez sélectionner un dossier avant de lancer cette application", RED)
            return

        try:
            display_name = app_name[:-4] if app_name.endswith(".pyw") else app_name[:-3]
            log_to_terminal(f"▶ Lancement de {display_name}...", BLUE)
            
            if is_local:
                # Préparer l'environnement pour les apps locales
                env = os.environ.copy()
                env["PYTHONIOENCODING"] = "utf-8"
                env["DATA_PATH"] = os.path.join(app_directory, "Data")
                
                # Naviguer vers le PATH pour order_it gauche/droite (après fin du processus)
                kiosk_target_path = None
                if app_name == "Kiosk gauche.py":
                    kiosk_target_path = CONSTANTS.KIOSK_GAUCHE_DEST
                    if not os.path.isdir(kiosk_target_path):
                        log_to_terminal(f"[AVERTISSEMENT] Le dossier {kiosk_target_path} n'est pas accessible", ORANGE)
                        kiosk_target_path = None

                elif app_name == "Kiosk droite.py":
                    kiosk_target_path = CONSTANTS.KIOSK_DROITE_DEST
                    if not os.path.isdir(kiosk_target_path):
                        log_to_terminal(f"[AVERTISSEMENT] Le dossier {kiosk_target_path} n'est pas accessible", ORANGE)
                        kiosk_target_path = None



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
                    encoding="utf-8",
                    errors="replace",
                    bufsize=1,
                    universal_newlines=True
                )

                # Minimise Dashboard pour laisser la place à l'app lancée
                if app_path.endswith(".pyw"):
                    page.window.minimized = True
                    page.update()

                    def _watch_local(proc=process, nav_path=kiosk_target_path):
                        proc.wait()
                        page.window.minimized = False
                        page.window.maximized = True
                        page.update()
                        if nav_path and os.path.isdir(nav_path):
                            navigate_to_folder(nav_path)

                    threading.Thread(target=_watch_local, daemon=True).start()
                elif kiosk_target_path:
                    def _watch_kiosk(proc=process, nav_path=kiosk_target_path):
                        proc.wait()
                        if os.path.isdir(nav_path):
                            navigate_to_folder(nav_path)

                    threading.Thread(target=_watch_kiosk, daemon=True).start()



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
                env["PYTHONIOENCODING"] = "utf-8"
                env["DATA_PATH"] = os.path.join(app_directory, "Data")
                env["FOLDER_PATH"] = current_browse_folder["path"] or selected_folder["path"]



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



                # Ajouter le dossier pour Transfert vers TEMP.py
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


                # Ajouter les dimensions pour Fit 203.py
                if app_name == "Fit 203.py" and series_name:
                    parts = series_name.split("|")
                    if len(parts) >= 2:
                        env["FIT_203_CROP_SIZE"] = parts[0]
                        env["FIT_203_PRINT_SIZE"] = parts[1]
                    if len(parts) == 3:
                        env["FIT_203_OUTPUT_FOLDER"] = parts[2]


                # Paramètres Copyright
                if app_name == "Copyright.py" and series_name:
                    mode_part, _, custom_part = series_name.partition(":")
                    env["COPYRIGHT_MODE"] = mode_part
                    if mode_part == "custom" and custom_part:
                        env["COPYRIGHT_CUSTOM"] = custom_part


                # (si aucun n'est sélectionné, la variable sera vide)
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
                    app_progress_bar.visible = False
                    try:
                        page.update()
                    except Exception:
                        pass
                    log_to_terminal(f"[OK] {display_name} terminé", GREEN)
                    # Désélectionner les fichiers traités (sauf si le script en a sélectionné de nouveaux)
                    if selected_files and pending_file_selection["names"] is None:
                        page.pubsub.send_all_on_topic("deselect", None)
                    # Rafraîchir la preview pour afficher les nouveaux dossiers/fichiers créés
                    request_refresh()
                
                app_progress_bar.visible = True
                try:
                    page.update()
                except Exception:
                    pass
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
            app_path = app_config[2] if len(app_config) > 2 else os.path.join(app_directory, "Data", app_name)
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
                if app_name == "SidePanel.pyw":
                    on_click_handler = lambda e: _launch_side_panel()
                elif app_name == "Comparaison.pyw":
                    on_click_handler = lambda e: _launch_comparaison()
                else:
                    on_click_handler = lambda e, name=app_name, path=app_path, local=is_local: launch_app(name, path, local)
                display_name = (
                    "Side Panel" if app_name == "SidePanel.pyw"
                    else (app_name[:-4] if app_name.endswith(".pyw") else app_name[:-3])
                )
                items.append(
                    ft.Container(
                        content=ft.Text(
                            display_name,
                            size=14,
                            color=app_color,
                            text_align=ft.TextAlign.CENTER,
                            weight=ft.FontWeight.W_500,
                            max_lines=3,
                        ),
                        expand=True,
                        alignment=ft.Alignment(0, 0),
                        on_click=on_click_handler,
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
        side_panel_path = os.path.join(app_directory, "Data", "SidePanel.pyw")
        fichiers_identiques_path = os.path.join(app_directory, "Data", "Fichiers identiques.py")

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
        copyright_path            = os.path.join(app_directory, "Data", "Copyright.py")
        images_en_pdf_path        = os.path.join(app_directory, "Data", "Images en PDF.py")
        remerciements_path        = os.path.join(app_directory, "Data", "Remerciements.py")
        copier_nefs_path          = os.path.join(app_directory, "Data", "Copier NEFs sélection.py")
        separer_raw_jpg_path      = os.path.join(app_directory, "Data", "Séparer RAW et JPG.py")

        quick_tools_col.controls = [
            _round_button(
                ft.Icons.MANAGE_SEARCH,
                GREEN,
                "Fichiers identiques",
                lambda e: launch_app("Fichiers identiques.py", fichiers_identiques_path, False),
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
                ft.Icons.FOLDER_ZIP,
                ORANGE,
                "Zipper la sélection",
                _prompt_and_zip_selection,
            ),
            _round_button(
                ft.Icons.HIDE_IMAGE,
                YELLOW,
                "Séparer RAW et JPG",
                lambda e: launch_app("Séparer RAW et JPG.py", separer_raw_jpg_path, False),
            ),
            _round_button(
                ft.Icons.IMAGE_SEARCH_OUTLINED,
                YELLOW,
                "Copier NEFs → SELECTION",
                lambda e: launch_app("Copier NEFs sélection.py", copier_nefs_path, False),
            ),
            # _round_button(
            #     ft.Icons.SMART_TOY,
            #     BLUE,
            #     "Envoyer à l'IA",
            #     ai_send_selected_images,
            # ),
            _round_button(
                ft.Icons.NOTE_ADD,
                BLUE,
                "Créer INFO.txt dans le dossier courant",
                _create_and_open_info_txt,
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
            search_query["value"] = ""
            search_field.value = ""
            preview_page["value"] = 0
            _add_to_recent(selected_folder["path"])
            _rebuild_recent_folders_menu()
            refresh_preview()



    async def close_window(e):
        """Ferme la fenêtre principale de l'application de façon asynchrone."""
        await page.window.close()



    def update_app(e):
        """Sauvegarde les fichiers utilisateur, git pull --rebase, vérifie les dépendances si requirements a changé, relance."""
        log_to_terminal("Mise à jour en cours…", YELLOW)
        def _run_update():



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
            for file_name in user_data_filenames:
                file_path = os.path.join(app_directory, file_name)
                if os.path.isfile(file_path):
                    try:
                        with open(file_path, "r", encoding="utf-8") as file_handle:
                            user_data_backups[file_name] = file_handle.read()
                    except Exception:
                        pass



            def _restore_user_data_files():
                for file_name, content in user_data_backups.items():
                    file_path = os.path.join(app_directory, file_name)
                    try:
                        with open(file_path, "w", encoding="utf-8") as file_handle:
                            file_handle.write(content)
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
                    log_to_terminal(f"[ERREUR] Erreur lors de la mise à jour.\n{git_command_output}", RED)
                    return



                # Supprimer le stash (changements de code locaux non désirés)
                if had_local_changes:
                    run_git_command("stash", "drop")



                # Restaurer systématiquement les fichiers utilisateur
                _restore_user_data_files()

                if "Already up to date" in git_command_output or "Déjà à jour" in git_command_output or git_command_output == "":
                    log_to_terminal("[OK] Déjà à jour.", GREEN)
                else:
                    log_to_terminal(f"[OK] Code mis à jour.\n{git_command_output}", GREEN)



                # ── Dépendances : pip uniquement si requirements.txt a changé ──
                requirements_file_path = os.path.join(app_directory, "requirements.txt")
                pip_cache_file_path = os.path.join(app_directory, ".pip_cache.json")
                if not os.path.isfile(requirements_file_path):
                    log_to_terminal("⚠ requirements.txt introuvable, installation ignorée.", YELLOW)
                else:
                    with open(requirements_file_path, "rb") as f:
                        requirements_checksum = hashlib.sha256(f.read()).hexdigest()

                    cached_checksum = None
                    try:
                        with open(pip_cache_file_path, "r", encoding="utf-8") as f:
                            cached_checksum = json.load(f).get("req_hash")
                    except Exception:
                        pass

                    # ── flet + flet-desktop : toujours synchronisés ──────
                    log_to_terminal("🔌 Mise à jour de flet et flet-desktop…", YELLOW)
                    flet_upgrade_proc = subprocess.Popen(
                        [sys.executable, "-m", "pip", "install", "flet", "flet-desktop", "--upgrade"],
                        stdout=subprocess.PIPE,
                        stderr=subprocess.STDOUT,
                        text=True,
                        encoding="utf-8",
                        errors="replace",
                        cwd=app_directory,
                    )
                    for line in flet_upgrade_proc.stdout:
                        line = line.rstrip()
                        if line:
                            log_to_terminal(line, LIGHT_GREY)
                    flet_upgrade_proc.wait()
                    if flet_upgrade_proc.returncode == 0:
                        log_to_terminal("[OK] flet et flet-desktop mis à jour.", GREEN)
                    else:
                        log_to_terminal(f"⚠ flet-desktop : pip a terminé avec le code {flet_upgrade_proc.returncode}.", YELLOW)

                    if cached_checksum == requirements_checksum:
                        log_to_terminal("[OK] Dépendances inchangées, installation ignorée.", GREEN)
                    else:
                        log_to_terminal("📦 Nouvelles dépendances détectées, installation en cours…", YELLOW)
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
                                log_to_terminal(line, LIGHT_GREY)
                        pip_install_process.wait()
                        if pip_install_process.returncode == 0:
                            log_to_terminal("[OK] Dépendances installées.", GREEN)
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
                            log_to_terminal(f"pip a terminé avec le code {pip_install_process.returncode}.", YELLOW)

                # ── Mise à jour d'Ollama ──────────────────────────────────
                log_to_terminal("🤖 Mise à jour d'Ollama...", YELLOW)
                try:
                    ollama_check = subprocess.run(
                        ["ollama", "--version"],
                        capture_output=True, text=True, timeout=5,
                    )
                    if ollama_check.returncode == 0:
                        log_to_terminal(f"[OK] Ollama détecté : {ollama_check.stdout.strip()}", GREEN)
                        tags_resp = subprocess.run(
                            ["ollama", "list"],
                            capture_output=True, text=True, timeout=10,
                        )
                        if tags_resp.returncode == 0:
                            for model_line in tags_resp.stdout.splitlines()[1:]:
                                model_tag = model_line.split()[0] if model_line.split() else ""
                                if model_tag:
                                    log_to_terminal(f"  ⬇️ ollama pull {model_tag}", LIGHT_GREY)
                                    pull_proc = subprocess.Popen(
                                        ["ollama", "pull", model_tag],
                                        stdout=subprocess.PIPE,
                                        stderr=subprocess.STDOUT,
                                        text=True, encoding="utf-8", errors="replace",
                                    )
                                    for pull_line in pull_proc.stdout:
                                        pull_line = pull_line.rstrip()
                                        if pull_line:
                                            log_to_terminal(f"    {pull_line}", LIGHT_GREY)
                                    pull_proc.wait()
                            log_to_terminal("[OK] Modèles Ollama à jour.", GREEN)
                    else:
                        log_to_terminal("[AVERTISSEMENT] Ollama non détecté, ignoré.", YELLOW)
                except FileNotFoundError:
                    log_to_terminal("Ollama non trouvé, tentative d'installation...", YELLOW)
                    try:
                        if sys.platform == "win32":
                            install_script = (
                                "Invoke-WebRequest -Uri 'https://ollama.com/download/OllamaSetup.exe' "
                                "-OutFile '$env:TEMP\\OllamaSetup.exe'; "
                                "Start-Process '$env:TEMP\\OllamaSetup.exe' -Wait"
                            )
                            subprocess.run(
                                ["powershell", "-Command", install_script],
                                timeout=300,
                            )
                        else:
                            subprocess.run(
                                ["sh", "-c", "curl -fsSL https://ollama.com/install.sh | sh"],
                                timeout=300,
                            )
                        subprocess.run(["ollama", "pull", CONSTANTS.AI_MODEL_TEXT], timeout=3600)
                        log_to_terminal("[OK] Ollama installé.", GREEN)
                    except Exception as install_exc:
                        log_to_terminal(f"[AVERTISSEMENT] Impossible d'installer Ollama : {install_exc}", YELLOW)
                        log_to_terminal("[INFO] Installez-le manuellement : https://ollama.com/download", LIGHT_GREY)
                except Exception as ollama_exc:
                    log_to_terminal(f"[AVERTISSEMENT] Ollama : {ollama_exc}", YELLOW)



                # ── Redémarrage automatique ───────────────────────────────
                log_to_terminal("🔄 Redémarrage du Dashboard…", BLUE)
                dashboard_path = os.path.abspath(__file__)
                async def _restart_after_update():
                    import time as _time
                    _time.sleep(0.4)
                    subprocess.Popen([sys.executable, dashboard_path])
                    _time.sleep(0.2)
                    try:
                        await page.window.close()
                    except Exception:
                        pass
                    os._exit(0)
                page.run_task(_restart_after_update)

            except Exception as exc:
                _restore_user_data_files()
                log_to_terminal(f"[ERREUR] {exc}", RED)

        threading.Thread(target=_run_update, daemon=True).start()



# ===================== CONNEXIONS UI ===================== #
    # ── Champ dossier ────────────────────────────────────────────────
    folder_path.on_submit = on_folder_path_submit
    folder_path.on_blur = on_folder_path_blur



    # ── Preview ───────────────────────────────────────────────────────
    sort_segment.on_change = on_sort_change
    select_toggle_button.on_click = toggle_select_all
    invert_selection_button.on_click = invert_selection
    select_same_date_button.on_click = select_same_date
    filter_sel_btn.on_click = _toggle_show_only_selection
    prev_page_btn.on_click = lambda e: go_to_page(-1)
    next_page_btn.on_click = lambda e: go_to_page(+1)



    # ── Recherche preview ─────────────────────────────────────────────
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
    _ai_load_history()
    _initial_drives = _get_removable_drives()
    if _initial_drives:
        removable_drives_state["list"] = _initial_drives
        _rebuild_drives_panel(_initial_drives)
    threading.Thread(target=_poll_removable_drives, daemon=True).start()


    terminal_is_expanded = {"value": False}

    # ── Système d'overlay (IA + Notes simultanés) ──────────────────────────
    # En-tête du panneau IA (gauche)
    ai_clear_button = ft.IconButton(
        icon=ft.Icons.DELETE_SWEEP,
        icon_color=LIGHT_GREY,
        icon_size=16,
        tooltip="Effacer la conversation IA",
        on_click=lambda e: _clear_ai_conversation(),
    )
    ai_folder_select_button = ft.IconButton(
        icon=ft.Icons.AUTO_AWESOME,
        icon_color=YELLOW,
        icon_size=16,
        tooltip="Sélection IA — analyser les images du dossier et copier les meilleures dans SELECTION/",
        on_click=lambda e: _ai_analyze_folder_for_selection(),
    )

    ai_fullscreen_btn = ft.IconButton(
        icon=ft.Icons.FULLSCREEN,
        icon_color=BLUE,
        icon_size=16,
        tooltip="IA seule (prend la place de l'apps_list + terminal) / Restaurer les deux panneaux",
        on_click=lambda e: toggle_ai_fullscreen(),
    )

    ai_panel_header = ft.Row([
        ft.Icon(ft.Icons.SMART_TOY, color=BLUE, size=14),
        ft.Text("IA", color=BLUE, size=11, weight=ft.FontWeight.BOLD),
        ft.Container(width=4),
        ai_model_dropdown,
        ft.Container(width=4),
        ai_status_text,
        ai_stop_button,
        ai_folder_select_button,
        ai_clear_button,
        ai_speaker_button,
        ft.Container(expand=True),
        ai_fullscreen_btn,
    ], spacing=2, vertical_alignment=ft.CrossAxisAlignment.CENTER)

    # En-tête du panneau Notes (droite)
    notepad_clear_button = ft.IconButton(
        icon=ft.Icons.DELETE_SWEEP,
        icon_color=ORANGE,
        icon_size=16,
        tooltip="Effacer tout le bloc-notes",
        on_click=lambda e: _notepad_clear(),
    )

    notepad_fullscreen_btn = ft.IconButton(
        icon=ft.Icons.FULLSCREEN,
        icon_color=VIOLET,
        icon_size=16,
        tooltip="Bloc-notes seul (prend la place de l'apps_list + terminal) / Restaurer les deux panneaux",
        on_click=lambda e: toggle_notepad_fullscreen(),
    )

    notepad_panel_header = ft.Row([
        notepad_header_icon,
        notepad_header_title,
        notepad_clear_button,
        ft.Container(expand=True),
        notepad_fullscreen_btn,
    ], spacing=4, vertical_alignment=ft.CrossAxisAlignment.CENTER)

    overlay_fullscreen = {"mode": None}  # None, "ai", "notepad"

    ai_panel_container = ft.Container(
        content=ft.Row([
            ft.Column([ai_panel_header, ai_container], spacing=4, expand=True),
            ft.Column([
                expand_button_overlay,
                ft.IconButton(
                    icon=ft.Icons.CLOSE,
                    icon_color=RED,
                    icon_size=16,
                    tooltip="Fermer IA & Notes",
                    on_click=lambda e: switch_to_terminal_mode(),
                ),
                ft.IconButton(
                    icon=ft.Icons.COPY_ALL,
                    icon_color=BLUE,
                    icon_size=16,
                    tooltip="Copier la conversation IA",
                    on_click=lambda e: _export_ai_conversation(to_notepad=False),
                ),
                ft.IconButton(
                    icon=ft.Icons.SEND_TO_MOBILE,
                    icon_color=VIOLET,
                    icon_size=16,
                    tooltip="Transférer la conversation vers le bloc-notes",
                    on_click=lambda e: _export_ai_conversation(to_notepad=True),
                ),
            ], alignment=ft.MainAxisAlignment.END, spacing=0),
        ], spacing=4, expand=True, vertical_alignment=ft.CrossAxisAlignment.STRETCH),
        expand=True,
        bgcolor=DARK,
        border=ft.Border.all(1, BLUE),
        border_radius=8,
        padding=5,
    )

    notepad_panel_container = ft.Container(
        content=ft.Row([
            ft.Column([notepad_panel_header, notepad_container], spacing=4, expand=True),
            ft.Column([
                expand_button_notepad,
                ft.IconButton(
                    icon=ft.Icons.HOME,
                    icon_color=VIOLET,
                    icon_size=16,
                    tooltip="Charger la note par défaut (.notes.md)",
                    on_click=lambda e: switch_to_note(),
                ),
                ft.IconButton(
                    icon=ft.Icons.VISIBILITY,
                    icon_color=LIGHT_GREY,
                    icon_size=16,
                    tooltip="Prévisualiser en Markdown",
                    on_click=lambda e: _notepad_toggle_preview(),
                ),
                ft.IconButton(
                    icon=ft.Icons.SAVE_AS,
                    icon_color=BLUE,
                    icon_size=16,
                    tooltip="Sauvegarder les notes sous…",
                    on_click=lambda e: page.run_task(_notepad_save_as),
                ),
            ], alignment=ft.MainAxisAlignment.END, spacing=0),
        ], spacing=4, expand=True, vertical_alignment=ft.CrossAxisAlignment.STRETCH),
        expand=True,
        bgcolor=DARK,
        border=ft.Border.all(1, VIOLET),
        border_radius=8,
        padding=5,
    )

    overlay_container = ft.Container(
        content=ft.Row([
            ai_panel_container,
            notepad_panel_container,
        ], expand=True, spacing=8),
        visible=False,
        bgcolor=BACKGROUND,
        left=0, right=0, top=0, bottom=0,
    )

    # ── Spacer et conteneur solo (mode pleine hauteur gauche) ─────────────────
    # _terminal_spacer : réserve la hauteur du terminal dans la colonne principale.
    # En mode solo, sa hauteur passe à 0 pour que la colonne gauche prenne toute la hauteur.
    _terminal_spacer = ft.Container(height=CONSTANTS.TERMINAL_HEIGHT)

    # _solo_left_container : overlay Stack positionné à gauche, visible uniquement en mode solo.
    # Sa largeur correspond à la colonne apps (expand=6 sur 15) et il couvre la hauteur entière.
    _solo_left_inner     = ft.Column([], expand=True)
    _solo_left_container = ft.Container(
        content=_solo_left_inner,
        visible=False,
        bgcolor=BACKGROUND,
        left=0, top=0, bottom=0,
    )
    _solo_left_state["container"] = _solo_left_container

    def _enter_solo_mode(panel_container, mode_name, do_update=True):
        """Bascule un panneau en mode solo pleine hauteur à gauche."""
        overlay_fullscreen["mode"] = mode_name
        # Repositionner bottom_panel_container en colonne gauche pleine hauteur.
        # On ne déplace pas les widgets (reparenting rompt les événements Flet).
        win_w = page.window.width or CONSTANTS.WINDOW_WIDTH
        bottom_panel_container.width  = int((win_w - 8) * 6 / 15 + 4)
        bottom_panel_container.top    = 0
        bottom_panel_container.right  = None
        bottom_panel_container.height = None
        # Masquer le panneau inactif ; l'actif reste dans overlay_container
        ai_panel_container.visible      = (mode_name == "ai")
        notepad_panel_container.visible = (mode_name == "notepad")
        overlay_container.visible = True
        _terminal_spacer.height = 0
        # Mettre à jour le bouton du panneau actif pour indiquer « réduire »
        _active_btn = ai_fullscreen_btn if mode_name == "ai" else notepad_fullscreen_btn
        _active_btn.icon    = ft.Icons.FULLSCREEN_EXIT
        _active_btn.tooltip = "Réduire / Revenir aux deux panneaux"
        if do_update:
            page.update()

    def _exit_solo_mode(do_update=True):
        """Restaure le mode deux panneaux depuis le mode solo."""
        overlay_fullscreen["mode"] = None
        # Restaurer bottom_panel_container en barre de fond
        bottom_panel_container.top    = None
        bottom_panel_container.right  = 0
        bottom_panel_container.width  = None
        bottom_panel_container.height = (
            page.window.height - CONSTANTS.WDA_HEIGHT
            if terminal_is_expanded["value"]
            else CONSTANTS.TERMINAL_HEIGHT
        )
        ai_panel_container.visible      = True
        notepad_panel_container.visible = True
        _terminal_spacer.height = CONSTANTS.TERMINAL_HEIGHT
        # Restaurer les deux boutons à leur icône d'origine
        ai_fullscreen_btn.icon    = ft.Icons.FULLSCREEN
        ai_fullscreen_btn.tooltip = "IA seule (prend la place de l'apps_list + terminal) / Restaurer les deux panneaux"
        notepad_fullscreen_btn.icon    = ft.Icons.FULLSCREEN
        notepad_fullscreen_btn.tooltip = "Bloc-notes seul (prend la place de l'apps_list + terminal) / Restaurer les deux panneaux"
        if do_update:
            page.update()

    def toggle_ai_fullscreen():
        """Mode solo IA : panel IA pleine hauteur à gauche, preview_list visible à droite."""
        if overlay_fullscreen["mode"] == "ai":
            _exit_solo_mode()
        elif overlay_fullscreen["mode"] == "notepad":
            _exit_solo_mode(do_update=False)
            _enter_solo_mode(ai_panel_container, "ai")
        else:
            _enter_solo_mode(ai_panel_container, "ai")

    def toggle_notepad_fullscreen():
        """Mode solo Bloc-notes : panel notes pleine hauteur à gauche, preview_list visible à droite."""
        if overlay_fullscreen["mode"] == "notepad":
            _exit_solo_mode()
        elif overlay_fullscreen["mode"] == "ai":
            _exit_solo_mode(do_update=False)
            _enter_solo_mode(notepad_panel_container, "notepad")
        else:
            _enter_solo_mode(notepad_panel_container, "notepad")

    def update_overlay_visibility():
        """Affiche ou masque l'overlay (IA à gauche + Notes à droite)."""
        panels_are_open = ai_mode["value"] or note_mode["value"]
        # Nettoyage du mode solo si les panneaux se ferment
        if not panels_are_open and overlay_fullscreen["mode"] in ("ai", "notepad"):
            # Restaurer bottom_panel_container au mode normal
            bottom_panel_container.top    = None
            bottom_panel_container.right  = 0
            bottom_panel_container.width  = None
            bottom_panel_container.height = CONSTANTS.TERMINAL_HEIGHT
            ai_panel_container.visible      = True
            notepad_panel_container.visible = True
            _terminal_spacer.height = CONSTANTS.TERMINAL_HEIGHT
        overlay_container.visible = panels_are_open
        if not panels_are_open:
            overlay_fullscreen["mode"] = None
            ai_panel_container.visible = True
            notepad_panel_container.visible = True
        open_panels_button.icon       = ft.Icons.SMART_TOY
        open_panels_button.icon_color = RED if panels_are_open else BLUE
        open_panels_button.tooltip    = "Fermer IA & Notes" if panels_are_open else "Ouvrir IA & Bloc-notes"

    open_panels_button = ft.IconButton(
        icon=ft.Icons.SMART_TOY,
        tooltip="Ouvrir IA & Bloc-notes",
        icon_color=BLUE,
        icon_size=16,
        on_click=lambda e: toggle_panels_open(),
    )

    def toggle_panels_open():
        if ai_mode["value"] or note_mode["value"]:
            switch_to_terminal_mode()
        else:
            note_target_file["path"] = notes_file_path
            load_notes()
            note_mode["value"] = True
            ai_mode["value"]   = True
            terminal_output.visible  = False
            terminal_cmd_row.visible = False
            update_overlay_visibility()
            terminal_output.update()
            terminal_cmd_row.update()
            try:
                page.update()
            except Exception:
                pass

    bottom_panel_container = ft.Container(
        content=ft.Stack([
            ft.Row([
                ft.Container(
                    content=ft.Row([
                        ft.Column([
                            terminal_output,
                            app_progress_bar,
                            terminal_cmd_row,
                        ], spacing=4, expand=True),
                        ft.Column([
                            expand_button_terminal,
                            open_panels_button,
                            ft.IconButton(
                                icon=ft.Icons.COPY_ALL,
                                tooltip="Copier le terminal",
                                on_click=lambda e: copy_terminal_to_clipboard(),
                                icon_color=BLUE,
                                icon_size=16,
                            ),
                            ft.IconButton(
                                icon=ft.Icons.CLEAR_ALL,
                                tooltip="Effacer le terminal",
                                on_click=clear_terminal,
                                icon_color=RED,
                                icon_size=16,
                            ),
                            ft.IconButton(
                                icon=ft.Icons.SEND,
                                icon_color=GREEN,
                                icon_size=16,
                                tooltip="Envoyer la commande",
                                on_click=on_terminal_command_submit,
                            ),
                        ], alignment=ft.MainAxisAlignment.END, spacing=0),
                    ], spacing=4, expand=True, vertical_alignment=ft.CrossAxisAlignment.STRETCH),
                    expand=True,
                    border=ft.Border.all(1, GREEN),
                    border_radius=8,
                    bgcolor=DARK,
                    padding=5,
                ),
                ft.Row([
                    favorites_panel,
                    drives_panel,
                ], expand=True, spacing=8, vertical_alignment=ft.CrossAxisAlignment.STRETCH),
            ], spacing=8, expand=True),
            overlay_container,
        ]),
        height=CONSTANTS.TERMINAL_HEIGHT,
        bgcolor=BACKGROUND,
        bottom=0,
        left=0,
        right=0,
    )

    def toggle_terminal_overlay():
        terminal_is_expanded["value"] = not terminal_is_expanded["value"]
        is_expanded = terminal_is_expanded["value"]
        bottom_panel_container.height = page.window.height - CONSTANTS.WDA_HEIGHT if is_expanded else CONSTANTS.TERMINAL_HEIGHT
        new_icon    = ft.Icons.EXPAND_MORE if is_expanded else ft.Icons.EXPAND_LESS
        new_tooltip = "Réduire  (Ctrl+↑)" if is_expanded else "Agrandir  (Ctrl+↑)"
        for expand_button in (expand_button_terminal, expand_button_overlay, expand_button_notepad):
            expand_button.icon    = new_icon
            expand_button.tooltip = new_tooltip
        page.update()
        # Réaffirmer la visibilité de l'overlay après le page.update() pour éviter
        # que Flet ne la réinitialise à sa valeur initiale (False) lors du re-render.
        if ai_mode["value"] or note_mode["value"]:
            overlay_container.visible = True
            overlay_container.update()

    expand_button_terminal.on_click = lambda e: toggle_terminal_overlay()
    expand_button_overlay.on_click  = lambda e: toggle_terminal_overlay()
    expand_button_notepad.on_click  = lambda e: toggle_terminal_overlay()

    def _open_bluetooth():
        if not _strip_state["active"]:
            _toggle_strip()
        if platform.system() == "Windows":
            subprocess.Popen(["fsquirt.exe", "/Receive"])
        else:
            subprocess.Popen(["open", "-a", "Bluetooth File Exchange"])


# ── Strip mode (réduction en bandeau pour écrans tactiles) ────────────────────
    _strip_state = {"active": False, "saved_height": CONSTANTS.WINDOW_HEIGHT, "was_maximized": False}
    _main_stack_ref = ft.Ref[ft.Stack]()
    strip_btn = ft.IconButton(
        icon=ft.Icons.UNFOLD_LESS,
        tooltip="Réduire en bandeau (écran tactile)",
        icon_color=LIGHT_GREY,
        bgcolor=DARK,
        icon_size=18,
    )

    def _toggle_strip(e=None):
        stack = _main_stack_ref.current
        is_mac = platform.system() == "Darwin"
        if not _strip_state["active"]:
            _strip_state["was_maximized"] = bool(page.window.maximized)
            _strip_state["saved_height"] = page.window.height or CONSTANTS.WINDOW_HEIGHT
            _strip_state["active"] = True
            # Sur macOS, changer window.height n'a aucun effet si la fenêtre est
            # maximisée : il faut d'abord la dé-maximiser explicitement.
            if is_mac and _strip_state["was_maximized"]:
                page.window.maximized = False
            stack.visible = False
            page.window.height = CONSTANTS.WDA_HEIGHT
            strip_btn.icon = ft.Icons.UNFOLD_MORE
            strip_btn.tooltip = "Restaurer la fenêtre"
            strip_btn.icon_color = BLUE
        else:
            _strip_state["active"] = False
            stack.visible = True
            if is_mac and _strip_state["was_maximized"]:
                page.window.maximized = True
            else:
                page.window.height = _strip_state["saved_height"]
            strip_btn.icon = ft.Icons.UNFOLD_LESS
            strip_btn.tooltip = "Réduire en bandeau (écran tactile)"
            strip_btn.icon_color = LIGHT_GREY
        page.update()

    strip_btn.on_click = _toggle_strip


# ===================== INTERFACE FLET ===================== #
    page.add(

        # ── Dessus ────────────────────────────
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
                ft.Container(
                    content=ft.Row(
                        [
                            ft.IconButton(
                                icon=ft.Icons.PHOTO_LIBRARY,
                                tooltip="Ouvrir le Kiosk",
                                on_click=lambda e: _launch_kiosk_flet(),
                                icon_color=VIOLET,
                                bgcolor=DARK,
                                icon_size=18,
                            ),
                            kiosk_tariff_btn,
                        ],
                        spacing=4,
                        tight=True,
                        vertical_alignment=ft.CrossAxisAlignment.CENTER,
                    ),
                    border=ft.Border.all(1, VIOLET),
                    border_radius=10,
                    padding=ft.Padding(4, 2, 8, 2),
                    margin=ft.Margin(6, 0, 6, 0),
                ),
                ft.IconButton(
                    icon=ft.Icons.VIEW_SIDEBAR,
                    tooltip="Ouvrir le Side Panel",
                    on_click=lambda e: _launch_side_panel(),
                    icon_color=BLUE,
                    bgcolor=DARK,
                    icon_size=18,
                ),
                ft.Container(expand=True),
                folder_path,
                recent_folders_btn,
                ft.IconButton(
                    icon=ft.Icons.FOLDER_OPEN,
                    icon_color=RED,
                    bgcolor=GREY,
                    tooltip="Parcourir…",
                    on_click=pick_folder,
                ),
                ft.IconButton(
                    icon=ft.Icons.REFRESH,
                    icon_color=BLUE,
                    bgcolor=GREY,
                    tooltip="Rafraîchir (Ctrl+R)",
                    on_click=lambda e: refresh_preview(force_reload=True),
                ),
                ft.IconButton(
                    icon=ft.Icons.OPEN_IN_NEW,
                    icon_color=GREEN,
                    bgcolor=GREY,
                    tooltip="Ouvrir l'explorateur",
                    on_click=lambda e: (open_in_file_explorer(current_browse_folder["path"] or selected_folder["path"]), _toggle_strip() if not _strip_state["active"] else None),
                ),
                ft.IconButton(
                    icon=ft.Icons.BLUETOOTH,
                    icon_color=ft.Colors.LIGHT_BLUE_300,
                    bgcolor=GREY,
                    tooltip="Recevoir un fichier via Bluetooth",
                    on_click=lambda e: _open_bluetooth(),
                ),

                ft.Container(expand=True),
                strip_btn,
                ft.IconButton(
                    icon=ft.Icons.MINIMIZE, on_click=lambda e: setattr(page.window, 'minimized', True),),
                ft.IconButton(
                    icon=ft.Icons.FULLSCREEN,
                    on_click=lambda e: (setattr(page.window, 'maximized', not page.window.maximized), page.update()),
                    tooltip="Maximiser / Restaurer",
                ),
                ft.IconButton(ft.Icons.CLOSE, on_click=close_window),
            ])
        ),
        ft.Stack([
            ft.Column([
            ft.Divider(),
            ft.Row([
                ft.Column([

                    # ── Zone gauche ────────────────────────────
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

                    # ── Apps ────────────────────────────
                    ft.Row([
                        ft.Container(
                            content=apps_list,
                            expand=True,
                            border=ft.Border.all(1, GREY),
                            border_radius=8,
                            bgcolor=DARK,
                            padding=ft.Padding(8, 8, 8, 8),
                        ),
                        ft.Container(
                            content=ft.ListView(
                                controls=[quick_tools_col],
                                expand=True,
                                auto_scroll=False,
                            ),
                            bgcolor=DARK,
                            border=ft.Border.all(1, GREY),
                            border_radius=8,
                            padding=ft.Padding.symmetric(vertical=8, horizontal=4),
                            width=56,
                        ),
                    ], expand=True, spacing=8),
                ], expand=6),
                ft.Column([

                    # ── Zone droite ────────────────────────────
                    ft.Row([
                        ft.Text("Contenu du dossier", weight=ft.FontWeight.BOLD, size=14, color=WHITE, margin=ft.Margin.only(left=10)),
                        ft.IconButton(
                            icon=ft.Icons.ARROW_UPWARD,
                            tooltip="Dossier parent",
                            on_click=go_to_parent_folder,
                            icon_color=BLUE,
                            icon_size=20,
                        ),
                        filter_sel_btn,
                        select_toggle_button,
                        invert_selection_button,
                        select_same_date_button,
                        ft.IconButton(
                            icon=ft.Icons.DELETE_SWEEP,
                            tooltip="Supprimer les fichiers sélectionnés",
                            on_click=delete_selected_files,
                            icon_color=RED,
                            icon_size=20,
                        ),
                        ft.Container(expand=True),
                        file_count_text,
                        ft.Container(width=4),
                        prev_page_btn,
                        page_indicator_text,
                        next_page_btn,
                    ], spacing=5, vertical_alignment=ft.CrossAxisAlignment.CENTER, height=36),
                    ft.Container(
                        content=ft.Row([
                        search_active_row,
                        selection_count_text,
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
                        padding=ft.Padding(0, 5, 0, 0), # Ajustement pour aligner le dessus avec les zones à gauche 
                    ),

                    # ── Preview list (droite) ────────────────────────────
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
            _terminal_spacer,
        ], expand=True, spacing=8),
        bottom_panel_container,
        _solo_left_container,
        ], expand=True, ref=_main_stack_ref),
    )

    if CONSTANTS.MAXIMIZED:
        async def _delayed_maximize():
            await asyncio.sleep(0.15)
            page.window.maximized = True
            page.update()
        page.run_task(_delayed_maximize)



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

ft.run(main, assets_dir="assets")
