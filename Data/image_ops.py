# -*- coding: utf-8 -*-
"""
image_ops.py — Traitement d'image pur (recadrage, couleur, planches).

Aucune dépendance à Flet ni à un état de session : chaque fonction reçoit
ses paramètres explicitement et retourne une nouvelle `PIL.Image.Image`.
Module partagé par `Hub.pyw` (tiroirs de la visionneuse), par
`Data/Recadrage manuel.pyw`, et par `Data/Retouche par lot.pyw` (débruitage,
virage, copyright, netteté, grain pellicule — les anciens scripts autonomes
correspondants ont été retirés, remplacés par cet outil unique) — qui
l'importent au lieu de dupliquer leur propre logique de traitement.

Toutes les fonctions ci-dessous sont des extractions fidèles de
`Data/Recadrage manuel.pyw` (classe `PhotoCropper`) : mêmes formules, mêmes
noms, `self.xxx` remplacés par des paramètres explicites.
"""
import colorsys
import functools
import io
import math
import os
import sys
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

import cv2
import numpy as np
from PIL import (Image, ImageCms, ImageDraw, ImageEnhance, ImageFilter,
                  ImageFont, ImageOps)
from PIL.ExifTags import TAGS

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import CONSTANTS

DPI = CONSTANTS.DPI

# Profil sRGB pré-construit (réutilisé pour chaque export).
_SRGB_PROFILE = ImageCms.createProfile("sRGB")
_SRGB_ICC = ImageCms.ImageCmsProfile(_SRGB_PROFILE).tobytes()


def mm_to_pixels(mm, dpi=DPI):
    """Convertit une dimension en millimètres en nombre de pixels entiers."""
    return int(mm / 25.4 * dpi)


# Transformations ICC -> sRGB mises en cache : buildTransform est coûteux
# (parsing du profil + LUT LittleCMS) et le même profil source revient pour
# toutes les photos d'une même série (ex. Display P3 sur tout un reportage
# iPhone). Clé = (hash du profil, mode de l'image source).
_srgb_transform_cache: dict = {}


def convert_to_srgb(source_image: Image.Image,
                     icc_profile: bytes | None) -> Image.Image:
    """Convertit une image PIL vers l'espace colorimétrique sRGB.

    Intent RELATIVE_COLORIMETRIC + compensation du point noir : c'est ce
    qu'appliquent Aperçu (macOS) et Photos (Windows) — l'aperçu doit
    coïncider avec eux, PERCEPTUAL donnait un rendu légèrement différent
    sur les profils à LUT (ex. FOGRA39). Les JPEG CMJN (profil imprimerie
    embarqué) sont convertis via leur profil AVANT tout convert("RGB") :
    la conversion naïve de PIL sursaturait fortement ces fichiers.
    """
    if not icc_profile:
        # Sans profil embarqué : sRGB par convention, sauf CMJN où PIL
        # fait une conversion naïve (mieux que rien, aucun profil dispo).
        if source_image.mode == "CMYK":
            return source_image.convert("RGB")
        return source_image
    try:
        cache_key = (hash(icc_profile), source_image.mode)
        transform = _srgb_transform_cache.get(cache_key)
        if transform is None:
            src_profile = ImageCms.ImageCmsProfile(io.BytesIO(icc_profile))
            description = ""
            try:
                description = ImageCms.getProfileDescription(src_profile)
            except Exception:
                pass
            if ("srgb" in description.lower()
                    and source_image.mode in ("RGB", "RGBA")):
                # Déjà en sRGB : aucune conversion nécessaire. False (et pas
                # None) en cache : mémorise le « rien à faire ».
                _srgb_transform_cache[cache_key] = False
                return source_image
            src_mode = ("CMYK" if source_image.mode == "CMYK"
                        else "RGB")
            transform = ImageCms.buildTransform(
                src_profile, _SRGB_PROFILE, src_mode, "RGB",
                renderingIntent=ImageCms.Intent.RELATIVE_COLORIMETRIC,
                flags=ImageCms.Flags.BLACKPOINTCOMPENSATION,
            )
            _srgb_transform_cache[cache_key] = transform
        if transform is False:
            return source_image
        if source_image.mode == "CMYK":
            return ImageCms.applyTransform(source_image, transform)
        return ImageCms.applyTransform(
            source_image.convert("RGB"), transform)
    except Exception:
        if source_image.mode == "CMYK":
            return source_image.convert("RGB")
        return source_image


def open_srgb(path) -> Image.Image:
    """Ouvre une image, corrige l'orientation EXIF puis convertit en RGB
    sRGB managé via son profil ICC embarqué (ex. profil scanner non-sRGB) —
    sinon un ``.convert("RGB")`` nu réinterprète les valeurs brutes comme si
    elles étaient déjà sRGB, ce qui assombrit/dénature le rendu à
    l'impression (retour user sur Virage.py).

    La rotation EXIF est appliquée AVANT la conversion ICC : cette dernière
    (ImageCms.applyTransform) reconstruit une nouvelle image sans le dict
    ``.info``/exif d'origine, donc un ``exif_transpose`` fait après coup ne
    verrait plus l'orientation. Un ``exif_transpose`` redondant en aval
    (scripts qui l'appelaient déjà) reste sans danger : plus de tag = no-op.

    À utiliser en entrée de tout script qui peut tourner sur un scan/photo
    brut ; combiner avec ``_SRGB_ICC`` en ``icc_profile=`` à l'enregistrement
    pour que le fichier de sortie reste correctement tagué."""
    source_image = ImageOps.exif_transpose(Image.open(path))
    return convert_to_srgb(
        source_image, source_image.info.get("icc_profile")).convert("RGB")


# ================================================================ #
#          COMPENSATION D'AFFICHAGE (écran large gamut)            #
# ================================================================ #
# Flutter (donc Flet) n'applique AUCUNE gestion des couleurs : les pixels
# sRGB de nos aperçus partent bruts vers l'écran. Sur un moniteur large
# gamut (ex. EIZO ColorEdge ~Adobe RGB, dalles P3 des MacBook), ils sont
# étirés sur tout le gamut du panneau -> aperçus nettement plus saturés
# que dans Aperçu/Photos, qui convertissent eux-mêmes vers le profil de
# l'écran (retour user). On compense donc côté Python : les pixels des
# APERÇUS (jamais des fichiers exportés) sont réencodés de sRGB vers le
# profil de l'écran juste avant l'affichage — affichés bruts par Flutter,
# ils redonnent la couleur voulue. Sur un écran sRGB, la transformation
# est une quasi-identité et est simplement désactivée.
#
# Désactivable via la variable d'environnement DISPLAY_COLOR_COMPENSATION=0
# (ou un chemin de profil imposé via DISPLAY_ICC_PROFILE).

_display_transform_cache: dict = {"built": False, "transform": None}


