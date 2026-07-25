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
                 resolution: str = "1K", timeout: float = 120.0) -> Image.Image:
    """Retouche générative Gemini sur la zone `rect` (x1, y1, x2, y2) de
    `image`, réintégrée avec un fondu de bords (feathering). Reprend
    `Augmentation IA.py::on_send_gemini` + `_composite_retouch`.

    `resolution` ("1K"/"2K"/"4K") : une petite zone retouchée n'a pas
    besoin de la même qualité qu'une pleine image (coût/temps Gemini) —
    à choisir selon la taille de `rect` et l'usage (aperçu vs impression).
    """
    x1, y1, x2, y2 = rect
    sel_w, sel_h = x2 - x1, y2 - y1
    crop = image.convert("RGB").crop(rect)

    full_prompt = CONSTANTS.AI_RETOUCH_SYSTEM_PROMPT + prompt
    buf = io.BytesIO()
    crop.save(buf, format="JPEG", quality=95)
    text_resp, image_bytes = _gemini_generate_image(
        full_prompt, input_image_bytes=buf.getvalue(), resolution=resolution)
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
                  prompt: str | None = None, *, upscale_model: str | None = None,
                  resolution: str = "4K", progress_cb=None, timeout: float = 300.0
                  ) -> tuple[Image.Image, Image.Image]:
    """Extension de cadre (outpainting) via Gemini. `margins_px` =
    (haut, bas, gauche, droite). Reprend `Augmentation IA.py::_do_expand` :
    edge-padding (répétition du pixel de bord) + remplissage Gemini.

    Priorité qualité impression : Gemini plafonne sa sortie (~4K) quel que
    soit le canevas envoyé ; la marge générée est donc portée à la taille
    cible via un modèle de sur-échantillonnage IA (`upscale_model`, cf.
    `list_pth_models`/`run_upscale`) plutôt qu'un simple redimensionnement.

    Fidélité des couleurs : quand un seul côté est étendu (pas de coin à
    combler), on ne montre à Gemini qu'une bande de contexte proche du
    bord (cf. `CONSTANTS.AI_EXPAND_CONTEXT_RATIO`) plutôt que la photo
    entière — celle-ci est de toute façon rabotée à ~4K avant l'envoi
    (thumbnail côté API), ce qui dilue les couleurs/textures près du bord
    sur les photos de plusieurs milliers de px, pile là où la continuité
    de teinte compte le plus (retour user : teintes pas respectées après
    extension). Avec 2+ côtés étendus (coins à combler), retombe sur la
    photo entière comme avant.

    Retourne `(gemini_canvas, img_rgb)` — le canevas généré (déjà à la
    taille cible new_w×new_h) et l'image d'origine RGB, SANS recollage :
    `composite_outpaint` fait ce dernier collage (photo d'origine au pixel
    près + fondu réglable) séparément, pour permettre de rejouer le fondu
    (slider) sans refaire l'appel Gemini.
    """
    import numpy as np

    top, bot, left, right = margins_px
    img_rgb = image.convert("RGB")
    iw, ih = img_rgb.size
    new_w, new_h = iw + left + right, ih + top + bot

    active_sides = sum(1 for m in margins_px if m > 0)
    single_side = active_sides == 1

    if single_side:
        def _depth(dim):
            return min(dim, max(CONSTANTS.AI_EXPAND_CONTEXT_MIN_PX,
                                round(dim * CONSTANTS.AI_EXPAND_CONTEXT_RATIO)))
        if left > 0:
            d = _depth(iw)
            crop_box = (0, 0, d, ih)
        elif right > 0:
            d = _depth(iw)
            crop_box = (iw - d, 0, iw, ih)
        elif top > 0:
            d = _depth(ih)
            crop_box = (0, 0, iw, d)
        else:  # bot > 0
            d = _depth(ih)
            crop_box = (0, ih - d, iw, ih)
        context_img = img_rgb.crop(crop_box)
    else:
        context_img = img_rgb

    cw, ch = context_img.size
    ctx_new_w, ctx_new_h = cw + left + right, ch + top + bot
    ctx_np = np.array(context_img, dtype=np.uint8)

    canvas_np = np.zeros((ctx_new_h, ctx_new_w, 3), dtype=np.uint8)
    canvas_np[top:top + ch, left:left + cw] = ctx_np
    if top > 0:
        canvas_np[:top, left:left + cw] = ctx_np[0:1]
    if bot > 0:
        canvas_np[top + ch:, left:left + cw] = ctx_np[-1:]
    if left > 0:
        canvas_np[top:top + ch, :left] = ctx_np[:, 0:1]
    if right > 0:
        canvas_np[top:top + ch, left + cw:] = ctx_np[:, -1:]
    if top > 0 and left > 0:
        canvas_np[:top, :left] = ctx_np[0, 0]
    if top > 0 and right > 0:
        canvas_np[:top, left + cw:] = ctx_np[0, -1]
    if bot > 0 and left > 0:
        canvas_np[top + ch:, :left] = ctx_np[-1, 0]
    if bot > 0 and right > 0:
        canvas_np[top + ch:, left + cw:] = ctx_np[-1, -1]

    sides = ", ".join(filter(None, [
        f"haut {top} px" if top else "",
        f"bas {bot} px" if bot else "",
        f"gauche {left} px" if left else "",
        f"droite {right} px" if right else "",
    ]))
    full_prompt = prompt or (
        f"Cette image ({ctx_new_w}×{ctx_new_h} px) montre un extrait de photo "
        f"({cw}×{ch} px) entouré de zones remplies avec les pixels de bord "
        f"répétés : {sides}. Ces zones répètent simplement la couleur du "
        "bord de la photo. Remplace-les par une extension naturelle et "
        "cohérente de la scène en continuant le style, l'éclairage, les "
        "couleurs et les textures visibles aux bords de l'extrait fourni. "
        "Ne modifie absolument pas la zone centrale.")

    buf = io.BytesIO()
    Image.fromarray(canvas_np).save(buf, format="JPEG", quality=92)
    text_resp, image_bytes = _gemini_generate_image(
        full_prompt, input_image_bytes=buf.getvalue(),
        aspect_ratio=f"{ctx_new_w}:{ctx_new_h}", resolution=resolution)
    if not image_bytes:
        raise RuntimeError(text_resp or "Gemini n'a renvoyé aucune image.")

    gemini_img = Image.open(io.BytesIO(image_bytes)).convert("RGB")

    # Gemini plafonne sa sortie (~4K) : au-delà, un modèle de
    # sur-échantillonnage IA préserve bien plus de détail qu'un simple
    # redimensionnement pour la marge nouvellement générée.
    if upscale_model and (gemini_img.width < ctx_new_w or gemini_img.height < ctx_new_h):
        gemini_img = run_upscale(gemini_img, upscale_model, progress_cb=progress_cb)

    if gemini_img.size != (ctx_new_w, ctx_new_h):
        gemini_img = gemini_img.resize((ctx_new_w, ctx_new_h), Image.Resampling.LANCZOS)

    if not single_side:
        return gemini_img, img_rgb

    # On a généré sur le contexte réduit, pas la photo entière : extraire
    # la marge neuve et la recoller dans un canevas plein format (le
    # reste, c'est la photo d'origine — déjà en pleine résolution, aucune
    # raison de repasser par Gemini pour ça). On déborde de toute la
    # bande de contexte (`d`, la version régénérée par Gemini, pas la
    # vraie photo) pour que le fondu réglable (`composite_outpaint`) ait
    # de quoi recouvrir sur toute sa plage un éventuel artefact pile à la
    # jonction contexte/marge côté Gemini (retour user : sans ce
    # débordement, cette zone valait exactement la vraie photo des deux
    # côtés du fondu — mélanger une image avec elle-même ne change rien,
    # quel que soit le réglage du slider). `img_rgb` est collé en
    # PREMIER : la marge (avec son débordement) est collée APRÈS et gagne
    # donc sur ce recouvrement ; `composite_outpaint` replace de toute
    # façon la vraie photo par-dessus avec son propre fondu.
    overlap = d
    full_canvas = Image.new("RGB", (new_w, new_h))
    full_canvas.paste(img_rgb, (left, top))
    if left > 0:
        strip = gemini_img.crop((0, 0, left + overlap, ctx_new_h))
        full_canvas.paste(strip, (0, top))
    elif right > 0:
        strip = gemini_img.crop((ctx_new_w - right - overlap, 0, ctx_new_w, ctx_new_h))
        full_canvas.paste(strip, (left + iw - overlap, top))
    elif top > 0:
        strip = gemini_img.crop((0, 0, ctx_new_w, top + overlap))
        full_canvas.paste(strip, (left, 0))
    else:  # bot > 0
        strip = gemini_img.crop((0, ctx_new_h - bot - overlap, ctx_new_w, ctx_new_h))
        full_canvas.paste(strip, (left, top + ih - overlap))

    return full_canvas, img_rgb


