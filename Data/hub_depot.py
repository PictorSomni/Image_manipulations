# -*- coding: utf-8 -*-
"""Hub — Dépôt : fichiers envoyés depuis le téléphone ou la tablette
(tuile « Dépôt » de la web app), stockés sur le Pi comme les pièces
jointes des tâches (hub-sync /files/<DEPOT_ID>)."""

import hashlib
import os
import tempfile
import threading

import flet as ft

import CONSTANTS
import hub_sync
import thumb_cache

DEPOT_ID = hashlib.md5(b"depot").hexdigest()  # = DEPOT_ID de la web app
IMG_EXTS = (".jpg", ".jpeg", ".png", ".gif", ".webp", ".bmp",
            ".tif", ".tiff", ".heic", ".pdf")


def build(ui):
    page = ui.page
    temp = os.path.join(tempfile.gettempdir(), "hub_depot")
    sel = set()
    grid = ft.GridView(max_extent=170, spacing=8, run_spacing=8,
                       child_aspect_ratio=0.8, expand=True)
    status = ft.Text("", size=CONSTANTS.TEXT_SM, color=ui.LIGHT_GREY)
    names = []

    def _bg(work, done):
        def run():
            try:
                out = work()
            except Exception as exc:
                out = exc

            async def apply():
                done(out)
                page.update()
            page.run_task(apply)
        threading.Thread(target=run, daemon=True).start()

    def _local(n):
        path = os.path.join(temp, n)
        if not os.path.exists(path):
            os.makedirs(temp, exist_ok=True)
            with open(path, "wb") as f:
                f.write(hub_sync.file_req("GET", DEPOT_ID, n))
        return path

    def _targets():
        return sorted(sel) or list(names)

    def _tile(n, thumb):
        on = n in sel
        img = (ft.Image(src=thumb, fit=ft.BoxFit.COVER, expand=True,
                        border_radius=CONSTANTS.BUTTON_RADIUS) if thumb
               else ft.Container(ft.Icon(ft.Icons.INSERT_DRIVE_FILE,
                                         size=48, color=ui.LIGHT_GREY),
                                 expand=True,
                                 alignment=ft.Alignment.CENTER))

        def toggle(e):
            sel.symmetric_difference_update({n})
            _draw()
            page.update()

        def view(e):
            ext = os.path.splitext(n)[1].lower()
            _bg(lambda: _local(n), lambda p: None if isinstance(
                p, Exception) else (ui._open_viewer(p) if ext in IMG_EXTS
                                    else ui._open_file_default(p)))
        return ft.GestureDetector(ft.Container(
            ft.Column([img, ft.Text(n, size=11, color=ui.WHITE,
                                    max_lines=2, no_wrap=False)],
                      spacing=4),
            padding=6, border_radius=CONSTANTS.BUTTON_RADIUS,
            bgcolor=ui.ORANGE if on else ui.DARK,
            border=ft.Border.all(2, ui.ORANGE if on else ui.GREY)),
            on_tap=toggle, on_double_tap=view,
            mouse_cursor=ft.MouseCursor.CLICK)

    thumbs = {}

    def _draw():
        grid.controls = [_tile(n, thumbs.get(n)) for n in names]
        status.value = (f"{len(sel)} sélectionné(s)" if sel else
                        f"{len(names)} fichier(s)" if names else
                        "Dépôt vide")

    def _load():
        got = hub_sync.list_files(DEPOT_ID)
        for n in got:
            if n not in thumbs and os.path.splitext(n)[1].lower() \
                    in IMG_EXTS:
                try:
                    thumbs[n] = thumb_cache.get_or_generate(
                        _local(n), size_px=320)
                except Exception:
                    thumbs[n] = None
        return got

    def _loaded(got):
        if isinstance(got, Exception):
            status.value = f"Pi injoignable : {got}"
            return
        names[:] = got
        sel.intersection_update(got)
        _draw()

    def refresh(e=None):
        status.value = "Chargement…"
        page.update()
        _bg(_load, _loaded)

    def _copy(folder):
        todo = _targets()
        if not folder or not todo:
            return

        def work():
            import shutil
            for n in todo:
                shutil.copy2(_local(n), os.path.join(folder, n))
            return folder

        def done(out):
            if isinstance(out, Exception):
                status.value = f"Erreur : {out}"
                return
            status.value = f"{len(todo)} copié(s) dans {out}"
            if out == ui.state.get("folder"):
                ui._refresh_folder()
        status.value = "Copie…"
        page.update()
        _bg(work, done)

    async def save_as(e):
        _copy(await ft.FilePicker().get_directory_path(
            dialog_title="Copier dans",
            initial_directory=ui.state.get("folder") or None))

    def delete(e):
        todo = sorted(sel)  # jamais « tout » sans sélection explicite
        if not todo:
            status.value = "Sélectionne d'abord les fichiers à supprimer"
            page.update()
            return

        def work():
            for n in todo:
                hub_sync.file_req("DELETE", DEPOT_ID, n)
                thumbs.pop(n, None)
            return _load()
        sel.clear()
        _bg(work, _loaded)

    def btn(text, icon, color, on_click):
        return ft.TextButton(text, icon=icon, on_click=on_click,
                             style=ft.ButtonStyle(color=color))

    dlg = ui._dialog(
        title=ft.Text("Dépôt"), bar_color=ui.ORANGE,
        content=ft.Container(ft.Column([grid, status], spacing=8),
                             width=760, height=520),
        actions=[
            btn("Dossier en cours", ft.Icons.DOWNLOAD, ui.WHITE,
                lambda e: _copy(ui.state.get("folder"))),
            btn("Copier dans…", ft.Icons.DRIVE_FOLDER_UPLOAD_OUTLINED,
                ui.WHITE, save_as),
            btn("Supprimer", ft.Icons.DELETE_OUTLINE, ui.RED, delete),
            btn("Actualiser", ft.Icons.REFRESH, ui.WHITE, refresh),
            btn("Fermer", ft.Icons.CLOSE, ui.WHITE, lambda e: close()),
        ])

    def close():
        dlg.open = False
        page.update()

    def open_depot(e=None):
        if dlg not in page.overlay:
            page.overlay.append(dlg)
        dlg.open = True
        refresh()

    return open_depot