def _windows_display_profile_path():
    """Profil ICC associé à l'écran sous Windows, associations par
    utilisateur comprises — GetICMProfileW (et donc
    ImageCms.get_display_profile) les ignore et retombe sur sRGB."""
    import winreg

    color_dir = os.path.join(
        os.environ.get("SystemRoot", r"C:\Windows"),
        "System32", "spool", "drivers", "color")

    def _profiles_from(root):
        found = []
        base = (r"SOFTWARE\Microsoft\Windows NT\CurrentVersion"
                r"\ICM\ProfileAssociations\Display")
        try:
            with winreg.OpenKey(root, base) as display_key:
                for i in range(winreg.QueryInfoKey(display_key)[0]):
                    device_class = winreg.EnumKey(display_key, i)
                    with winreg.OpenKey(display_key, device_class) as cls_key:
                        for j in range(winreg.QueryInfoKey(cls_key)[0]):
                            monitor = winreg.EnumKey(cls_key, j)
                            with winreg.OpenKey(cls_key, monitor) as mon_key:
                                try:
                                    value, _t = winreg.QueryValueEx(
                                        mon_key, "ICMProfile")
                                except OSError:
                                    continue
                                names = (value if isinstance(value, list)
                                         else [value])
                                # REG_MULTI_SZ : le profil par défaut est
                                # le DERNIER de la liste.
                                for name in reversed(names):
                                    if name:
                                        found.append(name)
                                        break
        except OSError:
            pass
        return found

    candidates = (_profiles_from(winreg.HKEY_CURRENT_USER)
                  or _profiles_from(winreg.HKEY_LOCAL_MACHINE))
    for name in candidates:
        path = name if os.path.isabs(name) else os.path.join(color_dir, name)
        if os.path.isfile(path):
            return path
    return None


def _macos_display_profile_path():
    """Profil de l'écran généré par ColorSync (un .icc par écran connecté,
    régénéré par macOS) — le plus récemment modifié correspond à l'écran
    branché en dernier."""
    displays_dir = os.path.expanduser("~/Library/ColorSync/Profiles/Displays")
    try:
        profiles = [os.path.join(displays_dir, f)
                    for f in os.listdir(displays_dir)
                    if f.lower().endswith((".icc", ".icm"))]
        if profiles:
            return max(profiles, key=os.path.getmtime)
    except OSError:
        pass
    return None


def get_display_transform():
    """Transformation ImageCms sRGB -> profil de l'écran, ou None si
    inutile (écran sRGB, profil introuvable, compensation désactivée).
    Construite une seule fois par session."""
    if _display_transform_cache["built"]:
        return _display_transform_cache["transform"]
    _display_transform_cache["built"] = True
    _display_transform_cache["transform"] = None
    if os.environ.get("DISPLAY_COLOR_COMPENSATION", "1") == "0":
        return None
    try:
        profile_path = os.environ.get("DISPLAY_ICC_PROFILE") or None
        if profile_path is None:
            import platform as _platform
            system = _platform.system()
            if system == "Windows":
                profile_path = _windows_display_profile_path()
            elif system == "Darwin":
                profile_path = _macos_display_profile_path()
        if not profile_path or not os.path.isfile(profile_path):
            return None
        display_profile = ImageCms.ImageCmsProfile(profile_path)
        try:
            description = ImageCms.getProfileDescription(display_profile)
        except Exception:
            description = ""
        if "srgb" in description.lower():
            return None   # écran sRGB : rien à compenser
        _display_transform_cache["transform"] = ImageCms.buildTransform(
            _SRGB_PROFILE, display_profile, "RGB", "RGB",
            renderingIntent=ImageCms.Intent.RELATIVE_COLORIMETRIC,
            flags=ImageCms.Flags.BLACKPOINTCOMPENSATION,
        )
    except Exception:
        _display_transform_cache["transform"] = None
    return _display_transform_cache["transform"]


def compensate_for_display(image: Image.Image) -> Image.Image:
    """Réencode une image sRGB dans l'espace du moniteur pour l'AFFICHAGE
    (aperçus Flet uniquement — ne jamais appliquer à un fichier exporté)."""
    transform = get_display_transform()
    if transform is None:
        return image
    try:
        return ImageCms.applyTransform(image.convert("RGB"), transform)
    except Exception:
        return image


def compensate_jpeg_bytes(jpeg_bytes: bytes, quality: int = 90) -> bytes:
    """Applique `compensate_for_display` à des bytes JPEG déjà encodés
    (miniatures en cache, visionneuse). Retourne les bytes d'origine si
    aucune compensation n'est nécessaire."""
    if get_display_transform() is None:
        return jpeg_bytes
    try:
        with Image.open(io.BytesIO(jpeg_bytes)) as img:
            corrected = compensate_for_display(img)
            buffer = io.BytesIO()
            corrected.save(buffer, format="JPEG", quality=quality)
            return buffer.getvalue()
    except Exception:
        return jpeg_bytes


def erode_alpha(source_image: Image.Image, radius: int) -> Image.Image:
    """Érode le canal alpha d'une image RGBA d'environ ``radius`` pixels."""
    if source_image.mode != "RGBA" or radius <= 0:
        return source_image
    r, g, b, alpha_channel = source_image.split()
    for _ in range(radius):
        alpha_channel = alpha_channel.filter(ImageFilter.MinFilter(3))
    return Image.merge("RGBA", (r, g, b, alpha_channel))


def feather_alpha(source_image: Image.Image, radius: int) -> Image.Image:
    """Adoucit (flou gaussien) le canal alpha d'une image RGBA d'environ
    ``radius`` pixels — lisse un contour en escalier (ex. flood fill à
    résolution réduite) sans changer la taille de la zone détourée,
    contrairement à `erode_alpha` qui la rétrécit."""
    if source_image.mode != "RGBA" or radius <= 0:
        return source_image
    r, g, b, alpha_channel = source_image.split()
    alpha_channel = alpha_channel.filter(ImageFilter.GaussianBlur(radius))
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
                              rembg_feather_pct: float = 0.0,
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

    # Image.transform(AFFINE) ne supporte que NEAREST/BILINEAR/BICUBIC
    # (LANCZOS lève ValueError) — contrairement à .resize().
    output_image = image.transform(
        (target_w_px, target_h_px), Image.Transform.AFFINE, affine_coeffs,
        resample=Image.Resampling.BICUBIC, fillcolor=(255, 255, 255, 0),
    )

    if output_image.mode == "RGBA":
        if rembg_erosion_pct > 0:
            erosion_radius = max(
                1, round(min(output_image.size) * rembg_erosion_pct / 100))
            output_image = erode_alpha(output_image, erosion_radius)
        if rembg_feather_pct > 0:
            feather_radius = max(
                1, round(min(output_image.size) * rembg_feather_pct / 100))
            output_image = feather_alpha(output_image, feather_radius)
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
                             rembg_feather_pct: float = 0.0,
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
        rembg_erosion_pct=rembg_erosion_pct, rembg_feather_pct=rembg_feather_pct,
        rembg_bg_mode=rembg_bg_mode, rembg_original=rembg_original,
    )


