# -*- coding: utf-8 -*-
"""
image_ops.py — Traitement d'image pur (recadrage, couleur, planches).

Aucune dépendance à Flet ni à un état de session : chaque fonction reçoit
ses paramètres explicitement et retourne une nouvelle `PIL.Image.Image`.
Module partagé par `Hub.pyw` (tiroirs de la visionneuse) et par
`Data/Recadrage manuel.pyw` (qui l'importe au lieu de dupliquer sa propre
logique de traitement).

Toutes les fonctions ci-dessous sont des extractions fidèles de
`Data/Recadrage manuel.pyw` (classe `PhotoCropper`) : mêmes formules, mêmes
noms, `self.xxx` remplacés par des paramètres explicites.
"""
import io
import math
import os
import sys
from dataclasses import dataclass

import numpy as np
from PIL import Image, ImageCms, ImageEnhance, ImageFilter

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import CONSTANTS

DPI = CONSTANTS.DPI

# Profil sRGB pré-construit (réutilisé pour chaque export).
_SRGB_PROFILE = ImageCms.createProfile("sRGB")
_SRGB_ICC = ImageCms.ImageCmsProfile(_SRGB_PROFILE).tobytes()


def mm_to_pixels(mm, dpi=DPI):
    """Convertit une dimension en millimètres en nombre de pixels entiers."""
    return int(mm / 25.4 * dpi)


def convert_to_srgb(source_image: Image.Image,
                     icc_profile: bytes | None) -> Image.Image:
    """Convertit une image PIL vers l'espace colorimétrique sRGB."""
    if not icc_profile:
        return source_image  # déjà sRGB par défaut
    try:
        src_profile = ImageCms.ImageCmsProfile(io.BytesIO(icc_profile))
        rgb_image = source_image.convert("RGB")
        return ImageCms.profileToProfile(
            rgb_image, src_profile, _SRGB_PROFILE,
            renderingIntent=ImageCms.Intent.PERCEPTUAL,
            outputMode="RGB",
        )
    except Exception:
        return source_image


def erode_alpha(source_image: Image.Image, radius: int) -> Image.Image:
    """Érode le canal alpha d'une image RGBA d'environ ``radius`` pixels."""
    if source_image.mode != "RGBA" or radius <= 0:
        return source_image
    r, g, b, alpha_channel = source_image.split()
    for _ in range(radius):
        alpha_channel = alpha_channel.filter(ImageFilter.MinFilter(3))
    return Image.merge("RGBA", (r, g, b, alpha_channel))


# ================================================================ #
#                    GÉOMÉTRIE DU RECADRAGE                        #
# ================================================================ #

@dataclass
class CropView:
    """État géométrique minimal nécessaire au calcul d'un recadrage.

    Reprend les attributs utilisés par `PhotoCropper` (Recadrage manuel.pyw)
    pour `_get_transformed_bounds`/`_clamp_offsets`/`_compute_crop_with_canvas` :
    canevas écran, échelle de base (couverture), pan utilisateur, zoom,
    rotation fine et dimensions de l'image source.
    """
    canvas_w: float
    canvas_h: float
    base_scale: float
    offset_x: float
    offset_y: float
    scale: float
    rotation: float           # degrés
    original_width: int
    original_height: int
    display_w: float          # ~ original_width * base_scale (cf. load_image)
    display_h: float          # ~ original_height * base_scale


def get_transformed_bounds(view: CropView) -> tuple[float, float]:
    """Boîte englobante de l'image après scale + rotation (repère écran)."""
    scaled_image_width = view.display_w * view.scale
    scaled_image_height = view.display_h * view.scale
    rotation_radians = math.radians(view.rotation)
    cos_angle = abs(math.cos(rotation_radians))
    sin_angle = abs(math.sin(rotation_radians))
    bounding_width = (scaled_image_width * cos_angle
                       + scaled_image_height * sin_angle)
    bounding_height = (scaled_image_width * sin_angle
                        + scaled_image_height * cos_angle)
    return bounding_width, bounding_height


