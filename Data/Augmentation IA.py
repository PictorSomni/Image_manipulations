# -*- coding: utf-8 -*-
"""
Retouche IA par sélection — v1.0
==================================

Sélectionnez une zone d'une image et envoyez-la à Gemini (Nano Banana 2 /
gemini-3.1-flash-image-preview) pour la modifier, puis réintégrez le résultat
dans l'image originale à taille exacte.

Flux de travail :
  1. L'image s'ouvre depuis FOLDER_PATH / SELECTED_FILES (env) ou via Ouvrir…
  2. Tracez un rectangle de sélection : clic gauche + glisser
  3. Décrivez la retouche dans le champ texte
  4. Cliquez « Envoyer à Gemini »
  5. La zone modifiée est réintégrée dans l'image à ses dimensions exactes
  6. Annulez (Ctrl+Z) ou Enregistrez / Enregistrez sous…

Dépendances :
  flet, Pillow, google-genai (pip install google-genai)

Variables d'environnement reconnues :
  GEMINI_API_KEY  — clé d'API Gemini (ou fichier .env)
  FOLDER_PATH     — dossier source des images
  SELECTED_FILES  — noms de fichiers séparés par « | »
"""

__version__ = "2.8.1"

import flet as ft
import flet.canvas as cv
import os
import io
import base64
import asyncio
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))
import CONSTANTS
from ai_tools import _gemini_generate_image

from PIL import Image

###############################################################
#                        PALETTE                              #
###############################################################
DARK       = CONSTANTS.COLOR_DARK
BG_UI      = CONSTANTS.COLOR_BACKGROUND
GREY       = CONSTANTS.COLOR_GREY
LIGHT_GREY = CONSTANTS.COLOR_LIGHT_GREY
BLUE       = CONSTANTS.COLOR_BLUE
GREEN      = CONSTANTS.COLOR_GREEN
ORANGE     = CONSTANTS.COLOR_ORANGE
RED        = CONSTANTS.COLOR_RED
WHITE      = CONSTANTS.COLOR_WHITE

IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".tiff", ".tif", ".bmp", ".webp"}
DPI = CONSTANTS.DPI

###############################################################
#                       UTILITAIRES                           #
###############################################################

def image_to_b64(img: Image.Image, fmt: str = "JPEG", quality: int = 92) -> str:
    buf = io.BytesIO()
    if fmt == "JPEG" and img.mode in ("RGBA", "LA", "P"):
        img = img.convert("RGB")
    img.save(buf, format=fmt, quality=quality)
    return base64.b64encode(buf.getvalue()).decode("utf-8")


###############################################################
#                       INTERFACE                             #
###############################################################

