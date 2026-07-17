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
import concurrent.futures
import datetime
import hashlib
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
import webbrowser
import zipfile
from types import SimpleNamespace

import flet as ft
import flet.canvas as ftcv
import flet_code_editor as fce
from PIL import Image as PILImage, ImageDraw as PILImageDraw, ImageOps as PILImageOps

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
    _format_ai_conversation,
    _ai_save_history, _MicRecorder, _gemini_transcribe_audio,
    _update_memory_file, _iterate_image_loop, _IMAGE_ITERATE_TOOLS,
    _gemini_generate_image, _gemini_generate_music, _gemini_refine_image_prompt,
    _score_images_batched, _analyze_images_batched, _take_screenshot,
)


# ── Surfaces déclarées une fois : clé, libellé, icône ────────────────────
SURFACES = [
    ("files", "Fichiers", ft.Icons.PHOTO_LIBRARY_OUTLINED),
    ("liste", "Liste",    ft.Icons.LIST_ALT_OUTLINED),
    ("ia",    "IA",       ft.Icons.SMART_TOY_OUTLINED),
    ("notes", "Notes",    ft.Icons.EDIT_NOTE_OUTLINED),
]

# Hauteur de fenêtre en mode bandeau (strip mode) — juste assez pour la
# barre de titre. Même valeur que Dashboard.pyw (CONSTANTS.WDA_HEIGHT) :
# 64 tronquait les boutons tactiles (HUB_TITLEBAR_TAP_HEIGHT=48 + bordure)
# une fois la fenêtre réduite à cette hauteur (retour user).
STRIP_HEIGHT = CONSTANTS.WDA_HEIGHT

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


# Même fichier que Dashboard.pyw:280 (open_with_config_file_path) : la
# liste de programmes "Ouvrir avec" est partagée entre les deux apps.
_OPEN_WITH_FILE = os.path.join(_APP_DIR, "open_with.json")


