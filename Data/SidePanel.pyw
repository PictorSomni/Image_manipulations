# -*- coding: utf-8 -*-
"""
Side Panel — App compacte (demi-écran) avec quatre onglets :

  Onglet 1 · Fichiers
    Prévisualisation d'un dossier source avec sélection par checkbox,
    filtres, tri et barre de recherche (identiques à Dashboard).
    Copie les fichiers sélectionnés vers un dossier de destination
    (avec création optionnelle d'un sous-dossier nommé).

  Onglet 2 · Liste
    Lecture / écriture d'un fichier .json contenant des entrées
    {nom, description}. Recherche et tri comme dans Dashboard.
    Cliquer sur un nom ou une description le copie dans le presse-papiers.
    Ajout, édition et suppression d'entrées.

Peut être lancé indépendamment ou depuis Dashboard.pyw.
"""

__version__ = "3.1.0"

# ==============================================================================
# TABLE DES MATIÈRES — SidePanel.pyw
# ==============================================================================
# 1. IMPORTS ........................................................ ~L 24
# 2. CONSTANTES ..................................................... ~L 44
# 3. FONCTIONS UTILITAIRES .......................................... ~L 62
# 4. INTERFACE PRINCIPALE main() .................................... ~L 80
#    4.1  Couleurs .................................................. ~L 82
#    4.2  Propriétés fenêtre ........................................ ~L 96
#    4.3  Config persistante ........................................ ~L 106
#    4.4  État partagé & données .................................... ~L 144
#    4.5  ██  Fonctions — Onglet 1 (Fichiers) ...................... ~L 549
#    4.6  ██  Fonctions — Onglet 2 (JSON) .......................... ~L 1495
#    4.7  ██  Fonctions — Onglet 3 (Bloc-notes) .................... ~L 1914
#    4.8  ██  Fonctions — Onglet 4 (IA) ............................ ~L 2025
#    4.9  Fenêtre & événements ...................................... ~L 3308
#    4.10 Construction de l'interface ............................... ~L 3341
#    4.11 Initialisation ............................................ ~L 3662
# ==============================================================================


#############################################################
#                          IMPORTS                          #
#############################################################
import flet as ft
import flet_code_editor as fce
import os
import shutil
import threading
import json
import re
import platform
import subprocess
import sys
import asyncio
import datetime
import concurrent.futures
import time
import base64
import urllib.request
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import CONSTANTS
import thumb_cache
import mcp_client
import credentials


#############################################################
#                         CONSTANTS                         #
#############################################################
_IMAGE_EXTS   = CONSTANTS.IMAGE_EXTS
_NOTEPAD_EXTS = CONSTANTS.NOTEPAD_EXTS

def _is_os_junk(entry):
    return CONSTANTS.is_os_junk(entry.name, entry.is_dir())


