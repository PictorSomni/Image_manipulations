# -*- coding: utf-8 -*-
"""Onglet Redresser de Retouche photo : on trace des lignes sur la photo,
chacune devient horizontale ou verticale selon son orientation dominante
(rotation + perspective, comme Guided Upright), avec une force réglable
de 0 à 100 %. Enregistré dans le fichier, original copié dans ORIGINAUX/.
"""

__version__ = "2.6.3"

import asyncio
import base64
import io
import os
import shutil

import flet as ft
import flet.canvas as cv
import numpy as np
from PIL import Image, ImageOps

import CONSTANTS
import image_ops
import ui_helpers

DARK = CONSTANTS.COLOR_DARK
GREY = CONSTANTS.COLOR_GREY
WHITE = CONSTANTS.COLOR_WHITE
LIGHT_GREY = CONSTANTS.COLOR_LIGHT_GREY
BLUE = CONSTANTS.COLOR_BLUE
VIOLET = CONSTANTS.COLOR_VIOLET
YELLOW = CONSTANTS.COLOR_YELLOW
ORANGE = CONSTANTS.COLOR_ORANGE

PANEL_W = 340
_PROXY = 1600
_BLANK = "data:image/gif;base64,R0lGODlhAQABAAD/ACwAAAAAAQABAAACADs="


def _decode(path):
    img = Image.open(path)
    icc = img.info.get("icc_profile")
    img = ImageOps.exif_transpose(img)
    if icc or img.mode == "CMYK":
        img = image_ops.convert_to_srgb(img, icc)
    return img.convert("RGB")


