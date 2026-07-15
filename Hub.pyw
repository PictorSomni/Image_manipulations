# -*- coding: utf-8 -*-
"""
Hub — Application unifiée (remplace à terme Dashboard + SidePanel).

Coquille adaptative construite sur le cerveau partagé de Data/ :
  - Rail gauche  : surfaces interchangeables (Fichiers, Liste, IA, Notes).
  - Centre       : la surface active remplit la fenêtre.
  - Rail droit   : Actions -> overlay plein écran.
  - Barre d'état : Terminal (centre), curseur Taille des vignettes (droite).

Voir docs/HUB_SPEC.md pour la vision complète. Étape 1 : coquille + surface
Fichiers minimale (parcourir + lister). Les autres surfaces sont des
placeholders structurés, remplis incrémentalement.

Lançable indépendamment ou depuis les anciennes apps.
"""

__version__ = "1.0.0"

import asyncio
import base64
import datetime
import io
import json
import math
import os
import time
import platform
import subprocess
import sys
import shutil
import threading
import zipfile
from types import SimpleNamespace

import flet as ft
import flet.canvas as ftcv
import flet_code_editor as fce
from PIL import Image as PILImage, ImageDraw as PILImageDraw

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                "Data"))
import CONSTANTS
import image_ops
import ai_ops
import thumb_cache
import mcp_client
import credentials
from ai_tools import (
    _backup_file, _folder_create_file, _folder_list_contents, _folder_read_file,
    _folder_delete_files, _web_search, _fetch_url_content, _run_terminal_command,
    build_tool_list, dispatch_folder_tool, DISPATCH_UNHANDLED,
    _gemini_chat_stream_with_tools, _claude_chat_stream_with_tools,
    _build_system_content, _md_dark, _copy_scored_photos,
    _ai_save_history, _MicRecorder, _gemini_transcribe_audio,
    _update_memory_file, _iterate_image_loop, _IMAGE_ITERATE_TOOLS,
    _gemini_generate_image, _gemini_generate_music, _gemini_refine_image_prompt,
    _score_images_batched, _take_screenshot,
)


# ── Surfaces déclarées une fois : clé, libellé, icône ────────────────────
SURFACES = [
    ("files", "Fichiers", ft.Icons.PHOTO_LIBRARY_OUTLINED),
    ("liste", "Liste",    ft.Icons.LIST_ALT_OUTLINED),
    ("ia",    "IA",       ft.Icons.SMART_TOY_OUTLINED),
    ("notes", "Notes",    ft.Icons.EDIT_NOTE_OUTLINED),
]

# Entre les 40px jugés "un peu grands" et l'ICON_MD=20 trop petit.
LIST_THUMB_SIZE = 56

# Mêmes fichiers que Dashboard.pyw (racine du repo) : dossiers récents et
# favoris partagés, pas de nouvel emplacement vide pour l'utilisateur.
_APP_DIR = os.path.dirname(os.path.abspath(__file__))
_RECENT_FILE = os.path.join(_APP_DIR, ".recent_folders.json")
_FAVORITES_FILE = os.path.join(_APP_DIR, ".favorites.json")