async def main(page: ft.Page) -> None:
    page.title = f"Retouche IA par sélection  v{__version__}"
    page.theme_mode = ft.ThemeMode.DARK
    page.bgcolor = BG_UI
    await page.window.to_front()

    # ── Collecte des images ──────────────────────────────────────────────────
    source_folder: str = os.environ.get(
        "FOLDER_PATH", os.path.dirname(os.path.abspath(__file__))
    )
    selected_env: str = os.environ.get("SELECTED_FILES", "")

    all_images: list[str] = []
    if os.path.isdir(source_folder):
        preferred = set(selected_env.split("|")) if selected_env else set()
        all_images = sorted(
            [
                e.path
                for e in os.scandir(source_folder)
                if os.path.splitext(e.name)[1].lower() in IMAGE_EXTENSIONS
                and (not preferred or os.path.basename(e.path) in preferred)
            ],
            key=lambda p: os.path.basename(p).lower(),
        )

    # ── État ─────────────────────────────────────────────────────────────────
    state: dict = {
        "index":        0,
        "source_path":  None,
        "orig_img":     None,
        "work_img":     None,
        "undo_img":     None,
        "selection":    None,   # (x1, y1, x2, y2) en coordonnées IMAGE
        "drag_start":   None,   # (cx, cy) canvas — début rubber band
        "drag_current": None,   # (cx, cy) canvas — position courante
        "render_info":  None,   # (tw, th, ox, oy, sx, sy)
        "view_size":    (1200, 800),
        "working":      False,
        "sel_mode":     False,  # True = sélection, False = navigation
    }

    # ── Éléments UI ──────────────────────────────────────────────────────────
    status_text    = ft.Text("", size=12, color=LIGHT_GREY)
    image_label    = ft.Text("—", size=13, color=WHITE, expand=True,
                             text_align=ft.TextAlign.CENTER)
    counter_text   = ft.Text("", size=12, color=LIGHT_GREY)
    progress_bar   = ft.ProgressBar(color=BLUE, bgcolor=GREY, visible=False)
    sel_info       = ft.Text(
        "Aucune sélection — clic + glisser pour définir une zone",
        size=11, color=LIGHT_GREY,
    )

    prompt_field = ft.TextField(
        label="Décrivez la retouche souhaitée",
        hint_text='ex : "Remplace le ciel par un coucher de soleil"',
        multiline=True,
        min_lines=3,
        max_lines=6,
        bgcolor=GREY,
        border_color=LIGHT_GREY,
        focused_border_color=BLUE,
        color=WHITE,
        label_style=ft.TextStyle(color=LIGHT_GREY),
    )

    preview_img = ft.Image(
        src="data:image/gif;base64,R0lGODlhAQABAAD/ACwAAAAAAQABAAACADs=",
        fit=ft.BoxFit.NONE,
        gapless_playback=True,
        visible=False,
    )

    sel_canvas = cv.Canvas(expand=True, shapes=[])

    preview_placeholder = ft.Container(
        content=ft.Column(
            [
                ft.Icon(ft.Icons.PHOTO_CAMERA, size=56, color=LIGHT_GREY),
                ft.Text("Aucune image chargée", color=LIGHT_GREY, size=13),
                ft.Text(
                    "Ouvrez une image ou placez-en dans le dossier lancé",
                    color=LIGHT_GREY, size=11,
                ),
            ],
            horizontal_alignment=ft.CrossAxisAlignment.CENTER,
            alignment=ft.MainAxisAlignment.CENTER,
            spacing=12,
        ),
        expand=True,
        alignment=ft.Alignment(0, 0),
        border=ft.Border.all(1, GREY),
        border_radius=8,
        bgcolor=DARK,
    )

    send_btn = ft.Button(
        "Envoyer à Gemini",
        icon=ft.Icons.AUTO_FIX_HIGH,
        bgcolor=BLUE,
        color=DARK,
        disabled=True,
        tooltip="Envoyer la sélection à Gemini pour modification",
    )
    undo_btn = ft.Button(
        "Annuler la retouche",
        icon=ft.Icons.UNDO,
        bgcolor=GREY,
        color=ORANGE,
        disabled=True,
        tooltip="Revenir à l'état avant la dernière retouche Gemini",
    )
    save_btn = ft.Button(
        "Enregistrer",
        icon=ft.Icons.SAVE,
        style=ft.ButtonStyle(
            bgcolor={
                ft.ControlState.DEFAULT:  GREEN,
                ft.ControlState.DISABLED: GREY,
            },
            color={
                ft.ControlState.DEFAULT:  WHITE,
                ft.ControlState.DISABLED: LIGHT_GREY,
            },
        ),
        disabled=True,
        tooltip="Écraser le fichier original",
    )
    saveas_btn = ft.Button(
        "Enregistrer sous…",
        icon=ft.Icons.SAVE_AS,
        bgcolor=GREY,
        color=WHITE,
        disabled=True,
        tooltip="Sauvegarder sous un nouveau nom ou emplacement",
    )
    open_btn = ft.Button(
        "Ouvrir une image",
        icon=ft.Icons.FOLDER_OPEN,
        bgcolor=GREY,
        color=WHITE,
    )
    prev_btn = ft.IconButton(
        icon=ft.Icons.CHEVRON_LEFT,
        icon_color=WHITE,
        bgcolor=GREY,
        disabled=True,
        tooltip="Image précédente",
    )
    next_btn = ft.IconButton(
        icon=ft.Icons.CHEVRON_RIGHT,
        icon_color=WHITE,
        bgcolor=GREY,
        disabled=True,
        tooltip="Image suivante",
    )
    clear_sel_btn = ft.TextButton(
        "Effacer la sélection",
        icon=ft.Icons.CLEAR,
        style=ft.ButtonStyle(color=LIGHT_GREY),
    )

    # ── Helpers de rendu ─────────────────────────────────────────────────────

    def _compute_render_info() -> None:
        img = state["work_img"] or state["orig_img"]
        if img is None:
            state["render_info"] = None
            return
        vw, vh = state["view_size"]
        ow, oh = img.size
        scale = min(vw / ow, vh / oh)
        tw = round(ow * scale)
        th = round(oh * scale)
        ox = (vw - tw) // 2
        oy = (vh - th) // 2
        state["render_info"] = (tw, th, ox, oy, scale, scale)

    def _display_to_image(cx: float, cy: float) -> tuple[int | None, int | None]:
        info = state["render_info"]
        if info is None:
            return None, None
        _, _, ox, oy, sx, sy = info
        img = state["orig_img"]
        ix = max(0, min(round((cx - ox) / sx), img.width  - 1))
        iy = max(0, min(round((cy - oy) / sy), img.height - 1))
        return ix, iy

    def _image_to_display(ix: int, iy: int) -> tuple[float, float]:
        info = state["render_info"]
        if info is None:
            return 0.0, 0.0
        _, _, ox, oy, sx, sy = info
        return ix * sx + ox, iy * sy + oy

    def _render_preview() -> None:
        img = state["work_img"] or state["orig_img"]
        if img is None:
            return
        _compute_render_info()
        info = state["render_info"]
        if info is None:
            return
        tw, th, ox, oy, sx, sy = info
        vw, vh = state["view_size"]

        thumb = img.convert("RGB").resize((tw, th), Image.Resampling.BILINEAR)
        canvas_img = Image.new("RGB", (vw, vh), (30, 30, 30))
        canvas_img.paste(thumb, (ox, oy))

        preview_img.src = f"data:image/jpeg;base64,{image_to_b64(canvas_img)}"
        preview_img.width        = vw
        preview_img.height       = vh
        preview_img.visible      = True
        sel_canvas.width         = vw
        sel_canvas.height        = vh
        image_gesture.width      = vw
        image_gesture.height     = vh
        inner_container.width    = vw
        inner_container.height   = vh
        preview_placeholder.visible = False
        _update_sel_canvas()
        page.update()

    def _update_sel_canvas() -> None:
        """Redessine le rectangle de sélection sur le canvas overlay Flet."""
        info = state["render_info"]
        sel_canvas.shapes.clear()
        if info is None:
            sel_canvas.update()
            return
        tw, th, ox, oy, *_ = info

        sel_display: tuple | None = None
        if state["drag_start"] is not None and state["drag_current"] is not None:
            x1 = min(state["drag_start"][0],  state["drag_current"][0])
            y1 = min(state["drag_start"][1],  state["drag_current"][1])
            x2 = max(state["drag_start"][0],  state["drag_current"][0])
            y2 = max(state["drag_start"][1],  state["drag_current"][1])
            sel_display = (x1, y1, x2, y2)
        elif state["selection"] is not None:
            dx1, dy1 = _image_to_display(state["selection"][0], state["selection"][1])
            dx2, dy2 = _image_to_display(state["selection"][2], state["selection"][3])
            sel_display = (dx1, dy1, dx2, dy2)

        if sel_display is not None:
            x1, y1, x2, y2 = sel_display
            x1 = max(ox, x1);  y1 = max(oy, y1)
            x2 = min(ox + tw, x2);  y2 = min(oy + th, y2)
            if x2 > x1 and y2 > y1:
                w, h = x2 - x1, y2 - y1
                sel_canvas.shapes.append(
                    cv.Rect(x=x1, y=y1, width=w, height=h,
                            paint=ft.Paint(
                                color=ft.Colors.with_opacity(0.18, ft.Colors.BLUE_400),
                                style=ft.PaintingStyle.FILL))
                )
                sel_canvas.shapes.append(
                    cv.Rect(x=x1, y=y1, width=w, height=h,
                            paint=ft.Paint(
                                color=ft.Colors.BLUE_400,
                                style=ft.PaintingStyle.STROKE,
                                stroke_width=2.0))
                )
        sel_canvas.update()

    # ── Chargement d'image ───────────────────────────────────────────────────

    async def _load_image_path(path: str) -> None:
        try:
            img = Image.open(path)
            img.load()
            if img.mode not in ("RGB", "RGBA"):
                img = img.convert("RGB")
            state["source_path"]     = path
            state["orig_img"]        = img.copy()
            state["work_img"]        = img.copy()
            state["undo_img"]        = None
            state["selection"]       = None
            state["drag_start"]      = None
            state["drag_current"]    = None
            state["zoom"]            = 1.0
            state["pan_offset"]      = (0.0, 0.0)
            state["pan_drag_origin"] = None

            image_label.value  = os.path.basename(path)
            status_text.value  = f"{img.width} × {img.height} px"
            sel_info.value     = "Aucune sélection — clic + glisser pour définir une zone"
            send_btn.disabled  = True
            undo_btn.disabled  = True
            save_btn.disabled  = True
            saveas_btn.disabled = True
            _render_preview()
        except Exception as ex:
            status_text.value = f"[ERREUR] {ex}"
            page.update()

    async def _load_image(index: int) -> None:
        if not all_images or not (0 <= index < len(all_images)):
            return
        state["index"] = index
        counter_text.value  = f"{index + 1} / {len(all_images)}"
        prev_btn.disabled   = (index == 0)
        next_btn.disabled   = (index >= len(all_images) - 1)
        await _load_image_path(all_images[index])

    # ── Rubber band ──────────────────────────────────────────────────────────

    # ── Rubber band (mode sélection uniquement) ──────────────────────────────

    def _on_pan_start(e) -> None:
        if not state["sel_mode"] or state["orig_img"] is None or state["working"]:
            return
        cx, cy = float(e.local_position.x), float(e.local_position.y)
        state["drag_start"]   = (cx, cy)
        state["drag_current"] = (cx, cy)

    def _on_pan_update(e) -> None:
        if not state["sel_mode"] or state["drag_start"] is None or state["working"]:
            return
        # local_position = position courante en espace content (pré-transform IV)
        state["drag_current"] = (float(e.local_position.x), float(e.local_position.y))
        _update_sel_canvas()

    def _on_pan_end(e) -> None:
        if not state["sel_mode"] or state["drag_start"] is None:
            return
        x1d, y1d = state["drag_start"]
        x2d, y2d = state["drag_current"] or state["drag_start"]
        state["drag_start"]   = None
        state["drag_current"] = None

        ix1, iy1 = _display_to_image(min(x1d, x2d), min(y1d, y2d))
        ix2, iy2 = _display_to_image(max(x1d, x2d), max(y1d, y2d))

        if (ix1 is not None and ix2 is not None and
                iy1 is not None and iy2 is not None and
                (ix2 - ix1) > 8 and (iy2 - iy1) > 8):
            state["selection"] = (ix1, iy1, ix2, iy2)
            w_sel = ix2 - ix1
            h_sel = iy2 - iy1
            sel_info.value = (
                f"Sélection : ({ix1}, {iy1}) → ({ix2}, {iy2})  —  "
                f"{w_sel} × {h_sel} px"
            )
            has_prompt = bool(prompt_field.value and prompt_field.value.strip())
            send_btn.disabled = not has_prompt
        else:
            state["selection"] = None
            sel_info.value = "Sélection trop petite — recommencez"
            send_btn.disabled = True

        sel_info.update()
        _update_sel_canvas()

    def _on_pan_cancel(e) -> None:
        state["drag_start"]   = None
        state["drag_current"] = None
        _update_sel_canvas()

    # ── Envoi à Gemini ───────────────────────────────────────────────────────

    async def on_send_gemini(e) -> None:
        if state["orig_img"] is None or state["selection"] is None or state["working"]:
            return
        prompt_text = (prompt_field.value or "").strip()
        if not prompt_text:
            status_text.value = "Saisissez une description de la retouche souhaitée"
            page.update()
            return

        state["working"]     = True
        send_btn.disabled    = True
        undo_btn.disabled    = True
        save_btn.disabled    = True
        saveas_btn.disabled  = True
        progress_bar.value   = None
        progress_bar.visible = True
        status_text.value    = "Envoi à Gemini…"
        page.update()

        sel = state["selection"]
        sel_w = sel[2] - sel[0]
        sel_h = sel[3] - sel[1]

        # Recadrage de la zone sélectionnée depuis l'image de travail
        crop = (state["work_img"] or state["orig_img"]).convert("RGB").crop(sel)

        def _do_gemini():
            buf = io.BytesIO()
            crop.save(buf, format="JPEG", quality=95)
            return _gemini_generate_image(prompt_text, input_image_bytes=buf.getvalue())

        try:
            text_resp, image_bytes = await asyncio.to_thread(_do_gemini)

            if image_bytes is None:
                status_text.value = f"[ERREUR Gemini] {text_resp}"
                page.update()
                return

            # Charge le résultat Gemini et le redimensionne exactement à la sélection
            gemini_img = Image.open(io.BytesIO(image_bytes)).convert("RGB")
            gemini_fit = gemini_img.resize((sel_w, sel_h), Image.Resampling.LANCZOS)

            # Sauvegarde de l'état pour annulation
            state["undo_img"] = (state["work_img"] or state["orig_img"]).copy()

            # Collage dans l'image de travail
            new_work = (state["work_img"] or state["orig_img"]).copy()
            new_work.paste(gemini_fit, (sel[0], sel[1]))
            state["work_img"] = new_work

            undo_btn.disabled   = False
            save_btn.disabled   = False
            saveas_btn.disabled = False

            gemini_dims = f"{gemini_img.width}×{gemini_img.height}"
            status_text.value = (
                f"[OK] Retouche appliquée  —  Gemini : {gemini_dims} px  →  "
                f"replacé à {sel_w}×{sel_h} px"
            )
            if text_resp:
                status_text.value += f"  |  « {text_resp[:80]} »"

        except Exception as ex:
            status_text.value = f"[ERREUR] {ex}"
        finally:
            state["working"]     = False
            progress_bar.visible = False
            has_sel    = state["selection"] is not None
            has_prompt = bool(prompt_field.value and prompt_field.value.strip())
            send_btn.disabled = not (has_sel and has_prompt)
            _render_preview()

    # ── Annulation ───────────────────────────────────────────────────────────

    def on_undo(e) -> None:
        if state["undo_img"] is None:
            return
        state["work_img"] = state["undo_img"]
        state["undo_img"] = None
        undo_btn.disabled = True
        status_text.value = "Retouche annulée"
        _render_preview()

    # ── Enregistrement ───────────────────────────────────────────────────────

    async def _save_to(path: str) -> bool:
        img = state["work_img"]
        if img is None:
            return False
        try:
            ext = os.path.splitext(path)[1].lower()
            rgb = img.convert("RGB")
            if ext in (".jpg", ".jpeg"):
                await asyncio.to_thread(
                    rgb.save, path,
                    format="JPEG", dpi=(DPI, DPI),
                    quality=100, subsampling=0,
                )
            elif ext == ".png":
                await asyncio.to_thread(
                    img.save, path,
                    format="PNG", dpi=(DPI, DPI),
                )
            elif ext in (".tif", ".tiff"):
                await asyncio.to_thread(
                    rgb.save, path,
                    format="TIFF", dpi=(DPI, DPI),
                )
            else:
                path += ".jpg"
                await asyncio.to_thread(
                    rgb.save, path,
                    format="JPEG", dpi=(DPI, DPI),
                    quality=100, subsampling=0,
                )
            state["source_path"] = path
            status_text.value = f"[OK] Enregistré : {os.path.basename(path)}"
            page.update()
            return True
        except Exception as ex:
            status_text.value = f"[ERREUR] Enregistrement : {ex}"
            page.update()
            return False

    async def _advance_after_save() -> None:
        next_index = state["index"] + 1
        if next_index < len(all_images):
            await _load_image(next_index)
        else:
            await page.window.close()  # type: ignore[misc]

    async def on_save(e) -> None:
        path = state["source_path"]
        if not path or state["work_img"] is None:
            return
        if await _save_to(path):
            await _advance_after_save()

    async def on_saveas(e) -> None:
        if state["work_img"] is None:
            return
        base = os.path.splitext(os.path.basename(state["source_path"] or "image"))[0]
        path = await ft.FilePicker().save_file(
            dialog_title="Enregistrer sous…",
            file_name=f"{base}_retouche.jpg",
            allowed_extensions=["jpg", "jpeg", "png", "tif", "tiff"],
        )
        if path:
            if not any(path.lower().endswith(ext)
                       for ext in (".jpg", ".jpeg", ".png", ".tif", ".tiff")):
                path += ".jpg"
            if await _save_to(path):
                await _advance_after_save()

    # ── Ouverture manuelle ───────────────────────────────────────────────────

    async def on_open(e) -> None:
        files = await ft.FilePicker().pick_files(
            dialog_title="Ouvrir une image",
            allowed_extensions=["jpg", "jpeg", "png", "bmp",
                                 "tiff", "tif", "webp"],
            allow_multiple=False,
        )
        if files and files[0].path:
            await _load_image_path(files[0].path)

    # ── Effacement de la sélection ───────────────────────────────────────────

    def on_clear_selection(e) -> None:
        state["selection"]    = None
        state["drag_start"]   = None
        state["drag_current"] = None
        sel_info.value    = "Sélection effacée — clic + glisser pour définir une zone"
        send_btn.disabled = True
        _render_preview()

    # ── Prompt ───────────────────────────────────────────────────────────────

    def on_prompt_change(e) -> None:
        has_prompt = bool(prompt_field.value and prompt_field.value.strip())
        send_btn.disabled = not (has_prompt and state["selection"] is not None)
        send_btn.update()

    # ── Navigation ───────────────────────────────────────────────────────────

    async def on_prev(e) -> None:
        await _load_image(state["index"] - 1)

    async def on_next(e) -> None:
        await _load_image(state["index"] + 1)

    # ── Câblage des événements ───────────────────────────────────────────────
    send_btn.on_click      = on_send_gemini
    undo_btn.on_click      = on_undo
    save_btn.on_click      = on_save
    saveas_btn.on_click    = on_saveas
    open_btn.on_click      = on_open
    clear_sel_btn.on_click = on_clear_selection
    prompt_field.on_change = on_prompt_change
    prev_btn.on_click      = on_prev
    next_btn.on_click      = on_next

    # ── Mode toggle ──────────────────────────────────────────────────────────
    mode_btn = ft.Button(
        "Activer sélection",
        icon=ft.Icons.CROP_FREE,
        bgcolor=GREY,
        color=WHITE,
        tooltip="Basculer entre navigation (zoom/déplacement) et sélection de zone",
    )

    # ── Gesture detector (rubber band, à l'intérieur de l'InteractiveViewer) ──
    image_gesture = ft.GestureDetector()
    image_gesture.content               = ft.Container(expand=True)   # zone de hit-test transparente
    image_gesture.on_pan_start          = _on_pan_start
    image_gesture.on_pan_update         = _on_pan_update
    image_gesture.on_pan_end            = _on_pan_end
    image_gesture.on_pan_cancel         = _on_pan_cancel
    image_gesture.on_secondary_tap_down = lambda e: on_clear_selection(e)
    image_gesture.mouse_cursor          = ft.MouseCursor.PRECISE
    image_gesture.visible               = False   # caché en mode navigation

    _vw, _vh = state["view_size"]
    inner_container = ft.Container(
        content=ft.Stack([preview_img, sel_canvas, image_gesture]),
        width=_vw,
        height=_vh,
    )

    preview_viewer = ft.InteractiveViewer(
        content=inner_container,
        pan_enabled=True,
        scale_enabled=True,
        min_scale=0.1,
        max_scale=10.0,
    )

    async def on_mode_toggle(_) -> None:
        state["sel_mode"] = not state["sel_mode"]
        if state["sel_mode"]:
            mode_btn.text              = "Activer navigation"  # type: ignore[attr-defined]
            mode_btn.icon              = ft.Icons.PAN_TOOL
            mode_btn.bgcolor           = BLUE
            image_gesture.visible      = True
            preview_viewer.pan_enabled = False
        else:
            mode_btn.text              = "Activer sélection"   # type: ignore[attr-defined]
            mode_btn.icon              = ft.Icons.CROP_FREE
            mode_btn.bgcolor           = GREY
            image_gesture.visible      = False
            preview_viewer.pan_enabled = True
            state["drag_start"]        = None
            state["drag_current"]      = None
            _update_sel_canvas()
        mode_btn.update()
        image_gesture.update()
        preview_viewer.update()

    mode_btn.on_click = on_mode_toggle

    # ── Mise en page ─────────────────────────────────────────────────────────
    left_panel = ft.Column(
        [
            # Ouverture et navigation
            open_btn,
            ft.Row(
                [prev_btn, image_label, next_btn],
                vertical_alignment=ft.CrossAxisAlignment.CENTER,
            ),
            counter_text,
            ft.Divider(color=GREY),
            # Sélection
            ft.Text("Zone sélectionnée", size=13,
                    weight=ft.FontWeight.BOLD, color=WHITE),
            mode_btn,
            ft.Text(
                "Navigation : glisser/molette = zoom & déplacement\n"
                "Sélection : glisser = zone  |  clic droit = effacer",
                size=10, color=LIGHT_GREY,
            ),
            sel_info,
            clear_sel_btn,
            ft.Divider(color=GREY),
            # Retouche IA
            ft.Text("Retouche IA (Gemini)", size=13,
                    weight=ft.FontWeight.BOLD, color=WHITE),
            prompt_field,
            send_btn,
            progress_bar,
            ft.Divider(color=GREY),
            # Undo
            undo_btn,
            ft.Divider(color=GREY),
            # Enregistrement
            ft.Text("Enregistrement", size=13,
                    weight=ft.FontWeight.BOLD, color=WHITE),
            save_btn,
            saveas_btn,
            ft.Container(expand=True),
            status_text,
        ],
        width=290,
        spacing=8,
        scroll=ft.ScrollMode.AUTO,
    )

    center_panel = ft.Column(
        [
            ft.Container(
                content=ft.Stack(
                    [preview_placeholder, preview_viewer],
                    expand=True,
                ),
                expand=True,
                border_radius=8,
                clip_behavior=ft.ClipBehavior.HARD_EDGE,
            ),
        ],
        expand=True,
        horizontal_alignment=ft.CrossAxisAlignment.CENTER,
        spacing=0,
    )

    page.add(
        ft.Row(
            [
                ft.Container(
                    content=left_panel,
                    padding=ft.Padding(12, 14, 12, 14),
                    bgcolor=DARK,
                    border_radius=10,
                    border=ft.Border.all(1, GREY),
                ),
                ft.Container(width=12),
                center_panel,
            ],
            expand=True,
            vertical_alignment=ft.CrossAxisAlignment.START,
        )
    )

    # ── Resize ───────────────────────────────────────────────────────────────

    def _on_page_resize(e=None) -> None:
        w = int(getattr(e, "width",  None) or page.width  or 1200)
        h = int(getattr(e, "height", None) or page.height or 800)
        vw = max(640, w - 340)
        vh = max(480, h - 60)
        state["view_size"] = (vw, vh)
        inner_container.width  = vw
        inner_container.height = vh
        if state["orig_img"] is not None:
            _render_preview()
        else:
            inner_container.update()

    page.on_resized = _on_page_resize

    # ── Démarrage ────────────────────────────────────────────────────────────

    async def _startup() -> None:
        pre_w = page.window.width or 0
        page.window.maximized = True
        page.update()
        for _ in range(40):
            await asyncio.sleep(0.1)
            if (page.window.width or 0) != pre_w:
                break
        await asyncio.sleep(0.5)
        _on_page_resize()
        if all_images:
            await _load_image(0)
        else:
            status_text.value = f"Aucune image dans : {source_folder}"
            page.update()

    page.run_task(_startup)


###############################################################
#                       POINT D'ENTRÉE                        #
###############################################################

if __name__ == "__main__":
    if sys.platform == "win32":
        from asyncio.proactor_events import _ProactorBasePipeTransport
        _orig_ccl = _ProactorBasePipeTransport._call_connection_lost

        def _patched_ccl(self, exc):
            try:
                _orig_ccl(self, exc)
            except (ConnectionResetError, OSError):
                pass

        _ProactorBasePipeTransport._call_connection_lost = _patched_ccl

    ft.run(main)
