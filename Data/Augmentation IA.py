# -*- coding: utf-8 -*-
"""
Retouche IA par sélection — v1.0
==================================

Sélectionnez une zone d'une image et envoyez-la à Gemini (Nano Banana 2 /
gemini-3.1-flash-image-preview) pour la modifier, puis réintégrez le résultat
dans l'image originale à taille exacte.

Flux de travail :
  1. L'image s'ouvre depuis FOLDER_PATH / SELECTED_FILES (env) ou via Ouvrir…
  2. Sélectionnez une zone :
       - clic gauche + glisser -> rectangle littéral (ex. zone à combler)
       - clic simple (sans glisser) -> masque précis de l'objet sous le
         curseur, via SAM2 (ex. remplacer un objet)
  3. Décrivez la retouche dans le champ texte
  4. Cliquez « Envoyer à Gemini »
  5. La zone modifiée est réintégrée dans l'image à ses dimensions exactes
  6. Annulez (Ctrl+Z) ou Enregistrez / Enregistrez sous…

Dépendances :
  flet, Pillow, google-genai (pip install google-genai)
  torch, sam2 (optionnel — sélection d'objet au clic ; sans eux, seul le
  rectangle glisser-déposer reste disponible, cf. SAM2_AVAILABLE)

Variables d'environnement reconnues :
  GEMINI_API_KEY  — clé d'API Gemini (ou fichier .env)
  FOLDER_PATH     — dossier source des images
  SELECTED_FILES  — noms de fichiers séparés par « | »
"""

__version__ = "3.1.0"

import flet as ft
import flet.canvas as cv
import os
import io
import base64
import asyncio
import importlib.util
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))
import CONSTANTS
import ai_ops
import image_ops
from ai_tools import _gemini_generate_image

from PIL import Image, ImageDraw, ImageFilter

###############################################################
#                        PALETTE                              #
###############################################################
DARK       = CONSTANTS.COLOR_DARK
BG_UI      = CONSTANTS.COLOR_BACKGROUND
GREY       = CONSTANTS.COLOR_GREY
LIGHT_GREY = CONSTANTS.COLOR_LIGHT_GREY
BLUE       = CONSTANTS.COLOR_BLUE
VIOLET     = CONSTANTS.COLOR_VIOLET
GREEN      = CONSTANTS.COLOR_GREEN
ORANGE     = CONSTANTS.COLOR_ORANGE
RED        = CONSTANTS.COLOR_RED
WHITE      = CONSTANTS.COLOR_WHITE

IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".tiff", ".tif", ".bmp", ".webp"}
DPI = CONSTANTS.DPI

# ---- Modèles IA locaux (.pth / .safetensors via spandrel) ----
_MODELS_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "models")
os.makedirs(_MODELS_DIR, exist_ok=True)

ESRGAN_AVAILABLE = (
    importlib.util.find_spec("torch")    is not None
    and importlib.util.find_spec("spandrel") is not None
)
REMBG_AVAILABLE = importlib.util.find_spec("rembg") is not None
_SAM2_CKPT_PATH = os.path.join(_MODELS_DIR, CONSTANTS.SAM2_CHECKPOINT)
_SAM2_PKG_MISSING = (
    importlib.util.find_spec("torch") is None
    or importlib.util.find_spec("sam2") is None
)
SAM2_AVAILABLE = (
    not _SAM2_PKG_MISSING and os.path.isfile(_SAM2_CKPT_PATH)
)


def _sam2_unavailable_reason() -> str:
    """Message précis (paquet vs checkpoint) pour guider l'installation."""
    if _SAM2_PKG_MISSING:
        return (
            "Sélection d'objet indisponible : pip install "
            "git+https://github.com/facebookresearch/sam2.git — "
            "glissez pour un rectangle")
    return (
        "Sélection d'objet indisponible : téléchargez "
        f"{CONSTANTS.SAM2_CHECKPOINT} depuis "
        "https://dl.fbaipublicfiles.com/segment_anything_2/092824/"
        f"{CONSTANTS.SAM2_CHECKPOINT} et placez-le dans "
        f"{_MODELS_DIR} — glissez pour un rectangle")