def _load_recent():
    try:
        with open(_RECENT_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        return [p for p in data if isinstance(p, str) and os.path.isdir(p)]
    except Exception:
        return []


def _save_recent(folders):
    try:
        with open(_RECENT_FILE, "w", encoding="utf-8") as f:
            json.dump(folders[:10], f, ensure_ascii=False, indent=2)
    except Exception:
        pass


def _add_recent(path):
    recents = _load_recent()
    path = os.path.normpath(path)
    if path in recents:
        recents.remove(path)
    recents.insert(0, path)
    _save_recent(recents)


def _load_favorites():
    try:
        with open(_FAVORITES_FILE, "r", encoding="utf-8") as f:
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


def _save_favorites(favorites):
    try:
        with open(_FAVORITES_FILE, "w", encoding="utf-8") as f:
            json.dump(favorites, f, ensure_ascii=False, indent=2)
    except Exception:
        pass


_ORDER_FILE = os.path.join(_APP_DIR, ".order.json")


def _load_order():
    # photo (chemin absolu) -> {format: nombre} — plusieurs formats possibles
    # par photo (un client veut parfois la même image en plusieurs tailles).
    try:
        with open(_ORDER_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        return {p: {fmt: int(n) for fmt, n in v.items() if int(n) > 0}
                for p, v in data.items() if isinstance(v, dict)}
    except Exception:
        return {}


def _save_order(order):
    try:
        with open(_ORDER_FILE, "w", encoding="utf-8") as f:
            json.dump(order, f, ensure_ascii=False, indent=2)
    except Exception:
        pass


def main(page: ft.Page):
    # ─── Couleurs (rôles sémantiques, cf. CONSTANTS §3bis) ───────────────
    DARK       = CONSTANTS.COLOR_DARK
    BACKGROUND = CONSTANTS.COLOR_BACKGROUND
    GREY       = CONSTANTS.COLOR_GREY
    WHITE      = CONSTANTS.COLOR_WHITE
    ORANGE     = CONSTANTS.COLOR_ORANGE
    BLUE       = CONSTANTS.COLOR_BLUE
    YELLOW     = CONSTANTS.COLOR_YELLOW
    RED        = CONSTANTS.COLOR_RED
    VIOLET     = CONSTANTS.COLOR_VIOLET
    GREEN      = CONSTANTS.COLOR_GREEN
    LIGHT_GREY = CONSTANTS.COLOR_LIGHT_GREY
    ICON_ACTION = CONSTANTS.ICON_ACTION

    # ─── Fenêtre ─────────────────────────────────────────────────────────
    page.title      = "Hub"
    page.theme_mode = ft.ThemeMode.DARK
    page.bgcolor    = BACKGROUND
    page.padding    = 0
    page.window.title_bar_hidden         = True
    page.window.title_bar_buttons_hidden = True
    page.window.width  = 1280
    page.window.height = 860
    page.run_task(page.window.to_front)

    # ─── État partagé ────────────────────────────────────────────────────
    state = {"surface": "files", "folder": None, "view": "grid",
             "thumb_size": 150, "thumb_token": 0,
             "sort": "date", "search": "", "only_selected": False}
    content = {"dirs": [], "imgs": [], "other": []}   # non filtrés
    selected = set()                     # chemins sélectionnés (images + dossiers)
    clipboard = {"paths": [], "mode": None}   # mode: "copy" | "cut" | None
    thumb_mem = {}                       # cache mémoire path -> bytes miniature
    # Mode commande : path -> {format: nombre} — une photo peut avoir
    # plusieurs formats commandés. Édition via un clic sur la vignette
    # (badge « N tailles ») qui ouvre un petit dialogue, pas de clic droit.
    order = _load_order()
    order_mode = {"value": False}
    _ORDER_TARIFF = CONSTANTS.PRINTS

    # ═════════════════════════════════════════════════════════════════════
    #  Surface Fichiers (Explorateur) — liste ⇄ vignettes + sélection
    # ═════════════════════════════════════════════════════════════════════
    files_path = ft.Text("Aucun dossier ouvert", size=CONSTANTS.TEXT_SM,
                         color=WHITE, no_wrap=True, expand=True)
    sel_count = ft.Text("", size=CONSTANTS.TEXT_XS, color=BLUE, no_wrap=True)
    # Vue liste : ListView + ListTile, primitives éprouvées de Dashboard.
    files_list = ft.ListView(expand=True, spacing=2, padding=8)
    # Vue vignettes : GridView natif Flet (max_extent gère les colonnes tout
    # seul — inutile de mesurer la largeur dispo et découper en Row à la main).
    files_grid = ft.GridView(expand=True, max_extent=state["thumb_size"] + 20,
                             child_aspect_ratio=state["thumb_size"] / (state["thumb_size"] + 50),
                             spacing=10, run_spacing=10, padding=8)
    # Conteneur échangeable (jamais de Stack ici : expand ne s'y propage pas
    # aux enfants -> zone effondrée, cf. incident précédent). On échange le
    # contenu, comme Dashboard.
    files_body = ft.Container(content=files_list, expand=True)

    def _update_sel_count():
        n = len(selected)
        sel_count.value = f"{n} sélectionnée{'s' if n > 1 else ''}" if n else ""

    def _set_selected(path, on):
        if on:
            selected.add(path)
        else:
            selected.discard(path)
        _update_sel_count()
        _render()

    def _dir_tile(path):
        checkbox = ft.Checkbox(
            value=path in selected, active_color=BLUE,
            on_change=lambda e, p=path: _set_selected(p, e.control.value))
        return ft.ListTile(
            leading=checkbox,
            title=ft.Row([
                ft.Icon(ft.Icons.FOLDER, color=ORANGE, size=CONSTANTS.ICON_MD),
                ft.Text(os.path.basename(path), size=CONSTANTS.TEXT_SM,
                       color=WHITE),
            ], spacing=8),
            on_click=lambda e, p=path: _navigate(p),
            hover_color=GREY, dense=True,
            content_padding=ft.Padding(left=8, top=0, right=8, bottom=0),
        )

    def _img_tile(path, pending):
        size = LIST_THUMB_SIZE
        thumb = thumb_mem.get(path)
        if thumb:
            visual = ft.Image(src=thumb, width=size, height=size,
                              fit=ft.BoxFit.COVER,
                              border_radius=ft.BorderRadius.all(4))
        else:
            visual = ft.Container(bgcolor=GREY, width=size, height=size,
                                  border_radius=ft.BorderRadius.all(4))
            pending[path] = visual
        filename_text = ft.Text(os.path.basename(path), size=CONSTANTS.TEXT_SM,
                                color=WHITE, expand=True, no_wrap=True,
                                overflow=ft.TextOverflow.ELLIPSIS)
        if order_mode["value"]:
            # Le badge va DANS le Row du titre (pas en `trailing` séparé) :
            # ListTile a fait s'effondrer le titre entier (miniature + nom
            # disparus) quand `trailing` portait le badge — cf. retour user.
            leading = None
            row_children = [visual, filename_text, _order_badge(path)]
        else:
            leading = ft.Checkbox(
                value=path in selected, active_color=BLUE,
                on_change=lambda e, p=path: _set_selected(p, e.control.value))
            row_children = [visual, filename_text]
        return ft.ListTile(
            leading=leading,
            title=ft.Row(row_children, spacing=12,
                        vertical_alignment=ft.CrossAxisAlignment.CENTER),
            on_click=lambda e, p=path: _open_viewer(p),
            hover_color=GREY, dense=True,
            content_padding=ft.Padding(left=8, top=2, right=8, bottom=2),
        )

    # ── Vue vignettes : carte GridView (cellule dimensionnée par max_extent /
    # child_aspect_ratio, pas de largeur manuelle) ────────────────────────
    def _dir_card(path):
        is_sel = path in selected
        checkbox = ft.Checkbox(
            value=is_sel, active_color=BLUE,
            on_change=lambda e, p=path: _set_selected(p, e.control.value))
        icon_zone = ft.Container(
            content=ft.Column([
                ft.Icon(ft.Icons.FOLDER, color=ORANGE, size=CONSTANTS.ICON_MD),
                ft.Text(os.path.basename(path), size=CONSTANTS.TEXT_XS,
                        color=WHITE, no_wrap=True),
            ], alignment=ft.MainAxisAlignment.CENTER,
               horizontal_alignment=ft.CrossAxisAlignment.CENTER, spacing=6,
               expand=True),
            expand=True, ink=True, on_click=lambda e, p=path: _navigate(p))
        header = ft.Row([ft.Container(expand=True), checkbox])
        return ft.Container(
            content=ft.Column([header, icon_zone], spacing=0, expand=True),
            padding=6,
            border=ft.Border.all(2, BLUE) if is_sel else ft.Border.all(1, GREY),
            border_radius=8)

    _FILE_ICONS = {
        ".json": ft.Icons.DATA_OBJECT_OUTLINED,
        ".txt": ft.Icons.DESCRIPTION_OUTLINED,
        ".md": ft.Icons.DESCRIPTION_OUTLINED,
        ".zip": ft.Icons.FOLDER_ZIP_OUTLINED,
        ".pdf": ft.Icons.PICTURE_AS_PDF_OUTLINED,
    }

    def _file_icon(path):
        return _FILE_ICONS.get(os.path.splitext(path)[1].lower(),
                               ft.Icons.INSERT_DRIVE_FILE_OUTLINED)

    def _open_file_default(path):
        try:
            system = platform.system()
            if system == "Windows":
                os.startfile(path)
            elif system == "Darwin":
                subprocess.Popen(["open", path])
            else:
                subprocess.Popen(["xdg-open", path])
        except Exception:
            pass

    # Extensions lisibles dans le Bloc-notes (coloration syntaxique), comme
    # Dashboard.pyw:1589-1597 — les autres s'ouvrent avec l'appli par défaut.
    # .json est exclu d'ici : il va dans la surface Liste (lecteur JSON),
    # pas le Bloc-notes brut — cf. _liste_open_path plus bas.
    _NOTEPAD_EXTS = {".py", ".pyw", ".md", ".markdown", ".txt"}

    def _open_file(path):
        ext = os.path.splitext(path)[1].lower()
        if ext == ".json":
            _liste_open_path(path)
        elif ext in _NOTEPAD_EXTS:
            _open_path_in_notes(path)
        else:
            _open_file_default(path)

    def _file_tile(path):
        return ft.ListTile(
            leading=ft.Icon(_file_icon(path), color=ICON_ACTION,
                            size=CONSTANTS.ICON_MD),
            title=ft.Text(os.path.basename(path), size=CONSTANTS.TEXT_SM, color=WHITE),
            on_click=lambda e, p=path: _open_file(p),
            hover_color=GREY, dense=True,
            content_padding=ft.Padding(left=8, top=0, right=8, bottom=0),
        )

    def _file_card(path):
        return ft.Container(
            content=ft.Column([
                ft.Icon(_file_icon(path), color=ICON_ACTION, size=CONSTANTS.ICON_MD),
                ft.Text(os.path.basename(path), size=CONSTANTS.TEXT_XS,
                        color=WHITE, no_wrap=True),
            ], alignment=ft.MainAxisAlignment.CENTER,
               horizontal_alignment=ft.CrossAxisAlignment.CENTER, spacing=6,
               expand=True),
            padding=6, border=ft.Border.all(1, GREY), border_radius=8,
            ink=True, on_click=lambda e, p=path: _open_file(p))

    def _grid_card(path, pending):
        is_sel = path in selected
        thumb = thumb_mem.get(path)
        if thumb:
            img = ft.Image(src=thumb, fit=ft.BoxFit.COVER, expand=True,
                           border_radius=ft.BorderRadius.all(6))
        else:
            img = ft.Container(bgcolor=GREY, expand=True,
                               border_radius=ft.BorderRadius.all(6))
            pending[path] = img
        # Zone image cliquable = ouvre la visionneuse ; case à cocher séparée
        # (widget dédié, comme leading=Checkbox dans un ListTile) = sélection.
        img_zone = ft.Container(content=img, expand=True, border_radius=6,
                                ink=True,
                                on_click=lambda e, p=path: _open_viewer(p))
        is_ordered = path in order
        label = ft.Text(os.path.basename(path), size=CONSTANTS.TEXT_XS,
                        color=WHITE, no_wrap=True)
        if order_mode["value"]:
            # Badge commande sous le nom (pas de case à cocher sur l'image) —
            # clic = dialogue plusieurs tailles, jamais de clic droit.
            highlighted = is_ordered
            body = [img_zone, label, _order_badge(path)]
        else:
            checkbox = ft.Checkbox(
                value=is_sel, active_color=BLUE,
                on_change=lambda e, p=path: _set_selected(p, e.control.value))
            header = ft.Row([ft.Container(expand=True), checkbox])
            highlighted = is_sel
            body = [header, img_zone, label]
        return ft.Container(
            content=ft.Column(body, spacing=4, expand=True,
                              horizontal_alignment=ft.CrossAxisAlignment.STRETCH),
            padding=6,
            border=ft.Border.all(2, BLUE) if highlighted else ft.Border.all(1, GREY),
            border_radius=8)

    def _sort_key(path):
        if state["sort"] == "date":
            try:
                return -os.path.getmtime(path)
            except OSError:
                return 0
        return os.path.basename(path).lower()

    def _visible_entries():
        query = state["search"].strip().lower()
        reverse = state["sort"] == "name_desc"
        dirs = [p for p in content["dirs"] if query in os.path.basename(p).lower()]
        imgs = [p for p in content["imgs"] if query in os.path.basename(p).lower()]
        other = [p for p in content["other"] if query in os.path.basename(p).lower()]
        dirs.sort(key=_sort_key, reverse=reverse)
        imgs.sort(key=_sort_key, reverse=reverse)
        other.sort(key=_sort_key, reverse=reverse)
        if state["only_selected"]:
            dirs = [p for p in dirs if p in selected]
            imgs = [p for p in imgs if p in selected]
            other = []
        return dirs, imgs, other

    def _with_ctx_menu(control, path):
        return ft.GestureDetector(
            on_secondary_tap_up=lambda e, p=path: _show_context_menu(p),
            content=control)

    def _render():
        # Mutation en place (.clear()+.extend()), jamais de réassignation de
        # .controls : Flet ne détecte pas toujours un remplacement wholesale
        # de la liste pour le diff de rendu (idiome Dashboard/SidePanel).
        dirs, imgs, other = _visible_entries()
        files_list.controls.clear()
        files_grid.controls.clear()
        if not dirs and not imgs and not other:
            if state["only_selected"]:
                msg = "Aucun élément sélectionné."
            elif state["search"].strip():
                msg = "Aucun résultat."
            else:
                msg = "Dossier vide."
            files_list.controls.append(
                ft.Text(msg, size=CONSTANTS.TEXT_SM, color=WHITE))
        elif state["view"] == "list":
            pending = {}
            files_list.controls.extend(_with_ctx_menu(_dir_tile(p), p) for p in dirs)
            files_list.controls.extend(
                _with_ctx_menu(_img_tile(p, pending), p) for p in imgs)
            files_list.controls.extend(_with_ctx_menu(_file_tile(p), p) for p in other)
            _start_thumb_loader(pending)
        else:
            pending = {}
            files_grid.controls.extend(_with_ctx_menu(_dir_card(p), p) for p in dirs)
            files_grid.controls.extend(
                _with_ctx_menu(_grid_card(p, pending), p) for p in imgs)
            files_grid.controls.extend(_with_ctx_menu(_file_card(p), p) for p in other)
            _start_thumb_loader(pending)
        files_body.content = files_list if state["view"] == "list" else files_grid
        _update_view_seg()
        page.update()

    def _start_thumb_loader(pending):
        """Génère les miniatures manquantes en arrière-plan (token = annulation)."""
        if not pending:
            return
        state["thumb_token"] += 1
        token = state["thumb_token"]
        snapshot = list(pending.items())

        def _load():
            for path, holder in snapshot:
                if state["thumb_token"] != token:
                    return
                data = thumb_cache.get_or_generate(path)
                if data and state["thumb_token"] == token:
                    thumb_mem[path] = data
                    holder.content = ft.Image(
                        src=data, width=holder.width, height=holder.height,
                        fit=ft.BoxFit.COVER, border_radius=ft.BorderRadius.all(6))
                    holder.bgcolor = None
                    page.run_task(_safe_update)

        threading.Thread(target=_load, daemon=True).start()

    async def _safe_update():
        try:
            page.update()
        except Exception:
            pass

    # ═════════════════════════════════════════════════════════════════════
    #  Copier / Couper / Coller / Supprimer — presse-papiers interne à l'app
    #  (pas le presse-papiers système : simple, fiable, suffisant ici).
    #  Suppression : pas de dialogue de confirmation (politique du projet),
    #  _backup_file avant toute suppression/écrasement à la place.
    # ═════════════════════════════════════════════════════════════════════
    def _context_menu_targets(path):
        if path in selected and len(selected) > 1:
            return list(selected)
        return [path]

    def _do_copy(paths):
        clipboard["paths"] = list(paths)
        clipboard["mode"] = "copy"
        page.update()

    def _do_cut(paths):
        clipboard["paths"] = list(paths)
        clipboard["mode"] = "cut"
        page.update()

    def _unique_dest(folder, name):
        base, ext = os.path.splitext(name)
        dest = os.path.join(folder, name)
        n = 1
        while os.path.exists(dest):
            dest = os.path.join(folder, f"{base} ({n}){ext}")
            n += 1
        return dest

    def _do_paste(event=None):
        folder = state["folder"]
        if not folder or not clipboard["paths"]:
            return
        for src in clipboard["paths"]:
            if not os.path.exists(src):
                continue
            dest = _unique_dest(folder, os.path.basename(src))
            try:
                if clipboard["mode"] == "cut":
                    shutil.move(src, dest)
                elif os.path.isdir(src):
                    shutil.copytree(src, dest)
                else:
                    shutil.copy2(src, dest)
            except Exception:
                continue
        if clipboard["mode"] == "cut":
            clipboard["paths"] = []
            clipboard["mode"] = None
        _navigate(folder)

    def _do_delete(paths):
        for p in paths:
            try:
                _backup_file(p)
                if os.path.isdir(p):
                    shutil.rmtree(p)
                else:
                    os.remove(p)
                selected.discard(p)
            except Exception:
                continue
        _update_sel_count()
        _navigate(state["folder"])

    def _do_duplicate(paths):
        folder = state["folder"]
        if not folder:
            return
        for src in paths:
            if not os.path.exists(src):
                continue
            stem, ext = os.path.splitext(os.path.basename(src))
            dest = _unique_dest(folder, f"{stem} (copie){ext}")
            try:
                if os.path.isdir(src):
                    shutil.copytree(src, dest)
                else:
                    shutil.copy2(src, dest)
            except Exception:
                continue
        _navigate(folder)

    def _do_zip(paths):
        folder = state["folder"]
        paths = [p for p in paths if os.path.exists(p)]
        if not folder or not paths:
            return
        name = (os.path.basename(folder) if len(paths) > 1
                else os.path.splitext(os.path.basename(paths[0]))[0])
        zip_path = _unique_dest(folder, f"{name}.zip")
        try:
            with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
                for p in paths:
                    if os.path.isdir(p):
                        base = os.path.dirname(p)
                        for root, _dirs, files in os.walk(p):
                            for f in files:
                                full = os.path.join(root, f)
                                zf.write(full, os.path.relpath(full, base))
                    else:
                        zf.write(p, os.path.basename(p))
        except Exception:
            pass
        _navigate(folder)

    def _do_copy_to_selection(paths):
        folder = state["folder"]
        if not folder:
            return
        selection_folder = os.path.join(folder, "SELECTION")
        os.makedirs(selection_folder, exist_ok=True)
        for src in paths:
            if not os.path.isfile(src):
                continue
            dest = _unique_dest(selection_folder, os.path.basename(src))
            try:
                shutil.copy2(src, dest)
            except Exception:
                continue
        _navigate(selection_folder)

    def _reveal_in_explorer(paths):
        target = paths[0] if paths else None
        if not target or not os.path.exists(target):
            return
        folder = target if os.path.isdir(target) else os.path.dirname(target)
        try:
            system = platform.system()
            if system == "Windows":
                if os.path.isfile(target):
                    subprocess.Popen(["explorer", "/select,", target])
                else:
                    subprocess.Popen(["explorer", folder])
            elif system == "Darwin":
                if os.path.isfile(target):
                    subprocess.Popen(["open", "-R", target])
                else:
                    subprocess.Popen(["open", folder])
            else:
                subprocess.Popen(["xdg-open", folder])
        except Exception:
            pass

    def _rename_item(paths):
        path = paths[0] if paths else None
        if not path or not os.path.exists(path):
            return
        parent = os.path.dirname(path)
        current_name = os.path.basename(path)
        stem, ext = os.path.splitext(current_name)
        name_field = ft.TextField(
            value=stem if ext else current_name,
            suffix=ft.Text(ext, color=GREY) if ext else None,
            autofocus=True, width=320, bgcolor=DARK, border_color=GREY,
            color=WHITE)

        def _cancel(event):
            dlg.open = False
            page.update()

        def _confirm(event):
            new_stem = (name_field.value or "").strip()
            dlg.open = False
            page.update()
            if not new_stem:
                return
            new_name = new_stem + ext
            if new_name == current_name:
                return
            new_path = os.path.join(parent, new_name)
            try:
                os.rename(path, new_path)
            except OSError:
                return
            selected.discard(path)
            _navigate(parent)

        name_field.on_submit = _confirm
        dlg = ft.AlertDialog(
            title=ft.Text("Renommer", size=13, color=WHITE),
            content=name_field,
            actions=[
                ft.TextButton("Annuler", on_click=_cancel),
                ft.TextButton("Renommer", on_click=_confirm),
            ],
        )
        page.overlay.append(dlg)
        dlg.open = True
        page.update()

    def _show_context_menu(path):
        targets = _context_menu_targets(path)
        label = (os.path.basename(path) if len(targets) == 1
                 else f"{len(targets)} éléments")

        def _cancel(event):
            dlg.open = False
            page.update()
            page.run_task(_focus_active_surface)

        def _act(fn):
            def _run(event):
                dlg.open = False
                page.update()
                fn(targets)
                page.run_task(_focus_active_surface)
            return _run

        def _menu_row(icon, color, text, fn):
            return ft.ListTile(
                leading=ft.Icon(icon, color=color, size=CONSTANTS.ICON_SM),
                title=ft.Text(text, size=CONSTANTS.TEXT_SM, color=WHITE),
                on_click=_act(fn), dense=True, hover_color=GREY,
                content_padding=ft.Padding(left=10, top=0, right=10, bottom=0))

        rows = []
        if len(targets) == 1:
            rows.append(_menu_row(ft.Icons.DRIVE_FILE_RENAME_OUTLINE,
                                   BLUE, "Renommer", _rename_item))
        rows.append(_menu_row(ft.Icons.CONTENT_COPY, BLUE,
                               "Copier", _do_copy))
        rows.append(_menu_row(ft.Icons.CONTENT_CUT, BLUE,
                               "Couper", _do_cut))
        rows.append(_menu_row(ft.Icons.FILE_COPY_OUTLINED, BLUE,
                               "Dupliquer ici", _do_duplicate))
        if clipboard["paths"]:
            rows.append(ft.ListTile(
                leading=ft.Icon(ft.Icons.CONTENT_PASTE, color=GREEN,
                                size=CONSTANTS.ICON_SM),
                title=ft.Text("Coller ici", size=CONSTANTS.TEXT_SM, color=WHITE),
                on_click=lambda e: (setattr(dlg, "open", False), page.update(),
                                    _do_paste()),
                dense=True, hover_color=GREY,
                content_padding=ft.Padding(left=10, top=0, right=10, bottom=0)))
        rows.append(_menu_row(ft.Icons.STAR_OUTLINE, YELLOW,
                               "Copier vers SELECTION", _do_copy_to_selection))
        rows.append(_menu_row(ft.Icons.FOLDER_ZIP_OUTLINED, YELLOW,
                               "Zipper", _do_zip))
        rows.append(_menu_row(ft.Icons.SMART_TOY_OUTLINED, VIOLET,
                               "Ajouter à l'IA", _add_to_ai))
        rows.append(_menu_row(
            ft.Icons.FOLDER_OPEN,
            VIOLET,
            "Afficher dans l'Explorateur" if platform.system() == "Windows"
            else "Afficher dans le Finder" if platform.system() == "Darwin"
            else "Afficher dans le gestionnaire de fichiers",
            _reveal_in_explorer))
        rows.append(_menu_row(ft.Icons.DELETE_OUTLINE, RED,
                               "Supprimer", _do_delete))

        dlg = ft.AlertDialog(
            title=ft.Text(label, size=13, color=WHITE, no_wrap=True),
            content=ft.Column(rows, spacing=0, tight=True, width=270),
            actions=[ft.TextButton("Fermer", on_click=_cancel)],
        )
        page.overlay.append(dlg)
        dlg.open = True
        page.update()

    def _navigate(path):
        path = os.path.normpath(path)
        if not os.path.isdir(path):
            return
        state["folder"] = path
        state["thumb_token"] += 1        # annule un chargement en cours
        files_path.value = path
        _add_recent(path)
        create_file_btn.disabled = False
        selected.clear()
        _update_sel_count()
        try:
            entries = list(os.scandir(path))
        except OSError as exc:
            content["dirs"], content["imgs"], content["other"] = [], [], []
            files_list.controls.clear()
            files_list.controls.append(ft.Text(str(exc), color=WHITE))
            files_body.content = files_list
            page.update()
            return
        exts = CONSTANTS.IMAGE_EXTS
        dirs, imgs, other = [], [], []
        for e in entries:
            if CONSTANTS.is_os_junk(e.name, e.is_dir()):
                continue
            if e.is_dir():
                dirs.append(e.path)
            elif os.path.splitext(e.name)[1].lower() in exts:
                imgs.append(e.path)
            else:
                other.append(e.path)
        content["dirs"] = sorted(dirs, key=lambda p: os.path.basename(p).lower())
        content["imgs"] = sorted(imgs, key=lambda p: os.path.basename(p).lower())
        content["other"] = sorted(other, key=lambda p: os.path.basename(p).lower())
        _render()
        page.run_task(_focus_active_surface)

    async def _pick_folder(event):
        folder = await ft.FilePicker().get_directory_path(
            dialog_title="Dossier d'images")
        if folder:
            _navigate(folder)

    def _toggle_all(event):
        entries = content["dirs"] + content["imgs"]
        if selected.issuperset(entries) and entries:
            selected.clear()
        else:
            selected.update(entries)
        _update_sel_count()
        _render()

    def _invert(event):
        new = set(content["dirs"] + content["imgs"]) - selected
        selected.clear()
        selected.update(new)
        _update_sel_count()
        _render()

    def _toggle_only_selected(event):
        state["only_selected"] = not state["only_selected"]
        only_sel_btn.style = ft.ButtonStyle(
            bgcolor=BLUE if state["only_selected"] else GREY,
            color=DARK if state["only_selected"] else WHITE)
        _render()

    def _toggle_order_mode(event):
        # Bascule inline (case à cocher <-> badge commande sur chaque
        # vignette) — pas de clic droit, pas de menu déroulant caché.
        order_mode["value"] = not order_mode["value"]
        order_mode_btn.style = ft.ButtonStyle(
            bgcolor=BLUE if order_mode["value"] else GREY,
            color=DARK if order_mode["value"] else WHITE)
        _render()

    def _mini_btn(icon, on_click):
        return ft.Container(
            content=ft.Icon(icon, size=12, color=ICON_ACTION),
            width=18, height=18, border_radius=4, bgcolor=GREY,
            alignment=ft.Alignment.CENTER, ink=True, on_click=on_click)

    def _refresh_viewer_order(path):
        # Le bandeau bas de la visionneuse a son propre badge (pas de
        # rebuild complet à chaque clic) : on ne le rafraîchit que si c'est
        # bien la photo affichée qui vient de changer.
        if (viewer_overlay in page.overlay and viewer_state["paths"]
                and viewer_state["paths"][viewer_state["index"]] == path):
            _update_viewer()

    def _edit_order_for_photo(path):
        # Un dialogue (page.overlay) plutôt qu'un Dropdown imbriqué dans la
        # grille défilante : un Dropdown niché dans un GridView voit son
        # panneau d'options tronqué (signalé par l'utilisateur — « je ne
        # vois pas toutes les tailles »). Toutes les tailles PRINTS listées
        # d'un coup, un stepper par taille -> plusieurs tailles par photo.
        entry = order.get(path, {})
        counters = {}

        def _apply(fmt, delta):
            e = order.setdefault(path, {})
            new_count = max(0, e.get(fmt, 0) + delta)
            if new_count:
                e[fmt] = new_count
            else:
                e.pop(fmt, None)
            if not e:
                order.pop(path, None)
            counters[fmt].value = str(new_count)
            _save_order(order)
            page.update()
            _render()
            _refresh_viewer_order(path)

        rows = []
        for fmt in _ORDER_TARIFF:
            count_text = ft.Text(str(entry.get(fmt, 0)), size=CONSTANTS.TEXT_SM,
                                 color=WHITE, width=22, text_align=ft.TextAlign.CENTER)
            counters[fmt] = count_text
            rows.append(ft.Row([
                ft.Text(fmt, size=CONSTANTS.TEXT_SM, color=WHITE, width=70),
                _mini_btn(ft.Icons.REMOVE, lambda e, f=fmt: _apply(f, -1)),
                count_text,
                _mini_btn(ft.Icons.ADD, lambda e, f=fmt: _apply(f, 1)),
            ], spacing=8, vertical_alignment=ft.CrossAxisAlignment.CENTER))

        def _close(event):
            dlg.open = False
            page.update()

        dlg = ft.AlertDialog(
            title=ft.Text(os.path.basename(path), size=13, color=WHITE, no_wrap=True),
            content=ft.Column(rows, spacing=8, tight=True, scroll=ft.ScrollMode.AUTO,
                              height=min(320, len(rows) * 40), width=220),
            actions=[ft.TextButton("Fermer", on_click=_close)],
        )
        page.overlay.append(dlg)
        dlg.open = True
        page.update()

    def _order_badge(path):
        entry = order.get(path, {})
        n = len(entry)
        label = f"{n} taille{'s' if n > 1 else ''}" if n else "+ Commande"
        return ft.Container(
            content=ft.Row([
                ft.Icon(ft.Icons.RECEIPT_LONG_OUTLINED, size=12, color=ICON_ACTION),
                ft.Text(label, size=CONSTANTS.TEXT_XS, color=WHITE),
            ], spacing=4, tight=True, alignment=ft.MainAxisAlignment.CENTER),
            padding=ft.Padding(6, 3, 6, 3), border_radius=6, bgcolor=GREY,
            ink=True, on_click=lambda e, p=path: _edit_order_for_photo(p),
            alignment=ft.Alignment.CENTER)

    def _apply_thumb_size(value):
        # Pas de _render() ici : les cartes existantes (Image/Container en
        # expand=True) se redimensionnent toutes seules quand max_extent
        # change -> juste reflow, aucune reconstruction. Un _render() complet
        # à chaque tick du curseur provoquait le clignotement signalé.
        size = int(value)
        if size == state["thumb_size"]:
            return
        state["thumb_size"] = size
        files_grid.max_extent = size + 20
        files_grid.child_aspect_ratio = size / (size + 50)
        if state["view"] == "grid":
            files_grid.update()

    def _seg_btn(icon, text, on_click):
        # Pas de `color=` sur l'Icon/Text imbriqués : ils héritent de
        # ButtonStyle.color, ce qui permet à _update_view_seg() de recolorer
        # tout le bouton (fond + icône + texte) en une seule affectation.
        return ft.TextButton(
            content=ft.Row([
                ft.Icon(icon, size=CONSTANTS.ICON_SM),
                ft.Text(text, size=CONSTANTS.TEXT_SM),
            ], spacing=4, tight=True),
            style=ft.ButtonStyle(bgcolor=GREY, color=WHITE,
                                 padding=ft.Padding(10, 6, 10, 6)),
            on_click=on_click,
        )

    def _update_view_seg():
        view_seg.selected_index = 0 if state["view"] == "grid" else 1

    def _on_view_seg_change(event):
        state["view"] = "grid" if event.control.selected_index == 0 else "list"
        _render()

    def _seg_label(icon, text):
        return ft.Row([
            ft.Icon(icon, size=CONSTANTS.ICON_SM, color=WHITE),
            ft.Text(text, size=CONSTANTS.TEXT_SM, color=WHITE),
        ], spacing=4, tight=True)

    view_seg = ft.CupertinoSlidingSegmentedButton(
        selected_index=0,
        controls=[
            _seg_label(ft.Icons.GRID_VIEW, "Vignettes"),
            _seg_label(ft.Icons.VIEW_LIST, "Liste"),
        ],
        bgcolor=DARK, thumb_color=BLUE, padding=ft.Padding(3, 3, 3, 3),
        on_change=_on_view_seg_change,
    )

    def _set_search(value):
        state["search"] = value or ""
        _render()

    search_field = ft.TextField(
        hint_text="Rechercher…", on_change=lambda e: _set_search(e.control.value),
        dense=True, height=36, width=170, bgcolor=DARK, border_color=GREY,
        color=WHITE, text_size=CONSTANTS.TEXT_SM,
        content_padding=ft.Padding(10, 0, 10, 0),
        prefix_icon=ft.Icons.SEARCH,
    )

    _SORT_LABELS = {"name_asc": "Nom (A→Z)", "name_desc": "Nom (Z→A)",
                    "date": "Date (récent d'abord)"}
    _SORT_SHORT = {"name_asc": "Nom ↑", "name_desc": "Nom ↓", "date": "Date ↓"}

    def _set_sort(mode):
        def _apply(event):
            state["sort"] = mode
            sort_label.value = f"Trier : {_SORT_SHORT[mode]}"
            _render()
        return _apply

    sort_label = ft.Text(f"Trier : {_SORT_SHORT['date']}", size=CONSTANTS.TEXT_SM,
                         color=WHITE)
    sort_btn = ft.PopupMenuButton(
        content=ft.Container(
            content=ft.Row([
                ft.Icon(ft.Icons.SORT, size=CONSTANTS.ICON_SM, color=WHITE),
                sort_label,
                ft.Icon(ft.Icons.ARROW_DROP_DOWN, size=CONSTANTS.ICON_SM, color=WHITE),
            ], spacing=4, tight=True),
            bgcolor=GREY, border_radius=8, padding=ft.Padding(10, 7, 6, 7)),
        items=[
            ft.PopupMenuItem(content=ft.Text("Nom (A→Z)"), on_click=_set_sort("name_asc")),
            ft.PopupMenuItem(content=ft.Text("Nom (Z→A)"), on_click=_set_sort("name_desc")),
            ft.PopupMenuItem(content=ft.Text("Date (récent d'abord)"),
                             on_click=_set_sort("date")),
        ],
    )

    # ═════════════════════════════════════════════════════════════════════
    #  Visionneuse plein écran — overlay unique réutilisable, ouvert(e) sur
    #  page.overlay (hors de l'arbre de mise en page normal -> aucun des
    #  soucis d'expand/Stack imbriqué rencontrés dans la surface Fichiers).
    # ═════════════════════════════════════════════════════════════════════
    viewer_state = {"paths": [], "index": 0}
    _prev_keyboard = {"fn": None}
    # path -> bytes tournés cette session : le chemin fichier ne change pas
    # après rotation, donc Flet pourrait réafficher l'ancienne image en cache
    # si on repasse par le chemin brut au lieu des bytes à jour.
    viewer_rotated_bytes = {}

    _BLANK_GIF = "data:image/gif;base64,R0lGODlhAQABAAD/ACwAAAAAAQABAAACADs="
    viewer_img = ft.Image(src=_BLANK_GIF, fit=ft.BoxFit.CONTAIN, expand=True,
                          gapless_playback=True)
    viewer_filename = ft.Text("", size=CONSTANTS.TEXT_SM, color=WHITE,
                              weight=ft.FontWeight.W_500)
    viewer_counter = ft.Text("", size=CONSTANTS.TEXT_XS, color=WHITE)
    viewer_checkbox = ft.Checkbox(
        value=False, active_color=BLUE,
        on_change=lambda e: _set_selected(
            viewer_state["paths"][viewer_state["index"]], e.control.value))

    viewer_order_slot = ft.Container(visible=False)

    def _update_viewer():
        idx, paths = viewer_state["index"], viewer_state["paths"]
        path = paths[idx]
        viewer_img.src = viewer_rotated_bytes.get(path, path)
        viewer_filename.value = os.path.basename(path)
        viewer_counter.value = f"{idx + 1} / {len(paths)}"
        viewer_checkbox.value = path in selected
        viewer_order_slot.visible = order_mode["value"]
        viewer_order_slot.content = (
            _order_badge(path) if order_mode["value"] else None)
        page.update()

    def _viewer_nav(delta):
        new_idx = viewer_state["index"] + delta
        if not (0 <= new_idx < len(viewer_state["paths"])):
            return
        viewer_state["index"] = new_idx
        _close_drawers()
        _update_viewer()

    def _close_viewer(event=None):
        page.on_keyboard_event = _prev_keyboard["fn"]
        _close_drawers()
        if viewer_overlay in page.overlay:
            page.overlay.remove(viewer_overlay)
        page.update()
        page.run_task(_focus_active_surface)

    def _viewer_on_key(event):
        if event.key == "Escape":
            _close_viewer()
        elif event.key == "Arrow Left":
            _viewer_nav(-1)
        elif event.key == "Arrow Right":
            _viewer_nav(1)

    def _rotate_current(direction):
        # Copie dérivée (HUB_SPEC §7) : l'original n'est jamais écrasé,
        # cohérent avec les tiroirs Retoucher/Recadrer (_derived_path).
        path = viewer_state["paths"][viewer_state["index"]]
        ext = os.path.splitext(path)[1].lower()
        if ext not in CONSTANTS.ROTATABLE_EXTS:
            return
        try:
            with PILImage.open(path) as im:
                rotated = im.rotate(90 if direction == "left" else -90, expand=True)
                if ext in (".jpg", ".jpeg"):
                    rotated = rotated.convert("RGB")
        except Exception:
            return
        fmt = "JPEG" if ext in (".jpg", ".jpeg") else "PNG"
        save_kwargs = {"quality": 100, "subsampling": 0} if fmt == "JPEG" else {}
        buf = io.BytesIO()
        rotated.save(buf, fmt, **save_kwargs)
        viewer_rotated_bytes[path] = buf.getvalue()
        viewer_img.src = viewer_rotated_bytes[path]   # aperçu immédiat
        page.update()

        def _persist():
            try:
                dest = _derived_path(path, "_pivote")
                rotated.save(dest, fmt, **save_kwargs)
            except Exception as exc:
                _log_to_terminal(f"[ERREUR] Rotation : {exc}", RED)
                return
            _log_to_terminal(f"Rotation enregistrée : {dest}", GREEN)

        threading.Thread(target=_persist, daemon=True).start()

    def _viewer_btn(icon, tip, cb):
        return ft.IconButton(icon=icon, icon_color=WHITE, icon_size=22,
                             tooltip=tip, on_click=cb)

    viewer_top_bar = ft.Container(
        content=ft.Row([
            viewer_filename, viewer_counter,
            ft.Container(expand=True),
            _viewer_btn(ft.Icons.CLOSE, "Fermer (Échap)", _close_viewer),
        ], spacing=10, vertical_alignment=ft.CrossAxisAlignment.CENTER),
        bgcolor=GREY, padding=ft.Padding(12, 8, 8, 8), border_radius=12,
    )
    viewer_bottom_bar = ft.Container(
        content=ft.Row([
            viewer_checkbox,
            ft.VerticalDivider(width=1, color=DARK),
            _viewer_btn(ft.Icons.ARROW_BACK_IOS_ROUNDED, "Précédente (←)",
                       lambda e: _viewer_nav(-1)),
            _viewer_btn(ft.Icons.ROTATE_LEFT, "Pivoter à gauche",
                       lambda e: _rotate_current("left")),
            _viewer_btn(ft.Icons.ROTATE_RIGHT, "Pivoter à droite",
                       lambda e: _rotate_current("right")),
            _viewer_btn(ft.Icons.ARROW_FORWARD_IOS_ROUNDED, "Suivante (→)",
                       lambda e: _viewer_nav(1)),
            viewer_order_slot,
        ], spacing=6, tight=True, vertical_alignment=ft.CrossAxisAlignment.CENTER),
        bgcolor=GREY, padding=ft.Padding(8, 6, 8, 6), border_radius=16,
    )
    # Pan/zoom natif Flet (même widget que le viewer plein écran de
    # Dashboard.pyw) : zéro callback Python par frame, donc jamais saccadé.
    # Contenu par défaut de `viewer_image_wrap` ; remplacé par le cadre de
    # recadrage (`crop_frame_holder`) pendant l'édition (cf. tiroir Recadrer).
    viewer_interactive = ft.InteractiveViewer(
        content=viewer_img, min_scale=1.0, max_scale=6.0,
        pan_enabled=True, scale_enabled=True, constrained=True)

    # Conteneurs positionnés nommés (pas `expand=True`) pour pouvoir réduire
    # dynamiquement `right` quand un tiroir est ouvert — évite qu'il ne
    # masque une partie de l'image (retour utilisateur).
    viewer_image_wrap = ft.Container(content=viewer_interactive, bgcolor=DARK,
                                     alignment=ft.Alignment.CENTER,
                                     left=0, top=0, bottom=0, right=0)
    viewer_top_bar_wrap = ft.Container(content=viewer_top_bar, top=8, left=8,
                                       right=8)
    viewer_bottom_bar_wrap = ft.Container(content=viewer_bottom_bar,
                                          bottom=16, left=0, right=0,
                                          alignment=ft.Alignment.CENTER)
    viewer_overlay = ft.Stack([
        viewer_image_wrap, viewer_top_bar_wrap, viewer_bottom_bar_wrap,
    ], expand=True)

    def _set_drawer_space(width):
        viewer_image_wrap.right = width
        viewer_top_bar_wrap.right = 8 + width
        viewer_bottom_bar_wrap.right = width

    def _derived_path(path, suffix):
        """Chemin d'un fichier dérivé (retouche/recadrage) : sous-dossier
        `_DERIVES/` à côté de l'original, jamais d'écrasement (HUB_SPEC §7)."""
        folder = os.path.join(os.path.dirname(path), "_DERIVES")
        os.makedirs(folder, exist_ok=True)
        base = os.path.splitext(os.path.basename(path))[0]
        return _unique_dest(folder, f"{base}{suffix}.jpg")

    # ═════════════════════════════════════════════════════════════════════
    #  Tiroir Retoucher — exposition/contraste/saturation/teinte/balance des
    #  blancs/ombres/hautes lumières (HUB_SPEC §6). Délègue à image_ops.py
    #  (même logique que Recadrage manuel.pyw, sans duplication).
    # ═════════════════════════════════════════════════════════════════════
    retouch_state = {"path": None, "preview_image": None, "exposure": 0.0,
                     "contrast": 0.0, "saturation": 0.0, "hue": 0.0,
                     "white_balance": 0.0, "shadows": 0.0, "highlights": 0.0}
    _RETOUCH_KEYS = ("exposure", "contrast", "saturation", "hue",
                     "white_balance", "shadows", "highlights")
    retouch_sliders = {}
    retouch_labels = {}

    def _retouch_apply(image):
        result = image_ops.apply_adjustments(
            image, exposure=retouch_state["exposure"],
            contrast=retouch_state["contrast"],
            saturation=retouch_state["saturation"],
            hue=retouch_state["hue"],
            white_balance=retouch_state["white_balance"])
        if retouch_state["shadows"]:
            result = image_ops.apply_shadows(result, retouch_state["shadows"])
        if retouch_state["highlights"]:
            result = image_ops.apply_highlights(result, retouch_state["highlights"])
        return result

    def _retouch_load_preview():
        if retouch_state["preview_image"] is not None:
            return retouch_state["preview_image"]
        try:
            with PILImage.open(retouch_state["path"]) as im:
                im = im.convert("RGB")
                im.thumbnail((1024, 1024), PILImage.LANCZOS)
                retouch_state["preview_image"] = im.copy()
        except Exception:
            retouch_state["preview_image"] = None
        return retouch_state["preview_image"]

    def _retouch_render():
        base = _retouch_load_preview()
        if base is None:
            return
        buf = io.BytesIO()
        _retouch_apply(base).save(buf, "JPEG", quality=85)
        viewer_img.src = buf.getvalue()
        page.update()

    def _retouch_slider_change(key):
        def _on_change(e):
            retouch_labels[key].value = f"{int(e.control.value):+d}"
            page.update()
        return _on_change

    def _retouch_slider_end(key):
        def _on_change_end(e):
            retouch_state[key] = e.control.value
            _retouch_render()
        return _on_change_end

    def _retouch_reset(event=None):
        for key in _RETOUCH_KEYS:
            retouch_state[key] = 0.0
            retouch_sliders[key].value = 0.0
            retouch_labels[key].value = "+0"
        viewer_img.src = viewer_rotated_bytes.get(
            retouch_state["path"], retouch_state["path"])
        page.update()

    def _retouch_validate(event=None):
        path = retouch_state["path"]
        try:
            with PILImage.open(path) as im:
                icc = im.info.get("icc_profile")
                full = im.convert("RGB")
                result = _retouch_apply(full)
                result = image_ops.convert_to_srgb(result, icc)
                dest = _derived_path(path, "_retouche")
                result.save(dest, "JPEG", quality=100,
                            dpi=(CONSTANTS.DPI, CONSTANTS.DPI))
        except Exception as exc:
            _log_to_terminal(f"[ERREUR] Retouche : {exc}", RED)
            return
        _log_to_terminal(f"Retouche enregistrée : {dest}", GREEN)
        _toggle_retouch_drawer()

    def _retouch_slider_row(key, label, lo, hi):
        slider = ft.Slider(min=lo, max=hi, value=0, expand=True,
                           on_change=_retouch_slider_change(key),
                           on_change_end=_retouch_slider_end(key))
        value_label = ft.Text("+0", size=CONSTANTS.TEXT_XS, color=GREY,
                              width=34)
        retouch_sliders[key] = slider
        retouch_labels[key] = value_label
        return ft.Column([
            ft.Row([ft.Text(label, size=CONSTANTS.TEXT_SM, color=WHITE),
                   ft.Container(expand=True), value_label]),
            slider,
        ], spacing=0, tight=True)

    retouch_panel = ft.Container(
        bgcolor=GREY, border_radius=10, padding=12,
        content=ft.Column([
            ft.Text("Retoucher", size=CONSTANTS.TEXT_MD, color=WHITE,
                   weight=ft.FontWeight.W_600),
            _retouch_slider_row("exposure", "Exposition", -100, 100),
            _retouch_slider_row("contrast", "Contraste", -100, 100),
            _retouch_slider_row("saturation", "Saturation", -100, 100),
            _retouch_slider_row("hue", "Teinte", -180, 180),
            _retouch_slider_row("white_balance", "Balance des blancs",
                                -100, 100),
            _retouch_slider_row("shadows", "Ombres", -100, 100),
            _retouch_slider_row("highlights", "Hautes lumières", -100, 100),
            ft.Row([
                ft.TextButton("Réinitialiser", on_click=_retouch_reset),
                ft.Container(expand=True),
                ft.ElevatedButton("Valider", icon=ft.Icons.CHECK,
                                  on_click=_retouch_validate),
            ]),
        ], spacing=8, tight=True, scroll=ft.ScrollMode.AUTO),
    )
    retouch_drawer = ft.Container(
        content=retouch_panel, top=0, bottom=0, right=0, width=320,
        visible=False, padding=8)

    def _toggle_retouch_drawer(event=None):
        opening = not retouch_drawer.visible
        crop_drawer.visible = False
        ia_drawer.visible = False
        retouch_drawer.visible = opening
        _set_drawer_space(320 if opening else 0)
        viewer_image_wrap.content = viewer_interactive
        if opening:
            retouch_state["path"] = viewer_state["paths"][viewer_state["index"]]
            retouch_state["preview_image"] = None
            _retouch_reset()
            page.run_task(viewer_interactive.reset)
        else:
            viewer_img.src = viewer_rotated_bytes.get(
                viewer_state["paths"][viewer_state["index"]],
                viewer_state["paths"][viewer_state["index"]])
        page.update()

    # ═════════════════════════════════════════════════════════════════════
    #  Tiroir Recadrer — format verrouillé sur l'impression, orientation
    #  toujours dérivée de l'image, rotation fine (jamais de coin vide),
    #  grille des tiers. HUB_SPEC §7.
    #
    #  Pan/zoom natifs Flet (`ft.InteractiveViewer`, même widget que le
    #  viewer plein écran de Dashboard.pyw) : l'image est affichée via son
    #  chemin fichier direct (décodage natif Flutter, aucun aller-retour
    #  PIL par frame) et déplacée/zoomée côté client — fluide même sur de
    #  grandes photos. Python ne reconstruit le scale/offset qu'à partir des
    #  évènements `on_interaction_update` (throttlés à 200ms par Flet), pour
    #  calculer le recadrage final PIL uniquement au clic sur "Valider".
    # ═════════════════════════════════════════════════════════════════════
    _CROP_MAX_W, _CROP_MAX_H = 760.0, 680.0

    crop_state = {"path": None, "icc_profile": None,
                 "original_width": 0, "original_height": 0,
                 "format_key": "ID", "is_portrait": True,
                 "angle": 0.0, "canvas_w": _CROP_MAX_W, "canvas_h": _CROP_MAX_H,
                 "base_scale": 1.0}
    crop_iv_state = {"scale": 1.0, "gesture_base_scale": 1.0,
                     "offset_x": 0.0, "offset_y": 0.0}
    # Pairing pour la planche ID×4 10×20 (2 identités sur le même feuillet,
    # cf. image_ops.build_print_sheet) : la première photo recadrée est mise
    # en attente jusqu'à ce que la seconde soit validée.
    crop_id4_pending = {"image": None}

    def _crop_compute_canvas_dims():
        fmt_w, fmt_h = CONSTANTS.FORMATS[crop_state["format_key"]]
        ratio = (fmt_w / fmt_h) if crop_state["is_portrait"] else (fmt_h / fmt_w)
        h = _CROP_MAX_H
        w = h * ratio
        if w > _CROP_MAX_W:
            w = _CROP_MAX_W
            h = w / ratio
        return w, h

    def _crop_effective_base_scale(angle, cw, ch):
        """Scale de couverture + marge de sécurité pour l'angle courant
        (jamais de coin vide après redressement) — même formule que
        `image_ops.clamp_offsets`, réutilisée en sondant scale=1.0."""
        ow = crop_state["original_width"]
        oh = crop_state["original_height"]
        cover = max(cw / ow, ch / oh)
        probe = image_ops.CropView(
            canvas_w=cw, canvas_h=ch, base_scale=cover, offset_x=0.0,
            offset_y=0.0, scale=1.0, rotation=angle, original_width=ow,
            original_height=oh, display_w=ow * cover, display_h=oh * cover)
        inflation = image_ops.clamp_offsets(probe, is_fit_in=False).scale
        return cover * inflation

    def _crop_iv_start(e):
        crop_iv_state["gesture_base_scale"] = crop_iv_state["scale"]

    def _crop_iv_update(e):
        crop_iv_state["scale"] = crop_iv_state["gesture_base_scale"] * e.scale
        crop_iv_state["offset_x"] += e.focal_point_delta.x
        crop_iv_state["offset_y"] += e.focal_point_delta.y

    # Marge de sécurité anti-coin-vide calculée UNE FOIS pour l'angle
    # extrême de la plage (±15°, cf. crop_angle_slider) plutôt qu'à chaque
    # changement d'angle : `crop_image_ctrl` n'a donc jamais besoin d'être
    # redimensionné/recentré pendant qu'on tourne — seule la propriété
    # `rotate` bouge, comme `image_container.rotate` dans
    # `PhotoCropper._update_transform` (Recadrage manuel.pyw). Reconstruire
    # le cadre à chaque degré (ancienne version) forçait un reset du zoom :
    # saccadé et frustrant si on était déjà zoomé.
    _CROP_MAX_ANGLE = 15.0
    _crop_last_rotation_render = {"t": 0.0}

    def _crop_rebuild_frame():
        if not crop_state["path"]:
            return
        cw, ch = _crop_compute_canvas_dims()
        crop_state["canvas_w"], crop_state["canvas_h"] = cw, ch
        base_scale = _crop_effective_base_scale(_CROP_MAX_ANGLE, cw, ch)
        crop_state["base_scale"] = base_scale
        ow, oh = crop_state["original_width"], crop_state["original_height"]
        crop_image_ctrl.src = crop_state["path"]
        crop_image_ctrl.width = ow * base_scale
        crop_image_ctrl.height = oh * base_scale
        crop_rotate_wrap.rotate = math.radians(crop_state["angle"])
        crop_frame_box.width = cw
        crop_frame_box.height = ch
        crop_iv.width = cw
        crop_iv.height = ch
        crop_grid_v1.left, crop_grid_v1.top, crop_grid_v1.height = cw / 3, 0, ch
        crop_grid_v2.left, crop_grid_v2.top, crop_grid_v2.height = 2 * cw / 3, 0, ch
        crop_grid_h1.left, crop_grid_h1.top, crop_grid_h1.width = 0, ch / 3, cw
        crop_grid_h2.left, crop_grid_h2.top, crop_grid_h2.width = 0, 2 * ch / 3, cw
        for line in crop_grid_lines:
            line.visible = crop_grid_toggle.value
        crop_iv_state.update(scale=1.0, gesture_base_scale=1.0,
                             offset_x=0.0, offset_y=0.0)
        page.update()
        page.run_task(crop_iv.reset)

    def _crop_load(path):
        try:
            with PILImage.open(path) as im:
                crop_state["icc_profile"] = im.info.get("icc_profile")
                w, h = im.size
        except Exception:
            crop_state["path"] = None
            return
        crop_state["path"] = path
        crop_state["original_width"] = w
        crop_state["original_height"] = h
        crop_state["is_portrait"] = h >= w  # dérivée de l'image au chargement
        crop_state["angle"] = 0.0
        crop_angle_slider.value = 0.0
        crop_angle_label.value = "+0.0°"

    def _crop_format_change(e):
        crop_state["format_key"] = e.control.value
        crop_id_row.visible = crop_state["format_key"] == "ID"
        _crop_rebuild_frame()

    def _crop_orientation_toggle(event=None):
        # Bouton "à la volée" : bascule manuellement l'orientation détectée
        # automatiquement au chargement (retour utilisateur — le bouton
        # avait disparu quand l'orientation est devenue 100% automatique).
        crop_state["is_portrait"] = not crop_state["is_portrait"]
        _crop_rebuild_frame()

    def _crop_id_segment_change(e):
        crop_10x20_toggle.visible = crop_id_segmented.selected_index == 2
        page.update()

    def _crop_grid_toggle_change(e):
        for line in crop_grid_lines:
            line.visible = e.control.value
        page.update()

    def _crop_angle_apply(angle):
        crop_state["angle"] = angle
        crop_angle_label.value = f"{angle:+.1f}°"
        crop_rotate_wrap.rotate = math.radians(angle)

    def _crop_angle_change(e):
        # Rotation fluide et continue (comme le slider de rotation de
        # Recadrage manuel.pyw) : seule la propriété `rotate` change, le
        # zoom/pan en cours n'est jamais perturbé. Throttle 30fps pour ne
        # pas saturer la file de messages Flet pendant le glisser.
        now = time.monotonic()
        if now - _crop_last_rotation_render["t"] < 1 / 30:
            return
        _crop_last_rotation_render["t"] = now
        _crop_angle_apply(max(-15.0, min(15.0, e.control.value)))
        crop_rotate_wrap.update()

    def _crop_angle_end(e):
        _crop_angle_apply(max(-15.0, min(15.0, e.control.value)))
        page.update()

    def _crop_current_layout():
        if crop_state["format_key"] != "ID":
            return "aucune"
        idx = crop_id_segmented.selected_index
        if idx == 1:
            return "id2"
        if idx == 2:
            return "id4_10x20" if crop_10x20_toggle.value else "id4"
        return "aucune"

    def _crop_validate(event=None):
        if not crop_state["path"]:
            return
        try:
            with PILImage.open(crop_state["path"]) as full_im:
                full_img = full_im.convert("RGB")
        except Exception as exc:
            _log_to_terminal(f"[ERREUR] Recadrage : {exc}", RED)
            return
        view = image_ops.CropView(
            canvas_w=crop_state["canvas_w"], canvas_h=crop_state["canvas_h"],
            base_scale=crop_state["base_scale"],
            offset_x=crop_iv_state["offset_x"],
            offset_y=crop_iv_state["offset_y"], scale=crop_iv_state["scale"],
            rotation=crop_state["angle"],
            original_width=crop_state["original_width"],
            original_height=crop_state["original_height"],
            display_w=crop_state["original_width"] * crop_state["base_scale"],
            display_h=crop_state["original_height"] * crop_state["base_scale"],
        )
        clamped = image_ops.clamp_offsets(view, is_fit_in=False)
        fmt_w, fmt_h = CONSTANTS.FORMATS[crop_state["format_key"]]
        cropped = image_ops.compute_crop_for_format(
            full_img, fmt_w, fmt_h, crop_state["is_portrait"], clamped,
            dpi=CONSTANTS.DPI)

        layout = _crop_current_layout()
        result = cropped
        dest_suffix = "_recadre"
        if layout == "id4_10x20":
            if crop_id4_pending["image"] is None:
                crop_id4_pending["image"] = cropped
                _log_to_terminal(
                    "Identité en attente de sa paire pour la planche "
                    "10×20 — recadrez la photo suivante.", ORANGE)
                _toggle_crop_drawer()
                return
            result = image_ops.build_print_sheet(
                cropped, "id4_10x20", dpi=CONSTANTS.DPI,
                previous_image=crop_id4_pending["image"])
            crop_id4_pending["image"] = None
            dest_suffix = "_planche_10x20"
        elif layout != "aucune":
            result = image_ops.build_print_sheet(cropped, layout,
                                                 dpi=CONSTANTS.DPI)
            dest_suffix = f"_{layout}"

        result = image_ops.convert_to_srgb(result, crop_state["icc_profile"])
        try:
            dest = _derived_path(crop_state["path"], dest_suffix)
            result.save(dest, "JPEG", quality=100,
                        dpi=(CONSTANTS.DPI, CONSTANTS.DPI))
        except Exception as exc:
            _log_to_terminal(f"[ERREUR] Recadrage : {exc}", RED)
            return
        _log_to_terminal(f"Recadrage enregistré : {dest}", GREEN)
        _toggle_crop_drawer()

    crop_format_dd = ft.Dropdown(
        options=[ft.dropdown.Option(name) for name in CONSTANTS.FORMATS],
        value="ID", width=280, bgcolor=DARK, border_color=LIGHT_GREY,
        color=WHITE, on_select=_crop_format_change)
    crop_id_segmented = ft.CupertinoSlidingSegmentedButton(
        selected_index=2,
        controls=[ft.Text("ID"), ft.Text("ID ×2"), ft.Text("ID ×4")],
        on_change=_crop_id_segment_change)
    crop_10x20_toggle = ft.Switch(label="Planche 10×20", value=True,
                                  visible=True)
    crop_id_row = ft.Column([crop_id_segmented, crop_10x20_toggle],
                            spacing=6, tight=True, visible=True)
    crop_grid_toggle = ft.Switch(label="Grille des tiers", value=True,
                                 on_change=_crop_grid_toggle_change)
    crop_angle_label = ft.Text("+0.0°", size=CONSTANTS.TEXT_XS, color=GREY)
    crop_angle_slider = ft.Slider(min=-15, max=15, value=0,
                                  on_change=_crop_angle_change,
                                  on_change_end=_crop_angle_end)
    crop_panel = ft.Container(
        bgcolor=GREY, border_radius=10, padding=12,
        content=ft.Column([
            ft.Row([
                ft.Text("Recadrer", size=CONSTANTS.TEXT_MD, color=WHITE,
                       weight=ft.FontWeight.W_600),
                ft.Container(expand=True),
                ft.IconButton(ft.Icons.SCREEN_ROTATION, icon_color=WHITE,
                             tooltip="Changer l'orientation",
                             on_click=_crop_orientation_toggle),
            ]),
            crop_format_dd,
            crop_id_row,
            crop_grid_toggle,
            ft.Row([ft.Text("Rotation fine", size=CONSTANTS.TEXT_SM,
                            color=WHITE),
                   ft.Container(expand=True), crop_angle_label]),
            crop_angle_slider,
            ft.Row([
                ft.TextButton("Annuler", on_click=lambda e: _toggle_crop_drawer()),
                ft.Container(expand=True),
                ft.ElevatedButton("Valider", icon=ft.Icons.CHECK,
                                  on_click=_crop_validate),
            ]),
        ], spacing=10, tight=True, scroll=ft.ScrollMode.AUTO),
    )
    crop_drawer = ft.Container(content=crop_panel, top=0, bottom=0, right=0,
                               width=320, visible=False, padding=8)

    # Cadre de recadrage : ft.InteractiveViewer natif (comme le viewer
    # plein écran de Dashboard.pyw) affiché à la place de `viewer_img`
    # pendant l'édition — pan/zoom gérés côté Flutter, zéro recalcul PIL
    # par frame. `constrained=False` + `boundary_margin=0` empêchent
    # nativement tout coin vide en translation ; l'inflation de
    # `base_scale` (cf. `_crop_effective_base_scale`) couvre la rotation.
    crop_image_ctrl = ft.Image(src=_BLANK_GIF, fit=ft.BoxFit.FILL,
                               gapless_playback=True)
    crop_rotate_wrap = ft.Container(content=crop_image_ctrl, rotate=0.0)
    crop_iv = ft.InteractiveViewer(
        content=crop_rotate_wrap, min_scale=1.0, max_scale=6.0,
        pan_enabled=True, scale_enabled=True, constrained=False,
        boundary_margin=ft.Margin.all(0),
        clip_behavior=ft.ClipBehavior.HARD_EDGE,
        on_interaction_start=_crop_iv_start,
        on_interaction_update=_crop_iv_update,
    )
    _crop_grid_color = ft.Colors.with_opacity(0.5, WHITE)
    crop_grid_v1 = ft.Container(bgcolor=_crop_grid_color, width=1)
    crop_grid_v2 = ft.Container(bgcolor=_crop_grid_color, width=1)
    crop_grid_h1 = ft.Container(bgcolor=_crop_grid_color, height=1)
    crop_grid_h2 = ft.Container(bgcolor=_crop_grid_color, height=1)
    crop_grid_lines = [crop_grid_v1, crop_grid_v2, crop_grid_h1, crop_grid_h2]
    crop_frame_box = ft.Container(
        bgcolor=DARK, clip_behavior=ft.ClipBehavior.HARD_EDGE,
        content=ft.Stack([crop_iv, *crop_grid_lines]))
    crop_frame_holder = ft.Container(content=crop_frame_box,
                                     alignment=ft.Alignment.CENTER,
                                     expand=True)

    def _toggle_crop_drawer(event=None):
        opening = not crop_drawer.visible
        retouch_drawer.visible = False
        ia_drawer.visible = False
        crop_drawer.visible = opening
        _set_drawer_space(320 if opening else 0)
        if opening:
            _crop_load(viewer_state["paths"][viewer_state["index"]])
            crop_id_row.visible = crop_state["format_key"] == "ID"
            viewer_image_wrap.content = crop_frame_holder
            _crop_rebuild_frame()
        else:
            viewer_image_wrap.content = viewer_interactive
        page.update()

    # ═════════════════════════════════════════════════════════════════════
    #  Tiroir IA — retouche générative (inpainting), extension de cadre
    #  (outpainting) et amélioration (upscale local). HUB_SPEC §11/§14.
    #  Délègue à ai_ops.py ; les dépendances lourdes (torch/spandrel,
    #  google-genai) ne sont importées que dans les threads de traitement,
    #  jamais au démarrage de Hub.
    #
    #  Sélection de la zone à retoucher : glisser-déposer souris, même
    #  mécanisme qu'Augmentation IA.py — un canevas de référence de taille
    #  FIXE (`_IA_VIEW_W/H`, indépendant de la taille réelle du widget), un
    #  `ft.InteractiveViewer` pour le pan/zoom d'inspection, et un
    #  `ft.GestureDetector` superposé (armé par un bouton dédié) dont
    #  `on_pan_*` rapporte des positions dans l'espace *contenu* (avant
    #  transform de l'InteractiveViewer) — donc toujours cohérentes avec le
    #  mapping écran → pixels image (`_ia_compute_render_info`), qu'on soit
    #  zoomé ou non.
    # ═════════════════════════════════════════════════════════════════════
    _IA_VIEW_W, _IA_VIEW_H = 640.0, 560.0

    ia_state = {"path": None, "image": None, "preview_image": None,
               "icc_profile": None, "working": False, "mode": "inpaint",
               "selection": None, "drag_start": None, "drag_current": None,
               "sel_mode": False, "render_info": None,
               "margin_top": 0.0, "margin_bottom": 0.0, "margin_left": 0.0,
               "margin_right": 0.0, "margin_touched": False}

    def _ia_compute_render_info():
        img = ia_state["image"]
        if img is None:
            ia_state["render_info"] = None
            return
        ow, oh = img.size
        s = min(_IA_VIEW_W / ow, _IA_VIEW_H / oh)
        tw, th = ow * s, oh * s
        ox, oy = (_IA_VIEW_W - tw) / 2, (_IA_VIEW_H - th) / 2
        ia_state["render_info"] = (ox, oy, s)

    def _ia_display_to_image(cx, cy):
        info = ia_state["render_info"]
        if info is None:
            return None, None
        ox, oy, s = info
        img = ia_state["image"]
        ix = max(0, min(round((cx - ox) / s), img.width - 1))
        iy = max(0, min(round((cy - oy) / s), img.height - 1))
        return ix, iy

    def _ia_image_to_display(ix, iy):
        info = ia_state["render_info"]
        if info is None:
            return 0.0, 0.0
        ox, oy, s = info
        return ix * s + ox, iy * s + oy

    def _ia_update_sel_canvas():
        ia_sel_canvas.shapes.clear()
        rect = None
        if ia_state["drag_start"] is not None and ia_state["drag_current"] is not None:
            (x1, y1), (x2, y2) = ia_state["drag_start"], ia_state["drag_current"]
            rect = (min(x1, x2), min(y1, y2), max(x1, x2), max(y1, y2))
        elif ia_state["selection"] is not None:
            dx1, dy1 = _ia_image_to_display(*ia_state["selection"][:2])
            dx2, dy2 = _ia_image_to_display(*ia_state["selection"][2:])
            rect = (dx1, dy1, dx2, dy2)
        if rect is not None:
            x1, y1, x2, y2 = rect
            if x2 > x1 and y2 > y1:
                ia_sel_canvas.shapes.append(ftcv.Rect(
                    x=x1, y=y1, width=x2 - x1, height=y2 - y1,
                    paint=ft.Paint(color=ft.Colors.with_opacity(0.18, RED),
                                   style=ft.PaintingStyle.FILL)))
                ia_sel_canvas.shapes.append(ftcv.Rect(
                    x=x1, y=y1, width=x2 - x1, height=y2 - y1,
                    paint=ft.Paint(color=RED, style=ft.PaintingStyle.STROKE,
                                   stroke_width=2.0)))
        ia_sel_canvas.update()

    def _ia_disarm_selection():
        ia_state["sel_mode"] = False
        ia_select_btn.text = "Sélectionner une zone"
        ia_select_btn.icon = ft.Icons.CROP
        ia_select_btn.bgcolor = GREY
        ia_gesture.visible = False
        ia_iv.pan_enabled = True

    def _ia_toggle_select(event=None):
        ia_state["sel_mode"] = not ia_state["sel_mode"]
        if ia_state["sel_mode"]:
            ia_select_btn.text = "Annuler la sélection"
            ia_select_btn.icon = ft.Icons.CROP_FREE
            ia_select_btn.bgcolor = BLUE
            ia_gesture.visible = True
            ia_iv.pan_enabled = False
        else:
            _ia_disarm_selection()
            ia_state["drag_start"] = None
            ia_state["drag_current"] = None
            _ia_update_sel_canvas()
        page.update()

    def _ia_on_pan_start(e):
        if not ia_state["sel_mode"]:
            return
        ia_state["drag_start"] = (e.local_position.x, e.local_position.y)
        ia_state["drag_current"] = ia_state["drag_start"]

    def _ia_on_pan_update(e):
        if not ia_state["sel_mode"] or ia_state["drag_start"] is None:
            return
        ia_state["drag_current"] = (e.local_position.x, e.local_position.y)
        _ia_update_sel_canvas()

    def _ia_on_pan_end(e):
        if not ia_state["sel_mode"] or ia_state["drag_start"] is None:
            return
        (x1d, y1d), (x2d, y2d) = ia_state["drag_start"], ia_state["drag_current"]
        ia_state["drag_start"] = None
        ia_state["drag_current"] = None
        ix1, iy1 = _ia_display_to_image(min(x1d, x2d), min(y1d, y2d))
        ix2, iy2 = _ia_display_to_image(max(x1d, x2d), max(y1d, y2d))
        if ix1 is not None and (ix2 - ix1) > 8 and (iy2 - iy1) > 8:
            ia_state["selection"] = (ix1, iy1, ix2, iy2)
            ia_send_inpaint_btn.disabled = False
        else:
            ia_state["selection"] = None
            ia_send_inpaint_btn.disabled = True
        _ia_disarm_selection()
        _ia_update_sel_canvas()
        page.update()

    def _ia_load(path):
        try:
            with PILImage.open(path) as im:
                ia_state["icc_profile"] = im.info.get("icc_profile")
                im = im.convert("RGB")
                ia_state["image"] = im.copy()
                preview = im.copy()
                preview.thumbnail((900, 900), PILImage.LANCZOS)
                ia_state["preview_image"] = preview
        except Exception:
            ia_state["image"] = None
            ia_state["preview_image"] = None
            return
        ia_state["path"] = path
        ia_state["selection"] = None
        ia_send_inpaint_btn.disabled = True
        _ia_compute_render_info()
        ia_preview_img.src = path

    def _ia_render():
        """Aperçu PIL (extension de cadre uniquement — la retouche générative
        utilise le canevas de sélection natif, cf. `_ia_update_sel_canvas`)."""
        base = ia_state["preview_image"]
        if base is None:
            return
        overlay = base.copy()
        w, h = overlay.size
        if ia_state["mode"] == "outpaint" and ia_state["margin_touched"]:
            mt = round(h * ia_state["margin_top"] / 100)
            mb = round(h * ia_state["margin_bottom"] / 100)
            ml = round(w * ia_state["margin_left"] / 100)
            mr = round(w * ia_state["margin_right"] / 100)
            padded = PILImage.new("RGB", (w + ml + mr, h + mt + mb), (60, 60, 60))
            padded.paste(overlay, (ml, mt))
            overlay = padded
        buf = io.BytesIO()
        overlay.convert("RGB").save(buf, "JPEG", quality=85)
        viewer_img.src = buf.getvalue()
        page.update()

    def _ia_set_mode(mode):
        def _on_click(e):
            ia_state["mode"] = mode
            ia_inpaint_section.visible = mode == "inpaint"
            ia_outpaint_section.visible = mode == "outpaint"
            ia_upscale_section.visible = mode == "upscale"
            if mode == "inpaint":
                viewer_image_wrap.content = ia_frame_holder
                page.run_task(ia_iv.reset)
            else:
                viewer_image_wrap.content = viewer_interactive
                if mode == "outpaint":
                    _ia_render()
                else:
                    viewer_img.src = viewer_rotated_bytes.get(
                        viewer_state["paths"][viewer_state["index"]],
                        viewer_state["paths"][viewer_state["index"]])
            page.update()
        return _on_click

    def _ia_margin_slider(key):
        def _on_end(e):
            ia_state[key] = e.control.value
            ia_state["margin_touched"] = True
            _ia_render()
        return _on_end

    def _ia_working_ui(working, message):
        ia_state["working"] = working
        ia_progress.visible = working
        ia_status_text.value = message
        ia_send_inpaint_btn.disabled = working
        ia_send_outpaint_btn.disabled = working
        ia_run_upscale_btn.disabled = working
        page.update()

    def _ia_send_inpaint(event=None):
        if ia_state["working"] or ia_state["image"] is None:
            return
        if ia_state["selection"] is None:
            _ia_working_ui(False, "Dessinez une sélection sur l'image.")
            return
        prompt = (ia_prompt_field.value or "").strip()
        if not prompt:
            _ia_working_ui(False, "Décrivez la retouche souhaitée.")
            return
        img = ia_state["image"]
        rect = ia_state["selection"]
        path = ia_state["path"]
        icc = ia_state["icc_profile"]
        _ia_working_ui(True, "Envoi à Gemini… (jusqu'à 2 min)")

        def _run():
            try:
                result = ai_ops.run_inpaint(img, rect, prompt)
                result = image_ops.convert_to_srgb(result, icc)
                dest = _derived_path(path, "_retouche_ia")
                result.save(dest, "JPEG", quality=100,
                            dpi=(CONSTANTS.DPI, CONSTANTS.DPI))
            except Exception as exc:
                _ia_working_ui(False, f"[ERREUR] {exc}")
                return
            _ia_working_ui(False, f"Enregistré : {os.path.basename(dest)}")
            _log_to_terminal(f"Retouche IA enregistrée : {dest}", GREEN)

        threading.Thread(target=_run, daemon=True).start()

    def _ia_send_outpaint(event=None):
        if ia_state["working"] or ia_state["image"] is None:
            return
        img = ia_state["image"]
        w, h = img.size
        margins = (round(h * ia_state["margin_top"] / 100),
                  round(h * ia_state["margin_bottom"] / 100),
                  round(w * ia_state["margin_left"] / 100),
                  round(w * ia_state["margin_right"] / 100))
        if sum(margins) == 0:
            _ia_working_ui(False, "Glissez les marges pour définir l'extension.")
            return
        path = ia_state["path"]
        icc = ia_state["icc_profile"]
        _ia_working_ui(True, "Extension… (jusqu'à 5 min)")

        def _run():
            try:
                result = ai_ops.run_outpaint(img, margins)
                result = image_ops.convert_to_srgb(result, icc)
                dest = _derived_path(path, "_extension_ia")
                result.save(dest, "JPEG", quality=100,
                            dpi=(CONSTANTS.DPI, CONSTANTS.DPI))
            except Exception as exc:
                _ia_working_ui(False, f"[ERREUR] {exc}")
                return
            _ia_working_ui(False, f"Enregistré : {os.path.basename(dest)}")
            _log_to_terminal(f"Extension IA enregistrée : {dest}", GREEN)

        threading.Thread(target=_run, daemon=True).start()

    def _ia_run_upscale(event=None):
        if ia_state["working"] or ia_state["image"] is None:
            return
        model_name = ia_model_dd.value
        if not model_name:
            _ia_working_ui(False, "Sélectionnez un modèle.")
            return
        img = ia_state["image"]
        path = ia_state["path"]
        icc = ia_state["icc_profile"]
        _ia_working_ui(True, f"Chargement de {model_name}…")

        def _progress(value, label):
            ia_progress.value = value
            if label:
                ia_status_text.value = label
            page.update()

        def _run():
            try:
                result = ai_ops.run_upscale(img, model_name, _progress)
                result = image_ops.convert_to_srgb(result, icc)
                dest = _derived_path(path, "_upscale")
                result.save(dest, "JPEG", quality=100,
                            dpi=(CONSTANTS.DPI, CONSTANTS.DPI))
            except Exception as exc:
                _ia_working_ui(False, f"[ERREUR] {exc}")
                return
            ia_progress.value = None
            _ia_working_ui(False, f"Enregistré : {os.path.basename(dest)}")
            _log_to_terminal(f"Amélioration IA enregistrée : {dest}", GREEN)

        threading.Thread(target=_run, daemon=True).start()

    # Cadre de sélection (mode Retouche) : InteractiveViewer natif pour
    # inspecter/zoomer + GestureDetector superposé pour le glisser-déposer
    # de sélection, armé par `ia_select_btn` — même mécanique que
    # `preview_viewer`/`image_gesture`/`inpaint_btn` dans Augmentation IA.py.
    ia_preview_img = ft.Image(src=_BLANK_GIF, width=_IA_VIEW_W,
                              height=_IA_VIEW_H, fit=ft.BoxFit.CONTAIN,
                              gapless_playback=True)
    ia_sel_canvas = ftcv.Canvas(width=_IA_VIEW_W, height=_IA_VIEW_H, shapes=[])
    ia_gesture = ft.GestureDetector(
        content=ft.Container(width=_IA_VIEW_W, height=_IA_VIEW_H),
        on_pan_start=_ia_on_pan_start, on_pan_update=_ia_on_pan_update,
        on_pan_end=_ia_on_pan_end, mouse_cursor=ft.MouseCursor.PRECISE,
        visible=False)
    ia_inner_box = ft.Container(
        width=_IA_VIEW_W, height=_IA_VIEW_H, bgcolor=DARK,
        content=ft.Stack([ia_preview_img, ia_sel_canvas, ia_gesture]))
    ia_iv = ft.InteractiveViewer(content=ia_inner_box, pan_enabled=True,
                                 scale_enabled=True, min_scale=0.5,
                                 max_scale=6.0)
    ia_frame_holder = ft.Container(content=ia_iv, alignment=ft.Alignment.CENTER,
                                   expand=True)

    ia_prompt_field = ft.TextField(
        label="Décrivez la modification", multiline=True, min_lines=2,
        max_lines=4, bgcolor=DARK, border_color=LIGHT_GREY, color=WHITE)
    ia_status_text = ft.Text("", size=CONSTANTS.TEXT_XS, color=GREY)
    ia_progress = ft.ProgressBar(color=BLUE, bgcolor=GREY, visible=False)
    ia_select_btn = ft.Button(
        "Sélectionner une zone", icon=ft.Icons.CROP, bgcolor=GREY,
        color=WHITE, on_click=_ia_toggle_select)
    ia_send_inpaint_btn = ft.ElevatedButton(
        "Envoyer à Gemini", icon=ft.Icons.AUTO_FIX_HIGH, disabled=True,
        on_click=_ia_send_inpaint)
    ia_inpaint_section = ft.Column([
        ft.Text("Glissez sur l'image pour définir la zone à retoucher",
               size=CONSTANTS.TEXT_SM, color=WHITE),
        ia_select_btn,
        ia_prompt_field,
        ia_send_inpaint_btn,
    ], spacing=8, tight=True, visible=True)

    ia_send_outpaint_btn = ft.ElevatedButton(
        "Étendre via Gemini", icon=ft.Icons.PHOTO_SIZE_SELECT_LARGE,
        on_click=_ia_send_outpaint)
    ia_outpaint_section = ft.Column([
        ft.Text("Marges à ajouter (% de l'image)", size=CONSTANTS.TEXT_SM,
               color=WHITE),
        ft.Text("Haut", size=CONSTANTS.TEXT_XS, color=GREY),
        ft.Slider(min=0, max=50, value=0, on_change_end=_ia_margin_slider("margin_top")),
        ft.Text("Bas", size=CONSTANTS.TEXT_XS, color=GREY),
        ft.Slider(min=0, max=50, value=0, on_change_end=_ia_margin_slider("margin_bottom")),
        ft.Text("Gauche", size=CONSTANTS.TEXT_XS, color=GREY),
        ft.Slider(min=0, max=50, value=0, on_change_end=_ia_margin_slider("margin_left")),
        ft.Text("Droite", size=CONSTANTS.TEXT_XS, color=GREY),
        ft.Slider(min=0, max=50, value=0, on_change_end=_ia_margin_slider("margin_right")),
        ia_send_outpaint_btn,
    ], spacing=4, tight=True, visible=False)

    ia_model_dd = ft.Dropdown(
        options=[ft.dropdown.Option(name) for name in ai_ops.list_pth_models()],
        width=280, bgcolor=DARK, border_color=LIGHT_GREY, color=WHITE)
    ia_run_upscale_btn = ft.ElevatedButton(
        "Lancer", icon=ft.Icons.HIGH_QUALITY, on_click=_ia_run_upscale)
    ia_upscale_section = ft.Column([
        ft.Text("Modèle local (Data/models/)", size=CONSTANTS.TEXT_SM,
               color=WHITE),
        ia_model_dd,
        ia_run_upscale_btn,
    ], spacing=4, tight=True, visible=False)

    ia_panel = ft.Container(
        bgcolor=GREY, border_radius=10, padding=12,
        content=ft.Column([
            ft.Text("IA", size=CONSTANTS.TEXT_MD, color=WHITE,
                   weight=ft.FontWeight.W_600),
            ft.Row([
                ft.TextButton("Retouche", on_click=_ia_set_mode("inpaint")),
                ft.TextButton("Extension", on_click=_ia_set_mode("outpaint")),
                ft.TextButton("Amélioration", on_click=_ia_set_mode("upscale")),
            ], spacing=2, tight=True),
            ia_inpaint_section, ia_outpaint_section, ia_upscale_section,
            ia_progress, ia_status_text,
            ft.TextButton("Fermer", on_click=lambda e: _toggle_ia_drawer()),
        ], spacing=8, tight=True, scroll=ft.ScrollMode.AUTO),
    )
    ia_drawer = ft.Container(content=ia_panel, top=0, bottom=0, right=0,
                             width=320, visible=False, padding=8)

    def _toggle_ia_drawer(event=None):
        opening = not ia_drawer.visible
        retouch_drawer.visible = False
        crop_drawer.visible = False
        ia_drawer.visible = opening
        _set_drawer_space(320 if opening else 0)
        if opening:
            _ia_load(viewer_state["paths"][viewer_state["index"]])
            ia_state["mode"] = "inpaint"
            ia_state["margin_touched"] = False
            _ia_disarm_selection()
            ia_state["drag_start"] = None
            ia_state["drag_current"] = None
            # Pas d'appel à `_ia_update_sel_canvas()` ici : `ia_sel_canvas`
            # n'est pas encore monté sur la page tant que
            # `viewer_image_wrap.content` n'a pas été assigné + `page.update()`
            # appelé plus bas (sinon Flet lève "Control must be added to the
            # page first"). On vide juste le modèle ; le rendu suivra le
            # `page.update()` de fin de fonction.
            ia_sel_canvas.shapes.clear()
            ia_inpaint_section.visible = True
            ia_outpaint_section.visible = False
            ia_upscale_section.visible = False
            ia_status_text.value = ""
            viewer_image_wrap.content = ia_frame_holder
            page.run_task(ia_iv.reset)
        else:
            viewer_image_wrap.content = viewer_interactive
            viewer_img.src = viewer_rotated_bytes.get(
                viewer_state["paths"][viewer_state["index"]],
                viewer_state["paths"][viewer_state["index"]])
        page.update()

    def _close_drawers():
        retouch_drawer.visible = False
        crop_drawer.visible = False
        ia_drawer.visible = False
        _set_drawer_space(0)
        viewer_image_wrap.content = viewer_interactive

    viewer_overlay.controls.extend([retouch_drawer, crop_drawer, ia_drawer])
    viewer_bottom_bar.content.controls.insert(
        -1, _viewer_btn(ft.Icons.TUNE, "Retoucher", _toggle_retouch_drawer))
    viewer_bottom_bar.content.controls.insert(
        -1, _viewer_btn(ft.Icons.CROP, "Recadrer", _toggle_crop_drawer))
    viewer_bottom_bar.content.controls.insert(
        -1, _viewer_btn(ft.Icons.AUTO_AWESOME, "IA", _toggle_ia_drawer))

    def _open_viewer(start_path):
        paths = content["imgs"] if start_path in content["imgs"] else [start_path]
        viewer_state["paths"] = paths
        viewer_state["index"] = paths.index(start_path)
        _close_drawers()
        _update_viewer()
        if viewer_overlay not in page.overlay:
            page.overlay.append(viewer_overlay)
        _prev_keyboard["fn"] = page.on_keyboard_event
        page.on_keyboard_event = _viewer_on_key
        page.update()

    # ═════════════════════════════════════════════════════════════════════
    #  Menu "Ouvrir ▾" — favoris + récents + parcourir, tout au même endroit
    #  (spec §5). Overlay maison (mêmes primitives que la visionneuse) plutôt
    #  qu'un PopupMenuButton : évite l'incertitude d'un IconButton imbriqué
    #  dans un item de menu natif.
    # ═════════════════════════════════════════════════════════════════════
    def _menu_section_label(text):
        return ft.Container(
            content=ft.Text(text.upper(), size=CONSTANTS.TEXT_XS, color=GREY,
                            weight=ft.FontWeight.BOLD),
            padding=ft.Padding(10, 6, 10, 2))

    def _open_from_menu(path):
        _close_open_menu()
        _navigate(path)

    def _fav_row(fav):
        path = fav["path"]
        name = fav["label"] or os.path.basename(path) or path
        return ft.ListTile(
            leading=ft.Icon(ft.Icons.STAR, color=YELLOW, size=CONSTANTS.ICON_SM),
            title=ft.Text(name, size=CONSTANTS.TEXT_SM, color=WHITE, no_wrap=True),
            trailing=ft.IconButton(
                ft.Icons.CLOSE, icon_color=RED, icon_size=16,
                tooltip="Retirer des favoris",
                on_click=lambda e, p=path: _remove_favorite(p)),
            on_click=lambda e, p=path: _open_from_menu(p),
            hover_color=GREY, dense=True,
            content_padding=ft.Padding(left=10, top=0, right=4, bottom=0),
        )

    def _recent_row(path):
        return ft.ListTile(
            leading=ft.Icon(ft.Icons.HISTORY, color=WHITE, size=CONSTANTS.ICON_SM),
            title=ft.Text(os.path.basename(path) or path, size=CONSTANTS.TEXT_SM,
                          color=WHITE, no_wrap=True),
            on_click=lambda e, p=path: _open_from_menu(p),
            hover_color=GREY, dense=True,
            content_padding=ft.Padding(left=10, top=0, right=8, bottom=0),
        )

    def _remove_favorite(path):
        favs = [f for f in _load_favorites() if f["path"] != path]
        _save_favorites(favs)
        _build_open_menu()   # rafraîchit sans fermer (retirer plusieurs d'affilée)
        page.update()

    def _add_favorite_current(event=None):
        path = state["folder"]
        if not path:
            return
        path = os.path.normpath(path)
        favs = _load_favorites()
        if not any(f["path"] == path for f in favs):
            favs.insert(0, {"path": path, "label": os.path.basename(path)})
            _save_favorites(favs)
        _close_open_menu()

    async def _browse_from_menu(event):
        _close_open_menu()
        await _pick_folder(event)

    _MENU_LANE_WIDTH = 214
    _MENU_LANE_HEIGHT = 340
    _FAV_COL_ITEMS = 8   # au-delà, une nouvelle colonne apparaît (défilement horizontal)
    _FAV_VISIBLE_COLS = 3   # colonnes de favoris visibles sans défiler
    _FAV_LANE_WIDTH = _MENU_LANE_WIDTH * _FAV_VISIBLE_COLS + 6 * (_FAV_VISIBLE_COLS - 1)

    def _chunked(seq, n):
        return [seq[i:i + n] for i in range(0, len(seq), n)]

    def _build_open_menu():
        favs = _load_favorites()
        recents = _load_recent()

        recent_items = [_recent_row(p) for p in recents[:12]] or [
            ft.Container(content=ft.Text("Aucun dossier récent",
                                         size=CONSTANTS.TEXT_SM, color=GREY),
                        padding=ft.Padding(10, 8, 10, 8))]
        recent_lane = ft.Container(
            width=_MENU_LANE_WIDTH, height=_MENU_LANE_HEIGHT,
            content=ft.Column([
                _menu_section_label("Récents"),
                ft.Column(recent_items, spacing=0, scroll=ft.ScrollMode.AUTO,
                          expand=True),
            ], spacing=0, expand=True))

        if favs:
            fav_chunks = _chunked([_fav_row(f) for f in favs], _FAV_COL_ITEMS)
        else:
            fav_chunks = [[ft.Container(
                content=ft.Text("Aucun favori", size=CONSTANTS.TEXT_SM, color=GREY),
                padding=ft.Padding(10, 8, 10, 8))]]
        # Une colonne par tranche de _FAV_COL_ITEMS ; au-delà de la largeur
        # d'une colonne, on défile horizontalement pour voir les suivantes
        # (jamais de wrap= — cf. incident rendu de la surface Fichiers).
        fav_columns_row = ft.Row(
            [ft.Container(width=_MENU_LANE_WIDTH,
                         content=ft.Column(chunk, spacing=0))
             for chunk in fav_chunks],
            spacing=6, scroll=ft.ScrollMode.ALWAYS)
        fav_lane = ft.Container(
            width=_FAV_LANE_WIDTH, height=_MENU_LANE_HEIGHT,
            content=ft.Column([
                _menu_section_label("Favoris"),
                fav_columns_row,
            ], spacing=0, expand=True))

        footer = ft.Row([
            ft.TextButton(
                content=ft.Row([
                    ft.Icon(ft.Icons.FOLDER_OPEN_OUTLINED, color=ICON_ACTION,
                            size=CONSTANTS.ICON_SM),
                    ft.Text("Parcourir…", size=CONSTANTS.TEXT_SM, color=WHITE),
                ], spacing=6, tight=True),
                on_click=_browse_from_menu),
            ft.Container(expand=True),
            ft.TextButton(
                content=ft.Row([
                    ft.Icon(ft.Icons.STAR_OUTLINE, color=YELLOW, size=CONSTANTS.ICON_SM),
                    ft.Text("Ajouter ce dossier", size=CONSTANTS.TEXT_SM, color=WHITE),
                ], spacing=6, tight=True),
                on_click=_add_favorite_current, disabled=not state["folder"]),
        ])

        open_menu_panel.content = ft.Column([
            ft.Row([recent_lane, ft.VerticalDivider(width=1, color=DARK), fav_lane],
                  spacing=6, vertical_alignment=ft.CrossAxisAlignment.START),
            ft.Divider(height=1, color=DARK),
            footer,
        ], spacing=6, tight=True)

    open_menu_panel = ft.Container(
        bgcolor=GREY, border_radius=10, padding=ft.Padding(6, 6, 6, 6),
        content=ft.Column([], spacing=0),
    )
    open_menu_overlay = ft.Stack([
        ft.Container(expand=True, on_click=lambda e: _close_open_menu()),
        ft.Container(content=open_menu_panel, top=84, left=52),
    ], expand=True)

    def _close_open_menu(event=None):
        if open_menu_overlay in page.overlay:
            page.overlay.remove(open_menu_overlay)
            page.update()

    def _toggle_open_menu(event=None):
        if open_menu_overlay in page.overlay:
            _close_open_menu()
            return
        _build_open_menu()
        page.overlay.append(open_menu_overlay)
        page.update()

    def _go_to_parent_folder(event=None):
        folder = state["folder"]
        if not folder:
            return
        parent = os.path.dirname(folder)
        if parent and parent != folder:
            _navigate(parent)

    parent_folder_btn = ft.IconButton(
        icon=ft.Icons.ARROW_UPWARD,
        icon_color=ICON_ACTION, icon_size=CONSTANTS.ICON_SM,
        style=ft.ButtonStyle(bgcolor=GREY),
        on_click=_go_to_parent_folder,
        tooltip="Dossier parent",
    )

    def _refresh_folder(event=None):
        if state["folder"]:
            _navigate(state["folder"])

    refresh_folder_btn = ft.IconButton(
        icon=ft.Icons.REFRESH,
        icon_color=ICON_ACTION, icon_size=CONSTANTS.ICON_SM,
        style=ft.ButtonStyle(bgcolor=GREY),
        on_click=_refresh_folder,
        tooltip="Rafraîchir",
    )

    open_menu_btn = ft.TextButton(
        content=ft.Row([
            ft.Icon(ft.Icons.FOLDER_OPEN_OUTLINED, color=ICON_ACTION,
                    size=CONSTANTS.ICON_SM),
            ft.Text("Ouvrir", size=CONSTANTS.TEXT_SM, color=WHITE),
            ft.Icon(ft.Icons.ARROW_DROP_DOWN, color=WHITE, size=CONSTANTS.ICON_SM),
        ], spacing=4, tight=True),
        style=ft.ButtonStyle(bgcolor=GREY),
        on_click=_toggle_open_menu,
        tooltip="Favoris, récents, parcourir…",
    )

    order_mode_btn = ft.TextButton(
        content=ft.Row([
            ft.Icon(ft.Icons.RECEIPT_LONG_OUTLINED, size=CONSTANTS.ICON_SM),
            ft.Text("Mode commande", size=CONSTANTS.TEXT_SM),
        ], spacing=4, tight=True),
        style=ft.ButtonStyle(bgcolor=GREY, color=WHITE),
        on_click=_toggle_order_mode,
        tooltip="Format + nombre directement sur chaque photo",
    )

    only_sel_btn = _seg_btn(ft.Icons.VISIBILITY_OUTLINED, "Afficher la sélection",
                            _toggle_only_selected)

    # _create_order_folder est défini plus loin (avec le reste de la logique
    # de commande) : lambda pour différer la résolution du nom jusqu'au clic.
    create_order_btn = ft.IconButton(
        ft.Icons.FOLDER_ZIP_OUTLINED, icon_color=BLUE, icon_size=18,
        tooltip="Créer le dossier de commande",
        on_click=lambda e: page.run_task(_create_order_folder, e))

    # _open_actions est défini plus loin dans main() (avec le dialogue
    # Actions) : lambda pour différer la résolution du nom jusqu'au clic.
    actions_btn = ft.ElevatedButton(
        content=ft.Row([
            ft.Icon(ft.Icons.BOLT_OUTLINED, color=DARK, size=CONSTANTS.ICON_SM),
            ft.Text("ACTIONS", size=CONSTANTS.TEXT_SM, color=DARK,
                    weight=ft.FontWeight.W_800),
        ], spacing=6, tight=True),
        style=ft.ButtonStyle(bgcolor=ORANGE, padding=ft.Padding(14, 10, 14, 10)),
        on_click=lambda e: _open_actions(e),
    )

    files_surface = ft.Column([
        ft.Container(
            content=ft.Column([
                ft.Row([
                    parent_folder_btn,
                    refresh_folder_btn,
                    open_menu_btn,
                    files_path,
                    sel_count,
                    search_field,
                    sort_btn,
                    view_seg,
                ], spacing=6),
                ft.Row([
                    _seg_btn(ft.Icons.SELECT_ALL, "Tout sélectionner", _toggle_all),
                    _seg_btn(ft.Icons.FLIP, "Inverser", _invert),
                    only_sel_btn,
                    ft.VerticalDivider(width=1, color=GREY),
                    order_mode_btn,
                    create_order_btn,
                    ft.Container(expand=True),
                    actions_btn,
                ], spacing=6),
            ], spacing=4),
            padding=ft.Padding(8, 8, 8, 0),
        ),
        ft.Divider(height=1, color=GREY),
        files_body,
    ], expand=True, spacing=0)

    # ═════════════════════════════════════════════════════════════════════
    #  Surface Bloc-notes — .notes.md partagé avec Dashboard/SidePanel
    # ═════════════════════════════════════════════════════════════════════
    _notes_file = os.path.join(_APP_DIR, ".notes.md")
    # Fichier actuellement chargé dans le Bloc-notes — .notes.md par défaut,
    # ou n'importe quel .py/.json/.md/.txt ouvert depuis la surface Fichiers
    # (cf. Dashboard.pyw:1577-1611, même principe de « bloc-notes générique »).
    note_target = {"path": _notes_file}
    _NOTE_LANGUAGES = {
        ".py": fce.CodeLanguage.PYTHON, ".pyw": fce.CodeLanguage.PYTHON,
        ".json": fce.CodeLanguage.JSON,
        ".md": fce.CodeLanguage.MARKDOWN, ".markdown": fce.CodeLanguage.MARKDOWN,
    }

    notes_field = fce.CodeEditor(
        text_style=ft.TextStyle(font_family="monospace", size=CONSTANTS.TERMINAL_FONT_SIZE),
        language=fce.CodeLanguage.MARKDOWN, code_theme=fce.CodeTheme.ATOM_ONE_DARK,
        gutter_style=fce.GutterStyle(width=88), expand=True,
    )
    notes_title = ft.Text("Bloc-notes", size=CONSTANTS.TEXT_LG, color=WHITE,
                          weight=ft.FontWeight.W_500, expand=True, no_wrap=True)
    notes_preview = ft.Markdown(
        "", selectable=True, extension_set=ft.MarkdownExtensionSet.GITHUB_WEB,
        code_theme=ft.MarkdownCodeTheme.ATOM_ONE_DARK, expand=True)
    notes_preview_scroll = ft.ListView(controls=[notes_preview], expand=True,
                                       visible=False)
    notes_is_preview = {"value": False}

    def _notes_load():
        path = note_target["path"]
        try:
            if os.path.exists(path):
                with open(path, "r", encoding="utf-8") as f:
                    notes_field.value = f.read()
            else:
                notes_field.value = ""
        except Exception:
            notes_field.value = ""

    def _notes_save(event=None):
        path = note_target["path"]
        try:
            _backup_file(path)   # filet anti-perte avant écrasement
            with open(path, "w", encoding="utf-8") as f:
                f.write(notes_field.value or "")
        except Exception:
            pass

    def _open_path_in_notes(path):
        note_target["path"] = path
        ext = os.path.splitext(path)[1].lower()
        notes_field.language = _NOTE_LANGUAGES.get(ext, fce.CodeLanguage.PLAINTEXT)
        notes_title.value = os.path.basename(path)
        _notes_load()
        if notes_is_preview["value"]:
            notes_is_preview["value"] = False
            notes_field.visible = True
            notes_preview_scroll.visible = False
            notes_preview_btn.icon = ft.Icons.VISIBILITY
            notes_preview_btn.tooltip = "Prévisualiser en Markdown"
        _select_surface("notes")

    def _notes_prepare_markdown(text):
        lines = ["&nbsp;" if ln.strip() == "" else ln + "  " for ln in text.split("\n")]
        return "\n".join(lines)

    def _notes_toggle_preview(event=None):
        notes_is_preview["value"] = not notes_is_preview["value"]
        if notes_is_preview["value"]:
            _notes_save()
            notes_preview.value = _notes_prepare_markdown(notes_field.value or "")
            notes_preview_scroll.visible = True
            notes_field.visible = False
            notes_preview_btn.icon = ft.Icons.EDIT
            notes_preview_btn.tooltip = "Revenir à l'édition"
        else:
            notes_field.visible = True
            notes_preview_scroll.visible = False
            notes_preview_btn.icon = ft.Icons.VISIBILITY
            notes_preview_btn.tooltip = "Prévisualiser en Markdown"
        page.update()

    def _notes_clear(event=None):
        notes_field.value = ""
        if notes_is_preview["value"]:
            notes_is_preview["value"] = False
            notes_field.visible = True
            notes_preview_scroll.visible = False
            notes_preview_btn.icon = ft.Icons.VISIBILITY
            notes_preview_btn.tooltip = "Prévisualiser en Markdown"
        _notes_save()
        page.update()

    def _create_file_confirm(dlg, name_field, folder):
        def _confirm(event):
            name = (name_field.value or "").strip()
            dlg.open = False
            page.update()
            if not name:
                return
            _folder_create_file(folder, name, "")
            _navigate(folder)
        return _confirm

    def _create_file_here(event=None):
        folder = state["folder"]
        if not folder:
            return
        name_field = ft.TextField(
            hint_text="nom-du-fichier.md", autofocus=True, width=280,
            bgcolor=DARK, border_color=BLUE, text_size=13, height=40,
            content_padding=ft.Padding(8, 4, 8, 4))
        dlg = ft.AlertDialog(
            title=ft.Text("Créer un fichier ici", size=13, color=WHITE),
            content=ft.Column([
                ft.Text(folder, size=11, color=GREY, no_wrap=True),
                name_field,
            ], spacing=6, tight=True, width=280),
            actions_alignment=ft.MainAxisAlignment.END,
        )

        def _cancel(event):
            dlg.open = False
            page.update()

        dlg.actions = [
            ft.TextButton("Créer", on_click=_create_file_confirm(dlg, name_field, folder)),
            ft.TextButton("Annuler", on_click=_cancel),
        ]
        name_field.on_submit = _create_file_confirm(dlg, name_field, folder)
        page.overlay.append(dlg)
        dlg.open = True
        page.update()

    notes_preview_btn = ft.IconButton(
        ft.Icons.VISIBILITY, icon_color=WHITE, icon_size=18,
        tooltip="Prévisualiser en Markdown", on_click=_notes_toggle_preview)
    create_file_btn = ft.IconButton(
        ft.Icons.NOTE_ADD_OUTLINED, icon_color=ICON_ACTION, icon_size=18,
        tooltip="Créer un fichier dans le dossier ouvert",
        on_click=_create_file_here, disabled=not state["folder"])

    notes_surface = ft.Column([
        ft.Container(
            content=ft.Row([
                notes_title,
                ft.IconButton(ft.Icons.SAVE_OUTLINED, icon_color=ICON_ACTION,
                             icon_size=18, tooltip="Enregistrer", on_click=_notes_save),
                notes_preview_btn,
                create_file_btn,
                ft.IconButton(ft.Icons.DELETE_OUTLINE, icon_color=RED, icon_size=18,
                             tooltip="Effacer", on_click=_notes_clear),
            ], spacing=4),
            padding=ft.Padding(8, 8, 8, 0),
        ),
        ft.Divider(height=1, color=GREY),
        ft.Container(content=notes_field, expand=True, padding=8),
        notes_preview_scroll,
    ], expand=True, spacing=0)
    _notes_load()

    # ═════════════════════════════════════════════════════════════════════
    #  Surface IA — chat + outils (cerveau mutualisé Data/ai_tools.py)
    #  v1 : modèles cloud uniquement (Gemini/Claude) — Ollama nécessite une
    #  gestion de process (_ensure_ollama_ready) hors scope pour l'instant.
    # ═════════════════════════════════════════════════════════════════════
    ai_conversation = []
    ai_streaming = {"value": False}
    ai_pending_images = []   # [{"path": str, "b64": str}, ...] — en attente d'envoi
    ai_pending_files = []    # [str, ...] chemins de documents en attente
    _ai_history_file = os.path.join(_APP_DIR, ".ai_conversation_hub.json")

    ai_chat_view = ft.ListView(expand=True, spacing=4, auto_scroll=True)
    ai_attach_row = ft.Row([], spacing=6, wrap=True, visible=False)
    ai_input_field = ft.TextField(
        hint_text="Posez votre question… (Entrée pour envoyer)",
        border_color=BLUE,
        text_style=ft.TextStyle(font_family="monospace", size=CONSTANTS.TERMINAL_FONT_SIZE),
        dense=True, expand=True, color=WHITE, bgcolor=DARK, shift_enter=True)
    ai_model_dropdown = ft.Dropdown(
        value=CONSTANTS.AI_MODEL_TEXT,
        options=[ft.dropdown.Option(m) for m in CONSTANTS.AI_DROPDOWN_MODELS
                 if m.startswith(("gemini", "claude"))],
        text_size=11, dense=True, color=WHITE, bgcolor=DARK, border_color=GREY,
        content_padding=ft.Padding.symmetric(horizontal=6, vertical=0), width=180)
    ai_status_text = ft.Text("", color=GREY, size=11, italic=True, max_lines=1,
                             overflow=ft.TextOverflow.ELLIPSIS, expand=True)
    ai_progress_bar = ft.ProgressBar(value=None, visible=False, color=BLUE, height=2)

    async def _ai_update_and_scroll():
        try:
            page.update()
            await asyncio.sleep(0)
            await ai_chat_view.scroll_to(offset=-1)
        except Exception:
            pass

    def _ai_refresh():
        # Depuis un thread (streaming IA en arrière-plan), page.update() direct
        # ne se propage pas de façon fiable en Flet 0.85 — il faut repasser par
        # la boucle asyncio de la page via page.run_task (idiome SidePanel).
        page.run_task(_ai_update_and_scroll)

    async def _ai_navigate_async(folder):
        # _navigate()/_render() appellent page.update() en interne : les lancer
        # via page.run_task (plutôt que depuis le thread IA directement) place
        # cet appel sur la boucle asyncio de la page, même contrainte que ci-dessus.
        if folder:
            try:
                _navigate(folder)
            except Exception:
                pass
        # Comme le pubsub "refresh" de SidePanel : l'IA peut avoir écrit dans
        # le fichier .json actuellement ouvert dans la surface Liste (create_
        # file/edit_file, aucun outil dédié) — la recharger à chaque refresh.
        try:
            _liste_reload()
        except Exception:
            pass

    def _ai_add_bubble(role, text):
        # Forme de bulle de chat façon artefact (.bub.u / .bub.a) : alignée à
        # droite (utilisateur, accent) ou à gauche (assistant, neutre), coin
        # arrondi asymétrique côté « pointe ». expand=8/2 sur la Row imite la
        # largeur max ~82% de l'artefact tout en restant responsive (utile en
        # mode compagnon demi-écran, cf. HUB_SPEC §3).
        is_user = role == "user"
        is_think = role == "think"
        if is_user:
            bubble_text = ft.Text(text, size=CONSTANTS.TERMINAL_FONT_SIZE, color=DARK,
                                  font_family="monospace", selectable=True)
            bubble = ft.Container(
                content=bubble_text, bgcolor=BLUE, padding=ft.Padding(9, 7, 9, 7),
                border_radius=ft.BorderRadius(top_left=13, top_right=13,
                                              bottom_left=13, bottom_right=4),
                expand=8)
            row = ft.Row([ft.Container(expand=2), bubble],
                        alignment=ft.MainAxisAlignment.END)
        elif is_think:
            bubble_text = ft.Text(f"💭 {text}", size=CONSTANTS.TERMINAL_FONT_SIZE - 1,
                                  color=LIGHT_GREY, italic=True, selectable=True)
            bubble = ft.Container(
                content=bubble_text, bgcolor=DARK, border=ft.Border.all(1, LIGHT_GREY),
                padding=ft.Padding(9, 7, 9, 7),
                border_radius=ft.BorderRadius(top_left=13, top_right=13,
                                              bottom_left=4, bottom_right=13),
                expand=8)
            row = ft.Row([bubble, ft.Container(expand=2)],
                        alignment=ft.MainAxisAlignment.START)
        else:
            bubble_text = ft.Markdown(
                _md_dark(text), selectable=True,
                extension_set=ft.MarkdownExtensionSet.GITHUB_WEB,
                code_theme=ft.MarkdownCodeTheme.ATOM_ONE_DARK, expand=True)
            bubble = ft.Container(
                content=bubble_text, bgcolor=GREY, padding=ft.Padding(9, 7, 9, 7),
                border_radius=ft.BorderRadius(top_left=13, top_right=13,
                                              bottom_left=4, bottom_right=13),
                expand=8)
            row = ft.Row([bubble, ft.Container(expand=2)],
                        alignment=ft.MainAxisAlignment.START)
        ai_chat_view.controls.append(row)
        _ai_refresh()
        return bubble_text

    def _ai_stop(event=None):
        ai_streaming["value"] = False

    def _ai_tool_paint():
        _ai_refresh()

    def _ai_add_image_bubble(image_path):
        try:
            thumb = thumb_cache.get_or_generate(image_path)
        except Exception:
            thumb = None
        if not thumb:
            try:
                with open(image_path, "rb") as f:
                    thumb = f.read()
            except Exception:
                thumb = None
        content = (ft.Image(src=thumb, width=320, fit=ft.BoxFit.CONTAIN,
                            border_radius=ft.BorderRadius.all(6))
                  if thumb else
                  ft.Text(f"[Image introuvable : {image_path}]", color=RED))
        bubble = ft.Container(
            content=content, bgcolor=GREY, padding=6,
            border_radius=ft.BorderRadius(top_left=13, top_right=13,
                                          bottom_left=4, bottom_right=13),
            expand=8)
        ai_chat_view.controls.append(
            ft.Row([bubble, ft.Container(expand=2)],
                  alignment=ft.MainAxisAlignment.START))
        _ai_refresh()

    def _ai_add_screenshot_bubble(b64_str):
        try:
            img_bytes = base64.b64decode(b64_str)
        except Exception:
            return
        bubble = ft.Container(
            content=ft.Image(src=img_bytes, width=320, fit=ft.BoxFit.CONTAIN,
                             border_radius=ft.BorderRadius.all(6)),
            bgcolor=GREY, border=ft.Border.all(1, LIGHT_GREY), padding=6,
            border_radius=ft.BorderRadius(top_left=13, top_right=13,
                                          bottom_left=4, bottom_right=13),
            expand=8)
        ai_chat_view.controls.append(
            ft.Row([bubble, ft.Container(expand=2)],
                  alignment=ft.MainAxisAlignment.START))
        _ai_refresh()

    def _ai_get_credential(service, username, timeout=300):
        # Coffre natif de l'OS (Data/credentials.py, keyring) — jamais en
        # clair sur disque. Bloque le thread IA (appelé depuis _run(), pas
        # le thread principal) le temps que l'utilisateur saisisse le mot
        # de passe, comme Dashboard.pyw:1355-1421.
        existing = credentials.get_credential(service, username)
        if existing is not None:
            return existing

        cred_event = threading.Event()
        cred_result = {"value": None}
        password_field = ft.TextField(
            label=f"Mot de passe pour {username}@{service}",
            password=True, can_reveal_password=True, autofocus=True, width=360,
            bgcolor=DARK, border_color=GREY, color=WHITE)

        def _confirm(e=None):
            value = password_field.value or ""
            if value:
                credentials.set_credential(service, username, value)
                cred_result["value"] = value
            dlg.open = False
            page.update()
            cred_event.set()

        def _cancel(e=None):
            dlg.open = False
            page.update()
            cred_event.set()

        password_field.on_submit = _confirm
        dlg = ft.AlertDialog(
            modal=True,
            title=ft.Text(f"🔐 Identifiant requis : {service}", size=14, color=WHITE),
            content=ft.Column([
                ft.Text(f"Aucun mot de passe enregistré pour {username}@{service}.",
                       size=13, color=WHITE),
                password_field,
            ], tight=True, width=360),
            actions=[ft.TextButton("Annuler", on_click=_cancel),
                     ft.Button("Enregistrer", bgcolor=BLUE, color=WHITE,
                              on_click=_confirm)],
            actions_alignment=ft.MainAxisAlignment.END,
        )

        async def _open_dlg():
            page.overlay.append(dlg)
            dlg.open = True
            page.update()
            try:
                await page.window.to_front()
            except Exception:
                pass
        page.run_task(_open_dlg)
        cred_event.wait(timeout=timeout)
        return cred_result["value"]

    def _ai_tool_generate_image(fn_name, args):
        prompt = args.get("prompt", "")
        aspect = args.get("aspect_ratio", "1:1")
        src_name = ""
        if fn_name == "generate_image":
            out_filename = (args.get("filename", "").strip()
                           or f"generated_{datetime.datetime.now():%Y%m%d_%H%M%S}.png")
            src_bytes = None
            label = prompt[:60] + ("…" if len(prompt) > 60 else "")
            _ai_add_bubble("assistant", f"🎨 Génération : {label}")
        else:
            src_name = args.get("source_filename", "").strip()
            out_filename = (args.get("output_filename", "").strip()
                           or f"edited_{datetime.datetime.now():%Y%m%d_%H%M%S}.png")
            src_bytes = None
            folder = state["folder"]
            if src_name and folder:
                src_path = os.path.join(folder, os.path.basename(src_name))
                if os.path.isfile(src_path):
                    with open(src_path, "rb") as f:
                        src_bytes = f.read()
            _ai_add_bubble("assistant", f"🎨 Édition : {src_name} → {out_filename}")

        prompt_refined = prompt
        model = ai_model_dropdown.value or CONSTANTS.AI_MODEL_TEXT
        if model.startswith(("gemini", "claude")) and prompt.strip():
            try:
                prompt_refined = _gemini_refine_image_prompt(
                    intent_prompt=prompt, user_request=prompt, mode=fn_name,
                    source_filename=src_name, model=CONSTANTS.AI_IMAGE_REFINER_MODEL)
            except Exception:
                prompt_refined = prompt
            if prompt_refined != prompt and CONSTANTS.AI_SHOW_REFINED_IMAGE_PROMPT:
                _ai_add_bubble("assistant",
                              f"🧪 Prompt image affiné automatiquement :\n\n{prompt_refined}")

        ai_status_text.value = "🎨 Génération d'image en cours…"
        _ai_refresh()
        try:
            text, img_bytes = _gemini_generate_image(
                prompt_refined, input_image_bytes=src_bytes,
                aspect_ratio=aspect, resolution="1K")
        except Exception as exc:
            text, img_bytes = f"[Erreur] {exc}", None

        if img_bytes:
            dest_folder = state["folder"] or os.path.join(_APP_DIR, "Generated")
            os.makedirs(dest_folder, exist_ok=True)
            save_path = os.path.join(dest_folder, out_filename)
            with open(save_path, "wb") as f:
                f.write(img_bytes)
            _ai_add_image_bubble(save_path)
            if state["folder"]:
                page.run_task(_ai_navigate_async, state["folder"])
            result = f"Image sauvegardée : {save_path}"
            if text:
                result += f"\n\nRéponse du service : {text}"
            return result
        result = "[Erreur] Aucune image n'a été générée/sauvegardée."
        if text:
            result += f"\n\nRéponse texte du service (sans image) :\n{text}"
        return result

    def _ai_tool_iterate_image(fn_name, args):
        src_name = args.get("source_filename", "").strip()
        goal = args.get("goal", "").strip()
        passes = args.get("passes") or CONSTANTS.AI_IMAGE_ITERATE_MAX_PASSES
        try:
            passes = max(1, int(passes))
        except (TypeError, ValueError):
            passes = CONSTANTS.AI_IMAGE_ITERATE_MAX_PASSES
        folder = state["folder"]
        if not src_name or not folder:
            return "[Erreur] iterate_image nécessite un dossier ouvert et un fichier source."
        src_path = os.path.join(folder, os.path.basename(src_name))
        if not os.path.isfile(src_path):
            return f"[Erreur] Fichier introuvable : {src_name}"
        _ai_add_bubble("assistant",
                      f"🔁 Itération image : {src_name} (max {passes} passes)\n"
                      f"Objectif : {goal}")
        ai_status_text.value = "🔁 Itération d'image en cours…"
        _ai_refresh()
        try:
            res = _iterate_image_loop(src_path, goal, passes,
                                      refiner_model=CONSTANTS.AI_IMAGE_REFINER_MODEL)
        except Exception as exc:
            res = {"final_path": None, "passes": [], "error": str(exc)}
        for p in res.get("passes", []):
            if p.get("ok"):
                _ai_add_bubble("assistant", f"✅ Passe {p['pass']} : objectif atteint.")
            else:
                _ai_add_bubble("assistant",
                              f"🔍 Passe {p['pass']} — à corriger :\n{p.get('critique', '')}")
                if p.get("path") and os.path.isfile(p["path"]):
                    _ai_add_image_bubble(p["path"])
        final = res.get("final_path")
        if final and os.path.isfile(final):
            page.run_task(_ai_navigate_async, folder)
            result = (f"Itération terminée ({len(res.get('passes', []))} passe(s)). "
                     f"Image finale : {final}")
        else:
            result = "[Erreur] Itération image : aucune image produite."
        if res.get("error"):
            result += f"\n{res['error']}"
        return result

    def _ai_tool_generate_music(fn_name, args):
        prompt = args.get("prompt", "")
        model = args.get("model", "lyria-3-clip-preview")
        filename = (args.get("filename", "").strip()
                   or f"music_{datetime.datetime.now():%Y%m%d_%H%M%S}.mp3")
        label = prompt[:60] + ("…" if len(prompt) > 60 else "")
        _ai_add_bubble("assistant", f"🎵 Génération musique : {label}")
        ai_status_text.value = "🎵 Génération musicale en cours…"
        _ai_refresh()
        try:
            audio_bytes, lyrics, err = _gemini_generate_music(prompt, model=model)
        except Exception as exc:
            audio_bytes, lyrics, err = None, None, str(exc)
        if audio_bytes:
            dest = state["folder"] or os.path.join(_APP_DIR, "Generated")
            os.makedirs(dest, exist_ok=True)
            save_path = os.path.join(dest, filename)
            with open(save_path, "wb") as f:
                f.write(audio_bytes)
            if state["folder"]:
                page.run_task(_ai_navigate_async, state["folder"])
            result = f"Musique sauvegardée : {save_path}"
            if lyrics:
                result += f"\n\nParoles / Structure :\n{lyrics}"
            return result
        return f"[Erreur] Génération musicale échouée : {err}"

    def _ai_tool_organize_files(fn_name, args):
        actions = args.get("actions", [])
        folder = state["folder"]
        if not actions:
            return "Aucune action à exécuter."
        if not folder:
            return "Aucun dossier ouvert."
        confirmed = True
        if CONSTANTS.AI_ORGANIZE_CONFIRM:
            confirm_event = threading.Event()
            confirm_result = {"value": False}
            rows = [ft.Text(f"• {a.get('filename', '?')}  →  "
                            f"{a.get('destination_subfolder', '?')}/",
                            size=12, color=WHITE) for a in actions[:40]]
            if len(actions) > 40:
                rows.append(ft.Text(f"… et {len(actions) - 40} autres",
                                    size=12, color=LIGHT_GREY))

            def _confirm(e=None):
                confirm_result["value"] = True
                dlg.open = False
                page.update()
                confirm_event.set()

            def _cancel(e=None):
                dlg.open = False
                page.update()
                confirm_event.set()

            dlg = ft.AlertDialog(
                modal=True,
                title=ft.Text("📂 Organiser les fichiers", size=14, color=WHITE),
                content=ft.Column([
                    ft.Text(args.get("summary") or "Organisation proposée par l'IA :",
                           size=13, color=WHITE),
                    ft.Column(rows, scroll=ft.ScrollMode.AUTO,
                             height=min(320, len(rows) * 24)),
                ], tight=True, width=500),
                actions=[ft.TextButton("Annuler", on_click=_cancel),
                         ft.Button("Exécuter", bgcolor=BLUE, color=WHITE,
                                  on_click=_confirm)],
                actions_alignment=ft.MainAxisAlignment.END,
            )

            async def _open_dlg():
                page.overlay.append(dlg)
                dlg.open = True
                page.update()
            page.run_task(_open_dlg)
            confirm_event.wait(timeout=300)
            confirmed = confirm_result["value"]
        if not confirmed:
            return "Organisation annulée par l'utilisateur."
        moves, errors = [], []
        for action in actions:
            filename = os.path.basename(action.get("filename", ""))
            subfolder = action.get("destination_subfolder", "").strip("/\\")
            if not filename or not subfolder:
                continue
            source = os.path.join(folder, filename)
            dest_dir = os.path.join(folder, subfolder)
            dest = os.path.join(dest_dir, filename)
            if not os.path.isfile(source):
                errors.append(f"Introuvable : {filename}")
                continue
            try:
                os.makedirs(dest_dir, exist_ok=True)
                if os.path.exists(dest):
                    _backup_file(dest)
                shutil.move(source, dest)
                moves.append(f"✓ {filename} → {subfolder}/")
            except Exception as exc:
                errors.append(f"✗ {filename} : {exc}")
        page.run_task(_ai_navigate_async, folder)
        lines = [f"{len(moves)} fichier(s) déplacé(s)."] + moves
        if errors:
            lines += ["Erreurs :"] + errors
        return "\n".join(lines)

    def _ai_tool_score_photos(fn_name, args):
        folder = state["folder"]
        if not folder:
            return "Aucun dossier ouvert."
        filenames = args.get("filenames") or []
        if filenames:
            candidates = [os.path.basename(n) for n in filenames
                         if os.path.isfile(os.path.join(folder, os.path.basename(n)))]
        else:
            candidates = sorted(
                e.name for e in os.scandir(folder)
                if e.is_file() and os.path.splitext(e.name)[1].lower()
                in CONSTANTS.IMAGE_EXTS)
        if not candidates:
            return "Aucune image trouvée."
        total = len(candidates)
        model = ai_model_dropdown.value or CONSTANTS.AI_MODEL_VISION
        batch_n = (CONSTANTS.AI_GEMINI_FOLDER_BATCH_SIZE if model.startswith("gemini")
                  else CONSTANTS.AI_FOLDER_SELECT_BATCH_SIZE)
        batches = (total + batch_n - 1) // batch_n
        progress_ctrl = _ai_add_bubble("assistant",
                                       f"🏆 Score de {total} image(s) — lot 1/{batches}…")

        def _on_progress(batch_num, total_batches):
            ai_status_text.value = f"🏆 Score lot {batch_num}/{total_batches}…"
            progress_ctrl.value = _md_dark(f"🏆 Score — lot {batch_num}/{total_batches}…")
            _ai_refresh()

        summary = _score_images_batched(
            CONSTANTS.AI_OLLAMA_URL, model, folder, candidates,
            contexte=args.get("contexte", ""),
            criteres_additionnels=args.get("criteres_additionnels") or [],
            batch_size=batch_n, image_exts=CONSTANTS.IMAGE_EXTS,
            max_size=CONSTANTS.AI_FOLDER_SELECT_IMAGE_SIZE,
            quality=CONSTANTS.AI_FOLDER_SELECT_QUALITY,
            on_progress=_on_progress,
            is_running=lambda: ai_streaming["value"])
        progress_ctrl.value = _md_dark(f"🏆 {summary}")
        _ai_refresh()
        return summary

    def _ai_tool_ask_clarifying(fn_name, args):
        question = args.get("question", "")
        options = (args.get("options") or [])[:5]
        q_event = threading.Event()
        q_result = {"value": None}

        def _choice(opt):
            def _handler(e=None):
                q_result["value"] = opt
                dlg.open = False
                page.update()
                q_event.set()
            return _handler

        other_field = ft.TextField(label="Autre réponse…", width=380,
                                   bgcolor=DARK, border_color=GREY, color=WHITE)

        def _other(e=None):
            q_result["value"] = (other_field.value or "").strip() or "(pas de réponse précisée)"
            dlg.open = False
            page.update()
            q_event.set()

        dlg = ft.AlertDialog(
            modal=True,
            title=ft.Text("❓ Question de l'IA", size=14, color=WHITE),
            content=ft.Column([
                ft.Text(question, size=13, color=WHITE),
                ft.Container(height=8),
                *[ft.Button(opt, bgcolor=BLUE, color=WHITE, on_click=_choice(opt))
                  for opt in options],
                ft.Container(height=8),
                ft.Row([other_field, ft.TextButton("Envoyer", on_click=_other)]),
            ], tight=True, width=440),
        )

        async def _open_dlg():
            page.overlay.append(dlg)
            dlg.open = True
            page.update()
            try:
                await page.window.to_front()
            except Exception:
                pass
        page.run_task(_open_dlg)
        q_event.wait(timeout=600)
        return q_result["value"] or "(l'utilisateur n'a pas répondu à temps)"

    _ai_last_screenshot = {"b64": None}

    def _ai_tool_take_screenshot(fn_name, args):
        region = args.get("region") or None
        ai_status_text.value = "📸 Capture d'écran…"
        _ai_add_bubble("assistant", "📸 Capture d'écran")
        _ai_refresh()
        capture = _take_screenshot(region=region)
        if not capture:
            _ai_last_screenshot["b64"] = None
            return "Échec de la capture d'écran."
        _ai_last_screenshot["b64"] = capture["b64"]
        _ai_add_screenshot_bubble(capture["b64"])
        return capture["text"]

    _AI_SPECIAL_TOOLS = {
        "generate_image": _ai_tool_generate_image,
        "edit_image": _ai_tool_generate_image,
        "iterate_image": _ai_tool_iterate_image,
        "generate_music": _ai_tool_generate_music,
        "organize_files": _ai_tool_organize_files,
        "score_photos": _ai_tool_score_photos,
        "ask_clarifying_question": _ai_tool_ask_clarifying,
        "take_screenshot": _ai_tool_take_screenshot,
    }

    def _ai_tool_navigate_folder(args):
        path = (args.get("path") or "").strip()
        if not path or not os.path.isdir(path):
            return f"Dossier introuvable : {path}"
        page.run_task(_ai_navigate_async, path)
        return f"Navigation vers {path} effectuée."

    def _ai_tool_select_files(args):
        folder = state["folder"]
        if not folder:
            return "Aucun dossier ouvert."
        filenames = args.get("filenames") or []
        mode = args.get("mode", "replace")
        paths = [os.path.join(folder, name) for name in filenames
                 if os.path.exists(os.path.join(folder, name))]

        async def _apply():
            if mode == "replace":
                selected.clear()
                selected.update(paths)
            elif mode == "add":
                selected.update(paths)
            elif mode == "remove":
                for p in paths:
                    selected.discard(p)
            _update_sel_count()
            _render()
        page.run_task(_apply)
        return f"Sélection mise à jour ({mode}) : {len(paths)} fichier(s)."

    def _ai_tool_read_notepad(args):
        return notes_field.value or "(vide)"

    def _ai_tool_write_notepad(args):
        content = args.get("content", "")
        action = args.get("action", "append")
        current = notes_field.value or ""
        downgraded = False
        if action == "replace" and current.strip():
            action = "append"
            downgraded = True
        if action == "replace":
            new_value = content
        elif action == "prepend":
            new_value = f"{content}\n\n{current}" if current else content
        else:
            new_value = f"{current}\n\n{content}" if current else content

        async def _apply():
            notes_field.value = new_value
            page.update()
            _notes_save()
        page.run_task(_apply)
        note = (" (replace rétrogradé en append : bloc-notes non vide)"
               if downgraded else "")
        return f"Bloc-notes mis à jour ({action}).{note}"

    _AI_FALLBACK_TOOLS = {
        "list_folder_contents": lambda args: _folder_list_contents(
            (args.get("path") or "").strip() or state["folder"] or ""),
        "read_file_content": lambda args: _folder_read_file(
            state["folder"], args.get("filename", ""),
            document_exts=CONSTANTS.AI_DOCUMENT_EXTS),
        "create_file": lambda args: _folder_create_file(
            state["folder"], args.get("filename", ""), args.get("content", "")),
        "delete_files": lambda args: _folder_delete_files(
            state["folder"], args.get("paths", [])),
        "web_search": lambda args: _web_search(args.get("query", "")),
        "fetch_url": lambda args: _fetch_url_content(
            args.get("url", ""), max_chars=CONSTANTS.AI_URL_MAX_CHARS),
        "run_terminal_command": lambda args: _run_terminal_command(
            args.get("command", "")),
        "update_memory_file": lambda args: _update_memory_file(
            args.get("target", ""), args.get("action", ""),
            args.get("content", ""), args.get("old_text", "")),
        "read_notepad": _ai_tool_read_notepad,
        "write_notepad": _ai_tool_write_notepad,
        "navigate_to_folder": _ai_tool_navigate_folder,
        "select_files_in_ui": _ai_tool_select_files,
    }

    # Résumés emoji des outils du fallback (dispatch_folder_tool en émet déjà
    # via ui.bubble() pour ses branches "pures" — move_file, copy_file,
    # create_folder, edit_file, zip/unzip, git_command, ask_subagent, etc. —
    # mais PAS pour ceux ci-dessous, gérés localement par app comme dans
    # Dashboard.pyw (l.3007-3033) : sans ça, l'appel disparaît une fois le
    # texte de statut effacé, aucune trace dans l'historique du chat.
    _AI_TOOL_BUBBLES = {
        "list_folder_contents": lambda a: "📂 Lecture du dossier",
        "read_file_content": lambda a: f"📄 Lecture : {a.get('filename', '')}",
        "create_file": lambda a: f"📝 Création de fichier : {a.get('filename', '')}",
        "delete_files": lambda a: "🗑️ Suppression",
        "web_search": lambda a: f"🔍 Recherche : {a.get('query', '')}",
        "fetch_url": lambda a: f"🌐 Lecture : {a.get('url', '')}",
        "run_terminal_command": lambda a: f"💻 Commande : {a.get('command', '')}",
    }

    def _ai_run_tool(fn_name, fn_args, ui):
        if fn_name.startswith("mcp__"):
            ai_status_text.value = f"🔌 {fn_name}…"
            _ai_add_bubble("assistant", f"🔌 Outil MCP : {fn_name}")
            _ai_refresh()
            try:
                return mcp_client.mcp_call_tool(fn_name, fn_args)
            except Exception as exc:
                return f"[Erreur] {fn_name} : {exc}"
        special = _AI_SPECIAL_TOOLS.get(fn_name)
        if special is not None:
            try:
                return special(fn_name, fn_args)
            except Exception as exc:
                return f"[Erreur] {fn_name} : {exc}"
        result = dispatch_folder_tool(fn_name, fn_args, state["folder"], ui)
        if result is not DISPATCH_UNHANDLED:
            return result
        handler = _AI_FALLBACK_TOOLS.get(fn_name)
        if handler is not None:
            try:
                return handler(fn_args)
            except Exception as exc:
                return f"[Erreur] {fn_name} : {exc}"
        return f"Outil « {fn_name} » indisponible dans le Hub pour l'instant."

    def _ai_save_history_now():
        try:
            _ai_save_history(ai_conversation, _ai_history_file)
        except Exception:
            pass

    def _ai_load_history():
        if not os.path.isfile(_ai_history_file):
            return
        try:
            with open(_ai_history_file, "r", encoding="utf-8") as f:
                saved = json.load(f)
            messages = saved.get("messages", []) if isinstance(saved, dict) else saved
        except Exception:
            return
        for msg in messages:
            role = msg.get("role")
            content = msg.get("content", "")
            if role not in ("user", "assistant") or not content:
                continue
            ai_conversation.append({"role": role, "content": content})
            _ai_add_bubble(role, content)

    def _ai_clear_conversation(event=None):
        ai_conversation.clear()
        ai_chat_view.controls.clear()
        ai_status_text.value = ""
        try:
            if os.path.isfile(_ai_history_file):
                os.remove(_ai_history_file)
        except Exception:
            pass
        page.update()

    def _ai_refresh_attach_row():
        ai_attach_row.controls.clear()
        for entry in ai_pending_images:
            ai_attach_row.controls.append(ft.Container(
                content=ft.Row([
                    ft.Icon(ft.Icons.IMAGE_OUTLINED, size=14, color=ORANGE),
                    ft.Text(os.path.basename(entry["path"]), size=CONSTANTS.TEXT_XS,
                           color=WHITE),
                    ft.IconButton(ft.Icons.CLOSE, icon_size=12, icon_color=RED,
                                 on_click=lambda e, en=entry: _ai_remove_image(en)),
                ], spacing=4, tight=True),
                bgcolor=GREY, border_radius=6, padding=ft.Padding(6, 2, 2, 2)))
        for path in ai_pending_files:
            ai_attach_row.controls.append(ft.Container(
                content=ft.Row([
                    ft.Icon(ft.Icons.DESCRIPTION_OUTLINED, size=14, color=YELLOW),
                    ft.Text(os.path.basename(path), size=CONSTANTS.TEXT_XS, color=WHITE),
                    ft.IconButton(ft.Icons.CLOSE, icon_size=12, icon_color=RED,
                                 on_click=lambda e, p=path: _ai_remove_file(p)),
                ], spacing=4, tight=True),
                bgcolor=GREY, border_radius=6, padding=ft.Padding(6, 2, 2, 2)))
        ai_attach_row.visible = bool(ai_attach_row.controls)
        page.update()

    def _ai_attach_image(path):
        if any(e["path"] == path for e in ai_pending_images):
            return
        try:
            with PILImage.open(path) as im:
                im = im.convert("RGB")
                max_side = 1024
                w, h = im.size
                if w > max_side or h > max_side:
                    ratio = min(max_side / w, max_side / h)
                    im = im.resize((int(w * ratio), int(h * ratio)), PILImage.LANCZOS)
                buf = io.BytesIO()
                im.save(buf, format="JPEG", quality=85)
                b64_data = base64.b64encode(buf.getvalue()).decode("utf-8")
        except Exception as exc:
            _ai_add_bubble("assistant", f"[Erreur] Impossible de lire l'image : {exc}")
            return
        ai_pending_images.append({"path": path, "b64": b64_data})
        _ai_refresh_attach_row()

    def _ai_remove_image(entry):
        if entry in ai_pending_images:
            ai_pending_images.remove(entry)
        _ai_refresh_attach_row()

    def _ai_attach_document_file(path):
        if path in ai_pending_files:
            return
        ai_pending_files.append(path)
        _ai_refresh_attach_row()

    def _ai_remove_file(path):
        if path in ai_pending_files:
            ai_pending_files.remove(path)
        _ai_refresh_attach_row()

    def _add_to_ai(paths):
        # Menu clic-droit Fichiers -> "Ajouter à l'IA" (cf. mémoire projet) :
        # images en pièce jointe visuelle, tout le reste en texte injecté.
        for p in paths:
            if os.path.splitext(p)[1].lower() in CONSTANTS.IMAGE_EXTS:
                _ai_attach_image(p)
            else:
                _ai_attach_document_file(p)
        _select_surface("ia")

    # État micro (dictée logicielle, PAS le bouton PTT physique F15/pynput
    # de Dashboard — matériel spécifique, hors scope de cette passe).
    _mic_state = {"active": False, "rec": None}

    def _mic_toggle(event=None):
        if _mic_state["active"]:
            _mic_stop()
        else:
            _mic_start()

    def _mic_start():
        if _mic_state["active"]:
            return

        def _on_ready():
            async def _flip():
                if not _mic_state["active"]:
                    return
                ai_mic_button.icon = ft.Icons.STOP_CIRCLE
                ai_mic_button.icon_color = RED
                ai_mic_button.tooltip = "Enregistrement… cliquer pour arrêter"
                ai_status_text.value = "🎤 Parlez maintenant… (recliquer pour arrêter)"
                page.update()
            page.run_task(_flip)

        try:
            recorder = _MicRecorder(sample_rate=CONSTANTS.AI_VOICE_STT_SAMPLE_RATE)
            recorder.start(on_ready=_on_ready)
        except Exception as exc:
            ai_status_text.value = f"Micro indisponible : {exc}"
            page.update()
            return
        _mic_state["rec"] = recorder
        _mic_state["active"] = True
        ai_mic_button.icon = ft.Icons.MIC
        ai_mic_button.icon_color = ORANGE
        ai_mic_button.tooltip = "Préparation du micro…"
        ai_status_text.value = "⏳ Préparation du micro… (attendez le rouge)"
        page.update()

    def _mic_stop():
        if not _mic_state["active"]:
            return
        _mic_state["active"] = False
        recorder = _mic_state["rec"]
        _mic_state["rec"] = None
        ai_mic_button.icon = ft.Icons.MIC_NONE
        ai_mic_button.icon_color = GREY
        ai_mic_button.tooltip = "Cliquer pour dicter (Gemini)"
        ai_status_text.value = "Transcription en cours…"
        page.update()

        def _worker():
            text = None
            try:
                wav = recorder.stop() if recorder else None
                if wav:
                    text = _gemini_transcribe_audio(
                        wav, language_code=CONSTANTS.AI_VOICE_STT_LANGUAGE,
                        model=CONSTANTS.AI_VOICE_STT_MODEL)
            except Exception:
                text = None

            async def _apply():
                if text:
                    existing = (ai_input_field.value or "").rstrip()
                    ai_input_field.value = f"{existing} {text}".strip() if existing else text
                    ai_status_text.value = ""
                    try:
                        await ai_input_field.focus()
                    except Exception:
                        pass
                else:
                    ai_status_text.value = "Aucun texte reconnu"
                page.update()
            page.run_task(_apply)

        threading.Thread(target=_worker, daemon=True).start()

    def _send_ai_message(text):
        if ai_streaming["value"] or (not text.strip() and not ai_pending_images
                                     and not ai_pending_files):
            return
        ai_streaming["value"] = True
        ai_send_button.disabled = True
        ai_stop_button.visible = True
        ai_status_text.value = "⏳ En cours…"
        ai_progress_bar.visible = True
        page.update()

        images_b64 = [e["b64"] for e in ai_pending_images]
        images_paths = [e["path"] for e in ai_pending_images]
        files_to_inject = list(ai_pending_files)
        ai_pending_images.clear()
        ai_pending_files.clear()
        _ai_refresh_attach_row()

        user_message = {"role": "user", "content": text}
        if images_b64:
            user_message["images"] = images_b64
        ai_conversation.append(user_message)

        display_text = text
        if images_paths:
            display_text = (display_text + "\n" if display_text else "") + \
                f"🖼️ {len(images_paths)} image(s) jointe(s)"
        if files_to_inject:
            display_text = (display_text + "\n" if display_text else "") + \
                "  ".join(f"📄 {os.path.basename(p)}" for p in files_to_inject)
        _ai_add_bubble("user", display_text)

        def _run():
            try:
                if files_to_inject:
                    blocks = []
                    for file_path in files_to_inject:
                        try:
                            with open(file_path, "r", encoding="utf-8",
                                     errors="replace") as f:
                                content = f.read(CONSTANTS.AI_FILE_MAX_CHARS)
                            blocks.append(
                                f"--- Document : {os.path.basename(file_path)} ---\n"
                                f"{content}\n--- Fin ---")
                        except Exception as exc:
                            blocks.append(
                                f"--- Document : {os.path.basename(file_path)} --- "
                                f"[Erreur lecture : {exc}]")
                    ai_conversation[-1]["content"] = (
                        ai_conversation[-1]["content"] + "\n\n" + "\n\n".join(blocks)
                    ).strip()
                folder = state["folder"]
                today = datetime.date.today().strftime("%d %B %Y")
                system_content = _build_system_content(folder, today)
                if folder:
                    system_content += f"\n\nDOSSIER ACTUELLEMENT OUVERT : {folder}"
                history = ai_conversation[-CONSTANTS.AI_HISTORY_LIMIT_CLOUD:]
                messages = [{"role": "system", "content": system_content}, *history]

                model = ai_model_dropdown.value or CONSTANTS.AI_MODEL_TEXT
                mcp_tools = mcp_client.mcp_get_all_tools()
                tool_ui = SimpleNamespace(
                    set_status=lambda t: setattr(ai_status_text, "value", t),
                    bubble=lambda t: _ai_add_bubble("assistant", t),
                    event=lambda t: None,
                    refresh=lambda: page.run_task(_ai_navigate_async, folder),
                    paint=_ai_tool_paint,
                    credential=_ai_get_credential,
                )

                for _round in range(20):
                    if not ai_streaming["value"]:
                        break
                    tools = build_tool_list(folder, mcp_tools,
                                           extra_tools=_IMAGE_ITERATE_TOOLS)
                    streamed = ""
                    tool_calls = []
                    thinking_ctrl = None
                    thinking = ""
                    token_count = 0
                    response_ctrl = None

                    if model.startswith("gemini"):
                        stream_iter = _gemini_chat_stream_with_tools(
                            model, messages, tools=tools,
                            temperature=CONSTANTS.AI_TEMPERATURE)
                    elif model.startswith("claude"):
                        stream_iter = _claude_chat_stream_with_tools(
                            model, messages, tools=tools,
                            temperature=CONSTANTS.AI_TEMPERATURE)
                    else:
                        _ai_add_bubble(
                            "assistant",
                            f"Modèle « {model} » non géré dans le Hub pour l'instant.")
                        break

                    for evt, data in stream_iter:
                        if not ai_streaming["value"]:
                            break
                        if evt == "tool_calls":
                            tool_calls.extend(data)
                        elif evt == "thinking":
                            thinking += data
                            if thinking_ctrl is None:
                                thinking_ctrl = _ai_add_bubble("think", data)
                            else:
                                thinking_ctrl.value = f"💭 {thinking}"
                                _ai_refresh()
                        else:
                            streamed += data
                            token_count += 1
                            if response_ctrl is None:
                                if streamed.strip():
                                    response_ctrl = _ai_add_bubble("assistant", streamed)
                            elif token_count % 5 == 0:
                                response_ctrl.value = _md_dark(streamed)
                                _ai_refresh()

                    if not tool_calls:
                        if response_ctrl is not None:
                            response_ctrl.value = _md_dark(streamed)
                            _ai_refresh()
                        elif streamed:
                            _ai_add_bubble("assistant", streamed)
                        ai_conversation.append({"role": "assistant", "content": streamed})
                        break

                    if response_ctrl is not None and streamed:
                        response_ctrl.value = _md_dark(streamed)
                        _ai_refresh()

                    messages.append(
                        {"role": "assistant", "content": "", "tool_calls": tool_calls})
                    ai_conversation.append(
                        {"role": "assistant", "content": "", "tool_calls": tool_calls})
                    for tc in tool_calls:
                        fn = tc.get("function", {})
                        fn_name = fn.get("name", "")
                        fn_args = fn.get("arguments") or {}
                        ai_status_text.value = f"🔧 {fn_name}…"
                        _ai_refresh()
                        # Bulle persistante pour les outils du fallback Hub —
                        # dispatch_folder_tool émet déjà la sienne via
                        # ui.bubble() pour ses propres branches (cf. commentaire
                        # _AI_TOOL_BUBBLES plus haut), pas de doublon possible.
                        bubble_fn = _AI_TOOL_BUBBLES.get(fn_name)
                        if bubble_fn is not None:
                            try:
                                _ai_add_bubble("assistant", bubble_fn(fn_args))
                            except Exception:
                                pass
                        result = _ai_run_tool(fn_name, fn_args, tool_ui)
                        tool_msg = {"role": "tool", "tool_name": fn_name,
                                   "name": fn_name, "content": result}
                        # take_screenshot : joindre l'image au tour d'outil
                        # pour que le modèle la « voie » réellement (le champ
                        # "images" est lu pour n'importe quel rôle par
                        # _ollama_messages_to_gemini, pas seulement "user").
                        if fn_name == "take_screenshot" and _ai_last_screenshot["b64"]:
                            tool_msg["images"] = [_ai_last_screenshot["b64"]]
                            _ai_last_screenshot["b64"] = None
                        messages.append(tool_msg)
                        ai_conversation.append(dict(tool_msg))
                else:
                    _ai_add_bubble("assistant", "⚠️ Trop de tours d'outils, arrêt.")
            except Exception as exc:
                _ai_add_bubble("assistant", f"[Erreur] {exc}")
            finally:
                ai_streaming["value"] = False
                ai_send_button.disabled = False
                ai_stop_button.visible = False
                ai_status_text.value = ""
                ai_progress_bar.visible = False
                _ai_save_history_now()
                _ai_refresh()

        threading.Thread(target=_run, daemon=True).start()

    def _ai_submit(event=None):
        text = (ai_input_field.value or "").strip()
        if not text and not ai_pending_images and not ai_pending_files:
            return
        ai_input_field.value = ""
        page.update()
        _send_ai_message(text)

    ai_input_field.on_submit = _ai_submit
    ai_send_button = ft.IconButton(ft.Icons.SEND, icon_color=BLUE,
                                   tooltip="Envoyer", on_click=_ai_submit)
    ai_stop_button = ft.IconButton(ft.Icons.STOP_CIRCLE, icon_color=RED,
                                   tooltip="Arrêter", visible=False, on_click=_ai_stop)
    ai_mic_button = ft.IconButton(
        ft.Icons.MIC_NONE, icon_color=GREY,
        tooltip="Cliquer pour dicter (Gemini)", on_click=_mic_toggle)
    ai_clear_button = ft.IconButton(
        ft.Icons.DELETE_OUTLINE, icon_color=RED, icon_size=18,
        tooltip="Effacer la conversation", on_click=_ai_clear_conversation)

    ia_surface = ft.Column([
        ft.Container(
            content=ft.Row([
                ft.Text("Assistant IA", size=CONSTANTS.TEXT_LG, color=WHITE,
                        weight=ft.FontWeight.W_500, expand=True),
                ai_model_dropdown,
                ai_clear_button,
            ], spacing=8),
            padding=ft.Padding(8, 8, 8, 0)),
        ft.Divider(height=1, color=GREY),
        ft.Container(content=ai_chat_view, expand=True, padding=8),
        ai_progress_bar,
        ft.Container(content=ai_attach_row, padding=ft.Padding(8, 4, 8, 0)),
        ft.Container(
            content=ft.Row([ai_input_field, ai_mic_button, ai_send_button,
                            ai_stop_button], spacing=4),
            padding=ft.Padding(8, 4, 8, 4)),
        ft.Container(content=ai_status_text, padding=ft.Padding(8, 0, 8, 6)),
    ], expand=True, spacing=0)
    _ai_load_history()

    # ═════════════════════════════════════════════════════════════════════
    #  Surface Liste / Mode commande — tableau de commande :
    #  order[path] = {format: nombre}, plusieurs formats possibles par photo.
    #  Édition via un badge cliquable sur la vignette (bouton "Mode commande"
    #  dans Fichiers), jamais de clic droit. Tarif dégressif PRINTS (mêmes
    #  paliers que Data/kiosk_flet.pyw : <=10 | <=50 | <=100 | <=200 | >200)
    #  + frais d'amorce si la commande n'est pas vide (CONSTANTS.ORDER_SETUP_FEE,
    #  partagé avec kiosk_flet.pyw).
    # ═════════════════════════════════════════════════════════════════════
    _ORDER_SETUP_FEE = CONSTANTS.ORDER_SETUP_FEE

    def _order_unit_price(fmt, total_count):
        tiers = _ORDER_TARIFF.get(fmt)
        if not tiers:
            return 0.0
        if total_count <= 10:
            return tiers[0]
        if total_count <= 50:
            return tiers[1]
        if total_count <= 100:
            return tiers[2]
        if total_count <= 200:
            return tiers[3]
        return tiers[4]

    def _order_lines():
        """Aplati order[path]={format:n} en lignes (path, format, count)."""
        return [(p, fmt, n) for p, formats in order.items()
                for fmt, n in formats.items()]

    def _order_totals():
        format_totals = {}
        for _p, fmt, n in _order_lines():
            format_totals[fmt] = format_totals.get(fmt, 0) + n
        prices = {}
        grand_total = 0.0
        for p, fmt, n in _order_lines():
            unit = _order_unit_price(fmt, format_totals[fmt])
            price = round(unit * n, 2)
            prices[(p, fmt)] = price
            grand_total += price
        if order:
            grand_total += _ORDER_SETUP_FEE
        return prices, round(grand_total, 2)

    async def _create_order_folder(event=None):
        if not order:
            return
        dest_root = await ft.FilePicker().get_directory_path(
            dialog_title="Dossier de destination pour la commande")
        if not dest_root:
            return
        order_folder = _unique_dest(dest_root, "COMMANDE")
        os.makedirs(order_folder, exist_ok=True)
        prices, grand_total = _order_totals()
        manifest = []
        for path, fmt, n in _order_lines():
            if not os.path.isfile(path):
                continue
            stem, ext = os.path.splitext(os.path.basename(path))
            dest = _unique_dest(order_folder, f"{stem}_{fmt}{ext}")
            try:
                shutil.copy2(path, dest)
            except Exception:
                continue
            manifest.append(
                f"{os.path.basename(dest)} — {fmt} × {n} = {prices[(path, fmt)]:.2f} €")
        manifest.append(f"\nTOTAL : {grand_total:.2f} €")
        try:
            with open(os.path.join(order_folder, "commande.txt"), "w",
                     encoding="utf-8") as f:
                f.write("\n".join(manifest))
        except OSError:
            pass
        _navigate(order_folder)

    # ═════════════════════════════════════════════════════════════════════
    #  Surface Liste — lecteur/éditeur .json générique (façon
    #  Data/SidePanel.pyw) : mots-clés ou tout autre texte à copier hors de
    #  l'app (ex. fiches PrestaShop). Format strict : liste d'objets
    #  {"nom": str, "description": str}. L'IA y écrit avec les outils
    #  fichiers génériques (create_file/edit_file, pas d'outil dédié) ; le
    #  callback refresh() du chat (cf. tool_ui plus haut) recharge cette
    #  surface après chaque appel d'outil, comme le pubsub "refresh" de
    #  SidePanel.
    # ═════════════════════════════════════════════════════════════════════
    _liste_file = {"path": os.path.join(_APP_DIR, ".liste.json")}
    liste_entries = []

    def _liste_load():
        liste_entries.clear()
        try:
            with open(_liste_file["path"], "r", encoding="utf-8") as f:
                data = json.load(f)
            if isinstance(data, list):
                for item in data:
                    if isinstance(item, dict) and "nom" in item:
                        liste_entries.append({
                            "nom": str(item.get("nom", "")),
                            "description": str(item.get("description", "")),
                        })
        except Exception:
            pass

    def _liste_save():
        path = _liste_file["path"]
        try:
            _backup_file(path)
            with open(path, "w", encoding="utf-8") as f:
                json.dump(liste_entries, f, ensure_ascii=False, indent=2)
        except Exception:
            pass

    def _liste_copy(text):
        async def _do():
            await page.clipboard.set(text or "")
            status_left.value = f"Copié : {(text or '')[:60]}"
            page.update()
        page.run_task(_do)

    def _liste_delete(index):
        def _cancel(event=None):
            dlg.open = False
            page.update()

        def _confirm(event=None):
            dlg.open = False
            page.update()
            if 0 <= index < len(liste_entries):
                liste_entries.pop(index)
                _liste_save()
                _liste_render()

        dlg = ft.AlertDialog(
            title=ft.Text("Supprimer cette entrée ?", size=13, color=WHITE),
            actions=[ft.TextButton("Annuler", on_click=_cancel),
                     ft.TextButton("Supprimer", on_click=_confirm)],
        )
        page.overlay.append(dlg)
        dlg.open = True
        page.update()

    def _liste_edit(index=None):
        is_new = index is None
        current = {"nom": "", "description": ""} if is_new else liste_entries[index]
        nom_field = ft.TextField(
            label="Nom", value=current["nom"], autofocus=True, width=320,
            bgcolor=DARK, border_color=GREY, color=WHITE)
        desc_field = ft.TextField(
            label="Description", value=current["description"], width=320,
            multiline=True, min_lines=2, max_lines=5, bgcolor=DARK,
            border_color=GREY, color=WHITE)

        def _cancel(event):
            dlg.open = False
            page.update()

        def _confirm(event):
            nom = (nom_field.value or "").strip()
            if not nom:
                nom_field.error_text = "Requis"
                page.update()
                return
            entry = {"nom": nom, "description": (desc_field.value or "").strip()}
            if is_new:
                liste_entries.insert(0, entry)
            else:
                liste_entries[index] = entry
            _liste_save()
            dlg.open = False
            page.update()
            _liste_render()

        dlg = ft.AlertDialog(
            title=ft.Text("Ajouter une entrée" if is_new else "Modifier",
                         size=13, color=WHITE),
            content=ft.Column([nom_field, desc_field], spacing=10, tight=True),
            actions=[ft.TextButton("Annuler", on_click=_cancel),
                     ft.TextButton("Enregistrer", on_click=_confirm)],
        )
        page.overlay.append(dlg)
        dlg.open = True
        page.update()

    def _liste_row(index, entry):
        return ft.Container(
            content=ft.Row([
                ft.Container(
                    content=ft.Text(entry["nom"], size=CONSTANTS.TEXT_SM,
                                    color=BLUE, weight=ft.FontWeight.W_600),
                    tooltip=f"Copier le nom : {entry['nom']}", expand=True,
                    ink=True, on_click=lambda e, t=entry["nom"]: _liste_copy(t)),
                ft.Container(
                    content=ft.Text(entry["description"] or "—",
                                    size=CONSTANTS.TEXT_XS, color=WHITE,
                                    max_lines=2,
                                    overflow=ft.TextOverflow.ELLIPSIS),
                    tooltip=f"Copier la description : {entry['description']}",
                    expand=True, ink=True,
                    on_click=lambda e, t=entry["description"]: _liste_copy(t)),
                ft.IconButton(ft.Icons.EDIT_OUTLINED, icon_size=16, icon_color=GREY,
                             on_click=lambda e, i=index: _liste_edit(i)),
                ft.IconButton(ft.Icons.DELETE_OUTLINE, icon_size=16, icon_color=RED,
                             on_click=lambda e, i=index: _liste_delete(i)),
            ], spacing=8, vertical_alignment=ft.CrossAxisAlignment.CENTER),
            padding=ft.Padding(10, 8, 10, 8), bgcolor=GREY, border_radius=6)

    liste_list_view = ft.ListView(expand=True, spacing=4, padding=8)
    liste_path_text = ft.Text(os.path.basename(_liste_file["path"]),
                              size=CONSTANTS.TEXT_SM, color=WHITE,
                              no_wrap=True, expand=True)

    def _liste_render():
        liste_list_view.controls.clear()
        if not liste_entries:
            liste_list_view.controls.append(ft.Text(
                "Liste vide. Ajoute une entrée, ou demande à l'IA de la "
                "remplir (create_file sur ce fichier .json).",
                size=CONSTANTS.TEXT_SM, color=GREY))
        else:
            liste_list_view.controls.extend(
                _liste_row(i, e) for i, e in enumerate(liste_entries))
        liste_path_text.value = os.path.basename(_liste_file["path"])
        page.update()

    def _liste_reload(event=None):
        _liste_load()
        _liste_render()

    def _liste_open_path(path):
        # Sélectionner un .json dans Fichiers l'ouvre ici — pas de bouton
        # "Ouvrir" séparé (retour user : le FilePicker faisait doublon).
        _liste_file["path"] = path
        _liste_reload()
        _select_surface("liste")

    async def _liste_new_file(event):
        folder = await ft.FilePicker().get_directory_path(
            dialog_title="Dossier pour le nouveau fichier .json")
        if not folder:
            return
        name_field = ft.TextField(
            label="Nom du fichier", value="liste.json", autofocus=True,
            width=280, bgcolor=DARK, border_color=GREY, color=WHITE)

        def _cancel(event):
            dlg.open = False
            page.update()

        def _confirm(event):
            name = (name_field.value or "").strip() or "liste.json"
            if not name.endswith(".json"):
                name += ".json"
            path = _unique_dest(folder, name)
            try:
                with open(path, "w", encoding="utf-8") as f:
                    json.dump([], f)
            except OSError:
                pass
            _liste_file["path"] = path
            dlg.open = False
            page.update()
            _liste_reload()

        dlg = ft.AlertDialog(
            title=ft.Text("Nouveau fichier JSON", size=13, color=WHITE),
            content=name_field,
            actions=[ft.TextButton("Annuler", on_click=_cancel),
                     ft.TextButton("Créer", on_click=_confirm)],
        )
        page.overlay.append(dlg)
        dlg.open = True
        page.update()

    liste_surface = ft.Column([
        ft.Container(
            content=ft.Row([
                ft.Icon(ft.Icons.DATA_OBJECT, color=VIOLET,
                       size=CONSTANTS.ICON_MD),
                liste_path_text,
                ft.IconButton(ft.Icons.NOTE_ADD_OUTLINED, icon_color=YELLOW,
                             icon_size=18, tooltip="Nouveau fichier .json",
                             on_click=_liste_new_file),
                ft.IconButton(ft.Icons.REFRESH, icon_color=BLUE, icon_size=18,
                             tooltip="Recharger depuis le disque",
                             on_click=_liste_reload),
                ft.ElevatedButton("Ajouter", icon=ft.Icons.ADD,
                                  on_click=lambda e: _liste_edit(None)),
            ], spacing=6),
            padding=ft.Padding(8, 8, 8, 0)),
        ft.Container(
            content=ft.Text(
                "Cliquer sur le nom (bleu) copie le nom, cliquer sur la "
                "description (gris) copie la description.",
                size=CONSTANTS.TEXT_XS, color=GREY),
            padding=ft.Padding(8, 0, 8, 4)),
        ft.Divider(height=1, color=GREY),
        ft.Container(content=liste_list_view, expand=True),
    ], expand=True, spacing=0)
    _liste_load()
    _liste_render()

    # ─── Surfaces encore à construire (placeholders structurés) ──────────
    def _placeholder(label):
        return ft.Container(
            content=ft.Text(f"{label} — à venir", size=CONSTANTS.TEXT_MD,
                            color=GREY),
            alignment=ft.Alignment.CENTER, expand=True)

    surface_content = {
        "files": files_surface,
        "liste": liste_surface,
        "ia":    ia_surface,
        "notes": notes_surface,
    }
    center = ft.Container(content=surface_content["files"], expand=True,
                          bgcolor=DARK)

    # ═════════════════════════════════════════════════════════════════════
    #  Rail gauche — onglets verticaux pleine hauteur (icône + texte vertical),
    #  bande colorée (BLUE) sur l'onglet actif, comme la maquette.
    # ═════════════════════════════════════════════════════════════════════
    rail_tabs = {}

    async def _focus_active_surface():
        # Le focus doit toujours être là où on va vraisemblablement taper en
        # premier, sans clic préalable : recherche en Fichiers, dernière
        # ligne du Bloc-notes, champ de l'IA, ou Terminal s'il est déployé
        # (prioritaire sur tout, quel que soit l'onglet actif).
        # Petit délai : sans lui, .focus() peut partir avant que le client
        # ait fini de monter le contrôle qu'on vient d'afficher/échanger
        # (page.update() n'attend pas le rendu) — la cause la plus probable
        # d'un focus qui "marche parfois, parfois pas".
        try:
            await asyncio.sleep(0.08)
            if terminal_panel.visible:
                await terminal_input.focus()
                return
            key = state["surface"]
            if key == "files":
                await search_field.focus()
            elif key == "notes":
                end = len(notes_field.value or "")
                notes_field.selection = ft.TextSelection(
                    base_offset=end, extent_offset=end)
                notes_field.update()
                await notes_field.focus()
            elif key == "ia":
                await ai_input_field.focus()
        except Exception:
            pass

    def _select_surface(key):
        state["surface"] = key
        center.content = surface_content[key]
        for k, tab in rail_tabs.items():
            is_active = k == key
            tab["container"].bgcolor = BLUE if is_active else None
            tab["icon"].color = DARK if is_active else WHITE
            tab["label"].color = DARK if is_active else WHITE
            tab["label"].weight = (ft.FontWeight.W_700 if is_active
                                   else ft.FontWeight.NORMAL)
        page.update()
        page.run_task(_focus_active_surface)

    def _rail_tab(key, label, icon):
        is_active = key == "files"
        icon_ctrl = ft.Icon(icon, size=CONSTANTS.ICON_SM,
                            color=DARK if is_active else WHITE)
        label_ctrl = ft.Text(label, size=CONSTANTS.TEXT_XS,
                             color=DARK if is_active else WHITE, no_wrap=True,
                             weight=ft.FontWeight.W_700 if is_active
                             else ft.FontWeight.NORMAL)
        tab = ft.Container(
            content=ft.Column([
                icon_ctrl,
                ft.Container(content=label_ctrl, rotate=ft.Rotate(-1.5708),
                            alignment=ft.Alignment.CENTER, height=76),
            ], horizontal_alignment=ft.CrossAxisAlignment.CENTER, spacing=4,
               alignment=ft.MainAxisAlignment.CENTER),
            expand=True, alignment=ft.Alignment.CENTER,
            ink=True, on_click=lambda e, k=key: _select_surface(k),
            bgcolor=BLUE if is_active else None,
        )
        rail_tabs[key] = {"container": tab, "icon": icon_ctrl, "label": label_ctrl}
        return tab

    left_rail = ft.Container(
        content=ft.Column([_rail_tab(*s) for s in SURFACES],
                          spacing=0, expand=True),
        width=60, bgcolor=GREY,
    )

    # ═════════════════════════════════════════════════════════════════════
    #  Rail droit — Actions : apps secondaires de Data/ lancées en sous-
    #  processus avec FOLDER_PATH / SELECTED_FILES (même contrat que
    #  Dashboard.pyw : launch_app). Périmètre = outils cités dans le flux de
    #  travail habituel (client + reportage) ; le reste de apps_list de
    #  Dashboard n'est pas encore repris ici.
    # ═════════════════════════════════════════════════════════════════════
    async def _tool_set_status(msg):
        status_left.value = msg
        page.update()

    async def _tool_refresh(folder):
        if folder:
            try:
                _navigate(folder)
            except Exception:
                pass

    def _launch_tool(script_name, is_local=False, extra_env=None):
        app_path = os.path.join(_APP_DIR, "Data", script_name)
        if not os.path.exists(app_path):
            status_left.value = f"Introuvable : {script_name}"
            page.update()
            return
        folder = state["folder"] or ""
        picked = list(selected)
        page.run_task(_tool_set_status, f"▶ Lancement : {script_name}…")

        def _run():
            env = dict(os.environ)
            env["PYTHONIOENCODING"] = "utf-8"
            env["DATA_PATH"] = os.path.join(_APP_DIR, "Data")
            if is_local:
                env["LAUNCHED_FROM_DASHBOARD"] = "1"
                env["SOURCE_FILES"] = "|".join(picked) if picked else folder
            else:
                env["FOLDER_PATH"] = folder
                if picked:
                    env["SELECTED_FILES"] = "|".join(
                        os.path.basename(p) for p in picked)
            if extra_env:
                env.update(extra_env)
            try:
                proc = subprocess.Popen(
                    [sys.executable, app_path], env=env,
                    stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                    text=True, encoding="utf-8", errors="replace")
            except Exception as exc:
                page.run_task(_tool_set_status, f"[Erreur] {script_name} : {exc}")
                return
            # Scripts headless (batch, sans GUI) : bloquer ici (thread dédié,
            # ne gèle pas l'UI) permet de savoir quand c'est vraiment fini —
            # avant ça, aucun retour visuel (« aucune réaction »), le seul
            # signe étaient les fichiers de sortie, invisibles sans rafraîchir.
            output, _ = proc.communicate()
            if proc.returncode != 0:
                tail = (output or "").strip().splitlines()[-1:] or [""]
                page.run_task(_tool_set_status,
                             f"[Erreur] {script_name} (code {proc.returncode}) "
                             f"{tail[0]}")
            else:
                page.run_task(_tool_set_status, f"✓ Terminé : {script_name}")
            page.run_task(_tool_refresh, folder)

        threading.Thread(target=_run, daemon=True).start()
        _close_actions()

    def _launch_renommer_sequence(event=None):
        name_field = ft.TextField(
            label="Nom de la série", hint_text="Ex: Mariage_Martin",
            autofocus=True, width=280, bgcolor=DARK, border_color=GREY,
            color=WHITE)

        def _cancel(e):
            dlg.open = False
            page.update()

        def _confirm(e):
            series = (name_field.value or "").strip()
            dlg.open = False
            page.update()
            _launch_tool("Renommer séquence.py",
                        extra_env={"SERIES_NAME": series})

        name_field.on_submit = _confirm
        dlg = ft.AlertDialog(
            title=ft.Text("Renommer séquence", size=13, color=WHITE),
            content=name_field,
            actions=[ft.TextButton("Annuler", on_click=_cancel),
                     ft.TextButton("Lancer", on_click=_confirm)],
        )
        page.overlay.append(dlg)
        dlg.open = True
        page.update()

    def _launch_two_in_one(event=None):
        def _cancel(e):
            dlg.open = False
            page.update()

        def _pick(val):
            def _on_click(e):
                w, h = val.split("x")
                dlg.open = False
                page.update()
                _launch_tool("2 en 1.py", extra_env={
                    "TWO_IN_ONE_WIDTH": w, "TWO_IN_ONE_HEIGHT": h})
            return _on_click

        buttons = [
            ft.Container(
                content=ft.Text(label, size=14, color=CONSTANTS.COLOR_HOVER_YELLOW,
                                text_align=ft.TextAlign.CENTER),
                bgcolor=GREY, border=ft.Border.all(1, CONSTANTS.COLOR_HOVER_YELLOW),
                border_radius=4, padding=ft.Padding(12, 10, 12, 10), width=280,
                alignment=ft.Alignment.CENTER, ink=True, on_click=_pick(val))
            for label, val in CONSTANTS.TWO_IN_ONE_FORMATS
        ]
        dlg = ft.AlertDialog(
            title=ft.Text("Format 2 en 1", color=WHITE),
            content=ft.Column(buttons, spacing=6, tight=True),
            actions=[ft.TextButton("Annuler", on_click=_cancel)],
            actions_alignment=ft.MainAxisAlignment.END,
        )
        page.overlay.append(dlg)
        dlg.open = True
        page.update()

    def _launch_print(event=None):
        imgs = [p for p in (list(selected) or content["imgs"])
                if os.path.splitext(p)[1].lower() in CONSTANTS.IMAGE_EXTS]
        if not imgs:
            return
        try:
            system = platform.system()
            if system == "Darwin":
                subprocess.call(["open"] + imgs)
            elif system == "Windows":
                for p in imgs:
                    os.startfile(p, "print")
            else:
                for p in imgs:
                    subprocess.Popen(["xdg-open", p])
        except Exception:
            pass
        _close_actions()

    def _launch_bluetooth(event=None):
        try:
            if platform.system() == "Windows":
                subprocess.Popen(["fsquirt.exe", "/Receive"])
            else:
                subprocess.Popen(["open", "-a", "Bluetooth File Exchange"])
        except Exception:
            pass
        _close_actions()

    def _launch_copy_to_selection(event=None):
        paths = list(selected) if selected else content["imgs"]
        if paths:
            _do_copy_to_selection(paths)
        _close_actions()

    def _launch_copy_scored(event=None):
        folder = state["folder"]
        if not folder:
            return

        def _run():
            _copy_scored_photos(folder)
            page.run_task(_actions_refresh_folder)

        threading.Thread(target=_run, daemon=True).start()
        _close_actions()

    async def _actions_refresh_folder():
        if state["folder"]:
            try:
                _navigate(state["folder"])
            except Exception:
                pass

    def _launch_text_prompt(title, label, hint, script_name, env_key):
        field = ft.TextField(label=label, hint_text=hint, autofocus=True,
                             width=280, bgcolor=DARK, border_color=GREY,
                             color=WHITE)

        def _cancel(e):
            dlg.open = False
            page.update()

        def _confirm(e):
            value = (field.value or "").strip()
            dlg.open = False
            page.update()
            _launch_tool(script_name, extra_env={env_key: value})

        field.on_submit = _confirm
        dlg = ft.AlertDialog(
            title=ft.Text(title, size=13, color=WHITE),
            content=field,
            actions=[ft.TextButton("Annuler", on_click=_cancel),
                     ft.TextButton("Lancer", on_click=_confirm)],
        )
        page.overlay.append(dlg)
        dlg.open = True
        page.update()

    def _launch_images_en_pdf(event=None):
        _launch_text_prompt("Images en PDF", "Nom du PDF", "Ex: Album_Mariage",
                            "Images en PDF.py", "PDF_NAME")

    def _launch_number_prompt(title, label, suffix, default, script_name,
                              env_key):
        field = ft.TextField(
            label=label, value=str(default), suffix=ft.Text(suffix, color=GREY),
            autofocus=True, width=200, bgcolor=DARK, border_color=GREY,
            color=WHITE, keyboard_type=ft.KeyboardType.NUMBER)

        def _cancel(e):
            dlg.open = False
            page.update()

        def _confirm(e):
            try:
                value = int((field.value or "").strip())
            except ValueError:
                field.error_text = "Nombre requis"
                page.update()
                return
            dlg.open = False
            page.update()
            _launch_tool(script_name, extra_env={env_key: str(value)})

        field.on_submit = _confirm
        dlg = ft.AlertDialog(
            title=ft.Text(title, size=13, color=WHITE),
            content=field,
            actions=[ft.TextButton("Annuler", on_click=_cancel),
                     ft.TextButton("Lancer", on_click=_confirm)],
        )
        page.overlay.append(dlg)
        dlg.open = True
        page.update()

    def _launch_redimensionner(event=None):
        _launch_number_prompt("Redimensionner", "Dimension max", "px",
                              CONSTANTS.RESIZE_DEFAULT, "Redimensionner.py",
                              "RESIZE_SIZE")

    def _launch_redimensionner_filigrane(event=None):
        _launch_number_prompt("Redimensionner + filigrane", "Dimension max",
                              "px", CONSTANTS.RESIZE_DEFAULT,
                              "Redimensionner filigrane.py",
                              "RESIZE_WATERMARK_SIZE")

    def _launch_compression_web(event=None):
        _launch_number_prompt("Compression web", "Qualité", "%",
                              CONSTANTS.WEB_QUALITY, "Compression web.py",
                              "WEB_QUALITY")

    def _launch_grain_pellicule(event=None):
        C = CONSTANTS

        def _num(env_key, label, default):
            return env_key, ft.TextField(
                label=label, value=str(default), width=140, bgcolor=DARK,
                border_color=GREY, color=WHITE,
                keyboard_type=ft.KeyboardType.NUMBER)

        def _section(label, color, sw_default, field_specs):
            sw = ft.Switch(value=sw_default, active_color=color)
            fields = [_num(*spec) for spec in field_specs]
            tile = ft.ExpansionTile(
                title=ft.Text(label, color=color, weight=ft.FontWeight.W_600,
                             size=CONSTANTS.TEXT_SM),
                leading=sw,
                controls=[ft.Container(
                    content=ft.Column([f for _, f in fields], spacing=8),
                    padding=ft.Padding(16, 4, 16, 12))],
            )
            return tile, sw, fields

        tile1, sw1, f1 = _section("Grain — Couche 1", ORANGE, True, [
            ("GRAIN_AMOUNT", "Intensité", C.GRAIN_AMOUNT),
            ("GRAIN_SIZE", "Taille", C.GRAIN_SIZE),
            ("GRAIN_COLOR_RATIO", "Part couleur", C.GRAIN_COLOR_RATIO),
            ("GRAIN_SHADOW_BOOST", "Concentration mi-tons",
             C.GRAIN_SHADOW_BOOST),
            ("GRAIN_CHROMA_SHIFT", "Décalage inter-canal",
             C.GRAIN_CHROMA_SHIFT),
        ])
        tile2, sw2, f2 = _section("Grain — Couche 2", ORANGE, False, [
            ("GRAIN2_AMOUNT", "Intensité", C.GRAIN2_AMOUNT),
            ("GRAIN2_SIZE", "Taille", C.GRAIN2_SIZE),
            ("GRAIN2_COLOR_RATIO", "Part couleur", C.GRAIN2_COLOR_RATIO),
            ("GRAIN2_SHADOW_BOOST", "Concentration mi-tons",
             C.GRAIN2_SHADOW_BOOST),
            ("GRAIN2_CHROMA_SHIFT", "Décalage inter-canal",
             C.GRAIN2_CHROMA_SHIFT),
        ])
        tile3, sw3, f3 = _section("Halation", RED, C.HALATION_ENABLED, [
            ("HALATION_THRESHOLD", "Seuil", C.HALATION_THRESHOLD),
            ("HALATION_RADIUS", "Rayon", C.HALATION_RADIUS),
            ("HALATION_INTENSITY", "Intensité", C.HALATION_INTENSITY),
            ("HALATION_RED_SHIFT", "Décalage rouge", C.HALATION_RED_SHIFT),
        ])
        tile4, sw4, f4 = _section("Bloom (Soft Light)", BLUE,
                                  C.BLOOM_ENABLED, [
            ("BLOOM_RADIUS", "Rayon", C.BLOOM_RADIUS),
            ("BLOOM_INTENSITY", "Intensité", C.BLOOM_INTENSITY),
        ])
        tile5, sw5, f5 = _section("Désaturation des extrêmes", VIOLET,
                                  C.DESAT_ENABLED, [
            ("DESAT_SHADOW_THRESHOLD", "Seuil ombres",
             C.DESAT_SHADOW_THRESHOLD),
            ("DESAT_SHADOW_INTENSITY", "Intensité ombres",
             C.DESAT_SHADOW_INTENSITY),
            ("DESAT_HIGHLIGHT_THRESHOLD", "Seuil HL",
             C.DESAT_HIGHLIGHT_THRESHOLD),
            ("DESAT_HIGHLIGHT_INTENSITY", "Intensité HL",
             C.DESAT_HIGHLIGHT_INTENSITY),
            ("DESAT_MIDTONE_BOOST", "Boost mi-tons", C.DESAT_MIDTONE_BOOST),
        ])
        tile6, sw6, f6 = _section("Courbe tonale", GREEN, C.CURVE_ENABLED, [
            ("CURVE_SHOULDER_START", "Seuil épaulement",
             C.CURVE_SHOULDER_START),
            ("CURVE_SHOULDER_STRENGTH", "Force épaulement",
             C.CURVE_SHOULDER_STRENGTH),
            ("CURVE_TOE_START", "Seuil pied", C.CURVE_TOE_START),
            ("CURVE_TOE_LIFT", "Relèvement pied", C.CURVE_TOE_LIFT),
        ])
        tile7, sw7, f7 = _section("Aberrations chromatiques", YELLOW,
                                  C.CA_ENABLED, [
            ("CA_STRENGTH", "Intensité", C.CA_STRENGTH),
            ("CA_AXIAL_RATIO", "Ratio axial", C.CA_AXIAL_RATIO),
        ])

        def _cancel(e):
            dlg.open = False
            page.update()

        def _confirm(e):
            env = {key: field.value for key, field in f1}
            env["GRAIN1_ENABLED"] = "1" if sw1.value else "0"
            if sw2.value:
                env.update({key: field.value for key, field in f2})
            env["HALATION_ENABLED"] = "1" if sw3.value else "0"
            env.update({key: field.value for key, field in f3})
            env["BLOOM_ENABLED"] = "1" if sw4.value else "0"
            env.update({key: field.value for key, field in f4})
            env["DESAT_ENABLED"] = "1" if sw5.value else "0"
            env.update({key: field.value for key, field in f5})
            env["CURVE_ENABLED"] = "1" if sw6.value else "0"
            env.update({key: field.value for key, field in f6})
            env["CA_ENABLED"] = "1" if sw7.value else "0"
            env.update({key: field.value for key, field in f7})
            dlg.open = False
            page.update()
            _launch_tool("Grain pellicule.py", extra_env=env)

        dlg = ft.AlertDialog(
            title=ft.Text("Grain pellicule — paramètres", size=13,
                         color=WHITE),
            content=ft.Column(
                [ft.Text("Les valeurs par défaut viennent de CONSTANTS.py "
                         "(section 12).", size=CONSTANTS.TEXT_XS, color=GREY),
                 tile1, tile2, tile3, tile4, tile5, tile6, tile7],
                spacing=4, tight=True, scroll=ft.ScrollMode.AUTO,
                width=340, height=420),
            actions=[ft.TextButton("Annuler", on_click=_cancel),
                     ft.TextButton("Lancer", on_click=_confirm)],
        )
        page.overlay.append(dlg)
        dlg.open = True
        page.update()

    def _launch_kiosk(tariff, event=None):
        # Sélection curatée obligatoire (HUB_SPEC §9) : la sélection en
        # cours si non vide, sinon toutes les photos du dossier ouvert —
        # jamais un dossier "à trou" laissé au listing libre du kiosque.
        folder = state["folder"]
        if not folder:
            status_left.value = "Ouvrez d'abord un dossier."
            page.update()
            return
        picked = [p for p in selected if p in content["imgs"]]
        names = ([os.path.basename(p) for p in picked] if picked
                else [os.path.basename(p) for p in content["imgs"]])
        if not names:
            status_left.value = "Aucune photo dans ce dossier."
            page.update()
            return
        kiosk_path = os.path.join(_APP_DIR, "Data", "kiosk_flet.pyw")
        env = dict(os.environ)
        env["PYTHONIOENCODING"] = "utf-8"
        env["FOLDER_PATH"] = folder
        env["SELECTED_FILES"] = "|".join(names)
        env["TARIFF_TYPE"] = tariff
        page.run_task(_tool_set_status, "▶ Lancement du kiosque…")

        def _run():
            try:
                subprocess.Popen([sys.executable, kiosk_path], env=env)
            except Exception as exc:
                page.run_task(_tool_set_status, f"[Erreur] Kiosque : {exc}")
                return
            page.run_task(_tool_set_status, "✓ Kiosque lancé")

        threading.Thread(target=_run, daemon=True).start()
        _close_actions()

    def _launch_recadrage_auto(event=None):
        default_fmt = "10x15"
        default_w, default_h = CONSTANTS.FORMATS[default_fmt]
        manual = {"value": False}

        fmt_dd = ft.Dropdown(
            options=[ft.dropdown.Option(name) for name in CONSTANTS.FORMATS],
            value=default_fmt, width=280, bgcolor=DARK, border_color=GREY,
            color=WHITE)
        width_field = ft.TextField(
            label="Largeur (mm)", value=str(default_w), width=132,
            bgcolor=DARK, border_color=GREY, color=WHITE, disabled=True,
            keyboard_type=ft.KeyboardType.NUMBER)
        height_field = ft.TextField(
            label="Hauteur (mm)", value=str(default_h), width=132,
            bgcolor=DARK, border_color=GREY, color=WHITE, disabled=True,
            keyboard_type=ft.KeyboardType.NUMBER)
        manual_switch = ft.Switch(label="Saisie manuelle (mm)", value=False)
        fit_switch = ft.Switch(label="Fit 100% (sans rognage)", value=False)
        white_border_switch = ft.Switch(label="Bord blanc 5mm", value=False)
        scope_text = ft.Text(
            f"Portée auto : {'sélection en cours' if selected else 'tout le dossier'}",
            size=CONSTANTS.TEXT_XS, color=GREY)

        def _on_manual_change(e):
            manual["value"] = manual_switch.value
            fmt_dd.disabled = manual["value"]
            width_field.disabled = not manual["value"]
            height_field.disabled = not manual["value"]
            page.update()

        manual_switch.on_change = _on_manual_change

        def _cancel(e):
            dlg.open = False
            page.update()

        def _confirm(e):
            if manual["value"]:
                try:
                    w = int(width_field.value)
                    h = int(height_field.value)
                except (TypeError, ValueError):
                    width_field.error_text = "Nombre requis"
                    page.update()
                    return
            else:
                w, h = CONSTANTS.FORMATS[fmt_dd.value]
            dlg.open = False
            page.update()
            _launch_tool("Recadrage automatique.py", extra_env={
                "FORCE_CROP_SIZE": f"{w}x{h}",
                "FORCE_CROP_SCOPE": "selected" if selected else "folder",
                "FORCE_CROP_FIT": "1" if fit_switch.value else "0",
                "FORCE_CROP_WHITE_BORDER":
                    "1" if white_border_switch.value else "0",
            })

        dlg = ft.AlertDialog(
            title=ft.Text("Recadrage automatique — format", size=13,
                         color=WHITE),
            content=ft.Column([
                fmt_dd,
                ft.Container(
                    content=ft.Column([manual_switch,
                                       ft.Row([width_field, height_field],
                                              spacing=8)]),
                    border=ft.Border.all(1, GREY), border_radius=8,
                    padding=10),
                fit_switch, white_border_switch, scope_text,
            ], spacing=12, tight=True, width=300),
            actions=[ft.TextButton("Annuler", on_click=_cancel),
                     ft.TextButton("Lancer", on_click=_confirm)],
        )
        page.overlay.append(dlg)
        dlg.open = True
        page.update()

    def _launch_copyright(event=None):
        custom_field = ft.TextField(
            prefix="© ", visible=False, width=280, bgcolor=DARK,
            border_color=GREY, color=WHITE)
        mode = {"value": "date"}

        def _pick(m):
            def _on_click(e):
                mode["value"] = m
                custom_field.visible = (m == "custom")
                for btn in options_row.controls:
                    btn.border = ft.Border.all(2, BLUE if btn.data == m
                                               else GREY)
                page.update()
            return _on_click

        def _option(m, icon, label):
            return ft.Container(
                data=m,
                content=ft.Column(
                    [ft.Icon(icon, size=20, color=BLUE),
                     ft.Text(label, size=CONSTANTS.TEXT_XS, color=WHITE,
                             text_align=ft.TextAlign.CENTER)],
                    horizontal_alignment=ft.CrossAxisAlignment.CENTER,
                    spacing=4, tight=True),
                bgcolor=DARK, border=ft.Border.all(2, BLUE if m == "date"
                                                   else GREY),
                border_radius=8, padding=10, width=90, height=70,
                ink=True, on_click=_pick(m),
            )

        options_row = ft.Row(
            [_option("date", ft.Icons.CALENDAR_TODAY_OUTLINED, "Date"),
             _option("filename", ft.Icons.INSERT_DRIVE_FILE_OUTLINED,
                     "Nom fichier"),
             _option("custom", ft.Icons.EDIT_OUTLINED, "Personnalisé")],
            spacing=8, alignment=ft.MainAxisAlignment.CENTER,
        )

        def _cancel(e):
            dlg.open = False
            page.update()

        def _confirm(e):
            custom = (custom_field.value or "").strip()
            if mode["value"] == "custom" and not custom:
                custom_field.error_text = "Requis"
                page.update()
                return
            dlg.open = False
            page.update()
            _launch_tool("Copyright.py", extra_env={
                "COPYRIGHT_MODE": mode["value"],
                "COPYRIGHT_CUSTOM": custom,
            })

        dlg = ft.AlertDialog(
            title=ft.Text("Copyright", size=13, color=WHITE),
            content=ft.Column([options_row, custom_field], spacing=10,
                              tight=True),
            actions=[ft.TextButton("Annuler", on_click=_cancel),
                     ft.TextButton("Lancer", on_click=_confirm)],
        )
        page.overlay.append(dlg)
        dlg.open = True
        page.update()

    # (label, icône, couleur, handler)
    # Catégories = les regroupements du flux de travail réel (cf. mémoire
    # project_business_workflow), pas les intitulés génériques de la
    # maquette (celle-ci utilisait des actions fictives) — Bluetooth et
    # Imprimer n'y sont plus : remontés dans la barre de titre (accès global).
    _ACTION_CATEGORIES = [
        ("Transfert & préparation", [
            ("Transfert vers TEMP", ft.Icons.DRIVE_FILE_MOVE_OUTLINED, BLUE,
             lambda e: _launch_tool("Transfert vers TEMP.py", is_local=True)),
            ("Conversion JPG", ft.Icons.IMAGE_OUTLINED, BLUE,
             lambda e: _launch_tool("Conversion JPG.py")),
            ("Renommer séquence", ft.Icons.SORT_BY_ALPHA, BLUE,
             _launch_renommer_sequence),
            ("Séparer RAW et JPG", ft.Icons.HIDE_IMAGE_OUTLINED, BLUE,
             lambda e: _launch_tool("Séparer RAW et JPG.py")),
        ]),
        ("Sélection", [
            ("Copier sélection → SELECTION", ft.Icons.FOLDER_COPY_OUTLINED, YELLOW,
             _launch_copy_to_selection),
            ("Copier NEFs → SELECTION", ft.Icons.IMAGE_SEARCH_OUTLINED, YELLOW,
             lambda e: _launch_tool("Copier NEFs sélection.py")),
            ("Copier selon score IA → SELECTION",
             ft.Icons.WORKSPACE_PREMIUM_OUTLINED, YELLOW, _launch_copy_scored),
            ("Fichiers identiques", ft.Icons.CONTENT_COPY, YELLOW,
             lambda e: _launch_tool("Fichiers identiques.py")),
        ]),
        ("Recadrage & impression", [
            ("Recadrage automatique", ft.Icons.CROP, GREEN,
             _launch_recadrage_auto),
            ("Recadrage manuel", ft.Icons.CROP_FREE, RED,
             lambda e: _launch_tool("Recadrage manuel.pyw")),
            ("2 en 1", ft.Icons.FILTER_2, GREEN, _launch_two_in_one),
        ]),
        ("Kiosque (mode client)", [
            ("Kiosque — Studios", ft.Icons.STOREFRONT_OUTLINED, VIOLET,
             lambda e: _launch_kiosk("STUDIOS", e)),
            ("Kiosque — Tirages", ft.Icons.LOCAL_PRINTSHOP_OUTLINED, VIOLET,
             lambda e: _launch_kiosk("PRINTS", e)),
        ]),
        ("Retouche", [
            ("Augmentation IA", ft.Icons.AUTO_FIX_HIGH_OUTLINED, VIOLET,
             lambda e: _launch_tool("Augmentation IA.py")),
            ("Grain pellicule", ft.Icons.GRAIN, VIOLET,
             _launch_grain_pellicule),
            ("N&B", ft.Icons.MONOCHROME_PHOTOS_OUTLINED, VIOLET,
             lambda e: _launch_tool("N&B.py")),
            ("Améliorer netteté", ft.Icons.AUTO_GRAPH, VIOLET,
             lambda e: _launch_tool("Améliorer netteté.py")),
            ("Débruiter", ft.Icons.BLUR_ON, VIOLET,
             lambda e: _launch_tool("Débruiter.py")),
            ("Comparaison", ft.Icons.COMPARE_OUTLINED, VIOLET,
             lambda e: _launch_tool("Comparaison.pyw")),
        ]),
        ("Export & livrables", [
            ("Redimensionner", ft.Icons.PHOTO_SIZE_SELECT_LARGE_OUTLINED, ORANGE,
             _launch_redimensionner),
            ("Redimensionner filigrane", ft.Icons.BRANDING_WATERMARK_OUTLINED,
             ORANGE, _launch_redimensionner_filigrane),
            ("Compression web", ft.Icons.COMPRESS_OUTLINED, ORANGE,
             _launch_compression_web),
            ("Images en PDF", ft.Icons.PICTURE_AS_PDF_OUTLINED, ORANGE,
             _launch_images_en_pdf),
            ("Remerciements", ft.Icons.CARD_GIFTCARD_OUTLINED, ORANGE,
             lambda e: _launch_tool("Remerciements.py")),
            ("Copyright", ft.Icons.COPYRIGHT_OUTLINED, ORANGE,
             _launch_copyright),
            ("Nettoyer métadonnées", ft.Icons.CLEANING_SERVICES_OUTLINED, ORANGE,
             lambda e: _launch_tool("Nettoyer metadonnées.py")),
        ]),
    ]

    def _action_card(label, icon, color, handler):
        return ft.Container(
            content=ft.Column([
                ft.Icon(icon, color=color, size=CONSTANTS.ICON_MD),
                ft.Text(label, size=CONSTANTS.TEXT_SM, color=WHITE,
                        text_align=ft.TextAlign.CENTER, max_lines=2,
                        overflow=ft.TextOverflow.ELLIPSIS),
            ], horizontal_alignment=ft.CrossAxisAlignment.CENTER, spacing=8,
               alignment=ft.MainAxisAlignment.CENTER),
            width=150, height=120, padding=10, border_radius=10,
            bgcolor=GREY, border=ft.Border.all(1, color),
            ink=True, on_click=handler,
        )

    _ACTION_GRID_COLUMNS = 6

    def _action_category(label, tools):
        # Colonnes fixes (`runs_count`, pas `max_extent`) : le nombre de
        # colonnes réel ne dépend plus de la largeur de fenêtre au moment du
        # rendu, donc `rows` est exact et la hauteur ne laisse plus de grand
        # vide sous les catégories qui ont peu d'outils (l'ancien calcul
        # supposait 3 colonnes alors que `max_extent` en affichait souvent
        # 6-7 sur une fenêtre large — d'où les écarts irréguliers).
        rows = (len(tools) - 1) // _ACTION_GRID_COLUMNS + 1
        grid = ft.GridView(runs_count=_ACTION_GRID_COLUMNS,
                           child_aspect_ratio=150 / 120,
                           spacing=10, run_spacing=10, height=rows * 132)
        grid.controls = [_action_card(*t) for t in tools]
        # Libellé de catégorie en ORANGE (pas GREY) : GREY sur le fond DARK
        # de l'overlay est quasi illisible, deux gris trop proches en
        # luminance — cf. retour user.
        return ft.Column([
            ft.Text(label.upper(), size=CONSTANTS.TEXT_XS, color=ORANGE,
                    weight=ft.FontWeight.W_700),
            grid,
        ], spacing=6)

    # Overlay plein écran (même primitive que viewer_overlay : Container
    # expand=True ajouté à page.overlay, hors de l'arbre de mise en page
    # normal) plutôt qu'un AlertDialog dimensionné en dur.
    actions_overlay = ft.Container(
        content=ft.Column([
            ft.Row([
                ft.Icon(ft.Icons.BOLT_OUTLINED, color=ORANGE,
                       size=CONSTANTS.ICON_MD),
                ft.Text("Actions", size=18, color=WHITE,
                       weight=ft.FontWeight.W_700, expand=True),
                ft.IconButton(ft.Icons.CLOSE, icon_color=RED, icon_size=22,
                             on_click=lambda e: _close_actions(),
                             tooltip="Fermer"),
            ], spacing=10),
            ft.Divider(height=1, color=GREY),
            ft.Column(
                [_action_category(label, tools)
                 for label, tools in _ACTION_CATEGORIES],
                spacing=20, scroll=ft.ScrollMode.AUTO, expand=True),
        ], spacing=12, expand=True),
        bgcolor=DARK, padding=20, expand=True,
    )

    def _close_actions(event=None):
        if actions_overlay in page.overlay:
            page.overlay.remove(actions_overlay)
        page.update()
        page.run_task(_focus_active_surface)

    def _open_actions(event):
        if actions_overlay not in page.overlay:
            page.overlay.append(actions_overlay)
        page.update()

    # ═════════════════════════════════════════════════════════════════════
    #  Terminal intégré — exécute une commande shell dans le dossier ouvert
    #  (même logique multiplateforme que Dashboard.pyw:4610-4666 : PowerShell
    #  sur Windows, zsh/bash ailleurs). Toute mise à jour UI passe par
    #  page.run_task (thread d'exécution -> cf. feedback_flet_rendering_gotchas
    #  point 5) ; ponytail : pas de debounce des mises à jour comme Dashboard
    #  (threading.Timer + lock), un run_task par ligne suffit à ce volume.
    # ═════════════════════════════════════════════════════════════════════
    terminal_output = ft.ListView(expand=True, spacing=2, auto_scroll=True)
    terminal_input = ft.TextField(
        hint_text="> Terminal", bgcolor=DARK, border_color=GREY, color=WHITE,
        text_size=CONSTANTS.TERMINAL_FONT_SIZE, expand=True,
        content_padding=ft.Padding(10, 8, 10, 8))

    def _log_to_terminal(message, color=None):
        message = (message or "").strip()
        if not message:
            return

        async def _do():
            terminal_output.controls.append(
                ft.Text(message, size=CONSTANTS.TERMINAL_FONT_SIZE,
                        color=color or WHITE, font_family="monospace",
                        selectable=True))
            if len(terminal_output.controls) > 1000:
                terminal_output.controls.pop(0)
            page.update()

        page.run_task(_do)

    def _exec_terminal_command(command_text):
        cwd = state["folder"] or _APP_DIR
        _log_to_terminal(f"> {command_text}", YELLOW)

        def _run():
            try:
                system = platform.system()
                if system == "Windows":
                    popen_kwargs = dict(
                        args=["powershell", "-NoProfile", "-NonInteractive",
                              "-Command", command_text],
                        shell=False)
                else:
                    shell_exe = ("/bin/zsh" if os.path.exists("/bin/zsh")
                                 else "/bin/bash")
                    popen_kwargs = dict(args=command_text, shell=True,
                                        executable=shell_exe)
                proc = subprocess.Popen(
                    **popen_kwargs, stdout=subprocess.PIPE,
                    stderr=subprocess.STDOUT, text=True, encoding="utf-8",
                    errors="replace", cwd=cwd)
                killed = {"value": False}

                def _kill_on_timeout():
                    if proc.poll() is None:
                        killed["value"] = True
                        proc.kill()
                        _log_to_terminal(
                            "[ERREUR] Commande interrompue (délai dépassé 30s)",
                            RED)

                watchdog = threading.Timer(30.0, _kill_on_timeout)
                watchdog.daemon = True
                watchdog.start()
                try:
                    had_output = False
                    for line in iter(proc.stdout.readline, ""):
                        if line.strip():
                            _log_to_terminal(line)
                            had_output = True
                    proc.wait()
                    if not killed["value"]:
                        if proc.returncode != 0:
                            _log_to_terminal(
                                f"[code retour {proc.returncode}]", RED)
                        elif not had_output:
                            _log_to_terminal("[aucun résultat]", GREY)
                finally:
                    watchdog.cancel()
            except FileNotFoundError:
                _log_to_terminal(f"[ERREUR] Dossier introuvable : {cwd}", RED)
            except Exception as error:
                _log_to_terminal(f"[ERREUR] {error}", RED)

        threading.Thread(target=_run, daemon=True).start()

    def _on_terminal_submit(event=None):
        command_text = (terminal_input.value or "").strip()
        if not command_text:
            return
        terminal_input.value = ""
        page.update()
        _exec_terminal_command(command_text)

    terminal_input.on_submit = _on_terminal_submit

    terminal_panel = ft.Container(
        content=ft.Column([
            ft.Container(content=terminal_output, expand=True, padding=8),
            ft.Container(content=ft.Row([terminal_input]),
                        padding=ft.Padding(8, 0, 8, 8)),
        ], spacing=0, expand=True),
        bgcolor=DARK, height=200, visible=False,
        border=ft.Border(top=ft.BorderSide(2, ORANGE)),
    )

    # ═════════════════════════════════════════════════════════════════════
    #  Barre d'état — Terminal (centre) + curseur Taille (droite)
    # ═════════════════════════════════════════════════════════════════════
    status_left = ft.Text("", size=CONSTANTS.TEXT_XS, color=WHITE, expand=True)

    def _toggle_terminal(event):
        terminal_panel.visible = not terminal_panel.visible
        page.update()
        page.run_task(_focus_active_surface)

    statusbar = ft.Container(
        content=ft.Row([
            status_left,
            ft.TextButton(
                content=ft.Row([
                    ft.Icon(ft.Icons.TERMINAL, size=CONSTANTS.ICON_SM, color=WHITE),
                    ft.Text("Terminal", size=CONSTANTS.TEXT_XS, color=WHITE),
                ], spacing=6, tight=True),
                on_click=_toggle_terminal,
            ),
            ft.Container(
                content=ft.Row([
                    ft.Icon(ft.Icons.PHOTO_SIZE_SELECT_LARGE, size=16, color=WHITE),
                    ft.Slider(min=90, max=260, value=state["thumb_size"], width=120,
                              active_color=BLUE,
                              on_change=lambda e: _apply_thumb_size(e.control.value)),
                ], spacing=4, tight=True),
                expand=True, alignment=ft.Alignment.CENTER_RIGHT,
            ),
        ], vertical_alignment=ft.CrossAxisAlignment.CENTER),
        height=40, padding=ft.Padding(12, 0, 12, 0), bgcolor=GREY,
    )

    # ═════════════════════════════════════════════════════════════════════
    #  Barre de titre (sans cadre) + assemblage
    # ═════════════════════════════════════════════════════════════════════
    async def _close(event):
        await page.window.close()

    def _minimize(event):
        page.window.minimized = True

    def _toggle_maximize(event):
        page.window.maximized = not page.window.maximized
        page.update()

    def _on_window_event(event):
        if event.data == "close":
            os._exit(0)

    page.window.on_event = _on_window_event

    titlebar = ft.WindowDragArea(
        ft.Row([
            ft.Container(
                content=ft.Row([
                    ft.Icon(ft.Icons.HUB_OUTLINED, color=ORANGE, size=18),
                    ft.Text(f"HUB  {__version__}", size=CONSTANTS.TEXT_LG,
                            color=WHITE, weight=ft.FontWeight.W_500),
                ], spacing=6),
                padding=ft.Padding(12, 0, 0, 0),
            ),
            ft.Container(expand=True),
            # Accès tactile : toujours visibles, quelle que soit la surface
            # active (écran tactile = pas de fallback clavier/raccourci).
            ft.Container(
                content=ft.Row([
                    ft.IconButton(ft.Icons.BLUETOOTH, icon_size=16,
                                 icon_color=BLUE, on_click=_launch_bluetooth,
                                 tooltip="Recevoir un fichier via Bluetooth"),
                    ft.IconButton(ft.Icons.PRINT_OUTLINED, icon_size=16,
                                 icon_color=ORANGE, on_click=_launch_print,
                                 tooltip="Imprimer la sélection (ou le dossier)"),
                ], spacing=0, tight=True),
                border=ft.Border.all(1, ORANGE), border_radius=8,
                margin=ft.Margin(0, 0, 8, 0),
            ),
            ft.Row([
                ft.IconButton(ft.Icons.REMOVE, icon_size=16, icon_color=YELLOW,
                              on_click=_minimize, tooltip="Réduire"),
                ft.IconButton(ft.Icons.FULLSCREEN, icon_size=16, icon_color=BLUE,
                              on_click=_toggle_maximize,
                              tooltip="Maximiser / Restaurer"),
                ft.IconButton(ft.Icons.CLOSE, icon_size=16, icon_color=RED,
                              on_click=_close, tooltip="Fermer"),
            ], spacing=0),
        ], vertical_alignment=ft.CrossAxisAlignment.CENTER),
    )

    page.add(ft.Column([
        titlebar,
        ft.Divider(height=1, color=GREY),
        ft.Row([left_rail, center], expand=True, spacing=0),
        terminal_panel,
        statusbar,
    ], expand=True, spacing=0))
    page.run_task(_focus_active_surface)


if __name__ == "__main__":
    ft.run(main)
