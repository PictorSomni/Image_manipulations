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
import re
import time
import platform
import subprocess
import sys
import shutil
import tempfile
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
import ui_helpers
import image_ops
import ai_ops
import thumb_cache
import mcp_client
import credentials
import mtp_devices
import rss_feeds
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
    _gemini_tts, _gemini_tts_stream, _gemini_live_tts_stream, _voice_play_audio,
)


# ── Surfaces déclarées une fois : clé, libellé, icône ────────────────────
SURFACES = [
    ("files", "Fichiers", ft.Icons.PHOTO_LIBRARY_OUTLINED),
    ("liste", "Liste",    ft.Icons.LIST_ALT_OUTLINED),
    ("ia",    "IA",       ft.Icons.SMART_TOY_OUTLINED),
    ("notes", "Notes",    ft.Icons.EDIT_NOTE_OUTLINED),
    ("actus", "Actus",    ft.Icons.RSS_FEED_OUTLINED),
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
_OPEN_TABS_FILE = os.path.join(_APP_DIR, ".open_tabs.json")


# Persistance JSON partagée avec ai_tools.py (historique de conversation) :
# lecture tolérante, écriture atomique, échec rapporté au terminal intégré
# via le hook branché dans main(). Cf. CONSTANTS §13bis.
_load_json = CONSTANTS.load_json
_save_json = CONSTANTS.save_json
_save_error_hook = CONSTANTS.save_error_hook


def _load_recent():
    # Pas de filtrage os.path.isdir() ici : cette fonction est appelée
    # depuis _add_recent() à CHAQUE navigation (donc sur le thread
    # principal, en synchrone) — vérifier l'existence de chaque dossier
    # récent y bloquait toute navigation, et l'ouverture du menu "Ouvrir",
    # plusieurs secondes dès qu'un des anciens dossiers pointe vers un
    # partage réseau/NAS temporairement injoignable (retour user). Le
    # nettoyage des entrées mortes se fait en arrière-plan côté menu
    # (_build_open_menu), pas ici.
    return [p for p in _load_json(_RECENT_FILE, []) if isinstance(p, str)]


def _save_recent(folders):
    return _save_json(_RECENT_FILE, folders[:10])


def _add_recent(path):
    recents = _load_recent()
    path = os.path.normpath(path)
    if path in recents:
        recents.remove(path)
    recents.insert(0, path)
    _save_recent(recents)


def _load_open_tabs():
    # Onglets multi-dossiers (retour user : les dossiers laissés ouverts
    # volontairement — en cours de travail — ne doivent pas se perdre à
    # chaque redémarrage/mise à jour de l'app). Tolérant comme les autres
    # lecteurs JSON de ce fichier : une entrée invalide ne casse pas le
    # chargement des autres.
    data = _load_json(_OPEN_TABS_FILE, {})
    if not isinstance(data, dict):
        return [], 0
    folders = [p for p in data.get("folders", []) if isinstance(p, str)]
    active = data.get("active", 0)
    return folders, active if isinstance(active, int) else 0


def _save_open_tabs(folders, active):
    return _save_json(_OPEN_TABS_FILE, {"folders": folders, "active": active})


def _load_favorites():
    result = []
    for item in _load_json(_FAVORITES_FILE, []):
        if isinstance(item, str):
            result.append({"path": item, "label": ""})
        elif isinstance(item, dict) and "path" in item:
            result.append({"path": item["path"],
                           "label": item.get("label", "")})
    return result


def _save_favorites(favorites):
    return _save_json(_FAVORITES_FILE, favorites)


# Même fichier que Dashboard.pyw:280 (open_with_config_file_path) : la
# liste de programmes "Ouvrir avec" est partagée entre les deux apps.
_OPEN_WITH_FILE = os.path.join(_APP_DIR, "open_with.json")


def _load_open_with_programs():
    return [p for p in _load_json(_OPEN_WITH_FILE, [])
            if isinstance(p, dict) and "label" in p and "exe" in p]


def _save_open_with_programs(programs):
    return _save_json(_OPEN_WITH_FILE, programs)


_ORDER_FILE = os.path.join(_APP_DIR, ".order.json")


def _load_order():
    # photo (chemin absolu) -> {format: nombre} — plusieurs formats possibles
    # par photo (un client veut parfois la même image en plusieurs tailles).
    try:
        return {p: {fmt: int(n) for fmt, n in v.items() if int(n) > 0}
                for p, v in _load_json(_ORDER_FILE, {}).items()
                if isinstance(v, dict)}
    except Exception:
        return {}


def _save_order(order):
    return _save_json(_ORDER_FILE, order)


# Même fichier que Dashboard.pyw:310 (recadrage_auto_config_path) : le
# dernier format utilisé pour "Recadrage automatique" est partagé.
_CROP_AUTO_FILE = os.path.join(_APP_DIR, ".recadrage_auto_config.json")


def _load_crop_auto_config():
    return _load_json(_CROP_AUTO_FILE, {})


def _save_crop_auto_config(config):
    return _save_json(_CROP_AUTO_FILE, config)


_ORDER_BW_FILE = os.path.join(_APP_DIR, ".order_bw.json")


def _load_order_bw():
    # photo (chemin absolu) -> True si la commande doit être tirée en N&B.
    # Fichier séparé de .order.json : {format: nombre} n'a pas de place
    # naturelle pour un booléen sans fausser _order_lines/_order_totals.
    try:
        return {p: bool(v)
                for p, v in _load_json(_ORDER_BW_FILE, {}).items() if v}
    except Exception:
        return {}


def _save_order_bw(order_bw):
    return _save_json(_ORDER_BW_FILE, order_bw)


def _lower_thread_priority():
    """Priorité basse pour un thread de fond (génération de miniatures) :
    la machine doit d'abord servir Hub (et le reste du système), les
    miniatures se remplissent avec le temps CPU restant — un dossier de
    plusieurs milliers de SVG (ex. un set d'émojis) ralentissait TOUTE la
    machine, pas seulement Hub (retour user). Best-effort : silencieux si
    l'API n'est pas dispo (permissions, plateforme non gérée...).
    """
    try:
        system = platform.system()
        if system == "Windows":
            import ctypes
            kernel32 = ctypes.windll.kernel32
            # GetCurrentThread() renvoie un HANDLE (64 bits sur Windows
            # x64) : sans ces restype/argtypes, ctypes le tronque en int
            # 32 bits et SetThreadPriority échoue silencieusement avec un
            # handle invalide.
            kernel32.GetCurrentThread.restype = ctypes.c_void_p
            kernel32.SetThreadPriority.argtypes = [ctypes.c_void_p, ctypes.c_int]
            THREAD_PRIORITY_LOWEST = -2
            handle = kernel32.GetCurrentThread()
            kernel32.SetThreadPriority(handle, THREAD_PRIORITY_LOWEST)
        elif system == "Darwin":
            # nice() est par PROCESSUS sur macOS (contrairement à Linux) —
            # l'appeler ici baisserait Hub entier, pas juste ce thread. La
            # QoS class est, elle, bien par thread (API Grand Central
            # Dispatch) : c'est l'équivalent correct côté macOS.
            import ctypes
            libc = ctypes.CDLL("/usr/lib/libSystem.dylib")
            QOS_CLASS_BACKGROUND = 0x09
            libc.pthread_set_qos_class_self_np(QOS_CLASS_BACKGROUND, 0)
        else:
            # Linux : chaque thread noyau a sa propre valeur nice, l'appel
            # n'affecte donc que le thread appelant.
            os.nice(10)
    except Exception:
        pass


def main(page: ft.Page):
    CONSTANTS.attach_error_copy_snackbar(page)
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
    _DEFAULT_THUMB_SIZE = 159    # 30% du curseur (min=90, max=320)
    _DEFAULT_FONT_SIZE = CONSTANTS.TERMINAL_FONT_SIZE
    state = {"surface": "files", "folder": None, "view": "grid",
             "thumb_size": _DEFAULT_THUMB_SIZE, "thumb_token": 0,
             "font_size": _DEFAULT_FONT_SIZE,   # taille de texte IA/Bloc-notes
             "sort": "date", "search": "", "only_selected": False,
             "last_selected": None, "thumb_fit": "contain",
             # Tarif partagé avec Recadrage manuel.pyw et kiosk_flet.pyw
             # (propagé via TARIFF_TYPE au lancement) : un seul switch ici
             # au lieu d'un réglage dupliqué dans chaque outil.
             "tariff_mode": "PRINTS"}
    _strip_state = {"active": False, "saved_height": CONSTANTS.WINDOW_HEIGHT,
                    "was_maximized": False}
    content = {"dirs": [], "imgs": [], "other": [],
               "mtime": {}}   # non filtrés ; mtime rempli par _navigate

    async def _focus_dialog_field(field):
        # autofocus=True sur un TextField de dialogue ne marche pas de
        # façon fiable (le contrôle n'est pas encore monté côté client
        # quand page.update() rend la main) — même cause que le focus des
        # surfaces (_focus_active_surface plus bas), même remède. Délai
        # plus long que celui de _focus_active_surface (0.08s) : ouvrir un
        # dialogue depuis le panneau Actions passe par _close_actions(),
        # qui programme déjà un focus vers la barre de recherche — le
        # dialogue doit gagner cette course, pas la perdre (retour user).
        try:
            await asyncio.sleep(0.15)
            await field.focus()
        except Exception:
            pass
    # Liste (pas un set) — ordre de clic préservé, comme Dashboard.pyw
    # (selected_files) : "Renommer séquence" numérote dans cet ordre-là
    # quand une sélection est fournie (retour user).
    selected = []                        # chemins sélectionnés (images + dossiers)
    clipboard = {"paths": [], "mode": None}   # mode: "copy" | "cut" | None
    drives_state = {"list": []}          # [(nom, chemin), ...] — cache tenu à jour par _poll_removable_drives
    phones_state = {"list": []}          # [(description, id PnP), ...] — téléphones MTP, même sondage

    # ─── Onglets multi-dossiers ─────────────────────────────────────────
    # state/content/selected restent les MÊMES objets pendant toute la vie
    # de l'app (jamais réassignés, cf. commentaires ci-dessus) — les ~130
    # endroits qui les lisent/écrivent continuent donc de fonctionner sans
    # modification. Un onglet ne stocke QUE {"id", "folder", "selected"} :
    # jamais de copie de `content` (péremption si des fichiers changent
    # pendant qu'on est sur un autre onglet) — changer d'onglet rappelle
    # simplement _navigate(), qui rescane à chaque fois (déjà le
    # comportement actuel, bon marché).
    tabs = []                            # [{"id", "folder", "selected"}, ...]
    _next_tab_id = {"n": 0}
    state["tab_id"] = None               # identifiant stable, changé
                                          # UNIQUEMENT par la bascule
                                          # d'onglet, jamais par _navigate()
                                          # — cf. _tool_refresh(origin_tab_id)
                                          # plus bas, qui s'en sert pour
                                          # ignorer un rafraîchissement
                                          # différé si l'utilisateur a
                                          # changé d'onglet entre-temps.
    _next_tab_id["n"] += 1
    tabs.append({"id": _next_tab_id["n"], "folder": None, "selected": []})
    state["tab_id"] = _next_tab_id["n"]
    # Lu ICI, avant toute écriture : _render_folder_tabs() (plus bas dans
    # main()) sauvegarde l'état des onglets à chaque appel, y compris lors
    # de la construction initiale de l'UI — un _load_open_tabs() différé
    # jusqu'à _initial_navigate lirait donc le fichier déjà écrasé par le
    # seul onglet vide du tout début, avant d'avoir pu restaurer quoi que
    # ce soit (retour user : les onglets ouverts avant fermeture doivent
    # survivre à un redémarrage).
    _startup_tabs, _startup_tabs_active = _load_open_tabs()

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

    # Repère quel champ de recherche a le focus (cf. _focused_input plus
    # bas, même principe) pour qu'Échap puisse l'atteindre malgré
    # _kb_suspend — un champ recherche suspend les raccourcis globaux tant
    # qu'il a le focus, Échap doit donc être vérifié AVANT ce garde-fou
    # dans _on_global_key plutôt que d'ajouter un handler par champ (Flet
    # 0.85 n'expose pas d'event clavier par contrôle, cf. plus bas).
    def _focus_search(name):
        def _handler(event=None):
            _suspend_kb(event)
            _focused_input["name"] = name
        return _handler

    def _blur_search(event=None):
        _resume_kb(event)
        _focused_input["name"] = None

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
    ai_text_refs = []                    # Text/Markdown des bulles IA, pour
                                          # un resize live du curseur police
    grid_card_refs = {}                  # path -> Container carte vignette,
                                          # pour recolorer la bordure de
                                          # sélection sans reconstruire toute
                                          # la grille (cf. _set_selected)
    sel_checkbox_refs = {}                # path -> Checkbox de sélection
                                          # (liste ou vignette), pour décocher
                                          # sans reconstruire toute la vue
                                          # (cf. _clear_selection_visuals)
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
        # en cours s'il y en a une (retour user). Comme "Tout sélectionner"
        # (_toggle_all) : ne compte que les fichiers, pas les sous-dossiers
        # (retour user).
        _dirs, imgs, other = _visible_entries()
        total = len(imgs) + len(other)
        n = len(selected)
        total_txt = f"{total} fichier{'s' if total > 1 else ''}"
        if n:
            status_left.value = (
                f"{total_txt}, {n} sélectionné{'s' if n > 1 else ''}")
        else:
            status_left.value = total_txt if total else ""
        _refresh_edit_buttons()

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
        # La case cochée dans la visionneuse plein écran est un Checkbox
        # distinct de celui de la vignette (viewer_checkbox vs
        # sel_checkbox_refs) : sans cette synchro, la sélection faite en
        # plein écran ne se voyait pas au retour en mode vignettes (retour
        # user).
        cb = sel_checkbox_refs.get(path)
        if cb is not None and cb.value != on:
            cb.value = on
            cb.update()

    def _clear_selection_visuals():
        # Utilisé à la fermeture du panneau Actions : décoche/décolore
        # juste les éléments actuellement sélectionnés (case + bordure,
        # via les refs déjà maintenues par _set_selected/_render) au lieu
        # d'un _render() complet — sur un gros dossier, reconstruire
        # toutes les vignettes ne servait qu'à effacer une sélection,
        # plusieurs secondes de latence perceptible à chaque fermeture
        # du panneau (retour user).
        touched = []
        for path in selected:
            cb = sel_checkbox_refs.get(path)
            if cb is not None:
                cb.value = False
                touched.append(cb)
            card = grid_card_refs.get(path)
            if card is not None:
                card.border = ft.Border.all(1, GREY)
                touched.append(card)
        selected.clear()
        _update_sel_count()
        status_left.update()
        if touched:
            page.update(*touched)

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
        sel_checkbox_refs[path] = checkbox
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
            fit = (ft.BoxFit.CONTAIN if state["thumb_fit"] == "contain"
                   else ft.BoxFit.COVER)
            visual = ft.Image(src=thumb, width=size, height=size, fit=fit,
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
            sel_checkbox_refs[path] = leading
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
        sel_checkbox_refs[path] = checkbox
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
            # Topaz Photo AI/Gigapixel et Luminar Neo basculent en mode
            # plugin restreint (export forcé) quand un fichier leur est
            # passé au lancement — comportement connu et accepté (retour
            # user : il a toujours une copie d'origine intacte via
            # Augmentation IA/Recadrage manuel, donc mieux vaut que la
            # photo s'ouvre à chaque fois plutôt que devoir la rouvrir à
            # la main en pleine journée de boutique).
            if platform.system() == "Darwin":
                cmd = ["open", "-a", resolved] + files
            else:
                cmd = [resolved] + files
            subprocess.Popen(cmd)
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
        sel_checkbox_refs[path] = checkbox
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
        sel_checkbox_refs[path] = checkbox
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
        fit_contain = state["thumb_fit"] == "contain"
        if thumb:
            img = ft.Image(src=thumb,
                           fit=ft.BoxFit.CONTAIN if fit_contain else ft.BoxFit.COVER,
                           expand=True, border_radius=ft.BorderRadius.all(6))
        else:
            img = ft.Container(bgcolor=GREY, expand=True,
                               border_radius=ft.BorderRadius.all(6))
            pending[path] = img
        # Zone image cliquable = ouvre la visionneuse ; case à cocher séparée
        # (widget dédié, comme leading=Checkbox dans un ListTile) = sélection.
        # bgcolor posé seulement en mode "entier" : comble les bandes vides
        # laissées par BoxFit.CONTAIN quand l'image ne remplit pas le carré
        # (retour user : montrer la miniature entière plutôt que recadrée).
        img_zone = ft.Container(content=img, expand=True, border_radius=6,
                                bgcolor=GREY if fit_contain else None,
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
            sel_checkbox_refs[path] = checkbox
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
            # mtime lus dans le cache rempli au scan (_navigate, via
            # entry.stat() de os.scandir — gratuit sous Windows) : le tri
            # "Date" (défaut) refaisait un os.path.getmtime PAR FICHIER à
            # CHAQUE rendu — un stat réseau par fichier et par frappe de
            # recherche sur un dossier NAS (retour user : Hub poussif sur
            # le Diskstation).
            mtime = content["mtime"].get(path)
            if mtime is None:
                try:
                    mtime = os.path.getmtime(path)
                except OSError:
                    mtime = 0.0
                content["mtime"][path] = mtime
            return -mtime
        return os.path.basename(path).lower()

    def _merge_files_sorted(imgs, other):
        # Images + autres fichiers triés ENSEMBLE (pas juste chaque groupe
        # séparément) : "Tout sélectionner" doit suivre le même ordre que
        # l'affichage, sinon une sélection mixte images/autres décale
        # l'ordre par rapport à l'ordre visuel (retour user : numérotation
        # "Renommer séquence" fausse quand des fichiers "autres" sont mêlés
        # aux images).
        return sorted(imgs + other, key=_sort_key,
                      reverse=(state["sort"] == "name_desc"))

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
        # sélection courante si elle existe. Ne sélectionne plus tout le
        # dossier automatiquement (retour user : pas pratique à l'usage,
        # utiliser le bouton "Tout sélectionner" à la place).
        if not selected:
            return
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
        sel_checkbox_refs.clear()
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
            files = _merge_files_sorted(imgs, other)
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
        # Le total affiché dans le statut suit le filtre visible (recherche,
        # "afficher la sélection"…) : sans ce recalcul ici, vider la
        # recherche après un Ctrl+A laisse le statut figé sur l'ancien
        # total filtré (retour user).
        _update_sel_count()
        page.update()

    def _start_thumb_loader(pending):
        """Génère les miniatures manquantes en arrière-plan (token = annulation)."""
        if not pending:
            return
        state["thumb_token"] += 1
        token = state["thumb_token"]
        snapshot = list(pending.items())

        def _load():
            _lower_thread_priority()
            # Un page.update() par miniature chargée noyait la boucle
            # d'événements sous des rafales de mises à jour sur les gros
            # dossiers (des centaines d'images) — l'app entière (clics,
            # scroll, menus...) devenait perceptiblement lente pendant le
            # chargement, pas seulement la sélection (retour user). Un seul
            # update() groupé toutes les ~100 ms suffit à faire apparaître
            # les miniatures au fil de l'eau sans jamais saturer le thread
            # principal, quel que soit le nombre de fichiers.
            #
            # page.update() SANS argument rediffuse toute la page (tout
            # l'arbre de contrôles, pas seulement les vignettes changées) —
            # sur un très gros dossier, ce diff complet répété ~10x/s
            # pendant toute la génération suffisait à saturer la boucle
            # d'événements : un clic (ex. entrer dans un sous-dossier)
            # pouvait rester en attente plusieurs minutes derrière la
            # rafale d'update() (retour user). page.update(*holders) ne
            # patche que les vignettes de ce batch, coût proportionnel au
            # batch et non à la taille du dossier.
            #
            # 2 workers en parallèle : Wand/PyMuPDF (SVG/PDF, de loin les
            # plus lents à générer) libèrent le GIL pendant le rendu, donc
            # ça accélère vraiment un dossier de centaines de vectoriels
            # sans saturer le CPU ni concurrencer le thread principal.
            # shutdown(wait=False, cancel_futures=True) : changer de
            # dossier abandonne aussitôt les tâches pas encore lancées au
            # lieu d'attendre que les 300 rendus se terminent (retour
            # user — jamais bloquer sur un dossier abandonné).
            # initializer=_lower_thread_priority : sur un dossier de
            # plusieurs milliers de SVG (ex. un set d'émojis), la
            # génération pouvait saturer le CPU de toute la machine, pas
            # seulement ralentir Hub — priorité basse pour que l'OS serve
            # Hub (et le reste du système) en premier (retour user).
            def _gen_thumb(path):
                # Compensation écran appliquée à la volée (jamais dans la
                # DB partagée .thumbcache.db : elle dépend du moniteur de
                # CETTE machine, le cache doit rester portable — Kiosk,
                # NAS...). Quelques ms par vignette, dans le pool basse
                # priorité.
                data = thumb_cache.get_or_generate(path)
                if data is None:
                    return None
                return image_ops.compensate_jpeg_bytes(
                    data, quality=CONSTANTS.THUMB_CACHE_QUALITY)

            pool = concurrent.futures.ThreadPoolExecutor(
                max_workers=2, initializer=_lower_thread_priority)
            futures = {pool.submit(_gen_thumb, path): (path, holder)
                      for path, holder in snapshot}
            last_update = 0.0
            done = 0
            total = len(futures)
            batch = []
            try:
                for future in concurrent.futures.as_completed(futures):
                    if state["thumb_token"] != token:
                        return
                    path, holder = futures[future]
                    done += 1
                    data = future.result()
                    if data:
                        thumb_mem[path] = data
                        # Fit lu en direct (pas figé au lancement du chargement)
                        # : sinon les vignettes remplies pendant que le dossier
                        # charge ignorent le switch "Miniatures entières" tant
                        # qu'on n'a pas rebasculé le switch pour forcer un
                        # _render() (retour user).
                        fit = (ft.BoxFit.CONTAIN if state["thumb_fit"] == "contain"
                               else ft.BoxFit.COVER)
                        holder.content = ft.Image(
                            src=data, width=holder.width, height=holder.height,
                            fit=fit, border_radius=ft.BorderRadius.all(6))
                        if fit == ft.BoxFit.COVER:
                            holder.bgcolor = None
                        batch.append(holder)
                        now = time.monotonic()
                        if now - last_update >= 0.1 or done == total:
                            last_update = now
                            page.run_task(_safe_update, batch, token)
                            batch = []
            finally:
                pool.shutdown(wait=False, cancel_futures=True)

        threading.Thread(target=_load, daemon=True).start()

    async def _safe_update(controls, token):
        # page.run_task ne fait que PLANIFIER l'appel : un changement de
        # dossier ou un switch liste/vignettes entre-temps a déjà vidé et
        # reconstruit files_list/files_grid (_render), rendant `controls`
        # obsolètes (détachés de l'arbre courant). Sans ce re-check du
        # token, page.update() sur ces contrôles fantômes provoquait côté
        # client un crash Flutter aléatoire ("RangeError (length): Invalid
        # value: Valid value range is empty: 0"), invisible côté Python
        # (retour user).
        if state["thumb_token"] != token:
            return
        try:
            if controls:
                page.update(*controls)
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
        _log_to_terminal(f"[...] {label}…", ORANGE, clear=True)
        action_progress_bar.visible = True
        page.update()

        def _run():
            # Épinglé (_busy_start/_busy_end) plutôt qu'un _toggle_strip :
            # une opération comme "coller un gros dossier" ne loggue qu'une
            # fois avant un shutil.copytree bloquant de plusieurs minutes —
            # sans épinglage, le terminal s'auto-masquait avant la fin
            # réelle (retour user). _toggle_strip réduit toute la fenêtre
            # (et masque le terminal avec, puisqu'il fait partie de `body`)
            # : jamais le bon outil pour garder le terminal visible.
            _busy_start()
            try:
                work()
            finally:
                action_progress_bar.visible = False
                _busy_end()
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
        _refresh_edit_buttons()
        page.update()
        _log_to_terminal(f"[OK] {len(clipboard['paths'])} élément(s) copié(s)", BLUE,
                        clear=True)

    def _do_cut(paths):
        clipboard["paths"] = list(paths)
        clipboard["mode"] = "cut"
        _refresh_edit_buttons()
        page.update()
        _log_to_terminal(
            f"[OK] {len(clipboard['paths'])} élément(s) coupé(s) — Ctrl+V pour coller",
            ORANGE, clear=True)

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
        origin_tab_id = state["tab_id"]
        # Instantané avant de démarrer le thread : `clipboard` peut changer
        # entre-temps (un nouveau copier/couper pendant que celui-ci tourne
        # encore) — sans ça, la boucle lirait un état déjà remplacé.
        src_paths = list(clipboard["paths"])
        is_cut = clipboard["mode"] == "cut"
        action = "déplacé" if is_cut else "collé"
        if is_cut:
            clipboard["paths"] = []
            clipboard["mode"] = None
            _refresh_edit_buttons()

        def _ask_conflict(name):
            # Dialogue bloquant sur le thread de fond, ouvert sur le thread
            # UI — même pattern threading.Event() que
            # _ai_tool_organize_files/_ai_tool_run_terminal_command
            # (retour user : demander garder-les-deux/remplacer au lieu de
            # renommer silencieusement en cas de conflit de nom).
            choice_event = threading.Event()
            choice = {"value": "skip", "apply_all": False}
            apply_all_cb = ft.Checkbox(
                label="Appliquer à tous les conflits suivants", value=False)

            def _pick(value):
                def _handler(e=None):
                    choice["value"] = value
                    choice["apply_all"] = apply_all_cb.value
                    dlg.open = False
                    page.update()
                    choice_event.set()
                return _handler

            dlg = ft.AlertDialog(
                modal=True,
                title=ft.Text("Élément déjà présent", size=CONSTANTS.TEXT_SM,
                              color=WHITE),
                content=ft.Column([
                    ft.Text(f'"{name}" existe déjà dans ce dossier.',
                           size=CONSTANTS.TEXT_SM, color=WHITE),
                    apply_all_cb,
                ], tight=True, width=420),
                actions=[
                    ft.TextButton("Ignorer", on_click=_pick("skip")),
                    ft.TextButton("Garder les deux", on_click=_pick("both")),
                    ft.Button("Remplacer", bgcolor=BLUE, color=WHITE,
                             on_click=_pick("replace")),
                ],
                actions_alignment=ft.MainAxisAlignment.END,
            )

            async def _open_dlg():
                page.overlay.append(dlg)
                dlg.open = True
                page.update()
            page.run_task(_open_dlg)
            choice_event.wait(timeout=300)
            return choice["value"], choice["apply_all"]

        def _work():
            pasted, skipped, errors = 0, 0, 0
            total = len(src_paths)
            forced_choice = None
            for i, src in enumerate(src_paths, 1):
                if not os.path.exists(src):
                    continue
                name = os.path.basename(src)
                _log_to_terminal(f"[...] Copie {i}/{total} : {name}", ORANGE)
                dest = os.path.join(folder, name)
                if os.path.exists(dest):
                    resolved = forced_choice
                    if resolved is None:
                        resolved, apply_all = _ask_conflict(name)
                        if apply_all:
                            forced_choice = resolved
                    if resolved == "skip":
                        skipped += 1
                        _log_to_terminal(f"[IGNORÉ] {name}", LIGHT_GREY)
                        continue
                    if resolved == "both":
                        dest = _unique_dest(folder, name)
                    elif resolved == "replace":
                        try:
                            _backup_file(dest)
                            if os.path.isdir(dest):
                                shutil.rmtree(dest)
                            else:
                                os.remove(dest)
                        except Exception as exc:
                            errors += 1
                            _log_to_terminal(f"[ERREUR] {name} : {exc}", RED)
                            continue
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
                    _log_to_terminal(f"[ERREUR] {name} : {exc}", RED)
            if pasted:
                _log_to_terminal(f"[OK] {pasted} élément(s) {action}(s)", BLUE)
            if skipped:
                _log_to_terminal(
                    f"[INFO] {skipped} élément(s) ignoré(s)", LIGHT_GREY)
            if errors:
                _log_to_terminal(f"[ATTENTION] {errors} erreur(s)", ORANGE)
            page.run_task(_tool_refresh, folder, None, origin_tab_id)

        _run_bg_action(f"Collage de {len(src_paths)} élément(s)", _work)

    # ═════════════════════════════════════════════════════════════════════
    #  Import depuis un téléphone (MTP, Windows uniquement) — cf.
    #  Data/mtp_devices.py. Copie directement dans le dossier Hub courant,
    #  pas besoin de passer par l'explorateur Windows (retour user :
    #  allers-retours tactiles pénibles entre Explorateur et Hub).
    # ═════════════════════════════════════════════════════════════════════
    #  RÈGLE : aucun appel MTP depuis le thread UI. COM s'initialise par
    #  thread et un pointeur d'interface n'est partageable qu'entre threads
    #  du même apartment ; mtp_devices met les threads de travail en MTA,
    #  mais le thread principal est en STA (comtypes l'initialise ainsi à
    #  l'import). Tout passer par des threads de travail garde donc tous
    #  les objets COM dans le même apartment. Le thread UI ne manipule que
    #  des chaînes : l'ID PnP et la description de l'appareil.
    def _format_size(n):
        if not n:
            return ""
        for unit in ("o", "Ko", "Mo", "Go"):
            if n < 1024 or unit == "Go":
                return f"{n:.0f} {unit}" if unit == "o" else f"{n:.1f} {unit}"
            n /= 1024

    def _open_mtp_import_dialog(pnp_id, description):
        # Navigation dossier par dossier plutôt qu'une liste à plat de tout
        # le téléphone : le premier essai listait 2385 photos d'un coup,
        # inexploitable au poste tactile (retour user 2026-08-07).
        status_text = ft.Text("Ouverture…", size=CONSTANTS.TEXT_SM,
                              color=WHITE)
        crumb_text = ft.Text("", size=CONSTANTS.TEXT_SM, color=LIGHT_GREY,
                             no_wrap=True, expand=True)
        up_btn = ft.IconButton(
            ft.Icons.ARROW_UPWARD, icon_color=BLUE,
            icon_size=CONSTANTS.ICON_SM, tooltip="Dossier parent",
            disabled=True)
        list_view = ft.ListView(height=360, spacing=2)
        import_btn = ft.TextButton("Importer", disabled=True)
        dlg = ft.AlertDialog(
            title=ft.Text(description, size=CONSTANTS.TEXT_SM, color=WHITE),
            content=ft.Column([
                ft.Row([crumb_text, up_btn], spacing=4),
                status_text,
                list_view,
            ], tight=True, width=520),
            actions=[
                ft.TextButton("Annuler",
                              on_click=lambda e: _close_mtp_dialog(dlg)),
                import_btn,
            ],
        )
        page.overlay.append(dlg)
        dlg.open = True
        page.update()

        # On coche des DOSSIERS, pas des photos : la sélection fine se fait
        # ensuite dans le panneau Fichiers, avec les vignettes, le plein
        # écran et tous les outils habituels — ce qui suppose de vrais
        # fichiers sur le disque (retour user 2026-08-07 : « je veux voir
        # les images », impossible sur une liste de noms). La sélection
        # survit à la navigation : on peut cocher Camera, remonter, cocher
        # Screenshots, et tout copier d'un coup.
        picked = {}
        # Pile des dossiers traversés, la racine de l'appareil en premier.
        trail = []

        def _refresh_import_btn():
            import_btn.disabled = not picked
            import_btn.text = (f"Copier ({len(picked)} dossier(s))" if picked
                               else "Copier")

        def _toggle(item, checkbox):
            # Appelée depuis on_change : Flet a DÉJÀ basculé checkbox.value
            # avant de déclencher l'événement. Le rebasculer ici annulerait
            # le clic (case qui refuse de se cocher).
            if checkbox.value:
                picked[item.object_id] = item
            else:
                picked.pop(item.object_id, None)
            _refresh_import_btn()
            page.update()

        def _load(item, label, descend):
            """Charge un dossier dans un thread : les appels WPD prennent
            de quelques dizaines de ms à plusieurs secondes selon le
            nombre d'objets, et figeraient l'UI Flet."""
            if descend:
                trail.append((label, item))
            elif len(trail) > 1:
                trail.pop()
            crumb_text.value = " › ".join(lbl for lbl, _ in trail)
            up_btn.disabled = len(trail) <= 1
            status_text.value = "Chargement…"
            list_view.controls.clear()
            page.update()
            threading.Thread(target=lambda: _fill(trail[-1][1]),
                             daemon=True).start()

        def _fill(current):
            if current is None:
                # Première ouverture : l'appareil est ouvert ici, dans un
                # thread de travail, et pas sur le thread UI (cf. la RÈGLE
                # plus haut). trail garde la racine pour les retours.
                try:
                    current = mtp_devices.MTPDevice(pnp_id).root()
                except Exception as exc:
                    status_text.value = f"Erreur : {exc}"
                    page.update()
                    return
                trail[0] = (trail[0][0], current)
            # PAS de "with" sur le pool : si le thread reste bloqué sur un
            # appel COM, la sortie du bloc attendrait sa fin
            # (shutdown(wait=True) implicite) et annulerait l'intérêt du
            # délai max. Le thread orphelin part à la fermeture de l'appli.
            pool = concurrent.futures.ThreadPoolExecutor(max_workers=1)
            future = pool.submit(mtp_devices.list_folder, current)
            try:
                # 90 s : marge large, uniquement pour éviter un blocage
                # définitif. Un dossier de 1600 photos se lit en moins
                # d'une seconde sur le Mi 10T de test.
                folders, files = future.result(timeout=90)
            except concurrent.futures.TimeoutError:
                status_text.value = (
                    "Le téléphone ne répond pas (délai dépassé). Vérifie "
                    "qu'il est déverrouillé et que le transfert de "
                    "fichiers est bien autorisé, puis réessaie.")
                page.update()
                pool.shutdown(wait=False)
                return
            except Exception as exc:
                # Volontairement large : une exception non prévue ici
                # (signature COM, appareil débranché en cours de route...)
                # tuait le thread en silence et laissait le dialogue figé
                # sur "Recherche des photos..." pour toujours — c'était ça,
                # le "blocage" du premier essai réel (2026-08-07).
                status_text.value = f"Erreur : {exc}"
                page.update()
                pool.shutdown(wait=False)
                return
            pool.shutdown(wait=False)

            rows = []
            for folder in folders:
                # Case = « copier ce dossier », clic sur la ligne = entrer
                # dedans. Les deux gestes sont distincts pour rester
                # utilisables au doigt.
                cb = ft.Checkbox(value=folder.object_id in picked,
                                 active_color=BLUE,
                                 on_change=lambda e, f=folder: _toggle(
                                     f, e.control))
                rows.append(ft.ListTile(
                    leading=cb,
                    title=ft.Text(folder.name, size=CONSTANTS.TEXT_SM,
                                  color=WHITE, no_wrap=True),
                    trailing=ft.Icon(ft.Icons.CHEVRON_RIGHT,
                                     color=LIGHT_GREY,
                                     size=CONSTANTS.ICON_SM),
                    dense=True,
                    on_click=lambda e, f=folder: _load(f, f.name, True),
                ))
            # Les photos sont listées pour voir ce que contient le dossier
            # avant de le cocher, mais sans case : on ne choisit pas photo
            # par photo ici.
            shown = 0
            for item in files:
                # Un dossier photo contient aussi des vidéos et des PDF
                # (Download surtout) : ils ne sont ni comptés ni copiés.
                if os.path.splitext(item.name)[1].lower() \
                        not in CONSTANTS.IMAGE_EXTS:
                    continue
                shown += 1
                if shown > 40:
                    continue
                details = [d for d in (
                    item.date.strftime("%d/%m/%Y") if item.date else "",
                    _format_size(item.size)) if d]
                rows.append(ft.ListTile(
                    leading=ft.Icon(ft.Icons.IMAGE_OUTLINED, color=GREY,
                                    size=CONSTANTS.ICON_SM),
                    title=ft.Text(item.name, size=CONSTANTS.TEXT_SM,
                                  color=LIGHT_GREY, no_wrap=True),
                    subtitle=ft.Text(" — ".join(details),
                                     size=CONSTANTS.TEXT_SM, color=GREY),
                    dense=True,
                ))
            if shown > 40:
                # Plafond d'affichage : rendre 1600 lignes fige Flet
                # plusieurs secondes, et ça ne sert à rien puisqu'on coche
                # le dossier entier.
                rows.append(ft.ListTile(
                    title=ft.Text(f"… et {shown - 40} autres photos",
                                  size=CONSTANTS.TEXT_SM, color=GREY,
                                  italic=True),
                    dense=True,
                ))
            list_view.controls = rows
            parts = []
            if folders:
                parts.append(f"{len(folders)} dossier(s)")
            if shown:
                parts.append(f"{shown} photo(s)")
            status_text.value = " — ".join(parts) or "Dossier vide"
            _refresh_import_btn()
            import_btn.on_click = lambda e: _confirm_mtp_import(
                dlg, list(picked.values()))
            page.update()

        up_btn.on_click = lambda e: _load(None, None, False)
        # La racine entre dans trail avec un item None : _fill l'ouvre
        # lui-même côté thread de travail.
        _load(None, description, True)

    def _close_mtp_dialog(dlg):
        dlg.open = False
        page.update()

    # Débit mesuré sur un Mi 10T en USB : ~33 Mo/s, soit 0,19 s pour une
    # photo de 6,3 Mo. Sert uniquement à annoncer une durée avant de lancer.
    _MTP_BYTES_PER_SEC = 33 * 1024 * 1024
    # Au-delà, on propose de n'en prendre qu'une partie : copier les 1637
    # photos de DCIM/Camera, c'est 9,9 Go et 5,3 min d'attente, alors qu'un
    # client vient en général imprimer ses photos récentes.
    _MTP_RECENT_COUNT = 200

    def _mtp_list_images(folders):
        """Liste les photos des dossiers donnés, les plus récentes en
        tête. Appelée depuis un thread de travail (appels MTP)."""
        items, total = [], 0
        seen = set()
        for folder in folders:
            # walk_files et pas list_folder : cocher DCIM doit prendre
            # Camera, Screenshots... sinon on ne copierait rien, ce
            # dossier ne contenant que des sous-dossiers sur Android.
            for item in mtp_devices.walk_files(folder):
                if item.object_id in seen:
                    continue
                if os.path.splitext(item.name)[1].lower() \
                        in CONSTANTS.IMAGE_EXTS:
                    seen.add(item.object_id)
                    items.append(item)
                    total += item.size or 0
        # Un seul tri global : cocher Camera + Screenshots doit donner
        # une suite chronologique, pas deux blocs accolés.
        items.sort(key=lambda f: (f.date is not None, f.date, f.name),
                   reverse=True)
        return items, total

    def _ask_mtp_copy(items, total, detail):
        if not items:
            _log_to_terminal(
                "[ATTENTION] Aucune photo trouvée", ORANGE, clear=True)
            return
        minutes = total / _MTP_BYTES_PER_SEC / 60
        duration = (f"{minutes:.0f} min" if minutes >= 1
                    else f"{total / _MTP_BYTES_PER_SEC:.0f} s")
        actions = [ft.TextButton(
            "Annuler", on_click=lambda e: _close_mtp_dialog(ask_dlg))]
        if len(items) > _MTP_RECENT_COUNT:
            recent = items[:_MTP_RECENT_COUNT]
            recent_size = sum(i.size or 0 for i in recent)
            actions.append(ft.TextButton(
                f"Les {_MTP_RECENT_COUNT} plus récentes "
                f"({_format_size(recent_size)})",
                on_click=lambda e: (_close_mtp_dialog(ask_dlg),
                                    _start_mtp_copy(recent))))
        actions.append(ft.TextButton(
            f"Tout copier ({_format_size(total)}, {duration})",
            on_click=lambda e: (_close_mtp_dialog(ask_dlg),
                                _start_mtp_copy(items))))
        ask_dlg = ft.AlertDialog(
            title=ft.Text("Copier depuis le téléphone",
                          size=CONSTANTS.TEXT_SM, color=WHITE),
            content=ft.Text(
                f"{len(items)} photo(s) {detail}, "
                f"{_format_size(total)} au total (~{duration}).\n\n"
                "Les photos sont copiées dans un dossier local, puis "
                "Hub s'ouvre dessus : tu y retrouves les vignettes, le "
                "plein écran, la sélection et le transfert vers TEMP.",
                color=WHITE),
            actions=actions,
        )
        page.overlay.append(ask_dlg)
        ask_dlg.open = True
        page.update()

    def _confirm_mtp_import(dlg, folders):
        _close_mtp_dialog(dlg)
        if not folders:
            return

        def _work():
            try:
                items, total = _mtp_list_images(folders)
            except Exception as exc:
                _log_to_terminal(f"[ERREUR] {exc}", RED, clear=True)
                return
            _ask_mtp_copy(items, total,
                         f"dans {len(folders)} dossier(s)")

        _run_bg_action("Inventaire des photos du téléphone", _work)

    def _mtp_copy_all(pnp_id, description):
        # Bouton "Tout copier" sur la ligne du téléphone : évite la
        # navigation dossier par dossier quand on veut juste tout
        # rapatrier d'un coup (retour user — certaines machines montrent
        # encore des appareils MTP fantômes, autant limiter les allers-
        # retours dans l'arborescence en direct).
        def _work():
            try:
                root = mtp_devices.MTPDevice(pnp_id).root()
                items, total = _mtp_list_images([root])
            except Exception as exc:
                _log_to_terminal(f"[ERREUR] {exc}", RED, clear=True)
                return
            _ask_mtp_copy(items, total, f"sur {description}")

        _run_bg_action(f"Inventaire des photos de {description}", _work)

    def _start_mtp_copy(items):
        # Sous-dossier daté : deux imports successifs ne se mélangent pas,
        # et on retrouve celui du client précédent (même principe que le
        # sous-dossier daté de Transfert vers TEMP.py).
        dest = os.path.join(
            CONSTANTS.PHONE_IMPORT_FOLDER,
            datetime.datetime.now().strftime("%Y-%m-%d %Hh%M"))
        origin_tab_id = state["tab_id"]

        def _work():
            try:
                os.makedirs(dest, exist_ok=True)
            except OSError as exc:
                _log_to_terminal(
                    f"[ERREUR] Dossier d'import impossible : {exc}", RED)
                return
            # Navigation immédiate sur le dossier vide : les photos y
            # apparaissent au fur et à mesure, on peut commencer à
            # travailler sans attendre la fin (retour user : « il me faut
            # des feedback pour voir l'avancée »).
            page.run_task(_tool_refresh, dest, None, origin_tab_id)
            done, errors, copied_bytes = 0, 0, 0
            total = len(items)
            for i, item in enumerate(items, 1):
                try:
                    item.download_to(dest)
                    done += 1
                    copied_bytes += item.size or 0
                except Exception as exc:
                    errors += 1
                    _log_to_terminal(f"[ERREUR] {item.name} : {exc}", RED)
                    continue
                _log_to_terminal(
                    f"[...] {i}/{total} — {item.name} "
                    f"({_format_size(copied_bytes)})", ORANGE)
                # Rafraîchit la grille toutes les 10 photos, mais JAMAIS si
                # une sélection est en cours : _tool_refresh passe par
                # _navigate, qui vide la sélection — ça effacerait le choix
                # en train d'être fait pendant la copie.
                if i % 10 == 0 and not selected:
                    page.run_task(_tool_refresh, dest, None, origin_tab_id)
            if done:
                _log_to_terminal(
                    f"[OK] {done} photo(s) copiée(s) dans {dest}", BLUE)
            if errors:
                _log_to_terminal(
                    f"[ATTENTION] {errors} échec(s) — téléphone verrouillé "
                    "ou débranché en cours de copie ?", ORANGE)
            if not selected:
                page.run_task(_tool_refresh, dest, None, origin_tab_id)

        _run_bg_action(
            f"Copie de {len(items)} photo(s) depuis le téléphone", _work)

    def _do_delete(paths):
        folder = state["folder"]
        origin_tab_id = state["tab_id"]

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
            page.run_task(_tool_refresh, folder, None, origin_tab_id)

        _run_bg_action(f"Suppression de {len(paths)} élément(s)", _work)

    def _do_duplicate(paths):
        folder = state["folder"]
        if not folder:
            return
        origin_tab_id = state["tab_id"]

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
            page.run_task(_tool_refresh, folder, None, origin_tab_id)

        _run_bg_action(f"Duplication de {len(paths)} élément(s)", _work)

    def _do_rotate(paths, degrees):
        # Reprend la logique de _rotate_current (viewer, ligne ~3157)
        # mais sur un lot de fichiers sélectionnés dans la grille plutôt
        # que sur la seule image ouverte dans le viewer — même écrasement
        # destructif de l'original (retour user), sans backup : la
        # rotation n'en a jamais fait ici (cf. _rotate_current).
        folder = state["folder"]
        origin_tab_id = state["tab_id"]

        def _work():
            rotated_n = 0
            for path in paths:
                ext = os.path.splitext(path)[1].lower()
                if ext not in CONSTANTS.ROTATABLE_EXTS:
                    continue
                try:
                    with PILImage.open(path) as im:
                        icc_profile = im.info.get("icc_profile")
                        rotated = im.rotate(degrees, expand=True)
                        if ext in (".jpg", ".jpeg"):
                            rotated = rotated.convert("RGB")
                    fmt = "JPEG" if ext in (".jpg", ".jpeg") else "PNG"
                    save_kwargs = ({"quality": 100, "subsampling": 0}
                                  if fmt == "JPEG" else {})
                    if icc_profile:
                        save_kwargs["icc_profile"] = icc_profile
                    rotated.save(path, fmt, **save_kwargs)
                    thumb_mem.pop(path, None)
                    rotated_n += 1
                except Exception as exc:
                    _log_to_terminal(
                        f"[ERREUR] {os.path.basename(path)} : {exc}", RED)
            if rotated_n:
                _log_to_terminal(f"[OK] {rotated_n} photo(s) pivotée(s)",
                                GREEN)
            page.run_task(_tool_refresh, folder, None, origin_tab_id)

        _run_bg_action(f"Rotation de {len(paths)} élément(s)", _work)

    def _do_zip(paths):
        folder = state["folder"]
        paths = [p for p in paths if os.path.exists(p)]
        if not folder or not paths:
            return
        origin_tab_id = state["tab_id"]
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
            page.run_task(_tool_refresh, folder, None, origin_tab_id)

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
        names = "\n".join(os.path.basename(p) for p in zip_paths)
        ui_helpers.confirm_dialog(
            page, "Supprimer le(s) ZIP ?",
            lambda: _do_delete(zip_paths), _KEYPAD_COLORS,
            message=f"Voulez-vous supprimer :\n{names}",
            confirm_label="Supprimer", cancel_label="Conserver",
            confirm_color=RED)

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
        total = len(paths)
        for i, src in enumerate(paths, 1):
            if not os.path.isfile(src):
                continue
            _log_to_terminal(
                f"[...] Copie {i}/{total} : {os.path.basename(src)}", ORANGE)
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

        fired = {"done": False}

        def _cancel(event):
            dlg.open = False
            page.update()

        def _confirm(event):
            if fired["done"]:
                return
            fired["done"] = True
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
                _log_to_terminal(f"[ERREUR] Renommage : {exc}", RED, clear=True)
                return
            _log_to_terminal(f"[OK] Renommé : {current_name} → {new_name}", GREEN,
                            clear=True)
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
        page.run_task(_focus_dialog_field, name_field)

    _KEYPAD_COLORS = {"dark": DARK, "red": RED, "grey": GREY,
                      "green": GREEN, "white": WHITE}

    def _numeric_keypad(fields, on_confirm=None, allow_decimal=False):
        """Pavé numérique tactile réutilisable — wrapper autour de
        ui_helpers.numeric_keypad (partagé avec les autres apps du
        dossier Data/, ex. Recadrage manuel.pyw) pour ne pas répéter les
        couleurs de Hub à chaque appel."""
        return ui_helpers.numeric_keypad(
            page, fields, _KEYPAD_COLORS, on_confirm=on_confirm,
            allow_decimal=allow_decimal)

    def _set_print_count(paths):
        # Préfixe "NX_" lu par Recadrage automatique.py (mode fit) pour
        # savoir combien de copies d'une image tuiler sur le canevas —
        # cf. extract_copy_count_from_filename.
        # Sans sélection, tout le dossier : sert notamment à remettre
        # l'ensemble des photos à 0 d'un coup (retour user). Même idiome
        # que le bouton Imprimer — sélection, sinon dossier entier.
        targets = [p for p in (list(paths) or content["imgs"])
                   if os.path.exists(p)]
        if not targets:
            return
        parent = os.path.dirname(targets[0])
        match = re.match(r"^(\d+)[xX]_", os.path.basename(targets[0]))
        current_count = int(match.group(1)) if match else 1

        # Champ vide au départ même si un nombre existait déjà : l'usager
        # tape directement le nouveau nombre sans devoir d'abord effacer
        # l'ancien (retour user). L'ancien nombre reste visible en filigrane
        # (hint_text) à titre indicatif.
        count_field = ft.TextField(
            value="", autofocus=True, width=100,
            # Le filigrane n'a de sens que sur un fichier : sur un lot, les
            # nombres actuels diffèrent d'une photo à l'autre.
            hint_text=str(current_count) if len(targets) == 1 else "",
            bgcolor=DARK, border_color=GREY, color=WHITE,
            keyboard_type=ft.KeyboardType.NUMBER)

        fired = {"done": False}

        def _cancel(event):
            dlg.open = False
            page.update()

        def _confirm(event):
            if fired["done"]:
                return
            fired["done"] = True
            dlg.open = False
            page.update()
            try:
                count = int(count_field.value)
            except (TypeError, ValueError):
                return
            label = "sans préfixe" if count <= 0 else f"{count}X_"
            _log_to_terminal(
                f"Nombre d'impressions → {label} "
                f"({len(targets)} fichier(s))…", clear=True)
            # Renommages séquentiels : os.rename est quasi instantané en
            # local, ça ne se voit pas même sur un gros dossier. À passer
            # dans un thread si un jour ça sert sur un partage réseau lent.
            renamed = 0
            for path in targets:
                current_name = os.path.basename(path)
                # 0 (ou moins) = pas de préfixe du tout ; 1 garde bien
                # "1X_", qui n'est pas la même chose qu'un nom nu : le
                # préfixe dit « tirage commandé, en 1 exemplaire »,
                # l'absence de préfixe dit « pas de tirage » (retour user).
                hit = re.match(r"^(\d+)[xX]_", current_name)
                clean_name = current_name[hit.end():] if hit else current_name
                new_name = (clean_name if count <= 0
                            else f"{count}X_{clean_name}")
                if new_name == current_name:
                    continue
                try:
                    os.rename(path, os.path.join(
                        os.path.dirname(path), new_name))
                except OSError as exc:
                    _log_to_terminal(f"[ERREUR] {current_name} : {exc}", RED)
                    continue
                _select_discard(path)
                renamed += 1
            _log_to_terminal(
                f"[OK] Nombre d'impressions : {renamed} fichier(s) "
                f"renommé(s) en {label}", GREEN)
            _navigate(parent)

        count_field.on_submit = _confirm

        # Pavé numérique tactile : dialogue ouvert depuis le panneau
        # Actions, potentiellement sur écran tactile sans clavier commode
        # sous la main (retour user).
        keypad = _numeric_keypad(count_field, on_confirm=_confirm)

        dlg = ft.AlertDialog(
            # Le nombre de fichiers est le garde-fou du mode « dossier
            # entier » : c'est là qu'on voit qu'on s'apprête à en toucher 47
            # et pas 1.
            title=ft.Text(
                f"Nombre d'impressions — {len(targets)} fichier(s) "
                "(0 = retirer le préfixe NX_)",
                size=CONSTANTS.TEXT_SM, color=WHITE),
            content=ft.Column([count_field, keypad], spacing=12, tight=True),
            # Pas de bouton "Valider" ici : le ✓ vert du pavé numérique fait
            # déjà ça, juste au-dessus (retour user).
            actions=[ft.TextButton("Annuler", on_click=_cancel)],
        )
        page.overlay.append(dlg)
        dlg.open = True
        page.update()
        page.run_task(_focus_dialog_field, count_field)

    def _folder_unit_price(format_name, total_count):
        """Même tarif dégressif que Recadrage manuel.pyw::_unit_price /
        kiosk_flet.pyw::_get_unit_price (CONSTANTS.STUDIOS / CONSTANTS.PRINTS),
        piloté par state["tariff_mode"]. `None` si le format (nom du
        sous-dossier) n'est pas tarifé."""
        if state["tariff_mode"] == "STUDIOS":
            return CONSTANTS.STUDIOS.get(format_name)
        tiers = CONSTANTS.PRINTS.get(format_name)
        if tiers is None:
            return None
        if total_count <= 10:
            return tiers[0]
        if total_count <= 50:
            return tiers[1]
        if total_count <= 100:
            return tiers[2]
        if total_count <= 200:
            return tiers[3]
        return tiers[4]

    def _update_commande_file(event=None):
        """(Re)génère commande.txt à la racine du dossier ouvert à partir
        des préfixes NX_ déjà présents dans ses sous-dossiers (un
        sous-dossier = un format) — même logique que
        Recadrage manuel.pyw::_write_commande_file. Permet de recalculer
        la commande après avoir changé le nombre d'impressions de
        plusieurs photos via _set_print_count, sans rouvrir cet outil
        (retour user)."""
        folder = state["folder"]
        if not folder:
            return
        commande_path = os.path.join(folder, "commande.txt")
        if not os.path.isfile(commande_path):
            # Lancé depuis un sous-dossier de format ouvert dans Hub (ex.
            # "10x15") : commande.txt est en réalité dans le dossier parent
            # -> on remonte d'un cran avant d'abandonner (retour user).
            parent = os.path.dirname(folder)
            parent_commande = os.path.join(parent, "commande.txt")
            if parent and os.path.isfile(parent_commande):
                folder = parent
                commande_path = parent_commande
            else:
                _log_to_terminal("[ERREUR] Pas de commande.txt dans ce dossier", RED)
                return

        def _fmt_eur(value):
            return f"{value:.2f}".replace(".", ",") + "€"

        try:
            subfolders = sorted(
                d for d in os.listdir(folder)
                if os.path.isdir(os.path.join(folder, d)))
            lines = []
            grand_total_price = 0.0
            any_priced = False
            for sub in subfolders:
                sub_path = os.path.join(folder, sub)
                rows = []
                subtotal_qty = 0
                for name in sorted(os.listdir(sub_path)):
                    match = re.match(r'^(\d+)X_', name, re.IGNORECASE)
                    if not match:
                        continue
                    copies = int(match.group(1))
                    rows.append((copies, name[match.end():]))
                    subtotal_qty += copies
                if not rows:
                    continue
                lines.append(f"[{sub}]")
                for copies, clean_name in rows:
                    lines.append(f"{copies}X {clean_name}")
                lines.append("-------------------------------------")
                unit = _folder_unit_price(sub, subtotal_qty)
                if unit is None:
                    lines.append(f"{subtotal_qty} photo(s) (non tarifé)")
                else:
                    sub_price = round(subtotal_qty * unit, 2)
                    grand_total_price += sub_price
                    any_priced = True
                    lines.append(
                        f"{subtotal_qty} photo(s) = {_fmt_eur(sub_price)}")
                lines.append("")
            if state["tariff_mode"] == "PRINTS" and any_priced:
                grand_total_price += CONSTANTS.ORDER_SETUP_FEE
                lines.append("+ Frais d'amorçage = "
                             f"{_fmt_eur(CONSTANTS.ORDER_SETUP_FEE)}")
            lines.append("======================")
            lines.append(f"TOTAL = {_fmt_eur(grand_total_price)}")
            with open(commande_path, "w", encoding="utf-8") as f:
                f.write("\n".join(lines))
        except OSError as exc:
            _log_to_terminal(f"[ERREUR] commande.txt : {exc}", RED)
            return
        _log_to_terminal("[OK] commande.txt mis à jour", GREEN)

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
        page.run_task(_focus_dialog_field, label_field)

    # ─── Onglets multi-dossiers (suite) ─────────────────────────────────
    def _find_tab(tab_id):
        return next((t for t in tabs if t["id"] == tab_id), None)

    def _snapshot_active_tab():
        """Recopie le dossier + la sélection courants dans l'entrée de
        l'onglet actif avant de basculer ailleurs — sans ça, revenir sur
        cet onglet plus tard perdrait la navigation faite pendant qu'il
        était affiché."""
        tab = _find_tab(state["tab_id"])
        if tab is not None:
            tab["folder"] = state["folder"]
            tab["selected"] = list(selected)

    def _tab_label_text(tab):
        # Onglet actif : label dérivé de state["folder"] (toujours à
        # jour, y compris pendant une navigation en profondeur dans le
        # même onglet) ; onglet inactif : dernière valeur mémorisée par
        # _snapshot_active_tab().
        is_active = tab["id"] == state["tab_id"]
        folder = state["folder"] if is_active else tab["folder"]
        if not folder:
            return "Nouvel onglet"
        return os.path.basename(folder.rstrip(os.sep))

    def _render_tab_bar(row, tabs_list, active_id, label_fn, select_fn,
                        close_fn, new_fn):
        # Générique : sert la barre d'onglets du panneau Fichiers ET,
        # en Phase 2, celle du panneau droit (Total Commander) — mêmes
        # contrôles, juste des listes/handlers différents.
        row.controls.clear()
        for tab in tabs_list:
            is_active = tab["id"] == active_id
            label = ft.Text(
                label_fn(tab), size=CONSTANTS.TEXT_SM,
                color=DARK if is_active else WHITE, no_wrap=True,
                max_lines=1, overflow=ft.TextOverflow.ELLIPSIS, width=140)
            close_btn = ft.IconButton(
                ft.Icons.CLOSE, icon_size=14,
                icon_color=DARK if is_active else LIGHT_GREY,
                tooltip="Fermer l'onglet", visible=len(tabs_list) > 1,
                on_click=lambda e, tid=tab["id"]: close_fn(tid),
                style=ft.ButtonStyle(padding=0), width=22, height=22)
            row.controls.append(ft.Container(
                content=ft.Row(
                    [label, close_btn], spacing=2, tight=True,
                    vertical_alignment=ft.CrossAxisAlignment.CENTER),
                padding=ft.Padding(10, 6, 4, 6), border_radius=6,
                bgcolor=BLUE if is_active else GREY, ink=True,
                on_click=lambda e, tid=tab["id"]: select_fn(tid)))
        row.controls.append(ft.IconButton(
            ft.Icons.ADD, icon_size=16, icon_color=BLUE,
            tooltip="Nouvel onglet", on_click=new_fn))
        try:
            row.update()
        except Exception:
            pass

    def _save_tabs_state():
        # Persisté à chaque changement (nouvel onglet, fermeture,
        # bascule, ou simple navigation dans l'onglet actif — cf. l'appel
        # à _render_folder_tabs() en fin de _navigate()) : pas besoin
        # d'un hook dédié à la fermeture de l'app, l'état sur disque est
        # déjà à jour en continu (retour user : retrouver au démarrage
        # les dossiers laissés ouverts avant un arrêt/redémarrage).
        folders = [state["folder"] if tab["id"] == state["tab_id"]
                  else tab["folder"] for tab in tabs]
        active_idx = next(
            (i for i, t in enumerate(tabs) if t["id"] == state["tab_id"]), 0)
        _save_open_tabs([f or "" for f in folders], active_idx)

    def _render_folder_tabs():
        _render_tab_bar(folder_tabs_row, tabs, state["tab_id"],
                        _tab_label_text, _select_folder_tab,
                        _close_folder_tab, _new_folder_tab)
        _save_tabs_state()

    def _restore_tab(tab_id):
        """Active l'onglet `tab_id` : rescane son dossier (content n'est
        jamais mis en cache par onglet, cf. commentaire de tête) et
        ré-applique sa sélection mémorisée, filtrée aux chemins qui
        existent encore sur disque."""
        tab = _find_tab(tab_id)
        if tab is None:
            return
        state["tab_id"] = tab_id
        selected.clear()
        if tab["folder"]:
            _navigate(tab["folder"])
        else:
            content["dirs"], content["imgs"], content["other"] = [], [], []
            content["mtime"] = {}
            state["folder"] = None
            files_path.value = ""
        _select_update(p for p in tab["selected"] if os.path.exists(p))
        _update_sel_count()
        _render()
        _render_folder_tabs()

    def _select_folder_tab(tab_id, event=None):
        if tab_id == state["tab_id"]:
            return
        _snapshot_active_tab()
        _restore_tab(tab_id)

    def _new_folder_tab(event=None):
        _snapshot_active_tab()
        _next_tab_id["n"] += 1
        tab_id = _next_tab_id["n"]
        tabs.append({"id": tab_id, "folder": None, "selected": []})
        _restore_tab(tab_id)
        _toggle_open_menu()

    def _close_folder_tab(tab_id, event=None):
        if len(tabs) <= 1:
            return   # toujours >= 1 onglet
        idx = next((i for i, t in enumerate(tabs) if t["id"] == tab_id), None)
        if idx is None:
            return
        if tab_id == state["tab_id"]:
            # Bascule sur le voisin AVANT de retirer l'onglet fermé de la
            # liste — jamais de tab_id actif orphelin entre les deux.
            neighbor = tabs[idx + 1] if idx + 1 < len(tabs) else tabs[idx - 1]
            _restore_tab(neighbor["id"])
        tabs[:] = [t for t in tabs if t["id"] != tab_id]
        _render_folder_tabs()

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
        _search_debounce["token"] += 1   # annule un rendu de frappe en attente
        state["search"] = ""
        search_field.value = ""
        try:
            entries = list(os.scandir(path))
        except OSError as exc:
            content["dirs"], content["imgs"], content["other"] = [], [], []
            files_list.controls.clear()
            files_list.controls.append(ft.Text(str(exc), color=WHITE))
            files_body.content = files_list
            _render_folder_tabs()
            page.update()
            return
        exts = CONSTANTS.IMAGE_EXTS | CONSTANTS.HUB_VECTOR_EXTS
        dirs, imgs, other = [], [], []
        mtimes = {}
        for e in entries:
            if CONSTANTS.is_os_junk(e.name, e.is_dir()):
                continue
            try:
                # entry.stat() vient du scandir déjà fait (gratuit sous
                # Windows) — alimente le cache mtime lu par _sort_key.
                mtimes[e.path] = e.stat().st_mtime
            except OSError:
                pass
            if e.is_dir():
                dirs.append(e.path)
            elif os.path.splitext(e.name)[1].lower() in exts:
                imgs.append(e.path)
            else:
                other.append(e.path)
        content["mtime"] = mtimes
        content["dirs"] = sorted(dirs, key=lambda p: os.path.basename(p).lower())
        content["imgs"] = sorted(imgs, key=lambda p: os.path.basename(p).lower())
        content["other"] = sorted(other, key=lambda p: os.path.basename(p).lower())
        _update_sel_count()
        _render()
        _render_folder_tabs()
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
            _select_update(_merge_files_sorted(imgs, other))
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
        mtime = content["mtime"].get(path)
        if mtime is None:
            try:
                mtime = os.path.getmtime(path)
            except OSError:
                return None
        return datetime.date.fromtimestamp(mtime)

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
        only_sel_icon.color = (
            DARK if state["only_selected"] else BLUE)
        _render()

    def _toggle_tariff(event):
        state["tariff_mode"] = "PRINTS" if event.control.value else "STUDIOS"
        event.control.label = ("Tarif Impression" if event.control.value
                                else "Tarif Studio")
        page.update()

    def _toggle_order_mode(event):
        # Bascule inline (case à cocher <-> badge commande sur chaque
        # vignette) — pas de clic droit, pas de menu déroulant caché.
        order_mode["value"] = not order_mode["value"]
        order_mode_btn.style = ft.ButtonStyle(
            bgcolor=ORANGE if order_mode["value"] else GREY)
        order_mode_icon.color = (
            DARK if order_mode["value"] else ORANGE)
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

    def _apply_font_size(value):
        # Même curseur que les vignettes (statusbar), reconfiguré en mode
        # "taille de texte" sur les onglets IA/Bloc-notes (cf. statusbar
        # plus bas) — pas de widget dupliqué, juste un réglage qui change
        # de cible selon l'onglet actif (retour user).
        size = int(value)
        if size == state["font_size"]:
            return
        state["font_size"] = size
        notes_field.text_style = ft.TextStyle(font_family="monospace", size=size)
        if state["surface"] == "notes" and not notes_is_preview["value"]:
            notes_field.update()
        notes_preview.md_style_sheet = ft.MarkdownStyleSheet(
            p_text_style=ft.TextStyle(size=size))
        if state["surface"] == "notes" and notes_is_preview["value"]:
            notes_preview.update()
        for ctrl, offset in ai_text_refs:
            if isinstance(ctrl, ft.Markdown):
                ctrl.md_style_sheet = ft.MarkdownStyleSheet(
                    p_text_style=ft.TextStyle(size=size))
            else:
                ctrl.size = size + offset
        if state["surface"] == "ia":
            ai_chat_view.update()

    def _bar_icon_btn(icon, color, on_click, tooltip, **kwargs):
        # Bouton icône de la barre Fichiers : pastille grise, icône
        # colorée, hauteur commune. Ce style était recopié à l'identique
        # sur 5 boutons (parent, rafraîchir, nouveau dossier, nouveau
        # fichier, dossier de commande) — d'où un create_order_btn resté
        # sans pastille au milieu de ses voisins. Un seul endroit à
        # toucher au prochain ajustement.
        return ft.IconButton(
            icon=icon, icon_color=color, icon_size=CONSTANTS.ICON_SM,
            style=ft.ButtonStyle(bgcolor=GREY, padding=ft.Padding.all(10)),
            height=CONSTANTS.HUB_TOOLBAR_H, on_click=on_click,
            tooltip=tooltip, **kwargs)

    def _seg_btn(icon, text, on_click, color=None):
        # Icône seule, libellé en infobulle : cette barre débordait dès que
        # la fenêtre passait en demi-écran (retour user). Les intitulés
        # ("Tout sélectionner", "Afficher la sélection"…) sont longs alors
        # que les icônes sont sans ambiguïté une fois la barre connue.
        #
        # `color=None` (par défaut) : l'Icon hérite de ButtonStyle.color, ce
        # qui permet à only_sel_btn (_toggle_only_selected) de recolorer tout
        # le bouton (fond + icône) en une seule affectation selon l'état
        # actif/inactif — ne pas fixer `color` dans ce cas. Un `color`
        # explicite (ex. VIOLET) sert aux boutons non-toggle.
        return ft.TextButton(
            content=ft.Icon(icon, size=CONSTANTS.ICON_SM, color=color),
            style=ft.ButtonStyle(bgcolor=GREY, color=WHITE,
                                 padding=ft.Padding(12, 0, 12, 0)),
            height=CONSTANTS.HUB_TOOLBAR_H, on_click=on_click,
            tooltip=text,
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

    # Debounce (~250 ms) : _render() reconstruit toute la vue et relance
    # le chargeur de miniatures — le faire à chaque caractère rendait la
    # frappe poussive sur les gros dossiers. Le rendu ne part qu'une fois
    # la frappe stabilisée ; le token invalide les rendus en attente
    # (nouvelle frappe, effacement, navigation).
    _search_debounce = {"token": 0}

    def _on_search_change(event):
        _search_debounce["token"] += 1
        token = _search_debounce["token"]
        value = event.control.value

        async def _apply():
            await asyncio.sleep(0.25)
            if _search_debounce["token"] == token:
                _set_search(value)

        page.run_task(_apply)

    def _clear_search(event=None):
        _search_debounce["token"] += 1
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
        hint_text="Rechercher…", on_change=_on_search_change,
        on_submit=_clear_search,
        height=45, bgcolor=DARK, border_color=BLUE,
        color=WHITE, text_size=CONSTANTS.TEXT_SM,
        content_padding=ft.Padding(8, 2, 8, 2),
        prefix_icon=ft.Icons.SEARCH,
        expand=True,
        on_focus=_focus_search("files_search"), on_blur=_blur_search,
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
            sort_label.value = _SORT_SHORT[mode]
            _render()
        return _apply

    # Sans le préfixe « Trier : » — l'icône SORT à côté le dit déjà, et
    # cette barre manque de place en demi-écran (retour user).
    sort_label = ft.Text(_SORT_SHORT['date'], size=CONSTANTS.TEXT_SM,
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
                    ft.Icon(ft.Icons.SORT, size=CONSTANTS.ICON_SM, color=YELLOW,
                            tooltip="Trier les fichiers"),
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
    viewer_state = {"paths": [], "index": 0, "win_start": 0}
    _prev_keyboard = {"fn": None}
    # path -> bytes tournés cette session : le chemin fichier ne change pas
    # après rotation, donc Flet pourrait réafficher l'ancienne image en cache
    # si on repasse par le chemin brut au lieu des bytes à jour.
    viewer_rotated_bytes = {}

    # Page PDF actuellement affichée par fichier (retour user : un PDF
    # multi-pages ne montrait toujours que la 1re page) — dict plutôt que
    # champ unique dans viewer_state pour que revenir sur un PDF déjà
    # feuilleté retrouve sa page, sans code de reset à ajouter à chaque
    # point de navigation entre fichiers.
    viewer_pdf_page = {}
    _pdf_page_count_cache = {}
    _pdf_page_render_cache = {}
    _PDF_PAGE_CACHE_MAX = 8

    def _pdf_page_count(path):
        if not path.lower().endswith(".pdf"):
            return 1
        if path not in _pdf_page_count_cache:
            try:
                import pymupdf as fitz  # "fitz" est un alias déprécié
                with fitz.open(path) as doc:
                    _pdf_page_count_cache[path] = doc.page_count
            except Exception:
                _pdf_page_count_cache[path] = 1
        return _pdf_page_count_cache[path]

    def _render_pdf_page(path, page_num):
        """JPEG (bytes) de la page `page_num` d'un PDF, corrigé écran comme
        les miniatures thumb_cache — rendu direct, hors thumb_cache (qui ne
        connaît que la page 0, utilisée pour les miniatures de la grille)."""
        key = (path, page_num)
        if key in _pdf_page_render_cache:
            return _pdf_page_render_cache[key]
        try:
            import pymupdf as fitz  # "fitz" est un alias déprécié
            with fitz.open(path) as doc:
                pg = doc[page_num]
                longest = max(pg.rect.width, pg.rect.height) or 1
                zoom = min(4.0, max(0.5, 3200 / longest))
                pix = pg.get_pixmap(matrix=fitz.Matrix(zoom, zoom), alpha=False)
                img = PILImage.frombytes(
                    "RGB", (pix.width, pix.height), pix.samples)
            buf = io.BytesIO()
            image_ops.compensate_for_display(img).save(
                buf, "JPEG", quality=90)
            data = buf.getvalue()
        except Exception:
            return None
        _pdf_page_render_cache[key] = data
        while len(_pdf_page_render_cache) > _PDF_PAGE_CACHE_MAX:
            _pdf_page_render_cache.pop(next(iter(_pdf_page_render_cache)))
        return data

    # Swipe tactile (retour user, comme Dashboard.pyw:5678) : PageView natif
    # Flet si disponible (buggy sur Linux d'après Dashboard) — une page par
    # image, chargées à la volée (_load_pages_around) pour ne pas décoder
    # tout un dossier d'un coup. Sinon, fallback = ancien système à image
    # unique + boutons/clavier, inchangé.
    _HAS_PAGE_VIEW = hasattr(ft, "PageView") and platform.system() != "Linux"
    page_image_controls = {}  # index -> ft.Image, seulement en mode PageView
    pages_loaded = set()

    _BLANK_GIF = "data:image/gif;base64,R0lGODlhAQABAAD/ACwAAAAAAQABAAACADs="
    viewer_img = ft.Image(src=_BLANK_GIF, fit=ft.BoxFit.CONTAIN, expand=True,
                          gapless_playback=True)
    viewer_filename = ft.Text("", size=CONSTANTS.TEXT_SM, color=WHITE,
                              weight=ft.FontWeight.W_500)
    viewer_meta = ft.Text("", size=CONSTANTS.TEXT_SM, color=WHITE)
    viewer_counter = ft.Text("", size=CONSTANTS.TEXT_SM, color=WHITE)
    viewer_pdf_page_text = ft.Text("", size=CONSTANTS.TEXT_SM, color=WHITE)
    viewer_pdf_page_row = ft.Row([
        ft.IconButton(icon=ft.Icons.KEYBOARD_ARROW_LEFT, icon_color=WHITE,
                     icon_size=CONSTANTS.ICON_SM, tooltip="Page précédente (↑)",
                     on_click=lambda e: _pdf_page_nav(-1)),
        viewer_pdf_page_text,
        ft.IconButton(icon=ft.Icons.KEYBOARD_ARROW_RIGHT, icon_color=WHITE,
                     icon_size=CONSTANTS.ICON_SM, tooltip="Page suivante (↓)",
                     on_click=lambda e: _pdf_page_nav(1)),
    ], spacing=0, tight=True, alignment=ft.MainAxisAlignment.CENTER)
    viewer_pdf_page_row.visible = False
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

    def _resolve_viewer_src(path):
        # Flutter ne sait pas afficher un .svg/.pdf par chemin (Image.file
        # ne rend que les formats raster) — on passe par thumb_cache pour
        # obtenir un PNG/JPEG rendu, en cache dès le deuxième affichage.
        if path in viewer_rotated_bytes:
            return viewer_rotated_bytes[path]
        ext = os.path.splitext(path)[1].lower()
        if ext == ".pdf":
            page_num = viewer_pdf_page.get(path, 0)
            if page_num:
                rendered_page = _render_pdf_page(path, page_num)
                if rendered_page:
                    return rendered_page
            # Page 0 : passe par thumb_cache (déjà en cache dès la
            # miniature de la grille, pas besoin de re-rendre via fitz).
            rendered = thumb_cache.get_or_generate(path, size_px=1600)
            if rendered:
                return image_ops.compensate_jpeg_bytes(rendered)
            return path
        if ext in CONSTANTS.HUB_VECTOR_EXTS:
            rendered = thumb_cache.get_or_generate(path, size_px=1600)
            if rendered:
                return image_ops.compensate_jpeg_bytes(rendered)
            return path
        return path

    def _update_overlay_bar():
        idx, paths = viewer_state["index"], viewer_state["paths"]
        path = paths[idx]
        viewer_filename.value = os.path.basename(path)
        viewer_meta.value = _viewer_meta_text(path)
        viewer_counter.value = f"{idx + 1} / {len(paths)}"
        viewer_checkbox.value = path in selected
        viewer_order_slot.visible = order_mode["value"]
        viewer_order_slot.content = (
            _order_badge(path) if order_mode["value"] else None)
        _update_pdf_page_ui(path)
        page.update()

    def _update_pdf_page_ui(path):
        count = _pdf_page_count(path)
        viewer_pdf_page_row.visible = count > 1
        if count > 1:
            viewer_pdf_page_text.value = (
                f"Page {viewer_pdf_page.get(path, 0) + 1} / {count}")

    def _pdf_page_nav(delta):
        if not viewer_state["paths"]:
            return
        idx = viewer_state["index"]
        path = viewer_state["paths"][idx]
        new_page = viewer_pdf_page.get(path, 0) + delta
        if not (0 <= new_page < _pdf_page_count(path)):
            return
        viewer_pdf_page[path] = new_page
        if _HAS_PAGE_VIEW:
            pages_loaded.discard(idx)
            _load_image_for_index(idx)
        else:
            viewer_img.src = _resolve_viewer_src(path)
        _update_pdf_page_ui(path)
        page.update()

    # Bytes corrigés pour l'affichage (conversion ICC -> sRGB + compensation
    # écran, cf. image_ops) : petit LRU en mémoire — un JPEG plein format
    # corrigé pèse plusieurs Mo, inutile d'en garder plus que la fenêtre de
    # navigation immédiate.
    _viewer_color_cache = {}
    _VIEWER_COLOR_CACHE_MAX = 8

    def _viewer_corrected_bytes(path):
        """JPEG corrigé pour l'affichage, ou None si rien à corriger
        (image sRGB sans profil sur écran sRGB)."""
        try:
            with PILImage.open(path) as img:
                icc_profile = img.info.get("icc_profile")
                img = PILImageOps.exif_transpose(img)
                needs_icc = bool(icc_profile) or img.mode == "CMYK"
                if (not needs_icc
                        and image_ops.get_display_transform() is None):
                    return None
                converted = (image_ops.convert_to_srgb(img, icc_profile)
                             if needs_icc else img)
                changed = converted is not img
                compensated = image_ops.compensate_for_display(converted)
                changed = changed or compensated is not converted
                if not changed:
                    return None
                buffer = io.BytesIO()
                compensated.convert("RGB").save(buffer, "JPEG", quality=90)
                return buffer.getvalue()
        except Exception:
            return None

    def _start_viewer_color_fix(idx, path, ctrl):
        # L'image s'affiche d'abord par chemin (instantané, Flutter décode)
        # puis les bytes corrigés remplacent la texture dès qu'ils sont
        # prêts — pas de latence perceptible à la navigation, mais les
        # couleurs deviennent identiques à Aperçu/Photos (retour user :
        # aperçus plus saturés sur écran large gamut, P3/CMJN délavés).
        if path in viewer_rotated_bytes:
            return
        if os.path.splitext(path)[1].lower() in CONSTANTS.HUB_VECTOR_EXTS:
            return

        def _work():
            data = _viewer_color_cache.get(path)
            if data is None:
                data = _viewer_corrected_bytes(path)
                if data is None:
                    return
                _viewer_color_cache[path] = data
                while len(_viewer_color_cache) > _VIEWER_COLOR_CACHE_MAX:
                    _viewer_color_cache.pop(next(iter(_viewer_color_cache)))
            paths_now = viewer_state["paths"]
            if (page_image_controls.get(idx) is ctrl
                    and 0 <= idx < len(paths_now)
                    and paths_now[idx] == path
                    and path not in viewer_rotated_bytes):
                ctrl.src = data
                # Hors sujet vignettes de dossier : ne pas invalider sur
                # thumb_token, juste réutiliser le token courant pour que
                # le garde-fou de _safe_update n'annule jamais cet appel.
                page.run_task(_safe_update, [ctrl], state["thumb_token"])

        threading.Thread(target=_work, daemon=True).start()

    def _load_image_for_index(idx):
        # Ne recharge jamais une page déjà chargée : la rotation en mémoire
        # (viewer_rotated_bytes) invalide explicitement l'index via
        # pages_loaded.discard() avant de rappeler cette fonction.
        paths = viewer_state["paths"]
        ctrl = page_image_controls.get(idx)
        if not (0 <= idx < len(paths)) or ctrl is None or idx in pages_loaded:
            return
        ctrl.src = _resolve_viewer_src(paths[idx])
        pages_loaded.add(idx)
        _start_viewer_color_fix(idx, paths[idx], ctrl)
        try:
            page.update()
        except Exception:
            pass

    def _load_pages_around(center):
        for offset in (0, 1, -1, 2, -2):
            _load_image_for_index(center + offset)

    def _update_viewer():
        idx = viewer_state["index"]
        if _HAS_PAGE_VIEW:
            pages_loaded.discard(idx)
            _load_pages_around(idx)
        else:
            viewer_img.src = _resolve_viewer_src(viewer_state["paths"][idx])
        _update_overlay_bar()

    async def _viewer_animate_page(delta):
        if delta < 0:
            await images_page_view.previous_page(
                animation_curve=ft.AnimationCurve.EASE_IN_OUT_CUBIC_EMPHASIZED,
                animation_duration=ft.Duration(milliseconds=300))
        else:
            await images_page_view.next_page(
                animation_curve=ft.AnimationCurve.EASE_IN_OUT_CUBIC_EMPHASIZED,
                animation_duration=ft.Duration(milliseconds=300))

    def _on_viewer_page_change(e):
        _close_drawers()
        viewer_state["index"] = (viewer_state["win_start"]
                                 + e.control.selected_index)
        _load_pages_around(viewer_state["index"])
        _update_overlay_bar()
        _maybe_shift_viewer_window()

    def _viewer_nav(delta):
        new_idx = viewer_state["index"] + delta
        if not (0 <= new_idx < len(viewer_state["paths"])):
            return
        _close_drawers()
        if _HAS_PAGE_VIEW:
            page.run_task(_viewer_animate_page, delta)
        else:
            viewer_state["index"] = new_idx
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
        elif event.key == "Arrow Up":
            _pdf_page_nav(-1)
        elif event.key == "Arrow Down":
            _pdf_page_nav(1)

    def _rotate_current(direction):
        # Écrase l'original (retour user : la miniature de la grille doit
        # refléter la rotation, contrairement aux tiroirs Retoucher/
        # Recadrer qui restent non-destructifs). Fait en SYNCHRONE (pas de
        # thread) : deux clics rapprochés (rotation à 180°) doivent
        # s'accumuler l'un sur l'autre — un thread en arrière-plan permettait
        # au 2e clic de relire le fichier avant que le 1er ait fini
        # d'écrire, donc de repartir de l'orientation d'origine à chaque
        # fois au lieu d'accumuler, et risquait une écriture concurrente sur
        # le même fichier.
        path = viewer_state["paths"][viewer_state["index"]]
        ext = os.path.splitext(path)[1].lower()
        if ext not in CONSTANTS.ROTATABLE_EXTS:
            return
        try:
            with PILImage.open(path) as im:
                icc_profile = im.info.get("icc_profile")
                rotated = im.rotate(90 if direction == "left" else -90, expand=True)
                if ext in (".jpg", ".jpeg"):
                    rotated = rotated.convert("RGB")
        except Exception:
            return
        fmt = "JPEG" if ext in (".jpg", ".jpeg") else "PNG"
        save_kwargs = {"quality": 100, "subsampling": 0} if fmt == "JPEG" else {}
        if icc_profile:
            # Sans ça, la rotation réenregistrait le fichier SANS son
            # profil (une photo Display P3 devenait délavée partout après
            # rotation) — le profil suit l'image, inchangé.
            save_kwargs["icc_profile"] = icc_profile
        # Bytes d'AFFICHAGE corrigés (ICC -> sRGB + compensation écran,
        # comme _viewer_corrected_bytes) — le fichier écrit sur disque,
        # lui, garde ses pixels et son profil d'origine.
        display_img = image_ops.compensate_for_display(
            image_ops.convert_to_srgb(rotated, icc_profile))
        buf = io.BytesIO()
        display_img.convert("RGB").save(buf, "JPEG", quality=90)
        viewer_rotated_bytes[path] = buf.getvalue()
        idx = viewer_state["index"]   # aperçu immédiat
        if _HAS_PAGE_VIEW:
            ctrl = page_image_controls.get(idx)
            if ctrl is not None:
                ctrl.src = viewer_rotated_bytes[path]
                pages_loaded.add(idx)
        else:
            viewer_img.src = viewer_rotated_bytes[path]
        page.update()

        try:
            rotated.save(path, fmt, **save_kwargs)
        except Exception as exc:
            _log_to_terminal(f"[ERREUR] Rotation : {exc}", RED)
            return
        _log_to_terminal(f"Rotation enregistrée : {path}", GREEN)
        # La miniature en cache (mémoire + SQLite) doit être régénérée
        # puisque le fichier a changé sous le même nom (cf. thumb_cache.
        # get_or_generate, qui compare la taille en octets) — sans purger
        # thumb_mem ici, la grille garderait l'ancienne vignette en mémoire
        # jusqu'au redémarrage de Hub.
        thumb_mem.pop(path, None)
        if state["folder"]:
            page.run_task(_ai_navigate_async, state["folder"])

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
            viewer_pdf_page_row,
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
            ft.VerticalDivider(width=1, color=LIGHT_GREY),
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
    def _build_viewer_page(img_ctrl, win_w, win_h):
        # Pan/zoom natif Flet (même widget que le viewer plein écran de
        # Dashboard.pyw:5567-5578) : `width`/`height` explicites (pas
        # `expand`) -> l'InteractiveViewer a un viewport concret, sinon
        # `constrained=True` le dimensionne sur le rectangle CONTAIN de
        # l'image (déjà lettrboxée) au lieu du plein écran, et zoomer
        # agrandit l'image DANS ce rectangle fixe au lieu du canevas
        # lui-même (retour user, captures à l'appui).
        return ft.InteractiveViewer(
            content=img_ctrl, min_scale=1.0, max_scale=6.0,
            pan_enabled=True, scale_enabled=True, constrained=True,
            width=win_w, height=win_h, clip_behavior=ft.ClipBehavior.HARD_EDGE)

    # Fenêtre glissante de pages : construire un contrôle par photo du
    # dossier faisait payer l'ouverture de la visionneuse (et chaque
    # page.update()) proportionnellement à la taille du dossier — sur des
    # centaines de photos, plusieurs secondes avant la première image
    # (retour user). Seules ~2×_VIEWER_WIN_HALF pages existent à la fois ;
    # la fenêtre se décale par reconstruction quand on approche du bord,
    # bien avant les pages réellement chargées (±2 par _load_pages_around).
    _VIEWER_WIN_HALF = 25
    _VIEWER_WIN_MARGIN = 8

    def _viewer_window_bounds(center, total):
        start = max(0, center - _VIEWER_WIN_HALF)
        end = min(total, center + _VIEWER_WIN_HALF + 1)
        return start, end

    def _build_page_containers(paths, start, end):
        # Une page par image de la fenêtre (retour user : swipe tactile
        # façon Dashboard) — seul le contenu autour de l'index courant est
        # réellement chargé (_load_pages_around), les autres pages restent
        # sur le gif blanc tant qu'on ne navigue pas jusqu'à elles.
        # page_image_controls est indexé par index GLOBAL dans `paths`.
        page_image_controls.clear()
        pages_loaded.clear()
        win_w = page.window.width or 1280
        win_h = page.window.height or 860
        containers = []
        for global_idx in range(start, end):
            img_ctrl = ft.Image(src=_BLANK_GIF, fit=ft.BoxFit.CONTAIN,
                                expand=True, gapless_playback=True)
            page_image_controls[global_idx] = img_ctrl
            containers.append(ft.Container(
                content=_build_viewer_page(img_ctrl, win_w, win_h),
                expand=True, alignment=ft.Alignment.CENTER, bgcolor=DARK))
        return containers

    def _maybe_shift_viewer_window():
        paths = viewer_state["paths"]
        total = len(paths)
        if total <= 2 * _VIEWER_WIN_HALF + 1:
            return
        idx = viewer_state["index"]
        start = viewer_state["win_start"]
        end = start + len(images_page_view.controls)
        near_left = idx - start < _VIEWER_WIN_MARGIN and start > 0
        near_right = end - idx <= _VIEWER_WIN_MARGIN and end < total
        if not (near_left or near_right):
            return
        new_start, new_end = _viewer_window_bounds(idx, total)
        if new_start == start:
            return
        viewer_state["win_start"] = new_start
        images_page_view.controls = _build_page_containers(
            paths, new_start, new_end)
        images_page_view.selected_index = idx - new_start
        # Pages autour de l'index rechargées AVANT le page.update() : la
        # photo courante ne repasse jamais par le gif blanc.
        _load_pages_around(idx)
        page.update()

    if _HAS_PAGE_VIEW:
        images_page_view = ft.PageView(
            controls=[], expand=True, horizontal=True,
            on_change=_on_viewer_page_change)
    else:
        # Fallback : une seule image visible à la fois (navigation par
        # boutons/clavier) — le système déjà en place avant le swipe.
        images_page_view = _build_viewer_page(
            viewer_img, page.window.width or 1280, page.window.height or 860)

    # Conteneurs positionnés nommés (pas `expand=True`) pour pouvoir réduire
    # dynamiquement `right` quand un tiroir est ouvert — évite qu'il ne
    # masque une partie de l'image (retour utilisateur).
    viewer_image_wrap = ft.Container(content=images_page_view, bgcolor=DARK,
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
        images_page_view.width = (page.window.width or 1280) - width
        images_page_view.height = page.window.height or 860

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
        -1, _viewer_btn(ft.Icons.CROP_FREE,
                       "Retoucher / recadrer (Recadrage manuel.pyw)",
                       _launch_editor_for_current("Recadrage manuel.pyw")))
    viewer_bottom_bar.content.controls.insert(
        -1, _viewer_btn(ft.Icons.AUTO_AWESOME, "Augmentation IA",
                       _launch_editor_for_current("Augmentation IA.py")))

    def _open_viewer(start_path):
        if selected and start_path in selected:
            paths = [p for p in content["imgs"] if p in selected]
        elif start_path in content["imgs"]:
            paths = content["imgs"]
        else:
            paths = [start_path]
        viewer_state["paths"] = paths
        viewer_state["index"] = paths.index(start_path)
        if _HAS_PAGE_VIEW:
            start, end = _viewer_window_bounds(viewer_state["index"],
                                               len(paths))
            viewer_state["win_start"] = start
            images_page_view.controls = _build_page_containers(
                paths, start, end)
            images_page_view.selected_index = viewer_state["index"] - start
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
                from concurrent.futures import ThreadPoolExecutor
                DRIVE_TYPE_REMOVABLE, DRIVE_TYPE_CDROM = 2, 5
                letters = "ABCDEFGHIJKLMNOPQRSTUVWXYZ"

                def _check_letter(letter):
                    path = f"{letter}:\\"
                    drive_type = ctypes.windll.kernel32.GetDriveTypeW(path)
                    if (drive_type in (DRIVE_TYPE_REMOVABLE, DRIVE_TYPE_CDROM)
                            and os.path.exists(path)):
                        label_buffer = ctypes.create_unicode_buffer(261)
                        ctypes.windll.kernel32.GetVolumeInformationW(
                            path, label_buffer, 261, None, None,
                            None, None, 0)
                        label = label_buffer.value or letter
                        return (f"{label} ({letter}:)", path)
                    return None

                # Une lettre par thread : un lecteur multi-cartes avec un
                # slot vide peut bloquer plusieurs secondes sur
                # GetVolumeInformationW/os.path.exists (matériel interrogé
                # pour de vrai) — en série, ces délais s'additionnaient
                # lettre par lettre avant que le périphérique réellement
                # branché n'apparaisse (retour user : trop lent pour
                # accéder à une carte SD/clé USB avec un client en attente).
                with ThreadPoolExecutor(max_workers=len(letters)) as pool:
                    for result in pool.map(_check_letter, letters):
                        if result:
                            drives.append(result)
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

    def _poll_removable_drives():
        # Comme Dashboard.pyw:7498 (_poll_removable_drives) : un scan
        # toutes les 3 s pendant toute la session, pour que le menu Ouvrir
        # lise une liste déjà à jour au lieu de scanner à chaque ouverture
        # (retour user : accès immédiat à une carte SD/clé USB avec un
        # client en attente). Les périphériques tout juste branchés
        # passent en tête de liste, les autres gardent leur ordre.
        prev_drives = []
        ordered_drives = []

        def _poll_phones():
            # Les téléphones MTP n'ont pas de lettre de lecteur : ils ne
            # peuvent pas passer par _get_removable_drives. Sondés ici pour
            # apparaître dans le même volet "Périphériques" du menu Ouvrir
            # (retour user 2026-08-07 : le bouton était perdu dans
            # Actions). list_devices() ouvre et referme chaque appareil
            # pour filtrer les emplacements de lecteur de cartes vides
            # (retour user 2026-08-15) : plus que ~50 ms si un vrai
            # téléphone est branché, mais reste sur un thread de travail,
            # donc apartment COM correct (cf. la RÈGLE dans la section
            # MTP), et sans impact sur l'UI.
            try:
                phones_state["list"] = [
                    (d.description, d.id) for d in mtp_devices.list_devices()]
            except Exception:
                phones_state["list"] = []

        # Premier sondage tout de suite : le scan initial des lecteurs, lui,
        # est fait en synchrone au démarrage, mais il doit rester hors du
        # thread principal pour les téléphones.
        _poll_phones()
        while True:
            time.sleep(3)
            try:
                drives = _get_removable_drives()
                if drives != prev_drives:
                    new_drives = [d for d in drives if d not in prev_drives]
                    existing_drives = [d for d in ordered_drives if d in drives]
                    ordered_drives = new_drives + existing_drives
                    prev_drives = drives
                    drives_state["list"] = ordered_drives
            except Exception:
                pass
            _poll_phones()

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

    def _phone_row(description, pnp_id):
        # Pas de bouton Éjecter : un appareil MTP n'est pas monté comme un
        # volume, il se débranche sans précaution. Et pas de _open_from_menu
        # non plus : il n'y a pas de chemin disque à ouvrir, d'où le
        # dialogue de navigation dédié.
        return ft.ListTile(
            leading=ft.Icon(ft.Icons.PHONE_IPHONE, color=BLUE,
                            size=CONSTANTS.ICON_SM),
            title=ft.Text(description, size=CONSTANTS.TEXT_SM, color=WHITE,
                          no_wrap=True),
            trailing=ft.IconButton(
                ft.Icons.DOWNLOAD, icon_color=BLUE,
                icon_size=CONSTANTS.ICON_SM,
                tooltip="Tout copier depuis l'appareil",
                on_click=lambda e: (_close_open_menu(),
                                    _mtp_copy_all(pnp_id, description))),
            on_click=lambda e: (_close_open_menu(),
                                _open_mtp_import_dialog(pnp_id, description)),
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

    def _menu_lane(title, items, empty_message):
        # Toujours une seule colonne par volet (défilement vertical si le
        # contenu déborde) — le menu Ouvrir reste figé à 3 colonnes
        # (Historique / Favoris / Périphériques), jamais plus (retour user).
        body = items or [ft.Container(
            content=ft.Text(empty_message, size=CONSTANTS.TEXT_SM, color=GREY),
            padding=ft.Padding(10, 8, 10, 8))]
        return ft.Container(
            width=_MENU_LANE_WIDTH, height=_MENU_LANE_HEIGHT,
            content=ft.Column([
                _menu_section_label(title),
                ft.Column(body, spacing=0, scroll=ft.ScrollMode.AUTO, expand=True),
            ], spacing=0, expand=True))

    def _build_open_menu():
        favs = _load_favorites()
        recents = _load_recent()

        recent_lane = _menu_lane(
            "Historique", [_recent_row(p) for p in recents[:30]],
            "Aucun dossier récent")
        fav_lane = _menu_lane(
            "Favoris", [_fav_row(f) for f in favs], "Aucun favori")
        # "Périphériques" lu directement dans drives_state["list"] — tenu
        # à jour en tâche de fond par _poll_removable_drives (toutes les
        # 3 s), donc déjà disponible sans scanner à l'ouverture du menu
        # (retour user : accès immédiat avec un client en attente).
        # Téléphones en tête : quand on en branche un, c'est pour l'ouvrir
        # tout de suite, alors qu'une clé/carte reste souvent branchée.
        drive_lane = _menu_lane(
            "Périphériques",
            [_phone_row(n, i) for n, i in phones_state["list"]]
            + [_drive_row(n, p) for n, p in drives_state["list"]],
            "Aucun périphérique externe")

        def _prune_recents():
            # Même raison que pour l'historique : la liste s'affiche telle
            # quelle tout de suite (non filtrée, cf. _load_recent), puis un
            # dossier disparu/injoignable (partage NAS endormi) est retiré
            # silencieusement une fois la vérification terminée, sans
            # jamais retarder l'affichage du menu (retour user).
            valid = [p for p in recents if os.path.isdir(p)]
            if valid == recents:
                return
            _save_recent(valid)
            items = [_recent_row(p) for p in valid[:30]] or [ft.Container(
                content=ft.Text("Aucun dossier récent",
                                size=CONSTANTS.TEXT_SM, color=GREY),
                padding=ft.Padding(10, 8, 10, 8))]
            recent_lane.content.controls[1].controls = items
            try:
                page.update()
            except Exception:
                pass

        threading.Thread(target=_prune_recents, daemon=True).start()

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

        lanes = [
            recent_lane, ft.VerticalDivider(color=LIGHT_GREY),
            fav_lane, ft.VerticalDivider(color=LIGHT_GREY),
            drive_lane,
        ]

        open_menu_panel.content = ft.Column([
            ft.Row(lanes, spacing=6, vertical_alignment=ft.CrossAxisAlignment.START),
            ft.Divider(height=1, color=LIGHT_GREY),
            footer,
        ], spacing=6, tight=True)

    open_menu_panel = ft.Container(
        bgcolor=GREY, border_radius=10, padding=ft.Padding(6, 6, 6, 6),
        border=ft.Border.all(1, BLUE),
        content=ft.Column([], spacing=0),
    )
    # top/left approximatifs : open_menu_btn a déménagé de files_header vers
    # la WDA (retour user), donc l'ancien ancrage (top=84, left=52, sous
    # l'ex-emplacement du bouton) ne correspond plus — à ajuster visuellement
    # si le panneau n'est pas pile sous le bouton "Ouvrir".
    open_menu_overlay = ft.Stack([
        ft.Container(expand=True, on_click=lambda e: _close_open_menu()),
        ft.Container(content=open_menu_panel, top=STRIP_HEIGHT + 4, left=200),
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

    parent_folder_btn = _bar_icon_btn(
        ft.Icons.ARROW_UPWARD, ICON_ACTION, _go_to_parent_folder,
        "Dossier parent")

    def _refresh_folder(event=None):
        folder = state["folder"]
        if not folder:
            return
        _log_to_terminal("[CMD] Rafraîchir", BLUE)
        # On jette les miniatures en mémoire du dossier courant ET le
        # cache SQLite persistant (thumb_cache.purge_folder) : se fier au
        # stat() (mtime/size) pour détecter un changement ne suffit pas —
        # sur un dossier réseau/NAS, ce stat() peut lui-même être périmé
        # juste après l'écriture par un autre programme (retour user :
        # photo modifiée sur le NAS toujours affichée à l'ancienne après
        # Rafraîchir, seul un redémarrage complet de Hub la rafraîchissait
        # enfin). "Rafraîchir" est un geste explicite et rare : on force
        # une régénération inconditionnelle plutôt que de re-questionner
        # un stat() qui vient justement de tromper le cache une 1re fois.
        for p in [p for p in thumb_mem if os.path.dirname(p) == folder]:
            del thumb_mem[p]
        thumb_cache.purge_folder(folder)
        # Même souci côté visionneuse plein écran : une appli tierce
        # utilisée en plugin (Affinity, Topaz...) réenregistre l'image à
        # plat sous le même chemin, mais Flutter garde l'ancien contenu
        # décodé pour ce chemin (FileImage mis en cache par chemin, pas par
        # contenu) — Rafraîchir seul ne suffisait pas, il fallait quitter
        # Hub entièrement. On jette nos caches par chemin et on repousse
        # l'image actuellement affichée en bytes bruts (comme
        # _rotate_current), ce qui contourne ce cache Flutter.
        pages_loaded.clear()
        _viewer_color_cache.clear()
        viewer_rotated_bytes.clear()
        _pdf_page_render_cache.clear()
        _pdf_page_count_cache.clear()
        if viewer_overlay in page.overlay and viewer_state["paths"]:
            idx = viewer_state["index"]
            path = viewer_state["paths"][idx]
            try:
                with open(path, "rb") as f:
                    data = f.read()
            except OSError:
                data = None
            if data is not None:
                ctrl = (page_image_controls.get(idx) if _HAS_PAGE_VIEW
                        else viewer_img)
                if ctrl is not None:
                    ctrl.src = data
                    if _HAS_PAGE_VIEW:
                        pages_loaded.add(idx)
                    page.update()
        # ponytail: ne force que l'image actuellement affichée ; si on
        # quitte puis revient sur la même image sans re-Rafraîchir, le
        # FileImage Flutter de ce chemin (mis en cache avant ce Rafraîchir)
        # peut resurgir. Solution complète : ne plus jamais passer par un
        # chemin brut en src, toujours des bytes — à faire si ça se reproduit.
        _navigate(folder)

    refresh_folder_btn = _bar_icon_btn(
        ft.Icons.REFRESH, ICON_ACTION, _refresh_folder, "Rafraîchir")

    def _create_folder_here(event=None):
        # Même principe que Dashboard.pyw:6218-6277 (create_new_folder) :
        # un simple dialogue nom -> os.makedirs, pas de duplication de
        # cette logique côté Data/ pour un geste aussi simple.
        folder = state["folder"]
        if not folder:
            return

        def _next_sequential_name():
            # Pas de nom saisi : "01", "02"... comme Transfert vers TEMP
            # (get_next_sequence_folder), jusqu'au premier nom libre.
            n = 1
            while os.path.exists(os.path.join(folder, f"{n:02d}")):
                n += 1
            return f"{n:02d}"

        def _on_confirm(value):
            name = value or _next_sequential_name()
            new_path = os.path.join(folder, name)
            try:
                os.makedirs(new_path, exist_ok=False)
            except OSError as exc:
                _log_to_terminal(f"[ERREUR] Création dossier : {exc}", RED)
                return
            _log_to_terminal(f"[OK] Dossier créé : {name}", BLUE)
            _navigate(new_path)

        ui_helpers.text_prompt_dialog(
            page, "Créer un nouveau dossier", _on_confirm, _KEYPAD_COLORS,
            hint_text="nom-du-dossier", confirm_label="Créer")

    def _create_file_here(event=None):
        folder = state["folder"]
        if not folder:
            return

        def _on_confirm(name):
            if not name:
                return
            # Pas d'extension tapée -> .md par défaut (retour user : le
            # champ Renommer masque l'extension en suffixe fixe, la
            # confusion est de penser que "Créer un fichier" fait pareil).
            if not os.path.splitext(name)[1]:
                name += ".md"
            _folder_create_file(folder, name, "")
            _navigate(folder)

        ui_helpers.text_prompt_dialog(
            page, "Créer un fichier ici", _on_confirm, _KEYPAD_COLORS,
            hint_text="nom-du-fichier.md", confirm_label="Créer")

    # _launch_tool / _launch_transfert_temp / _launch_recadrage_auto /
    # _launch_two_in_one sont définis plus loin dans main() : lambda pour
    # différer la résolution jusqu'au clic (même principe partout ici).
    # Icône seule (pas de TextButton avec label) — retour user : usage
    # fréquent à chaque client, sorti du panneau Actions, mais sans bloat
    # de largeur en mode compagnon demi-écran.
    def _toolbar_icon_btn(icon, color, on_click, tooltip):
        # Couleurs inversées (fond plein, icône DARK) + ICON_LG — retour
        # user : plus visibles que le style GREY/icône colorée des boutons
        # voisins (parent/refresh/nouveau dossier), marge dispo en demi-écran.
        return ft.IconButton(
            icon=icon, icon_color=DARK, icon_size=CONSTANTS.ICON_LG,
            style=ft.ButtonStyle(bgcolor=color, padding=ft.Padding.all(6)),
            height=CONSTANTS.HUB_TOOLBAR_H, on_click=on_click,
            tooltip=tooltip,
        )

    kiosk_gauche_btn = _toolbar_icon_btn(
        ft.Icons.KEYBOARD_DOUBLE_ARROW_LEFT_SHARP, VIOLET,
        lambda e: _launch_tool("Kiosk gauche.py", is_local=True),
        "Kiosk gauche")

    transfert_temp_btn = _toolbar_icon_btn(
        ft.Icons.DRIVE_FILE_MOVE_OUTLINED, BLUE,
        lambda e: _launch_transfert_temp(e),
        "Transfert vers TEMP (dossier Download)")

    # ROUGE volontaire (exception à « une couleur = un rôle ») : c'est
    # l'outil le plus lancé de la journée, le repérer d'un coup d'œil dans
    # la barre prime sur la cohérence de la palette (retour user).
    recadrage_manuel_btn = _toolbar_icon_btn(
        ft.Icons.CROP_FREE, RED,
        lambda e: _launch_tool(
            "Recadrage manuel.pyw",
            extra_env={"TARIFF_TYPE": state["tariff_mode"]}),
        "Recadrage manuel")

    recadrage_auto_btn = _toolbar_icon_btn(
        ft.Icons.CROP, GREEN, lambda e: _launch_recadrage_auto(e),
        "Recadrage automatique")

    two_en_un_btn = _toolbar_icon_btn(
        ft.CupertinoIcons.SQUARE_SPLIT_2X1, GREEN,
        lambda e: _launch_two_in_one(e),
        "2 en 1")

    retouche_par_lot_btn = _toolbar_icon_btn(
        ft.Icons.TUNE, VIOLET,
        lambda e: _launch_tool("Retouche par lot.pyw"),
        "Retouche par lot (aperçu live)")

    augmentation_ia_btn = _toolbar_icon_btn(
        ft.Icons.AUTO_FIX_HIGH_OUTLINED, VIOLET,
        lambda e: _launch_tool("Augmentation IA.py"),
        "Augmentation IA")
    # Toujours actifs, avec ou sans sélection : sans fichier sélectionné,
    # les outils lancés par _launch_tool traitent tout le dossier (retour
    # user) — cf. Data/skills.md:21 (SELECTED_FILES absent = tout le
    # dossier) et le garde-fou déjà dans _launch_tool (folder requis).

    new_folder_btn = _bar_icon_btn(
        ft.Icons.CREATE_NEW_FOLDER_OUTLINED, YELLOW, _create_folder_here,
        "Créer un nouveau dossier")

    create_file_btn = _bar_icon_btn(
        ft.Icons.NOTE_ADD_OUTLINED, ICON_ACTION, _create_file_here,
        "Créer un fichier dans le dossier ouvert",
        disabled=not state["folder"])

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

    # Accès direct à _set_print_count (déjà présent dans le panneau Actions)
    # depuis la barre Fichiers, à gauche de Mode commande (retour user).
    # Icônes seules sur toute cette barre, libellé en infobulle — cf. _seg_btn.
    # Ces trois-là étaient recopiés à la main sous la forme
    # TextButton(content=Icon(...)) — soit exactement ce que _seg_btn
    # produit déjà. Le garde-fou `len(selected) == 1` a été retiré :
    # _set_print_count applique déjà le même nombre à toute une sélection
    # multiple (targets = paths ou dossier entier), il bloquait donc sans
    # raison ce cas précis (retour user).
    print_count_btn = _seg_btn(
        ft.Icons.NUMBERS,
        "Changer le nombre de tirages (préfixe NX_) de la sélection",
        lambda e: _run_action(_set_print_count, list(selected)),
        color=ORANGE)

    # Recalcule commande.txt (dossier ouvert) après avoir changé le nombre
    # d'impressions de plusieurs photos, sans rouvrir Recadrage manuel.pyw
    # (retour user).
    update_order_btn = _seg_btn(
        ft.Icons.SYNC,
        "Recalcule commande.txt à partir des préfixes NX_ du dossier ouvert",
        lambda e: _run_action(_update_commande_file), color=ORANGE)

    # Icon() n'hérite pas de ButtonStyle.color (contrairement à Text()) —
    # couleur posée explicitement sur l'Icon, sinon elle reste au bleu par
    # défaut de Flet au lieu de CONSTANTS.COLOR_BLUE.
    # ORANGE comme le reste du cluster commande (nb de tirages, resync,
    # dossier de commande) : les quatre boutons servent une seule tâche.
    order_mode_btn = _seg_btn(
        ft.Icons.RECEIPT_LONG_OUTLINED,
        "Format + nombre directement sur chaque photo",
        _toggle_order_mode, color=ORANGE)
    # Ref sur l'Icon interne, comme only_sel_btn : _toggle_order_mode
    # recolore l'icône et le fond séparément selon l'état actif.
    order_mode_icon = order_mode_btn.content

    only_sel_btn = _seg_btn(ft.Icons.VISIBILITY_OUTLINED, "Afficher la sélection",
                            _toggle_only_selected)
    only_sel_icon = only_sel_btn.content
    only_sel_icon.color = BLUE

    tariff_switch = ft.Switch(
        label=("Tarif Impression" if state["tariff_mode"] == "PRINTS"
               else "Tarif Studio"),
        value=(state["tariff_mode"] == "PRINTS"),
        active_color=BLUE, on_change=_toggle_tariff,
        label_text_style=ft.TextStyle(size=CONSTANTS.TEXT_SM, color=WHITE),
        tooltip="Tarif utilisé par Recadrage manuel et le Kiosque")
    # Largeur fixe : "Tarif Impression" est plus long que "Tarif Studio",
    # sans ça la bascule fait trembler le reste de la barre d'outils.
    tariff_wrap = ft.Container(
        content=tariff_switch, height=CONSTANTS.HUB_TOOLBAR_H, width=150,
        alignment=ft.Alignment(0, 0), margin=ft.Margin.only(right=12))

    # _create_order_folder est défini plus loin (avec le reste de la logique
    # de commande) : lambda pour différer la résolution du nom jusqu'au clic.
    # Passe par _bar_icon_btn : c'est le seul de son cluster qui n'avait
    # pas la pastille grise de ses voisins (style oublié à la main).
    create_order_btn = _bar_icon_btn(
        ft.Icons.FOLDER_ZIP_OUTLINED, ORANGE,
        lambda e: page.run_task(_create_order_folder, e),
        "Créer le dossier de commande", visible=order_mode["value"])

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

    # Chips Renommer -> Supprimer : à côté de la recherche (retour user :
    # accès direct sans ouvrir le panneau Actions, où ils restent aussi).
    # Icône seule + grisées (disabled) tant qu'aucune sélection valide —
    # retour user : toujours un feedback visuel maximal sur ce qui est
    # utilisable.
    # (bouton, sa couleur active) — `disabled=True` seul ne suffit pas à
    # griser visiblement une icône dont `icon_color` est fixé explicitement
    # (retour user : pas assez visible) ; on repasse aussi l'icône en
    # LIGHT_GREY à la main, comme only_sel_btn le fait déjà pour son état.
    # Rempli par _edit_icon_btn : une seule source de vérité pour la couleur
    # (avant, la couleur du call-site était ignorée et divergeait de celle
    # utilisée au dégrisage).
    _sel_edit_btns = []

    def _edit_icon_btn(icon, color, on_click, tooltip, selection_driven=True):
        # Même pastille que le reste de la barre (_bar_icon_btn), mais
        # icon_color=LIGHT_GREY au départ : cohérent avec disabled=True tant
        # que _refresh_edit_buttons() n'a pas encore tourné une 1re fois.
        btn = _bar_icon_btn(icon, LIGHT_GREY, on_click, tooltip,
                            disabled=True)
        if selection_driven:
            _sel_edit_btns.append((btn, color))
        return btn

    # NE PAS retirer les gardes `if selected else None` de ces lambdas en
    # les croyant redondantes avec `disabled` : le panneau Actions
    # (_action_row -> ft.ListTile) réutilise ces mêmes on_click et n'a,
    # LUI, aucun état désactivé. Sans la garde, une ligne Actions cliquée
    # sans sélection lance l'action à vide.
    renommer_btn = _edit_icon_btn(
        ft.Icons.DRIVE_FILE_RENAME_OUTLINE, BLUE,
        lambda e: _run_action(_rename_item, list(selected))
                  if len(selected) == 1 else None,
        "Renommer")
    copier_btn = _edit_icon_btn(
        ft.Icons.CONTENT_COPY, BLUE,
        lambda e: _run_action(_do_copy, list(selected)) if selected else None,
        "Copier")
    couper_btn = _edit_icon_btn(
        ft.Icons.CONTENT_CUT, BLUE,
        lambda e: _run_action(_do_cut, list(selected)) if selected else None,
        "Couper")
    # Coller ne dépend pas de la sélection mais du presse-papiers interne
    # (clipboard["paths"]) — grisé/dégrisé séparément, cf. _do_copy/_do_cut/
    # _do_paste : hors de _sel_edit_btns.
    coller_btn = _edit_icon_btn(
        ft.Icons.CONTENT_PASTE, BLUE,
        lambda e: _run_action(_do_paste),
        "Coller", selection_driven=False)
    dupliquer_btn = _edit_icon_btn(
        ft.Icons.FILE_COPY_OUTLINED, BLUE,
        lambda e: _run_action(_do_duplicate, list(selected)) if selected else None,
        "Dupliquer")
    # ORANGE volontaire : « Zipper » produit un fichier au lieu d'agir sur
    # place, on le repère d'un coup d'œil parmi les bleus (retour user).
    zipper_btn = _edit_icon_btn(
        ft.Icons.FOLDER_ZIP_OUTLINED, ORANGE,
        lambda e: _run_action(_do_zip, list(selected)) if selected else None,
        "Zipper")
    ajouter_ia_btn = _edit_icon_btn(
        ft.Icons.SMART_TOY_OUTLINED, VIOLET,
        lambda e: _run_action(_add_to_ai, list(selected)) if selected else None,
        "Ajouter à l'IA")
    supprimer_btn = _edit_icon_btn(
        ft.Icons.DELETE_OUTLINE, RED,
        lambda e: _run_action(_do_delete, list(selected)) if selected else None,
        "Supprimer")

    def _set_edit_btn_state(btn, color, enabled):
        btn.disabled = not enabled
        btn.icon_color = color if enabled else LIGHT_GREY

    def _refresh_edit_buttons():
        n = len(selected)
        for btn, color in _sel_edit_btns:
            # Renommer n'a de sens que sur un seul élément ; les autres
            # acceptent n'importe quelle sélection non vide. Test par
            # identité plutôt qu'un `[1:]` qui dépendait de l'ordre de
            # création des boutons.
            enabled = (n == 1) if btn is renommer_btn else (n > 0)
            _set_edit_btn_state(btn, color, enabled)
        _set_edit_btn_state(coller_btn, BLUE, bool(clipboard["paths"]))
        for btn, _color in _sel_edit_btns + [(coller_btn, BLUE)]:
            try:
                btn.update()
            except Exception:
                pass

    edit_btns_row = ft.Row(
        [renommer_btn,
        ft.Container(ft.VerticalDivider(color=LIGHT_GREY),
            height=CONSTANTS.HUB_TOOLBAR_H),
        copier_btn, couper_btn, coller_btn, dupliquer_btn,
        ft.Container(ft.VerticalDivider(color=LIGHT_GREY),
        height=CONSTANTS.HUB_TOOLBAR_H),
        zipper_btn, ajouter_ia_btn, supprimer_btn], spacing=4)

    # Repli "..." sous CONSTANTS.HUB_TITLEBAR_NARROW_WIDTH, même principe
    # que la barre de titre (retour user) : ces 8 boutons ne wrappaient
    # pas et débordaient hors champ en demi-écran. Les libellés/couleurs
    # dupliquent volontairement renommer_btn..supprimer_btn ci-dessus —
    # simplification assumée : le menu n'a pas leur état grisé/dégrisé
    # (_refresh_edit_buttons ne le pilote pas), les handlers eux-mêmes
    # protègent déjà contre une sélection vide (garde `if selected else
    # None`), donc cliquer un item du menu sans rien sélectionné ne fait
    # rien — juste sans le retour visuel grisé de la version large.
    _EDIT_MENU_TOOLS = [
        (ft.Icons.DRIVE_FILE_RENAME_OUTLINE, BLUE, "Renommer",
         lambda e: _run_action(_rename_item, list(selected))
                   if len(selected) == 1 else None),
        (ft.Icons.CONTENT_COPY, BLUE, "Copier",
         lambda e: _run_action(_do_copy, list(selected)) if selected
                   else None),
        (ft.Icons.CONTENT_CUT, BLUE, "Couper",
         lambda e: _run_action(_do_cut, list(selected)) if selected
                   else None),
        (ft.Icons.CONTENT_PASTE, BLUE, "Coller",
         lambda e: _run_action(_do_paste)),
        (ft.Icons.FILE_COPY_OUTLINED, BLUE, "Dupliquer",
         lambda e: _run_action(_do_duplicate, list(selected)) if selected
                   else None),
        (ft.Icons.FOLDER_ZIP_OUTLINED, ORANGE, "Zipper",
         lambda e: _run_action(_do_zip, list(selected)) if selected
                   else None),
        (ft.Icons.SMART_TOY_OUTLINED, VIOLET, "Ajouter à l'IA",
         lambda e: _run_action(_add_to_ai, list(selected)) if selected
                   else None),
        (ft.Icons.DELETE_OUTLINE, RED, "Supprimer",
         lambda e: _run_action(_do_delete, list(selected)) if selected
                   else None),
    ]
    edit_btns_menu = ft.PopupMenuButton(
        icon=ft.Icons.MORE_HORIZ, icon_color=WHITE,
        icon_size=CONSTANTS.ICON_SM,
        tooltip="Renommer, copier, couper, coller, dupliquer, zipper, "
                "ajouter à l'IA, supprimer",
        items=[
            ft.PopupMenuItem(
                content=ft.Row([
                    ft.Icon(icon, color=color, size=CONSTANTS.ICON_SM),
                    ft.Text(label, size=CONSTANTS.TEXT_SM, color=WHITE),
                ], spacing=8),
                on_click=handler)
            for icon, color, label, handler in _EDIT_MENU_TOOLS
        ],
        visible=False,
    )

    touch_actions_line = ft.Row(
        [search_field_wrap, edit_btns_row, edit_btns_menu],
        spacing=32, vertical_alignment=ft.CrossAxisAlignment.CENTER, expand=True)

    # Seul "Nombre d'impressions" (print_count_btn) a un double dans le
    # panneau Actions (_fichier_actions) — retour user : seules les icônes
    # dupliquées là-bas peuvent se replier, tout le reste de cette ligne
    # (sélection, affichage, commande) reste TOUJOURS visible, sans repli.
    print_count_menu = ft.PopupMenuButton(
        icon=ft.Icons.MORE_HORIZ, icon_color=ORANGE,
        icon_size=CONSTANTS.ICON_SM,
        tooltip="Changer le nombre de tirages de la sélection",
        items=[
            ft.PopupMenuItem(
                content=ft.Row([
                    ft.Icon(ft.Icons.NUMBERS, color=ORANGE,
                           size=CONSTANTS.ICON_SM),
                    ft.Text("Nombre de tirages", size=CONSTANTS.TEXT_SM,
                           color=WHITE),
                ], spacing=8),
                on_click=lambda e: _run_action(
                    _set_print_count, list(selected)))
        ],
        visible=False,
    )
    selection_actions_row = ft.Row([
        _seg_btn(ft.Icons.SELECT_ALL, "Tout sélectionner", _toggle_all,
                 color=VIOLET),
        _seg_btn(ft.Icons.FLIP, "Inverser", _invert, color=VIOLET),
        _seg_btn(ft.Icons.EVENT, "Même date", _select_same_date,
                 color=VIOLET),
        only_sel_btn,
        ft.Container(expand=True),
        print_count_btn,
        print_count_menu,
        update_order_btn,
        order_mode_btn,
        create_order_btn,
    ], spacing=10, expand=True,
       vertical_alignment=ft.CrossAxisAlignment.CENTER)

    # Ligne 1 : dossier parent/rafraîchir/nouveau dossier/créer fichier +
    # Kiosk gauche/Transfert TEMP (absents du panneau Actions) + tri/
    # affichage TOUJOURS visibles (retour user : seules les icônes qui ont
    # un double dans le panneau Actions peuvent se replier). Seuls les 5
    # lanceurs présents dans _ACTION_CATEGORIES (Recadrage manuel/auto,
    # 2 en 1, Retouche par lot, Augmentation IA) se replient dans un menu
    # "..." en dessous de CONSTANTS.HUB_TITLEBAR_NARROW_WIDTH.
    tools_nav_row = ft.Row([
        parent_folder_btn, refresh_folder_btn, new_folder_btn,
        ft.Container(ft.VerticalDivider(color=LIGHT_GREY),
                    height=CONSTANTS.HUB_TOOLBAR_H),
        kiosk_gauche_btn, transfert_temp_btn,
        ft.Container(ft.VerticalDivider(color=LIGHT_GREY),
                    height=CONSTANTS.HUB_TOOLBAR_H),
        create_file_btn,
    ], spacing=8)

    _LAUNCHER_MENU_TOOLS = [
        (ft.Icons.CROP_FREE, RED, "Recadrage manuel",
         lambda e: _launch_tool(
             "Recadrage manuel.pyw",
             extra_env={"TARIFF_TYPE": state["tariff_mode"]})),
        (ft.Icons.CROP, GREEN, "Recadrage automatique",
         lambda e: _launch_recadrage_auto(e)),
        (ft.CupertinoIcons.SQUARE_SPLIT_2X1, GREEN, "2 en 1",
         lambda e: _launch_two_in_one(e)),
        (ft.Icons.TUNE, VIOLET, "Retouche par lot (aperçu live)",
         lambda e: _launch_tool("Retouche par lot.pyw")),
        (ft.Icons.AUTO_FIX_HIGH_OUTLINED, VIOLET, "Augmentation IA",
         lambda e: _launch_tool("Augmentation IA.py")),
    ]
    launcher_row = ft.Row([
        recadrage_manuel_btn, recadrage_auto_btn, two_en_un_btn,
        ft.Container(ft.VerticalDivider(color=LIGHT_GREY),
                    height=CONSTANTS.HUB_TOOLBAR_H),
        retouche_par_lot_btn, augmentation_ia_btn,
    ], spacing=8)
    launcher_menu = ft.PopupMenuButton(
        icon=ft.Icons.MORE_HORIZ, icon_color=WHITE,
        icon_size=CONSTANTS.ICON_SM,
        tooltip="Recadrages, 2 en 1, retouche par lot, augmentation IA",
        items=[
            ft.PopupMenuItem(
                content=ft.Row([
                    ft.Icon(icon, color=color, size=CONSTANTS.ICON_SM),
                    ft.Text(label, size=CONSTANTS.TEXT_SM, color=WHITE),
                ], spacing=8),
                on_click=handler)
            for icon, color, label, handler in _LAUNCHER_MENU_TOOLS
        ],
        visible=False,
    )

    files_header = ft.Container(
        content=ft.Column([
            ft.Row([
                tools_nav_row,
                ft.Container(ft.VerticalDivider(color=LIGHT_GREY),
                            height=CONSTANTS.HUB_TOOLBAR_H),
                launcher_row,
                launcher_menu,
                ft.Container(expand=True),
                sort_btn,
                view_seg_wrap,
            ], spacing=12, vertical_alignment=ft.CrossAxisAlignment.CENTER),
            selection_actions_row,
            touch_actions_line,
        ], spacing=10),
        padding=ft.Padding(12, 12, 12, 8),
        bgcolor=BACKGROUND,
    )

    # Barre d'onglets (dossiers ouverts) — motif Container cliquable + ink,
    # comme rail_tabs (_select_surface plus bas) : pas de ft.Tabs, jamais
    # utilisé ailleurs dans le dépôt.
    folder_tabs_row = ft.Row([], spacing=4, scroll=ft.ScrollMode.AUTO)
    folder_tabs_bar = ft.Container(
        content=folder_tabs_row, padding=ft.Padding(12, 6, 12, 0),
        bgcolor=BACKGROUND)
    _render_folder_tabs()

    files_surface = ft.Column([
        files_header,
        folder_tabs_bar,
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
        # Largeur de gouttière élargie (était 64) + ligne verticale
        # séparant les numéros de ligne du texte : GutterStyle n'expose
        # pas de bordure propre, donc superposée via un Stack, positionnée
        # pile à la largeur de la gouttière (retour user).
        _NOTES_GUTTER_WIDTH = 96
        notes_field = fce.CodeEditor(
            text_style=ft.TextStyle(font_family="monospace", size=state["font_size"]),
            language=getattr(fce.CodeLanguage, CONSTANTS.NOTEPAD_DEFAULT_LANGUAGE),
            code_theme=fce.CodeTheme.ATOM_ONE_DARK,
            gutter_style=fce.GutterStyle(
                width=_NOTES_GUTTER_WIDTH, background_color=BACKGROUND),
            expand=True,
        )
        notes_editor_content = ft.Stack([
            notes_field,
            ft.Container(width=2, bgcolor=LIGHT_GREY,
                        left=_NOTES_GUTTER_WIDTH, top=0, bottom=0),
        ], expand=True)
    else:
        notes_field = ft.TextField(
            multiline=True, expand=True, min_lines=4,
            text_style=ft.TextStyle(font_family="monospace", size=state["font_size"]),
            color=WHITE, border_color=ft.Colors.TRANSPARENT, border_radius=6,
            bgcolor=DARK, filled=True,
            hint_text="Écrivez vos notes ici…",
            hint_style=ft.TextStyle(color=LIGHT_GREY, italic=True),
        )
        notes_editor_content = notes_field
    notes_title = ft.Text("Bloc-notes", size=CONSTANTS.TEXT_LG, color=WHITE,
                          weight=ft.FontWeight.W_500, expand=True, no_wrap=True)
    notes_preview = ft.Markdown(
        "", selectable=True, extension_set=ft.MarkdownExtensionSet.GITHUB_WEB,
        code_theme=ft.MarkdownCodeTheme.ATOM_ONE_DARK, expand=True,
        auto_follow_links=True,
        md_style_sheet=ft.MarkdownStyleSheet(
            p_text_style=ft.TextStyle(size=state["font_size"])))
    notes_preview_scroll = ft.ListView(controls=[notes_preview], expand=True)
    # Conteneur unique dont on échange le `.content` (édition <-> aperçu),
    # comme `files_body` plus haut : deux enfants Column avec expand=True
    # se partagent l'espace 50/50 même quand l'un est invisible (Flet
    # conserve la part de flex d'un enfant caché) — d'où le bloc-notes qui
    # ne prenait que la moitié inférieure en aperçu Markdown.
    notes_body = ft.Container(
        content=notes_editor_content, expand=True, padding=8)
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
            notes_body.content = notes_editor_content
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
            notes_body.content = notes_editor_content
            notes_preview_btn.icon = ft.Icons.VISIBILITY
            notes_preview_btn.tooltip = "Prévisualiser en Markdown"
        page.update()

    def _notes_clear(event=None):
        notes_field.value = ""
        if notes_is_preview["value"]:
            notes_is_preview["value"] = False
            notes_body.content = notes_editor_content
            notes_preview_btn.icon = ft.Icons.VISIBILITY
            notes_preview_btn.tooltip = "Prévisualiser en Markdown"
        _notes_save()
        page.update()

    notes_home_btn = ft.IconButton(
        ft.Icons.HOME, icon_color=VIOLET, icon_size=CONSTANTS.ICON_SM,
        tooltip="Charger la note par défaut (.notes.md)",
        on_click=_notes_go_home)
    notes_preview_btn = ft.IconButton(
        ft.Icons.VISIBILITY, icon_color=WHITE, icon_size=CONSTANTS.ICON_SM,
        tooltip="Prévisualiser en Markdown", on_click=_notes_toggle_preview)

    notes_surface = ft.Column([
        ft.Container(
            content=ft.Row([
                notes_title,
                notes_home_btn,
                ft.IconButton(ft.Icons.SAVE_OUTLINED, icon_color=ICON_ACTION,
                             icon_size=CONSTANTS.ICON_SM, tooltip="Enregistrer", on_click=_notes_save),
                notes_preview_btn,
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
    # Dernières images jointes au chat (b64) : source de repli pour
    # edit_image quand le modèle l'appelle sur une image collée/uploadée
    # dans la conversation plutôt que sur un fichier du dossier ouvert — le
    # modèle ne connaît alors aucun nom de fichier réel (les bytes envoyés
    # via user_message["images"] ne portent aucune métadonnée de nom) et en
    # invente un plausible (ex. "input_file_1.png"), qui ne correspond à
    # rien sur disque : sans ce repli, edit_image tombait silencieusement
    # en génération pure (aucune image source), produisant un résultat sans
    # rapport avec la photo jointe (retour user).
    ai_last_attached_images = {"b64": []}
    ai_send_original_images = {"value": CONSTANTS.AI_IMAGE_ATTACH_DEFAULT_ORIGINAL}
    ai_tts_enabled = {"value": CONSTANTS.AI_VOICE_TTS_ENABLED}
    ai_tts_stop_event = {"event": None}
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
    # Qualité des images générées/éditées via generate_image/edit_image —
    # 1K par défaut (coût/temps), à monter à 4K pour une image destinée à
    # l'impression (cf. Data/ai_ops.py::run_outpaint pour le même principe).
    ai_image_quality_dropdown = ft.Dropdown(
        value="1K",
        options=[ft.dropdown.Option(q) for q in ("1K", "2K", "4K")],
        tooltip="Qualité des images générées/éditées par l'IA (1K/2K/4K)",
        text_size=CONSTANTS.TEXT_SM, dense=True, color=WHITE, bgcolor=DARK, border_color=GREY,
        content_padding=ft.Padding.symmetric(horizontal=6, vertical=0), width=90)
    # Modèle Nano Banana 2 pour generate_image/edit_image : "full" par
    # défaut (qualité/cohérence), "Lite" en option pour aller plus vite.
    ai_image_model_dropdown = ft.Dropdown(
        value="gemini-3.1-flash-image",
        options=[
            ft.dropdown.Option("gemini-3.1-flash-image", text="NB2"),
            ft.dropdown.Option("gemini-3.1-flash-lite-image",
                               text="NB2 Lite"),
        ],
        tooltip="Modèle Nano Banana 2 utilisé pour générer/éditer des images",
        text_size=CONSTANTS.TEXT_SM, dense=True, color=WHITE, bgcolor=DARK, border_color=GREY,
        content_padding=ft.Padding.symmetric(horizontal=6, vertical=0), width=150)
    ai_status_text = ft.Text("", color=LIGHT_GREY, size=CONSTANTS.TEXT_SM, italic=True, max_lines=1,
                             overflow=ft.TextOverflow.ELLIPSIS, expand=True)
    ai_progress_bar = ft.ProgressBar(value=None, visible=False, color=BLUE, height=2)

    # Contrôles réellement touchés par un tour de réponse IA. page.update()
    # SANS argument repousse tout l'arbre de la page (les 4 surfaces, la
    # grille de fichiers et ses centaines de vignettes, le terminal) — or
    # _ai_refresh est appelé plusieurs fois par seconde pendant un
    # streaming. On ne pousse donc que ces contrôles-là, comme
    # _clear_selection_visuals le fait déjà avec page.update(*touched).
    # Complété plus bas avec les boutons d'envoi (créés après) ; tant que
    # la liste est vide, page.update(*[]) retombe sur la mise à jour
    # complète, ce qui reste correct au démarrage.
    _ai_refresh_targets = [ai_chat_view, ai_status_text, ai_progress_bar]

    async def _ai_update_and_scroll():
        try:
            page.update(*_ai_refresh_targets)
            await asyncio.sleep(0)
            await ai_chat_view.scroll_to(offset=-1)
        except Exception:
            pass

    def _ai_append_bubble_row(row):
        """Empile une bulle en bornant l'historique affiché.

        Sans plafond, une journée de travail accumule des centaines de
        ft.Markdown et de ft.Image gardés en mémoire, tous réévalués à
        chaque rafraîchissement. Même principe que le terminal intégré
        (HUB_TERMINAL_MAX_LINES) : seules les dernières bulles servent, la
        conversation complète reste dans ai_conversation et dans le
        fichier d'historique.
        """
        ai_chat_view.controls.append(row)
        while len(ai_chat_view.controls) > CONSTANTS.HUB_AI_MAX_BUBBLES:
            ai_chat_view.controls.pop(0)
        # ai_text_refs (utilisé par le réglage de taille de police) pointe
        # sur les Text/Markdown des bulles : le borner aussi, sinon il
        # garde des références sur des contrôles retirés de l'affichage.
        while len(ai_text_refs) > CONSTANTS.HUB_AI_MAX_BUBBLES:
            ai_text_refs.pop(0)

    def _ai_refresh():
        # Depuis un thread (streaming IA en arrière-plan), page.update() direct
        # ne se propage pas de façon fiable en Flet 0.85 — il faut repasser par
        # la boucle asyncio de la page via page.run_task (idiome SidePanel).
        # Si la fenêtre se ferme pendant qu'une réponse tourne encore en
        # arrière-plan, page.run_task lève RuntimeError("session détruite")
        # de façon SYNCHRONE ici (avant même que _ai_update_and_scroll ne
        # démarre, donc son propre try/except ne l'attrape jamais) — sans ce
        # garde, l'exception remonte dans le handler d'erreur ET le finally
        # de _run, qui appellent tous les deux _ai_refresh(), et fait planter
        # le thread IA (retour user : crash à la fermeture de l'app).
        try:
            page.run_task(_ai_update_and_scroll)
        except Exception:
            pass

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

    def _speak_bubble(text, force_chunked=False):
        """Lit un texte via Gemini TTS.

        force_chunked=True force la lecture fidèle du texte affiché (sans mode Live).
        """
        def _set_tts_feedback(status_text, show_progress):
            ai_status_text.value = status_text
            ai_progress_bar.visible = show_progress

            async def _apply_ui_update():
                try:
                    page.update()
                except Exception:
                    try:
                        ai_status_text.update()
                        ai_progress_bar.update()
                    except Exception:
                        pass

            try:
                page.run_task(_apply_ui_update)
            except Exception:
                try:
                    page.update()
                except Exception:
                    pass

        # Arrêter le TTS précédent s'il tourne encore
        if ai_tts_stop_event["event"] is not None:
            ai_tts_stop_event["event"].set()
        stop_event = threading.Event()
        ai_tts_stop_event["event"] = stop_event
        selected_tts_mode = "chunked" if force_chunked else CONSTANTS.AI_VOICE_TTS_MODE
        if selected_tts_mode == "live":
            _set_tts_feedback(f"🔊 Live — {CONSTANTS.AI_VOICE_TTS_VOICE}…", True)
        else:
            _set_tts_feedback(f"🔊 Préparation de la voix — {CONSTANTS.AI_VOICE_TTS_VOICE}…", True)
        try:
            if selected_tts_mode == "live":
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
                # Streaming audio réel (une seule requête, lecture dès le
                # premier chunk) : plus rapide qu'un appel bloquant pour
                # toutes les longueurs de texte, donc plus besoin de
                # distinguer "court" (one-shot) et "long" (pipeline).
                _gemini_tts_stream(
                    text,
                    voice_name=CONSTANTS.AI_VOICE_TTS_VOICE,
                    tts_model=CONSTANTS.AI_VOICE_TTS_MODEL,
                    sample_rate=CONSTANTS.AI_VOICE_TTS_SAMPLE_RATE,
                    language_code=CONSTANTS.AI_VOICE_TTS_LANGUAGE,
                    stop_event=stop_event,
                    preroll_ms=CONSTANTS.AI_VOICE_TTS_PREROLL_MS,
                )
        except Exception as tts_exc:
            _set_tts_feedback(f"[❌ TTS] {tts_exc}", False)
            return
        finally:
            is_current_tts = ai_tts_stop_event["event"] is stop_event
            if is_current_tts:
                ai_tts_stop_event["event"] = None
                _set_tts_feedback("", False)
            # Referme toujours l'étape "lecture vocale" démarrée par
            # l'appelant (_busy_start appelé avant de lancer le thread qui
            # exécute cette fonction — jamais ici, pour éviter une fenêtre
            # où le compteur retombe à 0 entre le lancement du thread et
            # son premier tour de boucle).
            _busy_end()

    def _toggle_tts(event=None):
        """Active ou désactive la lecture vocale des réponses IA."""
        ai_tts_enabled["value"] = not ai_tts_enabled["value"]
        enabled = ai_tts_enabled["value"]
        ai_speaker_button.icon = ft.Icons.VOLUME_UP if enabled else ft.Icons.VOLUME_OFF
        ai_speaker_button.icon_color = BLUE if enabled else LIGHT_GREY
        ai_speaker_button.tooltip = ("Désactiver la lecture vocale" if enabled
                                     else "Activer la lecture vocale")
        try:
            ai_speaker_button.update()
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
            bubble_text = ft.Text(text, size=state["font_size"], color=DARK,
                                  font_family="monospace", selectable=True)
            bubble = ft.Container(
                content=bubble_text, bgcolor=BLUE, padding=ft.Padding(9, 7, 9, 7),
                border_radius=ft.BorderRadius(top_left=13, top_right=13,
                                              bottom_left=13, bottom_right=4),
                expand=8)
            row = ft.Row([ft.Container(expand=2), bubble],
                        alignment=ft.MainAxisAlignment.END)
        elif is_think:
            bubble_text = ft.Text(f"💭 {text}", size=state["font_size"] - 1,
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
                code_theme=ft.MarkdownCodeTheme.ATOM_ONE_DARK, expand=True,
                auto_follow_links=True,
                md_style_sheet=ft.MarkdownStyleSheet(
                    p_text_style=ft.TextStyle(size=state["font_size"])))
            bubble = ft.Container(
                content=bubble_text, bgcolor=GREY, padding=ft.Padding(9, 7, 9, 7),
                border_radius=ft.BorderRadius(top_left=13, top_right=13,
                                              bottom_left=4, bottom_right=13),
                expand=8)
            raw_text = text

            def _speak_current_bubble_text(text_control, fallback_text):
                current_text = getattr(text_control, "value", "")
                if not isinstance(current_text, str) or not current_text.strip():
                    current_text = fallback_text
                _speak_bubble(current_text, force_chunked=True)

            def _on_speak_click(e, text_control=bubble_text, fallback_text=raw_text):
                # Incrémenté ici (thread UI, synchrone au clic), pas dans
                # _speak_bubble : même raison que pour la lecture auto —
                # garantir que le compteur est déjà à jour avant que le
                # thread spawné n'ait eu la main.
                _busy_start()
                threading.Thread(target=_speak_current_bubble_text,
                                 args=(text_control, fallback_text),
                                 daemon=True).start()

            speak_btn = ft.IconButton(
                icon=ft.Icons.VOLUME_UP, icon_color=LIGHT_GREY, icon_size=14,
                tooltip="Lire cette réponse (lecture fidèle)",
                on_click=_on_speak_click,
            )
            row = ft.Row([bubble, speak_btn, ft.Container(expand=2)],
                        alignment=ft.MainAxisAlignment.START)
        ai_text_refs.append((bubble_text, -1 if is_think else 0))
        _ai_append_bubble_row(row)
        _ai_refresh()
        return bubble_text

    def _ai_stop(event=None):
        ai_streaming["value"] = False

    def _ai_tool_paint():
        # ui.paint() est le repaint GLOBAL du contrat dispatch_folder_tool
        # (ai_tools.py) : appelé après une opération fichier, il doit
        # repeindre la grille de fichiers, pas seulement le chat. Il reste
        # donc sur un page.update() complet — contrairement à _ai_refresh,
        # ciblé parce qu'il tourne plusieurs fois par seconde en streaming.
        # Une fois par appel d'outil : le coût est sans importance ici.
        async def _repaint():
            try:
                page.update()
            except Exception:
                pass
        try:
            page.run_task(_repaint)
        except Exception:
            pass

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
        _ai_append_bubble_row(
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
        _ai_append_bubble_row(
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

        fired = {"done": False}

        def _confirm(e=None):
            if fired["done"]:
                return
            fired["done"] = True
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
            await _focus_dialog_field(password_field)
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
            if src_bytes is None and ai_last_attached_images["b64"]:
                # Le nom donné par le modèle ne correspond à aucun fichier du
                # dossier ouvert — cas typique d'une image collée/uploadée
                # directement dans le chat (jamais présente sur disque sous
                # ce nom, le modèle invente alors un nom plausible du style
                # "input_file_1.png"). On retombe sur la dernière image
                # réellement jointe à la conversation plutôt que de générer
                # sans aucune image source (retour user : sans ça, edit_image
                # produisait silencieusement un résultat sans rapport avec
                # la photo jointe).
                try:
                    src_bytes = base64.b64decode(ai_last_attached_images["b64"][-1])
                    # Consommée : évite qu'un futur edit_image sur un nom de
                    # fichier différent (mais introuvable, ex. faute de
                    # frappe) ne retombe silencieusement sur cette même
                    # image, périmée, plusieurs tours plus tard.
                    ai_last_attached_images["b64"] = []
                except Exception:
                    src_bytes = None
            if src_bytes is None:
                return (
                    f"[Erreur] Fichier source introuvable : "
                    f"{src_name or '(non fourni)'}. Vérifie le nom exact "
                    "via list_folder_contents, ou demande à l'utilisateur de "
                    "joindre l'image dans le chat.")
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
                aspect_ratio=aspect,
                resolution=ai_image_quality_dropdown.value or "1K",
                model=ai_image_model_dropdown.value)
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
        # Le statut est posé AVANT la bulle : _ai_add_bubble se termine
        # déjà par _ai_refresh(), inutile d'en rajouter un.
        _ai_add_bubble("assistant", "📸 Capture d'écran")
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
            # Idem : le refresh est déjà fait en fin de _ai_add_bubble.
            _ai_add_bubble("assistant", f"🔌 Outil MCP : {fn_name}")
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
        saved = _load_json(_ai_history_file, None)
        if saved is None:
            return
        messages = saved.get("messages", []) if isinstance(saved, dict) else saved
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
        ai_text_refs.clear()
        ai_status_text.value = ""
        # Renommé en .bak plutôt que supprimé : ce bouton est une corbeille
        # rouge posée à quelques pixels de « transférer vers le bloc-notes »,
        # et l'effacement était instantané et définitif. Le renommage rend
        # le geste rattrapable sans ajouter un dialogue de confirmation sur
        # une action par ailleurs fréquente et volontaire.
        try:
            if os.path.isfile(_ai_history_file):
                os.replace(_ai_history_file, _ai_history_file + ".bak")
                _log_to_terminal(
                    "[OK] Conversation effacée — récupérable dans "
                    f"{os.path.basename(_ai_history_file)}.bak", GREEN)
        except OSError as exc:
            _log_to_terminal(f"[ERREUR] Effacement conversation : {exc}", RED)
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

    def _ai_attach_image(path, use_original=None):
        if any(e["path"] == path for e in ai_pending_images):
            return
        if use_original is None:
            use_original = ai_send_original_images["value"]
        try:
            if use_original:
                with open(path, "rb") as f:
                    b64_data = base64.b64encode(f.read()).decode("utf-8")
            else:
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
                _ai_attach_image(
                    p, use_original=CONSTANTS.AI_IMAGE_ATTACH_SELECTED_ORIGINAL)
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
                # Étape "enregistrement" : reste ouvert/en cours jusqu'à ce
                # que la transcription se termine (_busy_end appelé plus bas
                # dans _mic_stop/_apply, jamais ici — sinon la barre
                # clignoterait entre enregistrement et transcription).
                _busy_start()
                _log_to_terminal("🎤 Parlez maintenant… (recliquer pour arrêter)")
                page.update()
            page.run_task(_flip)

        try:
            recorder = _MicRecorder(sample_rate=CONSTANTS.AI_VOICE_STT_SAMPLE_RATE)
            recorder.start(on_ready=_on_ready)
        except Exception as exc:
            ai_status_text.value = f"Micro indisponible : {exc}"
            _log_to_terminal(f"Micro indisponible : {exc}", RED)
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
        # Toujours l'étape "en cours" (enregistrement -> transcription,
        # même période _busy_start/_busy_end) : pas de _busy_end ici.
        ai_status_text.value = "Transcription en cours…"
        _log_to_terminal("Transcription en cours…")
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
                    _log_to_terminal(f"🎤 « {text} »", BLUE)
                    if auto_send and not ai_streaming["value"]:
                        # Bouton PTT physique (F15) : on a parlé pour poser
                        # la question, donc on veut la réponse parlée aussi
                        # — active la lecture auto si elle ne l'était pas
                        # déjà (retour user : désactivée par défaut, oubliée
                        # après un relance de l'app).
                        if not ai_tts_enabled["value"]:
                            ai_tts_enabled["value"] = True
                            ai_speaker_button.icon = ft.Icons.VOLUME_UP
                            ai_speaker_button.icon_color = BLUE
                            ai_speaker_button.tooltip = "Désactiver la lecture vocale"
                        ai_input_field.value = ""
                        # .update() sur un contrôle précis lève une erreur
                        # s'il n'est pas actuellement monté (onglet IA pas
                        # affiché — le rail change center.content, l'ancien
                        # onglet est détaché) : sans ce garde, l'exception
                        # avortait _apply() AVANT _send_ai_message, donc le
                        # PTT physique (F15) ne faisait plus rien en dehors
                        # de l'onglet IA (retour user).
                        try:
                            ai_input_field.update()
                        except Exception:
                            pass
                        # Fin de l'étape enregistrement/transcription — la
                        # suivante (attente de réponse) est démarrée par
                        # _send_ai_message elle-même juste après, donc le
                        # terminal reste ouvert en continu (retour user).
                        _busy_end()
                        _send_ai_message(combined)
                    else:
                        ai_input_field.value = combined
                        try:
                            ai_input_field.update()
                        except Exception:
                            pass
                        try:
                            await ai_input_field.focus()
                        except Exception:
                            pass
                        _busy_end()
                else:
                    ai_status_text.value = "Aucun texte reconnu"
                    _log_to_terminal("Aucun texte reconnu", RED)
                    _busy_end()
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
        if not CONSTANTS.AI_VOICE_PTT_ENABLED:
            return
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

    def _send_ai_message(text):
        if ai_streaming["value"] or (not text.strip() and not ai_pending_images
                                     and not ai_pending_files):
            return
        ai_streaming["value"] = True
        ai_send_button.disabled = True
        ai_vasy_button.disabled = True
        ai_stop_button.visible = True
        ai_status_text.value = "⏳ En cours…"
        ai_progress_bar.visible = True
        _busy_start()
        # Ne doit jamais empêcher l'envoi (ex: onglet IA pas affiché) —
        # ai_streaming est déjà passé à True ci-dessus, un plantage ici
        # bloquerait tout définitivement (le garde en tête de fonction
        # empêche tout nouvel essai tant que la valeur reste bloquée).
        try:
            page.update()
        except Exception:
            pass

        images_b64 = [e["b64"] for e in ai_pending_images]
        images_paths = [e["path"] for e in ai_pending_images]
        files_to_inject = list(ai_pending_files)
        if images_b64:
            ai_last_attached_images["b64"] = images_b64
        ai_pending_images.clear()
        ai_pending_files.clear()
        _ai_refresh_attach_row()

        content = text
        if images_paths:
            # Le modèle ne voit sinon QUE les octets (user_message["images"])
            # sans aucun nom de fichier : pour éditer l'image jointe via
            # edit_image, il doit connaître le nom réel du fichier dans le
            # dossier ouvert, sinon il en invente un plausible qui ne
            # correspond à rien sur disque (retour user, cf. incident chat
            # gris → armure Anubis générée sans rapport avec la photo).
            names = ", ".join(os.path.basename(p) for p in images_paths)
            note = f"[Image(s) jointe(s) à ce message : {names}]"
            content = f"{content}\n\n{note}" if content else note
        user_message = {"role": "user", "content": content}
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

                for _round in range(CONSTANTS.AI_MAX_TOOL_ROUNDS):
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
                        if streamed:
                            preview = streamed if len(streamed) <= 120 else streamed[:117] + "…"
                            _log_to_terminal(f"🤖 {preview}", GREEN)
                        if streamed and ai_tts_enabled["value"]:
                            # Incrémenté ICI (thread appelant), pas dans
                            # _speak_bubble : le thread TTS spawné juste
                            # après peut démarrer après le _busy_end() du
                            # finally ci-dessous (ordonnancement non
                            # garanti) — sans ce compte pris tout de suite,
                            # le terminal se refermerait puis se rouvrirait
                            # (retour user : voulu en continu).
                            _busy_start()
                            threading.Thread(target=_speak_bubble,
                                             args=(streamed,), daemon=True).start()
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
                _log_to_terminal(f"[Erreur] {exc}", RED)
            finally:
                ai_streaming["value"] = False
                ai_send_button.disabled = False
                ai_vasy_button.disabled = False
                ai_stop_button.visible = False
                ai_status_text.value = ""
                ai_progress_bar.visible = False
                _ai_save_history_now()
                _ai_refresh()
                # Referme l'étape "réponse en cours" démarrée dans
                # _send_ai_message — si une lecture TTS vient d'être
                # lancée juste au-dessus, son propre _busy_start (pris
                # avant même ce finally) maintient le compteur > 0, donc
                # le terminal reste ouvert sans interruption jusqu'à la
                # fin de l'audio.
                _busy_end()

        threading.Thread(target=_run, daemon=True).start()

    def _ai_submit(event=None):
        if _mic_state["active"]:
            # Envoyer pendant un enregistrement en cours (clic sur Envoyer
            # au lieu du bouton micro) : on n'envoie pas le texte actuel du
            # champ (vide ou périmé), on arrête l'enregistrement et on
            # enchaîne transcription + envoi auto, comme en mode PTT.
            _mic_stop(auto_send=True)
            return
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

    def _ai_vasy(event=None):
        if ai_streaming["value"]:
            return
        _history_add("ai", "vas-y")
        _send_ai_message("vas-y")

    ai_vasy_button = ft.IconButton(
        ft.Icons.PLAY_CIRCLE_FILL, icon_color=GREEN,
        tooltip="Vas-y (confirme et lance l'action en attente, sans taper de texte)",
        on_click=_ai_vasy)
    ai_stop_button = ft.IconButton(ft.Icons.STOP_CIRCLE, icon_color=RED,
                                   tooltip="Arrêter", visible=False, on_click=_ai_stop)
    # Ces trois-là changent d'état au début et à la fin d'une réponse
    # (désactivés pendant, bouton Arrêter visible) : sans eux dans la
    # liste, le rafraîchissement ciblé les laisserait figés.
    _ai_refresh_targets.extend(
        [ai_send_button, ai_vasy_button, ai_stop_button])
    ai_mic_button = ft.IconButton(
        ft.Icons.MIC_NONE, icon_color=GREY,
        tooltip="Cliquer pour dicter (Gemini)", on_click=_mic_toggle)
    ai_clear_button = ft.IconButton(
        ft.Icons.DELETE_OUTLINE, icon_color=RED, icon_size=CONSTANTS.ICON_SM,
        tooltip="Effacer la conversation", on_click=_ai_clear_conversation)
    ai_speaker_button = ft.IconButton(
        icon=ft.Icons.VOLUME_UP if ai_tts_enabled["value"] else ft.Icons.VOLUME_OFF,
        icon_color=BLUE if ai_tts_enabled["value"] else LIGHT_GREY,
        icon_size=CONSTANTS.ICON_SM,
        tooltip=("Désactiver la lecture vocale" if ai_tts_enabled["value"]
                 else "Activer la lecture vocale"),
        visible=CONSTANTS.AI_VOICE_TTS_BTN_VISIBLE,
        on_click=_toggle_tts)
    ai_copy_button = ft.IconButton(
        ft.Icons.COPY_ALL, icon_color=BLUE, icon_size=CONSTANTS.ICON_SM,
        tooltip="Copier la conversation IA",
        on_click=lambda e: _export_ai_conversation(to_notepad=False))
    ai_to_notepad_button = ft.IconButton(
        ft.Icons.SEND_TO_MOBILE, icon_color=VIOLET, icon_size=CONSTANTS.ICON_SM,
        tooltip="Transférer la conversation vers le bloc-notes",
        on_click=lambda e: _export_ai_conversation(to_notepad=True))

    ai_image_mode_label = ft.Text(
        "REEL" if ai_send_original_images["value"] else "1024",
        color=GREEN if ai_send_original_images["value"] else BLUE,
        size=CONSTANTS.TEXT_SM - 3, weight=ft.FontWeight.BOLD)

    def _toggle_ai_image_size_mode(event=None):
        ai_send_original_images["value"] = not ai_send_original_images["value"]
        use_original = ai_send_original_images["value"]
        ai_image_size_button.icon_color = GREEN if use_original else BLUE
        ai_image_mode_label.value = "REEL" if use_original else "1024"
        ai_image_mode_label.color = GREEN if use_original else BLUE
        ai_image_size_button.tooltip = (
            "Mode images IA en taille réelle (fichier original) — "
            "affecte uniquement les nouveaux fichiers joints"
            if use_original else
            "Mode images IA optimisé (1024px max) — "
            "affecte uniquement les nouveaux fichiers joints")
        page.update()

    ai_image_size_button = ft.IconButton(
        ft.Icons.IMAGE,
        icon_color=GREEN if ai_send_original_images["value"] else BLUE,
        icon_size=CONSTANTS.ICON_SM,
        tooltip=(
            "Mode images IA en taille réelle (fichier original) — "
            "affecte uniquement les nouveaux fichiers joints"
            if ai_send_original_images["value"] else
            "Mode images IA optimisé (1024px max) — "
            "affecte uniquement les nouveaux fichiers joints"),
        on_click=_toggle_ai_image_size_mode)

    # Le bouton et son mode (« REEL »/« 1024 ») dans une seule pastille :
    # séparés, le texte flottait dans la barre comme un élément autonome
    # sans lien visible avec le bouton qu'il décrit.
    ai_image_size_group = ft.Container(
        content=ft.Row([ai_image_size_button, ai_image_mode_label],
                       spacing=0, tight=True),
        bgcolor=GREY, border_radius=6,
        padding=ft.Padding(0, 0, 8, 0))
    # Pas d'infobulle sur le conteneur : celle du bouton est déjà précise
    # et suit l'état (réel / 1024), une seconde par-dessus la masquerait.

    def _ai_header_separator():
        return ft.Container(ft.VerticalDivider(color=LIGHT_GREY),
                            height=CONSTANTS.HUB_TOOLBAR_H)

    ia_surface = ft.Column([
        ft.Container(
            # Trois groupes séparés, dans l'ordre d'usage : ce qu'on règle
            # (modèle, qualité, taille d'image) — ce qu'on fait de la
            # réponse (voix, copie, bloc-notes) — et l'effacement, isolé
            # tout à droite derrière son séparateur : la corbeille rouge
            # était collée au bouton « transférer vers le bloc-notes ».
            content=ft.Row([
                ft.Text("Assistant IA", size=CONSTANTS.TEXT_LG, color=WHITE,
                        weight=ft.FontWeight.W_500, expand=True),
                ai_model_dropdown,
                _ai_header_separator(),
                ai_image_model_dropdown,
                ai_image_quality_dropdown,
                ai_image_size_group,
                _ai_header_separator(),
                ai_speaker_button,
                ai_copy_button,
                ai_to_notepad_button,
                _ai_header_separator(),
                ai_clear_button,
            ], spacing=CONSTANTS.SPACE_SM),
            padding=ft.Padding(8, 8, 8, 0), bgcolor=BACKGROUND),
        ft.Divider(height=1, color=GREY),
        ft.Container(content=ai_chat_view, expand=True, padding=8),
        ai_progress_bar,
        ft.Container(content=ai_attach_row, padding=ft.Padding(8, 4, 8, 0)),
        ft.Container(
            content=ft.Row([ai_input_field, ai_vasy_button, ai_mic_button,
                            ai_send_button, ai_stop_button], spacing=4),
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
        # Récap par format (retour user : besoin du nombre de photos à
        # côté du prix par taille, pour reporter facilement dans le
        # logiciel de caisse — le décompte global (grand_total) reste
        # affiché en plus, pas à la place).
        format_price_totals: dict[str, float] = {}
        for (path, fmt), price in prices.items():
            format_price_totals[fmt] = round(
                format_price_totals.get(fmt, 0.0) + price, 2)
        manifest.append("")
        for fmt in sorted(format_totals):
            manifest.append(
                f"{fmt} : {format_totals[fmt]} photo(s) = "
                f"{format_price_totals[fmt]:.2f} €")
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
    #  l'app (ex. fiches PrestaShop). Format : liste d'objets dict, colonnes
    #  libres (ex. {"nom": str, "description": str} ou tout autre schéma) ;
    #  les colonnes affichées s'adaptent aux clés trouvées dans le fichier.
    #  L'IA y écrit avec les outils fichiers génériques (create_file/
    #  edit_file, pas d'outil dédié) ; le callback refresh() du chat (cf.
    #  tool_ui plus haut) recharge cette surface après chaque appel d'outil,
    #  comme le pubsub "refresh" de SidePanel.
    # ═════════════════════════════════════════════════════════════════════
    _liste_file = {"path": os.path.join(_APP_DIR, ".liste.json")}
    liste_entries = []
    _LISTE_DEFAULT_COLUMNS = ["nom", "description"]

    def _liste_columns():
        # ponytail: colonnes = union ordonnée des clés rencontrées ;
        # défaut nom/description si le fichier est vide (nouveau fichier).
        columns = []
        for entry in liste_entries:
            for key in entry:
                if key not in columns:
                    columns.append(key)
        return columns or list(_LISTE_DEFAULT_COLUMNS)

    _liste_load_error = {"msg": None}

    def _liste_load():
        # Erreur explicite plutôt qu'un "Liste vide" muet en cas de JSON
        # invalide ou de mauvais format (retour user : un fichier .json
        # cliqué dans Fichiers pouvait sembler vide sans qu'on sache si
        # c'est le fichier qui est vide ou le format qui ne convient pas).
        liste_entries.clear()
        _liste_load_error["msg"] = None
        path = _liste_file["path"]
        if not os.path.exists(path):
            return
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
        except Exception as exc:
            _liste_load_error["msg"] = f"JSON invalide : {exc}"
            return
        if not isinstance(data, list):
            _liste_load_error["msg"] = (
                "Ce fichier ne contient pas une liste d'entrées "
                f"(racine : {type(data).__name__}).")
            return
        for item in data:
            if isinstance(item, dict):
                liste_entries.append({k: str(v) for k, v in item.items()})
            else:
                # ponytail: tolère une liste de valeurs simples (pas
                # seulement des objets {"nom":...}) plutôt que de la
                # faire disparaître silencieusement.
                liste_entries.append({"nom": str(item), "description": ""})

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
        def _on_confirm():
            if 0 <= index < len(liste_entries):
                liste_entries.pop(index)
                _liste_save()
                _liste_render()

        ui_helpers.confirm_dialog(
            page, "Supprimer cette entrée ?", _on_confirm, _KEYPAD_COLORS,
            confirm_label="Supprimer")

    def _liste_edit(index=None):
        is_new = index is None
        columns = _liste_columns()
        current = liste_entries[index] if not is_new else {}
        fields = [
            ft.TextField(
                label=col, value=current.get(col, ""),
                autofocus=(i == 0), width=320,
                multiline=(i > 0), min_lines=1, max_lines=5,
                bgcolor=DARK, border_color=GREY, color=WHITE)
            for i, col in enumerate(columns)
        ]

        def _cancel(event):
            dlg.open = False
            page.update()

        def _confirm(event):
            first = (fields[0].value or "").strip()
            if not first:
                fields[0].error_text = "Requis"
                page.update()
                return
            entry = {col: (f.value or "").strip()
                     for col, f in zip(columns, fields)}
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
            content=ft.Column(fields, spacing=10, tight=True,
                              scroll=ft.ScrollMode.AUTO),
            actions=[ft.TextButton("Annuler", on_click=_cancel),
                     ft.TextButton("Enregistrer", on_click=_confirm)],
        )
        page.overlay.append(dlg)
        dlg.open = True
        page.update()
        page.run_task(_focus_dialog_field, fields[0])

    _LISTE_ACTIONS_WIDTH = 2 * (CONSTANTS.ICON_SM + 16)  # aligne l'en-tête sur les 2 IconButton

    def _liste_row(index, entry):
        columns = _liste_columns()
        cells = []
        for col in columns:
            value = entry.get(col, "")
            cells.append(ft.Container(
                content=ft.Text(value or "—", size=CONSTANTS.TEXT_SM,
                                color=WHITE, max_lines=2,
                                overflow=ft.TextOverflow.ELLIPSIS),
                tooltip=f"Copier {col} : {value}", expand=True, ink=True,
                on_click=lambda e, t=value: _liste_copy(t)))
        return ft.Container(
            content=ft.Row([
                *cells,
                ft.IconButton(ft.Icons.EDIT_OUTLINED, icon_size=CONSTANTS.ICON_SM, icon_color=GREY,
                             on_click=lambda e, i=index: _liste_edit(i)),
                ft.IconButton(ft.Icons.DELETE_OUTLINE, icon_size=CONSTANTS.ICON_SM, icon_color=RED,
                             on_click=lambda e, i=index: _liste_delete(i)),
            ], spacing=8, vertical_alignment=ft.CrossAxisAlignment.CENTER),
            padding=ft.Padding(10, 8, 10, 8), bgcolor=GREY, border_radius=6)

    def _liste_header():
        columns = _liste_columns()
        return ft.Row([
            *[ft.Container(
                content=ft.Text(col.upper(), size=CONSTANTS.TEXT_SM, color=WHITE,
                                weight=ft.FontWeight.W_600),
                expand=True) for col in columns],
            ft.Container(width=_LISTE_ACTIONS_WIDTH),
        ], spacing=8)

    liste_header_row = ft.Container(content=_liste_header(),
                                    padding=ft.Padding(10, 0, 10, 4))
    liste_list_view = ft.ListView(expand=True, spacing=4, padding=8)
    liste_path_text = ft.Text(os.path.basename(_liste_file["path"]),
                              size=CONSTANTS.TEXT_SM, color=WHITE,
                              no_wrap=True, expand=True)
    liste_search = {"value": ""}

    def _liste_matches_search(entry, query):
        return any(query in str(v).lower() for v in entry.values())

    def _liste_set_search(value):
        liste_search["value"] = (value or "").strip().lower()
        _liste_render()

    def _liste_clear_search(event=None):
        liste_search_field.value = ""
        liste_search["value"] = ""
        _liste_render()

    liste_search_field = ft.TextField(
        hint_text="Rechercher dans toutes les colonnes…",
        on_change=lambda e: _liste_set_search(e.control.value),
        on_submit=_liste_clear_search,
        height=45, bgcolor=DARK, border_color=BLUE,
        color=WHITE, text_size=CONSTANTS.TEXT_SM,
        content_padding=ft.Padding(8, 2, 8, 2),
        prefix_icon=ft.Icons.SEARCH, expand=True,
        on_focus=_focus_search("liste_search"), on_blur=_blur_search,
    )
    liste_search_close_btn = ft.IconButton(
        ft.Icons.CLOSE, icon_size=CONSTANTS.ICON_SM, icon_color=LIGHT_GREY,
        bgcolor=GREY, tooltip="Effacer la recherche",
        on_click=_liste_clear_search,
        style=ft.ButtonStyle(padding=ft.Padding.all(4)))
    liste_search_row = ft.Row(
        [liste_search_field, liste_search_close_btn], spacing=4,
        vertical_alignment=ft.CrossAxisAlignment.CENTER)

    def _liste_render():
        liste_header_row.content = _liste_header()
        liste_header_row.visible = bool(liste_entries)
        liste_list_view.controls.clear()
        query = liste_search["value"]
        rows = ([(i, e) for i, e in enumerate(liste_entries)
                 if _liste_matches_search(e, query)] if query
                else list(enumerate(liste_entries)))
        if not liste_entries:
            error = _liste_load_error["msg"]
            liste_list_view.controls.append(ft.Text(
                error if error else
                "Liste vide. Ajoute une entrée, ou demande à l'IA de la "
                "remplir (create_file sur ce fichier .json).",
                size=CONSTANTS.TEXT_SM, color=RED if error else GREY))
        elif not rows:
            liste_list_view.controls.append(ft.Text(
                "Aucun résultat.", size=CONSTANTS.TEXT_SM, color=GREY))
        else:
            liste_list_view.controls.extend(_liste_row(i, e) for i, e in rows)
        liste_path_text.value = os.path.basename(_liste_file["path"])
        page.update()

    def _liste_reload(event=None):
        _liste_load()
        _liste_render()

    def _liste_open_path(path):
        # Sélectionner un .json dans Fichiers l'ouvre ici — pas de bouton
        # "Ouvrir" séparé (retour user : le FilePicker faisait doublon).
        _liste_file["path"] = path
        liste_search_field.value = ""
        liste_search["value"] = ""
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
            liste_search_field.value = ""
            liste_search["value"] = ""
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
        page.run_task(_focus_dialog_field, name_field)

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
                "Colonnes adaptées au fichier .json chargé. Cliquer sur "
                "une valeur la copie dans le presse-papiers.",
                size=CONSTANTS.TEXT_SM, color=WHITE),
            padding=ft.Padding(8, 0, 8, 4)),
        ft.Container(content=liste_search_row, padding=ft.Padding(8, 0, 8, 6)),
        ft.Divider(height=1, color=GREY),
        liste_header_row,
        ft.Container(content=liste_list_view, expand=True),
    ], expand=True, spacing=0)
    _liste_load()
    _liste_render()

    # ═════════════════════════════════════════════════════════════════════
    #  Surface Actus — agrégateur RSS/Atom natif (Data/rss_feeds.py) : news
    #  tech/IA + notes d'épisode de podcasts, fusionnées et triées par date.
    #  Portage Python du prototype web dashboard-perso — pas de WebView
    #  (non supporté sous Windows/Linux desktop par flet-webview), donc
    #  rendu 100% natif Flet ici.
    # ═════════════════════════════════════════════════════════════════════
    actus_status = ft.Text("", size=CONSTANTS.TEXT_SM, color=LIGHT_GREY)
    actus_list_view = ft.ListView(expand=True, spacing=8,
                                  padding=ft.Padding(8, 4, 8, 8))
    actus_state = {"loading": False}

    def _actus_item_card(item):
        date_txt = (item["date"].astimezone().strftime("%d/%m/%Y %H:%M")
                   if item["date"] else "")
        rows = [
            ft.Row([
                ft.Container(
                    content=ft.Text(item["source"], size=11,
                                    color=BLUE),
                    bgcolor=ft.Colors.with_opacity(0.15, BLUE),
                    border_radius=4, padding=ft.Padding(6, 2, 6, 2)),
                ft.Text(date_txt, size=11, color=LIGHT_GREY),
            ], spacing=8),
            ft.Text(item["title"], size=CONSTANTS.TEXT_SM, color=WHITE,
                    weight=ft.FontWeight.W_600),
        ]
        if item["summary"]:
            rows.append(ft.Text(item["summary"], size=11,
                                color=LIGHT_GREY, max_lines=3,
                                overflow=ft.TextOverflow.ELLIPSIS))
        link = item["link"]
        return ft.Container(
            content=ft.Column(rows, spacing=4, tight=True),
            bgcolor=GREY, border_radius=8, padding=10, ink=True,
            on_click=(lambda e, u=link: webbrowser.open(u)) if link
                     else None)

    def _actus_refresh(event=None):
        if actus_state["loading"]:
            return
        actus_state["loading"] = True
        actus_status.value = "Chargement des flux…"
        actus_list_view.controls.clear()
        page.update()

        def _work():
            try:
                items = rss_feeds.fetch_all_feeds()
                error = None
            except Exception as exc:
                items, error = [], str(exc)

            async def _apply():
                actus_state["loading"] = False
                if error:
                    actus_status.value = f"Erreur de chargement : {error}"
                elif not items:
                    actus_status.value = "Aucun article trouvé."
                else:
                    actus_status.value = (
                        f"{len(items)} articles — mis à jour à "
                        f"{datetime.datetime.now().strftime('%H:%M')}")
                    actus_list_view.controls.extend(
                        _actus_item_card(it) for it in items)
                page.update()

            page.run_task(_apply)

        threading.Thread(target=_work, daemon=True).start()

    actus_surface = ft.Column([
        ft.Container(
            content=ft.Row([
                ft.Text("Actus", size=CONSTANTS.TEXT_SM, color=WHITE,
                        weight=ft.FontWeight.W_700),
                ft.IconButton(ft.Icons.REFRESH, icon_color=ICON_ACTION,
                             icon_size=CONSTANTS.ICON_SM,
                             tooltip="Actualiser les flux",
                             on_click=_actus_refresh),
                actus_status,
            ], spacing=8),
            padding=ft.Padding(8, 8, 8, 0), bgcolor=BACKGROUND),
        ft.Divider(height=1, color=GREY),
        ft.Container(content=actus_list_view, expand=True),
    ], expand=True, spacing=0)

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
        "actus": actus_surface,
    }
    center = ft.Container(content=surface_content["files"], expand=True,
                          bgcolor=DARK)

    # ═════════════════════════════════════════════════════════════════════
    #  Rail gauche — onglets verticaux pleine hauteur (icône + texte vertical),
    #  bande colorée (BLUE) sur l'onglet actif, comme la maquette.
    # ═════════════════════════════════════════════════════════════════════
    rail_tabs = {}

    async def _focus_active_surface():
        # Le focus doit être là où on va vraisemblablement taper en premier,
        # sans clic préalable : dernière ligne du Bloc-notes, champ de l'IA,
        # ou Terminal s'il est déployé (prioritaire sur tout, quel que soit
        # l'onglet actif). Pas la recherche en Fichiers : lui donner le
        # focus à chaque navigation suspendait les raccourcis clavier de la
        # grille (_kb_suspend via search_field.on_focus) tant qu'on n'avait
        # pas cliqué ailleurs — la grille doit rester utilisable au clavier
        # tout de suite après une navigation (retour user). La recherche ne
        # prend le focus que si on clique dessus.
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
            if key == "notes":
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
        # Bascule dynamique de l'épinglage forcé du terminal (_busy_start/
        # _busy_end) selon l'onglet visé — retour user : inutile de garder
        # le terminal ouvert de force sur l'onglet IA (le statut y est déjà
        # visible), mais il doit se réépingler si on le quitte en cours de
        # dictée/réponse.
        if _busy["count"] > 0:
            if key == "ia" and _busy["pinned_by_busy"]:
                _terminal_autohide["pinned"] = _busy["was_pinned"]
                _busy["pinned_by_busy"] = False
                _show_terminal_and_schedule_hide()
            elif key != "ia" and not _busy["pinned_by_busy"]:
                _busy["was_pinned"] = _terminal_autohide["pinned"]
                _terminal_autohide["pinned"] = True
                _busy["pinned_by_busy"] = True
        state["surface"] = key
        center.content = surface_content[key]
        if key == "actus" and not actus_list_view.controls:
            _actus_refresh()   # chargement paresseux : au premier passage
        for k, tab in rail_tabs.items():
            is_active = k == key
            tab["container"].bgcolor = BLUE if is_active else None
            tab["icon"].color = DARK if is_active else WHITE
            tab["label"].color = DARK if is_active else WHITE
            tab["label"].weight = (ft.FontWeight.W_700 if is_active
                                   else ft.FontWeight.NORMAL)
        _configure_size_control()
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

    async def _tool_refresh(folder, names=None, origin_tab_id=None):
        # `origin_tab_id` = tab_id capturé par l'appelant AVANT de lancer
        # son thread : si l'utilisateur a changé d'onglet pendant que
        # l'opération tournait, ce rafraîchissement différé écraserait
        # silencieusement l'onglet devenu actif avec le dossier d'origine.
        # Rien n'est perdu en sautant : l'onglet d'origine sera rescanné
        # fraîchement à sa prochaine activation (_restore_tab).
        if origin_tab_id is not None and origin_tab_id != state["tab_id"]:
            return
        if folder:
            try:
                _navigate(folder)
            except Exception:
                pass
        # "SELECTED_FILES:a.jpg|b.jpg" (cf. _launch_tool/_read_output) :
        # appliqué APRÈS _navigate() (qui vide `selected` en interne) pour
        # resélectionner ce que l'outil a repéré (ex. Fichiers identiques.py)
        # — sinon la ligne n'était que loguée dans le terminal, jamais
        # traduite en sélection (retour user).
        if names is not None:
            selected.clear()
            paths = [os.path.join(folder, name) for name in names if name]
            _select_update(p for p in paths if os.path.isfile(p))
            _update_sel_count()
            _render()

    # Scripts en .py (pas .pyw) qui ouvrent quand même leur propre fenêtre
    # Flet — l'extension seule ne suffit pas à détecter une vraie appli GUI.
    _GUI_TOOLS_PY_EXT = {"Augmentation IA.py"}

    def _launch_tool(script_name, is_local=False, extra_env=None):
        app_path = os.path.join(_APP_DIR, "Data", script_name)
        if not os.path.exists(app_path):
            _log_to_terminal(f"[ERREUR] Introuvable : {script_name}", RED)
            return
        folder = state["folder"] or ""
        origin_tab_id = state["tab_id"]
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

        # Panneau fermé AVANT tout le reste : le nom de l'action doit
        # apparaître dans le terminal (avec la barre de progression)
        # seulement une fois le panneau retiré, jamais pendant qu'il est
        # encore affiché — et le sous-processus ne démarre qu'ensuite,
        # dans le thread ci-dessous (retour user).
        _close_actions()
        # Épinglé pour toute la durée du subprocess (retour user) : sans ça,
        # un outil silencieux plus de HUB_TERMINAL_AUTOHIDE_DELAY (ex. un
        # batch sans sortie intermédiaire) referme le panneau alors que le
        # traitement tourne encore. On restaure l'épinglage précédent (ex.
        # ouvert manuellement) en cas de succès ; en cas d'erreur, on le
        # laisse ouvert pour que le message reste lisible.
        prev_pinned = _terminal_autohide["pinned"]
        _terminal_autohide["pinned"] = True
        _log_to_terminal(f"▶ Lancement de {display_name}...", BLUE, clear=True)
        action_progress_bar.visible = True
        page.update()

        def _run():
            env = dict(os.environ)
            env["PYTHONIOENCODING"] = "utf-8"
            env["DATA_PATH"] = os.path.join(_APP_DIR, "Data")
            if is_local:
                env["LAUNCHED_FROM_DASHBOARD"] = "1"
                # Comme Dashboard.pyw:8947-8948 : SOURCE_FILES seulement s'il
                # y a une sélection réelle. Sans ça, une sélection perdue
                # entre le clic et l'exécution (ex. dialogue de confirmation)
                # faisait basculer silencieusement sur `folder` entier —
                # copie récursive de tout Téléchargements au lieu des
                # fichiers choisis (retour user : transfert énorme/très lent
                # au lieu de quelques fichiers).
                if picked:
                    env["SOURCE_FILES"] = "|".join(picked)
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
                    stdin=subprocess.DEVNULL,
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
            # "SELECTED_FILES:a.jpg|b.jpg" (même convention Dashboard.pyw:719/
            # 9221-9240) : des outils comme Fichiers identiques.py repèrent des
            # fichiers et attendent qu'ils soient sélectionnés dans la preview
            # après coup — sans cette interception, la ligne n'était que
            # loguée dans le terminal, jamais appliquée (retour user).
            nav_target = {"path": None}
            sel_target = {"names": None}

            def _read_output(pipe, color):
                try:
                    for line in iter(pipe.readline, ""):
                        stripped = line.rstrip()
                        if not stripped:
                            continue
                        if stripped.startswith("NAVIGATE_TO:"):
                            nav_target["path"] = stripped[len("NAVIGATE_TO:"):]
                        elif stripped.startswith("SELECTED_FILES:"):
                            sel_target["names"] = stripped[
                                len("SELECTED_FILES:"):].split("|")
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
                async def _restore_window():
                    # Même séquence que _delayed_maximize au démarrage :
                    # dé-minimiser et maximiser dans le MÊME update est
                    # parfois ignoré par Windows — Hub revenait en mode
                    # fenêtré au lieu du plein écran après un outil
                    # (retour user). Deux updates séparés par un délai.
                    page.window.minimized = False
                    page.update()
                    await asyncio.sleep(0.2)
                    page.window.maximized = True
                    page.update()
                    await page.window.to_front()

                page.run_task(_restore_window)
                # Un outil lancé depuis la visionneuse plein écran (Recadrage
                # manuel/Augmentation IA sur l'image courante) laisse
                # `viewer_overlay` ouvert pendant tout le subprocess (Hub est
                # juste minimisé, pas la visionneuse fermée) — sans ce
                # nettoyage, restaurer la fenêtre ramenait l'utilisateur dans
                # la visionneuse au lieu de Hub (retour user). Gardé par
                # `in page.overlay` : ne touche à rien pour les outils lancés
                # depuis ailleurs (visionneuse jamais ouverte).
                if viewer_overlay in page.overlay:
                    _close_viewer()
                page.update()
            if proc.returncode != 0:
                _log_to_terminal(
                    f"[ERREUR] {script_name} — code retour {proc.returncode}",
                    RED)
                # Erreur : le panneau reste épinglé (pas de fermeture auto)
                # pour que le message reste lisible (retour user).
            else:
                _log_to_terminal(f"[OK] {script_name} terminé", GREEN)
                _terminal_autohide["pinned"] = prev_pinned
                _show_terminal_and_schedule_hide(
                    CONSTANTS.HUB_TERMINAL_TOOL_CLOSE_DELAY)
            page.run_task(_tool_refresh, nav_target["path"] or folder,
                          sel_target["names"], origin_tab_id)
            action_progress_bar.visible = False
            try:
                page.update()
            except Exception:
                pass

        threading.Thread(target=_run, daemon=True).start()

    def _launch_renommer_sequence(event=None):
        name_field = ft.TextField(
            label="Nom de la série", hint_text="Ex: Mariage_Martin",
            autofocus=True, width=280, bgcolor=DARK, border_color=GREY,
            color=WHITE)
        # Garde anti double-déclenchement : ENTER (on_submit) et le bouton
        # "Lancer" appellent tous deux _confirm. Sans ce verrou, un second
        # appel relit `selected` — déjà vidé par le _launch_tool du premier
        # appel (_close_actions) — et le script associé traite alors TOUT
        # le dossier au lieu des seuls fichiers sélectionnés (retour user :
        # renommage complet et destructif d'un dossier au lieu de 3 photos).
        fired = {"done": False}

        def _cancel(e):
            dlg.open = False
            page.update()

        def _confirm(e):
            if fired["done"]:
                return
            fired["done"] = True
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
        page.run_task(_focus_dialog_field, name_field)

    def _launch_two_in_one(event=None):
        def _cancel(e):
            dlg.open = False
            page.update()

        def _pick(val):
            def _on_click(e):
                # "127x178@210x297" = photo @ planche ; sans « @ », la
                # planche est déduite des photos (cf. TWO_IN_ONE_FORMATS).
                photo, _, sheet = val.partition("@")
                w, h = photo.split("x")
                dlg.open = False
                page.update()
                _launch_tool("2 en 1.py", extra_env={
                    "TWO_IN_ONE_WIDTH": w, "TWO_IN_ONE_HEIGHT": h,
                    "TWO_IN_ONE_SHEET": sheet})
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
            # `picked` transmis explicitement (capturé plus haut, avant
            # le dialogue) plutôt que laissé à _launch_tool qui relirait
            # `selected` après coup — évite une sélection périmée.
            extra_env = {"DELETE_AFTER_TRANSFER":
                         "1" if delete_after else "0"}
            if picked:
                extra_env["SOURCE_FILES"] = "|".join(picked)
            _launch_tool("Transfert vers TEMP.py", is_local=True,
                        extra_env=extra_env)

        if not picked:
            # Aucun fichier sélectionné = source par défaut Downloads,
            # le script supprime déjà d'office dans ce cas (voir
            # Transfert vers TEMP.py). Pas besoin de demander (retour
            # user).
            _launch(True)
            return

        ui_helpers.confirm_dialog(
            page, "Supprimer les fichiers après transfert ?",
            lambda: _launch(True), _KEYPAD_COLORS,
            message=f"{scope} seront transférés vers TEMP.\n\n"
                    "Supprimer les fichiers source après la copie réussie ?",
            confirm_label="Supprimer", cancel_label="Conserver",
            confirm_color=RED, on_cancel=lambda: _launch(False))

    def _images_to_pdf(imgs):
        """Fusionne des images en un PDF temporaire multi-pages.

        Un appel du verbe « print » par fichier ouvrait autrefois un seul
        assistant Windows regroupant toutes les photos ; depuis une mise à
        jour de l'appli Photos, chaque appel ouvre SA fenêtre (retour user).
        Un PDF unique = un seul dialogue d'impression, N pages, et le même
        comportement sur macOS/Linux.
        """
        pages = []
        dpis = set()
        total = len(imgs)
        for num, p in enumerate(imgs, start=1):
            _log_to_terminal(
                f"Préparation {num}/{total} : {os.path.basename(p)}")
            src = PILImage.open(p)
            src.load()
            # Relevé AVANT conversion : convert_to_srgb reconstruit l'image
            # via ImageCms et ne recopie pas info["dpi"].
            dpi = src.info.get("dpi")
            if dpi:
                dpis.add(round(float(dpi[0])))
            img = image_ops.convert_to_srgb(src, src.info.get("icc_profile"))
            img = PILImageOps.exif_transpose(img)
            if img.mode == "RGBA":
                bg = PILImage.new("RGB", img.size, (255, 255, 255))
                bg.paste(img, mask=img.split()[3])
                img = bg
            elif img.mode != "RGB":
                img = img.convert("RGB")
            pages.append(img)
        # PIL n'écrit qu'UNE résolution pour tout le PDF (celle passée au
        # save, cf. PdfImagePlugin._save) : sans elle il retombe sur 72 dpi
        # et une photo 300 dpi sort en page de 50 cm, que l'imprimante
        # réduit pour la faire tenir — le tirage n'est plus à 100 %.
        resolution = float(min(dpis)) if dpis else 300.0
        if len(dpis) > 1:
            _log_to_terminal(
                f"[ATTENTION] DPI mélangés dans la sélection ({sorted(dpis)}) "
                f"— tout le PDF sort à {resolution:.0f} dpi", ORANGE)
        fd, pdf_path = tempfile.mkstemp(prefix="Hub_impression_",
                                        suffix=".pdf")
        os.close(fd)
        _log_to_terminal(
            f"Assemblage du PDF ({total} pages à {resolution:.0f} dpi)…")
        pages[0].save(pdf_path, "PDF", resolution=resolution, save_all=True,
                      append_images=pages[1:])
        return pdf_path

    def _print_paths(paths):
        # Partagé entre le bouton Imprimer (titlebar/Actions, sélection ou
        # dossier entier) et l'entrée « Imprimer » du menu clic-droit
        # (fichier sur lequel on a cliqué).
        imgs = [p for p in paths
                if os.path.splitext(p)[1].lower() in CONSTANTS.IMAGE_EXTS]
        pdfs = [p for p in paths
                if os.path.splitext(p)[1].lower() == ".pdf"]
        if not imgs and not pdfs:
            _log_to_terminal("[ATTENTION] Aucune image à imprimer", ORANGE)
            return
        count = len(imgs) + len(pdfs)
        _log_to_terminal(f"Impression de {count} fichier(s)…", clear=True)
        # Bascule en mode ruban tout de suite (avant le travail, pas après) :
        # laisse la fenêtre d'impression de l'OS passer devant, et rend le
        # terminal visible pendant la préparation.
        if not _strip_state["active"]:
            _toggle_strip()

        def _run(imgs=imgs, pdfs=pdfs):
            # La fusion PDF lit et décode chaque image : sur une grosse
            # sélection ça prend plusieurs secondes, l'interface se figeait
            # sans le moindre retour (retour user). D'où le thread + les
            # logs de progression dans _images_to_pdf.
            if len(imgs) > 1:
                # Plusieurs images : un seul PDF plutôt que N dialogues.
                try:
                    pdfs = [_images_to_pdf(imgs)] + pdfs
                    imgs = []
                except Exception as exc:
                    _log_to_terminal(
                        f"[ATTENTION] Fusion PDF impossible ({exc}) — "
                        "impression image par image", ORANGE)
            elif len(imgs) == 1:
                # Une seule image : Windows Photos identifie le verbe
                # « print » par chemin de fichier, donc relancer
                # l'impression du même fichier source ne rouvre pas de
                # fenêtre la 2e fois (retour user). Une copie temporaire à
                # chemin neuf contourne ce blocage tout en gardant le
                # dialogue Photos natif (pas de bascule en PDF).
                try:
                    ext = os.path.splitext(imgs[0])[1]
                    fd, tmp_path = tempfile.mkstemp(
                        prefix="Hub_impression_", suffix=ext)
                    os.close(fd)
                    shutil.copy2(imgs[0], tmp_path)
                    imgs = [tmp_path]
                except Exception as exc:
                    _log_to_terminal(
                        f"[ATTENTION] Copie temporaire impossible ({exc}) "
                        "— impression du fichier original", ORANGE)
            try:
                system = platform.system()
                if system == "Darwin":
                    subprocess.call(["open"] + imgs + pdfs)
                elif system == "Windows":
                    for p in imgs:
                        os.startfile(p, "print")
                    for p in pdfs:
                        # Le verbe "print" ouvre l'appli d'impression PHOTO
                        # de Windows, qui ne sait pas gérer un PDF (retour
                        # user) — un simple "open" lance l'appli PDF par
                        # défaut (souvent le navigateur), depuis laquelle
                        # imprimer normalement.
                        os.startfile(p)
                else:
                    for p in imgs + pdfs:
                        subprocess.Popen(["xdg-open", p])
            except Exception as exc:
                _log_to_terminal(f"[ERREUR] Impression : {exc}", RED)
                return
            _log_to_terminal(
                f"[OK] Impression lancée pour {count} fichier(s)", GREEN)

        threading.Thread(target=_run, daemon=True).start()

    def _launch_print(event=None):
        paths = list(selected) or content["imgs"]
        _close_actions()
        _print_paths(paths)

    def _launch_bluetooth(event=None):
        _close_actions()
        try:
            if platform.system() == "Windows":
                subprocess.Popen(["fsquirt.exe", "/Receive"])
            else:
                subprocess.Popen(["open", "-a", "Bluetooth File Exchange"])
        except Exception:
            pass
        if not _strip_state["active"]:
            _toggle_strip()

    def _launch_copy_to_selection(event=None):
        paths = list(selected) if selected else content["imgs"]
        _close_actions()
        if paths:
            _do_copy_to_selection(paths)

    def _launch_copy_scored(event=None):
        folder = state["folder"]
        if not folder:
            return
        _close_actions()

        def _run():
            _copy_scored_photos(folder)
            page.run_task(_actions_refresh_folder)

        threading.Thread(target=_run, daemon=True).start()

    async def _actions_refresh_folder():
        if state["folder"]:
            try:
                _navigate(state["folder"])
            except Exception:
                pass

    def _launch_text_prompt(title, label, hint, script_name, env_key):
        def _on_confirm(value):
            _launch_tool(script_name, extra_env={env_key: value})

        ui_helpers.text_prompt_dialog(
            page, title, _on_confirm, _KEYPAD_COLORS, label=label,
            hint_text=hint, confirm_label="Lancer")

    def _launch_images_en_pdf(event=None):
        _launch_text_prompt("Images en PDF", "Nom du PDF", "Ex: Album_Mariage",
                            "Images en PDF.py", "PDF_NAME")

    def _launch_livret(event=None):
        _launch_text_prompt("Livret", "Nom du livret", "Ex: Album_Mariage",
                            "Livret.py", "LIVRET_NAME")

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

        fired = {"done": False}

        def _cancel(e):
            dlg.open = False
            page.update()

        def _confirm(e):
            if fired["done"]:
                return
            env = {}
            for (label, suffix, default, env_key), field in zip(fields, text_fields):
                try:
                    env[env_key] = str(int((field.value or "").strip()))
                except ValueError:
                    field.error_text = "Nombre requis"
                    page.update()
                    return
            fired["done"] = True
            dlg.open = False
            page.update()
            _launch_tool(script_name, extra_env=env)

        text_fields[-1].on_submit = _confirm
        keypad = _numeric_keypad(text_fields)
        dlg = ft.AlertDialog(
            title=ft.Text(title, size=CONSTANTS.TEXT_SM, color=WHITE),
            content=ft.Column(text_fields + [keypad], spacing=8, tight=True),
            actions=[ft.TextButton("Annuler", on_click=_cancel),
                     ft.TextButton("Lancer", on_click=_confirm)],
        )
        page.overlay.append(dlg)
        dlg.open = True
        page.update()
        page.run_task(_focus_dialog_field, text_fields[0])

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

    def _launch_kiosk(event=None):
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
        env["TARIFF_TYPE"] = state["tariff_mode"]
        _close_actions()
        page.run_task(_tool_set_status, "▶ Lancement du kiosque…")

        def _run():
            try:
                subprocess.Popen([sys.executable, kiosk_path], env=env,
                                 stdin=subprocess.DEVNULL)
            except Exception as exc:
                page.run_task(_tool_set_status, f"[Erreur] Kiosque : {exc}")
                return
            page.run_task(_tool_set_status, "✓ Kiosque lancé")

        threading.Thread(target=_run, daemon=True).start()

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
            value=default_fmt, width=280, bgcolor=DARK,
            border_color=LIGHT_GREY if manual["value"] else BLUE,
            color=WHITE, disabled=manual["value"])
        width_field = ft.TextField(
            label="Largeur (mm)", value=str(saved.get("manual_w", default_w)),
            width=132, bgcolor=DARK,
            border_color=BLUE if manual["value"] else LIGHT_GREY,
            color=WHITE if manual["value"] else GREY,
            disabled=not manual["value"], keyboard_type=ft.KeyboardType.NUMBER)
        height_field = ft.TextField(
            label="Hauteur (mm)", value=str(saved.get("manual_h", default_h)),
            width=132, bgcolor=DARK,
            border_color=BLUE if manual["value"] else LIGHT_GREY,
            color=WHITE if manual["value"] else GREY,
            disabled=not manual["value"], keyboard_type=ft.KeyboardType.NUMBER)
        manual_switch = ft.Switch(label="Saisie manuelle (mm)",
                                  value=manual["value"], active_color=BLUE)
        fit_switch = ft.Switch(label="Fit 100% (sans rognage)",
                               value=bool(saved.get("fit", False)),
                               active_color=BLUE)
        center_switch = ft.Switch(label="Centrer",
                                  value=bool(saved.get("center", False)),
                                  active_color=BLUE,
                                  disabled=not bool(saved.get("fit", False)))
        white_border_switch = ft.Switch(label="Bord blanc 5mm",
                                        value=bool(saved.get("white_border", False)),
                                        active_color=BLUE)
        scope_text = ft.Text(
            f"Portée auto : {'sélection en cours' if selected else 'tout le dossier'}",
            size=CONSTANTS.TEXT_SM, color=GREY)

        # Pavé numérique tactile, visible seulement en saisie manuelle
        # (les champs ne sont éditables que dans ce mode).
        keypad = _numeric_keypad([width_field, height_field])
        keypad.visible = manual["value"]

        def _on_manual_change(e):
            manual["value"] = manual_switch.value
            fmt_dd.disabled = manual["value"]
            width_field.disabled = not manual["value"]
            height_field.disabled = not manual["value"]
            width_field.color = WHITE if manual["value"] else GREY
            height_field.color = WHITE if manual["value"] else GREY
            fmt_dd.border_color = LIGHT_GREY if manual["value"] else BLUE
            width_field.border_color = BLUE if manual["value"] else LIGHT_GREY
            height_field.border_color = BLUE if manual["value"] else LIGHT_GREY
            keypad.visible = manual["value"]
            page.update()

        manual_switch.on_change = _on_manual_change

        def _on_fit_change(e):
            center_switch.disabled = not fit_switch.value
            page.update()

        fit_switch.on_change = _on_fit_change

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
                "center": center_switch.value,
                "white_border": white_border_switch.value,
            })
            dlg.open = False
            page.update()
            _launch_tool("Recadrage automatique.py", extra_env={
                "FORCE_CROP_SIZE": f"{w}x{h}",
                "FORCE_CROP_SCOPE": "selected" if selected else "folder",
                "FORCE_CROP_FIT": "1" if fit_switch.value else "0",
                "FORCE_CROP_CENTER": "1" if center_switch.value else "0",
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
                                              spacing=8),
                                       keypad]),
                    border=ft.Border.all(1, GREY), border_radius=8,
                    padding=10),
                ft.Row([fit_switch, center_switch], spacing=8),
                white_border_switch, scope_text,
            ], spacing=12, tight=True, width=380),
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

        # Panneau fermé et fenêtre ramenée au premier plan AVANT le
        # sélecteur de dossier natif (retour user : sur Windows, ce
        # sélecteur peut s'ouvrir masqué derrière la fenêtre principale —
        # tout semble figé (panneau Actions toujours affiché, bouton
        # Fermer inerte) pendant plusieurs minutes, le temps que
        # l'utilisateur retrouve la boîte de dialogue cachée. Situation
        # critique en présence d'un client (retour user).
        _close_actions()
        _log_to_terminal(
            "[...] Choisissez le second dossier à synchroniser…", ORANGE)
        try:
            await page.window.to_front()
        except Exception:
            pass
        folder_b = await ft.FilePicker().get_directory_path(
            dialog_title="Choisir le 2e dossier à synchroniser")
        if not folder_b:
            _log_to_terminal("[INFO] Synchronisation annulée", LIGHT_GREY)
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

    # (label, icône, couleur, handler)
    # Catégories = les regroupements du flux de travail réel (cf. mémoire
    # project_business_workflow), pas les intitulés génériques de la
    # maquette (celle-ci utilisait des actions fictives) — Bluetooth et
    # Imprimer n'y sont plus : remontés dans la barre de titre (accès global).
    # Reprend les handlers des boutons de la barre de recherche et de la
    # barre d'outils fichiers (retour user : clic droit → Actions est
    # parfois plus pratique/habituel que ces icônes) — mêmes lambdas,
    # donc mêmes garde-fous de sélection déjà en place. Rangée d'icônes
    # seules (sans texte), Imprimer/Nombre d'impressions déplacés juste
    # avant Supprimer dans la liste texte ci-dessous (retour user).
    _fichier_icon_actions = [
        ("Renommer", ft.Icons.DRIVE_FILE_RENAME_OUTLINE, BLUE,
         renommer_btn.on_click),
        ("Copier", ft.Icons.CONTENT_COPY, BLUE, copier_btn.on_click),
        # Ces trois-là déclenchent EXACTEMENT le même handler que les
        # boutons de la barre d'outils (couper/coller/zipper) : ils
        # doivent en porter la couleur, sinon la même action a deux
        # identités selon l'endroit où on la lance.
        ("Couper", ft.Icons.CONTENT_CUT, BLUE, couper_btn.on_click),
        ("Coller", ft.Icons.CONTENT_PASTE, BLUE, coller_btn.on_click),
        ("Dupliquer", ft.Icons.FILE_COPY_OUTLINED, BLUE,
         dupliquer_btn.on_click),
        ("Zipper", ft.Icons.FOLDER_ZIP_OUTLINED, ORANGE,
         zipper_btn.on_click),
        ("Ajouter à l'IA", ft.Icons.SMART_TOY_OUTLINED, VIOLET,
         ajouter_ia_btn.on_click),
        ("Pivoter 90° gauche", ft.Icons.ROTATE_LEFT, BLUE,
         lambda e: _run_action(_do_rotate, list(selected), 90)),
        ("Pivoter 90° droite", ft.Icons.ROTATE_RIGHT, BLUE,
         lambda e: _run_action(_do_rotate, list(selected), -90)),
        ("Pivoter 180°", ft.Icons.SCREEN_ROTATION, BLUE,
         lambda e: _run_action(_do_rotate, list(selected), 180)),
    ]
    # Sur la même rangée d'icônes que le reste, à la fin (retour user) —
    # plus de ListTile séparée pour Fichier.
    _fichier_icon_actions += [
        ("Imprimer", ft.Icons.PRINT_OUTLINED, ORANGE, _launch_print),
        ("Nombre d'impressions", ft.Icons.NUMBERS, ORANGE,
         lambda e: _run_action(_set_print_count, list(selected))),
        ("Supprimer", ft.Icons.DELETE_OUTLINE, RED,
         supprimer_btn.on_click),
    ]
    # Pas d'entrée "Importer depuis téléphone" ici : le téléphone apparaît
    # dans le volet "Périphériques" du menu Ouvrir, au même endroit que les
    # clés USB et les cartes SD, ce qui est là où on le cherche (retour
    # user 2026-08-07). Cf. _phone_row.
    _ACTION_CATEGORIES = [
        ("Fichier", _fichier_icon_actions),
        ("Préparation", [
            ("Conversion JPG", ft.Icons.IMAGE_OUTLINED, BLUE,
             lambda e: _launch_tool("Conversion JPG.py",
                                    extra_env={"CONVERT_FORMAT": "jpg"})),
            ("Conversion PNG", ft.Icons.IMAGE_OUTLINED, BLUE,
             lambda e: _launch_tool("Conversion JPG.py",
                                    extra_env={"CONVERT_FORMAT": "png"})),
            ("Renommer séquence", ft.Icons.SORT_BY_ALPHA, BLUE,
             _launch_renommer_sequence),
            ("Renommer pages Affinity", ft.Icons.FORMAT_LIST_NUMBERED, BLUE,
             lambda e: _launch_tool("Renommer pages Affinity.py")),
            ("Séparer RAW et JPG", ft.Icons.HIDE_IMAGE_OUTLINED, BLUE,
             lambda e: _launch_tool("Séparer RAW et JPG.py")),
        ]),
        # Ces quatre-là sont des copies vers un dossier : BLEU comme les
        # autres copies. Le JAUNE qu'elles portaient sert partout ailleurs
        # à désigner un dossier/fichier (icône de dossier, étoile favori),
        # jamais une action.
        ("Sélection", [
            ("Copier sélection → SELECTION", ft.Icons.FOLDER_COPY_OUTLINED, BLUE,
             _launch_copy_to_selection),
            ("Copier NEFs → SELECTION", ft.Icons.IMAGE_SEARCH_OUTLINED, BLUE,
             lambda e: _launch_tool("Copier NEFs sélection.py")),
            ("Copier selon score IA → SELECTION",
             ft.Icons.WORKSPACE_PREMIUM_OUTLINED, BLUE, _launch_copy_scored),
            ("Fichiers identiques", ft.Icons.CONTENT_COPY, BLUE,
             lambda e: _launch_tool("Fichiers identiques.py")),
        ]),
        ("Kiosque (mode client)", [
            ("Kiosque", ft.Icons.STOREFRONT_OUTLINED, ORANGE, _launch_kiosk),
        ]),
        ("Recadrage", [
            ("Recadrage manuel", ft.Icons.CROP_FREE, RED,
             recadrage_manuel_btn.on_click),
            ("Recadrage automatique", ft.Icons.CROP, GREEN,
             recadrage_auto_btn.on_click),
            ("2 en 1", ft.CupertinoIcons.SQUARE_SPLIT_2X1, GREEN,
             two_en_un_btn.on_click),
        ]),
        ("Retouche", [
            ("Retouche par lot", ft.Icons.TUNE, VIOLET,
             lambda e: _launch_tool("Retouche par lot.pyw")),
            ("Augmentation IA", ft.Icons.AUTO_FIX_HIGH_OUTLINED, VIOLET,
             lambda e: _launch_tool("Augmentation IA.py")),
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
            ("Livret", ft.Icons.MENU_BOOK_OUTLINED, ORANGE,
             _launch_livret),
            # Icône d'urne : Remerciements sert aux faire-part de décès,
            # c'est le repère visuel que Charles reconnaît dans le menu.
            # Ne PAS « corriger » en icône cadeau/carte (retour user).
            ("Remerciements", ft.CupertinoIcons.BIN_XMARK_FILL, ORANGE,
             lambda e: _launch_tool("Remerciements.py")),
            ("Nettoyer métadonnées", ft.Icons.CLEANING_SERVICES_OUTLINED, ORANGE,
             lambda e: _launch_tool("Nettoyer metadonnées.py")),
        ]),
        ("Maintenance", [
            ("Nettoyer anciens fichiers (> 60 jours)", ft.Icons.AUTO_DELETE,
             RED, lambda e: _launch_tool(
                 "Nettoyer anciens fichiers.py", is_local=True)),
            # COLOR_HOVER_YELLOW est un jeton de SURVOL, pas une couleur
            # d'icône : détourné ici, il rendait cette ligne unique dans
            # tout le panneau sans que ça veuille dire quoi que ce soit.
            ("Synchroniser avec un autre dossier", ft.Icons.SYNC, BLUE,
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

    def _icon_row(tools):
        # Rangée d'icônes seules (sans texte) pour les actions fichier
        # les plus fréquentes — évite une longue liste de ListTile pour
        # ce qui est déjà reconnaissable à l'icône (retour user).
        return ft.Row(
            [ft.IconButton(t[1], icon_color=t[2],
                          icon_size=CONSTANTS.ICON_LG, tooltip=t[0],
                          on_click=t[3]) for t in tools],
            spacing=0, wrap=True,
        )

    def _action_category(label, tools):
        # Libellé de catégorie en BLUE (pas GREY) : GREY sur le fond DARK
        # de l'overlay est quasi illisible, deux gris trop proches en
        # luminance — cf. retour user.
        if label == "Fichier":
            body = [_icon_row(tools)]
        else:
            body = [ft.Column([_action_row(*t) for t in tools], spacing=0)]
        return ft.Column([
            ft.Text(label.upper(), size=CONSTANTS.TEXT_SM, color=BLUE,
                    weight=ft.FontWeight.W_700),
            *body,
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
                lambda e, p=p: _run_action(_open_files_with, p, list(selected))
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
        page.update()
        # Que le panneau se ferme parce qu'une action vient d'être lancée
        # ou parce que l'utilisateur l'a simplement refermé, la sélection
        # ne doit pas rester en place (retour user) — chaque lanceur lit
        # `selected` avant d'appeler cette fonction, donc le vider ici est
        # sûr dans tous les cas. Pas de _render() complet : voir
        # _clear_selection_visuals.
        _clear_selection_visuals()
        page.run_task(_focus_active_surface)

    def _run_action(fn, *args):
        # Ferme le panneau Actions AVANT de lancer quoi que ce soit — le
        # nom de l'action doit apparaître dans le terminal (avec la barre
        # de progression) une fois le panneau déjà retiré, jamais pendant
        # qu'il est encore affiché (retour user). `args` est capturé par
        # l'appelant AVANT cet appel (ex. list(selected)), puisque
        # _close_actions() vide `selected` — fn reçoit donc toujours les
        # bonnes données malgré la fermeture qui précède son exécution.
        #
        # Hub tourne en .pyw (pas de console) : une exception ici partait
        # avant dans le vide, sans aucun message ni sur la sortie standard
        # ni dans le terminal intégré — l'app semblait « plantée » alors
        # qu'elle avait juste échoué silencieusement (retour user). On
        # rend désormais toute erreur visible dans le terminal intégré.
        try:
            _close_actions()
            fn(*args)
        except Exception as exc:
            _log_to_terminal(f"[ERREUR] {fn.__name__} : {exc}", RED)
            try:
                page.update()
            except Exception:
                pass

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

    async def _terminal_autohide_after_delay(delay=None):
        await asyncio.sleep(
            delay if delay is not None else CONSTANTS.HUB_TERMINAL_AUTOHIDE_DELAY)
        terminal_panel.visible = False
        page.update()

    def _show_terminal_and_schedule_hide(delay=None):
        # Sur l'onglet IA, ai_status_text/ai_progress_bar donnent déjà le
        # retour visuel — pas besoin du terminal en plus (retour user : il
        # « re-popait » à chaque étape de dictée). Un épinglage (manuel ou
        # _busy_start hors onglet IA) reste toujours prioritaire.
        if state["surface"] == "ia" and not _terminal_autohide["pinned"]:
            return
        terminal_panel.visible = True
        t = _terminal_autohide["task"]
        if t is not None and not t.done():
            t.cancel()
        if not _terminal_autohide["pinned"]:
            try:
                _terminal_autohide["task"] = page.run_task(
                    _terminal_autohide_after_delay, delay)
            except RuntimeError:
                # Fenêtre déjà fermée (session détruite) : un thread
                # d'arrière-plan encore en cours essaie de mettre à jour
                # un panneau qui n'existe plus, rien à faire.
                pass

    # Compteur d'étapes en cours (enregistrement, transcription, attente de
    # réponse IA, lecture TTS…) : chaque étape s'annonce/se termine via
    # _busy_start/_busy_end plutôt que de figer pinned/la barre elle-même,
    # pour que des étapes qui s'enchaînent sans interruption gardent le
    # terminal ouvert en continu au lieu de clignoter fermé/rouvert entre
    # deux (retour user : un retour visuel pour CHAQUE étape, en continu).
    # L'épinglage forcé n'a de sens que si l'onglet IA n'est PAS affiché
    # (ai_status_text/ai_progress_bar donnent déjà le retour visuel sur cet
    # onglet, retour user) — _pinned_by_busy distingue "épinglé par nous"
    # de "épinglé manuellement" pour ne jamais écraser un épinglage user.
    _busy = {"count": 0, "was_pinned": False, "pinned_by_busy": False}

    def _busy_start():
        if _busy["count"] == 0 and state["surface"] != "ia":
            _busy["was_pinned"] = _terminal_autohide["pinned"]
            _terminal_autohide["pinned"] = True
            _busy["pinned_by_busy"] = True
        if _busy["count"] == 0:
            action_progress_bar.visible = True
            _show_terminal_and_schedule_hide()
            try:
                page.update()
            except Exception:
                pass
        _busy["count"] += 1

    def _busy_end():
        _busy["count"] = max(0, _busy["count"] - 1)
        if _busy["count"] == 0:
            action_progress_bar.visible = False
            if _busy["pinned_by_busy"]:
                _terminal_autohide["pinned"] = _busy["was_pinned"]
                _busy["pinned_by_busy"] = False
            _show_terminal_and_schedule_hide()
            try:
                page.update()
            except Exception:
                pass

    _terminal_log_path = os.path.join(_APP_DIR, "Data", ".hub_terminal.log")

    def _log_to_terminal(message, color=None, clear=False):
        message = (message or "").strip()
        if not message:
            return
        # Persisté en plus de l'affichage (retour user) : le panneau se vide
        # au bout de HUB_TERMINAL_MAX_LINES lignes et se ferme tout seul —
        # sans ce fichier, la trace d'un bug survenu avant qu'on la lise est
        # perdue.
        try:
            if (os.path.exists(_terminal_log_path)
                    and os.path.getsize(_terminal_log_path)
                    > CONSTANTS.HUB_TERMINAL_LOG_MAX_BYTES):
                # Ne garder que la deuxième moitié : inutile de conserver
                # tout l'historique, seules les dernières lignes servent à
                # comprendre un bug récent (retour user).
                with open(_terminal_log_path, "rb") as f:
                    f.seek(-CONSTANTS.HUB_TERMINAL_LOG_MAX_BYTES // 2, os.SEEK_END)
                    tail = f.read()
                with open(_terminal_log_path, "wb") as f:
                    f.write(tail)
            with open(_terminal_log_path, "a", encoding="utf-8") as f:
                f.write(f"{datetime.datetime.now().isoformat(timespec='seconds')} {message}\n")
        except Exception:
            pass

        async def _do():
            if clear:
                # Chaque nouvelle action repart d'un terminal vide (retour
                # user) : l'historique complet reste de toute façon dans
                # _terminal_log_path ci-dessus, pas besoin de le garder
                # affiché en plus.
                terminal_output.controls.clear()
            terminal_output.controls.append(
                ft.Text(message, size=CONSTANTS.TERMINAL_FONT_SIZE,
                        color=color or WHITE, font_family="monospace",
                        selectable=True))
            if len(terminal_output.controls) > CONSTANTS.HUB_TERMINAL_MAX_LINES:
                terminal_output.controls.pop(0)
            _show_terminal_and_schedule_hide()
            page.update()

        try:
            page.run_task(_do)
        except RuntimeError:
            # Fenêtre déjà fermée (session détruite) : le message reste
            # dans _terminal_log_path ci-dessus, pas besoin de l'afficher.
            pass

    # Les fonctions _save_* sont au niveau module et ne voient pas
    # _log_to_terminal : on le leur branche ici, une fois pour toutes.
    _save_error_hook["fn"] = lambda msg: _log_to_terminal(msg, RED)

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

        fired = {"done": False}

        def _cancel(event):
            dlg.open = False
            page.update()

        def _confirm(event):
            if fired["done"]:
                return
            fired["done"] = True
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
        page.run_task(_focus_dialog_field, pwd_field)

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
        bgcolor=DARK, height=CONSTANTS.HUB_TERMINAL_HEIGHT, visible=False,
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
        terminal_panel.height = None if is_full else CONSTANTS.HUB_TERMINAL_HEIGHT
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

    # Curseur de taille unique dans la statusbar (retour user) : pilote la
    # taille des vignettes en Fichiers, et la taille du texte en IA/Bloc-
    # notes — reconfiguré par _configure_size_control() plutôt que dupliqué
    # par onglet. Double-clic dessus -> retour à la valeur par défaut.
    size_control_icon = ft.Icon(ft.Icons.PHOTO_SIZE_SELECT_LARGE,
                                size=CONSTANTS.ICON_SM, color=WHITE)
    size_control_slider = ft.Slider(width=140, active_color=BLUE)

    def _configure_size_control():
        if state["surface"] in ("ia", "notes"):
            size_control_icon.icon = ft.Icons.FORMAT_SIZE
            size_control_slider.min = 11
            size_control_slider.max = 24
            size_control_slider.value = state["font_size"]
            size_control_slider.on_change = lambda e: _apply_font_size(e.control.value)
            size_control_slider.tooltip = "Taille du texte (double-clic : réinitialiser)"
        else:
            size_control_icon.icon = ft.Icons.PHOTO_SIZE_SELECT_LARGE
            size_control_slider.min = 90
            size_control_slider.max = 320
            size_control_slider.value = state["thumb_size"]
            size_control_slider.on_change = lambda e: _apply_thumb_size(e.control.value)
            size_control_slider.tooltip = "Taille des vignettes (double-clic : réinitialiser)"

    def _reset_size_control(e=None):
        if state["surface"] in ("ia", "notes"):
            _apply_font_size(_DEFAULT_FONT_SIZE)
            size_control_slider.value = state["font_size"]
        else:
            _apply_thumb_size(_DEFAULT_THUMB_SIZE)
            size_control_slider.value = state["thumb_size"]
        size_control_slider.update()

    _configure_size_control()

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
                    tariff_wrap,
                    ft.Container(ft.VerticalDivider(color=LIGHT_GREY),
                                 height=CONSTANTS.HUB_TOOLBAR_H),
                    size_control_icon,
                    ft.GestureDetector(on_double_tap=_reset_size_control,
                                      content=size_control_slider),
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

    # (large, replié) : un seul des deux visible à la fois, selon la
    # largeur. Seules les icônes dupliquées dans le panneau Actions
    # (_fichier_actions/_ACTION_CATEGORIES) se replient (retour user) —
    # accessory_row/menu = barre de titre ; launcher_row/menu = lanceurs
    # d'outils dupliqués dans Actions (ligne 1, Fichiers) ; edit_btns_row/
    # menu = barre copier/coller (tous dupliqués dans Actions) ;
    # print_count_btn/menu = seul élément dupliqué dans Actions de la
    # ligne sélection/commande — tout le reste de cette ligne-là reste
    # toujours visible. Tout défini ailleurs dans main(), résolu au moment
    # de l'appel (comme les autres closures de main() référencées en
    # avance).
    def _narrow_bar_pairs():
        return [
            (accessory_row, accessory_menu),
            (launcher_row, launcher_menu),
            (edit_btns_row, edit_btns_menu),
            (print_count_btn, print_count_menu),
        ]

    def _apply_titlebar_width():
        narrow = (page.window.width or 0) < CONSTANTS.HUB_TITLEBAR_NARROW_WIDTH
        changed = False
        for row, menu in _narrow_bar_pairs():
            if row.visible != (not narrow):
                row.visible = not narrow
                menu.visible = narrow
                changed = True
        if changed:
            page.update()

    def _on_window_event(event):
        # Flet 0.86 : `WindowEvent` expose `.type` (WindowEventType), pas
        # `.data` (chaîne) comme dans les versions précédentes — l'ancien
        # code testait `event.data`, qui n'existe plus sur cette version et
        # levait une AttributeError avalée silencieusement par Flet à
        # chaque clic sur "Fermer"/redimension (retour user : le bouton
        # Fermer ne répondait plus du tout).
        if event.type == ft.WindowEventType.CLOSE:
            os._exit(0)
        elif event.type == ft.WindowEventType.RESIZED:
            _apply_titlebar_width()
            if viewer_overlay in page.overlay:
                # Le viewport de la visionneuse a une taille explicite (cf.
                # _set_drawer_space) : la rafraîchir au resize, sinon elle
                # reste calée sur la taille de fenêtre au moment de
                # l'ouverture.
                _set_drawer_space(viewer_image_wrap.right or 0)
            page.update()

    page.window.on_event = _on_window_event

    def _open_browser(event=None):
        webbrowser.open("https://www.google.com")
        if not _strip_state["active"]:
            _toggle_strip()

    def _launch_ssh_terminal(event=None):
        # Rejoint la session tmux "claude" sur le Pi hub — c'est là que
        # tourne cette conversation même. Un vrai terminal, sans passer
        # par la dictée (retour user : OpenWhispr avale des mots).
        # `tmux new -A -s claude` plutôt que `attach` : rattache la
        # session si elle existe déjà, sinon en crée une — ne plante
        # jamais si la session n'a pas encore démarré (retour user).
        # Le mot de passe SSH reste demandé normalement par le terminal
        # ouvert ; jamais saisi/mémorisé ici.
        ssh_cmd = 'ssh pictorsomni@pictorsomni -t "tmux new -A -s claude"'
        try:
            system = platform.system()
            if system == "Windows":
                if shutil.which("wt"):
                    subprocess.Popen([
                        "wt", "ssh", "pictorsomni@pictorsomni", "-t",
                        "tmux new -A -s claude"])
                else:
                    subprocess.Popen(f"start cmd /k {ssh_cmd}", shell=True)
            elif system == "Darwin":
                # Les guillemets internes de ssh_cmd (autour de la commande
                # tmux) doivent être échappés pour AppleScript, sinon
                # `do script "..."` se referme au premier " rencontré et le
                # reste atterrit comme identifiant hors chaîne — syntax
                # error -2740 (retour user).
                escaped_cmd = ssh_cmd.replace("\\", "\\\\").replace(
                    '"', '\\"')
                script = ('tell application "Terminal" to do script '
                         f'"{escaped_cmd}"')
                subprocess.Popen(["osascript", "-e", script])
            else:
                for term in ("x-terminal-emulator", "gnome-terminal",
                            "konsole", "xfce4-terminal", "xterm"):
                    if not shutil.which(term):
                        continue
                    if term == "gnome-terminal":
                        subprocess.Popen([term, "--", "bash", "-c", ssh_cmd])
                    else:
                        subprocess.Popen([term, "-e", ssh_cmd])
                    break
                else:
                    _log_to_terminal("[ERREUR] Aucun terminal trouvé", RED)
                    return
        except Exception as exc:
            _log_to_terminal(
                f"[ERREUR] Ouverture du terminal SSH : {exc}", RED)
            return
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
    # Icônes accessoires de la barre de titre (Bluetooth, impression,
    # navigateur, explorateur, terminal SSH) : repliées dans un menu "..."
    # sous CONSTANTS.HUB_TITLEBAR_NARROW_WIDTH plutôt que de déborder hors
    # de la fenêtre (retour user : invisibles en demi-écran sur écran
    # High-DPI avec zoom Windows — la Row de la barre de titre ne wrap pas).
    _TITLEBAR_ACCESSORY_TOOLS = [
        (ft.Icons.BLUETOOTH, "Recevoir un fichier via Bluetooth", BLUE,
         _launch_bluetooth),
        (ft.Icons.PRINT_OUTLINED, "Imprimer la sélection (ou le dossier)",
         ORANGE, _launch_print),
        (ft.Icons.PUBLIC, "Ouvrir le navigateur web", BLUE, _open_browser),
        (ft.Icons.OPEN_IN_NEW, "Ouvrir l'explorateur", GREEN,
         _open_in_file_explorer),
        (ft.Icons.TERMINAL, "Terminal SSH vers le Pi (session Claude)",
         VIOLET, _launch_ssh_terminal),
    ]
    accessory_row = ft.Container(
        content=ft.Row([
            ft.IconButton(
                icon, icon_size=CONSTANTS.ICON_LG,
                height=CONSTANTS.HUB_TITLEBAR_TAP_HEIGHT,
                icon_color=color, on_click=handler, tooltip=tip)
            for icon, tip, color, handler in _TITLEBAR_ACCESSORY_TOOLS
        ], spacing=0, tight=True),
        border=ft.Border.all(1, ORANGE), border_radius=8,
        margin=ft.Margin(0, 0, 8, 0),
    )
    accessory_menu = ft.Container(
        content=ft.PopupMenuButton(
            icon=ft.Icons.MORE_HORIZ, icon_color=ORANGE,
            icon_size=CONSTANTS.ICON_LG,
            tooltip="Autres actions (Bluetooth, impression, "
                    "navigateur, explorateur, terminal SSH)",
            items=[
                ft.PopupMenuItem(
                    content=ft.Row([
                        ft.Icon(icon, color=color, size=CONSTANTS.ICON_SM),
                        ft.Text(tip, size=CONSTANTS.TEXT_SM, color=WHITE),
                    ], spacing=8),
                    on_click=handler)
                for icon, tip, color, handler in _TITLEBAR_ACCESSORY_TOOLS
            ],
        ),
        border=ft.Border.all(1, ORANGE), border_radius=8,
        margin=ft.Margin(0, 0, 8, 0), visible=False,
    )

    titlebar = ft.Container(
        height=STRIP_HEIGHT,
        padding=ft.Padding(0, 0, 8, 0),
        content=ft.WindowDragArea(
            ft.Row([
                ft.Container(
                    content=ft.Row([
                        ft.Icon(ft.Icons.HUB_OUTLINED, color=ORANGE, size=CONSTANTS.ICON_SM),
                        ft.Text(f"HUB  {__version__}", size=CONSTANTS.TEXT_LG,
                                color=WHITE, weight=ft.FontWeight.W_500),
                    ], spacing=6),
                    padding=ft.Padding(16, 0, 0, 0),
                ),
                ft.IconButton(
                    icon=ft.Icons.SYSTEM_UPDATE_ALT,
                    tooltip="Mettre à jour (git pull --rebase)",
                    on_click=_update_app,
                    icon_color=LIGHT_GREY,
                    icon_size=CONSTANTS.ICON_SM,
                ),
                ft.Container(width=12),
                open_menu_btn,
                files_path,
                # Accès tactile : toujours visibles, quelle que soit la surface
                # active (écran tactile = pas de fallback clavier/raccourci).
                # accessory_row/accessory_menu : un seul des deux visible à
                # la fois, basculé par _apply_titlebar_width (resize).
                accessory_row,
                accessory_menu,
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
        # Échap efface la recherche active de la surface courante, QUE le
        # champ ait le focus ou non : l'usage normal est de chercher un
        # fichier puis de cliquer dessus pour le sélectionner, ce qui fait
        # perdre le focus du champ (retour user : Échap ne faisait plus
        # rien une fois la sélection commencée). Vérifié avant le
        # garde-fou _kb_suspend plus bas (qui ne s'applique qu'aux
        # raccourcis Ctrl+…/Suppr, pas à celui-ci) et avant tout dialogue
        # ouvert, pour ne pas voler l'Échap qui lui est destiné.
        if not ctrl and event.key == "Escape" and not _dialog_open():
            if state["surface"] == "files" and state.get("search"):
                _clear_search()
                return
            if state["surface"] == "liste" and liste_search["value"]:
                _liste_clear_search()
                return
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
    _apply_titlebar_width()   # état initial : pas d'attente du 1er resize

    # Aucun dossier sélectionné au lancement -> restaure les onglets
    # laissés ouverts à la fermeture précédente (retour user : un
    # redémarrage/une mise à jour ne doit pas faire perdre les dossiers
    # ouverts volontairement en cours de travail). À défaut, repli sur le
    # dernier dossier ouvert, sinon un dossier standard multiplateforme
    # (retour user : demander à l'IA de générer une image juste après le
    # lancement, sans dossier ouvert, faisait clignoter l'interface et
    # perdre le message — un dossier toujours ouvert évite cet état).
    if not state["folder"]:
        async def _initial_navigate():
            # Différé après le premier rendu : naviguer en synchrone ici
            # retardait l'apparition de la fenêtre de plusieurs secondes
            # quand le dernier dossier ouvert est un partage NAS lent
            # (os.path.isdir + scandir réseau AVANT le premier paint).
            # La coquille s'affiche d'abord, le dossier se remplit juste
            # derrière.
            await asyncio.sleep(0.05)
            saved_folders, saved_active = _startup_tabs, _startup_tabs_active
            saved_folders = [p for p in saved_folders
                             if p and os.path.isdir(p)]
            if saved_folders:
                # Le tout premier onglet (créé plus haut, vide) accueille
                # le premier dossier sauvegardé ; les suivants sont
                # ajoutés dans l'ordre où ils étaient ouverts. Contenu/
                # sélection restent chargés à la demande (cf. commentaire
                # de tête sur `tabs`), donc rien n'est scanné ici pour les
                # onglets qu'on ne restaure pas en tant qu'onglet actif.
                tabs[0]["folder"] = saved_folders[0]
                for folder in saved_folders[1:]:
                    _next_tab_id["n"] += 1
                    tabs.append({"id": _next_tab_id["n"], "folder": folder,
                                "selected": []})
                active_idx = (saved_active if 0 <= saved_active < len(tabs)
                              else 0)
                _restore_tab(tabs[active_idx]["id"])
                return
            default_folder = next(
                (p for p in _load_recent() if os.path.isdir(p)), None)
            if not default_folder:
                pictures = os.path.join(os.path.expanduser("~"), "Pictures")
                default_folder = (pictures if os.path.isdir(pictures)
                                  else os.path.expanduser("~"))
            _navigate(default_folder)

        page.run_task(_initial_navigate)

    page.run_task(_focus_active_surface)
    _mic_hotkey_start()

    # Scan initial synchrone (rapide, cf. _get_removable_drives) puis
    # relais par le thread de fond toutes les 3 s (comme Dashboard.pyw) :
    # le menu Ouvrir a donc toujours une liste prête, même au tout
    # premier clic après le lancement de Hub.
    drives_state["list"] = _get_removable_drives()
    threading.Thread(target=_poll_removable_drives, daemon=True).start()

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