def compute_fit_in(image: Image.Image, target_w_px: int, target_h_px: int,
                    original_width: int, original_height: int, *,
                    is_bw: bool = False, rembg_erosion_pct: float = 0.0,
                    rembg_feather_pct: float = 0.0,
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
        if rembg_feather_pct > 0:
            feather_radius = max(
                1, round(min(source_image.size) * rembg_feather_pct / 100))
            source_image = feather_alpha(source_image.copy(), feather_radius)
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


def apply_whites(input_image: Image.Image, value: float) -> Image.Image:
    """value : -100…+100. Négatif = abaisse le point blanc (le pixel le
    plus clair descend réellement), positif = pousse vers l'écrêtage.

    Complément de `apply_highlights`, dont la courbe s'annule
    volontairement à 255 (préserve le blanc pur) : ici le poids est
    quadratique et MAXIMAL à 255 — pensé pour recaler un scan surexposé
    dont le blanc doit redescendre (retour user)."""
    if value == 0:
        return input_image
    strength_factor = value / 100.0
    value_range = np.arange(256, dtype=np.float32)
    white_weight = (value_range / 255.0) ** 2
    white_amplitude = 80
    lookup_table = np.clip(
        value_range + strength_factor * white_amplitude * white_weight,
        0, 255).astype(np.uint8)
    image_array = np.array(input_image.convert("RGB"), dtype=np.uint8)
    return Image.fromarray(lookup_table[image_array], "RGB")


def apply_blacks(input_image: Image.Image, value: float) -> Image.Image:
    """value : -100…+100. Positif = relève le point noir (débouche le
    noir pur), négatif = l'enfonce.

    Complément de `apply_shadows`, dont la courbe s'annule à 0 (préserve
    le noir pur) : ici le poids est quadratique et maximal à 0."""
    if value == 0:
        return input_image
    strength_factor = value / 100.0
    value_range = np.arange(256, dtype=np.float32)
    black_weight = ((255.0 - value_range) / 255.0) ** 2
    black_amplitude = 80
    lookup_table = np.clip(
        value_range + strength_factor * black_amplitude * black_weight,
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


def apply_auto_color_cast(input_image: Image.Image,
                          strength: float = 100) -> Image.Image:
    """Neutralise une dominante (scans anciens virés rouge/jaune) et
    redonne du contraste perdu au délavage : étire chaque canal RVB
    indépendamment entre ses 0,5e/99,5e percentiles (« niveaux auto » par
    canal, les percentiles ignorent les quelques pixels extrêmes plutôt
    que le min/max bruts). `strength` : 0 = inchangé, 100 = correction
    pleine (chaque canal occupe tout 0-255) — chaque scan est délavé
    différemment, ce curseur permet de doser sans repartir sur des
    réglages manuels par photo. Au-delà de 100, extrapole dans le même
    sens (surcorrection) pour les photos les plus tenaces, avec un
    écrêtage plus marqué en contrepartie (retour user : certaines photos
    ont besoin de plus que la correction pleine)."""
    if strength <= 0:
        return input_image
    working_image = input_image.convert("RGB")
    original = np.asarray(working_image, dtype=np.float32)
    stretched = original.copy()
    for channel in range(3):
        band = original[:, :, channel]
        low, high = np.percentile(band, (0.5, 99.5))
        if high - low < 1.0:
            continue  # canal quasi uniforme : l'étirer amplifierait du bruit
        stretched[:, :, channel] = (band - low) * (255.0 / (high - low))
    if strength == 100:
        result = stretched
    else:
        blend = strength / 100.0
        result = original + (stretched - original) * blend
    return Image.fromarray(np.clip(result, 0, 255).astype(np.uint8), "RGB")


# ================================================================ #
#                    SUPPRESSION DE FOND (rembg)                   #
# ================================================================ #

_REMBG_MODEL_ALIASES = {
    ("precise", "human"): "birefnet-portrait",
    ("precise", "general"): "birefnet-general",
    ("fast", "human"): "u2net_human_seg",
    ("fast", "general"): "u2net",
}


def flood_background_mask(image: Image.Image, seed_xy: tuple[int, int] | None,
                           *, tolerance: int = 40, max_px: int = 1500
                           ) -> np.ndarray:
    """Masque booléen (True = fond) à la résolution ORIGINALE de `image`,
    par extension de zone (flood fill), sans modèle IA — voir
    `remove_background_flood`. Renvoyé brut (sans alpha/adoucissement)
    pour permettre de cumuler (union) plusieurs graines successives
    avant de composer l'alpha final via `compose_bg_alpha`.

    `seed_xy` (coordonnées pixel de `image`, ex. clic pipette) : flood
    depuis ce seul point. `None` : passe automatique depuis le haut et les
    côtés, sans clic — taillée pour le portrait sur fond clair (cf. le
    choix des graines plus bas).

    `tolerance` est une distance COULEUR euclidienne (RGB, 0-441) à la
    couleur du point cliqué : on retient les pixels dans cette bande, puis
    la seule composante CONNEXE qui contient la graine.

    Distance couleur et non luminosité seule : sous un éclairage uniforme,
    peau et cheveux tombent souvent à une luminosité proche d'un fond clair
    et se faisaient absorber par erreur, alors que leur teinte chaude reste
    nettement distincte d'un fond neutre (retour user).

    Pourquoi PAS un flood fill en plage flottante (cv2.floodFill sans
    FLOODFILL_FIXED_RANGE), qui compare chaque pixel à son VOISIN et sait
    donc suivre un fond en dégradé — ce dont la bande ci-dessus est
    incapable : mesuré sur les images réelles de l'atelier (tirages
    argentiques scannés), la plage flottante est inutilisable. Un tirage
    scanné n'a aucune arête franche à l'échelle du pixel (optique douce,
    grain, flou de numérisation), donc les écarts entre voisins sont
    partout minuscules et l'image entière forme une seule zone lisse :
    0 % de l'image à la tolérance 2, 80 % à 4, 98 % à 6. Le réglage passe
    de « rien » à « tout » en une dizaine de pixels de glissé, et déborde
    largement au-delà de la zone visée. La bande de couleur, elle, progresse
    régulièrement sur la même image (2 % à 20, 10 % à 40, 18 % à 60, 31 % à
    100) : c'est ce qui la rend dosable à la main.

    Le compromis est donc assumé dans ce sens précis : on renonce à
    traverser un dégradé de fond — pour lequel il faut monter la tolérance,
    voire préférer les modes rembg/BiRefNet — pour garder un réglage
    progressif sur des images texturées et bruitées, qui sont le cas réel.

    cv2 plutôt que scikit-image (`skimage.segmentation.flood`, utilisé
    auparavant) : OpenCV est déjà une dépendance de ce module, ce qui
    supprime une dépendance lourde à installer sur chaque poste, pour un
    résultat identique — la bande + composante connexe ci-dessous est
    exactement la définition de `flood(..., tolerance=...)`.
    """
    rgb = image.convert("RGB")
    w, h = rgb.size
    scale = min(1.0, max_px / max(w, h))
    sw, sh = max(1, round(w * scale)), max(1, round(h * scale))
    small = rgb.resize((sw, sh), Image.Resampling.BILINEAR) if scale < 1.0 else rgb
    arr = np.asarray(small, dtype=np.float64)

    if seed_xy is not None:
        sx, sy = seed_xy
        seeds = [(min(sh - 1, max(0, round(sy * scale))),
                  min(sw - 1, max(0, round(sx * scale))))]
    else:
        # Bord INFÉRIEUR volontairement exclu. Sur un portrait — le cas
        # visé par la passe automatique, photo d'identité sur fond clair —
        # le buste est coupé par le bas du cadre : ce bord est du sujet,
        # pas du fond. Mesuré sur un portrait de synthèse, la seule graine
        # bas-centre suffisait à emporter 70,8 % du sujet (le vêtement
        # entier) ; sans elle, 99,8 % du fond et 0 % du sujet.
        # Restent le haut, les coins hauts et les côtés jusqu'à mi-hauteur,
        # où le fond d'un portrait est toujours visible.
        seeds = [(0, 0), (0, sw - 1), (0, sw // 2),
                 (sh // 4, 0), (sh // 4, sw - 1),
                 (sh // 2, 0), (sh // 2, sw - 1)]

    bg_small = np.zeros((sh, sw), dtype=bool)
    for seed in seeds:
        dist = np.sqrt(((arr - arr[seed]) ** 2).sum(axis=2))
        # La composante connexe évite de retenir, ailleurs dans l'image,
        # des pixels de couleur voisine mais sans lien avec la zone visée.
        _, labels = cv2.connectedComponents(
            (dist <= tolerance).astype(np.uint8), connectivity=8)
        if labels[seed]:
            bg_small |= (labels == labels[seed])

    if scale >= 1.0:
        return bg_small
    bg_full = np.asarray(
        Image.fromarray((bg_small * 255).astype(np.uint8), mode="L")
        .resize((w, h), Image.Resampling.BILINEAR))
    return bg_full > 127


def compose_bg_alpha(image: Image.Image, bg_mask: np.ndarray,
                      feather_px: int = 2) -> Image.Image:
    """Applique `bg_mask` (True = fond, résolution originale de `image`)
    comme canal alpha, adouci de `feather_px` (contour en escalier sinon,
    le flood fill tourne à résolution réduite)."""

    alpha = np.where(bg_mask, 0, 255).astype(np.uint8)
    alpha_img = Image.fromarray(alpha, mode="L").filter(
        ImageFilter.GaussianBlur(feather_px))
    result = image.convert("RGBA")
    result.putalpha(alpha_img)
    return result


def remove_background_flood(image: Image.Image, *, tolerance: int = 40,
                             seed_xy: tuple[int, int] | None = None,
                             max_px: int = 1500) -> Image.Image:
    """Détourage instantané par extension de zone (flood fill) en un seul
    appel — voir `flood_background_mask` + `compose_bg_alpha` pour cumuler
    plusieurs graines (pipette additive)."""

    bg_mask = flood_background_mask(image, seed_xy, tolerance=tolerance,
                                     max_px=max_px)
    return compose_bg_alpha(image, bg_mask)


class FloodPipette:
    """État interactif de la pipette de détourage instantané (flood
    fill) : un clic-glissé fixe la graine, la distance du glissé ajuste
    la tolérance en direct, et plusieurs picks successifs s'accumulent
    (ajout) ou se retranchent (retrait, `sign = -1`) du masque de fond.

    Ne gère ni les événements souris/gestes ni le rendu — seulement
    l'état et la logique de combinaison des masques, pour rester
    utilisable aussi bien depuis un widget basé sur une classe
    (`Recadrage manuel.pyw`) que depuis des closures (`Augmentation
    IA.py`). L'appelant reste responsable de :
      - convertir les coordonnées écran → image (transform propre à
        chaque app) ;
      - appeler `flood_background_mask`/`compose_bg_alpha` avec la
        tolérance et le masque combiné renvoyés ici ;
      - rafraîchir l'affichage.
    """

    # Échelle : distance couleur euclidienne à la graine (0-441), cf.
    # `flood_background_mask`. Sur les tirages scannés de l'atelier, la
    # zone retenue croît régulièrement dans cette plage (2 % de l'image à
    # 20, 10 % à 40, 18 % à 60, 31 % à 100) — d'où un plafond à 150, au
    #-delà duquel on ratisse trop large pour rester utile.
    # `sensitivity` : 0.5 par pixel glissé, soit ~220 px pour aller du
    # défaut au plafond.
    def __init__(self, tolerance: int = 40, *, min_tolerance: int = 5,
                 max_tolerance: int = 150, sensitivity: float = 0.5):
        self.tolerance = tolerance
        self.min_tolerance = min_tolerance
        self.max_tolerance = max_tolerance
        self.sensitivity = sensitivity
        self.sign: int = 1              # 1 = ajoute, -1 = retire
        self.drag_px: float = 0.0
        self.bg_mask: np.ndarray | None = None
        self.armed: bool = False
        self.live_busy: bool = False    # throttle aperçu en direct : 1 seul recalcul en vol
        self.live_gen: int = 0          # jette les résultats devenus obsolètes

    def arm(self) -> None:
        """Arme la pipette pour une nouvelle session (attend un clic) —
        repart d'un masque vide."""
        self.armed = True
        self.bg_mask = None

    def try_start_live(self) -> bool:
        """Pose le verrou `live_busy` et renvoie True si aucun calcul
        n'est déjà en vol — à appeler de façon SYNCHRONE, dans le
        callback de glissement, AVANT de programmer la tâche async
        (`page.run_task`).

        `page.run_task` ne démarre pas la coroutine immédiatement : elle
        n'est exécutée qu'à la prochaine itération de la boucle asyncio.
        Si le verrou n'est posé qu'AU DÉBUT de la coroutine elle-même
        (comme on pourrait le croire), plusieurs callbacks de glissement
        consécutifs peuvent tous voir `live_busy` encore à False et
        programmer chacun leur propre calcul — plusieurs flood fill se
        chevauchent alors, et celui qui termine en dernier n'est pas
        forcément celui parti du point le plus récent : l'aperçu peut se
        figer sur un résultat périmé (retour user : la zone grandissait
        puis ne rétrécissait plus en rejouant le glissé en sens inverse).
        Poser le verrou ici, de façon synchrone, ferme cette fenêtre de
        course."""
        if self.live_busy:
            return False
        self.live_busy = True
        return True

    def disarm(self) -> None:
        self.armed = False

    def toggle_sign(self) -> None:
        self.sign = -1 if self.sign == 1 else 1

    def start_drag(self) -> None:
        self.drag_px = 0.0

    def drag(self, dx: float) -> int:
        """À appeler à chaque delta INCRÉMENTAL de mouvement pendant le
        glissé (`e.local_delta.x` côté Flet — malgré une docstring Flet
        ambiguë, c'est bien incrémental événement par événement : le pan
        de l'image, ailleurs dans ces mêmes apps, fait déjà `offset_x +=
        e.local_delta.x` et fonctionne correctement dans les deux sens,
        ce qui confirme le sens incrémental). Renvoie la tolérance
        courante (pour affichage/aperçu live)."""
        self.drag_px += dx
        return self.live_tolerance()

    def live_tolerance(self) -> int:
        return max(self.min_tolerance, min(self.max_tolerance, round(
            self.tolerance + self.drag_px * self.sensitivity)))

    def end_drag(self) -> int:
        """Fige la tolérance courante comme nouvelle base (le prochain
        glissé en repart) et renvoie sa valeur."""
        self.tolerance = self.live_tolerance()
        self.drag_px = 0.0
        return self.tolerance

    def combine(self, new_mask: np.ndarray) -> np.ndarray | None:
        """Combine `new_mask` (True = fond, ce pick) avec le masque déjà
        accumulé, sans le persister — pour un aperçu en direct."""
        if self.sign < 0:
            if self.bg_mask is None:
                return None
            return self.bg_mask & ~new_mask
        return new_mask if self.bg_mask is None else (self.bg_mask | new_mask)

    def commit(self, new_mask: np.ndarray) -> np.ndarray | None:
        """Persiste la combinaison dans `self.bg_mask`."""
        self.bg_mask = self.combine(new_mask)
        return self.bg_mask

    def reset(self) -> None:
        """Remet à zéro (nouvelle image, restauration, changement de mode)."""
        self.bg_mask = None
        self.armed = False
        self.sign = 1
        self.drag_px = 0.0


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


# ================================================================ #
#   RETOUCHE (Débruiter, Virage, Grain pellicule, Copyright, Netteté)
# ================================================================ #
# Extractions fidèles des scripts autonomes du même nom : mêmes formules,
# mêmes noms, partagées avec Data/Retouche par lot.pyw (aperçu live).


def apply_denoise(image: Image.Image, *, h: float = 4, h_color: float = 4,
                   template_window: int = 7, search_window: int = 21
                   ) -> Image.Image:
    """Réduction de bruit Non-Local Means — reprise fidèle de Débruiter.py."""
    bgr = cv2.cvtColor(np.array(image.convert("RGB")), cv2.COLOR_RGB2BGR)
    denoised_bgr = cv2.fastNlMeansDenoisingColored(
        bgr, None, h=h, hColor=h_color,
        templateWindowSize=template_window, searchWindowSize=search_window)
    return Image.fromarray(cv2.cvtColor(denoised_bgr, cv2.COLOR_BGR2RGB))


def apply_sharpen(image: Image.Image, *, radius1: float = 4,
                   percent1: int = 42, radius2: float = 2,
                   percent2: int = 42) -> Image.Image:
    """Deux passes d'UnsharpMask — reprise fidèle de Améliorer netteté.py."""
    result = image.filter(
        ImageFilter.UnsharpMask(radius=radius1, percent=percent1,
                               threshold=0))
    return result.filter(
        ImageFilter.UnsharpMask(radius=radius2, percent=percent2,
                               threshold=0))


def lift_shadows(gray, lift_pct):
    """Remonte le point noir avant colorisation, sans toucher le blanc :
    gray=0 -> lift_pct/100, gray=1 -> inchangé (pied de courbe argentique).
    Éclaircit l'image dans le fichier plutôt qu'en réduisant la densité à
    l'impression, ce qui délaverait aussi les hautes lumières colorées
    (retour user). Reprise fidèle de Virage.py."""
    if lift_pct <= 0:
        return gray
    lift = lift_pct / 100.0
    return lift + (1.0 - lift) * gray


def colorize_hsl(pil_img, hue_deg, saturation_pct, shadow_lift_pct=0):
    """Convertit en niveaux de gris puis colorise en HSL à teinte/saturation
    fixes — la luminosité de chaque pixel reste celle du noir et blanc,
    exactement comme "Coloriser" dans Photoshop/Affinity (noir en L=0,
    blanc en L=1, teinte pleine au milieu). Reprise fidèle de Virage.py."""
    gray = np.asarray(pil_img.convert("L"), dtype=np.float64) / 255.0
    gray = lift_shadows(gray, shadow_lift_pct)
    hue, sat = (hue_deg % 360) / 360.0, saturation_pct / 100.0
    # LUT de 256 entrées (une par niveau de gris possible) : colorsys ne
    # traite qu'un pixel à la fois, mais teinte/saturation étant fixes ici,
    # 256 appels suffisent au lieu d'un par pixel de l'image.
    lut = np.array(
        [colorsys.hls_to_rgb(hue, level / 255.0, sat) for level in range(256)],
        dtype=np.float32) * 255.0
    indices = np.clip(np.round(gray * 255), 0, 255).astype(np.uint8)
    return Image.fromarray(lut[indices].astype(np.uint8))


def colorize_multiply(pil_img, hue_deg, saturation_pct, lightness_pct,
                      shadow_lift_pct=0):
    """Convertit en niveaux de gris puis pose une couleur unie en mode
    Multiply par-dessus — exactement un calque couleur uni HSL + mode de
    fusion "Multiplier" dans Affinity/Photoshop (résultat = gris × couleur).

    Contrairement à "Coloriser" (substitution HSL), la teinte de la couleur
    reste visible jusque dans les hautes lumières : un gris à 255 (blanc)
    multiplié par la couleur redonne la couleur elle-même, jamais du blanc
    pur — un tirage papier ancien n'est jamais neutre, même dans ses zones
    les plus claires (retour user : hautes lumières "cramées" avec l'ancienne
    méthode, besoin de plus de contrôle sur la teinte obtenue).

    Multiply ne peut qu'assombrir (résultat <= gris) : shadow_lift_pct
    remonte le point noir en amont pour compenser une image trop sombre
    (retour user), sans toucher le blanc donc sans affecter la couleur des
    hautes lumières. Reprise fidèle de Virage.py."""
    gray = np.asarray(pil_img.convert("L"), dtype=np.float64) / 255.0
    gray = lift_shadows(gray, shadow_lift_pct)
    hue, light, sat = (hue_deg % 360) / 360.0, lightness_pct / 100.0, saturation_pct / 100.0
    color_rgb = np.array(colorsys.hls_to_rgb(hue, light, sat), dtype=np.float64)
    result = gray[:, :, np.newaxis] * color_rgb[np.newaxis, np.newaxis, :]
    return Image.fromarray(np.round(result * 255).astype(np.uint8))


_LUTS_DIR = Path(__file__).resolve().parent / "LUTs"


def list_cube_luts() -> list[str]:
    """Noms de fichiers .cube présents dans Data/LUTs, triés — la liste
    proposée par Retouche par lot.pyw suit donc le contenu du dossier sans
    rien à déclarer ailleurs (retour user : LUTs déposés à la volée)."""
    if not _LUTS_DIR.is_dir():
        return []
    return sorted(p.name for p in _LUTS_DIR.glob("*.cube"))


@functools.lru_cache(maxsize=8)
def _load_cube_lut(name: str):
    """Parse un LUT 3D .cube (Adobe/DaVinci Resolve) en table
    (size, size, size, 3) indexée [b, g, r] — le fichier liste les valeurs
    avec l'indice rouge variant le plus vite, ce qui correspond à l'ordre
    C d'un reshape (N, N, N, 3) une fois les axes nommés (bleu, vert,
    rouge). Mis en cache par nom de fichier : un LUT ne change pas entre
    deux images d'un même lot."""
    size = None
    domain_min = np.zeros(3, dtype=np.float32)
    domain_max = np.ones(3, dtype=np.float32)
    values = []
    # utf-8-sig : plusieurs LUTs du commerce (export Adobe/Windows) sont
    # sauvegardés avec un BOM, qui masquait sinon le mot-clé LUT_3D_SIZE
    # sur la première ligne et faisait échouer le parsing en silence
    # (retour user : aucun effet visible, aucune erreur).
    with open(_LUTS_DIR / name, "r", encoding="utf-8-sig") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#") or line.startswith("TITLE"):
                continue
            if line.startswith("LUT_3D_SIZE"):
                size = int(line.split()[-1])
            elif line.startswith("DOMAIN_MIN"):
                domain_min = np.array(line.split()[1:4], dtype=np.float32)
            elif line.startswith("DOMAIN_MAX"):
                domain_max = np.array(line.split()[1:4], dtype=np.float32)
            else:
                parts = line.split()
                if len(parts) == 3:
                    values.append([float(v) for v in parts])
    if not size or len(values) != size ** 3:
        raise ValueError(f"LUT .cube invalide ou incomplet : {name}")
    table = np.array(values, dtype=np.float32).reshape(size, size, size, 3)
    return table, domain_min, domain_max, size


def apply_cube_lut(pil_img: Image.Image, lut_name: str,
                   intensity: float = 100.0) -> Image.Image:
    """Applique un LUT 3D .cube par interpolation trilinéaire, mélangé à
    l'image d'origine selon `intensity` (0-100 %, comme un calque LUT
    d'opacité réduite). Silencieusement sans effet si `lut_name` est vide
    ou introuvable (fichier déplacé/supprimé entre deux lancements)."""
    if not lut_name or intensity <= 0:
        return pil_img
    try:
        table, domain_min, domain_max, size = _load_cube_lut(lut_name)
    except (OSError, ValueError):
        return pil_img

    rgb = np.asarray(pil_img.convert("RGB"), dtype=np.float32) / 255.0
    span = np.maximum(domain_max - domain_min, 1e-6)
    coord = np.clip((rgb - domain_min) / span, 0.0, 1.0) * (size - 1)
    i0 = np.floor(coord).astype(np.int32)
    i1 = np.minimum(i0 + 1, size - 1)
    frac = coord - i0
    r0, g0, b0 = i0[..., 0], i0[..., 1], i0[..., 2]
    r1, g1, b1 = i1[..., 0], i1[..., 1], i1[..., 2]
    fr, fg, fb = frac[..., 0:1], frac[..., 1:2], frac[..., 2:3]

    def corner(bi, gi, ri):
        return table[bi, gi, ri]

    c00 = corner(b0, g0, r0) * (1 - fr) + corner(b0, g0, r1) * fr
    c10 = corner(b0, g1, r0) * (1 - fr) + corner(b0, g1, r1) * fr
    c01 = corner(b1, g0, r0) * (1 - fr) + corner(b1, g0, r1) * fr
    c11 = corner(b1, g1, r0) * (1 - fr) + corner(b1, g1, r1) * fr
    c0 = c00 * (1 - fg) + c10 * fg
    c1 = c01 * (1 - fg) + c11 * fg
    mapped = c0 * (1 - fb) + c1 * fb

    amount = np.clip(intensity, 0.0, 100.0) / 100.0
    blended = rgb * (1 - amount) + mapped * amount
    return Image.fromarray((np.clip(blended, 0.0, 1.0) * 255).astype(np.uint8))


def add_chromatic_aberration(pil_img: Image.Image, strength: float,
                             axial_ratio: float = 0.15) -> Image.Image:
    """Aberration chromatique radiale + axiale : R agrandi, B rétréci, G =
    référence. Reprise fidèle de Grain pellicule.py.

    strength    : intensité en % de la diagonale (0.3 = subtil · 1.0 =
                  prononcé · 2.0 = fort)
    axial_ratio : part de translation uniforme ajoutée (0 = purement
                  radial, 0.15 = subtil au centre)
    """
    if strength <= 0:
        return pil_img
    img = np.array(pil_img, dtype=np.float32) / 255.0
    h, w = img.shape[:2]
    cy, cx = h / 2.0, w / 2.0

    scale = strength / 100.0
    scale_r = 1.0 + scale
    scale_b = max(1e-6, 1.0 - scale)

    y_grid, x_grid = np.mgrid[0:h, 0:w].astype(np.float32)
    dx = x_grid - cx
    dy = y_grid - cy

    axial = strength / 100.0 * min(h, w) * axial_ratio

    map_x_r = (cx + dx / scale_r + axial).astype(np.float32)
    map_y_r = (cy + dy / scale_r + axial).astype(np.float32)
    map_x_b = (cx + dx / scale_b - axial).astype(np.float32)
    map_y_b = (cy + dy / scale_b - axial).astype(np.float32)

    r = cv2.remap(img[:, :, 0], map_x_r, map_y_r, cv2.INTER_CUBIC, borderMode=cv2.BORDER_REPLICATE)
    g = img[:, :, 1]
    b = cv2.remap(img[:, :, 2], map_x_b, map_y_b, cv2.INTER_CUBIC, borderMode=cv2.BORDER_REPLICATE)

    result = np.clip(np.stack([r, g, b], axis=-1), 0.0, 1.0)
    return Image.fromarray((result * 255).astype(np.uint8))


def add_desaturate_extremes(
    pil_img: Image.Image,
    shadow_threshold: float,
    shadow_intensity: float,
    highlight_threshold: float,
    highlight_intensity: float,
    midtone_boost: float = 0.0,
) -> Image.Image:
    """Désature les ombres/HL et booste optionnellement la saturation des
    mi-tons. Reprise fidèle de Grain pellicule.py.

    shadow_threshold    : luma en dessous duquel les ombres sont désaturées
                          (ex. 0.25)
    shadow_intensity    : force de la désaturation dans les ombres (0.0–1.0)
    highlight_threshold : luma au-dessus duquel les hautes lumières sont
                          désaturées (ex. 0.85)
    highlight_intensity : force de la désaturation dans les hautes
                          lumières (0.0–1.0)
    midtone_boost       : saturation supplémentaire en mi-tons (0 = aucun,
                          0.3 = prononcé)
    """
    img = np.array(pil_img, dtype=np.float32) / 255.0
    luma = 0.299 * img[:, :, 0] + 0.587 * img[:, :, 1] + 0.114 * img[:, :, 2]
    gray = np.stack([luma, luma, luma], axis=-1)

    # Masque doux pour les ombres : 1.0 en luma=0, 0.0 au seuil
    shadow_mask = np.clip(1.0 - luma / max(1e-6, shadow_threshold), 0.0, 1.0)[:, :, np.newaxis]
    # Masque doux pour les hautes lumières : 0.0 au seuil, 1.0 en luma=1
    highlight_mask = np.clip(
        (luma - highlight_threshold) / max(1e-6, 1.0 - highlight_threshold), 0.0, 1.0
    )[:, :, np.newaxis]

    result = img + (gray - img) * shadow_mask * shadow_intensity
    result = result + (gray - result) * highlight_mask * highlight_intensity

    if midtone_boost > 0:
        # Masque mi-tons = (1 - shadow_mask) × (1 - highlight_mask) :
        # vaut 1 entre les deux seuils, retombe à 0 aux extrêmes.
        midtone_mask = (1.0 - shadow_mask) * (1.0 - highlight_mask)
        result = result + (result - gray) * midtone_mask * midtone_boost

    return Image.fromarray((np.clip(result, 0.0, 1.0) * 255).astype(np.uint8))


def add_film_grain(
    pil_img: Image.Image,
    amount: float,
    size: float,
    color_ratio: float,
    shadow_boost: float,
    floor: float,
    chroma_shift: float = 0.0,
) -> Image.Image:
    """Applique un grain argentique simulé à une image PIL RGB. Reprise
    fidèle de Grain pellicule.py.

    chroma_shift > 0 : grain indépendant par canal R/G/B avec décalage
    spatial, simulant le désalignement physique des couches d'émulsion
    argentique.
    """
    img = np.array(pil_img, dtype=np.float32) / 255.0
    h, w = img.shape[:2]

    size_px = max(1.0, size / 100.0 * min(h, w))
    grain_h = max(1, round(h / size_px))
    grain_w = max(1, round(w / size_px))

    rng = np.random.default_rng()
    grain_mono = rng.normal(0.0, amount, (grain_h, grain_w, 1)).astype(np.float32)

    if chroma_shift > 0.0:
        # Couches d'émulsion indépendantes : grain distinct par canal,
        # chacun agrandi séparément
        gr = cv2.resize(rng.normal(0.0, amount, (grain_h, grain_w)).astype(np.float32), (w, h), interpolation=cv2.INTER_CUBIC)
        gg = cv2.resize(rng.normal(0.0, amount, (grain_h, grain_w)).astype(np.float32), (w, h), interpolation=cv2.INTER_CUBIC)
        gb = cv2.resize(rng.normal(0.0, amount, (grain_h, grain_w)).astype(np.float32), (w, h), interpolation=cv2.INTER_CUBIC)
        # Décalage diagonal opposé entre R et B (G = référence)
        shift = round(chroma_shift * size_px)
        if shift > 0:
            gr = np.roll(gr, shift=( shift,  shift), axis=(0, 1))
            gb = np.roll(gb, shift=(-shift, -shift), axis=(0, 1))
        mono_full = cv2.resize(grain_mono[:, :, 0], (w, h), interpolation=cv2.INTER_CUBIC)
        mono_w = 1.0 - color_ratio
        grain = np.stack([
            mono_full * mono_w + gr * color_ratio,
            mono_full * mono_w + gg * color_ratio,
            mono_full * mono_w + gb * color_ratio,
        ], axis=-1)
    else:
        grain_color = rng.normal(0.0, amount, (grain_h, grain_w, 3)).astype(np.float32)
        grain_small = np.repeat(grain_mono, 3, axis=2) * (1.0 - color_ratio) + grain_color * color_ratio
        grain = cv2.resize(grain_small, (w, h), interpolation=cv2.INTER_CUBIC)

    luma = (0.299 * img[:, :, 0] + 0.587 * img[:, :, 1] + 0.114 * img[:, :, 2])
    # Parabole centrée sur les mi-tons avec plancher : peak à luma=0.5 (×1.0),
    # ombres/hautes lumières à floor — grain présent partout mais atténué
    # aux extrêmes
    weight = floor + (1.0 - floor) * np.clip(4.0 * luma * (1.0 - luma), 0.0, 1.0) ** shadow_boost
    weight = weight[:, :, np.newaxis]

    result = np.clip(img + grain * weight, 0.0, 1.0)
    return Image.fromarray((result * 255).astype(np.uint8))


def add_halation(
    pil_img: Image.Image,
    threshold: float,
    radius: float,
    intensity: float,
    red_shift: float,
) -> Image.Image:
    """Halo rougeâtre autour des hautes lumières (rebond de lumière sur la
    base du film). Reprise fidèle de Grain pellicule.py.

    radius est exprimé en % de la plus petite dimension de l'image
    (ex. 5 = 5 %). Blend mode Screen : img + h - img·h — jamais de
    clipping sur les HL déjà proches de 1.0.
    """
    img = np.array(pil_img, dtype=np.float32) / 255.0
    h, w = img.shape[:2]
    luma = 0.299 * img[:, :, 0] + 0.587 * img[:, :, 1] + 0.114 * img[:, :, 2]

    # Masque doux au-dessus du seuil
    mask = np.clip((luma - threshold) / max(1e-6, 1.0 - threshold), 0.0, 1.0)

    # Layer de halo basé sur le masque seul (pas img*mask) : la lumière
    # réfléchie par la base du film est indépendante des pixels sombres
    # environnants.
    halo = np.stack([
        np.clip(mask * (1.0 + red_shift), 0.0, 1.0),         # canal R boosté
        mask * max(0.0, 1.0 - red_shift * 0.2),              # canal G légèrement réduit
        mask * max(0.0, 1.0 - red_shift * 0.6),              # canal B atténué
    ], axis=-1).astype(np.float32)

    # Sigma en pixels (radius = % de la plus petite dim).
    # On floute à résolution réduite (effet basse fréquence) pour la
    # vitesse : on cible sigma ~20px dans l'espace réduit, puis on remonte.
    sigma = max(1.0, radius / 100.0 * min(h, w))
    scale = min(1.0, 20.0 / sigma)
    if scale < 1.0:
        sh, sw = max(1, int(h * scale)), max(1, int(w * scale))
        halo_s = cv2.resize(halo, (sw, sh), interpolation=cv2.INTER_AREA)
        halo_s = cv2.GaussianBlur(halo_s, (0, 0), sigmaX=sigma * scale, sigmaY=sigma * scale)
        blurred = cv2.resize(halo_s, (w, h), interpolation=cv2.INTER_LINEAR).astype(np.float32)
    else:
        blurred = cv2.GaussianBlur(halo, (0, 0), sigmaX=sigma, sigmaY=sigma)

    # Screen : img + h - img·h  (jamais de clipping — pixel à 0.95 avec
    # halo 0.15 donne 0.9575 au lieu de 1.10 en additif ; sur luma=0 le
    # halo s'exprime pleinement)
    halo = blurred * intensity
    result = np.clip(img + halo - img * halo, 0.0, 1.0)
    return Image.fromarray((result * 255).astype(np.uint8))


def add_bloom(
    pil_img: Image.Image,
    radius: float,
    intensity: float,
) -> Image.Image:
    """Glow général par superposition de l'image floutée en mode Soft
    Light. Reprise fidèle de Grain pellicule.py.

    radius est exprimé en % de la plus petite dimension de l'image
    (ex. 6 = 6 %). Soft Light renforce le contraste et la saturation
    perçue — effect argentique prononcé. La courbe (shoulder) permet
    d'atténuer a posteriori quand l'effet est trop marqué.
    """
    img = np.array(pil_img, dtype=np.float32) / 255.0
    h, w = img.shape[:2]
    sigma = max(1.0, radius / 100.0 * min(h, w))
    scale = min(1.0, 20.0 / sigma)
    if scale < 1.0:
        sh, sw = max(1, int(h * scale)), max(1, int(w * scale))
        img_s = cv2.resize(img, (sw, sh), interpolation=cv2.INTER_AREA)
        img_s = cv2.GaussianBlur(img_s, (0, 0), sigmaX=sigma * scale, sigmaY=sigma * scale)
        blurred = cv2.resize(img_s, (w, h), interpolation=cv2.INTER_LINEAR).astype(np.float32)
    else:
        blurred = cv2.GaussianBlur(img, (0, 0), sigmaX=sigma, sigmaY=sigma).astype(np.float32)
    # Soft Light (Photoshop)
    D = np.where(img <= 0.25,
                 ((16.0 * img - 12.0) * img + 4.0) * img,
                 np.sqrt(np.clip(img, 0.0, 1.0)))
    soft = np.where(blurred <= 0.5,
                    img - (1.0 - 2.0 * blurred) * img * (1.0 - img),
                    img + (2.0 * blurred - 1.0) * (D - img))
    result = img * (1.0 - intensity) + np.clip(soft, 0.0, 1.0) * intensity
    return Image.fromarray((np.clip(result, 0.0, 1.0) * 255).astype(np.uint8))


def get_date_taken(image):
    """Retourne la date de prise de vue depuis les EXIF, ou None. Reprise
    fidèle de Copyright.py."""
    try:
        exif_data = image._getexif()
        if exif_data:
            for tag_id, value in exif_data.items():
                if TAGS.get(tag_id) == "DateTimeOriginal":
                    # Format EXIF : "YYYY:MM:DD HH:MM:SS"
                    dt = datetime.strptime(value, "%Y:%m:%d %H:%M:%S")
                    MOIS = ["janvier", "février", "mars", "avril", "mai",
                           "juin", "juillet", "août", "septembre",
                           "octobre", "novembre", "décembre"]
                    return f"{dt.day} {MOIS[dt.month - 1]} {dt.year}"
    except Exception:
        pass
    return None


def add_copyright(image, label):
    """Dessine un bandeau de texte centré en bas de l'image (encadré blanc
    translucide). Reprise fidèle de Copyright.py. Mute `image` en place ET
    la retourne — l'appelant doit passer une copie s'il réutilise la
    source ailleurs (ex. cache d'aperçu)."""
    draw = ImageDraw.Draw(image, "RGBA")
    img_w, img_h = image.size

    font_size = round(img_h / 40)  # taille de police proportionnelle
    myFont = ImageFont.truetype(
        str(Path(__file__).resolve().parent.parent / "assets"
            / "Montserrat-Regular.ttf"), font_size)

    # Mesurer le texte
    bbox = draw.textbbox((0, 0), label, font=myFont)
    text_w = bbox[2] - bbox[0]
    text_h = bbox[3] - bbox[1]

    padding_x, padding_y = round(img_w / 40), round(img_h / 40)
    margin_bottom = round(img_h / 40)

    # Position centrée en bas
    box_x0 = (img_w - text_w) // 2 - padding_x
    box_y0 = img_h - text_h - padding_y * 2 - margin_bottom
    box_x1 = (img_w + text_w) // 2 + padding_x
    box_y1 = img_h - margin_bottom

    # Encadré blanc translucide
    draw.rounded_rectangle([box_x0, box_y0, box_x1, box_y1], radius=16,
                           fill=(255, 255, 255, 200))

    # Texte centré dans l'encadré
    text_x = (img_w - text_w) // 2
    text_y = box_y0 + padding_y
    draw.text((text_x, text_y), label, font=myFont, fill=(0, 0, 0, 255))

    return image


def preview_max_px(widget_px, floor_px, ceiling_px,
                   supersampling=None):
    """Résolution de rendu d'un aperçu, en px (côté le plus long).

    Flet dimensionne les contrôles en pixels LOGIQUES ; l'affichage les rend
    en pixels physiques, 2 à 3 fois plus nombreux sur un écran HDPI/Retina.
    Un aperçu rendu par PIL à une taille fixe y est donc étiré, et netteté,
    grain et bruit se jugent alors sur une image ré-échantillonnée.

    On rend à `widget_px * supersampling`, borné par `floor_px` (jamais plus
    grossier qu'avant ce calcul) et `ceiling_px` (au-delà, l'aperçu live
    devient plus lent que le geste qu'il accompagne).

    Partagé par `Recadrage manuel.pyw` et `Retouche par lot.pyw`, qui
    passent leurs propres bornes — le grain pellicule du second demande un
    proxy plus généreux que le cadrage du premier.
    """
    if supersampling is None:
        supersampling = CONSTANTS.PREVIEW_SUPERSAMPLING
    wanted = max(0, widget_px or 0) * supersampling
    return int(max(floor_px, min(wanted, ceiling_px)))
