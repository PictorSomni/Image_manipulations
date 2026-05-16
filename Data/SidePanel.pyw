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

__version__ = "2.5.3"


#############################################################
#                          IMPORTS                          #
#############################################################
import flet as ft
import os
import shutil
import threading
import json
import re
import platform
import subprocess
import sys
import asyncio
import time
import base64
import urllib.request
import urllib.error
import html.parser
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import CONSTANTS


#############################################################
#                         CONSTANTS                         #
#############################################################
_IMAGE_EXTS   = CONSTANTS.IMAGE_EXTS
_NOTEPAD_EXTS = CONSTANTS.NOTEPAD_EXTS

_OS_JUNK = {
    ".ds_store", "thumbs.db", "thumbs.db:encryptable",
    "ehthumbs.db", "desktop.ini", ".directory",
}


def _is_os_junk(entry):
    filename_lower = entry.name.lower()
    return filename_lower in _OS_JUNK or filename_lower.startswith("._")


# ── Extraction de contenu web pour l'IA ─────────────────────────────────────

class _HTMLTextExtractor(html.parser.HTMLParser):
    """Extrait le texte brut d'un document HTML en ignorant les balises."""
    _SKIP_TAGS = {"script", "style", "noscript", "head"}

    def __init__(self):
        super().__init__()
        self._skip_depth = 0
        self._parts = []

    def handle_starttag(self, tag, attrs):
        if tag in self._SKIP_TAGS:
            self._skip_depth += 1

    def handle_endtag(self, tag):
        if tag in self._SKIP_TAGS and self._skip_depth > 0:
            self._skip_depth -= 1

    def handle_data(self, data):
        if self._skip_depth == 0:
            stripped = data.strip()
            if stripped:
                self._parts.append(stripped)

    def get_text(self):
        return "\n".join(self._parts)