# Logique partagée avec Hub.pyw (tiroir IA) : device torch + liste des
# modèles locaux, extraits dans ai_ops.py pour ne plus être dupliqués.
_pick_torch_device = ai_ops._pick_torch_device
_list_pth_models = ai_ops.list_pth_models

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
    # Flet ajoute 10px de marge par défaut sur les 4 côtés de la page
    # (View.padding), non comptés par _LEFT_CHROME_W/_TITLEBAR_H plus bas
    # -> décalage systématique entre l'image affichée et les coordonnées
    # de sélection calculées (retour user).
    page.padding = 0
    page.window.title_bar_hidden = True
    page.window.title_bar_buttons_hidden = True
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
        "selection_mask": None, # masque PIL "L" (objet SAM2), taille = sélection, ou None si rectangle
        "drag_start":   None,   # (cx, cy) canvas — début rubber band
        "drag_current": None,   # (cx, cy) canvas — position courante
        "render_info":  None,   # (tw, th, ox, oy, sx, sy)
        "view_size":    (1200, 800),
        "working":      False,
        "sel_mode":     False,  # True = sélection, False = navigation
        "modified":     False,  # True si des modifications n'ont pas été enregistrées
        "rembg_active": False,  # True si le fond a été supprimé
        "rembg_rgba":   None,   # Image RGBA résultat rembg (conservé pour changer le fond)
        "rembg_before": None,   # work_img avant suppression du fond
        "bg_pick_active": False,  # True = pipette (mode Instantané) armée, attend un clic-glissé
        # Cache de la dernière retouche Gemini pour réajuster le fondu à la volée
        "retouch_fit":  None,   # Image RGB brute Gemini, redimensionnée à la sélection
        "retouch_base": None,   # Image de travail avant collage de la retouche
        "retouch_sel":  None,   # (x1, y1, x2, y2) de la retouche
        "retouch_mask": None,   # masque PIL "L" (objet SAM2) pour le fondu, ou None si rectangle
    }

    # Cache spandrel : un objet ModelDescriptor par fichier modèle
    _custom_model_cache: dict = {}

    # ── SAM2 : segmentation d'objet au clic ─────────────────────────────────
    # Le prédicteur (chargement du checkpoint) et l'encodage de l'image
    # courante sont coûteux — mis en cache pour que seuls les clics suivants
    # sur la MÊME image restent quasi-instantanés (predict() seul, sans
    # re-passer par l'encodeur).
    _sam2_state: dict = {"predictor": None, "embedded_img_id": None}

    def _get_sam2_predictor():
        if _sam2_state["predictor"] is not None:
            return _sam2_state["predictor"]
        from sam2.build_sam import build_sam2
        from sam2.sam2_image_predictor import SAM2ImagePredictor
        device = _pick_torch_device()
        ckpt = os.path.join(_MODELS_DIR, CONSTANTS.SAM2_CHECKPOINT)
        model = build_sam2(CONSTANTS.SAM2_CONFIG, ckpt_path=ckpt, device=device)
        predictor = SAM2ImagePredictor(model)
        _sam2_state["predictor"] = predictor
        return predictor

    def _sam2_segment_point(img: Image.Image, ix: int, iy: int) -> Image.Image | None:
        """Masque PIL "L" (255 = objet) de l'objet sous le point (ix, iy) en
        coordonnées image, ou None en cas d'échec. Appeler hors thread UI
        (asyncio.to_thread) : l'encodage + la prédiction sont bloquants."""
        import numpy as _np
        predictor = _get_sam2_predictor()
        img_id = id(img)
        if _sam2_state["embedded_img_id"] != img_id:
            predictor.set_image(_np.array(img.convert("RGB")))
            _sam2_state["embedded_img_id"] = img_id
        masks, scores, _logits = predictor.predict(
            point_coords=_np.array([[ix, iy]]),
            point_labels=_np.array([1]),
            multimask_output=True,
        )
        best = masks[int(_np.argmax(scores))]
        return Image.fromarray((best * 255).astype("uint8"), mode="L")

    # ── Éléments UI ──────────────────────────────────────────────────────────
    status_text    = ft.Text("", size=12, color=LIGHT_GREY)
    image_label    = ft.Text("—", size=13, color=WHITE, expand=True,
                             text_align=ft.TextAlign.CENTER)
    counter_text   = ft.Text("", size=12, color=LIGHT_GREY)
    progress_bar   = ft.ProgressBar(color=BLUE, bgcolor=GREY, visible=False)
    sel_info       = ft.Text(
        "Aucune sélection — clic pour un objet, glisser pour une zone",
        size=11, color=LIGHT_GREY,
    )

    # Slider de fondu des bords, visible seulement après une retouche Gemini.
    feather_slider = ft.Slider(
        min=0, max=0.4, divisions=40,
        value=CONSTANTS.AI_RETOUCH_FEATHER_RATIO,
        label="{value}", active_color=BLUE,
    )
    feather_row = ft.Column(
        [ft.Text("Fondu des bords", size=11, color=LIGHT_GREY), feather_slider],
        spacing=0, visible=False,
    )

    # Curseur dédié à l'objet SAM2 (masque, pas rectangle) : élargit le
    # masque AVANT d'écrire la retouche (retour user — voir et ajuster la
    # zone affectée avant de décrire ce qu'on veut à cet endroit, pas
    # après). Vit dans inpaint_dialog (cf. plus bas), visible seulement
    # pour une retouche par objet — un rectangle n'a pas de "contour" à
    # élargir. Valeur = fraction du plus petit côté de l'OBJET détecté
    # (pas des px fixes, cf. CONSTANTS.SAM2_MASK_DILATE_RATIO*).
    dilate_slider = ft.Slider(
        min=0, max=CONSTANTS.SAM2_MASK_DILATE_RATIO_MAX, divisions=50,
        value=CONSTANTS.SAM2_MASK_DILATE_RATIO,
        label="{value}", active_color=BLUE,
    )
    dilate_row = ft.Column(
        [ft.Text("Taille du masque", size=11, color=LIGHT_GREY), dilate_slider],
        spacing=0, visible=False,
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
        fit=ft.BoxFit.CONTAIN,
        gapless_playback=True,
        visible=False,
    )

    sel_canvas = cv.Canvas(expand=True, shapes=[])

    # Feedback visuel pendant la segmentation SAM2 (retour user : "je ne
    # sais pas si ça travaille") — anneau natif positionné exactement au
    # point cliqué, plus visible qu'un simple changement de texte.
    busy_ring = ft.ProgressRing(width=26, height=26, stroke_width=3, color=BLUE)
    busy_ring_wrap = ft.Container(content=busy_ring, left=0, top=0, visible=False)

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
        tooltip="Enregistrer dans le sous-dossier Retouche/",
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

    def _dilated_mask(raw: Image.Image, ratio: float) -> Image.Image:
        """Dilate `raw` (masque "L") de `ratio` × le plus petit côté de
        l'OBJET détecté (son bbox à l'intérieur du crop, pas le crop
        lui-même, qui a déjà une marge) — même principe qu'AI_RETOUCH_
        FEATHER_RATIO, pour qu'un objet fin reçoive une dilatation
        proportionnellement significative plutôt qu'un plafond fixe en px
        (retour user : un objet étroit n'était presque pas couvert même
        au maximum de l'ancien curseur en pixels)."""
        bbox = raw.getbbox()
        if bbox is None or ratio <= 0:
            return raw
        obj_w, obj_h = bbox[2] - bbox[0], bbox[3] - bbox[1]
        dilate_px = int(min(obj_w, obj_h) * ratio)
        if dilate_px <= 0:
            return raw
        return raw.filter(ImageFilter.MaxFilter(dilate_px * 2 + 1))

    def _render_preview() -> None:
        img = state["work_img"] or state["orig_img"]
        if img is None:
            return
        _compute_render_info()
        info = state["render_info"]
        if info is None:
            return
        vw, vh = state["view_size"]

        # Encode à résolution native (plafonnée à 3000px côté le plus long)
        # BoxFit.CONTAIN gère l'affichage — le zoom révèle les vrais pixels
        ow, oh = img.size
        MAX_PX = 3000
        if img.mode == "RGBA":
            _bg = Image.new("RGB", img.size, (180, 180, 180))
            _bg.paste(img.convert("RGB"), mask=img.split()[3])
            img_for_preview = _bg
        else:
            img_for_preview = img.convert("RGB")

        # Teinte du masque SAM2 en cours d'ajustement (dilate_slider) —
        # brûlée directement dans les MÊMES pixels que l'aperçu affiché,
        # avant tout redimensionnement : élimine tout risque de décalage
        # entre le calque et l'image (retour user — un calque séparé
        # positionné par coordonnées d'affichage tombait à côté).
        raw_mask = state["selection_mask"]
        sel      = state["selection"]
        if raw_mask is not None and sel is not None:
            mask = _dilated_mask(raw_mask, dilate_slider.value)
            full_mask = Image.new("L", img_for_preview.size, 0)
            full_mask.paste(mask, (sel[0], sel[1]))
            tint = Image.new("RGB", img_for_preview.size, (30, 144, 255))
            img_for_preview = Image.composite(
                tint, img_for_preview, full_mask.point(lambda v: v * 140 // 255))

        if max(ow, oh) > MAX_PX:
            s = MAX_PX / max(ow, oh)
            preview_data = img_for_preview.resize(
                (round(ow * s), round(oh * s)), Image.Resampling.LANCZOS
            )
        else:
            preview_data = img_for_preview

        preview_img.src = f"data:image/jpeg;base64,{image_to_b64(preview_data)}"
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

    def _decode_image(path: str) -> Image.Image:
        img = Image.open(path)
        img.load()
        if img.mode not in ("RGB", "RGBA"):
            img = img.convert("RGB")
        return img

    async def _load_image_path(path: str) -> None:
        try:
            img = await asyncio.to_thread(_decode_image, path)
            state["source_path"]     = path
            state["orig_img"]        = img.copy()
            state["work_img"]        = img.copy()
            state["undo_img"]        = None
            state["modified"]        = False
            state["selection"]       = None
            state["drag_start"]      = None
            state["drag_current"]    = None
            state["zoom"]            = 1.0
            state["pan_offset"]      = (0.0, 0.0)
            state["pan_drag_origin"] = None

            image_label.value  = os.path.basename(path)
            status_text.value  = f"{img.width} × {img.height} px"
            sel_info.value     = "Aucune sélection — clic pour un objet, glisser pour une zone"
            send_btn.disabled  = True
            undo_btn.disabled  = True
            save_btn.disabled   = True
            inpaint_btn.disabled = False
            expand_btn.disabled  = False
            rembg_apply_btn.disabled = not (REMBG_AVAILABLE or _rembg_mode[0] == 2)
            state["rembg_active"] = False
            state["rembg_rgba"]   = None
            state["rembg_before"] = None
            _bg_pick_cancel()
            _pipette.reset()
            _sync_pipette_sign_btn()
            rembg_apply_btn.text    = "Supprimer le fond"
            rembg_apply_btn.bgcolor = GREY if REMBG_AVAILABLE else GREY
            rembg_status.value = ""
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

    def _on_pan_down(e) -> None:
        """Contact initial du clic pipette (mode Instantané, Fond IA) —
        `on_pan_down` se déclenche instantanément, contrairement à
        `on_pan_start` qui n'est reconnu par Flutter qu'après un léger
        mouvement (retour user sur Recadrage manuel.pyw : la sélection
        tombait à côté du point cliqué). N'agit que si la pipette est
        armée, sinon ne fait rien (le rubber band démarre via
        `_on_pan_start`, geste distinct)."""
        if not state["bg_pick_active"]:
            return
        cx, cy = float(e.local_position.x), float(e.local_position.y)
        _pipette_start[0] = (cx, cy)
        _pipette.start_drag()

    def _on_pan_start(e) -> None:
        if not state["sel_mode"] or state["orig_img"] is None or state["working"]:
            return
        cx, cy = float(e.local_position.x), float(e.local_position.y)
        state["drag_start"]   = (cx, cy)
        state["drag_current"] = (cx, cy)

    def _on_pan_update(e) -> None:
        if state["bg_pick_active"]:
            if _pipette_start[0] is not None:
                tol = _pipette.drag(e.local_delta.x)
                _pipette_tolerance_label.value = f"Tol. {tol}"
                _pipette_tolerance_label.update()
                if _pipette.try_start_live():
                    cx, cy = _pipette_start[0]
                    ix, iy = _display_to_image(cx, cy)
                    if ix is not None and iy is not None:
                        page.run_task(_pipette_live_preview, ix, iy, tol)
                    else:
                        _pipette.live_busy = False  # clic hors image : rien à calculer
            return
        if not state["sel_mode"] or state["drag_start"] is None or state["working"]:
            return
        # local_position = position courante en espace content (pré-transform IV)
        state["drag_current"] = (float(e.local_position.x), float(e.local_position.y))
        _update_sel_canvas()

    def _cancel_selection_ui(message: str) -> None:
        """Aucune sélection exploitable (rectangle trop petit, clic hors
        image, SAM2 n'a rien trouvé) : reste en mode sélection, juste un
        message et un statut vidé, contrairement à _open_inpaint_dialog_
        for_selection qui valide une sélection et ouvre le dialogue."""
        state["selection"]      = None
        state["selection_mask"] = None
        sel_info.value    = message
        send_btn.disabled = True
        sel_info.update()
        _render_preview()

    def _open_inpaint_dialog_for_selection(w_sel: int, h_sel: int) -> None:
        has_prompt = bool(prompt_field.value and prompt_field.value.strip())
        send_btn.disabled = not has_prompt
        state["sel_mode"]          = False
        inpaint_btn.text           = "Retouche IA"
        inpaint_btn.icon           = ft.Icons.AUTO_FIX_HIGH
        inpaint_btn.bgcolor        = GREY
        image_gesture.visible      = False
        preview_viewer.pan_enabled = True
        has_mask = state["selection_mask"] is not None
        dilate_row.visible = has_mask
        if has_mask:
            dilate_slider.value = CONSTANTS.SAM2_MASK_DILATE_RATIO
        inpaint_dialog.open        = True
        sel_info.update()
        _render_preview()

    async def _select_object_at(cx: float, cy: float) -> None:
        """Clic (sans glisser) en mode sélection : segmente l'objet sous le
        curseur avec SAM2 plutôt que de tracer un rectangle."""
        if not SAM2_AVAILABLE:
            _cancel_selection_ui(_sam2_unavailable_reason())
            return
        ix, iy = _display_to_image(cx, cy)
        img = state["work_img"] or state["orig_img"]
        if ix is None or iy is None or img is None:
            _cancel_selection_ui("Clic hors image — recommencez")
            return
        sel_info.value = "Segmentation de l'objet (SAM2)…"
        sel_info.update()
        busy_ring_wrap.left    = cx - busy_ring.width / 2
        busy_ring_wrap.top     = cy - busy_ring.height / 2
        busy_ring_wrap.visible = True
        busy_ring_wrap.update()
        try:
            mask = await asyncio.to_thread(_sam2_segment_point, img, ix, iy)
        except Exception as exc:
            mask = None
            status_text.value = f"[ERREUR] SAM2 : {exc}"
        finally:
            busy_ring_wrap.visible = False
            busy_ring_wrap.update()
        if mask is None or not mask.getbbox():
            _cancel_selection_ui("Aucun objet détecté sous le clic — recommencez")
            return

        bx1, by1, bx2, by2 = mask.getbbox()
        # Marge = la dilatation MAX possible via le curseur "Taille du
        # masque" (proportionnelle au plus petit côté de l'OBJET, pas la
        # valeur par défaut) : sinon un masque dilaté en butée du curseur
        # serait tronqué au bord de ce crop.
        obj_w, obj_h = bx2 - bx1, by2 - by1
        pad = int(min(obj_w, obj_h) * CONSTANTS.SAM2_MASK_DILATE_RATIO_MAX)
        bx1 = max(0, bx1 - pad)
        by1 = max(0, by1 - pad)
        bx2 = min(img.width,  bx2 + pad)
        by2 = min(img.height, by2 + pad)

        # Masque brut (non dilaté) stocké tel quel — la dilatation est
        # appliquée à chaque aperçu/recollage (_dilated_mask), pilotée par
        # dilate_slider, pas figée ici (retour user : curseur réglable).
        state["selection"]      = (bx1, by1, bx2, by2)
        state["selection_mask"] = mask.crop((bx1, by1, bx2, by2))
        w_sel, h_sel = bx2 - bx1, by2 - by1
        sel_info.value = f"Objet sélectionné (SAM2) — {w_sel} × {h_sel} px"
        _open_inpaint_dialog_for_selection(w_sel, h_sel)

    def _on_pan_end(e) -> None:
        if state["bg_pick_active"]:
            if _pipette_start[0] is None:
                return
            cx, cy = _pipette_start[0]
            _pipette_start[0] = None
            ix, iy = _display_to_image(cx, cy)
            tol = _pipette.end_drag()
            if ix is not None and iy is not None:
                page.run_task(_apply_pipette_pick, ix, iy, tol)
            return
        # Un clic quasi immobile ne termine pas toujours un geste "pan" côté
        # Flutter (le glisser exige un minimum de mouvement pour être
        # reconnu comme tel) — c'est `on_tap_up`/_on_tap_click, un geste
        # dédié, qui gère le clic -> SAM2, pas une détection de mouvement
        # ici (retour user : la segmentation ne se déclenchait pas, ou très
        # rarement, avec l'ancienne détection par seuil).
        if not state["sel_mode"] or state["drag_start"] is None:
            return
        x1d, y1d = state["drag_start"]
        x2d, y2d = state["drag_current"] or state["drag_start"]
        state["drag_start"]   = None
        state["drag_current"] = None

        state["selection_mask"] = None
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
            _open_inpaint_dialog_for_selection(w_sel, h_sel)
        else:
            _cancel_selection_ui("Sélection trop petite — recommencez")

    def _on_pan_cancel(e) -> None:
        _pipette_start[0]      = None
        state["drag_start"]   = None
        state["drag_current"] = None
        _update_sel_canvas()

    def _on_tap_click(e) -> None:
        """Clic (tap, pas glisser) en mode sélection -> objet SAM2. Geste
        séparé du pan (cf. _on_pan_end) : un clic immobile ne remonte pas
        forcément par onPanStart/End côté Flutter, alors qu'un tap le fait
        toujours, mouvement ou non."""
        if not state["sel_mode"] or state["orig_img"] is None or state["working"]:
            return
        page.run_task(
            _select_object_at, float(e.local_position.x), float(e.local_position.y))

    # ── Envoi à Gemini ───────────────────────────────────────────────────────

    def _composite_retouch(ratio: float) -> None:
        """Recolle la retouche Gemini cachée avec un fondu de bords `ratio`.

        Opération légère (paste + flou gaussien) : aucun appel réseau.
        Utilisé au premier collage puis à chaque mouvement du slider de
        fondu. La dilatation du masque (dilate_slider), elle, est déjà
        décidée et appliquée AVANT l'envoi à Gemini (cf. _render_mask_
        overlay / on_send_gemini) — retouch_mask est donc déjà à sa
        taille finale ici, seul le flou reste ajustable après coup.
        """
        fit  = state["retouch_fit"]
        base = state["retouch_base"]
        sel  = state["retouch_sel"]
        if fit is None or base is None or sel is None:
            return
        w, h = fit.size
        feather = max(
            CONSTANTS.AI_RETOUCH_FEATHER_MIN,
            int(min(w, h) * ratio),
        )
        feather = min(feather, min(w, h) // 2)   # jamais au-delà du centre
        obj_mask = state["retouch_mask"]
        if obj_mask is not None:
            # Silhouette précise (SAM2) : bords déjà nets, un fondu bien
            # plus fin qu'un rectangle suffit (retour user — éviter de
            # "manger" l'objet avec un flou trop large).
            mask_feather = max(1, feather // CONSTANTS.SAM2_MASK_FEATHER_DIVISOR)
            mask = obj_mask.filter(ImageFilter.GaussianBlur(mask_feather))
        else:
            mask = Image.new("L", (w, h), 0)
            ImageDraw.Draw(mask).rectangle(
                (feather, feather, w - feather, h - feather), fill=255,
            )
            mask = mask.filter(ImageFilter.GaussianBlur(feather))
        new_work = base.copy()
        new_work.paste(fit, (sel[0], sel[1]), mask)
        state["work_img"] = new_work
        state["modified"] = True

    def on_feather_change(e) -> None:
        _composite_retouch(feather_slider.value)
        _render_preview()

    def on_dilate_change_end(e) -> None:
        # Barre indéterminée pendant le recalcul (retour user : aucun signe
        # que ça travaille sinon) — affichée AVANT l'appel bloquant, pour
        # qu'elle soit bien à l'écran pendant que _render_preview() tourne.
        progress_bar.value   = None
        progress_bar.visible = True
        page.update()
        try:
            _render_preview()
        finally:
            progress_bar.visible = False
            page.update()

    feather_slider.on_change     = on_feather_change
    # _render_preview() reconvertit/réencode l'image PLEINE résolution à
    # chaque appel (contrairement à _composite_retouch, léger) — le
    # déclencher sur `on_change` (donc à chaque tick pendant le glissement)
    # noyait l'UI de recalculs, ressenti comme un blocage sans retour
    # (retour user). `on_change_end` : un seul recalcul au relâchement,
    # comme les curseurs coûteux de Recadrage manuel.pyw. La bulle de
    # valeur native du slider (label="{value}") donne déjà un retour
    # numérique instantané pendant le glissement, sans recalcul.
    dilate_slider.on_change_end  = on_dilate_change_end

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
        progress_bar.value   = None
        progress_bar.visible = True
        status_text.value    = "Envoi à Gemini… (0s)"

        sel = state["selection"]
        sel_w = sel[2] - sel[0]
        sel_h = sel[3] - sel[1]
        sel_mask = state["selection_mask"]   # capturé avant reset ci-dessous
        if sel_mask is not None:
            # Dilatation déjà choisie/aperçue via dilate_slider avant
            # l'envoi (cf. _dilated_mask) — appliquée ici une fois pour
            # toutes, _composite_retouch ne s'occupe plus que du flou.
            sel_mask = _dilated_mask(sel_mask, dilate_slider.value)

        # Effacer la sélection et repasser en mode navigation immédiatement
        inpaint_dialog.open        = False
        state["selection"]         = None
        state["selection_mask"]    = None
        state["drag_start"]        = None
        state["drag_current"]      = None
        state["sel_mode"]          = False
        inpaint_btn.text           = "Retouche IA"
        inpaint_btn.icon           = ft.Icons.AUTO_FIX_HIGH
        inpaint_btn.bgcolor        = GREY
        image_gesture.visible      = False
        preview_viewer.pan_enabled = True
        _update_sel_canvas()

        page.update()

        # Recadrage de la zone sélectionnée depuis l'image de travail
        crop = (state["work_img"] or state["orig_img"]).convert("RGB").crop(sel)

        full_prompt = CONSTANTS.AI_RETOUCH_SYSTEM_PROMPT + prompt_text

        def _do_gemini():
            buf = io.BytesIO()
            crop.save(buf, format="JPEG", quality=95)
            return _gemini_generate_image(full_prompt, input_image_bytes=buf.getvalue())

        _elapsed = {"s": 0}

        async def _tick():
            while state["working"]:
                await asyncio.sleep(1)
                _elapsed["s"] += 1
                if state["working"]:
                    status_text.value = f"Envoi à Gemini… ({_elapsed['s']}s)"
                    page.update()

        _timer_task = asyncio.create_task(_tick())

        try:
            text_resp, image_bytes = await asyncio.wait_for(
                asyncio.to_thread(_do_gemini),
                timeout=120.0,
            )

            if image_bytes is None:
                status_text.value = f"[Gemini] {text_resp or 'Aucune image reçue.'}"
                page.update()
                return

            # Charge le résultat Gemini et le redimensionne exactement à la sélection
            gemini_img = Image.open(io.BytesIO(image_bytes)).convert("RGB")
            gemini_fit = gemini_img.resize((sel_w, sel_h), Image.Resampling.LANCZOS)

            # Sauvegarde de l'état pour annulation
            base = (state["work_img"] or state["orig_img"]).copy()
            state["undo_img"] = base.copy()

            # Cache pour réajuster le fondu à la volée via le slider (sans
            # rappeler Gemini), puis premier collage au fondu par défaut.
            state["retouch_fit"]  = gemini_fit
            state["retouch_base"] = base
            state["retouch_sel"]  = sel
            state["retouch_mask"] = sel_mask   # déjà dilaté ci-dessus si objet SAM2
            feather_slider.value  = CONSTANTS.AI_RETOUCH_FEATHER_RATIO
            feather_row.visible   = True
            _composite_retouch(CONSTANTS.AI_RETOUCH_FEATHER_RATIO)

            undo_btn.disabled   = False
            save_btn.disabled   = False

            gemini_dims = f"{gemini_img.width}×{gemini_img.height}"
            status_text.value = (
                f"[OK] Retouche appliquée  —  Gemini : {gemini_dims} px  →  "
                f"replacé à {sel_w}×{sel_h} px"
            )
            if text_resp:
                status_text.value += f"  |  « {text_resp[:80]} »"

        except asyncio.TimeoutError:
            status_text.value = "[ERREUR] Gemini n'a pas répondu en 2 minutes. Vérifiez votre connexion ou réessayez."
        except Exception as ex:
            status_text.value = f"[ERREUR] {ex}"
        finally:
            _timer_task.cancel()
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
        state["retouch_fit"]  = None   # cache obsolète après annulation
        state["retouch_mask"] = None
        feather_row.visible  = False
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
            state["modified"]    = False
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

    def _retouche_path() -> str | None:
        src = state["source_path"]
        if not src:
            return None
        retouche_dir = os.path.join(os.path.dirname(src), "Retouche")
        os.makedirs(retouche_dir, exist_ok=True)
        basename = os.path.basename(src)
        if state["rembg_active"] and rembg_dropdown.value == "Transparent":
            basename = os.path.splitext(basename)[0] + ".png"
        return os.path.join(retouche_dir, basename)

    async def on_save(e) -> None:
        if state["work_img"] is None:
            return
        path = _retouche_path()
        if path and await _save_to(path):
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
        state["selection"]      = None
        state["selection_mask"] = None
        state["drag_start"]     = None
        state["drag_current"]   = None
        sel_info.value    = "Sélection effacée — clic pour un objet, glisser pour une zone"
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

    # ── Éléments UI — modèles locaux ────────────────────────────────────────

    def _build_model_options() -> list[ft.dropdown.Option]:
        names = _list_pth_models()
        if not names:
            return [ft.dropdown.Option(key="", text="Aucun modèle (.pth / .safetensors) dans models/")]
        return [ft.dropdown.Option(key=n, text=n) for n in names]

    model_dropdown = ft.Dropdown(
        options=_build_model_options(),
        value=(_list_pth_models() or [""])[0],
        bgcolor=GREY,
        color=WHITE,
        border_color=LIGHT_GREY,
        text_size=11,
        dense=True,
        expand=True,
        disabled=not ESRGAN_AVAILABLE,
    )
    run_model_btn = ft.IconButton(
        icon=ft.Icons.PLAY_ARROW,
        icon_color=DARK,
        bgcolor=BLUE if ESRGAN_AVAILABLE else GREY,
        tooltip="Lancer le modèle sélectionné sur l'image",
        disabled=not ESRGAN_AVAILABLE or not _list_pth_models(),
    )
    refresh_models_btn = ft.IconButton(
        icon=ft.Icons.REFRESH,
        icon_color=WHITE,
        bgcolor=GREY,
        tooltip="Rafraîchir la liste des modèles",
    )
    enhance_progress_bar = ft.ProgressBar(color=BLUE, bgcolor=GREY, visible=False)
    enhance_status = ft.Text("", size=11, color=LIGHT_GREY)

    # ── Callbacks — modèles locaux ───────────────────────────────────────────

    def on_refresh_models(e) -> None:
        model_dropdown.options = _build_model_options()
        names = _list_pth_models()
        model_dropdown.value   = names[0] if names else ""
        run_model_btn.disabled = not ESRGAN_AVAILABLE or not names
        page.update()

    async def on_run_model(e) -> None:
        base = state["work_img"] or state["orig_img"]
        model_name = model_dropdown.value
        if base is None or state["working"] or not model_name:
            return

        state["working"]             = True
        run_model_btn.disabled       = True
        refresh_models_btn.disabled  = True
        send_btn.disabled            = True
        enhance_progress_bar.value   = None
        enhance_progress_bar.visible = True
        enhance_status.value         = f"Chargement de {model_name}…"
        page.update()

        has_alpha = (base.mode == "RGBA")
        alpha     = base.split()[3] if has_alpha else None

        def _progress_cb(value, label: str = "") -> None:
            enhance_progress_bar.value = value
            if label:
                enhance_status.value = label
            page.update()

        def _do_run():
            import torch as _torch
            import numpy as _np
            from spandrel import ModelLoader as _ModelLoader
            model_path = os.path.join(_MODELS_DIR, model_name)
            if model_name not in _custom_model_cache:
                _dev = _pick_torch_device()
                _progress_cb(None, f"Chargement de {model_name}…")
                desc = _ModelLoader().load_from_file(model_path)
                use_fp16 = (_dev == "cuda") and desc.supports_half
                desc.to(_dev, _torch.float16 if use_fp16 else _torch.float32)
                desc.model.eval()
                _custom_model_cache[model_name] = desc
            desc  = _custom_model_cache[model_name]
            _dev  = next(iter(desc.model.parameters())).device
            use_fp16 = (desc.dtype == _torch.float16)

            rgb = _np.array(base.convert("RGB")).astype(_np.float32) / 255.0
            h, w = rgb.shape[:2]

            TILE    = 512 if _dev.type == "cuda" else (384 if _dev.type == "mps" else 256)
            OVERLAP = TILE // 16
            STEP    = TILE - OVERLAP

            def _scale_factor():
                probe = _torch.zeros(1, 3, 4, 4, device=_dev)
                if use_fp16:
                    probe = probe.half()
                with _torch.inference_mode():
                    return desc(probe).shape[-1] // 4

            scale       = _scale_factor()
            out_h, out_w = h * scale, w * scale
            out_np_full = _np.zeros((out_h, out_w, 3), dtype=_np.float32)
            weight_map  = _np.zeros((out_h, out_w, 1), dtype=_np.float32)

            def _make_weight(th, tw):
                wy  = _np.ones(th, dtype=_np.float32)
                wx  = _np.ones(tw, dtype=_np.float32)
                fade = min(OVERLAP, th // 2, tw // 2)
                ramp = _np.linspace(0.0, 1.0, fade, dtype=_np.float32)
                wy[:fade] = ramp;  wy[-fade:] = ramp[::-1]
                wx[:fade] = ramp;  wx[-fade:] = ramp[::-1]
                return _np.outer(wy, wx)[:, :, _np.newaxis]

            ys = list(range(0, h - TILE, STEP)) + [max(0, h - TILE)]
            xs = list(range(0, w - TILE, STEP)) + [max(0, w - TILE)]
            if h <= TILE and w <= TILE:
                ys, xs = [0], [0]

            total_tiles = len(ys) * len(xs)
            done_tiles  = 0
            _progress_cb(0.0, f"Traitement — tuile 0/{total_tiles}")

            with _torch.inference_mode():
                for y0 in ys:
                    y1 = min(y0 + TILE, h)
                    for x0 in xs:
                        x1 = min(x0 + TILE, w)
                        tile_np = rgb[y0:y1, x0:x1]
                        tile_t  = _torch.from_numpy(tile_np).permute(2, 0, 1).unsqueeze(0).to(_dev)
                        if use_fp16:
                            tile_t = tile_t.half()
                        out_tile = desc(tile_t).squeeze(0).permute(1, 2, 0).clamp(0, 1)
                        if use_fp16:
                            out_tile = out_tile.float()
                        out_tile_np = out_tile.cpu().numpy()
                        oy0, ox0 = y0 * scale, x0 * scale
                        oy1, ox1 = oy0 + out_tile_np.shape[0], ox0 + out_tile_np.shape[1]
                        w_tile = _make_weight(out_tile_np.shape[0], out_tile_np.shape[1])
                        out_np_full[oy0:oy1, ox0:ox1] += out_tile_np * w_tile
                        weight_map  [oy0:oy1, ox0:ox1] += w_tile
                        done_tiles += 1
                        _progress_cb(
                            done_tiles / total_tiles,
                            f"Traitement — tuile {done_tiles}/{total_tiles}",
                        )

            out_np = ((_np.array(out_np_full) / _np.maximum(weight_map, 1e-6)).clip(0, 1) * 255).astype(_np.uint8)
            out = Image.fromarray(out_np)
            if has_alpha and alpha is not None:
                out = out.convert("RGBA")
                out.putalpha(alpha.resize(out.size, Image.Resampling.LANCZOS))
            return out

        try:
            result = await asyncio.to_thread(_do_run)
            state["undo_img"]  = state["work_img"]
            state["work_img"]  = result
            state["modified"]  = True
            undo_btn.disabled   = False
            save_btn.disabled   = False
            enhance_status.value = f"[OK] {model_name} → {result.width}×{result.height} px"
        except Exception as ex:
            enhance_status.value = f"[ERREUR] {model_name} : {ex}"
        finally:
            state["working"]             = False
            enhance_progress_bar.visible = False
            run_model_btn.disabled       = not ESRGAN_AVAILABLE or not _list_pth_models()
            refresh_models_btn.disabled  = False
            has_sel    = state["selection"] is not None
            has_prompt = bool(prompt_field.value and prompt_field.value.strip())
            send_btn.disabled = not (has_sel and has_prompt)
            page.update()
            _render_preview()

    run_model_btn.on_click      = on_run_model
    refresh_models_btn.on_click = on_refresh_models

    # ── Extension IA — outpainting ───────────────────────────────────────────

    _PREV_SZ  = 280
    _BLUE_MAX = 150

    _ep: dict = {
        "bx": 0, "by": 0, "bw": _BLUE_MAX, "bh": _BLUE_MAX,
        "rx1": 0, "ry1": 0, "rx2": _BLUE_MAX, "ry2": _BLUE_MAX,
        "scale_x": 1.0, "scale_y": 1.0,
        "dragging": None, "drag_origin": None, "drag_r_origin": None,
    }

    ep_top_lbl    = ft.Text("Haut : 0 px",    size=11, color=LIGHT_GREY)
    ep_bot_lbl    = ft.Text("Bas : 0 px",     size=11, color=LIGHT_GREY)
    ep_left_lbl   = ft.Text("Gauche : 0 px",  size=11, color=LIGHT_GREY)
    ep_right_lbl  = ft.Text("Droite : 0 px",  size=11, color=LIGHT_GREY)
    ep_canvas     = cv.Canvas(width=_PREV_SZ, height=_PREV_SZ, shapes=[])
    ep_status_lbl = ft.Text("", size=11, color=LIGHT_GREY)
    expand_progress = ft.ProgressBar(color=BLUE, bgcolor=GREY, visible=False)

    def _ep_margins() -> tuple[int, int, int, int]:
        e = _ep
        return (
            max(0, round((e["by"]                    - e["ry1"]) * e["scale_y"])),
            max(0, round((e["ry2"] - e["by"] - e["bh"]) * e["scale_y"])),
            max(0, round((e["bx"]                    - e["rx1"]) * e["scale_x"])),
            max(0, round((e["rx2"] - e["bx"] - e["bw"]) * e["scale_x"])),
        )

    def _ep_redraw() -> None:
        e = _ep
        shapes = ep_canvas.shapes
        shapes.clear()
        shapes.append(cv.Rect(
            x=0, y=0, width=_PREV_SZ, height=_PREV_SZ,
            paint=ft.Paint(color="#2a2a2a", style=ft.PaintingStyle.FILL),
        ))
        rw, rh = e["rx2"] - e["rx1"], e["ry2"] - e["ry1"]
        shapes.append(cv.Rect(
            x=e["rx1"], y=e["ry1"], width=rw, height=rh,
            paint=ft.Paint(
                color=ft.Colors.with_opacity(0.12, ft.Colors.RED_400),
                style=ft.PaintingStyle.FILL,
            ),
        ))
        shapes.append(cv.Rect(
            x=e["rx1"], y=e["ry1"], width=rw, height=rh,
            paint=ft.Paint(
                color=ft.Colors.RED_400,
                style=ft.PaintingStyle.STROKE,
                stroke_width=2.0,
            ),
        ))
        shapes.append(cv.Rect(
            x=e["bx"], y=e["by"], width=e["bw"], height=e["bh"],
            paint=ft.Paint(
                color=ft.Colors.with_opacity(0.25, ft.Colors.BLUE_400),
                style=ft.PaintingStyle.FILL,
            ),
        ))
        shapes.append(cv.Rect(
            x=e["bx"], y=e["by"], width=e["bw"], height=e["bh"],
            paint=ft.Paint(
                color=ft.Colors.BLUE_400,
                style=ft.PaintingStyle.STROKE,
                stroke_width=2.0,
            ),
        ))
        H = 8
        mid_rx = (e["rx1"] + e["rx2"]) / 2
        mid_ry = (e["ry1"] + e["ry2"]) / 2
        for hx, hy in [
            (mid_rx - H / 2, e["ry1"] - H / 2),
            (mid_rx - H / 2, e["ry2"] - H / 2),
            (e["rx1"] - H / 2, mid_ry - H / 2),
            (e["rx2"] - H / 2, mid_ry - H / 2),
        ]:
            shapes.append(cv.Rect(
                x=hx, y=hy, width=H, height=H,
                paint=ft.Paint(color=ft.Colors.RED_400, style=ft.PaintingStyle.FILL),
            ))
        ep_canvas.update()
        top, bot, left, right = _ep_margins()
        ep_top_lbl.value = f"Haut : {top} px"
        ep_top_lbl.update()
        ep_bot_lbl.value = f"Bas : {bot} px"
        ep_bot_lbl.update()
        ep_left_lbl.value = f"Gauche : {left} px"
        ep_left_lbl.update()
        ep_right_lbl.value = f"Droite : {right} px"
        ep_right_lbl.update()

    def _ep_reset() -> None:
        img = state["work_img"] or state["orig_img"]
        if img is None:
            return
        iw, ih = img.size
        if iw >= ih:
            bw, bh = _BLUE_MAX, max(1, round(_BLUE_MAX * ih / iw))
        else:
            bw, bh = max(1, round(_BLUE_MAX * iw / ih)), _BLUE_MAX
        bx, by = (_PREV_SZ - bw) // 2, (_PREV_SZ - bh) // 2
        _ep.update({
            "bx": bx, "by": by, "bw": bw, "bh": bh,
            "rx1": bx, "ry1": by, "rx2": bx + bw, "ry2": by + bh,
            "scale_x": iw / bw, "scale_y": ih / bh,
            "dragging": None, "drag_origin": None, "drag_r_origin": None,
        })

    _HIT_TOL = 10

    def _ep_hit_edge(cx: float, cy: float) -> str | None:
        e = _ep
        t = _HIT_TOL
        checks = [
            ("top",    abs(cy - e["ry1"]) < t and e["rx1"] - t < cx < e["rx2"] + t),
            ("bottom", abs(cy - e["ry2"]) < t and e["rx1"] - t < cx < e["rx2"] + t),
            ("left",   abs(cx - e["rx1"]) < t and e["ry1"] - t < cy < e["ry2"] + t),
            ("right",  abs(cx - e["rx2"]) < t and e["ry1"] - t < cy < e["ry2"] + t),
        ]
        for name, condition in checks:
            if condition:
                return name
        return None

    def _on_ep_pan_start(ev) -> None:
        cx, cy = float(ev.local_position.x), float(ev.local_position.y)
        _ep["dragging"]      = _ep_hit_edge(cx, cy)
        _ep["drag_origin"]   = (cx, cy)
        _ep["drag_r_origin"] = (_ep["rx1"], _ep["ry1"], _ep["rx2"], _ep["ry2"])

    def _on_ep_pan_update(ev) -> None:
        e = _ep
        if not e["dragging"]:
            return
        cx, cy = float(ev.local_position.x), float(ev.local_position.y)
        ox, oy = e["drag_origin"]
        orx1, ory1, orx2, ory2 = e["drag_r_origin"]
        dx, dy = cx - ox, cy - oy
        if e["dragging"] == "top":
            e["ry1"] = max(0, min(ory1 + dy, e["by"]))
        elif e["dragging"] == "bottom":
            e["ry2"] = min(_PREV_SZ, max(ory2 + dy, e["by"] + e["bh"]))
        elif e["dragging"] == "left":
            e["rx1"] = max(0, min(orx1 + dx, e["bx"]))
        elif e["dragging"] == "right":
            e["rx2"] = min(_PREV_SZ, max(orx2 + dx, e["bx"] + e["bw"]))
        _ep_redraw()

    def _on_ep_pan_end(_) -> None:
        _ep["dragging"] = None

    ep_gesture = ft.GestureDetector(
        content=ft.Container(width=_PREV_SZ, height=_PREV_SZ),
        on_pan_start=_on_ep_pan_start,
        on_pan_update=_on_ep_pan_update,
        on_pan_end=_on_ep_pan_end,
        mouse_cursor=ft.MouseCursor.PRECISE,
    )

    expand_btn = ft.Button(
        "Étendre l'image…",
        icon=ft.Icons.PHOTO_SIZE_SELECT_LARGE,
        bgcolor=GREY,
        color=WHITE,
        disabled=True,
        tooltip="Étendre le canevas via Gemini (outpainting)",
    )

    async def on_expand_gemini(_) -> None:
        top, bot, left, right = _ep_margins()
        if top + bot + left + right == 0:
            ep_status_lbl.value = "Glissez les bords rouges pour définir des marges."
            ep_status_lbl.update()
            return
        img = state["work_img"] or state["orig_img"]
        if img is None or state["working"]:
            return

        expand_dialog.open = False
        page.update()

        state["working"]        = True
        send_btn.disabled       = True
        expand_btn.disabled     = True
        expand_progress.value   = None
        expand_progress.visible = True
        iw, ih = img.size
        new_w, new_h = iw + left + right, ih + top + bot
        status_text.value = (
            f"Extension… {iw}×{ih} → {new_w}×{new_h} px  (↑{top} ↓{bot} ←{left} →{right})"
        )
        page.update()

        def _do_expand():
            import numpy as _np2
            img_rgb = img.convert("RGB")
            orig_np = _np2.array(img_rgb, dtype=_np2.uint8)

            canvas_np = _np2.zeros((new_h, new_w, 3), dtype=_np2.uint8)
            canvas_np[top:top + ih, left:left + iw] = orig_np
            if top   > 0: canvas_np[:top,       left:left + iw] = orig_np[0:1]
            if bot   > 0: canvas_np[top + ih:,  left:left + iw] = orig_np[-1:]
            if left  > 0: canvas_np[top:top + ih, :left]        = orig_np[:, 0:1]
            if right > 0: canvas_np[top:top + ih, left + iw:]   = orig_np[:, -1:]
            if top  > 0 and left  > 0: canvas_np[:top,      :left]      = orig_np[0,  0]
            if top  > 0 and right > 0: canvas_np[:top,      left + iw:] = orig_np[0,  -1]
            if bot  > 0 and left  > 0: canvas_np[top + ih:, :left]      = orig_np[-1, 0]
            if bot  > 0 and right > 0: canvas_np[top + ih:, left + iw:] = orig_np[-1, -1]

            sides = ", ".join(filter(None, [
                f"haut {top} px"     if top   else "",
                f"bas {bot} px"      if bot   else "",
                f"gauche {left} px"  if left  else "",
                f"droite {right} px" if right else "",
            ]))
            prompt = (
                f"Cette image ({new_w}×{new_h} px) montre une photo centrale "
                f"({iw}×{ih} px) entourée de zones remplies avec les pixels de bord "
                f"répétés : {sides}. Ces zones répètent simplement la couleur du bord "
                "de la photo. Remplace-les par une extension naturelle et cohérente de "
                "la scène en continuant le style, l'éclairage, les couleurs et les "
                "textures visibles aux bords de la photo centrale. "
                "Ne modifie absolument pas la zone centrale."
            )
            buf = io.BytesIO()
            Image.fromarray(canvas_np).save(buf, format="JPEG", quality=92)
            text_resp, img_bytes = _gemini_generate_image(
                prompt, input_image_bytes=buf.getvalue()
            )
            if not img_bytes:
                return (None, text_resp)

            return (Image.open(io.BytesIO(img_bytes)).convert("RGB").resize(
                (new_w, new_h), Image.Resampling.LANCZOS
            ), text_resp)

        _elapsed = {"s": 0}

        async def _tick():
            while state["working"]:
                await asyncio.sleep(1)
                _elapsed["s"] += 1
                if state["working"]:
                    status_text.value = f"Extension… ({_elapsed['s']}s)"
                    page.update()

        _timer_task = asyncio.create_task(_tick())

        try:
            result, text_resp = await asyncio.wait_for(
                asyncio.to_thread(_do_expand), timeout=300.0
            )
            if result is None:
                status_text.value = f"[Gemini] {text_resp or 'Aucune image reçue.'}"
                return

            state["undo_img"] = (state["work_img"] or state["orig_img"]).copy()
            state["work_img"] = result
            state["modified"] = True
            undo_btn.disabled  = False
            save_btn.disabled  = False
            status_text.value  = f"[OK] {iw}×{ih} → {new_w}×{new_h} px"

        except asyncio.TimeoutError:
            status_text.value = "[ERREUR] Gemini n'a pas répondu en 2 minutes."
        except Exception as ex:
            status_text.value = f"[ERREUR] {ex}"
        finally:
            _timer_task.cancel()
            state["working"]        = False
            expand_progress.visible = False
            expand_btn.disabled     = state["orig_img"] is None
            has_sel    = state["selection"] is not None
            has_prompt = bool(prompt_field.value and prompt_field.value.strip())
            send_btn.disabled = not (has_sel and has_prompt)
            _render_preview()

    def _open_expand_dialog(_) -> None:
        _ep_reset()
        ep_status_lbl.value = ""
        expand_dialog.open  = True
        page.update()
        _ep_redraw()

    expand_btn.on_click = _open_expand_dialog

    expand_dialog = ft.AlertDialog(
        modal=True,
        title=ft.Text("Étendre l'image (Outpainting)"),
        content=ft.Column(
            [
                ft.Text(
                    "Glissez les bords du rectangle rouge pour définir les marges d'extension.",
                    size=11, color=LIGHT_GREY,
                ),
                ft.Container(
                    content=ft.Stack([ep_canvas, ep_gesture]),
                    width=_PREV_SZ, height=_PREV_SZ,
                    border=ft.Border.all(1, GREY),
                    border_radius=6,
                    clip_behavior=ft.ClipBehavior.HARD_EDGE,
                ),
                ft.Row(
                    [
                        ft.Column([ep_top_lbl, ep_bot_lbl],    spacing=2),
                        ft.Column([ep_left_lbl, ep_right_lbl], spacing=2),
                    ],
                    spacing=24,
                ),
                ep_status_lbl,
            ],
            spacing=10,
            tight=True,
        ),
        actions=[
            ft.TextButton(
                "Annuler",
                on_click=lambda e: (setattr(expand_dialog, "open", False), page.update()),
            ),
            ft.TextButton(
                "Valider",
                style=ft.ButtonStyle(color=BLUE),
                on_click=lambda e: page.run_task(on_expand_gemini, e),
            ),
        ],
        actions_alignment=ft.MainAxisAlignment.END,
    )
    page.overlay.append(expand_dialog)

    # ── Suppression de fond (rembg) ──────────────────────────────────────────

    rembg_dropdown = ft.Dropdown(
        options=[
            ft.dropdown.Option("Blanc"),
            ft.dropdown.Option("Gris"),
            ft.dropdown.Option("Flou"),
            ft.dropdown.Option("Transparent"),
        ],
        value="Blanc",
        bgcolor=GREY,
        color=WHITE,
        border_color=LIGHT_GREY,
        text_size=11,
        dense=True,
        expand=True,
        disabled=not REMBG_AVAILABLE,
        tooltip="Type de fond après suppression" if REMBG_AVAILABLE else "pip install rembg onnxruntime",
    )
    rembg_apply_btn = ft.Button(
        "Supprimer le fond",
        icon=ft.Icons.AUTO_FIX_HIGH,
        bgcolor=GREY,
        color=WHITE,
        disabled=True,
        tooltip="Supprimer le fond via rembg" if REMBG_AVAILABLE else "pip install rembg onnxruntime",
    )
    rembg_progress = ft.ProgressBar(color=BLUE, bgcolor=GREY, visible=False)
    rembg_status   = ft.Text("", size=11, color=LIGHT_GREY)

    # 0 = rapide (u2net), 1 = précis (birefnet), 2 = instantané (pipette
    # flood fill, sans IA — cf. Recadrage manuel.pyw, logique partagée
    # via image_ops.FloodPipette).
    _rembg_mode    = [2]
    _rembg_human   = [True]    # True = portrait/human_seg, False = general
    _rembg_sessions: dict = {}
    _rembg_erosion_pct = [0.0]
    _rembg_feather_pct = [0.0]
    _pipette = image_ops.FloodPipette(CONSTANTS.RECADRAGE_FLOOD_TOLERANCE)
    _pipette_start: list = [None]   # (cx, cy) écran, capturé par _on_pan_down

    _rembg_mode_label = ft.Text("Instantané", size=12, color=DARK)
    rembg_precise_btn = ft.Button(
        content=_rembg_mode_label,
        bgcolor=GREEN,
        style=ft.ButtonStyle(padding=ft.Padding.symmetric(horizontal=8, vertical=2)),
        tooltip="Rapide (u2net) / Précis (birefnet) / Instantané (fond uni, sans IA)",
    )

    _rembg_model_label = ft.Text("Humain", size=12, color=DARK)
    rembg_model_btn = ft.Button(
        content=_rembg_model_label,
        bgcolor=VIOLET if REMBG_AVAILABLE else GREY,
        disabled=not REMBG_AVAILABLE,
        style=ft.ButtonStyle(padding=ft.Padding.symmetric(horizontal=8, vertical=2)),
        tooltip="Portrait / Généraliste",
    )

    _pipette_tolerance_label = ft.Text(
        f"Tol. {_pipette.tolerance}", size=11, color=LIGHT_GREY)
    pipette_sign_btn = ft.IconButton(
        icon=ft.Icons.ADD_CIRCLE_OUTLINE,
        icon_color=GREEN,
        tooltip="Pipette : ajoute à la sélection (cliquer pour passer en retrait)",
        visible=_rembg_mode[0] == 2,
        icon_size=18,
        style=ft.ButtonStyle(padding=ft.Padding.all(2)),
    )

    rembg_erosion_slider = ft.Slider(
        value=0, min=0, max=2, divisions=20, label="{value} %",
        active_color=ORANGE, width=90,
    )
    rembg_feather_slider = ft.Slider(
        value=0, min=0, max=0.5, divisions=20, label="{value} %",
        active_color=BLUE, width=90,
    )

    def _sync_pipette_sign_btn() -> None:
        if _pipette.sign == 1:
            pipette_sign_btn.icon = ft.Icons.ADD_CIRCLE_OUTLINE
            pipette_sign_btn.icon_color = GREEN
            pipette_sign_btn.tooltip = "Pipette : ajoute à la sélection (cliquer pour passer en retrait)"
        else:
            pipette_sign_btn.icon = ft.Icons.REMOVE_CIRCLE_OUTLINE
            pipette_sign_btn.icon_color = RED
            pipette_sign_btn.tooltip = "Pipette : retire de la sélection (cliquer pour repasser en ajout)"
        pipette_sign_btn.update()

    def on_pipette_sign_toggle(e) -> None:
        _pipette.toggle_sign()
        _sync_pipette_sign_btn()

    def _on_gesture_secondary_tap(e) -> None:
        """Clic droit sur `image_gesture` : bascule ajoute/retire en mode
        pipette (Fond IA instantané), efface la sélection en mode
        retouche/SAM2 — les deux sessions ne rendent jamais `image_gesture`
        visible en même temps, donc pas de conflit possible entre les deux
        usages (retour user : pourquoi pas le clic droit ici aussi ?)."""
        if state["bg_pick_active"]:
            on_pipette_sign_toggle(e)
        else:
            on_clear_selection(e)

    def _bg_pick_cancel() -> None:
        """Désarme la pipette sans rien appliquer (image_gesture repasse
        en pan normal) — cf. `_pipette_cancel` de Recadrage manuel.pyw."""
        if state["bg_pick_active"]:
            state["bg_pick_active"]   = False
            image_gesture.visible      = False
            preview_viewer.pan_enabled = True
            image_gesture.update()
            preview_viewer.update()

    def on_rembg_precise_toggle(e) -> None:
        _bg_pick_cancel()
        _rembg_mode[0] = (_rembg_mode[0] + 1) % 3
        if _rembg_mode[0] == 0:
            _rembg_mode_label.value = "Rapide"
            rembg_precise_btn.bgcolor = BLUE if REMBG_AVAILABLE else GREY
        elif _rembg_mode[0] == 1:
            _rembg_mode_label.value = "Précis"
            rembg_precise_btn.bgcolor = VIOLET if REMBG_AVAILABLE else GREY
        else:
            _rembg_mode_label.value = "Instantané"
            rembg_precise_btn.bgcolor = GREEN
        rembg_precise_btn.update()
        pipette_sign_btn.visible = _rembg_mode[0] == 2
        pipette_sign_btn.update()
        rembg_apply_btn.disabled = not (REMBG_AVAILABLE or _rembg_mode[0] == 2)
        rembg_apply_btn.update()

    def on_rembg_model_toggle(e) -> None:
        _rembg_human[0] = not _rembg_human[0]
        _rembg_model_label.value = "Humain"   if _rembg_human[0] else "Général"
        rembg_model_btn.bgcolor  = VIOLET     if _rembg_human[0] else ORANGE
        rembg_model_btn.update()

    rembg_precise_btn.on_click = on_rembg_precise_toggle
    rembg_model_btn.on_click   = on_rembg_model_toggle
    pipette_sign_btn.on_click  = on_pipette_sign_toggle

    def on_rembg_erosion_change(e) -> None:
        _rembg_erosion_pct[0] = round(e.control.value, 1)

    def on_rembg_erosion_end(e) -> None:
        _rembg_erosion_pct[0] = round(e.control.value, 1)
        if state["rembg_active"]:
            _rembg_apply_composite()
            _render_preview()
            page.update()

    def on_rembg_feather_change(e) -> None:
        _rembg_feather_pct[0] = round(e.control.value, 2)

    def on_rembg_feather_end(e) -> None:
        _rembg_feather_pct[0] = round(e.control.value, 2)
        if state["rembg_active"]:
            _rembg_apply_composite()
            _render_preview()
            page.update()

    rembg_erosion_slider.on_change     = on_rembg_erosion_change
    rembg_erosion_slider.on_change_end = on_rembg_erosion_end
    rembg_feather_slider.on_change     = on_rembg_feather_change
    rembg_feather_slider.on_change_end = on_rembg_feather_end

    def _rembg_apply_composite() -> None:
        rgba = state["rembg_rgba"]
        if rgba is None:
            return
        if _rembg_erosion_pct[0] > 0:
            r = max(1, round(min(rgba.size) * _rembg_erosion_pct[0] / 100))
            rgba = image_ops.erode_alpha(rgba, r)
        if _rembg_feather_pct[0] > 0:
            f = max(1, round(min(rgba.size) * _rembg_feather_pct[0] / 100))
            rgba = image_ops.feather_alpha(rgba, f)
        mode = rembg_dropdown.value
        if mode == "Transparent":
            state["work_img"] = rgba.copy()
            return
        w, h = rgba.size
        if mode == "Gris":
            bg = Image.new("RGBA", (w, h), (230, 230, 230, 255))
        elif mode == "Flou":
            bg = state["rembg_before"].convert("RGB").filter(
                ImageFilter.GaussianBlur(radius=64)
            ).convert("RGBA")
        else:
            bg = Image.new("RGBA", (w, h), (255, 255, 255, 255))
        bg.paste(rgba, mask=rgba.split()[3])
        state["work_img"] = bg.convert("RGB")

    def on_rembg_bg_change(e) -> None:
        if not state["rembg_active"]:
            return
        _rembg_apply_composite()
        _render_preview()

    async def _apply_pipette_pick(ix: int, iy: int, tolerance: int) -> None:
        """Version définitive du flood fill pipette (mode Instantané) :
        persiste le masque combiné et laisse la pipette armée pour
        enchaîner un autre clic-glissé (ajoute/retire, cf. pipette_sign_btn)."""
        source = state["rembg_before"] or state["work_img"] or state["orig_img"]
        rembg_status.value = "Détourage instantané…"
        page.update()
        try:
            new_mask = await asyncio.to_thread(
                image_ops.flood_background_mask, source, (ix, iy),
                tolerance=tolerance, max_px=1500)
            bg_mask = _pipette.commit(new_mask)
            state["rembg_before"] = source
            if bg_mask is not None:
                state["rembg_rgba"]   = image_ops.compose_bg_alpha(source, bg_mask)
                state["rembg_active"] = True
                _rembg_apply_composite()
                state["modified"]      = True
                undo_btn.disabled      = False
                save_btn.disabled      = False
                rembg_apply_btn.text    = "Restaurer le fond"
                rembg_apply_btn.bgcolor = ORANGE
                rembg_status.value = (
                    "[OK] Fond supprimé — glissez pour ajouter/retirer, recliquer pour restaurer")
            else:
                state["work_img"]     = source
                state["rembg_active"] = False
                rembg_apply_btn.text    = "Supprimer le fond"
                rembg_apply_btn.bgcolor = GREY
                rembg_status.value = "Rien à retirer — glissez d'abord pour ajouter une sélection"
            _pipette_tolerance_label.value = f"Tol. {tolerance}"
        except Exception as ex:
            rembg_status.value = f"[ERREUR] détourage : {ex}"
        finally:
            _render_preview()
            page.update()

    async def _pipette_live_preview(ix: int, iy: int, tolerance: int) -> None:
        """Aperçu en direct pendant le glissé — throttlé par le verrou
        `live_busy`, déjà posé par `_pipette.try_start_live()` (appelant,
        synchrone — cf. sa docstring : le poser ici serait trop tard,
        `page.run_task` ne démarre pas la coroutine immédiatement)."""
        my_gen = _pipette.live_gen = _pipette.live_gen + 1
        try:
            source = state["rembg_before"] or state["work_img"] or state["orig_img"]
            new_mask = await asyncio.to_thread(
                image_ops.flood_background_mask, source, (ix, iy),
                tolerance=tolerance, max_px=900)
            if my_gen != _pipette.live_gen:
                return
            combined = _pipette.combine(new_mask)
            if combined is not None:
                state["rembg_rgba"] = image_ops.compose_bg_alpha(source, combined)
                _rembg_apply_composite()
                _render_preview()
                page.update()
        except Exception:
            pass
        finally:
            _pipette.live_busy = False

    async def on_rembg_toggle(e) -> None:
        if state["work_img"] is None or state["working"]:
            return

        # Pipette armée mais aucun pick encore appliqué : rien à
        # restaurer, ce clic annule juste l'armement.
        if state["bg_pick_active"] and not state["rembg_active"]:
            _bg_pick_cancel()
            rembg_status.value = "Pipette désarmée"
            page.update()
            return

        # Restaurer TOUT le masque accumulé d'un coup (pas juste le
        # dernier pick ajouté/retiré).
        if state["rembg_active"]:
            _bg_pick_cancel()
            state["work_img"]     = state["rembg_before"]
            state["rembg_rgba"]   = None
            state["rembg_before"] = None
            state["rembg_active"] = False
            _pipette.reset()
            _sync_pipette_sign_btn()
            rembg_apply_btn.text    = "Supprimer le fond"
            rembg_apply_btn.bgcolor = GREY
            rembg_status.value = "Fond restauré"
            _render_preview()
            page.update()
            return

        if _rembg_mode[0] == 2:
            # Mode instantané : arme la pipette, le flood fill part du
            # prochain clic-glissé sur l'image (cf. _on_pan_down/_on_pan_end).
            # Fige la source AVANT le premier glissé : sans ça,
            # `_pipette_live_preview` retomberait sur `state["work_img"]`,
            # que `_rembg_apply_composite()` écrase à chaque aperçu avec
            # le fond déjà peint en blanc — le flood fill repartirait
            # alors d'une image de plus en plus blanchie, s'auto-alimentant
            # en boucle quelle que soit la direction du glissé (retour user).
            _pipette.arm()
            state["rembg_before"]     = state["work_img"]
            state["bg_pick_active"]   = True
            image_gesture.visible      = True
            preview_viewer.pan_enabled = False
            image_gesture.update()
            preview_viewer.update()
            rembg_status.value = "Cliquez sur le fond et glissez pour ajuster la sensibilité…"
            page.update()
            return

        state["working"]         = True
        rembg_apply_btn.disabled = True
        rembg_progress.value     = None
        rembg_progress.visible   = True
        rembg_status.value       = "Suppression du fond…"
        page.update()

        base = state["work_img"].copy()

        def _do_rembg():
            import rembg as _rembg
            if _rembg_mode[0] == 1:
                model = "birefnet-portrait" if _rembg_human[0] else "birefnet-general"
            else:
                model = "u2net_human_seg" if _rembg_human[0] else "u2net"
            if model not in _rembg_sessions:
                _rembg_sessions[model] = _rembg.new_session(model)
            return _rembg.remove(base.convert("RGB"), session=_rembg_sessions[model])

        try:
            rgba = await asyncio.to_thread(_do_rembg)
            state["rembg_before"] = base
            state["rembg_rgba"]   = rgba
            state["rembg_active"] = True
            _rembg_apply_composite()
            state["modified"]       = True
            undo_btn.disabled       = False
            save_btn.disabled       = False
            rembg_apply_btn.text    = "Restaurer le fond"
            rembg_apply_btn.bgcolor = ORANGE
            rembg_status.value      = "[OK] Fond supprimé"
        except Exception as ex:
            rembg_status.value = f"[ERREUR] {ex}"
        finally:
            state["working"]         = False
            rembg_progress.visible   = False
            rembg_apply_btn.disabled = False
            page.update()
            if state["rembg_active"]:
                _render_preview()

    rembg_apply_btn.on_click = on_rembg_toggle
    rembg_dropdown.on_change = on_rembg_bg_change

    # ── Câblage des événements ───────────────────────────────────────────────
    send_btn.on_click      = on_send_gemini
    undo_btn.on_click      = on_undo
    save_btn.on_click      = on_save
    open_btn.on_click      = on_open
    prompt_field.on_change = on_prompt_change
    prev_btn.on_click      = on_prev
    next_btn.on_click      = on_next

    # ── Bouton Retouche IA (remplace mode_btn) ───────────────────────────────
    inpaint_btn = ft.Button(
        "Retouche IA",
        icon=ft.Icons.AUTO_FIX_HIGH,
        bgcolor=GREY,
        color=WHITE,
        disabled=True,
        tooltip="Activer la sélection — glisser pour définir la zone à retoucher",
    )

    # ── Bouton Ignorer / Suivant ─────────────────────────────────────────────
    ignore_btn = ft.Button(
        "Ignorer / Suivant",
        icon=ft.Icons.SKIP_NEXT,
        bgcolor=GREY,
        color=WHITE,
        tooltip="Ignorer cette image et passer à la suivante",
    )

    async def on_ignore(_) -> None:
        next_index = state["index"] + 1
        if next_index < len(all_images):
            await _load_image(next_index)
        else:
            await page.window.close()

    ignore_btn.on_click = on_ignore

    # ── Gesture detector (rubber band, à l'intérieur de l'InteractiveViewer) ──
    image_gesture = ft.GestureDetector()
    image_gesture.content               = ft.Container(expand=True)
    image_gesture.on_pan_down           = _on_pan_down     # pipette (mode Instantané) — position immédiate
    image_gesture.on_pan_start          = _on_pan_start
    image_gesture.on_pan_update         = _on_pan_update
    image_gesture.on_pan_end            = _on_pan_end
    image_gesture.on_pan_cancel         = _on_pan_cancel
    image_gesture.on_tap_up             = _on_tap_click
    image_gesture.on_secondary_tap_down = _on_gesture_secondary_tap
    image_gesture.mouse_cursor          = ft.MouseCursor.PRECISE
    image_gesture.visible               = False

    _vw, _vh = state["view_size"]
    inner_container = ft.Container(
        content=ft.Stack([preview_img, sel_canvas, image_gesture, busy_ring_wrap]),
        width=_vw,
        height=_vh,
        bgcolor="#1e1e1e",
    )

    preview_viewer = ft.InteractiveViewer(
        content=inner_container,
        pan_enabled=True,
        scale_enabled=True,
        min_scale=0.1,
        max_scale=10.0,
    )

    async def on_inpaint_btn(_) -> None:
        state["sel_mode"] = not state["sel_mode"]
        if state["sel_mode"]:
            inpaint_btn.text           = "Annuler sélection"
            inpaint_btn.icon           = ft.Icons.CROP_FREE
            inpaint_btn.bgcolor        = BLUE
            image_gesture.visible      = True
            preview_viewer.pan_enabled = False
        else:
            inpaint_btn.text           = "Retouche IA"
            inpaint_btn.icon           = ft.Icons.AUTO_FIX_HIGH
            inpaint_btn.bgcolor        = GREY
            image_gesture.visible      = False
            preview_viewer.pan_enabled = True
            state["drag_start"]        = None
            state["drag_current"]      = None
            _update_sel_canvas()
        inpaint_btn.update()
        image_gesture.update()
        preview_viewer.update()

    inpaint_btn.on_click = on_inpaint_btn

    # ── Dialog inpainting ────────────────────────────────────────────────────
    def _cancel_inpaint_dialog(e=None) -> None:
        """Ferme le dialogue sans redessiner ni envoyer — retour user :
        coincé sans savoir comment fermer/annuler pendant que le dialogue
        (modal) empêchait tout, y compris cliquer sur le bouton Fermer de
        la fenêtre."""
        inpaint_dialog.open        = False
        state["selection"]         = None
        state["selection_mask"]    = None
        state["sel_mode"]          = False
        image_gesture.visible      = False
        preview_viewer.pan_enabled = True
        sel_info.value = "Sélection annulée — clic pour un objet, glisser pour une zone"
        send_btn.disabled = True
        _render_preview()

    def _reopen_selection() -> None:
        inpaint_dialog.open        = False
        state["sel_mode"]          = True
        state["selection"]         = None
        state["selection_mask"]    = None
        state["drag_start"]        = None
        state["drag_current"]      = None
        inpaint_btn.text           = "Annuler sélection"
        inpaint_btn.icon           = ft.Icons.CROP_FREE
        inpaint_btn.bgcolor        = BLUE
        image_gesture.visible      = True
        preview_viewer.pan_enabled = False
        _render_preview()

    inpaint_dialog = ft.AlertDialog(
        modal=True,
        title=ft.Text("Retouche IA (Gemini)"),
        content=ft.Column(
            [sel_info, dilate_row, prompt_field, progress_bar],
            tight=True,
            spacing=10,
            width=420,
        ),
        actions=[
            ft.TextButton(
                "Annuler",
                style=ft.ButtonStyle(color=LIGHT_GREY),
                on_click=_cancel_inpaint_dialog,
            ),
            ft.TextButton(
                "Redessiner",
                on_click=lambda e: _reopen_selection(),
            ),
            send_btn,
        ],
        actions_alignment=ft.MainAxisAlignment.END,
    )
    page.overlay.append(inpaint_dialog)

    # ── Mise en page ─────────────────────────────────────────────────────────
    left_panel = ft.Column(
        [
            ft.Text("Modèle IA local", size=12, color=LIGHT_GREY),
            ft.Row(
                [model_dropdown, refresh_models_btn, run_model_btn],
                spacing=4,
                vertical_alignment=ft.CrossAxisAlignment.CENTER,
            ),
            enhance_progress_bar,
            enhance_status,
            ft.Divider(color=GREY),
            inpaint_btn,
            expand_btn,
            expand_progress,
            feather_row,
            undo_btn,
            ft.Divider(color=GREY),
            ft.Text("Suppression de fond", size=12, color=LIGHT_GREY),
            rembg_dropdown,
            rembg_apply_btn,
            ft.Row([rembg_precise_btn, rembg_model_btn, pipette_sign_btn,
                    _pipette_tolerance_label], spacing=6, wrap=True),
            ft.Row([
                ft.Text("Ér.", size=11, color=LIGHT_GREY), rembg_erosion_slider,
                ft.Text("Ad.", size=11, color=LIGHT_GREY), rembg_feather_slider,
            ], spacing=2, vertical_alignment=ft.CrossAxisAlignment.CENTER),
            rembg_progress,
            rembg_status,
            ft.Divider(color=GREY),
            save_btn,
            ignore_btn,
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

    # ── Dialog de confirmation de fermeture ──────────────────────────────────

    async def _force_close() -> None:
        page.window.visible = False
        page.update()
        await page.window.destroy()

    async def _dialog_save() -> None:
        close_dialog.open = False
        page.update()
        path = _retouche_path()
        if path and await _save_to(path):
            await _force_close()

    close_dialog = ft.AlertDialog(
        modal=True,
        title=ft.Text("Modifications non enregistrées"),
        content=ft.Text(
            "L'image a été modifiée mais n'a pas été enregistrée.\n"
            "Que souhaitez-vous faire ?"
        ),
        actions=[
            ft.TextButton(
                "Enregistrer",
                on_click=lambda e: page.run_task(_dialog_save),
            ),
            ft.TextButton(
                "Quitter sans enregistrer",
                style=ft.ButtonStyle(color=RED),
                on_click=lambda e: page.run_task(_force_close),
            ),
        ],
        actions_alignment=ft.MainAxisAlignment.END,
    )
    page.overlay.append(close_dialog)

    async def on_close_btn(e) -> None:
        if state["modified"]:
            close_dialog.open = True
            page.update()
        else:
            await _force_close()

    title_bar = ft.WindowDragArea(
        ft.Row(
            [
                ft.Container(
                    ft.Text(
                        f"Retouche IA par sélection  v{__version__}",
                        size=13,
                        color=LIGHT_GREY,
                        expand=True,
                    ),
                    bgcolor=BG_UI,
                    padding=10,
                    expand=True,
                ),
                ft.IconButton(
                    icon=ft.Icons.CLOSE,
                    icon_color=LIGHT_GREY,
                    tooltip="Fermer",
                    on_click=on_close_btn,
                    style=ft.ButtonStyle(
                        overlay_color=ft.Colors.with_opacity(0.15, RED),
                    ),
                ),
            ],
        )
    )

    page.add(
        ft.Column(
            [
                title_bar,
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
                ),
            ],
            expand=True,
            spacing=0,
        )
    )

    # ── Resize ───────────────────────────────────────────────────────────────

    _TITLEBAR_H = 32
    # left_panel (width=290) + son padding gauche/droite (12+12) + le
    # séparateur ft.Container(width=12) entre les deux colonnes = 326, PAS
    # 340 comme avant. Cet écart de 14px faisait sous-dimensionner
    # `inner_container` par rapport à l'espace réellement disponible dans
    # `center_panel` -> InteractiveViewer recentrait le contenu dans un
    # viewport plus large que ce que cette fonction croyait, décalant la
    # sélection (rubber band) par rapport à l'image sous-jacente (retour
    # user). Si les largeurs de left_panel/padding/séparateur changent,
    # cette constante doit suivre.
    _LEFT_CHROME_W = 290 + 24 + 12

    def _on_page_resize(e=None) -> None:
        w = int(getattr(e, "width",  None) or page.width  or 1200)
        h = int(getattr(e, "height", None) or page.height or 800)
        vw = max(640, w - _LEFT_CHROME_W)
        vh = max(480, h - _TITLEBAR_H - 60)
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