def clamp_offsets(view: CropView, is_fit_in: bool = False) -> CropView:
    """Retourne une nouvelle `CropView` avec scale/offsets contraints pour
    qu'aucune bordure de l'image n'apparaisse à l'intérieur du canevas.

    Même algorithme que `PhotoCropper._clamp_offsets` : zoom minimal
    dépendant de la rotation (mode crop uniquement), puis clamp des offsets
    dans le repère local (tourné) de l'image.
    """
    scale = view.scale
    if (not is_fit_in and view.original_width > 4
            and view.original_height > 4):
        border_safety_factor = (
            1.0 + 2.0 / min(view.original_width, view.original_height)
        )
        base_effective_w = (view.base_scale * view.original_width
                             * border_safety_factor)
        base_effective_h = (view.base_scale * view.original_height
                             * border_safety_factor)
        rotation_radians = math.radians(view.rotation)
        cos_angle = abs(math.cos(rotation_radians))
        sin_angle = abs(math.sin(rotation_radians))
        required_width = view.canvas_w * cos_angle + view.canvas_h * sin_angle
        required_height = view.canvas_w * sin_angle + view.canvas_h * cos_angle
        min_scale_for_rotation = max(
            required_width / max(base_effective_w, 1e-6),
            required_height / max(base_effective_h, 1e-6),
            1.0,
        )
        scale = max(scale, min_scale_for_rotation)

    border_safety_factor = (
        1.0 + 2.0 / min(view.original_width, view.original_height)
        if (view.original_width > 4 and view.original_height > 4)
        else 1.0
    )
    effective_width = (view.base_scale * view.original_width * scale
                        * border_safety_factor)
    effective_height = (view.base_scale * view.original_height * scale
                         * border_safety_factor)

    rotation_radians = math.radians(view.rotation)
    cos_rotation = math.cos(rotation_radians)
    sin_rotation = math.sin(rotation_radians)

    half_canvas_width = view.canvas_w / 2.0
    half_canvas_height = view.canvas_h / 2.0
    half_image_width = effective_width / 2.0
    half_image_height = effective_height / 2.0

    projected_half_canvas_x = (abs(cos_rotation) * half_canvas_width
                                + abs(sin_rotation) * half_canvas_height)
    projected_half_canvas_y = (abs(sin_rotation) * half_canvas_width
                                + abs(cos_rotation) * half_canvas_height)

    max_local_offset_x = half_image_width - projected_half_canvas_x
    max_local_offset_y = half_image_height - projected_half_canvas_y

    local_offset_x = (cos_rotation * view.offset_x
                       + sin_rotation * view.offset_y)
    local_offset_y = (-sin_rotation * view.offset_x
                       + cos_rotation * view.offset_y)

    if max_local_offset_x <= 0.0:
        local_offset_x = 0.0
    else:
        local_offset_x = min(max_local_offset_x,
                              max(-max_local_offset_x, local_offset_x))

    if max_local_offset_y <= 0.0:
        local_offset_y = 0.0
    else:
        local_offset_y = min(max_local_offset_y,
                              max(-max_local_offset_y, local_offset_y))

    offset_x = cos_rotation * local_offset_x - sin_rotation * local_offset_y
    offset_y = sin_rotation * local_offset_x + cos_rotation * local_offset_y

    return CropView(
        canvas_w=view.canvas_w, canvas_h=view.canvas_h,
        base_scale=view.base_scale, offset_x=offset_x, offset_y=offset_y,
        scale=scale, rotation=view.rotation,
        original_width=view.original_width,
        original_height=view.original_height,
        display_w=view.display_w, display_h=view.display_h,
    )


