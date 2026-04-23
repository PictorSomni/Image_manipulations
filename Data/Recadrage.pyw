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
Tab       : basculer le mode de défilement de la souris entre zoom et rotation
"""

__version__ = "2.1.5"

#############################################################
#                          IMPORTS                          #
#############################################################
import flet as ft
import os
import shutil
import platform
import re
import time
from PIL import Image, ImageOps, ImageFilter, ImageEnhance, ImageCms
import asyncio
import contextlib
import math
import io
import base64
import numpy as np
import importlib.util

os.environ.setdefault("ORT_LOGGING_LEVEL", "3")  # Supprimer les avertissements de performance d'onnxruntime
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
    "20x20 (203x203mm)": (203, 203),
    "20x30 (203x305mm)": (203, 305),
    "A4 (210x297mm)": (210, 297),
    "30x30 (305x305mm)": (305, 305),
    "30x40 (305x405mm)": (305, 405),
    "A3 (297x420mm)": (297, 420),
    "30x45 (305x455mm)": (305, 455),
    "40x50 (405x505mm)": (405, 505),
    "40x60 (405x605mm)": (405, 605),
    "50x70 (505x705mm)": (505, 705),
    "60x80 (605x805mm)": (605, 805),
    "60x90 (605x905mm)": (605, 905),
    "70x100 (705x1005mm)": (705, 1005)
}

# ===================== COULEURS ===================== #
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



def convert_to_srgb(source_image: Image.Image, icc_profile: bytes | None) -> Image.Image:
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
    source_image : PIL.Image.Image
        Image source à convertir (mode RGB ou RGBA attendu).
    icc_profile : bytes or None
        Profil ICC brut de l'image source (source_image.info.get('icc_profile')).
        None si aucun profil n'est disponible.

    Returns
    -------
    PIL.Image.Image
        Image en mode RGB dans l'espace colorimétrique sRGB.
    """

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