def _load_open_with_programs():
    try:
        with open(_OPEN_WITH_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        return [p for p in data if isinstance(p, dict) and "label" in p and "exe" in p]
    except Exception:
        return []


def _save_open_with_programs(programs):
    try:
        with open(_OPEN_WITH_FILE, "w", encoding="utf-8") as f:
            json.dump(programs, f, ensure_ascii=False, indent=2)
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


# Même fichier que Dashboard.pyw:310 (recadrage_auto_config_path) : le
# dernier format utilisé pour "Recadrage automatique" est partagé.
_CROP_AUTO_FILE = os.path.join(_APP_DIR, ".recadrage_auto_config.json")


def _load_crop_auto_config():
    try:
        with open(_CROP_AUTO_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def _save_crop_auto_config(config):
    try:
        with open(_CROP_AUTO_FILE, "w", encoding="utf-8") as f:
            json.dump(config, f, ensure_ascii=False, indent=2)
    except Exception:
        pass


_ORDER_BW_FILE = os.path.join(_APP_DIR, ".order_bw.json")


def _load_order_bw():
    # photo (chemin absolu) -> True si la commande doit être tirée en N&B.
    # Fichier séparé de .order.json : {format: nombre} n'a pas de place
    # naturelle pour un booléen sans fausser _order_lines/_order_totals.
    try:
        with open(_ORDER_BW_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        return {p: bool(v) for p, v in data.items() if v}
    except Exception:
        return {}


def _save_order_bw(order_bw):
    try:
        with open(_ORDER_BW_FILE, "w", encoding="utf-8") as f:
            json.dump(order_bw, f, ensure_ascii=False, indent=2)
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
    page.window.width  = CONSTANTS.WINDOW_WIDTH
    page.window.height = CONSTANTS.WINDOW_HEIGHT
    # macOS ignore `maximized=True` tant que la fenêtre n'est pas encore
    # affichée -> False ici, True après coup (cf. _delayed_maximize plus
    # bas), même séquence que Dashboard.pyw:183-186/10874-10883.
    if platform.system() == "Darwin" and CONSTANTS.MAXIMIZED:
        page.window.maximized = False
    else:
        page.window.maximized = CONSTANTS.MAXIMIZED
    page.run_task(page.window.to_front)

    # ─── État partagé ────────────────────────────────────────────────────
    state = {"surface": "files", "folder": None, "view": "grid",
             "thumb_size": 320, "thumb_token": 0,
             "sort": "date", "search": "", "only_selected": False,
             "last_selected": None}
    _strip_state = {"active": False, "saved_height": CONSTANTS.WINDOW_HEIGHT,
                    "was_maximized": False}
    content = {"dirs": [], "imgs": [], "other": []}   # non filtrés
    # Liste (pas un set) — ordre de clic préservé, comme Dashboard.pyw
    # (selected_files) : "Renommer séquence" numérote dans cet ordre-là
    # quand une sélection est fournie (retour user).
    selected = []                        # chemins sélectionnés (images + dossiers)
    clipboard = {"paths": [], "mode": None}   # mode: "copy" | "cut" | None

    def _select_add(path):
        if path not in selected:
            selected.append(path)

    def _select_discard(path):
        if path in selected:
            selected.remove(path)

    def _select_update(paths):
        for p in paths:
            _select_add(p)
    # Compteur de suspension des raccourcis clavier (recherche/terminal
    # focus) — même principe que Dashboard.pyw (_suspend/_resume_keyboard_
    # shortcuts), via on_focus/on_blur plutôt qu'un appel manuel.
    _kb_suspend = {"count": 0}

    def _suspend_kb(event=None):
        _kb_suspend["count"] += 1

    def _resume_kb(event=None):
        _kb_suspend["count"] = max(0, _kb_suspend["count"] - 1)

    # Historique des saisies façon shell (Terminal, chat IA) : Flèche haut
    # rappelle les entrées précédemment soumises, Flèche bas revient vers
    # les plus récentes puis vers un champ vide. `_focused_input["name"]`
    # suit quel champ a le focus car page.on_keyboard_event est global
    # (Flet 0.85 n'expose pas d'event clavier par contrôle).
    _input_history = {"terminal": [], "ai": []}
    _history_idx = {"terminal": None, "ai": None}
    _focused_input = {"name": None}

    def _history_add(name, text):
        text = text.strip()
        if not text:
            return
        hist = _input_history[name]
        if not hist or hist[-1] != text:
            hist.append(text)
        _history_idx[name] = None

    def _history_navigate(name, key, field):
        hist = _input_history[name]
        if not hist:
            return
        idx = _history_idx[name]
        if key in ("Arrow Up", "ArrowUp"):
            idx = len(hist) - 1 if idx is None else max(0, idx - 1)
        else:
            if idx is None:
                return
            idx = idx + 1 if idx + 1 < len(hist) else None
        _history_idx[name] = idx
        field.value = "" if idx is None else hist[idx]
        end = len(field.value)
        field.selection = ft.TextSelection(base_offset=end, extent_offset=end)
        field.update()
    thumb_mem = {}                       # cache mémoire path -> bytes miniature
    card_icon_refs = []                  # Icon des cartes dossier/fichier en
                                          # vue vignettes, pour un resize live
                                          # avec le curseur (cf. _card_icon_size)
    list_visual_refs = []                # (Container, Icon|None) des lignes
                                          # de la vue liste, même resize live
    grid_card_refs = {}                  # path -> Container carte vignette,
                                          # pour recolorer la bordure de
                                          # sélection sans reconstruire toute
                                          # la grille (cf. _set_selected)
    # Mode commande : path -> {format: nombre} — une photo peut avoir
    # plusieurs formats commandés. Édition via un clic sur la vignette
    # (badge « N tailles ») qui ouvre un petit dialogue, pas de clic droit.
    order = _load_order()
    order_bw = _load_order_bw()
    order_mode = {"value": False}
    _ORDER_TARIFF = CONSTANTS.PRINTS

    # ═════════════════════════════════════════════════════════════════════
    #  Surface Fichiers (Explorateur) — liste ⇄ vignettes + sélection
    # ═════════════════════════════════════════════════════════════════════
    # Copie du champ de Dashboard.pyw:404-411 (label flottant natif Flet,
    # pas de height/dense/content_padding imposés) — accepte donc une
    # hauteur de ligne naturelle, potentiellement > CONSTANTS.HUB_TOOLBAR_H
    # (retour user : voulait explicitement ce style-là, pas une variante
    # compacte).
    files_path = ft.TextField(
        label="Dossier sélectionné",
        hint_text="Cliquez sur Parcourir... ou collez un chemin",
        expand=True, bgcolor=DARK, border_color=GREY, color=WHITE,
        on_focus=_suspend_kb, on_blur=_resume_kb,
    )
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
        # Barre du bas (pas le header) : total d'abord, puis la sélection
        # en cours s'il y en a une (retour user).
        dirs, imgs, other = _visible_entries()
        total = len(dirs) + len(imgs) + len(other)
        n = len(selected)
        total_txt = f"{total} fichier{'s' if total > 1 else ''}"
        if n:
            status_left.value = (
                f"{total_txt}, {n} sélectionné{'s' if n > 1 else ''}")
        else:
            status_left.value = total_txt if total else ""

    def _set_selected(path, on):
        # Un clic sur une vignette/case ne fait pas toujours perdre le focus
        # clavier au champ recherche (auto-focus par _focus_active_surface
        # après chaque navigation) côté Flet desktop : sans ce reset, le
        # compteur de suspension reste bloqué > 0 et Ctrl+C/X/V/A ne
        # répondent plus après la moindre navigation (retour user).
        _kb_suspend["count"] = 0
        if on:
            _select_add(path)
            state["last_selected"] = path
        else:
            _select_discard(path)
        _update_sel_count()
        if state["only_selected"]:
            # L'ensemble des éléments visibles change (filtre "ma
            # sélection") — un rendu complet reste nécessaire ici.
            _render()
            return
        # Sinon, pas de _render() complet : ça relancerait le chargeur de
        # miniatures pour toutes les images pas encore chargées à CHAQUE
        # coche, et la rafale de page.update() qui en résulte rend les
        # clics suivants sans effet tant que le dossier charge (retour
        # user — comme Dashboard.pyw, dont le on_checkbox_change ne
        # touche jamais au rendu complet). On ne met à jour que la case
        # (déjà synchronisée côté client) et la bordure de la carte en
        # vue vignettes.
        status_left.update()
        card = grid_card_refs.get(path)
        if card is not None:
            card.border = (ft.Border.all(2, BLUE) if on
                          else ft.Border.all(1, GREY))
            card.update()

    def _list_thumb_size():
        # Suit le curseur de taille de vignette (mode grille), ramené à une
        # échelle raisonnable pour une ligne de liste (retour user : lier
        # les deux tailles plutôt que garder LIST_THUMB_SIZE figé).
        return max(32, min(state["thumb_size"] * 0.28, 96))

    def _list_icon_box(icon, color):
        # Même empreinte (carré size x size) que la vignette de _img_tile,
        # pour que toutes les lignes de la vue liste aient la même hauteur,
        # miniature ou pas (retour user).
        size = _list_thumb_size()
        icon_ctl = ft.Icon(icon, color=color, size=size - 16)
        box = ft.Container(content=icon_ctl, width=size, height=size,
                           alignment=ft.Alignment.CENTER)
        list_visual_refs.append((box, icon_ctl))
        return box

    def _dir_tile(path):
        checkbox = ft.Checkbox(
            value=path in selected, active_color=BLUE,
            scale=CONSTANTS.HUB_TILE_CHECKBOX_SCALE,
            on_change=lambda e, p=path: _set_selected(p, e.control.value))
        return ft.ListTile(
            leading=checkbox,
            title=ft.Row([
                _list_icon_box(ft.Icons.FOLDER, YELLOW),
                ft.Text(os.path.basename(path), size=CONSTANTS.TEXT_SM,
                       color=WHITE),
            ], spacing=8),
            on_click=lambda e, p=path: _navigate(p),
            hover_color=GREY, dense=True,
            content_padding=ft.Padding(left=8, top=2, right=8, bottom=2),
        )

    def _img_tile(path, pending):
        size = _list_thumb_size()
        thumb = thumb_mem.get(path)
        if thumb:
            visual = ft.Image(src=thumb, width=size, height=size,
                              fit=ft.BoxFit.COVER,
                              border_radius=ft.BorderRadius.all(4))
        else:
            visual = ft.Container(bgcolor=GREY, width=size, height=size,
                                  border_radius=ft.BorderRadius.all(4))
            pending[path] = visual
        list_visual_refs.append((visual, None))
        filename_text = ft.Text(os.path.basename(path),
                                size=CONSTANTS.TEXT_SM,
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
                scale=CONSTANTS.HUB_TILE_CHECKBOX_SCALE,
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
    def _card_icon_size():
        # Suit le curseur de taille de vignette pour que dossiers/fichiers
        # remplissent la cellule comme les miniatures d'image (retour user).
        return max(CONSTANTS.ICON_LG, min(state["thumb_size"] * 0.4, 140))

    def _dir_card(path):
        is_sel = path in selected
        checkbox = ft.Checkbox(
            value=is_sel, active_color=BLUE,
            scale=CONSTANTS.HUB_TILE_CHECKBOX_SCALE,
            on_change=lambda e, p=path: _set_selected(p, e.control.value))
        icon = ft.Icon(ft.Icons.FOLDER, color=YELLOW, size=_card_icon_size())
        card_icon_refs.append(icon)
        icon_zone = ft.Container(
            content=ft.Column([
                icon,
                ft.Text(os.path.basename(path), size=CONSTANTS.TEXT_SM,
                        color=WHITE, no_wrap=True),
            ], alignment=ft.MainAxisAlignment.CENTER,
               horizontal_alignment=ft.CrossAxisAlignment.CENTER, spacing=6,
               expand=True),
            # `alignment=` est indispensable ici : un Container n'est pas un
            # parent flex, donc `expand=True` sur la Column enfant ne suffit
            # pas à la centrer — sans ça elle reste collée en haut à gauche
            # (retour user, capture d'écran à l'appui).
            alignment=ft.Alignment.CENTER,
            expand=True, ink=True, on_click=lambda e, p=path: _navigate(p))
        header = ft.Row([ft.Container(expand=True), checkbox])
        return ft.Container(
            content=ft.Column([header, icon_zone], spacing=0, expand=True),
            padding=6, expand=True,
            border=ft.Border.all(2, BLUE) if is_sel else ft.Border.all(1, GREY),
            border_radius=8)

    # icône + couleur par extension, mêmes couples que Dashboard.pyw:7529-7550
    # (retour user : cohérence visuelle entre les deux explorateurs).
    _FILE_ICONS = {
        ".json": (ft.Icons.DATA_OBJECT_OUTLINED, VIOLET),
        ".txt": (ft.Icons.DESCRIPTION_OUTLINED, LIGHT_GREY),
        ".md": (ft.Icons.DESCRIPTION_OUTLINED, LIGHT_GREY),
        ".log": (ft.Icons.DESCRIPTION_OUTLINED, LIGHT_GREY),
        ".zip": (ft.Icons.FOLDER_ZIP_OUTLINED, ORANGE),
        ".pdf": (ft.Icons.PICTURE_AS_PDF_OUTLINED, RED),
        ".af": (ft.Icons.ADOBE, GREEN),
        ".afphoto": (ft.Icons.ADOBE, GREEN),
        ".afdesign": (ft.Icons.ADOBE, GREEN),
        ".afpub": (ft.Icons.ADOBE, GREEN),
        ".psd": (ft.Icons.ADOBE, GREEN),
        ".psb": (ft.Icons.ADOBE, GREEN),
        ".svg": (ft.Icons.ADOBE, GREEN),
        ".eps": (ft.Icons.ADOBE, GREEN),
        ".ai": (ft.Icons.ADOBE, GREEN),
    }

    def _file_icon(path):
        return _FILE_ICONS.get(os.path.splitext(path)[1].lower(),
                               (ft.Icons.INSERT_DRIVE_FILE_OUTLINED, LIGHT_GREY))

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
            return
        # Bascule en mode ruban comme les autres ouvertures externes
        # (explorateur, impression, bluetooth, navigateur) — laisse la
        # fenêtre de l'appli externe passer devant sans que Hub prenne
        # toute la place.
        if not _strip_state["active"]:
            _toggle_strip()

    def _resolve_exe_path(exe):
        # Comme Dashboard.pyw:4858-4872 : les apps installées via
        # Microsoft Store (WindowsApps) ont un dossier versionné qui change
        # à chaque mise à jour automatique (ex. Affinity) — le chemin
        # enregistré dans open_with.json devient obsolète silencieusement.
        if not exe or os.path.isfile(exe):
            return exe
        if "WindowsApps" not in exe:
            return exe
        import re
        import glob as _glob
        pattern = re.sub(r"_\d+\.\d+\.\d+\.\d+_", "_*_", exe)
        matches = _glob.glob(pattern)
        return matches[0] if matches else exe

    def _open_files_with(prog, files):
        exe = prog.get("exe", "")
        if not exe:
            return
        try:
            resolved = _resolve_exe_path(exe)
            if resolved != exe:
                prog["exe"] = resolved
                programs = _load_open_with_programs()
                for p in programs:
                    if p.get("label") == prog.get("label") and p.get("exe") == exe:
                        p["exe"] = resolved
                        break
                _save_open_with_programs(programs)
                _log_to_terminal(
                    f"[INFO] Chemin mis à jour automatiquement pour {prog['label']}",
                    ORANGE)
            if platform.system() == "Darwin":
                subprocess.Popen(["open", "-a", resolved] + files)
            else:
                subprocess.Popen([resolved] + files)
        except Exception as exc:
            _log_to_terminal(f"[ERREUR] {prog.get('label', exe)} : {exc}", RED)
            return
        if not _strip_state["active"]:
            _toggle_strip()

    # Extensions lisibles dans le Bloc-notes (coloration syntaxique), comme
    # Dashboard.pyw:1589-1597 — les autres s'ouvrent avec l'appli par défaut.
    # .json est exclu d'ici : il va dans la surface Liste (lecteur JSON),
    # pas le Bloc-notes brut — cf. _liste_open_path plus bas.
    _NOTEPAD_EXTS = CONSTANTS.NOTEPAD_EXTS | {".markdown"}

    def _open_file(path):
        ext = os.path.splitext(path)[1].lower()
        if ext == ".json":
            _liste_open_path(path)
        elif ext == ".zip":
            # Clic = extraction, comme Dashboard.pyw:6080-6082 (retour user :
            # fonction absente de Hub jusqu'ici).
            _do_unzip([path])
        elif ext in _NOTEPAD_EXTS:
            _open_path_in_notes(path)
        else:
            _open_file_default(path)

    def _file_tile(path):
        # Case à cocher comme _dir_tile/_img_tile : la sélection (donc
        # copier/couper/coller) doit marcher sur N'IMPORTE QUEL fichier, pas
        # seulement les images — retour user (fichiers de production).
        checkbox = ft.Checkbox(
            value=path in selected, active_color=BLUE,
            scale=CONSTANTS.HUB_TILE_CHECKBOX_SCALE,
            on_change=lambda e, p=path: _set_selected(p, e.control.value))
        icon, icon_color = _file_icon(path)
        return ft.ListTile(
            leading=checkbox,
            title=ft.Row([
                _list_icon_box(icon, icon_color),
                ft.Text(os.path.basename(path),
                       size=CONSTANTS.TEXT_SM, color=WHITE),
            ], spacing=8),
            on_click=lambda e, p=path: _open_file(p),
            hover_color=GREY, dense=True,
            content_padding=ft.Padding(left=8, top=2, right=8, bottom=2),
        )

    def _file_card(path):
        is_sel = path in selected
        checkbox = ft.Checkbox(
            value=is_sel, active_color=BLUE,
            scale=CONSTANTS.HUB_TILE_CHECKBOX_SCALE,
            on_change=lambda e, p=path: _set_selected(p, e.control.value))
        icon_name, icon_color = _file_icon(path)
        icon_ctl = ft.Icon(icon_name, color=icon_color, size=_card_icon_size())
        card_icon_refs.append(icon_ctl)
        icon_zone = ft.Container(
            content=ft.Column([
                icon_ctl,
                ft.Text(os.path.basename(path), size=CONSTANTS.TEXT_SM,
                        color=WHITE, no_wrap=True),
            ], alignment=ft.MainAxisAlignment.CENTER,
               horizontal_alignment=ft.CrossAxisAlignment.CENTER, spacing=6,
               expand=True),
            alignment=ft.Alignment.CENTER,
            expand=True, ink=True, on_click=lambda e, p=path: _open_file(p))
        header = ft.Row([ft.Container(expand=True), checkbox])
        return ft.Container(
            content=ft.Column([header, icon_zone], spacing=0, expand=True),
            padding=6, expand=True,
            border=ft.Border.all(2, BLUE) if is_sel else ft.Border.all(1, GREY),
            border_radius=8)

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
        label = ft.Text(os.path.basename(path), size=CONSTANTS.TEXT_SM,
                        color=WHITE, no_wrap=True)
        if order_mode["value"]:
            # Badge commande sous le nom (pas de case à cocher sur l'image) —
            # clic = dialogue plusieurs tailles, jamais de clic droit.
            highlighted = is_ordered
            body = [img_zone, label, _order_badge(path)]
        else:
            checkbox = ft.Checkbox(
                value=is_sel, active_color=BLUE,
                scale=CONSTANTS.HUB_TILE_CHECKBOX_SCALE,
                on_change=lambda e, p=path: _set_selected(p, e.control.value))
            header = ft.Row([ft.Container(expand=True), checkbox])
            highlighted = is_sel
            body = [header, img_zone, label]
        card = ft.Container(
            content=ft.Column(body, spacing=4, expand=True,
                              horizontal_alignment=ft.CrossAxisAlignment.STRETCH),
            padding=6, expand=True,
            border=ft.Border.all(2, BLUE) if highlighted else ft.Border.all(1, GREY),
            border_radius=8)
        if not order_mode["value"]:
            grid_card_refs[path] = card
        return card

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
            other = [p for p in other if p in selected]
        return dirs, imgs, other

    def _on_ctx_menu(path, event):
        # Clic droit -> panneau Actions. Si un ou plusieurs éléments sont
        # déjà sélectionnés, cette sélection est conservée telle quelle
        # (retour user) ; seul le cas "rien de sélectionné" auto-sélectionne
        # l'élément cliqué, sinon les actions du panneau (qui opèrent sur
        # `selected`) n'auraient rien sur quoi agir.
        if not selected:
            _set_selected(path, True)
        _open_actions(event)

    def _with_ctx_menu(control, path):
        # GestureDetector scopé à la SEULE tuile (pas au conteneur
        # scrollable entier comme avant, cf. incident précédent) : n'absorbe
        # pas la molette/trackpad, contrairement au wrap sur tout
        # `files_body` qui interceptait aussi les ScrollEvent (retour user).
        return ft.GestureDetector(
            on_secondary_tap_up=lambda e, p=path: _on_ctx_menu(p, e),
            content=control)

    def _on_bg_ctx_menu(event):
        # Clic droit sur le fond (pas sur une tuile) : agit sur la
        # sélection courante si elle existe, sinon sur TOUS les éléments
        # visibles (retour user — différent de _on_ctx_menu qui, lui,
        # n'auto-sélectionne que l'élément cliqué).
        if not selected:
            dirs, imgs, other = _visible_entries()
            _select_update(dirs + imgs + other)
            _update_sel_count()
            _render()
        _open_actions(event)

    def _bg_filler():
        # Comme _with_ctx_menu, mais pour le fond : un GestureDetector
        # scopé à un petit bloc (pas au conteneur scrollable entier, même
        # incident que ci-dessus) placé après le dernier élément, pour que
        # le clic droit fonctionne aussi sous la dernière ligne/carte.
        return ft.GestureDetector(
            on_secondary_tap_up=_on_bg_ctx_menu,
            content=ft.Container(height=160))

    def _render():
        # Mutation en place (.clear()+.extend()), jamais de réassignation de
        # .controls : Flet ne détecte pas toujours un remplacement wholesale
        # de la liste pour le diff de rendu (idiome Dashboard/SidePanel).
        dirs, imgs, other = _visible_entries()
        files_list.controls.clear()
        files_grid.controls.clear()
        card_icon_refs.clear()
        list_visual_refs.clear()
        grid_card_refs.clear()
        if not dirs and not imgs and not other:
            if state["only_selected"]:
                msg = "Aucun élément sélectionné."
            elif state["search"].strip():
                msg = "Aucun résultat."
            else:
                msg = "Dossier vide."
            files_list.controls.append(
                ft.Text(msg, size=CONSTANTS.TEXT_SM, color=WHITE))
            files_list.controls.append(_bg_filler())
        else:
            # Images et autres fichiers mélangés puis re-triés ensemble
            # (pas rendus groupe par groupe) : le tri "Date" doit ordonner
            # tous les fichiers du dossier entre eux, pas juste chaque
            # type de fichier séparément (retour user). Les dossiers
            # restent en tête, comme dans tout explorateur de fichiers.
            img_set = set(imgs)
            files = sorted(imgs + other, key=_sort_key,
                          reverse=(state["sort"] == "name_desc"))
            if state["view"] == "list":
                pending = {}
                files_list.controls.extend(
                    _with_ctx_menu(_dir_tile(p), p) for p in dirs)
                files_list.controls.extend(
                    _with_ctx_menu(
                        _img_tile(p, pending) if p in img_set else _file_tile(p), p)
                    for p in files)
                files_list.controls.append(_bg_filler())
                _start_thumb_loader(pending)
            else:
                pending = {}
                files_grid.controls.extend(
                    _with_ctx_menu(_dir_card(p), p) for p in dirs)
                files_grid.controls.extend(
                    _with_ctx_menu(
                        _grid_card(p, pending) if p in img_set else _file_card(p), p)
                    for p in files)
                files_grid.controls.append(_bg_filler())
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
            # Un page.update() par miniature chargée noyait la boucle
            # d'événements sous des rafales de mises à jour sur les gros
            # dossiers (des centaines d'images) — l'app entière (clics,
            # scroll, menus...) devenait perceptiblement lente pendant le
            # chargement, pas seulement la sélection (retour user). Un seul
            # update() groupé toutes les ~100 ms suffit à faire apparaître
            # les miniatures au fil de l'eau sans jamais saturer le thread
            # principal, quel que soit le nombre de fichiers.
            #
            # 2 workers en parallèle : Wand/PyMuPDF (SVG/PDF, de loin les
            # plus lents à générer) libèrent le GIL pendant le rendu, donc
            # ça accélère vraiment un dossier de centaines de vectoriels
            # sans saturer le CPU ni concurrencer le thread principal.
            # shutdown(wait=False, cancel_futures=True) : changer de
            # dossier abandonne aussitôt les tâches pas encore lancées au
            # lieu d'attendre que les 300 rendus se terminent (retour
            # user — jamais bloquer sur un dossier abandonné).
            pool = concurrent.futures.ThreadPoolExecutor(max_workers=2)
            futures = {pool.submit(thumb_cache.get_or_generate, path): (path, holder)
                      for path, holder in snapshot}
            last_update = 0.0
            done = 0
            total = len(futures)
            try:
                for future in concurrent.futures.as_completed(futures):
                    if state["thumb_token"] != token:
                        return
                    path, holder = futures[future]
                    done += 1
                    data = future.result()
                    if data:
                        thumb_mem[path] = data
                        holder.content = ft.Image(
                            src=data, width=holder.width, height=holder.height,
                            fit=ft.BoxFit.COVER, border_radius=ft.BorderRadius.all(6))
                        holder.bgcolor = None
                        now = time.monotonic()
                        if now - last_update >= 0.1 or done == total:
                            last_update = now
                            page.run_task(_safe_update)
            finally:
                pool.shutdown(wait=False, cancel_futures=True)

        threading.Thread(target=_load, daemon=True).start()

    async def _safe_update():
        try:
            page.update()
        except Exception:
            pass

    def _run_bg_action(label, work):
        # Copier/coller/dupliquer/zipper/dézipper/supprimer pouvaient
        # geler toute la fenêtre le temps de l'opération (boucle
        # shutil/zipfile synchrone sur le thread de l'UI) — comme
        # _launch_tool pour les apps externes, on défère sur un thread et
        # on retourne tout de suite, avec la barre infinie + un message
        # dans le terminal pendant que ça tourne (retour user, même
        # rendu que app_progress_bar dans Dashboard.pyw).
        _log_to_terminal(f"[...] {label}…", ORANGE)
        action_progress_bar.visible = True
        page.update()

        def _run():
            try:
                work()
            finally:
                action_progress_bar.visible = False
                try:
                    page.update()
                except Exception:
                    pass

        threading.Thread(target=_run, daemon=True).start()

    # ═════════════════════════════════════════════════════════════════════
    #  Copier / Couper / Coller / Supprimer — presse-papiers interne à l'app
    #  (pas le presse-papiers système : simple, fiable, suffisant ici).
    #  Suppression : pas de dialogue de confirmation (politique du projet),
    #  _backup_file avant toute suppression/écrasement à la place.
    # ═════════════════════════════════════════════════════════════════════
    def _do_copy(paths):
        clipboard["paths"] = list(paths)
        clipboard["mode"] = "copy"
        page.update()
        _log_to_terminal(f"[OK] {len(clipboard['paths'])} élément(s) copié(s)", BLUE)

    def _do_cut(paths):
        clipboard["paths"] = list(paths)
        clipboard["mode"] = "cut"
        page.update()
        _log_to_terminal(
            f"[OK] {len(clipboard['paths'])} élément(s) coupé(s) — Ctrl+V pour coller",
            ORANGE)

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
        # Instantané avant de démarrer le thread : `clipboard` peut changer
        # entre-temps (un nouveau copier/couper pendant que celui-ci tourne
        # encore) — sans ça, la boucle lirait un état déjà remplacé.
        src_paths = list(clipboard["paths"])
        is_cut = clipboard["mode"] == "cut"
        action = "déplacé" if is_cut else "collé"
        if is_cut:
            clipboard["paths"] = []
            clipboard["mode"] = None

        def _work():
            pasted, errors = 0, 0
            for src in src_paths:
                if not os.path.exists(src):
                    continue
                dest = _unique_dest(folder, os.path.basename(src))
                try:
                    if is_cut:
                        shutil.move(src, dest)
                    elif os.path.isdir(src):
                        shutil.copytree(src, dest)
                    else:
                        shutil.copy2(src, dest)
                    pasted += 1
                except Exception as exc:
                    errors += 1
                    _log_to_terminal(f"[ERREUR] {os.path.basename(src)} : {exc}", RED)
            if pasted:
                _log_to_terminal(f"[OK] {pasted} élément(s) {action}(s)", BLUE)
            if errors:
                _log_to_terminal(f"[ATTENTION] {errors} erreur(s)", ORANGE)
            page.run_task(_tool_refresh, folder)

        _run_bg_action(f"Collage de {len(src_paths)} élément(s)", _work)

    def _do_delete(paths):
        folder = state["folder"]

        def _work():
            for p in paths:
                try:
                    _backup_file(p)
                    if os.path.isdir(p):
                        shutil.rmtree(p)
                    else:
                        os.remove(p)
                    _select_discard(p)
                    _log_to_terminal(f"[OK] Supprimé : {os.path.basename(p)}", GREEN)
                except Exception as exc:
                    _log_to_terminal(f"[ERREUR] {os.path.basename(p)} : {exc}", RED)
            _update_sel_count()
            page.run_task(_tool_refresh, folder)

        _run_bg_action(f"Suppression de {len(paths)} élément(s)", _work)

    def _do_duplicate(paths):
        folder = state["folder"]
        if not folder:
            return

        def _work():
            duplicated = 0
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
                    duplicated += 1
                except Exception as exc:
                    _log_to_terminal(f"[ERREUR] {os.path.basename(src)} : {exc}", RED)
            if duplicated:
                _log_to_terminal(f"[OK] {duplicated} élément(s) dupliqué(s)", BLUE)
            page.run_task(_tool_refresh, folder)

        _run_bg_action(f"Duplication de {len(paths)} élément(s)", _work)

    def _do_zip(paths):
        folder = state["folder"]
        paths = [p for p in paths if os.path.exists(p)]
        if not folder or not paths:
            return
        name = (os.path.basename(folder) if len(paths) > 1
                else os.path.splitext(os.path.basename(paths[0]))[0])
        zip_path = _unique_dest(folder, f"{name}.zip")

        def _work():
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
                _log_to_terminal(
                    f"[OK] Archive créée : {os.path.basename(zip_path)}", YELLOW)
            except Exception as exc:
                _log_to_terminal(f"[ERREUR] Zip : {exc}", RED)
            page.run_task(_tool_refresh, folder)

        _run_bg_action(f"Compression de {len(paths)} élément(s)", _work)

    def _extract_zip(zip_path):
        # Détection de dossier racine unique, comme Dashboard.pyw:5389-5405 :
        # si tout le contenu du zip est déjà sous un seul dossier, on
        # extrait directement à côté (pas de double niveau nom/nom/...).
        dest_dir = os.path.dirname(zip_path)
        zip_name = os.path.splitext(os.path.basename(zip_path))[0]
        with zipfile.ZipFile(zip_path, "r") as zf:
            names = zf.namelist()
            top_levels = {n.split("/")[0] for n in names if n}
            if len(top_levels) == 1 and any("/" in n for n in names):
                extract_to = dest_dir
            else:
                extract_to = os.path.join(dest_dir, zip_name)
                os.makedirs(extract_to, exist_ok=True)
            zf.extractall(extract_to)

    def _confirm_delete_zips(zip_paths):
        def _cancel(e):
            dlg.open = False
            page.update()

        def _confirm(e):
            dlg.open = False
            page.update()
            _do_delete(zip_paths)

        names = "\n".join(os.path.basename(p) for p in zip_paths)
        dlg = ft.AlertDialog(
            title=ft.Text("Supprimer le(s) ZIP ?", size=CONSTANTS.TEXT_SM,
                          color=WHITE),
            content=ft.Text(f"Voulez-vous supprimer :\n{names}",
                            size=CONSTANTS.TEXT_SM, color=WHITE),
            actions=[ft.TextButton("Conserver", on_click=_cancel),
                     ft.TextButton("Supprimer", on_click=_confirm,
                                  style=ft.ButtonStyle(color=RED))],
        )
        page.overlay.append(dlg)
        dlg.open = True
        page.update()

    def _do_unzip(paths):
        # Décompresser (retour user : fonction absente de Hub, présente
        # dans Dashboard.pyw:5389-5441) — même logique de suppression du
        # ZIP source, gouvernée par CONSTANTS.DELETE_ZIP_AFTER_EXTRACT.
        zips = [p for p in paths if os.path.isfile(p)
               and os.path.splitext(p)[1].lower() == ".zip"]
        if not zips:
            return
        folder = state["folder"]

        def _work():
            extracted = []
            for zip_path in zips:
                try:
                    _extract_zip(zip_path)
                    extracted.append(zip_path)
                    _log_to_terminal(
                        f"[OK] Décompressé : {os.path.basename(zip_path)}", GREEN)
                except Exception as exc:
                    _log_to_terminal(
                        f"[ERREUR] Décompression {os.path.basename(zip_path)} : "
                        f"{exc}", RED)
            if not extracted:
                return
            if CONSTANTS.DELETE_ZIP_AFTER_EXTRACT:
                _do_delete(extracted)
            else:
                async def _show_confirm():
                    _navigate(folder)
                    _confirm_delete_zips(extracted)
                page.run_task(_show_confirm)

        _run_bg_action(f"Décompression de {len(zips)} archive(s)", _work)

    def _do_copy_to_selection(paths):
        folder = state["folder"]
        if not folder:
            return
        selection_folder = os.path.join(folder, "SELECTION")
        os.makedirs(selection_folder, exist_ok=True)
        copied = 0
        for src in paths:
            if not os.path.isfile(src):
                continue
            dest = _unique_dest(selection_folder, os.path.basename(src))
            try:
                shutil.copy2(src, dest)
                copied += 1
            except Exception as exc:
                _log_to_terminal(f"[ERREUR] {os.path.basename(src)} : {exc}", RED)
        if copied:
            _log_to_terminal(f"[OK] {copied} fichier(s) copié(s) dans SELECTION/", BLUE)
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
            return
        if not _strip_state["active"]:
            _toggle_strip()

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
            except OSError as exc:
                _log_to_terminal(f"[ERREUR] Renommage : {exc}", RED)
                return
            _log_to_terminal(f"[OK] Renommé : {current_name} → {new_name}", GREEN)
            _select_discard(path)
            _navigate(parent)

        name_field.on_submit = _confirm
        dlg = ft.AlertDialog(
            title=ft.Text("Renommer", size=CONSTANTS.TEXT_SM, color=WHITE),
            content=name_field,
            actions=[
                ft.TextButton("Annuler", on_click=_cancel),
                ft.TextButton("Renommer", on_click=_confirm),
            ],
        )
        page.overlay.append(dlg)
        dlg.open = True
        page.update()

    def _show_exif_dialog(paths):
        # Comme Dashboard.pyw:5258-5302 : résolution + tags EXIF lisibles
        # d'une image, dans un dialogue scrollable et sélectionnable.
        path = paths[0]
        rows = []
        try:
            from PIL.ExifTags import TAGS
            with PILImage.open(path) as img:
                width, height = img.size
                raw = img.getexif()
            rows.append(ft.Text(f"Résolution : {width} × {height} px",
                                size=CONSTANTS.TEXT_SM, color=BLUE, selectable=True))
            if raw:
                for tag_id, value in raw.items():
                    if isinstance(value, bytes):
                        continue
                    tag_name = TAGS.get(tag_id, f"Tag {tag_id}")
                    rows.append(ft.Text(f"{tag_name} : {value}", size=CONSTANTS.TEXT_SM,
                                        color=WHITE, selectable=True))
            else:
                rows.append(ft.Text("Aucune donnée EXIF.", size=CONSTANTS.TEXT_SM,
                                    color=LIGHT_GREY))
        except Exception as exc:
            rows.append(ft.Text(f"Erreur : {exc}", size=CONSTANTS.TEXT_SM, color=RED))

        def _close_exif(event=None):
            exif_dlg.open = False
            page.update()

        exif_dlg = ft.AlertDialog(
            title=ft.Text(os.path.basename(path), size=CONSTANTS.TEXT_SM, color=LIGHT_GREY),
            content=ft.Column(rows, spacing=2, scroll=ft.ScrollMode.AUTO,
                              width=400, height=400),
            actions=[ft.TextButton("Fermer", on_click=_close_exif)],
            actions_alignment=ft.MainAxisAlignment.END,
        )
        page.overlay.append(exif_dlg)
        exif_dlg.open = True
        page.update()

    def _add_open_with_program(event=None):
        label_field = ft.TextField(hint_text="Nom (ex. Photoshop)", autofocus=True,
                                   width=280, bgcolor=DARK, border_color=BLUE,
                                   color=WHITE, text_size=CONSTANTS.TEXT_SM,
                                   height=CONSTANTS.HUB_DIALOG_FIELD_HEIGHT,
                                   content_padding=ft.Padding(8, 4, 8, 4))
        exe_field = ft.TextField(hint_text="Chemin de l'exécutable", width=280,
                                 bgcolor=DARK, border_color=BLUE, color=WHITE,
                                 text_size=CONSTANTS.TEXT_SM,
                                 height=CONSTANTS.HUB_DIALOG_FIELD_HEIGHT,
                                 content_padding=ft.Padding(8, 4, 8, 4))

        def _cancel(event):
            dlg.open = False
            page.update()

        def _confirm(event):
            label = (label_field.value or "").strip()
            exe = (exe_field.value or "").strip()
            if not label or not exe:
                return
            programs = _load_open_with_programs()
            programs.append({"label": label, "exe": exe})
            _save_open_with_programs(programs)
            dlg.open = False
            page.update()

        dlg = ft.AlertDialog(
            title=ft.Text("Ajouter un programme", size=CONSTANTS.TEXT_SM, color=WHITE),
            content=ft.Column([label_field, exe_field], spacing=8, tight=True,
                              width=280),
            actions=[
                ft.TextButton("Ajouter", on_click=_confirm),
                ft.TextButton("Annuler", on_click=_cancel),
            ],
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
        # Une recherche périmée après une action (suppression, déplacement,
        # outil lancé sur les résultats...) masquerait le contenu rechargé :
        # _navigate() est le point de passage commun à toute action sur
        # fichiers (cf. _do_delete/_do_paste/_tool_refresh...), donc on y
        # réinitialise la recherche plutôt qu'à chaque site d'appel.
        state["search"] = ""
        search_field.value = ""
        try:
            entries = list(os.scandir(path))
        except OSError as exc:
            content["dirs"], content["imgs"], content["other"] = [], [], []
            files_list.controls.clear()
            files_list.controls.append(ft.Text(str(exc), color=WHITE))
            files_body.content = files_list
            page.update()
            return
        exts = CONSTANTS.IMAGE_EXTS | CONSTANTS.HUB_VECTOR_EXTS
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
        _update_sel_count()
        _render()
        page.run_task(_focus_active_surface)

    def _on_files_path_submit(event):
        raw = (files_path.value or "").strip().strip('"').strip("'")
        if raw and os.path.isdir(raw):
            files_path.error = None
            _navigate(raw)
        else:
            files_path.error = "Dossier introuvable"
            files_path.value = state["folder"] or ""
        files_path.update()

    def _on_files_path_blur(event):
        _resume_kb(event)
        files_path.error = None
        files_path.value = state["folder"] or ""
        files_path.update()

    files_path.on_submit = _on_files_path_submit
    files_path.on_blur = _on_files_path_blur

    async def _pick_folder(event):
        folder = await ft.FilePicker().get_directory_path(
            dialog_title="Dossier d'images",
            initial_directory=state["folder"] or None)
        if folder:
            _navigate(folder)

    def _toggle_all(event):
        # Opère sur les éléments visibles (recherche / "afficher ma
        # sélection" appliqués), pas tout le dossier. Dès qu'il y a une
        # sélection (même partielle), le premier appui l'efface d'abord ;
        # il faut rappuyer (sélection vide) pour tout sélectionner —
        # évite d'écraser une sélection partielle par accident (retour user).
        if selected:
            selected.clear()
            _log_to_terminal("[OK] Sélection effacée", GREEN)
        else:
            # Uniquement les fichiers (images + autres), pas les
            # sous-dossiers (retour user).
            _dirs, imgs, other = _visible_entries()
            _select_update(imgs + other)
            _log_to_terminal(f"[OK] {len(selected)} élément(s) sélectionné(s)", BLUE)
        _update_sel_count()
        _render()

    def _invert(event):
        current = set(selected)
        new = [p for p in content["dirs"] + content["imgs"] + content["other"]
              if p not in current]
        selected.clear()
        _select_update(new)
        _update_sel_count()
        _render()
        _log_to_terminal(
            f"[OK] Sélection inversée — {len(selected)} élément(s) sélectionné(s)",
            BLUE)

    def _file_date(path):
        try:
            return datetime.date.fromtimestamp(os.path.getmtime(path))
        except OSError:
            return None

    def _select_same_date(event=None):
        """Comme Dashboard.pyw:6553-6577 (select_same_date) : sélectionne
        tous les fichiers du dossier pris à la même date (mtime) que le
        dernier fichier sélectionné — additif, ne supprime rien."""
        ref_path = state["last_selected"]
        if not ref_path or ref_path not in selected:
            _log_to_terminal(
                "[ATTENTION] Aucun fichier sélectionné comme référence", ORANGE)
            return
        ref_date = _file_date(ref_path)
        if ref_date is None:
            _log_to_terminal(
                "[ERREUR] Impossible de lire la date du fichier de référence", RED)
            return
        added = 0
        for fpath in content["imgs"] + content["other"]:
            if fpath in selected:
                continue
            if _file_date(fpath) == ref_date:
                _select_add(fpath)
                added += 1
        _update_sel_count()
        _render()
        _log_to_terminal(
            f"[OK] {len(selected)} fichier(s) du {ref_date.strftime('%d/%m/%Y')} "
            f"sélectionné(s) (+{added} ajouté(s))", BLUE)

    def _toggle_only_selected(event):
        state["only_selected"] = not state["only_selected"]
        only_sel_btn.style = ft.ButtonStyle(
            bgcolor=BLUE if state["only_selected"] else GREY)
        only_sel_icon.color = only_sel_text.color = (
            DARK if state["only_selected"] else BLUE)
        _render()

    def _toggle_order_mode(event):
        # Bascule inline (case à cocher <-> badge commande sur chaque
        # vignette) — pas de clic droit, pas de menu déroulant caché.
        order_mode["value"] = not order_mode["value"]
        order_mode_btn.style = ft.ButtonStyle(
            bgcolor=BLUE if order_mode["value"] else GREY)
        order_mode_icon.color = order_mode_text.color = (
            DARK if order_mode["value"] else BLUE)
        # "Créer le dossier de commande" n'a de sens qu'en mode commande —
        # masqué le reste du temps (retour user).
        create_order_btn.visible = order_mode["value"]
        if not order_mode["value"]:
            # Retour au mode normal : la sélection (cases à cocher) ET la
            # commande en cours (formats/tirages par photo) repartent de
            # zéro — sinon les tailles restaient en place même en changeant
            # de dossier, puisque `order` est persisté indépendamment du
            # dossier affiché (retour user).
            selected.clear()
            _update_sel_count()
            order.clear()
            order_bw.clear()
            _save_order(order)
            _save_order_bw(order_bw)
        _render()

    def _mini_btn(icon, on_click):
        return ft.Container(
            content=ft.Icon(icon, size=CONSTANTS.ICON_SM, color=ICON_ACTION),
            width=30, height=30, border_radius=6, bgcolor=GREY,
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
                                 color=WHITE, width=26, text_align=ft.TextAlign.CENTER)
            counters[fmt] = count_text
            rows.append(ft.Row([
                ft.Text(fmt, size=CONSTANTS.TEXT_SM, color=WHITE, width=76),
                _mini_btn(ft.Icons.REMOVE, lambda e, f=fmt: _apply(f, -1)),
                count_text,
                _mini_btn(ft.Icons.ADD, lambda e, f=fmt: _apply(f, 1)),
            ], spacing=10, vertical_alignment=ft.CrossAxisAlignment.CENTER))

        def _toggle_bw(e):
            if e.control.value:
                order_bw[path] = True
            else:
                order_bw.pop(path, None)
            _save_order_bw(order_bw)
            _render()
            _refresh_viewer_order(path)

        def _close(event):
            dlg.open = False
            page.update()

        bw_switch = ft.Checkbox(
            label="Noir & blanc", value=order_bw.get(path, False),
            active_color=VIOLET, on_change=_toggle_bw)

        dlg = ft.AlertDialog(
            title=ft.Text(os.path.basename(path), size=CONSTANTS.TEXT_SM, color=WHITE, no_wrap=True),
            content=ft.Column(rows + [ft.Divider(height=1), bw_switch], spacing=10,
                              tight=True, scroll=ft.ScrollMode.AUTO,
                              height=min(400, len(rows) * 48 + 70), width=250),
            actions=[ft.TextButton("Fermer", on_click=_close)],
        )
        page.overlay.append(dlg)
        dlg.open = True
        page.update()

    def _order_badge(path):
        entry = order.get(path, {})
        n = len(entry)
        label = f"{n} taille{'s' if n > 1 else ''}" if n else "+ Commande"
        if order_bw.get(path):
            label += " · N&B"
        return ft.Container(
            content=ft.Row([
                ft.Icon(ft.Icons.RECEIPT_LONG_OUTLINED, size=CONSTANTS.ICON_SM,
                        color=ICON_ACTION),
                ft.Text(label, size=CONSTANTS.TEXT_SM, color=WHITE),
            ], spacing=6, tight=True, alignment=ft.MainAxisAlignment.CENTER),
            padding=ft.Padding(12, 8, 12, 8), border_radius=8, bgcolor=GREY,
            ink=True, on_click=lambda e, p=path: _edit_order_for_photo(p),
            alignment=ft.Alignment.CENTER)

    def _apply_thumb_size(value):
        # Pas de _render() ici : les cartes existantes (Image/Container en
        # expand=True) se redimensionnent toutes seules quand max_extent
        # change -> juste reflow, aucune reconstruction. Un _render() complet
        # à chaque tick du curseur provoquait le clignotement signalé.
        # Les icônes dossier/fichier (Icon, pas de BoxFit) et les tuiles de
        # la vue liste (taille figée) ne suivent pas ce reflow automatique ->
        # resize manuel via card_icon_refs/list_visual_refs (retour user).
        size = int(value)
        if size == state["thumb_size"]:
            return
        state["thumb_size"] = size
        files_grid.max_extent = size + 20
        files_grid.child_aspect_ratio = size / (size + 50)
        for icon in card_icon_refs:
            icon.size = _card_icon_size()
        if state["view"] == "grid":
            files_grid.update()
        list_size = _list_thumb_size()
        for box, icon_ctl in list_visual_refs:
            box.width = list_size
            box.height = list_size
            if icon_ctl is not None:
                icon_ctl.size = list_size - 16
        if state["view"] == "list":
            files_list.update()

    def _seg_btn(icon, text, on_click, color=None):
        # `color=None` (par défaut) : l'Icon/Text hérite de ButtonStyle.color,
        # ce qui permet à only_sel_btn (_toggle_only_selected) de recolorer
        # tout le bouton (fond + icône + texte) en une seule affectation
        # selon l'état actif/inactif — ne pas fixer `color` dans ce cas.
        # Un `color` explicite (ex. VIOLET) sert aux boutons non-toggle
        # (tout sélectionner, inverser), comme Dashboard.pyw:656-670.
        return ft.TextButton(
            content=ft.Row([
                ft.Icon(icon, size=CONSTANTS.ICON_SM, color=color),
                ft.Text(text, size=CONSTANTS.TEXT_SM, color=color),
            ], spacing=6, tight=True),
            style=ft.ButtonStyle(bgcolor=GREY, color=WHITE,
                                 padding=ft.Padding(14, 0, 14, 0)),
            height=CONSTANTS.HUB_TOOLBAR_H, on_click=on_click,
        )

    # Icône du segment sélectionné (posée sur le thumb BLUE) en DARK pour
    # rester lisible ; les segments non sélectionnés restent en WHITE.
    _view_seg_icons = []

    def _update_view_seg():
        index = 0 if state["view"] == "grid" else 1
        view_seg.selected_index = index
        for i, icon in enumerate(_view_seg_icons):
            icon.color = DARK if i == index else WHITE
        view_seg.update()

    def _on_view_seg_change(event):
        state["view"] = "grid" if event.control.selected_index == 0 else "list"
        _update_view_seg()
        _render()

    def _seg_label(icon):
        icon_ctrl = ft.Icon(icon, size=CONSTANTS.ICON_SM, color=WHITE)
        _view_seg_icons.append(icon_ctrl)
        return ft.Row([icon_ctrl], spacing=4, tight=True)

    view_seg = ft.CupertinoSlidingSegmentedButton(
        selected_index=0,
        controls=[
            _seg_label(ft.Icons.GRID_VIEW),
            _seg_label(ft.Icons.VIEW_LIST),
        ],
        bgcolor=DARK, thumb_color=BLUE, padding=ft.Padding(4, 6, 4, 6),
        on_change=_on_view_seg_change,
    )
    _view_seg_icons[0].color = DARK
    # Container : le widget Cupertino a sa propre hauteur intrinsèque et
    # ignore `height=` posé directement sur lui (même souci que sort_btn/
    # search_field ci-dessus) — le Container extérieur impose CONSTANTS.HUB_TOOLBAR_H.
    view_seg_wrap = ft.Container(
        content=view_seg, height=CONSTANTS.HUB_TOOLBAR_H, alignment=ft.Alignment(0, 0))

    def _set_search(value):
        state["search"] = value or ""
        _render()

    def _clear_search(event=None):
        state["search"] = ""
        search_field.value = ""
        _render()

    # Copie exacte de Dashboard.pyw:724-745 : height=45 + content_padding
    # réduit + prefix_icon fonctionnent très bien tels quels dans Dashboard -
    # le bouton d'effacement y est un IconButton SÉPARÉ à côté du champ
    # (Row), jamais un `suffix=` posé sur le TextField. C'est ce `suffix=`
    # (tenté dans une version précédente de Hub) qui plaquait le hint vers
    # le bas : à corriger, revenir à cette structure plutôt que retoucher
    # le padding/prefix.
    search_field = ft.TextField(
        hint_text="Rechercher…", on_change=lambda e: _set_search(e.control.value),
        height=45, bgcolor=DARK, border_color=BLUE,
        color=WHITE, text_size=CONSTANTS.TEXT_SM,
        content_padding=ft.Padding(8, 2, 8, 2),
        prefix_icon=ft.Icons.SEARCH,
        expand=True,
        on_focus=_suspend_kb, on_blur=_resume_kb,
    )
    search_close_btn = ft.IconButton(
        ft.Icons.CLOSE, icon_size=CONSTANTS.ICON_SM, icon_color=LIGHT_GREY,
        bgcolor=GREY, tooltip="Effacer la recherche", on_click=_clear_search,
        style=ft.ButtonStyle(padding=ft.Padding.all(4)))
    search_field_wrap = ft.Row(
        [search_field, search_close_btn], spacing=4, expand=True,
        vertical_alignment=ft.CrossAxisAlignment.CENTER)

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
    # Container extérieur : PopupMenuButton ajoute sa propre marge/chrome
    # Material autour de `content`, ce qui rendait le bouton plus grand que
    # les CONSTANTS.HUB_TOOLBAR_H voisins malgré le Container interne déjà à la bonne
    # taille — le Container extérieur force la taille réellement mesurée
    # dans la Row (cf. même souci que prefix_icon sur search_field).
    sort_btn = ft.Container(
        height=CONSTANTS.HUB_TOOLBAR_H,
        content=ft.PopupMenuButton(
            content=ft.Container(
                content=ft.Row([
                    ft.Icon(ft.Icons.SORT, size=CONSTANTS.ICON_SM, color=YELLOW),
                    sort_label,
                    ft.Icon(ft.Icons.ARROW_DROP_DOWN, size=CONSTANTS.ICON_SM, color=WHITE),
                ], spacing=4, tight=True),
                bgcolor=GREY, border_radius=8, height=CONSTANTS.HUB_TOOLBAR_H,
                alignment=ft.Alignment(0, 0),
                padding=ft.Padding(12, 0, 8, 0)),
            items=[
                ft.PopupMenuItem(content=ft.Text("Nom (A→Z)"), on_click=_set_sort("name_asc")),
                ft.PopupMenuItem(content=ft.Text("Nom (Z→A)"), on_click=_set_sort("name_desc")),
                ft.PopupMenuItem(content=ft.Text("Date (récent d'abord)"),
                                 on_click=_set_sort("date")),
            ],
        ),
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
    viewer_meta = ft.Text("", size=CONSTANTS.TEXT_SM, color=WHITE)
    viewer_counter = ft.Text("", size=CONSTANTS.TEXT_SM, color=WHITE)
    viewer_checkbox = ft.Checkbox(
        value=False, active_color=BLUE,
        on_change=lambda e: _set_selected(
            viewer_state["paths"][viewer_state["index"]], e.control.value))

    viewer_order_slot = ft.Container(visible=False)

    def _viewer_meta_text(path):
        # Dimensions de l'octet actuellement affiché (pivoté ou non — pas
        # celles du fichier original si une rotation en mémoire est active),
        # taille du fichier sur disque en Mo. PIL n'ouvre que l'en-tête pour
        # `.size`, pas de décodage complet : coût négligeable à chaque nav.
        dims = None
        try:
            if path in viewer_rotated_bytes:
                with PILImage.open(io.BytesIO(viewer_rotated_bytes[path])) as im:
                    dims = im.size
            else:
                with PILImage.open(path) as im:
                    dims = im.size
        except Exception:
            dims = None
        try:
            size_mo = os.path.getsize(path) / (1024 * 1024)
        except OSError:
            size_mo = None
        parts = []
        if dims:
            parts.append(f"{dims[0]}×{dims[1]} px")
        if size_mo is not None:
            parts.append(f"{size_mo:.1f} Mo")
        return "  •  ".join(parts)

    def _update_viewer():
        idx, paths = viewer_state["index"], viewer_state["paths"]
        path = paths[idx]
        # Flutter ne sait pas afficher un .svg/.pdf par chemin (Image.file
        # ne rend que les formats raster) — on passe par thumb_cache pour
        # obtenir un PNG/JPEG rendu, en cache dès le deuxième affichage.
        ext = os.path.splitext(path)[1].lower()
        if path in viewer_rotated_bytes:
            viewer_img.src = viewer_rotated_bytes[path]
        elif ext in CONSTANTS.HUB_VECTOR_EXTS:
            viewer_img.src = thumb_cache.get_or_generate(path, size_px=1600) or path
        else:
            viewer_img.src = path
        viewer_filename.value = os.path.basename(path)
        viewer_meta.value = _viewer_meta_text(path)
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
        return ft.IconButton(icon=icon, icon_color=WHITE, icon_size=CONSTANTS.ICON_LG,
                             tooltip=tip, on_click=cb)

    # Pastilles flottantes semi-transparentes (façon Dashboard.pyw:5928-6052 —
    # overlay_bar_color/top_bar/close_btn_top/navigation_bar), jamais une
    # barre pleine largeur : celle-ci masquait une partie de l'image (retour
    # user) parce qu'elle courait de `left=8` à `right=8` sur toute la
    # largeur du viewport.
    _VIEWER_BAR_BG = ft.Colors.with_opacity(0.72, GREY)

    viewer_title_pill = ft.Container(
        content=ft.Column([
            ft.Row([viewer_filename, viewer_meta], spacing=10, tight=True,
                  alignment=ft.MainAxisAlignment.CENTER),
            viewer_counter,
        ], spacing=0, tight=True,
           horizontal_alignment=ft.CrossAxisAlignment.CENTER),
        bgcolor=_VIEWER_BAR_BG, padding=ft.Padding(18, 6, 18, 6),
        border_radius=12,
    )
    viewer_close_pill = ft.Container(
        content=_viewer_btn(ft.Icons.CLOSE, "Fermer (Échap)", _close_viewer),
        bgcolor=_VIEWER_BAR_BG, border_radius=20,
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
        bgcolor=_VIEWER_BAR_BG, padding=ft.Padding(8, 6, 8, 6), border_radius=16,
    )
    # Pan/zoom natif Flet (même widget que le viewer plein écran de
    # Dashboard.pyw:5567-5578) : `width`/`height` explicites (pas `expand`)
    # -> l'InteractiveViewer a un viewport concret, sinon `constrained=True`
    # le dimensionne sur le rectangle CONTAIN de l'image (déjà lettrboxée)
    # au lieu du plein écran, et zoomer agrandit l'image DANS ce rectangle
    # fixe au lieu du canevas lui-même (retour user, captures à l'appui).
    viewer_interactive = ft.InteractiveViewer(
        content=viewer_img, min_scale=1.0, max_scale=6.0,
        pan_enabled=True, scale_enabled=True, constrained=True,
        width=page.window.width or 1280, height=page.window.height or 860,
        clip_behavior=ft.ClipBehavior.HARD_EDGE)

    # Conteneurs positionnés nommés (pas `expand=True`) pour pouvoir réduire
    # dynamiquement `right` quand un tiroir est ouvert — évite qu'il ne
    # masque une partie de l'image (retour utilisateur).
    viewer_image_wrap = ft.Container(content=viewer_interactive, bgcolor=DARK,
                                     alignment=ft.Alignment.CENTER,
                                     left=0, top=0, bottom=0, right=0)
    viewer_top_bar_wrap = ft.Container(content=viewer_title_pill, top=8,
                                       left=0, right=0,
                                       alignment=ft.Alignment.CENTER)
    viewer_close_wrap = ft.Container(content=viewer_close_pill, top=8, right=8)
    viewer_bottom_bar_wrap = ft.Container(content=viewer_bottom_bar,
                                          bottom=16, left=0, right=0,
                                          alignment=ft.Alignment.CENTER)
    viewer_overlay = ft.Stack([
        viewer_image_wrap, viewer_top_bar_wrap, viewer_close_wrap,
        viewer_bottom_bar_wrap,
    ], expand=True)

    def _set_drawer_space(width):
        viewer_image_wrap.right = width
        viewer_top_bar_wrap.right = width
        viewer_close_wrap.right = 8 + width
        viewer_bottom_bar_wrap.right = width
        viewer_interactive.width = (page.window.width or 1280) - width
        viewer_interactive.height = page.window.height or 860

    def _derived_path(path, suffix):
        """Chemin d'un fichier dérivé (retouche/recadrage) : sous-dossier
        `_DERIVES/` à côté de l'original, jamais d'écrasement (HUB_SPEC §7)."""
        folder = os.path.join(os.path.dirname(path), "_DERIVES")
        os.makedirs(folder, exist_ok=True)
        base = os.path.splitext(os.path.basename(path))[0]
        return _unique_dest(folder, f"{base}{suffix}.jpg")

    # ═════════════════════════════════════════════════════════════════════
    #  Édition — Recadrage manuel.pyw (retouche + recadrage, tous les outils)
    #  et Augmentation IA.py (inpainting / extension / upscale) lancés comme
    #  outils externes dédiés plutôt que des tiroirs dupliquant leur UI dans
    #  Hub : les tiroirs ne couvraient jamais correctement tout l'écran
    #  (retour user + captures), et ces deux apps ont déjà tous les outils.
    #  `_launch_tool` est défini plus loin dans main() : référence différée
    #  via closure, même principe que `create_order_btn` plus haut.
    # ═════════════════════════════════════════════════════════════════════
    def _launch_editor_for_current(script_name):
        def _run(event=None):
            if not viewer_state["paths"]:
                return
            path = viewer_state["paths"][viewer_state["index"]]
            _launch_tool(script_name, extra_env={
                "FOLDER_PATH": os.path.dirname(path),
                "SELECTED_FILES": os.path.basename(path),
            })
        return _run

    def _close_drawers():
        # Sans tiroir in-app, plus rien à masquer : ne reste que le reset de
        # la taille du viewport (utile après navigation/resize).
        _set_drawer_space(0)

    viewer_bottom_bar.content.controls.insert(
        -1, _viewer_btn(ft.Icons.TUNE,
                       "Retoucher / recadrer (Recadrage manuel.pyw)",
                       _launch_editor_for_current("Recadrage manuel.pyw")))
    viewer_bottom_bar.content.controls.insert(
        -1, _viewer_btn(ft.Icons.AUTO_AWESOME, "Augmentation IA",
                       _launch_editor_for_current("Augmentation IA.py")))

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
            content=ft.Text(text.upper(), size=CONSTANTS.TEXT_SM, color=GREY,
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
                ft.Icons.CLOSE, icon_color=RED, icon_size=CONSTANTS.ICON_SM,
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

    def _get_removable_drives():
        # Même logique que Dashboard.pyw:7159 (_get_removable_drives) :
        # détection cross-plateforme sans dépendance externe.
        drives = []
        try:
            if platform.system() == "Darwin":
                macos_system_volumes = {
                    "Macintosh HD", "Macintosh HD - Data",
                    "com.apple.TimeMachine.localsnapshots",
                    "Recovery", "Preboot", "VM", "Update",
                }
                for entry in os.scandir("/Volumes"):
                    if (entry.is_dir() and os.path.ismount(entry.path)
                            and entry.name not in macos_system_volumes
                            and not entry.name.startswith(".")):
                        drives.append((entry.name, entry.path))
            elif platform.system() == "Windows":
                import ctypes
                DRIVE_TYPE_REMOVABLE, DRIVE_TYPE_CDROM = 2, 5
                volume_label_buffer = ctypes.create_unicode_buffer(261)
                for letter in "ABCDEFGHIJKLMNOPQRSTUVWXYZ":
                    path = f"{letter}:\\"
                    drive_type = ctypes.windll.kernel32.GetDriveTypeW(path)
                    if (drive_type in (DRIVE_TYPE_REMOVABLE, DRIVE_TYPE_CDROM)
                            and os.path.exists(path)):
                        ctypes.windll.kernel32.GetVolumeInformationW(
                            path, volume_label_buffer, 261, None, None,
                            None, None, 0)
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

    def _eject_drive(path):
        # Même logique que Dashboard.pyw:7376 (_eject_drive).
        _log_to_terminal(f"[...] Éjection en cours : {path}", VIOLET)

        def _run():
            sys_name = platform.system()
            for attempt in range(1, 4):
                try:
                    if sys_name == "Windows":
                        drive_letter = os.path.splitdrive(path)[0]
                        ps_cmd = (
                            f"(New-Object -comObject Shell.Application)"
                            f".Namespace(17).ParseName('{drive_letter}')"
                            f".InvokeVerb('Eject')")
                        subprocess.run(
                            ["powershell", "-Command", ps_cmd],
                            creationflags=subprocess.CREATE_NO_WINDOW,
                            timeout=10)
                        time.sleep(1.5)
                        if not os.path.exists(path):
                            _log_to_terminal(f"[OK] Éjecté : {path}", VIOLET)
                            return
                    elif sys_name == "Darwin":
                        result = subprocess.run(
                            ["diskutil", "eject", path],
                            capture_output=True, text=True, timeout=10)
                        if result.returncode == 0:
                            _log_to_terminal(f"[OK] Éjecté : {path}", VIOLET)
                            return
                    else:
                        result = subprocess.run(
                            ["umount", path],
                            capture_output=True, text=True, timeout=10)
                        if result.returncode == 0:
                            _log_to_terminal(f"[OK] Éjecté : {path}", VIOLET)
                            return
                except subprocess.TimeoutExpired:
                    pass
                except Exception as exc:
                    _log_to_terminal(f"[ERREUR] Éjection impossible : {exc}", RED)
                    return
                if attempt < 3:
                    time.sleep(1)
            _log_to_terminal(
                f"[ATTENTION] Éjection non confirmée : {path}", ORANGE)

        threading.Thread(target=_run, daemon=True).start()

    def _drive_row(name, path):
        return ft.ListTile(
            leading=ft.Icon(ft.Icons.USB, color=VIOLET, size=CONSTANTS.ICON_SM),
            title=ft.Text(name, size=CONSTANTS.TEXT_SM, color=WHITE, no_wrap=True),
            trailing=ft.IconButton(
                ft.Icons.EJECT, icon_color=LIGHT_GREY, icon_size=CONSTANTS.ICON_SM,
                tooltip="Éjecter le périphérique",
                on_click=lambda e, p=path: _eject_drive(p)),
            on_click=lambda e, p=path: _open_from_menu(p),
            hover_color=GREY, dense=True,
            content_padding=ft.Padding(left=10, top=0, right=4, bottom=0),
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
        fav_cols_shown = min(len(fav_chunks), _FAV_VISIBLE_COLS)
        fav_lane_width = (_MENU_LANE_WIDTH * fav_cols_shown
                          + 6 * (fav_cols_shown - 1))
        fav_lane = ft.Container(
            width=fav_lane_width, height=_MENU_LANE_HEIGHT,
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

        lanes = [recent_lane, ft.VerticalDivider(width=1, color=DARK), fav_lane]
        drives = _get_removable_drives()
        if drives:
            drive_lane = ft.Container(
                width=_MENU_LANE_WIDTH, height=_MENU_LANE_HEIGHT,
                content=ft.Column([
                    _menu_section_label("Périphériques"),
                    ft.Column([_drive_row(n, p) for n, p in drives], spacing=0,
                              scroll=ft.ScrollMode.AUTO, expand=True),
                ], spacing=0, expand=True))
            lanes += [ft.VerticalDivider(width=1, color=DARK), drive_lane]

        open_menu_panel.content = ft.Column([
            ft.Row(lanes, spacing=6, vertical_alignment=ft.CrossAxisAlignment.START),
            ft.Divider(height=1, color=DARK),
            footer,
        ], spacing=6, tight=True)

    open_menu_panel = ft.Container(
        bgcolor=GREY, border_radius=10, padding=ft.Padding(6, 6, 6, 6),
        border=ft.Border.all(1, BLUE),
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
        style=ft.ButtonStyle(bgcolor=GREY, padding=ft.Padding.all(10)),
        height=CONSTANTS.HUB_TOOLBAR_H, on_click=_go_to_parent_folder,
        tooltip="Dossier parent",
    )

    def _refresh_folder(event=None):
        folder = state["folder"]
        if not folder:
            return
        _log_to_terminal("[CMD] Rafraîchir", BLUE)
        # Comme Dashboard.pyw (refresh_preview force_reload=True) : on jette
        # les miniatures en mémoire du dossier courant pour forcer un
        # nouveau passage par thumb_cache.get_or_generate, qui régénère si
        # le fichier a changé (signature mtime/size/ctime) sous le même nom.
        for p in [p for p in thumb_mem if os.path.dirname(p) == folder]:
            del thumb_mem[p]
        _navigate(folder)

    refresh_folder_btn = ft.IconButton(
        icon=ft.Icons.REFRESH,
        icon_color=ICON_ACTION, icon_size=CONSTANTS.ICON_SM,
        style=ft.ButtonStyle(bgcolor=GREY, padding=ft.Padding.all(10)),
        height=CONSTANTS.HUB_TOOLBAR_H, on_click=_refresh_folder,
        tooltip="Rafraîchir",
    )

    def _create_folder_here(event=None):
        # Même principe que Dashboard.pyw:6218-6277 (create_new_folder) :
        # un simple AlertDialog nom -> os.makedirs, pas de duplication de
        # cette logique côté Data/ pour un geste aussi simple.
        folder = state["folder"]
        if not folder:
            return
        name_field = ft.TextField(
            hint_text="nom-du-dossier", autofocus=True, width=280,
            bgcolor=DARK, border_color=BLUE, text_size=CONSTANTS.TEXT_SM,
            height=CONSTANTS.HUB_DIALOG_FIELD_HEIGHT,
            content_padding=ft.Padding(8, 4, 8, 4))

        def _cancel(event):
            dlg.open = False
            page.update()

        def _confirm(event):
            name = (name_field.value or "").strip()
            dlg.open = False
            page.update()
            if not name:
                return
            try:
                os.makedirs(os.path.join(folder, name), exist_ok=False)
            except OSError as exc:
                _log_to_terminal(f"[ERREUR] Création dossier : {exc}", RED)
                return
            _log_to_terminal(f"[OK] Dossier créé : {name}", BLUE)
            _navigate(folder)

        name_field.on_submit = _confirm
        dlg = ft.AlertDialog(
            title=ft.Text("Créer un nouveau dossier", size=CONSTANTS.TEXT_SM, color=WHITE),
            content=name_field,
            actions=[
                ft.TextButton("Créer", on_click=_confirm),
                ft.TextButton("Annuler", on_click=_cancel),
            ],
        )
        page.overlay.append(dlg)
        dlg.open = True
        page.update()

    new_folder_btn = ft.IconButton(
        icon=ft.Icons.CREATE_NEW_FOLDER_OUTLINED,
        icon_color=ORANGE, icon_size=CONSTANTS.ICON_SM,
        style=ft.ButtonStyle(bgcolor=GREY, padding=ft.Padding.all(10)),
        height=CONSTANTS.HUB_TOOLBAR_H, on_click=_create_folder_here,
        tooltip="Créer un nouveau dossier",
    )

    open_menu_btn = ft.TextButton(
        content=ft.Row([
            ft.Icon(ft.Icons.FOLDER_OPEN_OUTLINED, color=ICON_ACTION,
                    size=CONSTANTS.ICON_SM),
            ft.Text("Ouvrir", size=CONSTANTS.TEXT_SM, color=WHITE,
                   weight=ft.FontWeight.W_600),
            ft.Icon(ft.Icons.ARROW_DROP_DOWN, color=WHITE, size=CONSTANTS.ICON_SM),
        ], spacing=4, tight=True),
        style=ft.ButtonStyle(bgcolor=GREY,
                             padding=ft.Padding(12, 0, 10, 0),
                             side=ft.BorderSide(1, BLUE)),
        height=CONSTANTS.HUB_TOOLBAR_H, on_click=_toggle_open_menu,
        tooltip="Favoris, récents, parcourir…",
    )

    # Icon() n'hérite pas de ButtonStyle.color (contrairement à Text()) —
    # couleur posée explicitement sur chaque Icon/Text, sinon l'icône reste
    # au bleu par défaut de Flet au lieu de CONSTANTS.COLOR_BLUE.
    order_mode_icon = ft.Icon(ft.Icons.RECEIPT_LONG_OUTLINED,
                              size=CONSTANTS.ICON_SM, color=BLUE)
    order_mode_text = ft.Text("Mode commande", size=CONSTANTS.TEXT_SM, color=BLUE)
    order_mode_btn = ft.TextButton(
        content=ft.Row([order_mode_icon, order_mode_text], spacing=6, tight=True),
        style=ft.ButtonStyle(bgcolor=GREY, padding=ft.Padding(14, 0, 14, 0)),
        height=CONSTANTS.HUB_TOOLBAR_H, on_click=_toggle_order_mode,
        tooltip="Format + nombre directement sur chaque photo",
    )

    only_sel_btn = _seg_btn(ft.Icons.VISIBILITY_OUTLINED, "Afficher la sélection",
                            _toggle_only_selected)
    only_sel_icon, only_sel_text = only_sel_btn.content.controls
    only_sel_icon.color = only_sel_text.color = BLUE

    # _create_order_folder est défini plus loin (avec le reste de la logique
    # de commande) : lambda pour différer la résolution du nom jusqu'au clic.
    create_order_btn = ft.IconButton(
        ft.Icons.FOLDER_ZIP_OUTLINED, icon_color=BLUE, icon_size=CONSTANTS.ICON_SM,
        height=CONSTANTS.HUB_TOOLBAR_H, tooltip="Créer le dossier de commande",
        on_click=lambda e: page.run_task(_create_order_folder, e),
        visible=order_mode["value"])

    # _open_actions est défini plus loin dans main() (avec le dialogue
    # Actions) : lambda pour différer la résolution du nom jusqu'au clic.
    actions_btn = ft.Button(
        content=ft.Row([
            ft.Icon(ft.Icons.BOLT_OUTLINED, color=DARK, size=CONSTANTS.ICON_SM),
            ft.Text("ACTIONS", size=CONSTANTS.TEXT_SM, color=DARK,
                    weight=ft.FontWeight.W_800),
        ], spacing=6, tight=True),
        style=ft.ButtonStyle(bgcolor=ORANGE, padding=ft.Padding(14, 10, 14, 10),
                             shape=ft.RoundedRectangleBorder(radius=10)),
        height=CONSTANTS.HUB_STATUSBAR_TAP_HEIGHT, on_click=lambda e: _open_actions(e),
    )

    # Les chips Renommer -> Supprimer (ex-"rangée d'actions tactiles") ont
    # déménagé en tête du panneau Actions (cf. _ACTION_CATEGORIES) — retour
    # user : la 2e ligne du header ne garde que la recherche.
    touch_actions_line = ft.Row(
        [search_field_wrap],
        spacing=10, vertical_alignment=ft.CrossAxisAlignment.CENTER, expand=True)

    files_header = ft.Container(
        content=ft.Column([
            ft.Row([
                ft.Row([parent_folder_btn, refresh_folder_btn,
                       new_folder_btn], spacing=8),
                ft.VerticalDivider(width=1, color=GREY),
                open_menu_btn,
                files_path,
                ft.VerticalDivider(width=1, color=GREY),
                sort_btn,
                view_seg_wrap,
            ], spacing=12, vertical_alignment=ft.CrossAxisAlignment.CENTER),
            ft.Row([
                _seg_btn(ft.Icons.SELECT_ALL, "Tout sélectionner", _toggle_all,
                         color=VIOLET),
                _seg_btn(ft.Icons.FLIP, "Inverser", _invert, color=VIOLET),
                _seg_btn(ft.Icons.EVENT, "Même date", _select_same_date,
                         color=VIOLET),
                only_sel_btn,
                ft.VerticalDivider(width=1, color=GREY),
                order_mode_btn,
                create_order_btn,
                ft.Container(expand=True),
            ], spacing=10, vertical_alignment=ft.CrossAxisAlignment.CENTER),
            touch_actions_line,
        ], spacing=10),
        padding=ft.Padding(12, 12, 12, 8),
        bgcolor=BACKGROUND,
    )

    files_surface = ft.Column([
        files_header,
        ft.Divider(height=1, color=GREY),
        files_body,
    ], expand=True, spacing=0)

    # ═════════════════════════════════════════════════════════════════════
    #  Surface Bloc-notes — .notes.md partagé avec Dashboard/SidePanel
    # ═════════════════════════════════════════════════════════════════════
    _notes_file = os.path.join(_APP_DIR, ".notes.md")
    _constants_path = os.path.join(_APP_DIR, "Data", "CONSTANTS.py")
    # Fichier actuellement chargé dans le Bloc-notes — .notes.md par défaut,
    # ou n'importe quel .py/.json/.md/.txt ouvert depuis la surface Fichiers
    # (cf. Dashboard.pyw:1577-1611, même principe de « bloc-notes générique »).
    note_target = {"path": _notes_file}
    _NOTE_LANGUAGES = {
        ".py": fce.CodeLanguage.PYTHON, ".pyw": fce.CodeLanguage.PYTHON,
        ".json": fce.CodeLanguage.JSON,
        ".md": fce.CodeLanguage.MARKDOWN, ".markdown": fce.CodeLanguage.MARKDOWN,
    }

    # flet-code-editor plante sous Linux (retour user) — même repli que
    # Dashboard.pyw:458-481 : TextField brut, sans coloration syntaxique.
    _HAS_CODE_EDITOR = platform.system() != "Linux"

    if _HAS_CODE_EDITOR:
        notes_field = fce.CodeEditor(
            text_style=ft.TextStyle(font_family="monospace", size=CONSTANTS.TERMINAL_FONT_SIZE),
            language=getattr(fce.CodeLanguage, CONSTANTS.NOTEPAD_DEFAULT_LANGUAGE),
            code_theme=fce.CodeTheme.ATOM_ONE_DARK,
            gutter_style=fce.GutterStyle(width=64, background_color=BACKGROUND), expand=True,
        )
    else:
        notes_field = ft.TextField(
            multiline=True, expand=True, min_lines=4,
            text_style=ft.TextStyle(font_family="monospace", size=CONSTANTS.TERMINAL_FONT_SIZE),
            color=WHITE, border_color=ft.Colors.TRANSPARENT, border_radius=6,
            bgcolor=DARK, filled=True,
            hint_text="Écrivez vos notes ici…",
            hint_style=ft.TextStyle(color=LIGHT_GREY, italic=True),
        )
    notes_title = ft.Text("Bloc-notes", size=CONSTANTS.TEXT_LG, color=WHITE,
                          weight=ft.FontWeight.W_500, expand=True, no_wrap=True)
    notes_preview = ft.Markdown(
        "", selectable=True, extension_set=ft.MarkdownExtensionSet.GITHUB_WEB,
        code_theme=ft.MarkdownCodeTheme.ATOM_ONE_DARK, expand=True)
    notes_preview_scroll = ft.ListView(controls=[notes_preview], expand=True)
    # Conteneur unique dont on échange le `.content` (édition <-> aperçu),
    # comme `files_body` plus haut : deux enfants Column avec expand=True
    # se partagent l'espace 50/50 même quand l'un est invisible (Flet
    # conserve la part de flex d'un enfant caché) — d'où le bloc-notes qui
    # ne prenait que la moitié inférieure en aperçu Markdown.
    notes_body = ft.Container(content=notes_field, expand=True, padding=8)
    notes_is_preview = {"value": False}
    notes_autosave_timer = {"task": None}
    notes_dirty = {"value": False}

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
        notes_dirty["value"] = False

    def _notes_save(event=None):
        path = note_target["path"]
        try:
            _backup_file(path)   # filet anti-perte avant écrasement
            with open(path, "w", encoding="utf-8") as f:
                f.write(notes_field.value or "")
        except Exception:
            return
        notes_dirty["value"] = False
        # Redémarrage seulement sur clic explicite (event fourni), pas lors
        # de l'autosave (débounce silencieux) — cf. Dashboard.pyw:1560-1573.
        if path == _constants_path and event is not None:
            _log_to_terminal(
                "[INFO] Redémarrage pour appliquer les nouvelles constantes…",
                ORANGE)
            hub_path = os.path.abspath(__file__)

            async def _restart_async():
                time.sleep(0.4)
                subprocess.Popen([sys.executable, hub_path])
                time.sleep(0.2)
                try:
                    await page.window.close()
                except Exception:
                    pass
                os._exit(0)
            page.run_task(_restart_async)

    async def _notes_autosave_after_delay():
        await asyncio.sleep(CONSTANTS.NOTEPAD_AUTOSAVE_DELAY)
        _notes_save()

    def _notes_on_change(e):
        # Même débounce que Dashboard.pyw:1534-1545 — annule le timer en
        # cours et en relance un à chaque frappe.
        notes_dirty["value"] = True
        t = notes_autosave_timer["task"]
        if t is not None and not t.done():
            t.cancel()
        notes_autosave_timer["task"] = page.run_task(_notes_autosave_after_delay)

    notes_field.on_change = _notes_on_change

    def _open_path_in_notes(path):
        note_target["path"] = path
        if _HAS_CODE_EDITOR:
            ext = os.path.splitext(path)[1].lower()
            notes_field.language = _NOTE_LANGUAGES.get(ext, fce.CodeLanguage.PLAINTEXT)
        notes_title.value = os.path.basename(path)
        _notes_load()
        if notes_is_preview["value"]:
            notes_is_preview["value"] = False
            notes_body.content = notes_field
            notes_preview_btn.icon = ft.Icons.VISIBILITY
            notes_preview_btn.tooltip = "Prévisualiser en Markdown"
        _select_surface("notes")

    def _notes_go_home(event=None):
        """Recharge .notes.md, comme Dashboard.pyw:10259-10265 — mais
        demande confirmation si le fichier ouvert a des modifications non
        enregistrées (autosave différé de CONSTANTS.NOTEPAD_AUTOSAVE_DELAY)."""
        if not notes_dirty["value"]:
            _open_path_in_notes(_notes_file)
            notes_title.value = "Bloc-notes"
            page.update()
            return

        current_name = os.path.basename(note_target["path"])

        def _do_home(discard):
            def _handler(ev):
                dlg.open = False
                if not discard:
                    _notes_save(ev)   # event non-None : applique CONSTANTS.py si besoin
                _open_path_in_notes(_notes_file)
                notes_title.value = "Bloc-notes"
                page.update()
            return _handler

        def _cancel(ev):
            dlg.open = False
            page.update()

        dlg = ft.AlertDialog(
            title=ft.Text("Modifications non enregistrées", size=CONSTANTS.TEXT_SM,
                          color=WHITE),
            content=ft.Text(
                f"Enregistrer les modifications de {current_name} avant "
                f"de recharger le bloc-notes ?", size=CONSTANTS.TEXT_SM, color=WHITE),
            actions=[
                ft.TextButton("Enregistrer", on_click=_do_home(False)),
                ft.TextButton("Ne pas enregistrer", on_click=_do_home(True)),
                ft.TextButton("Annuler", on_click=_cancel),
            ],
        )
        page.overlay.append(dlg)
        dlg.open = True
        page.update()

    def _notes_toggle_preview(event=None):
        notes_is_preview["value"] = not notes_is_preview["value"]
        if notes_is_preview["value"]:
            _notes_save()
            # Texte brut, sans préprocessing : les tentatives de forcer les
            # sauts de ligne (&nbsp;, doubles espaces) cassaient le rendu
            # Markdown standard (listes avalant le texte suivant — cf.
            # retour user). Markdown interprète le texte tel qu'écrit.
            notes_preview.value = notes_field.value or ""
            notes_body.content = notes_preview_scroll
            notes_preview_btn.icon = ft.Icons.EDIT
            notes_preview_btn.tooltip = "Revenir à l'édition"
        else:
            notes_body.content = notes_field
            notes_preview_btn.icon = ft.Icons.VISIBILITY
            notes_preview_btn.tooltip = "Prévisualiser en Markdown"
        page.update()

    def _notes_clear(event=None):
        notes_field.value = ""
        if notes_is_preview["value"]:
            notes_is_preview["value"] = False
            notes_body.content = notes_field
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
            bgcolor=DARK, border_color=BLUE, text_size=CONSTANTS.TEXT_SM,
            height=CONSTANTS.HUB_DIALOG_FIELD_HEIGHT,
            content_padding=ft.Padding(8, 4, 8, 4))
        dlg = ft.AlertDialog(
            title=ft.Text("Créer un fichier ici", size=CONSTANTS.TEXT_SM, color=WHITE),
            content=ft.Column([
                ft.Text(folder, size=CONSTANTS.TEXT_SM, color=GREY, no_wrap=True),
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

    notes_home_btn = ft.IconButton(
        ft.Icons.HOME, icon_color=VIOLET, icon_size=CONSTANTS.ICON_SM,
        tooltip="Charger la note par défaut (.notes.md)",
        on_click=_notes_go_home)
    notes_preview_btn = ft.IconButton(
        ft.Icons.VISIBILITY, icon_color=WHITE, icon_size=CONSTANTS.ICON_SM,
        tooltip="Prévisualiser en Markdown", on_click=_notes_toggle_preview)
    create_file_btn = ft.IconButton(
        ft.Icons.NOTE_ADD_OUTLINED, icon_color=ICON_ACTION, icon_size=CONSTANTS.ICON_SM,
        tooltip="Créer un fichier dans le dossier ouvert",
        on_click=_create_file_here, disabled=not state["folder"])

    notes_surface = ft.Column([
        ft.Container(
            content=ft.Row([
                notes_title,
                notes_home_btn,
                ft.IconButton(ft.Icons.SAVE_OUTLINED, icon_color=ICON_ACTION,
                             icon_size=CONSTANTS.ICON_SM, tooltip="Enregistrer", on_click=_notes_save),
                notes_preview_btn,
                create_file_btn,
                ft.IconButton(ft.Icons.DELETE_OUTLINE, icon_color=RED, icon_size=CONSTANTS.ICON_SM,
                             tooltip="Effacer", on_click=_notes_clear),
            ], spacing=4),
            padding=ft.Padding(8, 8, 8, 0),
            bgcolor=BACKGROUND,
        ),
        ft.Divider(height=1, color=GREY),
        notes_body,
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
    def _ai_input_on_focus(event=None):
        _focused_input["name"] = "ai"

    def _ai_input_on_blur(event=None):
        if _focused_input["name"] == "ai":
            _focused_input["name"] = None
        _history_idx["ai"] = None

    ai_input_field = ft.TextField(
        hint_text="Posez votre question… (Entrée pour envoyer)",
        border_color=BLUE,
        text_style=ft.TextStyle(font_family="monospace", size=CONSTANTS.TERMINAL_FONT_SIZE),
        dense=True, expand=True, color=WHITE, bgcolor=DARK, shift_enter=True,
        on_focus=_ai_input_on_focus, on_blur=_ai_input_on_blur)
    ai_model_dropdown = ft.Dropdown(
        value=CONSTANTS.AI_MODEL_TEXT,
        options=[ft.dropdown.Option(m) for m in CONSTANTS.AI_DROPDOWN_MODELS
                 if m.startswith(("gemini", "claude"))],
        text_size=CONSTANTS.TEXT_SM, dense=True, color=WHITE, bgcolor=DARK, border_color=GREY,
        content_padding=ft.Padding.symmetric(horizontal=6, vertical=0), width=180)
    ai_status_text = ft.Text("", color=LIGHT_GREY, size=CONSTANTS.TEXT_SM, italic=True, max_lines=1,
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
            title=ft.Text(f"🔐 Identifiant requis : {service}", size=CONSTANTS.TEXT_SM, color=WHITE),
            content=ft.Column([
                ft.Text(f"Aucun mot de passe enregistré pour {username}@{service}.",
                       size=CONSTANTS.TEXT_SM, color=WHITE),
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
                            size=CONSTANTS.TEXT_SM, color=WHITE) for a in actions[:40]]
            if len(actions) > 40:
                rows.append(ft.Text(f"… et {len(actions) - 40} autres",
                                    size=CONSTANTS.TEXT_SM, color=LIGHT_GREY))

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
                title=ft.Text("📂 Organiser les fichiers", size=CONSTANTS.TEXT_SM, color=WHITE),
                content=ft.Column([
                    ft.Text(args.get("summary") or "Organisation proposée par l'IA :",
                           size=CONSTANTS.TEXT_SM, color=WHITE),
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

    # Copie de Dashboard.pyw:3665-3744 : confirmation avant toute commande
    # (si CONSTANTS.AI_TERMINAL_CONFIRM) et systématiquement si `admin`
    # (élévation sudo/UAC/Touch ID via _run_elevated dans ai_tools.py) —
    # sans quoi l'IA pouvait exécuter des commandes admin sans validation
    # utilisateur. Même pattern threading.Event() que _ai_tool_organize_files
    # juste au-dessus (dialogue ouvert sur le thread UI, attente bloquante
    # sur le thread worker qui exécute l'outil).
    def _ai_tool_run_terminal_command(args):
        cmd = args.get("command", "")
        desc = args.get("description") or cmd
        admin = bool(args.get("admin", False))
        cwd = state["folder"] or None
        if CONSTANTS.AI_TERMINAL_CONFIRM or admin:
            confirm_event = threading.Event()
            confirm_result = {"value": False}

            def _confirm(e=None):
                confirm_result["value"] = True
                dlg.open = False
                page.update()
                confirm_event.set()

            def _cancel(e=None):
                dlg.open = False
                page.update()
                confirm_event.set()

            dlg_content = [
                ft.Text(desc, size=CONSTANTS.TEXT_SM, color=WHITE),
                ft.Container(height=8),
                ft.Container(
                    ft.Text(cmd, size=CONSTANTS.TEXT_SM, font_family="monospace",
                           color=YELLOW),
                    bgcolor=DARK, padding=10, border_radius=6),
            ]
            if admin:
                dlg_content.append(ft.Container(height=8))
                dlg_content.append(ft.Text(
                    "🔐 Une invite d'administrateur du système s'affichera "
                    "ensuite (mot de passe/Touch ID/UAC).",
                    size=CONSTANTS.TEXT_SM, color=YELLOW))

            dlg = ft.AlertDialog(
                modal=True,
                title=ft.Text(
                    "🔐 Exécuter en administrateur" if admin
                    else "💻 Exécuter une commande",
                    size=CONSTANTS.TEXT_SM, color=WHITE),
                content=ft.Column(dlg_content, tight=True, width=500),
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
            if not confirm_result["value"]:
                return "Commande annulée par l'utilisateur."
        return _run_terminal_command(cmd, cwd=cwd, admin=admin)

    # Copie de Dashboard.pyw:3881-3961 : CONSTANTS.AI_DELETE_CONFIRM (True
    # par défaut) doit toujours faire confirmer une suppression déclenchée
    # par l'IA - sans ça (lambda direct vers _folder_delete_files) l'IA
    # pouvait supprimer des fichiers sans validation utilisateur, même
    # défaut de configuration que run_terminal_command/admin plus haut.
    def _ai_tool_delete_files(args):
        paths = args.get("paths", [])
        summary = args.get("summary", "")
        if not paths:
            return "Aucun fichier à supprimer."
        confirmed = True
        if CONSTANTS.AI_DELETE_CONFIRM:
            del_event = threading.Event()
            del_result = {"confirmed": False}

            def _confirm(e=None):
                del_result["confirmed"] = True
                dlg.open = False
                page.update()
                del_event.set()

            def _cancel(e=None):
                dlg.open = False
                page.update()
                del_event.set()

            rows = [ft.Text(f"• {p}", size=CONSTANTS.TEXT_SM, color=WHITE)
                   for p in paths[:40]]
            if len(paths) > 40:
                rows.append(ft.Text(f"… et {len(paths) - 40} autres",
                                    size=CONSTANTS.TEXT_SM, color=LIGHT_GREY))
            dlg = ft.AlertDialog(
                modal=True,
                title=ft.Text("🗑️ Supprimer des fichiers", size=CONSTANTS.TEXT_SM,
                              color=WHITE),
                content=ft.Column([
                    ft.Text(summary or "Fichiers à supprimer :",
                           size=CONSTANTS.TEXT_SM, color=WHITE),
                    ft.Container(height=6),
                    ft.Column(rows, scroll=ft.ScrollMode.AUTO,
                             height=min(320, len(rows) * 24)),
                ], tight=True, width=500),
                actions=[ft.TextButton("Annuler", on_click=_cancel),
                         ft.Button("Supprimer", bgcolor=RED, color=WHITE,
                                  on_click=_confirm)],
                actions_alignment=ft.MainAxisAlignment.END,
            )

            async def _open_dlg():
                page.overlay.append(dlg)
                dlg.open = True
                page.update()
            page.run_task(_open_dlg)
            del_event.wait(timeout=300)
            confirmed = del_result["confirmed"]
        if not confirmed:
            return "Suppression annulée."
        result = _folder_delete_files(state["folder"], paths)
        page.run_task(_ai_navigate_async, state["folder"])
        return result

    # Copie de Dashboard.pyw:3139-3202 : `analyze_images` est annoncé à l'IA
    # via le schéma partagé (Data/ai_tools.py:1289) mais n'avait aucun
    # handler côté Hub -> l'IA pouvait l'appeler et recevait juste
    # « Outil indisponible ». Même structure que _ai_tool_score_photos
    # juste en dessous (bulle de progression par lot).
    def _ai_tool_analyze_images(fn_name, args):
        folder = state["folder"]
        if not folder:
            return "Aucun dossier ouvert."
        filenames = args.get("filenames") or []
        question = args.get("question", "")
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
                                       f"📸 Analyse de {total} image(s) — lot 1/{batches}…")

        def _on_progress(batch_num, total_batches):
            ai_status_text.value = f"📸 Analyse lot {batch_num}/{total_batches}…"
            progress_ctrl.value = _md_dark(f"📸 Analyse — lot {batch_num}/{total_batches}…")
            _ai_refresh()

        results = _analyze_images_batched(
            CONSTANTS.AI_OLLAMA_URL, model, folder, candidates, question,
            batch_size=batch_n, image_exts=CONSTANTS.IMAGE_EXTS,
            max_size=CONSTANTS.AI_FOLDER_SELECT_IMAGE_SIZE,
            quality=CONSTANTS.AI_FOLDER_SELECT_QUALITY,
            on_progress=_on_progress,
            is_running=lambda: ai_streaming["value"])
        progress_ctrl.value = _md_dark(f"📸 {total} image(s) analysée(s).")
        _ai_refresh()
        return "\n\n".join(results) or "Aucun résultat."

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
            title=ft.Text("❓ Question de l'IA", size=CONSTANTS.TEXT_SM, color=WHITE),
            content=ft.Column([
                ft.Text(question, size=CONSTANTS.TEXT_SM, color=WHITE),
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
        "analyze_images": _ai_tool_analyze_images,
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
                _select_update(paths)
            elif mode == "add":
                _select_update(paths)
            elif mode == "remove":
                for p in paths:
                    _select_discard(p)
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
        "delete_files": _ai_tool_delete_files,
        "web_search": lambda args: _web_search(args.get("query", "")),
        "fetch_url": lambda args: _fetch_url_content(
            args.get("url", ""), max_chars=CONSTANTS.AI_URL_MAX_CHARS),
        "run_terminal_command": _ai_tool_run_terminal_command,
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

    def _export_ai_conversation(to_notepad=False, event=None):
        if not ai_conversation:
            ai_status_text.value = "Aucune conversation à exporter"
            page.update()
            return
        text = _format_ai_conversation(ai_conversation, CONSTANTS.AI_USER_NAME,
                                       CONSTANTS.AI_SEPARATOR_WIDTH)

        async def _copy():
            try:
                await ft.Clipboard().set(text)
                ai_status_text.value = "Conversation copiée dans le presse-papiers"
            except Exception:
                ai_status_text.value = "Erreur lors de la copie"
            page.update()
        page.run_task(_copy)

        if to_notepad:
            current = notes_field.value or ""
            sep = ("\n\n" + "#" * CONSTANTS.AI_SEPARATOR_WIDTH + "\n\n"
                  if current.strip() else "")
            notes_field.value = current + sep + text
            _notes_save()
            if notes_is_preview["value"]:
                notes_preview.value = notes_field.value or ""
            _select_surface("notes")
            page.update()

    def _ai_refresh_attach_row():
        ai_attach_row.controls.clear()
        for entry in ai_pending_images:
            ai_attach_row.controls.append(ft.Container(
                content=ft.Row([
                    ft.Icon(ft.Icons.IMAGE_OUTLINED, size=CONSTANTS.ICON_SM, color=ORANGE),
                    ft.Text(os.path.basename(entry["path"]), size=CONSTANTS.TEXT_SM,
                           color=WHITE),
                    ft.IconButton(ft.Icons.CLOSE, icon_size=CONSTANTS.ICON_SM, icon_color=RED,
                                 on_click=lambda e, en=entry: _ai_remove_image(en)),
                ], spacing=4, tight=True),
                bgcolor=GREY, border_radius=6, padding=ft.Padding(6, 2, 2, 2)))
        for path in ai_pending_files:
            ai_attach_row.controls.append(ft.Container(
                content=ft.Row([
                    ft.Icon(ft.Icons.DESCRIPTION_OUTLINED, size=CONSTANTS.ICON_SM, color=YELLOW),
                    ft.Text(os.path.basename(path), size=CONSTANTS.TEXT_SM, color=WHITE),
                    ft.IconButton(ft.Icons.CLOSE, icon_size=CONSTANTS.ICON_SM, icon_color=RED,
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

    def _mic_stop(auto_send=False):
        """Arrête l'enregistrement et transcrit via Gemini.

        Copie de Dashboard.pyw:4299-4378 : ``auto_send`` (relâchement du
        bouton PTT physique) envoie le message dès la transcription, sans
        attendre une validation manuelle.
        """
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
                    combined = f"{existing} {text}".strip() if existing else text
                    ai_status_text.value = ""
                    if auto_send and not ai_streaming["value"]:
                        ai_input_field.value = ""
                        ai_input_field.update()
                        _send_ai_message(combined)
                    else:
                        ai_input_field.value = combined
                        ai_input_field.update()
                        try:
                            await ai_input_field.focus()
                        except Exception:
                            pass
                else:
                    ai_status_text.value = "Aucun texte reconnu"
                page.update()
            page.run_task(_apply)

        threading.Thread(target=_worker, daemon=True).start()

    def _mic_hotkey_start():
        """Écoute CONSTANTS.AI_VOICE_PTT_KEY : bouton PTT physique (macropad).

        Copie de Dashboard.pyw:4380-4451. Touche f13-f20 (aucun clavier
        standard ne la produit). Appui maintenu = enregistre, relâchement =
        transcrit et envoie directement le message à l'IA, même si Hub n'a
        pas le focus (raccourci global, via pynput).
        """
        ptt_name = CONSTANTS.AI_VOICE_PTT_KEY
        try:
            from pynput import keyboard as _pynput_kb
        except ImportError:
            _log_to_terminal(
                f"[IA] pynput absent : bouton micro physique ({ptt_name}) "
                "indisponible (pip install pynput).", ORANGE)
            return

        ptt_key = getattr(_pynput_kb.Key, ptt_name, None)
        if ptt_key is None:
            _log_to_terminal(
                f"[ERREUR] Touche PTT inconnue de pynput : {ptt_name!r} "
                "(voir CONSTANTS.AI_VOICE_PTT_KEY, doit être f13..f20).",
                RED)
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
        except Exception as hotkey_error:
            _log_to_terminal(
                f"[ERREUR] Bouton micro physique ({ptt_name}) : "
                f"{hotkey_error}", RED)
            return
        _mic_state["hotkey_listener"] = listener
        _log_to_terminal(f"[IA] Bouton micro physique ({ptt_name}) actif.", BLUE)

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
                _active_model = ai_model_dropdown.value or CONSTANTS.AI_MODEL_TEXT
                _history_limit = (
                    CONSTANTS.AI_HISTORY_LIMIT_CLOUD
                    if _active_model.startswith(("gemini", "claude"))
                    else CONSTANTS.AI_HISTORY_LIMIT_LOCAL)
                history = ai_conversation[-_history_limit:]
                # Une troncature brute peut couper juste après un tour
                # assistant(tool_calls), laissant une réponse d'outil
                # orpheline en tête, OU couper juste avant ce tour, laissant
                # le function_call lui-même en tête sans le tour "user" qui
                # le précédait : Gemini exige qu'un tour function_call soit
                # immédiatement précédé d'un tour user ou function_response,
                # sinon 400 INVALID_ARGUMENT (cf. nettoyage MCP Notion,
                # plusieurs paires d'appels d'outils dépassant la fenêtre).
                while history and (
                    history[0].get("role") == "tool"
                    or (history[0].get("role") == "assistant"
                        and history[0].get("tool_calls"))
                ):
                    history = history[1:]
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
        _history_add("ai", text)
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
        ft.Icons.DELETE_OUTLINE, icon_color=RED, icon_size=CONSTANTS.ICON_SM,
        tooltip="Effacer la conversation", on_click=_ai_clear_conversation)
    ai_copy_button = ft.IconButton(
        ft.Icons.COPY_ALL, icon_color=BLUE, icon_size=CONSTANTS.ICON_SM,
        tooltip="Copier la conversation IA",
        on_click=lambda e: _export_ai_conversation(to_notepad=False))
    ai_to_notepad_button = ft.IconButton(
        ft.Icons.SEND_TO_MOBILE, icon_color=VIOLET, icon_size=CONSTANTS.ICON_SM,
        tooltip="Transférer la conversation vers le bloc-notes",
        on_click=lambda e: _export_ai_conversation(to_notepad=True))

    ia_surface = ft.Column([
        ft.Container(
            content=ft.Row([
                ft.Text("Assistant IA", size=CONSTANTS.TEXT_LG, color=WHITE,
                        weight=ft.FontWeight.W_500, expand=True),
                ai_model_dropdown,
                ai_copy_button,
                ai_to_notepad_button,
                ai_clear_button,
            ], spacing=8),
            padding=ft.Padding(8, 8, 8, 0), bgcolor=BACKGROUND),
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
            dialog_title="Dossier de destination pour la commande",
            initial_directory=state["folder"] or None)
        if not dest_root:
            return
        order_folder = _unique_dest(dest_root, "COMMANDE")
        os.makedirs(order_folder, exist_ok=True)
        prices, grand_total = _order_totals()
        manifest = []
        for path, fmt, n in _order_lines():
            if not os.path.isfile(path):
                continue
            # Un sous-dossier par format/taille, avec dans chacun le
            # nombre de tirages en préfixe du nom (ex. "3X_photo.jpg") —
            # facilite le tri chez l'imprimeur (retour user).
            fmt_folder = os.path.join(order_folder, fmt)
            os.makedirs(fmt_folder, exist_ok=True)
            is_bw = order_bw.get(path, False)
            stem, ext = os.path.splitext(os.path.basename(path))
            nb_marker = "_NB" if is_bw else ""
            dest = _unique_dest(fmt_folder, f"{n}X_{stem}{nb_marker}{ext}")
            try:
                if is_bw:
                    with PILImage.open(path) as im:
                        im.convert("L").convert("RGB").save(dest)
                else:
                    shutil.copy2(path, dest)
            except Exception:
                continue
            nb_label = " (N&B)" if is_bw else ""
            manifest.append(
                f"{fmt}/{os.path.basename(dest)} — {fmt}{nb_label} × {n} = "
                f"{prices[(path, fmt)]:.2f} €")
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
            title=ft.Text("Supprimer cette entrée ?", size=CONSTANTS.TEXT_SM, color=WHITE),
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
                         size=CONSTANTS.TEXT_SM, color=WHITE),
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
                                    size=CONSTANTS.TEXT_SM, color=WHITE,
                                    max_lines=2,
                                    overflow=ft.TextOverflow.ELLIPSIS),
                    tooltip=f"Copier la description : {entry['description']}",
                    expand=True, ink=True,
                    on_click=lambda e, t=entry["description"]: _liste_copy(t)),
                ft.IconButton(ft.Icons.EDIT_OUTLINED, icon_size=CONSTANTS.ICON_SM, icon_color=GREY,
                             on_click=lambda e, i=index: _liste_edit(i)),
                ft.IconButton(ft.Icons.DELETE_OUTLINE, icon_size=CONSTANTS.ICON_SM, icon_color=RED,
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
            dialog_title="Dossier pour le nouveau fichier .json",
            initial_directory=state["folder"] or None)
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
            title=ft.Text("Nouveau fichier JSON", size=CONSTANTS.TEXT_SM, color=WHITE),
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
                       size=CONSTANTS.ICON_SM),
                liste_path_text,
                ft.IconButton(ft.Icons.NOTE_ADD_OUTLINED, icon_color=YELLOW,
                             icon_size=CONSTANTS.ICON_SM, tooltip="Nouveau fichier .json",
                             on_click=_liste_new_file),
                ft.IconButton(ft.Icons.REFRESH, icon_color=BLUE, icon_size=CONSTANTS.ICON_SM,
                             tooltip="Recharger depuis le disque",
                             on_click=_liste_reload),
                ft.Button("Ajouter", icon=ft.Icons.ADD,
                                  on_click=lambda e: _liste_edit(None)),
            ], spacing=6),
            padding=ft.Padding(8, 8, 8, 0), bgcolor=BACKGROUND),
        ft.Container(
            content=ft.Text(
                "Cliquer sur le nom (bleu) copie le nom, cliquer sur la "
                "description (gris) copie la description.",
                size=CONSTANTS.TEXT_SM, color=GREY),
            padding=ft.Padding(8, 0, 8, 4)),
        ft.Divider(height=1, color=GREY),
        ft.Container(content=liste_list_view, expand=True),
    ], expand=True, spacing=0)
    _liste_load()
    _liste_render()

    # ─── Surfaces encore à construire (placeholders structurés) ──────────
    def _placeholder(label):
        return ft.Container(
            content=ft.Text(f"{label} — à venir", size=CONSTANTS.TEXT_SM,
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
        if state["surface"] == "notes" and key != "notes":
            _notes_save()   # enregistre le bloc-notes au changement d'onglet
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
        label_ctrl = ft.Text(label, size=CONSTANTS.TEXT_SM,
                             color=DARK if is_active else WHITE, no_wrap=True,
                             weight=ft.FontWeight.W_700 if is_active
                             else ft.FontWeight.NORMAL)
        tab = ft.Container(
            content=ft.Column([
                icon_ctrl,
                ft.Container(content=label_ctrl, rotate=ft.Rotate(-1.5708),
                            alignment=ft.Alignment.CENTER, height=86),
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

    # Scripts en .py (pas .pyw) qui ouvrent quand même leur propre fenêtre
    # Flet — l'extension seule ne suffit pas à détecter une vraie appli GUI.
    _GUI_TOOLS_PY_EXT = {"Augmentation IA.py"}

    def _launch_tool(script_name, is_local=False, extra_env=None):
        app_path = os.path.join(_APP_DIR, "Data", script_name)
        if not os.path.exists(app_path):
            _log_to_terminal(f"[ERREUR] Introuvable : {script_name}", RED)
            return
        folder = state["folder"] or ""
        # Comme Dashboard.pyw:8933-8935 : sans ce garde-fou, un script
        # "dossier" reçoit FOLDER_PATH="" et retombe sur le dossier courant
        # du process — il tourne "pour de vrai" sur le mauvais dossier
        # (silencieusement, 0 fichier trouvé) au lieu d'échouer clairement.
        if not is_local and not folder:
            _log_to_terminal(
                "[ERREUR] Veuillez sélectionner un dossier avant de lancer "
                "cette application", RED)
            return
        picked = list(selected)
        display_name = (script_name[:-4] if script_name.endswith(".pyw")
                        else script_name[:-3])
        _log_to_terminal(f"▶ Lancement de {display_name}...", BLUE)

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
                    [sys.executable, "-u", app_path], env=env,
                    cwd=os.path.join(_APP_DIR, "Data"),
                    stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                    text=True, encoding="utf-8", errors="replace", bufsize=1)
            except Exception as exc:
                _log_to_terminal(f"[ERREUR] {script_name} : {exc}", RED)
                return
            # Outil avec sa propre fenêtre Flet (.pyw) : minimiser Hub le
            # temps qu'il tourne, comme Dashboard.pyw:8992-9004/9058-9068.
            is_gui_tool = (app_path.endswith(".pyw")
                          or script_name in _GUI_TOOLS_PY_EXT)
            if is_gui_tool:
                page.window.minimized = True
                page.update()

            # Lecture en temps réel, comme Dashboard.pyw:9314-9348
            # (read_output) : chaque ligne part au terminal au fil de l'eau
            # au lieu d'attendre la fin du process pour un résumé — sinon
            # aucune info avant la fin (et aucune en cas d'erreur muette).
            # Comme Dashboard.pyw:9013-9016/9107-9111 : une ligne
            # "NAVIGATE_TO:<chemin>" est interceptée plutôt que loguée, pour
            # naviguer vers le dossier réellement produit par l'outil (ex.
            # Transfert vers TEMP.py qui crée un sous-dossier daté).
            nav_target = {"path": None}

            def _read_output(pipe, color):
                try:
                    for line in iter(pipe.readline, ""):
                        stripped = line.rstrip()
                        if not stripped:
                            continue
                        if stripped.startswith("NAVIGATE_TO:"):
                            nav_target["path"] = stripped[len("NAVIGATE_TO:"):]
                        else:
                            _log_to_terminal(stripped, color)
                except Exception:
                    pass
                finally:
                    pipe.close()

            t_out = threading.Thread(target=_read_output,
                                     args=(proc.stdout, WHITE), daemon=True)
            t_err = threading.Thread(target=_read_output,
                                     args=(proc.stderr, RED), daemon=True)
            t_out.start()
            t_err.start()
            proc.wait()
            t_out.join()
            t_err.join()
            if is_gui_tool:
                page.window.minimized = False
                page.window.maximized = True
                page.run_task(page.window.to_front)
                page.update()
            if proc.returncode != 0:
                _log_to_terminal(
                    f"[ERREUR] {script_name} — code retour {proc.returncode}",
                    RED)
            else:
                _log_to_terminal(f"[OK] {script_name} terminé", GREEN)
            page.run_task(_tool_refresh, nav_target["path"] or folder)

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
            title=ft.Text("Renommer séquence", size=CONSTANTS.TEXT_SM, color=WHITE),
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
                content=ft.Text(label, size=CONSTANTS.TEXT_SM, color=CONSTANTS.COLOR_HOVER_YELLOW,
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

    def _launch_transfert_temp(event=None):
        # Même choix conserver/supprimer qu'au Dashboard.pyw:9024-9044
        # (transfer_confirm_dialog) avant de lancer le transfert.
        picked = list(selected)
        scope = (f"{len(picked)} fichier(s) sélectionné(s)" if picked
                 else "le contenu du dossier")

        def _launch(delete_after):
            def _on_click(e):
                dlg.open = False
                page.update()
                _launch_tool("Transfert vers TEMP.py", is_local=True,
                            extra_env={"DELETE_AFTER_TRANSFER":
                                       "1" if delete_after else "0"})
            return _on_click

        dlg = ft.AlertDialog(
            title=ft.Text("Supprimer les fichiers après transfert ?",
                         size=CONSTANTS.TEXT_SM, color=WHITE),
            content=ft.Text(
                f"{scope} seront transférés vers TEMP.\n\n"
                "Supprimer les fichiers source après la copie réussie ?",
                color=WHITE),
            actions=[
                ft.TextButton("Conserver", on_click=_launch(False)),
                ft.TextButton("Supprimer", on_click=_launch(True),
                             style=ft.ButtonStyle(color=RED)),
            ],
        )
        page.overlay.append(dlg)
        dlg.open = True
        page.update()

    def _print_paths(paths):
        # Partagé entre le bouton Imprimer (titlebar/Actions, sélection ou
        # dossier entier) et l'entrée « Imprimer » du menu clic-droit
        # (fichier sur lequel on a cliqué).
        imgs = [p for p in paths
                if os.path.splitext(p)[1].lower() in CONSTANTS.IMAGE_EXTS]
        if not imgs:
            _log_to_terminal("[ATTENTION] Aucune image à imprimer", ORANGE)
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
            _log_to_terminal(f"[OK] Impression lancée pour {len(imgs)} image(s)",
                             GREEN)
        except Exception as exc:
            _log_to_terminal(f"[ERREUR] Impression : {exc}", RED)
            return
        # Bascule en mode ruban quelle que soit l'entrée (titlebar ou
        # clic-droit) : laisse la fenêtre d'impression de l'OS passer
        # devant sans que Hub prenne toute la place.
        if not _strip_state["active"]:
            _toggle_strip()

    def _launch_print(event=None):
        _print_paths(list(selected) or content["imgs"])
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
        if not _strip_state["active"]:
            _toggle_strip()

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
            title=ft.Text(title, size=CONSTANTS.TEXT_SM, color=WHITE),
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

    def _launch_number_prompt(title, fields, script_name):
        # `fields` : liste de (label, suffix, default, env_key) — un champ
        # numérique par tuple, tous requis pour lancer l'outil.
        text_fields = [
            ft.TextField(
                label=label, value=str(default),
                suffix=ft.Text(suffix, color=GREY), autofocus=(i == 0),
                width=200, bgcolor=DARK, border_color=GREY, color=WHITE,
                keyboard_type=ft.KeyboardType.NUMBER)
            for i, (label, suffix, default, env_key) in enumerate(fields)
        ]

        def _cancel(e):
            dlg.open = False
            page.update()

        def _confirm(e):
            env = {}
            for (label, suffix, default, env_key), field in zip(fields, text_fields):
                try:
                    env[env_key] = str(int((field.value or "").strip()))
                except ValueError:
                    field.error_text = "Nombre requis"
                    page.update()
                    return
            dlg.open = False
            page.update()
            _launch_tool(script_name, extra_env=env)

        text_fields[-1].on_submit = _confirm
        dlg = ft.AlertDialog(
            title=ft.Text(title, size=CONSTANTS.TEXT_SM, color=WHITE),
            content=ft.Column(text_fields, spacing=8, tight=True),
            actions=[ft.TextButton("Annuler", on_click=_cancel),
                     ft.TextButton("Lancer", on_click=_confirm)],
        )
        page.overlay.append(dlg)
        dlg.open = True
        page.update()

    def _launch_redimensionner(event=None):
        _launch_number_prompt("Redimensionner", [
            ("Dimension max", "px", CONSTANTS.RESIZE_DEFAULT, "RESIZE_SIZE"),
            ("Qualité", "%", 100, "RESIZE_QUALITY"),
        ], "Redimensionner.py")

    def _launch_redimensionner_filigrane(event=None):
        _launch_number_prompt("Redimensionner + filigrane", [
            ("Dimension max", "px", CONSTANTS.RESIZE_DEFAULT,
             "RESIZE_WATERMARK_SIZE"),
        ], "Redimensionner filigrane.py")

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
        tile2, sw2, f2 = _section("Grain — Couche 2", ORANGE, True, [
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
            title=ft.Text("Grain pellicule — paramètres", size=CONSTANTS.TEXT_SM,
                         color=WHITE),
            content=ft.Column(
                [ft.Text("Les valeurs par défaut viennent de CONSTANTS.py "
                         "(section 12).", size=CONSTANTS.TEXT_SM, color=GREY),
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

    def _launch_comparaison(event=None):
        # Comme Dashboard.pyw:992-1074 (_launch_comparaison) : le second
        # dossier vient de la sélection quand c'est possible, pas d'un
        # sélecteur systématique — 1 dossier coché = 2e dossier direct,
        # 2 dossiers cochés = les deux, 2 images cochées = comparaison de
        # cette paire précise. Sélecteur seulement en dernier recours.
        folder1 = state["folder"] or ""
        if not folder1:
            _log_to_terminal(
                "[ERREUR] Veuillez sélectionner un dossier avant de lancer "
                "la Comparaison", RED)
            return
        picked = list(selected)
        picked_images = [
            p for p in picked if os.path.isfile(p)
            and os.path.splitext(p)[1].lower() in CONSTANTS.IMAGE_EXTS]
        picked_dirs = [p for p in picked if os.path.isdir(p)]

        def _do_launch(folder2):
            env = {"FOLDER_PATH": folder1, "SELECTED_FILES": ""}
            if folder2:
                env["SECOND_FOLDER"] = folder2
            if len(picked_images) == 2:
                env["SELECTED_PAIR_FILES"] = "|".join(
                    os.path.basename(p) for p in picked_images)
                env["SELECTED_PAIR_PATHS"] = "|".join(picked_images)
            else:
                images_in_folder1 = [
                    p for p in picked_images
                    if os.path.normpath(os.path.dirname(p))
                    == os.path.normpath(folder1)]
                if images_in_folder1:
                    env["SELECTED_FILES"] = "|".join(
                        os.path.basename(p) for p in images_in_folder1)
            _launch_tool("Comparaison.pyw", extra_env=env)

        if len(picked_images) == 2:
            _do_launch("")
            return
        if len(picked_dirs) >= 2:
            folder1 = os.path.normpath(picked_dirs[0])
            _do_launch(os.path.normpath(picked_dirs[1]))
            return
        if len(picked_dirs) == 1:
            _do_launch(os.path.normpath(picked_dirs[0]))
            return

        async def _pick_and_launch():
            picked_path = await ft.FilePicker().get_directory_path(
                dialog_title="Sélectionner le second dossier à comparer",
                initial_directory=folder1)
            if picked_path:
                _do_launch(os.path.normpath(picked_path))
            else:
                _log_to_terminal(
                    "[INFO] Comparaison annulée (pas de second dossier "
                    "sélectionné)", LIGHT_GREY)

        page.run_task(_pick_and_launch)

    def _launch_recadrage_auto(event=None):
        saved = _load_crop_auto_config()
        default_fmt = saved.get("format") if saved.get("format") in CONSTANTS.FORMATS else "10x15"
        default_w, default_h = CONSTANTS.FORMATS[default_fmt]
        manual = {"value": bool(saved.get("manual", False))}

        fmt_dd = ft.Dropdown(
            options=[ft.dropdown.Option(name) for name in CONSTANTS.FORMATS],
            value=default_fmt, width=280, bgcolor=DARK, border_color=GREY,
            color=WHITE, disabled=manual["value"])
        width_field = ft.TextField(
            label="Largeur (mm)", value=str(saved.get("manual_w", default_w)),
            width=132, bgcolor=DARK, border_color=GREY, color=WHITE,
            disabled=not manual["value"], keyboard_type=ft.KeyboardType.NUMBER)
        height_field = ft.TextField(
            label="Hauteur (mm)", value=str(saved.get("manual_h", default_h)),
            width=132, bgcolor=DARK, border_color=GREY, color=WHITE,
            disabled=not manual["value"], keyboard_type=ft.KeyboardType.NUMBER)
        manual_switch = ft.Switch(label="Saisie manuelle (mm)",
                                  value=manual["value"])
        fit_switch = ft.Switch(label="Fit 100% (sans rognage)",
                               value=bool(saved.get("fit", False)))
        white_border_switch = ft.Switch(label="Bord blanc 5mm",
                                        value=bool(saved.get("white_border", False)))
        scope_text = ft.Text(
            f"Portée auto : {'sélection en cours' if selected else 'tout le dossier'}",
            size=CONSTANTS.TEXT_SM, color=GREY)

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
            _save_crop_auto_config({
                "format": fmt_dd.value, "manual": manual["value"],
                "manual_w": width_field.value, "manual_h": height_field.value,
                "fit": fit_switch.value,
                "white_border": white_border_switch.value,
            })
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
            title=ft.Text("Recadrage automatique — format", size=CONSTANTS.TEXT_SM,
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
                    [ft.Icon(icon, size=CONSTANTS.ICON_SM, color=BLUE),
                     ft.Text(label, size=CONSTANTS.TEXT_SM, color=WHITE,
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
            title=ft.Text("Copyright", size=CONSTANTS.TEXT_SM, color=WHITE),
            content=ft.Column([options_row, custom_field], spacing=10,
                              tight=True),
            actions=[ft.TextButton("Annuler", on_click=_cancel),
                     ft.TextButton("Lancer", on_click=_confirm)],
        )
        page.overlay.append(dlg)
        dlg.open = True
        page.update()

    async def _sync_two_folders(event=None):
        """Comme Dashboard.pyw:9692-9782 (_sync_two_folders) : synchronise
        le dossier courant avec un 2e dossier choisi (sous-dossiers
        inclus). Pour chaque fichier, la version la plus récente (mtime)
        est copiée du côté qui ne l'a pas ou qui a une version plus
        ancienne. Aucun fichier n'est jamais supprimé."""
        folder_a = state["folder"]
        if not folder_a:
            _log_to_terminal("[ERREUR] Aucun dossier ouvert à synchroniser", RED)
            return

        folder_b = await ft.FilePicker().get_directory_path(
            dialog_title="Choisir le 2e dossier à synchroniser")
        if not folder_b:
            return
        folder_a = os.path.normpath(folder_a)
        folder_b = os.path.normpath(folder_b)
        if folder_a.lower() == folder_b.lower():
            _log_to_terminal("[ERREUR] Les 2 dossiers sont identiques", RED)
            return

        def _collect_files(src_root, dst_root):
            tasks = []
            for src_dir, _dirs, files in os.walk(src_root):
                rel = os.path.relpath(src_dir, src_root)
                dst_dir = dst_root if rel == "." else os.path.join(dst_root, rel)
                for name in files:
                    if CONSTANTS.is_os_junk(name):
                        continue
                    tasks.append((os.path.join(src_dir, name), dst_dir,
                                  os.path.join(dst_dir, name), name))
            return tasks

        def _do_sync():
            tasks = _collect_files(folder_a, folder_b) + _collect_files(folder_b, folder_a)
            total = len(tasks)
            _log_to_terminal(f"[...] {total} fichier(s) à comparer…", ORANGE)

            progress_text = ft.Text("", size=CONSTANTS.TERMINAL_FONT_SIZE,
                                    color=BLUE, font_family="monospace")
            terminal_output.controls.append(progress_text)
            try:
                page.update()
            except Exception:
                pass

            copied = 0
            errors = []
            last_update = 0
            for i, (src_path, dst_dir, dst_path, name) in enumerate(tasks, start=1):
                progress_text.value = f"[{i}/{total}] {name}"
                now = time.time()
                if now - last_update >= 0.1 or i == total:
                    last_update = now
                    try:
                        progress_text.update()
                    except Exception:
                        pass
                try:
                    if not os.path.exists(dst_path) or (
                            os.path.getmtime(src_path) > os.path.getmtime(dst_path)):
                        os.makedirs(dst_dir, exist_ok=True)
                        shutil.copy2(src_path, dst_path)
                        copied += 1
                except Exception as err:
                    errors.append(f"{name}: {err}")

            if copied:
                _log_to_terminal(f"[OK] {copied} fichier(s) synchronisé(s)", GREEN)
            else:
                _log_to_terminal("[OK] Dossiers déjà synchronisés", BLUE)
            for err in errors:
                _log_to_terminal(f"[ERREUR] {err}", RED)
            _navigate(folder_a)

        _log_to_terminal(f"[...] Synchronisation avec {folder_b} en cours…", ORANGE)
        threading.Thread(target=_do_sync, daemon=True).start()
        _close_actions()

    # (label, icône, couleur, handler)
    # Catégories = les regroupements du flux de travail réel (cf. mémoire
    # project_business_workflow), pas les intitulés génériques de la
    # maquette (celle-ci utilisait des actions fictives) — Bluetooth et
    # Imprimer n'y sont plus : remontés dans la barre de titre (accès global).
    _ACTION_CATEGORIES = [
        ("Édition", [
            # Ex-rangée d'actions tactiles du header (retour user : déplacée
            # tout en haut du panneau Actions). Mêmes icônes/couleurs
            # qu'avant, opère toujours sur `selected`. Chaque action ferme
            # le panneau une fois lancée (retour user), contrairement aux
            # _launch_tool ci-dessous qui, eux, ferment déjà après lancement
            # de leur sous-processus.
            ("Renommer", ft.Icons.DRIVE_FILE_RENAME_OUTLINE, BLUE,
             lambda e: (_rename_item(list(selected)), _close_actions())
                       if len(selected) == 1 else None),
            ("Copier", ft.Icons.CONTENT_COPY, BLUE,
             lambda e: (_do_copy(list(selected)), _close_actions())
                       if selected else None),
            ("Couper", ft.Icons.CONTENT_CUT, ORANGE,
             lambda e: (_do_cut(list(selected)), _close_actions())
                       if selected else None),
            ("Coller", ft.Icons.CONTENT_PASTE, YELLOW,
             lambda e: (_do_paste(), _close_actions())),
            ("Dupliquer", ft.Icons.FILE_COPY_OUTLINED, BLUE,
             lambda e: (_do_duplicate(list(selected)), _close_actions())
                       if selected else None),
            ("Zipper", ft.Icons.FOLDER_ZIP_OUTLINED, YELLOW,
             lambda e: (_do_zip(list(selected)), _close_actions())
                       if selected else None),
            ("Dézipper", ft.Icons.UNARCHIVE_OUTLINED, ORANGE,
             lambda e: (_do_unzip(list(selected)), _close_actions())
                       if selected else None),
            ("Ajouter à l'IA", ft.Icons.SMART_TOY_OUTLINED, VIOLET,
             lambda e: (_add_to_ai(list(selected)), _close_actions())
                       if selected else None),
            ("Supprimer", ft.Icons.DELETE_OUTLINE, RED,
             lambda e: (_do_delete(list(selected)), _close_actions())
                       if selected else None),
        ]),
        ("Transfert & préparation", [
            ("Transfert vers TEMP", ft.Icons.DRIVE_FILE_MOVE_OUTLINED, BLUE,
             _launch_transfert_temp),
            ("Conversion JPG", ft.Icons.IMAGE_OUTLINED, BLUE,
             lambda e: _launch_tool("Conversion JPG.py",
                                    extra_env={"CONVERT_FORMAT": "jpg"})),
            ("Conversion PNG", ft.Icons.IMAGE_OUTLINED, BLUE,
             lambda e: _launch_tool("Conversion JPG.py",
                                    extra_env={"CONVERT_FORMAT": "png"})),
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
            ("Kiosque — Studios", ft.Icons.STOREFRONT_OUTLINED, ORANGE,
             lambda e: _launch_kiosk("STUDIOS", e)),
            ("Kiosque — Tirages", ft.Icons.LOCAL_PRINTSHOP_OUTLINED, ORANGE,
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
             _launch_comparaison),
        ]),
        ("Export & livrables", [
            ("Redimensionner", ft.Icons.PHOTO_SIZE_SELECT_LARGE_OUTLINED, ORANGE,
             _launch_redimensionner),
            ("Redimensionner filigrane", ft.Icons.BRANDING_WATERMARK_OUTLINED,
             ORANGE, _launch_redimensionner_filigrane),
            ("Images en PDF", ft.Icons.PICTURE_AS_PDF_OUTLINED, ORANGE,
             _launch_images_en_pdf),
            ("Remerciements", ft.CupertinoIcons.BIN_XMARK_FILL, ORANGE,
             lambda e: _launch_tool("Remerciements.py")),
            ("Copyright", ft.Icons.COPYRIGHT_OUTLINED, ORANGE,
             _launch_copyright),
            ("Nettoyer métadonnées", ft.Icons.CLEANING_SERVICES_OUTLINED, ORANGE,
             lambda e: _launch_tool("Nettoyer metadonnées.py")),
        ]),
        ("Maintenance", [
            ("Nettoyer anciens fichiers (> 60 jours)", ft.Icons.AUTO_DELETE,
             RED, lambda e: _launch_tool(
                 "Nettoyer anciens fichiers.py", is_local=True)),
            ("Synchroniser avec un autre dossier", ft.Icons.SYNC,
             CONSTANTS.COLOR_HOVER_YELLOW,
             lambda e: page.run_task(_sync_two_folders, e)),
        ]),
    ]

    def _action_row(label, icon, color, handler, trailing=None):
        # Ligne de liste (ft.ListTile) plutôt qu'une carte en grille : plus
        # aucun calcul de colonnes/aspect ratio à faire tenir juste, fiable
        # quelle que soit la largeur — la grille précédente n'a jamais
        # correctement rendu ses hauteurs (retour user, plusieurs essais).
        return ft.ListTile(
            leading=ft.Icon(icon, color=color, size=CONSTANTS.ICON_LG),
            title=ft.Text(label, size=CONSTANTS.TEXT_SM, color=WHITE),
            trailing=trailing,
            on_click=handler, hover_color=GREY,
            content_padding=ft.Padding(left=8, top=4, right=8, bottom=4),
        )

    def _action_category(label, tools):
        # Libellé de catégorie en BLUE (pas GREY) : GREY sur le fond DARK
        # de l'overlay est quasi illisible, deux gris trop proches en
        # luminance — cf. retour user.
        return ft.Column([
            ft.Text(label.upper(), size=CONSTANTS.TEXT_SM, color=BLUE,
                    weight=ft.FontWeight.W_700),
            ft.Column([_action_row(*t) for t in tools], spacing=0),
        ], spacing=6)

    # "Ouvrir avec" — ex-menu clic-droit (cf. _with_ctx_menu), déplacé ici
    # car le clic droit ouvre désormais ce panneau au lieu d'un menu dédié.
    # Catégorie reconstruite à chaque ouverture (_open_actions) : la liste
    # de programmes vient d'open_with.json, modifiable via "Ajouter un
    # programme..." -> doit refléter les ajouts sans relancer le Hub.
    _open_with_category_col = ft.Column(spacing=6)

    def _remove_open_with_program(prog, event=None):
        programs = [p for p in _load_open_with_programs()
                   if not (p.get("label") == prog.get("label")
                           and p.get("exe") == prog.get("exe"))]
        _save_open_with_programs(programs)
        _rebuild_open_with_category()
        page.update()

    def _rebuild_open_with_category():
        rows = [
            _action_row(
                f"Ouvrir avec {p['label']}", ft.Icons.OPEN_IN_NEW, BLUE,
                lambda e, p=p: (_open_files_with(p, list(selected)), _close_actions())
                               if selected else None,
                trailing=ft.IconButton(
                    ft.Icons.CLOSE, icon_color=RED,
                    icon_size=CONSTANTS.ICON_SM,
                    tooltip=f"Supprimer {p['label']}",
                    on_click=lambda e, p=p: _remove_open_with_program(p)))
            for p in _load_open_with_programs()
        ]
        rows.append(_action_row("Ajouter un programme...", ft.Icons.ADD,
                                GREEN, lambda e: _add_open_with_program()))
        _open_with_category_col.controls = [
            ft.Text("OUVRIR AVEC", size=CONSTANTS.TEXT_SM, color=BLUE,
                    weight=ft.FontWeight.W_700),
            ft.Column(rows, spacing=0),
        ]

    _rebuild_open_with_category()

    # Overlay en demi-largeur (retour user : le plein écran gaspillait
    # l'espace) — un Row avec deux enfants `expand=1` se partage 50/50 et
    # reste correct au redimensionnement, pas besoin de recalculer une
    # largeur en pixels. Le fond gauche est cliquable pour fermer (« tap
    # outside »), comme un vrai overlay/drawer.
    actions_panel = ft.Container(
        content=ft.Column([
            ft.Container(
                content=ft.Row([
                    ft.Icon(ft.Icons.BOLT_OUTLINED, color=ORANGE,
                           size=CONSTANTS.ICON_SM),
                    ft.Text("Actions", size=CONSTANTS.TEXT_LG, color=WHITE,
                           weight=ft.FontWeight.W_700, expand=True),
                    ft.IconButton(ft.Icons.CLOSE, icon_color=RED,
                                 icon_size=CONSTANTS.ICON_LG,
                                 on_click=lambda e: _close_actions(),
                                 tooltip="Fermer"),
                ], spacing=10),
                padding=ft.Padding(20, 16, 20, 16), bgcolor=BACKGROUND,
            ),
            ft.Divider(height=1, color=GREY),
            ft.Container(
                content=ft.Column(
                    [_action_category(label, tools)
                     for label, tools in _ACTION_CATEGORIES]
                    + [_open_with_category_col],
                    spacing=20, scroll=ft.ScrollMode.AUTO, expand=True),
                padding=20, expand=True,
            ),
        ], spacing=0, expand=True),
        bgcolor=DARK, expand=1,
    )
    actions_overlay = ft.Row([
        ft.Container(expand=1, ink=False,
                    bgcolor=ft.Colors.with_opacity(0.35, "black"),
                    on_click=lambda e: _close_actions()),
        actions_panel,
    ], expand=True, spacing=0,
       vertical_alignment=ft.CrossAxisAlignment.STRETCH)

    def _close_actions(event=None):
        if actions_overlay in page.overlay:
            page.overlay.remove(actions_overlay)
        # Que le panneau se ferme parce qu'une action vient d'être lancée
        # ou parce que l'utilisateur l'a simplement refermé, la sélection
        # ne doit pas rester en place (retour user) — chaque lanceur lit
        # `selected` avant d'appeler cette fonction, donc le vider ici est
        # sûr dans tous les cas.
        selected.clear()
        _update_sel_count()
        _render()
        page.update()
        page.run_task(_focus_active_surface)

    def _open_actions(event):
        _rebuild_open_with_category()   # reflète un programme ajouté entre-temps
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
    def _terminal_input_on_focus(event=None):
        _suspend_kb(event)
        _focused_input["name"] = "terminal"

    def _terminal_input_on_blur(event=None):
        _resume_kb(event)
        if _focused_input["name"] == "terminal":
            _focused_input["name"] = None
        _history_idx["terminal"] = None

    terminal_input = ft.TextField(
        hint_text="> Terminal", bgcolor=DARK, border_color=GREY, color=WHITE,
        text_size=CONSTANTS.TERMINAL_FONT_SIZE, expand=True,
        content_padding=ft.Padding(10, 8, 10, 8),
        on_focus=_terminal_input_on_focus, on_blur=_terminal_input_on_blur)

    # Auto-affichage du terminal (retour user) : tout message y apparaissant
    # (action, copier/coller, outil lancé…) le fait apparaître, puis le
    # referme après quelques secondes de silence — même débounce que
    # _notes_autosave_after_delay (annule/relance un timer à chaque appel),
    # donc reste ouvert tant que des messages continuent d'arriver.
    # "pinned" = terminal ouvert manuellement (bouton Terminal) : reste
    # visible sans limite jusqu'à ce que l'utilisateur le referme lui-même,
    # après quoi l'auto-affichage/masquage reprend normalement.
    _terminal_autohide = {"task": None, "pinned": False}

    async def _terminal_autohide_after_delay():
        await asyncio.sleep(3.5)
        terminal_panel.visible = False
        page.update()

    def _show_terminal_and_schedule_hide():
        terminal_panel.visible = True
        t = _terminal_autohide["task"]
        if t is not None and not t.done():
            t.cancel()
        if not _terminal_autohide["pinned"]:
            _terminal_autohide["task"] = page.run_task(_terminal_autohide_after_delay)

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
            _show_terminal_and_schedule_hide()
            page.update()

        page.run_task(_do)

    def _export_terminal(to_notepad=False, event=None):
        text = "\n".join(c.value for c in terminal_output.controls
                         if isinstance(c, ft.Text) and c.value)
        if not text:
            return

        async def _copy():
            try:
                await ft.Clipboard().set(text)
                _log_to_terminal("[OK] Terminal copié dans le presse-papiers", BLUE)
            except Exception as exc:
                _log_to_terminal(f"[ERREUR] Copie terminal : {exc}", RED)
        page.run_task(_copy)

        if to_notepad:
            current = notes_field.value or ""
            sep = ("\n\n" + "#" * CONSTANTS.AI_SEPARATOR_WIDTH + "\n\n"
                  if current.strip() else "")
            notes_field.value = current + sep + text
            _notes_save()
            if notes_is_preview["value"]:
                notes_preview.value = notes_field.value or ""
            _select_surface("notes")
            page.update()

    def _exec_terminal_command(command_text, sudo_password=None):
        cwd = state["folder"] or _APP_DIR
        _log_to_terminal(f"> {command_text}", YELLOW)
        if sudo_password is not None:
            # "-S" fait lire le mot de passe sur stdin plutôt que sur le
            # tty : seul moyen de le fournir sans l'exposer en argument de
            # commande (visible dans `ps`) ni dans les logs du terminal.
            rest = command_text.split(None, 1)
            command_text = "sudo -S " + (rest[1] if len(rest) > 1 else "")

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
                    stderr=subprocess.STDOUT,
                    stdin=subprocess.PIPE if sudo_password is not None else None,
                    text=True, encoding="utf-8",
                    errors="replace", cwd=cwd)
                if sudo_password is not None:
                    try:
                        proc.stdin.write(sudo_password + "\n")
                        proc.stdin.flush()
                    except Exception:
                        pass
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

    def _prompt_sudo_password(command_text):
        pwd_field = ft.TextField(
            hint_text="Mot de passe administrateur", password=True,
            can_reveal_password=True, autofocus=True, width=280,
            bgcolor=DARK, border_color=BLUE, text_size=CONSTANTS.TEXT_SM,
            height=CONSTANTS.HUB_DIALOG_FIELD_HEIGHT,
            content_padding=ft.Padding(8, 4, 8, 4))

        def _cancel(event):
            dlg.open = False
            page.update()

        def _confirm(event):
            pwd = pwd_field.value or ""
            pwd_field.value = ""
            dlg.open = False
            page.update()
            _exec_terminal_command(command_text, sudo_password=pwd)

        pwd_field.on_submit = _confirm
        dlg = ft.AlertDialog(
            title=ft.Text("Mot de passe requis (sudo)", size=CONSTANTS.TEXT_SM, color=WHITE),
            content=pwd_field,
            actions=[
                ft.TextButton("Exécuter", on_click=_confirm),
                ft.TextButton("Annuler", on_click=_cancel),
            ],
        )
        page.overlay.append(dlg)
        dlg.open = True
        page.update()

    def _update_app(event=None):
        """Sauvegarde les fichiers utilisateur, git pull --rebase, vérifie
        les dépendances si requirements a changé, relance le Hub
        (cf. Dashboard.pyw:9792-10011, même logique de mise à jour)."""
        _log_to_terminal("Mise à jour en cours…", YELLOW)

        def _run_update():
            def run_git_command(*args):
                return subprocess.run(
                    ["git", *args], cwd=_APP_DIR, capture_output=True,
                    text=True, encoding="utf-8", errors="replace")

            user_data_filenames = [
                ".recent_folders.json", ".favorites.json",
                ".pip_cache.json", ".recadrage_auto_config.json",
            ]
            user_data_backups = {}
            for file_name in user_data_filenames:
                file_path = os.path.join(_APP_DIR, file_name)
                if os.path.isfile(file_path):
                    try:
                        with open(file_path, "r", encoding="utf-8") as f:
                            user_data_backups[file_name] = f.read()
                    except Exception:
                        pass

            def _restore_user_data_files():
                for file_name, content in user_data_backups.items():
                    file_path = os.path.join(_APP_DIR, file_name)
                    try:
                        with open(file_path, "w", encoding="utf-8") as f:
                            f.write(content)
                    except Exception:
                        pass

            try:
                stash_result = run_git_command("stash")
                had_local_changes = (
                    "No local changes" not in stash_result.stdout)

                git_pull_result = run_git_command(
                    "pull", "--rebase", "origin")
                git_command_output = (
                    git_pull_result.stdout + git_pull_result.stderr).strip()

                if git_pull_result.returncode != 0:
                    if had_local_changes:
                        run_git_command("rebase", "--abort")
                        run_git_command("stash", "pop")
                    _restore_user_data_files()
                    _log_to_terminal(
                        f"[ERREUR] Erreur lors de la mise à jour.\n"
                        f"{git_command_output}", RED)
                    return

                if had_local_changes:
                    run_git_command("stash", "drop")

                _restore_user_data_files()

                if ("Already up to date" in git_command_output
                        or "Déjà à jour" in git_command_output
                        or git_command_output == ""):
                    _log_to_terminal("[OK] Déjà à jour.", GREEN)
                else:
                    _log_to_terminal(
                        f"[OK] Code mis à jour.\n{git_command_output}",
                        GREEN)

                requirements_file_path = os.path.join(
                    _APP_DIR, "requirements.txt")
                pip_cache_file_path = os.path.join(
                    _APP_DIR, ".pip_cache.json")
                if not os.path.isfile(requirements_file_path):
                    _log_to_terminal(
                        "⚠ requirements.txt introuvable, installation "
                        "ignorée.", YELLOW)
                else:
                    with open(requirements_file_path, "rb") as f:
                        requirements_checksum = hashlib.sha256(
                            f.read()).hexdigest()

                    cached_checksum = None
                    try:
                        with open(pip_cache_file_path, "r",
                                  encoding="utf-8") as f:
                            cached_checksum = json.load(f).get("req_hash")
                    except Exception:
                        pass

                    _log_to_terminal(
                        "🔌 Mise à jour de flet et flet-desktop…", YELLOW)
                    flet_upgrade_proc = subprocess.Popen(
                        [sys.executable, "-m", "pip", "install", "flet",
                         "flet-desktop", "--upgrade"],
                        stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                        text=True, encoding="utf-8", errors="replace",
                        cwd=_APP_DIR)
                    for line in flet_upgrade_proc.stdout:
                        line = line.rstrip()
                        if line:
                            _log_to_terminal(line, LIGHT_GREY)
                    flet_upgrade_proc.wait()
                    if flet_upgrade_proc.returncode == 0:
                        _log_to_terminal(
                            "[OK] flet et flet-desktop mis à jour.", GREEN)
                    else:
                        _log_to_terminal(
                            f"⚠ flet-desktop : pip a terminé avec le code "
                            f"{flet_upgrade_proc.returncode}.", YELLOW)

                    if cached_checksum == requirements_checksum:
                        _log_to_terminal(
                            "[OK] Dépendances inchangées, installation "
                            "ignorée.", GREEN)
                    else:
                        _log_to_terminal(
                            "📦 Nouvelles dépendances détectées, "
                            "installation en cours…", YELLOW)
                        pip_install_process = subprocess.Popen(
                            [sys.executable, "-m", "pip", "install", "-r",
                             requirements_file_path, "--upgrade"],
                            stdout=subprocess.PIPE,
                            stderr=subprocess.STDOUT, text=True,
                            encoding="utf-8", errors="replace",
                            cwd=_APP_DIR)
                        for line in pip_install_process.stdout:
                            line = line.rstrip()
                            if line:
                                _log_to_terminal(line, LIGHT_GREY)
                        pip_install_process.wait()
                        if pip_install_process.returncode == 0:
                            _log_to_terminal(
                                "[OK] Dépendances installées.", GREEN)
                            try:
                                with open(pip_cache_file_path, "w",
                                          encoding="utf-8") as f:
                                    json.dump(
                                        {"req_hash": requirements_checksum,
                                         "updated_at": time.strftime(
                                             "%Y-%m-%d %H:%M")},
                                        f, ensure_ascii=False, indent=2)
                            except Exception:
                                pass
                        else:
                            _log_to_terminal(
                                f"pip a terminé avec le code "
                                f"{pip_install_process.returncode}.",
                                YELLOW)

                _log_to_terminal("🔄 Redémarrage du Hub…", BLUE)
                hub_path = os.path.abspath(__file__)

                async def _restart_after_update():
                    time.sleep(0.4)
                    subprocess.Popen([sys.executable, hub_path])
                    time.sleep(0.2)
                    try:
                        await page.window.close()
                    except Exception:
                        pass
                    os._exit(0)
                page.run_task(_restart_after_update)
            except Exception as error:
                _log_to_terminal(f"[ERREUR] Mise à jour : {error}", RED)

        threading.Thread(target=_run_update, daemon=True).start()

    def _on_terminal_submit(event=None):
        command_text = (terminal_input.value or "").strip()
        if not command_text:
            return

        # ── Commandes internes (slash-commands, cf. Dashboard.pyw:4584) ──
        if command_text.lower() == "/update":
            terminal_input.value = ""
            page.update()
            _update_app()
            return
        if command_text.lower() == "/option":
            terminal_input.value = ""
            page.update()
            _open_path_in_notes(_constants_path)
            return

        _history_add("terminal", command_text)
        terminal_input.value = ""
        page.update()
        if (platform.system() != "Windows"
                and command_text.split(None, 1)[0] == "sudo"):
            _prompt_sudo_password(command_text)
            return
        _exec_terminal_command(command_text)

    terminal_input.on_submit = _on_terminal_submit

    terminal_copy_button = ft.IconButton(
        ft.Icons.COPY_ALL, icon_color=BLUE, icon_size=CONSTANTS.ICON_SM,
        tooltip="Copier le terminal",
        on_click=lambda e: _export_terminal(to_notepad=False))
    terminal_to_notepad_button = ft.IconButton(
        ft.Icons.SEND_TO_MOBILE, icon_color=VIOLET, icon_size=CONSTANTS.ICON_SM,
        tooltip="Transférer le terminal vers le bloc-notes",
        on_click=lambda e: _export_terminal(to_notepad=True))
    terminal_fullscreen_btn = ft.IconButton(
        ft.Icons.FULLSCREEN, icon_color=WHITE, icon_size=CONSTANTS.ICON_SM,
        tooltip="Terminal plein écran (Ctrl/Cmd+Maj+↑)",
        on_click=lambda e: _toggle_terminal_fullscreen())

    def _clear_terminal(event=None):
        terminal_output.controls.clear()
        page.update()

    terminal_clear_button = ft.IconButton(
        ft.Icons.CLEAR_ALL, icon_color=RED, icon_size=CONSTANTS.ICON_SM,
        tooltip="Effacer le terminal", on_click=_clear_terminal)

    # Barre infinie (value=None) affichée pendant une action de fichiers
    # lancée en arrière-plan (copier/coller/dupliquer/zip/dézip/supprimer)
    # — même emplacement et même rôle que app_progress_bar dans
    # Dashboard.pyw (juste sous le terminal, au-dessus de la ligne de
    # saisie).
    action_progress_bar = ft.ProgressBar(value=None, visible=False,
                                         color=GREEN, height=2)

    terminal_panel = ft.Container(
        content=ft.Column([
            ft.Container(content=terminal_output, expand=True, padding=8),
            action_progress_bar,
            ft.Container(
                content=ft.Row([terminal_input, terminal_copy_button,
                                terminal_to_notepad_button,
                                terminal_clear_button,
                                terminal_fullscreen_btn]),
                padding=ft.Padding(8, 0, 8, 8)),
        ], spacing=0, expand=True),
        bgcolor=DARK, height=110, visible=False,
        border=ft.Border(top=ft.BorderSide(2, ORANGE)),
    )
    _terminal_fullscreen = {"active": False}

    def _toggle_terminal_fullscreen():
        # Bascule tout l'écran vers le terminal (cache la Row explorateur)
        # au lieu de juste afficher/masquer le panneau (_toggle_terminal,
        # Ctrl/Cmd+↑ sans Maj) — pratique pour lire une longue sortie sans
        # défiler dans la bande compacte façon snackbar (retour user :
        # ce bouton plein écran rend inutile un panneau compact plus haut).
        if not terminal_panel.visible:
            terminal_panel.visible = True
        _terminal_fullscreen["active"] = not _terminal_fullscreen["active"]
        is_full = _terminal_fullscreen["active"]
        main_row.visible = not is_full
        terminal_panel.expand = is_full
        terminal_panel.height = None if is_full else 110
        terminal_fullscreen_btn.icon = (
            ft.Icons.FULLSCREEN_EXIT if is_full else ft.Icons.FULLSCREEN)
        terminal_fullscreen_btn.tooltip = (
            "Quitter le plein écran (Ctrl/Cmd+Maj+↑)" if is_full
            else "Terminal plein écran (Ctrl/Cmd+Maj+↑)")
        t = _terminal_autohide["task"]
        if is_full and t is not None and not t.done():
            t.cancel()
        page.update()

    # ═════════════════════════════════════════════════════════════════════
    #  Barre d'état — Terminal (centre) + curseur Taille (droite)
    # ═════════════════════════════════════════════════════════════════════
    status_left = ft.Text("", size=CONSTANTS.TEXT_SM, color=WHITE, expand=True)

    def _toggle_terminal(event):
        terminal_panel.visible = not terminal_panel.visible
        _terminal_autohide["pinned"] = terminal_panel.visible
        t = _terminal_autohide["task"]
        if t is not None and not t.done():
            t.cancel()
        if not terminal_panel.visible and _terminal_fullscreen["active"]:
            _terminal_fullscreen["active"] = False
            main_row.visible = True
            terminal_panel.expand = False
            terminal_panel.height = 200
            terminal_fullscreen_btn.icon = ft.Icons.FULLSCREEN
            terminal_fullscreen_btn.tooltip = "Terminal plein écran (Ctrl/Cmd+Maj+↑)"
        page.update()
        page.run_task(_focus_active_surface)

    # Barre plus haute (56 au lieu de 40) + cibles tactiles agrandies pour
    # Terminal/Actions/curseur de taille — accès écran tactile (retour user).
    statusbar = ft.Container(
        content=ft.Row([
            status_left,
            ft.TextButton(
                content=ft.Row([
                    ft.Icon(ft.Icons.TERMINAL, size=CONSTANTS.ICON_SM, color=WHITE),
                    ft.Text("Terminal", size=CONSTANTS.TEXT_SM, color=WHITE),
                ], spacing=6, tight=True),
                height=CONSTANTS.HUB_STATUSBAR_TAP_HEIGHT, on_click=_toggle_terminal,
            ),
            actions_btn,
            ft.Container(
                content=ft.Row([
                    ft.Icon(ft.Icons.PHOTO_SIZE_SELECT_LARGE, size=CONSTANTS.ICON_SM, color=WHITE),
                    ft.Slider(min=90, max=320, value=state["thumb_size"], width=140,
                              active_color=BLUE,
                              on_change=lambda e: _apply_thumb_size(e.control.value)),
                ], spacing=4, tight=True),
                expand=True, alignment=ft.Alignment.CENTER_RIGHT,
            ),
        ], vertical_alignment=ft.CrossAxisAlignment.CENTER),
        height=CONSTANTS.HUB_STATUSBAR_HEIGHT,
        padding=ft.Padding(12, 0, 12, 0), bgcolor=GREY,
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
        elif event.data == "resized" and viewer_overlay in page.overlay:
            # Le viewport de la visionneuse a une taille explicite (cf.
            # _set_drawer_space) : la rafraîchir au resize, sinon elle reste
            # calée sur la taille de fenêtre au moment de l'ouverture.
            _set_drawer_space(viewer_image_wrap.right or 0)
            page.update()

    page.window.on_event = _on_window_event

    def _open_browser(event=None):
        webbrowser.open("https://www.google.com")
        if not _strip_state["active"]:
            _toggle_strip()

    def _open_in_file_explorer(event=None):
        # Comme Dashboard.pyw:4721-4736 (open_in_file_explorer) : ouvre le
        # dossier COURANT, sans dépendre d'une sélection — contrairement à
        # l'ancien bouton "Afficher" (touch_actions_row), qui ne faisait
        # rien tant qu'aucun fichier n'était coché.
        folder = state["folder"]
        if not folder or not os.path.isdir(folder):
            _log_to_terminal("[ERREUR] Aucun dossier sélectionné", RED)
            return
        try:
            system = platform.system()
            if system == "Windows":
                subprocess.Popen(f'explorer "{folder}"')
            elif system == "Darwin":
                subprocess.Popen(["open", folder])
            else:
                subprocess.Popen(["xdg-open", folder])
            _log_to_terminal(f"[OK] Ouverture du dossier : {os.path.basename(folder)}",
                             GREEN)
        except Exception as exc:
            _log_to_terminal(f"[ERREUR] Ouverture de l'explorateur : {exc}", RED)
            return
        if not _strip_state["active"]:
            _toggle_strip()

    def _toggle_strip(event=None):
        # Réduction en bandeau (écran tactile) : ne garde que la barre de
        # titre, comme Dashboard.pyw _toggle_strip — pratique pour garder
        # Hub visible/accessible pendant qu'on utilise l'explorateur, le
        # bluetooth, l'impression ou le navigateur.
        is_mac = platform.system() == "Darwin"
        if not _strip_state["active"]:
            _strip_state["was_maximized"] = bool(page.window.maximized)
            _strip_state["saved_height"] = page.window.height or CONSTANTS.WINDOW_HEIGHT
            _strip_state["active"] = True
            if is_mac and _strip_state["was_maximized"]:
                page.window.maximized = False
            body.visible = False
            page.window.height = STRIP_HEIGHT
            strip_btn.icon = ft.Icons.UNFOLD_MORE
            strip_btn.tooltip = "Restaurer la fenêtre"
            strip_btn.icon_color = BLUE
        else:
            _strip_state["active"] = False
            body.visible = True
            if is_mac and _strip_state["was_maximized"]:
                page.window.maximized = True
            else:
                page.window.height = _strip_state["saved_height"]
            strip_btn.icon = ft.Icons.UNFOLD_LESS
            strip_btn.tooltip = "Réduire en bandeau (écran tactile)"
            strip_btn.icon_color = WHITE
        page.update()

    strip_btn = ft.IconButton(ft.Icons.UNFOLD_LESS, icon_size=CONSTANTS.ICON_SM, icon_color=WHITE,
                              on_click=_toggle_strip,
                              tooltip="Réduire en bandeau (écran tactile)")

    # Container extérieur à hauteur fixe = STRIP_HEIGHT : le mode bandeau
    # (_toggle_strip) réduit la fenêtre à cette hauteur pour ne garder que
    # cette barre, donc les deux doivent rester synchronisées. Cibles
    # tactiles Bluetooth/Impression/Navigateur/Explorateur agrandies
    # (22 -> 30, height= explicite) pour un accès plus facile à l'écran
    # tactile (retour user).
    titlebar = ft.Container(
        height=STRIP_HEIGHT,
        content=ft.WindowDragArea(
            ft.Row([
                ft.Container(
                    content=ft.Row([
                        ft.Icon(ft.Icons.HUB_OUTLINED, color=ORANGE, size=CONSTANTS.ICON_SM),
                        ft.Text(f"HUB  {__version__}", size=CONSTANTS.TEXT_LG,
                                color=WHITE, weight=ft.FontWeight.W_500),
                    ], spacing=6),
                    padding=ft.Padding(12, 0, 0, 0),
                ),
                ft.IconButton(
                    icon=ft.Icons.SYSTEM_UPDATE_ALT,
                    tooltip="Mettre à jour (git pull --rebase)",
                    on_click=_update_app,
                    icon_color=LIGHT_GREY,
                    icon_size=CONSTANTS.ICON_SM,
                ),
                ft.Container(expand=True),
                # Accès tactile : toujours visibles, quelle que soit la surface
                # active (écran tactile = pas de fallback clavier/raccourci).
                ft.Container(
                    content=ft.Row([
                        ft.IconButton(
                            ft.Icons.BLUETOOTH,
                            icon_size=CONSTANTS.ICON_LG,
                            height=CONSTANTS.HUB_TITLEBAR_TAP_HEIGHT,
                            icon_color=BLUE, on_click=_launch_bluetooth,
                            tooltip="Recevoir un fichier via Bluetooth"),
                        ft.IconButton(
                            ft.Icons.PRINT_OUTLINED,
                            icon_size=CONSTANTS.ICON_LG,
                            height=CONSTANTS.HUB_TITLEBAR_TAP_HEIGHT,
                            icon_color=ORANGE, on_click=_launch_print,
                            tooltip="Imprimer la sélection (ou le dossier)"),
                        ft.IconButton(
                            ft.Icons.PUBLIC,
                            icon_size=CONSTANTS.ICON_LG,
                            height=CONSTANTS.HUB_TITLEBAR_TAP_HEIGHT,
                            icon_color=BLUE, on_click=_open_browser,
                            tooltip="Ouvrir le navigateur web"),
                        ft.IconButton(
                            ft.Icons.OPEN_IN_NEW,
                            icon_size=CONSTANTS.ICON_LG,
                            height=CONSTANTS.HUB_TITLEBAR_TAP_HEIGHT,
                            icon_color=GREEN, on_click=_open_in_file_explorer,
                            tooltip="Ouvrir l'explorateur"),
                    ], spacing=0, tight=True),
                    border=ft.Border.all(1, ORANGE), border_radius=8,
                    margin=ft.Margin(0, 0, 8, 0),
                ),
                strip_btn,
                ft.Row([
                    ft.IconButton(ft.Icons.REMOVE, icon_size=CONSTANTS.ICON_SM, icon_color=YELLOW,
                                  on_click=_minimize, tooltip="Réduire"),
                    ft.IconButton(ft.Icons.FULLSCREEN, icon_size=CONSTANTS.ICON_SM, icon_color=BLUE,
                                  on_click=_toggle_maximize,
                                  tooltip="Maximiser / Restaurer"),
                    ft.IconButton(ft.Icons.CLOSE, icon_size=CONSTANTS.ICON_SM, icon_color=RED,
                                  on_click=_close, tooltip="Fermer"),
                ], spacing=0),
            ], vertical_alignment=ft.CrossAxisAlignment.CENTER),
        ),
    )

    main_row = ft.Row([left_rail, center], expand=True, spacing=0)
    body = ft.Column([
        ft.Divider(height=1, color=GREY),
        main_row,
        terminal_panel,
        statusbar,
    ], expand=True, spacing=0)

    # ═════════════════════════════════════════════════════════════════════
    #  Raccourcis clavier globaux — mêmes gestes que Dashboard.pyw
    #  (Ctrl+A/C/X/V/I/N/R, Suppr, Ctrl+↑ terminal). Actifs seulement sur la
    #  surface Fichiers, hors saisie texte (recherche/terminal) et dialogue
    #  ouvert ; la visionneuse installe son propre handler par-dessus
    #  celui-ci (_prev_keyboard) et le restaure à la fermeture.
    # ═════════════════════════════════════════════════════════════════════
    def _dialog_open():
        return any(getattr(o, "open", False) for o in page.overlay)

    def _on_global_key(event):
        ctrl = event.ctrl or event.meta
        if ctrl and event.shift and event.key in ("Arrow Up", "ArrowUp"):
            _toggle_terminal_fullscreen()
            return
        if ctrl and event.key in ("Arrow Up", "ArrowUp"):
            _toggle_terminal(None)
            return
        if not ctrl and event.key in ("Arrow Up", "ArrowUp", "Arrow Down", "ArrowDown"):
            focused = _focused_input["name"]
            # Un champ non vide peut être une réponse multi-lignes en cours
            # de correction : les flèches doivent alors juste déplacer le
            # curseur, jamais écraser le texte par l'historique (retour
            # user, par sécurité). Exception : si on est déjà en train de
            # naviguer l'historique (idx non None), le champ contient un
            # message rappelé et pas un brouillon — les flèches doivent
            # continuer à faire défiler, sinon on resterait bloqué au
            # premier message rappelé.
            if (focused == "terminal"
                    and (not (terminal_input.value or "").strip()
                         or _history_idx["terminal"] is not None)):
                _history_navigate("terminal", event.key, terminal_input)
                return
            if (focused == "ai"
                    and (not (ai_input_field.value or "").strip()
                         or _history_idx["ai"] is not None)):
                _history_navigate("ai", event.key, ai_input_field)
                return
        if _kb_suspend["count"] > 0 or _dialog_open() or state["surface"] != "files":
            return
        key = (event.key or "").upper()
        if ctrl:
            if key == "A":
                _toggle_all(None)
            elif key == "C" and selected:
                _do_copy(list(selected))
            elif key == "X" and selected:
                _do_cut(list(selected))
            elif key == "V":
                _do_paste()
            elif key == "I":
                _invert(None)
            elif key == "D":
                _select_same_date(None)
            elif key == "N":
                _create_folder_here()
            elif key == "R":
                _refresh_folder()
        elif event.key == "Delete" and selected:
            _do_delete(list(selected))

    page.on_keyboard_event = _on_global_key

    page.add(ft.Column([
        titlebar,
        body,
    ], expand=True, spacing=0))
    page.run_task(_focus_active_surface)
    _mic_hotkey_start()

    if CONSTANTS.MAXIMIZED:
        async def _delayed_maximize():
            # Même délai que Dashboard.pyw:10874-10883 : `maximized=True`
            # fixé trop tôt (avant que la fenêtre soit réellement affichée)
            # ne prend pas toujours effet.
            await asyncio.sleep(0.15)
            if platform.system() == "Darwin":
                page.window.maximized = False
                page.update()
                await asyncio.sleep(0.05)
            page.window.maximized = True
            page.update()

        page.run_task(_delayed_maximize)


def _install_crash_logger():
    # Le terminal se ferme souvent avant que Charles ait pu copier une
    # trace en cas de plantage (crash de l'event loop Flet, thread IA...) —
    # on la persiste donc dans un fichier pour pouvoir la relire après coup.
    import traceback as _tb
    log_path = os.path.join(_APP_DIR, "Data", ".hub_crash.log")

    def _log_exc(exc_type, exc_value, exc_tb):
        with open(log_path, "a", encoding="utf-8") as f:
            f.write(f"\n{'=' * 70}\n{datetime.datetime.now().isoformat()}\n")
            f.writelines(_tb.format_exception(exc_type, exc_value, exc_tb))
        sys.__excepthook__(exc_type, exc_value, exc_tb)

    sys.excepthook = _log_exc

    def _log_thread_exc(args):
        _log_exc(args.exc_type, args.exc_value, args.exc_traceback)

    threading.excepthook = _log_thread_exc


if __name__ == "__main__":
    _install_crash_logger()
    ft.run(main)