def compute_crop_with_canvas(image: Image.Image, target_w_px: int,
                              target_h_px: int, view: CropView, *,
                              is_bw: bool = False,
                              rembg_erosion_pct: float = 0.0,
                              rembg_bg_mode: int = 0,
                              rembg_original: Image.Image | None = None
                              ) -> Image.Image:
    """Noyau du recadrage : matrice affine (rotation+scale+pan) appliquée à
    `image`, puis composition de fond (si RGBA post-rembg) et N&B.

    Reprend `PhotoCropper._compute_crop_with_canvas` : `view.scale`
    remplace `scale_override or self.scale`.
    """
    rotation_radians = math.radians(view.rotation)
    cos_rotation = math.cos(rotation_radians)
    sin_rotation = math.sin(rotation_radians)

    total_scale_factor = view.base_scale * view.scale
    if total_scale_factor <= 0:
        total_scale_factor = 1e-6

    if view.original_width > 4 and view.original_height > 4:
        total_scale_factor *= 1.0 + 2.0 / min(view.original_width,
                                               view.original_height)

    canvas_center_x = view.canvas_w / 2 + view.offset_x
    canvas_center_y = view.canvas_h / 2 + view.offset_y
    image_center_x = view.original_width / 2
    image_center_y = view.original_height / 2

    scaled_rotated_image_center_x = total_scale_factor * (
        cos_rotation * image_center_x - sin_rotation * image_center_y)
    scaled_rotated_image_center_y = total_scale_factor * (
        sin_rotation * image_center_x + cos_rotation * image_center_y)
    canvas_translation_x = canvas_center_x - scaled_rotated_image_center_x
    canvas_translation_y = canvas_center_y - scaled_rotated_image_center_y

    canvas_to_output_scale_x = view.canvas_w / target_w_px
    canvas_to_output_scale_y = view.canvas_h / target_h_px

    inverse_total_scale = 1.0 / total_scale_factor

    affine_m11 = inverse_total_scale * cos_rotation * canvas_to_output_scale_x
    affine_m12 = inverse_total_scale * sin_rotation * canvas_to_output_scale_y
    affine_m21 = inverse_total_scale * -sin_rotation * canvas_to_output_scale_x
    affine_m22 = inverse_total_scale * cos_rotation * canvas_to_output_scale_y

    inverse_translation_x = inverse_total_scale * (
        cos_rotation * canvas_translation_x
        + sin_rotation * canvas_translation_y)
    inverse_translation_y = inverse_total_scale * (
        -sin_rotation * canvas_translation_x
        + cos_rotation * canvas_translation_y)
    affine_offset_x = -inverse_translation_x
    affine_offset_y = -inverse_translation_y

    affine_coeffs = (affine_m11, affine_m12, affine_offset_x,
                      affine_m21, affine_m22, affine_offset_y)

    output_image = image.transform(
        (target_w_px, target_h_px), Image.Transform.AFFINE, affine_coeffs,
        resample=Image.Resampling.BICUBIC, fillcolor=(255, 255, 255, 0),
    )

    if output_image.mode == "RGBA":
        if rembg_erosion_pct > 0:
            erosion_radius = max(
                1, round(min(output_image.size) * rembg_erosion_pct / 100))
            output_image = erode_alpha(output_image, erosion_radius)
        if rembg_bg_mode == 0:
            background_layer = Image.new("RGBA", output_image.size,
                                          (255, 255, 255, 255))
        elif rembg_bg_mode == 1:
            background_layer = Image.new("RGBA", output_image.size,
                                          (230, 230, 230, 255))
        else:
            if rembg_original is not None:
                original_crop = rembg_original.convert("RGB").transform(
                    (target_w_px, target_h_px), Image.Transform.AFFINE,
                    affine_coeffs, resample=Image.Resampling.BICUBIC,
                    fillcolor=(255, 255, 255),
                )
                blurred_background = original_crop.filter(
                    ImageFilter.GaussianBlur(radius=64))
            else:
                white_background = Image.new("RGBA", output_image.size,
                                              (255, 255, 255, 255))
                blurred_background = Image.alpha_composite(
                    white_background, output_image
                ).convert("RGB").filter(ImageFilter.GaussianBlur(radius=64))
            background_layer = blurred_background.convert("RGBA")
        output_image = Image.alpha_composite(
            background_layer, output_image).convert("RGB")
    else:
        output_image = output_image.convert("RGB")

    if is_bw:
        output_image = output_image.convert("L").convert("RGB")

    return output_image


