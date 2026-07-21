# -*- coding: utf-8 -*-
"""
ai_ops.py — Retouche générative, extension de cadre et amélioration IA.

Sépare les opérations à dépendances lourdes (torch/spandrel, google-genai)
d'`image_ops.py` : import paresseux, aucun coût si le tiroir IA de la
visionneuse n'est jamais ouvert. Reprend fidèlement la logique de
`Data/Augmentation IA.py` (feathering, edge-padding, tiling spandrel),
dépouillée des callbacks Flet (`page.update()`, widgets).
"""
import io
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import CONSTANTS
from ai_tools import _gemini_generate_image

from PIL import Image, ImageDraw, ImageFilter

_MODELS_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "models")

# Cache des modèles spandrel chargés (par nom de fichier), vit tant que le
# process Python vit — même pattern que Augmentation IA.py.
_loaded_model_cache = {}


def _pick_torch_device() -> str:
    import torch
    if torch.cuda.is_available():
        return "cuda"
    if getattr(torch.backends, "mps", None) and torch.backends.mps.is_available():
        return "mps"
    return "cpu"


def list_pth_models() -> list[str]:
    """Noms des modèles .pth/.safetensors disponibles dans Data/models/."""
    if not os.path.isdir(_MODELS_DIR):
        return []
    return sorted(
        e.name for e in os.scandir(_MODELS_DIR)
        if e.name.lower().endswith((".pth", ".safetensors")))