def _erode_alpha(source_image: Image.Image, radius: int) -> Image.Image:
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

    if source_image.mode != "RGBA" or radius <= 0:
        return source_image
    r, g, b, alpha_channel = source_image.split()
    # MinFilter(3) appliqué radius fois : coût O(9 × radius × N pixels)
    # bien plus rapide que MinFilter(2*radius+1) en O((2r+1)² × N).
    for _ in range(radius):
        alpha_channel = alpha_channel.filter(ImageFilter.MinFilter(3))
    return Image.merge("RGBA", (r, g, b, alpha_channel))



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
        for cache_file in os.listdir(self._preview_tmp_dir):
            try: os.remove(os.path.join(self._preview_tmp_dir, cache_file))
            except OSError: pass
        self._preview_counter = 0
        self._prev_preview_path = None



        # Configuration du canvas (calculé dynamiquement)
        self.canvas_is_portrait = True
        self.current_format = FORMATS["ID (36x46mm)"]
        self.current_format_label = "ID (36x46mm)"
        self.border_13x15 = False
        self.border_10x20 = False
        self.border_13x20 = False
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
        self._scroll_rotates = False       # Tab bascule défilement trackpad → rotation
        self._gesture_scale_start = 1.0    # Scale au début du geste (suivi pour le zoom)
        self._gesture_rotation_prev = 0.0  # Rotation cumulée depuis le début du geste (radians)



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
        
        # Container de l'image — positionné dans le Stack, transformé via LayoutControl
        self.image_container = ft.Container(
            content=self.image_display,
            left=(self.canvas_w - self.display_w) / 2,
            top=(self.canvas_h - self.display_h) / 2,
        )



        # Lignes de grille des tiers (fixées au canevas, pas à l'image)
        grid_line_color = ft.Colors.with_opacity(0.5, "#707070")
        self._grid_lines = [
            ft.Container(bgcolor=grid_line_color, left=self.canvas_w / 3,     top=0,                    width=1,             height=self.canvas_h, visible=False),
            ft.Container(bgcolor=grid_line_color, left=2 * self.canvas_w / 3, top=0,                    width=1,             height=self.canvas_h, visible=False),
            ft.Container(bgcolor=grid_line_color, left=0,                     top=self.canvas_h / 3,    width=self.canvas_w, height=1,             visible=False),
            ft.Container(bgcolor=grid_line_color, left=0,                     top=2 * self.canvas_h / 3,width=self.canvas_w, height=1,             visible=False),
        ]



        # Stack : image + grille en overlay fixe
        self.image_stack = ft.Stack(
            controls=[self.image_container, *self._grid_lines],
            width=self.canvas_w,
            height=self.canvas_h,
        )



        # GestureDetector couvrant tout le canevas pour le pan, zoom, rotation
        self.gesture_detector = ft.GestureDetector(
            content=self.image_stack,
            mouse_cursor=ft.MouseCursor.MOVE,
            on_scale_start=self.on_gesture_start,
            on_scale_update=self.on_gesture_update,
            on_scale_end=self.on_gesture_end,
            on_scroll=self.on_gesture_scroll,
        )



        # Boutons d'action (créés ici pour que le main puisse les référencer)
        self.validate_button = ft.Button(
            "Valider & Suivant",
            icon=ft.Icons.CHECK,
            bgcolor=GREEN,
            color=DARK,
            on_click=self.validate_and_next,
        )



        # Bouton pour ignorer l'image courante
        self.ignore_button = ft.Button(
            "Ignorer Image",
            icon=ft.Icons.BLOCK,
            bgcolor=RED,
            color=DARK,
            on_click=self.ignore_image,
        )



        self.two_in_one_switch = ft.Switch(label="2 en 1", active_color=BLUE, value=False, visible=any(fmt in self.current_format_label for fmt in ["10x15", "13x18", "15x20"]), on_change=self.is_two_in_one_enabled)
        self.border_switch_13x15 = ft.Switch(label="13x15", active_color=ORANGE, value=False, visible="10x15" in self.current_format_label, on_change=self.on_border_toggle_13x15)
        self.border_switch_10x20 = ft.Switch(label="10x20", active_color=ORANGE, value=False, visible="10x15" in self.current_format_label, on_change=self.on_border_toggle_10x20)
        self.border_switch_13x20 = ft.Switch(label="13x20", active_color=ORANGE, value=False, visible="13x18" in self.current_format_label, on_change=self.on_border_toggle_13x20)
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



        # Érosion du masque — slider 0–2 % par tranche de 0,1 % (0 = désactivé)
        self.rembg_erosion_pct = 0.0
        self.rembg_erosion_slider = ft.Slider(
            value=0,
            min=0,
            max=2,
            divisions=20,
            label="{value} %",
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
        # Contraste
        self.contrast = 0.0
        self.contrast_slider = ft.Slider(
            value=0, min=-20, max=20, divisions=40, label="0",
            active_color=YELLOW,
            on_change=self.on_contrast_label,
            on_change_end=self.on_contrast_end,
        )

        # Saturation
        self.saturation = 20.0
        self.saturation_slider = ft.Slider(
            value=20, min=-100, max=100, divisions=20, label="20",
            active_color=VIOLET,
            on_change=self.on_saturation_label,
            on_change_end=self.on_saturation_end,
        )

        # Exposition (Exposure — similaire à Camera Raw, +20 = doublement de la luminosité)
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



        # Container principal du canevas de recadrage (Stack + GestureDetector)
        self.canvas_container = ft.Container(
            content=self.gesture_detector,
            clip_behavior=ft.ClipBehavior.HARD_EDGE,
            width=self.canvas_w,
            height=self.canvas_h,
            bgcolor=WHITE,
            border=ft.Border.all(1, WHITE),
        )



# ===================== Snackbar ===================== #
    def _snackbar(self, message, text_color=DARK, bg_color=BLUE):
        self.page.show_dialog(ft.SnackBar(
            ft.Text(message, color=text_color, size=16, text_align=ft.TextAlign.CENTER),
            bgcolor=bg_color,
            duration=3000,
            behavior=ft.SnackBarBehavior.FLOATING,
            padding=ft.Padding(21, 21, 21, 21),
            shape=ft.RoundedRectangleBorder(radius=8),
            ))



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
        format_width, format_height = self.current_format
        if self.canvas_is_portrait:
            target_aspect_ratio = format_width / format_height  # portrait: largeur < hauteur
        else:
            target_aspect_ratio = format_height / format_width  # paysage: largeur > hauteur

        self.canvas_w = available_width
        self.canvas_h = self.canvas_w / target_aspect_ratio
        if self.canvas_h > available_height:
            self.canvas_h = available_height
            self.canvas_w = self.canvas_h * target_aspect_ratio

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
        Applique pan, zoom et rotation via les propriétés LayoutControl.

        - `image_display.width/height` : zoom (redimensionnement layout, pas de re-rendu PIL).
        - `image_container.left/top`   : pan (décalage du coin sup. gauche dans le Stack).
        - `image_container.rotate`     : rotation autour du centre du container.
        """
        scaled_w = self.display_w * self.scale
        scaled_h = self.display_h * self.scale
        self.image_display.width  = scaled_w
        self.image_display.height = scaled_h
        self.image_container.left  = (self.canvas_w - scaled_w) / 2 + self.offset_x
        self.image_container.top   = (self.canvas_h - scaled_h) / 2 + self.offset_y
        self.image_container.rotate = math.radians(self.rotation)
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
            cached_scale, cached_rotation, bounds_result = self._bounds_cache
            if cached_scale == self.scale and cached_rotation == self.rotation:
                return bounds_result
        scaled_image_width = self.display_w * self.scale
        scaled_image_height = self.display_h * self.scale
        rotation_radians = math.radians(self.rotation)
        cos_angle = abs(math.cos(rotation_radians))
        sin_angle = abs(math.sin(rotation_radians))
        bounding_width  = scaled_image_width * cos_angle + scaled_image_height * sin_angle
        bounding_height = scaled_image_width * sin_angle + scaled_image_height * cos_angle
        bounds_result = (bounding_width, bounding_height)
        self._bounds_cache = (self.scale, self.rotation, bounds_result)
        return bounds_result



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

        La couverture est calculée depuis base_scale × orig (avec le même
        nudge appliqué à l'export) plutôt que depuis display_w/h (qui contient
        un surplus de +4 px). Cela garantit que le clamping correspond
        exactement à ce que l'export peut produire, évitant tout bord blanc.
        """

        # Couverture réelle en pixels écran — identique à l'export (_compute_crop_with_canvas)
        border_safety_factor = (1.0 + 2.0 / min(self.original_width, self.original_height)
                 if (self.original_width > 4 and self.original_height > 4) else 1.0)
        effective_width  = self.base_scale * self.original_width * self.scale * border_safety_factor
        effective_height = self.base_scale * self.original_height * self.scale * border_safety_factor

        if self.rotation != 0:
            rotation_radians = math.radians(self.rotation)
            cos_angle = abs(math.cos(rotation_radians))
            sin_angle = abs(math.sin(rotation_radians))
            rotated_width  = effective_width * cos_angle + effective_height * sin_angle
            rotated_height = effective_width * sin_angle + effective_height * cos_angle
        else:
            rotated_width  = effective_width
            rotated_height = effective_height

        horizontal_overflow = rotated_width - self.canvas_w
        if horizontal_overflow < 0.5:
            self.offset_x = 0
        else:
            max_horizontal_offset = horizontal_overflow / 2
            self.offset_x = min(max_horizontal_offset, max(-max_horizontal_offset, self.offset_x))

        vertical_overflow = rotated_height - self.canvas_h
        if vertical_overflow < 0.5:
            self.offset_y = 0
        else:
            max_vertical_offset = vertical_overflow / 2
            self.offset_y = min(max_vertical_offset, max(-max_vertical_offset, self.offset_y))



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
        affiché dans un snackbar et l'application passe automatiquement
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



        # Pré-remplir copies_count depuis le préfixe NX_ du nom de fichier
        copies_prefix_match = re.match(r'^(\d+)X_', os.path.basename(path))
        if copies_prefix_match:
            self.copies_count = int(copies_prefix_match.group(1))
        else:
            self.copies_count = 1
        if hasattr(self, 'copies_text'):
            self.copies_text.value = str(self.copies_count)



        # Vérifier que le fichier existe et est accessible
        if not os.path.isfile(path) or not os.access(path, os.R_OK):
            self._snackbar(f"Fichier inaccessible: {os.path.basename(path)}")
            self.page.update()

            # Passer à l'image suivante automatiquement
            self.current_index += 1
            if self.current_index < len(self.image_paths):
                self.load_image(preserve_orientation)
            return
        
        try:
            source_image = Image.open(path)

            # Conserver le profil ICC avant toute conversion
            self.icc_profile = source_image.info.get('icc_profile', None)

            # Conserver les données EXIF brutes (hors orientation)
            try:
                _raw_exif = source_image.getexif()
                # Supprimer le tag Orientation (274) car exif_transpose va corriger physiquement
                _raw_exif.pop(274, None)
                self.source_exif = _raw_exif.tobytes()
            except Exception:
                self.source_exif = None

            # Appliquer la rotation EXIF pour corriger l'orientation
            source_image = ImageOps.exif_transpose(source_image)
            source_image = source_image.convert("RGBA")
            self.current_pil_image = source_image
            self._rembg_original = None
            self.rembg_btn.selected = False
            self.original_width, self.original_height = source_image.size
        except Exception as e:
            self._snackbar(f"Erreur lors du chargement: {os.path.basename(path)} - {str(e)}")
            self.page.update()

            # Passer à l'image suivante automatiquement
            self.current_index += 1
            if self.current_index < len(self.image_paths):
                self.load_image(preserve_orientation)
            return

        if not preserve_orientation:
            self.canvas_is_portrait = True if self.original_height >= self.original_width else False

        self.update_canvas_size()



        # Calculer la taille de base : COVER en mode normal, CONTAIN en mode Fit-in
        scale_factor_width = self.canvas_w / self.original_width
        scale_factor_height = self.canvas_h / self.original_height
        if self.is_fit_in:
            self.base_scale = min(scale_factor_width, scale_factor_height)
        else:
            self.base_scale = max(scale_factor_width, scale_factor_height)
        
        self.display_w = int(round(self.original_width * self.base_scale))
        self.display_h = int(round(self.original_height * self.base_scale))
        if not self.is_fit_in:
            # +4 px garantit un débordement minimum même quand le ratio de l'image
            # correspond exactement à celui du format d'impression (ex. photo 2:3 en 10×15).
            # Sans ce surplus, overflow = 0 → _clamp_offsets bloque le pan à scale = 1.0.
            self.display_w = max(self.display_w, math.ceil(self.canvas_w) + 4)
            self.display_h = max(self.display_h, math.ceil(self.canvas_h) + 4)

        self.image_display.width = self.display_w
        self.image_display.height = self.display_h
        self._render_preview()

        # Appliquer la rotation et réinitialiser le transform
        self._clamp_offsets()
        self._update_transform()

        if "10x15" in self.current_format_label:
            self.border_switch_13x15.visible = True
            self.border_switch_13x15.value = self.border_13x15
            self.border_switch_10x20.visible = True
            self.border_switch_10x20.value = self.border_10x20
        else:
            self.border_switch_13x15.visible = False
            self.border_switch_10x20.visible = False

        if "13x18" in self.current_format_label:
            self.border_switch_13x20.visible = True
            self.border_switch_13x20.value = self.border_13x20
        else:
            self.border_switch_13x20.visible = False

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

        source_folder_path = self.source_folder

        # Délai pour s'assurer que tous les fichiers sont complètement copiés
        time.sleep(0.3)

        selected_files_env_value = os.environ.get("SELECTED_FILES", "")
        selected_files_filter = set(selected_files_env_value.split("|")) if selected_files_env_value else None

        try:
            all_folder_files = os.listdir(source_folder_path)
        except Exception as e:
            self._snackbar(f"Erreur lors de la lecture du dossier: {e}")
            return

        image_filenames = [f for f in all_folder_files if f.lower().endswith(('.png', '.jpg', '.jpeg', '.jpe', '.tif', '.tiff', '.bmp', '.dib', '.gif', '.webp', '.ico', '.pcx', '.tga', '.ppm', '.pgm', '.pbm', '.pnm')) and not f == "watermark.png"]
        total_image_count = len(image_filenames)

        if selected_files_filter:
            image_filenames = [f for f in image_filenames if f in selected_files_filter]
            if not image_filenames and total_image_count > 0:
                self._snackbar(f"{total_image_count} image(s) trouvée(s) mais aucune ne correspond aux fichiers sélectionnés")
                self.page.update()
                return

        if not image_filenames:
            if len(all_folder_files) == 0:
                self._snackbar("Le dossier est vide")
            else:
                self._snackbar(f"Aucun fichier image valide trouvé dans le dossier (total : {len(all_folder_files)})")
            self.page.update()
            return

        valid_image_paths = []
        for image_filename in image_filenames:
            image_path = os.path.join(source_folder_path, image_filename)
            if os.path.isfile(image_path) and os.access(image_path, os.R_OK):
                try:
                    with Image.open(image_path) as test_image:
                        test_image.verify()
                    valid_image_paths.append(image_path)
                except Exception:
                    pass

        if not valid_image_paths:
            self._snackbar(f"{len(image_filenames)} image(s) trouvée(s) mais aucune n'est accessible ou valide")
            self.page.update()
            return

        self.image_paths = valid_image_paths
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

        target_aspect_ratio = target_w_px / target_h_px
        available_width  = self.canvas_w
        available_height = self.canvas_h
        if available_width / available_height > target_aspect_ratio:
            virtual_canvas_height = available_height
            virtual_canvas_width  = available_height * target_aspect_ratio
        else:
            virtual_canvas_width  = available_width
            virtual_canvas_height = available_width / target_aspect_ratio

        virtual_base_scale = max(virtual_canvas_width / self.original_width, virtual_canvas_height / self.original_height)

        if self.base_scale > 0:
            image_space_offset_x = self.offset_x / (self.base_scale * self.scale)
            image_space_offset_y = self.offset_y / (self.base_scale * self.scale)
        else:
            image_space_offset_x = image_space_offset_y = 0.0
        virtual_offset_x = image_space_offset_x * virtual_base_scale * self.scale
        virtual_offset_y = image_space_offset_y * virtual_base_scale * self.scale

        return self._compute_crop_with_canvas(
            target_w_px, target_h_px,
            virtual_canvas_width, virtual_canvas_height,
            virtual_base_scale, virtual_offset_x, virtual_offset_y,
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

        format_dimensions = snapshot["dims"]
        is_portrait = snapshot["is_portrait"]
        fmt_w_mm, fmt_h_mm = format_dimensions
        if is_portrait:
            target_w_px = mm_to_pixels(fmt_w_mm)
            target_h_px = mm_to_pixels(fmt_h_mm)
        else:
            target_w_px = mm_to_pixels(fmt_h_mm)
            target_h_px = mm_to_pixels(fmt_w_mm)

        saved_rotation_angle = self.rotation
        saved_black_and_white = self.is_bw
        self.rotation = snapshot["rotation"]
        self.is_bw = snapshot.get("is_bw", False)



        # Si rembg n'était pas actif lors du snapshot mais l'est maintenant,
        # utiliser l'image originale (avant suppression du fond) pour ce format.
        saved_image_before_snapshot = None
        if not snapshot.get("rembg_active", False) and self.current_pil_image.mode == "RGBA" and self._rembg_original is not None:
            saved_image_before_snapshot = self.current_pil_image
            self.current_pil_image = self._rembg_original

        cropped_image = self._compute_crop_with_canvas(
            target_w_px, target_h_px,
            snapshot["canvas_w"], snapshot["canvas_h"],
            snapshot["base_scale"], snapshot["offset_x"], snapshot["offset_y"],
            scale_override=snapshot["scale"],
        )

        if saved_image_before_snapshot is not None:
            self.current_pil_image = saved_image_before_snapshot

        self.rotation = saved_rotation_angle
        self.is_bw = saved_black_and_white
        return cropped_image



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

        rotation_radians = math.radians(self.rotation)
        cos_rotation = math.cos(rotation_radians)
        sin_rotation = math.sin(rotation_radians)

        active_zoom_scale = scale_override if scale_override is not None else self.scale
        total_scale_factor = base_scale * active_zoom_scale
        if total_scale_factor <= 0:
            total_scale_factor = 1e-6

        # Décale légèrement total_scale_factor pour que le noyau BICUBIC ne sorte jamais
        # des limites de l'image source. Quand le ratio de l'image correspond exactement
        # au ratio du format au zoom par défaut, les pixels de bord se projettent sur les
        # coordonnées src 0.0 / orig_w, ce qui forcerait BICUBIC à lire l'index -1 —
        # PIL le comble avec (255,255,255,0) → fine frange blanche après compositage alpha.
        if self.original_width > 4 and self.original_height > 4:
            total_scale_factor *= 1.0 + 2.0 / min(self.original_width, self.original_height)

        canvas_center_x = canvas_w / 2 + offset_x
        canvas_center_y = canvas_h / 2 + offset_y
        image_center_x = self.original_width / 2
        image_center_y = self.original_height / 2

        scaled_rotated_image_center_x = total_scale_factor * (cos_rotation * image_center_x - sin_rotation * image_center_y)
        scaled_rotated_image_center_y = total_scale_factor * (sin_rotation * image_center_x + cos_rotation * image_center_y)
        canvas_translation_x = canvas_center_x - scaled_rotated_image_center_x
        canvas_translation_y = canvas_center_y - scaled_rotated_image_center_y

        canvas_to_output_scale_x = canvas_w / target_w_px
        canvas_to_output_scale_y = canvas_h / target_h_px

        inverse_total_scale = 1.0 / total_scale_factor

        affine_m11 = inverse_total_scale * cos_rotation * canvas_to_output_scale_x
        affine_m12 = inverse_total_scale * sin_rotation * canvas_to_output_scale_y
        affine_m21 = inverse_total_scale * -sin_rotation * canvas_to_output_scale_x
        affine_m22 = inverse_total_scale * cos_rotation * canvas_to_output_scale_y

        inverse_translation_x = inverse_total_scale * (cos_rotation * canvas_translation_x + sin_rotation * canvas_translation_y)
        inverse_translation_y = inverse_total_scale * (-sin_rotation * canvas_translation_x + cos_rotation * canvas_translation_y)
        affine_offset_x = -inverse_translation_x
        affine_offset_y = -inverse_translation_y

        output_image = self.current_pil_image.transform(
            (target_w_px, target_h_px),
            Image.Transform.AFFINE,
            (affine_m11, affine_m12, affine_offset_x, affine_m21, affine_m22, affine_offset_y),
            resample=Image.Resampling.BICUBIC,
            fillcolor=(255, 255, 255, 0),
        )

        if output_image.mode == "RGBA":
            # Érosion du canal alpha (suppression des franges résiduelles)
            if getattr(self, 'rembg_erosion_pct', 0.0) > 0:
                erosion_radius = max(1, round(min(output_image.size) * self.rembg_erosion_pct / 100))
                output_image = _erode_alpha(output_image, erosion_radius)
            if getattr(self, 'rembg_bg_white', True):
                background_layer = Image.new("RGBA", output_image.size, (255, 255, 255, 255))
            else:
                original_image_for_blur = self._rembg_original if self._rembg_original is not None else None
                if original_image_for_blur is not None:
                    original_crop = original_image_for_blur.convert("RGB").transform(
                        (target_w_px, target_h_px),
                        Image.Transform.AFFINE,
                        (affine_m11, affine_m12, affine_offset_x, affine_m21, affine_m22, affine_offset_y),
                        resample=Image.Resampling.BICUBIC,
                        fillcolor=(255, 255, 255),
                    )
                    blurred_background = original_crop.filter(ImageFilter.GaussianBlur(radius=64))
                else:
                    white_background = Image.new("RGBA", output_image.size, (255, 255, 255, 255))
                    blurred_background = Image.alpha_composite(white_background, output_image).convert("RGB").filter(ImageFilter.GaussianBlur(radius=64))
                background_layer = blurred_background.convert("RGBA")
            output_image = Image.alpha_composite(background_layer, output_image).convert("RGB")
        else:
            output_image = output_image.convert("RGB")

        if self.is_bw:
            output_image = output_image.convert("L").convert("RGB")

        return output_image



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

        source_image = self.current_pil_image
        if source_image.mode == "RGBA":

            # Érosion du canal alpha (suppression des franges résiduelles)
            if getattr(self, 'rembg_erosion_pct', 0.0) > 0:
                erosion_radius = max(1, round(min(source_image.size) * self.rembg_erosion_pct / 100))
                source_image = _erode_alpha(source_image.copy(), erosion_radius)
            if getattr(self, 'rembg_bg_white', True):
                background_layer = Image.new("RGBA", source_image.size, (255, 255, 255, 255))
            else:
                original_image_for_blur = self._rembg_original if self._rembg_original is not None else None
                if original_image_for_blur is not None:
                    blurred_background = original_image_for_blur.convert("RGB").filter(ImageFilter.GaussianBlur(radius=64))
                else:
                    white_background = Image.new("RGBA", source_image.size, (255, 255, 255, 255))
                    blurred_background = Image.alpha_composite(white_background, source_image).convert("RGB").filter(ImageFilter.GaussianBlur(radius=64))
                background_layer = blurred_background.convert("RGBA")
            source_image = Image.alpha_composite(background_layer, source_image).convert("RGB")
        else:
            source_image = source_image.convert("RGB")
        fit_scale_factor = min(target_w_px / self.original_width, target_h_px / self.original_height)
        resized_width  = max(1, int(round(self.original_width  * fit_scale_factor)))
        resized_height = max(1, int(round(self.original_height * fit_scale_factor)))
        resized_image = source_image.resize((resized_width, resized_height), Image.Resampling.BICUBIC)
        output_canvas = Image.new("RGB", (target_w_px, target_h_px), "white")
        paste_offset_x = (target_w_px - resized_width)  // 2
        paste_offset_y = (target_h_px - resized_height) // 2
        output_canvas.paste(resized_image, (paste_offset_x, paste_offset_y))
        if self.is_bw:
            output_canvas = output_canvas.convert("L").convert("RGB")
        return output_canvas



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

        divide_horizontally = target_w_px >= target_h_px

        if divide_horizontally:
            panel_width  = target_w_px // 2
            panel_height = target_h_px
            first_panel_position  = (0, 0)
            second_panel_position = (panel_width, 0)
        else:
            panel_width  = target_w_px
            panel_height = target_h_px // 2
            first_panel_position  = (0, 0)
            second_panel_position = (0, panel_height)

        first_image = self._force_portrait(first_image.convert("RGB"))
        first_panel = ImageOps.fit(first_image, (panel_width, panel_height), method=Image.Resampling.BICUBIC)

        second_panel = first_panel.copy()

        assembled_image = Image.new("RGB", (target_w_px, target_h_px), "white")
        assembled_image.paste(first_panel, first_panel_position)
        assembled_image.paste(second_panel, second_panel_position)
        return assembled_image



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

        panel_width  = mm_to_pixels(76)
        panel_height = mm_to_pixels(102)
        base_width   = mm_to_pixels(152)
        base_height  = mm_to_pixels(102)
        final_height = mm_to_pixels(127)

        first_image = self._force_portrait(first_image.convert("RGB"))
        photo_panel = ImageOps.fit(first_image, (panel_width, panel_height), method=Image.Resampling.BICUBIC)

        base_image = Image.new("RGB", (base_width, base_height), "white")
        base_image.paste(photo_panel, (0, 0))
        base_image.paste(photo_panel, (panel_width, 0))

        framed_image = Image.new("RGB", (base_width, final_height), "white")
        framed_image.paste(base_image, (0, 0))
        return framed_image



    def _adaptive_enhance(self, input_image):
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
        input_image : PIL.Image.Image
            Image RGB à améliorer.

        Returns
        -------
        PIL.Image.Image
            Image RGB améliorée.
        """

        ycbcr_image = input_image.convert("YCbCr")
        y, cb, cr = ycbcr_image.split()
        luminance_array = np.array(y, dtype=np.float32)
        mean_luminance = luminance_array.mean()



        # Saturation toujours boostée, correction luminosité uniquement si image sombre
        if mean_luminance >= 148:
            return ImageEnhance.Color(input_image).enhance(1.32)



        # Correction gamma : ramène la moyenne vers 148 sans dépasser +42 unités
        target_luminance = min(148.0, mean_luminance + 42.0)
        gamma = math.log(target_luminance / 255.0) / math.log(max(mean_luminance, 1.0) / 255.0)
        gamma = max(0.60, min(0.95, gamma))  # Bornes de sécurité

        adjusted_luminance = np.power(luminance_array / 255.0, gamma) * 255.0



        # Léger étirement des contrastes (coupe 0.5 % à chaque extrémité)
        low_percentile  = np.percentile(adjusted_luminance, 0.5)
        high_percentile = np.percentile(adjusted_luminance, 99.5)
        if high_percentile > low_percentile:
            adjusted_luminance = (adjusted_luminance - low_percentile) * 255.0 / (high_percentile - low_percentile)
        adjusted_luminance = np.clip(adjusted_luminance, 0, 255).astype(np.uint8)

        adjusted_y_channel = Image.fromarray(adjusted_luminance, "L")
        enhanced_image = Image.merge("YCbCr", (adjusted_y_channel, cb, cr)).convert("RGB")
        return ImageEnhance.Color(enhanced_image).enhance(1.42)



    def _apply_adjustments(self, input_image):
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

        working_image = input_image.convert("RGB")
        if self.exposure != 0:
            # Exposition : gamma inverse (+ = plus clair, - = plus sombre)
            # +100 multiplie la lumière x2, -100 la divise par 2
            exposure_factor = 2 ** (self.exposure / 100.0)
            exposure_lookup_table = np.clip(np.arange(256, dtype=np.float32) * exposure_factor, 0, 255).astype(np.uint8)
            pixel_array = np.array(working_image, dtype=np.uint8)
            working_image = Image.fromarray(exposure_lookup_table[pixel_array], "RGB")
        if self.contrast != 0:
            working_image = ImageEnhance.Contrast(working_image).enhance(1.0 + self.contrast / 100.0)
        if self.saturation != 0:
            working_image = ImageEnhance.Color(working_image).enhance(max(0.0, 1.0 + self.saturation / 100.0))
        if self.hue != 0:
            working_image = self._apply_hue(working_image, self.hue)
        if self.white_balance != 0:
            working_image = self._apply_white_balance(working_image, self.white_balance)
        return working_image



    def _apply_shadows(self, input_image, value):
        """
        Ajuste les ombres (similaire au slider Shadows de Camera Raw/Lightroom).
        value : -100 … +100. Positif = éclaircit les ombres, négatif = les assombrit.
        La courbe est nulle aux noirs purs (v=0), maximale vers v=96 et nulle dès les
        demi-tons (v≥192), ce qui préserve les noirs et les hautes lumières.
        """

        if value == 0:
            return input_image
        strength_factor = value / 100.0
        value_range = np.arange(256, dtype=np.float32)

        # Courbe sinusoïdale : sin(π·v/192) — zéro en 0, pic à 96, zéro à 192+
        normalized_value = value_range / 192.0
        shadow_weight = np.where(normalized_value <= 1.0, np.sin(np.pi * normalized_value), 0.0)
        shadow_amplitude = 60  # amplitude max en niveaux d'intensité
        lookup_table = np.clip(value_range + strength_factor * shadow_amplitude * shadow_weight, 0, 255).astype(np.uint8)
        input_rgb = input_image.convert("RGB")
        image_array = np.array(input_rgb, dtype=np.uint8)
        return Image.fromarray(lookup_table[image_array], "RGB")



    def _apply_highlights(self, input_image, value):
        """Ajuste les hautes lumières (miroir des ombres).
        value : -100 … +100. Positif = éclaircit les hautes lumières, négatif = les assombrit.
        Courbe nulle sous v=64, pic vers v=192, nulle aux blancs purs (v=255)."""

        if value == 0:
            return input_image
        strength_factor = value / 100.0
        value_range = np.arange(256, dtype=np.float32)

        # Courbe : sin(π·(v-64)/192) pour v dans [64, 255], zéro ailleurs
        normalized_value = (value_range - 64.0) / 192.0
        highlight_weight = np.where((normalized_value >= 0.0) & (normalized_value <= 1.0), np.sin(np.pi * normalized_value), 0.0)
        highlight_amplitude = 60
        lookup_table = np.clip(value_range + strength_factor * highlight_amplitude * highlight_weight, 0, 255).astype(np.uint8)
        input_rgb = input_image.convert("RGB")
        image_array = np.array(input_rgb, dtype=np.uint8)
        return Image.fromarray(lookup_table[image_array], "RGB")



    def _apply_hue(self, input_image, value):
        """Teinte : décale vers vert (négatif) ou magenta (positif), comme Lightroom.

        value dans [-180, +180] ; effet max ±30 % sur R/G/B via LUT.
        """

        if value == 0:
            return input_image
        normalized_value = value / 180.0       # [-1, +1]
        hue_strength = abs(normalized_value) * 0.30   # force max 30 %
        base_lookup = np.arange(256, dtype=np.float32)
        if normalized_value > 0:
            # Magenta : boost R et B, atténuer G
            red_lookup   = np.clip(base_lookup * (1.0 + hue_strength),       0, 255).astype(np.uint8)
            green_lookup = np.clip(base_lookup * (1.0 - hue_strength),       0, 255).astype(np.uint8)
            blue_lookup  = np.clip(base_lookup * (1.0 + hue_strength * 0.7), 0, 255).astype(np.uint8)
        else:
            # Vert : boost G, atténuer R et B
            red_lookup   = np.clip(base_lookup * (1.0 - hue_strength),       0, 255).astype(np.uint8)
            green_lookup = np.clip(base_lookup * (1.0 + hue_strength),       0, 255).astype(np.uint8)
            blue_lookup  = np.clip(base_lookup * (1.0 - hue_strength * 0.7), 0, 255).astype(np.uint8)
        pixel_array = np.array(input_image.convert("RGB"), dtype=np.uint8)
        result_array = np.stack([
            red_lookup[pixel_array[:, :, 0]],
            green_lookup[pixel_array[:, :, 1]],
            blue_lookup[pixel_array[:, :, 2]],
        ], axis=2)
        return Image.fromarray(result_array, "RGB")



    def _apply_white_balance(self, input_image, value):
        """Balance des blancs : -100 = froid (bleu), +100 = chaud (jaune/orange).\n\n        Applique une correction per-canal (R, G, B) proportionnelle à ``value``.
        """

        if value == 0:
            return input_image
        balance_strength = abs(value) / 100.0 * 0.20  # max ±20 % par canal
        pixel_array = np.array(input_image.convert("RGB"), dtype=np.float32)
        if value > 0:  # chaud : +R, léger +G, -B
            pixel_array[..., 0] = np.clip(pixel_array[..., 0] * (1.0 + balance_strength), 0, 255)
            pixel_array[..., 1] = np.clip(pixel_array[..., 1] * (1.0 + balance_strength * 0.2), 0, 255)
            pixel_array[..., 2] = np.clip(pixel_array[..., 2] * (1.0 - balance_strength), 0, 255)
        else:          # froid : -R, G neutre, +B
            pixel_array[..., 0] = np.clip(pixel_array[..., 0] * (1.0 - balance_strength), 0, 255)
            pixel_array[..., 2] = np.clip(pixel_array[..., 2] * (1.0 + balance_strength), 0, 255)
        return Image.fromarray(pixel_array.astype(np.uint8), "RGB")



    def _render_histogram(self, preview_img):
        """Génère un histogramme RGB et met à jour ``self.histogram_image``."""

        histogram_width, histogram_height = RIGHT_COL_WIDTH, HISTOGRAM_HEIGHT
        pixel_array = np.array(preview_img.convert("RGB"), dtype=np.uint8)
        pixel_array = pixel_array[::4, ::4]  # sous-échantillonnage pour la vitesse
        histogram_canvas = np.full((histogram_height, histogram_width, 3), (30, 30, 38), dtype=np.int32)
        channel_colors = np.array([[80, 20, 20], [20, 70, 20], [20, 20, 80]], dtype=np.int32)
        row_index_array = np.arange(histogram_height)[:, np.newaxis]  # (H, 1)
        for channel_index in range(3):
            pixel_counts, _ = np.histogram(pixel_array[..., channel_index], bins=histogram_width, range=(0, 256))
            max_pixel_count = max(int(pixel_counts.max()), 1)
            bar_heights = np.clip((pixel_counts * histogram_height // max_pixel_count), 0, histogram_height).astype(int)
            bar_start_row = histogram_height - bar_heights[np.newaxis, :]  # (1, W)
            colored_mask = row_index_array >= bar_start_row                 # (H, W)
            histogram_canvas += colored_mask[:, :, np.newaxis] * channel_colors[channel_index]
        histogram_canvas = np.clip(histogram_canvas, 0, 255).astype(np.uint8)
        histogram_pil_image = Image.fromarray(histogram_canvas, "RGB")
        png_buffer = io.BytesIO()
        histogram_pil_image.save(png_buffer, format="PNG")
        self.histogram_image.src = "data:image/png;base64," + base64.b64encode(png_buffer.getvalue()).decode()
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
        
        # Réduire à 2× la taille du canevas — meilleure netteté au zoom
        # sans atteindre la pleine résolution originale (compromis qualité/vitesse).
        preview_width  = max(1, int(self.display_w * 2))
        preview_height = max(1, int(self.display_h * 2))
        # Plafonner à la résolution originale pour éviter l'agrandissement inutile
        preview_width  = min(preview_width,  self.original_width)
        preview_height = min(preview_height, self.original_height)
        preview_image = self.current_pil_image.resize((preview_width, preview_height), Image.Resampling.BILINEAR)
        
        if preview_image.mode == "RGBA":
            # Clé de cache : image source + taille d'affichage + format + paramètres de composition
            composite_cache_key = (
                id(self.current_pil_image), preview_width, preview_height,
                round(self.canvas_w), self.canvas_is_portrait,
                getattr(self, 'rembg_erosion_pct', 0.0),
                getattr(self, 'rembg_bg_white', True),
            )
            if self._rembg_composite_cache is not None and self._rembg_composite_cache[0] == composite_cache_key:
                # Cache valide : réutiliser le composite sans recalculer
                preview_image = self._rembg_composite_cache[1].copy()
            else:
                # Érosion au format réduit — beaucoup plus rapide qu'à pleine résolution.
                # Le rayon est mis à l'échelle pour que la preview corresponde au résultat final.
                # L'échelle correcte est canvas_w / target_w_px (affichage → export),
                # et non display_w / orig_w (qui sous-estime fortement pour les petits formats).
                if getattr(self, 'rembg_erosion_pct', 0.0) > 0:
                    erosion_radius_scaled = max(1, round(min(preview_image.size) * self.rembg_erosion_pct / 100))
                    preview_image = _erode_alpha(preview_image, erosion_radius_scaled)
                if getattr(self, 'rembg_bg_white', True):
                    background_layer = Image.new("RGBA", preview_image.size, (255, 255, 255, 255))
                else:
                    # Utiliser l'image originale (opaque) comme source du flou pour éviter
                    # les débordements noirs des pixels transparents (alpha=0 → noir en RGBA→RGB)
                    blur_source_image = self._rembg_original if self._rembg_original is not None else None
                    if blur_source_image is not None:
                        blurred_background = blur_source_image.convert("RGB").resize((preview_width, preview_height), Image.Resampling.BILINEAR).filter(ImageFilter.GaussianBlur(radius=30))
                    else:
                        white_background = Image.new("RGBA", preview_image.size, (255, 255, 255, 255))
                        blurred_background = Image.alpha_composite(white_background, preview_image).convert("RGB").filter(ImageFilter.GaussianBlur(radius=30))
                    background_layer = blurred_background.convert("RGBA")
                preview_image = Image.alpha_composite(background_layer, preview_image).convert("RGB")
                self._rembg_composite_cache = (composite_cache_key, preview_image.copy())
        else:
            preview_image = preview_image.convert("RGB")

        # Noir et blanc
        if self.is_bw:
            preview_image = ImageOps.grayscale(preview_image).convert("RGB")

        # Contraste, saturation, exposition
        preview_image = self._apply_adjustments(preview_image)

        # Ombres
        if self.shadows != 0:
            preview_image = self._apply_shadows(preview_image, self.shadows)

        # Hautes lumières
        if self.highlights != 0:
            preview_image = self._apply_highlights(preview_image, self.highlights)

        # Netteté
        if self.is_sharpen:
            preview_image = preview_image.filter(ImageFilter.UnsharpMask(radius=4, percent=13, threshold=0))
            preview_image = preview_image.filter(ImageFilter.UnsharpMask(radius=2, percent=21, threshold=0))
        
        # Conversion sRGB : aligner le preview sur l'image enregistrée
        preview_image = convert_to_srgb(preview_image, getattr(self, 'icc_profile', None))
        
        # Encoder en mémoire — élimine l'I/O disque, invalide le cache Flutter via données uniques
        jpeg_buffer = io.BytesIO()
        preview_image.save(jpeg_buffer, format="JPEG", quality=70)
        self.image_display.src = "data:image/jpeg;base64," + base64.b64encode(jpeg_buffer.getvalue()).decode()
        self.image_display.update()
        self._render_histogram(preview_image)



    # ================================================================ #
    #                  NAVIGATION (PAN, ZOOM, ROTATION)                #
    # ================================================================ #
    def on_gesture_start(self, e):
        """Mémorise l'état au début d'un geste (pan, zoom, rotation)."""

        if not self.image_paths or not hasattr(self, 'original_width'):
            return
        self._gesture_scale_start = self.scale
        self._gesture_rotation_prev = 0.0



    def on_gesture_update(self, e):
        """
        Met à jour scale, offset et rotation depuis un geste GestureDetector.

        - `e.scale`                   : facteur de zoom cumulatif depuis le début du geste.
        - `e.focal_point_delta.x/y`   : déplacement du point focal depuis le dernier événement (pixels).
        - `e.rotation`                : rotation cumulée depuis le début du geste (radians) — twist deux doigts.
        """

        if not self.image_paths or not hasattr(self, 'original_width'):
            return

        # ── Zoom (pinch deux doigts) ────────────────────────────────────
        new_scale = max(1.0, min(10.0, self._gesture_scale_start * e.scale))
        self.scale = new_scale

        # ── Pan (déplacement du point focal) ────────────────────────────
        self.offset_x += e.focal_point_delta.x
        self.offset_y += e.focal_point_delta.y

        # ── Rotation (twist deux doigts) ─────────────────────────────────
        rotation_delta_rad = e.rotation - self._gesture_rotation_prev
        self._gesture_rotation_prev = e.rotation
        if abs(rotation_delta_rad) > 0.001:
            rotation_delta_deg = math.degrees(rotation_delta_rad)
            new_rotation = max(-15.0, min(15.0, self.rotation + rotation_delta_deg))
            if new_rotation != self.rotation:
                self.rotation = new_rotation
                self.rotation_slider.value = self.rotation
                self.rotation_slider.label = f"{self.rotation:.2f}°"
                self.rotation_slider.update()

        # ── Mise à jour du slider de zoom ────────────────────────────────
        zoom_slider_val = min(self.scale, self.zoom_slider.max)
        if abs(zoom_slider_val - self.zoom_slider.value) > 0.01:
            self.zoom_slider.value = zoom_slider_val
            self.zoom_slider.label = f"{self.scale:.2f}×"
            self.zoom_slider.update()

        # ── Transforms GPU + clampage ─────────────────────────────────────
        self._clamp_offsets()
        self._update_transform()



    def on_gesture_end(self, e):
        """Rafraîchit la prévisualisation et l'histogramme après la fin d'un geste."""

        if not self.image_paths or not hasattr(self, 'original_width'):
            return
        self._clamp_offsets()
        self._update_transform()
        self._render_preview()
        self.page.update()



    def on_gesture_scroll(self, e):
        """
        Défilement molette / trackpad deux doigts :
          - mode normal (badge absent) → scroll vertical → zoom.
          - mode Tab    (badge visible) → scroll vertical → rotation.
        """

        if not self.image_paths or not hasattr(self, 'original_width'):
            return
        dy = e.scroll_delta.y
        if self._scroll_rotates:
            # Mode Tab : molette → rotation (±15°)
            rotation_delta = dy * 0.005
            self.rotation = max(-15.0, min(15.0, self.rotation + rotation_delta))
            self.rotation_slider.value = self.rotation
            self.rotation_slider.label = f"{self.rotation:.2f}°"
            self.rotation_slider.update()
        else:
            # Mode normal : molette → zoom
            if dy != 0:
                zoom_delta = -dy * 0.0002
                self.scale = max(1.0, min(10.0, self.scale * (1.0 + zoom_delta)))
                zoom_slider_val = min(self.scale, self.zoom_slider.max)
                self.zoom_slider.value = zoom_slider_val
                self.zoom_slider.label = f"{self.scale:.2f}×"
                self.zoom_slider.update()
        self._clamp_offsets()
        self._update_transform()



    def _update_shift_badge(self):
        """Affiche un SnackBar indiquant le mode de défilement actif."""

        if self._scroll_rotates:
            msg = "Molette → Rotation activée"
        else:
            msg = "Molette → Zoom activé"
        self._snackbar(msg)
        self.page.update()



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
        et applique la transformation via les propriétés LayoutControl.
        """

        target_scale = e.control.value
        previous_scale = self.scale
        self.scale = target_scale
        ratio = self.scale / previous_scale if previous_scale > 0 else 1.0
        if previous_scale != self.scale and abs(ratio - 1.0) > 1e-6:
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
        self._snackbar("Rotation réinitialisée à 0°")



    def reset_zoom(self, e):
        """Remet le zoom à 1× et réinitialise le pan (double-clic sur le slider)."""

        self.scale = 1.0
        self.offset_x = 0.0
        self.offset_y = 0.0
        self.zoom_slider.value = 1.0
        self.zoom_slider.label = "1.00×"
        self.zoom_slider.update()
        self._update_transform()
        self._render_preview()
        self.page.update()
        self._snackbar("Zoom réinitialisé à 1× et pan réinitialisé")



    def _reset_slider(self, slider, attr, default_val, label_str):
        """Remet un slider de réglage à sa valeur par défaut et redéclenche le rendu."""

        setattr(self, attr, default_val)
        slider.value = default_val
        slider.label = label_str
        slider.update()
        self._render_preview()
        self.page.update()
        self._snackbar("Slider réinitialisé")


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
        """Met à jour le % d'érosion pendant le drag (pas de rendu)."""

        self.rembg_erosion_pct = round(e.control.value, 1)



    def on_rembg_erosion_end(self, e):
        """Regénère la preview au relâchement du slider d'érosion."""

        self.rembg_erosion_pct = round(e.control.value, 1)
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
            self._snackbar("[ERREUR] rembg non installé — pip install rembg onnxruntime")
            return
        if self.current_pil_image is None:
            self._snackbar("[ERREUR] aucune image chargée")
            return



        # Deuxième clic : restaurer l'image originale
        if self.rembg_btn.selected and self._rembg_original is not None:
            self.current_pil_image = self._rembg_original
            self._rembg_original = None
            self.rembg_btn.selected = False
            self._snackbar("Fond restauré")
            self._render_preview()
            self.page.update()
            return

        self.rembg_btn.disabled = True
        self._snackbar("Suppression du fond en cours…")
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
            self._snackbar("[OK] Fond supprimé — recliquer pour restaurer")
        except Exception as ex:
            self._snackbar(f"[ERREUR] rembg : {ex}")
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
        if self.border_13x15:
            self.border_10x20 = False
            self.border_switch_10x20.value = False
            self.border_switch_10x20.update()



    def on_border_toggle_10x20(self, e):
        """Active / désactive le cadre 10x20 pour une photo 10x15.
        Mutuellement exclusif avec 13x15."""

        self.border_10x20 = bool(e.control.value)
        if self.border_10x20:
            self.border_13x15 = False
            self.border_switch_13x15.value = False
            self.border_switch_13x15.update()




    def on_border_toggle_13x20(self, e):
        """Active / désactive le cadre 13x20 pour une photo 13x18."""

        self.border_13x20 = bool(e.control.value)



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
        self._snackbar("Ombres et Hautes Lumières remises à 0")



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
        self._snackbar("Tous les réglages remis à 0")



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
            self.border_switch_10x20.visible = True
            self.border_switch_10x20.value = self.border_10x20
            self.border_switch_13x20.visible = False
            self.border_switch_13x20.value = False
            self.border_13x20 = False
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
        elif "13x18" in self.current_format_label:
            self.two_in_one_switch.visible = True
            self.two_in_one_switch.value = False
            self.border_switch_13x15.visible = False
            self.border_switch_10x20.visible = False
            self.border_switch_10x20.value = False
            self.border_10x20 = False
            self.border_switch_13x20.visible = True
            self.border_switch_13x20.value = self.border_13x20
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
        elif "15x20" in self.current_format_label:
            self.two_in_one_switch.visible = True
            self.two_in_one_switch.value = False
            self.border_switch_13x15.visible = False
            self.border_switch_10x20.visible = False
            self.border_switch_10x20.value = False
            self.border_10x20 = False
            self.border_switch_13x20.visible = False
            self.border_switch_13x20.value = False
            self.border_13x20 = False
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
        elif "18x24" in self.current_format_label:
            self.two_in_one_switch.visible = False
            self.border_switch_20x24.visible = True
            self.border_switch_13x15.visible = False
            self.border_switch_10x20.visible = False
            self.border_switch_10x20.value = False
            self.border_10x20 = False
            self.border_switch_13x20.visible = False
            self.border_switch_13x20.value = False
            self.border_13x20 = False
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
            self.border_switch_10x20.visible = False
            self.border_switch_10x20.value = False
            self.border_10x20 = False
            self.border_switch_13x20.visible = False
            self.border_switch_13x20.value = False
            self.border_13x20 = False
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
            self.border_switch_10x20.visible = False
            self.border_switch_10x20.value = False
            self.border_10x20 = False
            self.border_switch_13x20.visible = False
            self.border_switch_13x20.value = False
            self.border_13x20 = False
            self.border_switch_13x10.visible = False
            self.border_switch_13x10.value = False
            self.border_13x10 = False
            self.border_switch_polaroid.visible = False
            self.border_switch_polaroid.value = False
            self.border_polaroid = False
        else:
            self.two_in_one_switch.visible = False
            self.border_switch_13x15.visible = False
            self.border_switch_10x20.visible = False
            self.border_switch_10x20.value = False
            self.border_10x20 = False
            self.border_switch_13x20.visible = False
            self.border_switch_13x20.value = False
            self.border_13x20 = False
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
            "border_10x20": self.border_10x20,
            "border_13x20": self.border_13x20,
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
            "rembg_active": self.rembg_btn.selected,
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
            self._snackbar("Toutes les images ont été traitées.")
            return

        self._snackbar("Enregistrement en cours...")

        used_paths = set()

        def unique_path(path):
            """
            Retourne un chemin de fichier unique en ajoutant un suffixe
            numérique (_2, _3, …) si le chemin est déjà réservé dans la
            session d'export courante.

            Utilise le set ``already_saved_paths`` (fermé sur la session d'export
            de l'image courante) pour tracer les chemins déjà attribués.

            Parameters
            ----------
            path : str
                Chemin candidat (peut être déjà dans already_saved_paths).

            Returns
            -------
            str
                Chemin garanti unique dans la session : identique à
                ``path`` s'il n'y a pas de conflit, sinon
                ``<base>_2<ext>``, ``<base>_3<ext>``…
            """

            already_saved_paths = used_paths
            if path not in already_saved_paths:
                already_saved_paths.add(path)
                return path
            file_base, file_extension = os.path.splitext(path)
            suffix_number = 2
            while True:
                candidate_path = f"{file_base}_{suffix_number}{file_extension}"
                if candidate_path not in already_saved_paths:
                    already_saved_paths.add(candidate_path)
                    return candidate_path
                suffix_number += 1

        output_is_portrait = self.canvas_is_portrait
        format_width_mm, format_height_mm = self.current_format
        if output_is_portrait:
            output_width_px = mm_to_pixels(format_width_mm)
            output_height_px = mm_to_pixels(format_height_mm)
        else:
            output_width_px = mm_to_pixels(format_height_mm)
            output_height_px = mm_to_pixels(format_width_mm)

        if self.is_fit_in:
            output_image = self._compute_fit_in(output_width_px, output_height_px)
        else:
            output_image = self._compute_crop(output_width_px, output_height_px)

        source_filename = os.path.basename(self.image_paths[self.current_index])
        base_filename, _ = os.path.splitext(source_filename)
        base_filename = re.sub(r'^\d+X_', '', base_filename)  # retirer le préfixe NX_ existant pour ne pas le doubler
        format_short_name = self.current_format_label.split()[0]
        copies_count_prefix = f"{self.copies_count}X_"
        output_filename = copies_count_prefix + base_filename + ".jpg"

        # Appliquer les réglages couleur sur la photo AVANT l'ajout des bordures/marges,
        # pour que les zones blanches (13x15, Polaroid, ID grille…) restent blanc pur.
        output_image = self._apply_adjustments(output_image)
        if self.shadows != 0:
            output_image = self._apply_shadows(output_image, self.shadows)
        if self.highlights != 0:
            output_image = self._apply_highlights(output_image, self.highlights)

        two_in_one_applied = False
        if self.is_two_in_one_enabled():
            if self.border_13x15 and "10x15" in format_short_name:
                output_image = self._build_two_in_one_10x15_to_13x15(output_image)
                format_short_name = "13x15"
            else:
                output_image = self._build_two_in_one_image(output_image, output_width_px, output_height_px)
            two_in_one_applied = True

        if (not two_in_one_applied) and self.border_13x15 and "10x15" in format_short_name:
            if output_is_portrait:
                source_width_px, source_height_px = mm_to_pixels(102), mm_to_pixels(152)
                output_framed_width_px, output_framed_height_px = mm_to_pixels(127), mm_to_pixels(152)
            else:
                source_width_px, source_height_px = mm_to_pixels(152), mm_to_pixels(102)
                output_framed_width_px, output_framed_height_px = mm_to_pixels(152), mm_to_pixels(127)
            fitted_photo = ImageOps.fit(output_image, (source_width_px, source_height_px), method=Image.Resampling.BICUBIC)
            framed_image = Image.new("RGB", (output_framed_width_px, output_framed_height_px), "white")
            framed_image.paste(fitted_photo, (0, 0))
            output_image = framed_image
            format_short_name = "13x15"

        if (not two_in_one_applied) and self.border_10x20 and "10x15" in format_short_name:
            if output_is_portrait:
                source_width_px, source_height_px = mm_to_pixels(102), mm_to_pixels(152)
                output_framed_width_px, output_framed_height_px = mm_to_pixels(102), mm_to_pixels(203)
            else:
                source_width_px, source_height_px = mm_to_pixels(152), mm_to_pixels(102)
                output_framed_width_px, output_framed_height_px = mm_to_pixels(203), mm_to_pixels(102)
            fitted_photo = ImageOps.fit(output_image, (source_width_px, source_height_px), method=Image.Resampling.BICUBIC)
            framed_image = Image.new("RGB", (output_framed_width_px, output_framed_height_px), "white")
            framed_image.paste(fitted_photo, (0, 0))
            output_image = framed_image
            format_short_name = "10x20"

        if (not two_in_one_applied) and self.border_13x20 and "13x18" in format_short_name:
            if output_is_portrait:
                source_width_px, source_height_px = mm_to_pixels(127), mm_to_pixels(178)
                output_framed_width_px, output_framed_height_px = mm_to_pixels(127), mm_to_pixels(203)
            else:
                source_width_px, source_height_px = mm_to_pixels(178), mm_to_pixels(127)
                output_framed_width_px, output_framed_height_px = mm_to_pixels(203), mm_to_pixels(127)
            fitted_photo = ImageOps.fit(output_image, (source_width_px, source_height_px), method=Image.Resampling.BICUBIC)
            framed_image = Image.new("RGB", (output_framed_width_px, output_framed_height_px), "white")
            framed_image.paste(fitted_photo, (0, 0))
            output_image = framed_image
            format_short_name = "13x20"

        if (not two_in_one_applied) and self.border_20x24 and "18x24" in format_short_name:
            ratio_20_24 = 203 / 240
            if output_is_portrait:
                framed_width_px = int(output_image.height * ratio_20_24)
                framed_image = Image.new("RGB", (framed_width_px, output_image.height), "white")
                framed_image.paste(output_image, (0, 0))
            else:
                framed_height_px = int(output_image.width * ratio_20_24)
                framed_image = Image.new("RGB", (output_image.width, framed_height_px), "white")
                framed_image.paste(output_image, (0, 0))
            output_image = framed_image
            format_short_name = "20x24"

        if (not two_in_one_applied) and self.border_13x10 and "10x10" in format_short_name:
            ratio_13_10 = 127 / 102
            if output_is_portrait:
                framed_height_px = int(output_image.width * ratio_13_10)
                framed_image = Image.new("RGB", (output_image.width, framed_height_px), "white")
                framed_image.paste(output_image, (0, 0))
            else:
                framed_width_px = int(output_image.height * ratio_13_10)
                framed_image = Image.new("RGB", (framed_width_px, output_image.height), "white")
                framed_image.paste(output_image, (0, 0))
            output_image = framed_image
            format_short_name = "13x10"

        if (not two_in_one_applied) and self.border_polaroid and "10x10" in format_short_name:
            POLAROID_WIDTH_PX = mm_to_pixels(127)
            POLAROID_HEIGHT_PX = mm_to_pixels(152)
            framed_image = Image.new("RGB", (POLAROID_WIDTH_PX, POLAROID_HEIGHT_PX), "white")
            paste_offset_x = (POLAROID_WIDTH_PX - output_image.width) // 2
            paste_offset_y = paste_offset_x
            framed_image.paste(output_image, (paste_offset_x, paste_offset_y))
            output_image = framed_image
            format_short_name = "Polaroid"

        if (not two_in_one_applied) and self.border_id4 and "ID" in self.current_format_label:
            SHEET_WIDTH_PX  = mm_to_pixels(127)
            SHEET_HEIGHT_PX = mm_to_pixels(102)
            SPACING_PX = mm_to_pixels(5)
            sheet_image = Image.new("RGB", (SHEET_WIDTH_PX, SHEET_HEIGHT_PX), "white")
            id_photo = output_image
            if id_photo.height > id_photo.width:
                id_photo = id_photo.rotate(90, expand=True)
            total_width  = id_photo.width  * 2 + SPACING_PX
            total_height = id_photo.height * 2 + SPACING_PX
            start_x = (SHEET_WIDTH_PX  - total_width)  // 2
            start_y = (SHEET_HEIGHT_PX - total_height) // 2
            for row in range(2):
                for col in range(2):
                    paste_x = start_x + col * (id_photo.width  + SPACING_PX)
                    paste_y = start_y + row * (id_photo.height + SPACING_PX)
                    sheet_image.paste(id_photo, (paste_x, paste_y))
            output_image = sheet_image
            format_short_name = "ID_X4"
            output_filename = f"{copies_count_prefix}ID {self.current_index + 1:02}.jpg"

        elif (not two_in_one_applied) and self.border_id2 and "ID" in self.current_format_label:
            SHEET_WIDTH_PX  = mm_to_pixels(102)
            SHEET_HEIGHT_PX = mm_to_pixels(102)
            SPACING_PX = mm_to_pixels(5)
            sheet_image = Image.new("RGB", (SHEET_WIDTH_PX, SHEET_HEIGHT_PX), "white")
            id_photo = output_image
            if id_photo.width > id_photo.height:
                id_photo = id_photo.rotate(90, expand=True)
            paste_offset_x = (SHEET_WIDTH_PX - id_photo.width) // 2
            first_paste_y  = SPACING_PX
            sheet_image.paste(id_photo, (paste_offset_x, first_paste_y))
            second_paste_y = SHEET_HEIGHT_PX - id_photo.height - SPACING_PX
            sheet_image.paste(id_photo, (paste_offset_x, second_paste_y))
            output_image = sheet_image
            format_short_name = "ID_X2"
            output_filename = f"{copies_count_prefix}ID {self.current_index + 1:02}.jpg"

        if format_short_name == "ID_X4" and self.save_to_network:
            if platform.system() == "Windows":
                output_directory = "\\\\Diskstation\\travaux en cours\\z2026"
            else:
                output_directory = "/Volumes/TRAVAUX EN COURS/Z2026"
        else:
            output_directory = os.path.join(self.source_folder, format_short_name)

        if self.is_sharpen:
            output_image = output_image.filter(ImageFilter.UnsharpMask(radius=4, percent=13, threshold=0))
            output_image = output_image.filter(ImageFilter.UnsharpMask(radius=2, percent=21, threshold=0))

        # Conversion vers sRGB (correction colorimétrique)
        output_image = convert_to_srgb(output_image, getattr(self, 'icc_profile', None))

        _exif_bytes = getattr(self, 'source_exif', None)
        jpeg_save_options = {"quality": 100, "format": "JPEG", "dpi": (DPI, DPI), "icc_profile": _SRGB_ICC}
        if _exif_bytes:
            jpeg_save_options["exif"] = _exif_bytes

        saved_file_path = None
        if not self.extra_formats:
            os.makedirs(output_directory, exist_ok=True)
            saved_file_path = unique_path(os.path.join(output_directory, output_filename))
            output_image.save(saved_file_path, **jpeg_save_options)

        # Exports formats supplémentaires (ou tous les exports si extra_formats non vide)
        for snapshot_index, snapshot in enumerate(self.extra_formats, start=1):
            snapshot_format_label = snapshot["label"]
            snapshot_format_short_name = snapshot_format_label.split()[0]
            snapshot_is_portrait = snapshot["is_portrait"]

            snapshot_format_dimensions = snapshot["dims"]
            snapshot_width_mm, snapshot_height_mm = snapshot_format_dimensions
            if snapshot_is_portrait:
                snapshot_output_width_px = mm_to_pixels(snapshot_width_mm)
                snapshot_output_height_px = mm_to_pixels(snapshot_height_mm)
            else:
                snapshot_output_width_px = mm_to_pixels(snapshot_height_mm)
                snapshot_output_height_px = mm_to_pixels(snapshot_width_mm)

            if snapshot.get("fit_in", False):
                saved_bw_for_snapshot = self.is_bw
                self.is_bw = snapshot.get("is_bw", False)
                # Si rembg n'était pas actif lors du snapshot mais l'est maintenant,
                # utiliser l'image originale pour ce format fit-in.
                saved_image_before_fit = None
                if not snapshot.get("rembg_active", False) and self.current_pil_image.mode == "RGBA" and self._rembg_original is not None:
                    saved_image_before_fit = self.current_pil_image
                    self.current_pil_image = self._rembg_original
                snapshot_output_image = self._compute_fit_in(snapshot_output_width_px, snapshot_output_height_px)
                if saved_image_before_fit is not None:
                    self.current_pil_image = saved_image_before_fit
                self.is_bw = saved_bw_for_snapshot
            else:
                snapshot_output_image = self._compute_crop_from_snapshot(snapshot)

            snapshot_two_in_one_applied = False

            # Appliquer les réglages couleur AVANT les bordures pour que les
            # zones blanches ajoutées (13x15, Polaroid…) restent blanc pur.
            original_contrast, original_saturation, original_exposure = self.contrast, self.saturation, self.exposure
            original_hue, original_white_balance = self.hue, self.white_balance
            self.contrast = snapshot.get("contrast", 0)
            self.saturation = snapshot.get("saturation", 0)
            self.exposure = snapshot.get("exposure", 0)
            self.hue = snapshot.get("hue", 0)
            self.white_balance = snapshot.get("white_balance", 0)
            snapshot_output_image = self._apply_adjustments(snapshot_output_image)
            self.contrast, self.saturation, self.exposure = original_contrast, original_saturation, original_exposure
            self.hue, self.white_balance = original_hue, original_white_balance
            if snapshot.get("shadows", 0) != 0:
                snapshot_output_image = self._apply_shadows(snapshot_output_image, snapshot["shadows"])
            if snapshot.get("highlights", 0) != 0:
                snapshot_output_image = self._apply_highlights(snapshot_output_image, snapshot["highlights"])

            if snapshot.get("two_in_one", False):
                if snapshot.get("border_13x15", False) and "10x15" in snapshot_format_short_name:
                    snapshot_output_image = self._build_two_in_one_10x15_to_13x15(snapshot_output_image)
                    snapshot_format_short_name = "13x15"
                else:
                    snapshot_output_image = self._build_two_in_one_image(snapshot_output_image, snapshot_output_width_px, snapshot_output_height_px)
                snapshot_two_in_one_applied = True

            if (not snapshot_two_in_one_applied) and snapshot.get("border_13x15", False) and "10x15" in snapshot_format_short_name:
                if snapshot_is_portrait:
                    snapshot_source_width, snapshot_source_height = mm_to_pixels(102), mm_to_pixels(152)
                    snapshot_framed_width, snapshot_framed_height = mm_to_pixels(127), mm_to_pixels(152)
                else:
                    snapshot_source_width, snapshot_source_height = mm_to_pixels(152), mm_to_pixels(102)
                    snapshot_framed_width, snapshot_framed_height = mm_to_pixels(152), mm_to_pixels(127)
                snapshot_fitted_photo = ImageOps.fit(snapshot_output_image, (snapshot_source_width, snapshot_source_height), method=Image.Resampling.LANCZOS)
                snapshot_framed_image = Image.new("RGB", (snapshot_framed_width, snapshot_framed_height), "white")
                snapshot_framed_image.paste(snapshot_fitted_photo, (0, 0))
                snapshot_output_image = snapshot_framed_image
                snapshot_format_short_name = "13x15"

            if (not snapshot_two_in_one_applied) and snapshot.get("border_10x20", False) and "10x15" in snapshot_format_short_name:
                if snapshot_is_portrait:
                    snapshot_source_width, snapshot_source_height = mm_to_pixels(102), mm_to_pixels(152)
                    snapshot_framed_width, snapshot_framed_height = mm_to_pixels(102), mm_to_pixels(203)
                else:
                    snapshot_source_width, snapshot_source_height = mm_to_pixels(152), mm_to_pixels(102)
                    snapshot_framed_width, snapshot_framed_height = mm_to_pixels(203), mm_to_pixels(102)
                snapshot_fitted_photo = ImageOps.fit(snapshot_output_image, (snapshot_source_width, snapshot_source_height), method=Image.Resampling.LANCZOS)
                snapshot_framed_image = Image.new("RGB", (snapshot_framed_width, snapshot_framed_height), "white")
                snapshot_framed_image.paste(snapshot_fitted_photo, (0, 0))
                snapshot_output_image = snapshot_framed_image
                snapshot_format_short_name = "10x20"

            if (not snapshot_two_in_one_applied) and snapshot.get("border_13x20", False) and "13x18" in snapshot_format_short_name:
                if snapshot_is_portrait:
                    snapshot_source_width, snapshot_source_height = mm_to_pixels(127), mm_to_pixels(178)
                    snapshot_framed_width, snapshot_framed_height = mm_to_pixels(127), mm_to_pixels(203)
                else:
                    snapshot_source_width, snapshot_source_height = mm_to_pixels(178), mm_to_pixels(127)
                    snapshot_framed_width, snapshot_framed_height = mm_to_pixels(203), mm_to_pixels(127)
                snapshot_fitted_photo = ImageOps.fit(snapshot_output_image, (snapshot_source_width, snapshot_source_height), method=Image.Resampling.LANCZOS)
                snapshot_framed_image = Image.new("RGB", (snapshot_framed_width, snapshot_framed_height), "white")
                snapshot_framed_image.paste(snapshot_fitted_photo, (0, 0))
                snapshot_output_image = snapshot_framed_image
                snapshot_format_short_name = "13x20"

            os.makedirs(snapshot_format_short_name, exist_ok=True)
            snapshot_copies_count = snapshot.get("copies", 1)
            snapshot_copies_prefix = f"{snapshot_copies_count}X_"
            snapshot_output_filename = snapshot_copies_prefix + base_filename + f"_{snapshot_index}.jpg"
            snapshot_output_directory = os.path.join(self.source_folder, snapshot_format_short_name)
            os.makedirs(snapshot_output_directory, exist_ok=True)
            snapshot_saved_path = unique_path(os.path.join(snapshot_output_directory, snapshot_output_filename))

            if snapshot.get("is_sharpen", self.is_sharpen):
                snapshot_output_image = snapshot_output_image.filter(ImageFilter.UnsharpMask(radius=4, percent=13, threshold=0))
                snapshot_output_image = snapshot_output_image.filter(ImageFilter.UnsharpMask(radius=2, percent=21, threshold=0))

            # Conversion vers sRGB (correction colorimétrique)
            snapshot_output_image = convert_to_srgb(snapshot_output_image, getattr(self, 'icc_profile', None))

            snapshot_output_image.save(snapshot_saved_path, **jpeg_save_options)
            saved_file_path = snapshot_saved_path

        self._snackbar(f"[OK] {os.path.basename(saved_file_path)} enregistré !")

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
                
                self._snackbar("[OK] Toutes les images sont traitées !")
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
            self._snackbar("Toutes les images ont été traitées.")
            asyncio.create_task(self.close_window())
            return

        self.current_index += 1

        if self.current_index >= len(self.image_paths):
            self._snackbar("Toutes les images ont été traitées.")
            asyncio.create_task(self.close_window())
            return

        self._snackbar("Image ignorée.")
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

        if event.key == "Tab":
            app._scroll_rotates = not app._scroll_rotates
            app._update_shift_badge()
        elif event.key == "Enter":
            app.validate_and_next(event)
        elif event.key == "Backspace":
            app.toggle_orientation(event)
        elif event.key == "Escape":
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
                app.border_switch_10x20,
                app.border_switch_13x20,
                app.border_switch_20x24,
                app.border_switch_13x10,
                app.border_switch_polaroid,
                app.border_switch_ID2,
                app.border_switch_ID4,
                app.network_switch,
            ], spacing=0),
            height=180,
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