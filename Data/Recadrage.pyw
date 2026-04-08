# -*- coding: utf-8 -*-
"""
Recadrage.pyw — Outil de recadrage photo interactif (Flet / PIL)
================================================================

Application de bureau multi-plateforme permettant de recadrer des photos
en lot selon des formats d'impression standards (tirages argentiques, photos
d'identité, etc.).

Fonctionnalités principales
----------------------------
* Recadrage interactif par glisser-déposer, zoom molette et pinch-to-zoom.
* Rotation fine (−15° … +15°) avec rendu aperçu en temps réel.
* Mode « Fit-in » : l'image entière tient dans le format (bords blancs).
* Noir & blanc, exposition, contraste, saturation, ombres, hautes lumières.
* Mise en page automatique : 2-en-1, ID ×2 / ×4, Polaroid, border 13x15,
  border 20x24, border 13x10.
* Formats multiples par image (plusieurs cadrages distincts sauvegardés
  en un seul clic via la liste « Formats multiples »).
* Mode batch interactif : toutes les images d'un dossier sont proposées
  l'une après l'autre ; l'opérateur valide ou ignore chaque photo.
* Export JPEG 300 dpi, espace colorimétrique sRGB avec profil ICC embarqué.

Dépendances
-----------
* flet    — interface graphique (widgets, événements, rendu)
* Pillow  — traitement d'image (recadrage, filtres, conversion couleur)
* numpy   — calculs LUT rapides (courbes ombres, hautes lumières, exposition)

Variables d'environnement reconnues
------------------------------------
FOLDER_PATH      : dossier source des images (défaut : répertoire courant)
SELECTED_FILES   : liste de noms de fichiers séparés par « | » à traiter
                   en priorité dans le dossier source

Raccourcis clavier
------------------
Entrée     : valider et passer à l'image suivante
Backspace  : basculer l'orientation portrait / paysage
Espace     : ignorer l'image courante et passer à la suivante

Version : voir __version__
"""

__version__ = "1.9.0"

#############################################################
#                          IMPORTS                          #
#############################################################
import flet as ft
import os
import shutil
import platform
import threading
import json
import time
from PIL import Image, ImageOps, ImageFilter, ImageEnhance, ImageCms
import asyncio
import contextlib
import math
import io
import base64
import numpy as np
import importlib.util

os.environ.setdefault("ORT_LOGGING_LEVEL", "3")  # Suppress onnxruntime performance warnings
REMBG_AVAILABLE = importlib.util.find_spec("rembg") is not None

# ===================== Configuration ===================== #
MAX_CANVAS_SIZE = 1200  # Taille max du canvas
CONTROLS_WIDTH = 270    # Largeur de la colonne de contrôles
DPI = 300  # Résolution d'export

# Formats d'impression (largeur_mm, hauteur_mm) - en portrait
FORMATS = {
    "ID (36x46mm)": (36, 46),
    "9x13 (89x127mm)": (89, 127),
    "10x10 (102x102mm)": (102, 102),
    "10x15 (102x152mm)": (102, 152),
    "13x18 (127x178mm)": (127, 178),
    "15x20 (152x203mm)": (152, 203),
    "15x15 (152x152mm)": (152, 152),
    "18x24 (178x240mm)": (178, 240),
    "20x30 (203x305mm)": (203, 305),
    "30x30 (305x305mm)": (305, 305),
    "30x40 (305x405mm)": (305, 405),
    "30x45 (305x455mm)": (305, 455),
    "40x50 (405x505mm)": (405, 505),
    "40x60 (405x605mm)": (405, 605),
    "50x70 (505x705mm)": (505, 705),
    "60x80 (605x805mm)": (605, 805),
    "60x90 (605x905mm)": (605, 905),
    "70x100 (705x1005mm)": (705, 1005)
}

# Colors
DARK = "#222429"
BG = "#373d4a"
GREY = "#2C3038"
LIGHT_GREY = "#9399A6"
BLUE = "#45B8F5"
VIOLET = "#AC92EC"
GREEN = "#49B76C"
YELLOW = "#EECB6D"
ORANGE = "#FFA071"
RED = "#F17171"
WHITE = "#c7ccd8"

# ===================== Layout ===================== #
LEFT_COL_WIDTH   = 200   # Largeur de la colonne de gauche (réglages sliders)
RIGHT_COL_WIDTH  = 250   # Largeur de la colonne de droite (formats + histogramme + boutons)
HISTOGRAM_HEIGHT = 85    # Hauteur de l'histogramme en pixels


def mm_to_pixels(mm, dpi=DPI):
    """
    Convertit une dimension en millimètres en nombre de pixels entiers.

    Parameters
    ----------
    mm : float
        Dimension à convertir en millimètres.
    dpi : int, optional
        Résolution cible en points par pouce (défaut : DPI = 300).

    Returns
    -------
    int
        Nombre de pixels correspondant (arrondi à l'entier inférieur).

    Exemple
    -------
    >>> mm_to_pixels(102, 300)  # 102 mm à 300 dpi ≈ 1205 px
    1205
    """
    return int(mm / 25.4 * dpi)

# Profil sRGB pré-construit (réutilisé pour chaque export)
_SRGB_PROFILE = ImageCms.createProfile("sRGB")
_SRGB_ICC = ImageCms.ImageCmsProfile(_SRGB_PROFILE).tobytes()

def convert_to_srgb(img: Image.Image, icc_profile: bytes | None) -> Image.Image:
    """
    Convertit une image PIL vers l'espace colorimétrique sRGB.

    Si un profil ICC source est fourni (lu depuis les métadonnées de
    l'image originale), la conversion est colorimétrique correcte via
    ImageCms avec l'intention de rendu PERCEPTUAL. Sans profil, l'image
    est supposée déjà en sRGB et est retournée telle quelle.

    Cette fonction est appelée systématiquement :
      - lors de la génération de la prévisualisation (_render_preview)
      - lors de l'export final (validate_and_next) pour garantir que le
        JPEG sauvegardé est conforme sRGB quel que soit l'espace source
        (AdobeRGB, ProPhoto, etc.).

    Parameters
    ----------
    img : PIL.Image.Image
        Image source à convertir (mode RGB ou RGBA attendu).
    icc_profile : bytes or None
        Profil ICC brut de l'image source (img.info.get('icc_profile')).
        None si aucun profil n'est disponible.

    Returns
    -------
    PIL.Image.Image
        Image en mode RGB dans l'espace colorimétrique sRGB.
    """
    if not icc_profile:
        return img  # déjà sRGB par défaut
    try:
        src_profile = ImageCms.ImageCmsProfile(io.BytesIO(icc_profile))
        img_rgb = img.convert("RGB")
        return ImageCms.profileToProfile(
            img_rgb, src_profile, _SRGB_PROFILE,
            renderingIntent=ImageCms.Intent.PERCEPTUAL,
            outputMode="RGB",
        )
    except Exception:
        return img


def _erode_alpha(img: Image.Image, radius: int) -> Image.Image:
    """
    Érode le canal alpha d'une image RGBA d'environ ``radius`` pixels.

    Utilise un filtre morphologique Min (ImageFilter.MinFilter) sur le
    canal alpha pour supprimer les franges résiduelles (halo coloré) en
    bordure de masque après suppression de fond par IA.

    Parameters
    ----------
    img : PIL.Image.Image
        Image en mode RGBA.
    radius : int
        Rayon d'érosion en pixels. 0 ou négatif = pas d'érosion.

    Returns
    -------
    PIL.Image.Image
        Image RGBA avec le canal alpha érodé.
    """
    if img.mode != "RGBA" or radius <= 0:
        return img
    r, g, b, a = img.split()
    # MinFilter(3) appliqué radius fois : coût O(9 × radius × N pixels)
    # bien plus rapide que MinFilter(2*radius+1) en O((2r+1)² × N).
    for _ in range(radius):
        a = a.filter(ImageFilter.MinFilter(3))
    return Image.merge("RGBA", (r, g, b, a))