def compute_crop_for_format(image: Image.Image, fmt_w_mm: float,
                             fmt_h_mm: float, is_portrait: bool,
                             view: CropView, *, is_bw: bool = False,
                             rembg_erosion_pct: float = 0.0,
                             rembg_bg_mode: int = 0,
                             rembg_original: Image.Image | None = None,
                             dpi: int = DPI) -> Image.Image:
    """Recadrage pour un format donné, centré sur le même point de vue que
    le canevas principal (canevas virtuel au ratio du format cible).

    `dpi` peut être réduit (ex. aperçu live d'un tiroir) pour accélérer le
    rendu ; l'export final doit utiliser le `DPI` d'impression (300).
    """
    if is_portrait:
        target_w_px = mm_to_pixels(fmt_w_mm, dpi)
        target_h_px = mm_to_pixels(fmt_h_mm, dpi)
    else:
        target_w_px = mm_to_pixels(fmt_h_mm, dpi)
        target_h_px = mm_to_pixels(fmt_w_mm, dpi)

    target_aspect_ratio = target_w_px / target_h_px
    available_width = view.canvas_w
    available_height = view.canvas_h
    if available_width / available_height > target_aspect_ratio:
        virtual_canvas_height = available_height
        virtual_canvas_width = available_height * target_aspect_ratio
    else:
        virtual_canvas_width = available_width
        virtual_canvas_height = available_width / target_aspect_ratio

    virtual_base_scale = max(virtual_canvas_width / view.original_width,
                              virtual_canvas_height / view.original_height)

    if view.base_scale > 0:
        image_space_offset_x = view.offset_x / (view.base_scale * view.scale)
        image_space_offset_y = view.offset_y / (view.base_scale * view.scale)
    else:
        image_space_offset_x = image_space_offset_y = 0.0
    virtual_offset_x = image_space_offset_x * virtual_base_scale * view.scale
    virtual_offset_y = image_space_offset_y * virtual_base_scale * view.scale

    virtual_view = CropView(
        canvas_w=virtual_canvas_width, canvas_h=virtual_canvas_height,
        base_scale=virtual_base_scale, offset_x=virtual_offset_x,
        offset_y=virtual_offset_y, scale=view.scale, rotation=view.rotation,
        original_width=view.original_width,
        original_height=view.original_height,
        display_w=view.display_w, display_h=view.display_h,
    )
    return compute_crop_with_canvas(
        image, target_w_px, target_h_px, virtual_view, is_bw=is_bw,
        rembg_erosion_pct=rembg_erosion_pct, rembg_bg_mode=rembg_bg_mode,
        rembg_original=rembg_original,
    )


def compute_fit_in(image: Image.Image, target_w_px: int, target_h_px: int,
                    original_width: int, original_height: int, *,
                    is_bw: bool = False, rembg_erosion_pct: float = 0.0,
                    rembg_bg_mode: int = 0,
                    rembg_original: Image.Image | None = None
                    ) -> Image.Image:
    """Image entière redimensionnée pour tenir dans le format cible (bords
    blancs), rotation ignorée. Reprend `PhotoCropper._compute_fit_in`."""
    source_image = image
    if source_image.mode == "RGBA":
        if rembg_erosion_pct > 0:
            erosion_radius = max(
                1, round(min(source_image.size) * rembg_erosion_pct / 100))
            source_image = erode_alpha(source_image.copy(), erosion_radius)
        if rembg_bg_mode == 0:
            background_layer = Image.new("RGBA", source_image.size,
                                          (255, 255, 255, 255))
        elif rembg_bg_mode == 1:
            background_layer = Image.new("RGBA", source_image.size,
                                          (230, 230, 230, 255))
        else:
            if rembg_original is not None:
                blurred_background = rembg_original.convert("RGB").filter(
                    ImageFilter.GaussianBlur(radius=64))
            else:
                white_background = Image.new("RGBA", source_image.size,
                                              (255, 255, 255, 255))
                blurred_background = Image.alpha_composite(
                    white_background, source_image
                ).convert("RGB").filter(ImageFilter.GaussianBlur(radius=64))
            background_layer = blurred_background.convert("RGBA")
        source_image = Image.alpha_composite(
            background_layer, source_image).convert("RGB")
    else:
        source_image = source_image.convert("RGB")

    fit_scale_factor = min(target_w_px / original_width,
                            target_h_px / original_height)
    resized_width = max(1, int(round(original_width * fit_scale_factor)))
    resized_height = max(1, int(round(original_height * fit_scale_factor)))
    resized_image = source_image.resize((resized_width, resized_height),
                                         Image.Resampling.BICUBIC)
    output_canvas = Image.new("RGB", (target_w_px, target_h_px), "white")
    paste_offset_x = (target_w_px - resized_width) // 2
    paste_offset_y = (target_h_px - resized_height) // 2
    output_canvas.paste(resized_image, (paste_offset_x, paste_offset_y))
    if is_bw:
        output_canvas = output_canvas.convert("L").convert("RGB")
    return output_canvas