def _fetch_url_content(url, max_chars=12_000):
    """Récupère le contenu textuel d'une URL HTTP(S), tronqué à max_chars."""
    try:
        req = urllib.request.Request(
            url,
            headers={"User-Agent": "Mozilla/5.0 (compatible; ImageManipBot/1.0)"},
        )
        with urllib.request.urlopen(req, timeout=15) as response:
            content_type = response.headers.get("Content-Type", "")
            charset = "utf-8"
            if "charset=" in content_type:
                charset = content_type.split("charset=")[-1].split(";")[0].strip()
            raw_bytes = response.read()
        raw_text = raw_bytes.decode(charset, errors="replace")
        if "</" in raw_text or "<br" in raw_text.lower():
            extractor = _HTMLTextExtractor()
            extractor.feed(raw_text)
            plain_text = extractor.get_text()
        else:
            plain_text = raw_text
        plain_text = re.sub(r"\n{3,}", "\n\n", plain_text).strip()
        if len(plain_text) > max_chars:
            plain_text = plain_text[:max_chars] + f"\n\n[… contenu tronqué à {max_chars} caractères]"
        return plain_text
    except Exception as fetch_error:
        return f"[Impossible de récupérer l'URL : {fetch_error}]"


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

    # ─── Propriétés fenêtre ──────────────────────────────────────────────
    page.title       = "Side Panel"
    page.theme_mode  = ft.ThemeMode.DARK
    page.bgcolor     = BACKGROUND
    page.window.title_bar_hidden         = True
    page.window.title_bar_buttons_hidden = True
    page.window.width  = 1024
    page.window.height = 960

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
    PAGE_SIZE        = 100
    preview_page     = {"value": 0}
    recent_src_list  = {"data": _load_recent_shared()}
    file_filter_active = {"value": False}   # afficher uniquement la sélection
    print_counts     = {"data": {}}   # filepath → int (nb d'impressions, défaut 1)
    print_formats    = {"data": {}}   # filepath → clé format (CONSTANTS.FORMATS)
    count_text_refs  = {"data": {}}   # filepath → ft.Text widget du compteur

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
    note_target_file     = {"path": os.path.normpath(os.path.join(app_dir, "..", ".notes.txt"))}
    notepad_is_preview   = {"value": False}

    # ───────────────────────────────────────────────────────────────────
    #  ██████████  État  ──  Onglet 4 (IA)
    # ───────────────────────────────────────────────────────────────────
    ai_history_file_path  = os.path.normpath(os.path.join(app_dir, "..", ".ai_conversation.json"))
    ai_conversation_sp    = []
    ai_streaming_sp       = {"value": False}
    ollama_process_sp     = {"proc": None}
    ai_pending_images_sp  = []
    ai_pending_files_sp   = []

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

    ai_chat_view_sp = ft.ListView(expand=True, spacing=4, auto_scroll=True)
    ai_input_field_sp = ft.TextField(
        hint_text="Posez votre question… (Entrée pour envoyer)",
        border_color=BLUE,
        text_style=ft.TextStyle(font_family="monospace", size=CONSTANTS.TERMINAL_FONT_SIZE),
        dense=True,
        expand=True,
        color=WHITE,
        bgcolor=DARK,
        shift_enter=True,
    )
    ai_model_label_sp  = ft.Text(CONSTANTS.AI_MODEL_TEXT, color=LIGHT_GREY, size=11, italic=True)
    ai_status_text_sp  = ft.Text("", color=LIGHT_GREY, size=11, italic=True)
    ai_stop_btn_sp     = ft.IconButton(
        icon=ft.Icons.STOP_CIRCLE,
        icon_color=LIGHT_GREY,
        icon_size=16,
        tooltip="Libérer le modèle (ollama stop)",
        visible=False,
    )
    ai_attach_row_sp   = ft.Row([], spacing=4, visible=False, wrap=True)
    ai_attach_btn_sp   = ft.IconButton(
        icon=ft.Icons.ATTACH_FILE,
        icon_color=LIGHT_GREY,
        icon_size=18,
        tooltip="Joindre une image, un document ou un fichier audio",
    )
    ai_send_btn_sp     = ft.IconButton(
        icon=ft.Icons.SEND,
        icon_color=BLUE,
        icon_size=18,
        tooltip="Envoyer",
    )
    ai_clear_btn_sp    = ft.IconButton(
        icon=ft.Icons.DELETE_SWEEP,
        icon_color=LIGHT_GREY,
        icon_size=16,
        tooltip="Effacer la conversation IA",
    )


    # ═════════════════════════════════════════════════════════════════════
    #  ██  Fonctions — Onglet 1
    # ═════════════════════════════════════════════════════════════════════

    def _selection_label():
        count = len(selected_files)
        if count == 0:
            return ""
        return f"{count} fichier{'s' if count > 1 else ''} sélectionné{'s' if count > 1 else ''}"

    def _update_toggle_btn():
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
        _update_toggle_btn()
        page.update()

    def _render_preview():
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

                    if is_image and not is_directory:
                        visual = ft.Container(
                            content=ft.Image(
                                src=file_path, fit=ft.BoxFit.COVER,
                                error_content=ft.Icon(icon_name, color=icon_color, size=21),
                            ),
                            width=64, height=64,
                            border_radius=4,
                            clip_behavior=ft.ClipBehavior.ANTI_ALIAS,
                        )
                    else:
                        visual = ft.Icon(icon_name, color=icon_color, size=21)

                    if is_image and not is_directory:
                        print_count   = print_counts["data"].get(file_path, 1)
                        format_value = print_formats["data"].get(file_path, "")
                        format_dropdown = ft.Dropdown(
                            value=format_value or None,
                            hint_text="Format",
                            options=[ft.dropdown.Option(key=key, text=key)
                                     for key in CONSTANTS.FORMATS.keys()],
                            on_select=lambda event, p=file_path: _set_format(p, event.control.value or ""),
                            text_size=11, height=36, width=110,
                            content_padding=ft.Padding(8, 0, 0, 0),
                            bgcolor=DARK, border_color=GREY,
                        )
                        count_label = ft.Text(str(print_count), size=12, color=WHITE, width=18,
                                      text_align=ft.TextAlign.CENTER)
                        count_text_refs["data"][file_path] = count_label
                        extra_controls = [
                            ft.Row([
                                ft.IconButton(
                                    icon=ft.Icons.REMOVE, icon_size=14,
                                    icon_color=ORANGE,
                                    style=ft.ButtonStyle(padding=ft.Padding.all(2)),
                                    on_click=lambda event, p=file_path: _dec_count(p),
                                    tooltip="Moins d'impressions",
                                ),
                                count_label,
                                ft.IconButton(
                                    icon=ft.Icons.ADD, icon_size=14,
                                    icon_color=GREEN,
                                    style=ft.ButtonStyle(padding=ft.Padding.all(2)),
                                    on_click=lambda event, p=file_path: _inc_count(p),
                                    tooltip="Plus d'impressions",
                                ),
                            ], spacing=0, tight=True),
                            format_dropdown,
                        ]
                    else:
                        extra_controls = []

                    controls.append(
                        ft.Container(
                            content=ft.Row(
                                [
                                    checkbox,
                                    visual,
                                    ft.Text(filename, size=13 if (is_image and not is_directory) else 16,
                                            color=WHITE, expand=True),
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

            _update_toggle_btn()
            _update_file_filter_btn()
            page.update()
        except Exception as render_exception:
            status_text.value = f"[ERREUR] Rendu: {render_exception}"
            page.update()

    def _navigate(path):
        if not path or not os.path.isdir(path):
            return
        current_src["path"]          = path
        src_path_field.value         = path
        selected_files.clear()
        selection_count_text.value   = ""
        preview_page["value"]        = 0
        _add_recent_src(path)
        _rebuild_recent_src_menu()
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

    def _update_file_filter_btn():
        selected_count = len(selected_files)
        if file_filter_active["value"]:
            file_filter_btn.icon_color = BLUE
            file_filter_btn.tooltip    = f"Filtre actif ({selected_count} sélectionné(s)) — cliquer pour afficher tout"
        else:
            file_filter_btn.icon_color = VIOLET if selected_count else LIGHT_GREY
            file_filter_btn.tooltip    = f"Afficher uniquement la sélection ({selected_count} sélectionné(s))"
        try:
            file_filter_btn.update()
        except Exception:
            pass

    def _dec_count(path):
        current_count = print_counts["data"].get(path, 1)
        if current_count > 1:
            print_counts["data"][path] = current_count - 1
            count_widget = count_text_refs["data"].get(path)
            if count_widget:
                count_widget.value = str(current_count - 1)
                count_widget.update()

    def _inc_count(path):
        current_count = print_counts["data"].get(path, 1)
        print_counts["data"][path] = current_count + 1
        count_widget = count_text_refs["data"].get(path)
        if count_widget:
            count_widget.value = str(current_count + 1)
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
        search_query["value"]  = search_text
        preview_page["value"]  = 0
        _render_preview()

    def _clear_search(event):
        search_query["value"] = ""
        search_field.value    = ""
        _render_preview()
        page.update()
        page.update()

    def _go_to_page(delta):
        total_entries       = len(all_entries["list"])
        total_pages = max(1, (total_entries + PAGE_SIZE - 1) // PAGE_SIZE)
        new_page_index      = max(0, min(preview_page["value"] + delta, total_pages - 1))
        if new_page_index == preview_page["value"]:
            return
        preview_page["value"] = new_page_index
        _render_preview()

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
                print_count = counts_snapshot.get(source_file, 1)
                format_key   = formats_snapshot.get(source_file, "")
                prefix_parts = [f"{print_count}X"]
                if format_key:
                    prefix_parts.append(format_key)
                destination_stem = "_".join(prefix_parts) + "_" + original_stem
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
        """Charge le fichier .notes.txt dans le champ du bloc-notes."""
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

    def _open_file_in_notepad(file_path):
        """Ouvre un fichier texte dans l'onglet Notes."""
        note_target_file["path"] = file_path
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
    _AI_AUDIO_EXTS     = CONSTANTS.AI_AUDIO_EXTS

    def _ai_add_bubble_sp(role, text):
        """Ajoute un message dans le panneau IA et retourne le contrôle (pour le streaming)."""
        is_user = role == "user"
        if is_user:
            bubble_text = ft.Text(
                text,
                size=CONSTANTS.TERMINAL_FONT_SIZE,
                color=BLUE,
                font_family="monospace",
                selectable=True,
                no_wrap=False,
            )
        else:
            bubble_text = ft.Markdown(
                text,
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
        row = ft.Row(
            [bubble],
            alignment=ft.MainAxisAlignment.END if is_user else ft.MainAxisAlignment.START,
        )
        ai_chat_view_sp.controls.append(row)
        async def _update_and_scroll():
            try:
                page.update()
                await asyncio.sleep(0)
                await ai_chat_view_sp.scroll_to(offset=-1)
            except Exception:
                pass
        page.run_task(_update_and_scroll)
        return bubble_text

    def _ai_save_history_sp():
        """Sauvegarde la conversation dans .ai_conversation.json."""
        try:
            serializable = [
                {"role": message["role"], "content": message["content"]}
                for message in ai_conversation_sp
                if message.get("role") in ("user", "assistant")
            ]
            with open(ai_history_file_path, "w", encoding="utf-8") as file_handle:
                json.dump(serializable, file_handle, ensure_ascii=False, indent=2)
        except Exception:
            pass

    def _ai_load_history_sp():
        """Charge .ai_conversation.json et reconstruit la vue."""
        if not os.path.isfile(ai_history_file_path):
            return
        try:
            with open(ai_history_file_path, "r", encoding="utf-8") as file_handle:
                saved_messages = json.load(file_handle)
            for message in saved_messages:
                role = message.get("role")
                content = message.get("content", "")
                if role not in ("user", "assistant"):
                    continue
                ai_conversation_sp.append({"role": role, "content": content})
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
                ai_chat_view_sp.controls.append(
                    ft.Row(
                        [bubble],
                        alignment=ft.MainAxisAlignment.END if is_user else ft.MainAxisAlignment.START,
                    )
                )
        except Exception:
            pass

    def _clear_ai_conversation_sp(event=None):
        """Efface l'historique de la conversation IA."""
        ai_conversation_sp.clear()
        ai_chat_view_sp.controls.clear()
        ai_status_text_sp.value = ""
        try:
            if os.path.isfile(ai_history_file_path):
                os.remove(ai_history_file_path)
        except Exception:
            pass
        try:
            page.update()
        except Exception:
            pass

    def _ai_build_conversation_text_sp():
        """Retourne la conversation IA formatée en texte brut."""
        lines = []
        for message in ai_conversation_sp:
            role = message.get("role", "")
            content = message.get("content", "")
            if role == "user":
                prefix = "Vous"
            elif role == "assistant":
                prefix = "IA"
            else:
                continue
            lines.append(f"[{prefix}]\n{content}\n")
        return "\n".join(lines).strip()

    def _ai_conversation_to_notepad_sp(event=None):
        """Formate la conversation IA et la transfère dans le bloc-notes."""
        if not ai_conversation_sp:
            return
        block = _ai_build_conversation_text_sp()
        existing = notepad_field.value or ""
        separator = "\n\n" + "─" * 40 + "\n\n" if existing.strip() else ""
        notepad_field.value = existing + separator + block
        _notepad_save()
        try:
            notepad_field.update()
        except Exception:
            pass
        # Basculer vers l'onglet Notes
        tabs.selected_index = 2
        try:
            tabs.update()
        except Exception:
            pass

    def _ai_stop_model_sp(event=None):
        """Libère le modèle chargé en RAM via `ollama stop`."""
        def _run_stop():
            try:
                subprocess.run(["ollama", "stop", CONSTANTS.AI_MODEL_VISION], timeout=10)
                subprocess.run(["ollama", "stop", CONSTANTS.AI_MODEL_TEXT],   timeout=10)
            except Exception:
                pass
            ai_stop_btn_sp.visible = False
            ai_status_text_sp.value = ""
            try:
                page.update()
            except Exception:
                pass
        threading.Thread(target=_run_stop, daemon=True).start()

    def _ai_refresh_attach_row_sp():
        """Reconstruit la barre de pièces jointes visuellement."""
        ai_attach_row_sp.controls.clear()
        for image_entry in ai_pending_images_sp:
            name = os.path.basename(image_entry["path"])
            entry_ref = image_entry
            ai_attach_row_sp.controls.append(
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
                            on_click=lambda event, ref=entry_ref: _ai_remove_image_sp(ref),
                        ),
                    ], spacing=2, tight=True),
                    bgcolor=GREY,
                    border_radius=4,
                    padding=ft.Padding(4, 2, 4, 2),
                )
            )
        for file_entry in ai_pending_files_sp:
            name = os.path.basename(file_entry["path"])
            file_type = file_entry["type"]
            icon_name = ft.Icons.AUDIO_FILE if file_type == "audio" else ft.Icons.DESCRIPTION
            entry_ref = file_entry
            ai_attach_row_sp.controls.append(
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
                            on_click=lambda event, ref=entry_ref: _ai_remove_file_sp(ref),
                        ),
                    ], spacing=2, tight=True),
                    bgcolor=GREY,
                    border_radius=4,
                    padding=ft.Padding(4, 2, 4, 2),
                )
            )
        ai_attach_row_sp.visible = bool(ai_pending_images_sp) or bool(ai_pending_files_sp)
        try:
            page.update()
        except Exception:
            pass

    def _ai_attach_image_sp(image_path):
        """Encode une image en base64 (redimensionnée à 1024px max) et l'ajoute aux pièces jointes."""
        if any(entry["path"] == image_path for entry in ai_pending_images_sp):
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
                _ai_add_bubble_sp("assistant", f"[ERREUR] Impossible de lire l'image : {exc}")
                return
        ai_pending_images_sp.append({"path": image_path, "b64": b64_data})
        _ai_refresh_attach_row_sp()

    def _ai_remove_image_sp(image_entry):
        if image_entry in ai_pending_images_sp:
            ai_pending_images_sp.remove(image_entry)
        _ai_refresh_attach_row_sp()

    def _ai_attach_document_file_sp(file_path):
        if any(entry["path"] == file_path for entry in ai_pending_files_sp):
            return
        ext = os.path.splitext(file_path)[1].lower()
        file_type = "audio" if ext in _AI_AUDIO_EXTS else "document"
        ai_pending_files_sp.append({"path": file_path, "type": file_type})
        _ai_refresh_attach_row_sp()

    def _ai_remove_file_sp(file_entry):
        if file_entry in ai_pending_files_sp:
            ai_pending_files_sp.remove(file_entry)
        _ai_refresh_attach_row_sp()

    def _ai_extract_file_content_sp(file_entry):
        """Extrait le contenu textuel d'un document ou transcrit un fichier audio."""
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
                    _ffmpeg_hint = "winget install ffmpeg"
                else:
                    _ffmpeg_hint = "sudo apt install ffmpeg"
                raise RuntimeError(
                    f"ffmpeg est requis pour transcrire les fichiers audio.\n"
                    f"Installez-le avec : {_ffmpeg_hint}"
                )
            whisper_model = _whisper.load_model("base")
            result = whisper_model.transcribe(file_path)
            transcribed_text = (result.get("text") or "").strip()
            if not transcribed_text:
                raise RuntimeError("La transcription est vide.")
            return name, transcribed_text
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

    async def _ai_pick_any_sp():
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
                        _ai_attach_image_sp(picked_file.path)
                    else:
                        _ai_attach_document_file_sp(picked_file.path)

    def _ensure_ollama_ready_sp(model_name=None):
        """Vérifie qu'Ollama est lancé et que le modèle est disponible."""
        if model_name is None:
            model_name = CONSTANTS.AI_MODEL_TEXT

        def _is_ollama_up():
            try:
                with urllib.request.urlopen(
                    f"{CONSTANTS.AI_OLLAMA_URL}/api/tags", timeout=3
                ) as resp:
                    return resp.status == 200
            except Exception:
                return False

        if not _is_ollama_up():
            _ai_add_bubble_sp("assistant", "⚙️ Démarrage d'Ollama en arrière-plan…")
            try:
                ollama_process_sp["proc"] = subprocess.Popen(
                    ["ollama", "serve"],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                )
            except FileNotFoundError:
                _ai_add_bubble_sp(
                    "assistant",
                    "[ERREUR] Ollama n'est pas installé sur cette machine.\n"
                    "Téléchargez-le sur https://ollama.com",
                )
                return False
            for _ in range(40):
                time.sleep(0.5)
                if _is_ollama_up():
                    break
            else:
                _ai_add_bubble_sp(
                    "assistant",
                    "[ERREUR] Ollama n'a pas démarré dans les délais impartis.",
                )
                return False

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
            pull_status_ctrl = _ai_add_bubble_sp(
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
                            pull_status_ctrl.value = f"⬇️ {model_name} — {status} {pct}%"
                        elif status:
                            pull_status_ctrl.value = f"⬇️ {model_name} — {status}"
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
                _ai_add_bubble_sp("assistant", f"[ERREUR] Téléchargement du modèle : {exc}")
                return False

        return True

    def _send_ai_message_sp(message_text):
        """Envoie un message à Ollama et streame la réponse dans le panneau IA."""
        if ai_streaming_sp["value"]:
            return
        if not message_text.strip() and not ai_pending_images_sp and not ai_pending_files_sp:
            return
        ai_streaming_sp["value"] = True
        ai_stop_btn_sp.visible = True
        ai_status_text_sp.value = "⏳ En cours…"
        try:
            page.update()
        except Exception:
            pass

        images_b64 = [entry["b64"] for entry in ai_pending_images_sp]
        ai_pending_images_sp.clear()
        _ai_refresh_attach_row_sp()

        files_to_inject = list(ai_pending_files_sp)
        ai_pending_files_sp.clear()
        _ai_refresh_attach_row_sp()

        active_model = CONSTANTS.AI_MODEL_VISION if images_b64 else CONSTANTS.AI_MODEL_TEXT
        ai_model_label_sp.value = f"{active_model}  {'🖼' if images_b64 else '💬'}"
        try:
            ai_model_label_sp.update()
        except Exception:
            pass

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
        ai_conversation_sp.append(user_message)

        display_text = message_text
        if images_b64:
            display_text = (
                f"🖼️ ({len(images_b64)} image(s))  {message_text}"
                if message_text else f"🖼️ {len(images_b64)} image(s) jointe(s)"
            )
        if files_to_inject:
            files_label = "  ".join(
                ("🎵" if entry["type"] == "audio" else "📄") + " " + os.path.basename(entry["path"])
                for entry in files_to_inject
            )
            display_text = (display_text + "  " if display_text else "") + files_label
        _ai_add_bubble_sp("user", display_text)

        def _run():
            full_response = ""
            response_text_ctrl = None
            try:
                if not _ensure_ollama_ready_sp(active_model):
                    return

                loading_ctrl = _ai_add_bubble_sp("assistant", "⏳ Réflexion en cours…")

                if files_to_inject:
                    injected_blocks = []
                    for file_entry in files_to_inject:
                        file_name = os.path.basename(file_entry["path"])
                        try:
                            if file_entry["type"] == "audio":
                                ai_status_text_sp.value = f"⏳ Transcription : {file_name}…"
                                try:
                                    page.update()
                                except Exception:
                                    pass
                            label, content = _ai_extract_file_content_sp(file_entry)
                            type_label = "Transcription audio" if file_entry["type"] == "audio" else "Document"
                            injected_blocks.append(
                                f"--- {type_label} : {label} ---\n{content[:50000]}\n--- Fin ---"
                            )
                        except Exception as extraction_exc:
                            _ai_add_bubble_sp("assistant", f"[ERREUR] {file_name} : {extraction_exc}")
                    if injected_blocks:
                        ai_conversation_sp[-1]["content"] += "\n\n" + "\n\n".join(injected_blocks)
                    ai_status_text_sp.value = "⏳ En cours…"
                    try:
                        page.update()
                    except Exception:
                        pass

                payload = json.dumps({
                    "model": active_model,
                    "messages": [
                        {"role": "system", "content": CONSTANTS.AI_SYSTEM_PROMPT},
                        *ai_conversation_sp,
                    ],
                    "stream": True,
                    "keep_alive": -1,
                    "options": {"temperature": CONSTANTS.AI_TEMPERATURE},
                }).encode("utf-8")
                request = urllib.request.Request(
                    f"{CONSTANTS.AI_OLLAMA_URL}/api/chat",
                    data=payload,
                    headers={"Content-Type": "application/json"},
                    method="POST",
                )
                with urllib.request.urlopen(request, timeout=300) as response:
                    for raw_line in response:
                        chunk = json.loads(raw_line.decode("utf-8"))
                        token = chunk.get("message", {}).get("content", "")
                        if token:
                            full_response += token
                            if response_text_ctrl is None:
                                if loading_ctrl is not None:
                                    try:
                                        ai_chat_view_sp.controls = [
                                            row for row in ai_chat_view_sp.controls
                                            if not (
                                                hasattr(row, "controls") and row.controls
                                                and hasattr(row.controls[0], "content")
                                                and row.controls[0].content is loading_ctrl
                                            )
                                        ]
                                        loading_ctrl = None
                                    except Exception:
                                        pass
                                response_text_ctrl = _ai_add_bubble_sp("assistant", token)
                            else:
                                response_text_ctrl.value = full_response
                                async def _stream_update():
                                    try:
                                        page.update()
                                        await asyncio.sleep(0)
                                        await ai_chat_view_sp.scroll_to(offset=-1)
                                    except Exception:
                                        pass
                                page.run_task(_stream_update)
                        if chunk.get("done"):
                            break
                if full_response:
                    ai_conversation_sp.append({"role": "assistant", "content": full_response})
                    _ai_save_history_sp()
                else:
                    _ai_add_bubble_sp("assistant", "[Aucune réponse reçue]")
            except Exception as exc:
                _ai_add_bubble_sp("assistant", f"[ERREUR] {exc}")
            finally:
                ai_streaming_sp["value"] = False
                ai_stop_btn_sp.visible = False
                ai_status_text_sp.value = ""
                try:
                    page.update()
                except Exception:
                    pass
                async def _refocus():
                    try:
                        await ai_input_field_sp.focus()
                    except Exception:
                        pass
                page.run_task(_refocus)

        threading.Thread(target=_run, daemon=True).start()

    def _on_ai_submit_sp():
        """Récupère le texte saisi, vide le champ et envoie le message à l'IA."""
        message_text = ai_input_field_sp.value.strip()
        if not message_text and not ai_pending_images_sp and not ai_pending_files_sp:
            return
        ai_input_field_sp.value = ""
        ai_input_field_sp.update()
        async def _refocus():
            try:
                await ai_input_field_sp.focus()
            except Exception:
                pass
        page.run_task(_refocus)
        _send_ai_message_sp(message_text)

    # Connexions boutons IA
    ai_input_field_sp.on_submit = lambda event: _on_ai_submit_sp()
    ai_send_btn_sp.on_click     = lambda event: _on_ai_submit_sp()
    ai_attach_btn_sp.on_click   = lambda event: page.run_task(_ai_pick_any_sp)
    ai_stop_btn_sp.on_click     = _ai_stop_model_sp
    ai_clear_btn_sp.on_click    = _clear_ai_conversation_sp

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
        _persist()
        _notepad_save()
        _ai_save_history_sp()
        await page.window.close()

    def _minimize(event):
        page.window.minimized = True

    def _toggle_maximize(event):
        page.window.maximized = not page.window.maximized
        page.update()


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
                icon=ft.Icons.FOLDER_OPEN, icon_color=RED,
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
                icon=ft.Icons.SAVE_OUTLINED,
                icon_color=BLUE,
                icon_size=18,
                tooltip="Sauvegarder",
                on_click=_notepad_save,
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

    tab4 = ft.Column([
        ft.Row([
            ft.Icon(ft.Icons.SMART_TOY, color=BLUE, size=16),
            ft.Text("IA", color=BLUE, size=13, weight=ft.FontWeight.BOLD),
            ft.Container(width=4),
            ai_model_label_sp,
            ft.Container(width=4),
            ai_status_text_sp,
            ai_stop_btn_sp,
            ft.Container(expand=True),
            ai_clear_btn_sp,
            ft.IconButton(
                icon=ft.Icons.SEND_TO_MOBILE,
                icon_color=VIOLET,
                icon_size=16,
                tooltip="Transférer la conversation vers le bloc-notes",
                on_click=_ai_conversation_to_notepad_sp,
            ),
        ], spacing=2, vertical_alignment=ft.CrossAxisAlignment.CENTER),
        ft.Container(
            content=ft.Column([
                ai_chat_view_sp,
                ai_attach_row_sp,
                ft.Row([
                    ai_attach_btn_sp,
                    ai_input_field_sp,
                    ai_send_btn_sp,
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
        content=ft.Column(
            expand=True,
            spacing=0,
            controls=[
                ft.TabBar(
                    tabs=[
                        ft.Tab(label="Fichiers", icon=ft.Icons.PHOTO_LIBRARY_OUTLINED),
                        ft.Tab(label="Liste",    icon=ft.Icons.LIST_ALT_OUTLINED),
                        ft.Tab(label="Notes",    icon=ft.Icons.EDIT_NOTE_OUTLINED),
                        ft.Tab(label="IA",       icon=ft.Icons.SMART_TOY_OUTLINED),
                    ],
                ),
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

    title_bar = ft.WindowDragArea(
        ft.Container(
            content=ft.Row([
                ft.Icon(ft.Icons.SPLITSCREEN, color=ORANGE, size=18),
                ft.Text(
                    f"SIDE PANEL  {__version__}",
                    size=15, color=WHITE,
                    weight=ft.FontWeight.W_500,
                ),
                ft.Container(expand=True),
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
            ], spacing=6, vertical_alignment=ft.CrossAxisAlignment.CENTER),
            bgcolor=DARK,
            padding=ft.Padding(10, 6, 6, 6),
        )
    )

    page.add(
        ft.Column([
            title_bar,
            ft.Divider(height=1, color=GREY),
            tabs,
        ], expand=True, spacing=0)
    )

    # ── Initialisation ───────────────────────────────────────────────────
    _rebuild_recent_src_menu()
    _rebuild_recent_json_menu()
    _notepad_load()
    _ai_load_history_sp()
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