#############################################################
#                         CONTENT                           #
#############################################################
class PhotoCropper:
    """
    Logique principale de l'application de recadrage photo.

    Cette classe centralise l'état de l'application, la construction des
    widgets Flet et toutes les méthodes de traitement d'image. Elle reçoit
    la `page` Flet fournie par le runtime et construit elle-même tous les
    contrôles (sliders, switches, boutons, canvas) qui sont ensuite montés
    dans la mise en page de la fonction `main`.

    Organisation interne
    --------------------
    État du batch
        image_paths, current_index, batch_mode, source_folder
    Configuration du canevas
        current_format, canvas_is_portrait, canvas_w, canvas_h
    Transformation interactive
        scale, offset_x, offset_y, base_scale, rotation
    Filtres actifs
        is_bw, is_sharpen, fit_in, contrast, saturation, exposure,
        shadows, highlights, enhance_toggle
    Mise en page / planches
        border_13x15, border_20x24, border_13x10, border_polaroid,
        border_id2, border_id4, copies_count, extra_formats
    Cache prévisualisation
        _preview_tmp_dir, _preview_counter, _prev_preview_path
    """

    def __init__(self, page: ft.Page):
        """
        Initialise l'application et construit tous les widgets Flet.

        La méthode réalise dans l'ordre :
          1. Création du répertoire de cache pour les prévisualisations
             temporaires (`.preview_cache`) et nettoyage des éventuels
             résidus d'une session précédente.
          2. Initialisation de toutes les variables d'état (voir attributs
             listés dans la docstring de la classe).
          3. Instanciation de chaque widget Flet (sliders, switches, boutons,
             GestureDetector, Stack, Container canvas).

          Les widgets ne sont PAS ajoutés à la page ici ; c'est la fonction
          `main` qui les monte dans la mise en page finale.

        Parameters
        ----------
        page : ft.Page
            La page Flet fournie par `ft.run(main)`.  Elle sert à :
            - déclencher les rafraîchissements visuels (page.update())
            - lire les dimensions courantes de la fenêtre
            - modifier le titre de la fenêtre
        """
        self.page = page
        # État du batch
        self.image_paths = []
        self.current_index = 0
        self.batch_mode = False
        self._preloaded = False
        self.source_folder = os.environ.get("FOLDER_PATH", os.getcwd())
        # Dossier de prévisualisation temporaire (au plus 1 fichier à la fois)
        self._preview_tmp_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".preview_cache")
        os.makedirs(self._preview_tmp_dir, exist_ok=True)
        # Vider les éventuels résidus d'une session précédente
        for _f in os.listdir(self._preview_tmp_dir):
            try: os.remove(os.path.join(self._preview_tmp_dir, _f))
            except OSError: pass
        self._preview_counter = 0
        self._prev_preview_path = None

        # Configuration du canvas (calculé dynamiquement)
        self.canvas_is_portrait = True
        self.current_format = FORMATS["ID (36x46mm)"]
        self.current_format_label = "ID (36x46mm)"
        self.border_13x15 = False
        self.border_20x24 = False
        self.border_13x10 = False
        self.border_polaroid = False
        self.border_id2 = False
        self.border_id4 = True
        self.save_to_network = True  # Sauvegarder les ID X4 sur le réseau par défaut
        self.enhance_toggle = False  # Retro-compat snapshots anciens
        self.canvas_w = 800  # Valeur initiale, ajustée au chargement
        self.canvas_h = self.canvas_w * self.current_format[1] / self.current_format[0]
        self.display_w = int(self.canvas_w)   # initialisé avant tout chargement d'image
        self.display_h = int(self.canvas_h)   # pour éviter AttributeError dans _clamp_offsets

        # Gestion du zoom et transformation
        self.scale = 1.0          # Scale actuel
        self.offset_x = 0.0       # Offset X en pixels
        self.offset_y = 0.0       # Offset Y en pixels
        self.base_scale = 1.0
        self.pinch_start_scale = 1.0  # Scale au début du pinch
        self._last_pan_render = 0.0   # Throttle pan : horodatage du dernier update
        self._last_rotation_render = 0.0  # Throttle rotation
        self._last_zoom_render = 0.0      # Throttle zoom
        self._bounds_cache: tuple | None = None  # Cache (scale, rotation, (bw, bh))

        # Option noir et blanc
        self.is_bw = False

        # Rotation
        self.rotation = 0.0
        self.rotation_slider = ft.Slider(
            value=self.rotation,
            min=-15.0,
            max=15.0,
            divisions=300,
            label=f"{self.rotation:.1f}°",
            active_color=BLUE,
            on_change=self.on_rotation_update,
            on_change_end=self.on_rotation_end,
        )

        # Zoom
        self.zoom_slider = ft.Slider(
            value=1.0,
            min=1.0,
            max=3.0,
            divisions=60,
            label="1.00×",
            active_color=BLUE,
            on_change=self.on_zoom_update,
            on_change_end=self.on_zoom_end,
        )

        # Ombres (Shadows — similaire à Camera Raw)
        self.shadows = 20.0
        self.shadows_slider = ft.Slider(
            value=self.shadows,
            min=-100,
            max=100,
            divisions=20,
            label="20",
            active_color=YELLOW,
            on_change=self.on_shadows_label,
            on_change_end=self.on_shadows_end,
        )

        # Hautes lumières (Highlights — similaire à Camera Raw)
        self.highlights = 0.0
        self.highlights_slider = ft.Slider(
            value=self.highlights,
            min=-100,
            max=100,
            divisions=20,
            label="0",
            active_color=YELLOW,
            on_change=self.on_highlights_label,
            on_change_end=self.on_highlights_end,
        )

        # Nombre d'exemplaires
        self.copies_count = 1
        self.copies_text = ft.Text(
            "1",
            size=22,
            weight=ft.FontWeight.BOLD,
            text_align=ft.TextAlign.CENTER,
            width=36,
            color=WHITE,
        )
        self.copies_minus_btn = ft.IconButton(
            icon=ft.Icons.REMOVE,
            icon_color=WHITE,
            icon_size=20,
            on_click=self.decrement_copies,
            tooltip="Moins",
        )
        self.copies_plus_btn = ft.IconButton(
            icon=ft.Icons.ADD,
            icon_color=BLUE,
            icon_size=20,
            on_click=self.increment_copies,
            tooltip="Plus",
        )

        # Formats multiples
        self.extra_formats = []  # list of snapshot dicts with full view state
        self.extra_formats_display = ft.Text("—", size=11, color=LIGHT_GREY, max_lines=1, text_align=ft.TextAlign.LEFT, no_wrap=True)

        # Image principale
        self.image_display = ft.Image(
            src="data:image/gif;base64,R0lGODlhAQABAAD/ACwAAAAAAQABAAACADs=", #1x1 pixel transparent GIF, plus léger que les placeholders de PIL
            fit=ft.BoxFit.COVER,
            gapless_playback=True,
        )
        
        # Container positionné dans un Stack avec scale/rotate pour le zoom et la rotation
        self.image_container = ft.Container(
            content=self.image_display,
            left=0,
            top=0,
        )

        # Lignes de grille des tiers (fixées au canevas, pas à l'image)
        _gc = ft.Colors.with_opacity(0.5, "#707070")
        self._grid_lines = [
            ft.Container(bgcolor=_gc, left=self.canvas_w / 3,     top=0,                    width=1,             height=self.canvas_h, visible=False),
            ft.Container(bgcolor=_gc, left=2 * self.canvas_w / 3, top=0,                    width=1,             height=self.canvas_h, visible=False),
            ft.Container(bgcolor=_gc, left=0,                     top=self.canvas_h / 3,    width=self.canvas_w, height=1,             visible=False),
            ft.Container(bgcolor=_gc, left=0,                     top=2 * self.canvas_h / 3,width=self.canvas_w, height=1,             visible=False),
        ]
        # Stack pour positionner l'image
        self.image_stack = ft.Stack(
            controls=[self.image_container, *self._grid_lines],
            width=self.canvas_w,
            height=self.canvas_h,
        )

        # GestureDetector pour gérer le pan et zoom
        self.gesture_detector = ft.GestureDetector(
            content=self.image_stack,
            on_pan_update=self.on_pan_update,
            on_pan_end=self.on_pan_end,
            on_scroll=self.on_scroll,
            # on_scale_start=self.on_scale_start,   # pinch trackpad macOS — désactivé (trop sensible)
            # on_scale_update=self.on_scale_update,  # pinch trackpad macOS — désactivé (trop sensible)
            drag_interval=33,
        )

        # visible status fallback when SnackBar is not shown
        self.status_text = ft.Text("")
        # action buttons (created here so main can reference them)
        self.validate_button = ft.Button(
            "Valider & Suivant",
            icon=ft.Icons.CHECK,
            bgcolor=GREEN,
            color=DARK,
            on_click=self.validate_and_next,
        )

        # Ignore button to skip current image
        self.ignore_button = ft.Button(
            "Ignorer Image",
            icon=ft.Icons.BLOCK,
            bgcolor=RED,
            color=DARK,
            on_click=self.ignore_image,
        )

        self.two_in_one_switch = ft.Switch(label="2 en 1", active_color=BLUE, value=False, visible=any(fmt in self.current_format_label for fmt in ["10x15", "13x18", "15x20"]), on_change=self.is_two_in_one_enabled)
        self.border_switch_13x15 = ft.Switch(label="13x15", active_color=ORANGE, value=False, visible="10x15" in self.current_format_label, on_change=self.on_border_toggle_13x15)
        self.border_switch_20x24 = ft.Switch(label="20x24", active_color=ORANGE, value=False, visible="18x24" in self.current_format_label, on_change=self.on_border_toggle_20x24)
        self.border_switch_13x10 = ft.Switch(label="13x10", active_color=ORANGE, value=False, visible="10x10" in self.current_format_label, on_change=self.on_border_toggle_13x10)
        self.border_switch_polaroid = ft.Switch(label="Polaroid", active_color=ORANGE, value=False, visible="10x10" in self.current_format_label, on_change=self.on_border_toggle_polaroid)
        self.border_switch_ID2 = ft.Switch(label="ID X2", active_color=ORANGE, value=False, visible="ID" in self.current_format_label, on_change=self.on_border_toggle_id2)
        self.border_switch_ID4 = ft.Switch(label="ID X4", active_color=ORANGE, value=True, visible="ID" in self.current_format_label, on_change=self.on_border_toggle_id4)
        self.network_switch = ft.Switch(label="Sauver sur réseau", active_color=GREEN, value=True, visible="ID" in self.current_format_label, on_change=self.on_network_toggle)
        self.sharpen_switch = ft.Switch(label="Netteté", active_color=BLUE, value=True, visible=True, on_change=self.on_sharpen_toggle)
        self.is_sharpen = True
        self.bw_switch = ft.Switch(label="Noir et blanc", active_color=YELLOW, value=False, on_change=self.on_bw_toggle)
        self.is_fit_in = False
        self.fit_in_switch = ft.Switch(label="Fit-in", active_color=VIOLET, value=False, on_change=self.on_fit_in_toggle)
        self.show_grid = False
        self.grid_switch = ft.Switch(label="Grille", active_color=BLUE, value=False, on_change=self.on_grid_toggle)
        # Suppression fond IA
        self._rembg_session = [None]        # birefnet-portrait / birefnet-general
        self._rembg_session_u2net = [None]  # u2net_human_seg / u2net
        self._rembg_original = None   # sauvegarde avant suppression du fond
        self._rembg_composite_cache = None  # (cache_key, PIL.Image RGB) — composite bg+mask à taille affichage
        self.rembg_bg_white = True
        self.rembg_human_seg = True
        self.rembg_precise = False  # False = rapide (u2net), True = précis (birefnet)
        self._rembg_bg_label = ft.Text("Fond blanc", size=12, color=DARK)
        self.rembg_bg_btn = ft.Button(
            content=self._rembg_bg_label,
            bgcolor=ft.Colors.GREY_200,
            on_click=self.on_rembg_bg_toggle,
            style=ft.ButtonStyle(
                padding=ft.Padding.symmetric(horizontal=6, vertical=2),
                shape=ft.RoundedRectangleBorder(radius=6),
            ),
            height=30,
            tooltip="Fond blanc / Fond flou",
        )
        self._rembg_model_label = ft.Text("Humain", size=12, color=DARK)
        self.rembg_model_btn = ft.Button(
            content=self._rembg_model_label,
            bgcolor=VIOLET,
            on_click=self.on_rembg_model_toggle,
            style=ft.ButtonStyle(
                padding=ft.Padding.symmetric(horizontal=6, vertical=2),
                shape=ft.RoundedRectangleBorder(radius=6),
            ),
            height=30,
            tooltip="Portrait / Généraliste" if REMBG_AVAILABLE else "",
        )
        self._rembg_precise_label = ft.Text("Rapide", size=12, color=DARK)
        self.rembg_precise_btn = ft.Button(
            content=self._rembg_precise_label,
            bgcolor=BLUE if REMBG_AVAILABLE else GREY,
            on_click=self.on_rembg_precise_toggle,
            style=ft.ButtonStyle(
                padding=ft.Padding.symmetric(horizontal=6, vertical=2),
                shape=ft.RoundedRectangleBorder(radius=6),
            ),
            height=30,
            disabled=not REMBG_AVAILABLE,
            tooltip="Rapide : u2net / Précis : birefnet" if REMBG_AVAILABLE else "",
        )
        # Érosion du masque — slider 0–8 px (0 = désactivé)
        self.rembg_erosion_radius = 5
        self.rembg_erosion_slider = ft.Slider(
            value=5,
            min=0,
            max=8,
            divisions=8,
            label="{value} px",
            active_color=ORANGE,
            on_change=self.on_rembg_erosion_change,
            on_change_end=self.on_rembg_erosion_end,
            width=130,
        )
        self.rembg_btn = ft.IconButton(
            icon=ft.Icons.AUTO_FIX_HIGH,
            selected_icon=ft.Icons.AUTO_FIX_HIGH,
            selected=False,
            icon_color=LIGHT_GREY,
            selected_icon_color=VIOLET,
            tooltip="Supprimer le fond par IA (rembg)" if REMBG_AVAILABLE else "pip install rembg onnxruntime",
            on_click=self.on_rembg,
            style=ft.ButtonStyle(padding=ft.Padding.all(4)),
        )

        # Sliders de réglages (panneau gauche)
        self.contrast = 0.0
        self.contrast_slider = ft.Slider(
            value=0, min=-20, max=20, divisions=40, label="0",
            active_color=YELLOW,
            on_change=self.on_contrast_label,
            on_change_end=self.on_contrast_end,
        )
        self.saturation = 20.0
        self.saturation_slider = ft.Slider(
            value=20, min=-100, max=100, divisions=20, label="20",
            active_color=VIOLET,
            on_change=self.on_saturation_label,
            on_change_end=self.on_saturation_end,
        )
        self.exposure = 10.0
        self.exposure_slider = ft.Slider(
            value=10, min=-100, max=100, divisions=20, label="10",
            active_color=YELLOW,
            on_change=self.on_exposure_label,
            on_change_end=self.on_exposure_end,
        )

        # Teinte (Hue)
        self.hue = 0.0
        self.hue_slider = ft.Slider(
            value=0, min=-180, max=180, divisions=36, label="0",
            active_color=VIOLET,
            on_change=self.on_hue_label,
            on_change_end=self.on_hue_end,
        )

        # Balance des blancs (temperature : - = froid/bleu, + = chaud/jaune)
        self.white_balance = 0.0
        self.white_balance_slider = ft.Slider(
            value=0, min=-100, max=100, divisions=20, label="0",
            active_color=VIOLET,
            on_change=self.on_wb_label,
            on_change_end=self.on_wb_end,
        )

        # Histogramme miniature
        self.histogram_image = ft.Image(
            src="data:image/gif;base64,R0lGODlhAQABAAD/ACwAAAAAAQABAAACADs=",
            width=RIGHT_COL_WIDTH,
            height=HISTOGRAM_HEIGHT,
            fit=ft.BoxFit.FILL,
            gapless_playback=True,
        )

        self.canvas_container = ft.Container(
            content=self.gesture_detector,
            bgcolor=ft.Colors.WHITE,
            clip_behavior=ft.ClipBehavior.HARD_EDGE,
            width=self.canvas_w,
            height=self.canvas_h,
            border=ft.Border.all(1, GREY),
        )

    # ================================================================ #
    #                    CANVAS & TRANSFORMATIONS                      #
    # ================================================================ #

    def update_canvas_size(self):
        """
        Recalcule et applique les dimensions optimales du canevas.

        Le canevas doit à la fois :
          - S'inscrire dans l'espace disponible (fenêtre − panneaux latéraux).
          - Respecter le ratio du format d'impression sélectionné et
            l'orientation courante (portrait / paysage).
          - Ne pas dépasser MAX_CANVAS_SIZE dans l'une ou l'autre dimension.

        Après le calcul, les attributs `canvas_w`, `canvas_h` sont mis à
        jour ainsi que les propriétés `width` / `height` des widgets
        `canvas_container` et `image_stack`.
        """
        available_width = min(self.page.window.width - CONTROLS_WIDTH - 80, MAX_CANVAS_SIZE) if self.page.window.width else 800
        available_height = min(self.page.window.height - 380, MAX_CANVAS_SIZE) if self.page.window.height else 600

        # Calculer le ratio du format choisi
        fmt_w, fmt_h = self.current_format
        if self.canvas_is_portrait:
            target_ratio = fmt_w / fmt_h  # portrait: largeur < hauteur
        else:
            target_ratio = fmt_h / fmt_w  # paysage: largeur > hauteur

        self.canvas_w = available_width
        self.canvas_h = self.canvas_w / target_ratio
        if self.canvas_h > available_height:
            self.canvas_h = available_height
            self.canvas_w = self.canvas_h * target_ratio

        self.canvas_container.width = self.canvas_w
        self.canvas_container.height = self.canvas_h
        self.image_stack.width = self.canvas_w
        self.image_stack.height = self.canvas_h
        # Repositionner les lignes de grille
        if hasattr(self, '_grid_lines'):
            self._grid_lines[0].left   = self.canvas_w / 3
            self._grid_lines[1].left   = 2 * self.canvas_w / 3
            self._grid_lines[0].height = self.canvas_h
            self._grid_lines[1].height = self.canvas_h
            self._grid_lines[2].top    = self.canvas_h / 3
            self._grid_lines[2].width  = self.canvas_w
            self._grid_lines[3].top    = 2 * self.canvas_h / 3
            self._grid_lines[3].width  = self.canvas_w
        self.page.update()

    def _update_transform(self):
        """
        Applique la transformation affine courante (scale, pan, rotation)
        au container de l'image dans le Stack.

        Appelle uniquement `.update()` sur le container (pas `page.update()`)
        pour minimiser le coût de rendu lors du pan/zoom interactif.
        """
        zoomed_w = self.display_w * self.scale
        zoomed_h = self.display_h * self.scale

        left = (self.canvas_w - zoomed_w) / 2 + self.offset_x
        top = (self.canvas_h - zoomed_h) / 2 + self.offset_y

        self.image_container.scale = self.scale
        self.image_container.rotate = math.radians(self.rotation)

        center_x = left + zoomed_w / 2
        center_y = top + zoomed_h / 2

        self.image_container.left = center_x - self.display_w / 2
        self.image_container.top  = center_y - self.display_h / 2
        self.image_container.update()

    def _get_transformed_bounds(self):
        """
        Retourne les dimensions de la boîte englobante de l'image après
        l'application du scale et de la rotation courante.

        La boîte englobante est calculée analytiquement (pas de rendu) :
          bound_w = scaled_w · |cos θ| + scaled_h · |sin θ|
          bound_h = scaled_w · |sin θ| + scaled_h · |cos θ|

        Résultat mis en cache : le calcul trigonométrique n'est refait que
        lorsque scale ou rotation ont changé depuis le dernier appel.

        Returns
        -------
        tuple[float, float]
            (bound_w, bound_h) en pixels écran.
        """
        if self._bounds_cache is not None:
            cs, cr, result = self._bounds_cache
            if cs == self.scale and cr == self.rotation:
                return result
        scaled_w = self.display_w * self.scale
        scaled_h = self.display_h * self.scale
        theta = math.radians(self.rotation)
        cos_t = abs(math.cos(theta))
        sin_t = abs(math.sin(theta))
        bound_w = scaled_w * cos_t + scaled_h * sin_t
        bound_h = scaled_w * sin_t + scaled_h * cos_t
        result = (bound_w, bound_h)
        self._bounds_cache = (self.scale, self.rotation, result)
        return result

    def _clamp_offsets(self):
        """
        Contraint offset_x et offset_y pour qu'aucune bordure de l'image
        n'apparaisse à l'intérieur du canevas.

        Règles appliquées :
          - Si l'image (après scale + rotation) est plus petite que le
            canevas dans un axe, l'offset est forcé à 0 sur cet axe (l'image
            reste centrée et ne peut pas être déplacée).
          - Sinon, l'offset est borné symétriquement entre -(débordement/2)
            et +(débordement/2) où le débordement vaut bound_dim − canvas_dim.
        """
        zoomed_w, zoomed_h = self._get_transformed_bounds()

        overflow_x = zoomed_w - self.canvas_w
        if overflow_x < 0.5:
            self.offset_x = 0
        else:
            max_offset_x = overflow_x / 2
            self.offset_x = min(max_offset_x, max(-max_offset_x, self.offset_x))

        overflow_y = zoomed_h - self.canvas_h
        if overflow_y < 0.5:
            self.offset_y = 0
        else:
            max_offset_y = overflow_y / 2
            self.offset_y = min(max_offset_y, max(-max_offset_y, self.offset_y))

    # ================================================================ #
    #                     CHARGEMENT DES IMAGES                        #
    # ================================================================ #

    def load_image(self, preserve_orientation=True):
        """
        Charge l'image courante (image_paths[current_index]) et prépare
        l'affichage.

        Étapes réalisées
        ------------------
        1. Réinitialisation des transformations (scale, offset).
        2. Vérification de l'accessibilité du fichier (existence + droits).
        3. Ouverture PIL : extraction du profil ICC, correction de
           l'orientation EXIF (`ImageOps.exif_transpose`), conversion RGBA.
        4. Détection automatique de l'orientation portrait / paysage
           (sauf si `preserve_orientation=True`).
        5. Calcul du `base_scale` pour que l'image « couvre » le canevas
           (mode crop) ou « tienne » dedans (mode fit-in).
        6. Génération de la prévisualisation via `_render_preview`.
        7. Mise à jour de la visibilité des switches (border, ID, etc.)
           selon le format actif.
        8. Mise à jour du titre de la fenêtre.

        En cas d'erreur (fichier invalide, exception PIL), le message est
        affiché dans `status_text` et l'application passe automatiquement
        à l'image suivante.

        Parameters
        ----------
        preserve_orientation : bool, optional
            Si True, l'orientation portrait/paysage du canevas n'est pas
            recalculée depuis les dimensions de l'image (utile lors d'un
            changement de format ou d'une bascule manuelle). Défaut : False.
        """
        if not self.image_paths:
            return
        if self.current_index >= len(self.image_paths):
            return
        # Réinitialiser les valeurs de transformation
        self.scale = 1.0
        self.offset_x = 0.0
        self.offset_y = 0.0
        if hasattr(self, 'zoom_slider'):
            self.zoom_slider.value = 1.0
            self.zoom_slider.label = "1.00×"

        path = self.image_paths[self.current_index]
        
        # Vérifier que le fichier existe et est accessible
        if not os.path.isfile(path) or not os.access(path, os.R_OK):
            self.status_text.value = f"Fichier inaccessible: {os.path.basename(path)}"
            self.page.update()
            # Passer à l'image suivante automatiquement
            self.current_index += 1
            if self.current_index < len(self.image_paths):
                self.load_image(preserve_orientation)
            return
        
        try:
            pil_img = Image.open(path)
            # Conserver le profil ICC avant toute conversion
            self.icc_profile = pil_img.info.get('icc_profile', None)
            # Appliquer la rotation EXIF pour corriger l'orientation
            pil_img = ImageOps.exif_transpose(pil_img)
            pil_img = pil_img.convert("RGBA")
            self.current_pil_image = pil_img
            self._rembg_original = None
            self.rembg_btn.selected = False
            self.orig_w, self.orig_h = pil_img.size
        except Exception as e:
            self.status_text.value = f"Erreur lors du chargement: {os.path.basename(path)} - {str(e)}"
            self.page.update()
            # Passer à l'image suivante automatiquement
            self.current_index += 1
            if self.current_index < len(self.image_paths):
                self.load_image(preserve_orientation)
            return

        if not preserve_orientation:
            self.canvas_is_portrait = True if self.orig_h >= self.orig_w else False

        self.update_canvas_size()
        
        # Calculer la taille de base : COVER en mode normal, CONTAIN en mode Fit-in
        scale_w = self.canvas_w / self.orig_w
        scale_h = self.canvas_h / self.orig_h
        if self.is_fit_in:
            self.base_scale = min(scale_w, scale_h)
        else:
            self.base_scale = max(scale_w, scale_h)
        
        self.display_w = int(round(self.orig_w * self.base_scale))
        self.display_h = int(round(self.orig_h * self.base_scale))
        if not self.is_fit_in:
            # +4 px garantit un débordement minimum même quand le ratio de l'image
            # correspond exactement à celui du format d'impression (ex. photo 2:3 en 10×15).
            # Sans ce surplus, overflow = 0 → _clamp_offsets bloque le pan à scale = 1.0.
            self.display_w = max(self.display_w, math.ceil(self.canvas_w) + 4)
            self.display_h = max(self.display_h, math.ceil(self.canvas_h) + 4)

        self.image_display.width = self.display_w
        self.image_display.height = self.display_h
        self._render_preview()

        # Réinitialiser le scale du container
        self.image_container.scale = 1.0

        # Appliquer la transformation initiale
        self._clamp_offsets()
        self._update_transform()

        if "10x15" in self.current_format_label:
            self.border_switch_13x15.visible = True
            self.border_switch_13x15.value = self.border_13x15
        else:
            self.border_switch_13x15.visible = False

        if "18x24" in self.current_format_label:
            self.border_switch_20x24.visible = True
            self.border_switch_20x24.value = self.border_20x24
        else:
            self.border_switch_20x24.visible = False

        if "10x10" in self.current_format_label:
            self.border_switch_13x10.visible = True
            self.border_switch_13x10.value = self.border_13x10
            self.border_switch_polaroid.visible = True
            self.border_switch_polaroid.value = self.border_polaroid
        else:
            self.border_switch_13x10.visible = False
            self.border_switch_polaroid.visible = False

        if "ID" in self.current_format_label:
            self.border_switch_ID2.visible = True
            self.border_switch_ID2.value = self.border_id2
            self.border_switch_ID4.visible = True
            self.border_switch_ID4.value = self.border_id4
            self.network_switch.visible = True
            self.network_switch.value = self.save_to_network
            self.sharpen_switch.value = True
        else:
            self.border_switch_ID2.visible = False
            self.border_switch_ID4.visible = False
            self.network_switch.visible = False
            self.sharpen_switch.value = self.sharpen_switch.value

        self.page.title = f"Crop: {os.path.basename(path)} ({self.current_index + 1}/{len(self.image_paths)})"
        self.page.update()
    
    def batch_process_interactive(self, e):
        """
        Initialise le batch interactif en listant les images du dossier source.

        Vérifications successives
        --------------------------
        1. Attente de 0,3 s pour s'assurer que les fichiers sont bien écrits
           sur le disque avant d'être lus.
        2. Lecture de FOLDER_PATH (dossier source) et optionnellement de
           SELECTED_FILES (liste de fichiers à prioriser).
        3. Filtrage des fichiers par extension image valide ; exclusion de
           `watermark.png`.
        4. Vérification d'intégrité de chaque image via `Image.verify()`.
        5. Si des images valides sont trouvées, `image_paths` et
           `current_index` sont initialisés et la première image est
           chargée.

        Ce flux est déclenché automatiquement 0,3 s après l'ouverture de
        la fenêtre (via `delayed_start` dans `main`) et peut aussi être
        appelé manuellement depuis un bouton.

        Parameters
        ----------
        e : ft.ControlEvent or None
            Événement Flet (non utilisé directement). Peut être None lors
            de l'appel programmatique depuis `delayed_start`.
        """
        import time

        folder = self.source_folder

        # Délai pour s'assurer que tous les fichiers sont complètement copiés
        time.sleep(0.3)

        selected_files_str = os.environ.get("SELECTED_FILES", "")
        selected_files_set = set(selected_files_str.split("|")) if selected_files_str else None

        try:
            all_files = os.listdir(folder)
        except Exception as e:
            self.status_text.value = f"Erreur lors de la lecture du dossier: {e}"
            self.page.update()
            return

        imgs = [f for f in all_files if f.lower().endswith(('.png', '.jpg', '.jpeg', '.jpe', '.tif', '.tiff', '.bmp', '.dib', '.gif', '.webp', '.ico', '.pcx', '.tga', '.ppm', '.pgm', '.pbm', '.pnm')) and not f == "watermark.png"]
        total_images_found = len(imgs)

        if selected_files_set:
            imgs = [f for f in imgs if f in selected_files_set]
            if not imgs and total_images_found > 0:
                self.status_text.value = f"{total_images_found} image(s) trouvée(s) mais aucune ne correspond aux fichiers sélectionnés"
                self.page.update()
                return

        if not imgs:
            if len(all_files) == 0:
                self.status_text.value = "Le dossier est vide"
            else:
                self.status_text.value = f"Aucune image valide trouvée dans le dossier ({len(all_files)} fichier(s) présent(s))"
            self.page.update()
            return

        valid_paths = []
        for img_file in imgs:
            img_path = os.path.join(folder, img_file)
            if os.path.isfile(img_path) and os.access(img_path, os.R_OK):
                try:
                    with Image.open(img_path) as test_img:
                        test_img.verify()
                    valid_paths.append(img_path)
                except Exception:
                    pass

        if not valid_paths:
            self.status_text.value = f"{len(imgs)} image(s) trouvée(s) mais aucune n'est accessible ou valide"
            self.page.update()
            return

        self.image_paths = valid_paths
        self.current_index = 0
        self.batch_mode = True
        self.load_image(preserve_orientation=False)

    # ================================================================ #
    #                      CALCUL DU RECADRAGE                         #
    # ================================================================ #

    def _compute_crop(self, target_w_px, target_h_px):
        """
        Calcule le recadrage de l'image courante pour le canevas principal.

        Raccourci vers `_compute_crop_with_canvas` en utilisant les
        paramètres du canevas principal (canvas_w, canvas_h, base_scale,
        offset_x, offset_y, scale).

        Parameters
        ----------
        target_w_px : int
            Largeur de l'image de sortie en pixels (résolution DPI).
        target_h_px : int
            Hauteur de l'image de sortie en pixels (résolution DPI).

        Returns
        -------
        PIL.Image.Image
            Image recadrée en mode RGB aux dimensions demandées.
        """
        return self._compute_crop_with_canvas(
            target_w_px, target_h_px,
            self.canvas_w, self.canvas_h,
            self.base_scale, self.offset_x, self.offset_y,
        )

    def _compute_crop_for_format(self, fmt_w_mm, fmt_h_mm, is_portrait):
        """
        Calcule le recadrage pour un format donné avec son propre ratio.

        Construit un canevas **virtuel** qui respecte le ratio du format
        cible tout en étant centré sur le même point de l'image que le
        canevas principal. Les offsets sont recalculés proportionnellement.

        Utilisé par la fonctionnalité « Formats multiples » pour exporter
        simultanément plusieurs formats différents depuis un seul point de
        vue « métier » (le centre de l'image vu à l'écran).

        Parameters
        ----------
        fmt_w_mm : float
            Largeur du format cible en mm.
        fmt_h_mm : float
            Hauteur du format cible en mm.
        is_portrait : bool
            True si l'export doit être en orientation portrait.

        Returns
        -------
        PIL.Image.Image
            Image recadrée en mode RGB aux dimensions du format cible (DPI).
        """
        if is_portrait:
            target_w_px = mm_to_pixels(fmt_w_mm)
            target_h_px = mm_to_pixels(fmt_h_mm)
        else:
            target_w_px = mm_to_pixels(fmt_h_mm)
            target_h_px = mm_to_pixels(fmt_w_mm)

        fmt_ratio = target_w_px / target_h_px
        avail_w = self.canvas_w
        avail_h = self.canvas_h
        if avail_w / avail_h > fmt_ratio:
            virt_h = avail_h
            virt_w = avail_h * fmt_ratio
        else:
            virt_w = avail_w
            virt_h = avail_w / fmt_ratio

        virt_base_scale = max(virt_w / self.orig_w, virt_h / self.orig_h)

        if self.base_scale > 0:
            off_img_x = self.offset_x / (self.base_scale * self.scale)
            off_img_y = self.offset_y / (self.base_scale * self.scale)
        else:
            off_img_x = off_img_y = 0.0
        virt_offset_x = off_img_x * virt_base_scale * self.scale
        virt_offset_y = off_img_y * virt_base_scale * self.scale

        return self._compute_crop_with_canvas(
            target_w_px, target_h_px,
            virt_w, virt_h,
            virt_base_scale, virt_offset_x, virt_offset_y,
        )

    def _compute_crop_from_snapshot(self, snapshot):
        """
        Calcule le recadrage à partir d'un snapshot complet de l'état de la vue.

        Un snapshot est un dictionnaire sauvegardé par `add_extra_format`.
        Il contient toutes les informations nécessaires pour reproduire le
        cadrage exact tel qu'il était au moment de l'ajout :
        dimensions du canevas virtuel, base_scale, scale, offsets, rotation,
        format (dims), orientation, réglages actifs (is_bw, shadows, etc.).

        La méthode écrase temporairement `self.rotation` et `self.is_bw`
        avec les valeurs du snapshot puis les restaure après le calcul.

        Parameters
        ----------
        snapshot : dict
            Dictionnaire produit par `add_extra_format`. Clés utilisées :
            ``dims``, ``is_portrait``, ``rotation``, ``is_bw``,
            ``canvas_w``, ``canvas_h``, ``base_scale``, ``scale``,
            ``offset_x``, ``offset_y``.

        Returns
        -------
        PIL.Image.Image
            Image recadrée en mode RGB aux dimensions du format du snapshot.
        """
        dims = snapshot["dims"]
        is_portrait = snapshot["is_portrait"]
        fmt_w_mm, fmt_h_mm = dims
        if is_portrait:
            target_w_px = mm_to_pixels(fmt_w_mm)
            target_h_px = mm_to_pixels(fmt_h_mm)
        else:
            target_w_px = mm_to_pixels(fmt_h_mm)
            target_h_px = mm_to_pixels(fmt_w_mm)

        saved_rotation = self.rotation
        saved_bw = self.is_bw
        self.rotation = snapshot["rotation"]
        self.is_bw = snapshot.get("is_bw", False)

        result = self._compute_crop_with_canvas(
            target_w_px, target_h_px,
            snapshot["canvas_w"], snapshot["canvas_h"],
            snapshot["base_scale"], snapshot["offset_x"], snapshot["offset_y"],
            scale_override=snapshot["scale"],
        )

        self.rotation = saved_rotation
        self.is_bw = saved_bw
        return result

    def _compute_crop_with_canvas(self, target_w_px, target_h_px,
                                   canvas_w, canvas_h, base_scale, offset_x, offset_y,
                                   scale_override=None):
        """
        Noyau du recadrage : calcule la transformation affine et l'applique.

        Algorithme
        ----------
        1. Calcule la transformation affine inverse (canvas → image source)
           en tenant compte du scale total, de la rotation et des offsets.
           La matrice affine 2×3 (à 6 paramètres) est passée directement à
           `Image.transform(..., Image.Transform.AFFINE, ...)` avec
           rééchantillonnage BICUBIC.
        2. Sur le résultat, applique la conversion N&B (`is_bw`).
        3. Aplatit le canal alpha sur fond blanc et retourne une image RGB.

        Note : les zones en dehors de l'image source apparaissent en blanc
        (fillcolor=(255,255,255,0) puis alpha composite à blanc).

        Parameters
        ----------
        target_w_px, target_h_px : int
            Dimensions de l'image de sortie en pixels.
        canvas_w, canvas_h : float
            Dimensions du canevas de référence en pixels écran.
        base_scale : float
            Scale de base calculé au chargement pour couvrir ce canevas.
        offset_x, offset_y : float
            Décalage de pan utilisateur en pixels écran.
        scale_override : float or None, optional
            Si fourni, écrase `self.scale` (utile pour les snapshots).

        Returns
        -------
        PIL.Image.Image
            Image recadrée en mode RGB.
        """
        angle = math.radians(self.rotation)
        cos_a = math.cos(angle)
        sin_a = math.sin(angle)

        scale = scale_override if scale_override is not None else self.scale
        total_scale = base_scale * scale
        if total_scale <= 0:
            total_scale = 1e-6

        canvas_cx = canvas_w / 2 + offset_x
        canvas_cy = canvas_h / 2 + offset_y
        orig_cx = self.orig_w / 2
        orig_cy = self.orig_h / 2

        ax_cx = total_scale * (cos_a * orig_cx - sin_a * orig_cy)
        ay_cy = total_scale * (sin_a * orig_cx + cos_a * orig_cy)
        tx = canvas_cx - ax_cx
        ty = canvas_cy - ay_cy

        sx = canvas_w / target_w_px
        sy = canvas_h / target_h_px

        inv_scale = 1.0 / total_scale

        a = inv_scale * cos_a * sx
        b = inv_scale * sin_a * sy
        d = inv_scale * -sin_a * sx
        e_m = inv_scale * cos_a * sy

        inv_tx = inv_scale * (cos_a * tx + sin_a * ty)
        inv_ty = inv_scale * (-sin_a * tx + cos_a * ty)
        c = -inv_tx
        f = -inv_ty

        pil_crop = self.current_pil_image.transform(
            (target_w_px, target_h_px),
            Image.Transform.AFFINE,
            (a, b, c, d, e_m, f),
            resample=Image.Resampling.BICUBIC,
            fillcolor=(255, 255, 255, 0),
        )

        if self.is_bw:
            pil_crop = pil_crop.convert("L")

        if pil_crop.mode == "RGBA":
            # Érosion du canal alpha (suppression des franges résiduelles)
            if getattr(self, 'rembg_erosion_radius', 0) > 0:
                pil_crop = _erode_alpha(pil_crop, self.rembg_erosion_radius)
            if getattr(self, 'rembg_bg_white', True):
                bg = Image.new("RGBA", pil_crop.size, (255, 255, 255, 255))
            else:
                orig_for_blur = self._rembg_original if self._rembg_original is not None else None
                if orig_for_blur is not None:
                    orig_crop = orig_for_blur.convert("RGB").transform(
                        (target_w_px, target_h_px),
                        Image.Transform.AFFINE,
                        (a, b, c, d, e_m, f),
                        resample=Image.Resampling.BICUBIC,
                        fillcolor=(255, 255, 255),
                    )
                    blurred_rgb = orig_crop.filter(ImageFilter.GaussianBlur(radius=64))
                else:
                    white = Image.new("RGBA", pil_crop.size, (255, 255, 255, 255))
                    blurred_rgb = Image.alpha_composite(white, pil_crop).convert("RGB").filter(ImageFilter.GaussianBlur(radius=64))
                bg = blurred_rgb.convert("RGBA")
            pil_crop = Image.alpha_composite(bg, pil_crop).convert("RGB")
        else:
            pil_crop = pil_crop.convert("RGB")

        return pil_crop

    def _compute_fit_in(self, target_w_px, target_h_px):
        """
        Calcule l'image entière redimensionnée pour tenir dans le format
        cible, avec des bords blancs sur les 2 côtés les plus courts.

        Contrairement à `_compute_crop` (mode crop / remplissage), cette
        méthode utilise un scale ``min`` pour que l'image entière soit
        visible. La rotation est toujours 0 (ignorée).

        Parameters
        ----------
        target_w_px : int
            Largeur de l'image de sortie en pixels.
        target_h_px : int
            Hauteur de l'image de sortie en pixels.

        Returns
        -------
        PIL.Image.Image
            Image redimensionnée collée sur fond blanc RGB.
        """
        img = self.current_pil_image
        if img.mode == "RGBA":
            # Érosion du canal alpha (suppression des franges résiduelles)
            if getattr(self, 'rembg_erosion_radius', 0) > 0:
                img = _erode_alpha(img.copy(), self.rembg_erosion_radius)
            if getattr(self, 'rembg_bg_white', True):
                bg = Image.new("RGBA", img.size, (255, 255, 255, 255))
            else:
                orig_for_blur = self._rembg_original if self._rembg_original is not None else None
                if orig_for_blur is not None:
                    blurred_rgb = orig_for_blur.convert("RGB").filter(ImageFilter.GaussianBlur(radius=64))
                else:
                    white = Image.new("RGBA", img.size, (255, 255, 255, 255))
                    blurred_rgb = Image.alpha_composite(white, img).convert("RGB").filter(ImageFilter.GaussianBlur(radius=64))
                bg = blurred_rgb.convert("RGBA")
            img = Image.alpha_composite(bg, img).convert("RGB")
        else:
            img = img.convert("RGB")
        fit_scale = min(target_w_px / self.orig_w, target_h_px / self.orig_h)
        new_w = max(1, int(round(self.orig_w * fit_scale)))
        new_h = max(1, int(round(self.orig_h * fit_scale)))
        resized = img.resize((new_w, new_h), Image.Resampling.BICUBIC)
        result = Image.new("RGB", (target_w_px, target_h_px), "white")
        x_offset = (target_w_px - new_w) // 2
        y_offset = (target_h_px - new_h) // 2
        result.paste(resized, (x_offset, y_offset))
        if self.is_bw:
            result = result.convert("L").convert("RGB")
        return result

    # ================================================================ #
    #                    CONSTRUCTION DES PLANCHES                     #
    # ================================================================ #

    def is_two_in_one_enabled(self):
        """
        Indique si le mode « 2 en 1 » est actif pour le format courant.

        Returns
        -------
        bool
            True si le switch « 2 en 1 » est coché ET que le format
            courant est compatible (10x15, 13x18 ou 15x20).
        """
        return bool(self.two_in_one_switch.value) and any(
            fmt in self.current_format_label for fmt in ["10x15", "13x18", "15x20"]
        )

    def _force_portrait(self, image):
        """
        Tourne l'image de 90° (sens antihoraire) si elle est en paysage.

        Utilisé avant d'assembler les panneaux 2-en-1 pour s'assurer que
        chaque vignette est en orientation portrait, quel que soit le sens
        de l'image source.

        Parameters
        ----------
        image : PIL.Image.Image
            Image à normaliser.

        Returns
        -------
        PIL.Image.Image
            Image en orientation portrait (height ≥ width).
        """
        if image.width > image.height:
            return image.rotate(90, expand=True)
        return image

    def _build_two_in_one_image(self, first_image, target_w_px, target_h_px):
        """
        Assemble une planche « 2 en 1 » en divisant le côté le plus long
        du format en deux panneaux égaux.

        Logique de découpage
        ---------------------
        Si target_w_px ≥ target_h_px (format paysage) : les deux copies
        sont posées côte à côte, chacune sur la moitié de la largeur.
        Sinon (format portrait) : les deux copies sont empilées, chacune
        sur la moitié de la hauteur.

        Chaque panneau utilise `ImageOps.fit` (recadrage centré) pour
        s'ajuster exactement aux dimensions du demi-format.

        Parameters
        ----------
        first_image : PIL.Image.Image
            Image recadrée représentant un exemplaire (produit par
            `_compute_crop` / `_compute_fit_in`).
        target_w_px, target_h_px : int
            Dimensions totales de la planche finale en pixels.

        Returns
        -------
        PIL.Image.Image
            Planche 2-en-1 en mode RGB aux dimensions (target_w_px, target_h_px).
        """
        split_on_width = target_w_px >= target_h_px

        if split_on_width:
            panel_w = target_w_px // 2
            panel_h = target_h_px
            first_pos = (0, 0)
            second_pos = (panel_w, 0)
        else:
            panel_w = target_w_px
            panel_h = target_h_px // 2
            first_pos = (0, 0)
            second_pos = (0, panel_h)

        first_image = self._force_portrait(first_image.convert("RGB"))
        first_panel = ImageOps.fit(first_image, (panel_w, panel_h), method=Image.Resampling.BICUBIC)

        second_panel = first_panel.copy()

        composed = Image.new("RGB", (target_w_px, target_h_px), "white")
        composed.paste(first_panel, first_pos)
        composed.paste(second_panel, second_pos)
        return composed

    def _build_two_in_one_10x15_to_13x15(self, first_image):
        """
        Cas particulier 2-en-1 pour le format 10x15 avec bord 13x15.

        Composition :
          - Deux panneaux de 76×102 mm (moitié de la largeur 10x15 arrondie)
            assemblés côte à côte sur une base de 152×102 mm.
          - La base est ensuite étendue à 152×127 mm avec du blanc en bas
            pour correspondre au format 13x15 (127 mm de hauteur).

        Parameters
        ----------
        first_image : PIL.Image.Image
            Image recadrée 10x15 (un exemplaire).

        Returns
        -------
        PIL.Image.Image
            Planche 13x15 en mode RGB avec les deux copies en haut et la
            marge blanche en bas.
        """
        panel_w = mm_to_pixels(76)
        panel_h = mm_to_pixels(102)
        base_w = mm_to_pixels(152)
        base_h = mm_to_pixels(102)
        final_h = mm_to_pixels(127)

        first_image = self._force_portrait(first_image.convert("RGB"))
        panel = ImageOps.fit(first_image, (panel_w, panel_h), method=Image.Resampling.BICUBIC)

        base = Image.new("RGB", (base_w, base_h), "white")
        base.paste(panel, (0, 0))
        base.paste(panel, (panel_w, 0))

        framed = Image.new("RGB", (base_w, final_h), "white")
        framed.paste(base, (0, 0))
        return framed

    def _adaptive_enhance(self, img):
        """
        Améliore automatiquement les images sous-exposées ou ternes.

        Stratégie
        ---------
        1. Conversion en YCbCr pour travailler uniquement sur la luminance Y.
        2. Calcul de la luminance moyenne (`mean_y`).
        3. **Si l'image est déjà bien exposée** (mean_y ≥ 148) : seule la
           saturation est boostée de +32 % (ImageEnhance.Color × 1.32).
        4. **Sinon** :
           a. Correction gamma : exposant calculé pour ramener mean_y vers
              148 sans jamais dépasser +42 niveaux (limité à 0.60–0.95).
           b. Léger étirement des contrastes (percentiles 0.5 % / 99.5 %).
           c. Saturation boostée de +42 % (ImageEnhance.Color × 1.42).

        Note : cette méthode n'est plus exposée directement dans l'UI mais
        reste accessible pour compatibilité avec d'anciens snapshots.

        Parameters
        ----------
        img : PIL.Image.Image
            Image RGB à améliorer.

        Returns
        -------
        PIL.Image.Image
            Image RGB améliorée.
        """
        ycbcr = img.convert("YCbCr")
        y, cb, cr = ycbcr.split()
        y_arr = np.array(y, dtype=np.float32)
        mean_y = y_arr.mean()

        # Saturation toujours boostée, correction luminosité uniquement si image sombre
        if mean_y >= 148:
            return ImageEnhance.Color(img).enhance(1.32)

        # Correction gamma : ramène la moyenne vers 148 sans dépasser +42 unités
        target_y = min(148.0, mean_y + 42.0)
        gamma = math.log(target_y / 255.0) / math.log(max(mean_y, 1.0) / 255.0)
        gamma = max(0.60, min(0.95, gamma))  # Bornes de sécurité

        y_enhanced = np.power(y_arr / 255.0, gamma) * 255.0

        # Léger étirement des contrastes (coupe 0.5 % à chaque extrémité)
        p_low = np.percentile(y_enhanced, 0.5)
        p_high = np.percentile(y_enhanced, 99.5)
        if p_high > p_low:
            y_enhanced = (y_enhanced - p_low) * 255.0 / (p_high - p_low)
        y_enhanced = np.clip(y_enhanced, 0, 255).astype(np.uint8)

        y_new = Image.fromarray(y_enhanced, "L")
        result = Image.merge("YCbCr", (y_new, cb, cr)).convert("RGB")
        return ImageEnhance.Color(result).enhance(1.42)

    def _apply_adjustments(self, img):
        """
        Applique les réglages d'exposition, contraste et saturation.

        Les trois curseurs sont appliqués successivement dans l'ordre
        exposition → contraste → saturation.

        Exposition
            Implémentée via une LUT gamma-like (table de correspondance 256
            valeurs) : factor = 2^(exposure/100). +100 ≙ ×2 lumière,
            -100 ≙ ÷2 lumière. Application via numpy pour la performance.
        Contraste
            `ImageEnhance.Contrast(img).enhance(1.0 + contrast/100)` :
            0 = neutre, +20 = 1.2×, -20 = 0.8×.
        Saturation
            `ImageEnhance.Color(img).enhance(max(0, 1.0 + saturation/100))` :
            0 = image désaturée (gris), 100 = saturation doublée.

        Parameters
        ----------
        img : PIL.Image.Image
            Image en mode RGB ou convertible en RGB.

        Returns
        -------
        PIL.Image.Image
            Image RGB ajustée.
        """
        img = img.convert("RGB")
        if self.exposure != 0:
            # Exposition : gamma inverse (+ = plus clair, - = plus sombre)
            # +100 multiplie la lumière x2, -100 la divise par 2
            factor = 2 ** (self.exposure / 100.0)
            lut = np.clip(np.arange(256, dtype=np.float32) * factor, 0, 255).astype(np.uint8)
            arr = np.array(img, dtype=np.uint8)
            img = Image.fromarray(lut[arr], "RGB")
        if self.contrast != 0:
            img = ImageEnhance.Contrast(img).enhance(1.0 + self.contrast / 100.0)
        if self.saturation != 0:
            img = ImageEnhance.Color(img).enhance(max(0.0, 1.0 + self.saturation / 100.0))
        if self.hue != 0:
            img = self._apply_hue(img, self.hue)
        if self.white_balance != 0:
            img = self._apply_white_balance(img, self.white_balance)
        return img

    def _apply_shadows(self, img, value):
        """Ajuste les ombres (similaire au slider Shadows de Camera Raw/Lightroom).
        value : -100 … +100. Positif = éclaircit les ombres, négatif = les assombrit.
        La courbe est nulle aux noirs purs (v=0), maximale vers v=96 et nulle dès les
        demi-tons (v≥192), ce qui préserve les noirs et les hautes lumières."""
        if value == 0:
            return img
        s = value / 100.0
        v_arr = np.arange(256, dtype=np.float32)
        # Courbe sinusoïdale : sin(π·v/192) — zéro en 0, pic à 96, zéro à 192+
        t = v_arr / 192.0
        weight = np.where(t <= 1.0, np.sin(np.pi * t), 0.0)
        strength = 60  # amplitude max en niveaux d'intensité
        lut = np.clip(v_arr + s * strength * weight, 0, 255).astype(np.uint8)
        img_rgb = img.convert("RGB")
        img_arr = np.array(img_rgb, dtype=np.uint8)
        return Image.fromarray(lut[img_arr], "RGB")

    def _apply_highlights(self, img, value):
        """Ajuste les hautes lumières (miroir des ombres).
        value : -100 … +100. Positif = éclaircit les hautes lumières, négatif = les assombrit.
        Courbe nulle sous v=64, pic vers v=192, nulle aux blancs purs (v=255)."""
        if value == 0:
            return img
        s = value / 100.0
        v_arr = np.arange(256, dtype=np.float32)
        # Courbe : sin(π·(v-64)/192) pour v dans [64, 255], zéro ailleurs
        t = (v_arr - 64.0) / 192.0
        weight = np.where((t >= 0.0) & (t <= 1.0), np.sin(np.pi * t), 0.0)
        strength = 60
        lut = np.clip(v_arr + s * strength * weight, 0, 255).astype(np.uint8)
        img_rgb = img.convert("RGB")
        img_arr = np.array(img_rgb, dtype=np.uint8)
        return Image.fromarray(lut[img_arr], "RGB")

    def _apply_hue(self, img, value):
        """Teinte : décale vers vert (négatif) ou magenta (positif), comme Lightroom.

        value dans [-180, +180] ; effet max ±30 % sur R/G/B via LUT.
        """
        if value == 0:
            return img
        t = value / 180.0          # [-1, +1]
        strength = abs(t) * 0.30   # force max 30 %
        lut = np.arange(256, dtype=np.float32)
        if t > 0:
            # Magenta : boost R et B, atténuer G
            lut_r = np.clip(lut * (1.0 + strength),        0, 255).astype(np.uint8)
            lut_g = np.clip(lut * (1.0 - strength),        0, 255).astype(np.uint8)
            lut_b = np.clip(lut * (1.0 + strength * 0.7),  0, 255).astype(np.uint8)
        else:
            # Vert : boost G, atténuer R et B
            lut_r = np.clip(lut * (1.0 - strength),        0, 255).astype(np.uint8)
            lut_g = np.clip(lut * (1.0 + strength),        0, 255).astype(np.uint8)
            lut_b = np.clip(lut * (1.0 - strength * 0.7),  0, 255).astype(np.uint8)
        arr = np.array(img.convert("RGB"), dtype=np.uint8)
        result = np.stack([
            lut_r[arr[:, :, 0]],
            lut_g[arr[:, :, 1]],
            lut_b[arr[:, :, 2]],
        ], axis=2)
        return Image.fromarray(result, "RGB")

    def _apply_white_balance(self, img, value):
        """Balance des blancs : -100 = froid (bleu), +100 = chaud (jaune/orange).\n\n        Applique une correction per-canal (R, G, B) proportionnelle à ``value``.
        """
        if value == 0:
            return img
        strength = abs(value) / 100.0 * 0.20  # max ±20 % par canal
        arr = np.array(img.convert("RGB"), dtype=np.float32)
        if value > 0:  # chaud : +R, léger +G, -B
            arr[..., 0] = np.clip(arr[..., 0] * (1.0 + strength), 0, 255)
            arr[..., 1] = np.clip(arr[..., 1] * (1.0 + strength * 0.2), 0, 255)
            arr[..., 2] = np.clip(arr[..., 2] * (1.0 - strength), 0, 255)
        else:          # froid : -R, G neutre, +B
            arr[..., 0] = np.clip(arr[..., 0] * (1.0 - strength), 0, 255)
            arr[..., 2] = np.clip(arr[..., 2] * (1.0 + strength), 0, 255)
        return Image.fromarray(arr.astype(np.uint8), "RGB")

    def _render_histogram(self, preview_img):
        """Génère un histogramme RGB et met à jour ``self.histogram_image``."""
        W, H = RIGHT_COL_WIDTH, HISTOGRAM_HEIGHT
        arr = np.array(preview_img.convert("RGB"), dtype=np.uint8)
        arr = arr[::4, ::4]  # sous-échantillonnage pour la vitesse
        canvas = np.full((H, W, 3), (30, 30, 38), dtype=np.int32)
        ch_colors = np.array([[80, 20, 20], [20, 70, 20], [20, 20, 80]], dtype=np.int32)
        row_indices = np.arange(H)[:, np.newaxis]  # (H, 1)
        for ch_idx in range(3):
            counts, _ = np.histogram(arr[..., ch_idx], bins=W, range=(0, 256))
            max_c = max(int(counts.max()), 1)
            heights = np.clip((counts * H // max_c), 0, H).astype(int)
            threshold = H - heights[np.newaxis, :]  # (1, W)
            mask = row_indices >= threshold          # (H, W)
            canvas += mask[:, :, np.newaxis] * ch_colors[ch_idx]
        canvas = np.clip(canvas, 0, 255).astype(np.uint8)
        hist_img = Image.fromarray(canvas, "RGB")
        buf = io.BytesIO()
        hist_img.save(buf, format="PNG")
        self.histogram_image.src = "data:image/png;base64," + base64.b64encode(buf.getvalue()).decode()
        try:
            self.histogram_image.update()
        except Exception:
            pass

    def _render_preview(self):
        """
        Génère et affiche la prévisualisation dans le canvas Flet.

        Pipeline de rendu
        -----------------
        1. Copie et aplatissement de l'alpha de `current_pil_image`.
        2. Redimensionnement rapide (BILINEAR) à `display_w` × `display_h`
           pour limiter la charge CPU lors des interactions.
        3. Conversion N&B si `is_bw` est actif.
        4. Application de `_apply_adjustments` (expo, contraste, saturation).
        5. Application des courbes ombres et hautes lumières si non nulles.
        6. Netteté via deux passes d'UnsharpMask si `is_sharpen` est actif.
        7. Conversion sRGB via `convert_to_srgb` (alignement colorimétrique
           avec l'export final).
        8. Sauvegarde JPEG qualité 88 dans un fichier temporaire nommé
           `_rc_<compteur>.jpg` dans `_preview_tmp_dir`.
           Un nom unique est nécessaire pour invalider le cache image de
           Flutter/Flet (le chemin doit changer à chaque mise à jour).
        9. Suppression du fichier précédent pour ne garder qu'un seul
           fichier sur disque à tout instant.

        Cette méthode est appelée à chaque modification d'un filtre ou
        lors du chargement d'une nouvelle image. Elle NE rafraîchit PAS
        `self.page` ; l'appelant le fait si nécessaire.
        """
        if not hasattr(self, 'current_pil_image') or self.current_pil_image is None:
            return
        if not hasattr(self, 'display_w'):
            return
        # Réduire à la taille d'affichage EN PREMIER — toutes les opérations
        # suivantes (érosion, composite, filtres) travaillent sur le petit canvas.
        pw = max(1, int(self.display_w))
        ph = max(1, int(self.display_h))
        preview = self.current_pil_image.resize((pw, ph), Image.Resampling.BILINEAR)
        if preview.mode == "RGBA":
            # Clé de cache : image source + taille d'affichage + format + paramètres de composition
            _cache_key = (
                id(self.current_pil_image), pw, ph,
                round(self.canvas_w), self.canvas_is_portrait,
                getattr(self, 'rembg_erosion_radius', 0),
                getattr(self, 'rembg_bg_white', True),
            )
            if self._rembg_composite_cache is not None and self._rembg_composite_cache[0] == _cache_key:
                # Cache valide : réutiliser le composite sans recalculer
                preview = self._rembg_composite_cache[1].copy()
            else:
                # Érosion au format réduit — beaucoup plus rapide qu'à pleine résolution.
                # Le rayon est mis à l'échelle pour que la preview corresponde au résultat final.
                # L'échelle correcte est canvas_w / target_w_px (affichage → export),
                # et non display_w / orig_w (qui sous-estime fortement pour les petits formats).
                if getattr(self, 'rembg_erosion_radius', 0) > 0:
                    fmt_w_mm, fmt_h_mm = self.current_format
                    if self.canvas_is_portrait:
                        target_w_px_preview = round(fmt_w_mm / 25.4 * DPI)
                    else:
                        target_w_px_preview = round(fmt_h_mm / 25.4 * DPI)
                    scale = self.canvas_w / max(1, target_w_px_preview)
                    scaled_radius = max(1, round(self.rembg_erosion_radius * scale))
                    preview = _erode_alpha(preview, scaled_radius)
                if getattr(self, 'rembg_bg_white', True):
                    bg = Image.new("RGBA", preview.size, (255, 255, 255, 255))
                else:
                    # Use original (opaque) image as blur source to avoid black bleed
                    # from transparent pixels (alpha=0 → black in RGBA→RGB conversion)
                    blur_src = self._rembg_original if self._rembg_original is not None else None
                    if blur_src is not None:
                        blurred_rgb = blur_src.convert("RGB").resize((pw, ph), Image.Resampling.BILINEAR).filter(ImageFilter.GaussianBlur(radius=30))
                    else:
                        white = Image.new("RGBA", preview.size, (255, 255, 255, 255))
                        blurred_rgb = Image.alpha_composite(white, preview).convert("RGB").filter(ImageFilter.GaussianBlur(radius=30))
                    bg = blurred_rgb.convert("RGBA")
                preview = Image.alpha_composite(bg, preview).convert("RGB")
                self._rembg_composite_cache = (_cache_key, preview.copy())
        else:
            preview = preview.convert("RGB")
        # Noir et blanc
        if self.is_bw:
            preview = ImageOps.grayscale(preview).convert("RGB")
        # Contraste, saturation, exposition
        preview = self._apply_adjustments(preview)
        # Ombres
        if self.shadows != 0:
            preview = self._apply_shadows(preview, self.shadows)
        # Hautes lumières
        if self.highlights != 0:
            preview = self._apply_highlights(preview, self.highlights)
        # Netteté
        if self.is_sharpen:
            preview = preview.filter(ImageFilter.UnsharpMask(radius=4, percent=13, threshold=0))
            preview = preview.filter(ImageFilter.UnsharpMask(radius=2, percent=21, threshold=0))
        # Conversion sRGB : aligner le preview sur l'image enregistrée
        preview = convert_to_srgb(preview, getattr(self, 'icc_profile', None))
        # Encoder en mémoire — élimine l'I/O disque, invalide le cache Flutter via données uniques
        _buf = io.BytesIO()
        preview.save(_buf, format="JPEG", quality=70)
        self.image_display.src = "data:image/jpeg;base64," + base64.b64encode(_buf.getvalue()).decode()
        self.image_display.update()
        self._render_histogram(preview)

    # ================================================================ #
    #                  NAVIGATION (PAN, ZOOM, ROTATION)                #
    # ================================================================ #

    def on_pan_update(self, e: ft.DragUpdateEvent):
        """
        Gestionnaire de glisser (drag) sur le canvas.

        Les deltas de position sont accumulés dans `offset_x` / `offset_y`
        à chaque événement (potentiellement 200+ Hz selon le système).
        Le rendu vers Flutter (`_clamp_offsets` + `_update_transform`) est
        limité à 60 fps via `_last_pan_render` pour éviter de saturer la
        file de messages Flet sur les machines lentes.

        Parameters
        ----------
        e : ft.DragUpdateEvent
            Événement Flet ; `e.local_delta` contient le déplacement
            en pixels depuis le dernier événement.
        """
        self.offset_x += e.local_delta.x
        self.offset_y += e.local_delta.y
        # Throttle : on limite les appels à _update_transform à 60 fps max.
        # Les deltas sont toujours accumulés ; seul l'envoi à Flutter est différé.
        now = time.monotonic()
        if now - self._last_pan_render < 1 / 30:
            return
        self._last_pan_render = now
        self._clamp_offsets()
        self._update_transform()

    def on_pan_end(self, e: ft.DragEndEvent):
        """Rafraîchit la prévisualisation et l'histogramme après la fin du pan."""
        self._clamp_offsets()
        self._render_preview()
        self.page.update()

    def on_scroll(self, e: ft.ScrollEvent):
        """Zoom molette : zoom centré sur le curseur."""
        now = time.monotonic()
        if now - self._last_zoom_render < 1 / 30:
            # Accumuler quand même le delta pour ne pas perdre de ticks
            delta = e.scroll_delta.y
            zoom_factor = 1 - delta / 5000
            self.scale = max(1.0, min(10.0, self.scale * zoom_factor))
            return
        self._last_zoom_render = now
        delta = e.scroll_delta.y
        zoom_factor = 1 - delta / 5000
        old_scale = self.scale
        self.scale = max(1.0, min(10.0, self.scale * zoom_factor))
        if old_scale != self.scale:
            ratio = self.scale / old_scale
            self.offset_x *= ratio
            self.offset_y *= ratio
            self.zoom_slider.value = self.scale
            self.zoom_slider.label = f"{self.scale:.2f}×"
            self.zoom_slider.update()
        self._clamp_offsets()
        self._update_transform()

    def on_rotation_update(self, e):
        """
        Gestionnaire du slider de rotation (pendant le glissement).

        Met à jour `self.rotation` et le label du slider immédiatement
        (opération légère, synchrone). Le rendu affine (`_clamp_offsets`
        + `_update_transform`) est limité à 60 fps via `_last_rotation_render`
        pour éviter de saturer la file de messages Flet sur les machines
        lentes. La prévisualisation PIL n'est pas re-générée ici.

        Parameters
        ----------
        e : ft.ControlEvent
            Événement Flet du slider ; `e.control.value` contient la
            valeur numérique courante en degrés.
        """
        self.rotation = e.control.value
        e.control.label = f"{self.rotation:.2f}°"
        e.control.update()
        now = time.monotonic()
        if now - self._last_rotation_render < 1 / 30:
            return
        self._last_rotation_render = now
        self._clamp_offsets()
        self._update_transform()

    def on_rotation_end(self, e):
        """Rafraîchit la prévisualisation et l'histogramme après la fin de la rotation."""
        self._render_preview()
        self.page.update()

    def on_zoom_update(self, e):
        """
        Gestionnaire du slider de zoom (pendant le glissement).

        Met à jour `self.scale`, corrige les offsets proportionnellement
        et rafraîchit le label immédiatement. Le rendu affine est limité
        à 60 fps via `_last_zoom_render` pour éviter de saturer la file
        de messages Flet sur les machines lentes.

        Parameters
        ----------
        e : ft.ControlEvent
            Événement Flet du slider ; `e.control.value` contient le
            facteur de zoom cible.
        """
        new_scale = e.control.value
        old_scale = self.scale
        self.scale = new_scale
        if old_scale != self.scale:
            ratio = self.scale / old_scale
            self.offset_x *= ratio
            self.offset_y *= ratio
        e.control.label = f"{self.scale:.2f}×"
        e.control.update()
        now = time.monotonic()
        if now - self._last_zoom_render < 1 / 30:
            return
        self._last_zoom_render = now
        self._clamp_offsets()
        self._update_transform()

    def on_zoom_end(self, e):
        """Rafraîchit la prévisualisation et l'histogramme après la fin du zoom."""
        self._clamp_offsets()
        self._render_preview()
        self.page.update()

    def reset_rotation(self, e):
        """
        Remet la rotation à zéro (0°).

        Remet à jour le slider, l'état interne, la transformation affine
        et rafraîchit la page.

        Parameters
        ----------
        e : ft.ControlEvent
            Événement Flet du bouton « 0° » (non utilisé directement).
        """
        self.rotation = 0.0
        self.rotation_slider.value = self.rotation
        self.rotation_slider.label = f"{self.rotation:.2f}°"
        self.rotation_slider.update()
        self._clamp_offsets()
        self._update_transform()

    def reset_zoom(self, e):
        """Remet le zoom à 1× par double-clic sur le slider."""
        self.scale = 1.0
        self.offset_x = 0.0
        self.offset_y = 0.0
        self.zoom_slider.value = 1.0
        self.zoom_slider.label = "1.00×"
        self.zoom_slider.update()
        self._clamp_offsets()
        self._update_transform()

    def _reset_slider(self, slider, attr, default_val, label_str):
        """Remet un slider de réglage à sa valeur par défaut et redéclenche le rendu."""
        setattr(self, attr, default_val)
        slider.value = default_val
        slider.label = label_str
        slider.update()
        self._render_preview()
        self.page.update()

    # ================================================================ #
    #                        TOGGLES & SWITCHES                        #
    # ================================================================ #

    def on_grid_toggle(self, e):
        """Active ou désactive la grille des tiers fixée au canevas."""
        self.show_grid = bool(e.control.value)
        for line in self._grid_lines:
            line.visible = self.show_grid
        self.page.update()

    def on_bw_toggle(self, e):
        """
        Active ou désactive le mode noir et blanc.

        Met à jour `is_bw` puis regénère la prévisualisation.

        Parameters
        ----------
        e : ft.ControlEvent
            Événement du Switch « Noir et blanc » ; `e.control.value` = bool.
        """
        self.is_bw = e.control.value
        self._render_preview()
        self.page.update()

    def on_fit_in_toggle(self, e):
        """
        Active ou désactive le mode Fit-in.

        En mode Fit-in, l'image entière tient dans le format choisi avec
        des bords blancs sur 2 côtés. La rotation est forcée à 0.
        Le pan et le zoom sont désactivés (l'image est trop petite pour
        déborder du canevas).

        Parameters
        ----------
        e : ft.ControlEvent
            Événement du Switch « Fit-in » ; `e.control.value` = bool.
        """
        self.is_fit_in = bool(e.control.value)
        if self.is_fit_in:
            self.rotation = 0.0
            self.rotation_slider.value = 0.0
            self.rotation_slider.label = "0.00°"
            self.rotation_slider.update()
        if self.image_paths:
            self.load_image(preserve_orientation=True)
        self.page.update()

    def on_sharpen_toggle(self, e):
        """
        Active ou désactive le filtre de netteté (UnsharpMask).

        Le filtre est appliqué en deux passes (radius 4 puis radius 2) à
        la fois sur la prévisualisation et lors de l'export final.

        Parameters
        ----------
        e : ft.ControlEvent
            Événement du Switch « Netteté ».
        """
        self.is_sharpen = bool(e.control.value)
        self._render_preview()
        self.page.update()

    def on_rembg_model_toggle(self, e):
        """Bascule entre portrait et général."""
        self.rembg_human_seg = not self.rembg_human_seg
        # Invalider toutes les sessions pour forcer le rechargement
        self._rembg_session[0] = None
        self._rembg_session_u2net[0] = None
        if self.rembg_human_seg:
            self._rembg_model_label.value = "Humain"
            self.rembg_model_btn.bgcolor = VIOLET
        else:
            self._rembg_model_label.value = "Général"
            self.rembg_model_btn.bgcolor = BLUE
        self.rembg_model_btn.update()

    def on_rembg_precise_toggle(self, e):
        """Bascule entre mode rapide (u2net) et mode précis (birefnet)."""
        self.rembg_precise = not self.rembg_precise
        if self.rembg_precise:
            self._rembg_precise_label.value = "Précis"
            self.rembg_precise_btn.bgcolor = VIOLET
        else:
            self._rembg_precise_label.value = "Rapide"
            self.rembg_precise_btn.bgcolor = BLUE
        self.rembg_precise_btn.update()

    def on_rembg_erosion_change(self, e):
        """Met à jour le rayon d'érosion pendant le drag (pas de rendu)."""
        self.rembg_erosion_radius = int(e.control.value)

    def on_rembg_erosion_end(self, e):
        """Regénère la preview au relâchement du slider d'érosion."""
        self.rembg_erosion_radius = int(e.control.value)
        self._render_preview()
        self.page.update()

    def on_rembg_bg_toggle(self, e):
        """Bascule fond blanc (GREY_200) ↔ fond flou (BLUE)."""
        self.rembg_bg_white = not self.rembg_bg_white
        if self.rembg_bg_white:
            self._rembg_bg_label.value = "Fond blanc"
            self._rembg_bg_label.color = DARK
            self.rembg_bg_btn.bgcolor = ft.Colors.GREY_200
        else:
            self._rembg_bg_label.value = "Fond flou"
            self._rembg_bg_label.color = DARK
            self.rembg_bg_btn.bgcolor = BLUE
        self.rembg_bg_btn.update()
        self._render_preview()
        self.page.update()

    async def on_rembg(self, e):
        """
        Bouton toggle de suppression du fond par IA (rembg).

        Comportement toggle
        -------------------
        * **Premier clic** (icône grise → violette) :
            Sauvegarde ``current_pil_image`` dans ``_rembg_original``, lance
            le traitement IA et remplace ``current_pil_image`` par le résultat
            RGBA. Le statut affiche ``[OK] Fond supprimé — recliquer pour
            restaurer``.
        * **Deuxième clic** (icône violette → grise) :
            Restaure ``_rembg_original`` dans ``current_pil_image`` sans
            relancer rembg. Rapide et réversible à tout moment.
        * Au chargement d'une nouvelle image, ``_rembg_original`` est remis
          à ``None`` et le bouton repasse en gris.

        Pipeline asynchrone
        -------------------
        Le calcul rembg (bloquant) est délégué à un thread pool via
        ``asyncio.to_thread(_do_rembg)``. Les mises à jour UI (``_render_preview``,
        ``page.update``) s'exécutent ensuite sur la boucle asyncio principale
        de Flet, garantissant un rafraîchissement immédiat sans avoir à
        utiliser des threads secondaires ou des callbacks explicites.

        Modèle IA
        ---------
        ``birefnet-portrait`` — modèle spécialisé sujets humains, téléchargé
        automatiquement dans ``~/.u2net/`` (~450 Mo) à la première utilisation.
        La session est mise en cache dans ``self._rembg_session[0]`` pour
        éviter de recharger le modèle à chaque clic.

        Mode précis
        -----------
        Si ``self.rembg_precise`` est ``True`` (switch « Précis » activé),
        ``alpha_matting=True`` est passé à ``rembg_remove`` avec les
        seuils ``foreground=240``, ``background=10``, ``erode_size=10``.
        Voir ``on_rembg_precise_toggle`` pour la description complète.

        Fond de remplacement
        --------------------
        ``current_pil_image`` reste en mode RGBA après traitement. L'aplatissement
        sur fond blanc (255,255,255) ou gris clair (220,220,220) est
        effectué à la volée dans ``_render_preview`` et à l'export, selon
        ``self.rembg_bg_white`` (switch « Fond blanc »).

        Parameters
        ----------
        e : ft.ControlEvent
            Événement du bouton icône (``on_click``).
        """
        if not REMBG_AVAILABLE:
            self.status_text.value = "[ERREUR] rembg non installé — pip install rembg onnxruntime"
            self.page.update()
            return
        if self.current_pil_image is None:
            self.status_text.value = "Aucune image chargée."
            self.page.update()
            return

        # Deuxième clic : restaurer l'image originale
        if self.rembg_btn.selected and self._rembg_original is not None:
            self.current_pil_image = self._rembg_original
            self._rembg_original = None
            self.rembg_btn.selected = False
            self.status_text.value = "Fond restauré"
            self._render_preview()
            self.page.update()
            return

        self.rembg_btn.disabled = True
        self.status_text.value = "Suppression du fond en cours…"
        self.page.update()

        def _do_rembg():
            from rembg import remove as _rembg_remove, new_session as _rembg_new_session
            if self.rembg_precise:
                # Mode précis : birefnet
                if self._rembg_session[0] is None:
                    model_name = "birefnet-portrait" if self.rembg_human_seg else "birefnet-general"
                    self._rembg_session[0] = _rembg_new_session(model_name)
                sess = self._rembg_session[0]
            else:
                # Mode rapide : u2net
                if self._rembg_session_u2net[0] is None:
                    model_name = "u2net_human_seg" if self.rembg_human_seg else "u2net"
                    self._rembg_session_u2net[0] = _rembg_new_session(model_name)
                sess = self._rembg_session_u2net[0]
            with contextlib.redirect_stderr(io.StringIO()):
                result = _rembg_remove(self.current_pil_image.convert("RGB"), session=sess)
            return result.convert("RGBA")

        try:
            result = await asyncio.to_thread(_do_rembg)
            self._rembg_original = self.current_pil_image
            self.current_pil_image = result
            self.rembg_btn.selected = True
            self.status_text.value = "[OK] Fond supprimé — recliquer pour restaurer"
        except Exception as ex:
            self.status_text.value = f"[ERREUR] rembg : {ex}"
        finally:
            self.rembg_btn.disabled = False
            self._render_preview()
            self.page.update()

    def on_network_toggle(self, e):
        """
        Active ou désactive la sauvegarde des planches ID ×4 sur le réseau.

        Quand activé, les planches ID ×4 sont sauvegardées dans le dossier
        réseau `z2026` (NAS DiskStation) plutôt que dans le dossier source.
        Le chemin réseau est adapté automatiquement selon le système
        d'exploitation (Windows : UNC, macOS/Linux : point de montage).

        Parameters
        ----------
        e : ft.ControlEvent
            Événement du Switch « Sauver sur réseau ».
        """
        self.save_to_network = bool(e.control.value)

    def on_border_toggle_13x15(self, e):
        """
        Active / désactive l'ajout d'une bordure blanche pour passer du
        format 10x15 au format 13x15.

        Quand activé, la photo 10x15 est collée sur un fond blanc de
        127×152 mm (portrait) ou 152×127 mm (paysage).

        Parameters
        ----------
        e : ft.ControlEvent
            Événement du Switch « 13x15 ».
        """
        self.border_13x15 = bool(e.control.value)

    def on_border_toggle_20x24(self, e):
        """
        Active / désactive l'ajout d'une bordure blanche pour passer du
        format 18x24 au format 20x24.

        La largeur de l'image 18x24 est agrandie avec du blanc pour
        atteindre le ratio 203÷240 (20x24).

        Parameters
        ----------
        e : ft.ControlEvent
            Événement du Switch « 20x24 ».
        """
        self.border_20x24 = bool(e.control.value)

    def on_border_toggle_13x10(self, e):
        """
        Active / désactive l'ajout d'une bordure blanche pour passer du
        format 10x10 au format 13x10.

        Mutuellement exclusif avec le mode Polaroid : activer 13x10
        désactive automatiquement Polaroid.

        Parameters
        ----------
        e : ft.ControlEvent
            Événement du Switch « 13x10 ».
        """
        self.border_13x10 = bool(e.control.value)
        if self.border_13x10:
            self.border_polaroid = False
            self.border_switch_polaroid.value = False
            self.page.update()

    def on_border_toggle_polaroid(self, e):
        """
        Active / désactive le cadre Polaroid.

        Place la photo 10x10 centrée avec des marges blanches égales
        sur un fond 127×152 mm (format Polaroid classique).
        Mutuellement exclusif avec le mode 13x10.

        Parameters
        ----------
        e : ft.ControlEvent
            Événement du Switch « Polaroid ».
        """
        self.border_polaroid = bool(e.control.value)
        if self.border_polaroid:
            self.border_13x10 = False
            self.border_switch_13x10.value = False
            self.page.update()

    def on_border_toggle_id2(self, e):
        """
        Active / désactive la planche ID ×2 (deux photos d'identité
        sur un tirage 10x10).

        Mutuellement exclusif avec la planche ID ×4 : activer ID X2
        désactive automatiquement ID X4.

        Parameters
        ----------
        e : ft.ControlEvent
            Événement du Switch « ID X2 ».
        """
        self.border_id2 = bool(e.control.value)
        if self.border_id2:
            self.border_id4 = False
            self.border_switch_ID4.value = False
            self.page.update()

    def on_border_toggle_id4(self, e):
        """
        Active / désactive la planche ID ×4 (quatre photos d'identité
        sur un tirage 10x13, espacées de 5 mm).

        Mutuellement exclusif avec la planche ID ×2 : activer ID X4
        désactive automatiquement ID X2.

        Parameters
        ----------
        e : ft.ControlEvent
            Événement du Switch « ID X4 ».
        """
        self.border_id4 = bool(e.control.value)
        if self.border_id4:
            self.border_id2 = False
            self.border_switch_ID2.value = False
            self.page.update()

    # Label uniquement (pendant le glissement)
    def on_shadows_label(self, e):
        """
        Mise à jour du label du slider Ombres pendant le glissement.

        Met à jour `self.shadows` et le label affiché sur le slider
        sans regénérer la prévisualisation (pour la fluidité du drag).
        Le rendu n'est déclenché qu'au relâchement via `on_shadows_end`.

        Parameters
        ----------
        e : ft.ControlEvent
            Événement Flet du slider.
        """
        self.shadows = e.control.value
        e.control.label = str(int(self.shadows))
        e.control.update()

    # Rendu au relâchement
    def on_shadows_end(self, e):
        """
        Rendu complet de la prévisualisation au relâchement du slider Ombres.

        Parameters
        ----------
        e : ft.ControlEvent
            Événement de fin de glissement (`on_change_end`).
        """
        self.shadows = e.control.value
        self._render_preview()
        self.page.update()

    def on_highlights_label(self, e):
        """
        Mise à jour du label du slider Hautes Lumières pendant le glissement.

        Même logique que `on_shadows_label` : mise à jour visuelle seule,
        pas de rendu.

        Parameters
        ----------
        e : ft.ControlEvent
            Événement Flet du slider.
        """
        self.highlights = e.control.value
        e.control.label = str(int(self.highlights))
        e.control.update()

    def on_highlights_end(self, e):
        """
        Rendu complet de la prévisualisation au relâchement du slider
        Hautes Lumières.

        Parameters
        ----------
        e : ft.ControlEvent
            Événement de fin de glissement (`on_change_end`).
        """
        self.highlights = e.control.value
        self._render_preview()
        self.page.update()

    def on_contrast_label(self, e):
        """
        Mise à jour du label du slider Contraste pendant le glissement.

        Parameters
        ----------
        e : ft.ControlEvent
            Événement Flet du slider.
        """
        self.contrast = e.control.value
        e.control.label = str(int(self.contrast))
        e.control.update()

    def on_contrast_end(self, e):
        """
        Rendu complet de la prévisualisation au relâchement du slider Contraste.

        Parameters
        ----------
        e : ft.ControlEvent
            Événement de fin de glissement.
        """
        self.contrast = e.control.value
        self._render_preview()
        self.page.update()

    def on_saturation_label(self, e):
        """
        Mise à jour du label du slider Saturation pendant le glissement.

        Parameters
        ----------
        e : ft.ControlEvent
            Événement Flet du slider.
        """
        self.saturation = e.control.value
        e.control.label = str(int(self.saturation))
        e.control.update()

    def on_saturation_end(self, e):
        """
        Rendu complet de la prévisualisation au relâchement du slider Saturation.

        Parameters
        ----------
        e : ft.ControlEvent
            Événement de fin de glissement.
        """
        self.saturation = e.control.value
        self._render_preview()
        self.page.update()

    def on_exposure_label(self, e):
        """
        Mise à jour du label du slider Exposition pendant le glissement.

        Parameters
        ----------
        e : ft.ControlEvent
            Événement Flet du slider.
        """
        self.exposure = e.control.value
        e.control.label = str(int(self.exposure))
        e.control.update()

    def on_exposure_end(self, e):
        """
        Rendu complet de la prévisualisation au relâchement du slider Exposition.

        Parameters
        ----------
        e : ft.ControlEvent
            Événement de fin de glissement.
        """
        self.exposure = e.control.value
        self._render_preview()
        self.page.update()

    def on_hue_label(self, e):
        """Mise à jour du label du slider Teinte pendant le glissement."""
        self.hue = e.control.value
        e.control.label = str(int(self.hue))
        e.control.update()

    def on_hue_end(self, e):
        """Rendu complet au relâchement du slider Teinte."""
        self.hue = e.control.value
        self._render_preview()
        self.page.update()

    def on_wb_label(self, e):
        """Mise à jour du label du slider Balance des blancs pendant le glissement."""
        self.white_balance = e.control.value
        e.control.label = str(int(self.white_balance))
        e.control.update()

    def on_wb_end(self, e):
        """Rendu complet au relâchement du slider Balance des blancs."""
        self.white_balance = e.control.value
        self._render_preview()
        self.page.update()

    def reset_shadows(self, e):
        """
        Réinitialise simultanément les sliders Ombres et Hautes Lumières à 0.

        Remet à jour les valeurs internes, les labels affichés et les
        valeurs des widgets Flet, puis regénère la prévisualisation.

        Parameters
        ----------
        e : ft.ControlEvent
            Événement du bouton de réinitialisation (non utilisé directement).
        """
        self.shadows = 0.0
        self.shadows_slider.value = 0.0
        self.shadows_slider.label = "0"
        self.shadows_slider.update()
        self.highlights = 0.0
        self.highlights_slider.value = 0.0
        self.highlights_slider.label = "0"
        self.highlights_slider.update()
        self._render_preview()
        self.page.update()

    def reset_adjustments(self, e):
        """
        Réinitialise tous les réglages (exposition, contraste, saturation,
        ombres, hautes lumières) à leurs valeurs neutres.

        Met à jour les valeurs internes, les labels et les valeurs des
        widgets Flet, puis regénère la prévisualisation.

        Parameters
        ----------
        e : ft.ControlEvent
            Événement du bouton « Réinit. réglages » (non utilisé directement).
        """
        self.contrast = 0.0
        self.contrast_slider.value = 0.0
        self.contrast_slider.label = "0"
        self.contrast_slider.update()
        self.saturation = 0.0
        self.saturation_slider.value = 0.0
        self.saturation_slider.label = "0"
        self.saturation_slider.update()
        self.exposure = 0.0
        self.exposure_slider.value = 0.0
        self.exposure_slider.label = "0"
        self.exposure_slider.update()
        self.shadows = 0.0
        self.shadows_slider.value = 0.0
        self.shadows_slider.label = "0"
        self.shadows_slider.update()
        self.highlights = 0.0
        self.highlights_slider.value = 0.0
        self.highlights_slider.label = "0"
        self.highlights_slider.update()
        self.hue = 0.0
        self.hue_slider.value = 0.0
        self.hue_slider.label = "0"
        self.hue_slider.update()
        self.white_balance = 0.0
        self.white_balance_slider.value = 0.0
        self.white_balance_slider.label = "0"
        self.white_balance_slider.update()
        self._render_preview()
        self.page.update()

    def change_ratio(self, e=None):
        """
        Change le format d'impression actif et met à jour l'interface.

        Déclenché par le RadioGroup de sélection du format. Cette méthode :
          1. Met à jour `current_format` et `current_format_label`.
          2. Affiche / masque les switches de bordure et planches spéciales
             (13x15, 20x24, 13x10, Polaroid, ID X2, ID X4, réseau) selon
             le format choisi.
          3. Recalcule la taille du canevas.
          4. Recharge l'image courante en préservant l'orientation.

        Parameters
        ----------
        e : ft.ControlEvent or None
            Événement du RadioGroup ; `e.control.value` = clé du dict FORMATS.
        """
        self.current_format = FORMATS[e.control.value]
        try:
            self.current_format_label = e.control.value
        except Exception:
            pass
        if "10x15" in self.current_format_label:
            self.two_in_one_switch.visible = True
            self.two_in_one_switch.value = False
            self.border_switch_13x15.visible = True
            self.border_switch_13x15.value = self.border_13x15
            self.border_switch_20x24.visible = False
            self.border_switch_20x24.value = False
            self.border_20x24 = False
            self.border_switch_13x10.visible = False
            self.border_switch_13x10.value = False
            self.border_13x10 = False
            self.border_switch_ID2.visible = False
            self.border_switch_ID2.value = False
            self.border_switch_ID4.visible = False
            self.border_switch_ID4.value = False
            self.network_switch.visible = False
        elif "13x18" in self.current_format_label or "15x20" in self.current_format_label:
            self.two_in_one_switch.visible = True
            self.two_in_one_switch.value = False
            self.border_switch_13x15.visible = False
            self.border_switch_20x24.visible = False
            self.border_switch_20x24.value = False
            self.border_20x24 = False
            self.border_switch_13x10.visible = False
            self.border_switch_13x10.value = False
            self.border_13x10 = False
            self.border_switch_ID2.visible = False
            self.border_switch_ID2.value = False
            self.border_switch_ID4.visible = False
            self.border_switch_ID4.value = False
            self.network_switch.visible = False
        elif "18x24" in self.current_format_label:
            self.two_in_one_switch.visible = False
            self.border_switch_20x24.visible = True
            self.border_switch_13x15.visible = False
            self.border_switch_13x10.visible = False
            self.border_switch_13x10.value = False
            self.border_13x10 = False
            self.border_switch_ID2.visible = False
            self.border_switch_ID2.value = False
            self.border_switch_ID4.visible = False
            self.border_switch_ID4.value = False
            self.network_switch.visible = False
            self.border_switch_polaroid.visible = False
            self.border_switch_polaroid.value = False
            self.border_polaroid = False
        elif "10x10" in self.current_format_label:
            self.two_in_one_switch.visible = False
            self.border_switch_13x10.visible = True
            self.border_switch_polaroid.visible = True
            self.border_switch_13x15.visible = False
            self.border_switch_ID2.visible = False
            self.border_switch_ID2.value = False
            self.border_switch_ID4.visible = False
            self.border_switch_ID4.value = False
            self.network_switch.visible = False
        elif "ID" in self.current_format_label:
            self.two_in_one_switch.visible = False
            self.border_switch_ID2.visible = True
            self.border_switch_ID4.visible = True
            self.network_switch.visible = True
            self.sharpen_switch.value = True
            self.border_switch_13x15.visible = False
            self.border_switch_13x10.visible = False
            self.border_switch_13x10.value = False
            self.border_13x10 = False
            self.border_switch_polaroid.visible = False
            self.border_switch_polaroid.value = False
            self.border_polaroid = False
        else:
            self.two_in_one_switch.visible = False
            self.border_switch_13x15.visible = False
            self.border_switch_20x24.visible = False
            self.border_switch_20x24.value = False
            self.border_20x24 = False
            self.border_switch_13x10.visible = False
            self.border_switch_13x10.value = False
            self.border_13x10 = False
            self.border_switch_ID2.visible = False
            self.border_switch_ID2.value = False
            self.border_switch_ID4.visible = False
            self.border_switch_ID4.value = False
            self.network_switch.visible = False
            self.border_switch_polaroid.visible = False
            self.border_switch_polaroid.value = False
            self.border_polaroid = False
        self.update_canvas_size()
        if self.image_paths:
            self.load_image(preserve_orientation=True)

    def toggle_orientation(self, e):
        """
        Bascule l'orientation du canevas entre portrait et paysage.

        Inverse `canvas_is_portrait`, recalcule les dimensions du canevas
        et recharge l'image courante. Met à jour la visibilité des switches
        selon le format actif.

        Raccourci clavier : Backspace.

        Parameters
        ----------
        e : ft.ControlEvent or ft.KeyboardEvent
            Événement déclencheur (bouton ou clavier).
        """
        self.canvas_is_portrait = not self.canvas_is_portrait
        self.update_canvas_size()
        if self.image_paths:
            self.load_image(preserve_orientation=True)

        self.two_in_one_switch.visible = True if (any(fmt in self.current_format_label for fmt in ["10x15", "13x18", "15x20"])) else False
        self.border_switch_13x15.visible = True if "10x15" in self.current_format_label else False
        self.border_switch_13x10.visible = True if "10x10" in self.current_format_label else False
        self.border_switch_polaroid.visible = True if "10x10" in self.current_format_label else False
        self.border_switch_ID2.visible = True if "ID" in self.current_format_label else False
        self.border_switch_ID4.visible = True if "ID" in self.current_format_label else False
        self.network_switch.visible = True if "ID" in self.current_format_label else False

    # ================================================================ #
    #                  FORMATS MULTIPLES & EXEMPLAIRES                 #
    # ================================================================ #

    def increment_copies(self, e):
        """
        Incrémente le compteur d'exemplaires (à l'infini).

        Chaque exemplaire produit un fichier supplémentaire lors de
        l'export (préfixe ``NX_`` dans le nom du fichier où N est le
        nombre d'exemplaires).

        Parameters
        ----------
        e : ft.ControlEvent
            Événement du bouton « + ».
        """
        self.copies_count += 1
        self.copies_text.value = str(self.copies_count)
        self.page.update()

    def decrement_copies(self, e):
        """
        Décrémente le compteur d'exemplaires (minimum 1).

        Parameters
        ----------
        e : ft.ControlEvent
            Événement du bouton « − ».
        """
        if self.copies_count > 1:
            self.copies_count -= 1
        self.copies_text.value = str(self.copies_count)
        self.page.update()

    def add_extra_format(self, e):
        """
        Enregistre un snapshot du cadrage courant dans la liste des formats
        multiples (`extra_formats`).

        Un snapshot est un dictionnaire qui capture l'état complet de la
        vue à cet instant : format, orientation, dimensions du canevas,
        base_scale, scale, offsets, rotation, réglages actifs (N&B, netteté,
        ombres, hautes lumières, contraste, saturation, exposition, etc.).

        Après l'ajout :
          - L'affichage de la liste des formats est mis à jour.
          - Le compteur d'exemplaires est remis à 1.
          - Tous les filtres (N&B, ombres, hautes lumières, contraste,
            saturation, exposition) sont remis à zéro pour préparer le
            prochain cadrage.

        À la validation (`validate_and_next`), tous les snapshots de
        `extra_formats` seront exportés en plus du cadrage principal.

        Parameters
        ----------
        e : ft.ControlEvent
            Événement du bouton « Ajouter le format courant ».
        """
        label = self.current_format_label
        dims = self.current_format
        is_portrait = self.canvas_is_portrait
        snapshot = {
            "label": label,
            "dims": dims,
            "is_portrait": is_portrait,
            "canvas_w": self.canvas_w,
            "canvas_h": self.canvas_h,
            "base_scale": self.base_scale,
            "scale": self.scale,
            "offset_x": self.offset_x,
            "offset_y": self.offset_y,
            "rotation": self.rotation,
            "copies": self.copies_count,
            "border_13x15": self.border_13x15,
            "is_bw": self.is_bw,
            "two_in_one": bool(self.two_in_one_switch.value),
            "is_sharpen": self.is_sharpen,
            "enhance_toggle": False,
            "fit_in": self.is_fit_in,
            "shadows": self.shadows,
            "highlights": self.highlights,
            "contrast": self.contrast,
            "saturation": self.saturation,
            "exposure": self.exposure,
            "hue": self.hue,
            "white_balance": self.white_balance,
        }
        self.extra_formats.append(snapshot)
        self._update_extra_formats_display()
        # Remettre uniquement le compteur d'exemplaires à 1 pour le prochain format
        self.copies_count = 1
        self.copies_text.value = "1"
        self.page.update()

    def clear_extra_formats(self, e):
        """
        Vide la liste des formats multiples (extra_formats).

        Met à jour l'affichage de la liste et rafraîchit la page.

        Parameters
        ----------
        e : ft.ControlEvent
            Événement du bouton « Vider la liste ».
        """
        self.extra_formats.clear()
        self._update_extra_formats_display()
        self.page.update()

    def _update_extra_formats_display(self):
        """
        Met à jour le texte récapitulatif des formats multiples.

        Pour chaque snapshot de `extra_formats`, génère une chaîne courte
        du type ``2X 10x15 P 2en1 N&B S+20 HL-10 C+5 Sat+30 E+15``
        indiquant le nombre d'exemplaires, le format, l'orientation, et les
        réglages non nuls actifs. Les snapshots sont joints par « + ».

        Met à jour `extra_formats_display.value` (affiché dans l'UI).
        Si la liste est vide, affiche « — ».
        """
        if self.extra_formats:
            parts = []
            for s in self.extra_formats:
                lbl = s["label"].split()[0]
                copies = s.get("copies", 1)
                parts.append(f"{copies}X {lbl}")
            self.extra_formats_display.value = " + ".join(parts)
        else:
            self.extra_formats_display.value = "—"

    # ================================================================ #
    #                            ACTIONS                               #
    # ================================================================ #

    def validate_and_next(self, e):
        """
        Exporte l'image courante et passe à la suivante.

        Pipeline d'export
        -----------------
        1. Calcul du recadrage principal via `_compute_crop` (ou
           `_compute_fit_in` en mode Fit-in).
        2. Application des mises en page spéciales dans l'ordre :
             a. 2-en-1 (split en deux panneaux identiques)
             b. Bordure 13x15 (10x15 → 13x15)
             c. Bordure 20x24 (18x24 → 20x24)
             d. Bordure 13x10 (10x10 → 13x10)
             e. Polaroid (10x10 centré sur 127×152 mm)
             f. ID ×4 (grille 2×2 sur 127×102 mm, espacement 5 mm)
             g. ID ×2 (pile verticale sur 102×102 mm)
        3. Détermination du dossier de destination :
             - Planches ID ×4 avec switch réseau activé → partage NAS
             - Tous les autres formats → sous-dossier du dossier source
        4. Application du filtre de netteté (UnsharpMask ×2), des réglages
           (exposition, contraste, saturation, ombres, hautes lumières).
        5. Conversion sRGB avec profil ICC embarqué.
        6. Sauvegarde JPEG qualité 100, 300 dpi.
        7. Export de chaque snapshot `extra_formats` (formats multiples)
           dans leur propre sous-dossier, avec leurs réglages propres.
        8. Réinitialisation de l'état (compteur, filtres, formats multiples).
        9. En mode batch : chargement de l'image suivante.
           Quand toutes les images sont traitées, fermeture de la fenêtre.

        Les noms de fichiers sont dédoublés automatiquement si un fichier
        du même nom existe déjà (suffixe `_2`, `_3`, etc.).

        Raccourci clavier : Entrée.

        Parameters
        ----------
        e : ft.ControlEvent or ft.KeyboardEvent
            Événement déclencheur (bouton « Valider & Suivant » ou clavier).
        """
        if not self.image_paths or self.current_index >= len(self.image_paths):
            self.status_text.value = "Toutes les images ont été traitées."
            self.page.update()
            return

        self.status_text.value = "Enregistrement..."
        self.page.update()

        used_paths = set()

        def unique_path(path):
            """
            Retourne un chemin de fichier unique en ajoutant un suffixe
            numérique (_2, _3, …) si le chemin est déjà réservé dans la
            session d'export courante.

            Utilise le set ``used_paths`` (fermé sur la session d'export
            de l'image courante) pour tracer les chemins déjà attribués.

            Parameters
            ----------
            path : str
                Chemin candidat (peut être déjà dans used_paths).

            Returns
            -------
            str
                Chemin garanti unique dans la session : identique à
                ``path`` s'il n'y a pas de conflit, sinon
                ``<base>_2<ext>``, ``<base>_3<ext>``…
            """
            if path not in used_paths:
                used_paths.add(path)
                return path
            base, ext = os.path.splitext(path)
            i = 2
            while True:
                candidate = f"{base}_{i}{ext}"
                if candidate not in used_paths:
                    used_paths.add(candidate)
                    return candidate
                i += 1

        export_is_portrait = self.canvas_is_portrait
        fmt_w_mm, fmt_h_mm = self.current_format
        if export_is_portrait:
            target_w_px = mm_to_pixels(fmt_w_mm)
            target_h_px = mm_to_pixels(fmt_h_mm)
        else:
            target_w_px = mm_to_pixels(fmt_h_mm)
            target_h_px = mm_to_pixels(fmt_w_mm)

        if self.is_fit_in:
            pil_crop = self._compute_fit_in(target_w_px, target_h_px)
        else:
            pil_crop = self._compute_crop(target_w_px, target_h_px)

        base = os.path.basename(self.image_paths[self.current_index])
        name, _ = os.path.splitext(base)
        fmt_short = self.current_format_label.split()[0]
        copies_prefix = f"{self.copies_count}X_"
        jpg = copies_prefix + name + ".jpg"

        two_in_one_applied = False
        if self.is_two_in_one_enabled():
            if self.border_13x15 and "10x15" in fmt_short:
                pil_crop = self._build_two_in_one_10x15_to_13x15(pil_crop)
                fmt_short = "13x15"
            else:
                pil_crop = self._build_two_in_one_image(pil_crop, target_w_px, target_h_px)
            two_in_one_applied = True

        if (not two_in_one_applied) and self.border_13x15 and "10x15" in fmt_short:
            if export_is_portrait:
                src_w, src_h = mm_to_pixels(102), mm_to_pixels(152)
                out_w, out_h = mm_to_pixels(127), mm_to_pixels(152)
            else:
                src_w, src_h = mm_to_pixels(152), mm_to_pixels(102)
                out_w, out_h = mm_to_pixels(152), mm_to_pixels(127)
            base_10x15 = ImageOps.fit(pil_crop, (src_w, src_h), method=Image.Resampling.BICUBIC)
            framed = Image.new("RGB", (out_w, out_h), "white")
            framed.paste(base_10x15, (0, 0))
            pil_crop = framed
            fmt_short = "13x15"

        if (not two_in_one_applied) and self.border_20x24 and "18x24" in fmt_short:
            ratio_20_24 = 203 / 240
            if export_is_portrait:
                target_w = int(pil_crop.height * ratio_20_24)
                framed = Image.new("RGB", (target_w, pil_crop.height), "white")
                framed.paste(pil_crop, (0, 0))
            else:
                target_h = int(pil_crop.width * ratio_20_24)
                framed = Image.new("RGB", (pil_crop.width, target_h), "white")
                framed.paste(pil_crop, (0, 0))
            pil_crop = framed
            fmt_short = "20x24"

        if (not two_in_one_applied) and self.border_13x10 and "10x10" in fmt_short:
            ratio_13_10 = 127 / 102
            if export_is_portrait:
                target_h = int(pil_crop.width * ratio_13_10)
                framed = Image.new("RGB", (pil_crop.width, target_h), "white")
                framed.paste(pil_crop, (0, 0))
            else:
                target_w = int(pil_crop.height * ratio_13_10)
                framed = Image.new("RGB", (target_w, pil_crop.height), "white")
                framed.paste(pil_crop, (0, 0))
            pil_crop = framed
            fmt_short = "13x10"

        if (not two_in_one_applied) and self.border_polaroid and "10x10" in fmt_short:
            POLAROID_WIDTH_PX = mm_to_pixels(127)
            POLAROID_HEIGHT_PX = mm_to_pixels(152)
            framed = Image.new("RGB", (POLAROID_WIDTH_PX, POLAROID_HEIGHT_PX), "white")
            x_offset = (POLAROID_WIDTH_PX - pil_crop.width) // 2
            y_offset = x_offset
            framed.paste(pil_crop, (x_offset, y_offset))
            pil_crop = framed
            fmt_short = "Polaroid"

        if (not two_in_one_applied) and self.border_id4 and "ID" in self.current_format_label:
            CANVA_WIDTH_PX = mm_to_pixels(127)
            CANVA_HEIGHT_PX = mm_to_pixels(102)
            SPACE_PX = mm_to_pixels(5)
            framed = Image.new("RGB", (CANVA_WIDTH_PX, CANVA_HEIGHT_PX), "white")
            img = pil_crop
            if img.height > img.width:
                img = img.rotate(90, expand=True)
            total_width = img.width * 2 + SPACE_PX
            total_height = img.height * 2 + SPACE_PX
            start_x = (CANVA_WIDTH_PX - total_width) // 2
            start_y = (CANVA_HEIGHT_PX - total_height) // 2
            for row in range(2):
                for col in range(2):
                    x_pos = start_x + col * (img.width + SPACE_PX)
                    y_pos = start_y + row * (img.height + SPACE_PX)
                    framed.paste(img, (x_pos, y_pos))
            pil_crop = framed
            fmt_short = "ID_X4"
            jpg = f"{copies_prefix}ID {self.current_index + 1:02}.jpg"

        elif (not two_in_one_applied) and self.border_id2 and "ID" in self.current_format_label:
            CANVA_WIDTH_PX = mm_to_pixels(102)
            CANVA_HEIGHT_PX = mm_to_pixels(102)
            SPACE_PX = mm_to_pixels(5)
            framed = Image.new("RGB", (CANVA_WIDTH_PX, CANVA_HEIGHT_PX), "white")
            img = pil_crop
            if img.width > img.height:
                img = img.rotate(90, expand=True)
            x_offset = (CANVA_WIDTH_PX - img.width) // 2
            y_offset_1 = SPACE_PX
            framed.paste(img, (x_offset, y_offset_1))
            y_offset_2 = CANVA_HEIGHT_PX - img.height - SPACE_PX
            framed.paste(img, (x_offset, y_offset_2))
            pil_crop = framed
            fmt_short = "ID_X2"
            jpg = f"{copies_prefix}ID {self.current_index + 1:02}.jpg"

        if fmt_short == "ID_X4" and self.save_to_network:
            if platform.system() == "Windows":
                base_dir = "\\\\Diskstation\\travaux en cours\\z2026"
            else:
                base_dir = "/Volumes/TRAVAUX EN COURS/Z2026"
        else:
            base_dir = os.path.join(self.source_folder, fmt_short)

        if self.is_sharpen:
            pil_crop = pil_crop.filter(ImageFilter.UnsharpMask(radius=4, percent=13, threshold=0))
            pil_crop = pil_crop.filter(ImageFilter.UnsharpMask(radius=2, percent=21, threshold=0))

        pil_crop = self._apply_adjustments(pil_crop)

        if self.shadows != 0:
            pil_crop = self._apply_shadows(pil_crop, self.shadows)

        if self.highlights != 0:
            pil_crop = self._apply_highlights(pil_crop, self.highlights)

        # Conversion vers sRGB (correction colorimétrique)
        pil_crop = convert_to_srgb(pil_crop, getattr(self, 'icc_profile', None))

        save_kwargs = {"quality": 100, "format": "JPEG", "dpi": (DPI, DPI), "icc_profile": _SRGB_ICC}

        out_path = None
        if not self.extra_formats:
            os.makedirs(base_dir, exist_ok=True)
            out_path = unique_path(os.path.join(base_dir, jpg))
            pil_crop.save(out_path, **save_kwargs)

        # Exports formats supplémentaires (ou tous les exports si extra_formats non vide)
        for idx, snapshot in enumerate(self.extra_formats, start=1):
            ex_label = snapshot["label"]
            ex_short = ex_label.split()[0]
            ex_is_portrait = snapshot["is_portrait"]

            ex_dims = snapshot["dims"]
            ex_fmt_w_mm, ex_fmt_h_mm = ex_dims
            if ex_is_portrait:
                ex_target_w_px = mm_to_pixels(ex_fmt_w_mm)
                ex_target_h_px = mm_to_pixels(ex_fmt_h_mm)
            else:
                ex_target_w_px = mm_to_pixels(ex_fmt_h_mm)
                ex_target_h_px = mm_to_pixels(ex_fmt_w_mm)

            if snapshot.get("fit_in", False):
                saved_bw = self.is_bw
                self.is_bw = snapshot.get("is_bw", False)
                ex_crop = self._compute_fit_in(ex_target_w_px, ex_target_h_px)
                self.is_bw = saved_bw
            else:
                ex_crop = self._compute_crop_from_snapshot(snapshot)

            ex_two_in_one_applied = False
            if snapshot.get("two_in_one", False):
                if snapshot.get("border_13x15", False) and "10x15" in ex_short:
                    ex_crop = self._build_two_in_one_10x15_to_13x15(ex_crop)
                    ex_short = "13x15"
                else:
                    ex_crop = self._build_two_in_one_image(ex_crop, ex_target_w_px, ex_target_h_px)
                ex_two_in_one_applied = True

            if (not ex_two_in_one_applied) and snapshot.get("border_13x15", False) and "10x15" in ex_short:
                if ex_is_portrait:
                    src_w, src_h = mm_to_pixels(102), mm_to_pixels(152)
                    out_w, out_h = mm_to_pixels(127), mm_to_pixels(152)
                else:
                    src_w, src_h = mm_to_pixels(152), mm_to_pixels(102)
                    out_w, out_h = mm_to_pixels(152), mm_to_pixels(127)
                base_fit = ImageOps.fit(ex_crop, (src_w, src_h), method=Image.Resampling.LANCZOS)
                framed = Image.new("RGB", (out_w, out_h), "white")
                framed.paste(base_fit, (0, 0))
                ex_crop = framed
                ex_short = "13x15"

            os.makedirs(ex_short, exist_ok=True)
            ex_copies = snapshot.get("copies", 1)
            ex_prefix = f"{ex_copies}X_"
            ex_jpg = ex_prefix + name + f"_{idx}.jpg"
            ex_dir = os.path.join(self.source_folder, ex_short)
            os.makedirs(ex_dir, exist_ok=True)
            ex_path = unique_path(os.path.join(ex_dir, ex_jpg))

            if snapshot.get("is_sharpen", self.is_sharpen):
                ex_crop = ex_crop.filter(ImageFilter.UnsharpMask(radius=4, percent=13, threshold=0))
                ex_crop = ex_crop.filter(ImageFilter.UnsharpMask(radius=2, percent=21, threshold=0))

            # Appliquer les réglages du snapshot
            saved_contrast, saved_saturation, saved_exposure = self.contrast, self.saturation, self.exposure
            saved_hue, saved_wb = self.hue, self.white_balance
            self.contrast = snapshot.get("contrast", 0)
            self.saturation = snapshot.get("saturation", 0)
            self.exposure = snapshot.get("exposure", 0)
            self.hue = snapshot.get("hue", 0)
            self.white_balance = snapshot.get("white_balance", 0)
            ex_crop = self._apply_adjustments(ex_crop)
            self.contrast, self.saturation, self.exposure = saved_contrast, saved_saturation, saved_exposure
            self.hue, self.white_balance = saved_hue, saved_wb

            if snapshot.get("shadows", 0) != 0:
                ex_crop = self._apply_shadows(ex_crop, snapshot["shadows"])

            if snapshot.get("highlights", 0) != 0:
                ex_crop = self._apply_highlights(ex_crop, snapshot["highlights"])

            # Conversion vers sRGB (correction colorimétrique)
            ex_crop = convert_to_srgb(ex_crop, getattr(self, 'icc_profile', None))

            ex_crop.save(ex_path, **save_kwargs)
            out_path = ex_path

        self.status_text.value = f"[OK] {os.path.basename(out_path)}"
        self.page.update()

        if self.batch_mode:
            self.current_index += 1
            self.extra_formats.clear()
            self._update_extra_formats_display()
            self.copies_count = 1
            self.copies_text.value = "1"
            if self.current_index < len(self.image_paths):
                self.load_image(preserve_orientation=False)
                return
            else:
                self.batch_mode = False
                self.extra_formats.clear()
                self._update_extra_formats_display()
                self.copies_count = 1
                self.copies_text.value = "1"
                self.canvas_container.visible = False
                self.validate_button.visible = False
                self.status_text.value = "[OK] Toutes les images sont traitées !"
                self.page.update()
                asyncio.create_task(self.close_window())
                return
        else:
            self.extra_formats.clear()
            self._update_extra_formats_display()
            self.copies_count = 1
            self.copies_text.value = "1"
            self.page.update()

    def ignore_image(self, e):
        """
        Ignore l'image courante sans l'exporter et passe à la suivante.

        Réinitialise les formats multiples et le compteur d'exemplaires,
        puis charge l'image suivante. Si toutes les images ont été ignorées
        ou traitées, ferme la fenêtre.

        Raccourci clavier : Espace.

        Parameters
        ----------
        e : ft.ControlEvent or ft.KeyboardEvent
            Événement déclencheur (bouton « Ignorer Image » ou espace clavier).
        """
        if not self.image_paths or self.current_index >= len(self.image_paths):
            self.status_text.value = "Toutes les images ont été traitées."
            self.page.update()
            asyncio.create_task(self.close_window())
            return

        self.current_index += 1

        if self.current_index >= len(self.image_paths):
            self.status_text.value = "Toutes les images ont été traitées."
            self.page.update()
            asyncio.create_task(self.close_window())
            return

        self.status_text.value = "Image ignorée."
        self.extra_formats.clear()
        self._update_extra_formats_display()
        self.copies_count = 1
        self.copies_text.value = "1"
        self.load_image(preserve_orientation=False)
        self.page.update()

    async def close_window(self, e=None):
        """
        Ferme la fenêtre de l'application en toute sécurité.

        Utilise un verrou interne (`_closing`) pour éviter les appels
        multiples simultanés (double-validation rapide, fermeture système).

        Tente d'abord de masquer la fenêtre visuellement (`window.visible =
        False`) avant d'appeler `window.destroy()`, ce qui produit une
        fermeture plus fluide sur macOS et Windows.

        Parameters
        ----------
        e : optional
            Événement déclencheur (non utilisé). Peut être None.
        """
        if getattr(self, '_closing', False):
            return
        self._closing = True
        # Nettoyer le dossier de cache de prévisualisation
        try:
            if os.path.isdir(self._preview_tmp_dir):
                shutil.rmtree(self._preview_tmp_dir, ignore_errors=True)
        except Exception:
            pass
        try:
            self.page.window.visible = False
            self.page.update()
        except Exception:
            pass
        try:
            await self.page.window.destroy()
        except Exception:
            pass

#############################################################
#                           MAIN                            #
#############################################################
def main(page: ft.Page):
    """
    Point d'entrée de l'application Flet.

    Cette fonction est passée à `ft.run(main)` et reçoit en paramètre
    la page Flet créée par le runtime.

    Elle réalise :
      1. Configuration de la fenêtre (titre, thème sombre, maximisée,
         couleur de fond).
      2. Instanciation de `PhotoCropper`.
      3. Attachement du gestionnaire de clavier (`on_keyboard_event`) :
           - Entrée    → validate_and_next
           - Backspace → toggle_orientation
           - Espace    → ignore_image
      4. Construction de la mise en page complète :
           - Panneau gauche  : sliders de réglages (rotation, exposition,
             hautes lumières, ombres, contraste, saturation, netteté).
           - Zone centrale   : barre d'opérations (exemplaires, formats
             multiples, N&B, Fit-in, orientation) + canvas interactif.
           - Panneau droit   : sélecteur de format et boutons d'action.
           - Overlay bas-droit : texte de statut.
      5. Gestionnaire de redimensionnement de la fenêtre.
      6. Lancement différé du batch (0,3 s) via `asyncio.create_task`
         pour laisser le temps à la fenêtre de s'initialiser complètement.

    Parameters
    ----------
    page : ft.Page
        Page Flet fournie par le runtime.
    """
    page.title = "Recadrage Photo"
    page.theme_mode = ft.ThemeMode.DARK
    page.window.maximized = True
    page.bgcolor = GREY
    page.run_task(page.window.to_front)

    app = PhotoCropper(page)

    def on_key(event: ft.KeyboardEvent):
        """
        Gestionnaire global des raccourcis clavier de la page.

        Raccourcis pris en charge :
          - ``Entrée``    → :meth:`validate_and_next`  – valider et passer
            à l'image suivante.
          - ``Backspace`` → :meth:`toggle_orientation` – basculer
            portrait / paysage.
          - ``Espace``    → :meth:`ignore_image`       – ignorer l'image
            courante sans l'exporter.

        Parameters
        ----------
        event : ft.KeyboardEvent
            Événement clavier Flet exposant ``event.key`` (nom textuel
            de la touche, p. ex. ``"Enter"``, ``"Backspace"``, ``" "``).
        """
        if event.key == "Enter":
            app.validate_and_next(event)
        elif event.key == "Backspace":
            app.toggle_orientation(event)
        elif event.key == " ":
            app.ignore_image(event)
    page.on_keyboard_event = on_key

    controls = ft.Column([
        ft.Container(
            # ── Panneau droite : Choix des dimensions des photos ──────────────────────
            content=ft.Column([
                ft.Text("Formats Photos", size=16, weight=ft.FontWeight.BOLD, color=WHITE),
                ft.Divider(height=4),
                ft.RadioGroup(
                    content=ft.Column(
                        [ft.Radio(value=fmt, label=fmt, fill_color=BLUE) for fmt in FORMATS.keys()],
                        scroll=ft.ScrollMode.AUTO,
                    ),
                    value="ID (36x46mm)",
                    on_change=app.change_ratio
                ),
            ], scroll=ft.ScrollMode.AUTO),
            height=400,
            border=ft.Border.all(1, GREY),
            bgcolor=DARK,
            border_radius=8,
            padding=ft.Padding.symmetric(horizontal=10, vertical=12),
        ),
        ft.Container(
            content=ft.Column([
                app.two_in_one_switch,
                app.border_switch_13x15,
                app.border_switch_20x24,
                app.border_switch_13x10,
                app.border_switch_polaroid,
                app.border_switch_ID2,
                app.border_switch_ID4,
                app.network_switch,
            ], spacing=0),
            height=150,
        ),
        ft.Divider(height=8),
        ft.Text("Histogramme", size=11, color=LIGHT_GREY, text_align=ft.TextAlign.CENTER),
        app.histogram_image,
        ft.Divider(height=4),
        app.validate_button,
        app.ignore_button
    ], width=RIGHT_COL_WIDTH)

    page.add(
        ft.Stack([
            ft.Row([
                # ── Panneau gauche : réglages sliders ──────────────────────
                ft.Container(
                    content=ft.Column([
                        ft.Text("Réglages", size=16, weight=ft.FontWeight.BOLD, color=WHITE),
                        ft.Divider(height=4),
                        # ── Géométrie ──────────────────────────────────────
                        ft.Container(
                            content=ft.Column([
                                ft.Text("GÉOMÉTRIE", size=10, color=BLUE, weight=ft.FontWeight.BOLD),
                                ft.Text("Rotation", size=12, color=LIGHT_GREY),
                                ft.GestureDetector(content=app.rotation_slider, on_double_tap=lambda e: app.reset_rotation(e)),
                                ft.Text("Zoom", size=12, color=LIGHT_GREY),
                                ft.GestureDetector(content=app.zoom_slider, on_double_tap=lambda e: app.reset_zoom(e)),
                            ], spacing=2),
                            bgcolor=DARK, border_radius=6,
                            padding=ft.Padding.symmetric(horizontal=8, vertical=6),
                            border=ft.Border.all(1, BLUE),
                        ),
                        ft.Divider(height=6),
                        # ── Luminosité ────────────────────────────────────
                        ft.Container(
                            content=ft.Column([
                                ft.Text("LUMINOSITÉ", size=10, color=YELLOW, weight=ft.FontWeight.BOLD),
                                ft.Text("Exposition", size=12, color=LIGHT_GREY),
                                ft.GestureDetector(content=app.exposure_slider, on_double_tap=lambda e: app._reset_slider(app.exposure_slider, 'exposure', 0.0, '0')),
                                ft.Text("Hautes lumières", size=12, color=LIGHT_GREY),
                                ft.GestureDetector(content=app.highlights_slider, on_double_tap=lambda e: app._reset_slider(app.highlights_slider, 'highlights', 0.0, '0')),
                                ft.Text("Ombres", size=12, color=LIGHT_GREY),
                                ft.GestureDetector(content=app.shadows_slider, on_double_tap=lambda e: app._reset_slider(app.shadows_slider, 'shadows', 0.0, '0')),
                                ft.Text("Contraste", size=12, color=LIGHT_GREY),
                                ft.GestureDetector(content=app.contrast_slider, on_double_tap=lambda e: app._reset_slider(app.contrast_slider, 'contrast', 0.0, '0')),
                            ], spacing=2),
                            bgcolor=DARK, border_radius=6,
                            padding=ft.Padding.symmetric(horizontal=8, vertical=6),
                            border=ft.Border.all(1, YELLOW),
                        ),
                        ft.Divider(height=6),
                        # ── Couleur ───────────────────────────────────────
                        ft.Container(
                            content=ft.Column([
                                ft.Text("COULEUR", size=10, color=VIOLET, weight=ft.FontWeight.BOLD),
                                ft.Text("Saturation", size=12, color=LIGHT_GREY),
                                ft.GestureDetector(content=app.saturation_slider, on_double_tap=lambda e: app._reset_slider(app.saturation_slider, 'saturation', 0.0, '0')),
                                ft.Text("Teinte  (−vert / +magenta)", size=12, color=LIGHT_GREY),
                                ft.GestureDetector(content=app.hue_slider, on_double_tap=lambda e: app._reset_slider(app.hue_slider, 'hue', 0.0, '0')),
                                ft.Text("Balance des blancs  (−froid / +chaud)", size=12, color=LIGHT_GREY),
                                ft.GestureDetector(content=app.white_balance_slider, on_double_tap=lambda e: app._reset_slider(app.white_balance_slider, 'white_balance', 0.0, '0')),
                            ], spacing=2),
                            bgcolor=DARK, border_radius=6,
                            padding=ft.Padding.symmetric(horizontal=8, vertical=6),
                            border=ft.Border.all(1, VIOLET),
                        ),
                        ft.Divider(height=6),
                        # ── Netteté ───────────────────────────────────────
                        ft.Container(
                            content=ft.Column([
                                ft.Text("NETTETÉ", size=10, color=GREEN, weight=ft.FontWeight.BOLD),
                                app.sharpen_switch,
                            ], spacing=2),
                            bgcolor=DARK, border_radius=6,
                            padding=ft.Padding.symmetric(horizontal=8, vertical=6),
                            border=ft.Border.all(1, GREEN),
                        ),
                        ft.Divider(height=6),
                        ft.Container(
                            content=ft.Button("Réinit. réglages", on_click=app.reset_adjustments, width=160, bgcolor=BG, color=WHITE),
                            alignment=ft.Alignment.CENTER, padding=ft.Padding.only(top=4, bottom=4)
                        ),
                    ], spacing=2, scroll=ft.ScrollMode.AUTO),
                    width=LEFT_COL_WIDTH,
                    bgcolor=DARK,
                    padding=ft.Padding.symmetric(horizontal=10, vertical=12),
                    border=ft.Border.all(1, GREY),
                    border_radius=8,
                ),
                ft.Container(
                # ── Panneau du dessus : Opérations ──────────────────────
                    content=ft.Column(
                        [
                            ft.Container(
                                content=ft.Column([
                                    ft.Text("Opérations", size=16, weight=ft.FontWeight.BOLD, color=WHITE, text_align=ft.TextAlign.CENTER),
                                    ft.Divider(height=4),
                                    ft.Row([
                                        ft.Column([
                                            ft.Text("Exemplaires", size=14, weight=ft.FontWeight.W_500, text_align=ft.TextAlign.CENTER),
                                            ft.Row([
                                                app.copies_minus_btn,
                                                app.copies_text,
                                                app.copies_plus_btn,
                                            ], alignment=ft.MainAxisAlignment.CENTER, spacing=0),
                                        ], spacing=8, horizontal_alignment=ft.CrossAxisAlignment.CENTER, width=200),
                                        ft.VerticalDivider(width=1, color=LIGHT_GREY),
                                        ft.Column([
                                            ft.Text("Formats multiples", size=14, weight=ft.FontWeight.W_500, text_align=ft.TextAlign.CENTER),
                                            ft.Row([
                                                ft.IconButton(
                                                    icon=ft.Icons.CLEAR,
                                                    icon_color=RED,
                                                    tooltip="Vider la liste",
                                                    on_click=app.clear_extra_formats,
                                                    icon_size=24,
                                                ),
                                                ft.IconButton(
                                                    icon=ft.Icons.ADD_CIRCLE_OUTLINE,
                                                    icon_color=BLUE,
                                                    tooltip="Ajouter le format courant à la liste",
                                                    on_click=app.add_extra_format,
                                                    icon_size=24,
                                                ),
                                                ft.Row([
                                                    app.extra_formats_display,
                                                ], scroll=ft.ScrollMode.AUTO, width=100, height=32, alignment=ft.MainAxisAlignment.START),
                                            ], width=210, alignment=ft.MainAxisAlignment.START, spacing=8),
                                        ], spacing=8, horizontal_alignment=ft.CrossAxisAlignment.CENTER, width=210),
                                        ft.VerticalDivider(width=1, color=LIGHT_GREY),
                                        ft.Column([
                                            app.bw_switch,
                                            app.fit_in_switch,
                                        ], horizontal_alignment=ft.CrossAxisAlignment.START, spacing=4),
                                        ft.VerticalDivider(width=1, color=LIGHT_GREY),                                            
                                        ft.Column([
                                            ft.Text("Fond IA", size=12, color=LIGHT_GREY, text_align=ft.TextAlign.CENTER),
                                            app.rembg_btn,
                                            ft.Row([app.rembg_bg_btn, app.rembg_model_btn, app.rembg_precise_btn], spacing=4),
                                            ft.Row([
                                                ft.Text("Ér.", size=11, color=LIGHT_GREY),
                                                app.rembg_erosion_slider,
                                            ], spacing=2, vertical_alignment=ft.CrossAxisAlignment.CENTER),
                                        ], horizontal_alignment=ft.CrossAxisAlignment.CENTER, alignment=ft.MainAxisAlignment.CENTER, spacing=2),
                                        ft.VerticalDivider(width=1, color=LIGHT_GREY),
                                        ft.Column([
                                            ft.Button(
                                                content=ft.Row([
                                                    ft.Icon(ft.Icons.SWAP_HORIZ, size=16, color=BLUE),
                                                    ft.Text("Orientation", size=14, color=BLUE),
                                                ], spacing=4, tight=True),
                                                bgcolor=BG,
                                                on_click=app.toggle_orientation,
                                                style=ft.ButtonStyle(
                                                    padding=ft.Padding.symmetric(horizontal=8, vertical=3),
                                                    shape=ft.RoundedRectangleBorder(radius=6),
                                                ),
                                                height=30,
                                            ),
                                            app.grid_switch,
                                        ], horizontal_alignment=ft.CrossAxisAlignment.START, alignment=ft.MainAxisAlignment.CENTER, spacing=4),
                                        ft.VerticalDivider(width=1, color=LIGHT_GREY),
                                    ], vertical_alignment=ft.CrossAxisAlignment.CENTER, spacing=16, alignment=ft.MainAxisAlignment.CENTER, scroll=ft.ScrollMode.AUTO, height=130),
                                ], alignment=ft.MainAxisAlignment.START, horizontal_alignment=ft.CrossAxisAlignment.CENTER),
                                padding=ft.Padding.only(top=6, bottom=6, left=12, right=12),
                                alignment=ft.Alignment(0, -1),
                                bgcolor=DARK,
                                border_radius=8,
                                width=1200,
                                border=ft.Border.all(1, GREY),
                            ),
                            # ── Zone centrale : Canevas de l'image ──────────────────────
                            ft.Container(
                                content=app.canvas_container,
                                expand=True,
                                alignment=ft.Alignment.CENTER,
                            ),
                        ],
                        spacing=0,
                        expand=True,
                        horizontal_alignment=ft.CrossAxisAlignment.CENTER,
                    ),
                    expand=True,
                ),
                ft.VerticalDivider(width=1),
                controls
            ], expand=True),
            ft.Container(
                content=app.status_text,
                bgcolor=DARK,
                padding=10,
                border_radius=8,
                right=20,
                bottom=20,
            ),
        ], expand=True)
    )

    # Gestionnaire de redimensionnement de la fenêtre
    def on_window_resize(e):
        """
        Gestionnaire de redimensionnement de la fenêtre principale.

        Recalcule les dimensions du canevas puis réapplique la transformation
        affine courante (pan / zoom / rotation).

        Parameters
        ----------
        e : ft.ControlEvent
            Événement de redimensionnement émis par Flet.
        """
        app.update_canvas_size()
        if app.image_paths:
            app._update_transform()
    
    page.on_resize = on_window_resize

    # Start directly in interactive batch mode on launch (avec délai pour s'assurer que la fenêtre est initialisée)
    async def delayed_start():
        """
        Coroutine de démarrage différé du mode batch interactif.

        Attend 0,3 s après l'ouverture de la fenêtre pour laisser le
        temps à Flet de maximiser la fenêtre et d'initialiser les
        dimensions du canevas, puis démarre
        :meth:`batch_process_interactive`. Un second délai de 0,1 s
        force un recalcul des dimensions après le premier chargement
        d'image.

        Planifiée via ``asyncio.create_task(delayed_start())`` dans
        :func:`main`.

        Notes
        -----
        Les exceptions sont silencieusement ignorées afin d'éviter un
        crash au démarrage si aucun fichier n'est sélectionné.
        """
        await asyncio.sleep(0.3)  # Attendre que la fenêtre soit maximisée
        try:
            app.batch_process_interactive(None)
            # Forcer un recalcul après le premier chargement pour s'assurer des bonnes dimensions
            await asyncio.sleep(0.1)
            if app.image_paths and app.batch_mode and app.current_index < len(app.image_paths):
                app.update_canvas_size()
                app.load_image(preserve_orientation=True)
        except Exception:
            pass
    
    asyncio.create_task(delayed_start())

# Utilisation de la syntaxe recommandée pour éviter le DeprecationWarning
if __name__ == "__main__":
    ft.run(main)