# ================================================================ #
#                    RÉGLAGES COULEUR                               #
# ================================================================ #

def apply_adjustments(input_image: Image.Image, *, exposure: float = 0,
                       contrast: float = 0, saturation: float = 0,
                       hue: float = 0, white_balance: float = 0
                       ) -> Image.Image:
    """Exposition → contraste → saturation → teinte → balance des blancs.
    Reprend `PhotoCropper._apply_adjustments`."""
    working_image = input_image.convert("RGB")
    if exposure != 0:
        offset = int(exposure * 0.5)
        lab = working_image.convert("LAB")
        l_ch, a_ch, b_ch = lab.split()
        lut = np.clip(np.arange(256) + offset, 0, 255).astype(np.uint8).tolist()
        working_image = Image.merge("LAB", (l_ch.point(lut), a_ch, b_ch)
                                     ).convert("RGB")
    if contrast != 0:
        working_image = ImageEnhance.Contrast(working_image).enhance(
            1.0 + contrast / 100.0)
    if saturation != 0:
        working_image = ImageEnhance.Color(working_image).enhance(
            max(0.0, 1.0 + saturation / 100.0))
    if hue != 0:
        working_image = apply_hue(working_image, hue)
    if white_balance != 0:
        working_image = apply_white_balance(working_image, white_balance)
    return working_image


def apply_shadows(input_image: Image.Image, value: float) -> Image.Image:
    """value : -100…+100. Positif = éclaircit les ombres."""
    if value == 0:
        return input_image
    strength_factor = value / 100.0
    value_range = np.arange(256, dtype=np.float32)
    normalized_value = value_range / 192.0
    shadow_weight = np.where(normalized_value <= 1.0,
                              np.sin(np.pi * normalized_value), 0.0)
    shadow_amplitude = 60
    lookup_table = np.clip(
        value_range + strength_factor * shadow_amplitude * shadow_weight,
        0, 255).astype(np.uint8)
    image_array = np.array(input_image.convert("RGB"), dtype=np.uint8)
    return Image.fromarray(lookup_table[image_array], "RGB")


def apply_highlights(input_image: Image.Image, value: float) -> Image.Image:
    """value : -100…+100. Positif = éclaircit les hautes lumières."""
    if value == 0:
        return input_image
    strength_factor = value / 100.0
    value_range = np.arange(256, dtype=np.float32)
    normalized_value = (value_range - 64.0) / 192.0
    highlight_weight = np.where(
        (normalized_value >= 0.0) & (normalized_value <= 1.0),
        np.sin(np.pi * normalized_value), 0.0)
    highlight_amplitude = 60
    lookup_table = np.clip(
        value_range + strength_factor * highlight_amplitude * highlight_weight,
        0, 255).astype(np.uint8)
    image_array = np.array(input_image.convert("RGB"), dtype=np.uint8)
    return Image.fromarray(lookup_table[image_array], "RGB")