def composite_outpaint(gemini_canvas: Image.Image, img_rgb: Image.Image,
                        margins_px: tuple[int, int, int, int],
                        feather_ratio: float = CONSTANTS.AI_EXPAND_FEATHER_RATIO
                        ) -> Image.Image:
    """Recolle `img_rgb` (photo d'origine, jamais régénérée) sur
    `gemini_canvas` (marge générée par `run_outpaint`) avec un fondu de
    raccord réglable. Opération légère (paste + flou gaussien, aucun appel
    réseau) — rappelable à volonté depuis un slider, comme
    `Augmentation IA.py::_composite_retouch` pour la retouche.

    Le masque de fondu est dimensionné à `img_rgb` (pas au canevas entier)
    avec le rectangle blanc RENTRÉ de `feather` px avant le flou — la
    transition reste donc entièrement À L'INTÉRIEUR de la photo d'origine.
    Un masque dessiné à pleine taille avec un fondu symétrique déborderait
    dans la marge, où le côté « photo d'origine » du mélange n'a pas de
    pixels valides (fond noir par défaut) : ligne noire marquée au raccord,
    quel que soit le fondu choisi (retour user).
    """
    top, bot, left, right = margins_px
    iw, ih = img_rgb.size

    feather = max(CONSTANTS.AI_EXPAND_FEATHER_MIN,
                  int(min(iw, ih) * feather_ratio))
    feather = min(feather, min(iw, ih) // 2)
    mask = Image.new("L", (iw, ih), 0)
    ImageDraw.Draw(mask).rectangle(
        (feather, feather, iw - feather, ih - feather), fill=255)
    mask = mask.filter(ImageFilter.GaussianBlur(feather))

    result = gemini_canvas.copy()
    result.paste(img_rgb, (left, top), mask)
    return result


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
        use_fp16 = device == "cuda" and desc.supports_half
        desc.to(device, torch.float16 if use_fp16 else torch.float32)
        desc.model.eval()
        _loaded_model_cache[model_name] = desc
    desc = _loaded_model_cache[model_name]
    device = next(iter(desc.model.parameters())).device
    use_fp16 = desc.dtype == torch.float16

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