def run_inpaint(image: Image.Image, rect: tuple[int, int, int, int],
                 prompt: str, *, feather_ratio: float | None = None,
                 timeout: float = 120.0) -> Image.Image:
    """Retouche générative Gemini sur la zone `rect` (x1, y1, x2, y2) de
    `image`, réintégrée avec un fondu de bords (feathering). Reprend
    `Augmentation IA.py::on_send_gemini` + `_composite_retouch`.
    """
    x1, y1, x2, y2 = rect
    sel_w, sel_h = x2 - x1, y2 - y1
    crop = image.convert("RGB").crop(rect)

    full_prompt = CONSTANTS.AI_RETOUCH_SYSTEM_PROMPT + prompt
    buf = io.BytesIO()
    crop.save(buf, format="JPEG", quality=95)
    text_resp, image_bytes = _gemini_generate_image(
        full_prompt, input_image_bytes=buf.getvalue())
    if image_bytes is None:
        raise RuntimeError(text_resp or "Gemini n'a renvoyé aucune image.")

    gemini_img = Image.open(io.BytesIO(image_bytes)).convert("RGB")
    gemini_fit = gemini_img.resize((sel_w, sel_h), Image.Resampling.LANCZOS)

    ratio = (feather_ratio if feather_ratio is not None
             else CONSTANTS.AI_RETOUCH_FEATHER_RATIO)
    feather = max(CONSTANTS.AI_RETOUCH_FEATHER_MIN,
                  int(min(sel_w, sel_h) * ratio))
    feather = min(feather, min(sel_w, sel_h) // 2)
    mask = Image.new("L", (sel_w, sel_h), 0)
    ImageDraw.Draw(mask).rectangle(
        (feather, feather, sel_w - feather, sel_h - feather), fill=255)
    mask = mask.filter(ImageFilter.GaussianBlur(feather))

    result = image.convert("RGB").copy()
    result.paste(gemini_fit, (x1, y1), mask)
    return result


def run_outpaint(image: Image.Image, margins_px: tuple[int, int, int, int],
                  prompt: str | None = None, *, timeout: float = 300.0
                  ) -> Image.Image:
    """Extension de cadre (outpainting) via Gemini. `margins_px` =
    (haut, bas, gauche, droite). Reprend `Augmentation IA.py::_do_expand` :
    edge-padding (répétition du pixel de bord) + remplissage Gemini.
    """
    import numpy as np

    top, bot, left, right = margins_px
    img_rgb = image.convert("RGB")
    iw, ih = img_rgb.size
    new_w, new_h = iw + left + right, ih + top + bot
    orig_np = np.array(img_rgb, dtype=np.uint8)

    canvas_np = np.zeros((new_h, new_w, 3), dtype=np.uint8)
    canvas_np[top:top + ih, left:left + iw] = orig_np
    if top > 0:
        canvas_np[:top, left:left + iw] = orig_np[0:1]
    if bot > 0:
        canvas_np[top + ih:, left:left + iw] = orig_np[-1:]
    if left > 0:
        canvas_np[top:top + ih, :left] = orig_np[:, 0:1]
    if right > 0:
        canvas_np[top:top + ih, left + iw:] = orig_np[:, -1:]
    if top > 0 and left > 0:
        canvas_np[:top, :left] = orig_np[0, 0]
    if top > 0 and right > 0:
        canvas_np[:top, left + iw:] = orig_np[0, -1]
    if bot > 0 and left > 0:
        canvas_np[top + ih:, :left] = orig_np[-1, 0]
    if bot > 0 and right > 0:
        canvas_np[top + ih:, left + iw:] = orig_np[-1, -1]

    sides = ", ".join(filter(None, [
        f"haut {top} px" if top else "",
        f"bas {bot} px" if bot else "",
        f"gauche {left} px" if left else "",
        f"droite {right} px" if right else "",
    ]))
    full_prompt = prompt or (
        f"Cette image ({new_w}×{new_h} px) montre une photo centrale "
        f"({iw}×{ih} px) entourée de zones remplies avec les pixels de bord "
        f"répétés : {sides}. Ces zones répètent simplement la couleur du "
        "bord de la photo. Remplace-les par une extension naturelle et "
        "cohérente de la scène en continuant le style, l'éclairage, les "
        "couleurs et les textures visibles aux bords de la photo centrale. "
        "Ne modifie absolument pas la zone centrale.")

    buf = io.BytesIO()
    Image.fromarray(canvas_np).save(buf, format="JPEG", quality=92)
    text_resp, image_bytes = _gemini_generate_image(
        full_prompt, input_image_bytes=buf.getvalue())
    if not image_bytes:
        raise RuntimeError(text_resp or "Gemini n'a renvoyé aucune image.")

    return Image.open(io.BytesIO(image_bytes)).convert("RGB").resize(
        (new_w, new_h), Image.Resampling.LANCZOS)


def run_upscale(image: Image.Image, model_name: str,
                 progress_cb=None) -> Image.Image:
    """Amélioration/upscale via un modèle local `.pth`/`.safetensors`
    (spandrel), tuilé avec overlap-add pondéré. Reprend
    `Augmentation IA.py::on_run_model::_do_run`.

    `progress_cb(value, label)` : `value` dans [0, 1] ou None (indéterminé).
    """
    import numpy as np
    import torch
    from spandrel import ModelLoader

    def _progress(value, label=""):
        if progress_cb:
            progress_cb(value, label)

    model_path = os.path.join(_MODELS_DIR, model_name)
    if model_name not in _loaded_model_cache:
        device = _pick_torch_device()
        _progress(None, f"Chargement de {model_name}…")
        desc = ModelLoader().load_from_file(model_path)
        desc.to(device)
        desc.model.eval()
        _loaded_model_cache[model_name] = desc
    desc = _loaded_model_cache[model_name]
    device = next(iter(desc.model.parameters())).device
    use_fp16 = device.type == "cuda"

    has_alpha = image.mode == "RGBA"
    alpha = image.split()[3] if has_alpha else None

    rgb = np.array(image.convert("RGB")).astype(np.float32) / 255.0
    h, w = rgb.shape[:2]

    tile = 512 if device.type == "cuda" else (384 if device.type == "mps" else 256)
    overlap = tile // 16
    step = tile - overlap

    def _scale_factor():
        probe = torch.zeros(1, 3, 4, 4, device=device)
        if use_fp16:
            probe = probe.half()
        with torch.inference_mode():
            return desc(probe).shape[-1] // 4

    scale = _scale_factor()
    out_h, out_w = h * scale, w * scale
    out_np_full = np.zeros((out_h, out_w, 3), dtype=np.float32)
    weight_map = np.zeros((out_h, out_w, 1), dtype=np.float32)

    def _make_weight(th, tw):
        wy = np.ones(th, dtype=np.float32)
        wx = np.ones(tw, dtype=np.float32)
        fade = min(overlap, th // 2, tw // 2)
        ramp = np.linspace(0.0, 1.0, fade, dtype=np.float32)
        wy[:fade] = ramp
        wy[-fade:] = ramp[::-1]
        wx[:fade] = ramp
        wx[-fade:] = ramp[::-1]
        return np.outer(wy, wx)[:, :, np.newaxis]

    ys = list(range(0, h - tile, step)) + [max(0, h - tile)]
    xs = list(range(0, w - tile, step)) + [max(0, w - tile)]
    if h <= tile and w <= tile:
        ys, xs = [0], [0]

    total_tiles = len(ys) * len(xs)
    done_tiles = 0
    _progress(0.0, f"Traitement — tuile 0/{total_tiles}")

    with torch.inference_mode():
        for y0 in ys:
            y1 = min(y0 + tile, h)
            for x0 in xs:
                x1 = min(x0 + tile, w)
                tile_np = rgb[y0:y1, x0:x1]
                tile_t = torch.from_numpy(tile_np).permute(2, 0, 1).unsqueeze(0).to(device)
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
                weight_map[oy0:oy1, ox0:ox1] += w_tile
                done_tiles += 1
                _progress(done_tiles / total_tiles,
                          f"Traitement — tuile {done_tiles}/{total_tiles}")

    out_np = ((out_np_full / np.maximum(weight_map, 1e-6)).clip(0, 1) * 255
              ).astype(np.uint8)
    out = Image.fromarray(out_np)
    if has_alpha and alpha is not None:
        out = out.convert("RGBA")
        out.putalpha(alpha.resize(out.size, Image.Resampling.LANCZOS))
    return out