def apply_hue(input_image: Image.Image, value: float) -> Image.Image:
    """value dans [-180, +180] : vert (négatif) ↔ magenta (positif)."""
    if value == 0:
        return input_image
    normalized_value = value / 180.0
    hue_strength = abs(normalized_value) * 0.30
    base_lookup = np.arange(256, dtype=np.float32)
    if normalized_value > 0:
        red_lookup = np.clip(base_lookup * (1.0 + hue_strength),
                              0, 255).astype(np.uint8)
        green_lookup = np.clip(base_lookup * (1.0 - hue_strength),
                                0, 255).astype(np.uint8)
        blue_lookup = np.clip(base_lookup * (1.0 + hue_strength * 0.7),
                               0, 255).astype(np.uint8)
    else:
        red_lookup = np.clip(base_lookup * (1.0 - hue_strength),
                              0, 255).astype(np.uint8)
        green_lookup = np.clip(base_lookup * (1.0 + hue_strength),
                                0, 255).astype(np.uint8)
        blue_lookup = np.clip(base_lookup * (1.0 - hue_strength * 0.7),
                               0, 255).astype(np.uint8)
    pixel_array = np.array(input_image.convert("RGB"), dtype=np.uint8)
    result_array = np.stack([
        red_lookup[pixel_array[:, :, 0]],
        green_lookup[pixel_array[:, :, 1]],
        blue_lookup[pixel_array[:, :, 2]],
    ], axis=2)
    return Image.fromarray(result_array, "RGB")


def apply_white_balance(input_image: Image.Image, value: float) -> Image.Image:
    """value : -100 = froid (bleu), +100 = chaud (jaune/orange)."""
    if value == 0:
        return input_image
    balance_strength = abs(value) / 100.0 * 0.20
    pixel_array = np.array(input_image.convert("RGB"), dtype=np.float32)
    if value > 0:
        pixel_array[..., 0] = np.clip(
            pixel_array[..., 0] * (1.0 + balance_strength), 0, 255)
        pixel_array[..., 1] = np.clip(
            pixel_array[..., 1] * (1.0 + balance_strength * 0.2), 0, 255)
        pixel_array[..., 2] = np.clip(
            pixel_array[..., 2] * (1.0 - balance_strength), 0, 255)
    else:
        pixel_array[..., 0] = np.clip(
            pixel_array[..., 0] * (1.0 - balance_strength), 0, 255)
        pixel_array[..., 2] = np.clip(
            pixel_array[..., 2] * (1.0 + balance_strength), 0, 255)
    return Image.fromarray(pixel_array.astype(np.uint8), "RGB")


# ================================================================ #
#                    SUPPRESSION DE FOND (rembg)                   #
# ================================================================ #

_REMBG_MODEL_ALIASES = {
    ("precise", "human"): "birefnet-portrait",
    ("precise", "general"): "birefnet-general",
    ("fast", "human"): "u2net_human_seg",
    ("fast", "general"): "u2net",
}


def run_rembg(image: Image.Image, *, precise: bool = False,
              human: bool = True, session_cache: dict | None = None
              ) -> Image.Image:
    """Supprime le fond via rembg (import paresseux — dépendance lourde,
    ~450 Mo au premier usage en mode précis). Factorise la logique
    dupliquée entre `Recadrage manuel.pyw` et `Augmentation IA.py`.

    `session_cache` : dict mutable fourni par l'appelant pour mettre en
    cache la session onnx par mode et éviter de recharger le modèle à
    chaque appel (ex. `{}` conservé entre deux retouches successives).
    """
    from rembg import remove as _rembg_remove, new_session as _rembg_new_session

    mode_key = ("precise" if precise else "fast", "human" if human else "general")
    model_name = _REMBG_MODEL_ALIASES[mode_key]
    cache = session_cache if session_cache is not None else {}
    session = cache.get(model_name)
    if session is None:
        session = _rembg_new_session(model_name)
        cache[model_name] = session
    return _rembg_remove(image, session=session)


# ================================================================ #
#                    PLANCHES D'IMPRESSION (imposition)             #
# ================================================================ #