class RedresserTab:
    """`view` à poser dans l'hôte ; `show(path)` charge une photo,
    `on_saved(name)` est appelé après enregistrement."""

    def __init__(self, page, on_saved):
        self.page = page
        self.on_saved = on_saved
        self.path = None
        self.proxy = None
        self.lines = []          # fractions ((x0, y0), (x1, y1))
        self.params = np.zeros(4)
        self.matrix = np.eye(3)  # proxy source → proxy sortie
        self.drag = None
        self.disp = (800, 600)   # taille d'affichage de l'aperçu

        self.image = ft.Image(src=_BLANK, gapless_playback=True,
                              fit=ft.BoxFit.FILL)
        self.canvas = cv.Canvas(shapes=[])
        self.gesture = ft.GestureDetector(
            content=ft.Container(bgcolor=ft.Colors.TRANSPARENT),
            on_pan_start=self._pan_start, on_pan_update=self._pan_update,
            on_pan_end=self._pan_end, drag_interval=16)
        self.stack = ft.Stack([self.image, self.canvas, self.gesture])
        self.veil = ui_helpers.busy_veil("Redressement…", VIOLET)
        self.veil.visible = False

        self.strength = ft.Slider(
            min=0, max=100, value=100, expand=True,
            active_color=VIOLET, on_change=self._on_strength,
            on_change_end=lambda e: self._render())
        self.strength_val = ft.Text("100 %", size=12, color=WHITE,
                                    weight=ft.FontWeight.W_500)
        self.count = ft.Text("", size=12, color=LIGHT_GREY)
        self.save_btn = self._btn("Enregistrer", ft.Icons.SAVE_OUTLINED,
                                  VIOLET, self._save)
        self.status = ft.Text("", size=12, color=LIGHT_GREY)

        zone = ft.Container(
            content=ft.Column([
                ft.Text("REDRESSER", size=CONSTANTS.TEXT_SM - 2,
                        color=VIOLET, weight=ft.FontWeight.W_600),
                self.count,
                ft.Row([ft.Text("Force", size=12, color=LIGHT_GREY),
                        self.strength_val],
                       alignment=ft.MainAxisAlignment.SPACE_BETWEEN),
                ft.Row([self.strength]),
                self._btn("Annuler la dernière ligne", ft.Icons.UNDO, GREY,
                          self._undo, color=WHITE),
                self._btn("Effacer les lignes", ft.Icons.CLEAR_ALL, GREY,
                          self._clear, color=WHITE),
            ], spacing=8, horizontal_alignment=ft.CrossAxisAlignment.STRETCH),
            border=ft.Border(left=ft.BorderSide(3, VIOLET)),
            padding=ft.Padding(CONSTANTS.SPACE_SM, CONSTANTS.SPACE_XS, 0,
                               CONSTANTS.SPACE_XS))
        panel = ft.Container(
            content=ft.Column([
                zone,
                ft.Container(expand=True),
                ft.Divider(height=1, color=GREY),
                ft.Row([self.save_btn]),
                self.status,
            ], spacing=CONSTANTS.SPACE_MD),
            width=PANEL_W, padding=CONSTANTS.SPACE_MD, bgcolor=DARK)
        self.view = ft.Row([
            ft.Container(
                content=ft.Stack([ft.Container(self.stack,
                                               alignment=ft.Alignment.CENTER,
                                               expand=True),
                                  self.veil], expand=True),
                expand=True, bgcolor="#1e1e1e", border_radius=8,
                margin=ft.Margin(CONSTANTS.SPACE_MD, CONSTANTS.SPACE_MD, 0,
                                 0)),
            panel,
        ], expand=True, spacing=CONSTANTS.SPACE_LG,
            vertical_alignment=ft.CrossAxisAlignment.STRETCH)
        self._refresh_controls()

    def _btn(self, label, icon, bg, handler, color=DARK):
        return ft.FilledButton(
            label, icon=icon, on_click=handler, bgcolor=bg, color=color,
            height=CONSTANTS.TOUCH_TARGET, expand=True,
            style=ft.ButtonStyle(shape=ft.RoundedRectangleBorder(
                radius=CONSTANTS.BUTTON_RADIUS)))

    # ── Chargement / taille ──────────────────────────────────────────
    def resize(self, avail_w, avail_h):
        self.disp_box = (max(200, avail_w), max(200, avail_h))
        if self.proxy is not None:
            self._fit()
            self._render()

    def _fit(self):
        bw, bh = getattr(self, "disp_box", (800, 600))
        pw, ph = self.proxy.size
        k = min(bw / pw, bh / ph)
        self.disp = (int(pw * k), int(ph * k))
        for c in (self.stack, self.image, self.canvas, self.gesture.content):
            c.width, c.height = self.disp

    async def show(self, path):
        self.path = path
        self.lines = []
        self.params = np.zeros(4)
        self.strength.value = 100
        self.strength_val.value = "100 %"
        self.status.value = ""
        async with ui_helpers.slow_veil(self.page, self.veil):
            img = await asyncio.to_thread(_decode, path)
            img.thumbnail((_PROXY, _PROXY), Image.LANCZOS)
            self.proxy = img
            self._fit()
            self._render()

    # ── Rendu ────────────────────────────────────────────────────────
    def _render(self):
        if self.proxy is None:
            return
        w, h = self.proxy.size
        s = self.strength.value / 100
        self.matrix = image_ops.upright_homography(self.params, w, h, s)
        out = image_ops.apply_upright(self.proxy, self.lines, s,
                                      params=self.params)
        out = out.resize(self.disp, Image.LANCZOS)
        buf = io.BytesIO()
        image_ops.to_display_profile(out).save(buf, "JPEG", quality=90)
        self.image.src = ("data:image/jpeg;base64,"
                          + base64.b64encode(buf.getvalue()).decode())
        self._draw_lines()
        self._refresh_controls()
        self.page.update()

    def _to_disp(self, fx, fy):
        w, h = self.proxy.size
        x, y = image_ops._project(self.matrix, [(fx * w, fy * h)])[0]
        return x * self.disp[0] / w, y * self.disp[1] / h

    def _from_disp(self, dx, dy):
        w, h = self.proxy.size
        pt = (dx * w / self.disp[0], dy * h / self.disp[1])
        x, y = image_ops._project(np.linalg.inv(self.matrix), [pt])[0]
        return x / w, y / h

    def _draw_lines(self, extra=None):
        shapes = []
        for line in self.lines:
            a = self._to_disp(*line[0])
            b = self._to_disp(*line[1])
            color = (YELLOW if image_ops.line_is_horizontal(line)
                     else BLUE)
            shapes.append(cv.Line(*a, *b, paint=ft.Paint(
                color=color, stroke_width=2)))
            for px, py in (a, b):
                shapes.append(cv.Circle(px, py, 4, paint=ft.Paint(
                    color=color)))
        if extra:
            shapes.append(cv.Line(*extra[0], *extra[1], paint=ft.Paint(
                color=WHITE, stroke_width=2)))
        self.canvas.shapes = shapes

    def _refresh_controls(self):
        n = len(self.lines)
        self.count.value = (f"{n} ligne{'s' if n > 1 else ''}" if n
                            else "Aucune ligne")
        self.save_btn.disabled = not n or not self.strength.value

    # ── Tracé des lignes ─────────────────────────────────────────────
    def _pan_start(self, e):
        p = (e.local_position.x, e.local_position.y)
        self.drag = [p, p]

    def _pan_update(self, e):
        if self.drag is None:
            return
        self.drag[1] = (e.local_position.x, e.local_position.y)
        self._draw_lines(self.drag)
        self.canvas.update()

    def _pan_end(self, e):
        drag, self.drag = self.drag, None
        if drag is None or self.proxy is None:
            return
        (x0, y0), (x1, y1) = drag
        if np.hypot(x1 - x0, y1 - y0) < 20:
            self._draw_lines()
            self.canvas.update()
            return
        self.lines.append((self._from_disp(x0, y0), self._from_disp(x1, y1)))
        self._solve()

    def _solve(self):
        w, h = self.proxy.size
        self.params = image_ops.upright_params(self.lines, w, h)
        self._render()

    def _undo(self, e):
        if self.lines:
            self.lines.pop()
            self._solve()

    def _clear(self, e):
        self.lines = []
        self._solve()

    def _on_strength(self, e):
        self.strength_val.value = f"{int(self.strength.value)} %"
        self.strength_val.update()

    # ── Enregistrement ───────────────────────────────────────────────
    async def _save(self, e):
        if not self.lines or self.path is None:
            return
        path = self.path
        s = self.strength.value / 100
        self.veil.visible = True
        self.page.update()
        try:
            await asyncio.to_thread(self._write, path, s)
            self.status.value = f"[OK] {os.path.basename(path)} redressée"
        except Exception as ex:
            self.status.value = f"[ERREUR] {ex}"
            self.veil.visible = False
            self.page.update()
            return
        self.veil.visible = False
        self.on_saved(os.path.basename(path))
        status = self.status.value
        await self.show(path)
        self.status.value = status
        self.page.update()

    def _write(self, path, strength):
        full = _decode(path)
        w, h = full.size
        # Lignes en fractions : même géométrie quelle que soit la taille.
        params = image_ops.upright_params(self.lines, w, h)
        out = image_ops.apply_upright(full, self.lines, strength,
                                      params=params)
        backup_dir = os.path.join(os.path.dirname(path), "ORIGINAUX")
        backup = os.path.join(backup_dir, os.path.basename(path))
        if not os.path.exists(backup):
            os.makedirs(backup_dir, exist_ok=True)
            shutil.copy2(path, backup)
        ext = os.path.splitext(path)[1].lower()
        fmt = {".png": "PNG", ".tif": "TIFF", ".tiff": "TIFF"}.get(ext,
                                                                   "JPEG")
        extra = ({"quality": 100, "subsampling": 0} if fmt == "JPEG"
                 else {})
        out.save(path, format=fmt, dpi=(CONSTANTS.DPI, CONSTANTS.DPI),
                 icc_profile=image_ops._SRGB_ICC, **extra)