from ai_tools import (
    _fetch_url_content, _web_search, _ollama_chat_once, _ollama_chat_stream,
    _ollama_chat_stream_with_tools, _gemini_chat_stream_with_tools,
    _parse_text_tool_calls, _strip_text_tool_calls,
    _format_ai_conversation, _folder_tool_definitions, _gemini_tool_definitions, _folder_list_contents,
    _folder_read_file, _folder_create_file, _folder_delete_files, _folder_move_file,
    _folder_copy_file, _folder_create_folder, _resolve_path,
    _folder_read_exif, _folder_zip_files, _folder_unzip_file,
    _encode_image_for_analysis, _analyze_images_batched, _take_screenshot,
    _score_images_batched, _copy_scored_photos,
    _gemini_generate_image, _gemini_refine_image_prompt, _gemini_generate_music,
    _WEB_TOOLS, _TERMINAL_TOOLS, _MEMORY_TOOLS, _SCREENSHOT_TOOLS, _NOTEPAD_TOOLS,
    _UI_TOOLS, _run_terminal_command,
    _EDIT_TOOLS, _READ_LINES_TOOLS, _SEARCH_TOOLS, _GIT_TOOLS, _TASK_TOOLS, _PDF_TOOLS, _SUBAGENT_TOOLS, _SCHEDULE_TOOLS,
    _HTTP_TOOLS, _SPREADSHEET_TOOLS, _PYAUTOGUI_TOOLS, _SSH_TOOLS,
    _edit_file, _read_file_lines, _search_in_files, _find_files, _git_command, _manage_tasks, _read_pdf,
    _ask_subagent, _schedule_task, _http_request, _read_spreadsheet, _ssh_command,
    _mouse_click, _keyboard_type, _keyboard_hotkey,
    _is_network_error,
    _update_memory_file, _build_system_content,
    _gemini_tts_stream, _gemini_live_tts_stream,
    _MicRecorder, _gemini_transcribe_audio,
    _claude_chat_stream_with_tools,
    _md_dark,
    _compact_history_summary,
    _ai_save_history as _ai_save_history_fn,
    _ensure_ollama_ready as _ensure_ollama_ready_fn,
)
#############################################################
#                           MAIN                            #
#############################################################
def main(page: ft.Page):

    # ─── Couleurs ────────────────────────────────────────────────────────
    DARK         = CONSTANTS.COLOR_DARK
    BACKGROUND   = CONSTANTS.COLOR_BACKGROUND
    GREY         = CONSTANTS.COLOR_GREY
    LIGHT_GREY   = CONSTANTS.COLOR_LIGHT_GREY
    BLUE         = CONSTANTS.COLOR_BLUE
    VIOLET       = CONSTANTS.COLOR_VIOLET
    GREEN        = CONSTANTS.COLOR_GREEN
    YELLOW       = CONSTANTS.COLOR_YELLOW
    HOVER_YELLOW = CONSTANTS.COLOR_HOVER_YELLOW
    ORANGE       = CONSTANTS.COLOR_ORANGE
    RED          = CONSTANTS.COLOR_RED
    WHITE        = CONSTANTS.COLOR_WHITE

    # Rôles sémantiques (voir CONSTANTS §3bis) : la couleur = un sens.
    ICON_NEUTRAL = CONSTANTS.ICON_NEUTRAL
    ICON_ACTION  = CONSTANTS.ICON_ACTION
    ICON_DANGER  = CONSTANTS.ICON_DANGER
    ICON_LAUNCH  = CONSTANTS.ICON_LAUNCH
    ICON_WARN    = CONSTANTS.ICON_WARN

    # Fond clair par défaut de flutter_markdown pour le code/blockquote,
    # illisible avec le texte blanc du thème sombre : on le recolore.
    AI_MD_STYLE = ft.MarkdownStyleSheet(
        code_text_style=ft.TextStyle(bgcolor=DARK, color=WHITE),
        codeblock_decoration=ft.BoxDecoration(bgcolor=DARK, border=ft.Border.all(1, BLUE), border_radius=5),
        blockquote_decoration=ft.BoxDecoration(bgcolor=DARK, border=ft.Border.all(1, BLUE), border_radius=5),
        blockquote_text_style=ft.TextStyle(color=WHITE),
        p_text_style=ft.TextStyle(size=CONSTANTS.TERMINAL_FONT_SIZE),
    )

    # ─── Propriétés fenêtre ──────────────────────────────────────────────
    page.title       = "Side Panel"
    page.theme_mode  = ft.ThemeMode.DARK
    page.bgcolor     = BACKGROUND
    page.window.title_bar_hidden         = True
    page.window.title_bar_buttons_hidden = True
    page.window.width  = 1024
    page.window.height = 960
    page.run_task(page.window.to_front)

    # ─── Chemins config ──────────────────────────────────────────────────
    app_dir             = os.path.dirname(os.path.abspath(__file__))
    config_file         = os.path.join(app_dir, ".sidepanel_config.json")
    _shared_recent_file = os.path.join(app_dir, ".recent_folders.json")  # partagé avec Dashboard

    # ─── Config persistante ──────────────────────────────────────────────
    def _load_config() -> dict:
        try:
            with open(config_file, "r", encoding="utf-8") as file_handle:
                return json.load(file_handle)
        except Exception:
            return {}

    def _save_config(config: dict):
        try:
            with open(config_file, "w", encoding="utf-8") as file_handle:
                json.dump(config, file_handle, ensure_ascii=False, indent=2)
        except Exception:
            pass

    config_data = _load_config()

    # ─── Dossiers récents partagés avec Dashboard ─────────────────────────
    def _load_recent_shared() -> list:
        try:
            with open(_shared_recent_file, "r", encoding="utf-8") as file_handle:
                loaded_data = json.load(file_handle)
            return [path for path in loaded_data if isinstance(path, str) and os.path.isdir(path)]
        except Exception:
            return []

    def _save_recent_shared(folders: list):
        try:
            with open(_shared_recent_file, "w", encoding="utf-8") as file_handle:
                json.dump(folders[:10], file_handle, ensure_ascii=False, indent=2)
        except Exception:
            pass

    # ─────────────────────────────────────────────────────────────────────
    #  ██████████  État  ──  Onglet 1 (Fichiers)
    # ─────────────────────────────────────────────────────────────────────
    current_src      = {"path": None}
    selected_files   = set()
    sort_mode        = {"value": 0}         # 0=A→Z  1=Z→A  2=Date
    all_entries      = {"list": [], "error": ""}
    search_query     = {"value": ""}
    refresh_token    = {"value": 0}
    PAGE_SIZE        = 60
    preview_page     = {"value": 0}
    recent_src_list  = {"data": _load_recent_shared()}
    file_filter_active = {"value": False}   # afficher uniquement la sélection
    print_counts     = {"data": {}}   # filepath → int (nb d'impressions, défaut 1)
    print_formats    = {"data": {}}   # filepath → clé format (CONSTANTS.FORMATS)
    count_text_refs  = {"data": {}}   # filepath → ft.Text widget du compteur
    checkbox_refs    = {"data": {}}   # filepath → ft.Checkbox widget
    _sp_thumb_cache        = {}  # {normpath: bytes} — miniatures déjà lues (accélère les retours liste)
    _sp_pending_thumb_refs = {}  # {normpath: (ft.Container, file_path)}
    _sp_thumb_token        = {"value": 0}  # Incrémenté à chaque changement de dossier

    # ─────────────────────────────────────────────────────────────────────
    #  ██████████  État  ──  Onglet 2 (Liste JSON)
    # ─────────────────────────────────────────────────────────────────────
    json_path        = {"value": config_data.get("json_path", os.path.join(app_dir, ".liste.json"))}
    json_entries     = {"list": []}
    list_sort_mode   = {"value": 2}         # 0=A→Z  1=Z→A  2=Récent
    list_search_query    = {"value": ""}
    recent_json_list    = {"data": [path for path in config_data.get("recent_json", []) if isinstance(path, str) and os.path.isfile(path)]}
    list_selected_items = {"data": set()}   # entrées cochées (filtre)
    list_done_items     = {"data": set()}   # entrées marquées "faites"
    list_filter_active  = {"value": False}  # afficher uniquement la sélection

    # ─────────────────────────────────────────────────────────────────────
    #  ██████████  État  ──  Onglet 3 (Bloc-notes)
    # ─────────────────────────────────────────────────────────────────────
    note_target_file     = {"path": os.path.normpath(os.path.join(app_dir, "..", ".notes.md"))}
    notepad_is_preview   = {"value": False}

    # ───────────────────────────────────────────────────────────────────
    #  ██████████  État  ──  Onglet 4 (IA)
    # ───────────────────────────────────────────────────────────────────
    ai_history_file_path  = os.path.normpath(os.path.join(app_dir, "..", ".ai_conversation.json"))
    ai_conversation    = []
    ai_history_compaction_state = {"summary": "", "summarized_count": 0}
    ai_streaming       = {"value": False}
    ollama_process     = {"proc": None}
    ai_pending_images  = []
    ai_pending_files   = []

    # ═════════════════════════════════════════════════════════════════════
    #  ██  Identifiants
    # ═════════════════════════════════════════════════════════════════════
    def get_or_ask_credential(service, username, timeout=300):
        """
        Retourne le mot de passe stocké pour (service, username) via le
        coffre natif de l'OS (Data/credentials.py). S'il n'existe pas,
        ouvre une boîte de dialogue pour le saisir (masqué) et l'enregistre
        pour les prochains appels. Renvoie None si l'utilisateur annule.
        """
        existing = credentials.get_credential(service, username)
        if existing is not None:
            return existing

        _cred_event = threading.Event()
        _cred_result = {"value": None}

        password_field = ft.TextField(
            label=f"Mot de passe pour {username}@{service}",
            password=True,
            can_reveal_password=True,
            autofocus=True,
            width=360,
            on_submit=lambda e: _on_cred_confirm(e),
        )

        def _on_cred_confirm(e=None):
            value = password_field.value or ""
            if value:
                credentials.set_credential(service, username, value)
                _cred_result["value"] = value
            _cred_dlg.open = False
            try:
                page.update()
            except Exception:
                pass
            _cred_event.set()

        def _on_cred_cancel(e=None):
            _cred_dlg.open = False
            try:
                page.update()
            except Exception:
                pass
            _cred_event.set()

        _cred_dlg = ft.AlertDialog(
            modal=True,
            title=ft.Text(f"🔐 Identifiant requis : {service}"),
            content=ft.Column(
                [
                    ft.Text(f"Aucun mot de passe enregistré pour {username}@{service}.", size=13),
                    password_field,
                ],
                tight=True, width=360,
            ),
            actions=[
                ft.TextButton("Annuler", on_click=_on_cred_cancel),
                ft.Button("Enregistrer", bgcolor=BLUE, color=WHITE, on_click=_on_cred_confirm),
            ],
            actions_alignment=ft.MainAxisAlignment.END,
        )
        page.overlay.append(_cred_dlg)
        _cred_dlg.open = True
        try:
            page.update()
        except Exception:
            pass
        _cred_event.wait(timeout=timeout)
        return _cred_result["value"]

    # ═════════════════════════════════════════════════════════════════════
    #  ██  Helpers persistance
    # ═════════════════════════════════════════════════════════════════════
    def _persist():
        _save_config({
            "dst_path":    dst_path_field.value or "",
            "json_path":   json_path["value"] or "",
            "recent_json": recent_json_list["data"],
        })

    def _add_recent_src(folder_path: str):
        recent_list = _load_recent_shared()
        folder_path = os.path.normpath(folder_path)
        if folder_path in recent_list:
            recent_list.remove(folder_path)
        recent_list.insert(0, folder_path)
        recent_list = recent_list[:10]
        _save_recent_shared(recent_list)
        recent_src_list["data"] = recent_list

    def _add_recent_json(json_file_path: str):
        json_file_path = os.path.normpath(json_file_path)
        recent_list = [existing for existing in recent_json_list["data"] if existing != json_file_path]
        recent_list.insert(0, json_file_path)
        recent_json_list["data"] = recent_list[:10]
        _persist()
        _rebuild_recent_json_menu()

    def _rebuild_recent_json_menu():
        recent_list = recent_json_list["data"]
        if not recent_list:
            recent_json_btn.items = [
                ft.PopupMenuItem(content=ft.Text("Aucun fichier récent"))
            ]
        else:
            recent_json_btn.items = [
                ft.PopupMenuItem(
                    content=ft.Row(
                        [ft.Icon(ft.Icons.DATA_OBJECT, size=16),
                         ft.Text(os.path.basename(path) or path)],
                        spacing=8, tight=True,
                    ),
                    on_click=lambda event, path=path: _open_json_in_list(path),
                )
                for path in recent_list
            ]
        try:
            recent_json_btn.update()
        except Exception:
            pass

    def _load_list_states():
        """Charge les états (sélection / faits) pour le fichier JSON courant."""
        config    = _load_config()
        all_states = config.get("list_states", {})
        path   = json_path["value"]
        state_entry  = all_states.get(path, {})
        list_selected_items["data"] = set(state_entry.get("selected", []))
        list_done_items["data"]     = set(state_entry.get("done", []))

    def _save_list_states():
        """Persiste les états (sélection / faits) pour le fichier JSON courant."""
        config    = _load_config()
        all_states = config.get("list_states", {})
        path   = json_path["value"]
        if path:
            all_states[path] = {
                "selected": list(list_selected_items["data"]),
                "done":     list(list_done_items["data"]),
            }
        config["list_states"] = all_states
        _save_config(config)


    # ═════════════════════════════════════════════════════════════════════
    #  ██  Éléments UI — Onglet 1
    # ═════════════════════════════════════════════════════════════════════

    src_path_field = ft.TextField(
        hint_text="Dossier source...",
        border_color=BLUE,
        text_size=13, height=36,
        content_padding=ft.Padding(8, 2, 8, 2),
        bgcolor=DARK, expand=True,
    )
    recent_src_btn = ft.PopupMenuButton(
        icon=ft.Icons.HISTORY,
        icon_color=LIGHT_GREY,
        tooltip="Sources récentes",
        items=[],
    )
    file_count_text      = ft.Text("", size=13, color=LIGHT_GREY)
    selection_count_text = ft.Text("", size=13, color=BLUE)

    file_filter_btn = ft.IconButton(
        icon=ft.Icons.FILTER_LIST,
        icon_color=LIGHT_GREY,
        icon_size=20,
        tooltip="Afficher uniquement la sélection",
    )
    select_toggle_btn = ft.IconButton(
        icon=ft.Icons.SELECT_ALL, icon_color=VIOLET,
        icon_size=20, tooltip="Tout sélectionner",
    )
    invert_btn = ft.IconButton(
        icon=ft.Icons.PUBLISHED_WITH_CHANGES, icon_color=VIOLET,
        icon_size=20, tooltip="Inverser la sélection",
    )

    sort_segment = ft.CupertinoSlidingSegmentedButton(
        selected_index=0, bgcolor=GREY, thumb_color=DARK,
        controls=[
            ft.Text("A→Z",  size=11, color=WHITE),
            ft.Text("Z→A",  size=11, color=WHITE),
            ft.Text("Date", size=11, color=WHITE),
        ],
        tooltip="Tri",
    )

    search_field = ft.TextField(
        hint_text="Rechercher...", border_color=BLUE,
        text_size=13, height=32, width=200,
        content_padding=ft.Padding(8, 2, 8, 2),
        prefix_icon=ft.Icons.SEARCH, bgcolor=DARK,
    )
    search_close_btn = ft.IconButton(
        icon=ft.Icons.CLOSE, icon_color=LIGHT_GREY, icon_size=16,
        style=ft.ButtonStyle(padding=ft.Padding.all(4)),
    )

    prev_page_btn = ft.IconButton(
        icon=ft.Icons.CHEVRON_LEFT, icon_size=18,
        icon_color=DARK, bgcolor=YELLOW,
        visible=False, hover_color=HOVER_YELLOW,
        tooltip="Page précédente",
    )
    next_page_btn = ft.IconButton(
        icon=ft.Icons.CHEVRON_RIGHT, icon_size=18,
        icon_color=DARK, bgcolor=YELLOW,
        visible=False, hover_color=HOVER_YELLOW,
        tooltip="Page suivante",
    )
    page_indicator = ft.Text("", size=12, color=LIGHT_GREY)

    preview_list = ft.ListView(expand=True, auto_scroll=False, spacing=4)
    preview_loading = ft.Container(
        content=ft.Row([
            ft.ProgressRing(width=16, height=16, stroke_width=2, color=BLUE),
            ft.Text("Chargement...", size=12, color=LIGHT_GREY),
        ], spacing=8, alignment=ft.MainAxisAlignment.CENTER),
        alignment=ft.Alignment(0, 0),
        expand=True, visible=False,
    )

    dst_path_field = ft.TextField(
        value=config_data.get("dst_path", ""),
        hint_text="Dossier de destination...",
        border_color=GREEN,
        text_size=13, height=36,
        content_padding=ft.Padding(8, 2, 8, 2),
        bgcolor=DARK, expand=True,
    )
    status_text = ft.Text("", size=12, color=LIGHT_GREY, expand=True)
    copy_btn = ft.Container(
        content=ft.Row([
            ft.Icon(ft.Icons.CONTENT_COPY, size=16, color=DARK),
            ft.Text("Copier la sélection", size=13, color=DARK,
                    weight=ft.FontWeight.BOLD),
        ], spacing=6, tight=True),
        bgcolor=GREEN, border_radius=6,
        padding=ft.Padding(12, 8, 12, 8),
        ink=True, tooltip="Copier les fichiers sélectionnés vers la destination",
    )
    copy_progress = ft.ProgressBar(
        color=GREEN, bgcolor=GREY,
        value=None,   # indéterminé (infini)
        visible=False,
        height=4,
    )


    # ═════════════════════════════════════════════════════════════════════
    #  ██  Éléments UI — Onglet 2
    # ═════════════════════════════════════════════════════════════════════

    json_path_field = ft.TextField(
        value=json_path["value"],
        hint_text="Fichier .json...",
        border_color=VIOLET, text_size=13, height=36,
        content_padding=ft.Padding(8, 2, 8, 2),
        bgcolor=DARK, expand=True,
    )
    recent_json_btn = ft.PopupMenuButton(
        icon=ft.Icons.HISTORY,
        icon_color=LIGHT_GREY,
        tooltip="Fichiers JSON récents",
        items=[],
    )
    list_search_field = ft.TextField(
        hint_text="Rechercher...", border_color=VIOLET,
        text_size=13, height=32, width=200,
        content_padding=ft.Padding(8, 2, 8, 2),
        prefix_icon=ft.Icons.SEARCH, bgcolor=DARK,
    )
    list_sort_segment = ft.CupertinoSlidingSegmentedButton(
        selected_index=2, bgcolor=GREY, thumb_color=DARK,
        controls=[
            ft.Text("A→Z",    size=11, color=WHITE),
            ft.Text("Z→A",    size=11, color=WHITE),
            ft.Text("Récent", size=11, color=WHITE),
        ],
        tooltip="Tri",
    )
    list_view   = ft.ListView(expand=True, auto_scroll=False, spacing=4)
    list_status = ft.Text("", size=12, color=LIGHT_GREY)
    list_count  = ft.Text("", size=12, color=LIGHT_GREY)
    filter_sel_btn = ft.IconButton(
        icon=ft.Icons.FILTER_LIST,
        icon_color=LIGHT_GREY,
        icon_size=20,
        tooltip="Afficher uniquement la sélection",
    )
    deselect_all_list_btn = ft.IconButton(
        icon=ft.Icons.DESELECT,
        icon_color=LIGHT_GREY,
        icon_size=20,
        tooltip="Désélectionner tout",
    )


    # ═════════════════════════════════════════════════════════════════════
    #  ██  Éléments UI — Onglet 3 (Bloc-notes)
    # ═════════════════════════════════════════════════════════════════════

    notepad_field = fce.CodeEditor(
        text_style=ft.TextStyle(font_family="monospace", size=CONSTANTS.TERMINAL_FONT_SIZE),
        language=getattr(fce.CodeLanguage, CONSTANTS.NOTEPAD_DEFAULT_LANGUAGE),
        code_theme=fce.CodeTheme.ATOM_ONE_DARK,
        gutter_style=fce.GutterStyle(width=56),
        expand=True,
    )
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
    notepad_preview_btn = ft.IconButton(
        icon=ft.Icons.VISIBILITY,
        icon_color=LIGHT_GREY,
        icon_size=18,
        tooltip="Prévisualiser en Markdown",
    )


    # ═══════════════════════════════════════════════════════════════════
    #  ██  Éléments UI — Onglet 4 (IA)
    # ═══════════════════════════════════════════════════════════════════

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
    ai_status_text  = ft.Text("", color=LIGHT_GREY, size=11, italic=True, max_lines=1, overflow=ft.TextOverflow.ELLIPSIS)
    ai_progress_bar = ft.ProgressBar(value=None, visible=False, color=BLUE, height=2)
    ai_stop_button     = ft.IconButton(
        icon=ft.Icons.STOP_CIRCLE,
        icon_color=LIGHT_GREY,
        icon_size=16,
        tooltip="Libérer le modèle (ollama stop)",
    )
    ai_attach_row   = ft.Row([], spacing=4, visible=False, wrap=True)
    ai_attach_button   = ft.IconButton(
        icon=ft.Icons.ATTACH_FILE,
        icon_color=LIGHT_GREY,
        icon_size=18,
        tooltip="Joindre une image ou un document",
    )
    ai_send_button     = ft.IconButton(
        icon=ft.Icons.SEND,
        icon_color=BLUE,
        icon_size=18,
        tooltip="Envoyer",
    )
    # Dictée vocale : cliquer pour démarrer, recliquer pour arrêter + transcrire
    _mic_state = {"rec": None, "active": False}
    ai_mic_button = ft.IconButton(
        icon=ft.Icons.MIC_NONE,
        icon_color=LIGHT_GREY,
        icon_size=20,
        tooltip="Cliquer pour dicter (Gemini) — recliquer pour arrêter",
        on_click=lambda e: _mic_toggle(),
    )
    ai_tts_enabled = {"value": CONSTANTS.AI_VOICE_TTS_ENABLED}
    ai_tts_stop_event = {"event": None}
    ai_speaker_button  = ft.IconButton(
        icon=ft.Icons.VOLUME_UP if CONSTANTS.AI_VOICE_TTS_ENABLED else ft.Icons.VOLUME_OFF,
        icon_color=CONSTANTS.COLOR_BLUE if CONSTANTS.AI_VOICE_TTS_ENABLED else CONSTANTS.COLOR_LIGHT_GREY,
        icon_size=18,
        tooltip="Désactiver la lecture vocale" if CONSTANTS.AI_VOICE_TTS_ENABLED else "Activer la lecture vocale",
        visible=CONSTANTS.AI_VOICE_TTS_BTN_VISIBLE,
    )
    ai_clear_button    = ft.IconButton(
        icon=ft.Icons.DELETE_SWEEP,
        icon_color=LIGHT_GREY,
        icon_size=16,
        tooltip="Effacer la conversation IA",
    )
    ai_copy_button     = ft.IconButton(
        icon=ft.Icons.COPY_ALL,
        icon_color=LIGHT_GREY,
        icon_size=16,
        tooltip="Copier la conversation IA",
    )


    # ═════════════════════════════════════════════════════════════════════
    #  ██  Fonctions — Onglet 1
    # ═════════════════════════════════════════════════════════════════════

    def _selection_label():
        count = len(selected_files)
        if count == 0:
            return ""
        return f"{count} fichier{'s' if count > 1 else ''} sélectionné{'s' if count > 1 else ''}"

    def _update_toggle_btn(update_control=True):
        if search_query["value"]:
            query_lower = search_query["value"].lower()
            filtered_paths = {
                fpath for (_name, fpath, is_dir, _is_img, _ext) in all_entries["list"]
                if not is_dir and query_lower in _name.lower()
            }
            all_filtered_selected = bool(filtered_paths) and filtered_paths.issubset(selected_files)
        else:
            all_filtered_selected = bool(selected_files)

        if all_filtered_selected:
            select_toggle_btn.icon       = ft.Icons.DESELECT
            select_toggle_btn.icon_color = ORANGE
            select_toggle_btn.tooltip    = "Désélectionner tout"
        else:
            select_toggle_btn.icon       = ft.Icons.SELECT_ALL
            select_toggle_btn.icon_color = VIOLET
            select_toggle_btn.tooltip    = "Tout sélectionner"
        if update_control:
            try:
                select_toggle_btn.update()
            except Exception:
                pass



    def _on_checkbox_change(event, path):
        if event.control.value:
            selected_files.add(path)
        else:
            selected_files.discard(path)
        selection_count_text.value = _selection_label()
        _update_toggle_btn(update_control=False)
        page.update()

    def _render_preview():
        checkbox_refs["data"].clear()
        count_text_refs["data"].clear()
        _sp_pending_thumb_refs.clear()
        try:
            entries = all_entries["list"]
            if search_query["value"]:
                search_lower = search_query["value"].lower()
                entries = [entry for entry in entries if search_lower in entry[0].lower()]

            if file_filter_active["value"]:
                entries = [entry for entry in entries if entry[1] in selected_files]

            total_entries = len(entries)
            total_pages = max(1, (total_entries + PAGE_SIZE - 1) // PAGE_SIZE)
            current_page_index      = min(preview_page["value"], total_pages - 1)
            preview_page["value"] = current_page_index

            controls = []

            if all_entries["error"]:
                controls.append(ft.Text(all_entries["error"], color=RED))
            elif not entries:
                if current_src["path"]:
                    controls.append(
                        ft.Text("(dossier vide)", color=LIGHT_GREY,
                                text_align=ft.TextAlign.CENTER)
                    )
            else:
                page_start = current_page_index * PAGE_SIZE
                page_end   = min(page_start + PAGE_SIZE, total_entries)
                for filename, file_path, is_directory, is_image, file_extension in entries[page_start:page_end]:
                    # Icône selon type
                    if is_directory:
                        icon_name, icon_color = ft.Icons.FOLDER, ft.Colors.AMBER_400
                    elif is_image:
                        icon_name, icon_color = ft.Icons.IMAGE, ft.Colors.GREEN_400
                    elif file_extension == ".pdf":
                        icon_name, icon_color = ft.Icons.PICTURE_AS_PDF, ft.Colors.RED_400
                    elif file_extension == ".zip":
                        icon_name, icon_color = ft.Icons.FOLDER_ZIP, ORANGE
                    elif file_extension in {".txt", ".md", ".log"}:
                        icon_name, icon_color = ft.Icons.DESCRIPTION, ft.Colors.BLUE_GREY_400
                    else:
                        icon_name, icon_color = ft.Icons.INSERT_DRIVE_FILE, ft.Colors.BLUE_GREY_400

                    checkbox = ft.Checkbox(
                        border_side=ft.BorderSide(color=BLUE),
                        value=file_path in selected_files,
                        on_change=lambda event, p=file_path: _on_checkbox_change(event, p),
                    )
                    checkbox_refs["data"][file_path] = checkbox

                    if is_image and not is_directory:
                        norm_path = os.path.normpath(file_path)
                        cached_b64 = _sp_thumb_cache.get(norm_path)
                        if cached_b64:
                            thumb_content = ft.Image(
                                src=cached_b64,
                                fit=ft.BoxFit.COVER,
                                width=64, height=64,
                                error_content=ft.Icon(icon_name, color=icon_color, size=21),
                            )
                        else:
                            thumb_content = ft.Icon(icon_name, color=icon_color, size=21)
                        thumb_container = ft.Container(
                            content=thumb_content,
                            width=64, height=64,
                            border_radius=4,
                            bgcolor=DARK if not cached_b64 else None,
                            clip_behavior=ft.ClipBehavior.ANTI_ALIAS,
                            on_click=lambda e, p=file_path: _show_fullscreen_preview(p),
                            tooltip="Prévisualiser en plein écran",
                            ink=True,
                        )
                        visual = thumb_container
                        if not cached_b64:
                            _sp_pending_thumb_refs[norm_path] = (thumb_container, file_path)
                    else:
                        visual = ft.Icon(icon_name, color=icon_color, size=21)

                    if is_image and not is_directory:
                        print_count   = print_counts["data"].get(file_path, 0)
                        format_value = print_formats["data"].get(file_path, "")
                        format_dropdown = ft.Dropdown(
                            value=format_value or None,
                            hint_text="Format",
                            options=[ft.dropdown.Option(key=key, text=key)
                                     for key in CONSTANTS.FORMATS.keys()],
                            on_select=lambda event, p=file_path: _set_format(p, event.control.value or ""),
                            text_size=11, height=32, width=112,
                            content_padding=ft.Padding(8, 0, 8, 0),
                            bgcolor=DARK, border_color=GREY,
                        )

                        count_label = ft.Text(
                            str(print_count) if print_count > 0 else "·",
                            size=11,
                            color=YELLOW if print_count > 0 else LIGHT_GREY,
                            text_align=ft.TextAlign.CENTER,
                            weight=ft.FontWeight.BOLD,
                        )
                        count_text_refs["data"][file_path] = count_label

                        minus_btn = ft.Container(
                            content=ft.Text(
                                "−",
                                size=13,
                                color=DARK if print_count > 0 else LIGHT_GREY,
                                text_align=ft.TextAlign.CENTER,
                                weight=ft.FontWeight.BOLD,
                            ),
                            width=26,
                            height=26,
                            bgcolor=ORANGE if print_count > 0 else GREY,
                            border_radius=ft.BorderRadius(4, 0, 0, 4),
                            alignment=ft.Alignment(0, 0),
                            on_click=(lambda event, p=file_path: _dec_count(p)) if print_count > 0 else None,
                            ink=print_count > 0,
                            tooltip="Moins d'impressions" if print_count > 0 else "",
                        )

                        count_display = ft.Container(
                            content=count_label,
                            width=22,
                            height=26,
                            bgcolor=DARK,
                            alignment=ft.Alignment(0, 0),
                        )

                        plus_btn = ft.Container(
                            content=ft.Text(
                                "+",
                                size=13,
                                color=DARK,
                                text_align=ft.TextAlign.CENTER,
                                weight=ft.FontWeight.BOLD,
                            ),
                            width=26,
                            height=26,
                            bgcolor=GREEN,
                            border_radius=ft.BorderRadius(0, 4, 4, 0),
                            alignment=ft.Alignment(0, 0),
                            on_click=lambda event, p=file_path: _inc_count(p),
                            ink=True,
                            tooltip="Plus d'impressions",
                        )

                        print_controls = ft.Row(
                            [minus_btn, count_display, plus_btn],
                            spacing=0,
                            tight=True,
                        )

                        extra_controls = [
                            print_controls,
                            format_dropdown,
                        ]
                    else:
                        extra_controls = []

                    filename_text = ft.Text(
                        filename,
                        size=13 if (is_image and not is_directory) else 16,
                        color=WHITE,
                        max_lines=1,
                        overflow=ft.TextOverflow.ELLIPSIS,
                    )

                    controls.append(
                        ft.Container(
                            content=ft.Row(
                                [
                                    checkbox,
                                    visual,
                                    ft.Container(content=filename_text, expand=True),
                                ] + extra_controls,
                                spacing=8,
                                vertical_alignment=ft.CrossAxisAlignment.CENTER,
                            ),
                            padding=ft.Padding(left=8, top=2, right=8, bottom=2),
                            ink=True,
                            ink_color=GREY,
                            on_click=lambda event, p=file_path, d=is_directory, ex=file_extension: _navigate(p) if d else _open_json_in_list(p) if ex == ".json" else _open_file_in_notepad(p) if ex in _NOTEPAD_EXTS else None,
                        )
                    )

            preview_list.controls.clear()
            preview_list.controls.extend(controls)
            preview_loading.visible = False

            # Pagination
            if total_entries > PAGE_SIZE:
                prev_page_btn.visible  = current_page_index > 0
                next_page_btn.visible  = current_page_index < total_pages - 1
                page_indicator.value   = (
                    f"{current_page_index * PAGE_SIZE + 1}-"
                    f"{min((current_page_index + 1) * PAGE_SIZE, total_entries)}/{total_entries}"
                )
            else:
                prev_page_btn.visible = False
                next_page_btn.visible = False
                page_indicator.value  = ""

            _update_toggle_btn(update_control=False)
            _update_file_filter_btn(update_control=False)
            page.update()
            _sp_start_thumb_loader()
        except Exception as render_exception:
            status_text.value = f"[ERREUR] Rendu: {render_exception}"
            preview_loading.visible = False
            preview_list.controls.clear()
            preview_list.controls.append(
                ft.Text(
                    f"Erreur de rendu: {render_exception}",
                    color=RED,
                    size=13,
                )
            )
            page.update()

    def _sp_start_thumb_loader():
        """Lance un thread qui génère les miniatures manquantes pour la page courante."""
        if not _sp_pending_thumb_refs:
            return
        pending_snapshot = list(_sp_pending_thumb_refs.items())
        load_token = _sp_thumb_token["value"]

        def _load():
            for norm_path, (container, file_path) in pending_snapshot:
                if _sp_thumb_token["value"] != load_token:
                    return
                b64 = thumb_cache.get_or_generate(file_path)
                if b64 and _sp_thumb_token["value"] == load_token:
                    _sp_thumb_cache[norm_path] = b64
                    container.bgcolor = None
                    container.content = ft.Image(
                        src=b64,
                        fit=ft.BoxFit.COVER,
                        width=64, height=64,
                    )

                    async def _apply():
                        try:
                            page.update()
                        except Exception:
                            pass

                    page.run_task(_apply)

        threading.Thread(target=_load, daemon=True).start()

    def _navigate(path):
        if not path or not os.path.isdir(path):
            return
        current_src["path"]          = path
        src_path_field.value         = path
        selected_files.clear()
        selection_count_text.value   = ""
        preview_page["value"]        = 0
        _sp_thumb_token["value"]     += 1
        _sp_pending_thumb_refs.clear()
        _add_recent_src(path)
        _rebuild_recent_src_menu()
        search_query["value"]       = ""
        search_field.value           = ""
        if file_filter_active["value"]:
            file_filter_active["value"] = False
            _update_file_filter_btn()
        _refresh_preview()

    def _refresh_preview(reset_page=True):
        if reset_page:
            preview_page["value"] = 0
        refresh_token["value"] += 1
        current_token = refresh_token["value"]
        preview_list.controls.clear()
        file_count_text.value   = ""
        folder = current_src["path"]
        preview_loading.visible = bool(folder)
        page.update()

        def _background_scan():
            entries_list = []
            file_count_label      = ""
            error_message          = ""
            if folder:
                try:
                    with os.scandir(folder) as scanner:
                        raw_entries = [scan_entry for scan_entry in scanner if not _is_os_junk(scan_entry)]
                    file_count = sum(1 for scan_entry in raw_entries if not scan_entry.is_dir())
                    file_count_label = f"({file_count} fichier{'s' if file_count > 1 else ''})"
                    if sort_mode["value"] == 2:
                        sorted_entries = sorted(raw_entries, key=lambda scan_entry: (not scan_entry.is_dir(), -scan_entry.stat().st_mtime))
                    elif sort_mode["value"] == 1:
                        sorted_entries = sorted(raw_entries, key=lambda scan_entry: (not scan_entry.is_dir(), scan_entry.name.lower()), reverse=True)
                    else:
                        sorted_entries = sorted(raw_entries, key=lambda scan_entry: (not scan_entry.is_dir(), scan_entry.name.lower()))
                    for scan_entry in sorted_entries:
                        file_extension    = os.path.splitext(scan_entry.name)[1].lower()
                        is_image = file_extension in _IMAGE_EXTS
                        entries_list.append(
                            (scan_entry.name, scan_entry.path, scan_entry.is_dir(), is_image, file_extension)
                        )
                except PermissionError:
                    error_message = "⚠️ Accès refusé à ce dossier"
                except Exception as exception:
                    error_message = f"⚠️ Erreur: {exception}"

            async def _apply_results():
                if refresh_token["value"] != current_token:
                    return
                all_entries["list"]  = entries_list
                all_entries["error"] = error_message
                file_count_text.value = file_count_label
                preview_loading.visible = False
                _render_preview()

            page.run_task(_apply_results)

        threading.Thread(target=_background_scan, daemon=True).start()


    def _rebuild_recent_src_menu():
        recent_list = _load_recent_shared()
        recent_src_list["data"] = recent_list
        if not recent_list:
            recent_src_btn.items = [
                ft.PopupMenuItem(content=ft.Text("Aucun dossier récent"))
            ]
        else:
            recent_src_btn.items = [
                ft.PopupMenuItem(
                    content=ft.Row(
                        [ft.Icon(ft.Icons.FOLDER, size=16),
                         ft.Text(os.path.basename(path) or path)],
                        spacing=8, tight=True,
                    ),
                    on_click=lambda event, path=path: _navigate(path),
                )
                for path in recent_list
            ]
        try:
            recent_src_btn.update()
        except Exception:
            pass

    # ── Sélection ────────────────────────────────────────────────────────
    def _select_all(event=None):
        entries = all_entries["list"]
        if search_query["value"]:
            query_lower = search_query["value"].lower()
            entries = [entry for entry in entries if query_lower in entry[0].lower()]
        for _, file_path, is_directory, _, _ in entries:
            if not is_directory:
                selected_files.add(file_path)
        selection_count_text.value = _selection_label()
        _render_preview()
        _update_toggle_btn()

    def _clear_selection(event=None):
        selected_files.clear()
        selection_count_text.value = ""
        if file_filter_active["value"]:
            file_filter_active["value"] = False
        _render_preview()
        _update_toggle_btn()

    def _toggle_all(event):
        if search_query["value"]:
            query_lower = search_query["value"].lower()
            filtered_paths = {
                file_path for (_name, file_path, is_directory, _is_image, _ext) in all_entries["list"]
                if not is_directory and query_lower in _name.lower()
            }
            if not filtered_paths.issubset(selected_files):
                _select_all()
            else:
                _clear_selection()
        else:
            if selected_files:
                _clear_selection()
            else:
                _select_all()

    def _send_selection_to_ai(event=None):
        """Joint les images/documents sélectionnés à la conversation IA (onglet IA)."""
        if not selected_files:
            return
        image_paths = [p for p in selected_files if os.path.splitext(p)[1].lower() in _IMAGE_EXTS]
        doc_paths = [p for p in selected_files if os.path.splitext(p)[1].lower() in _AI_DOCUMENT_EXTS]
        if not image_paths and not doc_paths:
            return
        for image_path in image_paths:
            _ai_attach_image(image_path)
        for doc_path in doc_paths:
            _ai_attach_document_file(doc_path)
        _clear_selection()
        tabs.selected_index = 3
        try:
            tabs.update()
        except Exception:
            pass

    def _invert(event):
        entries = all_entries["list"]
        for _, file_path, is_directory, _, _ in entries:
            if is_directory:
                continue
            if file_path in selected_files:
                selected_files.discard(file_path)
            else:
                selected_files.add(file_path)
        selection_count_text.value = _selection_label()
        _render_preview()
        _update_toggle_btn()

    def _toggle_file_filter(event):
        file_filter_active["value"] = not file_filter_active["value"]
        _update_file_filter_btn()
        _render_preview()

    def _update_file_filter_btn(update_control=True):
        selected_count = len(selected_files)
        if file_filter_active["value"]:
            file_filter_btn.icon_color = BLUE
            file_filter_btn.tooltip    = f"Filtre actif ({selected_count} sélectionné(s)) — cliquer pour afficher tout"
        else:
            file_filter_btn.icon_color = VIOLET if selected_count else LIGHT_GREY
            file_filter_btn.tooltip    = f"Afficher uniquement la sélection ({selected_count} sélectionné(s))"
        if update_control:
            try:
                file_filter_btn.update()
            except Exception:
                pass

    def _dec_count(path):
        current_count = print_counts["data"].get(path, 0)
        if current_count > 0:
            new_count = current_count - 1
            print_counts["data"][path] = new_count
            count_widget = count_text_refs["data"].get(path)
            if count_widget:
                count_widget.value = str(new_count) if new_count > 0 else "·"
                count_widget.color = YELLOW if new_count > 0 else LIGHT_GREY
                count_widget.update()

    def _inc_count(path):
        current_count = print_counts["data"].get(path, 0)
        new_count = current_count + 1
        print_counts["data"][path] = new_count
        count_widget = count_text_refs["data"].get(path)
        if count_widget:
            count_widget.value = str(new_count)
            count_widget.color = YELLOW
            count_widget.update()

    def _set_format(path, value):
        if value:
            print_formats["data"][path] = value
        else:
            print_formats["data"].pop(path, None)

    # ── Tri / Recherche ──────────────────────────────────────────────────
    def _on_sort_change(event):
        sort_mode["value"] = event.control.selected_index
        _refresh_preview()

    def _on_search_change(event):
        search_text = (search_field.value or "").strip()
        if not search_text:
            _clear_search(event)
            return
        if file_filter_active["value"]:
            file_filter_active["value"] = False
            _update_file_filter_btn()
        search_query["value"]  = search_text
        preview_page["value"]  = 0
        _render_preview()

    def _clear_search(event=None):
        search_query["value"] = ""
        search_field.value = ""
        preview_page["value"] = 0
        _render_preview()
        _update_toggle_btn()
        page.update()

    def _go_to_page(delta):
        total_entries       = len(all_entries["list"])
        total_pages = max(1, (total_entries + PAGE_SIZE - 1) // PAGE_SIZE)
        new_page_index      = max(0, min(preview_page["value"] + delta, total_pages - 1))
        if new_page_index == preview_page["value"]:
            return
        preview_page["value"] = new_page_index
        _render_preview()
        async def _scroll_top():
            await preview_list.scroll_to(offset=0, duration=0)
        page.run_task(_scroll_top)

    def _go_parent(event):
        if current_src["path"]:
            parent = os.path.dirname(current_src["path"])
            if parent and parent != current_src["path"]:
                _navigate(parent)

    def _open_in_explorer(event):
        folder = current_src["path"]
        if not folder or not os.path.isdir(folder):
            return
        try:
            if platform.system() == "Windows":
                subprocess.Popen(f'explorer "{folder}"')
            elif platform.system() == "Darwin":
                subprocess.Popen(["open", folder])
            else:
                subprocess.Popen(["xdg-open", folder])
        except Exception:
            pass

    # ── Aperçu plein écran ─────────────────────────────────────────────────
    def _show_fullscreen_preview(file_path: str):
        """Prévisualisation plein écran — PageView + InteractiveViewer (zoom/pan) + sélection + impression."""
        # Construire la liste des images navigables (recherche/filtre actifs respectés)
        entries = all_entries["list"]
        if search_query["value"]:
            query_lower = search_query["value"].lower()
            entries = [entry for entry in entries if query_lower in entry[0].lower()]
        if file_filter_active["value"]:
            entries = [entry for entry in entries if entry[1] in selected_files]
        else:
            page_start  = preview_page["value"] * PAGE_SIZE
            entries     = entries[page_start : page_start + PAGE_SIZE]
        image_paths = [fpath for (_name, fpath, is_dir, is_img, _ext) in entries if is_img and not is_dir]
        if not image_paths:
            return

        initial_index = image_paths.index(file_path) if file_path in image_paths else 0
        state = {"index": initial_index}
        _prev_keyboard_handler = page.on_keyboard_event
        _blank_gif = "data:image/gif;base64,R0lGODlhAQABAAD/ACwAAAAAAQABAAACADs="

        def _resolve_fullscreen_source(image_path: str) -> str:
            """Retourne une source sûre pour le plein écran.

            Si une URI base64 de miniature est fournie par erreur, on force
            l'utilisation du chemin image original.
            """
            if isinstance(image_path, str) and image_path.startswith("data:image"):
                return _cur()
            return image_path

        def _cur() -> str:
            return image_paths[state["index"]]

        def close_preview(e=None):
            page.on_keyboard_event = _prev_keyboard_handler
            if fs_overlay in page.overlay:
                page.overlay.remove(fs_overlay)
            for fpath, cb in checkbox_refs["data"].items():
                cb.value = fpath in selected_files
            for fpath, count_widget in count_text_refs["data"].items():
                current_count = print_counts["data"].get(fpath, 0)
                count_widget.value = str(current_count)
            selection_count_text.value = _selection_label()
            _update_toggle_btn(update_control=False)
            _update_file_filter_btn(update_control=False)
            page.update()

        # ── Barre de titre ────────────────────────────────────────────────
        fs_title = ft.Text(
            os.path.basename(file_path),
            size=14, color=WHITE,
            weight=ft.FontWeight.W_500,
            max_lines=1,
            overflow=ft.TextOverflow.ELLIPSIS,
            expand=True,
        )
        fs_counter = ft.Text(
            f"{initial_index + 1} / {len(image_paths)}",
            size=12, color=ft.Colors.WHITE70,
        )

        # ── Contrôles barre inférieure ────────────────────────────────────
        fs_checkbox = ft.Checkbox(
            value=file_path in selected_files,
            label="Sélectionner",
            label_style=ft.TextStyle(color=WHITE, size=13),
            active_color=BLUE,
            check_color=DARK,
        )

        def _on_fs_check(e):
            p = _cur()
            if e.control.value:
                selected_files.add(p)
            else:
                selected_files.discard(p)

        fs_checkbox.on_change = _on_fs_check

        fs_format = ft.Dropdown(
            value=print_formats["data"].get(file_path) or None,
            hint_text="Format",
            options=[
                ft.dropdown.Option(key="", text="— aucun —"),
            ] + [ft.dropdown.Option(key=k, text=k) for k in CONSTANTS.FORMATS.keys()],
            text_size=13, height=40, width=132,
            content_padding=ft.Padding(8, 0, 8, 0),
            bgcolor=GREY, border_color=BLUE,
        )

        def _on_fs_format(e):
            p = _cur()
            val = e.control.value or ""
            if val:
                print_formats["data"][p] = val
            else:
                print_formats["data"].pop(p, None)

        fs_format.on_select = _on_fs_format

        fs_count = ft.Text(
            str(print_counts["data"].get(file_path, 0)),
            size=26, color=WHITE,
            weight=ft.FontWeight.BOLD,
            width=50, text_align=ft.TextAlign.CENTER,
        )

        def _fs_dec(e=None):
            p = _cur()
            cur = print_counts["data"].get(p, 0)
            if cur > 0:
                print_counts["data"][p] = cur - 1
                fs_count.value = str(cur - 1)
                fs_count.update()

        def _fs_inc(e=None):
            p = _cur()
            cur = print_counts["data"].get(p, 0)
            print_counts["data"][p] = cur + 1
            fs_count.value = str(cur + 1)
            fs_count.update()

        # ── Chargement lazy ───────────────────────────────────────────────
        page_image_controls: dict = {}
        pages_loaded: set = set()

        def _build_page_containers():
            win_w = page.window.width or 1024
            win_h = (page.window.height or 960) - 50  # soustraire hauteur barre titre
            containers = []
            for idx in range(len(image_paths)):
                img_ctrl = ft.Image(
                    src=_blank_gif,
                    width=win_w,
                    height=win_h,
                    fit=ft.BoxFit.CONTAIN,
                    gapless_playback=True,
                    error_content=ft.Container(
                        content=ft.Icon(ft.Icons.BROKEN_IMAGE, color=LIGHT_GREY, size=64),
                        alignment=ft.Alignment(0, 0),
                    ),
                )
                page_image_controls[idx] = img_ctrl
                viewer = ft.InteractiveViewer(
                    key=f"fs_iv_{idx}",
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
                        bgcolor=DARK,
                    )
                )
            return containers

        def _load_image_for_index(load_index: int) -> None:
            if load_index < 0 or load_index >= len(image_paths):
                return
            if load_index in pages_loaded:
                return
            pages_loaded.add(load_index)
            if load_index in page_image_controls:
                page_image_controls[load_index].src = _resolve_fullscreen_source(image_paths[load_index])

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

        def _update_bar(new_index: int) -> None:
            state["index"] = new_index
            p = image_paths[new_index] if image_paths else ""
            fs_title.value = os.path.basename(p)
            fs_counter.value = f"{new_index + 1} / {len(image_paths)}"
            fs_checkbox.value = p in selected_files
            fs_format.value = print_formats["data"].get(p) or None
            fs_count.value = str(print_counts["data"].get(p, 0))
            page.update()

        def on_page_change(e) -> None:
            new_index = int(e.data)
            _update_bar(new_index)
            _load_pages_around(new_index)

        # ── PageView ou fallback ──────────────────────────────────────────
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
            win_w = page.window.width or 1024
            win_h = (page.window.height or 960) - 50
            _fb_img_ctrl = ft.Image(
                src=_blank_gif,
                width=win_w, height=win_h,
                fit=ft.BoxFit.CONTAIN,
                gapless_playback=True,
                error_content=ft.Container(
                    content=ft.Icon(ft.Icons.BROKEN_IMAGE, color=LIGHT_GREY, size=64),
                    alignment=ft.Alignment(0, 0),
                ),
            )
            page_image_controls[initial_index] = _fb_img_ctrl
            _fb_iv = ft.InteractiveViewer(
                key="fs_iv_fb",
                content=_fb_img_ctrl,
                min_scale=0.5, max_scale=10.0,
                pan_enabled=True, scale_enabled=True,
                width=win_w, height=win_h,
                clip_behavior=ft.ClipBehavior.HARD_EDGE,
            )
            images_page_view = ft.Container(
                content=_fb_iv,
                expand=True,
                alignment=ft.Alignment(0, 0),
                bgcolor=DARK,
            )

            def _fb_navigate(new_idx: int) -> None:
                old_idx = state["index"]
                _fb_img_ctrl.src = _resolve_fullscreen_source(image_paths[new_idx]) if image_paths else _blank_gif
                page_image_controls.clear()
                page_image_controls[new_idx] = _fb_img_ctrl
                pages_loaded.discard(old_idx)
                pages_loaded.add(new_idx)

        # ── Navigation ────────────────────────────────────────────────────
        async def navigate_prev(e=None) -> None:
            if not image_paths or state["index"] <= 0:
                return
            if _HAS_PAGE_VIEW:
                await images_page_view.previous_page(
                    animation_curve=ft.AnimationCurve.EASE_IN_OUT_CUBIC_EMPHASIZED,
                    animation_duration=ft.Duration(milliseconds=300),
                )
            else:
                new_idx = state["index"] - 1
                _fb_navigate(new_idx)
                _update_bar(new_idx)

        async def navigate_next(e=None) -> None:
            if not image_paths or state["index"] >= len(image_paths) - 1:
                return
            if _HAS_PAGE_VIEW:
                await images_page_view.next_page(
                    animation_curve=ft.AnimationCurve.EASE_IN_OUT_CUBIC_EMPHASIZED,
                    animation_duration=ft.Duration(milliseconds=300),
                )
            else:
                new_idx = state["index"] + 1
                _fb_navigate(new_idx)
                _update_bar(new_idx)

        def on_fs_key(event: ft.KeyboardEvent):
            if event.key in ("Arrow Left", "ArrowLeft"):
                page.run_task(navigate_prev, event)
            elif event.key in ("Arrow Right", "ArrowRight"):
                page.run_task(navigate_next, event)
            elif event.key in ("Arrow Up", "ArrowUp"):
                p = _cur()
                new_val = p not in selected_files
                if new_val:
                    selected_files.add(p)
                else:
                    selected_files.discard(p)
                fs_checkbox.value = new_val
                fs_checkbox.update()
            elif event.key == "Escape":
                close_preview()

        page.on_keyboard_event = on_fs_key

        # ── Barre flottante ───────────────────────────────────────────────
        bottom_bar = ft.Container(
            content=ft.Row([
                ft.IconButton(
                    icon=ft.Icons.CHEVRON_LEFT,
                    icon_color=WHITE, icon_size=36,
                    tooltip="Image précédente (←)",
                    on_click=lambda e: page.run_task(navigate_prev, e),
                    style=ft.ButtonStyle(padding=ft.Padding.all(4)),
                ),
                ft.Container(width=4),
                fs_checkbox,
                ft.Container(width=8),
                ft.Container(
                    content=fs_format,
                    padding=ft.Padding(0, 0, 0, 4),
                ),
                ft.Container(width=8),
                ft.IconButton(
                    icon=ft.Icons.REMOVE_CIRCLE_OUTLINE,
                    icon_color=RED, icon_size=32,
                    tooltip="Retirer une copie",
                    on_click=_fs_dec,
                    style=ft.ButtonStyle(padding=ft.Padding.all(4)),
                ),
                fs_count,
                ft.IconButton(
                    icon=ft.Icons.ADD_CIRCLE_OUTLINE,
                    icon_color=GREEN, icon_size=32,
                    tooltip="Ajouter une copie",
                    on_click=_fs_inc,
                    style=ft.ButtonStyle(padding=ft.Padding.all(4)),
                ),
                ft.Container(width=4),
                ft.IconButton(
                    icon=ft.Icons.CHEVRON_RIGHT,
                    icon_color=WHITE, icon_size=36,
                    tooltip="Image suivante (→)",
                    on_click=lambda e: page.run_task(navigate_next, e),
                    style=ft.ButtonStyle(padding=ft.Padding.all(4)),
                ),
            ], vertical_alignment=ft.CrossAxisAlignment.CENTER, tight=True),
            bgcolor=ft.Colors.with_opacity(0.80, GREY),
            border_radius=16,
            padding=ft.Padding(8, 6, 8, 6),
        )

        fs_overlay = ft.Container(
            content=ft.Stack([
                ft.Column([
                    ft.Container(
                        content=ft.Row([
                            ft.Container(width=8),
                            fs_title,
                            fs_counter,
                            ft.Container(width=8),
                            ft.IconButton(
                                icon=ft.Icons.CLOSE,
                                icon_color=RED, icon_size=28,
                                tooltip="Fermer (Échap)",
                                on_click=close_preview,
                                style=ft.ButtonStyle(bgcolor=DARK),
                            ),
                        ], vertical_alignment=ft.CrossAxisAlignment.CENTER),
                        bgcolor=DARK,
                        padding=ft.Padding(8, 4, 8, 4),
                        height=50,
                    ),
                    images_page_view,
                ], spacing=0, expand=True),
                ft.Container(
                    content=ft.Row(
                        [bottom_bar],
                        alignment=ft.MainAxisAlignment.CENTER,
                    ),
                    bottom=16, left=0, right=0,
                ),
            ], expand=True),
            bgcolor=DARK,
            expand=True,
        )

        page.overlay.append(fs_overlay)
        page.update()
        _load_pages_around(initial_index)


    async def _pick_src(event):
        folder = await ft.FilePicker().get_directory_path(
            dialog_title="Dossier source (images)"
        )
        if folder:
            _navigate(os.path.normpath(folder))

    async def _pick_dst(event):
        # save_file permet de créer un nouveau dossier sur macOS (bouton natif)
        # On pré-remplit le nom de fichier avec un placeholder ; on extrait ensuite
        # le dossier parent du chemin retourné.
        path = await ft.FilePicker().save_file(
            dialog_title="Choisir le dossier de destination",
            file_name="Sélectionner ce dossier",
        )
        if path:
            folder = os.path.dirname(os.path.normpath(path))
            dst_path_field.value = folder
            dst_path_field.update()
            _persist()
            _copy_selection(None)  # copie automatique dès que la destination est choisie

    # ── Copie & opérations sur fichiers ───────────────────────────────────
    def _on_status(topic, message):
        status_text.value = message
        page.update()

    page.pubsub.subscribe_topic("sel_status", _on_status)

    def _copy_selection(event):
        if not selected_files:
            status_text.value = "⚠️ Aucun fichier sélectionné"
            page.update()
            return
        destination_base = (dst_path_field.value or "").strip()
        if not destination_base or not os.path.isdir(destination_base):
            status_text.value = "⚠️ Dossier de destination invalide"
            page.update()
            return
        destination_folder = destination_base
        files_snapshot   = list(selected_files)
        counts_snapshot  = dict(print_counts["data"])
        formats_snapshot = dict(print_formats["data"])
        total_files = len(files_snapshot)
        copy_progress.visible = True
        status_text.value = f"[...] Copie de {total_files} fichier(s)..."
        page.update()

        def _perform_copy():
            try:
                os.makedirs(destination_folder, exist_ok=True)
            except Exception as exception:
                async def _report_copy_error():
                    copy_progress.visible = False
                    page.pubsub.send_all_on_topic("sel_status", f"[ERREUR] Création dossier: {exception}")
                page.run_task(_report_copy_error)
                return
            success_count, errors = 0, []
            for source_file in files_snapshot:
                if not os.path.isfile(source_file):
                    errors.append(f"{os.path.basename(source_file)}: introuvable")
                    continue
                original_stem, file_extension = os.path.splitext(os.path.basename(source_file))
                print_count = counts_snapshot.get(source_file, 0)
                format_key   = formats_snapshot.get(source_file, "")
                if print_count or format_key:
                    prefix_parts = []
                    if print_count:
                        prefix_parts.append(f"{print_count}X")
                    if format_key:
                        prefix_parts.append(format_key)
                    destination_stem = "_".join(prefix_parts) + "_" + original_stem
                else:
                    destination_stem = original_stem
                destination_path = os.path.join(destination_folder, destination_stem + file_extension)
                if os.path.exists(destination_path):
                    collision_index = 1
                    while os.path.exists(destination_path):
                        destination_path = os.path.join(destination_folder, f"{destination_stem} ({collision_index}){file_extension}")
                        collision_index += 1
                try:
                    shutil.copy2(source_file, destination_path)
                    success_count += 1
                except Exception as exception:
                    errors.append(f"{os.path.basename(source_file)}: {exception}")
            destination_label = os.path.basename(destination_folder) or destination_folder
            status_message = f"[OK] {success_count}/{total_files} copié(s) → {destination_label}"
            if errors:
                status_message += f"  |  {len(errors)} erreur(s)"
            async def _finalize_copy():
                copy_progress.visible = False
                page.pubsub.send_all_on_topic("sel_status", status_message)
            page.run_task(_finalize_copy)

        threading.Thread(target=_perform_copy, daemon=True).start()


    # ═════════════════════════════════════════════════════════════════════
    #  ██  Fonctions — Onglet 2
    # ═════════════════════════════════════════════════════════════════════

    def _load_json_list() -> list:
        path = json_path["value"]
        if not path or not os.path.isfile(path):
            return []
        try:
            with open(path, "r", encoding="utf-8") as file_handle:
                loaded_data = json.load(file_handle)
            if isinstance(loaded_data, list):
                result = []
                for item in loaded_data:
                    if isinstance(item, dict):
                        result.append({
                            "nom":         str(item.get("nom", "")),
                            "description": str(item.get("description", "")),
                        })
                return result
        except Exception:
            pass
        return []

    def _save_json_list():
        """Sauvegarde manuelle (bouton) — affiche un message de confirmation."""
        path = json_path["value"]
        if not path:
            list_status.value = "⚠️ Aucun fichier sélectionné"
            page.update()
            return
        try:
            with open(path, "w", encoding="utf-8") as file_handle:
                json.dump(json_entries["list"], file_handle, ensure_ascii=False, indent=2)
            list_status.value = "[OK] Sauvegardé"
        except Exception as exception:
            list_status.value = f"[ERREUR] {exception}"
        page.update()

    def _autosave():
        """Sauvegarde silencieuse après chaque ajout/édition/suppression."""
        path = json_path["value"]
        if not path:
            return
        try:
            with open(path, "w", encoding="utf-8") as file_handle:
                json.dump(json_entries["list"], file_handle, ensure_ascii=False, indent=2)
        except Exception as exception:
            list_status.value = f"[ERREUR] Autosave: {exception}"
            page.update()
        _save_list_states()

    def _copy_to_clipboard(text: str):
        try:
            page.set_clipboard(text)
            text_preview = text[:50] + ("..." if len(text) > 50 else "")
            list_status.value = f"[OK] Copié : {text_preview}"
        except Exception:
            # Fallback système
            try:
                if platform.system() == "Windows":
                    subprocess.Popen(["clip"], stdin=subprocess.PIPE).communicate(
                        text.encode("utf-16")
                    )
                elif platform.system() == "Darwin":
                    subprocess.Popen(["pbcopy"], stdin=subprocess.PIPE).communicate(
                        text.encode("utf-8")
                    )
                else:
                    subprocess.Popen(
                        ["xclip", "-selection", "clipboard"],
                        stdin=subprocess.PIPE,
                    ).communicate(text.encode("utf-8"))
                list_status.value = "[OK] Copié"
            except Exception as clipboard_exception:
                list_status.value = f"[ERREUR] Clipboard: {clipboard_exception}"
        page.update()

    def _render_list():
        entries = list(json_entries["list"])
        search_lower = list_search_query["value"].lower()
        if search_lower:
            entries = [
                entry for entry in entries
                if search_lower in entry["nom"].lower() or search_lower in entry["description"].lower()
            ]
        if list_sort_mode["value"] == 1:
            entries = sorted(entries, key=lambda list_entry: list_entry["nom"].lower(), reverse=True)
        elif list_sort_mode["value"] == 2:
            entries = list(reversed(entries))  # dernier ajouté en premier
        else:
            entries = sorted(entries, key=lambda list_entry: list_entry["nom"].lower())

        if list_filter_active["value"]:
            entries = [entry for entry in entries if entry["nom"] in list_selected_items["data"]]

        controls = []
        for entry in entries:
            nom  = entry["nom"]
            description = entry["description"]

            controls.append(
                ft.Container(
                    content=ft.Row([
                        # ── Checkbox sélection ────────────────────────
                        ft.Checkbox(
                            value=nom in list_selected_items["data"],
                            tooltip="Sélection (filtre)",
                            on_change=lambda event, entry_name=nom: _on_check_select(event, entry_name),
                            active_color=VIOLET,
                        ),
                        # ── Nom ──────────────────────────────────────
                        ft.Container(
                            content=ft.Text(
                                nom, size=14, weight=ft.FontWeight.BOLD,
                                color=BLUE, max_lines=1,
                                overflow=ft.TextOverflow.ELLIPSIS,
                            ),
                            on_click=lambda event, entry_name=nom: _copy_to_clipboard(entry_name),
                            tooltip=f"Copier le nom : {nom}",
                            ink=True, border_radius=6,
                            padding=ft.Padding(10, 6, 10, 6),
                            bgcolor=DARK,
                            expand=2,
                        ),
                        # ── Description ───────────────────────────────
                        ft.Container(
                            content=ft.Text(
                                description or "—", size=14, color=LIGHT_GREY,
                                max_lines=1, overflow=ft.TextOverflow.ELLIPSIS,
                            ),
                            on_click=lambda event, desc_value=description: _copy_to_clipboard(desc_value) if desc_value else None,
                            tooltip=f"Copier la description : {description}" if description else "Pas de description",
                            ink=True, border_radius=6,
                            padding=ft.Padding(10, 6, 10, 6),
                            bgcolor=DARK,
                            expand=3,
                        ),
                        # ── Actions ───────────────────────────────────
                        ft.Row([
                            ft.IconButton(
                                icon=ft.Icons.EDIT_OUTLINED,
                                icon_size=16, icon_color=LIGHT_GREY,
                                tooltip="Éditer",
                                on_click=lambda event, entry_name=nom, entry_desc=description: _edit_entry(entry_name, entry_desc),
                                style=ft.ButtonStyle(padding=ft.Padding.all(4)),
                            ),
                            # ── Checkbox mise en page ─────────────────────
                            ft.Checkbox(
                                value=nom in list_done_items["data"],
                                tooltip="Mise en page faite",
                                on_change=lambda event, entry_name=nom: _on_check_done(event, entry_name),
                                active_color=GREEN,
                            ),
                            ft.IconButton(
                                icon=ft.Icons.DELETE_OUTLINE,
                                icon_size=16, icon_color=RED,
                                tooltip="Supprimer",
                                on_click=lambda event, entry_name=nom: _delete_entry(entry_name),
                                style=ft.ButtonStyle(padding=ft.Padding.all(4)),
                            ),
                        ], spacing=0, tight=True),
                    ], spacing=6, vertical_alignment=ft.CrossAxisAlignment.CENTER),
                    border_radius=6,
                    padding=ft.Padding(6, 4, 6, 4),
                )
            )

        list_view.controls.clear()
        list_view.controls.extend(controls)
        total_count   = len(json_entries["list"])
        visible_count = len(entries)
        selected_count     = len(list_selected_items["data"])
        if list_filter_active["value"]:
            list_count.value = f"{visible_count} sélectionnée(s) / {total_count} total"
        elif search_lower:
            list_count.value = f"{visible_count}/{total_count} entrée(s)"
        else:
            list_count.value = f"{total_count} entrée(s)" + (f"  •  {selected_count} sélectionnée(s)" if selected_count else "")
        try:
            list_view.update()
            list_count.update()
        except Exception:
            pass

    def _load_and_render():
        json_entries["list"] = _load_json_list()
        _load_list_states()
        _render_list()
        page.update()

    def _on_refresh_topic(topic, message):
        """Recharge la liste JSON depuis le disque quand l'IA modifie un fichier."""
        _load_and_render()

    page.pubsub.subscribe_topic("refresh", _on_refresh_topic)

    def _open_json_in_list(path: str):
        """Charge un fichier JSON dans l'onglet Liste et bascule sur cet onglet."""
        json_path["value"]    = path
        json_path_field.value = path
        try:
            json_path_field.update()
        except Exception:
            pass
        _add_recent_json(path)
        _persist()
        _load_and_render()
        tabs.selected_index = 1
        try:
            tabs.update()
        except Exception:
            pass
        page.update()

    def _edit_entry(original_name: str, original_description: str):
        name_field = ft.TextField(
            label="Nom", value=original_name, autofocus=True,
            bgcolor=DARK, border_color=BLUE, text_size=13,
        )
        description_field = ft.TextField(
            label="Description", value=original_description,
            bgcolor=DARK, border_color=BLUE, text_size=13,
            multiline=True, min_lines=2, max_lines=6,
        )
        dialog = ft.AlertDialog(
            title=ft.Text("Éditer l'entrée"),
            content=ft.Column([name_field, description_field], spacing=8, tight=True, width=380),
        )

        def _confirm(event):
            new_name  = (name_field.value  or "").strip()
            new_description = (description_field.value or "").strip()
            if not new_name:
                name_field.error_text = "Requis"
                page.update()
                return
            for entry in json_entries["list"]:
                if entry["nom"] == original_name and entry["description"] == original_description:
                    entry["nom"]         = new_name
                    entry["description"] = new_description
                    break
            if new_name != original_name:
                if original_name in list_selected_items["data"]:
                    list_selected_items["data"].discard(original_name)
                    list_selected_items["data"].add(new_name)
                if original_name in list_done_items["data"]:
                    list_done_items["data"].discard(original_name)
                    list_done_items["data"].add(new_name)
            dialog.open = False
            page.update()
            _autosave()
            _render_list()

        def _cancel(event):
            dialog.open = False
            page.update()

        name_field.on_submit = _confirm
        dialog.actions = [
            ft.TextButton("Annuler", on_click=_cancel),
            ft.TextButton("OK", on_click=_confirm),
        ]
        page.overlay.append(dialog)
        dialog.open = True
        page.update()

    def _delete_entry(entry_name: str):
        def _confirm(event):
            json_entries["list"] = [
                entry_item for entry_item in json_entries["list"] if entry_item["nom"] != entry_name
            ]
            list_selected_items["data"].discard(entry_name)
            list_done_items["data"].discard(entry_name)
            dialog.open = False
            page.update()
            _autosave()
            _render_list()

        def _cancel(event):
            dialog.open = False
            page.update()

        dialog = ft.AlertDialog(
            title=ft.Text("Supprimer l'entrée ?"),
            content=ft.Text(f"« {entry_name} » sera supprimée de la liste."),
            actions=[
                ft.TextButton("Annuler", on_click=_cancel),
                ft.TextButton(
                    "Supprimer",
                    on_click=_confirm,
                    style=ft.ButtonStyle(color=RED),
                ),
            ],
        )
        page.overlay.append(dialog)
        dialog.open = True
        page.update()

    def _add_entry(event):
        block_field = ft.TextField(
            label="Bloc (1re ligne = nom, suite = description)",
            hint_text="Collez ou saisissez le bloc ici…",
            autofocus=True,
            bgcolor=DARK, border_color=BLUE, text_size=13,
            multiline=True, min_lines=3, max_lines=10,
            width=380,
        )
        dialog = ft.AlertDialog(
            title=ft.Text("Ajouter une entrée"),
            content=ft.Column([block_field], spacing=8, tight=True, width=380),
        )

        def _confirm(inner_event):
            raw_text   = (block_field.value or "").replace("\r\n", "\n").replace("\r", "\n").strip()
            text_lines = raw_text.split("\n", 1)
            entry_name   = text_lines[0].strip()
            entry_description  = text_lines[1].strip() if len(text_lines) > 1 else ""
            if not entry_name:
                block_field.error_text = "La première ligne (nom) est requise"
                page.update()
                return
            block_field.error_text = None
            json_entries["list"].append({"nom": entry_name, "description": entry_description})
            dialog.open = False
            page.update()
            _autosave()
            _render_list()

        def _cancel(inner_event):
            dialog.open = False
            page.update()

        dialog.actions = [
            ft.TextButton("Annuler", on_click=_cancel),
            ft.TextButton("Ajouter", on_click=_confirm),
        ]
        page.overlay.append(dialog)
        dialog.open = True
        page.update()

    # ── Recherche liste ──────────────────────────────────────────────────
    def _on_list_search_change(event):
        search_text = (list_search_field.value or "").strip()
        list_search_query["value"] = search_text
        _render_list()

    def _on_list_sort_change(event):
        list_sort_mode["value"] = event.control.selected_index
        _render_list()

    def _on_check_select(event, entry_name):
        if event.control.value:
            list_selected_items["data"].add(entry_name)
        else:
            list_selected_items["data"].discard(entry_name)
        _update_filter_btn()
        _save_list_states()

    def _on_check_done(event, entry_name):
        if event.control.value:
            list_done_items["data"].add(entry_name)
        else:
            list_done_items["data"].discard(entry_name)
        _save_list_states()

    def _toggle_list_filter(event):
        list_filter_active["value"] = not list_filter_active["value"]
        _update_filter_btn()
        _render_list()

    def _deselect_all_list(event):
        list_selected_items["data"].clear()
        if list_filter_active["value"]:
            list_filter_active["value"] = False
        _update_filter_btn()
        _save_list_states()
        _render_list()

    def _update_filter_btn():
        selected_count = len(list_selected_items["data"])
        if list_filter_active["value"]:
            filter_sel_btn.icon_color = VIOLET
            filter_sel_btn.tooltip    = f"Filtre actif ({selected_count} sélectionnée(s)) — cliquer pour afficher tout"
        else:
            filter_sel_btn.icon_color = LIGHT_GREY
            filter_sel_btn.tooltip    = f"Afficher uniquement la sélection ({selected_count} sélectionnée(s))"
        try:
            filter_sel_btn.update()
        except Exception:
            pass

    async def _pick_json(event):
        initial_directory = current_src["path"] or (
            os.path.dirname(json_path["value"])
            if json_path["value"] and os.path.isfile(json_path["value"])
            else None
        )
        pick_result = await ft.FilePicker().pick_files(
            dialog_title="Ouvrir un fichier JSON",
            allowed_extensions=["json"],
            allow_multiple=False,
            initial_directory=initial_directory,
        )
        picked_files = pick_result.files if hasattr(pick_result, "files") else pick_result
        if picked_files:
            file_path = picked_files[0].path
            json_path["value"]    = file_path
            json_path_field.value = file_path
            json_path_field.update()
            _add_recent_json(file_path)
            _persist()
            _load_and_render()

    def _on_json_path_submit(event):
        path_value = (json_path_field.value or "").strip()
        if path_value and os.path.isfile(path_value):
            json_path["value"] = path_value
            _add_recent_json(path_value)
            _persist()
            _load_and_render()
        else:
            json_path_field.error_text = "Fichier introuvable"
            json_path_field.update()

    # ═════════════════════════════════════════════════════════════════════
    #  ██  Fonctions — Onglet 3 (Bloc-notes)
    # ═════════════════════════════════════════════════════════════════════

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

    def _notepad_load():
        """Charge le fichier .notes.md dans le champ du bloc-notes."""
        if notepad_is_preview["value"]:
            notepad_is_preview["value"] = False
            notepad_field.visible = True
            notepad_preview_scroll.visible = False
        try:
            if os.path.exists(note_target_file["path"]):
                with open(note_target_file["path"], "r", encoding="utf-8") as file_handle:
                    notepad_field.value = file_handle.read()
            else:
                notepad_field.value = ""
        except Exception:
            notepad_field.value = ""
        try:
            notepad_field.update()
        except Exception:
            pass

    def _notepad_save(event=None):
        """Sauvegarde le contenu du bloc-notes dans le fichier cible."""
        try:
            with open(note_target_file["path"], "w", encoding="utf-8") as file_handle:
                file_handle.write(notepad_field.value or "")
        except Exception:
            pass

    def _notepad_toggle_preview(event=None):
        """Bascule entre édition et prévisualisation Markdown."""
        notepad_is_preview["value"] = not notepad_is_preview["value"]
        is_preview = notepad_is_preview["value"]
        if is_preview:
            _notepad_save()
            notepad_markdown_preview.value = _prepare_notepad_markdown(notepad_field.value or "")
            notepad_preview_scroll.visible = True
            notepad_field.visible = False
            notepad_preview_btn.icon = ft.Icons.EDIT
            notepad_preview_btn.tooltip = "Revenir à l'édition"
        else:
            notepad_field.visible = True
            notepad_preview_scroll.visible = False
            notepad_preview_btn.icon = ft.Icons.VISIBILITY
            notepad_preview_btn.tooltip = "Prévisualiser en Markdown"
        try:
            page.update()
        except Exception:
            pass

    notepad_preview_btn.on_click = _notepad_toggle_preview

    def _notepad_clear(event=None):
        """Efface le contenu du bloc-notes et sauvegarde immédiatement."""
        notepad_field.value = ""
        if notepad_is_preview["value"]:
            notepad_is_preview["value"] = False
            notepad_field.visible = True
            notepad_preview_scroll.visible = False
            notepad_preview_btn.icon = ft.Icons.VISIBILITY
            notepad_preview_btn.tooltip = "Prévisualiser en Markdown"
        _notepad_save()
        try:
            page.update()
        except Exception:
            pass

    def _open_file_in_notepad(file_path):
        """Ouvre un fichier texte dans l'onglet Notes."""
        note_target_file["path"] = file_path
        ext = os.path.splitext(file_path)[1].lower()
        if ext in (".py", ".pyw"):
            notepad_field.language = fce.CodeLanguage.PYTHON
        elif ext == ".json":
            notepad_field.language = fce.CodeLanguage.JSON
        elif ext in (".md",):
            notepad_field.language = fce.CodeLanguage.MARKDOWN
        elif ext in (".js", ".ts"):
            notepad_field.language = fce.CodeLanguage.JAVASCRIPT
        else:
            notepad_field.language = fce.CodeLanguage.PLAINTEXT
        _notepad_load()
        tabs.selected_index = 2
        try:
            tabs.update()
        except Exception:
            pass

    # ═══════════════════════════════════════════════════════════════════
    #  ██  Fonctions — Onglet 4 (IA)
    # ═══════════════════════════════════════════════════════════════════

    _AI_DOCUMENT_EXTS = CONSTANTS.AI_DOCUMENT_EXTS

    # _md_dark importé depuis ai_tools

    # ═════════════════════════════════════════════════════════════════════
    #  ██  Fonctions — Onglet 4 (IA)
    # ═════════════════════════════════════════════════════════════════════

    def _speak_bubble(text):
        """Lit un texte via Gemini TTS (mode configurable dans CONSTANTS.AI_VOICE_TTS_MODE)."""
        # Arrêter le TTS précédent s'il tourne encore
        if ai_tts_stop_event["event"] is not None:
            ai_tts_stop_event["event"].set()
        stop_event = threading.Event()
        ai_tts_stop_event["event"] = stop_event
        mode_label = "Live" if CONSTANTS.AI_VOICE_TTS_MODE == "live" else "TTS"
        ai_status_text.value = f"🔊 {mode_label} — {CONSTANTS.AI_VOICE_TTS_VOICE}…"
        try:
            ai_status_text.update()
        except Exception:
            pass
        try:
            if CONSTANTS.AI_VOICE_TTS_MODE == "live":
                _gemini_live_tts_stream(
                    text,
                    model=CONSTANTS.AI_VOICE_LIVE_MODEL,
                    voice_name=CONSTANTS.AI_VOICE_TTS_VOICE,
                    sample_rate=CONSTANTS.AI_VOICE_TTS_SAMPLE_RATE,
                    language_code=CONSTANTS.AI_VOICE_TTS_LANGUAGE,
                    stop_event=stop_event,
                    preroll_ms=CONSTANTS.AI_VOICE_TTS_PREROLL_MS,
                )
            else:
                _gemini_tts_stream(
                    text,
                    voice_name=CONSTANTS.AI_VOICE_TTS_VOICE,
                    tts_model=CONSTANTS.AI_VOICE_TTS_MODEL,
                    sample_rate=CONSTANTS.AI_VOICE_TTS_SAMPLE_RATE,
                    language_code=CONSTANTS.AI_VOICE_TTS_LANGUAGE,
                    stop_event=stop_event,
                )
        except Exception as tts_exc:
            ai_status_text.value = f"[❌ TTS] {tts_exc}"
            try:
                ai_status_text.update()
            except Exception:
                pass
            return
        finally:
            if ai_tts_stop_event["event"] is stop_event:
                ai_tts_stop_event["event"] = None
        ai_status_text.value = ""
        try:
            ai_status_text.update()
        except Exception:
            pass

    _fs_ai = {"chat_view": None}  # Référence vers la vue plein écran active (ou None)

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
                md_style_sheet=AI_MD_STYLE,
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
        _target_view = _fs_ai["chat_view"] if _fs_ai["chat_view"] is not None else ai_chat_view
        _target_view.controls.append(row)
        async def _update_and_scroll():
            try:
                page.update()
                await asyncio.sleep(0)
                await _target_view.scroll_to(offset=-1)
            except Exception:
                pass
        page.run_task(_update_and_scroll)
        return bubble_text

    def _ai_add_image_bubble(image_path):
        """Affiche une image générée dans le chat IA."""
        image_src = image_path
        try:
            if os.path.isfile(image_path):
                cached_image = thumb_cache.get_or_generate(image_path)
                if cached_image:
                    image_src = cached_image
                else:
                    with open(image_path, "rb") as image_file:
                        image_src = image_file.read()
        except Exception:
            image_src = image_path

        img_widget = ft.Image(
            src=image_src,
            width=400,
            border_radius=8,
            fit=ft.BoxFit.CONTAIN,
        )
        row = ft.Row(
            [ft.Container(img_widget, border_radius=8)],
            alignment=ft.MainAxisAlignment.START,
        )
        _target_view = _fs_ai["chat_view"] if _fs_ai["chat_view"] is not None else ai_chat_view
        _target_view.controls.append(row)
        async def _upd():
            try:
                page.update()
                await asyncio.sleep(0)
                await _target_view.scroll_to(offset=-1)
            except Exception:
                pass
        page.run_task(_upd)

    def _ai_add_screenshot_bubble(b64_str):
        """Affiche dans le chat IA la capture d'écran telle que le modèle la voit (debug)."""
        img_widget = ft.Image(
            src=base64.b64decode(b64_str),
            width=350,
            border_radius=8,
            fit=ft.BoxFit.CONTAIN,
        )
        row = ft.Row(
            [ft.Container(img_widget, border=ft.Border.all(1, LIGHT_GREY), border_radius=8)],
            alignment=ft.MainAxisAlignment.START,
        )
        _target_view = _fs_ai["chat_view"] if _fs_ai["chat_view"] is not None else ai_chat_view
        _target_view.controls.append(row)
        async def _upd():
            try:
                page.update()
                await asyncio.sleep(0)
                await _target_view.scroll_to(offset=-1)
            except Exception:
                pass
        page.run_task(_upd)

    def _ai_save_history():
        _ai_save_history_fn(ai_conversation, ai_history_file_path, ai_history_compaction_state)

    def _ai_load_history():
        """Charge .ai_conversation.json et reconstruit la vue."""
        if not os.path.isfile(ai_history_file_path):
            return
        try:
            with open(ai_history_file_path, "r", encoding="utf-8") as file_handle:
                saved_data = json.load(file_handle)
            if isinstance(saved_data, dict):
                saved_messages = saved_data.get("messages", [])
                ai_history_compaction_state.update(saved_data.get("history_compaction") or {})
            else:
                saved_messages = saved_data  # Ancien format : liste brute, pas de résumé sauvegardé
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
                        _md_dark(content),
                        selectable=True,
                        extension_set=ft.MarkdownExtensionSet.GITHUB_WEB,
                        code_theme=ft.MarkdownCodeTheme.ATOM_ONE_DARK,
                        md_style_sheet=AI_MD_STYLE,
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

    def _rebuild_ai_chat_view():
        """Reconstruit ai_chat_view depuis ai_conversation (appelé à la fermeture du plein écran)."""
        ai_chat_view.controls.clear()
        for message in ai_conversation:
            role    = message.get("role")
            content = message.get("content", "")
            if role not in ("user", "assistant"):
                continue
            is_user = role == "user"
            if is_user:
                btext = ft.Text(content, size=CONSTANTS.TERMINAL_FONT_SIZE, color=BLUE, font_family="monospace", selectable=True, no_wrap=False)
            else:
                btext = ft.Markdown(_md_dark(content), selectable=True, extension_set=ft.MarkdownExtensionSet.GITHUB_WEB, code_theme=ft.MarkdownCodeTheme.ATOM_ONE_DARK, md_style_sheet=AI_MD_STYLE, expand=True)
            bub = ft.Container(content=btext, bgcolor=DARK if is_user else GREY, border_radius=6, padding=ft.Padding(8, 4, 8, 4), expand=True)
            if is_user:
                row = ft.Row([bub], alignment=ft.MainAxisAlignment.END)
            else:
                raw = content
                spk = ft.IconButton(icon=ft.Icons.VOLUME_UP, icon_color=LIGHT_GREY, icon_size=14, tooltip="Lire", on_click=lambda e, t=raw: threading.Thread(target=_speak_bubble, args=(t,), daemon=True).start())
                row = ft.Row([bub, spk], alignment=ft.MainAxisAlignment.START, vertical_alignment=ft.CrossAxisAlignment.START)
            ai_chat_view.controls.append(row)

    def _open_ai_notepad_fullscreen(event=None):
        """Ouvre l'IA et le bloc-notes côte à côte en plein écran."""
        # ── Vue chat plein écran ─────────────────────────────────────────────
        fs_chat_view = ft.ListView(expand=True, spacing=4, auto_scroll=True)
        for message in ai_conversation:
            role    = message.get("role")
            content = message.get("content", "")
            if role not in ("user", "assistant"):
                continue
            is_user = role == "user"
            if is_user:
                btext = ft.Text(content, size=CONSTANTS.TERMINAL_FONT_SIZE, color=BLUE, font_family="monospace", selectable=True, no_wrap=False)
            else:
                btext = ft.Markdown(_md_dark(content), selectable=True, extension_set=ft.MarkdownExtensionSet.GITHUB_WEB, code_theme=ft.MarkdownCodeTheme.ATOM_ONE_DARK, md_style_sheet=AI_MD_STYLE, expand=True)
            bub = ft.Container(content=btext, bgcolor=DARK if is_user else GREY, border_radius=6, padding=ft.Padding(8, 4, 8, 4), expand=True)
            if is_user:
                row = ft.Row([bub], alignment=ft.MainAxisAlignment.END)
            else:
                raw = content
                spk = ft.IconButton(icon=ft.Icons.VOLUME_UP, icon_color=LIGHT_GREY, icon_size=14, tooltip="Lire", on_click=lambda e, t=raw: threading.Thread(target=_speak_bubble, args=(t,), daemon=True).start())
                row = ft.Row([bub, spk], alignment=ft.MainAxisAlignment.START, vertical_alignment=ft.CrossAxisAlignment.START)
            fs_chat_view.controls.append(row)

        _fs_ai["chat_view"] = fs_chat_view

        # ── Dropdown modèle synchronisé ──────────────────────────────────────
        fs_model_dd = ft.Dropdown(
            value=ai_model_dropdown.value,
            options=[ft.dropdown.Option(m) for m in CONSTANTS.AI_DROPDOWN_MODELS],
            text_size=11, dense=True, color=LIGHT_GREY, bgcolor=DARK, border_color=GREY,
            content_padding=ft.Padding.symmetric(horizontal=6, vertical=0), width=150,
        )
        fs_model_dd.on_change = lambda e: setattr(ai_model_dropdown, "value", e.control.value)

        # ── Bloc-notes synchronisé ───────────────────────────────────────────
        fs_notepad = fce.CodeEditor(
            text_style=ft.TextStyle(font_family="monospace", size=CONSTANTS.TERMINAL_FONT_SIZE),
            language=notepad_field.language,
            code_theme=fce.CodeTheme.ATOM_ONE_DARK,
            gutter_style=fce.GutterStyle(width=56),
            expand=True,
        )
        fs_notepad.value = notepad_field.value or ""

        # ── Champ de saisie IA plein écran ──────────────────────────────────
        fs_ai_input = ft.TextField(
            hint_text="Posez votre question… (Entrée pour envoyer, Maj+Entrée = nouvelle ligne)",
            bgcolor=DARK, color=WHITE, border_color=GREY, expand=True,
            multiline=True, shift_enter=True,
            text_style=ft.TextStyle(size=CONSTANTS.TERMINAL_FONT_SIZE),
        )

        def _fs_submit(event=None):
            if not (fs_ai_input.value or "").strip():
                return
            ai_input_field.value = fs_ai_input.value
            fs_ai_input.value = ""
            try:
                fs_ai_input.update()
            except Exception:
                pass
            _on_ai_submit()

        fs_ai_input.on_submit = _fs_submit

        # ── Dictée vocale plein écran (clic = démarrer / arrêter) ────────────
        _fs_mic_state = {"rec": None, "active": False}

        def _fs_mic_toggle():
            if _fs_mic_state["active"]:
                _fs_mic_stop()
            else:
                _fs_mic_start()

        def _fs_mic_start():
            if _fs_mic_state["active"]:
                return

            def _on_ready():
                async def _flip():
                    if not _fs_mic_state["active"]:
                        return
                    fs_mic_btn.icon = ft.Icons.STOP_CIRCLE
                    fs_mic_btn.icon_color = RED
                    fs_mic_btn.tooltip = "Enregistrement… cliquer pour arrêter"
                    try:
                        fs_mic_btn.update()
                    except Exception:
                        pass
                page.run_task(_flip)

            try:
                recorder = _MicRecorder(
                    sample_rate=CONSTANTS.AI_VOICE_STT_SAMPLE_RATE)
                recorder.start(on_ready=_on_ready)
            except Exception:
                return
            _fs_mic_state["rec"] = recorder
            _fs_mic_state["active"] = True
            fs_mic_btn.icon = ft.Icons.MIC
            fs_mic_btn.icon_color = ORANGE
            fs_mic_btn.tooltip = "Préparation du micro… (attendez le rouge)"
            try:
                fs_mic_btn.update()
            except Exception:
                pass

        def _fs_mic_stop():
            if not _fs_mic_state["active"]:
                return
            _fs_mic_state["active"] = False
            recorder = _fs_mic_state["rec"]
            _fs_mic_state["rec"] = None
            fs_mic_btn.icon = ft.Icons.MIC_NONE
            fs_mic_btn.icon_color = LIGHT_GREY
            fs_mic_btn.tooltip = "Cliquer pour dicter (Gemini) — recliquer pour arrêter"
            try:
                fs_mic_btn.update()
            except Exception:
                pass

            def _worker():
                text = None
                try:
                    wav = recorder.stop() if recorder else None
                    if wav:
                        text = _gemini_transcribe_audio(
                            wav,
                            language_code=CONSTANTS.AI_VOICE_STT_LANGUAGE,
                            model=CONSTANTS.AI_VOICE_STT_MODEL,
                        )
                except Exception:
                    pass

                async def _apply():
                    if text:
                        existing = (fs_ai_input.value or "").rstrip()
                        fs_ai_input.value = (
                            f"{existing} {text}" if existing else text)
                        fs_ai_input.update()
                        try:
                            await fs_ai_input.focus()
                        except Exception:
                            pass
                page.run_task(_apply)

            threading.Thread(target=_worker, daemon=True).start()

        # ── Boutons plein écran ──────────────────────────────────────────────
        fs_send_btn    = ft.IconButton(ft.Icons.SEND,         icon_color=BLUE,       icon_size=18, tooltip="Envoyer",              on_click=_fs_submit)
        fs_mic_btn     = ft.IconButton(ft.Icons.MIC_NONE, icon_color=LIGHT_GREY, icon_size=20, tooltip="Cliquer pour dicter (Gemini) — recliquer pour arrêter", on_click=lambda e: _fs_mic_toggle())
        fs_attach_btn  = ft.IconButton(ft.Icons.ATTACH_FILE,  icon_color=LIGHT_GREY, icon_size=18, tooltip="Joindre un fichier",    on_click=lambda e: page.run_task(_ai_pick_any))
        _fs_is_cloud = (ai_model_dropdown.value or "").startswith(("gemini", "claude"))
        fs_stop_btn    = ft.IconButton(ft.Icons.STOP_CIRCLE,  icon_color=LIGHT_GREY, icon_size=16, tooltip="Libérer le modèle",     on_click=lambda e: _ai_stop_model(), visible=not _fs_is_cloud)
        fs_copy_btn    = ft.IconButton(ft.Icons.COPY,         icon_color=LIGHT_GREY, icon_size=16, tooltip="Copier la conversation", on_click=lambda e: _export_ai_conversation(to_notepad=False))
        fs_clear_btn   = ft.IconButton(ft.Icons.DELETE_SWEEP, icon_color=LIGHT_GREY, icon_size=16, tooltip="Effacer la conversation", on_click=lambda e: _clear_ai_conversation())
        fs_speaker_btn = ft.IconButton(
            icon=ft.Icons.VOLUME_UP if ai_tts_enabled["value"] else ft.Icons.VOLUME_OFF,
            icon_color=BLUE if ai_tts_enabled["value"] else LIGHT_GREY,
            icon_size=16, tooltip="TTS",
            on_click=lambda e: _toggle_tts(),
        )
        fs_transfer_btn = ft.IconButton(
            icon=ft.Icons.SEND_TO_MOBILE, icon_color=VIOLET, icon_size=16,
            tooltip="Transférer la conversation vers le bloc-notes",
            on_click=lambda e: _export_ai_conversation(to_notepad=True),
        )
        fs_close_btn = ft.IconButton(ft.Icons.CLOSE_FULLSCREEN, icon_color=LIGHT_GREY, icon_size=18, tooltip="Fermer le plein écran")
        fs_status_text = ft.Text("", color=LIGHT_GREY, size=11, italic=True, max_lines=1, overflow=ft.TextOverflow.ELLIPSIS)
        fs_progress_bar = ft.ProgressBar(value=None, visible=ai_progress_bar.visible, color=BLUE, height=2)

        # ── Layout ───────────────────────────────────────────────────────────
        ai_left_panel = ft.Column([
            ft.Row([
                ft.Icon(ft.Icons.SMART_TOY, color=BLUE, size=14),
                ft.Text("IA", color=BLUE, size=12, weight=ft.FontWeight.BOLD),
                ft.Container(width=4),
                fs_model_dd,
                ft.Container(width=8),
                ft.Container(content=fs_status_text, expand=True),
                fs_stop_btn, fs_copy_btn, fs_clear_btn, fs_speaker_btn, fs_transfer_btn,
            ], spacing=2, vertical_alignment=ft.CrossAxisAlignment.CENTER),
            ft.Container(
                content=ft.Column([
                    fs_chat_view,
                    fs_progress_bar,
                    ft.Row([fs_attach_btn, fs_ai_input, fs_mic_btn, fs_send_btn],
                           spacing=4, vertical_alignment=ft.CrossAxisAlignment.CENTER),
                ], spacing=4, expand=True),
                expand=True,
                border=ft.Border.all(1, BLUE), border_radius=8, bgcolor=DARK,
                padding=ft.Padding(6, 6, 6, 6),
            ),
        ], expand=True, spacing=6)

        notepad_right_panel = ft.Column([
            ft.Row([
                ft.Icon(ft.Icons.CODE, color=VIOLET, size=14),
                ft.Text("Bloc-notes", color=VIOLET, size=12, weight=ft.FontWeight.BOLD),
            ], spacing=4, vertical_alignment=ft.CrossAxisAlignment.CENTER),
            ft.Container(
                content=fs_notepad,
                expand=True,
                border=ft.Border.all(1, VIOLET), border_radius=8, bgcolor=DARK,
                padding=ft.Padding(6, 6, 6, 6),
            ),
        ], expand=True, spacing=6)

        def _fs_status_sync_loop():
            """Reflète ai_status_text/ai_progress_bar (mis à jour par le tour d'outils
            en arrière-plan) sur les contrôles plein écran, tant que cette fenêtre est ouverte."""
            _last_text, _last_visible = None, None
            while _fs_ai.get("chat_view") is fs_chat_view:
                if ai_status_text.value != _last_text or ai_progress_bar.visible != _last_visible:
                    _last_text = fs_status_text.value = ai_status_text.value
                    _last_visible = fs_progress_bar.visible = ai_progress_bar.visible
                    try:
                        fs_status_text.update()
                        fs_progress_bar.update()
                    except Exception:
                        pass
                time.sleep(0.3)

        threading.Thread(target=_fs_status_sync_loop, daemon=True).start()

        def _close_fs(event=None):
            _fs_ai["chat_view"] = None
            if fs_notepad.value is not None:
                notepad_field.value = fs_notepad.value
                _notepad_save()
            if fs_overlay in page.overlay:
                page.overlay.remove(fs_overlay)
            _rebuild_ai_chat_view()
            try:
                page.update()
            except Exception:
                pass

        fs_close_btn.on_click = _close_fs

        fs_overlay = ft.Container(
            content=ft.Column([
                ft.Container(
                    content=ft.Row([
                        ft.Icon(ft.Icons.OPEN_IN_FULL, color=BLUE, size=14),
                        ft.Text("IA + Bloc-notes", color=WHITE, size=13, weight=ft.FontWeight.BOLD),
                        ft.Container(expand=True),
                        fs_close_btn,
                    ], spacing=6, vertical_alignment=ft.CrossAxisAlignment.CENTER),
                    bgcolor="#0d0f14",
                    padding=ft.Padding(8, 4, 4, 4),
                ),
                ft.Row([
                    ft.Container(content=ai_left_panel,        expand=True, padding=ft.Padding(8, 4, 4, 8)),
                    ft.VerticalDivider(width=1, color=GREY),
                    ft.Container(content=notepad_right_panel, expand=True, padding=ft.Padding(4, 4, 8, 8)),
                ], expand=True, spacing=0, vertical_alignment=ft.CrossAxisAlignment.STRETCH),
            ], expand=True, spacing=0),
            bgcolor=DARK, expand=True,
        )

        page.overlay.append(fs_overlay)
        page.update()

    def _clear_ai_conversation(event=None):
        """Efface l'historique de la conversation IA."""
        ai_conversation.clear()
        ai_history_compaction_state["summary"] = ""
        ai_history_compaction_state["summarized_count"] = 0
        ai_chat_view.controls.clear()
        if _fs_ai["chat_view"] is not None:
            _fs_ai["chat_view"].controls.clear()
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

    def _export_ai_conversation(to_notepad=False, event=None):
        """Copie la conversation IA dans le presse-papiers, et la transfère dans le bloc-notes si demandé."""
        if not ai_conversation:
            return
        text = _format_ai_conversation(ai_conversation, CONSTANTS.AI_USER_NAME, CONSTANTS.AI_SEPARATOR_WIDTH)
        async def _copy():
            try:
                await ft.Clipboard().set(text)
            except Exception:
                pass
        page.run_task(_copy)
        if to_notepad:
            existing = notepad_field.value or ""
            sep = "\n\n" + "#" * CONSTANTS.AI_SEPARATOR_WIDTH + "\n\n" if existing.strip() else ""
            notepad_field.value = existing + sep + text
            _notepad_save()
            try:
                notepad_field.update()
            except Exception:
                pass
            tabs.selected_index = 2
            try:
                tabs.update()
            except Exception:
                pass

    def _ai_stop_model(event=None):
        """Interrompt la génération en cours et débloque l'interface.

        Pour un modèle cloud (Gemini/Claude) on ne peut pas décharger la RAM,
        mais on remet `ai_streaming` à False immédiatement : la boucle agent
        s'arrête au prochain point de contrôle et l'UI est libérée même si
        l'appel réseau est figé (le thread se terminera au pire au timeout HTTP).
        """
        # Débloquer l'UI tout de suite, quel que soit le modèle.
        ai_streaming["value"] = False
        ai_stop_button.icon_color = LIGHT_GREY
        ai_status_text.value = "⏹ Interrompu"
        ai_progress_bar.visible = False
        try:
            page.update()
        except Exception:
            pass

        def _run_stop():
            try:
                current_model = ai_model_dropdown.value or CONSTANTS.AI_MODEL_TEXT
                if not (current_model or "").startswith(("gemini", "claude")):
                    subprocess.run(["ollama", "stop", CONSTANTS.AI_MODEL_VISION], timeout=10)
                    subprocess.run(["ollama", "stop", CONSTANTS.AI_MODEL_TEXT],   timeout=10)
            except Exception:
                pass
        threading.Thread(target=_run_stop, daemon=True).start()

    def _ai_refresh_attach_row():
        """Reconstruit la barre de pièces jointes visuellement."""
        ai_attach_row.controls.clear()
        for image_entry in ai_pending_images:
            name = os.path.basename(image_entry["path"])
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
                            on_click=lambda event, ref=entry_ref: _ai_remove_image(ref),
                        ),
                    ], spacing=2, tight=True),
                    bgcolor=GREY,
                    border_radius=4,
                    padding=ft.Padding(4, 2, 4, 2),
                )
            )
        for file_path in ai_pending_files:
            name = os.path.basename(file_path)
            icon_name = ft.Icons.DESCRIPTION
            entry_ref = file_path
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
                            on_click=lambda event, ref=entry_ref: _ai_remove_file(ref),
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
        if image_entry in ai_pending_images:
            ai_pending_images.remove(image_entry)
        _ai_refresh_attach_row()

    def _ai_attach_document_file(file_path):
        if file_path in ai_pending_files:
            return
        ai_pending_files.append(file_path)
        _ai_refresh_attach_row()

    def _ai_remove_file(file_entry):
        if file_entry in ai_pending_files:
            ai_pending_files.remove(file_entry)
        _ai_refresh_attach_row()

    def _ai_extract_file_content(file_path):
        """Extrait le contenu textuel d'un document."""
        ext = os.path.splitext(file_path)[1].lower()
        name = os.path.basename(file_path)
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
                raise ImportError("python-docx non installé. pip install python-docx")
        with open(file_path, "r", encoding="utf-8", errors="replace") as text_file:
            return name, text_file.read()

    async def _ai_pick_any():
        """Ouvre un sélecteur de fichier pour joindre une image ou un document."""
        _image_exts_pick = {"jpg", "jpeg", "png", "gif", "bmp", "webp"}
        result = await ft.FilePicker().pick_files(
            dialog_title="Joindre une image ou un document",
            allowed_extensions=[
                "jpg", "jpeg", "png", "gif", "bmp", "webp",
                "txt", "md", "py", "js", "ts", "json", "csv", "xml",
                "html", "htm", "yaml", "yml", "toml", "ini", "cfg", "log",
                "rst", "pdf", "docx", "doc", "rtf",
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

    def _ensure_ollama_ready(model_name=None):
        if model_name is None:
            model_name = CONSTANTS.AI_MODEL_TEXT
        return _ensure_ollama_ready_fn(
            model_name, _ai_add_bubble, page, ollama_process
        )

    def _send_ai_message(message_text):
        """Envoie un message à Ollama et streame la réponse dans le panneau IA."""
        if ai_streaming["value"]:
            return
        if not message_text.strip() and not ai_pending_images and not ai_pending_files:
            return
        ai_streaming["value"] = True
        ai_stop_button.visible = True
        ai_stop_button.icon_color = RED
        ai_status_text.value = "⏳ En cours…"
        try:
            page.update()
        except Exception:
            pass

        images_b64 = [entry["b64"] for entry in ai_pending_images]
        ai_pending_images.clear()
        _ai_refresh_attach_row()

        files_to_inject = list(ai_pending_files)
        ai_pending_files.clear()
        _ai_refresh_attach_row()

        active_model = ai_model_dropdown.value or CONSTANTS.AI_MODEL_TEXT

        url_pattern = re.compile(r'https?://[^\s<>"\)\]]+', re.IGNORECASE)
        found_urls = url_pattern.findall(message_text)
        enriched_text = message_text
        if found_urls:
            url_blocks = []
            for url in found_urls:
                page_content = _fetch_url_content(url, max_chars=CONSTANTS.AI_URL_MAX_CHARS)
                url_blocks.append(f"--- Contenu de {url} ---\n{page_content}\n--- Fin ---")
            enriched_text = message_text + "\n\n" + "\n\n".join(url_blocks)

        user_message = {"role": "user", "content": enriched_text}
        if images_b64:
            user_message["images"] = images_b64
        ai_conversation.append(user_message)

        display_text = message_text
        if images_b64:
            display_text = (
                f"🖼️ ({len(images_b64)} image(s))  {message_text}"
                if message_text else f"🖼️ {len(images_b64)} image(s) jointe(s)"
            )
        if files_to_inject:
            files_label = "  ".join(
                "📄 " + os.path.basename(file_path)
                for file_path in files_to_inject
            )
            display_text = (display_text + "  " if display_text else "") + files_label
        _ai_add_bubble("user", display_text)

        def _run():
            full_response = ""
            response_text_ctrl = None
            try:
                if not _ensure_ollama_ready(active_model):
                    return

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

                if files_to_inject:
                    injected_blocks = []
                    for file_path in files_to_inject:
                        file_name = os.path.basename(file_path)
                        try:
                            label, content = _ai_extract_file_content(file_path)
                            injected_blocks.append(
                                f"--- Document : {label} ---\n{content[:50000]}\n--- Fin ---"
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

                today = datetime.date.today().strftime("%d %B %Y")
                # ── Outils dossier (disponibles si un dossier est ouvert) ─────
                _folder_path_for_tools = current_src["path"]
                _FOLDER_TOOLS = _folder_tool_definitions(_folder_path_for_tools)
                _NEW_TOOLS = (_EDIT_TOOLS + _READ_LINES_TOOLS + _SEARCH_TOOLS + _GIT_TOOLS + _TASK_TOOLS
                              + _PDF_TOOLS + _SUBAGENT_TOOLS + _SCHEDULE_TOOLS
                              + _HTTP_TOOLS + _SPREADSHEET_TOOLS + _PYAUTOGUI_TOOLS + _SSH_TOOLS)
                _MCP_TOOLS = mcp_client.mcp_get_all_tools()
                if (active_model or "").startswith("gemini"):
                    _ALL_TOOLS = _WEB_TOOLS + _TERMINAL_TOOLS + _MEMORY_TOOLS + _SCREENSHOT_TOOLS + _NOTEPAD_TOOLS + _UI_TOOLS + _NEW_TOOLS + _MCP_TOOLS + _gemini_tool_definitions(_folder_path_for_tools)
                else:
                    _ALL_TOOLS = _WEB_TOOLS + _TERMINAL_TOOLS + _MEMORY_TOOLS + _SCREENSHOT_TOOLS + _NOTEPAD_TOOLS + _UI_TOOLS + _NEW_TOOLS + _MCP_TOOLS + _FOLDER_TOOLS
                # Limiter l'historique : 20 tours pour les modèles cloud capables, 10 pour les modèles locaux
                _history_limit = CONSTANTS.AI_HISTORY_LIMIT_CLOUD if (active_model or "").startswith(("gemini", "claude")) else CONSTANTS.AI_HISTORY_LIMIT_LOCAL
                _history = ai_conversation[-_history_limit:] if len(ai_conversation) > _history_limit else ai_conversation
                # Résume les tours qui sortent de la fenêtre au lieu de les oublier silencieusement
                _history_summary = _compact_history_summary(
                    ai_conversation, _history_limit, ai_history_compaction_state
                )
                _system_content = _build_system_content(
                    _folder_path_for_tools, today
                )
                if _history_summary:
                    _system_content += f"\n\nRÉSUMÉ DES ÉCHANGES PRÉCÉDENTS (hors fenêtre récente) :\n{_history_summary}"
                _system_content += f"\n\nRACINE DU PROJET (chemin absolu, pour .mots_cles.json etc.) : {os.path.dirname(app_dir)}"
                if _folder_path_for_tools:
                    _system_content += f"\n\nDOSSIER ACTUELLEMENT OUVERT : {_folder_path_for_tools}"
                if selected_files:
                    _sel_basenames = [os.path.basename(f) for f in selected_files]
                    _sel_list = "\n".join(f"- {n}" for n in _sel_basenames[:50])
                    _system_content += f"\n\nFICHIERS SÉLECTIONNÉS DANS L'INTERFACE ({len(selected_files)}) :\n{_sel_list}"
                    if len(selected_files) > 50:
                        _system_content += f"\n(… et {len(selected_files) - 50} autres non listés)"
                # Pour les modèles Ollama : retirer "thinking" et "events" de l'historique.
                # Gemma injecte ses tokens <think> dans msg.content ; réinjecter le thinking
                # extrait pollue la fenêtre de contexte et tronque les réponses tour après tour.
                _is_cloud = (active_model or "").startswith(("gemini", "claude"))
                _skip_keys = {"events"} if _is_cloud else {"events", "thinking"}
                messages = [
                    {"role": "system", "content": _system_content},
                    *[{k: v for k, v in m.items() if k not in _skip_keys} for m in _history],
                ]

                # ── Debug log & Journal permanent en Markdown ────────────────
                _DEBUG_MD = f"{os.path.dirname(app_dir)}/ai_conversations_debug.md"

                def _log_exchange_to_md(user_text: str, assistant_text: str, thinking_text: str = "", events_list: list = None) -> None:
                    """Ajoute l'échange au journal permanent en Markdown et le limite à ~500 lignes."""
                    try:
                        timestamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                        
                        # Construire le bloc Markdown de cet échange
                        block = []
                        block.append(f"## 💬 Échange du {timestamp}")
                        block.append(f"**👤 Utilisateur :**\n{user_text.strip()}\n")
                        
                        if thinking_text.strip():
                            # On préfixe chaque ligne de la réflexion par "> " pour utiliser notre superbe blockquote stylisé !
                            formatted_thinking = "\n".join(f"> {line}" for line in thinking_text.strip().splitlines())
                            block.append(f"💭 **Réflexion :**\n{formatted_thinking}\n")
                            
                        block.append(f"**🤖 Assistant :**\n{assistant_text.strip()}\n")
                        
                        if events_list:
                            block.append("🛠️ **Événements d'outils**") # Titre en gras pour faire plus propre
                            for evt in events_list:
                                block.append(f"- {evt}")
                            block.append("\n")
                            
                        block.append("---\n")
                        new_entry = "\n".join(block)
                        
                        # Lire l'historique existant
                        existing_content = ""
                        if os.path.exists(_DEBUG_MD):
                            with open(_DEBUG_MD, "r", encoding="utf-8") as f:
                                existing_content = f.read()
                        
                        # Combiner l'ancien et le nouveau journal
                        full_md = existing_content + "\n" + new_entry
                        lines = full_md.splitlines()
                        
                        # Limiter à environ 500 lignes
                        if len(lines) > 500:
                            # On prend les 500 dernières lignes
                            truncated_lines = lines[-500:]
                            
                            # On cherche le premier début d'échange "## 💬" pour couper proprement
                            start_idx = 0
                            for idx, line in enumerate(truncated_lines):
                                if line.startswith("## 💬"):
                                    start_idx = idx
                                    break
                            
                            # Si on a trouvé un début d'échange, on repart de là, sinon on prend les 500 brutes
                            final_lines = truncated_lines[start_idx:] if start_idx > 0 else truncated_lines
                            full_md = "*(Historique plus ancien tronqué pour rester sous 500 lignes)*\n\n" + "\n".join(final_lines)
                        
                        # Écrire dans le fichier permanent
                        with open(_DEBUG_MD, "w", encoding="utf-8") as f:
                            f.write(full_md.strip() + "\n")
                    except Exception:
                        pass
                
                # Capturer la demande originale de l'utilisateur (avant tout tour d'outil)
                # pour affiner le prompt d'image si generate_image/edit_image est appelé.
                _original_user_request = next(
                    (m["content"] for m in reversed(messages) if m["role"] == "user"),
                    "",
                )
                if len(_original_user_request) > 400:
                    _original_user_request = _original_user_request[:400] + "…"
                _image_tool_done = False  # True dès qu'une génération/édition image a réussi

                # ── Boucle agentique (jusqu'à 200 tours, auto-continuation intégrée) ──
                for _tool_round in range(200):
                    # Tous les 40 tours, injecter un rappel silencieux pour que
                    # le modèle ne s'arrête pas mentalement en cours de tâche longue.
                    if _tool_round > 0 and _tool_round % 40 == 0 and ai_streaming["value"]:
                        messages.append({"role": "user", "content": (
                            "Continue la tâche en cours. "
                            "Reprends là où tu t'es arrêté."
                        )})
                    # Streaming avec thinking natif Ollama et capture des tool_calls
                    _streamed = ""
                    _thinking = ""
                    _stream_tool_calls = []
                    _text_parsed_tools = False  # True si tool_calls viennent du parseur texte
                    thinking_ctrl = None
                    _turn_events = []          # Événements d'outils du tour courant (pour export)
                    _stream_token_count = 0
                    _STREAM_UPDATE_EVERY = 5

                    async def _scroll_and_update():
                        try:
                            page.update()
                            await asyncio.sleep(0)
                            await ai_chat_view.scroll_to(offset=-1)
                        except Exception:
                            pass

                    # ── Chaîne de fallback : Gemini 3.5 → Gemini 3.1 Pro → Gemma ─────
                    _fb_chain = [active_model or ""]
                    if _fb_chain[0].startswith("gemini"):
                        _c_fb = getattr(CONSTANTS, "AI_GEMINI_FALLBACK_CLOUD", "")
                        if _c_fb and _c_fb != _fb_chain[0]:
                            _fb_chain.append(_c_fb)
                    _l_fb = getattr(CONSTANTS, "AI_GEMINI_FALLBACK", "")
                    if _l_fb and _l_fb not in _fb_chain:
                        _fb_chain.append(_l_fb)

                    _fb_last_exc = None
                    _fb_skip_cloud = False
                    _fb_model_used = active_model or ""
                    for _fb_i, _fb_model in enumerate(_fb_chain):
                        if _fb_skip_cloud and _fb_model.startswith(("gemini", "claude")):
                            continue
                        if _fb_model.startswith(("gemini", "claude")):
                            _fb_tools = (_WEB_TOOLS + _TERMINAL_TOOLS + _MEMORY_TOOLS
                                         + _SCREENSHOT_TOOLS + _NOTEPAD_TOOLS + _UI_TOOLS + _NEW_TOOLS
                                         + _MCP_TOOLS
                                         + _gemini_tool_definitions(_folder_path_for_tools))
                        else:
                            _fb_tools = (_WEB_TOOLS + _TERMINAL_TOOLS + _MEMORY_TOOLS
                                         + _SCREENSHOT_TOOLS + _NOTEPAD_TOOLS + _UI_TOOLS + _NEW_TOOLS
                                         + _MCP_TOOLS
                                         + _FOLDER_TOOLS)
                        try:
                            if _fb_model.startswith("gemini"):
                                _stream_iter = _gemini_chat_stream_with_tools(
                                    _fb_model, messages,
                                    tools=_fb_tools, temperature=CONSTANTS.AI_TEMPERATURE)
                            elif _fb_model.startswith("claude"):
                                _stream_iter = _claude_chat_stream_with_tools(
                                    _fb_model, messages,
                                    tools=_fb_tools, temperature=CONSTANTS.AI_TEMPERATURE)
                            else:
                                _stream_iter = _ollama_chat_stream_with_tools(
                                    CONSTANTS.AI_OLLAMA_URL, _fb_model, messages,
                                    tools=_fb_tools, temperature=CONSTANTS.AI_TEMPERATURE,
                                    think=True)
                            for _evt, _dat in _stream_iter:
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
                                    _visible = re.sub(
                                        r'<think>.*?</think>', '', _streamed, flags=re.DOTALL)
                                    if '<think>' in _visible:
                                        _visible = _visible[:_visible.index('<think>')]
                                    _visible = _visible.strip()
                                    if response_text_ctrl is None:
                                        if _visible:
                                            _remove_loading()
                                            response_text_ctrl = _ai_add_bubble(
                                                "assistant", _visible)
                                    elif _stream_token_count % _STREAM_UPDATE_EVERY == 0:
                                        response_text_ctrl.value = _md_dark(_visible)
                                        page.run_task(_scroll_and_update)
                            _fb_model_used = _fb_model
                            _ALL_TOOLS = _fb_tools
                            break  # succès
                        except Exception as exc:
                            if _streamed or _stream_tool_calls or response_text_ctrl is not None:
                                raise
                            _fb_last_exc = exc
                            _fb_skip_cloud = _fb_skip_cloud or _is_network_error(exc)
                            _fb_next = next(
                                (m for m in _fb_chain[_fb_i + 1:]
                                 if not (_fb_skip_cloud and m.startswith(("gemini", "claude")))),
                                None,
                            )
                            if _fb_next is not None and loading_ctrl is not None:
                                loading_ctrl.value = (
                                    f"⚠️ {_fb_model} indisponible"
                                    f" — basculement vers {_fb_next}…"
                                )
                                try:
                                    page.update()
                                except Exception:
                                    pass
                    else:
                        if _fb_last_exc:
                            raise _fb_last_exc

                    _remove_loading()  # Garantit la suppression même si aucun contenu visible n'est arrivé
                    tool_calls = _stream_tool_calls
                    # Fallback non-streaming si le stream n'a rien renvoyé (Ollama uniquement)
                    if not _streamed and not _stream_tool_calls:
                        if not _fb_model_used.startswith(("gemini", "claude")):
                            _fallback = _ollama_chat_once(
                                CONSTANTS.AI_OLLAMA_URL, _fb_model_used, messages,
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

                    if not tool_calls:
                        full_response = _strip_text_tool_calls(_streamed)
                        # Nettoyage des blocs <think> dans le contenu (think=False, Ollama ≥ 0.7)
                        if not _thinking and "<think>" in full_response:
                            _think_match = re.search(r'<think>(.*?)</think>', full_response, re.DOTALL)
                            if _think_match:
                                # Bloc complet <think>…</think>
                                _thinking = _think_match.group(1).strip()
                                full_response = re.sub(r'<think>.*?</think>', '', full_response, flags=re.DOTALL).strip()
                            else:
                                # Bloc <think> non fermé (stream interrompu en plein thinking)
                                full_response = full_response.split("<think>", 1)[0].strip()
                            if response_text_ctrl is not None:
                                response_text_ctrl.value = _md_dark(full_response)
                                try:
                                    page.update()
                                except Exception:
                                    pass
                        if _thinking and thinking_ctrl is None:
                            _ai_add_bubble("think", _thinking)
                        if _fb_model_used != (active_model or ""):
                            full_response = full_response + f"\n\n*↩ {_fb_model_used}*"
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
                    _tool_tasks          = []
                    _folder_tool_results = []  # traités séquentiellement avant le pool
                    _screenshot_b64s     = []
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
                            _tool_tasks.append((fn_name, fn_args))
                        elif fn_name == "fetch_url":
                            url     = fn_args.get("url", "")
                            short_u = (url[:45] + "…") if len(url) > 45 else url
                            ai_status_text.value = f"🌐 {short_u}"
                            if loading_ctrl is not None:
                                loading_ctrl.value = f"🌐 {short_u}"
                            _ai_add_bubble("assistant", f"🌐 Lecture : {url}")
                            _tool_tasks.append((fn_name, fn_args))
                        elif fn_name == "list_folder_contents":
                            _folder_display = os.path.basename(_folder_path_for_tools) if _folder_path_for_tools else "?"
                            _list_path = fn_args.get("path", "").strip() or _folder_path_for_tools or ""
                            _folder_display = os.path.basename(_list_path) if _list_path else "?"
                            ai_status_text.value = "📂 Lecture du dossier…"
                            _ai_add_bubble("assistant", f"📂 Lecture du dossier « {_folder_display} »")
                            try:
                                page.update()
                            except Exception:
                                pass
                            _folder_tool_results.append((fn_name, _folder_list_contents(_list_path)))
                        elif fn_name == "read_file_content":
                            _read_filename = fn_args.get("filename", "")
                            ai_status_text.value = f"📄 Lecture : {_read_filename}…"
                            _ai_add_bubble("assistant", f"📄 Lecture : {_read_filename}")
                            try:
                                page.update()
                            except Exception:
                                pass
                            _folder_tool_results.append((fn_name, _folder_read_file(
                                _folder_path_for_tools, _read_filename,
                                document_exts=CONSTANTS.AI_DOCUMENT_EXTS,
                            )))
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
                                            ft.ElevatedButton(
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
                                    _navigate(_folder_path_for_tools)
                                    _org_result_lines = [f"{len(_executed_moves)} fichier(s) déplacé(s)."] + _executed_moves
                                    if _move_errors:
                                        _org_result_lines += ["Erreurs :"] + _move_errors
                                    _folder_tool_results.append((fn_name, "\n".join(_org_result_lines)))
                        elif fn_name == "analyze_images":
                            _analyze_filenames = fn_args.get("filenames", [])
                            _analyze_question  = fn_args.get("question", "")
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
                                _analyze_model = active_model
                                _analysis_progress_ctrl = _ai_add_bubble(
                                    "assistant",
                                    f"📸 Analyse de {len(_analyze_candidates)} image(s)…",
                                )
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
                                _analyze_batch = (
                                    CONSTANTS.AI_GEMINI_FOLDER_BATCH_SIZE
                                    if (_analyze_model or "").startswith("gemini")
                                    else CONSTANTS.AI_FOLDER_SELECT_BATCH_SIZE
                                )
                                _analyze_results = _analyze_images_batched(
                                    CONSTANTS.AI_OLLAMA_URL,
                                    _analyze_model,
                                    _folder_path_for_tools,
                                    _analyze_candidates,
                                    _analyze_question,
                                    batch_size=_analyze_batch,
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
                        elif fn_name == "score_photos":
                            _score_filenames = fn_args.get("filenames", [])
                            _score_contexte  = fn_args.get("contexte", "")
                            _score_criteres  = fn_args.get("criteres_additionnels", [])
                            if not _score_filenames:
                                _score_candidates = sorted([
                                    entry.name for entry in os.scandir(_folder_path_for_tools)
                                    if entry.is_file()
                                    and os.path.splitext(entry.name)[1].lower() in CONSTANTS.IMAGE_EXTS
                                ])
                            else:
                                _score_candidates = [
                                    os.path.basename(fname) for fname in _score_filenames
                                    if os.path.isfile(
                                        os.path.join(_folder_path_for_tools, os.path.basename(fname))
                                    )
                                ]
                            if not _score_candidates:
                                _folder_tool_results.append((fn_name, "Aucune image trouvée."))
                            else:
                                _score_model = active_model
                                _score_progress_ctrl = _ai_add_bubble(
                                    "assistant",
                                    f"🏆 Score de {len(_score_candidates)} image(s)…",
                                )
                                def _on_score_progress(batch_num, total_batches):
                                    ai_status_text.value = f"🏆 Score lot {batch_num}/{total_batches}…"
                                    if _score_progress_ctrl:
                                        _score_progress_ctrl.value = _md_dark(
                                            f"🏆 Score — lot {batch_num}/{total_batches}…"
                                        )
                                    try:
                                        page.update()
                                    except Exception:
                                        pass
                                _score_batch = (
                                    CONSTANTS.AI_GEMINI_FOLDER_BATCH_SIZE
                                    if (_score_model or "").startswith("gemini")
                                    else CONSTANTS.AI_FOLDER_SELECT_BATCH_SIZE
                                )
                                _score_summary = _score_images_batched(
                                    CONSTANTS.AI_OLLAMA_URL,
                                    _score_model,
                                    _folder_path_for_tools,
                                    _score_candidates,
                                    contexte=_score_contexte,
                                    criteres_additionnels=_score_criteres,
                                    batch_size=_score_batch,
                                    image_exts=CONSTANTS.IMAGE_EXTS,
                                    max_size=CONSTANTS.AI_FOLDER_SELECT_IMAGE_SIZE,
                                    quality=CONSTANTS.AI_FOLDER_SELECT_QUALITY,
                                    on_progress=_on_score_progress,
                                    is_running=lambda: ai_streaming["value"],
                                )
                                if _score_progress_ctrl:
                                    _score_progress_ctrl.value = _md_dark(f"🏆 {_score_summary}")
                                try:
                                    page.update()
                                except Exception:
                                    pass
                                _folder_tool_results.append((fn_name, _score_summary))
                        elif fn_name == "ask_clarifying_question":
                            _q_question = fn_args.get("question", "")
                            _q_options  = (fn_args.get("options") or [])[:5]
                            _q_event    = threading.Event()
                            _q_result   = {"answer": None}

                            def _on_q_choice(choice):
                                def _handler(event=None):
                                    _q_result["answer"] = choice
                                    _q_dlg.open = False
                                    page.update()
                                    _q_event.set()
                                return _handler

                            _q_other_field = ft.TextField(label="Autre réponse…", width=380)

                            def _on_q_other(event=None):
                                _q_result["answer"] = (
                                    _q_other_field.value or ""
                                ).strip() or "(pas de réponse précisée)"
                                _q_dlg.open = False
                                page.update()
                                _q_event.set()

                            _q_dlg = ft.AlertDialog(
                                modal=True,
                                title=ft.Text("❓ Question de l'IA"),
                                content=ft.Column(
                                    [
                                        ft.Text(_q_question, size=13, color=WHITE),
                                        ft.Container(height=8),
                                        *[
                                            ft.Button(opt, bgcolor=BLUE, color=WHITE, on_click=_on_q_choice(opt))
                                            for opt in _q_options
                                        ],
                                        ft.Container(height=8),
                                        ft.Row([
                                            _q_other_field,
                                            ft.TextButton("Envoyer", on_click=_on_q_other),
                                        ]),
                                    ],
                                    tight=True,
                                    width=440,
                                ),
                            )
                            page.overlay.append(_q_dlg)
                            _q_dlg.open = True
                            try:
                                page.update()
                            except Exception:
                                pass
                            _q_event.wait(timeout=600)
                            _folder_tool_results.append(
                                (fn_name, _q_result["answer"] or "(Charles n'a pas répondu à temps)")
                            )
                        elif fn_name.startswith("mcp__"):
                            _folder_tool_results.append(
                                (fn_name, mcp_client.mcp_call_tool(fn_name, fn_args))
                            )
                        elif fn_name in ("generate_image", "edit_image"):
                            if _image_tool_done:
                                _folder_tool_results.append(
                                    (fn_name, "Action ignorée : une image a déjà été générée/modifiée pour cette demande.")
                                )
                                continue
                            # Une seule tentative image par demande utilisateur pour éviter
                            # les boucles de prompts (réessais en chaîne côté modèle).
                            _image_tool_done = True
                            _gi_prompt     = fn_args.get("prompt", "")
                            _gi_aspect     = fn_args.get("aspect_ratio", "1:1")
                            _gi_resolution = fn_args.get("resolution", "1K")
                            _gi_src_name   = ""
                            if fn_name == "generate_image":
                                _gi_out_filename = (
                                    fn_args.get("filename", "").strip()
                                    or f"generated_{datetime.datetime.now():%Y%m%d_%H%M%S}.png"
                                )
                                _gi_src_bytes = None
                                _gi_label = _gi_prompt[:60] + ("…" if len(_gi_prompt) > 60 else "")
                                _ai_add_bubble("assistant", f"🎨 Génération : {_gi_label}")
                            else:  # edit_image
                                _gi_src_name = fn_args.get("source_filename", "").strip()
                                _gi_out_filename = (
                                    fn_args.get("output_filename", "").strip()
                                    or f"edited_{datetime.datetime.now():%Y%m%d_%H%M%S}.png"
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

                            _gi_prompt_refined = _gi_prompt
                            if (active_model or "").startswith("gemini") and _gi_prompt.strip():
                                _gi_prompt_refined = _gemini_refine_image_prompt(
                                    intent_prompt=_gi_prompt,
                                    user_request=_original_user_request,
                                    mode=fn_name,
                                    source_filename=_gi_src_name,
                                    model=active_model,
                                )
                                if _gi_prompt_refined != _gi_prompt:
                                    _ai_add_bubble("assistant", "🧪 Prompt image affiné automatiquement.")

                            ai_status_text.value = "🎨 Génération d'image en cours…"
                            ai_progress_bar.visible = True
                            try:
                                page.update()
                            except Exception:
                                pass
                            _gi_timeout_seconds = int(getattr(CONSTANTS, "AI_GEMINI_IMAGE_TIMEOUT", 180))
                            _gi_result_holder = {"value": ("[ERREUR] Timeout Gemini image.", None)}
                            _gi_done_event = threading.Event()

                            def _run_gemini_image_call():
                                try:
                                    _gi_result_holder["value"] = _gemini_generate_image(
                                        _gi_prompt_refined,
                                        input_image_bytes=_gi_src_bytes,
                                        aspect_ratio=_gi_aspect,
                                        resolution=_gi_resolution,
                                    )
                                except Exception as _gi_exc:
                                    _gi_result_holder["value"] = (f"[ERREUR] {str(_gi_exc)}", None)
                                finally:
                                    _gi_done_event.set()

                            threading.Thread(target=_run_gemini_image_call, daemon=True).start()
                            _gi_start_time = time.time()
                            while not _gi_done_event.wait(timeout=1.0):
                                _gi_elapsed_s = int(time.time() - _gi_start_time)
                                if _gi_elapsed_s >= _gi_timeout_seconds:
                                    break
                                ai_status_text.value = f"🎨 Génération d'image en cours… ({_gi_elapsed_s}s)"
                                try:
                                    page.update()
                                except Exception:
                                    pass
                            if not _gi_done_event.is_set():
                                _gi_text, _gi_bytes = (
                                    f"[ERREUR] Timeout Gemini image après {_gi_timeout_seconds}s.",
                                    None,
                                )
                            else:
                                _gi_text, _gi_bytes = _gi_result_holder["value"]
                            ai_progress_bar.visible = False
                            if _gi_bytes:
                                _gi_dest_folder = _folder_path_for_tools or os.path.join(app_dir, "Generated")
                                os.makedirs(_gi_dest_folder, exist_ok=True)
                                _gi_save_path = os.path.join(_gi_dest_folder, _gi_out_filename)
                                with open(_gi_save_path, "wb") as _fout:
                                    _fout.write(_gi_bytes)
                                _ai_add_image_bubble(_gi_save_path)
                                if _folder_path_for_tools:
                                    page.pubsub.send_all_on_topic("refresh", None)
                                _gi_result = f"Image sauvegardée : {_gi_save_path}"
                                if _gi_text:
                                    _gi_result += (
                                        "\n\n"
                                        f"Réponse du service : {_gi_text}\n"
                                        f"Fichier : {_gi_save_path}"
                                    )
                            else:
                                _gi_result = "[ERREUR] Aucune image n'a été générée/sauvegardée."
                                if _gi_text:
                                    _gi_result += (
                                        "\n\nRéponse texte du service (sans image):\n"
                                        f"{_gi_text}"
                                    )
                            _folder_tool_results.append((fn_name, _gi_result))
                        elif fn_name == "generate_music":
                            _gm_prompt   = fn_args.get("prompt", "")
                            _gm_model    = fn_args.get("model", "lyria-3-clip-preview")
                            _gm_filename = (
                                fn_args.get("filename", "").strip()
                                or f"music_{datetime.datetime.now():%Y%m%d_%H%M%S}.mp3"
                            )
                            _gm_label = _gm_prompt[:60] + ("…" if len(_gm_prompt) > 60 else "")
                            _ai_add_bubble("assistant", f"🎵 Génération musique : {_gm_label}")
                            ai_status_text.value = "🎵 Génération musicale en cours…"
                            ai_progress_bar.visible = True
                            try:
                                page.update()
                            except Exception:
                                pass
                            _gm_result_holder = {"value": (None, None, "Timeout")}
                            _gm_done_event = threading.Event()

                            def _run_music_call():
                                try:
                                    _gm_result_holder["value"] = _gemini_generate_music(
                                        _gm_prompt, model=_gm_model
                                    )
                                except Exception as _gm_exc:
                                    _gm_result_holder["value"] = (None, None, str(_gm_exc))
                                finally:
                                    _gm_done_event.set()

                            threading.Thread(target=_run_music_call, daemon=True).start()
                            _gm_start = time.time()
                            while not _gm_done_event.wait(timeout=1.0):
                                _gm_elapsed = int(time.time() - _gm_start)
                                if _gm_elapsed >= 180:
                                    break
                                ai_status_text.value = f"🎵 Génération musicale en cours… ({_gm_elapsed}s)"
                                try:
                                    page.update()
                                except Exception:
                                    pass
                            ai_progress_bar.visible = False
                            _gm_bytes, _gm_lyrics, _gm_err = _gm_result_holder["value"]
                            if _gm_bytes:
                                _gm_dest = _folder_path_for_tools or os.path.join(app_dir, "Generated")
                                os.makedirs(_gm_dest, exist_ok=True)
                                _gm_save_path = os.path.join(_gm_dest, _gm_filename)
                                with open(_gm_save_path, "wb") as _fout:
                                    _fout.write(_gm_bytes)
                                if _folder_path_for_tools:
                                    page.pubsub.send_all_on_topic("refresh", None)
                                _gm_result = f"Musique sauvegardée : {_gm_save_path}"
                                if _gm_lyrics:
                                    _gm_result += f"\n\nParoles / Structure :\n{_gm_lyrics}"
                            else:
                                _gm_result = f"[ERREUR] Génération musicale échouée : {_gm_err}"
                            _folder_tool_results.append((fn_name, _gm_result))
                        elif fn_name == "create_file":
                            _create_filename = fn_args.get("filename", "").strip()
                            if not _create_filename:
                                _create_filename = f"fichier_{datetime.datetime.now():%Y%m%d_%H%M%S}.txt"
                            _create_content  = fn_args.get("content", "")
                            ai_status_text.value = f"📝 Création : {_create_filename}…"
                            _ai_add_bubble("assistant", f"📝 Création du fichier : {_create_filename}")
                            try:
                                page.update()
                            except Exception:
                                pass
                            _create_result = _folder_create_file(
                                _folder_path_for_tools, _create_filename, _create_content
                            )
                            page.pubsub.send_all_on_topic("refresh", None)
                            _folder_tool_results.append((fn_name, _create_result))
                        elif fn_name == "run_terminal_command":
                            _cmd      = fn_args.get("command", "")
                            _cmd_desc = fn_args.get("description", _cmd)
                            _cmd_admin = bool(fn_args.get("admin", False))
                            _cwd = _folder_path_for_tools if _folder_path_for_tools else None
                            if CONSTANTS.AI_TERMINAL_CONFIRM or _cmd_admin:
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

                                _cmd_dlg_content = [
                                    ft.Text(_cmd_desc, size=13, color=WHITE),
                                    ft.Container(height=8),
                                    ft.Container(
                                        ft.Text(_cmd, size=12, font_family="monospace", color=YELLOW),
                                        bgcolor=DARK,
                                        padding=10,
                                        border_radius=6,
                                    ),
                                ]
                                if _cmd_admin:
                                    _cmd_dlg_content.append(ft.Container(height=8))
                                    _cmd_dlg_content.append(
                                        ft.Text(
                                            "🔐 Une invite d'administrateur du système "
                                            "s'affichera ensuite (mot de passe/Touch ID/UAC).",
                                            size=12, color=YELLOW,
                                        )
                                    )
                                _cmd_dlg = ft.AlertDialog(
                                    modal=True,
                                    title=ft.Text(
                                        "🔐 Exécuter en administrateur" if _cmd_admin
                                        else "💻 Exécuter une commande"
                                    ),
                                    content=ft.Column(
                                        _cmd_dlg_content,
                                        tight=True,
                                        width=500,
                                    ),
                                    actions=[
                                        ft.TextButton("Annuler", on_click=_on_cmd_cancel),
                                        ft.ElevatedButton(
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
                            try:
                                page.update()
                            except Exception:
                                pass
                            _folder_tool_results.append(
                                (fn_name, _run_terminal_command(_cmd, cwd=_cwd, admin=_cmd_admin))
                            )
                        elif fn_name == "update_memory_file":
                            _mem_target  = fn_args.get("target", "")
                            _mem_action  = fn_args.get("action", "")
                            _mem_content = fn_args.get("content", "")
                            _mem_old     = fn_args.get("old_text", "")
                            ai_status_text.value = f"🧠 Mise à jour mémoire ({_mem_target})…"
                            try:
                                page.update()
                            except Exception:
                                pass
                            _mem_result = _update_memory_file(_mem_target, _mem_action, _mem_content, _mem_old)
                            # Bulle de statut indépendante du texte final de l'IA : si l'appel
                            # échoue, Charles le voit tout de suite même si la réponse prétend le contraire.
                            try:
                                _mem_ok = json.loads(_mem_result).get("success", False)
                            except Exception:
                                _mem_ok = False
                            if _mem_ok:
                                _ai_add_bubble("assistant", f"🧠 Mémoire mise à jour ({_mem_target} / {_mem_action})")
                            else:
                                _ai_add_bubble("assistant", f"⚠️ Échec mise à jour mémoire ({_mem_target} / {_mem_action}) — voir détails ci-dessous")
                            _folder_tool_results.append((fn_name, _mem_result))
                        elif fn_name == "read_notepad":
                            _np_current = notepad_field.value or ""
                            ai_status_text.value = "📝 Lecture du bloc-notes…"
                            _ai_add_bubble("assistant", "📝 Lecture du bloc-notes")
                            try:
                                page.update()
                            except Exception:
                                pass
                            _folder_tool_results.append(
                                (fn_name, _np_current if _np_current.strip() else "(Bloc-notes vide)")
                            )
                        elif fn_name == "write_notepad":
                            _np_content = fn_args.get("content", "")
                            _np_action  = fn_args.get("action", "replace")
                            # ponytail: jamais de remplacement silencieux d'un bloc-notes non
                            # vide — on retombe sur append tant que Charles n'a pas confirmé.
                            _np_blocked_replace = _np_action == "replace" and bool((notepad_field.value or "").strip())
                            if _np_blocked_replace:
                                _np_action = "append"
                            if _np_action == "replace":
                                notepad_field.value = _np_content
                            elif _np_action == "append":
                                notepad_field.value = (notepad_field.value or "") + "\n" + _np_content
                            elif _np_action == "prepend":
                                notepad_field.value = _np_content + "\n" + (notepad_field.value or "")
                            if notepad_is_preview["value"]:
                                notepad_markdown_preview.value = _prepare_notepad_markdown(notepad_field.value or "")
                            _notepad_save()
                            try:
                                notepad_field.update()
                                if notepad_is_preview["value"]:
                                    notepad_markdown_preview.update()
                            except Exception:
                                pass
                            if _np_blocked_replace:
                                ai_status_text.value = "📝 Remplacement refusé — ajouté à la suite"
                                _ai_add_bubble("assistant", "📝 Remplacement refusé (bloc-notes non vide) — contenu ajouté à la suite. Demande confirmation à Charles avant un vrai remplacement.")
                                _folder_tool_results.append(
                                    (fn_name, "Remplacement refusé : le bloc-notes n'est pas vide. Contenu ajouté en 'append' à la place. Si un remplacement complet est vraiment nécessaire, demande confirmation explicite à Charles dans le chat avant de réessayer.")
                                )
                            else:
                                ai_status_text.value = "📝 Bloc-notes mis à jour"
                                _ai_add_bubble("assistant", f"📝 Bloc-notes mis à jour ({_np_action})")
                                _folder_tool_results.append(
                                    (fn_name, f"Bloc-notes mis à jour ({_np_action}). Longueur : {len(notepad_field.value or '')} caractères.")
                                )
                        elif fn_name == "take_screenshot":
                            _ss_region = fn_args.get("region") or None
                            ai_status_text.value = "📸 Capture d'écran…"
                            _ai_add_bubble("assistant", "📸 Capture d'écran")
                            try:
                                page.update()
                            except Exception:
                                pass
                            _ss_capture = _take_screenshot(region=_ss_region)
                            if _ss_capture:
                                _screenshot_b64s.append(_ss_capture["b64"])
                                _folder_tool_results.append((fn_name, _ss_capture["text"]))
                                _ai_add_screenshot_bubble(_ss_capture["b64"])
                            else:
                                _folder_tool_results.append((fn_name, "Échec de la capture d'écran."))
                        elif fn_name == "mouse_click":
                            _mc_x      = int(fn_args.get("x", 0))
                            _mc_y      = int(fn_args.get("y", 0))
                            _mc_button = fn_args.get("button", "left")
                            _mc_clicks = fn_args.get("clicks", 1)
                            ai_status_text.value = f"🖱️ Clic ({_mc_x}, {_mc_y})…"
                            _ai_add_bubble("assistant", f"🖱️ Clic {_mc_button} à ({_mc_x}, {_mc_y})")
                            try:
                                page.update()
                            except Exception:
                                pass
                            _folder_tool_results.append(
                                (fn_name, _mouse_click(_mc_x, _mc_y, _mc_button, _mc_clicks))
                            )
                        elif fn_name == "keyboard_type":
                            _kt_text  = fn_args.get("text", "")
                            _kt_short = (_kt_text[:30] + "…") if len(_kt_text) > 30 else _kt_text
                            ai_status_text.value = f"⌨️ Saisie : {_kt_short}…"
                            _ai_add_bubble("assistant", f"⌨️ Saisie : « {_kt_short} »")
                            try:
                                page.update()
                            except Exception:
                                pass
                            _folder_tool_results.append((fn_name, _keyboard_type(_kt_text)))
                        elif fn_name == "keyboard_hotkey":
                            _kh_keys = fn_args.get("keys", [])
                            _kh_str  = "+".join(_kh_keys)
                            ai_status_text.value = f"⌨️ Raccourci : {_kh_str}…"
                            _ai_add_bubble("assistant", f"⌨️ Raccourci : {_kh_str}")
                            try:
                                page.update()
                            except Exception:
                                pass
                            _folder_tool_results.append(
                                (fn_name, _keyboard_hotkey(*_kh_keys))
                            )
                        elif fn_name == "navigate_to_folder":
                            _nav_path = fn_args.get("path", "").strip()
                            if not _nav_path or not os.path.isdir(_nav_path):
                                _folder_tool_results.append((fn_name, f"Dossier introuvable : {_nav_path or '(vide)'}"))
                            else:
                                _navigate(_nav_path)
                                _folder_path_for_tools = _nav_path
                                ai_status_text.value = f"📂 Navigation → {os.path.basename(_nav_path)}"
                                _ai_add_bubble("assistant", f"📂 Navigation vers : {_nav_path}")
                                try:
                                    page.update()
                                except Exception:
                                    pass
                                _folder_tool_results.append((fn_name, f"Dossier ouvert : {_nav_path}"))
                        elif fn_name == "select_files_in_ui":
                            _sel_names = fn_args.get("filenames", [])
                            _sel_mode  = fn_args.get("mode", "replace")
                            _folder_for_sel = _folder_path_for_tools or ""
                            if not _folder_for_sel:
                                _folder_tool_results.append((fn_name, "Aucun dossier ouvert pour sélectionner des fichiers."))
                            else:
                                if _sel_mode == "replace":
                                    selected_files.clear()
                                _changed = 0
                                for _sel_name in _sel_names:
                                    _sel_path = os.path.join(_folder_for_sel, os.path.basename(_sel_name))
                                    if os.path.exists(_sel_path):
                                        if _sel_mode == "remove":
                                            if _sel_path in selected_files:
                                                selected_files.discard(_sel_path)
                                                _changed += 1
                                        else:
                                            if _sel_path not in selected_files:
                                                selected_files.add(_sel_path)
                                                _changed += 1
                                page.pubsub.send_all_on_topic("refresh", None)
                                _verb = "retiré(s)" if _sel_mode == "remove" else "sélectionné(s)"
                                ai_status_text.value = f"✅ {_changed} fichier(s) {_verb}"
                                _ai_add_bubble("assistant", f"✅ {_changed} fichier(s) {_verb}. Sélection totale : {len(selected_files)} fichier(s).")
                                try:
                                    page.update()
                                except Exception:
                                    pass
                                _folder_tool_results.append(
                                    (fn_name, f"{_changed} fichier(s) {_verb}. Sélection totale : {len(selected_files)} fichier(s).")
                                )
                        elif fn_name == "delete_files":
                            _del_paths   = fn_args.get("paths", [])
                            _del_summary = fn_args.get("summary", "")
                            if not _del_paths:
                                _folder_tool_results.append((fn_name, "Aucun fichier à supprimer."))
                            else:
                                _del_confirmed = True
                                if CONSTANTS.AI_DELETE_CONFIRM:
                                    ai_status_text.value = "🗑️ Suppression — en attente de confirmation…"
                                    try:
                                        page.update()
                                    except Exception:
                                        pass
                                    _del_event  = threading.Event()
                                    _del_result = {"confirmed": False}

                                    def _on_del_confirm(event=None):
                                        _del_result["confirmed"] = True
                                        _del_dlg.open = False
                                        page.update()
                                        _del_event.set()

                                    def _on_del_cancel(event=None):
                                        _del_dlg.open = False
                                        page.update()
                                        _del_event.set()

                                    _del_rows = [
                                        ft.Text(f"• {p}", size=12, color=WHITE)
                                        for p in _del_paths[:40]
                                    ]
                                    if len(_del_paths) > 40:
                                        _del_rows.append(ft.Text(f"… et {len(_del_paths) - 40} autres", size=12, color=LIGHT_GREY))
                                    _del_dlg = ft.AlertDialog(
                                        modal=True,
                                        title=ft.Text("🗑️ Supprimer des fichiers"),
                                        content=ft.Column(
                                            [
                                                ft.Text(_del_summary or "Fichiers à supprimer :", size=13, color=WHITE),
                                                ft.Container(height=6),
                                                ft.Column(
                                                    _del_rows,
                                                    scroll=ft.ScrollMode.AUTO,
                                                    height=min(320, len(_del_rows) * 24),
                                                ),
                                            ],
                                            tight=True,
                                            width=500,
                                        ),
                                        actions=[
                                            ft.TextButton("Annuler", on_click=_on_del_cancel),
                                            ft.ElevatedButton(
                                                "Supprimer",
                                                bgcolor=ft.Colors.RED_700,
                                                color=WHITE,
                                                on_click=_on_del_confirm,
                                            ),
                                        ],
                                        actions_alignment=ft.MainAxisAlignment.END,
                                    )
                                    page.overlay.append(_del_dlg)
                                    _del_dlg.open = True
                                    try:
                                        page.update()
                                    except Exception:
                                        pass
                                    _del_event.wait(timeout=300)
                                    _del_confirmed = _del_result["confirmed"]
                                if not _del_confirmed:
                                    _folder_tool_results.append((fn_name, "Suppression annulée."))
                                else:
                                    _del_res = _folder_delete_files(_folder_path_for_tools, _del_paths)
                                    page.pubsub.send_all_on_topic("refresh", None)
                                    ai_status_text.value = "🗑️ Suppression effectuée"
                                    _ai_add_bubble("assistant", f"🗑️ Suppression effectuée")
                                    _turn_events.append("🗑️ Suppression effectuée")
                                    try:
                                        page.update()
                                    except Exception:
                                        pass
                                    _folder_tool_results.append((fn_name, _del_res))
                        elif fn_name == "move_file":
                            _mv_src = fn_args.get("source", "").strip()
                            _mv_dst = fn_args.get("destination", "").strip()
                            if not _mv_src or not _mv_dst:
                                _folder_tool_results.append((fn_name, "Paramètres source ou destination manquants."))
                            else:
                                _mv_res = _folder_move_file(_folder_path_for_tools, _mv_src, _mv_dst)
                                page.pubsub.send_all_on_topic("refresh", None)
                                _ai_add_bubble("assistant", f"📦 Déplacement : {os.path.basename(_mv_src)} → {_mv_dst}")
                                _turn_events.append(f"📦 Déplacement : {os.path.basename(_mv_src)} → {_mv_dst}")
                                try:
                                    page.update()
                                except Exception:
                                    pass
                                _folder_tool_results.append((fn_name, _mv_res))
                        elif fn_name == "copy_file":
                            _cp_src = fn_args.get("source", "").strip()
                            _cp_dst = fn_args.get("destination", "").strip()
                            if not _cp_src or not _cp_dst:
                                _folder_tool_results.append((fn_name, "Paramètres source ou destination manquants."))
                            else:
                                _cp_res = _folder_copy_file(_folder_path_for_tools, _cp_src, _cp_dst)
                                page.pubsub.send_all_on_topic("refresh", None)
                                _ai_add_bubble("assistant", f"📋 Copie : {os.path.basename(_cp_src)} → {_cp_dst}")
                                _turn_events.append(f"📋 Copie : {os.path.basename(_cp_src)} → {_cp_dst}")
                                try:
                                    page.update()
                                except Exception:
                                    pass
                                _folder_tool_results.append((fn_name, _cp_res))
                        elif fn_name == "create_folder":
                            _mkdir_path = fn_args.get("path", "").strip()
                            if not _mkdir_path:
                                _folder_tool_results.append((fn_name, "Chemin manquant."))
                            else:
                                _mkdir_res = _folder_create_folder(_folder_path_for_tools, _mkdir_path)
                                page.pubsub.send_all_on_topic("refresh", None)
                                _ai_add_bubble("assistant", f"📁 Dossier créé : {_mkdir_path}")
                                _turn_events.append(f"📁 Dossier créé : {_mkdir_path}")
                                try:
                                    page.update()
                                except Exception:
                                    pass
                                _folder_tool_results.append((fn_name, _mkdir_res))
                        elif fn_name == "read_exif":
                            _exif_files = fn_args.get("filenames", [])
                            if not _exif_files:
                                _folder_tool_results.append((fn_name, "Aucun fichier fourni."))
                            else:
                                _exif_res = _folder_read_exif(_folder_path_for_tools, _exif_files)
                                _folder_tool_results.append((fn_name, _exif_res))
                        elif fn_name == "zip_files":
                            _zip_paths = fn_args.get("paths", [])
                            _zip_name = fn_args.get("zip_name", "archive") or "archive"
                            _zip_dest = fn_args.get("destination", "") or None
                            if not _zip_paths:
                                _folder_tool_results.append((fn_name, "Aucun fichier fourni."))
                            else:
                                _zip_res = _folder_zip_files(_folder_path_for_tools, _zip_paths, _zip_name, _zip_dest)
                                page.pubsub.send_all_on_topic("refresh", None)
                                _ai_add_bubble("assistant", f"🗜️ Archive créée : {_zip_name}")
                                _turn_events.append(f"🗜️ Archive créée : {_zip_name}")
                                try:
                                    page.update()
                                except Exception:
                                    pass
                                _folder_tool_results.append((fn_name, _zip_res))
                        elif fn_name == "unzip_file":
                            _unzip_src = fn_args.get("source", "").strip()
                            _unzip_dest = fn_args.get("destination", "") or None
                            if not _unzip_src:
                                _folder_tool_results.append((fn_name, "Source manquante."))
                            else:
                                _unzip_res = _folder_unzip_file(_folder_path_for_tools, _unzip_src, _unzip_dest)
                                page.pubsub.send_all_on_topic("refresh", None)
                                _ai_add_bubble("assistant", f"📦 Extrait : {os.path.basename(_unzip_src)}")
                                _turn_events.append(f"📦 Extrait : {os.path.basename(_unzip_src)}")
                                try:
                                    page.update()
                                except Exception:
                                    pass
                                _folder_tool_results.append((fn_name, _unzip_res))
                        elif fn_name == "edit_file":
                            _ef_path = fn_args.get("filepath", "").strip()
                            _ef_old  = fn_args.get("old_string", "")
                            _ef_new  = fn_args.get("new_string", "")
                            if not _ef_path or _ef_old == "":
                                _folder_tool_results.append((fn_name, "Paramètres filepath / old_string manquants."))
                            else:
                                ai_status_text.value = f"✏️ Édition : {os.path.basename(_ef_path)}…"
                                _ai_add_bubble("assistant", f"✏️ Édition : {_ef_path}")
                                try:
                                    page.update()
                                except Exception:
                                    pass
                                _ef_res = _edit_file(_folder_path_for_tools, _ef_path, _ef_old, _ef_new)
                                page.pubsub.send_all_on_topic("refresh", None)
                                _folder_tool_results.append((fn_name, _ef_res))
                        elif fn_name == "read_file_lines":
                            _rl_path  = fn_args.get("filepath", "").strip()
                            _rl_start = fn_args.get("start_line", 1)
                            _rl_end   = fn_args.get("end_line", None)
                            if not _rl_path:
                                _folder_tool_results.append((fn_name, "Paramètre filepath manquant."))
                            else:
                                _rl_end_str = str(_rl_end) if _rl_end else "fin"
                                ai_status_text.value = f"📄 Lignes {_rl_start}–{_rl_end_str} : {os.path.basename(_rl_path)}…"
                                try:
                                    page.update()
                                except Exception:
                                    pass
                                _folder_tool_results.append(
                                    (fn_name, _read_file_lines(_folder_path_for_tools, _rl_path, _rl_start, _rl_end))
                                )
                        elif fn_name == "search_in_files":
                            _si_pattern = fn_args.get("pattern", "")
                            _si_path    = (fn_args.get("path", "") or "").strip() or None
                            _si_glob    = fn_args.get("file_glob", "*") or "*"
                            _si_max     = int(fn_args.get("max_results", 50) or 50)
                            _si_case    = bool(fn_args.get("case_sensitive", False))
                            if not _si_pattern:
                                _folder_tool_results.append((fn_name, "Paramètre 'pattern' manquant."))
                            else:
                                ai_status_text.value = f"🔎 Grep : {_si_pattern}…"
                                try:
                                    page.update()
                                except Exception:
                                    pass
                                _si_res = _search_in_files(
                                    _folder_path_for_tools, _si_pattern,
                                    path=_si_path, file_glob=_si_glob,
                                    max_results=_si_max, case_sensitive=_si_case,
                                )
                                _folder_tool_results.append((fn_name, _si_res))
                        elif fn_name == "find_files":
                            _ff_pattern  = fn_args.get("pattern", "")
                            _ff_basepath = (fn_args.get("base_path", "") or "").strip() or None
                            _ff_max      = int(fn_args.get("max_results", 200) or 200)
                            if not _ff_pattern:
                                _folder_tool_results.append((fn_name, "Paramètre 'pattern' manquant."))
                            else:
                                ai_status_text.value = f"🔎 Glob : {_ff_pattern}…"
                                try:
                                    page.update()
                                except Exception:
                                    pass
                                _ff_res = _find_files(
                                    _folder_path_for_tools, _ff_pattern,
                                    base_path=_ff_basepath, max_results=_ff_max,
                                )
                                _folder_tool_results.append((fn_name, _ff_res))
                        elif fn_name == "git_command":
                            _git_args = fn_args.get("args", [])
                            _git_cwd  = (fn_args.get("cwd", "") or "").strip() or _folder_path_for_tools or None
                            if not _git_args:
                                _folder_tool_results.append((fn_name, "Paramètre 'args' manquant."))
                            else:
                                _git_label = " ".join(str(a) for a in _git_args[:3])
                                ai_status_text.value = f"🔀 git {_git_label}…"
                                _ai_add_bubble("assistant", f"🔀 git {' '.join(str(a) for a in _git_args)}")
                                try:
                                    page.update()
                                except Exception:
                                    pass
                                _git_res = _git_command(_git_args, cwd=_git_cwd)
                                _folder_tool_results.append((fn_name, _git_res))
                        elif fn_name == "manage_tasks":
                            _task_res = _manage_tasks(
                                fn_args.get("action", "list"),
                                task_id=fn_args.get("task_id") or None,
                                title=fn_args.get("title") or None,
                                status=fn_args.get("status") or None,
                                notes=fn_args.get("notes") or None,
                            )
                            _folder_tool_results.append((fn_name, _task_res))
                        elif fn_name == "read_pdf":
                            _pdf_path  = fn_args.get("filepath", "").strip()
                            _pdf_pages = fn_args.get("pages") or None
                            if not _pdf_path:
                                _folder_tool_results.append((fn_name, "Paramètre 'filepath' manquant."))
                            else:
                                ai_status_text.value = f"📄 PDF : {os.path.basename(_pdf_path)}…"
                                try:
                                    page.update()
                                except Exception:
                                    pass
                                _pdf_res = _read_pdf(_folder_path_for_tools, _pdf_path, pages=_pdf_pages)
                                _folder_tool_results.append((fn_name, _pdf_res))
                        elif fn_name == "ask_subagent":
                            _sa_task    = fn_args.get("task", "")
                            _sa_context = fn_args.get("context") or None
                            _sa_model   = fn_args.get("model") or None
                            if not _sa_task:
                                _folder_tool_results.append((fn_name, "Paramètre 'task' manquant."))
                            else:
                                _sa_short = (_sa_task[:50] + "…") if len(_sa_task) > 50 else _sa_task
                                ai_status_text.value = f"🤖 Sous-agent : {_sa_short}…"
                                _ai_add_bubble("assistant", f"🤖 Sous-agent : {_sa_short}")
                                try:
                                    page.update()
                                except Exception:
                                    pass
                                _sa_res = _ask_subagent(_sa_task, context=_sa_context, model=_sa_model)
                                _folder_tool_results.append((fn_name, _sa_res))
                        elif fn_name == "schedule_task":
                            ai_status_text.value = f"⏰ Planificateur : {fn_args.get('action', 'list')}…"
                            try:
                                page.update()
                            except Exception:
                                pass
                            _sched_res = _schedule_task(
                                fn_args.get("action", "list"),
                                name=fn_args.get("name") or None,
                                command=fn_args.get("command") or None,
                                when=fn_args.get("when") or None,
                            )
                            _folder_tool_results.append((fn_name, _sched_res))
                        elif fn_name == "http_request":
                            _hr_method = (fn_args.get("method", "GET") or "GET").upper()
                            _hr_url = fn_args.get("url", "").strip()
                            if not _hr_url:
                                _folder_tool_results.append((fn_name, "Paramètre 'url' manquant."))
                            else:
                                ai_status_text.value = f"🌐 {_hr_method} {_hr_url[:60]}…"
                                try:
                                    page.update()
                                except Exception:
                                    pass
                                _hr_res = _http_request(
                                    _hr_method, _hr_url,
                                    headers=fn_args.get("headers") or None,
                                    body=fn_args.get("body") or None,
                                    timeout=fn_args.get("timeout") or 30,
                                )
                                _folder_tool_results.append((fn_name, _hr_res))
                        elif fn_name == "ssh_command":
                            _ssh_host = fn_args.get("host", "").strip()
                            _ssh_user = fn_args.get("username", "").strip()
                            _ssh_cmd  = fn_args.get("command", "")
                            if not _ssh_host or not _ssh_user or not _ssh_cmd:
                                _folder_tool_results.append((fn_name, "Paramètres 'host', 'username' et 'command' requis."))
                            else:
                                ai_status_text.value = f"🔐 SSH {_ssh_user}@{_ssh_host}…"
                                try:
                                    page.update()
                                except Exception:
                                    pass
                                _ssh_pwd = get_or_ask_credential(_ssh_host, _ssh_user)
                                if _ssh_pwd is None:
                                    _folder_tool_results.append((fn_name, "Connexion annulée par l'utilisateur (mot de passe non fourni)."))
                                else:
                                    _ssh_res = _ssh_command(
                                        _ssh_host, _ssh_user, _ssh_pwd, _ssh_cmd,
                                        port=fn_args.get("port") or 22,
                                        timeout=fn_args.get("timeout") or 30,
                                    )
                                    _folder_tool_results.append((fn_name, _ssh_res))
                        elif fn_name == "read_spreadsheet":
                            _ss_path = fn_args.get("filepath", "").strip()
                            if not _ss_path:
                                _folder_tool_results.append((fn_name, "Paramètre 'filepath' manquant."))
                            else:
                                ai_status_text.value = f"📊 Tableur : {os.path.basename(_ss_path)}…"
                                try:
                                    page.update()
                                except Exception:
                                    pass
                                _ss_res = _read_spreadsheet(
                                    _folder_path_for_tools, _ss_path,
                                    sheet=fn_args.get("sheet") or None,
                                    max_rows=fn_args.get("max_rows") or 100,
                                )
                                _folder_tool_results.append((fn_name, _ss_res))
                    # Remonter les erreurs/avertissements d'outils dans le chat (visible même
                    # quand le terminal est masqué en mode IA), pas seulement au modèle.
                    for _tr_name, _tr_result in _folder_tool_results:
                        if isinstance(_tr_result, str) and _tr_result.startswith(("[Erreur]", "[ATTENTION]")):
                            _ai_add_bubble("assistant", f"⚠️ {_tr_name} : {_tr_result}")
                    try:
                        page.update()
                    except Exception:
                        pass
                    # ── Injecter les résultats d'outils dans l'historique ────────────────
                    # Exécuter tous les outils web/URL en parallèle
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
                    if _screenshot_b64s:
                        messages.append({
                            "role": "user",
                            "content": "Voici la/les capture(s) d'écran demandée(s) :",
                            "images": _screenshot_b64s,
                        })
                    if _text_parsed_tools:
                        # Gemma ne supporte pas role="tool" — injecter les résultats
                        # comme message user pour éviter HTTP 500 au deuxième appel.
                        _results_lines = [f"[{_tn}]: {_tr}" for _tn, _tr in _all_tool_results]
                        messages.append({
                            "role": "user",
                            "content": "Résultats des outils :\n" + "\n\n".join(_results_lines),
                        })
                    else:
                        for _t_name, _t_result in _all_tool_results:
                            messages.append({"role": "tool", "tool_name": _t_name, "name": _t_name, "content": _t_result})
                        messages.append({"role": "user", "content": (
                            "Voici les résultats des outils. Si d'autres outils sont nécessaires "
                            "pour terminer la tâche, utilise-les. Sinon, réponds à l'utilisateur."
                        )})
                    _remove_loading()

                # Sécurité au cas où la boucle d'outils n'aurait pas été exécutée
                _turn_events = locals().get('_turn_events', [])
                _thinking = locals().get('_thinking', "")

                _last_user_text = next(
                    (m["content"] for m in reversed(ai_conversation) if m["role"] == "user"),
                    message_text
                )

                if full_response:
                    _entry = {"role": "assistant", "content": full_response}
                    if _thinking:
                        _entry["thinking"] = _thinking
                    if _turn_events:
                        _entry["events"] = _turn_events
                    ai_conversation.append(_entry)
                    _ai_save_history()

                    # 📝 Log permanent dans le fichier Markdown
                    _log_exchange_to_md(_last_user_text, full_response, _thinking, _turn_events)
                else:
                    _fallback_response = "[Aucune réponse reçue]"
                    if _thinking:
                        # La réflexion a déjà été affichée — sauvegarder sans ajouter de bulle d'erreur par-dessus
                        _entry = {"role": "assistant", "content": _fallback_response, "thinking": _thinking}
                        if _turn_events:
                            _entry["events"] = _turn_events
                        ai_conversation.append(_entry)
                        _ai_save_history()
                    else:
                        if _turn_events:
                            ai_conversation.append({"role": "assistant", "content": _fallback_response, "events": _turn_events})
                            _ai_save_history()
                        _ai_add_bubble("assistant", _fallback_response)

                    # 📝 Log permanent même s'il n'y a pas eu de réponse
                    _log_exchange_to_md(_last_user_text, _fallback_response, _thinking, _turn_events)
            except Exception as exc:
                _ai_add_bubble("assistant", f"[ERREUR] {exc}")
                full_response = ""
            finally:
                ai_streaming["value"] = False
                ai_stop_button.icon_color = LIGHT_GREY
                ai_status_text.value = ""
                ai_progress_bar.visible = False
                try:
                    page.update()
                except Exception:
                    pass
                if full_response and ai_tts_enabled["value"]:
                    threading.Thread(target=_speak_bubble, args=(full_response,), daemon=True).start()
                async def _refocus():
                    try:
                        await ai_input_field.focus()
                    except Exception:
                        pass
                page.run_task(_refocus)

        threading.Thread(target=_run, daemon=True).start()

    def _mic_toggle():
        """Bascule l'enregistrement micro (clic pour démarrer / arrêter)."""
        if _mic_state["active"]:
            _mic_stop()
        else:
            _mic_start()

    def _mic_start():
        """Démarre l'enregistrement micro."""
        if _mic_state["active"]:
            return

        def _on_ready():
            # Appelé depuis le thread audio dès que le micro capte réellement.
            async def _flip():
                if not _mic_state["active"]:
                    return
                ai_mic_button.icon = ft.Icons.STOP_CIRCLE
                ai_mic_button.icon_color = RED
                ai_mic_button.tooltip = "Enregistrement… cliquer pour arrêter"
                ai_status_text.value = (
                    "🎤 Parlez maintenant… (recliquer pour arrêter)")
                for control in (ai_mic_button, ai_status_text):
                    try:
                        control.update()
                    except Exception:
                        pass
            page.run_task(_flip)

        try:
            recorder = _MicRecorder(
                sample_rate=CONSTANTS.AI_VOICE_STT_SAMPLE_RATE)
            recorder.start(on_ready=_on_ready)
        except Exception:
            ai_status_text.value = "Micro indisponible"
            try:
                ai_status_text.update()
            except Exception:
                pass
            return
        _mic_state["rec"] = recorder
        _mic_state["active"] = True
        # État « préparation » tant que le micro n'a pas démarré (~1 s sous
        # Windows, davantage en Bluetooth) : évite de perdre le début.
        ai_mic_button.icon = ft.Icons.MIC
        ai_mic_button.icon_color = ORANGE
        ai_mic_button.tooltip = "Préparation du micro…"
        ai_status_text.value = "⏳ Préparation du micro… (attendez le rouge)"
        for control in (ai_mic_button, ai_status_text):
            try:
                control.update()
            except Exception:
                pass

    def _mic_stop(auto_send=False):
        """Arrête l'enregistrement, transcrit via Gemini et insère le texte.

        Si ``auto_send`` est vrai (relâchement du bouton PTT), le message
        est envoyé à l'IA aussitôt transcrit, sans attendre une validation
        manuelle — permet de dicter sans revenir devant l'application.
        """
        if not _mic_state["active"]:
            return
        _mic_state["active"] = False
        recorder = _mic_state["rec"]
        _mic_state["rec"] = None
        ai_mic_button.icon = ft.Icons.MIC_NONE
        ai_mic_button.icon_color = LIGHT_GREY
        ai_mic_button.tooltip = "Cliquer pour dicter (Gemini) — recliquer pour arrêter"
        ai_status_text.value = "Transcription en cours…"
        for control in (ai_mic_button, ai_status_text):
            try:
                control.update()
            except Exception:
                pass

        def _worker():
            text = None
            diag = ""
            try:
                wav = recorder.stop() if recorder else None
                if wav:
                    # Diagnostic : capté vs réel vs pertes (distingue un souci
                    # de capture Bluetooth d'un souci de transcription Gemini).
                    try:
                        import os
                        import tempfile
                        rate = getattr(recorder, "sample_rate", 0) or 1
                        dur = (len(wav) - 44) / 2.0 / rate
                        real = getattr(recorder, "elapsed", 0.0)
                        drops = getattr(recorder, "_overflows", 0)
                        diag = (f"🎙 {dur:.1f}s captées / {real:.1f}s réelles "
                                f"@ {rate}Hz — {drops} pertes")
                        dbg = os.path.join(tempfile.gettempdir(),
                                           "dictee_debug.wav")
                        with open(dbg, "wb") as debug_file:
                            debug_file.write(wav)
                    except Exception:
                        pass
                    text = _gemini_transcribe_audio(
                        wav,
                        language_code=CONSTANTS.AI_VOICE_STT_LANGUAGE,
                        model=CONSTANTS.AI_VOICE_STT_MODEL,
                    )
            except Exception:
                pass

            async def _apply():
                if text:
                    existing = (ai_input_field.value or "").rstrip()
                    combined = f"{existing} {text}" if existing else text
                    ai_status_text.value = diag
                    if auto_send and not ai_streaming["value"]:
                        ai_input_field.value = ""
                        ai_input_field.update()
                        _send_ai_message(combined.strip())
                    else:
                        ai_input_field.value = combined
                        ai_input_field.update()
                        try:
                            await ai_input_field.focus()
                        except Exception:
                            pass
                else:
                    ai_status_text.value = (diag + " — aucun texte") if diag \
                        else "Aucun texte reconnu"
                try:
                    ai_status_text.update()
                except Exception:
                    pass
            page.run_task(_apply)

        threading.Thread(target=_worker, daemon=True).start()

    def _mic_hotkey_start():
        """Écoute CONSTANTS.AI_VOICE_PTT_KEY : bouton PTT (CircuitPython).

        Touche f13-f20 (aucun clavier standard ne la produit — aucun risque
        de déclenchement accidentel). Appui maintenu = enregistre,
        relâchement = transcrit et envoie directement le message à l'IA,
        même si SidePanel n'a pas le focus (raccourci global).

        Priorité sur Dashboard.pyw : si Side Panel a été lancé depuis
        Dashboard, Dashboard s'efface de lui-même sur cette touche tant que
        ce processus tourne (voir ``_mic_state["side_panel_priority"]``
        dans Dashboard.pyw) — Side Panel n'a rien à faire de son côté.
        """
        try:
            from pynput import keyboard as _pynput_kb
        except ImportError:
            return

        ptt_key = getattr(_pynput_kb.Key, CONSTANTS.AI_VOICE_PTT_KEY, None)
        if ptt_key is None:
            return

        # pynput ne livre pas toujours la même représentation à l'appui et
        # au relâchement (X11/Linux : Key.f15 à l'appui, KeyCode brut au
        # relâchement) — on compare aussi le vk pour reconnaître la même
        # touche physique dans les deux sens.
        target_vk = getattr(getattr(ptt_key, "value", ptt_key), "vk", None)

        def _is_ptt(key):
            if key == ptt_key:
                return True
            vk = getattr(getattr(key, "value", key), "vk", None)
            return target_vk is not None and vk == target_vk

        async def _press_async():
            _mic_start()

        async def _release_async():
            _mic_stop(auto_send=True)

        def _on_press(key):
            if _is_ptt(key):
                page.run_task(_press_async)

        def _on_release(key):
            if _is_ptt(key):
                page.run_task(_release_async)

        try:
            listener = _pynput_kb.Listener(
                on_press=_on_press, on_release=_on_release)
            listener.daemon = True
            listener.start()
        except Exception:
            return
        _mic_state["hotkey_listener"] = listener

    _mic_hotkey_start()

    async def _ai_paste_clipboard(auto_send=False):
        """Colle le presse-papiers dans le champ IA (dictée vocale Wispr Flow).

        Les champs Flutter n'acceptent pas l'insertion directe des outils de
        dictée ; on récupère donc le texte via le presse-papiers. Si
        ``auto_send`` est vrai, le message est envoyé dans la foulée.
        """
        try:
            clip = await ft.Clipboard().get()
        except Exception:
            return
        if not clip or not clip.strip():
            ai_status_text.value = "Presse-papiers vide"
            try:
                ai_status_text.update()
            except Exception:
                pass
            return
        clip = clip.strip()
        existing = (ai_input_field.value or "").rstrip()
        ai_input_field.value = f"{existing} {clip}" if existing else clip
        ai_input_field.update()
        try:
            await ai_input_field.focus()
        except Exception:
            pass
        if auto_send:
            _on_ai_submit()

    def _on_ai_submit():
        """Récupère le texte saisi, vide le champ et envoie le message à l'IA."""
        message_text = ai_input_field.value.strip()
        # Champ vide : coller le presse-papiers (dictée vocale) puis envoyer.
        if not message_text and not ai_pending_images and not ai_pending_files:
            page.run_task(_ai_paste_clipboard, True)
            return
        ai_input_field.value = ""
        ai_input_field.update()
        async def _refocus():
            try:
                await ai_input_field.focus()
            except Exception:
                pass
        page.run_task(_refocus)
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

    # Connexions boutons IA
    ai_input_field.on_submit = lambda event: _on_ai_submit()
    ai_send_button.on_click     = lambda event: _on_ai_submit()
    ai_attach_button.on_click   = lambda event: page.run_task(_ai_pick_any)
    ai_speaker_button.on_click  = lambda event: _toggle_tts()
    ai_stop_button.on_click     = _ai_stop_model
    ai_clear_button.on_click    = _clear_ai_conversation
    ai_copy_button.on_click     = lambda e: _export_ai_conversation(to_notepad=False)

    async def _new_json_file(event):
        """Crée un nouveau fichier JSON vide : choix du dossier puis du nom."""
        initial_directory = current_src["path"] or (
            os.path.dirname(json_path["value"])
            if json_path["value"] and os.path.isfile(json_path["value"])
            else None
        )
        folder = await ft.FilePicker().get_directory_path(
            dialog_title="Choisir l'emplacement du nouveau fichier JSON",
            initial_directory=initial_directory,
        )
        if not folder:
            return

        name_field = ft.TextField(
            label="Nom du fichier",
            hint_text="ex: ma_liste",
            suffix=ft.Text(".json", color=LIGHT_GREY),
            autofocus=True,
            bgcolor=DARK, border_color=VIOLET, text_size=13,
            width=320,
        )
        dialog = ft.AlertDialog(
            title=ft.Text("Nouveau fichier JSON"),
            content=ft.Column([
                ft.Text(
                    folder, size=11, color=LIGHT_GREY,
                    overflow=ft.TextOverflow.ELLIPSIS, max_lines=1,
                ),
                name_field,
            ], spacing=8, tight=True, width=360),
        )

        def _confirm(inner_event):
            file_name = (name_field.value or "").strip()
            if not file_name:
                name_field.error_text = "Requis"
                page.update()
                return
            if not file_name.lower().endswith(".json"):
                file_name = file_name + ".json"
            file_path = os.path.join(folder, file_name)
            dialog.open = False
            page.update()
            try:
                with open(file_path, "w", encoding="utf-8") as file_handle:
                    json.dump([], file_handle, ensure_ascii=False, indent=2)
                json_path["value"]    = file_path
                json_path_field.value = file_path
                json_path_field.update()
                _add_recent_json(file_path)
                _persist()
                _load_and_render()
                list_status.value = f"[OK] Créé : {file_name}"
            except Exception as exception:
                list_status.value = f"[ERREUR] {exception}"
            page.update()

        def _cancel(inner_event):
            dialog.open = False
            page.update()

        name_field.on_submit = _confirm
        dialog.actions = [
            ft.TextButton("Annuler", on_click=_cancel),
            ft.TextButton("Créer", on_click=_confirm),
        ]
        page.overlay.append(dialog)
        dialog.open = True
        page.update()


    # ═════════════════════════════════════════════════════════════════════
    #  ██  Actions fenêtre
    # ═════════════════════════════════════════════════════════════════════

    async def _close(event):
        await page.window.close()
        os._exit(0)

    # ── Fenêtre & événements ──────────────────────────────────────────────────
    def _minimize(event):
        page.window.minimized = True

    def _toggle_maximize(event):
        page.window.maximized = not page.window.maximized
        page.update()

    def _on_window_event(event):
        if event.data == "close":
            os._exit(0)

    page.window.on_event = _on_window_event

    # ═════════════════════════════════════════════════════════════════════
    #  ██  Connexions
    # ═════════════════════════════════════════════════════════════════════

    select_toggle_btn.on_click = _toggle_all
    invert_btn.on_click        = _invert
    file_filter_btn.on_click   = _toggle_file_filter
    sort_segment.on_change     = _on_sort_change
    search_field.on_change     = _on_search_change
    search_field.on_submit     = _on_search_change
    search_close_btn.on_click  = _clear_search
    prev_page_btn.on_click     = lambda event: _go_to_page(-1)
    next_page_btn.on_click     = lambda event: _go_to_page(+1)
    copy_btn.on_click          = _copy_selection
    src_path_field.on_submit   = lambda event: (
        _navigate((src_path_field.value or "").strip())
    )

    def _on_tab_change(event):
        """Sauvegarde les notes automatiquement quand on quitte l'onglet Bloc-notes."""
        _notepad_save()

    list_search_field.on_change    = _on_list_search_change
    list_search_field.on_submit    = _on_list_search_change
    list_sort_segment.on_change    = _on_list_sort_change
    json_path_field.on_submit      = _on_json_path_submit
    filter_sel_btn.on_click        = _toggle_list_filter
    deselect_all_list_btn.on_click  = _deselect_all_list


    # ═════════════════════════════════════════════════════════════════════
    #  ██  Layout — Onglet 1
    # ═════════════════════════════════════════════════════════════════════

    tab1 = ft.Column([
        # ── Ligne source ─────────────────────────────────────────────
        ft.Row([
            ft.IconButton(
                icon=ft.Icons.ARROW_UPWARD, icon_color=BLUE,
                icon_size=18, tooltip="Dossier parent",
                on_click=_go_parent,
            ),
            src_path_field,
            recent_src_btn,
            ft.IconButton(
                icon=ft.Icons.FOLDER_OPEN, icon_color=ICON_ACTION,
                icon_size=20, tooltip="Parcourir...",
                on_click=_pick_src,
            ),
            ft.IconButton(
                icon=ft.Icons.REFRESH, icon_color=BLUE,
                icon_size=20, tooltip="Rafraîchir",
                on_click=lambda event: _refresh_preview(),
            ),
            ft.IconButton(
                icon=ft.Icons.OPEN_IN_NEW, icon_color=GREEN,
                icon_size=18, tooltip="Ouvrir dans l'explorateur",
                on_click=_open_in_explorer,
            ),
            
        ], spacing=4, vertical_alignment=ft.CrossAxisAlignment.CENTER),

        # ── Barre de sélection + recherche ───────────────────────────
        ft.Row([
            file_filter_btn,
            select_toggle_btn,
            invert_btn,
            ft.IconButton(
                icon=ft.Icons.SMART_TOY, icon_color=BLUE,
                icon_size=18, tooltip="Envoyer la sélection à l'IA",
                on_click=_send_selection_to_ai,
            ),
            search_field,
            search_close_btn,
            ft.Container(expand=True),
            selection_count_text,
            file_count_text,
            sort_segment,
            prev_page_btn,
            page_indicator,
            next_page_btn,
        ], spacing=4, vertical_alignment=ft.CrossAxisAlignment.CENTER),

        # ── Liste de prévisualisation ─────────────────────────────────
        ft.Container(
            content=ft.Stack([preview_list, preview_loading]),
            expand=True,
            border=ft.Border.all(1, GREY),
            border_radius=8,
            bgcolor=DARK,
        ),

        # ── Section destination ───────────────────────────────────────
        ft.Container(
            content=ft.Column([
                ft.Row([
                    ft.Icon(ft.Icons.FOLDER_SPECIAL, color=GREEN, size=16),
                    ft.Text("Vers :", size=13, color=GREEN,
                            weight=ft.FontWeight.W_500),
                    dst_path_field,
                    ft.IconButton(
                        icon=ft.Icons.FOLDER_OPEN, icon_color=GREEN,
                        icon_size=18, tooltip="Parcourir...",
                        on_click=_pick_dst,
                    ),
                    copy_btn,
                ], spacing=4, vertical_alignment=ft.CrossAxisAlignment.CENTER),
                copy_progress,
                status_text,
            ], spacing=6, tight=True),
            bgcolor=GREY,
            border_radius=8,
            padding=ft.Padding(10, 8, 10, 8),
        ),
    ], expand=True, spacing=6)


    # ═════════════════════════════════════════════════════════════════════
    #  ██  Layout — Onglet 2
    # ═════════════════════════════════════════════════════════════════════

    tab2 = ft.Column([
        # ── Ligne fichier JSON ────────────────────────────────────────
        ft.Row([
            ft.Icon(ft.Icons.DATA_OBJECT, color=VIOLET, size=18),
            json_path_field,
            recent_json_btn,
            ft.IconButton(
                icon=ft.Icons.FOLDER_OPEN, icon_color=VIOLET,
                icon_size=18, tooltip="Ouvrir un fichier JSON",
                on_click=_pick_json,
            ),
            ft.IconButton(
                icon=ft.Icons.NOTE_ADD_OUTLINED, icon_color=YELLOW,
                icon_size=18, tooltip="Créer un nouveau fichier JSON",
                on_click=_new_json_file,
            ),
            ft.IconButton(
                icon=ft.Icons.REFRESH, icon_color=BLUE,
                icon_size=18, tooltip="Rafraîchir (relire le fichier depuis le disque)",
                on_click=lambda e: _load_and_render(),
            ),
        ], spacing=4, vertical_alignment=ft.CrossAxisAlignment.CENTER),

        # ── Barre de recherche + tri + ajout ─────────────────────────
        ft.Row([
            ft.Container(
                content=ft.Row([
                    ft.Icon(ft.Icons.ADD, size=14, color=DARK),
                    ft.Text("Ajouter", size=12, color=DARK,
                            weight=ft.FontWeight.BOLD),
                ], spacing=4),
                bgcolor=VIOLET, border_radius=6,
                padding=ft.Padding(5, 5, 5, 5),
                on_click=_add_entry, ink=True,
                tooltip="Ajouter une entrée",
            ),
            list_search_field,
            filter_sel_btn,
            deselect_all_list_btn,
            ft.Container(expand=True),
            list_sort_segment,
        ], spacing=4, vertical_alignment=ft.CrossAxisAlignment.CENTER),

        ft.Text(
            "Cliquer sur le nom (bleu) copie le nom, cliquer sur la description (gris) copie la description.",
            size=11, color=LIGHT_GREY, italic=True,
        ),

        # ── Liste ─────────────────────────────────────────────────────
        ft.Container(
            content=list_view,
            expand=True,
            border=ft.Border.all(1, GREY),
            border_radius=8,
            bgcolor=DARK,
            padding=ft.Padding(4, 4, 4, 4),
        ),

        # ── Bas ───────────────────────────────────────────────────────
        ft.Row([
            list_count,
            ft.Container(expand=True),
            list_status,
        ], spacing=4),
    ], expand=True, spacing=6)


    # ═════════════════════════════════════════════════════════════════════
    #  ██  Layout — Onglet 3 (Bloc-notes)
    # ═════════════════════════════════════════════════════════════════════

    tab3 = ft.Column([
        ft.Row([
            ft.Icon(ft.Icons.EDIT_NOTE, color=VIOLET, size=16),
            ft.Text("Notes", color=VIOLET, size=13, weight=ft.FontWeight.BOLD),
            ft.Container(expand=True),
            notepad_preview_btn,
            ft.IconButton(
                icon=ft.Icons.DELETE_OUTLINE,
                icon_color=RED,
                icon_size=18,
                tooltip="Effacer le bloc-notes",
                on_click=_notepad_clear,
            ),
        ], spacing=4, vertical_alignment=ft.CrossAxisAlignment.CENTER),
        ft.Container(
            content=ft.Column([
                notepad_field,
                notepad_preview_scroll,
            ], spacing=0, expand=True),
            expand=True,
            border=ft.Border.all(1, VIOLET),
            border_radius=8,
            bgcolor=DARK,
            padding=ft.Padding(4, 4, 4, 4),
        ),
    ], expand=True, spacing=6)


    # ═════════════════════════════════════════════════════════════════════
    #  ██  Layout — Onglet 4 (IA)
    # ═════════════════════════════════════════════════════════════════════

    _ai_tab4_header = ft.Row([
        ft.Icon(ft.Icons.SMART_TOY, color=BLUE, size=16),
        ft.Text("IA", color=BLUE, size=13, weight=ft.FontWeight.BOLD),
        ft.Container(width=4),
        ai_model_dropdown,
        ft.Container(width=4),
        ft.Container(
            content=ft.Row([ai_stop_button], spacing=0),
            border=ft.Border.all(1, GREY),
            border_radius=6,
            padding=ft.Padding(0, 0, 0, 0),
        ),
        ft.Container(width=8),
        ft.Container(content=ai_status_text, expand=True),
        ai_copy_button,
        ai_clear_button,
        ai_speaker_button,
        ft.IconButton(
            icon=ft.Icons.SEND_TO_MOBILE,
            icon_color=VIOLET,
            icon_size=16,
            tooltip="Transférer la conversation vers le bloc-notes",
            on_click=lambda e: _export_ai_conversation(to_notepad=True),
        ),
        ft.IconButton(
            icon=ft.Icons.OPEN_IN_FULL,
            icon_color=LIGHT_GREY,
            icon_size=16,
            tooltip="IA + Bloc-notes côte à côte (plein écran)",
            on_click=_open_ai_notepad_fullscreen,
        ),
    ], spacing=2, vertical_alignment=ft.CrossAxisAlignment.CENTER)
    tab4 = ft.Column([
        _ai_tab4_header,
        ft.Container(
            content=ft.Column([
                ai_chat_view,
                ai_attach_row,
                ai_progress_bar,
                ft.Row([
                    ai_attach_button,
                    ai_input_field,
                    ai_mic_button,
                    ai_send_button,
                ], spacing=4, vertical_alignment=ft.CrossAxisAlignment.CENTER),
            ], spacing=4, expand=True),
            expand=True,
            border=ft.Border.all(1, BLUE),
            border_radius=8,
            bgcolor=DARK,
            padding=ft.Padding(6, 6, 6, 6),
        ),
    ], expand=True, spacing=6)


    # ═════════════════════════════════════════════════════════════════════
    #  ██  Onglets + Barre de titre
    # ═════════════════════════════════════════════════════════════════════

    tabs = ft.Tabs(
        length=4,
        selected_index=0,
        expand=True,
        on_change=_on_tab_change,
        content=ft.Column(
            expand=True,
            spacing=0,
            controls=[
                ft.WindowDragArea(
                    ft.Row([
                        ft.Container(
                            content=ft.Row([
                                ft.Icon(ft.Icons.SPLITSCREEN, color=ORANGE, size=18),
                                ft.Text(
                                    f"SIDE PANEL  {__version__}",
                                    size=CONSTANTS.TEXT_LG, color=WHITE,
                                    weight=ft.FontWeight.W_500,
                                ),
                            ], spacing=6),
                            padding=ft.Padding(10, 0, 0, 0),
                        ),
                        ft.Container(expand=True),
                        ft.TabBar(
                            tabs=[
                                ft.Tab(label="Fichiers", icon=ft.Icons.PHOTO_LIBRARY_OUTLINED),
                                ft.Tab(label="Liste",    icon=ft.Icons.LIST_ALT_OUTLINED),
                                ft.Tab(label="Notes",    icon=ft.Icons.EDIT_NOTE_OUTLINED),
                                ft.Tab(label="IA",       icon=ft.Icons.SMART_TOY_OUTLINED),
                            ],
                        ),
                        ft.Container(expand=True),
                        ft.Row([
                            ft.IconButton(
                                icon=ft.Icons.REMOVE, icon_size=16,
                                on_click=_minimize, tooltip="Réduire",
                            ),
                            ft.IconButton(
                                icon=ft.Icons.FULLSCREEN, icon_size=16,
                                on_click=_toggle_maximize, tooltip="Maximiser / Restaurer",
                            ),
                            ft.IconButton(
                                icon=ft.Icons.CLOSE, icon_size=16,
                                on_click=_close, tooltip="Fermer",
                            ),
                        ], spacing=0),
                    ], vertical_alignment=ft.CrossAxisAlignment.CENTER),
                ),
                ft.Divider(height=1, color=GREY),
                ft.TabBarView(
                    expand=True,
                    controls=[
                        ft.Container(
                            content=tab1,
                            padding=ft.Padding(10, 8, 10, 8),
                            expand=True,
                        ),
                        ft.Container(
                            content=tab2,
                            padding=ft.Padding(10, 8, 10, 8),
                            expand=True,
                        ),
                        ft.Container(
                            content=tab3,
                            padding=ft.Padding(10, 8, 10, 8),
                            expand=True,
                        ),
                        ft.Container(
                            content=tab4,
                            padding=ft.Padding(10, 8, 10, 8),
                            expand=True,
                        ),
                    ],
                ),
            ],
        ),
    )

    page.add(tabs)
    # ── Initialisation ───────────────────────────────────────────────────
    _rebuild_recent_src_menu()
    _rebuild_recent_json_menu()
    _notepad_load()
    _ai_load_history()
    if os.path.isfile(json_path["value"]):
        _load_and_render()
    else:
        list_count.value = "0 entrée(s)"

    # Navigation initiale : dossier transmis par Dashboard via variable d'environnement
    initial_folder = os.environ.get("SELECTEUR_INITIAL_FOLDER", "").strip()
    if initial_folder and os.path.isdir(initial_folder):
        _navigate(initial_folder)

    # Fichier JSON transmis par Dashboard (clic sur un .json)
    initial_json_path = os.environ.get("SELECTEUR_JSON_PATH", "").strip()
    if initial_json_path and os.path.isfile(initial_json_path):
        _open_json_in_list(initial_json_path)


#############################################################
#                         DÉMARRAGE                         #
#############################################################
if sys.platform == "win32":
    original_exception_handler = None

    def _silence_proactor_pipe_errors(loop, context):
        exception = context.get("exception")
        if isinstance(exception, (ConnectionResetError, BrokenPipeError)):
            return
        if original_exception_handler:
            original_exception_handler(loop, context)
        else:
            loop.default_exception_handler(context)

    event_loop = asyncio.new_event_loop()
    original_exception_handler = event_loop.get_exception_handler()
    event_loop.set_exception_handler(_silence_proactor_pipe_errors)
    asyncio.set_event_loop(event_loop)

ft.run(main)