def build_print_sheet(cropped_image: Image.Image, layout: str, dpi: int = DPI,
                       *, previous_image: Image.Image | None = None,
                       bottom_half: bool = True
                       ) -> Image.Image | None:
    """Assemble une ou plusieurs copies d'une photo déjà recadrée sur une
    planche d'impression.

    Paramètres
    ----------
    cropped_image : image déjà recadrée au format identité (10x15 portrait
        pour `id2`/`id4`, ou format libre pour `bordure`).
    layout : ``"bordure"`` (bord blanc 5mm), ``"polaroid"`` (127x152mm,
        photo 10x10 centrée), ``"id2"`` (102x102mm, 2 copies empilées),
        ``"id4"`` (127x102mm, grille 2x2), ``"id4_10x20"`` (102x203mm,
        4 copies par moitié — nécessite un appairage de 2 photos).
    previous_image : pour ``id4_10x20`` uniquement — la photo précédente en
        attente d'appairage. Si fourni, la planche complète (les deux
        moitiés) est retournée ; sinon `None` est retourné (mise en attente,
        à charge de l'appelant de garder `cropped_image` pour le prochain
        appel).
    bottom_half : pour ``id4_10x20`` isolé (fin de batch) — moitié de la
        feuille à remplir (`CONSTANTS.ID_X4_10x20_PHOTOS_BOTTOM`).

    Reprend la géométrie de `PhotoCropper.validate_and_next` (bordures et
    planches), reformulée sans état de batch caché.
    """
    if layout == "bordure":
        margin = mm_to_pixels(5, dpi)
        w, h = cropped_image.size
        canvas = Image.new("RGB", (w, h), "white")
        inner = cropped_image.resize((w - 2 * margin, h - 2 * margin),
                                      Image.Resampling.BICUBIC)
        canvas.paste(inner, (margin, margin))
        return canvas

    if layout == "polaroid":
        sheet_w, sheet_h = mm_to_pixels(127, dpi), mm_to_pixels(152, dpi)
        photo_size = mm_to_pixels(100, dpi)
        canvas = Image.new("RGB", (sheet_w, sheet_h), "white")
        photo = cropped_image.resize((photo_size, photo_size),
                                      Image.Resampling.BICUBIC)
        canvas.paste(photo, ((sheet_w - photo_size) // 2,
                              (sheet_h - photo_size) // 3))
        return canvas

    if layout == "id2":
        sheet_w, sheet_h = mm_to_pixels(102, dpi), mm_to_pixels(102, dpi)
        gap = mm_to_pixels(5, dpi)
        photo_h = (sheet_h - gap) // 2
        canvas = Image.new("RGB", (sheet_w, sheet_h), "white")
        photo = cropped_image.resize((sheet_w, photo_h),
                                      Image.Resampling.BICUBIC)
        canvas.paste(photo, (0, 0))
        canvas.paste(photo, (0, photo_h + gap))
        return canvas

    if layout == "id4":
        sheet_w, sheet_h = mm_to_pixels(127, dpi), mm_to_pixels(102, dpi)
        gap = mm_to_pixels(5, dpi)
        cell_w = (sheet_w - gap) // 2
        cell_h = (sheet_h - gap) // 2
        canvas = Image.new("RGB", (sheet_w, sheet_h), "white")
        photo = cropped_image.resize((cell_w, cell_h),
                                      Image.Resampling.BICUBIC)
        for row in range(2):
            for col in range(2):
                x = col * (cell_w + gap)
                y = row * (cell_h + gap)
                canvas.paste(photo, (x, y))
        return canvas

    if layout == "id4_10x20":
        sheet_w, sheet_h = mm_to_pixels(102, dpi), mm_to_pixels(203, dpi)
        gap = mm_to_pixels(5, dpi)
        half_h = sheet_h // 2
        cell_w = (sheet_w - gap) // 2
        cell_h = (half_h - gap) // 2

        def _paste_id4_block(canvas, image, top_y):
            photo = image.resize((cell_w, cell_h), Image.Resampling.BICUBIC)
            for row in range(2):
                for col in range(2):
                    x = col * (cell_w + gap)
                    y = top_y + row * (cell_h + gap)
                    canvas.paste(photo, (x, y))

        if previous_image is None:
            return None  # mis en attente d'appairage par l'appelant

        canvas = Image.new("RGB", (sheet_w, sheet_h), "white")
        top_image, bottom_image = (
            (previous_image, cropped_image) if bottom_half
            else (cropped_image, previous_image)
        )
        _paste_id4_block(canvas, top_image, 0)
        _paste_id4_block(canvas, bottom_image, half_h)
        return canvas

    raise ValueError(f"layout inconnu : {layout!r}")
