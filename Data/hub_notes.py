# -*- coding: utf-8 -*-
"""Hub — Bloc-notes (.notes.md partagé).

Section extraite de Hub.pyw (main) : build(ui) reçoit l'espace de
noms de main (ui) et renvoie les noms utilisés ailleurs dans Hub."""


from ai_tools import _backup_file
import CONSTANTS
import asyncio
import flet as ft
import flet_code_editor as fce
import os
import platform
import subprocess
import sys


def build(ui):
    BACKGROUND = ui.BACKGROUND
    DARK = ui.DARK
    GREY = ui.GREY
    ICON_ACTION = ui.ICON_ACTION
    LIGHT_GREY = ui.LIGHT_GREY
    ORANGE = ui.ORANGE
    RED = ui.RED
    VIOLET = ui.VIOLET
    WHITE = ui.WHITE
    _APP_DIR = ui._APP_DIR
    __file__ = ui.__file__
    _dialog = ui._dialog
    _dlg_btn = ui._dlg_btn
    _run_task = ui._run_task
    page = ui.page
    state = ui.state
    _focus_active_surface = ui.late__focus_active_surface
    _log_to_terminal = ui.late__log_to_terminal
    _sync_notes_btn = ui.late__sync_notes_btn
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
            color=WHITE,
            border=CONSTANTS.input_border(ft.Colors.TRANSPARENT, radius=6),
            bgcolor=DARK, filled=True,
            hint_text="Écrivez vos notes ici…",
            hint_style=ft.TextStyle(color=LIGHT_GREY, italic=True),
        )
        notes_editor_content = notes_field
    notes_title = ft.Text("Bloc-notes", size=CONSTANTS.TEXT_LG, color=VIOLET,
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
        note_target["truncated"] = False
        try:
            if os.path.exists(path):
                size = os.path.getsize(path)
                if size > CONSTANTS.NOTEPAD_MAX_LOAD_BYTES:
                    # Un gros fichier (ex. .mcp_errors.log sans rotation
                    # avant ce fix) chargé en entier gelait l'UI le temps
                    # du rendu, surtout dans l'éditeur avec coloration
                    # syntaxique (retour user) — on ne charge que la fin,
                    # comme le journal du terminal (HUB_TERMINAL_LOG_
                    # MAX_BYTES). Lecture seule : sauvegarder ce buffer
                    # tronqué écraserait le reste du fichier sur disque.
                    with open(path, "rb") as f:
                        f.seek(-CONSTANTS.NOTEPAD_MAX_LOAD_BYTES, os.SEEK_END)
                        tail = f.read().decode("utf-8", errors="replace")
                    kb = CONSTANTS.NOTEPAD_MAX_LOAD_BYTES // 1000
                    notes_field.value = (
                        f"[Fichier tronqué : {size / 1e6:.1f} Mo au total, "
                        f"seules les {kb} derniers ko sont affichés ici, en "
                        "lecture seule]\n\n" + tail)
                    note_target["truncated"] = True
                else:
                    with open(path, "r", encoding="utf-8") as f:
                        notes_field.value = f.read()
            else:
                notes_field.value = ""
        except Exception:
            notes_field.value = ""
        notes_field.disabled = note_target["truncated"]
        notes_dirty["value"] = False

    def _notes_save(event=None):
        path = note_target["path"]
        if note_target.get("truncated"):
            # Filet de sécurité : même si le champ est désactivé (donc
            # normalement pas modifiable), l'autosave différé ne doit
            # jamais pouvoir réécrire le fichier avec le seul extrait
            # chargé en mémoire.
            return
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
                # await asyncio.sleep, pas time.sleep : cette coroutine
                # tourne sur la boucle asyncio (page.run_task) — un sleep
                # bloquant gèlerait toute autre mise à jour UI en attente
                # pendant ce temps (retour audit).
                await asyncio.sleep(0.4)
                subprocess.Popen([sys.executable, hub_path])
                await asyncio.sleep(0.2)
                try:
                    await page.window.close()
                except Exception:
                    pass
                os._exit(0)
            _run_task(_restart_async)

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
        notes_autosave_timer["task"] = _run_task(_notes_autosave_after_delay)

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
        _show_notes_panel()

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

        dlg = _dialog(
            title=ft.Text("Modifications non enregistrées", size=CONSTANTS.TEXT_SM,
                          color=WHITE),
            content=ft.Text(
                f"Enregistrer les modifications de {current_name} avant "
                f"de recharger le bloc-notes ?", size=CONSTANTS.TEXT_SM, color=WHITE),
            actions=[
                _dlg_btn("Annuler", "cancel", on_click=_cancel),
                _dlg_btn("Ne pas enregistrer", "danger",
                         on_click=_do_home(True)),
                _dlg_btn("Enregistrer", "primary", on_click=_do_home(False)),
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

    # Bandeau en bas (comme terminal_panel), pas surface plein écran
    # (retour user) : reste replié à CONSTANTS.HUB_TERMINAL_HEIGHT par
    # défaut, mais avec une poignée en haut pour l'ajuster (retour user).
    _NOTES_MIN_HEIGHT, _NOTES_MAX_HEIGHT = 120, 700

    def _on_notes_resize(e):
        # Glisser vers le haut (delta.y négatif) doit agrandir le bandeau
        # ancré en bas — même logique que _on_resize_edge de Recadrage
        # manuel.pyw, sans le -> % (ici une hauteur en px directe).
        notes_panel.height = max(_NOTES_MIN_HEIGHT, min(
            _NOTES_MAX_HEIGHT, notes_panel.height - e.local_delta.y))
        notes_panel.update()

    notes_resize_handle = ft.GestureDetector(
        content=ft.Container(height=6, bgcolor=VIOLET),
        mouse_cursor=ft.MouseCursor.RESIZE_UP_DOWN,
        on_pan_update=_on_notes_resize,
    )

    notes_panel = ft.Container(
        content=ft.Column([notes_resize_handle, notes_surface],
                          spacing=0, expand=True),
        bgcolor=DARK, height=CONSTANTS.HUB_TERMINAL_HEIGHT, visible=False,
    )

    def _show_notes_panel():
        """Ouvre le panneau Notes sans toucher à l'onglet actif (Fichiers/
        Liste/IA reste affiché à côté) — remplace les anciens passages par
        _select_surface("notes")."""
        notes_panel.visible = True
        _sync_notes_btn()
        page.update()
        _run_task(_focus_active_surface)

    def _toggle_notes(event):
        notes_panel.visible = not notes_panel.visible
        if not notes_panel.visible:
            _notes_save()   # comme l'ancien changement d'onglet
        _sync_notes_btn()
        page.update()
        _run_task(_focus_active_surface)

    return {
        "_constants_path": _constants_path,
        "_notes_load": _notes_load,
        "_notes_save": _notes_save,
        "_open_path_in_notes": _open_path_in_notes,
        "_show_notes_panel": _show_notes_panel,
        "_toggle_notes": _toggle_notes,
        "note_target": note_target,
        "notes_field": notes_field,
        "notes_is_preview": notes_is_preview,
        "notes_panel": notes_panel,
        "notes_preview": notes_preview,
    }
