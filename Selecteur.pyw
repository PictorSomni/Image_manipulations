# -*- coding: utf-8 -*-
"""
Sélecteur — App compacte (demi-écran) avec deux onglets :

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

__version__ = "2.1.5"


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


#############################################################
#                         CONSTANTS                         #
#############################################################
_IMAGE_EXTS = {
    ".jpg", ".jpeg", ".png", ".gif", ".bmp",
    ".webp", ".ico", ".tiff", ".tif",
}

_OS_JUNK = {
    ".ds_store", "thumbs.db", "thumbs.db:encryptable",
    "ehthumbs.db", "desktop.ini", ".directory",
}


def _is_os_junk(entry):
    n = entry.name.lower()
    return n in _OS_JUNK or n.startswith("._")


#############################################################
#                           MAIN                            #
#############################################################
def main(page: ft.Page):

    # ─── Couleurs ────────────────────────────────────────────────────────
    DARK        = "#222429"
    BACKGROUND  = "#373d4a"
    GREY        = "#2C3038"
    LIGHT_GREY  = "#9399A6"
    BLUE        = "#45B8F5"
    VIOLET      = "#B587FE"
    GREEN       = "#49B76C"
    YELLOW      = "#FBCD5F"
    HOVER_YELLOW= "#F9BA4E"
    ORANGE      = "#FFA071"
    RED         = "#F17171"
    WHITE       = "#c7ccd8"

    # ─── Propriétés fenêtre ──────────────────────────────────────────────
    page.title       = "Sélecteur"
    page.theme_mode  = ft.ThemeMode.DARK
    page.bgcolor     = BACKGROUND
    page.window.title_bar_hidden         = True
    page.window.title_bar_buttons_hidden = True
    page.window.width  = 960
    page.window.height = 960

    # ─── Chemins config ──────────────────────────────────────────────────
    app_dir             = os.path.dirname(os.path.abspath(__file__))
    config_file         = os.path.join(app_dir, ".selecteur_config.json")
    _shared_recent_file = os.path.join(app_dir, ".recent_folders.json")  # partagé avec Dashboard

    # ─── Config persistante ──────────────────────────────────────────────
    def _load_config() -> dict:
        try:
            with open(config_file, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return {}

    def _save_config(cfg: dict):
        try:
            with open(config_file, "w", encoding="utf-8") as f:
                json.dump(cfg, f, ensure_ascii=False, indent=2)
        except Exception:
            pass

    _cfg = _load_config()

    # ─── Dossiers récents partagés avec Dashboard ─────────────────────────
    def _load_recent_shared() -> list:
        try:
            with open(_shared_recent_file, "r", encoding="utf-8") as f:
                data = json.load(f)
            return [p for p in data if isinstance(p, str) and os.path.isdir(p)]
        except Exception:
            return []

    def _save_recent_shared(folders: list):
        try:
            with open(_shared_recent_file, "w", encoding="utf-8") as f:
                json.dump(folders[:10], f, ensure_ascii=False, indent=2)
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

    # ─────────────────────────────────────────────────────────────────────
    #  ██████████  État  ──  Onglet 2 (Liste JSON)
    # ─────────────────────────────────────────────────────────────────────
    json_path        = {"value": _cfg.get("json_path", os.path.join(app_dir, ".liste.json"))}
    json_entries     = {"list": []}
    list_sort_mode   = {"value": 2}         # 0=A→Z  1=Z→A  2=Récent
    list_search_q    = {"value": ""}
    recent_json_list    = {"data": [p for p in _cfg.get("recent_json", []) if isinstance(p, str) and os.path.isfile(p)]}
    list_selected_items = {"data": set()}   # entrées cochées (filtre)
    list_done_items     = {"data": set()}   # entrées marquées "faites"
    list_filter_active  = {"value": False}  # afficher uniquement la sélection

    # ═════════════════════════════════════════════════════════════════════
    #  ██  Helpers persistance
    # ═════════════════════════════════════════════════════════════════════
    def _persist():
        _save_config({
            "dst_path":    dst_path_field.value or "",
            "json_path":   json_path["value"] or "",
            "recent_json": recent_json_list["data"],
        })

    def _add_recent_src(p: str):
        lst = _load_recent_shared()
        p = os.path.normpath(p)
        if p in lst:
            lst.remove(p)
        lst.insert(0, p)
        lst = lst[:10]
        _save_recent_shared(lst)
        recent_src_list["data"] = lst

    def _add_recent_json(p: str):
        p = os.path.normpath(p)
        lst = [x for x in recent_json_list["data"] if x != p]
        lst.insert(0, p)
        recent_json_list["data"] = lst[:10]
        _persist()
        _rebuild_recent_json_menu()

    def _rebuild_recent_json_menu():
        lst = recent_json_list["data"]
        if not lst:
            recent_json_btn.items = [
                ft.PopupMenuItem(content=ft.Text("Aucun fichier récent"))
            ]
        else:
            recent_json_btn.items = [
                ft.PopupMenuItem(
                    content=ft.Row(
                        [ft.Icon(ft.Icons.DATA_OBJECT, size=16),
                         ft.Text(os.path.basename(p) or p)],
                        spacing=8, tight=True,
                    ),
                    on_click=lambda e, p=p: _open_json_in_list(p),
                )
                for p in lst
            ]
        try:
            recent_json_btn.update()
        except Exception:
            pass

    def _load_list_states():
        """Charge les états (sélection / faits) pour le fichier JSON courant."""
        cfg    = _load_config()
        states = cfg.get("list_states", {})
        path   = json_path["value"]
        entry  = states.get(path, {})
        list_selected_items["data"] = set(entry.get("selected", []))
        list_done_items["data"]     = set(entry.get("done", []))

    def _save_list_states():
        """Persiste les états (sélection / faits) pour le fichier JSON courant."""
        cfg    = _load_config()
        states = cfg.get("list_states", {})
        path   = json_path["value"]
        if path:
            states[path] = {
                "selected": list(list_selected_items["data"]),
                "done":     list(list_done_items["data"]),
            }
        cfg["list_states"] = states
        _save_config(cfg)


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
        value=_cfg.get("dst_path", ""),
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
    #  ██  Fonctions — Onglet 1
    # ═════════════════════════════════════════════════════════════════════

    def _selection_label():
        n = len(selected_files)
        if n == 0:
            return ""
        return f"{n} fichier{'s' if n > 1 else ''} sélectionné{'s' if n > 1 else ''}"

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



    def _on_checkbox_change(e, path):
        if e.control.value:
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
                q = search_query["value"].lower()
                entries = [en for en in entries if q in en[0].lower()]

            if file_filter_active["value"]:
                entries = [en for en in entries if en[1] in selected_files]

            total       = len(entries)
            total_pages = max(1, (total + PAGE_SIZE - 1) // PAGE_SIZE)
            cur_pg      = min(preview_page["value"], total_pages - 1)
            preview_page["value"] = cur_pg

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
                start = cur_pg * PAGE_SIZE
                end   = min(start + PAGE_SIZE, total)
                for name, fpath, is_dir, is_img, ext in entries[start:end]:
                    # Icône selon type
                    if is_dir:
                        icon, ic = ft.Icons.FOLDER, ft.Colors.AMBER_400
                    elif is_img:
                        icon, ic = ft.Icons.IMAGE, ft.Colors.GREEN_400
                    elif ext == ".pdf":
                        icon, ic = ft.Icons.PICTURE_AS_PDF, ft.Colors.RED_400
                    elif ext == ".zip":
                        icon, ic = ft.Icons.FOLDER_ZIP, ORANGE
                    elif ext in {".txt", ".md", ".log"}:
                        icon, ic = ft.Icons.DESCRIPTION, ft.Colors.BLUE_GREY_400
                    else:
                        icon, ic = ft.Icons.INSERT_DRIVE_FILE, ft.Colors.BLUE_GREY_400

                    checkbox = ft.Checkbox(
                        border_side=ft.BorderSide(color=BLUE),
                        value=fpath in selected_files,
                        on_change=lambda e, p=fpath: _on_checkbox_change(e, p),
                    )

                    if is_img and not is_dir:
                        visual = ft.Container(
                            content=ft.Image(
                                src=fpath, fit=ft.BoxFit.COVER,
                                error_content=ft.Icon(icon, color=ic, size=21),
                            ),
                            width=64, height=64,
                            border_radius=4,
                            clip_behavior=ft.ClipBehavior.ANTI_ALIAS,
                        )
                    else:
                        visual = ft.Icon(icon, color=ic, size=21)

                    controls.append(
                        ft.Container(
                            content=ft.Row(
                                [
                                    checkbox,
                                    visual,
                                    ft.Text(name, size=16, color=WHITE, expand=True),
                                ],
                                spacing=8,
                                vertical_alignment=ft.CrossAxisAlignment.CENTER,
                            ),
                            padding=ft.Padding(left=8, top=2, right=8, bottom=2),
                            ink=True,
                            ink_color=GREY,
                            on_click=lambda e, p=fpath, d=is_dir, ex=ext: _navigate(p) if d else _open_json_in_list(p) if ex == ".json" else None,
                        )
                    )

            preview_list.controls.clear()
            preview_list.controls.extend(controls)
            preview_loading.visible = False

            # Pagination
            if total > PAGE_SIZE:
                prev_page_btn.visible  = cur_pg > 0
                next_page_btn.visible  = cur_pg < total_pages - 1
                page_indicator.value   = (
                    f"{cur_pg * PAGE_SIZE + 1}-"
                    f"{min((cur_pg + 1) * PAGE_SIZE, total)}/{total}"
                )
            else:
                prev_page_btn.visible = False
                next_page_btn.visible = False
                page_indicator.value  = ""

            _update_toggle_btn()
            _update_file_filter_btn()
            page.update()
        except Exception as ex:
            status_text.value = f"[ERREUR] Rendu: {ex}"
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
        cur_token = refresh_token["value"]
        preview_list.controls.clear()
        file_count_text.value   = ""
        folder = current_src["path"]
        preview_loading.visible = bool(folder)
        page.update()

        def _bg():
            entries_data = []
            file_ct      = ""
            err          = ""
            if folder:
                try:
                    with os.scandir(folder) as it:
                        raw = [e for e in it if not _is_os_junk(e)]
                    n_files = sum(1 for e in raw if not e.is_dir())
                    file_ct = f"({n_files} fichier{'s' if n_files > 1 else ''})"
                    if sort_mode["value"] == 2:
                        srt = sorted(raw, key=lambda e: (not e.is_dir(), -e.stat().st_mtime))
                    elif sort_mode["value"] == 1:
                        srt = sorted(raw, key=lambda e: (not e.is_dir(), e.name.lower()), reverse=True)
                    else:
                        srt = sorted(raw, key=lambda e: (not e.is_dir(), e.name.lower()))
                    for entry in srt:
                        ext    = os.path.splitext(entry.name)[1].lower()
                        is_img = ext in _IMAGE_EXTS
                        entries_data.append(
                            (entry.name, entry.path, entry.is_dir(), is_img, ext)
                        )
                except PermissionError:
                    err = "⚠️ Accès refusé à ce dossier"
                except Exception as ex:
                    err = f"⚠️ Erreur: {ex}"

            page.pubsub.send_all_on_topic(
                "sel_preview_ready",
                (cur_token, entries_data, file_ct, err),
            )

        threading.Thread(target=_bg, daemon=True).start()

    def _on_preview_ready(topic, payload):
        token, entries_data, file_ct, err = payload
        if refresh_token["value"] != token:
            return
        all_entries["list"]  = entries_data
        all_entries["error"] = err
        file_count_text.value = file_ct
        _render_preview()

    page.pubsub.subscribe_topic("sel_preview_ready", _on_preview_ready)

    def _rebuild_recent_src_menu():
        lst = _load_recent_shared()
        recent_src_list["data"] = lst
        if not lst:
            recent_src_btn.items = [
                ft.PopupMenuItem(content=ft.Text("Aucun dossier récent"))
            ]
        else:
            recent_src_btn.items = [
                ft.PopupMenuItem(
                    content=ft.Row(
                        [ft.Icon(ft.Icons.FOLDER, size=16),
                         ft.Text(os.path.basename(p) or p)],
                        spacing=8, tight=True,
                    ),
                    on_click=lambda e, p=p: _navigate(p),
                )
                for p in lst
            ]
        try:
            recent_src_btn.update()
        except Exception:
            pass

    # ── Sélection ────────────────────────────────────────────────────────
    def _select_all(e=None):
        entries = all_entries["list"]
        if search_query["value"]:
            query_lower = search_query["value"].lower()
            entries = [en for en in entries if query_lower in en[0].lower()]
        for _, fpath, is_dir, _, _ in entries:
            if not is_dir:
                selected_files.add(fpath)
        selection_count_text.value = _selection_label()
        _render_preview()
        _update_toggle_btn()

    def _clear_selection(e=None):
        selected_files.clear()
        selection_count_text.value = ""
        if file_filter_active["value"]:
            file_filter_active["value"] = False
        _render_preview()
        _update_toggle_btn()

    def _toggle_all(e):
        if search_query["value"]:
            query_lower = search_query["value"].lower()
            filtered_paths = {
                fpath for (_name, fpath, is_dir, _is_img, _ext) in all_entries["list"]
                if not is_dir and query_lower in _name.lower()
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

    def _invert(e):
        entries = all_entries["list"]
        for _, fpath, is_dir, _, _ in entries:
            if is_dir:
                continue
            if fpath in selected_files:
                selected_files.discard(fpath)
            else:
                selected_files.add(fpath)
        selection_count_text.value = _selection_label()
        _render_preview()
        _update_toggle_btn()

    def _toggle_file_filter(e):
        file_filter_active["value"] = not file_filter_active["value"]
        _update_file_filter_btn()
        _render_preview()

    def _update_file_filter_btn():
        n = len(selected_files)
        if file_filter_active["value"]:
            file_filter_btn.icon_color = BLUE
            file_filter_btn.tooltip    = f"Filtre actif ({n} sélectionné(s)) — cliquer pour afficher tout"
        else:
            file_filter_btn.icon_color = VIOLET if n else LIGHT_GREY
            file_filter_btn.tooltip    = f"Afficher uniquement la sélection ({n} sélectionné(s))"
        try:
            file_filter_btn.update()
        except Exception:
            pass

    # ── Tri / Recherche ──────────────────────────────────────────────────
    def _on_sort_change(e):
        sort_mode["value"] = e.control.selected_index
        _refresh_preview()

    def _on_search_change(e):
        q = (search_field.value or "").strip()
        if not q:
            _clear_search(e)
            return
        search_query["value"]  = q
        preview_page["value"]  = 0
        _render_preview()

    def _clear_search(e):
        search_query["value"] = ""
        search_field.value    = ""
        _render_preview()
        page.update()
        page.update()

    def _go_to_page(delta):
        total       = len(all_entries["list"])
        total_pages = max(1, (total + PAGE_SIZE - 1) // PAGE_SIZE)
        new_pg      = max(0, min(preview_page["value"] + delta, total_pages - 1))
        if new_pg == preview_page["value"]:
            return
        preview_page["value"] = new_pg
        _render_preview()

    def _go_parent(e):
        if current_src["path"]:
            parent = os.path.dirname(current_src["path"])
            if parent and parent != current_src["path"]:
                _navigate(parent)

    def _open_in_explorer(e):
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

    async def _pick_src(e):
        folder = await ft.FilePicker().get_directory_path(
            dialog_title="Dossier source (images)"
        )
        if folder:
            _navigate(os.path.normpath(folder))

    async def _pick_dst(e):
        folder = await ft.FilePicker().get_directory_path(
            dialog_title="Dossier de destination"
        )
        if folder:
            dst_path_field.value = os.path.normpath(folder)
            dst_path_field.update()
            _persist()

    def _on_status(topic, msg):
        status_text.value = msg
        page.update()

    page.pubsub.subscribe_topic("sel_status", _on_status)

    def _copy_selection(e):
        if not selected_files:
            status_text.value = "⚠️ Aucun fichier sélectionné"
            page.update()
            return
        dst_base = (dst_path_field.value or "").strip()
        if not dst_base or not os.path.isdir(dst_base):
            status_text.value = "⚠️ Dossier de destination invalide"
            page.update()
            return
        dst = dst_base
        files_snap = list(selected_files)
        n = len(files_snap)
        status_text.value = f"[...] Copie de {n} fichier(s)..."
        page.update()

        def _do():
            try:
                os.makedirs(dst, exist_ok=True)
            except Exception as ex:
                page.pubsub.send_all_on_topic("sel_status", f"[ERREUR] Création dossier: {ex}")
                return
            ok, errors = 0, []
            for src in files_snap:
                if not os.path.isfile(src):
                    errors.append(f"{os.path.basename(src)}: introuvable")
                    continue
                dest_path = os.path.join(dst, os.path.basename(src))
                if os.path.exists(dest_path):
                    stem, ext = os.path.splitext(os.path.basename(src))
                    c = 1
                    while os.path.exists(dest_path):
                        dest_path = os.path.join(dst, f"{stem} ({c}){ext}")
                        c += 1
                try:
                    shutil.copy2(src, dest_path)
                    ok += 1
                except Exception as ex:
                    errors.append(f"{os.path.basename(src)}: {ex}")
            dst_label = os.path.basename(dst) or dst
            msg = f"[OK] {ok}/{n} copié(s) → {dst_label}"
            if errors:
                msg += f"  |  {len(errors)} erreur(s)"
            page.pubsub.send_all_on_topic("sel_status", msg)

        threading.Thread(target=_do, daemon=True).start()


    # ═════════════════════════════════════════════════════════════════════
    #  ██  Fonctions — Onglet 2
    # ═════════════════════════════════════════════════════════════════════

    def _load_json_list() -> list:
        path = json_path["value"]
        if not path or not os.path.isfile(path):
            return []
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
            if isinstance(data, list):
                result = []
                for item in data:
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
            with open(path, "w", encoding="utf-8") as f:
                json.dump(json_entries["list"], f, ensure_ascii=False, indent=2)
            list_status.value = "[OK] Sauvegardé"
        except Exception as ex:
            list_status.value = f"[ERREUR] {ex}"
        page.update()

    def _autosave():
        """Sauvegarde silencieuse après chaque ajout/édition/suppression."""
        path = json_path["value"]
        if not path:
            return
        try:
            with open(path, "w", encoding="utf-8") as f:
                json.dump(json_entries["list"], f, ensure_ascii=False, indent=2)
        except Exception as ex:
            list_status.value = f"[ERREUR] Autosave: {ex}"
            page.update()
        _save_list_states()

    def _copy_to_clipboard(text: str):
        try:
            page.set_clipboard(text)
            preview = text[:50] + ("..." if len(text) > 50 else "")
            list_status.value = f"[OK] Copié : {preview}"
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
            except Exception as ex2:
                list_status.value = f"[ERREUR] Clipboard: {ex2}"
        page.update()

    def _render_list():
        entries = list(json_entries["list"])
        q = list_search_q["value"].lower()
        if q:
            entries = [
                e for e in entries
                if q in e["nom"].lower() or q in e["description"].lower()
            ]
        if list_sort_mode["value"] == 1:
            entries = sorted(entries, key=lambda e: e["nom"].lower(), reverse=True)
        elif list_sort_mode["value"] == 2:
            entries = list(reversed(entries))  # dernier ajouté en premier
        else:
            entries = sorted(entries, key=lambda e: e["nom"].lower())

        if list_filter_active["value"]:
            entries = [e for e in entries if e["nom"] in list_selected_items["data"]]

        controls = []
        for entry in entries:
            nom  = entry["nom"]
            desc = entry["description"]

            controls.append(
                ft.Container(
                    content=ft.Row([
                        # ── Checkbox sélection ────────────────────────
                        ft.Checkbox(
                            value=nom in list_selected_items["data"],
                            tooltip="Sélection (filtre)",
                            on_change=lambda e, n=nom: _on_check_select(e, n),
                            active_color=VIOLET,
                        ),
                        # ── Nom ──────────────────────────────────────
                        ft.Container(
                            content=ft.Text(
                                nom, size=14, weight=ft.FontWeight.BOLD,
                                color=BLUE, max_lines=1,
                                overflow=ft.TextOverflow.ELLIPSIS,
                            ),
                            on_click=lambda e, n=nom: _copy_to_clipboard(n),
                            tooltip=f"Copier le nom : {nom}",
                            ink=True, border_radius=6,
                            padding=ft.Padding(10, 6, 10, 6),
                            bgcolor=DARK,
                            expand=2,
                        ),
                        # ── Description ───────────────────────────────
                        ft.Container(
                            content=ft.Text(
                                desc or "—", size=14, color=LIGHT_GREY,
                                max_lines=1, overflow=ft.TextOverflow.ELLIPSIS,
                            ),
                            on_click=lambda e, d=desc: _copy_to_clipboard(d) if d else None,
                            tooltip=f"Copier la description : {desc}" if desc else "Pas de description",
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
                                on_click=lambda e, n=nom, d=desc: _edit_entry(n, d),
                                style=ft.ButtonStyle(padding=ft.Padding.all(4)),
                            ),
                            # ── Checkbox mise en page ─────────────────────
                            ft.Checkbox(
                                value=nom in list_done_items["data"],
                                tooltip="Mise en page faite",
                                on_change=lambda e, n=nom: _on_check_done(e, n),
                                active_color=GREEN,
                            ),
                            ft.IconButton(
                                icon=ft.Icons.DELETE_OUTLINE,
                                icon_size=16, icon_color=RED,
                                tooltip="Supprimer",
                                on_click=lambda e, n=nom: _delete_entry(n),
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
        n_total   = len(json_entries["list"])
        n_visible = len(entries)
        n_sel     = len(list_selected_items["data"])
        if list_filter_active["value"]:
            list_count.value = f"{n_visible} sélectionnée(s) / {n_total} total"
        elif q:
            list_count.value = f"{n_visible}/{n_total} entrée(s)"
        else:
            list_count.value = f"{n_total} entrée(s)" + (f"  •  {n_sel} sélectionnée(s)" if n_sel else "")
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

    def _edit_entry(nom_orig: str, desc_orig: str):
        nom_f = ft.TextField(
            label="Nom", value=nom_orig, autofocus=True,
            bgcolor=DARK, border_color=BLUE, text_size=13,
        )
        desc_f = ft.TextField(
            label="Description", value=desc_orig,
            bgcolor=DARK, border_color=BLUE, text_size=13,
            multiline=True, min_lines=2, max_lines=6,
        )
        dlg = ft.AlertDialog(
            title=ft.Text("Éditer l'entrée"),
            content=ft.Column([nom_f, desc_f], spacing=8, tight=True, width=380),
        )

        def _confirm(e):
            new_nom  = (nom_f.value  or "").strip()
            new_desc = (desc_f.value or "").strip()
            if not new_nom:
                nom_f.error_text = "Requis"
                page.update()
                return
            for entry in json_entries["list"]:
                if entry["nom"] == nom_orig and entry["description"] == desc_orig:
                    entry["nom"]         = new_nom
                    entry["description"] = new_desc
                    break
            if new_nom != nom_orig:
                if nom_orig in list_selected_items["data"]:
                    list_selected_items["data"].discard(nom_orig)
                    list_selected_items["data"].add(new_nom)
                if nom_orig in list_done_items["data"]:
                    list_done_items["data"].discard(nom_orig)
                    list_done_items["data"].add(new_nom)
            dlg.open = False
            page.update()
            _autosave()
            _render_list()

        def _cancel(e):
            dlg.open = False
            page.update()

        nom_f.on_submit = _confirm
        dlg.actions = [
            ft.TextButton("Annuler", on_click=_cancel),
            ft.TextButton("OK", on_click=_confirm),
        ]
        page.overlay.append(dlg)
        dlg.open = True
        page.update()

    def _delete_entry(nom: str):
        def _confirm(e):
            json_entries["list"] = [
                en for en in json_entries["list"] if en["nom"] != nom
            ]
            list_selected_items["data"].discard(nom)
            list_done_items["data"].discard(nom)
            dlg.open = False
            page.update()
            _autosave()
            _render_list()

        def _cancel(e):
            dlg.open = False
            page.update()

        dlg = ft.AlertDialog(
            title=ft.Text("Supprimer l'entrée ?"),
            content=ft.Text(f"« {nom} » sera supprimée de la liste."),
            actions=[
                ft.TextButton("Annuler", on_click=_cancel),
                ft.TextButton(
                    "Supprimer",
                    on_click=_confirm,
                    style=ft.ButtonStyle(color=RED),
                ),
            ],
        )
        page.overlay.append(dlg)
        dlg.open = True
        page.update()

    def _add_entry(e):
        bloc_f = ft.TextField(
            label="Bloc (1re ligne = nom, suite = description)",
            hint_text="Collez ou saisissez le bloc ici…",
            autofocus=True,
            bgcolor=DARK, border_color=BLUE, text_size=13,
            multiline=True, min_lines=3, max_lines=10,
            width=380,
        )
        dlg = ft.AlertDialog(
            title=ft.Text("Ajouter une entrée"),
            content=ft.Column([bloc_f], spacing=8, tight=True, width=380),
        )

        def _confirm(e2):
            raw   = (bloc_f.value or "").replace("\r\n", "\n").replace("\r", "\n").strip()
            lines = raw.split("\n", 1)
            nom   = lines[0].strip()
            desc  = lines[1].strip() if len(lines) > 1 else ""
            if not nom:
                bloc_f.error_text = "La première ligne (nom) est requise"
                page.update()
                return
            bloc_f.error_text = None
            json_entries["list"].append({"nom": nom, "description": desc})
            dlg.open = False
            page.update()
            _autosave()
            _render_list()

        def _cancel(e2):
            dlg.open = False
            page.update()

        dlg.actions = [
            ft.TextButton("Annuler", on_click=_cancel),
            ft.TextButton("Ajouter", on_click=_confirm),
        ]
        page.overlay.append(dlg)
        dlg.open = True
        page.update()

    # ── Recherche liste ──────────────────────────────────────────────────
    def _on_list_search_change(e):
        q = (list_search_field.value or "").strip()
        list_search_q["value"] = q
        _render_list()

    def _on_list_sort_change(e):
        list_sort_mode["value"] = e.control.selected_index
        _render_list()

    def _on_check_select(e, nom):
        if e.control.value:
            list_selected_items["data"].add(nom)
        else:
            list_selected_items["data"].discard(nom)
        _update_filter_btn()
        _save_list_states()

    def _on_check_done(e, nom):
        if e.control.value:
            list_done_items["data"].add(nom)
        else:
            list_done_items["data"].discard(nom)
        _save_list_states()

    def _toggle_list_filter(e):
        list_filter_active["value"] = not list_filter_active["value"]
        _update_filter_btn()
        _render_list()

    def _deselect_all_list(e):
        list_selected_items["data"].clear()
        if list_filter_active["value"]:
            list_filter_active["value"] = False
        _update_filter_btn()
        _save_list_states()
        _render_list()

    def _update_filter_btn():
        n = len(list_selected_items["data"])
        if list_filter_active["value"]:
            filter_sel_btn.icon_color = VIOLET
            filter_sel_btn.tooltip    = f"Filtre actif ({n} sélectionnée(s)) — cliquer pour afficher tout"
        else:
            filter_sel_btn.icon_color = LIGHT_GREY
            filter_sel_btn.tooltip    = f"Afficher uniquement la sélection ({n} sélectionnée(s))"
        try:
            filter_sel_btn.update()
        except Exception:
            pass

    async def _pick_json(e):
        initial_dir = current_src["path"] or (
            os.path.dirname(json_path["value"])
            if json_path["value"] and os.path.isfile(json_path["value"])
            else None
        )
        result = await ft.FilePicker().pick_files(
            dialog_title="Ouvrir un fichier JSON",
            allowed_extensions=["json"],
            allow_multiple=False,
            initial_directory=initial_dir,
        )
        files = result.files if hasattr(result, "files") else result
        if files:
            p = files[0].path
            json_path["value"]    = p
            json_path_field.value = p
            json_path_field.update()
            _add_recent_json(p)
            _persist()
            _load_and_render()

    def _on_json_path_submit(e):
        p = (json_path_field.value or "").strip()
        if p and os.path.isfile(p):
            json_path["value"] = p
            _add_recent_json(p)
            _persist()
            _load_and_render()
        else:
            json_path_field.error_text = "Fichier introuvable"
            json_path_field.update()

    async def _new_json_file(e):
        """Crée un nouveau fichier JSON vide : choix du dossier puis du nom."""
        initial_dir = current_src["path"] or (
            os.path.dirname(json_path["value"])
            if json_path["value"] and os.path.isfile(json_path["value"])
            else None
        )
        folder = await ft.FilePicker().get_directory_path(
            dialog_title="Choisir l'emplacement du nouveau fichier JSON",
            initial_directory=initial_dir,
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
        dlg = ft.AlertDialog(
            title=ft.Text("Nouveau fichier JSON"),
            content=ft.Column([
                ft.Text(
                    folder, size=11, color=LIGHT_GREY,
                    overflow=ft.TextOverflow.ELLIPSIS, max_lines=1,
                ),
                name_field,
            ], spacing=8, tight=True, width=360),
        )

        def _confirm(ev):
            name = (name_field.value or "").strip()
            if not name:
                name_field.error_text = "Requis"
                page.update()
                return
            if not name.lower().endswith(".json"):
                name = name + ".json"
            p = os.path.join(folder, name)
            dlg.open = False
            page.update()
            try:
                with open(p, "w", encoding="utf-8") as f:
                    json.dump([], f, ensure_ascii=False, indent=2)
                json_path["value"]    = p
                json_path_field.value = p
                json_path_field.update()
                _add_recent_json(p)
                _persist()
                _load_and_render()
                list_status.value = f"[OK] Créé : {name}"
            except Exception as ex:
                list_status.value = f"[ERREUR] {ex}"
            page.update()

        def _cancel(ev):
            dlg.open = False
            page.update()

        name_field.on_submit = _confirm
        dlg.actions = [
            ft.TextButton("Annuler", on_click=_cancel),
            ft.TextButton("Créer", on_click=_confirm),
        ]
        page.overlay.append(dlg)
        dlg.open = True
        page.update()


    # ═════════════════════════════════════════════════════════════════════
    #  ██  Actions fenêtre
    # ═════════════════════════════════════════════════════════════════════

    async def _close(e):
        _persist()
        await page.window.close()

    def _minimize(e):
        page.window.minimized = True

    def _toggle_maximize(e):
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
    prev_page_btn.on_click     = lambda e: _go_to_page(-1)
    next_page_btn.on_click     = lambda e: _go_to_page(+1)
    copy_btn.on_click          = _copy_selection
    src_path_field.on_submit   = lambda e: (
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
                on_click=lambda e: _refresh_preview(),
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
    #  ██  Onglets + Barre de titre
    # ═════════════════════════════════════════════════════════════════════

    tabs = ft.Tabs(
        length=2,
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
                    f"SÉLECTEUR  {__version__}",
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
    if os.path.isfile(json_path["value"]):
        _load_and_render()
    else:
        list_count.value = "0 entrée(s)"

    # Navigation initiale : dossier transmis par Dashboard via variable d'environnement
    _initial_folder = os.environ.get("SELECTEUR_INITIAL_FOLDER", "").strip()
    if _initial_folder and os.path.isdir(_initial_folder):
        _navigate(_initial_folder)

    # Fichier JSON transmis par Dashboard (clic sur un .json)
    _initial_json = os.environ.get("SELECTEUR_JSON_PATH", "").strip()
    if _initial_json and os.path.isfile(_initial_json):
        _open_json_in_list(_initial_json)


#############################################################
#                         DÉMARRAGE                         #
#############################################################
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
